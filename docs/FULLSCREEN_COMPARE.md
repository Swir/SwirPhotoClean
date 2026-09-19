# Fullscreen Compare + integrated Difference View

The primary fullscreen review path in SWIR PhotoClean keeps the two-photo compare workflow fast while making pixel differences available without opening a second review workflow.

## Controls

- `F11` opens fullscreen compare for exactly two selected photos from the active group.
- Mouse wheel or `+` / `-` changes the synchronized zoom.
- Drag either pane to pan both panes using the same relative center.
- `R` resets zoom and pan.
- `D` or the **Differences** button toggles the right pane between the second source photo and a bounded Difference View heatmap.
- `Esc` closes fullscreen compare.

## Difference mode

Difference mode is built lazily only when requested. The left pane remains the reference image and the right pane becomes the existing local Difference View heatmap. The metadata line reports:

- percentage of analyzed pixels above the difference threshold;
- mean channel delta on a 0–255 scale;
- analysis dimensions and threshold.

If source dimensions differ, the Difference View uses the same bounded normalization rules as `photoclean/difference.py`; this is a review aid, not evidence that two images are interchangeable.

## Safety

Fullscreen compare and Difference View are read-only:

- no cleanup mark is created or cleared;
- no file is rewritten;
- no Recycle Bin operation is exposed from the fullscreen window;
- the existing 40-megapixel preview limit remains enforced;
- Difference View stays bounded to its existing analysis-size limit;
- closing or toggling Difference View does not alter `ScanResult`.

The normal cleanup path still requires explicit user marking, group protection, pre-operation file revalidation, the Recycle Bin button and confirmation.
