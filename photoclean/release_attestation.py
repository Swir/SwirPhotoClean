"""Packaged Windows handoff for qualified release evidence.

This module intentionally lives inside ``photoclean`` so PyInstaller includes the
attestation path used by the same EXE that performed the physical Recycle Bin
verification. It does not close STATUS.md or replace manual review.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .diagnostics import (
    COPY_NAME,
    MANIFEST_NAME,
    ORIGINAL_NAME,
    RecycleVerificationError,
)
from .evidence_snapshot import load_validated_restore_evidence_snapshot
from .safety_contract import SafetyContractError, runtime_safety_contract_sha256

SCHEMA_VERSION = 3
EVIDENCE_KIND = "windows-recycle-restore"
ATTESTATION_NAME = "RELEASE_EVIDENCE.json"
_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPARSE_POINT_ATTRIBUTE = 0x400
_MAX_ATTESTATION_BYTES = 256 * 1024
_READ_CHUNK_BYTES = 64 * 1024
_REQUIRED_TRUE_FLAGS = (
    "physical_recycle_move_confirmed",
    "manual_restore_performed",
    "original_preserved",
    "restored_copy_sha256_verified",
    "report_review_valid",
    "windows_packaged_runtime_confirmed",
)
_REQUIRED_KEYS = {
    "schema_version",
    "kind",
    "session_id",
    "fixture_sha256",
    "manifest_fingerprint",
    "evidence_report_sha256",
    "safety_contract_sha256",
    "verified_at_utc",
    "reviewed_at_utc",
    *_REQUIRED_TRUE_FLAGS,
    "acceptance_gate_closed",
}


class PackagedAttestationError(ValueError):
    """The packaged evidence handoff is incomplete, stale or unsafe."""


def _parse_utc(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise PackagedAttestationError(f"{label} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise PackagedAttestationError(f"{label} is not a valid ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise PackagedAttestationError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _current_contract() -> str:
    try:
        return runtime_safety_contract_sha256()
    except SafetyContractError as error:
        raise PackagedAttestationError(f"release safety contract unavailable: {error}") from error


def _require_packaged_windows(manifest: dict) -> None:
    environment = manifest.get("environment")
    if not isinstance(environment, dict):
        raise PackagedAttestationError("validated report is missing runtime environment identity")
    if environment.get("frozen") is not True:
        raise PackagedAttestationError(
            "qualified release evidence must come from packaged SwirPhotoClean.exe"
        )
    platform_text = environment.get("platform")
    if (
        not isinstance(platform_text, str)
        or not platform_text.strip().lower().startswith("windows")
    ):
        raise PackagedAttestationError(
            "qualified release evidence must come from a real Windows runtime"
        )


def _event_for(manifest: dict, stage: str) -> dict:
    events = manifest.get("events")
    if not isinstance(events, list):
        raise PackagedAttestationError("evidence manifest is missing its ordered event log")
    matches = [
        event
        for event in events
        if isinstance(event, dict) and event.get("stage") == stage
    ]
    if len(matches) != 1:
        raise PackagedAttestationError(
            f"evidence manifest must contain exactly one {stage!r} event"
        )
    return matches[0]


def validate_packaged_attestation(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise PackagedAttestationError("RELEASE_EVIDENCE.json must contain a JSON object")
    keys = set(payload)
    missing = sorted(_REQUIRED_KEYS - keys)
    unknown = sorted(keys - _REQUIRED_KEYS)
    if missing:
        raise PackagedAttestationError(
            "RELEASE_EVIDENCE.json is missing fields: " + ", ".join(missing)
        )
    if unknown:
        raise PackagedAttestationError(
            "RELEASE_EVIDENCE.json contains unsupported fields: " + ", ".join(unknown)
        )
    if payload["schema_version"] != SCHEMA_VERSION:
        raise PackagedAttestationError("unsupported RELEASE_EVIDENCE.json schema version")
    if payload["kind"] != EVIDENCE_KIND:
        raise PackagedAttestationError(f"release evidence kind must be {EVIDENCE_KIND!r}")

    session_id = payload["session_id"]
    if not isinstance(session_id, str) or not _HEX32.fullmatch(session_id):
        raise PackagedAttestationError(
            "session_id must be 32 lowercase hexadecimal characters"
        )
    for field in (
        "fixture_sha256",
        "manifest_fingerprint",
        "evidence_report_sha256",
        "safety_contract_sha256",
    ):
        value = payload[field]
        if not isinstance(value, str) or not _HEX64.fullmatch(value):
            raise PackagedAttestationError(
                f"{field} must be 64 lowercase hexadecimal characters"
            )

    if payload["safety_contract_sha256"] != _current_contract():
        raise PackagedAttestationError(
            "runtime evidence belongs to a different release safety contract"
        )

    verified_at = _parse_utc(payload["verified_at_utc"], "verified_at_utc")
    reviewed_at = _parse_utc(payload["reviewed_at_utc"], "reviewed_at_utc")
    if reviewed_at < verified_at:
        raise PackagedAttestationError(
            "reviewed_at_utc cannot be earlier than verified_at_utc"
        )
    for field in _REQUIRED_TRUE_FLAGS:
        if payload[field] is not True:
            raise PackagedAttestationError(
                f"{field} must be true for a qualified release"
            )
    if payload["acceptance_gate_closed"] is not False:
        raise PackagedAttestationError(
            "packaged attestation must not claim that STATUS.md is closed"
        )
    return dict(payload)


def build_packaged_attestation(
    report_path: str | Path,
    *,
    confirm_manual_restore: bool,
    reviewed_at: datetime | None = None,
) -> dict:
    if not confirm_manual_restore:
        raise PackagedAttestationError(
            "manual Windows Restore must be explicitly confirmed"
        )

    try:
        check, report, raw, source = load_validated_restore_evidence_snapshot(report_path)
    except RecycleVerificationError as error:
        raise PackagedAttestationError(
            f"Recycle evidence report is not release-ready: {error}"
        ) from error

    manifest = source.get("manifest")
    inspection = source.get("inspection")
    if not isinstance(manifest, dict) or not isinstance(inspection, dict):
        raise PackagedAttestationError(
            "validated report is missing manifest or inspection data"
        )
    _require_packaged_windows(manifest)

    contract = manifest.get("safety_contract_sha256")
    if not isinstance(contract, str) or not _HEX64.fullmatch(contract):
        raise PackagedAttestationError(
            "validated report is not bound to a qualified release safety contract"
        )
    if contract != _current_contract():
        raise PackagedAttestationError(
            "validated report was produced by a different release safety contract"
        )

    recycled = _event_for(manifest, "recycled")
    restored = _event_for(manifest, "restored-verified")
    if recycled.get("source_absent_after_recycle") is not True:
        raise PackagedAttestationError(
            "recycle event does not prove source absence after the move"
        )
    if recycled.get("original_preserved") is not True:
        raise PackagedAttestationError(
            "recycle event does not prove the original was preserved"
        )
    if restored.get("original_preserved") is not True:
        raise PackagedAttestationError("restore event does not preserve the original")
    if restored.get("restored_copy_matches_sha256") is not True:
        raise PackagedAttestationError(
            "restore event does not verify restored copy SHA-256"
        )
    if restored.get("restored_copy_distinct") is not True:
        raise PackagedAttestationError(
            "restore event does not prove the restored copy is physically distinct"
        )
    if inspection.get("valid") is not True:
        raise PackagedAttestationError("fresh report inspection is not valid")
    if (
        inspection.get("original_matches") is not True
        or inspection.get("copy_matches") is not True
    ):
        raise PackagedAttestationError(
            "fresh report inspection does not match both generated files"
        )

    verified_at = manifest.get("verified_at_utc")
    _parse_utc(verified_at, "verified_at_utc")
    review_time = reviewed_at or datetime.now(timezone.utc)
    if review_time.tzinfo is None:
        raise PackagedAttestationError("reviewed_at must include a timezone")
    reviewed_text = review_time.astimezone(timezone.utc).replace(microsecond=0).isoformat()

    payload = {
        "schema_version": SCHEMA_VERSION,
        "kind": EVIDENCE_KIND,
        "session_id": check.session_id,
        "fixture_sha256": check.digest,
        "manifest_fingerprint": check.manifest_fingerprint,
        "evidence_report_sha256": hashlib.sha256(raw).hexdigest(),
        "safety_contract_sha256": contract,
        "verified_at_utc": verified_at,
        "reviewed_at_utc": reviewed_text,
        "physical_recycle_move_confirmed": True,
        "manual_restore_performed": True,
        "original_preserved": True,
        "restored_copy_sha256_verified": True,
        "report_review_valid": True,
        "windows_packaged_runtime_confirmed": True,
        "acceptance_gate_closed": False,
    }
    return validate_packaged_attestation(payload)


def _absolute_without_resolving(path: str | Path) -> Path:
    """Return an absolute path while preserving the final filesystem entry."""
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


def _require_safe_attestation_directory_ancestry(
    directory: Path,
    *,
    allow_missing: bool = False,
) -> None:
    """Reject redirected output ancestry before the packaged evidence writer runs."""
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
        except FileNotFoundError:
            if allow_missing:
                continue
            raise PackagedAttestationError(
                f"RELEASE_EVIDENCE.json output directory does not exist: {entry}"
            )
        except OSError as error:
            raise PackagedAttestationError(
                f"cannot safely inspect RELEASE_EVIDENCE.json output directory {entry}: {error}"
            ) from error

        if stat.S_ISLNK(info.st_mode) or bool(
            getattr(info, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE
        ):
            raise PackagedAttestationError(
                "RELEASE_EVIDENCE.json output directory ancestry must not contain "
                f"symlinks, junctions or reparse points: {entry}"
            )
        if not stat.S_ISDIR(info.st_mode):
            raise PackagedAttestationError(
                "RELEASE_EVIDENCE.json output directory ancestry contains a "
                f"non-directory entry: {entry}"
            )


def _file_identity(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    """Return metadata that must stay stable for one attestation-file read."""
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(getattr(info, "st_nlink", 1)),
        int(info.st_size),
        int(getattr(info, "st_mtime_ns", int(info.st_mtime * 1_000_000_000))),
        int(getattr(info, "st_ctime_ns", int(info.st_ctime * 1_000_000_000))),
    )


def _path_and_handle_identity_match(
    path_identity: tuple[int, int, int, int, int, int],
    handle_identity: tuple[int, int, int, int, int, int],
) -> bool:
    """Compare path/handle identity while tolerating Windows stat representation noise."""
    if os.name != "nt":
        return path_identity == handle_identity
    path_inode = path_identity[1]
    handle_inode = handle_identity[1]
    if path_inode <= 0 or handle_inode <= 0 or path_inode != handle_inode:
        return False
    return path_identity[2:5] == handle_identity[2:5]


def _attestation_output_identity(path: Path) -> tuple[int, int, int, int, int, int] | None:
    """Return output identity or fail closed for unsafe existing output entries."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise PackagedAttestationError(
            f"cannot safely inspect RELEASE_EVIDENCE.json output path {path}: {error}"
        ) from error

    if stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE
    ):
        raise PackagedAttestationError(
            "RELEASE_EVIDENCE.json output must not be a symlink, junction or reparse point"
        )
    if not stat.S_ISREG(info.st_mode):
        raise PackagedAttestationError(
            "RELEASE_EVIDENCE.json output must be a regular file"
        )
    if int(getattr(info, "st_nlink", 1)) != 1:
        raise PackagedAttestationError(
            "RELEASE_EVIDENCE.json output must not be hardlinked"
        )
    if int(info.st_size) > _MAX_ATTESTATION_BYTES:
        raise PackagedAttestationError(
            "RELEASE_EVIDENCE.json is too large to validate safely"
        )
    return _file_identity(info)


def _read_bounded_handle(
    descriptor: int,
    *,
    opened_identity: tuple[int, int, int, int, int, int],
) -> bytes:
    """Read bounded bytes from one already-open attestation handle."""
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
    except OSError as error:
        raise PackagedAttestationError(
            f"cannot seek RELEASE_EVIDENCE.json handle safely: {error}"
        ) from error

    chunks: list[bytes] = []
    total = 0
    while True:
        remaining = _MAX_ATTESTATION_BYTES + 1 - total
        if remaining <= 0:
            raise PackagedAttestationError(
                "RELEASE_EVIDENCE.json is too large to validate safely"
            )
        try:
            chunk = os.read(descriptor, min(_READ_CHUNK_BYTES, remaining))
        except OSError as error:
            raise PackagedAttestationError(
                f"cannot read RELEASE_EVIDENCE.json handle safely: {error}"
            ) from error
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > _MAX_ATTESTATION_BYTES:
            raise PackagedAttestationError(
                "RELEASE_EVIDENCE.json is too large to validate safely"
            )

    after = os.fstat(descriptor)
    if _file_identity(after) != opened_identity:
        raise PackagedAttestationError(
            "RELEASE_EVIDENCE.json changed while its open handle was being read"
        )
    raw = b"".join(chunks)
    if len(raw) != opened_identity[3]:
        raise PackagedAttestationError(
            "RELEASE_EVIDENCE.json size changed while its open handle was being read"
        )
    return raw


def _validate_opened_attestation_handle(
    descriptor: int,
    *,
    expected_path_identity: tuple[int, int, int, int, int, int] | None = None,
) -> tuple[dict, tuple[int, int, int, int, int, int]]:
    """Validate one open regular single-link attestation handle and return its payload."""
    try:
        opened = os.fstat(descriptor)
    except OSError as error:
        raise PackagedAttestationError(
            f"cannot inspect RELEASE_EVIDENCE.json open handle: {error}"
        ) from error
    if not stat.S_ISREG(opened.st_mode):
        raise PackagedAttestationError(
            "RELEASE_EVIDENCE.json changed to a non-regular file while opening"
        )
    if bool(getattr(opened, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE):
        raise PackagedAttestationError(
            "RELEASE_EVIDENCE.json changed to a reparse point while opening"
        )
    if int(getattr(opened, "st_nlink", 1)) != 1:
        raise PackagedAttestationError(
            "RELEASE_EVIDENCE.json became hardlinked while opening"
        )
    if int(opened.st_size) > _MAX_ATTESTATION_BYTES:
        raise PackagedAttestationError(
            "RELEASE_EVIDENCE.json is too large to validate safely"
        )
    opened_identity = _file_identity(opened)
    if (
        expected_path_identity is not None
        and not _path_and_handle_identity_match(expected_path_identity, opened_identity)
    ):
        raise PackagedAttestationError(
            "RELEASE_EVIDENCE.json changed while it was being opened"
        )

    raw = _read_bounded_handle(descriptor, opened_identity=opened_identity)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PackagedAttestationError(
            f"cannot decode RELEASE_EVIDENCE.json safely: {error}"
        ) from error
    return validate_packaged_attestation(payload), opened_identity


def _read_stable_attestation(path: Path) -> dict:
    """Read final release evidence through one identity-bound, bounded file handle."""
    _require_safe_attestation_directory_ancestry(path.parent)
    before_identity = _attestation_output_identity(path)
    if before_identity is None:
        raise PackagedAttestationError("RELEASE_EVIDENCE.json output disappeared before verification")

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise PackagedAttestationError(
            f"cannot open RELEASE_EVIDENCE.json safely: {error}"
        ) from error
    try:
        payload, opened_identity = _validate_opened_attestation_handle(
            descriptor,
            expected_path_identity=before_identity,
        )
    finally:
        os.close(descriptor)

    _require_safe_attestation_directory_ancestry(path.parent)
    final_identity = _attestation_output_identity(path)
    if final_identity != before_identity:
        raise PackagedAttestationError(
            "RELEASE_EVIDENCE.json path changed while final bytes were being verified"
        )
    if not _path_and_handle_identity_match(final_identity, opened_identity):
        raise PackagedAttestationError(
            "RELEASE_EVIDENCE.json path no longer refers to the verified file handle"
        )
    return payload


def _validated_output_path(report_path: str | Path, output_path: str | Path) -> Path:
    """Return a safe attestation destination without aliasing source evidence files."""
    report = Path(report_path).expanduser().resolve()
    output = _absolute_without_resolving(output_path)
    protected = (
        report,
        report.parent / MANIFEST_NAME,
        report.parent / ORIGINAL_NAME,
        report.parent / COPY_NAME,
    )
    if any(_paths_alias(output, source) for source in protected):
        raise PackagedAttestationError(
            "RELEASE_EVIDENCE.json output cannot overwrite or alias the evidence report, "
            "manifest, or generated verification files"
        )
    return output


def _write_validated_json_atomically(
    output: Path,
    payload: dict,
    expected_output_identity: tuple[int, int, int, int, int, int] | None,
) -> None:
    """Validate staged bytes on one handle and guard the path before atomic replace."""
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(encoded) > _MAX_ATTESTATION_BYTES:
        raise PackagedAttestationError(
            "staged RELEASE_EVIDENCE.json is too large to validate safely"
        )

    _require_safe_attestation_directory_ancestry(output.parent)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.",
        suffix=".tmp",
        dir=output.parent,
    )
    temporary = Path(temporary_name)
    staged_identity: tuple[int, int, int, int, int, int] | None = None
    try:
        try:
            offset = 0
            while offset < len(encoded):
                written = os.write(descriptor, encoded[offset:])
                if written <= 0:
                    raise PackagedAttestationError(
                        "cannot write complete staged RELEASE_EVIDENCE.json"
                    )
                offset += written
            os.fsync(descriptor)

            staged, staged_identity = _validate_opened_attestation_handle(descriptor)
            if staged != payload:
                raise PackagedAttestationError(
                    "staged release evidence differs from validated attestation"
                )
        finally:
            os.close(descriptor)

        _require_safe_attestation_directory_ancestry(output.parent)
        temporary_identity = _attestation_output_identity(temporary)
        if (
            staged_identity is None
            or temporary_identity is None
            or not _path_and_handle_identity_match(temporary_identity, staged_identity)
        ):
            raise PackagedAttestationError(
                "staged RELEASE_EVIDENCE.json path changed after same-handle validation"
            )
        if _attestation_output_identity(output) != expected_output_identity:
            raise PackagedAttestationError(
                "RELEASE_EVIDENCE.json output changed while validated bytes were staged"
            )
        try:
            os.replace(temporary, output)
        except OSError as error:
            raise PackagedAttestationError(
                f"cannot atomically replace RELEASE_EVIDENCE.json output: {error}"
            ) from error
        _require_safe_attestation_directory_ancestry(output.parent)
        _attestation_output_identity(output)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def write_packaged_attestation(
    report_path: str | Path,
    output_path: str | Path,
    *,
    confirm_manual_restore: bool,
) -> Path:
    payload = build_packaged_attestation(
        report_path,
        confirm_manual_restore=confirm_manual_restore,
    )
    output = _validated_output_path(report_path, output_path)
    _require_safe_attestation_directory_ancestry(output.parent, allow_missing=True)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise PackagedAttestationError(
            f"cannot create RELEASE_EVIDENCE.json output directory: {error}"
        ) from error
    _require_safe_attestation_directory_ancestry(output.parent)
    expected_output_identity = _attestation_output_identity(output)
    _write_validated_json_atomically(output, payload, expected_output_identity)

    written = _read_stable_attestation(output)
    if written != payload:
        raise PackagedAttestationError(
            "written release evidence differs from validated attestation"
        )
    return output.resolve()
