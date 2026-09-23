# Review metadata safety — Burst Cleaner and media classification

Burst Cleaner and screenshot/graphic/camera classification are **review-only** features. They never mark files for removal and they never bypass the normal cleanup revalidation or Windows Recycle Bin path.

## Burst evidence rules

A burst candidate is only built from members of an existing visually-similar group. Byte-identical copies are collapsed by full SHA-256 digest, and capture timing comes from embedded EXIF metadata only. Filenames and filesystem modification times are never used as substitutes for capture evidence. If two frames identify different cameras/devices, they are not joined into one burst sequence.

## Classification evidence rules

Media classification uses conservative local evidence such as embedded camera metadata, the scanned dimensions, image format, alpha/palette characteristics and known screen dimensions. A screenshot/graphic label remains a review candidate, not a cleanup decision. The classifier now uses the same shared EXIF parser as Burst Cleaner so standard nested camera metadata is interpreted consistently.

## Stable metadata reads

A scan result can remain open while files on disk change. Both review paths therefore treat the saved `Photo` filesystem signature as part of their evidence:

1. the file and its path ancestry must not cross a symlink, junction or reparse point;
2. the current path metadata must match the object recorded by the scan;
3. Pillow receives an already-open binary handle whose filesystem identity matches that saved object;
4. the path is checked again after the metadata read.

If any check fails, Burst Cleaner excludes the frame and media classification reports the entry as unavailable/unknown. The features prefer missing review evidence over evidence from a stale or substituted path.

This does **not** turn review metadata into deletion authorization. A later cleanup request still goes through the normal full content and keeper revalidation immediately before the Windows Recycle Bin operation.
