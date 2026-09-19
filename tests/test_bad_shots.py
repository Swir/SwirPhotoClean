import unittest
from pathlib import Path
from threading import Event

from photoclean.bad_shots import classify_quality, find_bad_shot_candidates
from photoclean.core import Photo
from photoclean.quality import PhotoQuality


def photo(name: str) -> Photo:
    return Photo(
        path=Path(name),
        size=1000,
        modified_ns=1,
        device=1,
        inode=1,
        digest=(name.encode("utf-8").hex() + "0" * 64)[:64],
        width=100,
        height=100,
        dhash=0,
        color=b"\0" * 192,
    )


def quality(item: Photo, *, overall=80.0, sharpness=80.0, exposure=80.0, available=True):
    return PhotoQuality(
        photo=item,
        available=available,
        overall_score=overall if available else 0.0,
        sharpness_score=sharpness if available else 0.0,
        exposure_score=exposure if available else 0.0,
        dark_clip_percent=0.0,
        light_clip_percent=0.0,
        mean_luma=128.0,
        notes=("balanced",) if available else ("unavailable",),
        error=None if available else "unavailable",
    )


class BadShotFinderTests(unittest.TestCase):
    def test_soft_photo_is_review_candidate_not_action(self):
        item = photo("soft.jpg")
        candidate = classify_quality(quality(item, overall=42, sharpness=8, exposure=90))
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.photo.path, item.path)
        self.assertIn("possible-blur", candidate.reasons)
        self.assertGreater(candidate.severity, 0)

    def test_balanced_photo_is_not_candidate(self):
        item = photo("balanced.jpg")
        self.assertIsNone(classify_quality(quality(item, overall=82, sharpness=75, exposure=91)))

    def test_finder_orders_and_limits_candidates(self):
        items = [photo("mild.jpg"), photo("severe.jpg"), photo("good.jpg")]
        scores = {
            "mild.jpg": quality(items[0], overall=30, sharpness=18, exposure=80),
            "severe.jpg": quality(items[1], overall=10, sharpness=2, exposure=25),
            "good.jpg": quality(items[2], overall=90, sharpness=90, exposure=90),
        }
        result = find_bad_shot_candidates(items, analyzer=lambda item: scores[item.path.name], max_results=1)
        self.assertFalse(result.cancelled)
        self.assertEqual(result.analyzed_count, 3)
        self.assertEqual(result.candidate_count, 2)
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].photo.path.name, "severe.jpg")

    def test_unavailable_evidence_is_counted_but_not_flagged(self):
        item = photo("missing.jpg")
        result = find_bad_shot_candidates([item], analyzer=lambda _: quality(item, available=False))
        self.assertEqual(result.analyzed_count, 1)
        self.assertEqual(result.unavailable_count, 1)
        self.assertEqual(result.candidate_count, 0)
        self.assertEqual(result.candidates, ())

    def test_cancellation_stops_without_inventing_results(self):
        items = [photo("first.jpg"), photo("second.jpg")]
        cancel = Event()

        def analyzer(item):
            cancel.set()
            return quality(item, overall=90, sharpness=90, exposure=90)

        result = find_bad_shot_candidates(items, analyzer=analyzer, cancel_event=cancel)
        self.assertTrue(result.cancelled)
        self.assertEqual(result.analyzed_count, 1)
        self.assertEqual(result.candidate_count, 0)

    def test_invalid_result_limit_is_rejected(self):
        with self.assertRaises(ValueError):
            find_bad_shot_candidates([], max_results=0)


if __name__ == "__main__":
    unittest.main()
