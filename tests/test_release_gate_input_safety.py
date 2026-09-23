import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from photoclean.safety_contract import source_safety_contract_sha256
from tools.release_gate import (
    _MAX_RUNTIME_EVIDENCE_BYTES,
    ReleaseGateError,
    _read_runtime_evidence,
    _read_stable_runtime_evidence_payload,
)


def valid_runtime_evidence() -> dict:
    return {
        "schema_version": 3,
        "kind": "windows-recycle-restore",
        "session_id": "a" * 32,
        "fixture_sha256": "b" * 64,
        "manifest_fingerprint": "c" * 64,
        "evidence_report_sha256": "d" * 64,
        "safety_contract_sha256": source_safety_contract_sha256(),
        "verified_at_utc": "2026-09-23T08:00:00+00:00",
        "reviewed_at_utc": "2026-09-23T08:05:00+00:00",
        "physical_recycle_move_confirmed": True,
        "manual_restore_performed": True,
        "original_preserved": True,
        "restored_copy_sha256_verified": True,
        "report_review_valid": True,
        "windows_packaged_runtime_confirmed": True,
        "acceptance_gate_closed": False,
    }


def write_valid_evidence(path: Path) -> None:
    path.write_text(
        json.dumps(valid_runtime_evidence(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


class ReleaseGateInputSafetyTests(unittest.TestCase):
    def test_regular_bounded_runtime_evidence_snapshot_is_parsed(self):
        with tempfile.TemporaryDirectory() as folder:
            evidence = Path(folder) / "RELEASE_EVIDENCE.json"
            write_valid_evidence(evidence)

            loaded = _read_stable_runtime_evidence_payload(evidence)

            self.assertEqual(loaded["kind"], "windows-recycle-restore")
            self.assertEqual(
                loaded["safety_contract_sha256"],
                source_safety_contract_sha256(),
            )

    def test_directory_is_rejected_before_json_read(self):
        with tempfile.TemporaryDirectory() as folder:
            evidence = Path(folder) / "RELEASE_EVIDENCE.json"
            evidence.mkdir()

            with self.assertRaisesRegex(ReleaseGateError, "regular file"):
                _read_stable_runtime_evidence_payload(evidence)

    def test_hardlinked_runtime_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.json"
            alias = Path(folder) / "RELEASE_EVIDENCE.json"
            write_valid_evidence(source)
            try:
                os.link(source, alias)
            except OSError as error:
                self.skipTest(f"hardlinks unavailable in test environment: {error}")

            with self.assertRaisesRegex(ReleaseGateError, "hardlinked"):
                _read_stable_runtime_evidence_payload(alias)

    def test_symlink_runtime_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.json"
            alias = Path(folder) / "RELEASE_EVIDENCE.json"
            write_valid_evidence(source)
            try:
                os.symlink(source, alias)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"symlinks unavailable in test environment: {error}")

            with self.assertRaisesRegex(
                ReleaseGateError,
                "symlink, junction or reparse point",
            ):
                _read_stable_runtime_evidence_payload(alias)

    def test_oversized_runtime_evidence_is_rejected_before_json_decode(self):
        with tempfile.TemporaryDirectory() as folder:
            evidence = Path(folder) / "RELEASE_EVIDENCE.json"
            evidence.write_bytes(b"x" * (_MAX_RUNTIME_EVIDENCE_BYTES + 1))

            with self.assertRaisesRegex(ReleaseGateError, "too large"):
                _read_stable_runtime_evidence_payload(evidence)

    def test_invalid_utf8_is_reported_as_gate_error(self):
        with tempfile.TemporaryDirectory() as folder:
            evidence = Path(folder) / "RELEASE_EVIDENCE.json"
            evidence.write_bytes(b"\xff\xfe\xfd")

            with self.assertRaisesRegex(ReleaseGateError, "UTF-8 JSON"):
                _read_stable_runtime_evidence_payload(evidence)

    def test_qualified_gate_rejects_hardlinked_runtime_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.json"
            alias = Path(folder) / "RELEASE_EVIDENCE.json"
            write_valid_evidence(source)
            try:
                os.link(source, alias)
            except OSError as error:
                self.skipTest(f"hardlinks unavailable in test environment: {error}")

            with patch("tools.release_evidence.RELEASE_EVIDENCE_PATH", alias):
                with self.assertRaisesRegex(ReleaseGateError, "hardlinked"):
                    _read_runtime_evidence(required=True)


if __name__ == "__main__":
    unittest.main()
