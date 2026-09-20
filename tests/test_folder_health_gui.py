import tempfile
import tkinter as tk
import unittest
from pathlib import Path

from photoclean import i18n
from photoclean.core import Group, Photo, ScanResult
from photoclean.folder_health_app import PhotoCleanApp
from photoclean.folder_health_gui import FolderHealthWindow


def photo(name, *, size=1000, digest=None):
    return Photo(
        path=Path(name),
        size=size,
        modified_ns=1,
        device=1,
        inode=hash(name) & 0xFFFF,
        digest=digest or name,
        width=100,
        height=80,
        dhash=0,
        color=b"\0" * 192,
    )


class FolderHealthGuiTests(unittest.TestCase):
    def setUp(self):
        self.settings_dir = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.settings_dir.name) / "settings.json"

    def tearDown(self):
        self.settings_dir.cleanup()
        i18n.language = "pl"

    def _result(self):
        a = photo("library/a.png", size=3000, digest="same")
        b = photo("library/b.png", size=3000, digest="same")
        c = photo("library/c.jpg", size=2000)
        d = photo("library/d.jpg", size=1000)
        return ScanResult(
            photos=[a, b, c, d],
            groups=[
                Group("exact", (a, b)),
                Group("similar", (b, c)),
            ],
            warnings=["fixture warning"],
        )

    def test_window_reports_conservative_metrics_without_mutating_result(self):
        root = tk.Tk()
        root.withdraw()
        window = None
        try:
            result = self._result()
            before_groups = tuple(result.groups)
            before_warnings = tuple(result.warnings)
            window = FolderHealthWindow(root, result)
            root.update_idletasks()

            self.assertEqual(window.health.total_photos, 4)
            self.assertEqual(window.health.exact_duplicate_files, 1)
            self.assertEqual(window.health.exact_reclaimable_bytes, 3000)
            self.assertEqual(window.health.unflagged_files, 1)
            self.assertEqual(len(window.files.get_children()), 4)
            self.assertIn("2.9 KB", window.metric_vars["savings"].get())
            self.assertEqual(tuple(result.groups), before_groups)
            self.assertEqual(tuple(result.warnings), before_warnings)
        finally:
            if window is not None and window.window.winfo_exists():
                window.window.destroy()
            root.destroy()

    def test_english_window_is_localized(self):
        i18n.language = "en"
        root = tk.Tk()
        root.withdraw()
        window = None
        try:
            window = FolderHealthWindow(root, self._result())
            root.update_idletasks()
            self.assertIn("groups", window.metric_vars["duplicates"].get())
            self.assertIn("of library", window.metric_vars["savings"].get())
            self.assertIn("never marks or removes", window.status_var.get())
        finally:
            if window is not None and window.window.winfo_exists():
                window.window.destroy()
            root.destroy()

    def test_final_app_exposes_ctrl_h_and_keeps_cleanup_marks(self):
        root = tk.Tk()
        root.withdraw()
        app = PhotoCleanApp(root, self.settings_path)
        try:
            app.result = self._result()
            app.marked = {Path("library/b.png")}
            before = set(app.marked)
            self.assertTrue(root.bind("<Control-h>"))
            app.open_folder_health()
            root.update_idletasks()
            self.assertIsNotNone(app.folder_health_view)
            self.assertEqual(app.marked, before)

            first_window = app.folder_health_view
            app.open_folder_health()
            root.update_idletasks()
            self.assertIs(app.folder_health_view, first_window)
            self.assertEqual(app.marked, before)
        finally:
            root.after_cancel(app.poll_id)
            root.destroy()


if __name__ == "__main__":
    unittest.main()
