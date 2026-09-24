"""Hardened public CLI handoff for Recycle Bin evidence review.

The physical move/restore state machine remains owned by :mod:`recycle_evidence`.
This adapter makes the user-facing ``status`` and ``review`` commands consume an
immutable, bounded snapshot of ``recycle-evidence-report.json`` before they print
release-readiness guidance. It never closes the 1.0 acceptance gate.
"""
from __future__ import annotations

from pathlib import Path

from . import recycle_evidence as workflow
from .diagnostics import (
    RecycleVerificationError,
    inspect_recycle_evidence,
    load_recycle_verification,
)
from .evidence_snapshot import load_validated_restore_evidence_snapshot


def _safe_status(manifest: str | Path) -> int:
    # Preserve the caller's lexical ancestry until the hardened loader can inspect
    # every component. Resolving here would hide a symlink/junction/reparse parent.
    manifest_path = workflow._absolute_without_resolving(manifest)
    check = load_recycle_verification(manifest_path)
    workflow._require_runtime_safety_contract(check)
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
    print(f"SAFETY_CONTRACT_SHA256={workflow._runtime_contract_digest()}")

    if inspection.stage == "prepared":
        print(
            "NEXT=Run the guarded move without recreating the fixture: "
            f"SwirPhotoClean.exe --recycle-restore-move \"{manifest_path}\""
        )
        return 0

    if inspection.stage == "recycled":
        print(
            "NEXT=Restore RECYCLE-ME.png from Windows Recycle Bin, then run: "
            f"SwirPhotoClean.exe --recycle-restore-verify \"{manifest_path}\""
        )
        return 0

    report = manifest_path.parent / workflow.REPORT_NAME
    print(f"REPORT_PRESENT={'yes' if report.is_file() else 'no'} path={report}")
    if not report.is_file():
        print(
            "NEXT=Re-run --recycle-restore-verify to recreate the evidence report; "
            "the physical restore does not need to be repeated."
        )
        return 0

    reviewed, report_path, _raw, _payload = load_validated_restore_evidence_snapshot(
        report,
        manifest=manifest_path,
    )
    continuity = workflow._require_restored_receipt_identity(reviewed)
    print("REPORT_VALID=yes")
    print(
        "FILESYSTEM_IDENTITY_CONTINUITY="
        + ("yes" if continuity else "not-recorded")
    )
    print(
        "NEXT=Run the read-only report review before changing STATUS.md: "
        f"SwirPhotoClean.exe --recycle-restore-review \"{report_path}\""
    )
    print("READY_FOR_REVIEW")
    return 0


def _safe_review(report: str | Path) -> int:
    check, report_path, _raw, _payload = load_validated_restore_evidence_snapshot(report)
    continuity = workflow._require_restored_receipt_identity(check)
    print("REPORT_VALID")
    print(f"EVIDENCE_STAGE={check.stage}")
    print(f"SESSION={check.session_id or 'legacy'}")
    print(f"SHA256={check.digest}")
    print(f"SAFETY_CONTRACT_SHA256={workflow._runtime_contract_digest()}")
    print(
        "FILESYSTEM_IDENTITY_CONTINUITY="
        + ("yes" if continuity else "not-recorded")
    )
    print(f"MANIFEST={check.manifest}")
    print(f"EVIDENCE_REPORT={report_path}")
    print(
        "NEXT=Only after physically confirming Windows Restore, create the packaged "
        "release attestation with: SwirPhotoClean.exe --recycle-restore-attest "
        f"\"{report_path}\" --confirm-manual-restore"
    )
    print("READY_FOR_MANUAL_ACCEPTANCE_REVIEW")
    return 0


def cli_main(argv: tuple[str, ...] | list[str]) -> int:
    """Run the hardened review commands; delegate state-changing commands unchanged."""
    args = list(argv)
    if not args:
        print("Recycle restore evidence command missing.")
        return 2

    command = args[0]
    if command not in {"--recycle-restore-status", "--recycle-restore-review"}:
        return workflow.cli_main(args)

    try:
        if command == "--recycle-restore-status":
            if len(args) != 2:
                raise RecycleVerificationError(
                    "status requires exactly one recycle-verification.json path"
                )
            return _safe_status(args[1])

        if len(args) != 2:
            raise RecycleVerificationError(
                "review requires exactly one recycle-evidence-report.json path"
            )
        return _safe_review(args[1])
    except (RecycleVerificationError, OSError) as error:
        print(f"EVIDENCE_FAILED: {error}")
        return 2
