import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from photoclean.safety_contract import (
    ASSET_NAME,
    SAFETY_CONTRACT_FILES,
    SafetyContractError,
    build_source_safety_contract,
    runtime_safety_contract,
    validate_safety_contract,
    validate_source_safety_contract,
)


class SafetyContractTests(unittest.TestCase):
    def _source_tree(self, root: Path) -> None:
        for index, relative in enumerate(SAFETY_CONTRACT_FILES):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"fixture-{index}\n", encoding="utf-8")

    def test_contract_covers_runtime_build_release_and_gui_attestation_path(self):
        required = {
            ".github/workflows/windows.yml",
            "requirements.txt",
            "requirements-build.txt",
            "run.py",
            "photoclean/__init__.py",
            "photoclean/core.py",
            "photoclean/diagnostics.py",
            "photoclean/diagnostics_gui.py",
            "photoclean/diagnostics_plus_gui.py",
            "photoclean/recycle.py",
            "photoclean/recycle_evidence.py",
            "photoclean/release_attestation.py",
            "photoclean/release_evidence_cli.py",
            "photoclean/safety_contract.py",
            "photoclean/selftest.py",
            "photoclean/selftest_performance.py",
            "photoclean/storage.py",
            "tools/release_evidence.py",
            "tools/release_gate.py",
            "tools/release_provenance.py",
            "tools/safety_contract.py",
        }
        self.assertEqual(required - set(SAFETY_CONTRACT_FILES), set())

    def test_source_contract_is_deterministic_and_changes_with_safety_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self._source_tree(root)
            first = build_source_safety_contract(root)
            second = build_source_safety_contract(root)
            self.assertEqual(first, second)
            self.assertEqual(len(first["sha256"]), 64)
            self.assertEqual(
                [item["path"] for item in first["files"]],
                list(SAFETY_CONTRACT_FILES),
            )

            changed = root / SAFETY_CONTRACT_FILES[0]
            changed.write_text("changed safety behavior\n", encoding="utf-8")
            third = build_source_safety_contract(root)
            self.assertNotEqual(first["sha256"], third["sha256"])

    def test_build_identity_dispatch_gui_attestation_and_provenance_changes_invalidate_contract(self):
        for relative in (
            "photoclean/__init__.py",
            "photoclean/storage.py",
            "photoclean/diagnostics_gui.py",
            "photoclean/diagnostics_plus_gui.py",
            "requirements-build.txt",
            "photoclean/selftest.py",
            "tools/release_provenance.py",
        ):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                self._source_tree(root)
                before = build_source_safety_contract(root)["sha256"]
                target = root / relative
                target.write_text(target.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")
                after = build_source_safety_contract(root)["sha256"]
                self.assertNotEqual(before, after)

    def test_validation_rejects_tampered_digest_and_stale_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self._source_tree(root)
            payload = build_source_safety_contract(root)
            self.assertEqual(validate_safety_contract(payload), payload)
            self.assertEqual(validate_source_safety_contract(payload, root), payload)

            tampered = json.loads(json.dumps(payload))
            tampered["sha256"] = "0" * 64
            with self.assertRaises(SafetyContractError):
                validate_safety_contract(tampered)

            (root / SAFETY_CONTRACT_FILES[-1]).write_text("new gate\n", encoding="utf-8")
            with self.assertRaisesRegex(SafetyContractError, "stale"):
                validate_source_safety_contract(payload, root)

    def test_missing_required_source_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self._source_tree(root)
            (root / SAFETY_CONTRACT_FILES[2]).unlink()
            with self.assertRaises(SafetyContractError):
                build_source_safety_contract(root)

    def test_frozen_runtime_reads_and_validates_bundled_asset(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source"
            source.mkdir()
            self._source_tree(source)
            payload = build_source_safety_contract(source)

            bundle = root / "bundle"
            asset = bundle / "assets" / ASSET_NAME
            asset.parent.mkdir(parents=True)
            asset.write_text(json.dumps(payload), encoding="utf-8")

            with patch("photoclean.safety_contract.sys.frozen", True, create=True), patch(
                "photoclean.safety_contract.sys._MEIPASS", str(bundle), create=True
            ):
                loaded = runtime_safety_contract()
            self.assertEqual(loaded["sha256"], payload["sha256"])


if __name__ == "__main__":
    unittest.main()
