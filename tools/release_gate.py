from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "photoclean" / "__init__.py"
RELEASE_NOTES = ROOT / "RELEASE_NOTES.md"

_VERSION_ASSIGNMENT = re.compile(r'__version__\s*=\s*"([^"]+)"')
_SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$"
)


class ReleaseGateError(ValueError):
    """Release metadata or acceptance evidence is not safe to publish."""


@dataclass(frozen=True, slots=True)
class ReleaseDecision:
    version: str
    channel: str
    done: int
    total: int
    runtime_evidence_required: bool = False


def parse_version(module_text: str) -> str:
    match = _VERSION_ASSIGNMENT.search(module_text)
    if not match:
        raise ReleaseGateError("photoclean.__version__ is missing")
    version = match.group(1)
    if not _SEMVER.fullmatch(version):
        raise ReleaseGateError(
            f"version {version!r} is not supported semantic version X.Y.Z[-prerelease]"
        )
    return version


def _validated_version(version: str):
    match = _SEMVER.fullmatch(version)
    if not match:
        raise ReleaseGateError(f"invalid release version: {version!r}")
    return match


def _validate_acceptance_metrics(done: int, total: int) -> None:
    if total <= 0 or done < 0 or done > total:
        raise ReleaseGateError(f"invalid acceptance metrics: {done}/{total}")


def candidate_channel(version: str) -> str:
    """Return the intended channel without asserting publication readiness."""
    match = _validated_version(version)
    major = int(match.group(1))
    prerelease = match.group(4)
    return "stable" if major >= 1 and prerelease is None else "prerelease"


def validate_build_candidate(version: str, done: int, total: int) -> None:
    """Allow exact-version package qualification before manual release evidence exists.

    This gate is intentionally build-only. It validates version/acceptance metadata,
    but it does not authorize publication. The strict publication path continues to
    require the complete acceptance gate and qualified Windows runtime evidence.
    """
    _validated_version(version)
    _validate_acceptance_metrics(done, total)


def release_channel(version: str, done: int, total: int) -> str:
    match = _validated_version(version)
    _validate_acceptance_metrics(done, total)

    major = int(match.group(1))
    prerelease = match.group(4)
    stable = major >= 1 and prerelease is None
    if stable and done != total:
        raise ReleaseGateError(
            f"stable {version} is blocked: acceptance gate is {done}/{total}, not complete"
        )
    return "stable" if stable else "prerelease"


def runtime_evidence_required(version: str) -> bool:
    """Require physical Windows evidence for qualified Beta/RC/1.x publications."""
    match = _validated_version(version)
    major = int(match.group(1))
    prerelease = (match.group(4) or "").lower()
    if major >= 1:
        return True
    tokens = [token for token in re.split(r"[.-]", prerelease) if token]
    return any(token in {"beta", "rc"} for token in tokens)


def validate_qualified_acceptance(version: str, done: int, total: int) -> None:
    _validate_acceptance_metrics(done, total)
    if runtime_evidence_required(version) and done != total:
        raise ReleaseGateError(
            f"qualified {version} release is blocked: acceptance gate is "
            f"{done}/{total}, not complete"
        )


def validate_release_notes(version: str, text: str) -> None:
    headings = [line.strip() for line in text.splitlines() if line.strip().startswith("# ")]
    expected = f"# SWIR PhotoClean {version}"
    if not headings or headings[0] != expected:
        found = headings[0] if headings else "<missing>"
        raise ReleaseGateError(
            f"RELEASE_NOTES.md heading mismatch: expected {expected!r}, found {found!r}"
        )


def _acceptance_metrics() -> tuple[int, int, float]:
    try:
        from tools.readme_progress import metrics
    except ModuleNotFoundError:
        from readme_progress import metrics
    return metrics()


def _read_runtime_evidence(*, required: bool) -> bool:
    try:
        from tools.release_evidence import (
            RELEASE_EVIDENCE_PATH,
            ReleaseEvidenceError,
            validate_release_evidence,
        )
    except ModuleNotFoundError:
        from release_evidence import (  # type: ignore
            RELEASE_EVIDENCE_PATH,
            ReleaseEvidenceError,
            validate_release_evidence,
        )

    if not RELEASE_EVIDENCE_PATH.exists():
        if required:
            raise ReleaseGateError(
                f"qualified release requires valid {RELEASE_EVIDENCE_PATH.name}: file is missing"
            )
        return False

    try:
        payload = json.loads(RELEASE_EVIDENCE_PATH.read_text(encoding="utf-8"))
        validate_release_evidence(payload)
    except (OSError, json.JSONDecodeError, ReleaseEvidenceError) as error:
        raise ReleaseGateError(
            f"qualified release requires valid {RELEASE_EVIDENCE_PATH.name}: {error}"
        ) from error
    return True


def evaluate_build_candidate() -> ReleaseDecision:
    """Validate the exact version that CI is allowed to build and hand to Windows review."""
    version = parse_version(VERSION_FILE.read_text(encoding="utf-8"))
    done, total, _ = _acceptance_metrics()
    validate_build_candidate(version, done, total)
    validate_release_notes(version, RELEASE_NOTES.read_text(encoding="utf-8"))

    evidence_required = runtime_evidence_required(version)
    # Before the physical Windows test, evidence is expected to be absent. If a
    # file is present, however, it must already be valid for the exact safety
    # contract so CI never silently builds around stale/tampered evidence.
    if evidence_required:
        _read_runtime_evidence(required=False)

    return ReleaseDecision(
        version=version,
        channel=candidate_channel(version),
        done=done,
        total=total,
        runtime_evidence_required=evidence_required,
    )


def evaluate_release() -> ReleaseDecision:
    version = parse_version(VERSION_FILE.read_text(encoding="utf-8"))
    done, total, _ = _acceptance_metrics()
    channel = release_channel(version, done, total)
    validate_release_notes(version, RELEASE_NOTES.read_text(encoding="utf-8"))

    evidence_required = runtime_evidence_required(version)
    validate_qualified_acceptance(version, done, total)
    if evidence_required:
        _read_runtime_evidence(required=True)

    return ReleaseDecision(
        version=version,
        channel=channel,
        done=done,
        total=total,
        runtime_evidence_required=evidence_required,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail closed when release metadata or acceptance evidence is unsafe."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--build-check",
        action="store_true",
        help="validate the exact-version package candidate without authorizing publication",
    )
    group.add_argument("--check", action="store_true", help="validate and print a release decision")
    group.add_argument("--channel", action="store_true", help="print only stable/prerelease")
    args = parser.parse_args()

    try:
        if args.build_check:
            decision = evaluate_build_candidate()
        else:
            decision = evaluate_release()
    except (OSError, ReleaseGateError) as error:
        raise SystemExit(f"release gate failed: {error}") from error

    if args.channel:
        print(decision.channel)
    else:
        evidence = "required" if decision.runtime_evidence_required else "not-required"
        gate = "build-candidate" if args.build_check else "release"
        print(
            f"{gate} gate ok: version={decision.version} "
            f"channel={decision.channel} acceptance={decision.done}/{decision.total} "
            f"runtime-evidence={evidence}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
