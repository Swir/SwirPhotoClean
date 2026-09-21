import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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
    window.recycle_status = DummyVar()
    window.prepare_button = DummyWidget()
    window.move_button = DummyWidget()
    window.verify_button = DummyWidget()
    window.open_button = DummyWidget()
    window.copy_button = DummyWidget()
    window.app = SimpleNamespace(root=DummyRoot())
    return window


class DiagnosticsReleaseEvidenceGuiTests(unittest.TestCase):
    def test_prepare_binds_gui_flow_to_release_qualified_evidence_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            prepared = fake_check(base)
            window = bare_window()

            with (
                patch("photoclean.diagnostics_gui.filedialog.askdirectory", return_value=str(base)),
                patch(
                    "photoclean.diagnostics_gui.inspect_recycle_support",
                    return_value=SimpleNamespace(ready=True, detail="ready"),
                ),
                patch(
                    "photoclean.diagnostics_gui.create_restore_evidence",
                    return_value=prepared,
                ) as create_restore,
            ):
                window.prepare_check()

            create_restore.assert_called_once_with(str(base))
            self.assertIs(window.check, prepared)
            self.assertIsNone(window.evidence_report)
            self.assertEqual(window.move_button.options["state"], "normal")
            self.assertEqual(window.verify_button.options["state"], "disabled")
            self.assertEqual(window.copy_button.options["state"], "normal")

    def test_move_reuses_bound_manifest_instead_of_raw_diagnostics_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            prepared = fake_check(Path(tmp))
            recycled = fake_check(Path(tmp), stage="recycled")
            window = bare_window(prepared)

            with (
                patch("photoclean.diagnostics_gui.messagebox.askyesno", return_value=True),
                patch(
                    "photoclean.diagnostics_gui.move_restore_evidence",
                    return_value=recycled,
                ) as move_restore,
            ):
                window.move_check()

            move_restore.assert_called_once_with(prepared.manifest)
            self.assertIs(window.check, recycled)
            self.assertEqual(window.move_button.options["state"], "disabled")
            self.assertEqual(window.verify_button.options["state"], "normal")

    def test_verify_exports_and_freshly_validates_release_evidence_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            recycled = fake_check(folder, stage="recycled")
            verified = fake_check(folder, stage="restored-verified")
            report = folder / "recycle-evidence-report.json"
            window = bare_window(recycled)

            with (
                patch(
                    "photoclean.diagnostics_gui.verify_restore_evidence",
                    return_value=(verified, report),
                ) as verify_restore,
                patch(
                    "photoclean.diagnostics_gui.validate_restore_evidence_report",
                    return_value=(verified, report),
                ) as validate_report,
                patch("photoclean.diagnostics_gui.messagebox.showinfo"),
            ):
                window.verify_check()

            verify_restore.assert_called_once_with(recycled.manifest)
            validate_report.assert_called_once_with(report, manifest=verified.manifest)
            self.assertIs(window.check, verified)
            self.assertEqual(window.evidence_report, report)
            self.assertEqual(window.verify_button.options["state"], "disabled")
            self.assertEqual(window.copy_button.options["state"], "normal")
            self.assertIn(str(report), window.recycle_status.value)

            window.copy_evidence_path()
            self.assertEqual(window.app.root.clipboard, str(report))

    def test_copy_uses_manifest_until_final_report_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            prepared = fake_check(Path(tmp))
            window = bare_window(prepared)

            window.copy_evidence_path()

            self.assertEqual(window.app.root.clipboard, str(prepared.manifest))


if __name__ == "__main__":
    unittest.main()
