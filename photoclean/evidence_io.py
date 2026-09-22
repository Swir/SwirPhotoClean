"""Fail-closed JSON persistence for Recycle Bin release evidence.

The physical Recycle Bin / Restore workflow is release-critical.  Its local
manifest and exported report must therefore avoid following attacker-controlled
links, mutating hardlinked files, predictable staging names, and silent target
replacement while validated bytes are being staged.

This module is installed by :mod:`run` before the GUI or evidence CLI is loaded.
It preserves the existing evidence data model while replacing only the JSON
writer/export boundary with a durable, fail-closed implementation.
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


OutputIdentity = tuple[int, int, int, int, int, int]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _absolute_without_resolving(path: str | os.PathLike) -> Path:
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


def _safe_output_identity(path: Path) -> OutputIdentity | None:
    """Snapshot an existing output entry or reject unsafe filesystem objects.

    Existing hardlinked outputs are rejected even when they do not currently
    alias a generated fixture.  Opening such a path for replacement is
    needlessly ambiguous for release evidence and could otherwise mutate an
    unrelated file if a future writer regressed to in-place writes.
    """
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

    return (
        int(info.st_dev),
        int(info.st_ino),
        int(getattr(info, "st_nlink", 1)),
        int(info.st_size),
        int(getattr(info, "st_mtime_ns", int(info.st_mtime * 1_000_000_000))),
        int(getattr(info, "st_ctime_ns", int(info.st_ctime * 1_000_000_000))),
    )


def hardened_atomic_write_json(path: Path, payload: dict) -> None:
    """Durably stage validated JSON beside ``path`` and atomically replace it.

    The function mirrors the historical diagnostics writer contract, including
    automatic manifest fingerprinting, but never opens the destination for
    in-place writes.  The destination identity is checked before staging and
    immediately before replacement so an intervening path swap fails closed.
    """
    target = _absolute_without_resolving(path)
    normalized = dict(payload)
    if normalized.get("version") == diagnostics.MANIFEST_VERSION:
        normalized["manifest_fingerprint"] = diagnostics._payload_fingerprint(normalized)

    expected_identity = _safe_output_identity(target)
    raw = json.dumps(normalized, ensure_ascii=False, indent=2).encode("utf-8")

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
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())

        try:
            staged_raw = temporary.read_bytes()
        except OSError as error:
            raise diagnostics.RecycleVerificationError(
                f"Cannot re-read staged evidence JSON: {error}"
            ) from error
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
        if staged_payload != normalized:
            raise diagnostics.RecycleVerificationError(
                "Staged evidence JSON does not match the validated payload"
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
    """Export a fresh evidence report without following unsafe output aliases."""
    manifest = (
        check_or_manifest.manifest
        if isinstance(check_or_manifest, diagnostics.RecycleVerification)
        else Path(check_or_manifest)
    )
    check = diagnostics.load_recycle_verification(manifest)
    inspection = diagnostics.inspect_recycle_evidence(check)
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

    try:
        manifest_payload = json.loads(check.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise diagnostics.RecycleVerificationError(
            f"Cannot read recycle verification manifest for evidence export: {error}"
        ) from error

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


def install_hardened_evidence_io() -> None:
    """Install hardened persistence before GUI/CLI modules bind diagnostics helpers."""
    diagnostics._atomic_write_json = hardened_atomic_write_json
    diagnostics.export_recycle_evidence = hardened_export_recycle_evidence

    # Keep an already-imported CLI coherent as well.  Normal application startup
    # installs before recycle_evidence is imported, but this makes repeated/test
    # installation deterministic and safe.
    recycle_module = sys.modules.get("photoclean.recycle_evidence")
    if recycle_module is not None:
        setattr(recycle_module, "_atomic_write_json", hardened_atomic_write_json)
        setattr(recycle_module, "export_recycle_evidence", hardened_export_recycle_evidence)
