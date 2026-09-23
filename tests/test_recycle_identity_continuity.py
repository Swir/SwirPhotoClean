import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from photoclean.diagnostics import RecycleVerificationError
from photoclean.recycle import RecycleReceipt
from photoclean.recycle_evidence import (
    RECYCLE_RECEIPT_FIELD,
    cli_main,
    prepare_restore_evidence,
    validate_restore_evidence_report,
    verify_restore_evidence,
)


class RecycleIdentityContinuityTests(unittest.TestCase):
    def _rename_recycler(self, destination: Path):
        def recycle(path: str):
            source = Path(path)
            info = source.stat()
            receipt = RecycleReceipt(
                source_device=int(info.st_dev),
                source_inode=int(info.st_ino),
                recycled_shell_path=str(destination),
            )
            source.replace(destination)
            return receipt

        return recycle

    def test_same_filesystem_object_restore_is_bound_into_review_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fake_bin = root / "fake-recycle-bin-item.png"
            recycled = prepare_restore_evidence(
                root / "workspace",
                recycler=self._rename_recycler(fake_bin),
            )

            payload = json.loads(recycled.manifest.read_text(encoding="utf-8"))
            receipt = payload[RECYCLE_RECEIPT_FIELD]
            self.assertGreater(receipt["source_inode"], 0)
            self.assertEqual(
                payload["events"][-1][RECYCLE_RECEIPT_FIELD],
                receipt,
            )
            self.assertTrue(fake_bin.is_file())
            self.assertFalse(recycled.copy.exists())

            # A normal same-volume Recycle Bin restore is represented by moving
            # the exact filesystem object back to its original generated path.
            fake_bin.replace(recycled.copy)
            restored_info = recycled.copy.stat()
            self.assertEqual(int(restored_info.st_dev), receipt["source_device"])
            self.assertEqual(int(restored_info.st_ino), receipt["source_inode"])

            verified, report = verify_restore_evidence(recycled.manifest)
            self.assertEqual(verified.stage, "restored-verified")
            reviewed, reviewed_report = validate_restore_evidence_report(report)
            self.assertEqual(reviewed.manifest, verified.manifest)
            self.assertEqual(reviewed_report, report)

            stream = io.StringIO()
            with redirect_stdout(stream):
                exit_code = cli_main(["--recycle-restore-review", str(report)])
            self.assertEqual(exit_code, 0)
            self.assertIn("FILESYSTEM_IDENTITY_CONTINUITY=yes", stream.getvalue())
            self.assertIn("READY_FOR_MANUAL_ACCEPTANCE_REVIEW", stream.getvalue())

    def test_byte_identical_recreated_file_cannot_fake_receipt_bound_restore(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fake_bin = root / "fake-recycle-bin-item.png"
            recycled = prepare_restore_evidence(
                root / "workspace",
                recycler=self._rename_recycler(fake_bin),
            )

            # Recreate the bytes from KEEP-ME.png instead of restoring the object
            # that was actually moved. Digest/size match, but file identity must
            # expose the substitution before the manifest can advance.
            shutil.copy2(recycled.original, recycled.copy)
            with self.assertRaisesRegex(
                RecycleVerificationError,
                "same filesystem object",
            ):
                verify_restore_evidence(recycled.manifest)

            payload = json.loads(recycled.manifest.read_text(encoding="utf-8"))
            self.assertEqual(payload["stage"], "recycled")
            self.assertTrue(fake_bin.is_file())

    def test_injected_recycler_without_receipt_keeps_legacy_test_path_compatible(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)

            def simple_recycler(path: str):
                Path(path).unlink()

            recycled = prepare_restore_evidence(root / "workspace", recycler=simple_recycler)
            payload = json.loads(recycled.manifest.read_text(encoding="utf-8"))
            self.assertNotIn(RECYCLE_RECEIPT_FIELD, payload)

            shutil.copy2(recycled.original, recycled.copy)
            verified, report = verify_restore_evidence(recycled.manifest)
            self.assertEqual(verified.stage, "restored-verified")

            stream = io.StringIO()
            with redirect_stdout(stream):
                exit_code = cli_main(["--recycle-restore-review", str(report)])
            self.assertEqual(exit_code, 0)
            self.assertIn("FILESYSTEM_IDENTITY_CONTINUITY=not-recorded", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
