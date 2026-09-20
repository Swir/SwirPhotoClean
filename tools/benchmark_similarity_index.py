"""Measure Python memory/time for the in-memory similar-photo BK-tree index."""
from __future__ import annotations

import argparse
import random
import threading
import time
import tracemalloc
from pathlib import Path

from photoclean.core import BKTree, Photo


def make_photo(index: int, dhash: int) -> Photo:
    return Photo(
        path=Path(f"synthetic-{index:07d}.jpg"),
        size=1,
        modified_ns=1,
        device=1,
        inode=index + 1,
        digest=f"{index:064x}"[-64:],
        width=1920,
        height=1080,
        dhash=dhash,
        color=bytes([index % 251]) * 192,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark the sparse similarity index without reading real photos."
    )
    parser.add_argument("--count", type=int, default=50_000, help="synthetic photos")
    parser.add_argument("--seed", type=int, default=20260920, help="deterministic PRNG seed")
    parser.add_argument(
        "--collision-every",
        type=int,
        default=0,
        help="reuse the previous dHash every N photos; 0 keeps hashes random",
    )
    args = parser.parse_args()
    if args.count < 1:
        raise SystemExit("--count must be >= 1")
    if args.collision_every < 0:
        raise SystemExit("--collision-every must be >= 0")

    rng = random.Random(args.seed)
    tree = BKTree()
    cancel = threading.Event()
    hashes: list[int] = []

    tracemalloc.start()
    started = time.perf_counter()
    previous = None
    for index in range(args.count):
        if args.collision_every and previous is not None and index % args.collision_every == 0:
            dhash = previous
        else:
            dhash = rng.getrandbits(64)
        previous = dhash
        hashes.append(dhash)
        tree.add(dhash, make_photo(index, dhash))
    build_seconds = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    query_started = time.perf_counter()
    sample_step = max(1, len(hashes) // 1000)
    hits = 0
    for dhash in hashes[::sample_step]:
        hits += sum(1 for _ in tree.query(dhash, 0, cancel))
    query_seconds = time.perf_counter() - query_started

    print(f"photos={args.count}")
    print(f"build_seconds={build_seconds:.6f}")
    print(f"build_photos_per_second={args.count / max(build_seconds, 1e-9):.1f}")
    print(f"peak_traced_mib={peak / (1024 * 1024):.3f}")
    print(f"sample_query_seconds={query_seconds:.6f}")
    print(f"sample_hits={hits}")


if __name__ == "__main__":
    main()
