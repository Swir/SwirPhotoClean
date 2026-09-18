import tempfile
import unittest
from pathlib import Path

from PIL import Image

from photoclean.burst import burst_sequences, read_capture_time
from photoclean.core import Group, Photo, ScanResult


def make_jpeg(path: Path, timestamp: str | None):
    image = Image.new("RGB", (64, 48), (70, 110, 150))
    if timestamp is None:
        image.save(path, format="JPEG")
        return
    exif = Image.Exif()
    exif[36867] = timestamp
    image.save(path, format="JPEG", exif=exif)


def photo(path: Path, *, digest: str, width=640, height=480, size=1000):
    return Photo(
        path=path,
        size=size,
        modified_ns=1,
        device=1,
        inode=hash(str(path)) & 0xFFFF,
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

    def test_invalid_arguments_are_rejected(self):
        with self.assertRaises(ValueError):
            burst_sequences(ScanResult(), max_gap_seconds=-1)
        with self.assertRaises(ValueError):
            burst_sequences(ScanResult(), minimum_frames=1)


if __name__ == "__main__":
    unittest.main()
