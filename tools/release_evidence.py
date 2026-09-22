from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from photoclean.safety_contract import (  # noqa: E402
    SafetyContractError,
    source_safety_contract_sha256,
)

RELEASE_EVIDENCE_PATH = ROOT / "RELEASE_EVIDENCE.json"
SCHEMA_VERSION = 3
EVIDENCE_KIND = "windows-recycle-restore"
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


class ReleaseEvidenceError(ValueError):
    """Runtime evidence is missing, ambiguous or unsafe for a qualified release."""


def _parse_utc(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise ReleaseEvidenceError(f"{label} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ReleaseEvidenceError(f"{label} is not a valid ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise ReleaseEvidenceError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _current_safety_contract() -> str:
    try:
        return source_safety_contract_sha256(ROOT)
    except SafetyContractError as error:
        raise ReleaseEvidenceError(f"cannot evaluate current release safety contract: {error}") from error


def _require_windows_packaged_runtime(manifest: dict) -> None:
    """Require physical acceptance evidence to originate from the frozen Windows app."""
    environment = manifest.get("environment")
    if not isinstance(environment, dict):
        raise ReleaseEvidenceError(
            "validated report is missing the runtime environment identity"
        )

    if environment.get("frozen") is not True:
        raise ReleaseEvidenceError(
            "qualified release evidence must be produced by packaged SwirPhotoClean.exe, "
            "not a source/interpreter run"
        )

    platform_text = environment.get("platform")
    if (
        not isinstance(platform_text, str)
        or not platform_text.strip()
        or not platform_text.strip().lower().startswith("windows")
    ):
        raise ReleaseEvidenceError(
            "qualified release evidence must be produced on a real Windows runtime"
        )


def validate_release_evidence(payload: object) -> dict:
    """Validate sanitized evidence and bind it to the current safety-critical source."""
    if not isinstance(payload, dict):
        raise ReleaseEvidenceError("RELEASE_EVIDENCE.json must contain a JSON object")

    keys = set(payload)
    missing = sorted(_REQUIRED_KEYS - keys)
    unknown = sorted(keys - _REQUIRED_KEYS)
    if missing:
        raise ReleaseEvidenceError(
            "RELEASE_EVIDENCE.json is missing fields: " + ", ".join(missing)
        )
    if unknown:
        raise ReleaseEvidenceError(
            "RELEASE_EVIDENCE.json contains unsupported fields: " + ", ".join(unknown)
        )

    if payload["schema_version"] != SCHEMA_VERSION:
        raise ReleaseEvidenceError("unsupported RELEASE_EVIDENCE.json schema version")
    if payload["kind"] != EVIDENCE_KIND:
        raise ReleaseEvidenceError(
            f"release evidence kind must be {EVIDENCE_KIND!r}"
        )

    session_id = payload["session_id"]
    if not isinstance(session_id, str) or not _HEX32.fullmatch(session_id):
        raise ReleaseEvidenceError("session_id must be 32 lowercase hexadecimal characters")

    for field in (
        "fixture_sha256",
        "manifest_fingerprint",
        "evidence_report_sha256",
        "safety_contract_sha256",
    ):
        value = payload[field]
        if not isinstance(value, str) or not _HEX64.fullmatch(value):
            raise ReleaseEvidenceError(
                f"{field} must be 64 lowercase hexadecimal characters"
            )

    current_contract = _current_safety_contract()
    if payload["safety_contract_sha256"] != current_contract:
        raise ReleaseEvidenceError(
            "runtime evidence belongs to a different release safety contract; "
            "repeat the physical Windows Recycle Bin move/Restore verification "
            "after safety-critical changes"
        )

    verified_at = _parse_utc(payload["verified_at_utc"], "verified_at_utc")
    reviewed_at = _parse_utc(payload["reviewed_at_utc"], "reviewed_at_utc")
    if reviewed_at < verified_at:
        raise ReleaseEvidenceError(
            "reviewed_at_utc cannot be earlier than verified_at_utc"
        )

    for field in _REQUIRED_TRUE_FLAGS:
        if payload[field] is not True:
            raise ReleaseEvidenceError(f"{field} must be true for a qualified release")
    if payload["acceptance_gate_closed"] is not False:
        raise ReleaseEvidenceError(
            "release evidence must not claim that it closes the repository acceptance gate"
        )

    return dict(payload)


def _event_for(manifest: dict, stage: str) -> dict:
    events = manifest.get("events")
    if not isinstance(events, list):
        raise ReleaseEvidenceError("evidence manifest is missing its ordered event log")
    matches = [
        event
        for event in events
        if isinstance(event, dict) and event.get("stage") == stage
    ]
    if len(matches) != 1:
        raise ReleaseEvidenceError(
            f"evidence manifest must contain exactly one {stage!r} event"
        )
    return matches[0]


def build_release_evidence(
    report_path: str | Path,
    *,
    confirm_manual_restore: bool,
    reviewed_at: datetime | None = None,
) -> dict:
    """Create a sanitized release attestation from a freshly validated local report.

    ``confirm_manual_restore`` is intentionally explicit: the code can validate that
    the generated file disappeared and later returned with the expected SHA-256,
    but only the human performing the Windows test can attest that Restore was
    actually chosen in Windows Recycle Bin.
    """
    if not confirm_manual_restore:
        raise ReleaseEvidenceError(
            "manual Windows Restore must be explicitly confirmed before release evidence is written"
        )

    try:
        from photoclean.diagnostics import RecycleVerificationError
        from photoclean.evidence_snapshot import load_validated_restore_evidence_snapshot

        check, report, raw, source = load_validated_restore_evidence_snapshot(report_path)
    except RecycleVerificationError as error:
        raise ReleaseEvidenceError(f"Recycle evidence report is not release-ready: {error}") from error

    manifest = source.get("manifest")
    inspection = source.get("inspection")
    if not isinstance(manifest, dict) or not isinstance(inspection, dict):
        raise ReleaseEvidenceError("validated report is missing manifest or inspection data")

    _require_windows_packaged_runtime(manifest)

    safety_contract = manifest.get("safety_contract_sha256")
    if not isinstance(safety_contract, str) or not _HEX64.fullmatch(safety_contract):
        raise ReleaseEvidenceError(
            "validated report is not bound to a qualified release safety contract"
        )
    current_contract = _current_safety_contract()
    if safety_contract != current_contract:
        raise ReleaseEvidenceError(
            "validated report was produced by a different release safety contract"
        )

    recycled = _event_for(manifest, "recycled")
    restored = _event_for(manifest, "restored-verified")
    if recycled.get("source_absent_after_recycle") is not True:
        raise ReleaseEvidenceError("recycle event does not prove source absence after the move")
    if recycled.get("original_preserved") is not True:
        raise ReleaseEvidenceError("recycle event does not prove the generated original was preserved")
    if restored.get("original_preserved") is not True:
        raise ReleaseEvidenceError("restore event does not preserve the generated original")
    if restored.get("restored_copy_matches_sha256") is not True:
        raise ReleaseEvidenceError("restore event does not verify the restored copy SHA-256")
    if restored.get("restored_copy_distinct") is not True:
        raise ReleaseEvidenceError("restore event does not prove the restored copy is physically distinct")
    if inspection.get("valid") is not True:
        raise ReleaseEvidenceError("fresh report inspection is not valid")
    if inspection.get("original_matches") is not True or inspection.get("copy_matches") is not True:
        raise ReleaseEvidenceError("fresh report inspection does not match both generated files")

    verified_at = manifest.get("verified_at_utc")
    _parse_utc(verified_at, "verified_at_utc")
    review_time = reviewed_at or datetime.now(timezone.utc)
    if review_time.tzinfo is None:
        raise ReleaseEvidenceError("reviewed_at must include a timezone")
    reviewed_text = review_time.astimezone(timezone.utc).replace(microsecond=0).isoformat()

    payload = {
        "schema_version": SCHEMA_VERSION,
        "kind": EVIDENCE_KIND,
        "session_id": check.session_id,
        "fixture_sha256": check.digest,
        "manifest_fingerprint": check.manifest_fingerprint,
        "evidence_report_sha256": hashlib.sha256(raw).hexdigest(),
        "safety_contract_sha256": safety_contract,
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
    return validate_release_evidence(payload)


def write_release_evidence(
    report_path: str | Path,
    output_path: str | Path = RELEASE_EVIDENCE_PATH,
    *,
    confirm_manual_restore: bool,
) -> Path:
    payload = build_release_evidence(
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
    return output


def read_release_evidence(path: str | Path = RELEASE_EVIDENCE_PATH) -> dict:
    evidence = Path(path)
    try:
        payload = json.loads(evidence.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseEvidenceError(f"cannot read release evidence: {error}") from error
    return validate_release_evidence(payload)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create or validate sanitized Windows runtime evidence for a qualified release."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    writer = subparsers.add_parser(
        "write",
        help="validate a local Recycle restore report and write RELEASE_EVIDENCE.json",
    )
    writer.add_argument("--report", required=True, help="path to recycle-evidence-report.json")
    writer.add_argument(
        "--output",
        default=str(RELEASE_EVIDENCE_PATH),
        help="output path (default: repository RELEASE_EVIDENCE.json)",
    )
    writer.add_argument(
        "--confirm-manual-restore",
        action="store_true",
        help="attest that Windows Recycle Bin Restore was actually performed manually",
    )

    verifier = subparsers.add_parser(
        "verify",
        help="validate an existing sanitized release evidence file against current safety code",
    )
    verifier.add_argument(
        "--file",
        default=str(RELEASE_EVIDENCE_PATH),
        help="evidence file to validate",
    )

    args = parser.parse_args()
    try:
        if args.command == "write":
            output = write_release_evidence(
                args.report,
                args.output,
                confirm_manual_restore=args.confirm_manual_restore,
            )
            print(f"RELEASE_EVIDENCE_WRITTEN path={output}")
            print("ACCEPTANCE_GATE_CLOSED=no")
            return 0

        payload = read_release_evidence(args.file)
        print(
            "RELEASE_EVIDENCE_VALID "
            f"session={payload['session_id']} sha256={payload['fixture_sha256']} "
            f"safety_contract={payload['safety_contract_sha256']}"
        )
        return 0
    except (OSError, ReleaseEvidenceError) as error:
        raise SystemExit(f"release evidence failed: {error}") from error


if __name__ == "__main__":
    raise SystemExit(main())
