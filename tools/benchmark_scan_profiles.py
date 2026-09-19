"""Manual benchmark for scanner profiles; no pass/fail timing threshold."""
from __future__ import annotations

import argparse
import shutil
import statistics
import tempfile
import time
import tracemalloc
from pathlib import Path

from PIL import Image, ImageDraw

from photoclean.core import scan
from photoclean.performance import PROFILES


def fixture(path: Path, index: int, size=(1280, 720)):
    image = Image.new("RGB", size, (30 + index % 80, 50, 90))
    draw = ImageDraw.Draw(image)
    draw.rectangle((50 + index % 40, 70, 600, 500), fill=(130, 80 + index % 100, 60))
    draw.ellipse((700, 120, 1120, 610), fill=(45, 140, 90 + index % 100))
    draw.text((70, 620), f"SWIR {index:04d}", fill="white")
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


def main():
    parser = argparse.ArgumentParser(description="Benchmark Eco/Balanced/Fast scanner profiles.")
    parser.add_argument("--count", type=int, default=80, help="generated unique photos")
    parser.add_argument("--runs", type=int, default=3, help="runs per profile")
    args = parser.parse_args()
    if args.count < 2 or args.runs < 1:
        raise SystemExit("--count must be >= 2 and --runs >= 1")

    with tempfile.TemporaryDirectory(prefix="swir-photoclean-profile-bench-") as folder:
        root = Path(folder)
        for index in range(args.count):
            fixture(root / f"photo-{index:04d}.jpg", index)
        for index in range(max(1, args.count // 10)):
            shutil.copy2(root / f"photo-{index:04d}.jpg", root / f"copy-{index:04d}.jpg")

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
            throughput = len(latest.photos) / statistics.median(timings)
            print(
                f"{profile:8s} median={statistics.median(timings):.3f}s "
                f"throughput={throughput:.1f} photos/s peak={max(peaks) / (1024 * 1024):.1f} MiB"
            )


if __name__ == "__main__":
    main()
