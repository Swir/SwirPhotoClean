import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path

from PIL import ExifTags, Image

from photoclean.core import ScanResult, read_photo
from photoclean.library import analyze_library_metadata, read_library_metadata


class LibraryMetadataTests(unittest.TestCase):
    def _photo(
        self,
        folder,
        name,
        *,
        captured=None,
        make=None,
        model=None,
        nested=False,
        subsecond=None,
    ):
        path = Path(folder) / name
        exif = Image.Exif()
        if captured is not None:
            if nested:
                nested_exif = {36867: captured}
                if subsecond is not None:
                    nested_exif[37521] = subsecond
                exif[ExifTags.IFD.Exif] = nested_exif
            else:
                exif[36867] = captured
                if subsecond is not None:
                    exif[37521] = subsecond
        if make is not None:
            exif[271] = make
        if model is not None:
            exif[272] = model
        Image.new("RGB", (64, 48), (20, 60, 100)).save(path, format="JPEG", exif=exif)
        return read_photo(path, threading.Event())

    def test_timeline_and_device_groups_use_exif_only(self):
        with tempfile.TemporaryDirectory() as folder:
            first = self._photo(
                folder,
                "a.jpg",
                captured="2026:09:18 12:00:01",
                make="Apple",
                model="iPhone 15 Pro",
            )
            second = self._photo(
                folder,
                "b.jpg",
                captured="2026:09:18 12:00:02",
                make="Apple",
                model="Apple iPhone 15 Pro",
            )
            no_exif = self._photo(folder, "c.jpg")

            report = analyze_library_metadata(ScanResult(photos=[first, second, no_exif]))

            self.assertFalse(report.cancelled)
            self.assertEqual(report.analyzed_count, 3)
            self.assertEqual(report.captured_count, 2)
            self.assertEqual(report.device_count, 2)
            self.assertEqual(report.missing_capture_count, 1)
            self.assertEqual(report.missing_device_count, 1)
            self.assertEqual(len(report.timeline), 1)
            self.assertEqual(report.timeline[0].day.isoformat(), "2026-09-18")
            self.assertEqual(len(report.timeline[0].photos), 2)
            self.assertEqual(len(report.devices), 1)
            self.assertEqual(report.devices[0].label, "Apple iPhone 15 Pro")
            self.assertEqual(len(report.devices[0].photos), 2)

    def test_standard_nested_exif_ifd_populates_timeline_and_subseconds(self):
        with tempfile.TemporaryDirectory() as folder:
            photo = self._photo(
                folder,
                "nested.jpg",
                captured="2026:09:20 06:07:08",
                make="Google",
                model="Pixel 10 Pro",
                nested=True,
                subsecond="9876543",
            )
            item = read_library_metadata(photo)
            self.assertEqual(item.capture_source, "DateTimeOriginal")
            self.assertEqual(item.captured_at.microsecond, 987654)
            self.assertEqual(item.device_label, "Google Pixel 10 Pro")

            report = analyze_library_metadata([photo])
            self.assertEqual(report.captured_count, 1)
            self.assertEqual(report.timeline[0].day.isoformat(), "2026-09-20")
            self.assertEqual(report.devices[0].label, "Google Pixel 10 Pro")

    def test_no_filesystem_time_fallback_and_newest_days_first(self):
        with tempfile.TemporaryDirectory() as folder:
            older = self._photo(folder, "old.jpg", captured="2024:01:02 03:04:05", make="Canon", model="EOS R8")
            newer = self._photo(folder, "new.jpg", captured="2026:09:19 06:07:08", make="Canon", model="EOS R8")
            missing = self._photo(folder, "missing.jpg", make="Sony", model="A7 IV")

            report = analyze_library_metadata([older, newer, missing])

            self.assertEqual([bucket.day.isoformat() for bucket in report.timeline], ["2026-09-19", "2024-01-02"])
            self.assertEqual(report.captured_count, 2)
            missing_meta = next(item for item in report.metadata if item.photo.path.name == "missing.jpg")
            self.assertIsNone(missing_meta.captured_at)
            labels = [bucket.label for bucket in report.devices]
            self.assertEqual(labels, ["Canon EOS R8", "Sony A7 IV"])

    def test_unavailable_file_is_counted_without_mutating_scan(self):
        with tempfile.TemporaryDirectory() as folder:
            photo = self._photo(folder, "a.jpg", captured="2026:09:19 01:02:03")
            missing = replace(photo, path=Path(folder) / "gone.jpg")
            result = ScanResult(photos=[missing])

            report = analyze_library_metadata(result)

            self.assertEqual(report.analyzed_count, 1)
            self.assertEqual(report.unavailable_count, 1)
            self.assertEqual(report.captured_count, 0)
            self.assertEqual(result.photos[0].path.name, "gone.jpg")

    def test_cancellation_before_start_returns_partial_empty_report(self):
        event = threading.Event()
        event.set()
        report = analyze_library_metadata([], cancel_event=event)
        self.assertFalse(report.cancelled)  # nothing needed processing

        with tempfile.TemporaryDirectory() as folder:
            photo = self._photo(folder, "a.jpg", captured="2026:09:19 01:02:03")
            report = analyze_library_metadata([photo], cancel_event=event)
            self.assertTrue(report.cancelled)
            self.assertEqual(report.analyzed_count, 0)
            self.assertEqual(report.timeline, ())
            self.assertEqual(report.devices, ())

    def test_read_metadata_exposes_source_tag(self):
        with tempfile.TemporaryDirectory() as folder:
            photo = self._photo(folder, "a.jpg", captured="2026:09:19 11:12:13", make="Nikon", model="Z6 III")
            item = read_library_metadata(photo)
            self.assertEqual(item.capture_source, "DateTimeOriginal")
            self.assertEqual(item.device_label, "Nikon Z6 III")


if __name__ == "__main__":
    unittest.main()
