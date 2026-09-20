import threading
import unittest
from pathlib import Path

from photoclean.core import BKTree, Photo


def photo(name: str, dhash: int) -> Photo:
    return Photo(
        path=Path(name),
        size=1,
        modified_ns=1,
        device=1,
        inode=1,
        digest=f"digest-{name}",
        width=100,
        height=100,
        dhash=dhash,
        color=bytes([32]) * 192,
    )


class SimilarityIndexMemoryTests(unittest.TestCase):
    def test_unique_nodes_keep_optional_containers_unallocated(self):
        tree = BKTree()
        first = photo("a.jpg", 0)
        second = photo("b.jpg", 1)
        third = photo("c.jpg", 3)

        tree.add(first.dhash, first)
        self.assertIsNone(tree.root.collisions)
        self.assertIsNone(tree.root.children)

        tree.add(second.dhash, second)
        self.assertIsNone(tree.root.collisions)
        self.assertIsNotNone(tree.root.children)
        child = next(iter(tree.root.children.values()))
        self.assertIsNone(child.collisions)
        self.assertIsNone(child.children)

        tree.add(third.dhash, third)
        self.assertIsNone(tree.root.collisions)
        self.assertTrue(tree.root.children)

    def test_identical_hash_allocates_collision_bucket_only_when_needed(self):
        tree = BKTree()
        first = photo("a.jpg", 0x1234)
        second = photo("b.jpg", 0x1234)
        third = photo("c.jpg", 0x1234)

        tree.add(first.dhash, first)
        self.assertIsNone(tree.root.collisions)
        tree.add(second.dhash, second)
        tree.add(third.dhash, third)

        self.assertEqual(tree.root.collisions, [second, third])
        matches = list(tree.query(first.dhash, 0, threading.Event()))
        self.assertEqual(matches, [first, second, third])

    def test_radius_query_preserves_all_matching_candidates(self):
        tree = BKTree()
        candidates = [
            photo("anchor.jpg", 0b0000),
            photo("near.jpg", 0b0001),
            photo("also-near.jpg", 0b0010),
            photo("far.jpg", 0b1111),
        ]
        for candidate in candidates:
            tree.add(candidate.dhash, candidate)

        matches = list(tree.query(0, 1, threading.Event()))
        self.assertEqual({item.path.name for item in matches}, {"anchor.jpg", "near.jpg", "also-near.jpg"})


if __name__ == "__main__":
    unittest.main()
