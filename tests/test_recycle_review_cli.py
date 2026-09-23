import io
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from photoclean.recycle_evidence import prepare_restore_evidence, verify_restore_evidence
from photoclean.recycle_review_cli import cli_main


class RecycleReviewCliTests(unittest.TestCase):
    def _verified_report(self, folder: str):
        def fake_recycler(path):
            Path(path).unlink()

        recycled = prepare_restore_evidence(folder, recycler=fake_recycler)
        shutil.copy2(recycled.original, recycled.copy)
        return verify_restore_evidence(recycled.manifest)

    def test_review_uses_snapshot_and_prints_packaged_attestation_handoff(self):
        with tempfile.TemporaryDirectory() as folder:
            verified, report = self._verified_report(folder)
            before_manifest = verified.manifest.read_bytes()
            before_report = report.read_bytes()

            stream = io.StringIO()
            with redirect_stdout(stream):
                code = cli_main(["--recycle-restore-review", str(report)])

            output = stream.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("REPORT_VALID", output)
            self.assertIn("--recycle-restore-attest", output)
            self.assertIn("--confirm-manual-restore", output)
            self.assertIn("READY_FOR_MANUAL_ACCEPTANCE_REVIEW", output)
            self.assertEqual(verified.manifest.read_bytes(), before_manifest)
            self.assertEqual(report.read_bytes(), before_report)

    def test_review_rejects_hardlinked_report_before_ready_message(self):
        with tempfile.TemporaryDirectory() as folder:
            _verified, report = self._verified_report(folder)
            alias = report.parent / "review-alias.json"
            try:
                os.link(report, alias)
            except OSError as error:
                self.skipTest(f"hardlinks unavailable in test environment: {error}")

            stream = io.StringIO()
            with redirect_stdout(stream):
                code = cli_main(["--recycle-restore-review", str(alias)])

            output = stream.getvalue()
            self.assertEqual(code, 2)
            self.assertIn("EVIDENCE_FAILED", output)
            self.assertIn("hardlinked", output)
            self.assertNotIn("READY_FOR_MANUAL_ACCEPTANCE_REVIEW", output)

    def test_status_rejects_hardlinked_report_before_ready_message(self):
        with tempfile.TemporaryDirectory() as folder:
            verified, report = self._verified_report(folder)
            alias = report.parent / "status-alias.json"
            try:
                os.link(report, alias)
            except OSError as error:
                self.skipTest(f"hardlinks unavailable in test environment: {error}")

            stream = io.StringIO()
            with redirect_stdout(stream):
                code = cli_main(["--recycle-restore-status", str(verified.manifest)])

            output = stream.getvalue()
            self.assertEqual(code, 2)
            self.assertIn("EVIDENCE_FAILED", output)
            self.assertIn("hardlinked", output)
            self.assertNotIn("READY_FOR_REVIEW", output)

    def test_non_review_commands_delegate_to_authoritative_workflow(self):
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = cli_main(["--recycle-restore-move"])
        self.assertEqual(code, 2)
        self.assertIn("move requires exactly one", stream.getvalue())

    def test_review_bad_arity_fails_closed(self):
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = cli_main(["--recycle-restore-review"])
        self.assertEqual(code, 2)
        self.assertIn("review requires exactly one", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
