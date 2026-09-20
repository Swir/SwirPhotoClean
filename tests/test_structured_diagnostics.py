import json
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from photoclean import i18n
from photoclean.core import ScanIssue, ScanResult, scan
from photoclean.diagnostics_plus_gui import EnhancedDiagnosticsWindow, category_label
from photoclean.folder_health_app import PhotoCleanApp
from photoclean.scan_diagnostics import (
    build_scan_diagnostics_report,
    classify_scan_warning,
    scan_issue_records,
    summarize_scan_result,
    summarize_scan_warnings,
    write_scan_diagnostics_report,
)


class StructuredDiagnosticsTests(unittest.TestCase):
    def test_known_polish_and_english_scanner_reasons_are_stable(self):
        cases = {
            "C:/missing: folder niedostępny lub dowiązanie": "root_unavailable",
            "C:/missing: folder unavailable or a link": "root_unavailable",
            "C:/photo.jpg: dowiązanie / plik chmurowy — pominięty": "reparse_skipped",
            "C:/photo.jpg: another hard link to the same file — skipped": "hardlink_skipped",
            "C:/huge.jpg: image exceeds the 40 megapixel limit": "pixel_limit",
            "C:/anim.gif: obraz animowany lub wielostronicowy — pominięty": "multi_frame",
            "C:/photo.jpg: file changed during scanning": "changed_during_scan",
            "C:/private.jpg: [WinError 5] Access is denied": "access_error",
            "C:/broken.jpg: cannot identify image file": "image_read_error",
        }
        for warning, expected in cases.items():
            with self.subTest(warning=warning):
                self.assertEqual(classify_scan_warning(warning), expected)

    def test_native_scanner_issue_is_language_independent(self):
        original_language = i18n.language
        try:
            for language in ("pl", "en"):
                with self.subTest(language=language), tempfile.TemporaryDirectory() as folder:
                    i18n.language = language
                    photo = Path(folder) / "large.png"
                    Image.new("RGB", (20, 20), "navy").save(photo)
                    with patch("photoclean.core.MAX_PIXELS", 100):
                        result = scan([folder], include_similar=False)
                    self.assertEqual(len(result.warnings), 1)
                    self.assertEqual(len(result.issues), 1)
                    self.assertEqual(result.issues[0].category, "pixel_limit")
                    self.assertEqual(result.issues[0].path, photo)
                    report = build_scan_diagnostics_report(result)
                    self.assertEqual(report["issue_counts"], {"pixel_limit": 1})
                    self.assertEqual(report["scan"]["issue_source"], "structured")
        finally:
            i18n.language = original_language

    def test_root_permission_failure_becomes_structured_issue(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            real_linked = __import__("photoclean.core", fromlist=["linked"]).linked

            def fail_root(path):
                if Path(path) == root:
                    raise PermissionError("test access denied")
                return real_linked(path)

            with patch("photoclean.core.linked", side_effect=fail_root):
                result = scan([root], include_similar=False)
            self.assertEqual(result.photos, [])
            self.assertEqual(len(result.warnings), 1)
            self.assertEqual(len(result.issues), 1)
            self.assertEqual(result.issues[0].category, "access_error")
            self.assertIn("test access denied", result.issues[0].message)

    def test_structured_category_wins_over_legacy_text_guess(self):
        message = "C:/broken.jpg: cannot identify image file"
        result = ScanResult(
            warnings=[message],
            issues=[ScanIssue("walk_error", message, Path("C:/broken.jpg"))],
        )
        self.assertEqual(scan_issue_records(result), (("walk_error", message),))
        self.assertEqual(summarize_scan_result(result), (("walk_error", 1),))
        report = build_scan_diagnostics_report(result)
        self.assertEqual(report["issue_counts"], {"walk_error": 1})
        self.assertEqual(report["scan"]["issue_source"], "structured")

    def test_mismatched_structured_metadata_falls_back_without_losing_warnings(self):
        result = ScanResult(
            warnings=["C:/bad.jpg: cannot identify image file"],
            issues=[],
        )
        self.assertEqual(
            scan_issue_records(result),
            (("image_read_error", "C:/bad.jpg: cannot identify image file"),),
        )
        self.assertEqual(build_scan_diagnostics_report(result)["scan"]["issue_source"], "legacy-warning-fallback")

    def test_summary_and_json_report_preserve_raw_messages(self):
        result = ScanResult(
            warnings=[
                "C:/a.gif: animated or multi-page image — skipped",
                "C:/b.gif: animated or multi-page image — skipped",
                "C:/c.jpg: [WinError 5] Access is denied",
            ]
        )
        self.assertEqual(
            summarize_scan_warnings(result.warnings),
            (("multi_frame", 2), ("access_error", 1)),
        )
        self.assertEqual(
            summarize_scan_result(result),
            (("multi_frame", 2), ("access_error", 1)),
        )
        report = build_scan_diagnostics_report(result, marked_count=3)
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["scan"]["warnings"], 3)
        self.assertEqual(report["scan"]["marked_for_recycle_bin"], 3)
        self.assertEqual(report["scan"]["issue_source"], "legacy-warning-fallback")
        self.assertEqual(report["issue_counts"], {"multi_frame": 2, "access_error": 1})
        self.assertEqual(len(report["issues"]), 3)
        self.assertIn("local file paths", report["privacy_note"])

    def test_export_is_valid_json_and_contains_no_photo_bytes(self):
        result = ScanResult(warnings=["C:/bad.jpg: cannot identify image file"])
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "diagnostics.json"
            written = write_scan_diagnostics_report(result, target)
            payload = json.loads(written.read_text(encoding="utf-8"))
            self.assertEqual(payload["issue_counts"], {"image_read_error": 1})
            self.assertNotIn("photo_bytes", payload)
            self.assertFalse(any(path.suffix == ".tmp" for path in Path(folder).iterdir()))

    def test_final_app_uses_enhanced_diagnostics_without_mutating_marks(self):
        settings_dir = tempfile.TemporaryDirectory()
        root = tk.Tk()
        root.withdraw()
        app = PhotoCleanApp(root, Path(settings_dir.name) / "settings.json")
        try:
            app.result = ScanResult(
                warnings=[
                    "C:/huge.jpg: obraz przekracza limit 40 megapikseli",
                    "C:/broken.jpg: cannot identify image file",
                ]
            )
            app.marked = {Path("C:/planned.jpg")}
            before = set(app.marked)
            app.open_diagnostics()
            root.update_idletasks()

            self.assertIsInstance(app.diagnostics_view, EnhancedDiagnosticsWindow)
            self.assertEqual(
                app.diagnostics_view.issue_summary,
                (("pixel_limit", 1), ("image_read_error", 1)),
            )
            self.assertEqual(app.marked, before)
            self.assertTrue(root.bind("<Control-Shift-D>"))
            self.assertTrue(category_label("pixel_limit"))
        finally:
            if getattr(app, "diagnostics_view", None) is not None:
                try:
                    app.diagnostics_view.window.destroy()
                except tk.TclError:
                    pass
            root.after_cancel(app.poll_id)
            root.destroy()
            settings_dir.cleanup()


if __name__ == "__main__":
    unittest.main()