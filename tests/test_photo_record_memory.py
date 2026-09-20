import pickle
import unittest
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

from photoclean.core import Photo


class PhotoRecordMemoryTests(unittest.TestCase):
    @staticmethod
    def make_photo() -> Photo:
        return Photo(
            path=Path("sample.jpg"),
            size=123,
            modified_ns=456,
            device=7,
            inode=8,
            digest="a" * 64,
            width=1920,
            height=1080,
            dhash=0x1234,
            color=bytes([32]) * 192,
        )

    def test_photo_uses_slots_without_dynamic_instance_dict(self):
        photo = self.make_photo()
        self.assertFalse(hasattr(photo, "__dict__"))
        self.assertEqual(
            [item.name for item in fields(Photo)],
            [
                "path",
                "size",
                "modified_ns",
                "device",
                "inode",
                "digest",
                "width",
                "height",
                "dhash",
                "color",
            ],
        )

    def test_photo_remains_frozen_and_value_comparable(self):
        photo = self.make_photo()
        self.assertEqual(photo, self.make_photo())
        with self.assertRaises(FrozenInstanceError):
            photo.width = 1

    def test_photo_remains_pickle_roundtrip_compatible(self):
        photo = self.make_photo()
        restored = pickle.loads(pickle.dumps(photo))
        self.assertEqual(restored, photo)


if __name__ == "__main__":
    unittest.main()
