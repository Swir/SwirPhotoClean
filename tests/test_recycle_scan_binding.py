import hashlib
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from photoclean import core
from photoclean.recycle import _scan_bound_snapshot, _scan_signature_from_stat


class RecycleScanBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        original = self.root / "original.png"
        duplicate = self.root / "duplicate.png"
        Image.new("RGB", (64, 48), "#336699").save(original)
        shutil.copy2(original, duplicate)
        self.result = core.scan([self.root], include_similar=False)
        self.assertEqual(len(self.result.groups), 1)
        self.target = self.result.groups[0].photos[0]

    def tearDown(self):
        self.tmp.cleanup()

    def test_production_dispatch_forwards_exact_scan_identity_and_digest(self):
        with patch("photoclean.recycle.recycle_file") as recycle_file:
            completed, failed = core.recycle_selected(self.result, [self.target.path])

        self.assertEqual(completed, [self.target.path])
        self.assertEqual(failed, [])
        recycle_file.assert_called_once_with(
            str(self.target.path),
            expected_scan_signature=(
                self.target.size,
                self.target.modified_ns,
                self.target.device,
                self.target.inode,
            ),
            expected_scan_digest=self.target.digest,
        )

    def test_injected_recycle_callback_keeps_legacy_one_argument_contract(self):
        calls = []
        completed, failed = core.recycle_selected(
            self.result,
            [self.target.path],
            recycle=calls.append,
        )

        self.assertEqual(completed, [self.target.path])
        self.assertEqual(failed, [])
        self.assertEqual(calls, [str(self.target.path)])

    def test_scan_bound_snapshot_accepts_unchanged_scanned_object(self):
        candidate = self.root / "standalone.bin"
        candidate.write_bytes(b"safe-scan-binding")
        expected_signature = _scan_signature_from_stat(candidate.stat())
        expected_digest = hashlib.sha256(candidate.read_bytes()).hexdigest()

        checked, _identity, digest = _scan_bound_snapshot(
            candidate,
            expected_scan_signature=expected_signature,
            expected_scan_digest=expected_digest,
        )

        self.assertEqual(checked, candidate.absolute())
        self.assertEqual(digest, expected_digest)

    def test_scan_bound_snapshot_rejects_content_change_with_restored_scan_metadata(self):
        candidate = self.root / "same-metadata.bin"
        candidate.write_bytes(b"safe")
        before = candidate.stat()
        expected_signature = _scan_signature_from_stat(before)
        expected_digest = hashlib.sha256(b"safe").hexdigest()

        candidate.write_bytes(b"evil")  # same size: only full-content evidence differs
        os.utime(candidate, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual(_scan_signature_from_stat(candidate.stat()), expected_signature)

        with self.assertRaisesRegex(OSError, "Zawartość pliku zmieniła się"):
            _scan_bound_snapshot(
                candidate,
                expected_scan_signature=expected_signature,
                expected_scan_digest=expected_digest,
            )

    def test_scan_bound_snapshot_rejects_identity_change_before_hash_baseline(self):
        candidate = self.root / "identity.bin"
        candidate.write_bytes(b"safe")
        expected_signature = _scan_signature_from_stat(candidate.stat())
        expected_digest = hashlib.sha256(b"safe").hexdigest()
        candidate.write_bytes(b"replacement-is-longer")

        with self.assertRaisesRegex(OSError, "Plik zmienił się"):
            _scan_bound_snapshot(
                candidate,
                expected_scan_signature=expected_signature,
                expected_scan_digest=expected_digest,
            )


if __name__ == "__main__":
    unittest.main()
