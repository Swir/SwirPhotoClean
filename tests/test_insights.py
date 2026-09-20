import unittest
from pathlib import Path

from photoclean.core import Group, Photo, ScanResult
from photoclean.insights import folder_health, recommend_keeper


def photo(name, *, size=1000, width=100, height=100, digest=None):
    return Photo(
        path=Path(name),
        size=size,
        modified_ns=1,
        device=1,
        inode=hash(name) & 0xFFFF,
        digest=digest or name,
        width=width,
        height=height,
        dhash=0,
        color=b"\0" * 192,
    )


class SmartKeepTests(unittest.TestCase):
    def test_exact_group_reports_equivalent_copies(self):
        a = photo("long-folder/a-copy.png", digest="same")
        b = photo("b.png", digest="same")
        recommendation = recommend_keeper(Group("exact", (a, b)))
        self.assertTrue(recommendation.equivalent_exact)
        self.assertEqual(recommendation.confidence, "equivalent")
        self.assertEqual(recommendation.photo, b)

    def test_resolution_dominates_similar_group_ranking(self):
        small = photo("small.png", size=4_000_000, width=640, height=480)
        large = photo("large.jpg", size=900_000, width=1920, height=1080)
        recommendation = recommend_keeper(Group("similar", (small, large)))
        self.assertEqual(recommendation.photo, large)
        self.assertGreater(recommendation.resolution_points, 60)

    def test_format_breaks_same_resolution_tie(self):
        jpeg = photo("copy.jpg", size=100_000, width=1000, height=1000)
        png = photo("copy.png", size=100_000, width=1000, height=1000)
        recommendation = recommend_keeper(Group("similar", (jpeg, png)))
        self.assertEqual(recommendation.photo, png)
        self.assertEqual(recommendation.confidence, "medium")

    def test_empty_group_is_rejected(self):
        with self.assertRaises(ValueError):
            recommend_keeper(Group("similar", ()))


class FolderHealthTests(unittest.TestCase):
    def test_exact_savings_preserve_one_copy(self):
        a = photo("a.png", size=1000, digest="same")
        b = photo("b.png", size=1000, digest="same")
        c = photo("c.png", size=1000, digest="same")
        result = ScanResult(photos=[a, b, c], groups=[Group("exact", (a, b, c))])
        health = folder_health(result)
        self.assertEqual(health.exact_groups, 1)
        self.assertEqual(health.exact_group_members, 3)
        self.assertEqual(health.exact_duplicate_files, 2)
        self.assertEqual(health.exact_reclaimable_bytes, 2000)
        self.assertEqual(health.total_bytes, 3000)
        self.assertAlmostEqual(health.exact_reclaimable_percent, 66.67, places=2)

    def test_similar_candidates_do_not_inflate_reclaimable_bytes(self):
        a = photo("a.jpg", size=1000)
        b = photo("b.jpg", size=2000)
        result = ScanResult(photos=[a, b], groups=[Group("similar", (a, b))])
        health = folder_health(result)
        self.assertEqual(health.exact_reclaimable_bytes, 0)
        self.assertEqual(health.exact_reclaimable_percent, 0)
        self.assertEqual(health.similar_groups, 1)
        self.assertEqual(health.similar_review_files, 2)

    def test_similar_review_count_deduplicates_overlapping_paths(self):
        a = photo("a.jpg")
        b = photo("b.jpg")
        c = photo("c.jpg")
        result = ScanResult(
            photos=[a, b, c],
            groups=[Group("similar", (a, b)), Group("similar", (b, c))],
            warnings=["fixture warning"],
        )
        health = folder_health(result, largest_limit=2)
        self.assertEqual(health.similar_review_files, 3)
        self.assertEqual(health.grouped_files, 3)
        self.assertEqual(health.unflagged_files, 0)
        self.assertEqual(health.warning_count, 1)
        self.assertEqual(len(health.largest_files), 2)

    def test_unflagged_count_uses_union_of_exact_and_similar_paths(self):
        a = photo("a.png", digest="same")
        b = photo("b.png", digest="same")
        c = photo("c.jpg")
        d = photo("d.jpg")
        result = ScanResult(
            photos=[a, b, c, d],
            groups=[Group("exact", (a, b)), Group("similar", (b, c))],
        )
        health = folder_health(result)
        self.assertEqual(health.grouped_files, 3)
        self.assertEqual(health.unflagged_files, 1)

    def test_repeated_exact_members_cannot_inflate_savings(self):
        a = photo("a.png", size=1000, digest="same")
        b = photo("b.png", size=1000, digest="same")
        c = photo("c.png", size=1000, digest="same")
        result = ScanResult(
            photos=[a, b, c],
            groups=[
                Group("exact", (a, b)),
                Group("exact", (a, b, c)),
            ],
        )
        health = folder_health(result)
        self.assertEqual(health.exact_groups, 1)
        self.assertEqual(health.exact_group_members, 3)
        self.assertEqual(health.exact_duplicate_files, 2)
        self.assertEqual(health.exact_reclaimable_bytes, 2000)

    def test_inconsistent_exact_sizes_are_counted_conservatively(self):
        a = photo("a.png", size=1000, digest="same")
        b = photo("b.png", size=1200, digest="same")
        c = photo("c.png", size=900, digest="same")
        result = ScanResult(photos=[a, b, c], groups=[Group("exact", (a, b, c))])
        health = folder_health(result)
        self.assertEqual(health.exact_reclaimable_bytes, 1900)

    def test_group_member_outside_scan_cannot_inflate_health(self):
        a = photo("a.png", size=1000, digest="same")
        b = photo("b.png", size=1000, digest="same")
        injected = photo("outside.png", size=50_000_000, digest="same")
        result = ScanResult(
            photos=[a, b],
            groups=[Group("exact", (a, b, injected))],
        )
        health = folder_health(result)
        self.assertEqual(health.exact_groups, 1)
        self.assertEqual(health.exact_group_members, 2)
        self.assertEqual(health.exact_duplicate_files, 1)
        self.assertEqual(health.exact_reclaimable_bytes, 1000)
        self.assertEqual(health.total_bytes, 2000)

    def test_repeated_similar_group_does_not_inflate_group_count(self):
        a = photo("a.jpg")
        b = photo("b.jpg")
        result = ScanResult(
            photos=[a, b],
            groups=[Group("similar", (a, b)), Group("similar", (b, a))],
        )
        health = folder_health(result)
        self.assertEqual(health.similar_groups, 1)
        self.assertEqual(health.similar_review_files, 2)

    def test_negative_largest_limit_is_rejected(self):
        with self.assertRaises(ValueError):
            folder_health(ScanResult(), largest_limit=-1)


if __name__ == "__main__":
    unittest.main()
