# Review Power Mode

SWIR PhotoClean 1.0 review work is intentionally **review-first**. This layer makes large duplicate/similar groups faster to inspect without changing detection, Smart Keep scoring, saved scan results or Recycle Bin safety.

## Filter and sort

The file list in the active group includes a live filter and deterministic sort options:

- **Smart Keep first** — places the existing explainable Smart Keep recommendation first for similar-photo groups. It never marks the recommendation or any other file for cleanup.
- **Scan order** — restores the stable order emitted by the scanner.
- **Name A→Z** — case-insensitive filename/path order.
- **Largest file** — descending file size.
- **Highest resolution** — descending pixel count, then file size.

Filtering is local and non-destructive. Whitespace-separated terms use AND matching across the full path, filename, extension, dimensions and raw byte size. Clearing the filter restores hidden rows with their original group identity. Existing cleanup marks remain unchanged while filtering or sorting.

## Keyboard Power Mode

| Shortcut | Action |
| --- | --- |
| `Ctrl+F` | Focus/select the current-group filter |
| `Ctrl+↑` / `Ctrl+↓` | Previous / next result group |
| `Alt+↑` / `Alt+↓` | Previous / next visible file |
| `Ctrl+M` | Mark/unmark the selected file(s) for Recycle Bin review |
| `Ctrl+Shift+M` | Clear all cleanup marks |
| `Ctrl+C` | Copy selected full paths when the file list has focus |
| `F11` | Fullscreen compare for exactly two selected photos |
| `F1` | Show shortcut help |

There is deliberately **no keyboard shortcut that starts Recycle Bin cleanup**. Moving files still requires the explicit cleanup button, the normal revalidation path, group protection and a user confirmation dialog.

## Safety invariants

Review Power Mode does not:

- modify `ScanResult` groups or photo order,
- auto-mark Smart Keep alternatives for cleanup,
- bypass Safe Mode,
- bypass pre-cleanup SHA-256/file revalidation,
- allow all members of a group to be selected,
- add any permanent-delete fallback.

Tree row IDs remain the original group indices even when the visible list is sorted or filtered. This keeps compare, mark, copy-path and cleanup planning mapped to the original scanned `Photo` records.
