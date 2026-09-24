"""Read-only exact-duplicate hotspot analysis for Folder Health.

The helper consumes an existing ScanResult and never mutates marks or files.
Hotspot savings are derived only from byte-identical SHA-256 groups. One
conservative keeper is retained for every digest before any folder is credited
with redundant-copy bytes.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .core import Photo, ScanResult


@dataclass(frozen=True, slots=True)
class FolderHotspot:
    """One folder containing redundant exact-copy candidates."""

    folder: Path
    exact_groups: int
    duplicate_files: int
    reclaimable_bytes: int


def _trusted_exact_buckets(result: ScanResult) -> dict[str, dict[Path, Photo]]:
    """Return exact digest buckets constrained to authoritative scanned photos.

    Repeated/overlapping groups are deduplicated by path. A group member outside
    ``ScanResult.photos`` or with a digest that no longer agrees with the scanned
    record is ignored, matching the conservative Folder Health trust boundary.
    """

    scanned_by_path = {photo.path: photo for photo in result.photos}
    buckets: dict[str, dict[Path, Photo]] = defaultdict(dict)
    for group in result.groups:
        if group.kind != "exact":
            continue
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


def duplicate_hotspots(result: ScanResult, limit: int = 8) -> tuple[FolderHotspot, ...]:
    """Rank folders by conservative exact-duplicate reclaimable bytes.

    For each SHA-256 digest, one member is always kept. The keeper is chosen
    deterministically as the largest member, with a case-insensitive path tie
    break. Every other member is an *informational* redundant-copy candidate and
    contributes its non-negative encoded size to its parent folder. No cleanup
    mark is created and similar-photo groups are never included.
    """

    if limit < 0:
        raise ValueError("limit must be non-negative")
    if limit == 0:
        return ()

    duplicate_counts: dict[Path, int] = defaultdict(int)
    reclaimable_bytes: dict[Path, int] = defaultdict(int)
    group_digests: dict[Path, set[str]] = defaultdict(set)

    for digest, members in _trusted_exact_buckets(result).items():
        photos = tuple(members.values())
        keeper = min(
            photos,
            key=lambda photo: (
                -max(0, photo.size),
                str(photo.path).casefold(),
            ),
        )
        for photo in photos:
            if photo.path == keeper.path:
                continue
            folder = photo.path.parent
            duplicate_counts[folder] += 1
            reclaimable_bytes[folder] += max(0, photo.size)
            group_digests[folder].add(digest)

    hotspots = [
        FolderHotspot(
            folder=folder,
            exact_groups=len(group_digests[folder]),
            duplicate_files=count,
            reclaimable_bytes=reclaimable_bytes[folder],
        )
        for folder, count in duplicate_counts.items()
        if count > 0
    ]
    hotspots.sort(
        key=lambda item: (
            -item.reclaimable_bytes,
            -item.duplicate_files,
            str(item.folder).casefold(),
        )
    )
    return tuple(hotspots[:limit])
