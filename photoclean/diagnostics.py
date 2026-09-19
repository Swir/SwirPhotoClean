"""Read-only diagnostics plus a generated Recycle Bin verification workflow.

The verification helper never uses personal photos. It creates its own tiny PNG
pair, moves only the generated copy through the existing recycle-only path and
requires an explicit manual restore before evidence can be marked verified.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from .core import ScanResult

MANIFEST_NAME = "recycle-verification.json"
MANIFEST_VERSION = 2
SUPPORTED_MANIFEST_VERSIONS = {1, 2}
EVIDENCE_REPORT_VERSION = 1
ORIGINAL_NAME = "KEEP-ME.png"
COPY_NAME = "RECYCLE-ME.png"
VALID_STAGES = {"prepared", "recycled", "restored-verified"}
STAGE_ORDER = ("prepared", "recycled", "restored-verified")


class RecycleVerificationError(RuntimeError):
    """A generated verification fixture is invalid or cannot be verified."""


@dataclass(frozen=True)
class DiagnosticsSnapshot:
    platform: str
    python: str
    frozen: bool
    photo_count: int
    exact_group_count: int
    similar_group_count: int
    warning_count: int
    marked_count: int
    cancelled: bool


@dataclass(frozen=True)
class RecycleSupport:
    windows: bool
    dependencies: bool
    local_fixed_drive: bool | None
    ready: bool
    detail: str


@dataclass(frozen=True)
class RecycleVerification:
    folder: Path
    original: Path
    copy: Path
    manifest: Path
    digest: str
    stage: str
    session_id: str = ""
    manifest_version: int = MANIFEST_VERSION
    file_size: int = 0
    manifest_fingerprint: str = ""


@dataclass(frozen=True)
class RecycleEvidenceInspection:
    manifest_version: int
    session_id: str
    stage: str
    manifest_fingerprint: str
    event_count: int
    original_present: bool
    copy_present: bool
    original_matches: bool
    copy_matches: bool | None
    valid: bool
    problems: tuple[str, ...]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_payload_bytes(payload: dict) -> bytes:
    normalized = dict(payload)
    normalized.pop("manifest_fingerprint", None)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _payload_fingerprint(payload: dict) -> str:
    return hashlib.sha256(_canonical_payload_bytes(payload)).hexdigest()


def _parse_utc_timestamp(value, label: str) -> datetime:
    if not isinstance(value, str):
        raise RecycleVerificationError(f"Missing {label} timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise RecycleVerificationError(f"Invalid {label} timestamp") from error
    if parsed.tzinfo is None:
        raise RecycleVerificationError(f"{label} timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _is_link_or_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _atomic_write_json(path: Path, payload: dict) -> None:
    payload = dict(payload)
    if payload.get("version") == MANIFEST_VERSION:
        payload["manifest_fingerprint"] = _payload_fingerprint(payload)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def build_diagnostics_snapshot(result: ScanResult, marked_count: int = 0) -> DiagnosticsSnapshot:
    return DiagnosticsSnapshot(
        platform=f"{platform.system()} {platform.release()}".strip(),
        python=platform.python_version(),
        frozen=bool(getattr(sys, "frozen", False)),
        photo_count=len(result.photos),
        exact_group_count=sum(group.kind == "exact" for group in result.groups),
        similar_group_count=sum(group.kind == "similar" for group in result.groups),
        warning_count=len(result.warnings),
        marked_count=max(0, int(marked_count)),
        cancelled=bool(result.cancelled),
    )


def inspect_recycle_support(path: str | os.PathLike | None = None) -> RecycleSupport:
    """Preflight the prerequisites without moving or deleting any file."""
    if os.name != "nt":
        return RecycleSupport(False, False, None, False, "Windows required")

    try:
        import pythoncom  # noqa: F401
        from send2trash.win.IFileOperationProgressSink import FileOperationProgressSink  # noqa: F401
        from win32com.shell import shell  # noqa: F401
    except Exception as error:
        return RecycleSupport(True, False, None, False, f"Recycle dependencies unavailable: {error}")

    local_fixed = None
    if path is not None:
        import ctypes

        absolute = str(Path(path).absolute())
        volume = ctypes.create_unicode_buffer(32768)
        if not ctypes.windll.kernel32.GetVolumePathNameW(absolute, volume, len(volume)):
            return RecycleSupport(True, True, False, False, "Cannot resolve target volume")
        local_fixed = ctypes.windll.kernel32.GetDriveTypeW(volume.value) == 3
        if not local_fixed:
            return RecycleSupport(True, True, False, False, "Target must be on a local fixed drive")

    return RecycleSupport(True, True, local_fixed, True, "Recycle prerequisites available")


def _validate_common_payload(payload: dict) -> tuple[int, str, str]:
    version = payload.get("version")
    if version not in SUPPORTED_MANIFEST_VERSIONS:
        raise RecycleVerificationError("Unsupported recycle verification manifest version")
    stage = payload.get("stage")
    if stage not in VALID_STAGES:
        raise RecycleVerificationError("Invalid recycle verification stage")
    if payload.get("original_file") != ORIGINAL_NAME or payload.get("copy_file") != COPY_NAME:
        raise RecycleVerificationError("Unexpected recycle verification file names")
    digest = payload.get("digest_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise RecycleVerificationError("Invalid recycle verification digest")
    try:
        int(digest, 16)
    except ValueError as error:
        raise RecycleVerificationError("Invalid recycle verification digest") from error
    return version, stage, digest


def _validate_v2_payload(payload: dict, stage: str) -> tuple[str, int, str]:
    session_id = payload.get("session_id")
    try:
        parsed_session = uuid.UUID(str(session_id))
    except (ValueError, TypeError, AttributeError) as error:
        raise RecycleVerificationError("Invalid recycle verification session id") from error
    if parsed_session.version != 4:
        raise RecycleVerificationError("Recycle verification session id must be UUID4")

    file_size = payload.get("file_size")
    if not isinstance(file_size, int) or isinstance(file_size, bool) or file_size <= 0:
        raise RecycleVerificationError("Invalid recycle verification file size")

    events = payload.get("events")
    if not isinstance(events, list):
        raise RecycleVerificationError("Missing recycle verification event log")
    expected_stages = list(STAGE_ORDER[: STAGE_ORDER.index(stage) + 1])
    observed_stages = [event.get("stage") if isinstance(event, dict) else None for event in events]
    if observed_stages != expected_stages:
        raise RecycleVerificationError("Recycle verification event order does not match stage")

    previous_time = None
    for event in events:
        current_time = _parse_utc_timestamp(event.get("at_utc"), f"{event.get('stage')} event")
        if previous_time is not None and current_time < previous_time:
            raise RecycleVerificationError("Recycle verification event timestamps are out of order")
        previous_time = current_time

    fingerprint = payload.get("manifest_fingerprint")
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise RecycleVerificationError("Missing recycle verification manifest fingerprint")
    if fingerprint != _payload_fingerprint(payload):
        raise RecycleVerificationError("Recycle verification manifest fingerprint mismatch")

    return parsed_session.hex, file_size, fingerprint


def _legacy_to_v2_payload(payload: dict, check: RecycleVerification) -> dict:
    """Upgrade a v1 manifest in memory so a legacy verification can continue safely."""
    now = _utc_now()
    stage_index = STAGE_ORDER.index(check.stage)
    created = payload.get("created_at_utc")
    try:
        _parse_utc_timestamp(created, "created")
    except RecycleVerificationError:
        created = now
    events = []
    for index, stage in enumerate(STAGE_ORDER[: stage_index + 1]):
        timestamp = created if index == 0 else now
        events.append(
            {
                "stage": stage,
                "at_utc": timestamp,
                "legacy_import": True,
            }
        )
    file_size = 0
    if check.original.is_file() and not _is_link_or_reparse(check.original):
        file_size = check.original.stat().st_size
    elif check.copy.is_file() and not _is_link_or_reparse(check.copy):
        file_size = check.copy.stat().st_size
    if file_size <= 0:
        raise RecycleVerificationError("Cannot safely upgrade legacy manifest without generated file size")

    upgraded = dict(payload)
    upgraded.update(
        {
            "version": MANIFEST_VERSION,
            "session_id": uuid.uuid4().hex,
            "file_size": file_size,
            "events": events,
            "upgraded_from_version": 1,
        }
    )
    upgraded.pop("manifest_fingerprint", None)
    return upgraded


def load_recycle_verification(manifest: str | os.PathLike) -> RecycleVerification:
    raw_manifest_path = Path(manifest)
    if _is_link_or_reparse(raw_manifest_path):
        raise RecycleVerificationError("Recycle verification manifest cannot be a symlink or reparse point")
    manifest_path = raw_manifest_path.resolve()
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RecycleVerificationError(f"Cannot read recycle verification manifest: {error}") from error
    if not isinstance(payload, dict):
        raise RecycleVerificationError("Recycle verification manifest must contain an object")

    version, stage, digest = _validate_common_payload(payload)
    session_id = ""
    file_size = 0
    fingerprint = ""
    if version == MANIFEST_VERSION:
        session_id, file_size, fingerprint = _validate_v2_payload(payload, stage)

    folder = manifest_path.parent
    return RecycleVerification(
        folder=folder,
        original=folder / ORIGINAL_NAME,
        copy=folder / COPY_NAME,
        manifest=manifest_path,
        digest=digest,
        stage=stage,
        session_id=session_id,
        manifest_version=version,
        file_size=file_size,
        manifest_fingerprint=fingerprint,
    )


def _new_manifest_payload(check: RecycleVerification, created_at: str) -> dict:
    return {
        "version": MANIFEST_VERSION,
        "stage": check.stage,
        "session_id": check.session_id,
        "digest_sha256": check.digest,
        "file_size": check.file_size,
        "original_file": ORIGINAL_NAME,
        "copy_file": COPY_NAME,
        "created_at_utc": created_at,
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "frozen": bool(getattr(sys, "frozen", False)),
        },
        "events": [
            {
                "stage": "prepared",
                "at_utc": created_at,
                "original_present": True,
                "copy_present": True,
            }
        ],
    }


def _read_payload_for_transition(check: RecycleVerification) -> dict:
    loaded = load_recycle_verification(check.manifest)
    payload = json.loads(loaded.manifest.read_text(encoding="utf-8"))
    if loaded.manifest_version == 1:
        payload = _legacy_to_v2_payload(payload, loaded)
    return payload


def _transition_manifest(check: RecycleVerification, stage: str, **evidence) -> RecycleVerification:
    if stage not in VALID_STAGES:
        raise RecycleVerificationError("Invalid recycle verification transition")
    payload = _read_payload_for_transition(check)
    current = payload["stage"]
    current_index = STAGE_ORDER.index(current)
    target_index = STAGE_ORDER.index(stage)
    if target_index != current_index + 1:
        raise RecycleVerificationError("Invalid recycle verification stage transition")

    timestamp = _utc_now()
    payload["stage"] = stage
    payload["events"].append({"stage": stage, "at_utc": timestamp, **evidence})
    payload.update(evidence)
    if stage == "recycled":
        payload["recycled_at_utc"] = timestamp
    elif stage == "restored-verified":
        payload["verified_at_utc"] = timestamp
    _atomic_write_json(check.manifest, payload)
    return load_recycle_verification(check.manifest)


def create_recycle_verification(base_directory: str | os.PathLike) -> RecycleVerification:
    """Create two byte-identical generated PNGs and a tamper-evident local manifest."""
    base = Path(base_directory).resolve()
    if not base.is_dir():
        raise RecycleVerificationError("Choose an existing folder for the generated verification files")

    folder = Path(tempfile.mkdtemp(prefix="SwirPhotoClean-Recycle-Check-", dir=base))
    original = folder / ORIGINAL_NAME
    copy = folder / COPY_NAME
    manifest = folder / MANIFEST_NAME

    image = Image.new("RGB", (96, 64), "#1769aa")
    image.save(original, format="PNG")
    shutil.copy2(original, copy)
    digest = _sha256(original)
    if _sha256(copy) != digest:
        raise RecycleVerificationError("Generated verification copies are not identical")
    if os.path.samefile(original, copy):
        raise RecycleVerificationError("Generated verification files unexpectedly refer to the same file")

    created_at = _utc_now()
    check = RecycleVerification(
        folder,
        original,
        copy,
        manifest,
        digest,
        "prepared",
        session_id=uuid.uuid4().hex,
        manifest_version=MANIFEST_VERSION,
        file_size=original.stat().st_size,
    )
    _atomic_write_json(manifest, _new_manifest_payload(check, created_at))
    return load_recycle_verification(manifest)


def _require_expected_file(path: Path, digest: str, label: str, expected_size: int = 0) -> None:
    if not path.is_file():
        raise RecycleVerificationError(f"{label} is missing: {path}")
    if _is_link_or_reparse(path):
        raise RecycleVerificationError(f"{label} cannot be a symlink or reparse point: {path}")
    if expected_size and path.stat().st_size != expected_size:
        raise RecycleVerificationError(f"{label} size changed: {path}")
    if _sha256(path) != digest:
        raise RecycleVerificationError(f"{label} content changed: {path}")


def _require_distinct_files(original: Path, copy: Path) -> None:
    try:
        if os.path.samefile(original, copy):
            raise RecycleVerificationError("Generated original and copy must be distinct files")
    except OSError as error:
        raise RecycleVerificationError(f"Cannot compare generated verification files: {error}") from error


def move_generated_copy_to_recycle(check: RecycleVerification, recycler=None) -> RecycleVerification:
    """Move only RECYCLE-ME.png via the guarded recycle path; KEEP-ME.png must survive."""
    check = load_recycle_verification(check.manifest)
    if check.stage != "prepared":
        raise RecycleVerificationError("Recycle verification is not in the prepared stage")

    _require_expected_file(check.original, check.digest, "Original verification file", check.file_size)
    _require_expected_file(check.copy, check.digest, "Generated copy", check.file_size)
    _require_distinct_files(check.original, check.copy)

    if recycler is None:
        from .recycle import recycle_file

        recycler = recycle_file

    try:
        recycler(str(check.copy))
    except Exception as error:
        if not check.original.is_file():
            raise RecycleVerificationError("Original verification file disappeared during a failed recycle attempt") from error
        if check.copy.exists():
            _require_expected_file(check.copy, check.digest, "Generated copy", check.file_size)
        raise RecycleVerificationError(str(error)) from error

    _require_expected_file(check.original, check.digest, "Original verification file", check.file_size)
    if check.copy.exists():
        raise RecycleVerificationError("Recycle operation returned success but the generated copy still exists")

    return _transition_manifest(
        check,
        "recycled",
        source_absent_after_recycle=True,
        original_preserved=True,
    )


def verify_restored_copy(check: RecycleVerification) -> RecycleVerification:
    """Verify a user-restored generated copy and record local evidence."""
    check = load_recycle_verification(check.manifest)
    if check.stage != "recycled":
        raise RecycleVerificationError("Move the generated copy to the Recycle Bin before verifying restore")

    _require_expected_file(check.original, check.digest, "Original verification file", check.file_size)
    _require_expected_file(check.copy, check.digest, "Restored verification copy", check.file_size)
    _require_distinct_files(check.original, check.copy)

    return _transition_manifest(
        check,
        "restored-verified",
        original_preserved=True,
        restored_copy_matches_sha256=True,
        restored_copy_distinct=True,
    )


def _matches_expected_file(path: Path, digest: str, expected_size: int) -> tuple[bool, str | None]:
    if not path.exists():
        return False, "missing"
    if not path.is_file():
        return False, "not a regular file"
    if _is_link_or_reparse(path):
        return False, "symlink or reparse point"
    try:
        if expected_size and path.stat().st_size != expected_size:
            return False, "size mismatch"
        if _sha256(path) != digest:
            return False, "SHA-256 mismatch"
    except OSError as error:
        return False, str(error)
    return True, None


def inspect_recycle_evidence(check_or_manifest: RecycleVerification | str | os.PathLike) -> RecycleEvidenceInspection:
    """Validate the manifest fingerprint, stage log and generated-file state without mutating it."""
    manifest = (
        check_or_manifest.manifest
        if isinstance(check_or_manifest, RecycleVerification)
        else Path(check_or_manifest)
    )
    check = load_recycle_verification(manifest)
    payload = json.loads(check.manifest.read_text(encoding="utf-8"))
    events = payload.get("events") if isinstance(payload.get("events"), list) else []

    original_matches, original_problem = _matches_expected_file(
        check.original, check.digest, check.file_size
    )
    copy_matches = None
    copy_problem = None
    if check.copy.exists():
        copy_matches, copy_problem = _matches_expected_file(
            check.copy, check.digest, check.file_size
        )

    problems = []
    if not original_matches:
        problems.append(f"original: {original_problem or 'invalid'}")

    if check.stage == "prepared":
        if copy_matches is not True:
            problems.append(f"copy: {copy_problem or 'missing'}")
    elif check.stage == "recycled":
        if check.copy.exists():
            problems.append("copy: expected to be absent after recycle stage")
    elif check.stage == "restored-verified":
        if copy_matches is not True:
            problems.append(f"restored copy: {copy_problem or 'missing'}")

    if check.copy.exists() and check.original.exists():
        try:
            if os.path.samefile(check.original, check.copy):
                problems.append("original and copy refer to the same physical file")
        except OSError as error:
            problems.append(f"same-file check failed: {error}")

    return RecycleEvidenceInspection(
        manifest_version=check.manifest_version,
        session_id=check.session_id,
        stage=check.stage,
        manifest_fingerprint=check.manifest_fingerprint,
        event_count=len(events),
        original_present=check.original.exists(),
        copy_present=check.copy.exists(),
        original_matches=original_matches,
        copy_matches=copy_matches,
        valid=not problems,
        problems=tuple(problems),
    )


def export_recycle_evidence(
    check_or_manifest: RecycleVerification | str | os.PathLike,
    destination: str | os.PathLike,
) -> Path:
    """Export a read-only evidence report. This never closes the repository acceptance gate."""
    manifest = (
        check_or_manifest.manifest
        if isinstance(check_or_manifest, RecycleVerification)
        else Path(check_or_manifest)
    )
    check = load_recycle_verification(manifest)
    inspection = inspect_recycle_evidence(check)
    if not inspection.valid:
        raise RecycleVerificationError(
            "Recycle verification evidence is inconsistent: " + "; ".join(inspection.problems)
        )

    target = Path(destination).resolve()
    protected = {check.original.resolve(), check.copy.resolve(), check.manifest.resolve()}
    if target in protected:
        raise RecycleVerificationError("Evidence report cannot overwrite verification fixture files")

    payload = json.loads(check.manifest.read_text(encoding="utf-8"))
    report = {
        "report_version": EVIDENCE_REPORT_VERSION,
        "exported_at_utc": _utc_now(),
        "acceptance_gate_closed": False,
        "note": (
            "Local evidence only. Review the generated files and manifest before "
            "changing the SWIR PhotoClean 1.0 acceptance checklist."
        ),
        "inspection": asdict(inspection),
        "manifest": payload,
    }
    _atomic_write_json(target, report)
    return target
