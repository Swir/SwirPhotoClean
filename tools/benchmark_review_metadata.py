"""Reproducible local benchmark for read-only metadata review tools.

This is intentionally not a CI pass/fail test. Disk, antivirus and filesystem
cache differences make absolute time thresholds unreliable. Use the reported
median throughput to compare changes on the same machine.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import tempfile
import threading
import time
import tracemalloc
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from photoclean.classification import analyze_media_types
from photoclean.core import read_photo
from photoclean.library import analyze_library_metadata


def build_fixture(folder: Path, count: int):
    cancel = threading.Event()
    photos = []
    for index in range(count):
        width = 320 + (index % 5) * 8
        height = 240 + (index % 7) * 8
        image = Image.new(
            "RGB",
            (width, height),
            ((index * 29) % 255, (index * 47) % 255, (index * 71) % 255),
        )
        exif = Image.Exif()
        if index % 3 != 0:
            exif[271] = "SWIR Bench"
            exif[272] = f"Device-{index % 8}"
            exif[36867] = f"2026:09:{1 + (index % 19):02d} 12:{index % 60:02d}:00"
        path = folder / f"bench-{index:05d}.jpg"
        image.save(path, format="JPEG", quality=82, exif=exif)
        photos.append(read_photo(path, cancel))
    return tuple(photos)


def measure(label: str, func, photos, repeat: int):
    samples = []
    peaks = []
    for _ in range(repeat):
        tracemalloc.start()
        started = time.perf_counter()
        report = func(photos)
        elapsed = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        if report.analyzed_count != len(photos):
            raise RuntimeError(f"{label}: analyzed {report.analyzed_count}/{len(photos)}")
        samples.append(elapsed)
        peaks.append(peak)
    median = statistics.median(samples)
    throughput = len(photos) / median if median else float("inf")
    return median, throughput, max(peaks)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=500, help="synthetic images to inspect (default: 500)")
    parser.add_argument("--repeat", type=int, default=3, help="timed repetitions per inspector (default: 3)")
    args = parser.parse_args()
    if args.count < 1 or args.repeat < 1:
        parser.error("--count and --repeat must be positive")

    with tempfile.TemporaryDirectory(prefix="swirphotoclean-bench-") as temp:
        folder = Path(temp)
        photos = build_fixture(folder, args.count)
        print(f"fixture: {len(photos)} JPEG files")
        for label, func in (
            ("EXIF Library Explorer", analyze_library_metadata),
            ("Media Type Inspector", analyze_media_types),
        ):
            median, throughput, peak = measure(label, func, photos, args.repeat)
            print(
                f"{label}: median={median:.3f}s  throughput={throughput:.1f} files/s  "
                f"python_peak={peak / (1024 * 1024):.2f} MiB"
            )

    print("Note: compare results only on the same machine/storage; this benchmark has no release gate threshold.")


if __name__ == "__main__":
    main()
