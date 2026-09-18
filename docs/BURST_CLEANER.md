# Burst Cleaner

Burst Cleaner is a **review-only** helper for short photo series. It does not mark or remove files.

## Detection rules

A burst is suggested only when all of the following are true:

1. The photos already belong to a `similar` result group produced by the normal scanner.
2. Byte-identical copies are collapsed by SHA-256 digest, so copied files cannot inflate a burst.
3. Each included frame exposes a parseable EXIF capture timestamp (`DateTimeOriginal`, `DateTimeDigitized`, or `DateTime`).
4. Consecutive captures are no more than 3 seconds apart by default.

The feature deliberately **does not** fall back to filenames or filesystem modification time. Missing EXIF means there is not enough evidence to call the files a burst.

## Review workflow

Open **View → Burst Cleaner…** or press `Ctrl+B` after a completed scan. The window lists detected series, the matching result group, frame count, capture span, and the current Smart Keep suggestion. Double-click a series or choose **Open group** to return to the normal review view.

Smart Keep remains a suggestion only. Burst Cleaner never creates Recycle Bin selections automatically, and every eventual move still goes through the normal explicit confirmation and full file revalidation path.

## Limitations

- Cameras or editors that remove EXIF capture timestamps will not produce burst candidates.
- EXIF timestamps usually have one-second resolution, so several frames can legitimately have identical timestamps.
- A visually similar group can contain more than one time-separated burst; Burst Cleaner keeps those sequences separate.
- The current feature does not claim face, expression, motion-blur, or semantic quality analysis.
