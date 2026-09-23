"""Packaged/source CLI adapter for the generated Recycle Bin restore workflow.

The authoritative verification model lives in :mod:`photoclean.diagnostics`. This
module only makes that existing tamper-evident workflow easy to execute from a
release-candidate EXE. It never closes the repository acceptance gate itself.
"""
from __future__ import annotations

import json
import os
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
from .recycle import RecycleReceipt, recycle_file
from .safety_contract import SafetyContractError, runtime_safety_contract_sha256

REPORT_NAME = "recycle-evidence-report.json"
WORKSPACE_NAME = "SwirPhotoClean-Recycle-Restore-Test"
SAFETY_CONTRACT_FIELD = "safety_contract_sha256"
RECYCLE_RECEIPT_FIELD = "recycle_receipt"
RECYCLE_RECEIPT_VERSION = 1


def _absolute_without_resolving(path: str | os.PathLike) -> Path:
    """Return an absolute lexical path without following symlinks/junctions.

    Release-evidence intake is hardened later by :mod:`photoclean.evidence_io`.
    Passing it a pre-resolved path would erase the original ancestry and could
    hide a symlink/junction/reparse component before the hardened loader has a
    chance to reject it.
    """
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


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


def _receipt_payload(receipt: RecycleReceipt) -> dict:
    return {
        "version": RECYCLE_RECEIPT_VERSION,
        "source_device": int(receipt.source_device),
        "source_inode": int(receipt.source_inode),
        "recycled_shell_path": str(receipt.recycled_shell_path or ""),
    }


def _validated_receipt(payload: dict) -> dict | None:
    receipt = payload.get(RECYCLE_RECEIPT_FIELD)
    if receipt is None:
        return None
    expected_fields = {
        "version",
        "source_device",
        "source_inode",
        "recycled_shell_path",
    }
    if not isinstance(receipt, dict) or set(receipt) != expected_fields:
        raise RecycleVerificationError("Recycle receipt is malformed")
    if receipt.get("version") != RECYCLE_RECEIPT_VERSION:
        raise RecycleVerificationError("Unsupported recycle receipt version")
    device = receipt.get("source_device")
    inode = receipt.get("source_inode")
    shell_path = receipt.get("recycled_shell_path")
    if (
        not isinstance(device, int)
        or isinstance(device, bool)
        or device < 0
        or not isinstance(inode, int)
        or isinstance(inode, bool)
        or inode < 0
        or not isinstance(shell_path, str)
    ):
        raise RecycleVerificationError("Recycle receipt contains invalid filesystem identity")
    return dict(receipt)


def _record_recycle_receipt(
    check: RecycleVerification,
    receipt: RecycleReceipt,
) -> RecycleVerification:
    """Persist the Windows Shell receipt inside the fingerprinted manifest."""
    payload = _read_manifest_payload(check)
    if payload.get("stage") != "recycled":
        raise RecycleVerificationError("Recycle receipt can only be recorded in recycled stage")
    normalized = _receipt_payload(receipt)
    existing = payload.get(RECYCLE_RECEIPT_FIELD)
    if existing is not None and existing != normalized:
        raise RecycleVerificationError("Recycle verification already contains a different receipt")
    events = payload.get("events")
    if not isinstance(events, list) or not events or not isinstance(events[-1], dict):
        raise RecycleVerificationError("Recycle verification event log is unavailable")
    if events[-1].get("stage") != "recycled":
        raise RecycleVerificationError("Recycle receipt does not match the current event stage")
    payload[RECYCLE_RECEIPT_FIELD] = normalized
    events[-1][RECYCLE_RECEIPT_FIELD] = normalized
    _atomic_write_json(check.manifest, payload)
    return load_recycle_verification(check.manifest)


def _require_restored_receipt_identity(check: RecycleVerification) -> bool:
    """Prove that a restored file is the same filesystem object moved by Shell.

    Legacy/source tests that use an injected recycler and do not return a
    :class:`RecycleReceipt` remain valid but cannot claim object-identity
    continuity. A real packaged Windows move returns a receipt. On filesystems
    exposing a non-zero inode/file index, restore verification then rejects a
    byte-identical replacement that was recreated after the move.
    """
    payload = _read_manifest_payload(check)
    receipt = _validated_receipt(payload)
    if receipt is None or receipt["source_inode"] <= 0:
        return False
    try:
        info = check.copy.stat()
    except OSError as error:
        raise RecycleVerificationError(
            f"Restored verification copy is unavailable for identity continuity: {error}"
        ) from error
    restored_identity = (int(info.st_dev), int(info.st_ino))
    expected_identity = (receipt["source_device"], receipt["source_inode"])
    if restored_identity != expected_identity:
        raise RecycleVerificationError(
            "Restored verification copy is byte-compatible but is not the same "
            "filesystem object that Windows moved to the Recycle Bin"
        )
    return True


def create_restore_evidence(
    workspace: str | Path | None = None,
) -> RecycleVerification:
    """Create a fresh generated fixture bound to the current release safety contract."""
    base = _absolute_without_resolving(workspace) if workspace is not None else default_workspace()
    base.mkdir(parents=True, exist_ok=True)
    check = create_recycle_verification(base)
    return _bind_runtime_safety_contract(check)


def move_restore_evidence(
    manifest: str | Path,
    *,
    recycler: Callable[[str], object] | None = None,
) -> RecycleVerification:
    """Retry or perform the guarded Recycle Bin move for an existing prepared fixture.

    The production Windows recycler returns a :class:`RecycleReceipt`. The adapter
    fingerprints that receipt into the evidence manifest so a later restore can be
    tied to the same filesystem object rather than only to matching bytes.
    """
    check = load_recycle_verification(_absolute_without_resolving(manifest))
    _require_runtime_safety_contract(check)
    recycle_action = recycler if recycler is not None else recycle_file
    captured: list[object] = []

    def capture_receipt(path: str) -> object:
        result = recycle_action(path)
        captured.append(result)
        return result

    moved = move_generated_copy_to_recycle(check, recycler=capture_receipt)
    if captured and isinstance(captured[-1], RecycleReceipt):
        moved = _record_recycle_receipt(moved, captured[-1])
    return moved


def prepare_restore_evidence(
    workspace: str | Path | None = None,
    *,
    recycler: Callable[[str], object] | None = None,
) -> RecycleVerification:
    """Create generated fixtures and move only RECYCLE-ME.png to Recycle Bin."""
    check = create_restore_evidence(workspace)
    return move_restore_evidence(check.manifest, recycler=recycler)


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
    check = load_recycle_verification(_absolute_without_resolving(manifest))
    _require_runtime_safety_contract(check)
    identity_continuity = _require_restored_receipt_identity(check)
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
        _absolute_without_resolving(report_path)
        if report_path is not None
        else verified.folder / REPORT_NAME
    )
    report = export_recycle_evidence(verified, destination)
    if identity_continuity:
        # The receipt is already embedded in the manifest/report. Keep this check
        # read-only: no second state transition is required merely to record that
        # the comparison succeeded.
        _require_restored_receipt_identity(verified)
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
    report = _absolute_without_resolving(report_path)
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
        _absolute_without_resolving(manifest)
        if manifest is not None
        else report.parent / "recycle-verification.json"
    )
    check = load_recycle_verification(manifest_path)
    _require_runtime_safety_contract(check)
    if check.stage != "restored-verified":
        raise RecycleVerificationError(
            "Recycle evidence report is reviewable only after restored-verified stage"
        )
    _require_restored_receipt_identity(check)

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
    receipt = _validated_receipt(_read_manifest_payload(check))
    if receipt is not None:
        print(
            "FILESYSTEM_IDENTITY_RECEIPT="
            + ("available" if receipt["source_inode"] > 0 else "unavailable")
        )
    print(
        "Restore RECYCLE-ME.png from Windows Recycle Bin, then run: "
        f"SwirPhotoClean.exe --recycle-restore-verify \"{check.manifest}\""
    )


def _print_status(manifest: str | Path) -> int:
    manifest_path = _absolute_without_resolving(manifest)
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
            continuity = _require_restored_receipt_identity(check)
            print("REPORT_VALID=yes")
            print(
                "FILESYSTEM_IDENTITY_CONTINUITY="
                + ("yes" if continuity else "not-recorded")
            )
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
    continuity = _require_restored_receipt_identity(check)
    print("REPORT_VALID")
    print(f"EVIDENCE_STAGE={check.stage}")
    print(f"SESSION={check.session_id or 'legacy'}")
    print(f"SHA256={check.digest}")
    print(f"SAFETY_CONTRACT_SHA256={_runtime_contract_digest()}")
    print(
        "FILESYSTEM_IDENTITY_CONTINUITY="
        + ("yes" if continuity else "not-recorded")
    )
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
            continuity = _require_restored_receipt_identity(verified)
            print("RESTORE_VERIFIED")
            print(f"ORIGINAL_PRESERVED path={verified.original}")
            print(f"RESTORED_COPY path={verified.copy}")
            print(f"SHA256={verified.digest}")
            print(f"SAFETY_CONTRACT_SHA256={_runtime_contract_digest()}")
            print(
                "FILESYSTEM_IDENTITY_CONTINUITY="
                + ("yes" if continuity else "not-recorded")
            )
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
