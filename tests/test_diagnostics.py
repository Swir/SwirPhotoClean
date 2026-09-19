import shutil
import tempfile
import unittest
from pathlib import Path

from photoclean.core import Group, Photo, ScanResult
from photoclean.diagnostics import (
    RecycleVerificationError,
    build_diagnostics_snapshot,
    create_recycle_verification,
    load_recycle_verification,
    move_generated_copy_to_recycle,
    verify_restored_copy,
)


def photo(path, digest):
    return Photo(Path(path), 10, 1, 2, 3, digest, 20, 10, 0, bytes(192))


class DiagnosticsTests(unittest.TestCase):
    def test_snapshot_reports_scan_state_without_mutation(self):
        first = photo("a.png", "a" * 64)
        second = photo("b.png", "a" * 64)
        third = photo("c.png", "b" * 64)
        result = ScanResult(
            photos=[first, second, third],
            groups=[Group("exact", (first, second)), Group("similar", (first, third))],
            warnings=["one warning"],
        )

        snapshot = build_diagnostics_snapshot(result, marked_count=1)

        self.assertEqual(snapshot.photo_count, 3)
        self.assertEqual(snapshot.exact_group_count, 1)
        self.assertEqual(snapshot.similar_group_count, 1)
        self.assertEqual(snapshot.warning_count, 1)
        self.assertEqual(snapshot.marked_count, 1)
        self.assertFalse(snapshot.cancelled)

    def test_generated_pair_is_identical_and_manifest_is_loadable(self):
        with tempfile.TemporaryDirectory() as folder:
            check = create_recycle_verification(folder)
            loaded = load_recycle_verification(check.manifest)

            self.assertEqual(loaded.stage, "prepared")
            self.assertTrue(loaded.original.is_file())
            self.assertTrue(loaded.copy.is_file())
            self.assertEqual(loaded.digest, check.digest)
            self.assertEqual(loaded.original.read_bytes(), loaded.copy.read_bytes())

    def test_fake_recycle_then_manual_restore_produces_verified_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            check = create_recycle_verification(folder)

            def fake_recycler(path):
                Path(path).unlink()

            recycled = move_generated_copy_to_recycle(check, recycler=fake_recycler)
            self.assertEqual(recycled.stage, "recycled")
            self.assertTrue(recycled.original.is_file())
            self.assertFalse(recycled.copy.exists())

            shutil.copy2(recycled.original, recycled.copy)
            verified = verify_restored_copy(recycled)
            self.assertEqual(verified.stage, "restored-verified")
            self.assertTrue(verified.original.is_file())
            self.assertTrue(verified.copy.is_file())
            manifest_text = verified.manifest.read_text(encoding="utf-8")
            self.assertIn('"restored_copy_matches_sha256": true', manifest_text)
            self.assertIn('"original_preserved": true', manifest_text)

    def test_failed_recycle_keeps_generated_files_and_prepared_stage(self):
        with tempfile.TemporaryDirectory() as folder:
            check = create_recycle_verification(folder)

            def failing_recycler(path):
                raise OSError("Recycle Bin unavailable")

            with self.assertRaises(RecycleVerificationError):
                move_generated_copy_to_recycle(check, recycler=failing_recycler)

            loaded = load_recycle_verification(check.manifest)
            self.assertEqual(loaded.stage, "prepared")
            self.assertTrue(loaded.original.is_file())
            self.assertTrue(loaded.copy.is_file())

    def test_restore_cannot_be_verified_before_recycle_stage(self):
        with tempfile.TemporaryDirectory() as folder:
            check = create_recycle_verification(folder)
            with self.assertRaises(RecycleVerificationError):
                verify_restored_copy(check)


if __name__ == "__main__":
    unittest.main()
