"""Read-only blur/exposure review candidates for completed photo scans.

The finder deliberately reports *possible* issues. It never marks, moves or
deletes files and it does not treat an artistic soft/dark/high-key photograph as
objectively bad. Results are ordered review hints backed by the same bounded,
local quality analysis used by Smart Keep.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from typing import Callable, Iterable

from .core import Photo
from .quality import PhotoQuality, assess_photo

BLUR_SHARPNESS_THRESHOLD = 22.0
EXPOSURE_THRESHOLD = 50.0
OVERALL_THRESHOLD = 35.0


@dataclass(frozen=True)
class BadShotCandidate:
    """One non-destructive review candidate and the evidence behind it."""

    photo: Photo
    quality: PhotoQuality
    severity: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class BadShotScan:
    """Summary of an on-demand bad-shot review pass."""

    candidates: tuple[BadShotCandidate, ...]
    analyzed_count: int
    unavailable_count: int
    candidate_count: int
    cancelled: bool


def _gap(value: float, threshold: float) -> float:
    if threshold <= 0 or value >= threshold:
        return 0.0
    return min(100.0, 100.0 * (threshold - value) / threshold)


def classify_quality(quality: PhotoQuality) -> BadShotCandidate | None:
    """Return a review candidate when quality signals cross conservative limits."""

    if not quality.available:
        return None

    reasons: list[str] = []
    severities: list[float] = []
    if quality.sharpness_score < BLUR_SHARPNESS_THRESHOLD:
        reasons.append("possible-blur")
        severities.append(_gap(quality.sharpness_score, BLUR_SHARPNESS_THRESHOLD))
    if quality.exposure_score < EXPOSURE_THRESHOLD:
        reasons.append("exposure-risk")
        severities.append(_gap(quality.exposure_score, EXPOSURE_THRESHOLD))
    if quality.overall_score < OVERALL_THRESHOLD:
        reasons.append("low-overall")
        severities.append(_gap(quality.overall_score, OVERALL_THRESHOLD))

    if not reasons:
        return None
    severity = round(max(severities), 2)
    return BadShotCandidate(
        photo=quality.photo,
        quality=quality,
        severity=severity,
        reasons=tuple(reasons),
    )


def find_bad_shot_candidates(
    photos: Iterable[Photo],
    *,
    analyzer: Callable[[Photo], PhotoQuality] = assess_photo,
    cancel_event: Event | None = None,
    progress: Callable[[int, int], None] | None = None,
    max_results: int = 300,
) -> BadShotScan:
    """Analyze a completed scan without mutating files or Recycle Bin marks.

    Analysis is cancellable and reports progress without touching Tk. All photos
    are inspected unless cancellation is requested; only the highest-severity
    ``max_results`` candidates are retained for the review table.
    """

    if max_results < 1:
        raise ValueError("max_results must be at least 1")

    items = tuple(photos)
    total = len(items)
    candidates: list[BadShotCandidate] = []
    analyzed = 0
    unavailable = 0
    candidate_count = 0
    cancelled = False

    for index, photo in enumerate(items, start=1):
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            break

        quality = analyzer(photo)
        analyzed += 1
        if not quality.available:
            unavailable += 1
        else:
            candidate = classify_quality(quality)
            if candidate is not None:
                candidate_count += 1
                candidates.append(candidate)

        # Avoid flooding the GUI queue on very large libraries while still
        # keeping progress responsive.
        if progress is not None and (index == total or index % 10 == 0):
            progress(index, total)

    candidates.sort(
        key=lambda item: (
            item.severity,
            -item.quality.overall_score,
            str(item.photo.path).casefold(),
        ),
        reverse=True,
    )
    if len(candidates) > max_results:
        candidates = candidates[:max_results]

    return BadShotScan(
        candidates=tuple(candidates),
        analyzed_count=analyzed,
        unavailable_count=unavailable,
        candidate_count=candidate_count,
        cancelled=cancelled,
    )
