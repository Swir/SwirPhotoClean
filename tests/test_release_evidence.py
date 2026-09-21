import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.release_evidence import (
    ReleaseEvidenceError,
    build_release_evidence,
    read_release_evidence,
    write_release_evidence,
)
from photoclean.recycle_evidence import (
    prepare_restore_evidence,
    verify_restore_evidence,
)


class ReleaseEvidenceTests(unittest.TestCase):
    def _verified_report(self, folder: str):
        def fake_recycler(path):
            Path(path).unlink()

        recycled = prepare_restore_evidence(folder, recycler=fake_recycler)
        shutil.copy2(recycled.original, recycled.copy)
        verified, report = verify_restore_evidence(recycled.manifest)
        return verified, report

    def test_build_requires_explicit_manual_restore_attestation(self):
        with tempfile.TemporaryDirectory() as folder:
            _verified, report = self._verified_report(folder)
            with self.assertRaises(ReleaseEvidenceError):
                build_release_evidence(
                    report,
                    confirm_manual_restore=False,
                )

    def test_build_sanitizes_validated_report_into_commit_safe_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            verified, report = self._verified_report(folder)
            payload = build_release_evidence(
                report,
                confirm_manual_restore=True,
            )

            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(payload["kind"], "windows-recycle-restore")
            self.assertEqual(payload["session_id"], verified.session_id)
            self.assertEqual(payload["fixture_sha256"], verified.digest)
            self.assertEqual(
                payload["manifest_fingerprint"],
                verified.manifest_fingerprint,
            )
            self.assertEqual(len(payload["evidence_report_sha256"]), 64)
            self.assertTrue(payload["physical_recycle_move_confirmed"])
            self.assertTrue(payload["manual_restore_performed"])
            self.assertTrue(payload["original_preserved"])
            self.assertTrue(payload["restored_copy_sha256_verified"])
            self.assertTrue(payload["report_review_valid"])
            self.assertFalse(payload["acceptance_gate_closed"])

            serialized = json.dumps(payload)
            self.assertNotIn(str(Path(folder).resolve()), serialized)
            self.assertNotIn("KEEP-ME.png", serialized)
            self.assertNotIn("RECYCLE-ME.png", serialized)

    def test_write_and_read_round_trip_validated_release_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            _verified, report = self._verified_report(folder)
            output = Path(folder) / "RELEASE_EVIDENCE.json"
            written = write_release_evidence(
                report,
                output,
                confirm_manual_restore=True,
            )
            self.assertEqual(written, output.resolve())
            loaded = read_release_evidence(written)
            self.assertEqual(loaded["kind"], "windows-recycle-restore")
            self.assertFalse(loaded["acceptance_gate_closed"])

    def test_tampered_report_is_rejected_before_release_attestation(self):
        with tempfile.TemporaryDirectory() as folder:
            _verified, report = self._verified_report(folder)
            payload = json.loads(report.read_text(encoding="utf-8"))
            payload["inspection"]["copy_matches"] = False
            report.write_text(json.dumps(payload, indent=2), encoding="utf-8")

            with self.assertRaises(ReleaseEvidenceError):
                build_release_evidence(
                    report,
                    confirm_manual_restore=True,
                )


if __name__ == "__main__":
    unittest.main()
