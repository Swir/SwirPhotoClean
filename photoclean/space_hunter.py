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
    member of every exact digest is always preserved in the estimate. Similar
    groups merely label files as review candidates and never increase the
    reclaimable-space figure.

    Repeated/overlapping exact-group records are collapsed by verified SHA-256
    digest before savings are counted, and duplicate context is retained only for
    rows that can actually appear in the bounded largest-files table.
    """

    if file_limit < 0:
        raise ValueError("file_limit must be non-negative")
    if folder_limit < 0:
        raise ValueError("folder_limit must be non-negative")

    folder_bytes: dict[Path, int] = defaultdict(int)
    folder_counts: dict[Path, int] = defaultdict(int)
    total_bytes = 0
    for photo in result.photos:
        safe_size = max(0, photo.size)
        total_bytes += safe_size
        parent = photo.path.parent
        folder_bytes[parent] += safe_size
        folder_counts[parent] += 1

    def file_key(photo: Photo):
        return photo.size, str(photo.path).casefold()

    top_photos = heapq.nlargest(file_limit, result.photos, key=file_key) if file_limit else []
    top_paths = {photo.path for photo in top_photos}
    scanned_by_path = {photo.path: photo for photo in result.photos}

    # Exact-group evidence may be repeated or overlapping in resumed/adapted
    # ScanResults. Trust only members that match authoritative scan metadata, then
    # reduce to the SHA-256 digests for which at least two distinct scanned paths
    # were actually presented as exact duplicates.
    exact_digests: set[str] = set()
    similar_top_paths: set[Path] = set()
    for group in result.groups:
        if group.kind == "exact":
            paths_by_digest: dict[str, set[Path]] = defaultdict(set)
            for member in group.photos:
                photo = scanned_by_path.get(member.path)
                if photo is None or photo.digest != member.digest:
                    continue
                paths_by_digest[photo.digest].add(photo.path)
            exact_digests.update(
                digest
                for digest, paths in paths_by_digest.items()
                if len(paths) >= 2
            )
        elif group.kind == "similar":
            valid_paths = {
                member.path
                for member in group.photos
                if member.path in scanned_by_path
            }
            if len(valid_paths) >= 2:
                similar_top_paths.update(valid_paths & top_paths)

    exact_counts: dict[str, int] = defaultdict(int)
    exact_totals: dict[str, int] = defaultdict(int)
    exact_max_sizes: dict[str, int] = defaultdict(int)
    seen_exact_paths: set[Path] = set()
    for photo in result.photos:
        if photo.digest not in exact_digests or photo.path in seen_exact_paths:
            continue
        seen_exact_paths.add(photo.path)
        safe_size = max(0, photo.size)
        exact_counts[photo.digest] += 1
        exact_totals[photo.digest] += safe_size
        exact_max_sizes[photo.digest] = max(exact_max_sizes[photo.digest], safe_size)

    exact_stats: dict[str, tuple[int, int]] = {}
    exact_duplicate_files = 0
    exact_reclaimable_bytes = 0
    for digest, count in exact_counts.items():
        if count < 2:
            continue
        reclaimable = max(0, exact_totals[digest] - exact_max_sizes[digest])
        exact_stats[digest] = (count, reclaimable)
        exact_duplicate_files += count - 1
        exact_reclaimable_bytes += reclaimable

    largest_files = []
    for photo in top_photos:
        context = exact_stats.get(photo.digest)
        if context is not None:
            status = "exact"
            group_size, reclaimable = context
        elif photo.path in similar_top_paths:
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

    top_folders = (
        heapq.nlargest(
            folder_limit,
            folder_bytes,
            key=lambda path: (folder_bytes[path], str(path).casefold()),
        )
        if folder_limit
        else []
    )
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
