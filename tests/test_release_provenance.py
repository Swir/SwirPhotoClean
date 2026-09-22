import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.release_provenance import (
    LEGACY_SCHEMA_VERSION,
    ProvenanceError,
    build_manifest,
    sha256_file,
    verify_manifest,
    write_manifest,
)


COMMIT = "0123456789abcdef0123456789abcdef01234567"
CONTRACT = "a" * 64
OTHER_CONTRACT = "b" * 64


class ReleaseProvenanceTests(unittest.TestCase):
    def _archive(self, root: Path, name: str = "SwirPhotoClean-1.0.0-Windows.zip") -> Path:
        archive = root / name
        archive.write_bytes(b"PK\x03\x04swir-photo-clean-release-fixture")
        return archive

    def _evidence(self, root: Path) -> Path:
        evidence = root / "RELEASE_EVIDENCE.json"
        evidence.write_text(
            json.dumps(
                {
                    "kind": "windows-recycle-restore",
                    "fixture": "generated-only",
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return evidence

    def test_round_trip_binds_archive_version_commit_run_channel_contract_and_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = self._archive(root)
            evidence = self._evidence(root)
            manifest_path = root / "release.provenance.json"

            written = write_manifest(
                manifest_path,
                archive,
                version="1.0.0",
                git_commit=COMMIT.upper(),
                workflow_run_id="123456789",
                channel="stable",
                safety_contract_sha256=CONTRACT,
                release_evidence=evidence,
            )
            verified = verify_manifest(
                manifest_path,
                archive,
                expected_version="1.0.0",
                expected_commit=COMMIT,
                expected_workflow_run_id=123456789,
                expected_channel="stable",
                expected_safety_contract_sha256=CONTRACT,
                release_evidence=evidence,
            )

            self.assertEqual(written, verified)
            self.assertEqual(verified["schema"], 2)
            self.assertEqual(verified["git_commit"], COMMIT)
            self.assertEqual(verified["workflow_run_id"], "123456789")
            self.assertEqual(verified["safety_contract_sha256"], CONTRACT)
            self.assertEqual(verified["artifact"]["name"], archive.name)
            self.assertEqual(verified["artifact"]["size"], archive.stat().st_size)
            self.assertEqual(len(verified["artifact"]["sha256"]), 64)
            self.assertEqual(
                verified["release_evidence"],
                {
                    "name": evidence.name,
                    "size": evidence.stat().st_size,
                    "sha256": sha256_file(evidence),
                },
            )

    def test_tampered_archive_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = self._archive(root)
            manifest_path = root / "release.provenance.json"
            write_manifest(
                manifest_path,
                archive,
                version="1.0.0-rc.1",
                git_commit=COMMIT,
                workflow_run_id=42,
                channel="prerelease",
                safety_contract_sha256=CONTRACT,
            )
            archive.write_bytes(archive.read_bytes() + b"tampered")

            with self.assertRaisesRegex(ProvenanceError, "size mismatch|SHA-256 mismatch"):
                verify_manifest(
                    manifest_path,
                    archive,
                    expected_safety_contract_sha256=CONTRACT,
                )

    def test_tampered_release_evidence_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = self._archive(root)
            evidence = self._evidence(root)
            manifest_path = root / "release.provenance.json"
            write_manifest(
                manifest_path,
                archive,
                version="1.0.0",
                git_commit=COMMIT,
                workflow_run_id=43,
                channel="stable",
                safety_contract_sha256=CONTRACT,
                release_evidence=evidence,
            )
            evidence.write_text('{"tampered": true}\n', encoding="utf-8")

            with self.assertRaisesRegex(
                ProvenanceError,
                "release evidence size mismatch|release evidence SHA-256 mismatch",
            ):
                verify_manifest(
                    manifest_path,
                    archive,
                    expected_safety_contract_sha256=CONTRACT,
                    release_evidence=evidence,
                )

    def test_safety_contract_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = self._archive(root)
            manifest_path = root / "release.provenance.json"
            write_manifest(
                manifest_path,
                archive,
                version="1.0.0",
                git_commit=COMMIT,
                workflow_run_id=44,
                channel="stable",
                safety_contract_sha256=CONTRACT,
            )

            with self.assertRaisesRegex(ProvenanceError, "safety contract mismatch"):
                verify_manifest(
                    manifest_path,
                    archive,
                    expected_safety_contract_sha256=OTHER_CONTRACT,
                )

    def test_renamed_archive_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = self._archive(root)
            manifest_path = root / "release.provenance.json"
            write_manifest(
                manifest_path,
                archive,
                version="0.3.0",
                git_commit=COMMIT,
                workflow_run_id=7,
                channel="prerelease",
                safety_contract_sha256=CONTRACT,
            )
            renamed = root / "renamed.zip"
            archive.replace(renamed)

            with self.assertRaisesRegex(ProvenanceError, "archive name mismatch"):
                verify_manifest(
                    manifest_path,
                    renamed,
                    expected_safety_contract_sha256=CONTRACT,
                )

    def test_expected_identity_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = self._archive(root)
            manifest_path = root / "release.provenance.json"
            write_manifest(
                manifest_path,
                archive,
                version="1.0.0-rc.1",
                git_commit=COMMIT,
                workflow_run_id=99,
                channel="prerelease",
                safety_contract_sha256=CONTRACT,
            )

            with self.assertRaisesRegex(ProvenanceError, "commit mismatch"):
                verify_manifest(
                    manifest_path,
                    archive,
                    expected_commit="f" * 40,
                    expected_safety_contract_sha256=CONTRACT,
                )
            with self.assertRaisesRegex(ProvenanceError, "workflow run mismatch"):
                verify_manifest(
                    manifest_path,
                    archive,
                    expected_workflow_run_id=100,
                    expected_safety_contract_sha256=CONTRACT,
                )

    def test_schema_two_unknown_fields_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = self._archive(root)
            manifest_path = root / "release.provenance.json"
            write_manifest(
                manifest_path,
                archive,
                version="1.0.0",
                git_commit=COMMIT,
                workflow_run_id=45,
                channel="stable",
                safety_contract_sha256=CONTRACT,
            )
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload["unexpected"] = True
            manifest_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ProvenanceError, "unsupported top-level fields"):
                verify_manifest(
                    manifest_path,
                    archive,
                    expected_safety_contract_sha256=CONTRACT,
                )

    def test_legacy_schema_one_remains_verifiable_without_new_binding_expectations(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = self._archive(root)
            manifest_path = root / "legacy.provenance.json"
            payload = {
                "schema": LEGACY_SCHEMA_VERSION,
                "project": "SwirPhotoClean",
                "version": "0.3.0",
                "git_commit": COMMIT,
                "workflow_run_id": "7",
                "channel": "prerelease",
                "artifact": {
                    "name": archive.name,
                    "size": archive.stat().st_size,
                    "sha256": sha256_file(archive),
                },
            }
            manifest_path.write_text(
                json.dumps(payload, indent=2) + "\n",
                encoding="utf-8",
            )

            verified = verify_manifest(manifest_path, archive)
            self.assertEqual(verified["schema"], LEGACY_SCHEMA_VERSION)

            with self.assertRaisesRegex(ProvenanceError, "legacy provenance does not bind"):
                verify_manifest(
                    manifest_path,
                    archive,
                    expected_safety_contract_sha256=CONTRACT,
                )

    def test_auto_detects_current_contract_and_repository_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = self._archive(root)
            evidence = self._evidence(root)
            manifest_path = root / "release.provenance.json"

            with (
                patch(
                    "tools.release_provenance._current_safety_contract_sha256",
                    return_value=CONTRACT,
                ),
                patch(
                    "tools.release_provenance.DEFAULT_RELEASE_EVIDENCE",
                    evidence,
                ),
            ):
                written = write_manifest(
                    manifest_path,
                    archive,
                    version="1.0.0",
                    git_commit=COMMIT,
                    workflow_run_id=46,
                    channel="stable",
                )
                verified = verify_manifest(manifest_path, archive)

            self.assertEqual(written, verified)
            self.assertEqual(verified["safety_contract_sha256"], CONTRACT)
            self.assertEqual(
                verified["release_evidence"]["sha256"],
                sha256_file(evidence),
            )

    def test_malformed_manifest_and_inputs_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = self._archive(root)
            manifest_path = root / "release.provenance.json"

            with self.assertRaises(ProvenanceError):
                build_manifest(
                    archive,
                    version="1.0",
                    git_commit=COMMIT,
                    workflow_run_id=1,
                    channel="stable",
                    safety_contract_sha256=CONTRACT,
                )
            with self.assertRaises(ProvenanceError):
                build_manifest(
                    archive,
                    version="1.0.0",
                    git_commit="deadbeef",
                    workflow_run_id=1,
                    channel="stable",
                    safety_contract_sha256=CONTRACT,
                )
            with self.assertRaisesRegex(ProvenanceError, "64 lowercase hexadecimal"):
                build_manifest(
                    archive,
                    version="1.0.0",
                    git_commit=COMMIT,
                    workflow_run_id=1,
                    channel="stable",
                    safety_contract_sha256="A" * 64,
                )

            manifest_path.write_text(json.dumps({"schema": 999}), encoding="utf-8")
            with self.assertRaisesRegex(ProvenanceError, "unsupported provenance schema"):
                verify_manifest(manifest_path, archive)


if __name__ == "__main__":
    unittest.main()
