import shutil
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from photoclean import i18n
from photoclean.core import ScanResult, scan
from photoclean.pro_gui import PhotoCleanApp


def fixture(path, size=(320, 240)):
    image = Image.new("RGB", size, "#aaccdd")
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 40, 160, 180), fill="#aa5533")
    draw.ellipse((180, 60, 300, 200), fill="#33aa55")
    draw.line((0, 230, 319, 10), fill="white", width=8)
    image.save(path)


class ProGuiTests(unittest.TestCase):
    def setUp(self):
        self.settings_dir = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.settings_dir.name) / "settings.json"

    def tearDown(self):
        self.settings_dir.cleanup()
        i18n.language = "pl"

    def test_exact_group_shows_conservative_health_and_no_auto_mark(self):
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
                root.update_idletasks()

                self.assertIn("Smart Keep", app.status.get())
                self.assertIn("identyczne", app.status.get())
                self.assertIn("Pewne duplikaty: 1", app.summary.get())
                self.assertFalse(app.marked)
                self.assertFalse(any(str(app.files.set(i, "name")).startswith("★ ") for i in app.files.get_children()))
        finally:
            root.after_cancel(app.poll_id)
            root.destroy()

    def test_similar_group_marks_only_visual_recommendation(self):
        root = tk.Tk()
        root.withdraw()
        app = PhotoCleanApp(root, self.settings_path)
        try:
            with tempfile.TemporaryDirectory() as folder:
                original = Path(folder) / "original.png"
                fixture(original)
                with Image.open(original) as image:
                    image.resize((160, 120)).save(Path(folder) / "small.jpg", quality=85)

                app.result = scan([folder])
                app.render_groups()
                similar_index = next(
                    index for index, group in enumerate(app.result.groups) if group.kind == "similar"
                )
                app.groups.selection_set(str(similar_index))
                app.choose_group()
                root.update_idletasks()

                names = [str(app.files.set(i, "name")) for i in app.files.get_children()]
                self.assertEqual(sum(name.startswith("★ ") for name in names), 1)
                self.assertIn("Smart Keep", app.status.get())
                self.assertFalse(app.marked)
        finally:
            root.after_cancel(app.poll_id)
            root.destroy()

    def test_insight_summary_localizes_without_losing_state(self):
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
                app.toggle_mark()
                self.assertEqual(len(app.marked), 1)

                app.language_var.set("English")
                app.change_language()
                root.update_idletasks()

                self.assertIn("Exact duplicates: 1", app.summary.get())
                self.assertIn("Smart Keep", app.status.get())
                self.assertIn("byte-identical", app.status.get())
                self.assertEqual(len(app.marked), 1)
                menu = root.nametowidget(root["menu"])
                self.assertEqual(menu.entrycget(menu.index("end"), "label"), "Session")
        finally:
            root.after_cancel(app.poll_id)
            root.destroy()

    def test_session_save_resume_restores_review_without_recycle_marks(self):
        root = tk.Tk()
        root.withdraw()
        app = PhotoCleanApp(root, self.settings_path)
        try:
            with tempfile.TemporaryDirectory() as folder:
                first = Path(folder) / "a.png"
                fixture(first)
                shutil.copy2(first, Path(folder) / "b.png")
                app.folders.insert("end", folder)
                app.result = scan([folder])
                app.render_groups()
                app.files.selection_set("0")
                app.toggle_mark()
                self.assertEqual(len(app.marked), 1)

                session_path = Path(folder) / "review.swirpc"
                with patch("photoclean.pro_gui.filedialog.asksaveasfilename", return_value=str(session_path)):
                    app.save_session_dialog()
                self.assertTrue(session_path.is_file())
                self.assertIn("Zapisano sesję", app.status.get())

                app.result = ScanResult()
                app.marked = {first}
                app.folders.delete(0, "end")
                app.render_groups()
                with patch("photoclean.pro_gui.filedialog.askopenfilename", return_value=str(session_path)):
                    app.load_session_dialog()
                root.update_idletasks()

                self.assertEqual(len(app.result.photos), 2)
                self.assertEqual(len(app.result.groups), 1)
                self.assertEqual(app.folders.get(0), folder)
                self.assertTrue(app.similarity.get())
                self.assertFalse(app.marked)
                self.assertEqual(str(app.trash_button["state"]), "disabled")
                self.assertIn("Wczytano sesję", app.status.get())
        finally:
            root.after_cancel(app.poll_id)
            root.destroy()

    def test_session_dialog_rejects_empty_results_before_file_picker(self):
        root = tk.Tk()
        root.withdraw()
        app = PhotoCleanApp(root, self.settings_path)
        try:
            with patch("photoclean.pro_gui.messagebox.showinfo") as info, patch(
                "photoclean.pro_gui.filedialog.asksaveasfilename"
            ) as picker:
                app.save_session_dialog()
            info.assert_called_once()
            picker.assert_not_called()
        finally:
            root.after_cancel(app.poll_id)
            root.destroy()


if __name__ == "__main__":
    unittest.main()
