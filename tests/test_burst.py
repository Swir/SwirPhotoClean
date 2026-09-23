import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import ExifTags, Image

from photoclean.burst import burst_sequences, read_capture_time
from photoclean.core import Group, Photo, ScanResult


def make_jpeg(
    path: Path,
    timestamp: str | None,
    *,
    make: str | None = None,
    model: str | None = None,
    nested: bool = False,
    subsecond: str | None = None,
):
    image = Image.new("RGB", (64, 48), (70, 110, 150))
    exif = Image.Exif()
    if timestamp is not None:
        if nested:
            nested_exif = {36867: timestamp}
            if subsecond is not None:
                nested_exif[37521] = subsecond
            exif[ExifTags.IFD.Exif] = nested_exif
        else:
            exif[36867] = timestamp
            if subsecond is not None:
                exif[37521] = subsecond
    if make is not None:
        exif[271] = make
    if model is not None:
        exif[272] = model
    image.save(path, format="JPEG", exif=exif)


def photo(path: Path, *, digest: str, width=640, height=480):
    info = path.stat()
    return Photo(
        path=path,
        size=info.st_size,
        modified_ns=info.st_mtime_ns,
        device=info.st_dev,
        inode=info.st_ino,
        digest=digest,
        width=width,
        height=height,
        dhash=0,
        color=b"\0" * 192,
    )


class BurstMetadataTests(unittest.TestCase):
    def test_reads_datetime_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frame.jpg"
            make_jpeg(path, "2026:09:19 01:02:03")
            capture = read_capture_time(path)
            self.assertIsNotNone(capture)
            self.assertEqual(capture.source, "DateTimeOriginal")
            self.assertEqual(capture.value.year, 2026)
            self.assertEqual(capture.value.second, 3)

    def test_reads_standard_nested_datetime_original_with_subseconds(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "camera.jpg"
            make_jpeg(
                path,
                "2026:09:19 01:02:03",
                make="Canon",
                model="EOS R8",
                nested=True,
                subsecond="1234567",
            )
            capture = read_capture_time(path)
            self.assertIsNotNone(capture)
            self.assertEqual(capture.source, "DateTimeOriginal")
            self.assertEqual(capture.value.microsecond, 123456)
            self.assertEqual(capture.camera_label, "Canon EOS R8")

    def test_missing_exif_is_not_guessed_from_file_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frame.jpg"
            make_jpeg(path, None)
            self.assertIsNone(read_capture_time(path))


class BurstSequenceTests(unittest.TestCase):
    def test_detects_close_exif_frames_and_recommends_best(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = [root / f"frame-{index}.jpg" for index in range(3)]
            for index, path in enumerate(paths):
                make_jpeg(path, f"2026:09:19 01:00:0{index}")
            photos = (
                photo(paths[0], digest="a" * 64, width=800, height=600),
                photo(paths[1], digest="b" * 64, width=1920, height=1080),
                photo(paths[2], digest="c" * 64, width=1280, height=720),
            )
            result = ScanResult(photos=list(photos), groups=[Group("similar", photos)])
            sequences = burst_sequences(result)
            self.assertEqual(len(sequences), 1)
            self.assertEqual(len(sequences[0].photos), 3)
            self.assertEqual(sequences[0].group_index, 0)
            self.assertEqual(sequences[0].span_seconds, 2.0)
            self.assertEqual(sequences[0].keeper.photo, photos[1])

    def test_splits_sequences_when_capture_gap_is_too_large(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stamps = ["01:00:00", "01:00:02", "01:00:10", "01:00:12"]
            photos = []
            for index, clock in enumerate(stamps):
                path = root / f"frame-{index}.jpg"
                make_jpeg(path, f"2026:09:19 {clock}")
                photos.append(photo(path, digest=f"{index + 1:064x}"))
            group = Group("similar", tuple(photos))
            sequences = burst_sequences(ScanResult(photos=photos, groups=[group]), max_gap_seconds=3)
            self.assertEqual([len(item.photos) for item in sequences], [2, 2])

    def test_splits_close_frames_when_known_camera_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            photos = []
            cameras = [
                ("Canon", "EOS R8"),
                ("Canon", "EOS R8"),
                ("Sony", "A7 IV"),
                ("Sony", "A7 IV"),
            ]
            for index, (make, model) in enumerate(cameras):
                path = root / f"frame-{index}.jpg"
                make_jpeg(
                    path,
                    f"2026:09:19 01:00:0{index}",
                    make=make,
                    model=model,
                    nested=True,
                )
                photos.append(photo(path, digest=f"{index + 1:064x}"))
            group = Group("similar", tuple(photos))
            sequences = burst_sequences(ScanResult(photos=photos, groups=[group]), max_gap_seconds=3)
            self.assertEqual([len(item.photos) for item in sequences], [2, 2])
            self.assertEqual([item.camera_label for item in sequences], ["Canon EOS R8", "Sony A7 IV"])

    def test_exact_groups_are_not_burst_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "a.jpg"
            second = root / "b.jpg"
            make_jpeg(first, "2026:09:19 01:00:00")
            make_jpeg(second, "2026:09:19 01:00:01")
            photos = (
                photo(first, digest="a" * 64),
                photo(second, digest="a" * 64),
            )
            result = ScanResult(photos=list(photos), groups=[Group("exact", photos)])
            self.assertEqual(burst_sequences(result), ())

    def test_byte_identical_copies_are_collapsed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = [root / name for name in ("a.jpg", "a-copy.jpg", "b.jpg")]
            for index, path in enumerate(paths):
                make_jpeg(path, f"2026:09:19 01:00:0{index}")
            photos = (
                photo(paths[0], digest="a" * 64),
                photo(paths[1], digest="a" * 64),
                photo(paths[2], digest="b" * 64),
            )
            result = ScanResult(photos=list(photos), groups=[Group("similar", photos)])
            sequences = burst_sequences(result)
            self.assertEqual(len(sequences), 1)
            self.assertEqual(len(sequences[0].photos), 2)
            self.assertEqual(len({item.digest for item in sequences[0].photos}), 2)

    def test_stale_replaced_frame_is_excluded_from_burst_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "a.jpg"
            second = root / "b.jpg"
            make_jpeg(first, "2026:09:19 01:00:00")
            make_jpeg(second, "2026:09:19 01:00:01")
            photos = (
                photo(first, digest="a" * 64),
                photo(second, digest="b" * 64),
            )
            result = ScanResult(photos=list(photos), groups=[Group("similar", photos)])

            # The saved Photo describes the pre-change object. Appending bytes keeps
            # the image parseable while guaranteeing a different filesystem size.
            second.write_bytes(second.read_bytes() + b"stale-after-scan")

            self.assertEqual(burst_sequences(result), ())

    def test_reparse_ancestor_is_excluded_from_burst_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "a.jpg"
            second = root / "b.jpg"
            make_jpeg(first, "2026:09:19 01:00:00")
            make_jpeg(second, "2026:09:19 01:00:01")
            photos = (
                photo(first, digest="a" * 64),
                photo(second, digest="b" * 64),
            )
            result = ScanResult(photos=list(photos), groups=[Group("similar", photos)])

            real_linked = __import__("photoclean.burst", fromlist=["linked"]).linked

            def linked_with_unsafe_root(path):
                return path == root or real_linked(path)

            with patch("photoclean.burst.linked", side_effect=linked_with_unsafe_root):
                self.assertEqual(burst_sequences(result), ())

    def test_invalid_arguments_are_rejected(self):
        with self.assertRaises(ValueError):
            burst_sequences(ScanResult(), max_gap_seconds=-1)
        with self.assertRaises(ValueError):
            burst_sequences(ScanResult(), minimum_frames=1)


if __name__ == "__main__":
    unittest.main()
