"""Read-only disk-space insights built only from completed scan metadata.

The analysis never marks, moves, renames or deletes files. Reclaimable space is
reported only for byte-identical SHA-256 duplicate groups while visually similar
photos remain review-only.
"""
from __future__ import annotations

import heapq
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .core import Photo, ScanResult


@dataclass(frozen=True)
class SpaceFile:
    """One large file together with conservative duplicate context."""

    photo: Photo
    status: str
    exact_group_size: int = 0
    exact_group_reclaimable_bytes: int = 0


@dataclass(frozen=True)
class SpaceFolder:
    """Aggregate size of scanned photos in one immediate parent folder."""

    path: Path
    total_bytes: int
    photo_count: int


@dataclass(frozen=True)
class SpaceReport:
    """Conservative disk-space report for a completed scan."""

    photo_count: int
    total_bytes: int
    exact_duplicate_files: int
    exact_reclaimable_bytes: int
    largest_files: tuple[SpaceFile, ...]
    largest_folders: tuple[SpaceFolder, ...]


def build_space_report(
    result: ScanResult,
    *,
    file_limit: int = 100,
    folder_limit: int = 30,
) -> SpaceReport:
    """Build a bounded read-only report without touching the filesystem.

    Only exact SHA-256 groups contribute to ``exact_reclaimable_bytes``. One
    member of every exact group is always preserved in the estimate. Similar
    groups merely label files as review candidates and never increase the
    reclaimable-space figure.
    """

    if file_limit < 0:
        raise ValueError("file_limit must be non-negative")
    if folder_limit < 0:
        raise ValueError("folder_limit must be non-negative")

    exact_context: dict[Path, tuple[int, int]] = {}
    similar_paths: set[Path] = set()
    exact_duplicate_files = 0
    exact_reclaimable_bytes = 0

    for group in result.groups:
        photos = tuple(group.photos)
        if not photos:
            continue
        if group.kind == "exact":
            group_size = len(photos)
            reclaimable = max(0, sum(photo.size for photo in photos) - max(photo.size for photo in photos))
            exact_duplicate_files += max(0, group_size - 1)
            exact_reclaimable_bytes += reclaimable
            for photo in photos:
                exact_context[photo.path] = (group_size, reclaimable)
        elif group.kind == "similar":
            similar_paths.update(photo.path for photo in photos)

    folder_bytes: dict[Path, int] = defaultdict(int)
    folder_counts: dict[Path, int] = defaultdict(int)
    total_bytes = 0
    for photo in result.photos:
        total_bytes += max(0, photo.size)
        parent = photo.path.parent
        folder_bytes[parent] += max(0, photo.size)
        folder_counts[parent] += 1

    def file_key(photo: Photo):
        return photo.size, str(photo.path).casefold()

    top_photos = heapq.nlargest(file_limit, result.photos, key=file_key) if file_limit else []
    largest_files = []
    for photo in top_photos:
        context = exact_context.get(photo.path)
        if context is not None:
            status = "exact"
            group_size, reclaimable = context
        elif photo.path in similar_paths:
            status = "similar"
            group_size, reclaimable = 0, 0
        else:
            status = "other"
            group_size, reclaimable = 0, 0
        largest_files.append(
            SpaceFile(
                photo=photo,
                status=status,
                exact_group_size=group_size,
                exact_group_reclaimable_bytes=reclaimable,
            )
        )

    top_folders = heapq.nlargest(
        folder_limit,
        folder_bytes,
        key=lambda path: (folder_bytes[path], str(path).casefold()),
    ) if folder_limit else []
    largest_folders = tuple(
        SpaceFolder(path=path, total_bytes=folder_bytes[path], photo_count=folder_counts[path])
        for path in top_folders
    )

    return SpaceReport(
        photo_count=len(result.photos),
        total_bytes=total_bytes,
        exact_duplicate_files=exact_duplicate_files,
        exact_reclaimable_bytes=exact_reclaimable_bytes,
        largest_files=tuple(largest_files),
        largest_folders=largest_folders,
    )
