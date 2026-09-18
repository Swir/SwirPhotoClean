"""Explainable, read-only cleanup insights.

This module never marks or removes files. It only summarizes scan results and
produces a conservative Smart Keep recommendation for review in the GUI.
"""
from __future__ import annotations

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
    """Conservative scan summary suitable for UI/reporting."""

    total_photos: int
    exact_groups: int
    exact_duplicate_files: int
    similar_groups: int
    similar_review_files: int
    warning_count: int
    exact_reclaimable_bytes: int
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


def folder_health(result: ScanResult, largest_limit: int = 5) -> FolderHealth:
    """Summarize a scan without treating similar photos as guaranteed savings.

    `exact_reclaimable_bytes` counts only byte-identical duplicates and always
    preserves one member of each exact group. Similar groups are review
    candidates only and never contribute to the reclaimable-byte estimate.
    """

    if largest_limit < 0:
        raise ValueError("largest_limit must be non-negative")

    exact_groups = [group for group in result.groups if group.kind == "exact"]
    similar_groups = [group for group in result.groups if group.kind == "similar"]

    exact_duplicate_files = sum(max(0, len(group.photos) - 1) for group in exact_groups)
    exact_reclaimable_bytes = sum(
        max(0, sum(photo.size for photo in group.photos) - max(photo.size for photo in group.photos))
        for group in exact_groups
        if group.photos
    )
    similar_review_paths = {photo.path for group in similar_groups for photo in group.photos}
    largest_files = tuple(sorted(result.photos, key=lambda photo: photo.size, reverse=True)[:largest_limit])

    return FolderHealth(
        total_photos=len(result.photos),
        exact_groups=len(exact_groups),
        exact_duplicate_files=exact_duplicate_files,
        similar_groups=len(similar_groups),
        similar_review_files=len(similar_review_paths),
        warning_count=len(result.warnings),
        exact_reclaimable_bytes=exact_reclaimable_bytes,
        largest_files=largest_files,
    )
