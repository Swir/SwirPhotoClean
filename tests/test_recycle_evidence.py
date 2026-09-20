import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from photoclean.diagnostics import (
    COPY_NAME,
    MANIFEST_NAME,
    ORIGINAL_NAME,
    RecycleVerificationError,
    create_recycle_verification,
    export_recycle_evidence,
    inspect_recycle_evidence,
    load_recycle_verification,
    move_generated_copy_to_recycle,
    verify_restored_copy,
)


class RecycleEvidenceTests(unittest.TestCase):
    def test_new_manifest_has_uuid_event_log_and_fingerprint(self):
        with tempfile.TemporaryDirectory() as folder:
            check = create_recycle_verification(folder)
            payload = json.loads(check.manifest.read_text(encoding="utf-8"))

            self.assertEqual(payload["version"], 2)
            self.assertEqual(payload["stage"], "prepared")
            self.assertEqual([event["stage"] for event in payload["events"]], ["prepared"])
            self.assertEqual(len(payload["session_id"]), 32)
            self.assertGreater(payload["file_size"], 0)
            self.assertEqual(len(payload["manifest_fingerprint"]), 64)

            inspection = inspect_recycle_evidence(check)
            self.assertTrue(inspection.valid)
            self.assertEqual(inspection.stage, "prepared")
            self.assertEqual(inspection.event_count, 1)
            self.assertTrue(inspection.original_matches)
            self.assertTrue(inspection.copy_matches)

    def test_manifest_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            check = create_recycle_verification(folder)
            payload = json.loads(check.manifest.read_text(encoding="utf-8"))
            payload["file_size"] += 1
            check.manifest.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            with self.assertRaises(RecycleVerificationError):
                load_recycle_verification(check.manifest)

    def test_fake_recycle_restore_and_export_produce_consistent_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            check = create_recycle_verification(folder)

            def fake_recycler(path):
                Path(path).unlink()

            recycled = move_generated_copy_to_recycle(check, recycler=fake_recycler)
            recycled_inspection = inspect_recycle_evidence(recycled)
            self.assertTrue(recycled_inspection.valid)
            self.assertEqual(recycled_inspection.stage, "recycled")
            self.assertEqual(recycled_inspection.event_count, 2)
            self.assertFalse(recycled_inspection.copy_present)

            shutil.copy2(recycled.original, recycled.copy)
            verified = verify_restored_copy(recycled)
            inspection = inspect_recycle_evidence(verified)
            self.assertTrue(inspection.valid)
            self.assertEqual(inspection.stage, "restored-verified")
            self.assertEqual(inspection.event_count, 3)
            self.assertTrue(inspection.copy_matches)

            destination = Path(folder) / "evidence-report.json"
            exported = export_recycle_evidence(verified, destination)
            report = json.loads(exported.read_text(encoding="utf-8"))
            self.assertFalse(report["acceptance_gate_closed"])
            self.assertTrue(report["inspection"]["valid"])
            self.assertEqual(report["inspection"]["stage"], "restored-verified")
            self.assertEqual(
                [event["stage"] for event in report["manifest"]["events"]],
                ["prepared", "recycled", "restored-verified"],
            )

    def test_hardlink_cannot_fake_manual_restore(self):
        with tempfile.TemporaryDirectory() as folder:
            check = create_recycle_verification(folder)

            def fake_recycler(path):
                Path(path).unlink()

            recycled = move_generated_copy_to_recycle(check, recycler=fake_recycler)
            try:
                os.link(recycled.original, recycled.copy)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"hardlinks unavailable: {error}")

            with self.assertRaises(RecycleVerificationError):
                verify_restored_copy(recycled)

    def test_invalid_recycled_state_cannot_be_exported(self):
        with tempfile.TemporaryDirectory() as folder:
            check = create_recycle_verification(folder)

            def fake_recycler(path):
                Path(path).unlink()

            recycled = move_generated_copy_to_recycle(check, recycler=fake_recycler)
            Image.new("RGB", (96, 64), "red").save(recycled.copy, format="PNG")

            inspection = inspect_recycle_evidence(recycled)
            self.assertFalse(inspection.valid)
            self.assertIn("expected to be absent", " ".join(inspection.problems))
            with self.assertRaises(RecycleVerificationError):
                export_recycle_evidence(recycled, Path(folder) / "invalid-report.json")

    def test_legacy_v1_prepared_manifest_upgrades_on_transition(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            original = base / ORIGINAL_NAME
            copy = base / COPY_NAME
            Image.new("RGB", (32, 24), "navy").save(original, format="PNG")
            shutil.copy2(original, copy)
            digest = hashlib.sha256(original.read_bytes()).hexdigest()
            manifest = base / MANIFEST_NAME
            manifest.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "stage": "prepared",
                        "digest_sha256": digest,
                        "original_file": ORIGINAL_NAME,
                        "copy_file": COPY_NAME,
                        "created_at_utc": "2026-09-19T00:00:00+00:00",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            loaded = load_recycle_verification(manifest)
            self.assertEqual(loaded.manifest_version, 1)

            def fake_recycler(path):
                Path(path).unlink()

            recycled = move_generated_copy_to_recycle(loaded, recycler=fake_recycler)
            self.assertEqual(recycled.manifest_version, 2)
            self.assertEqual(recycled.stage, "recycled")
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(payload["upgraded_from_version"], 1)
            self.assertEqual([event["stage"] for event in payload["events"]], ["prepared", "recycled"])


if __name__ == "__main__":
    unittest.main()
