import json
import tempfile
import unittest
from pathlib import Path

from photoclean.cleanup_history import (
    append_cleanup_record,
    build_cleanup_plan,
    finalize_cleanup_record,
    load_cleanup_history,
)
from photoclean.core import Group, Photo, ScanResult


def photo(path: Path, *, size=100, digest="a" * 64, inode=1):
    return Photo(
        path=path,
        size=size,
        modified_ns=1,
        device=1,
        inode=inode,
        digest=digest,
        width=100,
        height=80,
        dhash=0,
        color=b"\x00" * 192,
    )


class CleanupHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.a = photo(self.root / "oryginał.png", size=120, digest="1" * 64, inode=1)
        self.b = photo(self.root / "kopia.png", size=120, digest="1" * 64, inode=2)
        self.c = photo(self.root / "podobne.jpg", size=90, digest="2" * 64, inode=3)
        self.result = ScanResult(
            photos=[self.a, self.b, self.c],
            groups=[
                Group("exact", (self.a, self.b)),
                Group("similar", (self.a, self.b, self.c)),
            ],
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_exact_duplicate_move_is_only_reclaimable_after_bin_empty(self):
        plan = build_cleanup_plan(
            self.result,
            [self.b.path],
            started_at="2026-09-19T08:00:00+00:00",
            record_id="exact",
        )
        self.assertTrue(plan.candidates[0].exact_survivor)
        record = finalize_cleanup_record(
            plan,
            [self.b.path],
            [],
            finished_at="2026-09-19T08:00:01+00:00",
        )
        self.assertEqual(record.completed_count, 1)
        self.assertEqual(record.moved_to_recycle_bytes, 120)
        self.assertEqual(record.guaranteed_reclaimable_after_bin_empty, 120)
        self.assertEqual(record.scan_photo_count_before, 3)
        self.assertEqual(record.scan_photo_count_after_snapshot, 2)
        self.assertTrue(record.fully_completed)

    def test_similar_only_move_never_inflates_guaranteed_space(self):
        plan = build_cleanup_plan(self.result, [self.c.path], record_id="similar")
        self.assertFalse(plan.candidates[0].exact_survivor)
        record = finalize_cleanup_record(plan, [self.c.path], [])
        self.assertEqual(record.moved_to_recycle_bytes, 90)
        self.assertEqual(record.guaranteed_reclaimable_after_bin_empty, 0)

    def test_failed_or_cancelled_item_is_not_counted_as_moved(self):
        plan = build_cleanup_plan(self.result, [self.b.path], record_id="failed")
        record = finalize_cleanup_record(plan, [], ["Kosz niedostępny"])
        self.assertEqual(record.completed_count, 0)
        self.assertEqual(record.moved_to_recycle_bytes, 0)
        self.assertEqual(record.guaranteed_reclaimable_after_bin_empty, 0)
        self.assertEqual(record.entries[0].status, "not_moved")
        self.assertFalse(record.fully_completed)

    def test_unknown_selected_path_is_rejected(self):
        with self.assertRaises(ValueError):
            build_cleanup_plan(self.result, [self.root / "spoza-skanu.png"])

    def test_history_roundtrip_keeps_unicode_and_hashes(self):
        path = self.root / "cleanup-history.json"
        plan = build_cleanup_plan(self.result, [self.a.path], record_id="ąęść")
        record = finalize_cleanup_record(plan, [self.a.path], [])
        append_cleanup_record(path, record)
        loaded = load_cleanup_history(path)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].record_id, "ąęść")
        self.assertEqual(loaded[0].entries[0].digest, "1" * 64)
        self.assertIn("oryginał", loaded[0].entries[0].path)

    def test_history_limit_retains_only_newest_records(self):
        path = self.root / "cleanup-history.json"
        for index in range(3):
            plan = build_cleanup_plan(self.result, [self.a.path], record_id=f"r{index}")
            append_cleanup_record(path, finalize_cleanup_record(plan, [], []), limit=2)
        loaded = load_cleanup_history(path)
        self.assertEqual([record.record_id for record in loaded], ["r1", "r2"])

    def test_corrupt_or_wrong_schema_history_is_rejected(self):
        path = self.root / "cleanup-history.json"
        path.write_text("not-json", encoding="utf-8")
        with self.assertRaises(ValueError):
            load_cleanup_history(path)
        path.write_text(json.dumps({"schema": 999, "sessions": []}), encoding="utf-8")
        with self.assertRaises(ValueError):
            load_cleanup_history(path)

    def test_completed_paths_must_belong_to_plan(self):
        plan = build_cleanup_plan(self.result, [self.a.path], record_id="scope")
        with self.assertRaises(ValueError):
            finalize_cleanup_record(plan, [self.c.path], [])


if __name__ == "__main__":
    unittest.main()
