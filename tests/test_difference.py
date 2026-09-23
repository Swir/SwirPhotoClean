import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from photoclean.core import read_photo
from photoclean.difference import _load_rgb, build_difference_preview


def photo(path: Path):
    return read_photo(path, threading.Event())


class DifferenceTests(unittest.TestCase):
    def test_identical_files_produce_zero_difference(self):
        with tempfile.TemporaryDirectory() as folder:
            left = Path(folder) / "left.png"
            right = Path(folder) / "right.png"
            Image.new("RGB", (120, 80), "#335577").save(left)
            shutil.copy2(left, right)

            preview = build_difference_preview(photo(left), photo(right))

            self.assertEqual(preview.report.changed_ratio, 0.0)
            self.assertEqual(preview.report.mean_delta, 0.0)
            self.assertIsNone(preview.report.changed_bbox)
            self.assertFalse(preview.report.resampled)
            self.assertEqual(preview.heatmap.size, (120, 80))

    def test_visible_edit_reports_changed_region(self):
        with tempfile.TemporaryDirectory() as folder:
            left = Path(folder) / "left.png"
            right = Path(folder) / "right.png"
            Image.new("RGB", (160, 120), "white").save(left)
            edited = Image.new("RGB", (160, 120), "white")
            draw = ImageDraw.Draw(edited)
            draw.rectangle((40, 30, 90, 75), fill="black")
            edited.save(right)

            preview = build_difference_preview(photo(left), photo(right), threshold=10)

            self.assertGreater(preview.report.changed_ratio, 0.05)
            self.assertGreater(preview.report.mean_delta, 1.0)
            self.assertIsNotNone(preview.report.changed_bbox)
            self.assertFalse(preview.report.resampled)

    def test_different_dimensions_are_bounded_and_flagged_as_resampled(self):
        with tempfile.TemporaryDirectory() as folder:
            left = Path(folder) / "left.png"
            right = Path(folder) / "right.png"
            Image.new("RGB", (2400, 1600), "#335577").save(left)
            Image.new("RGB", (1200, 800), "#335577").save(right)

            preview = build_difference_preview(photo(left), photo(right), max_side=600)

            self.assertTrue(preview.report.resampled)
            self.assertLessEqual(max(preview.report.analysis_size), 600)
            self.assertEqual(preview.heatmap.size, preview.report.analysis_size)
            self.assertEqual(preview.report.changed_ratio, 0.0)

    def test_large_sources_receive_bounded_target_before_decode(self):
        with tempfile.TemporaryDirectory() as folder:
            left = Path(folder) / "left.png"
            right = Path(folder) / "right.png"
            Image.new("RGB", (2400, 1600), "#335577").save(left)
            Image.new("RGB", (1200, 800), "#335577").save(right)
            left_photo = photo(left)
            right_photo = photo(right)

            with patch("photoclean.difference._load_rgb", wraps=_load_rgb) as loader:
                preview = build_difference_preview(
                    left_photo,
                    right_photo,
                    max_side=600,
                )

            self.assertEqual(loader.call_count, 2)
            self.assertEqual(loader.call_args_list[0].args[1], (600, 400))
            self.assertEqual(loader.call_args_list[1].args[1], (600, 400))
            self.assertEqual(preview.report.analysis_size, (600, 400))

    def test_transparent_source_is_matted_to_white_without_alpha_output(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "transparent.png"
            source = Image.new("RGBA", (80, 60), (255, 0, 0, 0))
            source.putpixel((10, 10), (255, 0, 0, 255))
            source.save(path)
            item = photo(path)

            loaded = _load_rgb(item, (80, 60))

            self.assertEqual(loaded.mode, "RGB")
            self.assertEqual(loaded.getpixel((0, 0)), (255, 255, 255))
            self.assertEqual(loaded.getpixel((10, 10)), (255, 0, 0))

    def test_same_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "same.png"
            Image.new("RGB", (80, 60), "white").save(path)
            item = photo(path)
            with self.assertRaises(ValueError):
                build_difference_preview(item, item)


if __name__ == "__main__":
    unittest.main()
