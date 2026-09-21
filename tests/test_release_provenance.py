import json
import tempfile
import unittest
from pathlib import Path

from tools.release_provenance import (
    ProvenanceError,
    build_manifest,
    verify_manifest,
    write_manifest,
)


COMMIT = "0123456789abcdef0123456789abcdef01234567"


class ReleaseProvenanceTests(unittest.TestCase):
    def _archive(self, root: Path, name: str = "SwirPhotoClean-1.0.0-Windows.zip") -> Path:
        archive = root / name
        archive.write_bytes(b"PK\x03\x04swir-photo-clean-release-fixture")
        return archive

    def test_round_trip_binds_archive_version_commit_run_and_channel(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = self._archive(root)
            manifest_path = root / "release.provenance.json"

            written = write_manifest(
                manifest_path,
                archive,
                version="1.0.0",
                git_commit=COMMIT.upper(),
                workflow_run_id="123456789",
                channel="stable",
            )
            verified = verify_manifest(
                manifest_path,
                archive,
                expected_version="1.0.0",
                expected_commit=COMMIT,
                expected_workflow_run_id=123456789,
                expected_channel="stable",
            )

            self.assertEqual(written, verified)
            self.assertEqual(verified["git_commit"], COMMIT)
            self.assertEqual(verified["workflow_run_id"], "123456789")
            self.assertEqual(verified["artifact"]["name"], archive.name)
            self.assertEqual(verified["artifact"]["size"], archive.stat().st_size)
            self.assertEqual(len(verified["artifact"]["sha256"]), 64)

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
            )
            archive.write_bytes(archive.read_bytes() + b"tampered")

            with self.assertRaisesRegex(ProvenanceError, "size mismatch|SHA-256 mismatch"):
                verify_manifest(manifest_path, archive)

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
            )
            renamed = root / "renamed.zip"
            archive.replace(renamed)

            with self.assertRaisesRegex(ProvenanceError, "archive name mismatch"):
                verify_manifest(manifest_path, renamed)

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
            )

            with self.assertRaisesRegex(ProvenanceError, "commit mismatch"):
                verify_manifest(
                    manifest_path,
                    archive,
                    expected_commit="f" * 40,
                )
            with self.assertRaisesRegex(ProvenanceError, "workflow run mismatch"):
                verify_manifest(
                    manifest_path,
                    archive,
                    expected_workflow_run_id=100,
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
                )
            with self.assertRaises(ProvenanceError):
                build_manifest(
                    archive,
                    version="1.0.0",
                    git_commit="deadbeef",
                    workflow_run_id=1,
                    channel="stable",
                )

            manifest_path.write_text(json.dumps({"schema": 999}), encoding="utf-8")
            with self.assertRaisesRegex(ProvenanceError, "unsupported provenance schema"):
                verify_manifest(manifest_path, archive)


if __name__ == "__main__":
    unittest.main()
