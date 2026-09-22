import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from photoclean.diagnostics import RecycleVerificationError
from photoclean.diagnostics_gui import DiagnosticsWindow


class DummyWidget:
    def __init__(self):
        self.options = {}

    def configure(self, **kwargs):
        self.options.update(kwargs)


class DummyVar:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = value


class DummyRoot:
    def __init__(self):
        self.clipboard = None

    def clipboard_clear(self):
        self.clipboard = ""

    def clipboard_append(self, value):
        self.clipboard = value


def fake_check(folder: Path, stage="prepared"):
    return SimpleNamespace(
        folder=folder,
        manifest=folder / "recycle-verification.json",
        original=folder / "KEEP-ME.png",
        copy=folder / "RECYCLE-ME.png",
        stage=stage,
    )


def bare_window(check=None):
    window = DiagnosticsWindow.__new__(DiagnosticsWindow)
    window.window = object()
    window.check = check
    window.evidence_report = None
    window.release_attestation = None
    window.recycle_status = DummyVar()
    window.prepare_button = DummyWidget()
    window.move_button = DummyWidget()
    window.verify_button = DummyWidget()
    window.attest_button = DummyWidget()
    window.open_button = DummyWidget()
    window.copy_button = DummyWidget()
    window.resume_button = DummyWidget()
    window.app = SimpleNamespace(root=DummyRoot())
    return window


class DiagnosticsResumeEvidenceTests(unittest.TestCase):
    def test_resume_prepared_session_revalidates_contract_and_enables_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            manifest = folder / "recycle-verification.json"
            prepared = fake_check(folder, "prepared")
            window = bare_window()

            with (
                patch("photoclean.diagnostics_gui.filedialog.askopenfilename", return_value=str(manifest)),
                patch("photoclean.diagnostics_gui.load_recycle_verification", return_value=prepared) as load_check,
                patch("photoclean.diagnostics_gui._require_runtime_safety_contract") as require_contract,
            ):
                window.resume_check()

            load_check.assert_called_once_with(manifest.resolve())
            require_contract.assert_called_once_with(prepared)
            self.assertIs(window.check, prepared)
            self.assertEqual(window.move_button.options["state"], "normal")
            self.assertEqual(window.verify_button.options["state"], "disabled")
            self.assertEqual(window.attest_button.options["state"], "disabled")
            self.assertEqual(window.open_button.options["state"], "normal")
            self.assertEqual(window.copy_button.options["state"], "normal")

    def test_resume_recycled_session_enables_verify_without_mutating_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            manifest = folder / "recycle-verification.json"
            recycled = fake_check(folder, "recycled")
            window = bare_window()

            with (
                patch("photoclean.diagnostics_gui.filedialog.askopenfilename", return_value=str(manifest)),
                patch("photoclean.diagnostics_gui.load_recycle_verification", return_value=recycled),
                patch("photoclean.diagnostics_gui._require_runtime_safety_contract"),
            ):
                window.resume_check()

            self.assertIs(window.check, recycled)
            self.assertEqual(window.move_button.options["state"], "disabled")
            self.assertEqual(window.verify_button.options["state"], "normal")
            self.assertEqual(window.attest_button.options["state"], "disabled")
            self.assertIsNone(window.evidence_report)

    def test_resume_verified_session_revalidates_existing_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            manifest = folder / "recycle-verification.json"
            report = folder / "recycle-evidence-report.json"
            report.write_text("{}", encoding="utf-8")
            verified = fake_check(folder, "restored-verified")
            window = bare_window()

            with (
                patch("photoclean.diagnostics_gui.filedialog.askopenfilename", return_value=str(manifest)),
                patch("photoclean.diagnostics_gui.load_recycle_verification", return_value=verified),
                patch("photoclean.diagnostics_gui._require_runtime_safety_contract"),
                patch(
                    "photoclean.diagnostics_gui.validate_restore_evidence_report",
                    return_value=(verified, report),
                ) as validate_report,
            ):
                window.resume_check()

            validate_report.assert_called_once_with(report, manifest=verified.manifest)
            self.assertEqual(window.evidence_report, report)
            self.assertIsNone(window.release_attestation)
            self.assertEqual(window.verify_button.options["state"], "disabled")
            self.assertEqual(window.attest_button.options["state"], "normal")
            self.assertEqual(window.copy_button.options["state"], "normal")
            self.assertIn(str(report), window.recycle_status.value)

    def test_resume_verified_session_without_report_allows_safe_regeneration(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            manifest = folder / "recycle-verification.json"
            verified = fake_check(folder, "restored-verified")
            window = bare_window()

            with (
                patch("photoclean.diagnostics_gui.filedialog.askopenfilename", return_value=str(manifest)),
                patch("photoclean.diagnostics_gui.load_recycle_verification", return_value=verified),
                patch("photoclean.diagnostics_gui._require_runtime_safety_contract"),
            ):
                window.resume_check()

            self.assertIs(window.check, verified)
            self.assertIsNone(window.evidence_report)
            self.assertIsNone(window.release_attestation)
            self.assertEqual(window.verify_button.options["state"], "normal")
            self.assertEqual(window.attest_button.options["state"], "disabled")
            self.assertIn("odtworzyć", window.recycle_status.value)

    def test_resume_rejects_manifest_from_different_safety_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            manifest = folder / "recycle-verification.json"
            stale = fake_check(folder, "prepared")
            window = bare_window()

            with (
                patch("photoclean.diagnostics_gui.filedialog.askopenfilename", return_value=str(manifest)),
                patch("photoclean.diagnostics_gui.load_recycle_verification", return_value=stale),
                patch(
                    "photoclean.diagnostics_gui._require_runtime_safety_contract",
                    side_effect=RecycleVerificationError("different release safety contract"),
                ),
                patch("photoclean.diagnostics_gui.messagebox.showerror") as show_error,
            ):
                window.resume_check()

            self.assertIsNone(window.check)
            show_error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
