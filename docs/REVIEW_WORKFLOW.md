# Review workflow

SWIR PhotoClean is review-first. Similar photos are never treated as safe-to-delete duplicates, and the application never marks files for removal automatically.

## Fast review

1. Select a result group.
2. Select up to two photos in the file list.
3. Double-click either preview, or press **F11**, to open the fullscreen comparison view when two photos are selected.
4. Use the mouse wheel or `+` / `-` to zoom both images together.
5. Drag either image to pan both views to the same relative area.
6. Press `R` or **Fit** to return to fitted view. Press `Esc` to close the comparison window.

The synchronized view is relative rather than pixel-locked, so images with different resolutions can still be compared at corresponding areas.

## Smart Keep

For visually similar photos, Smart Keep can highlight one review candidate based on explainable quality signals. It is a suggestion only. Exact byte-identical duplicates remain equivalent from the application's point of view.

## Session save / resume

Use **Session → Save session…** (`Ctrl+S`) after a completed scan to store review metadata. Use **Session → Open session…** (`Ctrl+O`) to resume later. Recycle Bin selections are deliberately excluded from session files and cleared when a session is loaded.

## Safety

Moving files still requires an explicit user selection and confirmation. Before any Recycle Bin operation the application revalidates the selected files and refuses to proceed when the safe Windows Recycle Bin path cannot be confirmed. There is no fallback to permanent deletion.
