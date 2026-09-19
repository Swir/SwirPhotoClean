import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path

from PIL import Image

from photoclean.classification import analyze_media_types, inspect_media_type
from photoclean.core import ScanResult, read_photo


class MediaClassificationTests(unittest.TestCase):
    def _photo(
        self,
        folder,
        name,
        *,
        size=(800, 600),
        image_format="PNG",
        mode="RGB",
        make=None,
        model=None,
        captured=None,
    ):
        path = Path(folder) / name
        exif = Image.Exif()
        if make is not None:
            exif[271] = make
        if model is not None:
            exif[272] = model
        if captured is not None:
            exif[36867] = captured
        image = Image.new(mode, size, (20, 60, 100, 180) if mode == "RGBA" else (20, 60, 100))
        save_kwargs = {"format": image_format}
        if len(exif):
            save_kwargs["exif"] = exif
        image.save(path, **save_kwargs)
        return read_photo(path, threading.Event())

    def test_camera_exif_wins_over_screen_sized_png(self):
        with tempfile.TemporaryDirectory() as folder:
            photo = self._photo(
                folder,
                "camera.png",
                size=(1920, 1080),
                make="Sony",
                model="A7 IV",
                captured="2026:09:19 08:00:00",
            )
            item = inspect_media_type(photo)
            self.assertEqual(item.category, "camera_photo")
            self.assertEqual(item.confidence, "high")
            self.assertIn("camera_metadata", item.reasons)
            self.assertIn("capture_timestamp", item.reasons)

    def test_common_screen_png_is_conservative_screenshot_candidate(self):
        with tempfile.TemporaryDirectory() as folder:
            photo = self._photo(folder, "capture.png", size=(1920, 1080))
            item = inspect_media_type(photo)
            self.assertEqual(item.category, "screenshot_candidate")
            self.assertEqual(item.confidence, "medium")
            self.assertIn("common_screen_dimensions", item.reasons)
            self.assertIn("screen_friendly_format", item.reasons)
            self.assertFalse(item.has_camera_metadata)

    def test_common_screen_jpeg_is_only_low_confidence_candidate(self):
        with tempfile.TemporaryDirectory() as folder:
            photo = self._photo(folder, "capture.jpg", size=(1920, 1080), image_format="JPEG")
            item = inspect_media_type(photo)
            self.assertEqual(item.category, "screenshot_candidate")
            self.assertEqual(item.confidence, "low")
            self.assertEqual(item.reasons, ("common_screen_dimensions", "no_camera_metadata"))

    def test_transparent_png_is_graphic_candidate(self):
        with tempfile.TemporaryDirectory() as folder:
            photo = self._photo(folder, "overlay.png", size=(777, 555), mode="RGBA")
            item = inspect_media_type(photo)
            self.assertEqual(item.category, "graphic_candidate")
            self.assertEqual(item.confidence, "high")
            self.assertTrue(item.has_alpha)
            self.assertIn("alpha_channel", item.reasons)

    def test_plain_jpeg_without_evidence_stays_unknown(self):
        with tempfile.TemporaryDirectory() as folder:
            photo = self._photo(folder, "export.jpg", size=(801, 603), image_format="JPEG")
            item = inspect_media_type(photo)
            self.assertEqual(item.category, "unknown")
            self.assertEqual(item.confidence, "low")
            self.assertEqual(item.reasons, ("insufficient_evidence",))

    def test_report_groups_categories_and_keeps_scan_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            camera = self._photo(folder, "camera.jpg", image_format="JPEG", make="Canon", model="EOS R8")
            screenshot = self._photo(folder, "screen.png", size=(1080, 2400))
            graphic = self._photo(folder, "graphic.png", size=(700, 500), mode="RGBA")
            unknown = self._photo(folder, "unknown.jpg", size=(803, 607), image_format="JPEG")
            result = ScanResult(photos=[camera, screenshot, graphic, unknown])

            report = analyze_media_types(result)

            self.assertEqual(report.total_count, 4)
            self.assertEqual(report.count("camera_photo"), 1)
            self.assertEqual(report.count("screenshot_candidate"), 1)
            self.assertEqual(report.count("graphic_candidate"), 1)
            self.assertEqual(report.count("unknown"), 1)
            self.assertEqual(
                [bucket.category for bucket in report.buckets],
                ["camera_photo", "screenshot_candidate", "graphic_candidate", "unknown"],
            )
            self.assertEqual([photo.path.name for photo in result.photos], ["camera.jpg", "screen.png", "graphic.png", "unknown.jpg"])
            self.assertEqual(result.groups, [])

    def test_unavailable_file_is_unknown_and_counted(self):
        with tempfile.TemporaryDirectory() as folder:
            original = self._photo(folder, "a.png")
            missing = replace(original, path=Path(folder) / "gone.png")
            report = analyze_media_types([missing])
            self.assertEqual(report.unavailable_count, 1)
            self.assertEqual(report.count("unknown"), 1)
            self.assertEqual(report.items[0].reasons, ("unavailable",))

    def test_cancellation_before_processing_returns_empty_partial_report(self):
        with tempfile.TemporaryDirectory() as folder:
            photo = self._photo(folder, "a.png")
            event = threading.Event()
            event.set()
            report = analyze_media_types([photo], cancel_event=event)
            self.assertTrue(report.cancelled)
            self.assertEqual(report.analyzed_count, 0)
            self.assertEqual(report.buckets, ())


if __name__ == "__main__":
    unittest.main()
