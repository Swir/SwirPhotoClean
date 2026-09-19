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


def _load_rgb(photo: Photo) -> Image.Image:
    with Image.open(photo.path) as source:
        if source.width * source.height > MAX_PIXELS:
            raise ValueError("Image exceeds the 40 megapixel safety limit")
        image = ImageOps.exif_transpose(source).convert("RGBA")
        background = Image.new("RGBA", image.size, "white")
        background.alpha_composite(image)
        return background.convert("RGB")


def _bounded_size(width: int, height: int, max_side: int) -> tuple[int, int]:
    if max_side < 64:
        raise ValueError("max_side must be at least 64 pixels")
    scale = min(1.0, max_side / max(width, height))
    return max(1, round(width * scale)), max(1, round(height * scale))


def _normalize_pair(left: Image.Image, right: Image.Image, max_side: int) -> tuple[Image.Image, Image.Image, bool]:
    target_source = left.size if left.size == right.size else (
        min(left.width, right.width),
        min(left.height, right.height),
    )
    target = _bounded_size(*target_source, max_side=max_side)
    resampled = left.size != target or right.size != target
    if left.size != target:
        left = left.resize(target, Image.Resampling.LANCZOS)
    if right.size != target:
        right = right.resize(target, Image.Resampling.LANCZOS)
    return left, right, resampled


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

    left = _load_rgb(left_photo)
    right = _load_rgb(right_photo)
    left_original_size = left.size
    right_original_size = right.size
    left, right, resampled = _normalize_pair(left, right, max_side)

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
        analysis_size=left.size,
        resampled=resampled,
        mean_delta=mean_delta,
        changed_ratio=changed_ratio,
        changed_bbox=changed_bbox,
        threshold=threshold,
    )
    return DifferencePreview(report=report, heatmap=heatmap)
