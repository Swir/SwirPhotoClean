import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from photoclean import core


def fixture(path: Path, accent: str = "#33aa55") -> None:
    image = Image.new("RGB", (640, 480), "#aaccdd")
    draw = ImageDraw.Draw(image)
    draw.rectangle((50, 60, 320, 360), fill="#aa5533")
    draw.ellipse((350, 100, 590, 390), fill=accent)
    draw.line((0, 450, 639, 20), fill="white", width=12)
    image.save(path)


class DuplicateAnalysisCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_exact_copies_decode_pixels_once(self):
        original = self.root / "a-original.png"
        fixture(original)
        shutil.copy2(original, self.root / "b-copy.png")
        shutil.copy2(original, self.root / "c-copy.png")

        with patch("photoclean.core._analysis_rgb", wraps=core._analysis_rgb) as analyze:
            result = core.scan([self.root], include_similar=False)

        self.assertFalse(result.cancelled)
        self.assertEqual(len(result.photos), 3)
        self.assertEqual(analyze.call_count, 1)
        self.assertEqual(len(result.groups), 1)
        self.assertEqual(result.groups[0].kind, "exact")
        self.assertEqual(len(result.groups[0].photos), 3)
        self.assertEqual(len({photo.digest for photo in result.photos}), 1)
        self.assertEqual(len({photo.dhash for photo in result.photos}), 1)
        self.assertEqual(len({photo.color for photo in result.photos}), 1)

    def test_different_full_hashes_are_still_analyzed_independently(self):
        fixture(self.root / "a.png", "#33aa55")
        fixture(self.root / "b.png", "#3355aa")

        with patch("photoclean.core._analysis_rgb", wraps=core._analysis_rgb) as analyze:
            result = core.scan([self.root], include_similar=False)

        self.assertEqual(len(result.photos), 2)
        self.assertEqual(analyze.call_count, 2)
        self.assertEqual(len({photo.digest for photo in result.photos}), 2)

    def test_duplicate_cache_does_not_change_similarity_expansion(self):
        original = self.root / "a-original.png"
        fixture(original)
        shutil.copy2(original, self.root / "b-copy.png")
        with Image.open(original) as image:
            image.resize((320, 240)).save(self.root / "c-resized.jpg", quality=88)

        result = core.scan([self.root])

        kinds = [group.kind for group in result.groups]
        self.assertEqual(kinds, ["exact", "similar"])
        self.assertEqual(len(result.groups[0].photos), 2)
        self.assertEqual(len(result.groups[1].photos), 3)


if __name__ == "__main__":
    unittest.main()
