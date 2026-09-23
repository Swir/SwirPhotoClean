import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from photoclean import core


def fixture(path: Path, accent: str = "#33aa55") -> None:
    image = Image.new("RGB", (320, 240), "#aaccdd")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 30, 160, 190), fill="#aa5533")
    draw.ellipse((175, 50, 300, 205), fill=accent)
    draw.line((0, 225, 319, 10), fill="white", width=7)
    image.save(path)


class ScannerBoundReadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.target = self.root / "target.png"
        fixture(self.target)

    def tearDown(self):
        self.tmp.cleanup()

    def test_pixel_decode_uses_the_bound_hash_stream(self):
        observed = []
        original_image_open = Image.open

        def tracking_open(file, *args, **kwargs):
            observed.append(file)
            return original_image_open(file, *args, **kwargs)

        with patch("photoclean.core.Image.open", side_effect=tracking_open):
            photo = core.read_photo(self.target, threading.Event())

        self.assertEqual(photo.path, self.target)
        self.assertEqual(len(observed), 1)
        self.assertFalse(isinstance(observed[0], (str, os.PathLike)))
        self.assertTrue(hasattr(observed[0], "fileno"))
        self.assertTrue(hasattr(observed[0], "read"))

    def test_substituted_open_handle_is_rejected_before_hash_or_decode(self):
        decoy = self.root / "decoy.png"
        fixture(decoy, accent="#3355aa")
        original_open = Path.open

        def substituted_open(path, *args, **kwargs):
            if path == self.target and args and args[0] == "rb":
                return original_open(decoy, *args, **kwargs)
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", substituted_open):
            with self.assertRaises(core.ScanIssueError) as raised:
                core.read_photo(self.target, threading.Event())

        self.assertEqual(raised.exception.category, "changed_during_scan")

    def test_same_metadata_different_object_is_rejected_when_file_ids_exist(self):
        decoy = self.root / "decoy-copy.png"
        shutil.copy2(self.target, decoy)
        target_info = self.target.stat()
        decoy_info = decoy.stat()
        if not target_info.st_ino or not decoy_info.st_ino or target_info.st_ino == decoy_info.st_ino:
            self.skipTest("filesystem does not expose distinct stable file ids")
        self.assertEqual(target_info.st_size, decoy_info.st_size)
        self.assertEqual(target_info.st_mtime_ns, decoy_info.st_mtime_ns)

        original_open = Path.open

        def substituted_open(path, *args, **kwargs):
            if path == self.target and args and args[0] == "rb":
                return original_open(decoy, *args, **kwargs)
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", substituted_open):
            with self.assertRaises(core.ScanIssueError) as raised:
                core.read_photo(self.target, threading.Event())

        self.assertEqual(raised.exception.category, "changed_during_scan")

    def test_scan_records_substituted_target_as_structured_change_issue(self):
        decoy = self.root / "zz-decoy.png"
        fixture(decoy, accent="#3355aa")
        original_open = Path.open

        def substituted_open(path, *args, **kwargs):
            if path == self.target and args and args[0] == "rb":
                return original_open(decoy, *args, **kwargs)
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", substituted_open):
            result = core.scan([self.root], include_similar=False)

        categories = [issue.category for issue in result.issues]
        self.assertIn("changed_during_scan", categories)
        self.assertNotIn(self.target, {photo.path for photo in result.photos})
        self.assertIn(decoy, {photo.path for photo in result.photos})


if __name__ == "__main__":
    unittest.main()
