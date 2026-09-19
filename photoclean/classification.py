"""Conservative, local media-type inspection for completed scan results.

The classifier deliberately prefers ``unknown`` over confident guesses. It never
changes source files, scan groups or Recycle Bin marks. A "screenshot" result is
always a candidate unless there is explicit camera metadata supporting a photo.
"""
from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from PIL import Image

from .core import Photo, ScanResult


CAMERA_MAKE_TAG = 271
CAMERA_MODEL_TAG = 272
DATETIME_ORIGINAL_TAG = 36867

# Exact pixel sizes seen on common desktop/mobile displays. We intentionally
# require an exact match and missing camera metadata before surfacing a
# screenshot candidate. Orientation is handled automatically.
_COMMON_SCREEN_SIZES = frozenset(
    {
        (320, 568),
        (375, 667),
        (375, 812),
        (390, 844),
        (393, 852),
        (414, 896),
        (428, 926),
        (430, 932),
        (750, 1334),
        (828, 1792),
        (1080, 1920),
        (1080, 2340),
        (1080, 2400),
        (1080, 2412),
        (1080, 2460),
        (1080, 2520),
        (1080, 2640),
        (1125, 2436),
        (1170, 2532),
        (1179, 2556),
        (1242, 2208),
        (1242, 2688),
        (1284, 2778),
        (1290, 2796),
        (1366, 768),
        (1440, 2560),
        (1440, 2880),
        (1440, 2960),
        (1440, 3040),
        (1440, 3120),
        (1536, 2048),
        (1600, 900),
        (1600, 2560),
        (1668, 2224),
        (1668, 2388),
        (1920, 1080),
        (1920, 1200),
        (2048, 2732),
        (2560, 1440),
        (2560, 1600),
        (3440, 1440),
        (3840, 2160),
    }
)
_SCREEN_FRIENDLY_FORMATS = frozenset({"PNG", "WEBP"})
_GRAPHIC_FORMATS = frozenset({"PNG", "WEBP", "GIF", "BMP"})


@dataclass(frozen=True)
class MediaClassification:
    photo: Photo
    category: str
    confidence: str
    reasons: tuple[str, ...]
    image_format: str | None
    mode: str | None
    has_camera_metadata: bool
    has_capture_timestamp: bool
    has_alpha: bool
    palette_like: bool

    @property
    def dimensions(self) -> str:
        return f"{self.photo.width}x{self.photo.height}"


@dataclass(frozen=True)
class MediaBucket:
    category: str
    photos: tuple[Photo, ...]

    @property
    def total_bytes(self) -> int:
        return sum(photo.size for photo in self.photos)


@dataclass(frozen=True)
class MediaInspectionReport:
    items: tuple[MediaClassification, ...]
    buckets: tuple[MediaBucket, ...]
    analyzed_count: int
    unavailable_count: int
    cancelled: bool

    @property
    def total_count(self) -> int:
        return len(self.items)

    def count(self, category: str) -> int:
        return sum(item.category == category for item in self.items)


_CATEGORY_ORDER = {
    "camera_photo": 0,
    "screenshot_candidate": 1,
    "graphic_candidate": 2,
    "unknown": 3,
}


def _clean_exif_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    text = " ".join(str(value).replace("\x00", " ").split()).strip()
    return text[:200] if text else None


def _screen_size(width: int, height: int) -> bool:
    pair = (width, height)
    return pair in _COMMON_SCREEN_SIZES or (height, width) in _COMMON_SCREEN_SIZES


def inspect_media_type(photo: Photo) -> MediaClassification:
    """Classify one image using conservative, explainable local evidence."""

    with Image.open(photo.path) as image:
        image_format = (image.format or photo.path.suffix.lstrip(".") or "").upper() or None
        mode = image.mode or None
        exif = image.getexif()
        make = _clean_exif_text(exif.get(CAMERA_MAKE_TAG))
        model = _clean_exif_text(exif.get(CAMERA_MODEL_TAG))
        captured = _clean_exif_text(exif.get(DATETIME_ORIGINAL_TAG))
        camera_metadata = bool(make or model)
        capture_timestamp = bool(captured)
        has_alpha = bool("A" in (mode or "") or "transparency" in image.info)
        palette_like = mode in {"1", "P"}

    reasons: list[str] = []
    if camera_metadata:
        reasons.append("camera_metadata")
        if capture_timestamp:
            reasons.append("capture_timestamp")
        return MediaClassification(
            photo=photo,
            category="camera_photo",
            confidence="high",
            reasons=tuple(reasons),
            image_format=image_format,
            mode=mode,
            has_camera_metadata=True,
            has_capture_timestamp=capture_timestamp,
            has_alpha=has_alpha,
            palette_like=palette_like,
        )

    screen_size = _screen_size(photo.width, photo.height)
    if screen_size and image_format in _SCREEN_FRIENDLY_FORMATS:
        reasons.extend(("common_screen_dimensions", "screen_friendly_format", "no_camera_metadata"))
        return MediaClassification(
            photo=photo,
            category="screenshot_candidate",
            confidence="medium",
            reasons=tuple(reasons),
            image_format=image_format,
            mode=mode,
            has_camera_metadata=False,
            has_capture_timestamp=capture_timestamp,
            has_alpha=has_alpha,
            palette_like=palette_like,
        )

    if image_format in _GRAPHIC_FORMATS and (has_alpha or palette_like):
        if has_alpha:
            reasons.append("alpha_channel")
        if palette_like:
            reasons.append("palette_mode")
        reasons.extend(("graphic_friendly_format", "no_camera_metadata"))
        return MediaClassification(
            photo=photo,
            category="graphic_candidate",
            confidence="high",
            reasons=tuple(reasons),
            image_format=image_format,
            mode=mode,
            has_camera_metadata=False,
            has_capture_timestamp=capture_timestamp,
            has_alpha=has_alpha,
            palette_like=palette_like,
        )

    if screen_size:
        reasons.extend(("common_screen_dimensions", "no_camera_metadata"))
        category = "screenshot_candidate"
        confidence = "low"
    else:
        reasons.append("insufficient_evidence")
        category = "unknown"
        confidence = "low"

    return MediaClassification(
        photo=photo,
        category=category,
        confidence=confidence,
        reasons=tuple(reasons),
        image_format=image_format,
        mode=mode,
        has_camera_metadata=False,
        has_capture_timestamp=capture_timestamp,
        has_alpha=has_alpha,
        palette_like=palette_like,
    )


def analyze_media_types(
    result_or_photos: ScanResult | Iterable[Photo],
    *,
    cancel_event: threading.Event | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> MediaInspectionReport:
    """Inspect a scan without mutating it or making cleanup decisions."""

    photos = tuple(result_or_photos.photos if isinstance(result_or_photos, ScanResult) else result_or_photos)
    cancel_event = cancel_event or threading.Event()
    progress = progress or (lambda done, total: None)

    items: list[MediaClassification] = []
    unavailable = 0
    cancelled = False
    total = len(photos)

    for index, photo in enumerate(photos, 1):
        if cancel_event.is_set():
            cancelled = True
            break
        try:
            item = inspect_media_type(photo)
        except (OSError, ValueError):
            unavailable += 1
            item = MediaClassification(
                photo=photo,
                category="unknown",
                confidence="low",
                reasons=("unavailable",),
                image_format=None,
                mode=None,
                has_camera_metadata=False,
                has_capture_timestamp=False,
                has_alpha=False,
                palette_like=False,
            )
        items.append(item)
        progress(index, total)

    groups: dict[str, list[Photo]] = defaultdict(list)
    for item in items:
        groups[item.category].append(item.photo)
    buckets = tuple(
        MediaBucket(category, tuple(sorted(group, key=lambda photo: str(photo.path).casefold())))
        for category, group in sorted(groups.items(), key=lambda pair: _CATEGORY_ORDER.get(pair[0], 99))
    )
    return MediaInspectionReport(
        items=tuple(items),
        buckets=buckets,
        analyzed_count=len(items),
        unavailable_count=unavailable,
        cancelled=cancelled,
    )
