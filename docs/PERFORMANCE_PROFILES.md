# Performance Profiles

SWIR PhotoClean provides three scanner profiles. They tune file-reading and cooperative scheduling only; **they do not change SHA-256 exact matching, similarity thresholds, image signatures, Smart Keep rules, or Recycle Bin safety**.

| Profile | SHA-256 read chunk | Cooperative yield | Intended use |
| --- | ---: | ---: | --- |
| Eco | 256 KiB | every 1 MiB | Prefer responsiveness and lower short-lived I/O buffers on slower/busy systems. |
| Balanced | 1 MiB | every 8 MiB | Default. General Windows 10/11 use. |
| Fast | 4 MiB | none beyond cancellation checkpoints | Reduce Python read-loop overhead on fast local storage. |

The scanner still runs in a background worker. All profiles keep cancellation checkpoints during hashing, image decode stages, directory traversal, exact grouping and similar-photo grouping. Large directory lists are sorted in place to avoid allocating an additional full list merely for deterministic traversal.

## Safety and determinism

- A profile is captured when a scan starts; changing the menu while a scan is running affects only the next scan.
- Exact duplicates always use the full-file SHA-256 digest.
- Similar-photo detection uses the same visual data and threshold under every profile.
- An incomplete/cancelled scan still clears actionable groups and cannot be used for cleanup.
- Cleanup revalidation keeps its conservative default hashing path and never uses a permanent-delete fallback.

## Settings

The selection is stored locally in `performance.json` next to the existing application settings. It is deliberately separate from `settings.json`, so language persistence and performance persistence cannot overwrite each other. Invalid/corrupt values safely fall back to `Balanced`.

## Benchmarking

A manual benchmark is available:

```powershell
python tools/benchmark_scan_profiles.py --count 80 --runs 3
```

It generates temporary fixtures, runs all profiles, reports median time / throughput / peak traced Python memory, and fails if any profile changes the resulting photos or groups. There is intentionally no fixed timing threshold in CI because disk/cache/runner differences would make it unreliable.
