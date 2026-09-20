# Performance Profiles

SWIR PhotoClean provides three scanner profiles. They tune file-reading and cooperative scheduling only; **they do not change SHA-256 exact matching, similarity thresholds, image signatures, Smart Keep rules, or Recycle Bin safety**.

| Profile | SHA-256 read chunk | Cooperative yield | Intended use |
| --- | ---: | ---: | --- |
| Eco | 256 KiB | every 1 MiB | Prefer responsiveness and lower short-lived I/O buffers on slower/busy systems. |
| Balanced | 1 MiB | every 8 MiB | Default. General Windows 10/11 use. |
| Fast | 4 MiB | none beyond cancellation checkpoints | Reduce Python read-loop overhead on fast local storage. |

The scanner still runs in a background worker. All profiles keep cancellation checkpoints during hashing, image decode stages, directory traversal, exact grouping and similar-photo grouping. Large directory lists are sorted in place to avoid allocating an additional full list merely for deterministic traversal.

## Large-photo memory behavior

The scanner avoids unnecessary full-resolution intermediate image buffers on the common camera-photo path. An opaque RGB image whose EXIF orientation is already normal can be analyzed directly instead of always creating a full-size EXIF-transposed copy, RGBA copy, white matte and second RGB copy. Files that really need orientation correction still use EXIF transpose, while alpha/transparency still uses the same explicit white-matte behavior as before.

This optimization changes allocation behavior only. The resulting oriented dimensions, dHash, low-resolution color signature and full-file SHA-256 remain governed by the same rules, and regression tests cover the opaque fast path, transparent white matte and rotated EXIF path.

## Similarity-index memory behavior

The similar-photo BK-tree now uses slot-based nodes and allocates collision buckets and child dictionaries only when a node actually needs them. The review grouping phase also allocates a members list only after an anchor receives its first real similar-photo match. A mostly unique library therefore no longer pays for one collision list, one empty child dictionary and one singleton review bucket per perceptual-hash anchor.

This is a container-layout optimization only: dHash radius checks, color/aspect verification, fixed-anchor grouping, exact SHA-256 expansion and cancellation semantics are unchanged. Regression tests exercise unique hashes, identical-hash collisions and radius queries.

A deterministic in-memory benchmark is available for comparing similarity-index revisions on the same machine:

```powershell
python tools/benchmark_similarity_index.py --count 50000
```

To stress dHash collisions as well:

```powershell
python tools/benchmark_similarity_index.py --count 50000 --collision-every 20
```

The benchmark uses synthetic `Photo` records only and never scans personal files or performs cleanup. It reports build throughput, traced Python peak memory and sampled query time; there is intentionally no universal pass/fail memory threshold because Python/runtime versions and machine characteristics differ.

## Photo-record memory behavior

Every successful image kept in a scan result is represented by a `Photo` record. These records now use dataclass slots, removing the per-instance dynamic attribute dictionary while keeping the same immutable fields, equality behavior and pickling compatibility. This reduces steady Python object overhead for large libraries without changing SHA-256 evidence, visual signatures, paths, cleanup revalidation or session semantics.

A deterministic synthetic benchmark compares the current record layout with the former dictionary-backed dataclass layout:

```powershell
python tools/benchmark_photo_records.py --count 100000
```

The benchmark shares payload values where practical so the reported difference focuses on record-container overhead. Results are intended for before/after comparisons on the same Python runtime rather than as a universal pass/fail threshold.

## Safety and determinism

- A profile is captured when a scan starts; changing the menu while a scan is running affects only the next scan.
- Exact duplicates always use the full-file SHA-256 digest.
- Similar-photo detection uses the same visual data and threshold under every profile.
- An incomplete/cancelled scan still clears actionable groups and cannot be used for cleanup.
- Cleanup revalidation keeps its conservative default hashing path and never uses a permanent-delete fallback.

## Settings

The selection is stored locally in `performance.json` next to the existing application settings. It is deliberately separate from `settings.json`, so language persistence and performance persistence cannot overwrite each other. Invalid/corrupt values safely fall back to `Balanced`.

## Large-library benchmark

A manual generated-library benchmark is available:

```powershell
python tools/benchmark_scan_profiles.py --count 250 --runs 2 --json benchmark.json
```

The default fixture uses 250 unique 1600×900 JPEGs plus periodic exact copies. For every profile it reports median scan time, throughput, peak traced Python memory and cooperative cancellation latency. It also fails if Eco/Balanced/Fast produce different photo/group results, if a cancellation request is not observed, or if a cancelled scan exposes actionable groups.

For a heavier manual stress run, increase both library size and pixel count, for example:

```powershell
python tools/benchmark_scan_profiles.py --count 1000 --runs 1 --width 2400 --height 1600 --cancel-after 50 --json large-library.json
```

To focus on the high-resolution allocation path, use fewer but much larger generated photos (still below the 40 MP safety limit), for example:

```powershell
python tools/benchmark_scan_profiles.py --count 120 --runs 1 --width 6000 --height 4000 --cancel-after 15 --json highres-library.json
```

The benchmark never performs cleanup and never calls the Recycle Bin. There is intentionally no fixed timing or memory threshold in CI because storage, cache state, antivirus activity and runner hardware make those values environment-dependent; the JSON output is intended for regression comparison on the same machine.
