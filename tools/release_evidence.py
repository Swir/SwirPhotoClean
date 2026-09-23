from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
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
_REPARSE_POINT_ATTRIBUTE = 0x400
_MAX_RELEASE_EVIDENCE_BYTES = 64 * 1024
_READ_CHUNK_BYTES = 64 * 1024
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


def _absolute_without_resolving(path: str | Path) -> Path:
    """Return an absolute path while preserving the final filesystem entry."""
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def _paths_alias(first: Path, second: Path) -> bool:
    """Detect lexical aliases and existing hardlink/symlink aliases."""
    first_text = os.path.normcase(os.path.abspath(os.fspath(first)))
    second_text = os.path.normcase(os.path.abspath(os.fspath(second)))
    if first_text == second_text:
        return True
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False


def _require_safe_release_evidence_directory_ancestry(
    directory: Path,
    *,
    allow_missing: bool = False,
) -> None:
    """Reject redirected lexical output ancestry before writing release evidence.

    The walk deliberately uses ``lstat`` without resolving the path so symlinks,
    Windows junctions and other reparse points stay visible.  Missing descendants
    are allowed only during the pre-``mkdir`` check; every existing ancestor must
    already be an ordinary directory.
    """
    current = _absolute_without_resolving(directory)
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
        except FileNotFoundError:
            if allow_missing:
                continue
            raise ReleaseEvidenceError(
                f"release evidence output directory does not exist: {entry}"
            )
        except OSError as error:
            raise ReleaseEvidenceError(
                f"cannot safely inspect release evidence output directory {entry}: {error}"
            ) from error

        if stat.S_ISLNK(info.st_mode) or bool(
            getattr(info, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE
        ):
            raise ReleaseEvidenceError(
                "release evidence output directory ancestry must not contain symlinks, "
                f"junctions or reparse points: {entry}"
            )
        if not stat.S_ISDIR(info.st_mode):
            raise ReleaseEvidenceError(
                f"release evidence output directory ancestry contains a non-directory entry: {entry}"
            )


def _release_evidence_input_identity(info) -> tuple[int, int, int, int, int, int]:
    """Normalize metadata used to bind a verified input path to one open handle."""
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(getattr(info, "st_nlink", 1)),
        int(info.st_size),
        int(getattr(info, "st_mtime_ns", int(info.st_mtime * 1_000_000_000))),
        int(getattr(info, "st_ctime_ns", int(info.st_ctime * 1_000_000_000))),
    )


def _release_evidence_path_and_handle_identity_match(
    path_identity: tuple[int, int, int, int, int, int],
    handle_identity: tuple[int, int, int, int, int, int],
) -> bool:
    """Compare path/handle identity without known Windows CRT metadata noise."""
    if os.name != "nt":
        return path_identity == handle_identity

    path_inode = path_identity[1]
    handle_inode = handle_identity[1]
    if path_inode <= 0 or handle_inode <= 0 or path_inode != handle_inode:
        return False
    return path_identity[2:5] == handle_identity[2:5]


def _require_safe_release_evidence_input(path: Path):
    """Reject ambiguous filesystem objects before standalone evidence verification."""
    try:
        info = path.lstat()
    except OSError as error:
        raise ReleaseEvidenceError(
            f"cannot safely inspect release evidence input {path}: {error}"
        ) from error

    if stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE
    ):
        raise ReleaseEvidenceError(
            "release evidence input must not be a symlink, junction or reparse point"
        )
    if not stat.S_ISREG(info.st_mode):
        raise ReleaseEvidenceError("release evidence input must be a regular file")
    if int(getattr(info, "st_nlink", 1)) != 1:
        raise ReleaseEvidenceError("release evidence input must not be hardlinked")
    if int(info.st_size) > _MAX_RELEASE_EVIDENCE_BYTES:
        raise ReleaseEvidenceError(
            f"release evidence input is too large: maximum is {_MAX_RELEASE_EVIDENCE_BYTES} bytes"
        )
    return info


def _read_stable_release_evidence_payload(path: str | Path) -> object:
    """Read one bounded immutable snapshot of sanitized release evidence."""
    evidence = _absolute_without_resolving(path)
    before = _require_safe_release_evidence_input(evidence)
    before_identity = _release_evidence_input_identity(before)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(evidence, flags)
    except OSError as error:
        raise ReleaseEvidenceError(f"cannot open release evidence safely: {error}") from error

    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ReleaseEvidenceError(
                "release evidence input changed to a non-regular file while opening"
            )
        if bool(getattr(opened, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE):
            raise ReleaseEvidenceError(
                "release evidence input changed to a reparse point while opening"
            )
        if int(getattr(opened, "st_nlink", 1)) != 1:
            raise ReleaseEvidenceError(
                "release evidence input became hardlinked while opening"
            )
        opened_identity = _release_evidence_input_identity(opened)
        if not _release_evidence_path_and_handle_identity_match(
            before_identity,
            opened_identity,
        ):
            raise ReleaseEvidenceError(
                "release evidence input changed while it was being opened"
            )

        chunks: list[bytes] = []
        total = 0
        while True:
            remaining = _MAX_RELEASE_EVIDENCE_BYTES + 1 - total
            if remaining <= 0:
                raise ReleaseEvidenceError(
                    f"release evidence input is too large: maximum is {_MAX_RELEASE_EVIDENCE_BYTES} bytes"
                )
            try:
                chunk = os.read(descriptor, min(_READ_CHUNK_BYTES, remaining))
            except OSError as error:
                raise ReleaseEvidenceError(
                    f"cannot read release evidence safely: {error}"
                ) from error
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > _MAX_RELEASE_EVIDENCE_BYTES:
                raise ReleaseEvidenceError(
                    f"release evidence input is too large: maximum is {_MAX_RELEASE_EVIDENCE_BYTES} bytes"
                )

        after = os.fstat(descriptor)
        if _release_evidence_input_identity(after) != opened_identity:
            raise ReleaseEvidenceError("release evidence input changed while being read")
    finally:
        os.close(descriptor)

    final = _require_safe_release_evidence_input(evidence)
    if _release_evidence_input_identity(final) != before_identity:
        raise ReleaseEvidenceError("release evidence input path changed while being read")

    raw = b"".join(chunks)
    if len(raw) != int(before.st_size):
        raise ReleaseEvidenceError("release evidence input size changed while being read")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReleaseEvidenceError(
            f"release evidence input is not valid UTF-8 JSON: {error}"
        ) from error


def _release_evidence_output_identity(
    path: Path,
) -> tuple[int, int, int, int, int, int] | None:
    """Return output identity or fail closed for unsafe existing output entries."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise ReleaseEvidenceError(
            f"cannot safely inspect release evidence output path {path}: {error}"
        ) from error

    if stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE
    ):
        raise ReleaseEvidenceError(
            "release evidence output must not be a symlink, junction or reparse point"
        )
    if not stat.S_ISREG(info.st_mode):
        raise ReleaseEvidenceError("release evidence output must be a regular file")
    if int(getattr(info, "st_nlink", 1)) != 1:
        raise ReleaseEvidenceError("release evidence output must not be hardlinked")
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(getattr(info, "st_nlink", 1)),
        int(info.st_size),
        int(getattr(info, "st_mtime_ns", int(info.st_mtime * 1_000_000_000))),
        int(getattr(info, "st_ctime_ns", int(info.st_ctime * 1_000_000_000))),
    )


def _write_validated_atomic_json(
    output: Path,
    payload: dict,
    expected_output_identity: tuple[int, int, int, int, int, int] | None,
) -> None:
    """Durably stage validated bytes beside the target before one atomic replace."""
    raw = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _require_safe_release_evidence_directory_ancestry(output.parent)
    _require_safe_release_evidence_directory_ancestry(output.parent)
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{output.name}.",
            suffix=".tmp",
            dir=output.parent,
        )
    except OSError as error:
        raise ReleaseEvidenceError(
            f"cannot create exclusive release evidence staging file: {error}"
        ) from error

    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())

        try:
            staged_raw = temporary.read_bytes()
        except OSError as error:
            raise ReleaseEvidenceError(
                f"cannot re-read staged release evidence: {error}"
            ) from error
        if staged_raw != raw:
            raise ReleaseEvidenceError("staged release evidence bytes changed before commit")
        try:
            staged_payload = json.loads(staged_raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ReleaseEvidenceError(
                "staged release evidence is not valid UTF-8 JSON"
            ) from error
        validate_release_evidence(staged_payload)

        _require_safe_release_evidence_directory_ancestry(output.parent)
        if _release_evidence_output_identity(output) != expected_output_identity:
            raise ReleaseEvidenceError(
                "release evidence output changed while validated bytes were staged"
            )
        try:
            os.replace(temporary, output)
        except OSError as error:
            raise ReleaseEvidenceError(
                f"cannot atomically replace release evidence output: {error}"
            ) from error
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def write_release_evidence(
    report_path: str | Path,
    output_path: str | Path = RELEASE_EVIDENCE_PATH,
    *,
    confirm_manual_restore: bool,
) -> Path:
    report = _absolute_without_resolving(report_path)
    output = _absolute_without_resolving(output_path)
    if _paths_alias(report, output):
        raise ReleaseEvidenceError(
            "release evidence output must not overwrite or alias the raw recycle evidence report"
        )

    payload = build_release_evidence(
        report,
        confirm_manual_restore=confirm_manual_restore,
    )
    _require_safe_release_evidence_directory_ancestry(
        output.parent,
        allow_missing=True,
    )
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise ReleaseEvidenceError(
            f"cannot create release evidence output directory: {error}"
        ) from error
    _require_safe_release_evidence_directory_ancestry(output.parent)
    expected_output_identity = _release_evidence_output_identity(output)
    _write_validated_atomic_json(output, payload, expected_output_identity)
    return output.resolve()


def read_release_evidence(path: str | Path = RELEASE_EVIDENCE_PATH) -> dict:
    payload = _read_stable_release_evidence_payload(path)
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