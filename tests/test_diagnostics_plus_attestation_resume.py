import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from photoclean.diagnostics_gui import DiagnosticsWindow
from photoclean.diagnostics_plus_gui import (
    EnhancedDiagnosticsWindow,
    validate_resumed_release_attestation,
)
from photoclean.release_attestation import PackagedAttestationError


class DummyWidget:
    def __init__(self, **options):
        self.options = dict(options)

    def configure(self, **kwargs):
        self.options.update(kwargs)


class DummyVar:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = value


def fake_check(folder: Path):
    return SimpleNamespace(
        folder=folder,
        session_id="1" * 32,
        digest="2" * 64,
        manifest_fingerprint="3" * 64,
    )


class DiagnosticsPersistedAttestationResumeTests(unittest.TestCase):
    def test_cross_check_binds_attestation_to_exact_resumed_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            report = folder / "recycle-evidence-report.json"
            report.write_bytes(b"qualified-report\n")
            attestation = folder / "RELEASE_EVIDENCE.json"
            attestation.write_text("{}", encoding="utf-8")
            check = fake_check(folder)
            validated = {
                "session_id": check.session_id,
                "fixture_sha256": check.digest,
                "manifest_fingerprint": check.manifest_fingerprint,
                "evidence_report_sha256": hashlib.sha256(report.read_bytes()).hexdigest(),
            }

            with patch(
                "photoclean.diagnostics_plus_gui.validate_packaged_attestation",
                return_value=validated,
            ) as validator:
                result = validate_resumed_release_attestation(check, report, attestation)

            self.assertEqual(result, attestation.resolve())
            validator.assert_called_once_with({})

    def test_cross_check_rejects_attestation_from_another_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            report = folder / "recycle-evidence-report.json"
            report.write_bytes(b"current-report\n")
            attestation = folder / "RELEASE_EVIDENCE.json"
            attestation.write_text(json.dumps({"schema_version": 3}), encoding="utf-8")
            check = fake_check(folder)
            validated = {
                "session_id": check.session_id,
                "fixture_sha256": check.digest,
                "manifest_fingerprint": check.manifest_fingerprint,
                "evidence_report_sha256": "9" * 64,
            }

            with patch(
                "photoclean.diagnostics_plus_gui.validate_packaged_attestation",
                return_value=validated,
            ):
                with self.assertRaisesRegex(
                    PackagedAttestationError,
                    "evidence_report_sha256",
                ):
                    validate_resumed_release_attestation(check, report, attestation)

    def test_resume_recovers_valid_existing_attestation_without_rewriting_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            report = folder / "recycle-evidence-report.json"
            report.write_text("{}", encoding="utf-8")
            attestation = folder / "RELEASE_EVIDENCE.json"
            attestation.write_text("{}", encoding="utf-8")
            check = fake_check(folder)

            window = EnhancedDiagnosticsWindow.__new__(EnhancedDiagnosticsWindow)
            window.window = object()
            window.check = None
            window.evidence_report = None
            window.release_attestation = None
            window.attest_button = DummyWidget(state="normal")
            window.copy_button = DummyWidget(state="normal")
            window.recycle_status = DummyVar()

            def base_resume(instance):
                instance.check = check
                instance.evidence_report = report

            with (
                patch.object(DiagnosticsWindow, "resume_check", autospec=True, side_effect=base_resume),
                patch(
                    "photoclean.diagnostics_plus_gui.validate_resumed_release_attestation",
                    return_value=attestation.resolve(),
                ) as validate_existing,
            ):
                window.resume_check()

            validate_existing.assert_called_once_with(check, report, attestation)
            self.assertEqual(window.release_attestation, attestation.resolve())
            self.assertEqual(window.attest_button.options["state"], "disabled")
            self.assertEqual(window.copy_button.options["state"], "normal")
            self.assertIn("RELEASE_EVIDENCE", window.copy_button.options["text"])
            self.assertIn(str(attestation.resolve()), window.recycle_status.value)

    def test_invalid_existing_attestation_is_visible_and_not_adopted(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            report = folder / "recycle-evidence-report.json"
            report.write_text("{}", encoding="utf-8")
            attestation = folder / "RELEASE_EVIDENCE.json"
            attestation.write_text("{}", encoding="utf-8")
            check = fake_check(folder)

            window = EnhancedDiagnosticsWindow.__new__(EnhancedDiagnosticsWindow)
            window.window = object()
            window.check = None
            window.evidence_report = None
            window.release_attestation = None
            window.attest_button = DummyWidget(state="normal")
            window.copy_button = DummyWidget(state="normal")
            window.recycle_status = DummyVar()

            def base_resume(instance):
                instance.check = check
                instance.evidence_report = report

            with (
                patch.object(DiagnosticsWindow, "resume_check", autospec=True, side_effect=base_resume),
                patch(
                    "photoclean.diagnostics_plus_gui.validate_resumed_release_attestation",
                    side_effect=PackagedAttestationError("stale evidence"),
                ),
                patch("photoclean.diagnostics_plus_gui.messagebox.showerror") as show_error,
            ):
                window.resume_check()

            self.assertIsNone(window.release_attestation)
            self.assertEqual(window.attest_button.options["state"], "normal")
            show_error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
