# Fullscreen Compare + integrated Difference View

The primary fullscreen review path in SWIR PhotoClean keeps the two-photo compare workflow fast while making pixel differences, EXIF context and explainable quality signals available without opening a second review workflow.

## Controls

- `F11` opens fullscreen compare for exactly two selected photos from the active group.
- Mouse wheel or `+` / `-` changes the synchronized zoom.
- Drag either pane to pan both panes using the same relative center.
- `R` resets zoom and pan.
- `D` or the **Differences** button toggles the right pane between the second source photo and a bounded Difference View heatmap.
- `Esc` closes fullscreen compare.

## Review insights

Each source-photo pane includes read-only context intended to make a manual review decision easier:

- Photo Quality Score with local sharpness and exposure components;
- camera/device label from EXIF `Make` / `Model` when present;
- capture time and the EXIF tag that supplied it when present;
- Smart Keep status for the currently compared pair.

For visually similar files, Smart Keep identifies one suggested copy and reports its score and confidence. This remains a recommendation only; the alternative stays fully visible for manual review and no selection state changes automatically.

For exact byte-identical copies, fullscreen review reports the pair as equivalent instead of pretending that one copy has better visual quality. Missing EXIF is shown as missing; filesystem timestamps and filenames are not substituted as capture evidence.

## Difference mode

Difference mode is built lazily only when requested. The left pane remains the reference image and the right pane becomes the existing local Difference View heatmap. The metadata line reports:

- percentage of analyzed pixels above the difference threshold;
- mean channel delta on a 0–255 scale;
- analysis dimensions and threshold.

If source dimensions differ, the Difference View uses the same bounded normalization rules as `photoclean/difference.py`; this is a review aid, not evidence that two images are interchangeable.

Toggling Difference View back to the source photo restores that photo's quality, EXIF and Smart Keep context.

## Safety

Fullscreen compare, review insights and Difference View are read-only. They do not change review marks, modify source files or expose file-operation controls. Quality and Smart Keep values are advisory only, EXIF metadata is read without editing, the existing 40-megapixel preview limit remains enforced, Difference View stays bounded to its existing analysis-size limit, and closing or toggling the window does not alter `ScanResult`.

The normal application safety path remains separate and still requires explicit user action and the existing validation checks.
