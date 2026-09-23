"""Versioned, non-destructive scan-session persistence.

Saved sessions contain scan metadata only. They never restore Recycle Bin marks,
never perform file operations, and every later recycle action still goes through
the normal full revalidation in :mod:`photoclean.core`.
"""
from __future__ import annotations

import json
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .core import MAX_PIXELS, Group, Photo, ScanResult, linked, signature

FORMAT = "swir-photoclean-session"
VERSION = 1
MAX_SESSION_BYTES = 64 * 1024 * 1024
MAX_PHOTOS = 250_000
MAX_GROUPS = 250_000
MAX_WARNINGS = 20_000
_REPARSE_POINT_ATTRIBUTE = 0x400

SessionTargetIdentity = tuple[int, int, int, int, int, int]


class SessionError(ValueError):
    """Raised when a session file is malformed, unsupported, or unsafe to load."""


@dataclass(frozen=True)
class SessionSnapshot:
    roots: tuple[Path, ...]
    threshold: int
    include_similar: bool
    result: ScanResult


@dataclass(frozen=True)
class SessionAudit:
    """Read-only resume preflight against the files currently on disk.

    The audit intentionally checks only filesystem identity/metadata. It is a fast
    stale-session filter, not deletion evidence. Any later Recycle Bin action still
    performs the normal full content revalidation before a file can move.
    """

    snapshot: SessionSnapshot
    checked_count: int
    valid_count: int
    missing_count: int
    changed_count: int
    unavailable_count: int
    unsafe_link_count: int
    duplicate_identity_count: int
    dropped_group_count: int

    @property
    def stale_count(self) -> int:
        return self.checked_count - self.valid_count


def _require_int(value, name, *, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise SessionError(f"{name} must be an integer")
    if minimum is not None and value < minimum:
        raise SessionError(f"{name} is below the supported range")
    if maximum is not None and value > maximum:
        raise SessionError(f"{name} exceeds the supported range")
    return value


def _require_text(value, name, *, max_length=32_768):
    if not isinstance(value, str):
        raise SessionError(f"{name} must be text")
    if len(value) > max_length:
        raise SessionError(f"{name} is too long")
    return value


def _photo_to_json(photo: Photo):
    return {
        "path": str(photo.path),
        "size": photo.size,
        "modified_ns": photo.modified_ns,
        "device": photo.device,
        "inode": photo.inode,
        "digest": photo.digest,
        "width": photo.width,
        "height": photo.height,
        "dhash": photo.dhash,
        "color": photo.color.hex(),
    }


def _photo_from_json(raw):
    if not isinstance(raw, dict):
        raise SessionError("photo entry must be an object")
    path = Path(_require_text(raw.get("path"), "photo.path"))
    size = _require_int(raw.get("size"), "photo.size", minimum=0)
    modified_ns = _require_int(raw.get("modified_ns"), "photo.modified_ns", minimum=0)
    device = _require_int(raw.get("device"), "photo.device", minimum=0)
    inode = _require_int(raw.get("inode"), "photo.inode", minimum=0)
    digest = _require_text(raw.get("digest"), "photo.digest", max_length=64)
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest.lower()):
        raise SessionError("photo.digest must be a SHA-256 hex digest")
    width = _require_int(raw.get("width"), "photo.width", minimum=1)
    height = _require_int(raw.get("height"), "photo.height", minimum=1)
    if width * height > MAX_PIXELS:
        raise SessionError("photo dimensions exceed the application pixel limit")
    dhash = _require_int(raw.get("dhash"), "photo.dhash", minimum=0, maximum=(1 << 64) - 1)
    color_hex = _require_text(raw.get("color"), "photo.color", max_length=384)
    if len(color_hex) != 384:
        raise SessionError("photo.color has an invalid length")
    try:
        color = bytes.fromhex(color_hex)
    except ValueError as error:
        raise SessionError("photo.color is not valid hexadecimal data") from error
    if len(color) != 192:
        raise SessionError("photo.color has an invalid decoded length")
    return Photo(path, size, modified_ns, device, inode, digest.lower(), width, height, dhash, color)


def snapshot_to_dict(snapshot: SessionSnapshot):
    if snapshot.result.cancelled:
        raise SessionError("cancelled scans cannot be saved as resumable sessions")
    photos = list(snapshot.result.photos)
    if len(photos) > MAX_PHOTOS:
        raise SessionError("too many photos for a session snapshot")
    if len(snapshot.result.groups) > MAX_GROUPS:
        raise SessionError("too many groups for a session snapshot")
    if len(snapshot.result.warnings) > MAX_WARNINGS:
        raise SessionError("too many warnings for a session snapshot")

    by_path = {photo.path: index for index, photo in enumerate(photos)}
    if len(by_path) != len(photos):
        raise SessionError("scan result contains duplicate photo paths")

    groups = []
    for group in snapshot.result.groups:
        if group.kind not in ("exact", "similar"):
            raise SessionError("unsupported group kind")
        try:
            members = [by_path[photo.path] for photo in group.photos]
        except KeyError as error:
            raise SessionError("group references a photo outside the scan result") from error
        if len(members) < 2 or len(set(members)) != len(members):
            raise SessionError("group must contain at least two distinct photos")
        groups.append({"kind": group.kind, "members": members})

    return {
        "format": FORMAT,
        "version": VERSION,
        "roots": [str(Path(root)) for root in snapshot.roots],
        "threshold": snapshot.threshold,
        "include_similar": snapshot.include_similar,
        "photos": [_photo_to_json(photo) for photo in photos],
        "groups": groups,
        "warnings": list(snapshot.result.warnings),
    }


def snapshot_from_dict(raw):
    if not isinstance(raw, dict):
        raise SessionError("session root must be an object")
    if raw.get("format") != FORMAT:
        raise SessionError("not a SWIR PhotoClean session")
    if raw.get("version") != VERSION:
        raise SessionError("unsupported session version")

    roots_raw = raw.get("roots")
    if not isinstance(roots_raw, list) or len(roots_raw) > 1024:
        raise SessionError("invalid roots list")
    roots = tuple(Path(_require_text(item, "root")) for item in roots_raw)
    threshold = _require_int(raw.get("threshold"), "threshold", minimum=0, maximum=16)
    include_similar = raw.get("include_similar")
    if not isinstance(include_similar, bool):
        raise SessionError("include_similar must be boolean")

    photos_raw = raw.get("photos")
    groups_raw = raw.get("groups")
    warnings_raw = raw.get("warnings")
    if not isinstance(photos_raw, list) or len(photos_raw) > MAX_PHOTOS:
        raise SessionError("invalid photo list")
    if not isinstance(groups_raw, list) or len(groups_raw) > MAX_GROUPS:
        raise SessionError("invalid group list")
    if not isinstance(warnings_raw, list) or len(warnings_raw) > MAX_WARNINGS:
        raise SessionError("invalid warnings list")

    photos = [_photo_from_json(item) for item in photos_raw]
    if len({photo.path for photo in photos}) != len(photos):
        raise SessionError("session contains duplicate photo paths")

    groups = []
    for raw_group in groups_raw:
        if not isinstance(raw_group, dict) or raw_group.get("kind") not in ("exact", "similar"):
            raise SessionError("invalid group entry")
        members = raw_group.get("members")
        if not isinstance(members, list) or len(members) < 2:
            raise SessionError("group must contain at least two members")
        indices = [_require_int(index, "group member", minimum=0) for index in members]
        if len(set(indices)) != len(indices) or any(index >= len(photos) for index in indices):
            raise SessionError("group contains an invalid photo reference")
        group_photos = tuple(photos[index] for index in indices)
        if raw_group["kind"] == "exact" and len({photo.digest for photo in group_photos}) != 1:
            raise SessionError("exact group contains different file digests")
        groups.append(Group(raw_group["kind"], group_photos))

    warnings = [_require_text(item, "warning", max_length=65_536) for item in warnings_raw]
    result = ScanResult(photos=photos, groups=groups, warnings=warnings, cancelled=False)
    return SessionSnapshot(roots=roots, threshold=threshold, include_similar=include_similar, result=result)


def audit_session_snapshot(snapshot: SessionSnapshot, *, detail_limit: int = 20) -> SessionAudit:
    """Drop stale session members before review without touching any source file.

    A resumed session can outlive the files it describes. This preflight compares
    each saved member with its current filesystem signature and rejects missing,
    changed, unavailable or linked/reparse entries. It also restores the scanner's
    invariant that one physical file identity can appear only once, so a stale or
    hand-edited session cannot present hardlink aliases as independent copies.
    Groups are rebuilt only from surviving members and groups with fewer than two
    members are dropped.

    This is deliberately *not* a content-hash safety check. It keeps resume fast
    for large libraries; cleanup still performs the normal full hash/content
    revalidation immediately before any Recycle Bin operation.
    """

    _require_int(detail_limit, "detail_limit", minimum=0, maximum=1000)
    valid: list[Photo] = []
    invalid_paths: set[Path] = set()
    seen_file_identities: set[tuple[int, int]] = set()
    detail_lines: list[str] = []
    missing_count = 0
    changed_count = 0
    unavailable_count = 0
    unsafe_link_count = 0
    duplicate_identity_count = 0

    def reject(photo: Photo, reason: str):
        invalid_paths.add(photo.path)
        if len(detail_lines) < detail_limit:
            detail_lines.append(f"Session resume skipped {photo.path}: {reason}")

    for photo in snapshot.result.photos:
        try:
            if linked(photo.path):
                unsafe_link_count += 1
                reject(photo, "link/reparse point")
                continue
            current = photo.path.stat()
        except FileNotFoundError:
            missing_count += 1
            reject(photo, "file is missing")
            continue
        except OSError as error:
            unavailable_count += 1
            reject(photo, f"file is unavailable ({error})")
            continue

        expected = (photo.size, photo.modified_ns, photo.device, photo.inode)
        if signature(current) != expected:
            changed_count += 1
            reject(photo, "filesystem signature changed since the saved scan")
            continue

        current_inode = int(current.st_ino)
        identity = (int(current.st_dev), current_inode)
        if current_inode and identity in seen_file_identities:
            duplicate_identity_count += 1
            reject(photo, "same physical file is already present in the resumed session")
            continue
        if current_inode:
            seen_file_identities.add(identity)
        valid.append(photo)

    valid_paths = {photo.path for photo in valid}
    groups: list[Group] = []
    dropped_group_count = 0
    for group in snapshot.result.groups:
        members = tuple(photo for photo in group.photos if photo.path in valid_paths)
        if len(members) >= 2:
            groups.append(Group(group.kind, members))
        else:
            dropped_group_count += 1

    warnings = list(snapshot.result.warnings)
    stale_count = len(snapshot.result.photos) - len(valid)
    audit_warnings: list[str] = []
    if stale_count:
        audit_warnings.append(
            "Session resume preflight: "
            f"kept {len(valid)}/{len(snapshot.result.photos)} photos; "
            f"missing={missing_count}, changed={changed_count}, "
            f"unavailable={unavailable_count}, link/reparse={unsafe_link_count}, "
            f"duplicate-identity={duplicate_identity_count}; "
            f"dropped groups={dropped_group_count}."
        )
        audit_warnings.extend(detail_lines)
        omitted = stale_count - len(detail_lines)
        if omitted > 0:
            audit_warnings.append(f"Session resume skipped {omitted} additional stale entries.")

    available_warning_slots = max(0, MAX_WARNINGS - len(warnings))
    warnings.extend(audit_warnings[:available_warning_slots])
    result = ScanResult(photos=valid, groups=groups, warnings=warnings, cancelled=False)
    sanitized = SessionSnapshot(
        roots=snapshot.roots,
        threshold=snapshot.threshold,
        include_similar=snapshot.include_similar,
        result=result,
    )
    return SessionAudit(
        snapshot=sanitized,
        checked_count=len(snapshot.result.photos),
        valid_count=len(valid),
        missing_count=missing_count,
        changed_count=changed_count,
        unavailable_count=unavailable_count,
        unsafe_link_count=unsafe_link_count,
        duplicate_identity_count=duplicate_identity_count,
        dropped_group_count=dropped_group_count,
    )


def _absolute_without_resolving(path) -> Path:
    """Return an absolute destination path while preserving its final entry."""
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def _normalized_absolute(path: Path) -> str:
    """Normalize a path lexically without following its final filesystem entry."""
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _safe_session_target_identity(path: Path) -> SessionTargetIdentity | None:
    """Snapshot an existing save target or reject unsafe filesystem objects."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise SessionError(f"cannot safely inspect session destination {path}: {error}") from error

    if stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE
    ):
        raise SessionError(
            "session destination must not be a symlink, junction or reparse point"
        )
    if not stat.S_ISREG(info.st_mode):
        raise SessionError("session destination must be a regular file")
    if int(getattr(info, "st_nlink", 1)) != 1:
        raise SessionError("session destination must not be hardlinked")

    return (
        int(info.st_dev),
        int(info.st_ino),
        int(getattr(info, "st_nlink", 1)),
        int(info.st_size),
        int(getattr(info, "st_mtime_ns", int(info.st_mtime * 1_000_000_000))),
        int(getattr(info, "st_ctime_ns", int(info.st_ctime * 1_000_000_000))),
    )


def _ensure_session_target_not_photo(
    snapshot: SessionSnapshot,
    target: Path,
    target_identity: SessionTargetIdentity | None,
) -> None:
    """Never let session persistence replace a photo represented by the snapshot.

    This check intentionally uses the already-read target identity plus stored scan
    identities, rather than calling ``samefile`` for every photo. Large sessions can
    therefore validate a new destination without thousands of filesystem probes.
    """
    target_path = _normalized_absolute(target)
    target_file_id = None
    if target_identity is not None and target_identity[1]:
        target_file_id = (target_identity[0], target_identity[1])

    for photo in snapshot.result.photos:
        if _normalized_absolute(photo.path) == target_path:
            raise SessionError("session destination cannot overwrite or alias a scanned photo")
        if (
            target_file_id is not None
            and photo.inode
            and (photo.device, photo.inode) == target_file_id
        ):
            raise SessionError("session destination cannot overwrite or alias a scanned photo")


def save_session(snapshot: SessionSnapshot, destination):
    """Safely persist a scan snapshot without replacing any scanned photo."""

    destination = _absolute_without_resolving(destination)
    payload = json.dumps(snapshot_to_dict(snapshot), ensure_ascii=False, separators=(",", ":"))
    encoded = payload.encode("utf-8")
    if len(encoded) > MAX_SESSION_BYTES:
        raise SessionError("session snapshot exceeds the supported size")
    destination.parent.mkdir(parents=True, exist_ok=True)

    expected_identity = _safe_session_target_identity(destination)
    _ensure_session_target_not_photo(snapshot, destination, expected_identity)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=destination.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())

        # A path swapped while bytes are being prepared must fail closed. If the
        # target changes into a source photo, its filesystem identity changes too.
        if _safe_session_target_identity(destination) != expected_identity:
            raise SessionError("session destination changed while validated bytes were staged")
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _read_session_bytes(source: Path) -> bytes:
    """Read at most the configured session limit from one open file handle.

    A separate ``stat`` followed by ``read_text`` leaves a race where a session can
    grow or be replaced between the size check and the actual read. Bounded reads
    keep the memory limit authoritative even when the file changes concurrently.
    """

    try:
        with source.open("rb") as stream:
            encoded = stream.read(MAX_SESSION_BYTES + 1)
            if len(encoded) > MAX_SESSION_BYTES:
                raise SessionError("session file exceeds the supported size")
            # A regular file normally satisfies the sized read in one call. Keep a
            # second one-byte probe so unusual streams/filesystems cannot hide data
            # behind a short read and bypass the configured upper bound.
            if stream.read(1):
                raise SessionError("session file exceeds the supported size")
            return encoded
    except SessionError:
        raise
    except OSError as error:
        raise SessionError(f"cannot read session: {error}") from error


def load_session(source):
    """Load and strictly validate a bounded snapshot without touching referenced photos."""

    source = Path(source)
    encoded = _read_session_bytes(source)
    try:
        raw = json.loads(encoded.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise SessionError(f"invalid session file: {error}") from error
    return snapshot_from_dict(raw)