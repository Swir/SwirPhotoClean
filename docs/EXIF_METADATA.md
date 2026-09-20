# EXIF evidence used by review features

SWIR PhotoClean treats embedded metadata as **review evidence**, never as an automatic cleanup decision. Timeline, Camera/Device Groups and Burst Cleaner stay read-only and never mark a file for the Recycle Bin.

## Capture-time priority

The shared parser reads the standard nested **Exif IFD** used by cameras and phones and keeps compatibility with older files that expose the same tags at the top level. Capture time is considered in this order:

1. `DateTimeOriginal`
2. `DateTimeDigitized`
3. `DateTime`

When the matching `SubSecTime*` tag is present, up to six fractional-second digits are preserved. Missing or malformed timestamps are reported as missing metadata; the application does **not** guess capture time from filenames, folders or filesystem modification time.

## Camera/device identity

Camera groups use EXIF `Make` and `Model`. If both values are present they are combined without duplicating the manufacturer when the model already starts with it. Missing device metadata stays unknown rather than being inferred.

Burst Cleaner only considers photos that already belong to a visually similar result group and have EXIF capture times close together. Byte-identical copies are collapsed before burst analysis. When two frames explicitly identify different cameras/devices, they are split into separate burst sequences even if their timestamps are close. Unknown camera metadata does not by itself reject a sequence.

## Safety and limitations

- EXIF analysis is local and read-only.
- No metadata field selects, moves, rewrites or deletes a photo.
- Similar-photo and burst results always require human review.
- EXIF timestamps are treated as the camera's recorded local wall-clock time; timezone normalization is not invented when offset metadata is absent.
- Corrupt or unsupported EXIF affects only metadata-based views and does not weaken exact-duplicate hashing or Recycle Bin safety checks.
