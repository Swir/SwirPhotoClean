"""Read-only blur/exposure review candidates for completed photo scans.

The finder deliberately reports *possible* issues. It never marks, moves or
deletes files and it does not treat an artistic soft/dark/high-key photograph as
objectively bad. Results are ordered review hints backed by the same bounded,
local quality analysis used by Smart Keep.
"""
from __future__ import annotations

import heapq
from collections.abc import Sized
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


def _candidate_sort_key(item: BadShotCandidate) -> tuple[float, float, str]:
    """Match the historical highest-priority-first candidate ordering."""

    return (
        item.severity,
        -item.quality.overall_score,
        str(item.photo.path).casefold(),
    )


def _stream_with_total(photos: Iterable[Photo]) -> tuple[Iterable[Photo], int]:
    """Avoid copying normal scanner lists while preserving progress totals.

    ``ScanResult.photos`` is a sized list, so the production path can stream it
    directly. Unsized iterables are materialized only as a compatibility fallback
    because the public progress callback expects a stable total count.
    """

    if isinstance(photos, Sized):
        return photos, len(photos)
    items = tuple(photos)
    return items, len(items)


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
    are inspected unless cancellation is requested. For normal sized scanner
    inputs the function streams the existing list directly, and candidate
    retention is bounded to ``max_results`` with a small heap instead of storing
    every flagged photo before sorting.
    """

    if max_results < 1:
        raise ValueError("max_results must be at least 1")

    items, total = _stream_with_total(photos)
    retained: list[tuple[tuple[float, float, str], int, BadShotCandidate]] = []
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
                # Higher sort keys are higher review priority. ``-index`` keeps
                # equal-key behavior stable with the previous full-list sort:
                # earlier input wins the max_results cutoff.
                entry = (_candidate_sort_key(candidate), -index, candidate)
                if len(retained) < max_results:
                    heapq.heappush(retained, entry)
                elif entry[:2] > retained[0][:2]:
                    heapq.heapreplace(retained, entry)

        # Avoid flooding the GUI queue on very large libraries while still
        # keeping progress responsive.
        if progress is not None and (index == total or index % 10 == 0):
            progress(index, total)

    ordered = tuple(
        entry[2]
        for entry in sorted(retained, key=lambda entry: (entry[0], entry[1]), reverse=True)
    )

    return BadShotScan(
        candidates=ordered,
        analyzed_count=analyzed,
        unavailable_count=unavailable,
        candidate_count=candidate_count,
        cancelled=cancelled,
    )
