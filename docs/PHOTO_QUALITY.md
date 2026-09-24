# Photo Quality Score

SWIR PhotoClean uses a local, read-only quality score as an additional review signal for similar photos and Burst Cleaner sequences.

## What it measures

The score is intentionally simple and explainable:

- **Sharpness** — estimated from edge strength on a bounded grayscale sample.
- **Exposure** — penalizes heavy clipping in deep shadows or highlights and extreme average luminance.
- **Overall quality** — combines sharpness and exposure for review only.

The quality score never marks, moves or deletes a file. It is not an AI model and does not upload photos anywhere.

## Smart Keep + Quality

For similar photos, the enhanced recommendation combines:

- decoded resolution,
- local quality score,
- file-format preference,
- encoded bytes per pixel as a weak tie-breaker.

Resolution remains important, but a clearly soft or strongly clipped frame can lose to a slightly smaller, cleaner frame. Exact duplicate groups bypass subjective scoring because byte-identical files are equivalent.

For very large groups, detailed quality analysis is bounded to the strongest structural candidates so the review path stays responsive. Large individual photos are also reduced to the requested analysis bound before EXIF orientation and grayscale scoring allocate additional pixel buffers; JPEG decoders are asked to downsample early when supported.

## Stable-handle scan-identity guard

A quality result is only a review aid for the exact scan record that produced it. Before opening the image, SWIR PhotoClean checks the lexical file path and its parent chain and rejects symlink, junction or other reparse-point ancestry instead of resolving through it.

The image is then opened once. The authoritative descriptor is matched against the scan-time size, modification timestamp and available device/inode identity and against the object observed immediately before the open. Pillow decodes from a duplicate of that already-bound descriptor rather than reopening the pathname. After analysis, the authoritative descriptor, pathname and path ancestry are checked again before a successful score may be returned.

Successful stable analyses may be cached for responsiveness, but a cache entry is consulted only after the current pathname has been rebound to a matching open descriptor. Missing, replaced, redirected or newly unsafe paths therefore cannot receive an old cached score. Read/decode failures are never cached, so a temporary sharing violation or decoder error can be retried on the next review request.

This guard is deliberately cheaper than the destructive-path validation. It does **not** prove byte identity and does **not** replace the full SHA-256 revalidation performed before any Recycle Bin operation.

## Important limitations

Photo quality is subjective. An intentionally soft portrait, a dark night photo, a high-key image or an artistic motion blur can receive a lower heuristic score even when it is the preferred image. The score therefore remains a suggestion that must be reviewed by the user.

The current quality signals do not attempt face-expression ranking, aesthetic ranking, semantic scene understanding or generative AI analysis.

## Safety

Quality analysis is read-only. Recycle Bin rules remain unchanged:

- nothing is automatically selected,
- at least one file must remain in each affected result group,
- files are revalidated before recycling,
- no permanent-delete fallback is allowed.
