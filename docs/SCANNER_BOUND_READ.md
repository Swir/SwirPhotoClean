# Scanner bound-read safety

SwirPhotoClean 1.0 keeps exact duplicate detection strict while making one candidate read describe one stable filesystem object.

## One handle for hash and pixel analysis

For a newly seen image, the scanner now opens the candidate once, binds that handle to the pre-open `size / mtime / device / inode` identity, hashes the complete file with SHA-256 through that handle, seeks back to the beginning, and gives the same open handle to Pillow for dimensions, EXIF-aware pixel analysis, dHash and the compact colour signature.

The handle identity is rechecked after hashing and after decoding, and the pathname is rechecked after the handle closes. If those identities no longer agree, the candidate is rejected with the structured `changed_during_scan` diagnostic instead of entering exact or similar groups.

This closes the hash-vs-decode pathname-swap window where two opens of the same pathname could theoretically observe different filesystem objects. It also avoids a redundant path open for unique images.

## Exact duplicate semantics stay unchanged

- every candidate is still fully SHA-256 hashed;
- filename, size or timestamp alone never creates an exact match;
- an already verified exact digest may reuse only pixel-analysis results;
- similar-photo groups remain heuristic and review-only;
- cleanup still performs its own operation-time revalidation and Windows Recycle Bin safety checks.

## Regression coverage

`tests/test_core_bound_read.py` verifies that Pillow receives the already-bound hash stream, substituted file handles fail closed, same-size/same-mtime aliases with distinct filesystem identities are rejected where stable file IDs are available, and scan diagnostics preserve the `changed_during_scan` category.

The authoritative 1.0 acceptance gate remains unchanged: physical Windows Recycle Bin move → Restore evidence is still required before 1.0 can be qualified.
