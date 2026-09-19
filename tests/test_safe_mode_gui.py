import shutil
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from photoclean.core import scan
from photoclean.safe_mode_gui import PhotoCleanApp


class SafeModeGuiTests(unittest.TestCase):
    def setUp(self):
        self.settings_dir = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.settings_dir.name) / "settings.json"

    def tearDown(self):
        self.settings_dir.cleanup()

    def _app_with_exact_group(self):
        root = tk.Tk()
        root.withdraw()
        app = PhotoCleanApp(root, self.settings_path)
        folder = tempfile.TemporaryDirectory()
        first = Path(folder.name) / "a.png"
        Image.new("RGB", (120, 80), "teal").save(first)
        shutil.copy2(first, Path(folder.name) / "b.png")
        app.result = scan([folder.name])
        app.render_groups()
        return root, app, folder

    def test_safe_mode_keeps_marks_but_disables_cleanup(self):
        root, app, folder = self._app_with_exact_group()
        try:
            app.files.selection_set("0")
            app.toggle_mark()
            self.assertEqual(len(app.marked), 1)
            self.assertEqual(str(app.trash_button["state"]), "normal")

            app.safe_mode.set(True)
            app._safe_mode_changed()

            self.assertEqual(len(app.marked), 1)
            self.assertEqual(str(app.mark_button["state"]), "normal")
            self.assertEqual(str(app.trash_button["state"]), "disabled")
            self.assertIn("Tryb bezpieczny WŁĄCZONY", app.status.get())
        finally:
            root.after_cancel(app.poll_id)
            root.destroy()
            folder.cleanup()

    def test_safe_mode_blocks_direct_confirm_recycle_call(self):
        root, app, folder = self._app_with_exact_group()
        try:
            app.files.selection_set("0")
            app.toggle_mark()
            app.safe_mode.set(True)
            app.update_summary()

            with patch("photoclean.safe_mode_gui.messagebox.showinfo") as info, patch(
                "photoclean.safe_mode_gui.DifferencePhotoCleanApp.confirm_recycle"
            ) as parent_recycle:
                app.confirm_recycle()

            info.assert_called_once()
            parent_recycle.assert_not_called()
            self.assertEqual(len(app.marked), 1)
        finally:
            root.after_cancel(app.poll_id)
            root.destroy()
            folder.cleanup()

    def test_turning_safe_mode_off_restores_normal_guarded_button_state(self):
        root, app, folder = self._app_with_exact_group()
        try:
            app.files.selection_set("0")
            app.toggle_mark()
            app.safe_mode.set(True)
            app.update_summary()
            self.assertEqual(str(app.trash_button["state"]), "disabled")

            app.safe_mode.set(False)
            app._safe_mode_changed()

            self.assertEqual(str(app.trash_button["state"]), "normal")
            self.assertEqual(len(app.marked), 1)
        finally:
            root.after_cancel(app.poll_id)
            root.destroy()
            folder.cleanup()


if __name__ == "__main__":
    unittest.main()
