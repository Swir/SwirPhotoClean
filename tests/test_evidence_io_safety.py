import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from photoclean import diagnostics
from photoclean.evidence_io import (
    hardened_atomic_write_json,
    hardened_export_recycle_evidence,
    hardened_inspect_recycle_evidence,
    hardened_load_recycle_verification,
    hardened_read_json_object,
    hardened_read_manifest_payload,
    hardened_read_payload_for_transition,
    hardened_validate_restore_evidence_report,
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

    def test_symlink_parent_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            real_parent = root / "real-parent"
            real_parent.mkdir()
            linked_parent = root / "linked-parent"
            try:
                linked_parent.symlink_to(real_parent, target_is_directory=True)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"directory symlinks unavailable: {error}")

            target = linked_parent / "evidence.json"
            with self.assertRaisesRegex(
                diagnostics.RecycleVerificationError,
                "directory ancestry",
            ):
                hardened_atomic_write_json(target, {"safe": True})

            self.assertFalse((real_parent / "evidence.json").exists())
            self.assertEqual(list(real_parent.glob(".evidence.json.*.tmp")), [])

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

    def test_directory_ancestry_is_rechecked_before_atomic_replace(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "evidence.json"
            ancestry_error = diagnostics.RecycleVerificationError(
                "Evidence output directory ancestry changed before commit"
            )

            with mock.patch(
                "photoclean.evidence_io._require_safe_directory_ancestry",
                side_effect=[None, None, ancestry_error],
            ) as ancestry_check:
                with self.assertRaisesRegex(
                    diagnostics.RecycleVerificationError,
                    "directory ancestry changed before commit",
                ):
                    hardened_atomic_write_json(target, {"safe": True})

            self.assertEqual(ancestry_check.call_count, 3)
            self.assertFalse(target.exists())
            self.assertEqual(list(Path(folder).glob(".evidence.json.*.tmp")), [])

    def test_manifest_hardlink_is_rejected_before_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            check = diagnostics.create_recycle_verification(folder)
            alias = Path(folder) / "manifest-hardlink.json"
            try:
                os.link(check.manifest, alias)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"hardlinks unavailable: {error}")

            with self.assertRaisesRegex(
                diagnostics.RecycleVerificationError,
                "must not be hardlinked",
            ):
                hardened_load_recycle_verification(alias)

    def test_manifest_symlink_parent_is_rejected_without_resolving_it(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            real_parent = root / "real"
            real_parent.mkdir()
            check = diagnostics.create_recycle_verification(real_parent)
            linked_folder = root / "linked-fixture"
            try:
                linked_folder.symlink_to(check.folder, target_is_directory=True)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"directory symlinks unavailable: {error}")

            linked_manifest = linked_folder / check.manifest.name
            with self.assertRaisesRegex(
                diagnostics.RecycleVerificationError,
                "directory ancestry",
            ):
                hardened_load_recycle_verification(linked_manifest)

    def test_manifest_path_swap_between_lstat_and_open_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            check = diagnostics.create_recycle_verification(folder)
            manifest = check.manifest
            replacement = Path(folder) / "replacement.json"
            shutil.copy2(manifest, replacement)
            original_open = os.open
            swapped = False

            def swap_then_open(path, flags):
                nonlocal swapped
                if not swapped and Path(path) == manifest:
                    swapped = True
                    backup = Path(folder) / "original-manifest.json"
                    manifest.replace(backup)
                    replacement.replace(manifest)
                return original_open(path, flags)

            with mock.patch(
                "photoclean.evidence_io.os.open",
                side_effect=swap_then_open,
            ):
                with self.assertRaisesRegex(
                    diagnostics.RecycleVerificationError,
                    "changed while it was being opened",
                ):
                    hardened_load_recycle_verification(manifest)

    def test_manifest_snapshot_drives_inspection_and_export(self):
        with tempfile.TemporaryDirectory() as folder:
            verified = self._verified_fixture(folder)
            loaded = hardened_load_recycle_verification(verified.manifest)
            inspection = hardened_inspect_recycle_evidence(loaded)
            self.assertTrue(inspection.valid)
            self.assertEqual(inspection.stage, "restored-verified")

            report = hardened_export_recycle_evidence(
                loaded,
                Path(folder) / "stable-report.json",
            )
            payload = hardened_read_json_object(
                report,
                max_bytes=2 * 1024 * 1024,
                label="Recycle evidence report",
            )
            self.assertEqual(
                payload["manifest"]["manifest_fingerprint"],
                loaded.manifest_fingerprint,
            )
            self.assertEqual(
                payload["inspection"]["manifest_fingerprint"],
                loaded.manifest_fingerprint,
            )

    def test_install_rebinds_readers_writer_exporter_and_validator(self):
        from photoclean import recycle_evidence

        old_diagnostics = {
            "_atomic_write_json": diagnostics._atomic_write_json,
            "load_recycle_verification": diagnostics.load_recycle_verification,
            "_read_payload_for_transition": diagnostics._read_payload_for_transition,
            "inspect_recycle_evidence": diagnostics.inspect_recycle_evidence,
            "export_recycle_evidence": diagnostics.export_recycle_evidence,
        }
        old_workflow = {
            "load_recycle_verification": recycle_evidence.load_recycle_verification,
            "_atomic_write_json": recycle_evidence._atomic_write_json,
            "_read_manifest_payload": recycle_evidence._read_manifest_payload,
            "inspect_recycle_evidence": recycle_evidence.inspect_recycle_evidence,
            "export_recycle_evidence": recycle_evidence.export_recycle_evidence,
            "validate_restore_evidence_report": recycle_evidence.validate_restore_evidence_report,
        }
        try:
            install_hardened_evidence_io()
            self.assertIs(
                diagnostics._atomic_write_json,
                hardened_atomic_write_json,
            )
            self.assertIs(
                diagnostics.load_recycle_verification,
                hardened_load_recycle_verification,
            )
            self.assertIs(
                diagnostics._read_payload_for_transition,
                hardened_read_payload_for_transition,
            )
            self.assertIs(
                diagnostics.inspect_recycle_evidence,
                hardened_inspect_recycle_evidence,
            )
            self.assertIs(
                diagnostics.export_recycle_evidence,
                hardened_export_recycle_evidence,
            )
            self.assertIs(
                recycle_evidence._read_manifest_payload,
                hardened_read_manifest_payload,
            )
            self.assertIs(
                recycle_evidence.validate_restore_evidence_report,
                hardened_validate_restore_evidence_report,
            )
        finally:
            for name, value in old_diagnostics.items():
                setattr(diagnostics, name, value)
            for name, value in old_workflow.items():
                setattr(recycle_evidence, name, value)

    def test_application_bootstrap_installs_hardening_before_runtime_dispatch(self):
        run_py = Path(__file__).resolve().parents[1] / "run.py"
        source = run_py.read_text(encoding="utf-8")
        install_at = source.index("install_hardened_evidence_io()")
        runtime_at = source.index("from photoclean.storage import resolve_runtime_storage")
        self.assertLess(install_at, runtime_at)


if __name__ == "__main__":
    unittest.main()
