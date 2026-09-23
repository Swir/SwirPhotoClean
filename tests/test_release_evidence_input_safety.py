import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.release_evidence import (
    _MAX_RELEASE_EVIDENCE_BYTES,
    ReleaseEvidenceError,
    read_release_evidence,
)


class ReleaseEvidenceInputSafetyTests(unittest.TestCase):
    def test_reader_rejects_non_regular_input(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ReleaseEvidenceError, "regular file"):
                read_release_evidence(folder)

    def test_reader_rejects_hardlinked_input(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "RELEASE_EVIDENCE.json"
            alias = Path(folder) / "release-evidence-hardlink.json"
            source.write_text("{}\n", encoding="utf-8")
            try:
                os.link(source, alias)
            except OSError as error:
                self.skipTest(f"hardlinks unavailable in test environment: {error}")

            with self.assertRaisesRegex(ReleaseEvidenceError, "hardlinked"):
                read_release_evidence(alias)

    def test_reader_rejects_symlink_input(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.json"
            alias = Path(folder) / "RELEASE_EVIDENCE.json"
            source.write_text("{}\n", encoding="utf-8")
            try:
                alias.symlink_to(source)
            except OSError as error:
                self.skipTest(f"symlinks unavailable in test environment: {error}")

            with self.assertRaisesRegex(
                ReleaseEvidenceError,
                "symlink, junction or reparse point",
            ):
                read_release_evidence(alias)

    def test_reader_rejects_oversized_input_before_json_parse(self):
        with tempfile.TemporaryDirectory() as folder:
            evidence = Path(folder) / "RELEASE_EVIDENCE.json"
            evidence.write_bytes(b"{" + b" " * _MAX_RELEASE_EVIDENCE_BYTES + b"}")

            with self.assertRaisesRegex(ReleaseEvidenceError, "too large"):
                read_release_evidence(evidence)

    def test_reader_rejects_path_swap_between_lstat_and_open(self):
        with tempfile.TemporaryDirectory() as folder:
            evidence = Path(folder) / "RELEASE_EVIDENCE.json"
            replacement = Path(folder) / "replacement.json"
            evidence.write_text("{}\n", encoding="utf-8")
            replacement.write_text("{}\n", encoding="utf-8")
            original_open = os.open
            swapped = False

            def swapping_open(path, flags, *args, **kwargs):
                nonlocal swapped
                if not swapped and Path(path) == evidence:
                    swapped = True
                    os.replace(replacement, evidence)
                return original_open(path, flags, *args, **kwargs)

            with patch("tools.release_evidence.os.open", side_effect=swapping_open):
                with self.assertRaisesRegex(ReleaseEvidenceError, "changed while it was being opened"):
                    read_release_evidence(evidence)

            self.assertTrue(swapped)

    def test_reader_rejects_invalid_utf8_after_safe_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            evidence = Path(folder) / "RELEASE_EVIDENCE.json"
            evidence.write_bytes(b"\xff\xfe\xfd")

            with self.assertRaisesRegex(ReleaseEvidenceError, "valid UTF-8 JSON"):
                read_release_evidence(evidence)


if __name__ == "__main__":
    unittest.main()
