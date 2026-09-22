import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from photoclean.diagnostics import _atomic_write_json
from photoclean.recycle_evidence import prepare_restore_evidence, verify_restore_evidence
from tools.release_evidence import ReleaseEvidenceError, write_release_evidence


class ReleaseEvidenceOutputSafetyTests(unittest.TestCase):
    def _verified_report(self, folder: str) -> Path:
        def fake_recycler(path):
            Path(path).unlink()

        recycled = prepare_restore_evidence(folder, recycler=fake_recycler)
        shutil.copy2(recycled.original, recycled.copy)
        verified, _report = verify_restore_evidence(recycled.manifest)

        manifest = json.loads(verified.manifest.read_text(encoding="utf-8"))
        manifest["environment"]["frozen"] = True
        manifest["environment"]["platform"] = "Windows-11-10.0.26100-SP0"
        _atomic_write_json(verified.manifest, manifest)

        _verified, report = verify_restore_evidence(verified.manifest)
        return report

    def test_writer_refuses_to_overwrite_raw_report(self):
        with tempfile.TemporaryDirectory() as folder:
            report = self._verified_report(folder)
            before = report.read_bytes()

            with self.assertRaisesRegex(ReleaseEvidenceError, "overwrite or alias"):
                write_release_evidence(
                    report,
                    report,
                    confirm_manual_restore=True,
                )

            self.assertEqual(report.read_bytes(), before)

    def test_writer_refuses_hardlink_alias_to_raw_report(self):
        with tempfile.TemporaryDirectory() as folder:
            report = self._verified_report(folder)
            alias = Path(folder) / "release-evidence-hardlink.json"
            try:
                os.link(report, alias)
            except OSError as error:
                self.skipTest(f"hardlinks unavailable in test environment: {error}")
            before = report.read_bytes()

            with self.assertRaisesRegex(ReleaseEvidenceError, "overwrite or alias"):
                write_release_evidence(
                    report,
                    alias,
                    confirm_manual_restore=True,
                )

            self.assertEqual(report.read_bytes(), before)
            self.assertEqual(alias.read_bytes(), before)

    def test_writer_does_not_reuse_legacy_fixed_tmp_path(self):
        with tempfile.TemporaryDirectory() as folder:
            report = self._verified_report(folder)
            output = Path(folder) / "RELEASE_EVIDENCE.json"
            legacy_tmp = output.with_suffix(output.suffix + ".tmp")
            sentinel = b"stale-temporary-sentinel"
            legacy_tmp.write_bytes(sentinel)

            written = write_release_evidence(
                report,
                output,
                confirm_manual_restore=True,
            )

            self.assertEqual(written, output.resolve())
            self.assertTrue(output.is_file())
            self.assertEqual(legacy_tmp.read_bytes(), sentinel)
            self.assertEqual(list(Path(folder).glob(".RELEASE_EVIDENCE.json.*.tmp")), [])

    def test_failed_atomic_replace_cleans_exclusive_stage(self):
        with tempfile.TemporaryDirectory() as folder:
            report = self._verified_report(folder)
            output = Path(folder) / "RELEASE_EVIDENCE.json"

            with patch(
                "tools.release_evidence.os.replace",
                side_effect=OSError("simulated replace failure"),
            ):
                with self.assertRaisesRegex(ReleaseEvidenceError, "atomically replace"):
                    write_release_evidence(
                        report,
                        output,
                        confirm_manual_restore=True,
                    )

            self.assertFalse(output.exists())
            self.assertEqual(list(Path(folder).glob(".RELEASE_EVIDENCE.json.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
