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

The review is started on demand from **View → Blur / bad-shot review…** (`Ctrl+Shift+B`). Analysis runs on a worker thread; Tk is updated only through the GUI event queue. The operation can be cancelled at any time. For very large collections the engine keeps only the highest-priority rows in the table while still reporting the total number of candidates found.

## Limitations

This is not an AI aesthetic judge, face-quality detector, subject-aware focus detector or automatic cleanup system. It cannot know whether blur, darkness or highlights are intentional. Use the result together with the image preview and original context before making any cleanup decision.
