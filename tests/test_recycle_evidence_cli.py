import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from photoclean.diagnostics import RecycleVerificationError, inspect_recycle_evidence
from photoclean.recycle_evidence import (
    cli_main,
    prepare_restore_evidence,
    verify_restore_evidence,
)


class RecycleEvidenceCliTests(unittest.TestCase):
    def test_adapter_uses_existing_tamper_evident_workflow_end_to_end(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder) / "workspace"

            def fake_recycler(path):
                Path(path).unlink()

            recycled = prepare_restore_evidence(base, recycler=fake_recycler)
            inspection = inspect_recycle_evidence(recycled)
            self.assertTrue(inspection.valid)
            self.assertEqual(inspection.stage, "recycled")
            self.assertTrue(recycled.original.exists())
            self.assertFalse(recycled.copy.exists())

            shutil.copy2(recycled.original, recycled.copy)
            verified, report = verify_restore_evidence(recycled.manifest)
            self.assertEqual(verified.stage, "restored-verified")
            self.assertTrue(report.is_file())
            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertFalse(payload["acceptance_gate_closed"])
            self.assertEqual(payload["inspection"]["stage"], "restored-verified")
            self.assertTrue(payload["inspection"]["valid"])

    def test_verify_can_resume_report_export_after_post_transition_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder) / "workspace"

            def fake_recycler(path):
                Path(path).unlink()

            recycled = prepare_restore_evidence(base, recycler=fake_recycler)
            shutil.copy2(recycled.original, recycled.copy)

            with patch(
                "photoclean.recycle_evidence.export_recycle_evidence",
                side_effect=OSError("simulated report write failure"),
            ):
                with self.assertRaises(OSError):
                    verify_restore_evidence(recycled.manifest)

            after_failure = inspect_recycle_evidence(recycled.manifest)
            self.assertTrue(after_failure.valid)
            self.assertEqual(after_failure.stage, "restored-verified")
            self.assertEqual(after_failure.event_count, 3)

            verified, report = verify_restore_evidence(recycled.manifest)
            self.assertEqual(verified.stage, "restored-verified")
            self.assertTrue(report.is_file())

            after_retry = inspect_recycle_evidence(recycled.manifest)
            self.assertTrue(after_retry.valid)
            self.assertEqual(after_retry.stage, "restored-verified")
            self.assertEqual(after_retry.event_count, 3)

    def test_failed_move_does_not_advance_manifest_or_remove_generated_files(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder) / "workspace"

            def fail(_path):
                raise OSError("Recycle Bin unavailable")

            with self.assertRaises(RecycleVerificationError):
                prepare_restore_evidence(base, recycler=fail)
            manifests = list(base.rglob("recycle-verification.json"))
            self.assertEqual(len(manifests), 1)
            payload = json.loads(manifests[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["stage"], "prepared")
            check_folder = manifests[0].parent
            self.assertTrue((check_folder / "KEEP-ME.png").exists())
            self.assertTrue((check_folder / "RECYCLE-ME.png").exists())

    def test_verify_refuses_missing_manual_restore(self):
        with tempfile.TemporaryDirectory() as folder:
            def fake_recycler(path):
                Path(path).unlink()

            recycled = prepare_restore_evidence(folder, recycler=fake_recycler)
            with self.assertRaises(RecycleVerificationError):
                verify_restore_evidence(recycled.manifest)

    def test_cli_rejects_bad_arity_without_starting_gui(self):
        self.assertEqual(cli_main(["--recycle-restore-verify"]), 2)
        self.assertEqual(
            cli_main(["--recycle-restore-prepare", "one", "two"]),
            2,
        )
        self.assertEqual(cli_main(["--unknown-recycle-command"]), 2)


if __name__ == "__main__":
    unittest.main()
