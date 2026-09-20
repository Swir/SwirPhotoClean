"""Conservative EXIF-backed burst review helpers.

Burst Cleaner is intentionally read-only. A burst is only suggested when files
already belong to a visually-similar result group *and* at least two distinct
image digests expose capture timestamps close together in EXIF metadata.
Missing EXIF is never guessed from filenames or filesystem modification times.
Known camera/device identity is also used conservatively: frames from two
explicitly different devices are never merged into the same burst sequence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .core import Group, Photo, ScanResult
from .exif_metadata import read_exif_metadata
from .quality import QualityKeeperRecommendation, recommend_keeper_with_quality


@dataclass(frozen=True)
class CaptureTime:
    """Parsed local EXIF capture timestamp and the evidence that supplied it."""

    value: datetime
    source: str
    camera_label: str | None = None


@dataclass(frozen=True)
class BurstSequence:
    """A review-only burst candidate inside one similar-photo group."""

    group_index: int
    photos: tuple[Photo, ...]
    started_at: datetime
    ended_at: datetime
    keeper: QualityKeeperRecommendation
    camera_label: str | None = None

    @property
    def span_seconds(self) -> float:
        return max(0.0, (self.ended_at - self.started_at).total_seconds())


def read_capture_time(path: Path) -> CaptureTime | None:
    """Read a capture timestamp from EXIF without decoding the full image.

    The shared parser understands the standard nested Exif IFD used by cameras
    and phones, while retaining compatibility with top-level metadata written by
    older tools. The function deliberately does not fall back to file mtime.
    Returning ``None`` is safer than inventing burst evidence.
    """

    try:
        metadata = read_exif_metadata(path)
    except (OSError, ValueError):
        return None
    if metadata.captured_at is None or metadata.capture_source is None:
        return None
    return CaptureTime(
        value=metadata.captured_at,
        source=metadata.capture_source,
        camera_label=metadata.device_label,
    )


def _distinct_digest_photos(group: Group) -> tuple[Photo, ...]:
    """Collapse byte-identical copies so a copied file cannot fake a burst."""

    chosen: dict[str, Photo] = {}
    for photo in group.photos:
        previous = chosen.get(photo.digest)
        if previous is None or str(photo.path).casefold() < str(previous.path).casefold():
            chosen[photo.digest] = photo
    return tuple(chosen.values())


def _same_known_camera(left: str | None, right: str | None) -> bool:
    """Return False only when both sides explicitly identify different devices."""

    if not left or not right:
        return True
    return left.casefold() == right.casefold()


def burst_sequences(
    result: ScanResult,
    *,
    max_gap_seconds: float = 3.0,
    minimum_frames: int = 2,
) -> tuple[BurstSequence, ...]:
    """Find conservative burst candidates from visually-similar groups.

    Requirements for a sequence:
    - source group must be ``similar``;
    - byte-identical copies are collapsed by digest;
    - every included frame must have a parseable EXIF capture timestamp;
    - adjacent captures must be no more than ``max_gap_seconds`` apart;
    - when camera/device identity is available for both sides, it must agree.

    Nothing is marked for deletion. ``keeper`` is an explainable Smart Keep
    suggestion enhanced with local sharpness/exposure review signals.
    """

    if max_gap_seconds < 0:
        raise ValueError("max_gap_seconds must be non-negative")
    if minimum_frames < 2:
        raise ValueError("minimum_frames must be at least 2")

    metadata_cache: dict[Path, CaptureTime | None] = {}
    found: list[BurstSequence] = []

    for group_index, group in enumerate(result.groups):
        if group.kind != "similar":
            continue

        timestamped: list[tuple[datetime, Photo, CaptureTime]] = []
        for photo in _distinct_digest_photos(group):
            if photo.path not in metadata_cache:
                metadata_cache[photo.path] = read_capture_time(photo.path)
            evidence = metadata_cache[photo.path]
            if evidence is not None:
                timestamped.append((evidence.value, photo, evidence))

        timestamped.sort(key=lambda item: (item[0], str(item[1].path).casefold()))
        if len(timestamped) < minimum_frames:
            continue

        current: list[tuple[datetime, Photo, CaptureTime]] = [timestamped[0]]
        current_camera = timestamped[0][2].camera_label

        def flush(sequence: list[tuple[datetime, Photo, CaptureTime]]):
            if len(sequence) < minimum_frames:
                return
            photos = tuple(photo for _, photo, _ in sequence)
            known_cameras = {
                evidence.camera_label
                for _, _, evidence in sequence
                if evidence.camera_label
            }
            camera_label = next(iter(known_cameras)) if len(known_cameras) == 1 else None
            review_group = Group("similar", photos)
            found.append(
                BurstSequence(
                    group_index=group_index,
                    photos=photos,
                    started_at=sequence[0][0],
                    ended_at=sequence[-1][0],
                    keeper=recommend_keeper_with_quality(review_group),
                    camera_label=camera_label,
                )
            )

        for item in timestamped[1:]:
            gap = (item[0] - current[-1][0]).total_seconds()
            item_camera = item[2].camera_label
            same_camera = _same_known_camera(current_camera, item_camera)
            if gap <= max_gap_seconds and same_camera:
                current.append(item)
                if current_camera is None and item_camera:
                    current_camera = item_camera
            else:
                flush(current)
                current = [item]
                current_camera = item_camera
        flush(current)

    return tuple(found)
