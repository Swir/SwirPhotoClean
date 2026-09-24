import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from photoclean.diagnostics import _atomic_write_json
from photoclean.recycle_evidence import prepare_restore_evidence, verify_restore_evidence
from tools.release_evidence import ReleaseEvidenceError, write_release_evidence


class StableReleaseEvidenceOutputTests(unittest.TestCase):
    def _verified_report(self, folder: str) -> Path:
        def fake_recycler(path):
            Path(path).unlink()

        recycled = prepare_restore_evidence(folder, recycler=fake_recycler)
        shutil.copy2(recycled.original, recycled.copy)
        verified, _report = verify_restore_evidence(recycled.manifest)

        manifest = json.loads(verified.manifest.read_text(encoding="utf-8"))
        manifest["environment"]["frozen"] = True
        manifest["environment"]["platform"] = "Windows-11-10.0.26100-SP0"
        _atomic_write_json(verified.manifest, manifest)

        _verified, report = verify_restore_evidence(verified.manifest)
        return report

    def test_writer_does_not_reopen_stage_or_final_output_by_path(self):
        with tempfile.TemporaryDirectory() as folder:
            report = self._verified_report(folder)
            output = Path(folder) / "RELEASE_EVIDENCE.json"
            original_read_bytes = Path.read_bytes

            def guarded_read_bytes(path, *args, **kwargs):
                if path.name == output.name or (
                    path.name.startswith(f".{output.name}.") and path.name.endswith(".tmp")
                ):
                    raise AssertionError("release evidence output must use stable handles")
                return original_read_bytes(path, *args, **kwargs)

            with patch.object(Path, "read_bytes", guarded_read_bytes):
                written = write_release_evidence(
                    report,
                    output,
                    confirm_manual_restore=True,
                )

            self.assertEqual(written, output.resolve())
            self.assertTrue(output.is_file())

    def test_writer_detects_staged_path_identity_change(self):
        with tempfile.TemporaryDirectory() as folder:
            report = self._verified_report(folder)
            output = Path(folder) / "RELEASE_EVIDENCE.json"

            from tools import release_evidence

            real_identity = release_evidence._release_evidence_output_identity

            def changed_identity(path):
                identity = real_identity(path)
                if (
                    identity is not None
                    and path.name.startswith(f".{output.name}.")
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
                "tools.release_evidence._release_evidence_output_identity",
                side_effect=changed_identity,
            ):
                with self.assertRaisesRegex(ReleaseEvidenceError, "staged.*path changed"):
                    write_release_evidence(
                        report,
                        output,
                        confirm_manual_restore=True,
                    )

            self.assertFalse(output.exists())
            self.assertEqual(list(Path(folder).glob(".RELEASE_EVIDENCE.json.*.tmp")), [])

    def test_writer_detects_final_path_swap_during_open(self):
        with tempfile.TemporaryDirectory() as folder:
            report = self._verified_report(folder)
            output = Path(folder) / "RELEASE_EVIDENCE.json"
            replacement = Path(folder) / "replacement-release-evidence.json"
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

            with patch("tools.release_evidence.os.open", side_effect=swapping_open):
                with self.assertRaisesRegex(ReleaseEvidenceError, "changed while it was being opened"):
                    write_release_evidence(
                        report,
                        output,
                        confirm_manual_restore=True,
                    )

            self.assertTrue(swapped)
            self.assertTrue(output.is_file())

    def test_writer_rejects_oversized_existing_output(self):
        with tempfile.TemporaryDirectory() as folder:
            report = self._verified_report(folder)
            output = Path(folder) / "RELEASE_EVIDENCE.json"
            sentinel = b"x" * (64 * 1024 + 1)
            output.write_bytes(sentinel)

            with self.assertRaisesRegex(ReleaseEvidenceError, "output is too large"):
                write_release_evidence(
                    report,
                    output,
                    confirm_manual_restore=True,
                )

            self.assertEqual(output.read_bytes(), sentinel)


if __name__ == "__main__":
    unittest.main()
