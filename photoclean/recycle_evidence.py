"""Packaged/source CLI adapter for the generated Recycle Bin restore workflow.

The authoritative verification model lives in :mod:`photoclean.diagnostics`. This
module only makes that existing tamper-evident workflow easy to execute from a
release-candidate EXE. It never closes the repository acceptance gate itself.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from .diagnostics import (
    RecycleVerification,
    RecycleVerificationError,
    _atomic_write_json,
    create_recycle_verification,
    export_recycle_evidence,
    inspect_recycle_evidence,
    load_recycle_verification,
    move_generated_copy_to_recycle,
    verify_restored_copy,
)
from .safety_contract import SafetyContractError, runtime_safety_contract_sha256

REPORT_NAME = "recycle-evidence-report.json"
WORKSPACE_NAME = "SwirPhotoClean-Recycle-Restore-Test"
SAFETY_CONTRACT_FIELD = "safety_contract_sha256"


def default_workspace() -> Path:
    home = Path.home()
    documents = home / "Documents"
    base = documents if documents.is_dir() else home
    return base / WORKSPACE_NAME


def _read_manifest_payload(check: RecycleVerification) -> dict:
    try:
        payload = json.loads(check.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RecycleVerificationError(
            f"Cannot read recycle verification manifest: {error}"
        ) from error
    if not isinstance(payload, dict):
        raise RecycleVerificationError("Recycle verification manifest must contain an object")
    return payload


def _runtime_contract_digest() -> str:
    try:
        return runtime_safety_contract_sha256()
    except SafetyContractError as error:
        raise RecycleVerificationError(f"Release safety contract unavailable: {error}") from error


def _bind_runtime_safety_contract(check: RecycleVerification) -> RecycleVerification:
    """Bind a freshly prepared fixture to the exact runtime/build safety contract."""
    payload = _read_manifest_payload(check)
    digest = _runtime_contract_digest()
    existing = payload.get(SAFETY_CONTRACT_FIELD)
    if existing is not None and existing != digest:
        raise RecycleVerificationError(
            "Recycle verification is already bound to a different release safety contract"
        )
    payload[SAFETY_CONTRACT_FIELD] = digest
    _atomic_write_json(check.manifest, payload)
    return load_recycle_verification(check.manifest)


def _require_runtime_safety_contract(check: RecycleVerification) -> str:
    """Reject legacy/stale evidence when the running safety-critical code differs."""
    payload = _read_manifest_payload(check)
    recorded = payload.get(SAFETY_CONTRACT_FIELD)
    if (
        not isinstance(recorded, str)
        or len(recorded) != 64
        or recorded != recorded.lower()
    ):
        raise RecycleVerificationError(
            "Recycle verification is not bound to a qualified release safety contract; "
            "prepare a fresh evidence session with the current build"
        )
    try:
        int(recorded, 16)
    except ValueError as error:
        raise RecycleVerificationError(
            "Recycle verification contains an invalid release safety-contract digest"
        ) from error
    current = _runtime_contract_digest()
    if recorded != current:
        raise RecycleVerificationError(
            "Recycle verification belongs to a different release safety contract; "
            "prepare and physically test a fresh session after safety-critical changes"
        )
    return recorded


def create_restore_evidence(
    workspace: str | Path | None = None,
) -> RecycleVerification:
    """Create a fresh generated fixture bound to the current release safety contract."""
    base = Path(workspace).expanduser().resolve() if workspace is not None else default_workspace()
    base.mkdir(parents=True, exist_ok=True)
    check = create_recycle_verification(base)
    return _bind_runtime_safety_contract(check)


def move_restore_evidence(
    manifest: str | Path,
    *,
    recycler: Callable[[str], object] | None = None,
) -> RecycleVerification:
    """Retry or perform the guarded Recycle Bin move for an existing prepared fixture."""
    check = load_recycle_verification(Path(manifest).expanduser().resolve())
    _require_runtime_safety_contract(check)
    return move_generated_copy_to_recycle(check, recycler=recycler)


def prepare_restore_evidence(
    workspace: str | Path | None = None,
    *,
    recycler: Callable[[str], object] | None = None,
) -> RecycleVerification:
    """Create generated fixtures and move only RECYCLE-ME.png to Recycle Bin."""
    check = create_restore_evidence(workspace)
    return move_generated_copy_to_recycle(check, recycler=recycler)


def verify_restore_evidence(
    manifest: str | Path,
    *,
    report_path: str | Path | None = None,
) -> tuple[RecycleVerification, Path]:
    """Verify a manual Windows restore and export the existing evidence report.

    Export is intentionally resumable. The manifest transition to
    ``restored-verified`` is durable and can happen before report creation. If a
    disk/permission interruption prevents the report from being written, running
    the verify command again revalidates the already-verified fixture and exports
    the report without adding another stage event.
    """
    check = load_recycle_verification(Path(manifest).expanduser().resolve())
    _require_runtime_safety_contract(check)
    if check.stage == "recycled":
        verified = verify_restored_copy(check)
    elif check.stage == "restored-verified":
        # A previous verification may have completed the tamper-evident state
        # transition but failed while writing the convenience report. Exporting
        # again is safe because export_recycle_evidence performs a fresh,
        # read-only inspection of both generated files and the manifest.
        verified = check
    else:
        raise RecycleVerificationError(
            "Recycle restore evidence must be in recycled or restored-verified stage"
        )

    destination = (
        Path(report_path).expanduser().resolve()
        if report_path is not None
        else verified.folder / REPORT_NAME
    )
    report = export_recycle_evidence(verified, destination)
    return verified, report


def validate_restore_evidence_report(
    report_path: str | Path,
    *,
    manifest: str | Path | None = None,
) -> tuple[RecycleVerification, Path]:
    """Validate an exported report against the live manifest and generated files.

    This is deliberately read-only. A report is reviewable only if its embedded
    manifest and inspection are byte-for-byte equivalent at the JSON data-model
    level to a fresh validation of the current fixture. The helper never flips
    the repository acceptance gate.
    """
    report = Path(report_path).expanduser().resolve()
    try:
        payload = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RecycleVerificationError(f"Cannot read recycle evidence report: {error}") from error
    if not isinstance(payload, dict):
        raise RecycleVerificationError("Recycle evidence report must contain an object")
    if payload.get("report_version") != 1:
        raise RecycleVerificationError("Unsupported recycle evidence report version")
    if payload.get("acceptance_gate_closed") is not False:
        raise RecycleVerificationError(
            "Recycle evidence report must not claim that the repository acceptance gate is closed"
        )
    embedded_manifest = payload.get("manifest")
    embedded_inspection = payload.get("inspection")
    if not isinstance(embedded_manifest, dict) or not isinstance(embedded_inspection, dict):
        raise RecycleVerificationError("Recycle evidence report is missing manifest or inspection data")

    manifest_path = (
        Path(manifest).expanduser().resolve()
        if manifest is not None
        else report.parent / "recycle-verification.json"
    )
    check = load_recycle_verification(manifest_path)
    _require_runtime_safety_contract(check)
    if check.stage != "restored-verified":
        raise RecycleVerificationError(
            "Recycle evidence report is reviewable only after restored-verified stage"
        )

    inspection = inspect_recycle_evidence(check)
    if not inspection.valid:
        raise RecycleVerificationError(
            "Recycle verification evidence is inconsistent: "
            + "; ".join(inspection.problems)
        )

    try:
        current_manifest = json.loads(check.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RecycleVerificationError(
            f"Cannot re-read recycle verification manifest: {error}"
        ) from error

    if embedded_manifest != current_manifest:
        raise RecycleVerificationError(
            "Recycle evidence report manifest does not match the current verification manifest"
        )

    # JSON converts tuples (for example ``problems``) to lists. Normalizing via a
    # JSON round-trip lets us compare the exported shape exactly without mutating
    # either source structure.
    current_inspection = json.loads(
        json.dumps(asdict(inspection), ensure_ascii=False, sort_keys=True)
    )
    if embedded_inspection != current_inspection:
        raise RecycleVerificationError(
            "Recycle evidence report inspection does not match a fresh fixture inspection"
        )

    return check, report


def _print_move_success(check: RecycleVerification) -> None:
    print(f"MOVE_CONFIRMED manifest={check.manifest}")
    print(f"ORIGINAL_PRESERVED path={check.original}")
    print(f"RESTORE_REQUIRED path={check.copy}")
    print(
        "Restore RECYCLE-ME.png from Windows Recycle Bin, then run: "
        f"SwirPhotoClean.exe --recycle-restore-verify \"{check.manifest}\""
    )


def _print_status(manifest: str | Path) -> int:
    manifest_path = Path(manifest).expanduser().resolve()
    check = load_recycle_verification(manifest_path)
    _require_runtime_safety_contract(check)
    inspection = inspect_recycle_evidence(check)
    if not inspection.valid:
        raise RecycleVerificationError(
            "Recycle verification evidence is inconsistent: "
            + "; ".join(inspection.problems)
        )

    print(
        f"EVIDENCE_VALID stage={inspection.stage} "
        f"session={inspection.session_id or 'legacy'}"
    )
    print(f"ORIGINAL_PRESENT={'yes' if inspection.original_present else 'no'}")
    print(f"COPY_PRESENT={'yes' if inspection.copy_present else 'no'}")
    print(f"SAFETY_CONTRACT_SHA256={_runtime_contract_digest()}")

    if inspection.stage == "prepared":
        print(
            "NEXT=Run the guarded move without recreating the fixture: "
            f"SwirPhotoClean.exe --recycle-restore-move \"{manifest_path}\""
        )
    elif inspection.stage == "recycled":
        print(
            "NEXT=Restore RECYCLE-ME.png from Windows Recycle Bin, then run: "
            f"SwirPhotoClean.exe --recycle-restore-verify \"{manifest_path}\""
        )
    else:
        report = manifest_path.parent / REPORT_NAME
        print(f"REPORT_PRESENT={'yes' if report.is_file() else 'no'} path={report}")
        if report.is_file():
            validate_restore_evidence_report(report, manifest=manifest_path)
            print("REPORT_VALID=yes")
            print(
                "NEXT=Run the read-only report review before changing STATUS.md: "
                f"SwirPhotoClean.exe --recycle-restore-review \"{report}\""
            )
            print("READY_FOR_REVIEW")
        else:
            print(
                "NEXT=Re-run --recycle-restore-verify to recreate the evidence report; "
                "the physical restore does not need to be repeated."
            )
    return 0


def _print_report_review(report: str | Path) -> int:
    check, report_path = validate_restore_evidence_report(report)
    print("REPORT_VALID")
    print(f"EVIDENCE_STAGE={check.stage}")
    print(f"SESSION={check.session_id or 'legacy'}")
    print(f"SHA256={check.digest}")
    print(f"SAFETY_CONTRACT_SHA256={_runtime_contract_digest()}")
    print(f"MANIFEST={check.manifest}")
    print(f"EVIDENCE_REPORT={report_path}")
    print("READY_FOR_MANUAL_ACCEPTANCE_REVIEW")
    return 0


def cli_main(argv: tuple[str, ...] | list[str]) -> int:
    args = list(argv)
    if not args:
        print("Recycle restore evidence command missing.")
        return 2

    command = args.pop(0)
    try:
        if command == "--recycle-restore-prepare":
            if len(args) > 1:
                raise RecycleVerificationError(
                    "prepare accepts at most one optional workspace path"
                )
            prepared = create_restore_evidence(args[0] if args else None)
            try:
                moved = move_restore_evidence(prepared.manifest)
            except (RecycleVerificationError, OSError):
                print("MOVE_NOT_CONFIRMED")
                print(f"PREPARED_MANIFEST path={prepared.manifest}")
                print(
                    "RETRY_COMMAND=SwirPhotoClean.exe --recycle-restore-move "
                    f"\"{prepared.manifest}\""
                )
                raise
            _print_move_success(moved)
            return 0

        if command == "--recycle-restore-move":
            if len(args) != 1:
                raise RecycleVerificationError(
                    "move requires exactly one prepared recycle-verification.json path"
                )
            moved = move_restore_evidence(args[0])
            _print_move_success(moved)
            return 0

        if command == "--recycle-restore-status":
            if len(args) != 1:
                raise RecycleVerificationError(
                    "status requires exactly one recycle-verification.json path"
                )
            return _print_status(args[0])

        if command == "--recycle-restore-review":
            if len(args) != 1:
                raise RecycleVerificationError(
                    "review requires exactly one recycle-evidence-report.json path"
                )
            return _print_report_review(args[0])

        if command == "--recycle-restore-verify":
            if len(args) != 1:
                raise RecycleVerificationError(
                    "verify requires exactly one recycle-verification.json path"
                )
            verified, report = verify_restore_evidence(args[0])
            print("RESTORE_VERIFIED")
            print(f"ORIGINAL_PRESERVED path={verified.original}")
            print(f"RESTORED_COPY path={verified.copy}")
            print(f"SHA256={verified.digest}")
            print(f"SAFETY_CONTRACT_SHA256={_runtime_contract_digest()}")
            print(f"EVIDENCE_REPORT path={report}")
            print(
                "REVIEW_COMMAND=SwirPhotoClean.exe --recycle-restore-review "
                f"\"{report}\""
            )
            return 0

        raise RecycleVerificationError(f"unknown evidence command: {command}")
    except (RecycleVerificationError, OSError) as error:
        print(f"EVIDENCE_FAILED: {error}")
        return 2
