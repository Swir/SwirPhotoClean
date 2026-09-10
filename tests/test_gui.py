import shutil
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from photoclean.core import scan
from photoclean.gui import PhotoCleanApp


class GuiTests(unittest.TestCase):
    def test_layout_fits_minimum_window_at_150_percent(self):
        root = tk.Tk()
        root.withdraw()
        root.tk.call("tk", "scaling", 1.5)
        app = PhotoCleanApp(root)
        try:
            root.geometry("900x700")
            root.update_idletasks()
            self.assertLessEqual(root.winfo_reqwidth(), 900)
            self.assertLessEqual(root.winfo_reqheight(), 700)
        finally:
            root.after_cancel(app.poll_id)
            root.destroy()

    def test_preview_mark_export_state(self):
        root = tk.Tk()
        root.withdraw()
        app = PhotoCleanApp(root)
        try:
            with tempfile.TemporaryDirectory() as folder:
                p = Path(folder) / "a.png"
                Image.new("RGB", (100, 100), "teal").save(p)
                shutil.copy(p, Path(folder) / "b.png")
                app.result = scan([folder])
                app.render_groups()
                root.update()
                self.assertEqual(len(app.images), 2)
                self.assertNotIn("\n", app.preview_panels[0][1]["text"])
                self.assertFalse(app.marked)
                app.files.selection_set("0")
                app.copy_selected_paths()
                self.assertEqual(root.clipboard_get(), str(p))
                app.toggle_mark()
                self.assertEqual(len(app.marked), 1)
                self.assertEqual(str(app.trash_button["state"]), "normal")
                app.files.selection_set("1")
                with patch("photoclean.gui.messagebox.showwarning") as warn:
                    app.toggle_mark()
                    warn.assert_called_once()
                self.assertEqual(len(app.marked), 1)
                app.set_busy(True)
                app.clear_marks()
                self.assertEqual(len(app.marked), 1)
                self.assertEqual(str(app.trash_button["state"]), "disabled")
                app.set_busy(False)
                app.open_preview(0)
                windows = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
                self.assertEqual(len(windows), 1)
                windows[0].destroy()
                app.clear_marks()
                self.assertFalse(app.marked)
        finally:
            root.after_cancel(app.poll_id)
            root.destroy()


if __name__ == "__main__":
    unittest.main()
