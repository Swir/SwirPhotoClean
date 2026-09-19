"""Manual large-library benchmark for scanner profiles; no fixed timing gate.

The benchmark uses generated photos only. It verifies that Eco/Balanced/Fast
produce identical scan results, records traced Python peak memory, and measures
cooperative cancellation latency without touching cleanup or the Recycle Bin.
"""
from __future__ import annotations

import argparse
import json
import shutil
import statistics
import tempfile
import threading
import time
import tracemalloc
from pathlib import Path

from PIL import Image, ImageDraw

from photoclean.core import scan
from photoclean.performance import PROFILES


def fixture(path: Path, index: int, size=(1600, 900)):
    image = Image.new("RGB", size, (30 + index % 80, 50, 90))
    draw = ImageDraw.Draw(image)
    width, height = size
    draw.rectangle(
        (max(10, width // 25 + index % 40), max(10, height // 12), width * 3 // 7, height * 7 // 10),
        fill=(130, 80 + index % 100, 60),
    )
    draw.ellipse(
        (width * 5 // 9, height // 8, width * 8 // 9, height * 17 // 20),
        fill=(45, 140, 90 + index % 100),
    )
    draw.text((max(10, width // 20), max(10, height * 17 // 20)), f"SWIR {index:05d}", fill="white")
    image.save(path, quality=91)


def canonical(result):
    return (
        tuple((photo.path.name, photo.digest, photo.dhash, photo.color) for photo in result.photos),
        tuple((group.kind, tuple(photo.path.name for photo in group.photos)) for group in result.groups),
    )


def run_once(root: Path, profile: str):
    tracemalloc.start()
    started = time.perf_counter()
    result = scan([root], performance_profile=profile)
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return elapsed, peak, result


def cancellation_probe(root: Path, profile: str, cancel_after: int):
    cancel = threading.Event()
    progress_count = 0
    requested_at = None

    def progress(_message):
        nonlocal progress_count, requested_at
        progress_count += 1
        if requested_at is None and progress_count >= cancel_after:
            requested_at = time.perf_counter()
            cancel.set()

    started = time.perf_counter()
    result = scan([root], performance_profile=profile, cancel=cancel, progress=progress)
    finished = time.perf_counter()
    if requested_at is None:
        raise RuntimeError(f"profile {profile}: cancellation trigger was not reached")
    if not result.cancelled:
        raise RuntimeError(f"profile {profile}: scan did not report cancellation")
    if result.groups:
        raise RuntimeError(f"profile {profile}: cancelled scan exposed actionable groups")
    return {
        "trigger_after_progress_events": cancel_after,
        "photos_observed": len(result.photos),
        "cancel_latency_ms": round((finished - requested_at) * 1000, 3),
        "elapsed_ms": round((finished - started) * 1000, 3),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark Eco/Balanced/Fast profiles on a generated photo library."
    )
    parser.add_argument("--count", type=int, default=250, help="generated unique photos")
    parser.add_argument("--runs", type=int, default=2, help="full runs per profile")
    parser.add_argument("--width", type=int, default=1600, help="generated image width")
    parser.add_argument("--height", type=int, default=900, help="generated image height")
    parser.add_argument(
        "--duplicate-every",
        type=int,
        default=10,
        help="add one exact copy for every N unique photos (0 disables copies)",
    )
    parser.add_argument(
        "--cancel-after",
        type=int,
        default=25,
        help="request cancellation after this many progress events",
    )
    parser.add_argument("--json", type=Path, help="optional JSON report path")
    args = parser.parse_args()

    if args.count < 2 or args.runs < 1:
        raise SystemExit("--count must be >= 2 and --runs >= 1")
    if args.width < 64 or args.height < 64:
        raise SystemExit("--width and --height must be >= 64")
    if args.duplicate_every < 0:
        raise SystemExit("--duplicate-every must be >= 0")
    if args.cancel_after < 1:
        raise SystemExit("--cancel-after must be >= 1")

    with tempfile.TemporaryDirectory(prefix="swir-photoclean-profile-bench-") as folder:
        root = Path(folder)
        for index in range(args.count):
            fixture(root / f"photo-{index:05d}.jpg", index, (args.width, args.height))

        duplicate_count = 0
        if args.duplicate_every:
            for index in range(0, args.count, args.duplicate_every):
                shutil.copy2(root / f"photo-{index:05d}.jpg", root / f"copy-{index:05d}.jpg")
                duplicate_count += 1

        total_files = args.count + duplicate_count
        cancel_trigger = min(args.cancel_after, max(1, total_files))
        report = {
            "fixture": {
                "unique_photos": args.count,
                "exact_copies": duplicate_count,
                "total_files": total_files,
                "width": args.width,
                "height": args.height,
            },
            "runs_per_profile": args.runs,
            "profiles": {},
        }

        reference = None
        for profile in PROFILES:
            timings = []
            peaks = []
            latest = None
            for _ in range(args.runs):
                elapsed, peak, latest = run_once(root, profile)
                timings.append(elapsed)
                peaks.append(peak)

            current = canonical(latest)
            if reference is None:
                reference = current
            elif current != reference:
                raise RuntimeError(f"profile {profile} changed scan results")

            median_seconds = statistics.median(timings)
            throughput = len(latest.photos) / median_seconds
            cancellation = cancellation_probe(root, profile, cancel_trigger)
            profile_report = {
                "median_seconds": round(median_seconds, 6),
                "throughput_photos_per_second": round(throughput, 3),
                "peak_traced_mib": round(max(peaks) / (1024 * 1024), 3),
                "photos": len(latest.photos),
                "groups": len(latest.groups),
                "cancel": cancellation,
            }
            report["profiles"][profile] = profile_report
            print(
                f"{profile:8s} median={median_seconds:.3f}s "
                f"throughput={throughput:.1f} photos/s "
                f"peak={profile_report['peak_traced_mib']:.1f} MiB "
                f"cancel={cancellation['cancel_latency_ms']:.1f} ms"
            )

        if args.json:
            destination = args.json.expanduser().resolve()
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(f"JSON report: {destination}")


if __name__ == "__main__":
    main()
