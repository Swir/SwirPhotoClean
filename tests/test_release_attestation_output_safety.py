import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from photoclean.diagnostics import _atomic_write_json
from photoclean.recycle_evidence import prepare_restore_evidence, verify_restore_evidence
from photoclean.release_attestation import (
    ATTESTATION_NAME,
    PackagedAttestationError,
    validate_packaged_attestation,
    write_packaged_attestation,
)


class ReleaseAttestationOutputSafetyTests(unittest.TestCase):
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

    def test_attestation_output_cannot_overwrite_source_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            verified, report = self._verified_packaged_report(folder)
            protected = [report, verified.manifest, verified.original, verified.copy]
            before = {path: path.read_bytes() for path in protected}

            for target in protected:
                with self.subTest(target=target.name):
                    with self.assertRaises(PackagedAttestationError):
                        write_packaged_attestation(
                            report,
                            target,
                            confirm_manual_restore=True,
                        )
                    self.assertEqual(target.read_bytes(), before[target])

    def test_attestation_output_cannot_hardlink_alias_source_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            _verified, report = self._verified_packaged_report(folder)
            alias = report.parent / "release-evidence-hardlink.json"
            try:
                os.link(report, alias)
            except OSError as error:
                self.skipTest(f"hardlinks unavailable in test environment: {error}")
            before = report.read_bytes()

            # The newer snapshot intake can reject the now-hardlinked source report
            # before the writer reaches its output-alias guard. Both paths are
            # deliberately fail-closed and must preserve both filesystem entries.
            with self.assertRaisesRegex(
                PackagedAttestationError,
                "overwrite or alias|must not be hardlinked",
            ):
                write_packaged_attestation(
                    report,
                    alias,
                    confirm_manual_restore=True,
                )

            self.assertEqual(report.read_bytes(), before)
            self.assertEqual(alias.read_bytes(), before)

    def test_attestation_writer_rejects_hardlinked_unrelated_output(self):
        with tempfile.TemporaryDirectory() as folder:
            _verified, report = self._verified_packaged_report(folder)
            unrelated = report.parent / "unrelated.json"
            unrelated.write_text("keep", encoding="utf-8")
            output = report.parent / ATTESTATION_NAME
            try:
                os.link(unrelated, output)
            except OSError as error:
                self.skipTest(f"hardlinks unavailable in test environment: {error}")

            with self.assertRaisesRegex(PackagedAttestationError, "must not be hardlinked"):
                write_packaged_attestation(
                    report,
                    output,
                    confirm_manual_restore=True,
                )

            self.assertEqual(unrelated.read_text(encoding="utf-8"), "keep")
            self.assertEqual(output.read_text(encoding="utf-8"), "keep")

    def test_attestation_writer_rejects_symlink_output(self):
        with tempfile.TemporaryDirectory() as folder:
            _verified, report = self._verified_packaged_report(folder)
            destination = report.parent / "unrelated.json"
            destination.write_text("keep", encoding="utf-8")
            output = report.parent / ATTESTATION_NAME
            try:
                output.symlink_to(destination)
            except OSError as error:
                self.skipTest(f"symlinks unavailable in test environment: {error}")

            with self.assertRaisesRegex(PackagedAttestationError, "symlink"):
                write_packaged_attestation(
                    report,
                    output,
                    confirm_manual_restore=True,
                )

            self.assertEqual(destination.read_text(encoding="utf-8"), "keep")

    def test_attestation_writer_rejects_redirected_parent_ancestry(self):
        with tempfile.TemporaryDirectory() as folder:
            _verified, report = self._verified_packaged_report(folder)
            real_output = report.parent / "real-output"
            real_output.mkdir()
            redirected = report.parent / "redirected-output"
            try:
                redirected.symlink_to(real_output, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"directory symlinks unavailable in test environment: {error}")
            output = redirected / ATTESTATION_NAME

            with self.assertRaisesRegex(
                PackagedAttestationError,
                "directory ancestry.*symlinks|directory ancestry must not contain",
            ):
                write_packaged_attestation(
                    report,
                    output,
                    confirm_manual_restore=True,
                )

            self.assertFalse((real_output / ATTESTATION_NAME).exists())

    def test_attestation_writer_allows_safe_missing_nested_output_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            _verified, report = self._verified_packaged_report(folder)
            output = report.parent / "safe" / "nested" / ATTESTATION_NAME

            written = write_packaged_attestation(
                report,
                output,
                confirm_manual_restore=True,
            )

            self.assertEqual(written, output.resolve())
            payload = validate_packaged_attestation(
                json.loads(output.read_text(encoding="utf-8"))
            )
            self.assertTrue(payload["windows_packaged_runtime_confirmed"])

    def test_attestation_writer_does_not_reuse_predictable_tmp_path(self):
        with tempfile.TemporaryDirectory() as folder:
            _verified, report = self._verified_packaged_report(folder)
            output = report.parent / ATTESTATION_NAME
            legacy_tmp = output.with_suffix(output.suffix + ".tmp")
            legacy_tmp.write_text("do-not-touch", encoding="utf-8")

            written = write_packaged_attestation(
                report,
                output,
                confirm_manual_restore=True,
            )

            self.assertEqual(written, output.resolve())
            self.assertEqual(legacy_tmp.read_text(encoding="utf-8"), "do-not-touch")
            payload = validate_packaged_attestation(
                json.loads(output.read_text(encoding="utf-8"))
            )
            self.assertTrue(payload["manual_restore_performed"])
            self.assertFalse(payload["acceptance_gate_closed"])

    def test_attestation_writer_detects_output_identity_change_before_replace(self):
        with tempfile.TemporaryDirectory() as folder:
            _verified, report = self._verified_packaged_report(folder)
            output = report.parent / ATTESTATION_NAME

            from photoclean import release_attestation

            real_identity = release_attestation._attestation_output_identity
            output_checks = 0

            def changed_output_identity(path):
                nonlocal output_checks
                if path == output:
                    output_checks += 1
                    if output_checks == 1:
                        return None
                    return (1, 2, 1, 4, 5, 6)
                return real_identity(path)

            with patch(
                "photoclean.release_attestation._attestation_output_identity",
                side_effect=changed_output_identity,
            ):
                with self.assertRaisesRegex(PackagedAttestationError, "changed while validated"):
                    write_packaged_attestation(
                        report,
                        output,
                        confirm_manual_restore=True,
                    )

            self.assertGreaterEqual(output_checks, 2)
            self.assertFalse(output.exists())
            self.assertEqual(list(report.parent.glob(".RELEASE_EVIDENCE.json.*.tmp")), [])

    def test_attestation_writer_cleans_stage_when_atomic_replace_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            _verified, report = self._verified_packaged_report(folder)
            output = report.parent / ATTESTATION_NAME

            with patch(
                "photoclean.release_attestation.os.replace",
                side_effect=OSError("simulated replace failure"),
            ):
                with self.assertRaisesRegex(PackagedAttestationError, "atomically replace"):
                    write_packaged_attestation(
                        report,
                        output,
                        confirm_manual_restore=True,
                    )

            self.assertFalse(output.exists())
            self.assertEqual(list(report.parent.glob(".RELEASE_EVIDENCE.json.*.tmp")), [])

    def test_attestation_writer_does_not_reopen_staged_or_final_json_by_path(self):
        with tempfile.TemporaryDirectory() as folder:
            _verified, report = self._verified_packaged_report(folder)
            output = report.parent / ATTESTATION_NAME
            original_read_text = Path.read_text

            def guarded_read_text(path, *args, **kwargs):
                name = path.name
                if name == ATTESTATION_NAME or (
                    name.startswith(f".{ATTESTATION_NAME}.") and name.endswith(".tmp")
                ):
                    raise AssertionError("release attestation must use stable handles")
                return original_read_text(path, *args, **kwargs)

            with patch.object(Path, "read_text", guarded_read_text):
                written = write_packaged_attestation(
                    report,
                    output,
                    confirm_manual_restore=True,
                )

            self.assertEqual(written, output.resolve())
            self.assertTrue(output.is_file())

    def test_attestation_writer_detects_final_path_swap_during_open(self):
        with tempfile.TemporaryDirectory() as folder:
            _verified, report = self._verified_packaged_report(folder)
            output = report.parent / ATTESTATION_NAME
            replacement = report.parent / "replacement-release-evidence.json"
            real_open = os.open
            swapped = False

            def swapping_open(path, flags, mode=0o777, *, dir_fd=None):
                nonlocal swapped
                candidate = Path(path)
                if not swapped and candidate == output and output.exists():
                    replacement.write_bytes(output.read_bytes())
                    os.replace(replacement, output)
                    swapped = True
                if dir_fd is None:
                    return real_open(path, flags, mode)
                return real_open(path, flags, mode, dir_fd=dir_fd)

            with patch("photoclean.release_attestation.os.open", side_effect=swapping_open):
                with self.assertRaisesRegex(PackagedAttestationError, "changed while it was being opened"):
                    write_packaged_attestation(
                        report,
                        output,
                        confirm_manual_restore=True,
                    )

            self.assertTrue(swapped)
            self.assertTrue(output.is_file())

    def test_attestation_writer_detects_staged_path_identity_change(self):
        with tempfile.TemporaryDirectory() as folder:
            _verified, report = self._verified_packaged_report(folder)
            output = report.parent / ATTESTATION_NAME

            from photoclean import release_attestation

            real_identity = release_attestation._attestation_output_identity

            def changed_identity(path):
                identity = real_identity(path)
                if (
                    identity is not None
                    and path.name.startswith(f".{ATTESTATION_NAME}.")
                    and path.name.endswith(".tmp")
                ):
                    return (
                        identity[0],
                        identity[1] + 1,
                        identity[2],
                        identity[3],
                        identity[4],
                        identity[5],
                    )
                return identity

            with patch(
                "photoclean.release_attestation._attestation_output_identity",
                side_effect=changed_identity,
            ):
                with self.assertRaisesRegex(PackagedAttestationError, "staged.*path changed"):
                    write_packaged_attestation(
                        report,
                        output,
                        confirm_manual_restore=True,
                    )

            self.assertFalse(output.exists())
            self.assertEqual(list(report.parent.glob(".RELEASE_EVIDENCE.json.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
