import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from photoclean.core import Group, Photo, ScanResult
from photoclean.session import (
    SessionError,
    SessionSnapshot,
    audit_session_snapshot,
    load_session,
    snapshot_to_dict,
)


def _photo_from_file(path: Path, *, digest: str = "a" * 64) -> Photo:
    info = path.stat()
    return Photo(
        path=path,
        size=info.st_size,
        modified_ns=info.st_mtime_ns,
        device=info.st_dev,
        inode=info.st_ino,
        digest=digest,
        width=32,
        height=32,
        dhash=0,
        color=bytes(192),
    )


class SessionResumeHardeningTests(unittest.TestCase):
    def test_loader_enforces_byte_limit_even_if_path_stat_is_stale(self):
        """A pre-read stat must not be able to authorize a later oversized read."""

        snapshot = SessionSnapshot((), 6, False, ScanResult())
        payload = json.dumps(snapshot_to_dict(snapshot)) + (" " * 1024)
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "oversized.swirpc"
            source.write_text(payload, encoding="utf-8")

            # The pre-hardening loader trusted this stat before read_text(). A
            # concurrent growth/replacement could therefore bypass MAX_SESSION_BYTES.
            with patch.object(Path, "stat", return_value=SimpleNamespace(st_size=1)):
                with patch("photoclean.session.MAX_SESSION_BYTES", 256):
                    with self.assertRaisesRegex(
                        SessionError, "session file exceeds the supported size"
                    ):
                        load_session(source)

    def test_resume_drops_second_hardlink_identity_and_collapsed_group(self):
        """Resume must keep the scanner invariant: one physical file, one member."""

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first_path = root / "first.jpg"
            second_path = root / "second.jpg"
            first_path.write_bytes(b"same-physical-file")
            try:
                os.link(first_path, second_path)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"hardlinks unavailable: {error}")

            first = _photo_from_file(first_path)
            second = _photo_from_file(second_path)
            if not first.inode:
                self.skipTest("filesystem does not expose stable inode/file identity")

            snapshot = SessionSnapshot(
                roots=(root,),
                threshold=6,
                include_similar=True,
                result=ScanResult(
                    photos=[first, second],
                    groups=[Group("exact", (first, second))],
                ),
            )

            audit = audit_session_snapshot(snapshot)

            self.assertEqual(audit.checked_count, 2)
            self.assertEqual(audit.valid_count, 1)
            self.assertEqual(audit.duplicate_identity_count, 1)
            self.assertEqual(audit.stale_count, 1)
            self.assertEqual(audit.dropped_group_count, 1)
            self.assertEqual(audit.snapshot.result.photos, [first])
            self.assertEqual(audit.snapshot.result.groups, [])
            self.assertTrue(
                any(
                    "duplicate-identity=1" in warning
                    for warning in audit.snapshot.result.warnings
                )
            )


if __name__ == "__main__":
    unittest.main()
