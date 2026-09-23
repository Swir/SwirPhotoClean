"""Cleanup audit metadata for Recycle-Bin operations.

This module records paths, sizes, hashes and outcomes only. It never restores or
removes files. Space is counted as reclaimable only for completed byte-identical
duplicate moves with an unselected exact copy, and only after the Recycle Bin is
emptied.
"""
from __future__ import annotations

import json
import os
import stat
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from . import i18n
from .core import ScanResult

SCHEMA_VERSION = 1
DEFAULT_HISTORY_LIMIT = 100
MAX_HISTORY_BYTES = 32 * 1024 * 1024
_REPARSE_POINT_ATTRIBUTE = 0x400
_HEX_DIGITS = frozenset("0123456789abcdef")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _require_plain_int(value, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"cleanup history {label} must be an integer")
    return value


def _require_plain_bool(value, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"cleanup history {label} must be a boolean")
    return value


def _require_text(value, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise ValueError(f"cleanup history {label} must be a string")
    return value


def _require_digest(value, label: str) -> str:
    digest = _require_text(value, label)
    if len(digest) != 64 or any(character not in _HEX_DIGITS for character in digest):
        raise ValueError(f"cleanup history {label} must be a lowercase SHA-256 digest")
    return digest


def _history_identity(info) -> tuple[int, int, int, int, int, int]:
    """Normalize metadata used to bind one history path to one opened file."""
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(getattr(info, "st_nlink", 1)),
        int(info.st_size),
        int(getattr(info, "st_mtime_ns", int(info.st_mtime * 1_000_000_000))),
        int(getattr(info, "st_ctime_ns", int(info.st_ctime * 1_000_000_000))),
    )


def _history_path_handle_match(path_identity, handle_identity) -> bool:
    """Compare path and open-handle identity without Windows CRT ctime noise."""
    if os.name != "nt":
        return path_identity == handle_identity
    path_inode = path_identity[1]
    handle_inode = handle_identity[1]
    if path_inode <= 0 or handle_inode <= 0 or path_inode != handle_inode:
        return False
    return path_identity[2:5] == handle_identity[2:5]


def _require_safe_history_entry(path: Path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        raise
    except OSError as error:
        raise ValueError(f"cannot inspect cleanup history: {error}") from error
    if stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE
    ):
        raise ValueError("cleanup history must not be a symlink, junction or reparse point")
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("cleanup history must be a regular file")
    if int(info.st_size) > MAX_HISTORY_BYTES:
        raise ValueError(
            f"cleanup history is too large: maximum is {MAX_HISTORY_BYTES} bytes"
        )
    return info


def _read_stable_history_payload(path: Path) -> object | None:
    """Read one bounded immutable snapshot of the persisted cleanup audit.

    History is presentation/audit metadata rather than a deletion authority, but a
    corrupt or externally replaced file must still not freeze the UI or display
    invented cleanup totals. Read through one verified regular-file handle, cap the
    payload size and revalidate the path afterwards. A missing file remains the
    normal empty-history state.
    """
    path = Path(path)
    try:
        before = _require_safe_history_entry(path)
    except FileNotFoundError:
        return None
    before_identity = _history_identity(before)

    try:
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode):
                raise ValueError("cleanup history changed to a non-regular file while opening")
            if bool(getattr(opened, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE):
                raise ValueError("cleanup history changed to a reparse point while opening")
            opened_identity = _history_identity(opened)
            if not _history_path_handle_match(before_identity, opened_identity):
                raise ValueError("cleanup history changed while it was being opened")
            raw = stream.read(MAX_HISTORY_BYTES + 1)
            if len(raw) > MAX_HISTORY_BYTES:
                raise ValueError(
                    f"cleanup history is too large: maximum is {MAX_HISTORY_BYTES} bytes"
                )
            after_read = os.fstat(stream.fileno())
            if _history_identity(after_read) != opened_identity:
                raise ValueError("cleanup history changed while it was being read")
    except ValueError:
        raise
    except OSError as error:
        raise ValueError(f"cannot read cleanup history: {error}") from error

    try:
        final = _require_safe_history_entry(path)
    except FileNotFoundError as error:
        raise ValueError("cleanup history path disappeared while it was being read") from error
    if _history_identity(final) != before_identity:
        raise ValueError("cleanup history path changed while it was being read")
    if len(raw) != int(before.st_size):
        raise ValueError("cleanup history size changed while it was being read")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read cleanup history: {error}") from error


@dataclass(frozen=True)
class CleanupCandidate:
    path: str
    size: int
    digest: str
    exact_survivor: bool


@dataclass(frozen=True)
class CleanupPlan:
    record_id: str
    started_at: str
    scan_photo_count: int
    scan_group_count: int
    candidates: tuple[CleanupCandidate, ...]

    @property
    def requested_count(self) -> int:
        return len(self.candidates)

    @property
    def requested_bytes(self) -> int:
        return sum(item.size for item in self.candidates)


@dataclass(frozen=True)
class CleanupEntry:
    path: str
    size: int
    digest: str
    status: str
    exact_survivor: bool


@dataclass(frozen=True)
class CleanupRecord:
    record_id: str
    started_at: str
    finished_at: str
    scan_photo_count_before: int
    scan_photo_count_after_snapshot: int
    scan_group_count: int
    requested_count: int
    completed_count: int
    requested_bytes: int
    moved_to_recycle_bytes: int
    guaranteed_reclaimable_after_bin_empty: int
    entries: tuple[CleanupEntry, ...]
    errors: tuple[str, ...]

    @property
    def fully_completed(self) -> bool:
        return self.completed_count == self.requested_count and not self.errors

    @property
    def moved_paths(self) -> tuple[str, ...]:
        return tuple(item.path for item in self.entries if item.status == "moved")

    def to_dict(self) -> dict:
        data = asdict(self)
        data["entries"] = [asdict(item) for item in self.entries]
        data["errors"] = list(self.errors)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "CleanupRecord":
        if not isinstance(data, dict):
            raise ValueError("cleanup history entry must be an object")
        expected_fields = {
            "record_id",
            "started_at",
            "finished_at",
            "scan_photo_count_before",
            "scan_photo_count_after_snapshot",
            "scan_group_count",
            "requested_count",
            "completed_count",
            "requested_bytes",
            "moved_to_recycle_bytes",
            "guaranteed_reclaimable_after_bin_empty",
            "entries",
            "errors",
        }
        if set(data) != expected_fields:
            raise ValueError("cleanup history entry has missing or unsupported fields")
        entries_raw = data.get("entries")
        errors_raw = data.get("errors")
        if not isinstance(entries_raw, list) or not isinstance(errors_raw, list):
            raise ValueError("cleanup history entry has invalid entries/errors")
        entries = []
        for raw in entries_raw:
            if not isinstance(raw, dict) or set(raw) != {
                "path", "size", "digest", "status", "exact_survivor"
            }:
                raise ValueError("cleanup history file entry has invalid fields")
            status = raw.get("status")
            if status not in {"moved", "not_moved"}:
                raise ValueError("cleanup history file entry has invalid status")
            size = _require_plain_int(raw.get("size"), "file size")
            if size < 0:
                raise ValueError("cleanup history file size must not be negative")
            entries.append(
                CleanupEntry(
                    path=_require_text(raw.get("path"), "file path"),
                    size=size,
                    digest=_require_digest(raw.get("digest"), "file digest"),
                    status=status,
                    exact_survivor=_require_plain_bool(
                        raw.get("exact_survivor"), "exact_survivor"
                    ),
                )
            )
        if not all(isinstance(value, str) for value in errors_raw):
            raise ValueError("cleanup history errors must contain strings")
        record = cls(
            record_id=_require_text(data.get("record_id"), "record_id"),
            started_at=_require_text(data.get("started_at"), "started_at"),
            finished_at=_require_text(data.get("finished_at"), "finished_at"),
            scan_photo_count_before=_require_plain_int(
                data.get("scan_photo_count_before"), "scan_photo_count_before"
            ),
            scan_photo_count_after_snapshot=_require_plain_int(
                data.get("scan_photo_count_after_snapshot"), "scan_photo_count_after_snapshot"
            ),
            scan_group_count=_require_plain_int(data.get("scan_group_count"), "scan_group_count"),
            requested_count=_require_plain_int(data.get("requested_count"), "requested_count"),
            completed_count=_require_plain_int(data.get("completed_count"), "completed_count"),
            requested_bytes=_require_plain_int(data.get("requested_bytes"), "requested_bytes"),
            moved_to_recycle_bytes=_require_plain_int(
                data.get("moved_to_recycle_bytes"), "moved_to_recycle_bytes"
            ),
            guaranteed_reclaimable_after_bin_empty=_require_plain_int(
                data.get("guaranteed_reclaimable_after_bin_empty"),
                "guaranteed_reclaimable_after_bin_empty",
            ),
            entries=tuple(entries),
            errors=tuple(errors_raw),
        )
        if record.requested_count != len(record.entries):
            raise ValueError("cleanup history requested count does not match entries")
        if record.completed_count != sum(item.status == "moved" for item in record.entries):
            raise ValueError("cleanup history completed count does not match entries")
        counters = (
            record.scan_photo_count_before,
            record.scan_photo_count_after_snapshot,
            record.scan_group_count,
            record.requested_count,
            record.completed_count,
            record.requested_bytes,
            record.moved_to_recycle_bytes,
            record.guaranteed_reclaimable_after_bin_empty,
        )
        if min(counters) < 0:
            raise ValueError("cleanup history contains a negative counter")
        expected_requested_bytes = sum(item.size for item in record.entries)
        expected_moved_bytes = sum(
            item.size for item in record.entries if item.status == "moved"
        )
        expected_reclaimable = sum(
            item.size
            for item in record.entries
            if item.status == "moved" and item.exact_survivor
        )
        expected_after = max(0, record.scan_photo_count_before - record.completed_count)
        if record.requested_bytes != expected_requested_bytes:
            raise ValueError("cleanup history requested bytes do not match entries")
        if record.moved_to_recycle_bytes != expected_moved_bytes:
            raise ValueError("cleanup history moved bytes do not match entries")
        if record.guaranteed_reclaimable_after_bin_empty != expected_reclaimable:
            raise ValueError("cleanup history reclaimable bytes do not match entries")
        if record.scan_photo_count_after_snapshot != expected_after:
            raise ValueError("cleanup history after-scan count does not match completed entries")
        return record


def history_path(settings_path=None) -> Path:
    settings = Path(settings_path) if settings_path is not None else i18n.settings_file()
    return settings.with_name("cleanup-history.json")


def build_cleanup_plan(result: ScanResult, selected: Iterable[Path], *, started_at: str | None = None, record_id: str | None = None) -> CleanupPlan:
    selected_paths = {Path(path) for path in selected}
    photos = {photo.path: photo for photo in result.photos}
    unknown = selected_paths - photos.keys()
    if unknown:
        raise ValueError(f"cleanup plan contains paths outside scan result: {sorted(map(str, unknown))}")

    exact_survivors: set[Path] = set()
    for group in result.groups:
        if group.kind != "exact":
            continue
        members = {photo.path for photo in group.photos}
        if members - selected_paths:
            exact_survivors.update(members & selected_paths)

    candidates = tuple(
        CleanupCandidate(path=str(path), size=photos[path].size, digest=photos[path].digest, exact_survivor=path in exact_survivors)
        for path in sorted(selected_paths, key=lambda value: str(value).casefold())
    )
    return CleanupPlan(
        record_id=record_id or uuid.uuid4().hex,
        started_at=started_at or _utc_now(),
        scan_photo_count=len(result.photos),
        scan_group_count=len(result.groups),
        candidates=candidates,
    )


def finalize_cleanup_record(plan: CleanupPlan, completed: Iterable[Path], errors: Iterable[str], *, finished_at: str | None = None) -> CleanupRecord:
    completed_paths = {str(Path(path)) for path in completed}
    planned_paths = {item.path for item in plan.candidates}
    unknown = completed_paths - planned_paths
    if unknown:
        raise ValueError(f"completed cleanup contains unplanned paths: {sorted(unknown)}")

    entries = tuple(
        CleanupEntry(path=item.path, size=item.size, digest=item.digest, status="moved" if item.path in completed_paths else "not_moved", exact_survivor=item.exact_survivor)
        for item in plan.candidates
    )
    moved = tuple(item for item in entries if item.status == "moved")
    return CleanupRecord(
        record_id=plan.record_id,
        started_at=plan.started_at,
        finished_at=finished_at or _utc_now(),
        scan_photo_count_before=plan.scan_photo_count,
        scan_photo_count_after_snapshot=max(0, plan.scan_photo_count - len(moved)),
        scan_group_count=plan.scan_group_count,
        requested_count=plan.requested_count,
        completed_count=len(moved),
        requested_bytes=plan.requested_bytes,
        moved_to_recycle_bytes=sum(item.size for item in moved),
        guaranteed_reclaimable_after_bin_empty=sum(item.size for item in moved if item.exact_survivor),
        entries=entries,
        errors=tuple(str(error) for error in errors),
    )


def load_cleanup_history(path: Path) -> tuple[CleanupRecord, ...]:
    path = Path(path)
    payload = _read_stable_history_payload(path)
    if payload is None:
        return ()
    if not isinstance(payload, dict) or set(payload) != {"schema", "sessions"}:
        raise ValueError("cleanup history root has invalid fields")
    if payload.get("schema") != SCHEMA_VERSION:
        raise ValueError("unsupported cleanup history schema")
    sessions = payload.get("sessions")
    if not isinstance(sessions, list):
        raise ValueError("cleanup history sessions must be a list")
    if len(sessions) > DEFAULT_HISTORY_LIMIT:
        raise ValueError(
            f"cleanup history contains too many sessions: maximum is {DEFAULT_HISTORY_LIMIT}"
        )
    return tuple(CleanupRecord.from_dict(item) for item in sessions)


def append_cleanup_record(path: Path, record: CleanupRecord, *, limit: int = DEFAULT_HISTORY_LIMIT) -> Path:
    if limit < 1 or limit > DEFAULT_HISTORY_LIMIT:
        raise ValueError(
            f"cleanup history limit must be between 1 and {DEFAULT_HISTORY_LIMIT}"
        )
    path = Path(path)
    existing = list(load_cleanup_history(path))
    existing.append(record)
    sessions = existing[-limit:]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as stream:
            temporary = Path(stream.name)
            json.dump({"schema": SCHEMA_VERSION, "sessions": [item.to_dict() for item in sessions]}, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path