import tempfile
import tkinter as tk
import unittest
from pathlib import Path

from photoclean import i18n
from photoclean.core import Group, Photo, ScanResult
from photoclean.folder_health_app import PhotoCleanApp
from photoclean.folder_hotspots import duplicate_hotspots


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


class FolderHotspotTests(unittest.TestCase):
    def test_exact_duplicates_rank_folder_by_reclaimable_bytes(self):
        a = photo("library/a.png", size=1000, digest="same")
        b = photo("library/b.png", size=1000, digest="same")
        c = photo("library/c.png", size=1000, digest="same")
        result = ScanResult(photos=[a, b, c], groups=[Group("exact", (a, b, c))])

        hotspots = duplicate_hotspots(result)

        self.assertEqual(len(hotspots), 1)
        self.assertEqual(hotspots[0].folder, Path("library"))
        self.assertEqual(hotspots[0].exact_groups, 1)
        self.assertEqual(hotspots[0].duplicate_files, 2)
        self.assertEqual(hotspots[0].reclaimable_bytes, 2000)

    def test_repeated_exact_groups_cannot_inflate_hotspots(self):
        a = photo("library/a.png", digest="same")
        b = photo("library/b.png", digest="same")
        c = photo("library/c.png", digest="same")
        result = ScanResult(
            photos=[a, b, c],
            groups=[
                Group("exact", (a, b)),
                Group("exact", (c, b, a)),
            ],
        )

        hotspot = duplicate_hotspots(result)[0]
        self.assertEqual(hotspot.exact_groups, 1)
        self.assertEqual(hotspot.duplicate_files, 2)
        self.assertEqual(hotspot.reclaimable_bytes, 2000)

    def test_similar_groups_never_contribute(self):
        a = photo("photos/a.jpg", size=2_000_000)
        b = photo("photos/b.jpg", size=2_000_000)
        result = ScanResult(photos=[a, b], groups=[Group("similar", (a, b))])
        self.assertEqual(duplicate_hotspots(result), ())

    def test_member_outside_authoritative_scan_is_ignored(self):
        a = photo("library/a.png", digest="same")
        b = photo("library/b.png", digest="same")
        injected = photo("elsewhere/injected.png", size=99_000_000, digest="same")
        result = ScanResult(
            photos=[a, b],
            groups=[Group("exact", (a, b, injected))],
        )

        hotspots = duplicate_hotspots(result)
        self.assertEqual(len(hotspots), 1)
        self.assertEqual(hotspots[0].duplicate_files, 1)
        self.assertEqual(hotspots[0].reclaimable_bytes, 1000)
        self.assertNotEqual(hotspots[0].folder, Path("elsewhere"))

    def test_keeper_is_largest_then_path_deterministic_across_folders(self):
        smaller = photo("a/smaller.png", size=900, digest="same")
        keeper = photo("z/keeper.png", size=1200, digest="same")
        result = ScanResult(
            photos=[smaller, keeper],
            groups=[Group("exact", (smaller, keeper))],
        )
        hotspots = duplicate_hotspots(result)
        self.assertEqual(len(hotspots), 1)
        self.assertEqual(hotspots[0].folder, Path("a"))
        self.assertEqual(hotspots[0].reclaimable_bytes, 900)

        first = photo("a/first.png", size=1000, digest="tie")
        second = photo("b/second.png", size=1000, digest="tie")
        tied = ScanResult(
            photos=[second, first],
            groups=[Group("exact", (second, first))],
        )
        tied_hotspots = duplicate_hotspots(tied)
        self.assertEqual(tied_hotspots[0].folder, Path("b"))

    def test_limit_validation(self):
        self.assertEqual(duplicate_hotspots(ScanResult(), limit=0), ())
        with self.assertRaises(ValueError):
            duplicate_hotspots(ScanResult(), limit=-1)


class FolderHotspotGuiTests(unittest.TestCase):
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
        return ScanResult(
            photos=[a, b, c],
            groups=[Group("exact", (a, b))],
        )

    def test_final_app_opens_read_only_hotspot_drilldown_without_changing_marks(self):
        root = tk.Tk()
        root.withdraw()
        app = PhotoCleanApp(root, self.settings_path)
        try:
            app.result = self._result()
            app.marked = {Path("library/b.png")}
            before = set(app.marked)

            app.open_folder_health()
            root.update_idletasks()
            health_view = app.folder_health_view
            self.assertTrue(hasattr(health_view, "open_hotspots"))

            health_view.open_hotspots()
            root.update_idletasks()
            hotspot_view = health_view.hotspot_view
            self.assertIsNotNone(hotspot_view)
            self.assertEqual(len(hotspot_view.tree.get_children()), 1)
            self.assertEqual(hotspot_view.hotspots[0].reclaimable_bytes, 3000)
            self.assertEqual(app.marked, before)
        finally:
            if getattr(app, "folder_health_view", None) is not None:
                health = app.folder_health_view
                hotspot = getattr(health, "hotspot_view", None)
                if hotspot is not None:
                    try:
                        if hotspot.window.winfo_exists():
                            hotspot.window.destroy()
                    except tk.TclError:
                        pass
                try:
                    if health.window.winfo_exists():
                        health.window.destroy()
                except tk.TclError:
                    pass
            root.after_cancel(app.poll_id)
            root.destroy()


if __name__ == "__main__":
    unittest.main()
