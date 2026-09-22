import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from photoclean import diagnostics
from photoclean.evidence_io import (
    hardened_atomic_write_json,
    hardened_export_recycle_evidence,
    install_hardened_evidence_io,
)


class EvidenceIOSafetyTests(unittest.TestCase):
    def _verified_fixture(self, folder):
        check = diagnostics.create_recycle_verification(folder)

        def fake_recycler(path):
            Path(path).unlink()

        recycled = diagnostics.move_generated_copy_to_recycle(
            check,
            recycler=fake_recycler,
        )
        shutil.copy2(recycled.original, recycled.copy)
        return diagnostics.verify_restored_copy(recycled)

    def test_existing_regular_report_can_be_replaced_safely(self):
        with tempfile.TemporaryDirectory() as folder:
            verified = self._verified_fixture(folder)
            target = Path(folder) / "evidence-report.json"
            target.write_text('{"stale": true}', encoding="utf-8")

            exported = hardened_export_recycle_evidence(verified, target)
            payload = json.loads(exported.read_text(encoding="utf-8"))

            self.assertEqual(exported, target.absolute())
            self.assertEqual(payload["report_version"], 1)
            self.assertFalse(payload["acceptance_gate_closed"])
            self.assertTrue(payload["inspection"]["valid"])
            self.assertEqual(payload["inspection"]["stage"], "restored-verified")

    def test_hardlinked_report_destination_is_rejected_without_touching_fixture(self):
        with tempfile.TemporaryDirectory() as folder:
            verified = self._verified_fixture(folder)
            target = Path(folder) / "evidence-report.json"
            original_bytes = verified.original.read_bytes()
            try:
                os.link(verified.original, target)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"hardlinks unavailable: {error}")

            with self.assertRaises(diagnostics.RecycleVerificationError):
                hardened_export_recycle_evidence(verified, target)

            self.assertEqual(verified.original.read_bytes(), original_bytes)
            self.assertTrue(os.path.samefile(verified.original, target))

    def test_symlink_report_destination_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            verified = self._verified_fixture(folder)
            target = Path(folder) / "evidence-report.json"
            try:
                target.symlink_to(verified.original)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"symlinks unavailable: {error}")

            with self.assertRaises(diagnostics.RecycleVerificationError):
                hardened_export_recycle_evidence(verified, target)

            self.assertTrue(target.is_symlink())
            self.assertTrue(verified.original.is_file())

    def test_output_creation_during_staging_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "evidence.json"
            changed_identity = (1, 2, 1, 3, 4, 5)

            with mock.patch(
                "photoclean.evidence_io._safe_output_identity",
                side_effect=[None, changed_identity],
            ):
                with self.assertRaises(diagnostics.RecycleVerificationError) as raised:
                    hardened_atomic_write_json(target, {"safe": True})

            self.assertIn("changed while validated bytes were staged", str(raised.exception))
            self.assertFalse(target.exists())
            leftovers = list(Path(folder).glob(".evidence.json.*.tmp"))
            self.assertEqual(leftovers, [])

    def test_install_rebinds_diagnostics_writer_and_exporter(self):
        old_writer = diagnostics._atomic_write_json
        old_exporter = diagnostics.export_recycle_evidence
        try:
            install_hardened_evidence_io()
            self.assertIs(diagnostics._atomic_write_json, hardened_atomic_write_json)
            self.assertIs(
                diagnostics.export_recycle_evidence,
                hardened_export_recycle_evidence,
            )
        finally:
            diagnostics._atomic_write_json = old_writer
            diagnostics.export_recycle_evidence = old_exporter

    def test_application_bootstrap_installs_hardening_before_runtime_dispatch(self):
        run_py = Path(__file__).resolve().parents[1] / "run.py"
        source = run_py.read_text(encoding="utf-8")
        install_at = source.index("install_hardened_evidence_io()")
        runtime_at = source.index("from photoclean.storage import resolve_runtime_storage")
        self.assertLess(install_at, runtime_at)


if __name__ == "__main__":
    unittest.main()
