from __future__ import annotations

import argparse
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


def release_channel(version: str, done: int, total: int) -> str:
    match = _SEMVER.fullmatch(version)
    if not match:
        raise ReleaseGateError(f"invalid release version: {version!r}")
    if total <= 0 or done < 0 or done > total:
        raise ReleaseGateError(f"invalid acceptance metrics: {done}/{total}")

    major = int(match.group(1))
    prerelease = match.group(4)
    stable = major >= 1 and prerelease is None
    if stable and done != total:
        raise ReleaseGateError(
            f"stable {version} is blocked: acceptance gate is {done}/{total}, not complete"
        )
    return "stable" if stable else "prerelease"


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


def evaluate_release() -> ReleaseDecision:
    version = parse_version(VERSION_FILE.read_text(encoding="utf-8"))
    done, total, _ = _acceptance_metrics()
    channel = release_channel(version, done, total)
    validate_release_notes(version, RELEASE_NOTES.read_text(encoding="utf-8"))
    return ReleaseDecision(version=version, channel=channel, done=done, total=total)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail closed when release metadata or the stable acceptance gate is unsafe."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="validate and print a release decision")
    group.add_argument("--channel", action="store_true", help="print only stable/prerelease")
    args = parser.parse_args()

    try:
        decision = evaluate_release()
    except (OSError, ReleaseGateError) as error:
        raise SystemExit(f"release gate failed: {error}") from error

    if args.channel:
        print(decision.channel)
    else:
        print(
            f"release gate ok: version={decision.version} "
            f"channel={decision.channel} acceptance={decision.done}/{decision.total}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
