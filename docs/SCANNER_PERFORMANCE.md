# Scanner performance notes

SwirPhotoClean keeps exact-duplicate detection strict: every candidate file is still read completely and hashed with SHA-256 before it can participate in an exact group. No filename, timestamp, size-only or partial-hash shortcut is used for cleanup evidence.

## Duplicate-heavy libraries

The scanner keeps one successful representative per SHA-256 digest while walking the library. If another file produces the same full digest, SwirPhotoClean reuses the already verified representative's decoded pixel analysis (`width`, `height`, dHash and compact color signature) instead of decoding the identical image again. The duplicate file is still fully hashed and its filesystem signature is revalidated after hashing.

This optimization is safe because exact-group semantics already require matching full SHA-256 digests. It does not change Recycle Bin behavior, pre-delete revalidation, Smart Keep, similar-photo review, or the keep-one rule.

The exact-group index also allocates a members list only after a digest is actually duplicated. Unique photos keep only the representative entry, reducing container overhead for large mostly-unique libraries.

## Similarity candidate hot paths

Similar-photo grouping uses a BK-tree over the 64-bit dHash. Large libraries can contain many images with the same dHash, especially flat screenshots, exported graphics and near-uniform frames. Those candidates live in a collision bucket beneath one BK-tree node.

Collision buckets are cooperatively cancellable: the scanner checks the cancellation event before yielding each collided candidate instead of waiting until the whole bucket has been traversed. This keeps the Cancel action responsive even on a pathological same-hash set and does not change which candidates would be returned by a complete scan.

The compact 8×8 RGB signature comparison also stops accumulating squared colour error as soon as the final acceptance bound has already been exceeded. For scanner-generated signatures this is algebraically the same mean-squared-error decision as before; it only avoids needless channel comparisons for obviously different candidates.

## Regression coverage

`tests/test_core_duplicate_cache.py` verifies that:

- several exact copies perform pixel analysis once,
- different full SHA-256 digests are analyzed independently,
- exact-copy expansion inside a similar-photo group is unchanged.

`tests/test_similarity_cancel_latency.py` additionally verifies that:

- a large same-dHash collision bucket observes cancellation inside the bucket,
- an uncancelled collision query still returns every candidate in order,
- the colour-error acceptance boundary is unchanged,
- obviously different colour signatures short-circuit after the decision is already impossible to recover.

The normal Windows workflow still runs the complete unit/GUI suite, PyInstaller onedir build, packaged `SwirPhotoClean.exe --self-test`, and Portable Mode smoke test.

## Synthetic benchmark

From the repository root:

```powershell
python tools/benchmark_duplicate_scan.py --count 250 --width 1920 --height 1080
```

For profile-level throughput, memory and cancellation measurements:

```powershell
python tools/benchmark_scan_profiles.py --count 250 --width 1920 --height 1080 --cancel-after 25
```

The benchmarks create synthetic images, validate scan semantics and print machine-specific throughput / memory / cancellation measurements. Treat the numbers as regression data rather than a performance promise.
