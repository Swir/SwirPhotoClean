import hashlib
import shutil
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from photoclean import i18n
from photoclean.compare_insights_gui import InsightFullscreenCompare, PhotoCleanApp
from photoclean.core import scan


def jpeg_fixture(path, size=(640, 480), accent="#33aa55", captured="2026:09:19 21:30:00"):
    image = Image.new("RGB", size, "#aaccdd")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 60, min(size[0] - 20, 300), min(size[1] - 20, 330)), fill="#aa5533")
    draw.ellipse((size[0] // 2, 80, size[0] - 30, min(size[1] - 30, 380)), fill=accent)
    exif = Image.Exif()
    exif[36867] = captured
    exif[271] = "SWIR"
    exif[272] = "TestCam"
    image.save(path, quality=92, exif=exif)


def png_fixture(path):
    image = Image.new("RGB", (320, 240), "#2f6688")
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 30, 180, 190), fill="#d07040")
    image.save(path)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class CompareInsightsGuiTests(unittest.TestCase):
    def setUp(self):
        self.settings_dir = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.settings_dir.name) / "settings.json"

    def tearDown(self):
        self.settings_dir.cleanup()
        i18n.language = "pl"

    def test_fullscreen_shows_quality_exif_and_smart_keep_without_mutation(self):
        root = tk.Tk()
        root.withdraw()
        window = None
        try:
            with tempfile.TemporaryDirectory() as folder:
                first = Path(folder) / "large.jpg"
                second = Path(folder) / "small.jpg"
                jpeg_fixture(first, (640, 480), "#33aa55")
                jpeg_fixture(second, (420, 315), "#44bb66")
                photos = tuple(scan([folder], threshold=16).photos[:2])
                self.assertEqual(len(photos), 2)
                before = {photo.path: digest(photo.path) for photo in photos}

                window = InsightFullscreenCompare(root, photos, group_kind="similar")
                root.update_idletasks()
                details = [value.get() for value in window.detail_vars]
                joined = "\n".join(details)

                self.assertIn("Jakość", joined)
                self.assertIn("ostrość", joined)
                self.assertIn("ekspozycja", joined)
                self.assertIn("Aparat: SWIR TestCam", joined)
                self.assertIn("Wykonano: 2026-09-19 21:30:00", joined)
                self.assertEqual(
                    sum("Smart Keep: sugerowana kopia" in detail for detail in details),
                    1,
                )
                self.assertEqual(
                    {photo.path: digest(photo.path) for photo in photos},
                    before,
                )
        finally:
            if window is not None and window.window.winfo_exists():
                window.window.destroy()
            root.destroy()

    def test_exact_pair_is_described_as_byte_equivalent(self):
        root = tk.Tk()
        root.withdraw()
        window = None
        try:
            with tempfile.TemporaryDirectory() as folder:
                first = Path(folder) / "a.png"
                second = Path(folder) / "b.png"
                png_fixture(first)
                shutil.copy2(first, second)
                photos = tuple(scan([folder]).photos[:2])
                window = InsightFullscreenCompare(root, photos, group_kind="exact")
                root.update_idletasks()

                for detail in window.detail_vars:
                    self.assertIn("identyczne bajtowo", detail.get())
        finally:
            if window is not None and window.window.winfo_exists():
                window.window.destroy()
            root.destroy()

    def test_english_insight_metadata_is_localized(self):
        root = tk.Tk()
        root.withdraw()
        window = None
        i18n.language = "en"
        try:
            with tempfile.TemporaryDirectory() as folder:
                first = Path(folder) / "a.jpg"
                second = Path(folder) / "b.jpg"
                jpeg_fixture(first, accent="#228855")
                jpeg_fixture(second, accent="#338866")
                photos = tuple(scan([folder], threshold=16).photos[:2])
                window = InsightFullscreenCompare(root, photos, group_kind="similar")
                root.update_idletasks()
                joined = "\n".join(value.get() for value in window.detail_vars)

                self.assertIn("Quality", joined)
                self.assertIn("sharpness", joined)
                self.assertIn("Camera: SWIR TestCam", joined)
                self.assertIn("Captured: 2026-09-19 21:30:00", joined)
                self.assertIn("Smart Keep:", joined)
        finally:
            if window is not None and window.window.winfo_exists():
                window.window.destroy()
            root.destroy()

    def test_final_app_passes_active_group_kind_to_insight_compare(self):
        root = tk.Tk()
        root.withdraw()
        app = PhotoCleanApp(root, self.settings_path)
        try:
            with tempfile.TemporaryDirectory() as folder:
                first = Path(folder) / "a.png"
                png_fixture(first)
                shutil.copy2(first, Path(folder) / "b.png")
                app.result = scan([folder])
                app.render_groups()
                before = set(app.marked)

                with patch(
                    "photoclean.compare_insights_gui.InsightFullscreenCompare"
                ) as compare:
                    app.open_fullscreen_compare()

                compare.assert_called_once()
                self.assertEqual(len(compare.call_args.args[1]), 2)
                self.assertEqual(compare.call_args.kwargs["group_kind"], "exact")
                self.assertEqual(app.marked, before)
                self.assertIs(app.compare_view, compare.return_value)
        finally:
            root.after_cancel(app.poll_id)
            root.destroy()


if __name__ == "__main__":
    unittest.main()
