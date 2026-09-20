import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from photoclean.diagnostics import RecycleVerificationError, inspect_recycle_evidence
from photoclean.recycle_evidence import (
    cli_main,
    create_restore_evidence,
    move_restore_evidence,
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

    def test_prepared_fixture_can_retry_move_without_recreating_it(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder) / "workspace"
            prepared = create_restore_evidence(base)
            original_manifest = prepared.manifest
            original_folder = prepared.folder

            def fail(_path):
                raise OSError("temporary Recycle Bin failure")

            with self.assertRaises(RecycleVerificationError):
                move_restore_evidence(prepared.manifest, recycler=fail)

            after_failure = inspect_recycle_evidence(prepared.manifest)
            self.assertTrue(after_failure.valid)
            self.assertEqual(after_failure.stage, "prepared")
            self.assertTrue(prepared.original.exists())
            self.assertTrue(prepared.copy.exists())

            def fake_recycler(path):
                Path(path).unlink()

            recycled = move_restore_evidence(prepared.manifest, recycler=fake_recycler)
            self.assertEqual(recycled.manifest, original_manifest)
            self.assertEqual(recycled.folder, original_folder)
            self.assertEqual(recycled.stage, "recycled")
            self.assertTrue(recycled.original.exists())
            self.assertFalse(recycled.copy.exists())

    def test_status_command_is_read_only_across_recycle_and_restore_stages(self):
        with tempfile.TemporaryDirectory() as folder:
            def fake_recycler(path):
                Path(path).unlink()

            recycled = prepare_restore_evidence(folder, recycler=fake_recycler)
            before = recycled.manifest.read_text(encoding="utf-8")
            stream = io.StringIO()
            with redirect_stdout(stream):
                exit_code = cli_main(["--recycle-restore-status", str(recycled.manifest)])
            self.assertEqual(exit_code, 0)
            self.assertIn("EVIDENCE_VALID stage=recycled", stream.getvalue())
            self.assertIn("--recycle-restore-verify", stream.getvalue())
            self.assertEqual(recycled.manifest.read_text(encoding="utf-8"), before)

            shutil.copy2(recycled.original, recycled.copy)
            verified, report = verify_restore_evidence(recycled.manifest)
            before_verified = verified.manifest.read_text(encoding="utf-8")
            stream = io.StringIO()
            with redirect_stdout(stream):
                exit_code = cli_main(["--recycle-restore-status", str(verified.manifest)])
            self.assertEqual(exit_code, 0)
            self.assertIn("EVIDENCE_VALID stage=restored-verified", stream.getvalue())
            self.assertIn("REPORT_PRESENT=yes", stream.getvalue())
            self.assertIn("READY_FOR_REVIEW", stream.getvalue())
            self.assertTrue(report.is_file())
            self.assertEqual(verified.manifest.read_text(encoding="utf-8"), before_verified)

    def test_verify_refuses_missing_manual_restore(self):
        with tempfile.TemporaryDirectory() as folder:
            def fake_recycler(path):
                Path(path).unlink()

            recycled = prepare_restore_evidence(folder, recycler=fake_recycler)
            with self.assertRaises(RecycleVerificationError):
                verify_restore_evidence(recycled.manifest)

    def test_cli_rejects_bad_arity_without_starting_gui(self):
        self.assertEqual(cli_main(["--recycle-restore-verify"]), 2)
        self.assertEqual(cli_main(["--recycle-restore-move"]), 2)
        self.assertEqual(cli_main(["--recycle-restore-status"]), 2)
        self.assertEqual(
            cli_main(["--recycle-restore-prepare", "one", "two"]),
            2,
        )
        self.assertEqual(cli_main(["--unknown-recycle-command"]), 2)


if __name__ == "__main__":
    unittest.main()
