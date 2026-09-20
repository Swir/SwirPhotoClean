"""Synthetic duplicate-heavy scanner benchmark for development/regression checks."""
from __future__ import annotations

import argparse
import shutil
import tempfile
import time
import tracemalloc
from pathlib import Path

from PIL import Image, ImageDraw

from photoclean.core import scan


def create_fixture(path: Path, size: tuple[int, int]) -> None:
    image = Image.new("RGB", size, "#16212b")
    draw = ImageDraw.Draw(image)
    width, height = size
    draw.rectangle((width // 12, height // 10, width // 2, height * 4 // 5), fill="#16a6c9")
    draw.ellipse((width // 2, height // 5, width * 11 // 12, height * 4 // 5), fill="#d15b37")
    draw.line((0, height - 1, width - 1, 0), fill="white", width=max(2, width // 200))
    image.save(path, quality=92)


def run(count: int, width: int, height: int) -> None:
    if count < 2:
        raise ValueError("count must be at least 2")
    with tempfile.TemporaryDirectory(prefix="swirphotoclean-duplicate-bench-") as directory:
        root = Path(directory)
        original = root / "photo-00000.jpg"
        create_fixture(original, (width, height))
        for index in range(1, count):
            shutil.copy2(original, root / f"photo-{index:05d}.jpg")

        tracemalloc.start()
        started = time.perf_counter()
        result = scan([root], include_similar=False, performance_profile="fast")
        elapsed = time.perf_counter() - started
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        exact = [group for group in result.groups if group.kind == "exact"]
        if result.cancelled or len(result.photos) != count or len(exact) != 1 or len(exact[0].photos) != count:
            raise RuntimeError("benchmark scan produced unexpected results")

        print(f"files={count}")
        print(f"dimensions={width}x{height}")
        print(f"elapsed_seconds={elapsed:.3f}")
        print(f"files_per_second={count / elapsed:.1f}")
        print(f"tracemalloc_peak_mib={peak / (1024 * 1024):.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark a duplicate-heavy SwirPhotoClean scan")
    parser.add_argument("--count", type=int, default=250)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    args = parser.parse_args()
    run(args.count, args.width, args.height)


if __name__ == "__main__":
    main()
