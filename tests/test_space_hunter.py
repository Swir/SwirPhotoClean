import unittest
from pathlib import Path

from photoclean.core import Group, Photo, ScanResult
from photoclean.space_hunter import build_space_report


def photo(name, *, size=1000, digest=None, width=100, height=100):
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


class SpaceHunterTests(unittest.TestCase):
    def test_exact_reclaim_preserves_one_copy(self):
        a = photo("album/a.png", size=2500, digest="same")
        b = photo("backup/a.png", size=2500, digest="same")
        c = photo("copy/a.png", size=2500, digest="same")
        result = ScanResult(photos=[a, b, c], groups=[Group("exact", (a, b, c))])

        report = build_space_report(result)

        self.assertEqual(report.photo_count, 3)
        self.assertEqual(report.total_bytes, 7500)
        self.assertEqual(report.exact_duplicate_files, 2)
        self.assertEqual(report.exact_reclaimable_bytes, 5000)
        self.assertTrue(all(item.status == "exact" for item in report.largest_files))
        self.assertTrue(all(item.exact_group_size == 3 for item in report.largest_files))
        self.assertTrue(all(item.exact_group_reclaimable_bytes == 5000 for item in report.largest_files))

    def test_similar_photos_never_inflate_guaranteed_savings(self):
        a = photo("album/a.jpg", size=4000)
        b = photo("album/b.jpg", size=3500)
        result = ScanResult(photos=[a, b], groups=[Group("similar", (a, b))])

        report = build_space_report(result)

        self.assertEqual(report.exact_duplicate_files, 0)
        self.assertEqual(report.exact_reclaimable_bytes, 0)
        self.assertEqual({item.status for item in report.largest_files}, {"similar"})

    def test_file_status_prefers_exact_when_groups_overlap(self):
        a = photo("a.jpg", size=3000, digest="same")
        b = photo("b.jpg", size=3000, digest="same")
        c = photo("c.jpg", size=2900)
        result = ScanResult(
            photos=[a, b, c],
            groups=[Group("exact", (a, b)), Group("similar", (a, c))],
        )

        report = build_space_report(result)
        by_name = {item.photo.path.name: item for item in report.largest_files}

        self.assertEqual(by_name["a.jpg"].status, "exact")
        self.assertEqual(by_name["b.jpg"].status, "exact")
        self.assertEqual(by_name["c.jpg"].status, "similar")

    def test_largest_files_and_folders_are_bounded_and_sorted(self):
        a = photo("one/a.jpg", size=100)
        b = photo("one/b.jpg", size=300)
        c = photo("two/c.jpg", size=200)
        result = ScanResult(photos=[a, b, c])

        report = build_space_report(result, file_limit=2, folder_limit=1)

        self.assertEqual([item.photo.path.name for item in report.largest_files], ["b.jpg", "c.jpg"])
        self.assertEqual(len(report.largest_folders), 1)
        self.assertEqual(report.largest_folders[0].path, Path("one"))
        self.assertEqual(report.largest_folders[0].total_bytes, 400)
        self.assertEqual(report.largest_folders[0].photo_count, 2)

    def test_repeated_exact_groups_are_collapsed_by_digest(self):
        a = photo("a.jpg", size=1000, digest="same")
        b = photo("b.jpg", size=1000, digest="same")
        c = photo("c.jpg", size=1000, digest="same")
        result = ScanResult(
            photos=[a, b, c],
            groups=[
                Group("exact", (a, b)),
                Group("exact", (b, c)),
                Group("exact", (a, b, c)),
            ],
        )

        report = build_space_report(result)

        self.assertEqual(report.exact_duplicate_files, 2)
        self.assertEqual(report.exact_reclaimable_bytes, 2000)
        self.assertTrue(all(item.exact_group_size == 3 for item in report.largest_files))
        self.assertTrue(all(item.exact_group_reclaimable_bytes == 2000 for item in report.largest_files))

    def test_group_member_outside_scan_cannot_inflate_savings(self):
        a = photo("a.jpg", size=1000, digest="same")
        b = photo("b.jpg", size=1000, digest="same")
        injected = photo("outside.jpg", size=50_000_000, digest="same")
        result = ScanResult(
            photos=[a, b],
            groups=[Group("exact", (a, b, injected))],
        )

        report = build_space_report(result)

        self.assertEqual(report.exact_duplicate_files, 1)
        self.assertEqual(report.exact_reclaimable_bytes, 1000)
        self.assertEqual(report.total_bytes, 2000)
        self.assertTrue(all(item.exact_group_size == 2 for item in report.largest_files))

    def test_single_valid_similar_member_is_not_labeled(self):
        a = photo("a.jpg", size=2000)
        injected = photo("outside.jpg", size=1000)
        result = ScanResult(
            photos=[a],
            groups=[Group("similar", (a, injected))],
        )

        report = build_space_report(result)

        self.assertEqual(report.largest_files[0].status, "other")

    def test_zero_limits_return_only_summary(self):
        result = ScanResult(photos=[photo("a.jpg", size=123)])
        report = build_space_report(result, file_limit=0, folder_limit=0)
        self.assertEqual(report.total_bytes, 123)
        self.assertEqual(report.largest_files, ())
        self.assertEqual(report.largest_folders, ())

    def test_negative_limits_are_rejected(self):
        with self.assertRaises(ValueError):
            build_space_report(ScanResult(), file_limit=-1)
        with self.assertRaises(ValueError):
            build_space_report(ScanResult(), folder_limit=-1)


if __name__ == "__main__":
    unittest.main()
