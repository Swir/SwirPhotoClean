"""Local, read-only photo quality signals used only for review suggestions.

The heuristics in this module are deliberately conservative. They never mark,
move or delete files. Scores are review aids, not a claim of objective image
quality: an intentionally soft or dark photograph can still be the preferred
shot.
"""
from __future__ import annotations

import stat
import warnings
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps, ImageStat

from .core import Group, Photo
from .insights import recommend_keeper

_FORMAT_SCORE = {
    ".png": 100.0,
    ".tif": 100.0,
    ".tiff": 100.0,
    ".bmp": 80.0,
    ".webp": 70.0,
    ".jpg": 60.0,
    ".jpeg": 60.0,
    ".gif": 30.0,
}


@dataclass(frozen=True)
class PhotoQuality:
    """Explainable read-only quality signals for one photo."""

    photo: Photo
    available: bool
    overall_score: float
    sharpness_score: float
    exposure_score: float
    dark_clip_percent: float
    light_clip_percent: float
    mean_luma: float
    notes: tuple[str, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class QualityKeeperRecommendation:
    """Smart Keep recommendation enhanced with local quality signals."""

    photo: Photo
    score: float
    confidence: str
    equivalent_exact: bool
    quality: PhotoQuality | None
    analyzed_count: int
    unavailable_count: int


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _pixels(photo: Photo) -> int:
    return max(1, photo.width * photo.height)


def _density(photo: Photo) -> float:
    return photo.size / _pixels(photo)


def _format_score(path: Path) -> float:
    return _FORMAT_SCORE.get(path.suffix.lower(), 45.0)


def _unavailable(photo: Photo, error: object) -> PhotoQuality:
    return PhotoQuality(
        photo=photo,
        available=False,
        overall_score=0.0,
        sharpness_score=0.0,
        exposure_score=0.0,
        dark_clip_percent=0.0,
        light_clip_percent=0.0,
        mean_luma=0.0,
        notes=("unavailable",),
        error=str(error),
    )


def _unsafe_path(info) -> bool:
    """Reject path indirection that the scanner itself does not accept."""

    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _scan_identity_matches(photo: Photo, info) -> bool:
    """Cheaply verify that review still points at the scanned filesystem object."""

    if info.st_size != photo.size or info.st_mtime_ns != photo.modified_ns:
        return False
    current_device = int(getattr(info, "st_dev", 0) or 0)
    current_inode = int(getattr(info, "st_ino", 0) or 0)
    if photo.device and current_device and current_device != photo.device:
        return False
    if photo.inode and current_inode and current_inode != photo.inode:
        return False
    return True


def _quality_sample(source: Image.Image, max_side: int) -> Image.Image:
    """Create the bounded grayscale sample before allocating full-size conversions.

    Pillow may still need to decode the source format, but for codecs that support
    ``draft`` (notably JPEG) the decoder can reduce work up front. More importantly,
    orientation and grayscale conversion now operate on a bounded image instead of
    creating another full-resolution pixel buffer solely for a 384 px review score.
    """

    if source.width > max_side or source.height > max_side:
        try:
            source.draft(source.mode, (max_side, max_side))
        except (AttributeError, OSError, ValueError):
            pass
        source.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)

    oriented = ImageOps.exif_transpose(source)
    image = oriented if oriented.mode == "L" else oriented.convert("L")
    if image.width > max_side or image.height > max_side:
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return image


@lru_cache(maxsize=512)
def _assess_photo_cached(photo: Photo, max_side: int) -> PhotoQuality:
    """Compute one quality score after the public wrapper validates scan identity."""

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(photo.path) as source:
                image = _quality_sample(source, max_side)
                if image.width < 3 or image.height < 3:
                    raise ValueError("image sample is too small")

                histogram = image.histogram()
                pixel_count = max(1, image.width * image.height)
                dark_clip = 100.0 * sum(histogram[:8]) / pixel_count
                light_clip = 100.0 * sum(histogram[248:]) / pixel_count
                mean_luma = float(ImageStat.Stat(image).mean[0])

                # FIND_EDGES is intentionally simple and deterministic. Cropping the
                # one-pixel border avoids the artificial frame introduced by the
                # convolution at image boundaries.
                edges = image.filter(ImageFilter.FIND_EDGES)
                if edges.width > 4 and edges.height > 4:
                    edges = edges.crop((2, 2, edges.width - 2, edges.height - 2))
                edge_mean = float(ImageStat.Stat(edges).mean[0])
                sharpness = _clamp((edge_mean - 1.5) * 5.0)

                clipping_penalty = min(80.0, (dark_clip + light_clip) * 1.6)
                brightness_penalty = 0.0
                if mean_luma < 32.0:
                    brightness_penalty = min(35.0, (32.0 - mean_luma) * 1.1)
                elif mean_luma > 223.0:
                    brightness_penalty = min(35.0, (mean_luma - 223.0) * 1.1)
                exposure = _clamp(100.0 - clipping_penalty - brightness_penalty)
                overall = _clamp(0.70 * sharpness + 0.30 * exposure)

                notes: list[str] = []
                if sharpness < 25.0:
                    notes.append("soft")
                if dark_clip >= 8.0:
                    notes.append("dark-clipping")
                if light_clip >= 8.0:
                    notes.append("light-clipping")
                if not notes:
                    notes.append("balanced")

                return PhotoQuality(
                    photo=photo,
                    available=True,
                    overall_score=round(overall, 2),
                    sharpness_score=round(sharpness, 2),
                    exposure_score=round(exposure, 2),
                    dark_clip_percent=round(dark_clip, 2),
                    light_clip_percent=round(light_clip, 2),
                    mean_luma=round(mean_luma, 2),
                    notes=tuple(notes),
                )
    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        return _unavailable(photo, error)


def assess_photo(photo: Photo, max_side: int = 384) -> PhotoQuality:
    """Analyze sharpness/exposure on a bounded, scan-identity-checked sample.

    The review score is cached, but the path is revalidated before and after every
    access so a removed, replaced, relinked or otherwise changed scan result cannot
    keep serving a stale cached quality recommendation. This is a review guard, not
    a replacement for the full SHA-256 revalidation used by Recycle Bin cleanup.
    """

    if max_side < 64 or max_side > 1024:
        raise ValueError("max_side must be between 64 and 1024")

    try:
        before = photo.path.lstat()
    except OSError as error:
        return _unavailable(photo, error)
    if _unsafe_path(before) or not _scan_identity_matches(photo, before):
        return _unavailable(photo, "file changed or became unsafe since scan")

    assessment = _assess_photo_cached(photo, max_side)

    try:
        after = photo.path.lstat()
    except OSError as error:
        return _unavailable(photo, error)
    before_identity = (
        before.st_size,
        before.st_mtime_ns,
        getattr(before, "st_dev", 0),
        getattr(before, "st_ino", 0),
        getattr(before, "st_file_attributes", 0),
    )
    after_identity = (
        after.st_size,
        after.st_mtime_ns,
        getattr(after, "st_dev", 0),
        getattr(after, "st_ino", 0),
        getattr(after, "st_file_attributes", 0),
    )
    if (
        before_identity != after_identity
        or _unsafe_path(after)
        or not _scan_identity_matches(photo, after)
    ):
        return _unavailable(photo, "file changed during quality analysis")
    return assessment


def recommend_keeper_with_quality(
    group: Group,
    *,
    analyzer=assess_photo,
    max_quality_candidates: int = 12,
) -> QualityKeeperRecommendation:
    """Return Smart Keep enhanced by sharpness/exposure evidence.

    Exact groups remain byte-equivalent and therefore bypass subjective quality
    scoring. For similar groups, structural signals (resolution/format/density)
    stay dominant while quality contributes enough to avoid preferring a clearly
    soft or heavily clipped frame merely because it is marginally larger.
    """

    photos = tuple(group.photos)
    if not photos:
        raise ValueError("Cannot recommend a keeper for an empty group")
    if max_quality_candidates < 1:
        raise ValueError("max_quality_candidates must be at least 1")

    base = recommend_keeper(group)
    if base.equivalent_exact:
        return QualityKeeperRecommendation(
            photo=base.photo,
            score=base.score,
            confidence="equivalent",
            equivalent_exact=True,
            quality=None,
            analyzed_count=0,
            unavailable_count=0,
        )

    max_pixels = max(_pixels(photo) for photo in photos)
    max_density = max(_density(photo) for photo in photos)

    structural = sorted(
        photos,
        key=lambda photo: (
            _pixels(photo) / max_pixels,
            _format_score(photo.path),
            _density(photo) / max_density if max_density else 0.0,
            photo.size,
            str(photo.path).casefold(),
        ),
        reverse=True,
    )
    analysis_targets = set(structural[:max_quality_candidates])

    ranked: list[tuple[float, Photo, PhotoQuality | None]] = []
    analyzed_count = 0
    unavailable_count = 0
    for photo in photos:
        resolution = 100.0 * (_pixels(photo) / max_pixels)
        density = 100.0 * (_density(photo) / max_density if max_density else 0.0)
        container = _format_score(photo.path)
        assessment = analyzer(photo) if photo in analysis_targets else None
        if assessment is not None and assessment.available:
            quality_score = assessment.overall_score
            analyzed_count += 1
        else:
            # Neutral quality evidence keeps unanalysed/unavailable files in the
            # race without pretending that missing evidence means poor quality.
            quality_score = 50.0
            if assessment is not None:
                unavailable_count += 1
        score = (
            0.45 * resolution
            + 0.35 * quality_score
            + 0.10 * container
            + 0.10 * density
        )
        ranked.append((round(score, 2), photo, assessment))

    ranked.sort(
        key=lambda item: (
            item[0],
            _pixels(item[1]),
            item[1].size,
            str(item[1].path).casefold(),
        ),
        reverse=True,
    )
    winner_score, winner, winner_quality = ranked[0]
    margin = winner_score - ranked[1][0] if len(ranked) > 1 else winner_score
    confidence = "high" if margin >= 12 else "medium" if margin >= 6 else "low"
    if unavailable_count or analyzed_count < min(len(photos), max_quality_candidates):
        confidence = "low" if confidence == "medium" else confidence

    return QualityKeeperRecommendation(
        photo=winner,
        score=winner_score,
        confidence=confidence,
        equivalent_exact=False,
        quality=winner_quality if winner_quality and winner_quality.available else None,
        analyzed_count=analyzed_count,
        unavailable_count=unavailable_count,
    )
