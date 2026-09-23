# Burst Cleaner review safety

Burst Cleaner is a **review-only** feature. It never marks files for removal and it never bypasses the normal cleanup revalidation or Windows Recycle Bin path.

## Evidence rules

A burst candidate is only built from members of an existing visually-similar group. Byte-identical copies are collapsed by full SHA-256 digest, and capture timing comes from embedded EXIF metadata only. Filenames and filesystem modification times are never used as substitutes for capture evidence. If two frames identify different cameras/devices, they are not joined into one burst sequence.

## Stable metadata reads

A scan result can remain open while files on disk change. Burst review therefore treats the saved `Photo` filesystem signature as part of its evidence:

1. the file and its path ancestry must not cross a symlink, junction or reparse point;
2. the current path metadata must match the object recorded by the scan;
3. the EXIF parser receives an already-open binary handle whose filesystem identity matches that saved object;
4. the path is checked again after the metadata read.

If any check fails, that frame is excluded from burst evidence. The feature prefers an incomplete/no burst suggestion over metadata from a stale or substituted path.

This does **not** turn burst evidence into deletion authorization. A later cleanup request still goes through the normal full content and keeper revalidation immediately before the Windows Recycle Bin operation.
