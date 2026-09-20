"""Packaged/source CLI adapter for the generated Recycle Bin restore workflow.

The authoritative verification model lives in :mod:`photoclean.diagnostics`. This
module only makes that existing tamper-evident workflow easy to execute from a
release-candidate EXE. It never closes the repository acceptance gate itself.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from .diagnostics import (
    RecycleVerification,
    RecycleVerificationError,
    create_recycle_verification,
    export_recycle_evidence,
    load_recycle_verification,
    move_generated_copy_to_recycle,
    verify_restored_copy,
)

REPORT_NAME = "recycle-evidence-report.json"
WORKSPACE_NAME = "SwirPhotoClean-Recycle-Restore-Test"


def default_workspace() -> Path:
    home = Path.home()
    documents = home / "Documents"
    base = documents if documents.is_dir() else home
    return base / WORKSPACE_NAME


def prepare_restore_evidence(
    workspace: str | Path | None = None,
    *,
    recycler: Callable[[str], object] | None = None,
) -> RecycleVerification:
    """Create generated fixtures and move only RECYCLE-ME.png to Recycle Bin."""
    base = Path(workspace).expanduser().resolve() if workspace is not None else default_workspace()
    base.mkdir(parents=True, exist_ok=True)
    check = create_recycle_verification(base)
    return move_generated_copy_to_recycle(check, recycler=recycler)


def verify_restore_evidence(
    manifest: str | Path,
    *,
    report_path: str | Path | None = None,
) -> tuple[RecycleVerification, Path]:
    """Verify a manual Windows restore and export the existing evidence report."""
    check = load_recycle_verification(Path(manifest).expanduser().resolve())
    verified = verify_restored_copy(check)
    destination = (
        Path(report_path).expanduser().resolve()
        if report_path is not None
        else verified.folder / REPORT_NAME
    )
    report = export_recycle_evidence(verified, destination)
    return verified, report


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
            check = prepare_restore_evidence(args[0] if args else None)
            print(f"MOVE_CONFIRMED manifest={check.manifest}")
            print(f"ORIGINAL_PRESERVED path={check.original}")
            print(f"RESTORE_REQUIRED path={check.copy}")
            print(
                "Restore RECYCLE-ME.png from Windows Recycle Bin, then run: "
                f"SwirPhotoClean.exe --recycle-restore-verify \"{check.manifest}\""
            )
            return 0

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
            print(f"EVIDENCE_REPORT path={report}")
            return 0

        raise RecycleVerificationError(f"unknown evidence command: {command}")
    except (RecycleVerificationError, OSError) as error:
        print(f"EVIDENCE_FAILED: {error}")
        return 2
