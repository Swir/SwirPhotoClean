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

For very large groups, detailed quality analysis is bounded to the strongest structural candidates so the review path stays responsive. Missing or unreadable quality evidence is treated as neutral rather than as poor quality.

## Important limitations

Photo quality is subjective. An intentionally soft portrait, a dark night photo, a high-key image or an artistic motion blur can receive a lower heuristic score even when it is the preferred image. The score therefore remains a suggestion that must be reviewed by the user.

The current quality signals do not attempt face-expression ranking, aesthetic ranking, semantic scene understanding or generative AI analysis.

## Safety

Quality analysis is read-only. Recycle Bin rules remain unchanged:

- nothing is automatically selected,
- at least one file must remain in each affected result group,
- files are revalidated before recycling,
- no permanent-delete fallback is allowed.
