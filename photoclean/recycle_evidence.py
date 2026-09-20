"""Manual Windows Recycle Bin move/restore evidence helper.

The helper creates only generated test files. It never restores automatically and
never permanently deletes anything. A successful run proves the move phase first;
the user must restore the generated copy from Windows Recycle Bin and run verify.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

SCHEMA_VERSION = 1
EVIDENCE_KIND = "swir_photoclean_windows_recycle_restore"


class EvidenceError(RuntimeError):
    """Raised when evidence is incomplete, malformed or fails a safety check."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def _load_evidence(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise EvidenceError(f"Cannot read evidence file: {error}") from error
    if not isinstance(payload, dict):
        raise EvidenceError("Evidence root must be a JSON object.")
    if payload.get("schema") != SCHEMA_VERSION or payload.get("kind") != EVIDENCE_KIND:
        raise EvidenceError("Unsupported Recycle Bin evidence format.")
    for key in ("original_path", "copy_path", "sha256", "phase"):
        if not isinstance(payload.get(key), str) or not payload[key]:
            raise EvidenceError(f"Evidence field {key!r} is missing or invalid.")
    if payload["original_path"] == payload["copy_path"]:
        raise EvidenceError("Evidence original/copy paths must be different.")
    digest = payload["sha256"].lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise EvidenceError("Evidence SHA-256 is invalid.")
    return payload


def default_workspace() -> Path:
    """Choose an ordinary user-owned location for the generated restore test."""
    home = Path.home()
    documents = home / "Documents"
    base = documents if documents.is_dir() else home
    return base / "SwirPhotoClean-Recycle-Restore-Test"


def prepare_restore_evidence(
    workspace: Path | str | None = None,
    *,
    recycle: Callable[[str], object] | None = None,
    now: Callable[[], str] = _utc_now,
    payload_factory: Callable[[], bytes] | None = None,
) -> Path:
    """Create an original/copy pair and move only the copy to Recycle Bin.

    An evidence JSON is written *before* the recycle request so an interrupted or
    failed move still leaves an auditable record. Success means only that the move
    phase was confirmed and the original remained intact; restore stays pending.
    """
    root = Path(workspace) if workspace is not None else default_workspace()
    root = root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    if recycle is None:
        from .recycle import recycle_file
        recycle = recycle_file

    payload_factory = payload_factory or (
        lambda: b"SWIR PhotoClean generated Recycle Bin restore evidence\n" + secrets.token_bytes(64)
    )

    for _ in range(20):
        token = secrets.token_hex(5)
        original = root / f"SwirPhotoClean-original-{token}.bin"
        copy = root / f"SwirPhotoClean-copy-{token}.bin"
        evidence = root / f"SwirPhotoClean-recycle-evidence-{token}.json"
        if not original.exists() and not copy.exists() and not evidence.exists():
            break
    else:
        raise EvidenceError("Could not allocate unique generated evidence paths.")

    data = payload_factory()
    if not isinstance(data, (bytes, bytearray, memoryview)) or len(data) == 0:
        raise EvidenceError("Generated evidence payload must contain bytes.")
    data = bytes(data)
    original.write_bytes(data)
    copy.write_bytes(data)
    expected = _sha256(original)
    if _sha256(copy) != expected:
        raise EvidenceError("Generated original/copy hashes differ before recycle.")

    record = {
        "schema": SCHEMA_VERSION,
        "kind": EVIDENCE_KIND,
        "created_utc": now(),
        "phase": "prepared",
        "workspace": str(root),
        "original_path": str(original),
        "copy_path": str(copy),
        "sha256": expected,
        "original_preserved": True,
        "recycle_move_confirmed": False,
        "restore_verified": False,
        "manual_restore_required": True,
    }
    _write_json_atomic(evidence, record)

    try:
        recycle(str(copy))
    except Exception as error:
        record.update(
            phase="recycle_failed",
            recycle_error=str(error),
            original_preserved=original.exists() and _sha256(original) == expected,
            copy_still_present=copy.exists(),
        )
        try:
            _write_json_atomic(evidence, record)
        except OSError:
            pass
        if not original.exists() or not copy.exists():
            raise EvidenceError(
                "Recycle move raised an error and the generated original/copy pair is no longer intact."
            ) from error
        raise EvidenceError(f"Recycle Bin move was not confirmed: {error}") from error

    if not original.exists() or _sha256(original) != expected:
        record.update(phase="safety_failure", original_preserved=False)
        _write_json_atomic(evidence, record)
        raise EvidenceError("Generated original changed during the Recycle Bin move test.")
    if copy.exists():
        record.update(phase="safety_failure", copy_still_present=True)
        _write_json_atomic(evidence, record)
        raise EvidenceError("Recycle operation returned success but the generated copy is still present.")

    record.update(
        phase="awaiting_restore",
        recycle_move_confirmed=True,
        moved_utc=now(),
        original_preserved=True,
        copy_still_present=False,
    )
    _write_json_atomic(evidence, record)
    return evidence


def verify_restore_evidence(
    evidence_path: Path | str,
    *,
    now: Callable[[], str] = _utc_now,
) -> dict:
    """Verify that the generated copy was manually restored and both hashes match."""
    path = Path(evidence_path).expanduser().resolve()
    record = _load_evidence(path)
    if record["phase"] not in {"awaiting_restore", "verified"}:
        raise EvidenceError(
            f"Evidence phase is {record['phase']!r}; a confirmed move awaiting restore is required."
        )
    if not record.get("recycle_move_confirmed"):
        raise EvidenceError("Evidence does not contain a confirmed Recycle Bin move.")

    original = Path(record["original_path"])
    copy = Path(record["copy_path"])
    expected = record["sha256"].lower()
    if not original.is_file():
        raise EvidenceError(f"Generated original is missing: {original}")
    if _sha256(original) != expected:
        raise EvidenceError("Generated original changed; restore evidence is invalid.")
    if not copy.is_file():
        raise EvidenceError(
            f"Restored generated copy was not found at its original path: {copy}"
        )
    if _sha256(copy) != expected:
        raise EvidenceError("Restored generated copy hash does not match the original.")

    record.update(
        phase="verified",
        verified_utc=now(),
        original_preserved=True,
        restore_verified=True,
        copy_still_present=True,
    )
    _write_json_atomic(path, record)
    return record


def cli_main(argv: tuple[str, ...] | list[str]) -> int:
    """CLI used by both source launcher and packaged EXE."""
    args = list(argv)
    if not args:
        print("Recycle restore evidence command missing.")
        return 2

    command = args.pop(0)
    try:
        if command == "--recycle-restore-prepare":
            if len(args) > 1:
                raise EvidenceError("prepare accepts at most one optional workspace path")
            evidence = prepare_restore_evidence(args[0] if args else None)
            record = _load_evidence(evidence)
            print(f"MOVE_CONFIRMED evidence={evidence}")
            print(f"ORIGINAL_PRESERVED path={record['original_path']}")
            print(f"RESTORE_REQUIRED path={record['copy_path']}")
            print(
                "Restore the generated copy from Windows Recycle Bin, then run: "
                f"SwirPhotoClean.exe --recycle-restore-verify \"{evidence}\""
            )
            return 0
        if command == "--recycle-restore-verify":
            if len(args) != 1:
                raise EvidenceError("verify requires exactly one evidence JSON path")
            record = verify_restore_evidence(args[0])
            print("RESTORE_VERIFIED")
            print(f"ORIGINAL_PRESERVED path={record['original_path']}")
            print(f"RESTORED_COPY path={record['copy_path']}")
            print(f"SHA256={record['sha256']}")
            return 0
        raise EvidenceError(f"unknown evidence command: {command}")
    except EvidenceError as error:
        print(f"EVIDENCE_FAILED: {error}")
        return 2
