import hashlib
import shutil
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from photoclean import i18n
from photoclean.core import scan
from photoclean.fullscreen_plus_gui import IntegratedFullscreenCompare, PhotoCleanApp


def fixture(path, size=(320, 240), accent="#33aa55"):
    image = Image.new("RGB", size, "#aaccdd")
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 40, 160, 180), fill="#aa5533")
    draw.ellipse((180, 60, 300, 200), fill=accent)
    draw.line((0, 230, 319, 10), fill="white", width=8)
    image.save(path)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class FullscreenPlusGuiTests(unittest.TestCase):
    def setUp(self):
        self.settings_dir = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.settings_dir.name) / "settings.json"

    def tearDown(self):
        self.settings_dir.cleanup()
        i18n.language = "pl"

    def test_final_app_routes_fullscreen_to_integrated_compare_without_marks(self):
        root = tk.Tk()
        root.withdraw()
        app = PhotoCleanApp(root, self.settings_path)
        try:
            with tempfile.TemporaryDirectory() as folder:
                first = Path(folder) / "a.png"
                fixture(first)
                shutil.copy2(first, Path(folder) / "b.png")
                app.result = scan([folder])
                app.render_groups()
                before = set(app.marked)

                with patch(
                    "photoclean.fullscreen_plus_gui.IntegratedFullscreenCompare"
                ) as compare:
                    app.open_fullscreen_compare()

                compare.assert_called_once()
                self.assertEqual(len(compare.call_args.args[1]), 2)
                self.assertEqual(app.marked, before)
                self.assertIs(app.compare_view, compare.return_value)
        finally:
            root.after_cancel(app.poll_id)
            root.destroy()

    def test_difference_toggle_is_lazy_reversible_and_read_only(self):
        root = tk.Tk()
        root.withdraw()
        window = None
        try:
            with tempfile.TemporaryDirectory() as folder:
                first = Path(folder) / "a.png"
                second = Path(folder) / "b.png"
                fixture(first)
                fixture(second, accent="#ff0055")
                result = scan([folder], threshold=16)
                self.assertGreaterEqual(len(result.photos), 2)
                photos = tuple(result.photos[:2])
                before = {photo.path: digest(photo.path) for photo in photos}

                window = IntegratedFullscreenCompare(root, photos)
                root.update_idletasks()
                self.assertIsNone(window.difference_preview)
                self.assertFalse(window.difference_visible)

                window.toggle_difference()
                root.update_idletasks()
                self.assertTrue(window.difference_visible)
                self.assertIsNotNone(window.difference_preview)
                self.assertGreater(window.difference_preview.report.changed_ratio, 0.0)
                self.assertIn("Różnice", window.detail_vars[1].get())

                cached = window.difference_preview
                window.toggle_difference()
                root.update_idletasks()
                self.assertFalse(window.difference_visible)
                self.assertIs(window.difference_preview, cached)
                self.assertEqual(
                    {photo.path: digest(photo.path) for photo in photos},
                    before,
                )
        finally:
            if window is not None and window.window.winfo_exists():
                window.window.destroy()
            root.destroy()

    def test_english_difference_metadata_is_localized(self):
        root = tk.Tk()
        root.withdraw()
        window = None
        i18n.language = "en"
        try:
            with tempfile.TemporaryDirectory() as folder:
                first = Path(folder) / "a.png"
                second = Path(folder) / "b.png"
                fixture(first)
                fixture(second, accent="#ff0055")
                photos = tuple(scan([folder], threshold=16).photos[:2])
                window = IntegratedFullscreenCompare(root, photos)
                window.toggle_difference()
                root.update_idletasks()
                self.assertIn("Differences", window.detail_vars[1].get())
                self.assertIn("preview only", window.detail_vars[1].get())
                self.assertEqual(window.mode_button.cget("text"), "Photo")
        finally:
            if window is not None and window.window.winfo_exists():
                window.window.destroy()
            root.destroy()


if __name__ == "__main__":
    unittest.main()
