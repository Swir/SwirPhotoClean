import json
import shutil
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
