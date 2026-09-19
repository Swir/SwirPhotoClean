"""Conservative EXIF-backed burst review helpers.

Burst Cleaner is intentionally read-only. A burst is only suggested when files
already belong to a visually-similar result group *and* at least two distinct
image digests expose capture timestamps close together in EXIF metadata.
Missing EXIF is never guessed from filenames or filesystem modification times.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image

from .core import Group, Photo, ScanResult
from .quality import QualityKeeperRecommendation, recommend_keeper_with_quality

# EXIF tag ids from the TIFF/Exif specification.
_DATETIME_TAGS = (
    (36867, "DateTimeOriginal"),
    (36868, "DateTimeDigitized"),
    (306, "DateTime"),
)
_EXIF_FORMAT = "%Y:%m:%d %H:%M:%S"


@dataclass(frozen=True)
class CaptureTime:
    """Parsed local EXIF capture timestamp and the tag that supplied it."""

    value: datetime
    source: str


@dataclass(frozen=True)
class BurstSequence:
    """A review-only burst candidate inside one similar-photo group."""

    group_index: int
    photos: tuple[Photo, ...]
    started_at: datetime
    ended_at: datetime
    keeper: QualityKeeperRecommendation

    @property
    def span_seconds(self) -> float:
        return max(0.0, (self.ended_at - self.started_at).total_seconds())


def _coerce_exif_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("ascii", errors="ignore")
    text = str(value).strip().strip("\x00")
    return text or None


def read_capture_time(path: Path) -> CaptureTime | None:
    """Read a capture timestamp from EXIF without decoding the full image.

    The function deliberately does not fall back to file mtime because copied or
    restored files can have unrelated filesystem timestamps. Returning ``None``
    is safer than inventing burst evidence.
    """

    try:
        with Image.open(path) as image:
            exif = image.getexif()
            for tag, source in _DATETIME_TAGS:
                text = _coerce_exif_text(exif.get(tag))
                if not text:
                    continue
                try:
                    # Some cameras append timezone/subsecond data after the
                    # standard 19-character DateTime value. Burst ordering only
                    # needs the canonical second-resolution portion.
                    parsed = datetime.strptime(text[:19], _EXIF_FORMAT)
                except ValueError:
                    continue
                return CaptureTime(parsed, source)
    except (OSError, ValueError):
        return None
    return None


def _distinct_digest_photos(group: Group) -> tuple[Photo, ...]:
    """Collapse byte-identical copies so a copied file cannot fake a burst."""

    chosen: dict[str, Photo] = {}
    for photo in group.photos:
        previous = chosen.get(photo.digest)
        if previous is None or str(photo.path).casefold() < str(previous.path).casefold():
            chosen[photo.digest] = photo
    return tuple(chosen.values())


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
    - adjacent captures must be no more than ``max_gap_seconds`` apart.

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

        timestamped: list[tuple[datetime, Photo]] = []
        for photo in _distinct_digest_photos(group):
            evidence = metadata_cache.get(photo.path)
            if photo.path not in metadata_cache:
                evidence = read_capture_time(photo.path)
                metadata_cache[photo.path] = evidence
            if evidence is not None:
                timestamped.append((evidence.value, photo))

        timestamped.sort(key=lambda item: (item[0], str(item[1].path).casefold()))
        if len(timestamped) < minimum_frames:
            continue

        current: list[tuple[datetime, Photo]] = [timestamped[0]]

        def flush(sequence: list[tuple[datetime, Photo]]):
            if len(sequence) < minimum_frames:
                return
            photos = tuple(photo for _, photo in sequence)
            review_group = Group("similar", photos)
            found.append(
                BurstSequence(
                    group_index=group_index,
                    photos=photos,
                    started_at=sequence[0][0],
                    ended_at=sequence[-1][0],
                    keeper=recommend_keeper_with_quality(review_group),
                )
            )

        for item in timestamped[1:]:
            gap = (item[0] - current[-1][0]).total_seconds()
            if gap <= max_gap_seconds:
                current.append(item)
            else:
                flush(current)
                current = [item]
        flush(current)

    return tuple(found)
