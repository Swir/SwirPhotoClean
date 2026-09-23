import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
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


class PreRecycleBoundReadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.target = self.root / "target.png"
        fixture(self.target)
        self.photo = core.read_photo(self.target, threading.Event())

    def tearDown(self):
        self.tmp.cleanup()

    def test_stable_scanned_photo_revalidates(self):
        core.verify_photo(self.photo, threading.Event())

    def test_substituted_hash_handle_is_rejected_even_with_same_size_and_time(self):
        decoy = self.root / "decoy.png"
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
            with self.assertRaises(core.SafetyError):
                core.verify_photo(self.photo, threading.Event())

    def test_handle_metadata_change_after_hash_is_rejected(self):
        original_fstat = os.fstat
        calls = 0

        def changing_fstat(fd):
            nonlocal calls
            calls += 1
            info = original_fstat(fd)
            if calls != 2:
                return info
            return SimpleNamespace(
                st_mode=info.st_mode,
                st_size=info.st_size,
                st_mtime_ns=info.st_mtime_ns + 1,
                st_dev=info.st_dev,
                st_ino=info.st_ino,
                st_file_attributes=getattr(info, "st_file_attributes", 0),
            )

        with patch("photoclean.core.os.fstat", side_effect=changing_fstat):
            with self.assertRaises(core.SafetyError):
                core.verify_photo(self.photo, threading.Event())

        self.assertGreaterEqual(calls, 2)

    def test_reparse_ancestry_is_rechecked_after_bound_hash(self):
        original_linked = core.linked
        target_checks = 0

        def changed_ancestry(path):
            nonlocal target_checks
            if path == self.target:
                target_checks += 1
                if target_checks >= 2:
                    return True
            return original_linked(path)

        with patch("photoclean.core.linked", side_effect=changed_ancestry):
            with self.assertRaises(core.SafetyError):
                core.verify_photo(self.photo, threading.Event())

        self.assertGreaterEqual(target_checks, 2)

    def test_keeper_substitution_blocks_recycle_plan_before_callback(self):
        duplicate = self.root / "copy.png"
        shutil.copy2(self.target, duplicate)
        result = core.scan([self.root], include_similar=False)
        group = result.groups[0]
        target, keeper = group.photos[0], group.photos[1]

        decoy = self.root / "keeper-decoy.png"
        shutil.copy2(keeper.path, decoy)
        keeper_info = keeper.path.stat()
        decoy_info = decoy.stat()
        if not keeper_info.st_ino or not decoy_info.st_ino or keeper_info.st_ino == decoy_info.st_ino:
            self.skipTest("filesystem does not expose distinct stable file ids")

        original_open = Path.open
        recycle_calls = []

        def substituted_open(path, *args, **kwargs):
            if path == keeper.path and args and args[0] == "rb":
                return original_open(decoy, *args, **kwargs)
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", substituted_open):
            with self.assertRaises(core.SafetyError):
                core.recycle_selected(
                    result,
                    [target.path],
                    recycle=recycle_calls.append,
                )

        self.assertEqual(recycle_calls, [])


if __name__ == "__main__":
    unittest.main()
