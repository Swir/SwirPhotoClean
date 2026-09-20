# Scanner performance notes

SwirPhotoClean keeps exact-duplicate detection strict: every candidate file is still read completely and hashed with SHA-256 before it can participate in an exact group. No filename, timestamp, size-only or partial-hash shortcut is used for cleanup evidence.

## Duplicate-heavy libraries

The scanner keeps one successful representative per SHA-256 digest while walking the library. If another file produces the same full digest, SwirPhotoClean reuses the already verified representative's decoded pixel analysis (`width`, `height`, dHash and compact color signature) instead of decoding the identical image again. The duplicate file is still fully hashed and its filesystem signature is revalidated after hashing.

This optimization is safe because exact-group semantics already require matching full SHA-256 digests. It does not change Recycle Bin behavior, pre-delete revalidation, Smart Keep, similar-photo review, or the keep-one rule.

The exact-group index also allocates a members list only after a digest is actually duplicated. Unique photos keep only the representative entry, reducing container overhead for large mostly-unique libraries.

## Regression coverage

`tests/test_core_duplicate_cache.py` verifies that:

- several exact copies perform pixel analysis once,
- different full SHA-256 digests are analyzed independently,
- exact-copy expansion inside a similar-photo group is unchanged.

The normal Windows workflow still runs the complete unit/GUI suite, PyInstaller onedir build, packaged `SwirPhotoClean.exe --self-test`, and Portable Mode smoke test.

## Synthetic benchmark

From the repository root:

```powershell
python tools/benchmark_duplicate_scan.py --count 250 --width 1920 --height 1080
```

The benchmark creates one synthetic JPEG plus exact copies, runs an exact-only Fast-profile scan, validates the resulting exact group, and prints elapsed time, files/second and Python `tracemalloc` peak memory. Treat the numbers as machine-specific regression data rather than a performance promise.
