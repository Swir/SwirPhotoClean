"""Fail-closed JSON persistence and intake for Recycle Bin release evidence.

The physical Recycle Bin / Restore workflow is release-critical. Its local
manifest and exported report must therefore avoid following attacker-controlled
links, mutating hardlinked files, predictable staging names, silent target
replacement, and mutable-path reads that can change between validation steps.

This module is installed by :mod:`run` before the GUI or evidence CLI is loaded.
It preserves the existing evidence data model while replacing the JSON
read/write/export boundary with durable, fail-closed implementations.
"""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from . import diagnostics

_REPARSE_POINT_ATTRIBUTE = 0x400
_MAX_MANIFEST_BYTES = 256 * 1024
_MAX_EVIDENCE_REPORT_BYTES = 2 * 1024 * 1024
_READ_CHUNK_BYTES = 64 * 1024

OutputIdentity = tuple[int, int, int, int, int, int]
InputIdentity = tuple[int, int, int, int, int, int]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _absolute_without_resolving(path: str | os.PathLike) -> Path:
    """Return an absolute path while preserving every lexical filesystem entry."""
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def _paths_alias(first: Path, second: Path) -> bool:
    """Detect lexical aliases and existing hardlink/symlink aliases."""
    first_text = os.path.normcase(os.path.abspath(os.fspath(first)))
    second_text = os.path.normcase(os.path.abspath(os.fspath(second)))
    if first_text == second_text:
        return True
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False


def _require_safe_directory_ancestry(directory: Path) -> None:
    """Require every lexical directory ancestor to be a real directory."""
    current = _absolute_without_resolving(directory)
    chain: list[Path] = []
    while True:
        chain.append(current)
        parent = current.parent
        if parent == current:
            break
        current = parent

    for entry in reversed(chain):
        try:
            info = entry.lstat()
        except OSError as error:
            raise diagnostics.RecycleVerificationError(
                f"Cannot safely inspect evidence directory {entry}: {error}"
            ) from error

        if stat.S_ISLNK(info.st_mode) or bool(
            getattr(info, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE
        ):
            raise diagnostics.RecycleVerificationError(
                "Evidence directory ancestry must not contain symlinks, "
                f"junctions or reparse points: {entry}"
            )
        if not stat.S_ISDIR(info.st_mode):
            raise diagnostics.RecycleVerificationError(
                f"Evidence directory ancestry contains a non-directory entry: {entry}"
            )


def _file_identity(info: os.stat_result) -> InputIdentity:
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(getattr(info, "st_nlink", 1)),
        int(info.st_size),
        int(getattr(info, "st_mtime_ns", int(info.st_mtime * 1_000_000_000))),
        int(getattr(info, "st_ctime_ns", int(info.st_ctime * 1_000_000_000))),
    )


def _path_and_handle_identity_match(
    path_identity: InputIdentity,
    handle_identity: InputIdentity,
) -> bool:
    """Compare path/handle identity without known Windows CRT metadata noise."""
    if os.name != "nt":
        return path_identity == handle_identity

    path_inode = path_identity[1]
    handle_inode = handle_identity[1]
    if path_inode <= 0 or handle_inode <= 0 or path_inode != handle_inode:
        return False
    return path_identity[2:5] == handle_identity[2:5]


def _safe_input_info(path: Path, *, max_bytes: int, label: str) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as error:
        raise diagnostics.RecycleVerificationError(
            f"Cannot safely inspect {label}: {error}"
        ) from error

    if stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE
    ):
        raise diagnostics.RecycleVerificationError(
            f"{label} must not be a symlink, junction or reparse point"
        )
    if not stat.S_ISREG(info.st_mode):
        raise diagnostics.RecycleVerificationError(f"{label} must be a regular file")
    if int(getattr(info, "st_nlink", 1)) != 1:
        raise diagnostics.RecycleVerificationError(f"{label} must not be hardlinked")
    if int(info.st_size) > max_bytes:
        raise diagnostics.RecycleVerificationError(
            f"{label} is too large to validate safely"
        )
    return info


def hardened_read_json_object(
    path: str | os.PathLike,
    *,
    max_bytes: int = _MAX_MANIFEST_BYTES,
    label: str = "Recycle verification manifest",
) -> dict:
    """Read one bounded JSON object from one verified filesystem handle.

    The lexical parent chain and final entry are checked before open. The opened
    handle must match the inspected path, its metadata must remain stable while
    bytes are read, and the path/ancestry are revalidated afterwards. This
    rejects hardlinks, redirected ancestry and path-swap/TOCTOU ambiguity.
    """
    source = _absolute_without_resolving(path)
    _require_safe_directory_ancestry(source.parent)
    before = _safe_input_info(source, max_bytes=max_bytes, label=label)
    before_identity = _file_identity(before)

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(source, flags)
    except OSError as error:
        raise diagnostics.RecycleVerificationError(
            f"Cannot open {label} safely: {error}"
        ) from error

    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise diagnostics.RecycleVerificationError(
                f"{label} changed to a non-regular file while opening"
            )
        if bool(getattr(opened, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE):
            raise diagnostics.RecycleVerificationError(
                f"{label} changed to a reparse point while opening"
            )
        if int(getattr(opened, "st_nlink", 1)) != 1:
            raise diagnostics.RecycleVerificationError(
                f"{label} became hardlinked while opening"
            )
        opened_identity = _file_identity(opened)
        if not _path_and_handle_identity_match(before_identity, opened_identity):
            raise diagnostics.RecycleVerificationError(
                f"{label} changed while it was being opened"
            )

        chunks: list[bytes] = []
        total = 0
        while True:
            remaining = max_bytes + 1 - total
            if remaining <= 0:
                raise diagnostics.RecycleVerificationError(
                    f"{label} is too large to validate safely"
                )
            try:
                chunk = os.read(descriptor, min(_READ_CHUNK_BYTES, remaining))
            except OSError as error:
                raise diagnostics.RecycleVerificationError(
                    f"Cannot read {label} safely: {error}"
                ) from error
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                raise diagnostics.RecycleVerificationError(
                    f"{label} is too large to validate safely"
                )

        after = os.fstat(descriptor)
        if _file_identity(after) != opened_identity:
            raise diagnostics.RecycleVerificationError(
                f"{label} changed while it was being read"
            )
    finally:
        os.close(descriptor)

    _require_safe_directory_ancestry(source.parent)
    final = _safe_input_info(source, max_bytes=max_bytes, label=label)
    if _file_identity(final) != before_identity:
        raise diagnostics.RecycleVerificationError(
            f"{label} path changed while it was being read"
        )

    raw = b"".join(chunks)
    if len(raw) != int(before.st_size):
        raise diagnostics.RecycleVerificationError(
            f"{label} size changed while it was being read"
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise diagnostics.RecycleVerificationError(
            f"{label} is not valid UTF-8 JSON: {error}"
        ) from error
    if not isinstance(payload, dict):
        raise diagnostics.RecycleVerificationError(f"{label} must contain an object")
    return payload


def _load_manifest_snapshot(
    manifest: str | os.PathLike,
) -> tuple[diagnostics.RecycleVerification, dict]:
    manifest_path = _absolute_without_resolving(manifest)
    payload = hardened_read_json_object(manifest_path)

    version, stage, digest = diagnostics._validate_common_payload(payload)
    session_id = ""
    file_size = 0
    fingerprint = ""
    if version == diagnostics.MANIFEST_VERSION:
        session_id, file_size, fingerprint = diagnostics._validate_v2_payload(
            payload, stage
        )

    folder = manifest_path.parent
    check = diagnostics.RecycleVerification(
        folder=folder,
        original=folder / diagnostics.ORIGINAL_NAME,
        copy=folder / diagnostics.COPY_NAME,
        manifest=manifest_path,
        digest=digest,
        stage=stage,
        session_id=session_id,
        manifest_version=version,
        file_size=file_size,
        manifest_fingerprint=fingerprint,
    )
    return check, payload


def hardened_load_recycle_verification(
    manifest: str | os.PathLike,
) -> diagnostics.RecycleVerification:
    check, _payload = _load_manifest_snapshot(manifest)
    return check


def hardened_read_manifest_payload(check: diagnostics.RecycleVerification) -> dict:
    loaded, payload = _load_manifest_snapshot(check.manifest)
    if loaded.session_id != check.session_id or loaded.digest != check.digest:
        raise diagnostics.RecycleVerificationError(
            "Recycle verification manifest identity changed before use"
        )
    return payload


def hardened_read_payload_for_transition(
    check: diagnostics.RecycleVerification,
) -> dict:
    loaded, payload = _load_manifest_snapshot(check.manifest)
    if loaded.manifest_version == 1:
        payload = diagnostics._legacy_to_v2_payload(payload, loaded)
    return payload


def _inspect_recycle_snapshot(
    check: diagnostics.RecycleVerification,
    payload: dict,
) -> diagnostics.RecycleEvidenceInspection:
    events = payload.get("events") if isinstance(payload.get("events"), list) else []

    original_matches, original_problem = diagnostics._matches_expected_file(
        check.original, check.digest, check.file_size
    )
    copy_matches = None
    copy_problem = None
    if check.copy.exists():
        copy_matches, copy_problem = diagnostics._matches_expected_file(
            check.copy, check.digest, check.file_size
        )

    problems = []
    if not original_matches:
        problems.append(f"original: {original_problem or 'invalid'}")

    if check.stage == "prepared":
        if copy_matches is not True:
            problems.append(f"copy: {copy_problem or 'missing'}")
    elif check.stage == "recycled":
        if check.copy.exists():
            problems.append("copy: expected to be absent after recycle stage")
    elif check.stage == "restored-verified":
        if copy_matches is not True:
            problems.append(f"restored copy: {copy_problem or 'missing'}")

    if check.copy.exists() and check.original.exists():
        try:
            if os.path.samefile(check.original, check.copy):
                problems.append("original and copy refer to the same physical file")
        except OSError as error:
            problems.append(f"same-file check failed: {error}")

    return diagnostics.RecycleEvidenceInspection(
        manifest_version=check.manifest_version,
        session_id=check.session_id,
        stage=check.stage,
        manifest_fingerprint=check.manifest_fingerprint,
        event_count=len(events),
        original_present=check.original.exists(),
        copy_present=check.copy.exists(),
        original_matches=original_matches,
        copy_matches=copy_matches,
        valid=not problems,
        problems=tuple(problems),
    )


def hardened_inspect_recycle_evidence(
    check_or_manifest: diagnostics.RecycleVerification | str | os.PathLike,
) -> diagnostics.RecycleEvidenceInspection:
    manifest = (
        check_or_manifest.manifest
        if isinstance(check_or_manifest, diagnostics.RecycleVerification)
        else Path(check_or_manifest)
    )
    check, payload = _load_manifest_snapshot(manifest)
    return _inspect_recycle_snapshot(check, payload)


def _safe_output_identity(path: Path) -> OutputIdentity | None:
    """Snapshot an existing output entry or reject unsafe filesystem objects."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise diagnostics.RecycleVerificationError(
            f"Cannot safely inspect evidence output path {path}: {error}"
        ) from error

    if stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE
    ):
        raise diagnostics.RecycleVerificationError(
            "Evidence output must not be a symlink, junction or reparse point"
        )
    if not stat.S_ISREG(info.st_mode):
        raise diagnostics.RecycleVerificationError(
            "Evidence output must be a regular file"
        )
    if int(getattr(info, "st_nlink", 1)) != 1:
        raise diagnostics.RecycleVerificationError(
            "Evidence output must not be hardlinked"
        )

    return _file_identity(info)


def _write_descriptor_all(descriptor: int, raw: bytes) -> None:
    """Write every staged byte without converting the descriptor back to a path."""
    offset = 0
    while offset < len(raw):
        try:
            written = os.write(descriptor, raw[offset:])
        except OSError as error:
            raise diagnostics.RecycleVerificationError(
                f"Cannot write staged evidence JSON safely: {error}"
            ) from error
        if written <= 0:
            raise diagnostics.RecycleVerificationError(
                "Staged evidence JSON write made no forward progress"
            )
        offset += written


def _read_descriptor_exact(descriptor: int, *, max_bytes: int) -> bytes:
    """Re-read staged bytes through the same verified handle with a hard bound."""
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
    except OSError as error:
        raise diagnostics.RecycleVerificationError(
            f"Cannot seek staged evidence JSON safely: {error}"
        ) from error

    chunks: list[bytes] = []
    total = 0
    while True:
        remaining = max_bytes + 1 - total
        if remaining <= 0:
            raise diagnostics.RecycleVerificationError(
                "Staged evidence JSON is too large to validate safely"
            )
        try:
            chunk = os.read(descriptor, min(_READ_CHUNK_BYTES, remaining))
        except OSError as error:
            raise diagnostics.RecycleVerificationError(
                f"Cannot re-read staged evidence JSON safely: {error}"
            ) from error
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > max_bytes:
            raise diagnostics.RecycleVerificationError(
                "Staged evidence JSON is too large to validate safely"
            )
    return b"".join(chunks)


def hardened_atomic_write_json(path: Path, payload: dict) -> None:
    """Durably verify staged JSON on one handle, then atomically replace ``path``."""
    target = _absolute_without_resolving(path)
    normalized = dict(payload)
    is_manifest = normalized.get("version") == diagnostics.MANIFEST_VERSION
    if is_manifest:
        normalized["manifest_fingerprint"] = diagnostics._payload_fingerprint(normalized)

    _require_safe_directory_ancestry(target.parent)
    expected_identity = _safe_output_identity(target)
    raw = json.dumps(normalized, ensure_ascii=False, indent=2).encode("utf-8")
    output_limit = _MAX_MANIFEST_BYTES if is_manifest else _MAX_EVIDENCE_REPORT_BYTES
    if len(raw) > output_limit:
        raise diagnostics.RecycleVerificationError(
            "Evidence JSON is too large to stage safely"
        )
    expected_payload = json.loads(raw.decode("utf-8"))

    _require_safe_directory_ancestry(target.parent)
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
        )
    except OSError as error:
        raise diagnostics.RecycleVerificationError(
            f"Cannot create exclusive evidence staging file: {error}"
        ) from error

    temporary = Path(temporary_name)
    staged_identity: InputIdentity | None = None
    try:
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise diagnostics.RecycleVerificationError(
                    "Evidence staging handle is not a regular file"
                )
            if bool(getattr(opened, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE):
                raise diagnostics.RecycleVerificationError(
                    "Evidence staging handle unexpectedly became a reparse point"
                )
            if int(getattr(opened, "st_nlink", 1)) != 1:
                raise diagnostics.RecycleVerificationError(
                    "Evidence staging handle must not be hardlinked"
                )

            _write_descriptor_all(descriptor, raw)
            try:
                os.fsync(descriptor)
            except OSError as error:
                raise diagnostics.RecycleVerificationError(
                    f"Cannot flush staged evidence JSON safely: {error}"
                ) from error

            written = os.fstat(descriptor)
            if not stat.S_ISREG(written.st_mode):
                raise diagnostics.RecycleVerificationError(
                    "Evidence staging handle changed to a non-regular file"
                )
            if bool(getattr(written, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE):
                raise diagnostics.RecycleVerificationError(
                    "Evidence staging handle changed to a reparse point"
                )
            if int(getattr(written, "st_nlink", 1)) != 1:
                raise diagnostics.RecycleVerificationError(
                    "Evidence staging handle became hardlinked before verification"
                )
            staged_identity = _file_identity(written)
            if int(written.st_size) != len(raw):
                raise diagnostics.RecycleVerificationError(
                    "Staged evidence JSON size does not match validated bytes"
                )

            staged_raw = _read_descriptor_exact(descriptor, max_bytes=output_limit)
            after_read = os.fstat(descriptor)
            if _file_identity(after_read) != staged_identity:
                raise diagnostics.RecycleVerificationError(
                    "Evidence staging handle changed while bytes were verified"
                )
        finally:
            try:
                os.close(descriptor)
            except OSError:
                pass

        if staged_raw != raw:
            raise diagnostics.RecycleVerificationError(
                "Staged evidence JSON bytes changed before commit"
            )
        try:
            staged_payload = json.loads(staged_raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise diagnostics.RecycleVerificationError(
                "Staged evidence JSON is not valid UTF-8 JSON"
            ) from error
        if staged_payload != expected_payload:
            raise diagnostics.RecycleVerificationError(
                "Staged evidence JSON does not match the validated payload"
            )

        _require_safe_directory_ancestry(target.parent)
        staged_path_info = _safe_input_info(
            temporary,
            max_bytes=output_limit,
            label="Evidence staging file",
        )
        if staged_identity is None or not _path_and_handle_identity_match(
            _file_identity(staged_path_info), staged_identity
        ):
            raise diagnostics.RecycleVerificationError(
                "Evidence staging file path changed before commit"
            )
        if _safe_output_identity(target) != expected_identity:
            raise diagnostics.RecycleVerificationError(
                "Evidence output changed while validated bytes were staged"
            )

        try:
            os.replace(temporary, target)
        except OSError as error:
            raise diagnostics.RecycleVerificationError(
                f"Cannot atomically replace evidence output: {error}"
            ) from error
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def hardened_export_recycle_evidence(
    check_or_manifest: diagnostics.RecycleVerification | str | os.PathLike,
    destination: str | os.PathLike,
) -> Path:
    """Export a fresh report from one stable manifest snapshot."""
    manifest = (
        check_or_manifest.manifest
        if isinstance(check_or_manifest, diagnostics.RecycleVerification)
        else Path(check_or_manifest)
    )
    check, manifest_payload = _load_manifest_snapshot(manifest)
    inspection = _inspect_recycle_snapshot(check, manifest_payload)
    if not inspection.valid:
        raise diagnostics.RecycleVerificationError(
            "Recycle verification evidence is inconsistent: "
            + "; ".join(inspection.problems)
        )

    target = _absolute_without_resolving(destination)
    protected = (check.original, check.copy, check.manifest)
    for protected_path in protected:
        if _paths_alias(target, protected_path):
            raise diagnostics.RecycleVerificationError(
                "Evidence report cannot overwrite or alias verification fixture files"
            )

    report = {
        "report_version": diagnostics.EVIDENCE_REPORT_VERSION,
        "exported_at_utc": _utc_now(),
        "acceptance_gate_closed": False,
        "note": (
            "Local evidence only. Review the generated files and manifest before "
            "changing the SWIR PhotoClean 1.0 acceptance checklist."
        ),
        "inspection": asdict(inspection),
        "manifest": manifest_payload,
    }
    hardened_atomic_write_json(target, report)
    return target


def _require_runtime_contract_snapshot(workflow, manifest_payload: dict) -> str:
    recorded = manifest_payload.get(workflow.SAFETY_CONTRACT_FIELD)
    if (
        not isinstance(recorded, str)
        or len(recorded) != 64
        or recorded != recorded.lower()
    ):
        raise diagnostics.RecycleVerificationError(
            "Recycle verification is not bound to a qualified release safety contract; "
            "prepare a fresh evidence session with the current build"
        )
    try:
        int(recorded, 16)
    except ValueError as error:
        raise diagnostics.RecycleVerificationError(
            "Recycle verification contains an invalid release safety-contract digest"
        ) from error
    current = workflow._runtime_contract_digest()
    if recorded != current:
        raise diagnostics.RecycleVerificationError(
            "Recycle verification belongs to a different release safety contract; "
            "prepare and physically test a fresh session after safety-critical changes"
        )
    return recorded


def _require_restored_receipt_identity_snapshot(
    workflow,
    check: diagnostics.RecycleVerification,
    manifest_payload: dict,
) -> bool:
    receipt = workflow._validated_receipt(manifest_payload)
    if receipt is None or receipt["source_inode"] <= 0:
        return False
    try:
        info = check.copy.stat()
    except OSError as error:
        raise diagnostics.RecycleVerificationError(
            f"Restored verification copy is unavailable for identity continuity: {error}"
        ) from error
    restored_identity = (int(info.st_dev), int(info.st_ino))
    expected_identity = (receipt["source_device"], receipt["source_inode"])
    if restored_identity != expected_identity:
        raise diagnostics.RecycleVerificationError(
            "Restored verification copy is byte-compatible but is not the same "
            "filesystem object that Windows moved to the Recycle Bin"
        )
    return True


def hardened_validate_restore_evidence_report(
    report_path: str | Path,
    *,
    manifest: str | Path | None = None,
) -> tuple[diagnostics.RecycleVerification, Path]:
    """Validate report + live manifest from bounded immutable snapshots."""
    from . import recycle_evidence as workflow

    report = _absolute_without_resolving(report_path)
    payload = hardened_read_json_object(
        report,
        max_bytes=_MAX_EVIDENCE_REPORT_BYTES,
        label="Recycle evidence report",
    )
    if payload.get("report_version") != diagnostics.EVIDENCE_REPORT_VERSION:
        raise diagnostics.RecycleVerificationError(
            "Unsupported recycle evidence report version"
        )
    if payload.get("acceptance_gate_closed") is not False:
        raise diagnostics.RecycleVerificationError(
            "Recycle evidence report must not claim that the repository acceptance gate is closed"
        )
    embedded_manifest = payload.get("manifest")
    embedded_inspection = payload.get("inspection")
    if not isinstance(embedded_manifest, dict) or not isinstance(
        embedded_inspection, dict
    ):
        raise diagnostics.RecycleVerificationError(
            "Recycle evidence report is missing manifest or inspection data"
        )

    manifest_path = (
        _absolute_without_resolving(manifest)
        if manifest is not None
        else report.parent / diagnostics.MANIFEST_NAME
    )
    check, current_manifest = _load_manifest_snapshot(manifest_path)
    _require_runtime_contract_snapshot(workflow, current_manifest)
    if check.stage != "restored-verified":
        raise diagnostics.RecycleVerificationError(
            "Recycle evidence report is reviewable only after restored-verified stage"
        )
    _require_restored_receipt_identity_snapshot(workflow, check, current_manifest)

    inspection = _inspect_recycle_snapshot(check, current_manifest)
    if not inspection.valid:
        raise diagnostics.RecycleVerificationError(
            "Recycle verification evidence is inconsistent: "
            + "; ".join(inspection.problems)
        )

    if embedded_manifest != current_manifest:
        raise diagnostics.RecycleVerificationError(
            "Recycle evidence report manifest does not match the current verification manifest"
        )

    current_inspection = json.loads(
        json.dumps(asdict(inspection), ensure_ascii=False, sort_keys=True)
    )
    if embedded_inspection != current_inspection:
        raise diagnostics.RecycleVerificationError(
            "Recycle evidence report inspection does not match a fresh fixture inspection"
        )

    return check, report


def install_hardened_evidence_io() -> None:
    """Install hardened persistence/intake before GUI/CLI modules bind helpers."""
    diagnostics._atomic_write_json = hardened_atomic_write_json
    diagnostics.load_recycle_verification = hardened_load_recycle_verification
    diagnostics._read_payload_for_transition = hardened_read_payload_for_transition
    diagnostics.inspect_recycle_evidence = hardened_inspect_recycle_evidence
    diagnostics.export_recycle_evidence = hardened_export_recycle_evidence

    # Import only after diagnostics has been rebound so ``from diagnostics import``
    # references inside the workflow capture the hardened implementations.
    from . import recycle_evidence as recycle_module

    recycle_module.load_recycle_verification = hardened_load_recycle_verification
    recycle_module._atomic_write_json = hardened_atomic_write_json
    recycle_module._read_manifest_payload = hardened_read_manifest_payload
    recycle_module.inspect_recycle_evidence = hardened_inspect_recycle_evidence
    recycle_module.export_recycle_evidence = hardened_export_recycle_evidence
    recycle_module.validate_restore_evidence_report = (
        hardened_validate_restore_evidence_report
    )

    # Tests or embedders may have imported the immutable report adapter before
    # installation. Rebind its local validator reference if so.
    snapshot_module = sys.modules.get("photoclean.evidence_snapshot")
    if snapshot_module is not None:
        setattr(
            snapshot_module,
            "validate_restore_evidence_report",
            hardened_validate_restore_evidence_report,
        )
