import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from photoclean.diagnostics_plus_gui import validate_resumed_release_attestation
from photoclean.release_attestation import PackagedAttestationError


def fake_check(folder: Path):
    return SimpleNamespace(
        folder=folder,
        manifest=folder / "recycle-verification.json",
        stage="restored-verified",
        session_id="1" * 32,
        digest="2" * 64,
        manifest_fingerprint="3" * 64,
    )


class DiagnosticsResumeInputSafetyTests(unittest.TestCase):
    def test_resumed_attestation_rejects_symlink_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            report = folder / "recycle-evidence-report-real.json"
            report.write_bytes(b"stable-report\n")
            linked = folder / "recycle-evidence-report.json"
            try:
                linked.symlink_to(report)
            except OSError as error:
                self.skipTest(f"symlinks unavailable in test environment: {error}")

            attestation = folder / "RELEASE_EVIDENCE.json"
            attestation.write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(
                PackagedAttestationError,
                "symlink, junction or reparse point",
            ):
                validate_resumed_release_attestation(
                    fake_check(folder),
                    linked,
                    attestation,
                )

    def test_resumed_attestation_rejects_hardlinked_attestation(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            report = folder / "recycle-evidence-report.json"
            report.write_bytes(b"stable-report\n")

            target = folder / "RELEASE_EVIDENCE-source.json"
            target.write_text("{}", encoding="utf-8")
            linked = folder / "RELEASE_EVIDENCE.json"
            try:
                os.link(target, linked)
            except OSError as error:
                self.skipTest(f"hardlinks unavailable in test environment: {error}")

            with self.assertRaisesRegex(PackagedAttestationError, "hardlinked"):
                validate_resumed_release_attestation(
                    fake_check(folder),
                    report,
                    linked,
                )


if __name__ == "__main__":
    unittest.main()
