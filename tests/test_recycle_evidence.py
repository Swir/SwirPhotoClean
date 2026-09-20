import json
import tempfile
import unittest
from pathlib import Path

from photoclean.recycle_evidence import (
    EvidenceError,
    cli_main,
    prepare_restore_evidence,
    verify_restore_evidence,
)


class RecycleRestoreEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fake_bin = self.root / "fake-bin"
        self.fake_bin.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def fake_recycle(self, path: str):
        source = Path(path)
        source.replace(self.fake_bin / source.name)

    def test_prepare_then_manual_restore_verifies_both_generated_copies(self):
        evidence = prepare_restore_evidence(
            self.root / "workspace",
            recycle=self.fake_recycle,
            now=lambda: "2026-09-20T12:00:00Z",
            payload_factory=lambda: b"generated-evidence-payload",
        )
        record = json.loads(evidence.read_text(encoding="utf-8"))
        original = Path(record["original_path"])
        copy = Path(record["copy_path"])
        recycled = self.fake_bin / copy.name
        self.assertEqual(record["phase"], "awaiting_restore")
        self.assertTrue(record["recycle_move_confirmed"])
        self.assertTrue(original.exists())
        self.assertFalse(copy.exists())
        self.assertTrue(recycled.exists())

        recycled.replace(copy)  # simulate the user's explicit Recycle Bin restore
        verified = verify_restore_evidence(
            evidence,
            now=lambda: "2026-09-20T12:01:00Z",
        )
        self.assertEqual(verified["phase"], "verified")
        self.assertTrue(verified["restore_verified"])
        self.assertTrue(original.exists())
        self.assertTrue(copy.exists())
        self.assertEqual(original.read_bytes(), copy.read_bytes())

    def test_failed_recycle_keeps_generated_pair_and_records_failure(self):
        def fail(_path: str):
            raise OSError("Recycle Bin unavailable")

        with self.assertRaises(EvidenceError):
            prepare_restore_evidence(
                self.root / "workspace",
                recycle=fail,
                payload_factory=lambda: b"generated-evidence-payload",
            )
        evidence_files = list((self.root / "workspace").glob("*evidence*.json"))
        self.assertEqual(len(evidence_files), 1)
        record = json.loads(evidence_files[0].read_text(encoding="utf-8"))
        self.assertEqual(record["phase"], "recycle_failed")
        self.assertTrue(Path(record["original_path"]).exists())
        self.assertTrue(Path(record["copy_path"]).exists())
        self.assertFalse(record["recycle_move_confirmed"])

    def test_verify_rejects_modified_original(self):
        evidence = prepare_restore_evidence(
            self.root / "workspace",
            recycle=self.fake_recycle,
            payload_factory=lambda: b"generated-evidence-payload",
        )
        record = json.loads(evidence.read_text(encoding="utf-8"))
        copy = Path(record["copy_path"])
        (self.fake_bin / copy.name).replace(copy)
        Path(record["original_path"]).write_bytes(b"changed")
        with self.assertRaises(EvidenceError):
            verify_restore_evidence(evidence)
        unchanged = json.loads(evidence.read_text(encoding="utf-8"))
        self.assertEqual(unchanged["phase"], "awaiting_restore")
        self.assertFalse(unchanged["restore_verified"])

    def test_verify_requires_restored_copy(self):
        evidence = prepare_restore_evidence(
            self.root / "workspace",
            recycle=self.fake_recycle,
            payload_factory=lambda: b"generated-evidence-payload",
        )
        with self.assertRaises(EvidenceError):
            verify_restore_evidence(evidence)

    def test_cli_rejects_bad_arity_without_side_effects(self):
        self.assertEqual(cli_main(["--recycle-restore-verify"]), 2)
        self.assertEqual(cli_main(["--recycle-restore-prepare", "a", "b"]), 2)


if __name__ == "__main__":
    unittest.main()
