"""Read-only EXIF timeline and camera/device grouping helpers.

The library explorer deliberately uses embedded image metadata only. Filesystem
mtime, filenames, folder names and other weak signals are never presented as
capture-time or camera evidence.
"""
from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Iterable

from PIL import Image

from .core import Photo, ScanResult

_DATETIME_TAGS = (
    (36867, "DateTimeOriginal"),
    (36868, "DateTimeDigitized"),
    (306, "DateTime"),
)
_EXIF_FORMAT = "%Y:%m:%d %H:%M:%S"
_MAKE_TAG = 271
_MODEL_TAG = 272
_MAX_METADATA_TEXT = 200


@dataclass(frozen=True)
class LibraryPhotoMetadata:
    photo: Photo
    captured_at: datetime | None
    capture_source: str | None
    camera_make: str | None
    camera_model: str | None

    @property
    def device_label(self) -> str | None:
        make = self.camera_make
        model = self.camera_model
        if make and model:
            if model.casefold().startswith(make.casefold()):
                return model
            return f"{make} {model}"
        return model or make


@dataclass(frozen=True)
class TimelineBucket:
    day: date
    photos: tuple[Photo, ...]

    @property
    def total_bytes(self) -> int:
        return sum(photo.size for photo in self.photos)


@dataclass(frozen=True)
class DeviceBucket:
    label: str
    photos: tuple[Photo, ...]

    @property
    def total_bytes(self) -> int:
        return sum(photo.size for photo in self.photos)


@dataclass(frozen=True)
class LibraryMetadataReport:
    metadata: tuple[LibraryPhotoMetadata, ...]
    timeline: tuple[TimelineBucket, ...]
    devices: tuple[DeviceBucket, ...]
    analyzed_count: int
    unavailable_count: int
    cancelled: bool

    @property
    def total_count(self) -> int:
        return len(self.metadata)

    @property
    def captured_count(self) -> int:
        return sum(item.captured_at is not None for item in self.metadata)

    @property
    def device_count(self) -> int:
        return sum(item.device_label is not None for item in self.metadata)

    @property
    def missing_capture_count(self) -> int:
        return self.total_count - self.captured_count

    @property
    def missing_device_count(self) -> int:
        return self.total_count - self.device_count


def _clean_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    text = " ".join(str(value).replace("\x00", " ").split()).strip()
    if not text:
        return None
    return text[:_MAX_METADATA_TEXT]


def _parse_datetime(value) -> datetime | None:
    text = _clean_text(value)
    if not text or len(text) < 19:
        return None
    try:
        return datetime.strptime(text[:19], _EXIF_FORMAT)
    except ValueError:
        return None


def read_library_metadata(photo: Photo) -> LibraryPhotoMetadata:
    """Read EXIF capture and camera metadata without decoding the full image."""

    with Image.open(photo.path) as image:
        exif = image.getexif()
        captured_at = None
        capture_source = None
        for tag, source in _DATETIME_TAGS:
            captured_at = _parse_datetime(exif.get(tag))
            if captured_at is not None:
                capture_source = source
                break
        make = _clean_text(exif.get(_MAKE_TAG))
        model = _clean_text(exif.get(_MODEL_TAG))
    return LibraryPhotoMetadata(
        photo=photo,
        captured_at=captured_at,
        capture_source=capture_source,
        camera_make=make,
        camera_model=model,
    )


def analyze_library_metadata(
    result_or_photos: ScanResult | Iterable[Photo],
    *,
    cancel_event: threading.Event | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> LibraryMetadataReport:
    """Build read-only timeline and camera/device groups from EXIF evidence.

    Missing metadata is reported as missing; it is never filled from filesystem
    timestamps or filenames. Read errors affect only the metadata explorer and
    never mutate the original scan result.
    """

    photos = tuple(result_or_photos.photos if isinstance(result_or_photos, ScanResult) else result_or_photos)
    cancel_event = cancel_event or threading.Event()
    progress = progress or (lambda done, total: None)

    metadata: list[LibraryPhotoMetadata] = []
    unavailable = 0
    cancelled = False
    total = len(photos)

    for index, photo in enumerate(photos, 1):
        if cancel_event.is_set():
            cancelled = True
            break
        try:
            item = read_library_metadata(photo)
        except (OSError, ValueError):
            unavailable += 1
            item = LibraryPhotoMetadata(photo, None, None, None, None)
        metadata.append(item)
        progress(index, total)

    timeline_map: dict[date, list[Photo]] = defaultdict(list)
    device_map: dict[str, list[Photo]] = defaultdict(list)
    for item in metadata:
        if item.captured_at is not None:
            timeline_map[item.captured_at.date()].append(item.photo)
        if item.device_label is not None:
            device_map[item.device_label].append(item.photo)

    timeline = tuple(
        TimelineBucket(day, tuple(sorted(items, key=lambda photo: str(photo.path).casefold())))
        for day, items in sorted(timeline_map.items(), key=lambda pair: pair[0], reverse=True)
    )
    devices = tuple(
        DeviceBucket(label, tuple(sorted(items, key=lambda photo: str(photo.path).casefold())))
        for label, items in sorted(device_map.items(), key=lambda pair: pair[0].casefold())
    )
    return LibraryMetadataReport(
        metadata=tuple(metadata),
        timeline=timeline,
        devices=devices,
        analyzed_count=len(metadata),
        unavailable_count=unavailable,
        cancelled=cancelled,
    )
