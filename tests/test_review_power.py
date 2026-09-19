import shutil
import tempfile
import tkinter as tk
import unittest
from pathlib import Path

from PIL import Image

from photoclean import i18n
from photoclean.core import Photo, scan
from photoclean.review_power import filter_sort_photo_indices, move_selection
from photoclean.review_power_gui import PhotoCleanApp


def fake_photo(path, size, width, height):
    return Photo(
        path=Path(path),
        size=size,
        modified_ns=1,
        device=1,
        inode=1,
        digest=f"digest-{path}",
        width=width,
        height=height,
        dhash=0,
        color=b"\x00" * 192,
    )


class ReviewPowerHelperTests(unittest.TestCase):
    def test_filter_is_term_based_and_keeps_original_indices(self):
        photos = (
            fake_photo("C:/Album/Holiday One.jpg", 100, 800, 600),
            fake_photo("C:/Album/Holiday Two.png", 200, 1920, 1080),
            fake_photo("C:/Other/Portrait.jpg", 300, 1200, 1800),
        )
        self.assertEqual(
            filter_sort_photo_indices(photos, "holiday png", "original"),
            (1,),
        )
        self.assertEqual(
            filter_sort_photo_indices(photos, "1920x1080", "original"),
            (1,),
        )

    def test_marked_and_unmarked_scopes_are_presentation_only(self):
        photos = (
            fake_photo("C:/x/b.jpg", 200, 800, 600),
            fake_photo("C:/x/a.jpg", 100, 4000, 3000),
            fake_photo("C:/x/c.jpg", 500, 1200, 900),
        )
        marked = {photos[0].path, photos[2].path}
        self.assertEqual(
            filter_sort_photo_indices(
                photos,
                sort_mode="name",
                marked_paths=marked,
                filter_scope="marked",
            ),
            (0, 2),
        )
        self.assertEqual(
            filter_sort_photo_indices(
                photos,
                query="a.jpg",
                sort_mode="original",
                marked_paths=marked,
                filter_scope="unmarked",
            ),
            (1,),
        )
        self.assertEqual(marked, {photos[0].path, photos[2].path})
        with self.assertRaises(ValueError):
            filter_sort_photo_indices(photos, filter_scope="cleanup-now")

    def test_sort_modes_are_deterministic_and_non_mutating(self):
        photos = (
            fake_photo("C:/x/b.jpg", 200, 800, 600),
            fake_photo("C:/x/a.jpg", 100, 4000, 3000),
            fake_photo("C:/x/c.jpg", 500, 1200, 900),
        )
        snapshot = tuple(photos)
        self.assertEqual(filter_sort_photo_indices(photos, sort_mode="name"), (1, 0, 2))
        self.assertEqual(filter_sort_photo_indices(photos, sort_mode="size_desc"), (2, 0, 1))
        self.assertEqual(filter_sort_photo_indices(photos, sort_mode="resolution_desc"), (1, 2, 0))
        self.assertEqual(
            filter_sort_photo_indices(
                photos,
                sort_mode="recommended",
                recommended_path=photos[2].path,
            ),
            (2, 0, 1),
        )
        self.assertEqual(photos, snapshot)

    def test_move_selection_clamps_to_visible_items(self):
        children = ("1", "4", "7")
        self.assertEqual(move_selection(children, "4", 1), "7")
        self.assertEqual(move_selection(children, "4", -1), "1")
        self.assertEqual(move_selection(children, "7", 1), "7")
        self.assertEqual(move_selection(children, None, -1), "7")


class ReviewPowerGuiTests(unittest.TestCase):
    def setUp(self):
        self.settings_dir = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.settings_dir.name) / "settings.json"

    def tearDown(self):
        self.settings_dir.cleanup()
        i18n.language = "pl"

    def _app_with_exact_pair(self, root):
        app = PhotoCleanApp(root, self.settings_path)
        folder = tempfile.TemporaryDirectory()
        first = Path(folder.name) / "alpha.png"
        Image.new("RGB", (320, 240), "#336699").save(first)
        second = Path(folder.name) / "beta.png"
        shutil.copy2(first, second)
        app.result = scan([folder.name])
        app.render_groups()
        root.update_idletasks()
        return app, folder

    def test_filter_preserves_marks_and_original_tree_ids(self):
        root = tk.Tk()
        root.withdraw()
        app = PhotoCleanApp(root, self.settings_path)
        try:
            with tempfile.TemporaryDirectory() as folder:
                first = Path(folder) / "alpha.png"
                Image.new("RGB", (320, 240), "#336699").save(first)
                second = Path(folder) / "beta.png"
                shutil.copy2(first, second)
                app.result = scan([folder])
                app.render_groups()
                root.update_idletasks()

                self.assertEqual(tuple(app.files.get_children()), ("0", "1"))
                app.files.selection_set("0")
                app.toggle_mark()
                marked_before = set(app.marked)

                app.review_filter_var.set("beta")
                app._apply_review_view()
                self.assertEqual(tuple(app.files.get_children()), ("1",))
                self.assertEqual(app.marked, marked_before)
                self.assertIn("1/2", app.review_visible_var.get())

                app.review_filter_var.set("")
                app._apply_review_view()
                self.assertEqual(set(app.files.get_children()), {"0", "1"})
                self.assertEqual(app.marked, marked_before)
        finally:
            root.after_cancel(app.poll_id)
            root.destroy()

    def test_mark_scope_refreshes_immediately_when_mark_changes(self):
        root = tk.Tk()
        root.withdraw()
        app, folder = self._app_with_exact_pair(root)
        try:
            app.files.selection_set("0")
            app.toggle_mark()
            self.assertEqual(len(app.marked), 1)

            app.review_scope = "marked"
            app._apply_review_view()
            self.assertEqual(tuple(app.files.get_children()), ("0",))
            self.assertIn("1/2", app.review_visible_var.get())
            self.assertIn("1", app.review_visible_var.get())

            app.files.selection_set("0")
            app.toggle_mark()
            self.assertEqual(app.marked, set())
            self.assertEqual(tuple(app.files.get_children()), ())

            app.review_scope = "unmarked"
            app._apply_review_view()
            self.assertEqual(tuple(app.files.get_children()), ("0", "1"))
        finally:
            root.after_cancel(app.poll_id)
            root.destroy()
            folder.cleanup()

    def test_keyboard_power_bindings_exist_without_cleanup_shortcut(self):
        root = tk.Tk()
        root.withdraw()
        app = PhotoCleanApp(root, self.settings_path)
        try:
            self.assertTrue(root.bind("<Control-f>"))
            self.assertTrue(root.bind("<Control-Key-1>"))
            self.assertTrue(root.bind("<Control-Key-2>"))
            self.assertTrue(root.bind("<Control-Key-3>"))
            self.assertTrue(root.bind("<Control-Down>"))
            self.assertTrue(root.bind("<Alt-Down>"))
            self.assertTrue(root.bind("<F1>"))
            self.assertEqual(root.bind("<Control-Delete>"), "")
            self.assertTrue(app.files.bind("<Control-c>"))
        finally:
            root.after_cancel(app.poll_id)
            root.destroy()


if __name__ == "__main__":
    unittest.main()
