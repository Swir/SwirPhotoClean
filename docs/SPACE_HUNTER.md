# Space Hunter

Space Hunter is a read-only disk-space view for a completed SWIR PhotoClean scan.

## What it shows

- the total size of all successfully scanned photos,
- the number of byte-identical duplicate copies,
- a conservative guaranteed-savings estimate based only on exact SHA-256 groups,
- up to 200 of the largest scanned image files,
- up to 50 parent folders containing the largest total amount of scanned image data,
- whether a large file belongs to an exact duplicate group, a similar-photo review group, or neither.

## Safety model

Space Hunter does not mark, move, rename, rewrite, or delete files. It only consumes the metadata already collected by the completed scan.

The guaranteed-savings figure counts only byte-identical exact duplicate groups. The estimate always preserves one member of every exact digest. Repeated or overlapping exact-group records are collapsed by verified SHA-256 digest, and members that are not present in the authoritative `ScanResult.photos` set cannot inflate the estimate. In the defensive case of inconsistent recorded sizes for one digest, the largest member is treated as the keeper.

Similar-photo groups never contribute to the guaranteed-savings number, because visually similar files may contain different moments, edits, crops, metadata, or quality.

The file table can navigate back to an existing duplicate/similar review group, but the user must still make the cleanup decision in the normal review workflow. Opening Space Hunter never changes the current Recycle Bin selection.

## Performance

The report performs no image decoding and no additional disk hashing. It aggregates existing scan metadata and keeps the displayed file/folder lists bounded so the UI does not attempt to render an unbounded number of rows.

For large libraries, duplicate/similar context is retained only for rows that can actually appear in the bounded largest-files table. Exact savings are aggregated by verified digest rather than by copying per-file context for every duplicate member. This keeps the report conservative while reducing transient memory on duplicate-heavy libraries.
