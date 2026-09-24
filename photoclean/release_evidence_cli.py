from __future__ import annotations

from pathlib import Path

from .recycle_evidence import _absolute_without_resolving
from .release_attestation import (
    ATTESTATION_NAME,
    PackagedAttestationError,
    write_packaged_attestation,
)


def _parse_attest_args(args: list[str]) -> tuple[Path, Path, bool]:
    if not args:
        raise PackagedAttestationError(
            "attest requires a recycle-evidence-report.json path"
        )

    # Keep lexical ancestry intact until the hardened evidence reader/writer can
    # reject symlink/junction/reparse components. Path.resolve() here would erase
    # the exact filesystem path supplied by the packaged Windows operator.
    report = _absolute_without_resolving(args.pop(0))
    output: Path | None = None
    confirmed = False

    while args:
        token = args.pop(0)
        if token == "--confirm-manual-restore":
            if confirmed:
                raise PackagedAttestationError(
                    "--confirm-manual-restore may be supplied only once"
                )
            confirmed = True
            continue
        if token == "--output":
            if output is not None:
                raise PackagedAttestationError("--output may be supplied only once")
            if not args:
                raise PackagedAttestationError("--output requires a file path")
            output = _absolute_without_resolving(args.pop(0))
            continue
        raise PackagedAttestationError(f"unknown attest option: {token}")

    if not confirmed:
        raise PackagedAttestationError(
            "attest requires --confirm-manual-restore after you physically choose "
            "Restore in Windows Recycle Bin"
        )
    if output is None:
        output = report.parent / ATTESTATION_NAME
    return report, output, confirmed


def cli_main(argv: tuple[str, ...] | list[str]) -> int:
    args = list(argv)
    if not args:
        print("Release evidence command missing.")
        return 2

    command = args.pop(0)
    try:
        if command != "--recycle-restore-attest":
            raise PackagedAttestationError(
                f"unknown release evidence command: {command}"
            )
        report, output, confirmed = _parse_attest_args(args)
        written = write_packaged_attestation(
            report,
            output,
            confirm_manual_restore=confirmed,
        )
        print(f"RELEASE_EVIDENCE_WRITTEN path={written}")
        print("RELEASE_EVIDENCE_VALID=yes")
        print("ACCEPTANCE_GATE_CLOSED=no")
        print(
            "NEXT=Copy this validated RELEASE_EVIDENCE.json to the repository root "
            "for the qualified release gate, then review the physical Windows evidence "
            "before changing STATUS.md."
        )
        return 0
    except (OSError, PackagedAttestationError) as error:
        print(f"EVIDENCE_FAILED: {error}")
        return 2
