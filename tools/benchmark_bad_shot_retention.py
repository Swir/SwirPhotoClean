"""Manual memory benchmark for bounded Bad-Shot Finder retention.

Uses synthetic in-memory Photo records and a deterministic analyzer. It performs
no filesystem reads/writes except an optional JSON report and never touches the
Recycle Bin. There is intentionally no fixed timing or memory pass/fail gate.
"""
from __future__ import annotations

import argparse
import json
import time
import tracemalloc
from pathlib import Path

from photoclean.bad_shots import find_bad_shot_candidates
from photoclean.core import Photo
from photoclean.quality import PhotoQuality


class SyntheticPhotos:
    """Sized lazy input matching the production streaming contract."""

    def __init__(self, count: int):
        self.count = count

    def __len__(self):
        return self.count

    def __iter__(self):
        for index in range(self.count):
            yield Photo(
                path=Path(f"synthetic-{index:07d}.jpg"),
                size=2_000_000 + index,
                modified_ns=index + 1,
                device=1,
                inode=index + 1,
                digest=f"{index:064x}"[-64:],
                width=4000,
                height=3000,
                dhash=index & ((1 << 64) - 1),
                color=b"\0" * 192,
            )


def analyzer(photo: Photo) -> PhotoQuality:
    # Keep every synthetic photo below at least one conservative threshold so
    # candidate_count exercises the bounded-retention path heavily.
    index = max(0, photo.inode - 1)
    sharpness = float(index % 20)
    exposure = 35.0 + float(index % 10)
    overall = 20.0 + float(index % 12)
    return PhotoQuality(
        photo=photo,
        available=True,
        overall_score=overall,
        sharpness_score=sharpness,
        exposure_score=exposure,
        dark_clip_percent=0.0,
        light_clip_percent=0.0,
        mean_luma=128.0,
        notes=("synthetic-benchmark",),
        error=None,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark Bad-Shot Finder top-K retention on a lazy synthetic library."
    )
    parser.add_argument("--count", type=int, default=100_000, help="synthetic photos to analyze")
    parser.add_argument("--max-results", type=int, default=300, help="rows retained for review")
    parser.add_argument("--json", type=Path, help="optional JSON report path")
    args = parser.parse_args()

    if args.count < 1:
        raise SystemExit("--count must be >= 1")
    if args.max_results < 1:
        raise SystemExit("--max-results must be >= 1")

    photos = SyntheticPhotos(args.count)
    tracemalloc.start()
    started = time.perf_counter()
    result = find_bad_shot_candidates(
        photos,
        analyzer=analyzer,
        max_results=args.max_results,
    )
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    if result.analyzed_count != args.count:
        raise RuntimeError("benchmark did not analyze the requested photo count")
    if result.candidate_count != args.count:
        raise RuntimeError("synthetic analyzer should flag every photo")
    if len(result.candidates) != min(args.count, args.max_results):
        raise RuntimeError("retained candidate count exceeded or missed the configured bound")

    report = {
        "photos": args.count,
        "candidate_count": result.candidate_count,
        "retained_candidates": len(result.candidates),
        "max_results": args.max_results,
        "elapsed_seconds": round(elapsed, 6),
        "throughput_photos_per_second": round(args.count / elapsed, 3) if elapsed else None,
        "peak_traced_mib": round(peak / (1024 * 1024), 3),
    }
    print(json.dumps(report, indent=2))

    if args.json:
        destination = args.json.expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"JSON report: {destination}")


if __name__ == "__main__":
    main()
