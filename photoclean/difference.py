"""Read-only pixel difference preview for two user-selected photos."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageOps, ImageStat

from .core import MAX_PIXELS, Photo

DEFAULT_THRESHOLD = 10
MAX_ANALYSIS_SIDE = 1600


@dataclass(frozen=True)
class DifferenceReport:
    left_path: Path
    right_path: Path
    left_size: tuple[int, int]
    right_size: tuple[int, int]
    analysis_size: tuple[int, int]
    resampled: bool
    mean_delta: float
    changed_ratio: float
    changed_bbox: tuple[int, int, int, int] | None
    threshold: int


@dataclass(frozen=True)
class DifferencePreview:
    report: DifferenceReport
    heatmap: Image.Image


def _bounded_size(width: int, height: int, max_side: int) -> tuple[int, int]:
    if max_side < 64:
        raise ValueError("max_side must be at least 64 pixels")
    scale = min(1.0, max_side / max(width, height))
    return max(1, round(width * scale)), max(1, round(height * scale))


def _analysis_target(
    left_photo: Photo,
    right_photo: Photo,
    max_side: int,
) -> tuple[tuple[int, int], bool]:
    """Choose the common bounded size before either source is fully decoded.

    ``Photo.width``/``height`` already describe the EXIF-oriented scan result, so
    the target can be decided from trusted scan metadata. This lets each large
    source be resized and released before the second source is decoded instead of
    retaining two full-resolution images at once.
    """

    left_size = (left_photo.width, left_photo.height)
    right_size = (right_photo.width, right_photo.height)
    target_source = left_size if left_size == right_size else (
        min(left_size[0], right_size[0]),
        min(left_size[1], right_size[1]),
    )
    target = _bounded_size(*target_source, max_side=max_side)
    return target, left_size != target or right_size != target


def _load_rgb(photo: Photo, target: tuple[int, int]) -> Image.Image:
    """Load one EXIF-oriented source and return only the bounded RGB working copy."""

    with Image.open(photo.path) as source:
        if source.width * source.height > MAX_PIXELS:
            raise ValueError("Image exceeds the 40 megapixel safety limit")
        oriented = ImageOps.exif_transpose(source)
        has_transparency = (
            oriented.mode in {"RGBA", "LA"} or "transparency" in oriented.info
        )
        if has_transparency:
            rgba = oriented.convert("RGBA")
            image = Image.new("RGB", rgba.size, "white")
            image.paste(rgba, mask=rgba.getchannel("A"))
        elif oriented.mode == "RGB":
            # Detach the pixels from the source handle before its context closes.
            image = oriented.copy()
        else:
            image = oriented.convert("RGB")

        if image.size != target:
            image = image.resize(target, Image.Resampling.LANCZOS)
        return image


def build_difference_preview(
    left_photo: Photo,
    right_photo: Photo,
    *,
    threshold: int = DEFAULT_THRESHOLD,
    max_side: int = MAX_ANALYSIS_SIDE,
) -> DifferencePreview:
    """Build a bounded read-only heatmap; it never mutates or rewrites source files."""
    if left_photo.path == right_photo.path:
        raise ValueError("Choose two different photos")
    if not 0 <= threshold <= 255:
        raise ValueError("threshold must be between 0 and 255")

    left_original_size = (left_photo.width, left_photo.height)
    right_original_size = (right_photo.width, right_photo.height)
    target, resampled = _analysis_target(left_photo, right_photo, max_side)

    # Load and bound sources sequentially. For large camera photos this avoids
    # keeping two full-resolution decoded images alive at the same time.
    left = _load_rgb(left_photo, target)
    right = _load_rgb(right_photo, target)

    difference = ImageChops.difference(left, right)
    grayscale = difference.convert("L")
    histogram = grayscale.histogram()
    changed = sum(histogram[threshold + 1 :])
    total = max(1, left.width * left.height)
    changed_ratio = changed / total
    mean_delta = sum(ImageStat.Stat(difference).mean) / 3.0
    mask = grayscale.point(lambda value: 255 if value > threshold else 0)
    changed_bbox = mask.getbbox()

    if changed_bbox is None:
        enhanced = grayscale
    else:
        enhanced = ImageOps.autocontrast(grayscale)
    heatmap = ImageOps.colorize(enhanced, black="#02050A", white="#62E5FF")

    report = DifferenceReport(
        left_path=left_photo.path,
        right_path=right_photo.path,
        left_size=left_original_size,
        right_size=right_original_size,
        analysis_size=target,
        resampled=resampled,
        mean_delta=mean_delta,
        changed_ratio=changed_ratio,
        changed_bbox=changed_bbox,
        threshold=threshold,
    )
    return DifferencePreview(report=report, heatmap=heatmap)
