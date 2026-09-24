import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from photoclean.diagnostics import _atomic_write_json
from photoclean.recycle_evidence import prepare_restore_evidence, verify_restore_evidence
from tools import release_evidence as release_evidence_module
from tools.release_evidence import ReleaseEvidenceError, write_release_evidence


class ReleaseEvidenceOutputAncestryTests(unittest.TestCase):
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

    def test_writer_creates_missing_safe_output_directory_ancestry(self):
        with tempfile.TemporaryDirectory() as folder:
            report = self._verified_report(folder)
            output = Path(folder) / "safe" / "nested" / "RELEASE_EVIDENCE.json"

            written = write_release_evidence(
                report,
                output,
                confirm_manual_restore=True,
            )

            self.assertEqual(written, output.resolve())
            self.assertTrue(output.is_file())

    def test_writer_rejects_symlinked_output_directory_ancestry(self):
        with tempfile.TemporaryDirectory() as folder:
            report = self._verified_report(folder)
            root = Path(folder)
            real = root / "real-output"
            real.mkdir()
            alias = root / "redirected-output"
            try:
                os.symlink(real, alias, target_is_directory=True)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"directory symlinks unavailable in test environment: {error}")

            output = alias / "RELEASE_EVIDENCE.json"
            with self.assertRaisesRegex(
                ReleaseEvidenceError,
                "directory ancestry must not contain symlinks|junctions|reparse points",
            ):
                write_release_evidence(
                    report,
                    output,
                    confirm_manual_restore=True,
                )

            self.assertFalse((real / "RELEASE_EVIDENCE.json").exists())

    def test_writer_rejects_unrelated_hardlinked_existing_output(self):
        with tempfile.TemporaryDirectory() as folder:
            report = self._verified_report(folder)
            root = Path(folder)
            sentinel = root / "unrelated.json"
            output = root / "RELEASE_EVIDENCE.json"
            before = b"do-not-replace-this-hardlink"
            sentinel.write_bytes(before)
            try:
                os.link(sentinel, output)
            except OSError as error:
                self.skipTest(f"hardlinks unavailable in test environment: {error}")

            with self.assertRaisesRegex(ReleaseEvidenceError, "must not be hardlinked"):
                write_release_evidence(
                    report,
                    output,
                    confirm_manual_restore=True,
                )

            self.assertEqual(sentinel.read_bytes(), before)
            self.assertEqual(output.read_bytes(), before)

    def test_late_ancestry_failure_cleans_randomized_staging_file(self):
        with tempfile.TemporaryDirectory() as folder:
            report = self._verified_report(folder)
            output = Path(folder) / "RELEASE_EVIDENCE.json"
            original_check = (
                release_evidence_module._require_safe_release_evidence_directory_ancestry
            )
            calls = 0

            def fail_after_stage_before_commit(directory, *, allow_missing=False):
                nonlocal calls
                calls += 1
                # The fourth ancestry check occurs after the exclusive staging file
                # has been written/validated but before os.replace commits it. A
                # failure there must clean staging and leave the destination absent.
                if calls == 4:
                    raise ReleaseEvidenceError("simulated late output ancestry redirect")
                return original_check(directory, allow_missing=allow_missing)

            with patch(
                "tools.release_evidence._require_safe_release_evidence_directory_ancestry",
                side_effect=fail_after_stage_before_commit,
            ):
                with self.assertRaisesRegex(ReleaseEvidenceError, "late output ancestry redirect"):
                    write_release_evidence(
                        report,
                        output,
                        confirm_manual_restore=True,
                    )

            self.assertFalse(output.exists())
            self.assertEqual(list(Path(folder).glob(".RELEASE_EVIDENCE.json.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
