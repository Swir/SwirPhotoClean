"""Compare slotted Photo-record overhead with the pre-optimization layout."""
from __future__ import annotations

import argparse
import gc
import tracemalloc
from dataclasses import dataclass
from pathlib import Path

from photoclean.core import Photo


@dataclass(frozen=True)
class LegacyPhoto:
    path: Path
    size: int
    modified_ns: int
    device: int
    inode: int
    digest: str
    width: int
    height: int
    dhash: int
    color: bytes


def measure(factory, count: int) -> int:
    shared_path = Path("synthetic.jpg")
    shared_digest = "a" * 64
    shared_color = bytes([32]) * 192
    gc.collect()
    tracemalloc.start()
    records = [
        factory(
            shared_path,
            1,
            1,
            1,
            index + 1,
            shared_digest,
            1920,
            1080,
            index & ((1 << 64) - 1),
            shared_color,
        )
        for index in range(count)
    ]
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    if len(records) != count:
        raise RuntimeError("record allocation mismatch")
    return peak


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure Photo record container overhead without reading real files."
    )
    parser.add_argument("--count", type=int, default=100_000, help="synthetic records")
    args = parser.parse_args()
    if args.count < 1:
        raise SystemExit("--count must be >= 1")

    slotted_peak = measure(Photo, args.count)
    legacy_peak = measure(LegacyPhoto, args.count)
    savings = max(0, legacy_peak - slotted_peak)

    print(f"records={args.count}")
    print(f"slotted_peak_mib={slotted_peak / (1024 * 1024):.3f}")
    print(f"legacy_peak_mib={legacy_peak / (1024 * 1024):.3f}")
    print(f"estimated_savings_mib={savings / (1024 * 1024):.3f}")
    print(f"estimated_savings_bytes_per_record={savings / args.count:.1f}")


if __name__ == "__main__":
    main()
