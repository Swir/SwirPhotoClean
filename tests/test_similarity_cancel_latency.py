import threading
import unittest
from pathlib import Path

from photoclean.core import BKTree, Cancelled, Photo, similar


class CountingCancel:
    """Deterministic cancellation source for inner-loop regression coverage."""

    def __init__(self, stop_on_call: int):
        self.calls = 0
        self.stop_on_call = stop_on_call

    def is_set(self):
        self.calls += 1
        return self.calls >= self.stop_on_call


class CountingColor:
    """Bytes-like iterable that records how much of a signature was inspected."""

    def __init__(self, values):
        self.values = tuple(values)
        self.reads = 0

    def __len__(self):
        return len(self.values)

    def __iter__(self):
        for value in self.values:
            self.reads += 1
            yield value


def photo(index: int, *, dhash: int = 0, color=None) -> Photo:
    signature = bytes([index % 251]) * 192 if color is None else color
    return Photo(
        path=Path(f"photo-{index:04d}.jpg"),
        size=100 + index,
        modified_ns=1_000 + index,
        device=1,
        inode=index + 1,
        digest=f"{index + 1:064x}",
        width=1920,
        height=1080,
        dhash=dhash,
        color=signature,
    )


class SimilarityCancellationTests(unittest.TestCase):
    def test_large_same_hash_collision_bucket_remains_cancellable(self):
        tree = BKTree()
        for index in range(200):
            tree.add(0, photo(index, dhash=0, color=bytes(192)))

        cancel = CountingCancel(stop_on_call=3)
        with self.assertRaises(Cancelled):
            list(tree.query(0, 0, cancel))

        # One outer checkpoint plus per-collision checkpoints should stop the
        # pathological bucket almost immediately rather than yielding all 200.
        self.assertEqual(cancel.calls, 3)

    def test_normal_collision_query_still_returns_every_candidate(self):
        tree = BKTree()
        expected = []
        for index in range(8):
            item = photo(index, dhash=0, color=bytes(192))
            expected.append(item.path)
            tree.add(0, item)

        actual = [item.path for item in tree.query(0, 0, threading.Event())]
        self.assertEqual(actual, expected)

    def test_color_error_boundary_keeps_existing_similarity_semantics(self):
        base = photo(0, color=bytes([0]) * 192)
        at_limit = photo(1, color=bytes([14]) * 192)
        over_limit = photo(2, color=bytes([15]) * 192)

        self.assertTrue(similar(base, at_limit, 0))
        self.assertFalse(similar(base, over_limit, 0))

    def test_obviously_different_color_signature_short_circuits(self):
        left_color = CountingColor([0] * 192)
        right_color = CountingColor([255] + [0] * 191)
        left = photo(0, color=left_color)
        right = photo(1, color=right_color)

        self.assertFalse(similar(left, right, 0))
        self.assertEqual(left_color.reads, 1)
        self.assertEqual(right_color.reads, 1)


if __name__ == "__main__":
    unittest.main()
