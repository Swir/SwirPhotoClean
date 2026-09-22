"""Immutable snapshot validation for Recycle Bin release evidence.

Release attestation must be derived from the exact report bytes that were
validated.  Reading a report once for validation and again for attestation leaves
a time-of-check/time-of-use gap where the file can change between those steps.
This helper snapshots the report bytes first, validates that immutable snapshot
against the live manifest and generated fixture, and returns those same bytes to
the attestation layer for hashing and sanitization.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from .diagnostics import RecycleVerificationError
from .recycle_evidence import validate_restore_evidence_report


def load_validated_restore_evidence_snapshot(
    report_path: str | Path,
    *,
    manifest: str | Path | None = None,
) -> tuple[object, Path, bytes, dict]:
    """Return one validated report snapshot and the exact bytes that were checked.

    The original report is read exactly once.  A temporary copy containing those
    exact bytes is then passed to the authoritative report validator while the
    live manifest/fixture remains authoritative.  Downstream attestation code must
    hash and sanitize ``raw``/``payload`` returned here rather than re-reading the
    mutable source path.
    """
    report = Path(report_path).expanduser().resolve()
    manifest_path = (
        Path(manifest).expanduser().resolve()
        if manifest is not None
        else report.parent / "recycle-verification.json"
    )

    try:
        raw = report.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RecycleVerificationError(
            f"Cannot snapshot recycle evidence report: {error}"
        ) from error
    if not isinstance(payload, dict):
        raise RecycleVerificationError("Recycle evidence report must contain an object")

    try:
        with tempfile.TemporaryDirectory(prefix="swirphotoclean-evidence-") as folder:
            snapshot = Path(folder) / "recycle-evidence-report.json"
            snapshot.write_bytes(raw)
            check, _validated_snapshot = validate_restore_evidence_report(
                snapshot,
                manifest=manifest_path,
            )
    except OSError as error:
        raise RecycleVerificationError(
            f"Cannot validate immutable recycle evidence snapshot: {error}"
        ) from error

    return check, report, raw, payload
