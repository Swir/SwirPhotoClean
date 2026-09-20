# Blur / Bad-Shot Review

SWIR PhotoClean includes a **read-only review aid** for photos that may deserve a closer look because of very low sharpness, severe exposure problems, or a low combined local quality score.

## Safety model

- The feature never selects a file for the Recycle Bin.
- It never moves, deletes, renames or rewrites a photo.
- Analysis is local and uses the same bounded Pillow-based quality signals as Smart Keep.
- A flagged photo is only a **review candidate**, not a verdict that the image is bad.
- Intentional soft focus, low-key/high-key photography, scans, screenshots and minimalist images can legitimately cross the heuristic thresholds.
- Unavailable/corrupt files are counted separately and are not silently scored as poor-quality images.

## What is measured

The current conservative pass uses three signals from `photoclean.quality`:

- sharpness below a low threshold → `possible-blur`,
- exposure score below a low threshold → `exposure-risk`,
- combined score below a low threshold → `low-overall`.

The UI orders candidates by review priority and shows the underlying quality, sharpness and exposure values so the user can understand why an image appeared.

## Performance and cancellation

The review is started on demand from **View → Blur / bad-shot review…** (`Ctrl+Shift+B`). Analysis runs on a worker thread; Tk is updated only through the GUI event queue. The operation can be cancelled at any time.

For the normal production input (`ScanResult.photos`, a sized list), the finder now streams the existing collection directly instead of first duplicating every photo reference into another tuple. Candidate retention is also bounded: only the highest-priority `max_results` rows are kept in a min-heap while `candidate_count` still records every flagged photo. With the default limit this means the review table retains at most 300 candidate objects regardless of how many lower-priority candidates are found. The final order is intentionally identical to the previous full-list sort, including stable handling at the cutoff.

Unsized custom iterables are still materialized as a compatibility fallback because the existing progress callback requires a stable total count. The desktop application does not use that fallback path.

A dedicated manual benchmark is available as `python tools/benchmark_bad_shot_retention.py`. It uses synthetic in-memory `Photo` records and a deterministic analyzer, touches no source photos, and reports elapsed time plus `tracemalloc` peak memory without imposing a brittle timing gate.

## Limitations

This is not an AI aesthetic judge, face-quality detector, subject-aware focus detector or automatic cleanup system. It cannot know whether blur, darkness or highlights are intentional. Use the result together with the image preview and original context before making any cleanup decision.
