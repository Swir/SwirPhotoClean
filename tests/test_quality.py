import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageFilter, ImageDraw

from photoclean.core import Group, Photo
from photoclean.quality import assess_photo, recommend_keeper_with_quality


def as_photo(path: Path, *, digest: str) -> Photo:
    info = path.stat()
    with Image.open(path) as image:
        width, height = image.size
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


def checkerboard(size=128, block=8):
    image = Image.new("L", (size, size), 255)
    draw = ImageDraw.Draw(image)
    for y in range(0, size, block):
        for x in range(0, size, block):
            if (x // block + y // block) % 2:
                draw.rectangle((x, y, x + block - 1, y + block - 1), fill=0)
    return image.convert("RGB")


class PhotoQualityTests(unittest.TestCase):
    def test_sharp_checkerboard_scores_above_blurred_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sharp_path = root / "sharp.png"
            blur_path = root / "blur.png"
            sharp = checkerboard()
            sharp.save(sharp_path)
            sharp.filter(ImageFilter.GaussianBlur(radius=4)).save(blur_path)

            sharp_score = assess_photo(as_photo(sharp_path, digest="a" * 64))
            blur_score = assess_photo(as_photo(blur_path, digest="b" * 64))

            self.assertTrue(sharp_score.available)
            self.assertTrue(blur_score.available)
            self.assertGreater(sharp_score.sharpness_score, blur_score.sharpness_score)
            self.assertGreater(sharp_score.overall_score, blur_score.overall_score)

    def test_mid_tone_exposure_scores_above_fully_clipped_black(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mid_path = root / "mid.png"
            black_path = root / "black.png"
            Image.new("RGB", (96, 96), (128, 128, 128)).save(mid_path)
            Image.new("RGB", (96, 96), (0, 0, 0)).save(black_path)

            mid = assess_photo(as_photo(mid_path, digest="c" * 64))
            black = assess_photo(as_photo(black_path, digest="d" * 64))

            self.assertGreater(mid.exposure_score, black.exposure_score)
            self.assertGreater(black.dark_clip_percent, 90.0)

    def test_quality_enhanced_keeper_prefers_sharper_equal_resolution_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sharp_path = root / "frame-a.png"
            blur_path = root / "frame-b.png"
            sharp = checkerboard()
            sharp.save(sharp_path)
            sharp.filter(ImageFilter.GaussianBlur(radius=5)).save(blur_path)
            sharp_photo = as_photo(sharp_path, digest="e" * 64)
            blur_photo = as_photo(blur_path, digest="f" * 64)

            recommendation = recommend_keeper_with_quality(
                Group("similar", (blur_photo, sharp_photo))
            )
            self.assertEqual(recommendation.photo.path, sharp_path)
            self.assertIsNotNone(recommendation.quality)
            self.assertEqual(recommendation.analyzed_count, 2)

    def test_exact_group_bypasses_subjective_quality_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "a.png"
            second = root / "b.png"
            Image.new("RGB", (64, 64), "gray").save(first)
            Image.new("RGB", (64, 64), "gray").save(second)
            a = as_photo(first, digest="same")
            b = as_photo(second, digest="same")

            def forbidden(_photo):
                raise AssertionError("exact copies must not require subjective quality analysis")

            recommendation = recommend_keeper_with_quality(
                Group("exact", (a, b)), analyzer=forbidden
            )
            self.assertTrue(recommendation.equivalent_exact)
            self.assertEqual(recommendation.analyzed_count, 0)

    def test_missing_file_returns_unavailable_instead_of_crashing(self):
        missing = Photo(
            path=Path("definitely-missing-photo.jpg"),
            size=1,
            modified_ns=1,
            device=1,
            inode=1,
            digest="0" * 64,
            width=100,
            height=100,
            dhash=0,
            color=b"\0" * 192,
        )
        result = assess_photo(missing)
        self.assertFalse(result.available)
        self.assertTrue(result.error)


if __name__ == "__main__":
    unittest.main()
