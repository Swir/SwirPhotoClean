import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from photoclean.cleanup_history import (
    CleanupEntry,
    CleanupRecord,
    append_cleanup_record,
    load_cleanup_history,
)


class CleanupHistoryHardeningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root / "cleanup-history.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _record(self) -> CleanupRecord:
        entry = CleanupEntry(
            path=str(self.root / "kopia.png"),
            size=120,
            digest="1" * 64,
            status="moved",
            exact_survivor=True,
        )
        return CleanupRecord(
            record_id="hardening",
            started_at="2026-09-23T17:00:00+00:00",
            finished_at="2026-09-23T17:00:01+00:00",
            scan_photo_count_before=2,
            scan_photo_count_after_snapshot=1,
            scan_group_count=1,
            requested_count=1,
            completed_count=1,
            requested_bytes=120,
            moved_to_recycle_bytes=120,
            guaranteed_reclaimable_after_bin_empty=120,
            entries=(entry,),
            errors=(),
        )

    def test_byte_identical_open_handle_substitution_is_rejected(self):
        append_cleanup_record(self.path, self._record())
        decoy = self.root / "decoy-history.json"
        shutil.copy2(self.path, decoy)
        original_open = Path.open

        def redirected_open(path, *args, **kwargs):
            if Path(path) == self.path:
                return original_open(decoy, *args, **kwargs)
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", redirected_open):
            with self.assertRaisesRegex(ValueError, "changed while it was being opened"):
                load_cleanup_history(self.path)

    def test_oversized_history_is_rejected_before_json_parsing(self):
        self.path.write_bytes(b"{" + b"x" * 64)
        with patch("photoclean.cleanup_history.MAX_HISTORY_BYTES", 32):
            with self.assertRaisesRegex(ValueError, "too large"):
                load_cleanup_history(self.path)

    def test_tampered_requested_bytes_are_rejected(self):
        append_cleanup_record(self.path, self._record())
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["sessions"][0]["requested_bytes"] = 999999
        self.path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "requested bytes do not match entries"):
            load_cleanup_history(self.path)

    def test_truthy_non_boolean_exact_survivor_is_rejected(self):
        append_cleanup_record(self.path, self._record())
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["sessions"][0]["entries"][0]["exact_survivor"] = 1
        self.path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "exact_survivor must be a boolean"):
            load_cleanup_history(self.path)

    def test_unknown_record_fields_are_rejected(self):
        append_cleanup_record(self.path, self._record())
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["sessions"][0]["invented_counter"] = 1
        self.path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "missing or unsupported fields"):
            load_cleanup_history(self.path)


if __name__ == "__main__":
    unittest.main()
