import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

from photoclean.diagnostics import _atomic_write_json
from photoclean.recycle_evidence import (
    prepare_restore_evidence,
    verify_restore_evidence,
)
from photoclean.release_attestation import (
    PackagedAttestationError,
    build_packaged_attestation,
    validate_packaged_attestation,
)
from photoclean.release_evidence_cli import cli_main
from tools.release_evidence import build_release_evidence


class PackagedReleaseAttestationTests(unittest.TestCase):
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

    def test_packaged_builder_matches_repository_release_schema(self):
        with tempfile.TemporaryDirectory() as folder:
            _verified, report = self._verified_packaged_report(folder)
            reviewed_at = datetime(
                2026,
                9,
                21,
                15,
                0,
                0,
                tzinfo=timezone.utc,
            )

            repository_payload = build_release_evidence(
                report,
                confirm_manual_restore=True,
                reviewed_at=reviewed_at,
            )
            packaged_payload = build_packaged_attestation(
                report,
                confirm_manual_restore=True,
                reviewed_at=reviewed_at,
            )

            self.assertEqual(packaged_payload, repository_payload)
            self.assertFalse(packaged_payload["acceptance_gate_closed"])

    def test_packaged_cli_writes_and_revalidates_default_output(self):
        with tempfile.TemporaryDirectory() as folder:
            _verified, report = self._verified_packaged_report(folder)
            stdout = StringIO()

            with redirect_stdout(stdout):
                result = cli_main(
                    [
                        "--recycle-restore-attest",
                        str(report),
                        "--confirm-manual-restore",
                    ]
                )

            self.assertEqual(result, 0)
            output = report.parent / "RELEASE_EVIDENCE.json"
            self.assertTrue(output.is_file())
            payload = validate_packaged_attestation(
                json.loads(output.read_text(encoding="utf-8"))
            )
            self.assertTrue(payload["manual_restore_performed"])
            self.assertTrue(payload["windows_packaged_runtime_confirmed"])
            self.assertFalse(payload["acceptance_gate_closed"])
            self.assertIn("RELEASE_EVIDENCE_VALID=yes", stdout.getvalue())

    def test_packaged_cli_requires_explicit_manual_restore_confirmation(self):
        with tempfile.TemporaryDirectory() as folder:
            _verified, report = self._verified_packaged_report(folder)
            stdout = StringIO()

            with redirect_stdout(stdout):
                result = cli_main(
                    [
                        "--recycle-restore-attest",
                        str(report),
                    ]
                )

            self.assertEqual(result, 2)
            self.assertFalse((report.parent / "RELEASE_EVIDENCE.json").exists())
            self.assertIn("--confirm-manual-restore", stdout.getvalue())

    def test_packaged_builder_rejects_tampered_report(self):
        with tempfile.TemporaryDirectory() as folder:
            _verified, report = self._verified_packaged_report(folder)
            payload = json.loads(report.read_text(encoding="utf-8"))
            payload["inspection"]["copy_matches"] = False
            report.write_text(
                json.dumps(payload, indent=2),
                encoding="utf-8",
            )

            with self.assertRaises(PackagedAttestationError):
                build_packaged_attestation(
                    report,
                    confirm_manual_restore=True,
                )


if __name__ == "__main__":
    unittest.main()
