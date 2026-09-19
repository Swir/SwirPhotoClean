# EXIF Library Explorer

`View -> EXIF library...` (`Ctrl+Alt+L`) is a local, read-only metadata explorer for a completed SWIR PhotoClean scan.

## What it shows

- **Timeline** grouped by year, month and day.
- **Camera / device groups** based on EXIF `Make` and `Model`.
- File counts and total bytes for every visible group.
- Copyable paths for the selected period/device.
- A shortcut to the first duplicate/similar group containing a photo from the selected metadata group.

## Evidence rules

The explorer intentionally prefers missing information over invented information:

- capture time comes only from EXIF `DateTimeOriginal`, then `DateTimeDigitized`, then `DateTime`;
- no filesystem modification-time fallback is used;
- camera/device labels come only from EXIF `Make` and `Model`;
- filenames and folder names are not parsed to guess dates or devices;
- malformed or unavailable metadata is counted and does not change the scan result.

This matters because copied, restored, exported or cloud-synchronized files can have filesystem timestamps unrelated to when the photo was captured.

## Safety and performance

- Metadata analysis runs in a cancellable worker thread; Tk updates remain on the GUI thread.
- Pillow reads image metadata only; the explorer does not rewrite EXIF or source files.
- The feature never marks files for the Recycle Bin and never changes existing review marks.
- Safe Mode and all normal Recycle Bin safeguards remain unchanged.
- A cancelled analysis is partial and clearly labelled as cancelled.

## Limitations

Some images legitimately have no EXIF data. Messaging apps, screenshots, edited exports and privacy tools often remove metadata. Camera names are displayed as supplied by the file and may vary between firmware/apps. EXIF timestamps are local camera times and are not normalized to a timezone unless the source metadata itself provides one; this explorer currently groups by the canonical EXIF local date.
