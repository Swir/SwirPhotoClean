import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from photoclean.core import scan, sha256
from photoclean.performance import (
    DEFAULT_PROFILE,
    PROFILES,
    load_performance_profile,
    performance_settings_path,
    save_performance_profile,
)


def fixture(path, size=(320, 240)):
    image = Image.new("RGB", size, "#aaccdd")
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 40, 160, 180), fill="#aa5533")
    draw.ellipse((180, 60, 300, 200), fill="#33aa55")
    draw.line((0, 230, 319, 10), fill="white", width=8)
    image.save(path)


def canonical(result):
    photos = tuple(
        (photo.path.name, photo.digest, photo.width, photo.height, photo.dhash, photo.color)
        for photo in result.photos
    )
    groups = tuple(
        (group.kind, tuple(photo.path.name for photo in group.photos))
        for group in result.groups
    )
    return photos, groups, tuple(result.warnings), result.cancelled


class PerformanceProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        fixture(self.root / "original.png")
        shutil.copy2(self.root / "original.png", self.root / "copy.png")
        with Image.open(self.root / "original.png") as image:
            image.resize((160, 120)).save(self.root / "small.jpg", quality=85)

    def tearDown(self):
        self.tmp.cleanup()

    def test_profiles_do_not_change_detection_results(self):
        results = [canonical(scan([self.root], performance_profile=key)) for key in PROFILES]
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[1], results[2])

    def test_profiles_have_bounded_hash_memory_and_expected_tuning(self):
        self.assertLess(PROFILES["eco"].hash_chunk_bytes, PROFILES["balanced"].hash_chunk_bytes)
        self.assertLess(PROFILES["balanced"].hash_chunk_bytes, PROFILES["fast"].hash_chunk_bytes)
        self.assertGreater(PROFILES["eco"].cooperative_yield_bytes, 0)
        self.assertEqual(PROFILES["fast"].cooperative_yield_bytes, 0)

    def test_eco_yields_during_large_hash_but_fast_does_not(self):
        target = self.root / "large.bin"
        target.write_bytes(b"x" * (2 * 1024 * 1024))
        cancel = threading.Event()
        with patch("photoclean.core.time.sleep") as sleep:
            eco_digest = sha256(target, cancel, "eco")
            self.assertGreaterEqual(sleep.call_count, 1)
        with patch("photoclean.core.time.sleep") as sleep:
            fast_digest = sha256(target, cancel, "fast")
            sleep.assert_not_called()
        self.assertEqual(eco_digest, fast_digest)

    def test_profile_setting_roundtrip_is_separate_from_language_file(self):
        settings = self.root / "settings.json"
        settings.write_text('{"language": "en"}', encoding="utf-8")
        self.assertEqual(load_performance_profile(settings), DEFAULT_PROFILE)
        save_performance_profile(settings, "fast")
        self.assertEqual(load_performance_profile(settings), "fast")
        self.assertEqual(settings.read_text(encoding="utf-8"), '{"language": "en"}')
        self.assertEqual(performance_settings_path(settings).name, "performance.json")

    def test_corrupt_or_unknown_profile_setting_falls_back_safely(self):
        path = performance_settings_path(self.root / "settings.json")
        path.write_text("not-json", encoding="utf-8")
        self.assertEqual(load_performance_profile(self.root / "settings.json"), DEFAULT_PROFILE)
        path.write_text('{"performance_profile": "turbo"}', encoding="utf-8")
        self.assertEqual(load_performance_profile(self.root / "settings.json"), DEFAULT_PROFILE)
        with self.assertRaises(ValueError):
            scan([self.root], performance_profile="turbo")


if __name__ == "__main__":
    unittest.main()
