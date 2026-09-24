import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFilter, ImageOps

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

    def test_cached_quality_is_not_reused_after_file_disappears(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cached.png"
            checkerboard().save(path)
            photo = as_photo(path, digest="1" * 64)

            first = assess_photo(photo)
            self.assertTrue(first.available)
            path.unlink()

            second = assess_photo(photo)
            self.assertFalse(second.available)
            self.assertTrue(second.error)

    def test_transient_read_failure_does_not_poison_quality_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "flaky.png"
            checkerboard().save(path)
            photo = as_photo(path, digest="4" * 64)
            real_image_open = Image.open
            attempts = 0

            def flaky_open(*args, **kwargs):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise OSError("temporary sharing violation")
                return real_image_open(*args, **kwargs)

            with patch("photoclean.quality.Image.open", side_effect=flaky_open):
                first = assess_photo(photo)
                second = assess_photo(photo)

            self.assertFalse(first.available)
            self.assertIn("temporary sharing violation", first.error)
            self.assertTrue(second.available)
            self.assertEqual(attempts, 2)

    def test_changed_scan_identity_is_rejected_before_quality_recommendation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "changed.png"
            checkerboard().save(path)
            photo = as_photo(path, digest="2" * 64)
            self.assertTrue(assess_photo(photo).available)

            Image.new("RGB", (32, 32), "black").save(path)
            changed = assess_photo(photo)

            self.assertFalse(changed.available)
            self.assertIn("changed", changed.error)

    def test_reparse_ancestor_is_rejected_before_quality_decode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "frame.png"
            checkerboard().save(path)
            photo = as_photo(path, digest="5" * 64)
            from photoclean import quality as quality_module

            real_linked = quality_module.linked

            def linked_with_unsafe_root(candidate):
                return Path(candidate) == root or real_linked(Path(candidate))

            with patch(
                "photoclean.quality.linked",
                side_effect=linked_with_unsafe_root,
            ), patch(
                "photoclean.quality.Image.open",
                side_effect=AssertionError("unsafe ancestry must be rejected before decode"),
            ):
                result = assess_photo(photo)

            self.assertFalse(result.available)
            self.assertIn("unsafe", result.error.lower())

    def test_redirected_open_handle_is_rejected_before_quality_decode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "frame.png"
            replacement = root / "replacement.png"
            checkerboard().save(path)
            Image.new("RGB", (37, 29), "navy").save(replacement)
            photo = as_photo(path, digest="6" * 64)

            path_type = type(path)
            real_open = path_type.open

            def redirected_open(candidate, *args, **kwargs):
                mode = args[0] if args else kwargs.get("mode", "r")
                if candidate == path and mode == "rb":
                    return real_open(replacement, *args, **kwargs)
                return real_open(candidate, *args, **kwargs)

            with patch.object(path_type, "open", new=redirected_open), patch(
                "photoclean.quality.Image.open",
                side_effect=AssertionError("redirected handle must be rejected before decode"),
            ):
                result = assess_photo(photo)

            self.assertFalse(result.available)
            self.assertIn("redirected", result.error.lower())

    def test_large_quality_source_is_bounded_before_orientation_and_grayscale(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "large.png"
            Image.new("RGB", (1600, 1200), (90, 130, 170)).save(path)
            photo = as_photo(path, digest="3" * 64)
            observed_sizes = []
            real_exif_transpose = ImageOps.exif_transpose

            def observe(image):
                observed_sizes.append(image.size)
                return real_exif_transpose(image)

            with patch("photoclean.quality.ImageOps.exif_transpose", side_effect=observe):
                result = assess_photo(photo, max_side=128)

            self.assertTrue(result.available)
            self.assertTrue(observed_sizes)
            self.assertLessEqual(max(observed_sizes[0]), 128)


if __name__ == "__main__":
    unittest.main()
