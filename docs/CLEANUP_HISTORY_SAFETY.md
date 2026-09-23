# Cleanup History safety model

Cleanup History is audit metadata only. It records what a cleanup session attempted, what Windows reported as moved to the Recycle Bin, file sizes and SHA-256 values. It is never used as authority to delete or restore a file.

## Stable reads

`cleanup-history.json` is loaded as one bounded snapshot. SwirPhotoClean rejects non-regular/reparse entries, files above the bounded history size, an opened handle that does not match the inspected path, mutation during the read, and a path that changes before validation finishes. Missing history remains the normal empty-history state.

## Semantic validation

Each persisted record is checked before it is shown. Requested/completed counts must match the stored entries, byte totals must be derivable from those entries, reclaimable space is accepted only for moved exact duplicates with a surviving copy, SHA-256 fields must have the expected lowercase form, and boolean fields must be real JSON booleans rather than truthy integers or strings.

This prevents a corrupted or externally replaced history file from inventing cleanup totals or making the UI ingest an unbounded JSON document. Validation failure affects history/diagnostics only; it does not create any fallback deletion path and does not change the Windows Recycle Bin safety contract.
