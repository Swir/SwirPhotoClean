import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from photoclean.diagnostics import _atomic_write_json
from photoclean.evidence_snapshot import load_validated_restore_evidence_snapshot
from photoclean.recycle_evidence import (
    prepare_restore_evidence,
    validate_restore_evidence_report,
    verify_restore_evidence,
)


class EvidenceSnapshotTests(unittest.TestCase):
    def _verified_packaged_report(self, folder: str):
        def fake_recycler(path):
            Path(path).unlink()

        recycled = prepare_restore_evidence(folder, recycler=fake_recycler)
        shutil.copy2(recycled.original, recycled.copy)
        verified, _report = verify_restore_evidence(recycled.manifest)

        manifest = json.loads(verified.manifest.read_text(encoding="utf-8"))
        manifest["environment"]["frozen"] = True
        manifest["environment"]["platform"] = "Windows-11-10.0.26100-SP0"
        _atomic_write_json(verified.manifest, manifest)

        verified, report = verify_restore_evidence(verified.manifest)
        return verified, report

    def test_snapshot_returns_exact_validated_report_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            verified, report = self._verified_packaged_report(folder)
            expected_raw = report.read_bytes()

            check, report_path, raw, payload = load_validated_restore_evidence_snapshot(report)

            self.assertEqual(check.session_id, verified.session_id)
            self.assertEqual(report_path, report.resolve())
            self.assertEqual(raw, expected_raw)
            self.assertEqual(payload, json.loads(expected_raw.decode("utf-8")))
            self.assertEqual(
                hashlib.sha256(raw).hexdigest(),
                hashlib.sha256(expected_raw).hexdigest(),
            )

    def test_original_report_mutation_cannot_replace_bytes_being_validated(self):
        with tempfile.TemporaryDirectory() as folder:
            verified, report = self._verified_packaged_report(folder)
            original_raw = report.read_bytes()
            original_validator = validate_restore_evidence_report

            def mutate_original_then_validate_snapshot(snapshot, *, manifest=None):
                tampered = json.loads(report.read_text(encoding="utf-8"))
                tampered["inspection"]["copy_matches"] = False
                report.write_text(json.dumps(tampered, indent=2), encoding="utf-8")
                return original_validator(snapshot, manifest=manifest)

            with patch(
                "photoclean.evidence_snapshot.validate_restore_evidence_report",
                side_effect=mutate_original_then_validate_snapshot,
            ):
                check, _report_path, raw, payload = load_validated_restore_evidence_snapshot(report)

            self.assertEqual(check.session_id, verified.session_id)
            self.assertEqual(raw, original_raw)
            self.assertTrue(payload["inspection"]["copy_matches"])
            self.assertNotEqual(report.read_bytes(), original_raw)


if __name__ == "__main__":
    unittest.main()
