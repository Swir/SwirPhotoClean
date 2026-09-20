"""Explainable, read-only cleanup insights.

This module never marks or removes files. It only summarizes scan results and
produces conservative review signals such as Smart Keep and Folder Health.
"""
from __future__ import annotations

import heapq
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .core import Group, Photo, ScanResult

# Format points are deliberately a small part of the score. Resolution remains
# dominant so a tiny lossless export does not outrank a substantially larger
# photographic original merely because of its container format.
_FORMAT_POINTS = {
    ".png": 20.0,
    ".tif": 20.0,
    ".tiff": 20.0,
    ".bmp": 16.0,
    ".webp": 14.0,
    ".jpg": 12.0,
    ".jpeg": 12.0,
    ".gif": 6.0,
}


@dataclass(frozen=True)
class KeeperRecommendation:
    """A non-destructive suggestion for which member of a group to keep."""

    photo: Photo
    score: float
    resolution_points: float
    format_points: float
    density_points: float
    confidence: str
    equivalent_exact: bool = False


@dataclass(frozen=True)
class FolderHealth:
    """Conservative scan summary suitable for UI/reporting.

    All reclaimable-byte figures are derived only from byte-identical SHA-256
    groups and preserve at least one copy for each digest. Similar-photo groups
    remain review-only and never contribute to the savings estimate.
    """

    total_photos: int
    total_bytes: int
    grouped_files: int
    unflagged_files: int
    exact_groups: int
    exact_group_members: int
    exact_duplicate_files: int
    similar_groups: int
    similar_review_files: int
    warning_count: int
    exact_reclaimable_bytes: int
    exact_reclaimable_percent: float
    largest_files: tuple[Photo, ...]


def _pixels(photo: Photo) -> int:
    return max(1, photo.width * photo.height)


def _encoded_density(photo: Photo) -> float:
    """Bytes per decoded pixel; a weak tie-breaker, not a quality measurement."""

    return photo.size / _pixels(photo)


def _format_points(path: Path) -> float:
    return _FORMAT_POINTS.get(path.suffix.lower(), 8.0)


def recommend_keeper(group: Group) -> KeeperRecommendation:
    """Return an explainable keep suggestion without selecting anything.

    Exact groups are byte-identical, so the function explicitly reports them as
    equivalent rather than pretending one copy has better image quality. Similar
    groups use only evidence already collected by the scanner: decoded
    resolution, file format and encoded bytes-per-pixel. The latter is a small
    tie-breaker and is intentionally *not* described as sharpness.
    """

    photos = tuple(group.photos)
    if not photos:
        raise ValueError("Cannot recommend a keeper for an empty group")

    if group.kind == "exact" or len({photo.digest for photo in photos}) == 1:
        # Prefer a deterministic path only so the UI can focus one row. Every
        # member is still reported as byte-equivalent.
        chosen = min(photos, key=lambda photo: (len(str(photo.path)), str(photo.path).casefold()))
        return KeeperRecommendation(
            photo=chosen,
            score=100.0,
            resolution_points=70.0,
            format_points=20.0,
            density_points=10.0,
            confidence="equivalent",
            equivalent_exact=True,
        )

    max_pixels = max(_pixels(photo) for photo in photos)
    max_density = max(_encoded_density(photo) for photo in photos)

    ranked: list[KeeperRecommendation] = []
    for photo in photos:
        resolution_points = 70.0 * (_pixels(photo) / max_pixels)
        format_points = _format_points(photo.path)
        density_points = 10.0 * (_encoded_density(photo) / max_density if max_density else 0.0)
        ranked.append(
            KeeperRecommendation(
                photo=photo,
                score=round(resolution_points + format_points + density_points, 2),
                resolution_points=round(resolution_points, 2),
                format_points=round(format_points, 2),
                density_points=round(density_points, 2),
                confidence="low",
            )
        )

    ranked.sort(
        key=lambda item: (
            item.score,
            _pixels(item.photo),
            item.photo.size,
            str(item.photo.path).casefold(),
        ),
        reverse=True,
    )
    winner = ranked[0]
    margin = winner.score - ranked[1].score if len(ranked) > 1 else winner.score
    confidence = "high" if margin >= 15 else "medium" if margin >= 7 else "low"
    return KeeperRecommendation(
        photo=winner.photo,
        score=winner.score,
        resolution_points=winner.resolution_points,
        format_points=winner.format_points,
        density_points=winner.density_points,
        confidence=confidence,
    )


def _exact_digest_buckets(
    groups: Iterable[Group],
    scanned_by_path: dict[Path, Photo],
) -> dict[str, dict[Path, Photo]]:
    """Deduplicate trustworthy exact membership by SHA-256 digest and path.

    `ScanResult.photos` is the authoritative set. A stale/malformed adapter must
    not inflate health numbers by injecting a path outside that set or by pairing
    a path with metadata that disagrees with the scanned photo.
    """

    buckets: dict[str, dict[Path, Photo]] = defaultdict(dict)
    for group in groups:
        for member in group.photos:
            photo = scanned_by_path.get(member.path)
            if photo is None or photo.digest != member.digest:
                continue
            buckets[photo.digest].setdefault(photo.path, photo)
    return {
        digest: members
        for digest, members in buckets.items()
        if len(members) >= 2
    }


def folder_health(result: ScanResult, largest_limit: int = 5) -> FolderHealth:
    """Build a conservative, read-only health report for the scanned library.

    Safe savings are counted only for exact SHA-256 duplicates. For every digest
    bucket one copy is always preserved, and repeated paths/groups cannot inflate
    the total. Similar groups are review candidates only. `grouped_files` is the
    unique union of exact and similar result members; `unflagged_files` are scanned
    photos that currently appear in neither type of result group.

    Large-file selection uses a bounded top-K heap, so opening/refreshing Folder
    Health no longer sorts an entire large library merely to render a handful of
    rows.
    """

    if largest_limit < 0:
        raise ValueError("largest_limit must be non-negative")

    scanned_by_path = {photo.path: photo for photo in result.photos}
    exact_buckets = _exact_digest_buckets(
        (group for group in result.groups if group.kind == "exact"),
        scanned_by_path,
    )
    exact_paths = {path for bucket in exact_buckets.values() for path in bucket}

    similar_member_sets = {
        frozenset(
            photo.path
            for photo in group.photos
            if photo.path in scanned_by_path
        )
        for group in result.groups
        if group.kind == "similar"
    }
    similar_member_sets = {members for members in similar_member_sets if len(members) >= 2}
    similar_paths = set().union(*similar_member_sets) if similar_member_sets else set()
    grouped_files = len(exact_paths) + sum(
        1 for path in similar_paths if path not in exact_paths
    )

    exact_duplicate_files = 0
    exact_reclaimable_bytes = 0
    for bucket in exact_buckets.values():
        photos = tuple(bucket.values())
        if len(photos) < 2:
            continue
        exact_duplicate_files += len(photos) - 1
        # Keep the largest member in the extremely defensive case where malformed
        # external/session data associates one digest with inconsistent sizes.
        exact_reclaimable_bytes += max(
            0,
            sum(max(0, photo.size) for photo in photos)
            - max(max(0, photo.size) for photo in photos),
        )

    total_bytes = sum(max(0, photo.size) for photo in result.photos)
    exact_reclaimable_percent = (
        (exact_reclaimable_bytes / total_bytes) * 100.0 if total_bytes else 0.0
    )
    largest_files = (
        tuple(
            heapq.nlargest(
                largest_limit,
                result.photos,
                key=lambda photo: (photo.size, str(photo.path).casefold()),
            )
        )
        if largest_limit
        else ()
    )

    return FolderHealth(
        total_photos=len(result.photos),
        total_bytes=total_bytes,
        grouped_files=grouped_files,
        unflagged_files=max(0, len(result.photos) - grouped_files),
        exact_groups=len(exact_buckets),
        exact_group_members=len(exact_paths),
        exact_duplicate_files=exact_duplicate_files,
        similar_groups=len(similar_member_sets),
        similar_review_files=len(similar_paths),
        warning_count=len(result.warnings),
        exact_reclaimable_bytes=exact_reclaimable_bytes,
        exact_reclaimable_percent=round(exact_reclaimable_percent, 2),
        largest_files=largest_files,
    )
