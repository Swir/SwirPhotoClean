# Folder Health Center

Folder Health is a read-only health report for the current SWIR PhotoClean scan. Open it with **View → Folder Health** or `Ctrl+H` after a scan or after resuming a validated session.

## What it reports

The center summarizes the current `ScanResult` without rescanning files:

- number of scanned photos and their combined encoded size;
- exact duplicate groups and the number of extra byte-identical copies;
- conservative **Exact savings** in bytes and as a percentage of the scanned library;
- visually similar photos that still require manual review;
- photos that are outside any duplicate/similar group;
- the largest scanned files, including dimensions and full paths;
- scan warnings/skips, with a prominent warning when a scan was cancelled.

The largest-files table is informational. A large file is not treated as a bad photo and is never selected automatically.

## Conservative savings model

**Exact savings are based only on SHA-256 exact-duplicate evidence already produced by the scanner.** Similar-photo groups never contribute to the savings number.

For every exact digest bucket, Folder Health always preserves at least one member. Membership is deduplicated by path, so repeated or overlapping exact-group records cannot multiply the estimate. In the defensive case of inconsistent metadata for one digest, the largest member is treated as the keeper and only the remaining bytes are counted.

This number means “bytes represented by redundant byte-identical copies in the current scan”. It is not a claim that Windows has already freed that space. Moving files to the Recycle Bin does not guarantee immediately available disk space until the Recycle Bin is emptied.

## Safety boundary

Folder Health does not:

- create or clear cleanup marks;
- move, rename, rewrite or delete source files;
- expose a Recycle Bin action;
- turn similar-photo matches into safe-delete candidates;
- authorize a resumed session for cleanup.

Actual cleanup remains in the normal review workflow. Before any selected file can move, SWIR PhotoClean still preserves at least one group member, revalidates the target and keeper, uses only the Windows Recycle Bin path, and has no permanent-delete fallback.

## Language and large libraries

The center is available in Polish and English. It renders a bounded largest-files list and caps the notice text shown in the window, while the underlying scan result remains unchanged. Refreshing the center recalculates only in-memory summary data and never starts another disk scan.

The largest-files selection uses a bounded top-K heap instead of sorting the complete photo list. Exact groups are streamed from `ScanResult.groups` into the conservative digest buckets without first creating separate exact/similar group lists, and grouped-file counts avoid an additional full union set. These changes preserve the existing ordering and safety semantics while reducing transient CPU/memory overhead on large scans.
