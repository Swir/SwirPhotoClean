import os
import tempfile
import unittest
from pathlib import Path

from photoclean.recycle import recycle_file


@unittest.skipUnless(os.name == "nt", "Windows Recycle Bin integration")
class WindowsRecycleTests(unittest.TestCase):
    def test_generated_file_is_moved_or_left_untouched_on_error(self):
        """A failed shell operation must never turn into permanent deletion."""
        with tempfile.TemporaryDirectory(prefix="swir-photoclean-recycle-") as folder:
            target = Path(folder) / "generated-recycle-test.txt"
            target.write_text("SWIR PhotoClean generated test data", encoding="utf-8")
            try:
                recycle_file(target)
            except OSError:
                self.assertTrue(target.exists(), "A failed recycle operation removed the file")
            else:
                self.assertFalse(target.exists(), "A successful recycle operation left the source file")


if __name__ == "__main__":
    unittest.main()
