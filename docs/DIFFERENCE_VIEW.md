# Difference View

Difference View is a read-only review tool for two photos selected from the same result group. It is designed to make small edits, crop/resample effects and export differences easier to inspect without changing the cleanup selection.

## Open it

1. Finish or load a scan.
2. Select one result group.
3. Select exactly two photos in that group.
4. Choose **View → Difference view…** or press `Ctrl+Alt+D`.

The window shows a bounded cyan-on-dark heatmap. Dark areas are similar; brighter areas have a larger pixel delta.

## Metrics

- **Pixels above threshold** is the percentage of analysis pixels whose grayscale delta is above the preview threshold.
- **Mean difference** is the average RGB-channel delta on a `0..255` scale.
- **Change bounds** reports the bounding box containing thresholded changes when one exists.
- If the photos have different dimensions, the preview is explicitly marked as **resampled**. Resampling is used only for the visualization and does not alter either source file.

The preview is bounded to a maximum analysis side so very large photos do not create an unbounded comparison buffer. Normal image safety limits still apply.

## Controls

- Mouse wheel or `+` / `-`: zoom the heatmap.
- Drag: pan.
- `R`: fit/reset view.
- `Esc`: close.

## Safety

Difference View is intentionally non-destructive:

- source files are opened read-only;
- no image is rewritten or exported;
- the current Recycle Bin marks are not changed;
- no file is automatically selected for cleanup;
- a visual difference is never treated as proof that one photo is safe to delete.

Use Fullscreen Compare and metadata/quality information together with Difference View before making a cleanup decision.
