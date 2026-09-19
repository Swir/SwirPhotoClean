import shutil
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from photoclean.core import scan
from photoclean.difference_gui import PhotoCleanApp


def fixture(path, size=(320, 240)):
    image = Image.new("RGB", size, "#aaccdd")
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 40, 160, 180), fill="#aa5533")
    draw.ellipse((180, 60, 300, 200), fill="#33aa55")
    image.save(path)


class DifferenceGuiTests(unittest.TestCase):
    def setUp(self):
        self.settings_dir = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.settings_dir.name) / "settings.json"

    def tearDown(self):
        self.settings_dir.cleanup()

    def test_selected_pair_routes_to_read_only_difference_window(self):
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

                with patch("photoclean.difference_gui.DifferenceWindow") as difference:
                    app.open_difference_view()

                difference.assert_called_once()
                self.assertEqual(len(difference.call_args.args[1]), 2)
                self.assertEqual(app.marked, before)
        finally:
            root.after_cancel(app.poll_id)
            root.destroy()

    def test_difference_view_requires_two_selected_photos(self):
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
                app.files.selection_set("0")
                app.files.selection_remove("1")

                with patch("photoclean.difference_gui.messagebox.showinfo") as info, patch(
                    "photoclean.difference_gui.DifferenceWindow"
                ) as difference:
                    app.open_difference_view()

                info.assert_called_once()
                difference.assert_not_called()
        finally:
            root.after_cancel(app.poll_id)
            root.destroy()


if __name__ == "__main__":
    unittest.main()
