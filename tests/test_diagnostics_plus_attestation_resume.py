import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from photoclean.diagnostics import RecycleVerificationError
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


def fake_check(folder: Path, *, stage="restored-verified"):
    return SimpleNamespace(
        folder=folder,
        manifest=folder / "recycle-evidence.json",
        stage=stage,
        session_id="1" * 32,
        digest="2" * 64,
        manifest_fingerprint="3" * 64,
    )


def make_window():
    window = EnhancedDiagnosticsWindow.__new__(EnhancedDiagnosticsWindow)
    window.window = object()
    window.check = None
    window.evidence_report = None
    window.release_attestation = None
    window.attest_button = DummyWidget(state="normal")
    window.copy_button = DummyWidget(state="normal")
    window.recycle_status = DummyVar()

    def apply_state(check, report=None):
        window.check = check
        window.evidence_report = report
        window.release_attestation = None

    window._apply_check_state = apply_state
    return window


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

            self.assertEqual(result, attestation.absolute())
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
            check = fake_check(folder)
            check.manifest.write_text("{}", encoding="utf-8")
            report = folder / "recycle-evidence-report.json"
            report.write_text("{}", encoding="utf-8")
            attestation = folder / "RELEASE_EVIDENCE.json"
            attestation.write_text("{}", encoding="utf-8")
            window = make_window()

            with (
                patch("photoclean.diagnostics_plus_gui.filedialog.askopenfilename", return_value=str(check.manifest)),
                patch("photoclean.diagnostics_plus_gui.load_recycle_verification", return_value=check),
                patch("photoclean.diagnostics_plus_gui._require_runtime_safety_contract") as require_contract,
                patch("photoclean.diagnostics_plus_gui.validate_restore_evidence_report") as validate_report,
                patch(
                    "photoclean.diagnostics_plus_gui.validate_resumed_release_attestation",
                    return_value=attestation.resolve(),
                ) as validate_existing,
            ):
                window.resume_check()

            require_contract.assert_called_once_with(check)
            validate_report.assert_called_once_with(report, manifest=check.manifest)
            validate_existing.assert_called_once_with(check, report, attestation)
            self.assertIs(window.check, check)
            self.assertEqual(window.evidence_report, report)
            self.assertEqual(window.release_attestation, attestation.resolve())
            self.assertEqual(window.attest_button.options["state"], "disabled")
            self.assertEqual(window.copy_button.options["state"], "normal")
            self.assertIn("RELEASE_EVIDENCE", window.copy_button.options["text"])
            self.assertIn(str(attestation.resolve()), window.recycle_status.value)

    def test_invalid_existing_attestation_is_visible_and_not_adopted(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            check = fake_check(folder)
            check.manifest.write_text("{}", encoding="utf-8")
            report = folder / "recycle-evidence-report.json"
            report.write_text("{}", encoding="utf-8")
            attestation = folder / "RELEASE_EVIDENCE.json"
            attestation.write_text("{}", encoding="utf-8")
            window = make_window()

            with (
                patch("photoclean.diagnostics_plus_gui.filedialog.askopenfilename", return_value=str(check.manifest)),
                patch("photoclean.diagnostics_plus_gui.load_recycle_verification", return_value=check),
                patch("photoclean.diagnostics_plus_gui._require_runtime_safety_contract"),
                patch("photoclean.diagnostics_plus_gui.validate_restore_evidence_report"),
                patch(
                    "photoclean.diagnostics_plus_gui.validate_resumed_release_attestation",
                    side_effect=PackagedAttestationError("stale evidence"),
                ),
                patch("photoclean.diagnostics_plus_gui.messagebox.showerror") as show_error,
            ):
                window.resume_check()

            self.assertIs(window.check, check)
            self.assertEqual(window.evidence_report, report)
            self.assertIsNone(window.release_attestation)
            self.assertEqual(window.attest_button.options["state"], "normal")
            show_error.assert_called_once()

    def test_failed_new_manifest_cannot_recover_attestation_from_previous_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_folder = root / "old-session"
            old_folder.mkdir()
            old_check = fake_check(old_folder)
            old_report = old_folder / "recycle-evidence-report.json"
            old_report.write_text("{}", encoding="utf-8")
            old_attestation = old_folder / "RELEASE_EVIDENCE.json"
            old_attestation.write_text("{}", encoding="utf-8")

            window = make_window()
            window.check = old_check
            window.evidence_report = old_report
            window.release_attestation = old_attestation
            invalid_manifest = root / "broken.json"
            invalid_manifest.write_text("not-json", encoding="utf-8")

            with (
                patch("photoclean.diagnostics_plus_gui.filedialog.askopenfilename", return_value=str(invalid_manifest)),
                patch(
                    "photoclean.diagnostics_plus_gui.load_recycle_verification",
                    side_effect=RecycleVerificationError("bad manifest"),
                ),
                patch(
                    "photoclean.diagnostics_plus_gui.validate_resumed_release_attestation"
                ) as validate_existing,
                patch("photoclean.diagnostics_plus_gui.messagebox.showerror") as show_error,
            ):
                window.resume_check()

            validate_existing.assert_not_called()
            show_error.assert_called_once()
            self.assertIs(window.check, old_check)
            self.assertEqual(window.evidence_report, old_report)
            self.assertEqual(window.release_attestation, old_attestation)


if __name__ == "__main__":
    unittest.main()
