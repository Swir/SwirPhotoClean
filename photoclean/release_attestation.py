"""Packaged Windows handoff for qualified release evidence.

This module intentionally lives inside ``photoclean`` so PyInstaller includes the
attestation path used by the same EXE that performed the physical Recycle Bin
verification. It does not close STATUS.md or replace manual review.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .diagnostics import RecycleVerificationError
from .recycle_evidence import validate_restore_evidence_report
from .safety_contract import SafetyContractError, runtime_safety_contract_sha256

SCHEMA_VERSION = 3
EVIDENCE_KIND = "windows-recycle-restore"
ATTESTATION_NAME = "RELEASE_EVIDENCE.json"
_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
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
        check, report = validate_restore_evidence_report(report_path)
    except RecycleVerificationError as error:
        raise PackagedAttestationError(
            f"Recycle evidence report is not release-ready: {error}"
        ) from error

    try:
        raw = report.read_bytes()
        source = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PackagedAttestationError(
            f"cannot read validated recycle evidence report: {error}"
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
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)

    try:
        written = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PackagedAttestationError(
            f"cannot re-read written release evidence: {error}"
        ) from error
    if validate_packaged_attestation(written) != payload:
        raise PackagedAttestationError(
            "written release evidence differs from validated attestation"
        )
    return output
