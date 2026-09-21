import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from photoclean.diagnostics import RecycleVerificationError, create_recycle_verification
from photoclean.recycle_evidence import (
    create_restore_evidence,
    move_restore_evidence,
    prepare_restore_evidence,
    verify_restore_evidence,
)
from photoclean.safety_contract import source_safety_contract_sha256


class RecycleSafetyContractTests(unittest.TestCase):
    def test_new_cli_evidence_session_records_current_safety_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            check = create_restore_evidence(folder)
            payload = json.loads(check.manifest.read_text(encoding="utf-8"))
            self.assertEqual(
                payload["safety_contract_sha256"],
                source_safety_contract_sha256(),
            )
            self.assertTrue(check.original.exists())
            self.assertTrue(check.copy.exists())

    def test_stale_contract_blocks_move_before_generated_copy_is_touched(self):
        with tempfile.TemporaryDirectory() as folder:
            check = create_restore_evidence(folder)
            stale = "0" * 64
            if stale == source_safety_contract_sha256():
                stale = "1" * 64

            with patch(
                "photoclean.recycle_evidence.runtime_safety_contract_sha256",
                return_value=stale,
            ):
                with self.assertRaisesRegex(RecycleVerificationError, "different release safety contract"):
                    move_restore_evidence(
                        check.manifest,
                        recycler=lambda path: Path(path).unlink(),
                    )

            self.assertTrue(check.original.exists())
            self.assertTrue(check.copy.exists())

    def test_stale_contract_blocks_restore_verification(self):
        with tempfile.TemporaryDirectory() as folder:
            recycled = prepare_restore_evidence(
                folder,
                recycler=lambda path: Path(path).unlink(),
            )
            shutil.copy2(recycled.original, recycled.copy)
            stale = "0" * 64
            if stale == source_safety_contract_sha256():
                stale = "1" * 64

            with patch(
                "photoclean.recycle_evidence.runtime_safety_contract_sha256",
                return_value=stale,
            ):
                with self.assertRaisesRegex(RecycleVerificationError, "different release safety contract"):
                    verify_restore_evidence(recycled.manifest)

            self.assertTrue(recycled.original.exists())
            self.assertTrue(recycled.copy.exists())

    def test_unbound_legacy_manifest_cannot_enter_qualified_cli_workflow(self):
        with tempfile.TemporaryDirectory() as folder:
            check = create_recycle_verification(folder)
            with self.assertRaisesRegex(RecycleVerificationError, "not bound"):
                move_restore_evidence(
                    check.manifest,
                    recycler=lambda path: Path(path).unlink(),
                )
            self.assertTrue(check.original.exists())
            self.assertTrue(check.copy.exists())


if __name__ == "__main__":
    unittest.main()
