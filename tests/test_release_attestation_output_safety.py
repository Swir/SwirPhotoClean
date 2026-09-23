import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from photoclean.diagnostics import _atomic_write_json
from photoclean.recycle_evidence import prepare_restore_evidence, verify_restore_evidence
from photoclean.release_attestation import (
    ATTESTATION_NAME,
    PackagedAttestationError,
    validate_packaged_attestation,
    write_packaged_attestation,
)


class ReleaseAttestationOutputSafetyTests(unittest.TestCase):
    def _verified_packaged_report(self, folder: str):
        def fake_recycler(path):
            Path(path).unlink()

        recycled = prepare_restore_evidence(folder, recycler=fake_recycler)
        shutil.copy2(recycled.original, recycled.copy)
        verified, _report = verify_restore_evidence(recycled.manifest)

        manifest = json.loads(verified.manifest.read_text(encoding="utf-8"))
        manifest["environment"]["frozen"] = True
        manifest["environment"]["platform"] = "Windows-11-10.0.26100-SP0"
        _atomic_write_json(verified.manifest, manifest)

        verified, report = verify_restore_evidence(verified.manifest)
        return verified, report

    def test_attestation_output_cannot_overwrite_source_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            verified, report = self._verified_packaged_report(folder)
            protected = [report, verified.manifest, verified.original, verified.copy]
            before = {path: path.read_bytes() for path in protected}

            for target in protected:
                with self.subTest(target=target.name):
                    with self.assertRaises(PackagedAttestationError):
                        write_packaged_attestation(
                            report,
                            target,
                            confirm_manual_restore=True,
                        )
                    self.assertEqual(target.read_bytes(), before[target])

    def test_attestation_output_cannot_hardlink_alias_source_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            _verified, report = self._verified_packaged_report(folder)
            alias = report.parent / "release-evidence-hardlink.json"
            try:
                os.link(report, alias)
            except OSError as error:
                self.skipTest(f"hardlinks unavailable in test environment: {error}")
            before = report.read_bytes()

            # The newer snapshot intake can reject the now-hardlinked source report
            # before the writer reaches its output-alias guard. Both paths are
            # deliberately fail-closed and must preserve both filesystem entries.
            with self.assertRaisesRegex(
                PackagedAttestationError,
                "overwrite or alias|must not be hardlinked",
            ):
                write_packaged_attestation(
                    report,
                    alias,
                    confirm_manual_restore=True,
                )

            self.assertEqual(report.read_bytes(), before)
            self.assertEqual(alias.read_bytes(), before)

    def test_attestation_writer_rejects_symlink_output(self):
        with tempfile.TemporaryDirectory() as folder:
            _verified, report = self._verified_packaged_report(folder)
            destination = report.parent / "unrelated.json"
            destination.write_text("keep", encoding="utf-8")
            output = report.parent / ATTESTATION_NAME
            try:
                output.symlink_to(destination)
            except OSError as error:
                self.skipTest(f"symlinks unavailable in test environment: {error}")

            with self.assertRaisesRegex(PackagedAttestationError, "symlink"):
                write_packaged_attestation(
                    report,
                    output,
                    confirm_manual_restore=True,
                )

            self.assertEqual(destination.read_text(encoding="utf-8"), "keep")

    def test_attestation_writer_does_not_reuse_predictable_tmp_path(self):
        with tempfile.TemporaryDirectory() as folder:
            _verified, report = self._verified_packaged_report(folder)
            output = report.parent / ATTESTATION_NAME
            legacy_tmp = output.with_suffix(output.suffix + ".tmp")
            legacy_tmp.write_text("do-not-touch", encoding="utf-8")

            written = write_packaged_attestation(
                report,
                output,
                confirm_manual_restore=True,
            )

            self.assertEqual(written, output.resolve())
            self.assertEqual(legacy_tmp.read_text(encoding="utf-8"), "do-not-touch")
            payload = validate_packaged_attestation(
                json.loads(output.read_text(encoding="utf-8"))
            )
            self.assertTrue(payload["manual_restore_performed"])
            self.assertFalse(payload["acceptance_gate_closed"])

    def test_attestation_writer_detects_output_identity_change_before_replace(self):
        with tempfile.TemporaryDirectory() as folder:
            _verified, report = self._verified_packaged_report(folder)
            output = report.parent / ATTESTATION_NAME

            with patch(
                "photoclean.release_attestation._attestation_output_identity",
                side_effect=[None, (1, 2, 3, 4, 5)],
            ):
                with self.assertRaisesRegex(PackagedAttestationError, "changed while validated"):
                    write_packaged_attestation(
                        report,
                        output,
                        confirm_manual_restore=True,
                    )

            self.assertFalse(output.exists())
            self.assertEqual(list(report.parent.glob(".RELEASE_EVIDENCE.json.*.tmp")), [])

    def test_attestation_writer_cleans_stage_when_atomic_replace_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            _verified, report = self._verified_packaged_report(folder)
            output = report.parent / ATTESTATION_NAME

            with patch(
                "photoclean.release_attestation.os.replace",
                side_effect=OSError("simulated replace failure"),
            ):
                with self.assertRaisesRegex(PackagedAttestationError, "atomically replace"):
                    write_packaged_attestation(
                        report,
                        output,
                        confirm_manual_restore=True,
                    )

            self.assertFalse(output.exists())
            self.assertEqual(list(report.parent.glob(".RELEASE_EVIDENCE.json.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
