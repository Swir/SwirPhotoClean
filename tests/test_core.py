import csv
import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageEnhance

from photoclean.core import SafetyError, export_csv, recycle_selected, scan


def fixture(path, size=(320, 240)):
    im = Image.new("RGB", size, "#aaccdd")
    draw = ImageDraw.Draw(im)
    draw.rectangle((30, 40, 160, 180), fill="#aa5533")
    draw.ellipse((180, 60, 300, 200), fill="#33aa55")
    draw.line((0, 230, 319, 10), fill="white", width=8)
    im.save(path)
    return im


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        fixture(self.root / "oryginał.png")
        shutil.copy2(self.root / "oryginał.png", self.root / "kopia.png")

    def tearDown(self):
        self.tmp.cleanup()

    def test_exact_and_unicode_overlap(self):
        result = scan([self.root, self.root])
        self.assertEqual(len(result.photos), 2)
        self.assertEqual(len(result.groups), 1)
        self.assertEqual(result.groups[0].kind, "exact")

    def test_resized_jpeg_similar(self):
        with Image.open(self.root / "oryginał.png") as im:
            im.resize((160, 120)).save(self.root / "small.jpg", quality=85)
        result = scan([self.root])
        self.assertEqual([g.kind for g in result.groups], ["exact", "similar"])
        self.assertEqual(len(result.groups[1].photos), 3)

    def test_flat_different_colors_not_similar(self):
        Image.new("RGB", (100, 100), "red").save(self.root / "red.png")
        Image.new("RGB", (100, 100), "blue").save(self.root / "blue.png")
        result = scan([self.root])
        self.assertEqual(len(result.groups), 1)

    def test_corrupt_and_multiframe_reported(self):
        (self.root / "bad.jpg").write_bytes(b"not an image")
        Image.new("RGB", (20, 20), "red").save(self.root / "anim.gif", save_all=True, append_images=[Image.new("RGB", (20, 20), "blue")])
        result = scan([self.root])
        self.assertEqual(len(result.warnings), 2)
        self.assertEqual(len(result.photos), 2)

    def test_cancel_has_no_actionable_results(self):
        cancel = threading.Event()
        cancel.set()
        result = scan([self.root], cancel=cancel)
        self.assertTrue(result.cancelled)
        self.assertEqual(result.groups, [])
        with self.assertRaises(SafetyError):
            recycle_selected(result, [], recycle=lambda _: None)

    def test_exact_only(self):
        with Image.open(self.root / "oryginał.png") as im:
            im.resize((160, 120)).save(self.root / "small.jpg")
        self.assertEqual([g.kind for g in scan([self.root], include_similar=False).groups], ["exact"])

    def test_hardlink_is_not_extra_copy(self):
        os.link(self.root / "oryginał.png", self.root / "hardlink.png")
        result = scan([self.root])
        self.assertEqual(len(result.photos), 2)
        self.assertEqual(len(result.warnings), 1)

    def test_changed_file_blocks_entire_plan(self):
        result = scan([self.root])
        target = result.groups[0].photos[0].path
        target.write_bytes(b"changed")
        calls = []
        with self.assertRaises(SafetyError):
            recycle_selected(result, [target], recycle=calls.append)
        self.assertEqual(calls, [])

    def test_changed_keeper_blocks_disposal(self):
        result = scan([self.root])
        target, keeper = result.groups[0].photos
        keeper.path.unlink()
        with self.assertRaises(SafetyError):
            recycle_selected(result, [target.path], recycle=lambda _: self.fail("must not recycle"))

    def test_all_copies_blocked(self):
        result = scan([self.root])
        with self.assertRaises(SafetyError):
            recycle_selected(result, [p.path for p in result.photos], recycle=lambda _: self.fail())

    def test_unrecognized_path_blocked(self):
        with self.assertRaises(SafetyError):
            recycle_selected(scan([self.root]), [self.root / "unknown"], recycle=lambda _: self.fail())

    def test_success_uses_only_injected_recycle(self):
        result = scan([self.root])
        target = result.photos[0].path
        calls = []
        completed, errors = recycle_selected(result, [target], recycle=calls.append)
        self.assertEqual(completed, [target])
        self.assertEqual(errors, [])
        self.assertEqual(calls, [str(target)])
        self.assertTrue(target.exists())

    def test_recycle_failure_does_not_unlink(self):
        result = scan([self.root])
        target = result.photos[0].path
        def fail(_):
            raise OSError("Kosz niedostępny")
        completed, errors = recycle_selected(result, [target], recycle=fail)
        self.assertEqual(completed, [])
        self.assertTrue(errors)
        self.assertTrue(target.exists())

    def test_hash_detects_change_with_restored_size_and_time(self):
        result = scan([self.root])
        photo = result.photos[0]
        data = bytearray(photo.path.read_bytes())
        data[-1] ^= 1
        photo.path.write_bytes(data)
        os.utime(photo.path, ns=(photo.modified_ns, photo.modified_ns))
        with self.assertRaises(SafetyError):
            recycle_selected(result, [photo.path], recycle=lambda _: self.fail())

    def test_csv_roundtrip(self):
        result = scan([self.root])
        target = self.root / "report.csv"
        export_csv(result, target)
        with target.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.reader(stream, delimiter=";"))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1][2], str(result.groups[0].photos[0].path))

    def test_empty_and_missing_folders(self):
        empty = self.root / "empty"
        empty.mkdir()
        self.assertEqual(scan([empty]).groups, [])
        self.assertEqual(len(scan([self.root / "missing"]).warnings), 1)


if __name__ == "__main__":
    unittest.main()
