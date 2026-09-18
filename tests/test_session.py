import json
import tempfile
import unittest
from pathlib import Path

from photoclean.core import Group, Photo, ScanResult
from photoclean.session import SessionError, SessionSnapshot, load_session, save_session, snapshot_from_dict, snapshot_to_dict


def photo(path, *, digest="a" * 64, size=1000, inode=1):
    return Photo(
        path=Path(path),
        size=size,
        modified_ns=123,
        device=1,
        inode=inode,
        digest=digest,
        width=320,
        height=240,
        dhash=42,
        color=bytes(range(192)),
    )


class SessionTests(unittest.TestCase):
    def test_roundtrip_preserves_scan_and_settings_without_marks(self):
        a = photo("C:/photos/a.png", inode=1)
        b = photo("C:/photos/b.png", inode=2)
        result = ScanResult(
            photos=[a, b],
            groups=[Group("exact", (a, b))],
            warnings=["fixture warning"],
        )
        snapshot = SessionSnapshot(
            roots=(Path("C:/photos"),),
            threshold=6,
            include_similar=True,
            result=result,
        )
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "review.swirphoto"
            save_session(snapshot, target)
            loaded = load_session(target)

        self.assertEqual(loaded.roots, snapshot.roots)
        self.assertEqual(loaded.threshold, 6)
        self.assertTrue(loaded.include_similar)
        self.assertFalse(loaded.result.cancelled)
        self.assertEqual(loaded.result.photos, result.photos)
        self.assertEqual(loaded.result.groups, result.groups)
        self.assertEqual(loaded.result.warnings, ["fixture warning"])
        serialized = snapshot_to_dict(snapshot)
        self.assertNotIn("marked", serialized)
        self.assertNotIn("selected", serialized)

    def test_cancelled_scan_cannot_be_saved(self):
        snapshot = SessionSnapshot((), 6, True, ScanResult(cancelled=True))
        with self.assertRaises(SessionError):
            snapshot_to_dict(snapshot)

    def test_exact_group_digest_mismatch_is_rejected(self):
        a = photo("a.png", digest="a" * 64, inode=1)
        b = photo("b.png", digest="b" * 64, inode=2)
        raw = snapshot_to_dict(SessionSnapshot((), 6, True, ScanResult(photos=[a, b])))
        raw["groups"] = [{"kind": "exact", "members": [0, 1]}]
        with self.assertRaises(SessionError):
            snapshot_from_dict(raw)

    def test_out_of_range_group_reference_is_rejected(self):
        a = photo("a.png")
        raw = snapshot_to_dict(SessionSnapshot((), 6, True, ScanResult(photos=[a])))
        raw["groups"] = [{"kind": "similar", "members": [0, 9]}]
        with self.assertRaises(SessionError):
            snapshot_from_dict(raw)

    def test_duplicate_paths_are_rejected(self):
        a = photo("same.png", inode=1)
        b = photo("same.png", inode=2)
        with self.assertRaises(SessionError):
            snapshot_to_dict(SessionSnapshot((), 6, True, ScanResult(photos=[a, b])))

    def test_invalid_hash_color_and_pixel_limit_are_rejected(self):
        base = snapshot_to_dict(SessionSnapshot((), 6, True, ScanResult(photos=[photo("a.png")])))
        for field, value in (
            ("digest", "not-a-digest"),
            ("color", "00"),
            ("width", 100_000),
        ):
            raw = json.loads(json.dumps(base))
            raw["photos"][0][field] = value
            with self.subTest(field=field):
                with self.assertRaises(SessionError):
                    snapshot_from_dict(raw)

    def test_unknown_format_and_version_are_rejected(self):
        base = snapshot_to_dict(SessionSnapshot((), 6, False, ScanResult()))
        raw = dict(base)
        raw["format"] = "other"
        with self.assertRaises(SessionError):
            snapshot_from_dict(raw)
        raw = dict(base)
        raw["version"] = 99
        with self.assertRaises(SessionError):
            snapshot_from_dict(raw)

    def test_malformed_json_is_reported_as_session_error(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "broken.swirphoto"
            target.write_text("{broken", encoding="utf-8")
            with self.assertRaises(SessionError):
                load_session(target)

    def test_save_is_atomic_when_replace_fails(self):
        from unittest.mock import patch

        snapshot = SessionSnapshot((), 6, False, ScanResult())
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "review.swirphoto"
            target.write_text("original", encoding="utf-8")
            with patch("photoclean.session.os.replace", side_effect=OSError("blocked")):
                with self.assertRaises(OSError):
                    save_session(snapshot, target)
            self.assertEqual(target.read_text(encoding="utf-8"), "original")
            self.assertEqual([path.name for path in Path(folder).iterdir()], ["review.swirphoto"])


if __name__ == "__main__":
    unittest.main()
