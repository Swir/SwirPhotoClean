import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import photoclean.evidence_io as evidence_io
from photoclean.diagnostics import RecycleVerificationError


class EvidenceIoNoFollowTests(unittest.TestCase):
    def test_reader_requests_no_follow_flag_when_available(self):
        with tempfile.TemporaryDirectory() as folder:
            manifest = Path(folder) / "manifest.json"
            manifest.write_text(json.dumps({"stage": "test"}), encoding="utf-8")

            real_open = os.open
            synthetic_nofollow = 1 << 29
            seen_flags = []

            def recording_open(path, flags, *args, **kwargs):
                seen_flags.append(flags)
                return real_open(path, flags & ~synthetic_nofollow, *args, **kwargs)

            with patch.object(
                evidence_io.os,
                "O_NOFOLLOW",
                synthetic_nofollow,
                create=True,
            ), patch.object(evidence_io.os, "open", side_effect=recording_open):
                payload = evidence_io.hardened_read_json_object(
                    manifest,
                    label="test evidence",
                )

            self.assertEqual(payload, {"stage": "test"})
            self.assertTrue(seen_flags)
            self.assertTrue(seen_flags[0] & synthetic_nofollow)

    def test_final_entry_swap_after_lstat_fails_closed(self):
        if not hasattr(os, "O_NOFOLLOW"):
            self.skipTest("platform does not expose O_NOFOLLOW")

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = root / "manifest.json"
            alternate = root / "alternate.json"
            manifest.write_text(json.dumps({"stage": "original"}), encoding="utf-8")
            alternate.write_text(json.dumps({"stage": "alternate"}), encoding="utf-8")

            original_safe_input_info = evidence_io._safe_input_info
            calls = 0

            def swap_after_first_inspection(path, *, max_bytes, label):
                nonlocal calls
                info = original_safe_input_info(path, max_bytes=max_bytes, label=label)
                calls += 1
                if calls == 1:
                    manifest.unlink()
                    try:
                        manifest.symlink_to(alternate)
                    except OSError as error:
                        self.skipTest(f"symlinks unavailable: {error}")
                return info

            with patch.object(
                evidence_io,
                "_safe_input_info",
                side_effect=swap_after_first_inspection,
            ):
                with self.assertRaises(RecycleVerificationError):
                    evidence_io.hardened_read_json_object(
                        manifest,
                        label="test evidence",
                    )

    def test_open_error_never_falls_back_to_path_read(self):
        with tempfile.TemporaryDirectory() as folder:
            manifest = Path(folder) / "manifest.json"
            manifest.write_text(json.dumps({"stage": "test"}), encoding="utf-8")

            with patch.object(
                evidence_io.os,
                "open",
                side_effect=OSError("simulated safe-open failure"),
            ):
                with self.assertRaisesRegex(
                    RecycleVerificationError,
                    "Cannot open test evidence safely",
                ):
                    evidence_io.hardened_read_json_object(
                        manifest,
                        label="test evidence",
                    )


if __name__ == "__main__":
    unittest.main()
