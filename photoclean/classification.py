"""Conservative, local media-type inspection for completed scan results.

The classifier deliberately prefers ``unknown`` over confident guesses. It never
changes source files, scan groups or Recycle Bin marks. A "screenshot" result is
always a candidate unless there is explicit camera metadata supporting a photo.
"""
from __future__ import annotations

import os
import stat
import threading
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from PIL import Image

from .core import Photo, ScanResult, linked, signature
from .exif_metadata import metadata_from_exif


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
_CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2}
_SORT_MODES = frozenset({"path", "size_desc", "resolution_desc", "confidence"})


def _screen_size(width: int, height: int) -> bool:
    pair = (width, height)
    return pair in _COMMON_SCREEN_SIZES or (height, width) in _COMMON_SCREEN_SIZES


def filter_and_sort_media_items(
    items: Iterable[MediaClassification],
    *,
    query: str = "",
    sort_by: str = "path",
) -> tuple[MediaClassification, ...]:
    """Return a deterministic read-only view of classifications.

    Filtering is intentionally local and textual. It matches path/name, format,
    dimensions, category/confidence and explainable reason identifiers. Sorting
    never mutates the input sequence or the underlying scan.
    """

    if sort_by not in _SORT_MODES:
        raise ValueError(f"unsupported media sort mode: {sort_by}")

    normalized = " ".join(query.casefold().split())

    def searchable(item: MediaClassification) -> str:
        reason_text = " ".join(reason.replace("_", " ") for reason in item.reasons)
        return " ".join(
            (
                str(item.photo.path).casefold(),
                (item.image_format or "").casefold(),
                item.dimensions.casefold(),
                item.category.replace("_", " ").casefold(),
                item.confidence.casefold(),
                reason_text.casefold(),
            )
        )

    visible = [item for item in items if not normalized or normalized in searchable(item)]

    def path_key(item: MediaClassification):
        return str(item.photo.path).casefold()

    if sort_by == "path":
        key = lambda item: (path_key(item),)
    elif sort_by == "size_desc":
        key = lambda item: (-item.photo.size, path_key(item))
    elif sort_by == "resolution_desc":
        key = lambda item: (-(item.photo.width * item.photo.height), -item.photo.size, path_key(item))
    else:
        key = lambda item: (
            _CONFIDENCE_ORDER.get(item.confidence, 99),
            _CATEGORY_ORDER.get(item.category, 99),
            path_key(item),
        )

    return tuple(sorted(visible, key=key))


def _scan_signature(photo: Photo) -> tuple[int, int, int, int]:
    return photo.size, photo.modified_ns, photo.device, photo.inode


def inspect_media_type(photo: Photo) -> MediaClassification:
    """Classify one stable scanned image using conservative local evidence.

    Classification runs after the scanner, so the pathname may no longer identify
    the object whose dimensions/hash were recorded. Bind Pillow to one already-open
    handle matching the saved scanner signature and reject stale/reparse paths.
    This keeps screenshot/graphic/camera labels from being derived from a substituted
    file while preserving the feature's read-only, review-only behavior.
    """

    expected = _scan_signature(photo)
    if any(linked(part) for part in (photo.path, *photo.path.parents)):
        raise OSError(f"unsafe link/reparse path: {photo.path}")
    before = photo.path.stat()
    if not stat.S_ISREG(before.st_mode) or signature(before) != expected:
        raise OSError(f"file changed since scan: {photo.path}")

    with photo.path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or signature(opened) != expected:
            raise OSError(f"file changed while opening for media inspection: {photo.path}")
        with Image.open(stream) as image:
            image_format = (image.format or photo.path.suffix.lstrip(".") or "").upper() or None
            mode = image.mode or None
            metadata = metadata_from_exif(image.getexif())
            camera_metadata = bool(metadata.camera_make or metadata.camera_model)
            capture_timestamp = metadata.captured_at is not None
            has_alpha = bool("A" in (mode or "") or "transparency" in image.info)
            palette_like = mode in {"1", "P"}

    after = photo.path.stat()
    if not stat.S_ISREG(after.st_mode) or signature(after) != expected:
        raise OSError(f"file changed during media inspection: {photo.path}")

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
