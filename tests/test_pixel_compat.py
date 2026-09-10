import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from photoclean.core import scan

class PixelCompatibilityTests(unittest.TestCase):
    def test_scan_without_flattened_data_api(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Image.new("RGB", (64, 48), "teal")
            image.save(Path(directory) / "a.png")
            image.save(Path(directory) / "b.png")
            with patch.object(Image.Image, "get_flattened_data", create=True, side_effect=AttributeError("API unavailable")):
                result = scan([directory])
            self.assertEqual(len(result.photos), 2)
            self.assertEqual(len(result.groups), 1)
            self.assertEqual(len(result.photos[0].color), 192)
            self.assertFalse(result.warnings)
