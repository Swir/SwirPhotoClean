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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from .core import ScanResult

MANIFEST_NAME = "recycle-verification.json"
MANIFEST_VERSION = 1
ORIGINAL_NAME = "KEEP-ME.png"
COPY_NAME = "RECYCLE-ME.png"
VALID_STAGES = {"prepared", "recycled", "restored-verified"}


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


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


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


def _manifest_payload(check: RecycleVerification, **extra) -> dict:
    payload = {
        "version": MANIFEST_VERSION,
        "stage": check.stage,
        "digest_sha256": check.digest,
        "original_file": ORIGINAL_NAME,
        "copy_file": COPY_NAME,
    }
    payload.update(extra)
    return payload


def _write_manifest(check: RecycleVerification, **extra) -> None:
    payload = _manifest_payload(check, **extra)
    temporary = check.manifest.with_suffix(check.manifest.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(check.manifest)


def load_recycle_verification(manifest: str | os.PathLike) -> RecycleVerification:
    manifest_path = Path(manifest).resolve()
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RecycleVerificationError(f"Cannot read recycle verification manifest: {error}") from error

    if payload.get("version") != MANIFEST_VERSION:
        raise RecycleVerificationError("Unsupported recycle verification manifest version")
    stage = payload.get("stage")
    if stage not in VALID_STAGES:
        raise RecycleVerificationError("Invalid recycle verification stage")
    if payload.get("original_file") != ORIGINAL_NAME or payload.get("copy_file") != COPY_NAME:
        raise RecycleVerificationError("Unexpected recycle verification file names")
    digest = payload.get("digest_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise RecycleVerificationError("Invalid recycle verification digest")

    folder = manifest_path.parent
    return RecycleVerification(
        folder=folder,
        original=folder / ORIGINAL_NAME,
        copy=folder / COPY_NAME,
        manifest=manifest_path,
        digest=digest,
        stage=stage,
    )


def create_recycle_verification(base_directory: str | os.PathLike) -> RecycleVerification:
    """Create two byte-identical generated PNGs and a local evidence manifest."""
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

    check = RecycleVerification(folder, original, copy, manifest, digest, "prepared")
    _write_manifest(check, created_at_utc=_utc_now())
    return check


def _require_expected_file(path: Path, digest: str, label: str) -> None:
    if not path.is_file():
        raise RecycleVerificationError(f"{label} is missing: {path}")
    if _sha256(path) != digest:
        raise RecycleVerificationError(f"{label} content changed: {path}")


def move_generated_copy_to_recycle(check: RecycleVerification, recycler=None) -> RecycleVerification:
    """Move only RECYCLE-ME.png via the guarded recycle path; KEEP-ME.png must survive."""
    check = load_recycle_verification(check.manifest)
    if check.stage != "prepared":
        raise RecycleVerificationError("Recycle verification is not in the prepared stage")

    _require_expected_file(check.original, check.digest, "Original verification file")
    _require_expected_file(check.copy, check.digest, "Generated copy")

    if recycler is None:
        from .recycle import recycle_file

        recycler = recycle_file

    try:
        recycler(str(check.copy))
    except Exception as error:
        if not check.original.is_file():
            raise RecycleVerificationError("Original verification file disappeared during a failed recycle attempt") from error
        if check.copy.exists():
            _require_expected_file(check.copy, check.digest, "Generated copy")
        raise RecycleVerificationError(str(error)) from error

    _require_expected_file(check.original, check.digest, "Original verification file")
    if check.copy.exists():
        raise RecycleVerificationError("Recycle operation returned success but the generated copy still exists")

    recycled = RecycleVerification(check.folder, check.original, check.copy, check.manifest, check.digest, "recycled")
    previous = json.loads(check.manifest.read_text(encoding="utf-8"))
    _write_manifest(
        recycled,
        created_at_utc=previous.get("created_at_utc"),
        recycled_at_utc=_utc_now(),
        original_preserved=True,
    )
    return recycled


def verify_restored_copy(check: RecycleVerification) -> RecycleVerification:
    """Verify a user-restored generated copy and record local evidence."""
    check = load_recycle_verification(check.manifest)
    if check.stage != "recycled":
        raise RecycleVerificationError("Move the generated copy to the Recycle Bin before verifying restore")

    _require_expected_file(check.original, check.digest, "Original verification file")
    _require_expected_file(check.copy, check.digest, "Restored verification copy")

    verified = RecycleVerification(check.folder, check.original, check.copy, check.manifest, check.digest, "restored-verified")
    previous = json.loads(check.manifest.read_text(encoding="utf-8"))
    _write_manifest(
        verified,
        created_at_utc=previous.get("created_at_utc"),
        recycled_at_utc=previous.get("recycled_at_utc"),
        verified_at_utc=_utc_now(),
        original_preserved=True,
        restored_copy_matches_sha256=True,
    )
    return verified
