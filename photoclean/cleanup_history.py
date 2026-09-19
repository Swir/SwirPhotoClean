"""Cleanup audit metadata for Recycle-Bin operations.

This module records paths, sizes, hashes and outcomes only. It never restores or
removes files. Space is counted as reclaimable only for completed byte-identical
duplicate moves with an unselected exact copy, and only after the Recycle Bin is
emptied.
"""
from __future__ import annotations

import json
import os
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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
        entries_raw = data.get("entries")
        errors_raw = data.get("errors")
        if not isinstance(entries_raw, list) or not isinstance(errors_raw, list):
            raise ValueError("cleanup history entry has invalid entries/errors")
        entries = []
        for raw in entries_raw:
            if not isinstance(raw, dict):
                raise ValueError("cleanup history file entry must be an object")
            status = raw.get("status")
            if status not in {"moved", "not_moved"}:
                raise ValueError("cleanup history file entry has invalid status")
            entries.append(CleanupEntry(path=str(raw["path"]), size=int(raw["size"]), digest=str(raw["digest"]), status=status, exact_survivor=bool(raw["exact_survivor"])))
        record = cls(
            record_id=str(data["record_id"]),
            started_at=str(data["started_at"]),
            finished_at=str(data["finished_at"]),
            scan_photo_count_before=int(data["scan_photo_count_before"]),
            scan_photo_count_after_snapshot=int(data["scan_photo_count_after_snapshot"]),
            scan_group_count=int(data["scan_group_count"]),
            requested_count=int(data["requested_count"]),
            completed_count=int(data["completed_count"]),
            requested_bytes=int(data["requested_bytes"]),
            moved_to_recycle_bytes=int(data["moved_to_recycle_bytes"]),
            guaranteed_reclaimable_after_bin_empty=int(data["guaranteed_reclaimable_after_bin_empty"]),
            entries=tuple(entries),
            errors=tuple(str(value) for value in errors_raw),
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
    if not path.exists():
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read cleanup history: {error}") from error
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA_VERSION:
        raise ValueError("unsupported cleanup history schema")
    sessions = payload.get("sessions")
    if not isinstance(sessions, list):
        raise ValueError("cleanup history sessions must be a list")
    return tuple(CleanupRecord.from_dict(item) for item in sessions)


def append_cleanup_record(path: Path, record: CleanupRecord, *, limit: int = DEFAULT_HISTORY_LIMIT) -> Path:
    if limit < 1:
        raise ValueError("cleanup history limit must be at least one")
    path = Path(path)
    existing = list(load_cleanup_history(path)) if path.exists() else []
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
