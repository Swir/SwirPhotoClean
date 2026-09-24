from __future__ import annotations

import argparse
import json
import os
import re
import stat
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
_REPARSE_POINT_ATTRIBUTE = 0x400
_MAX_RUNTIME_EVIDENCE_BYTES = 64 * 1024


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


def _runtime_evidence_identity(info) -> tuple[int, int, int, int, int, int]:
    """Normalize metadata used to bind a release-evidence path to one open handle."""
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(getattr(info, "st_nlink", 1)),
        int(info.st_size),
        int(getattr(info, "st_mtime_ns", int(info.st_mtime * 1_000_000_000))),
        int(getattr(info, "st_ctime_ns", int(info.st_ctime * 1_000_000_000))),
    )


def _runtime_path_and_handle_identity_match(
    path_identity: tuple[int, int, int, int, int, int],
    handle_identity: tuple[int, int, int, int, int, int],
) -> bool:
    """Compare lstat/fstat identity without Windows CRT representation noise."""
    if os.name != "nt":
        return path_identity == handle_identity

    path_inode = path_identity[1]
    handle_inode = handle_identity[1]
    if path_inode <= 0 or handle_inode <= 0 or path_inode != handle_inode:
        return False
    return path_identity[2:5] == handle_identity[2:5]


def _require_safe_runtime_evidence_directory_ancestry(directory: Path) -> None:
    """Reject redirected lexical ancestry around RELEASE_EVIDENCE.json.

    The release gate intentionally inspects the path as supplied instead of resolving
    it first. Every existing parent must therefore remain an ordinary directory both
    before and after the bounded handle read; symlinks, junctions and other reparse
    points fail closed rather than redirecting the publication gate to another file.
    """
    current = Path(os.path.abspath(os.fspath(directory.expanduser())))
    chain: list[Path] = []
    while True:
        chain.append(current)
        parent = current.parent
        if parent == current:
            break
        current = parent

    for entry in reversed(chain):
        try:
            info = entry.lstat()
        except OSError as error:
            raise ReleaseGateError(
                f"cannot safely inspect runtime evidence directory {entry}: {error}"
            ) from error
        if stat.S_ISLNK(info.st_mode) or bool(
            getattr(info, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE
        ):
            raise ReleaseGateError(
                "runtime evidence directory ancestry must not contain symlinks, "
                f"junctions or reparse points: {entry}"
            )
        if not stat.S_ISDIR(info.st_mode):
            raise ReleaseGateError(
                f"runtime evidence directory ancestry contains a non-directory entry: {entry}"
            )


def _require_safe_runtime_evidence_entry(path: Path):
    """Reject aliases and ambiguous filesystem objects before release authorization."""
    try:
        info = path.lstat()
    except OSError as error:
        raise ReleaseGateError(
            f"cannot safely inspect runtime evidence input {path}: {error}"
        ) from error

    if stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE
    ):
        raise ReleaseGateError(
            "runtime evidence input must not be a symlink, junction or reparse point"
        )
    if not stat.S_ISREG(info.st_mode):
        raise ReleaseGateError("runtime evidence input must be a regular file")
    if int(getattr(info, "st_nlink", 1)) != 1:
        raise ReleaseGateError("runtime evidence input must not be hardlinked")
    if int(info.st_size) > _MAX_RUNTIME_EVIDENCE_BYTES:
        raise ReleaseGateError(
            f"runtime evidence input is too large: maximum is {_MAX_RUNTIME_EVIDENCE_BYTES} bytes"
        )
    return info


def _read_stable_runtime_evidence_payload(path: Path) -> object:
    """Read one bounded immutable snapshot of RELEASE_EVIDENCE.json.

    The publication gate must validate the exact bytes captured from the verified
    regular-file handle. A path swap, hardlink, reparse point, redirected parent,
    oversized input or metadata mutation therefore fails closed instead of
    authorizing a release from a different filesystem object than the one inspected
    before opening.
    """
    evidence = Path(os.path.abspath(os.fspath(path.expanduser())))
    _require_safe_runtime_evidence_directory_ancestry(evidence.parent)
    before = _require_safe_runtime_evidence_entry(evidence)
    before_identity = _runtime_evidence_identity(before)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(evidence, flags)
    except OSError as error:
        raise ReleaseGateError(
            f"cannot open runtime evidence safely: {error}"
        ) from error

    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ReleaseGateError(
                "runtime evidence input changed to a non-regular file while opening"
            )
        if bool(getattr(opened, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE):
            raise ReleaseGateError(
                "runtime evidence input changed to a reparse point while opening"
            )
        if int(getattr(opened, "st_nlink", 1)) != 1:
            raise ReleaseGateError(
                "runtime evidence input became hardlinked while opening"
            )
        opened_identity = _runtime_evidence_identity(opened)
        if not _runtime_path_and_handle_identity_match(before_identity, opened_identity):
            raise ReleaseGateError(
                "runtime evidence input changed while it was being opened"
            )

        chunks: list[bytes] = []
        total = 0
        while True:
            remaining = _MAX_RUNTIME_EVIDENCE_BYTES + 1 - total
            if remaining <= 0:
                raise ReleaseGateError(
                    f"runtime evidence input is too large: maximum is {_MAX_RUNTIME_EVIDENCE_BYTES} bytes"
                )
            try:
                chunk = os.read(descriptor, min(64 * 1024, remaining))
            except OSError as error:
                raise ReleaseGateError(
                    f"cannot read runtime evidence safely: {error}"
                ) from error
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > _MAX_RUNTIME_EVIDENCE_BYTES:
                raise ReleaseGateError(
                    f"runtime evidence input is too large: maximum is {_MAX_RUNTIME_EVIDENCE_BYTES} bytes"
                )

        after = os.fstat(descriptor)
        if _runtime_evidence_identity(after) != opened_identity:
            raise ReleaseGateError("runtime evidence input changed while being read")
    finally:
        os.close(descriptor)

    _require_safe_runtime_evidence_directory_ancestry(evidence.parent)
    final = _require_safe_runtime_evidence_entry(evidence)
    if _runtime_evidence_identity(final) != before_identity:
        raise ReleaseGateError("runtime evidence input path changed while being read")

    raw = b"".join(chunks)
    if len(raw) != int(before.st_size):
        raise ReleaseGateError("runtime evidence input size changed while being read")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReleaseGateError(
            f"runtime evidence input is not valid UTF-8 JSON: {error}"
        ) from error


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

    try:
        RELEASE_EVIDENCE_PATH.lstat()
    except FileNotFoundError:
        if required:
            raise ReleaseGateError(
                f"qualified release requires valid {RELEASE_EVIDENCE_PATH.name}: file is missing"
            )
        return False
    except OSError as error:
        raise ReleaseGateError(
            f"cannot inspect {RELEASE_EVIDENCE_PATH.name} before release evaluation: {error}"
        ) from error

    try:
        payload = _read_stable_runtime_evidence_payload(RELEASE_EVIDENCE_PATH)
        validate_release_evidence(payload)
    except (OSError, ReleaseEvidenceError, ReleaseGateError) as error:
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