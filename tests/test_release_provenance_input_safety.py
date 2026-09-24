import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.release_provenance import (
    _MAX_PROVENANCE_MANIFEST_BYTES,
    ProvenanceError,
    build_manifest,
    load_manifest,
    sha256_file,
)


COMMIT = "0123456789abcdef0123456789abcdef01234567"
CONTRACT = "a" * 64


class ReleaseProvenanceInputSafetyTests(unittest.TestCase):
    def _archive(self, root: Path) -> Path:
        archive = root / "SwirPhotoClean-1.0.0-Windows.zip"
        archive.write_bytes(b"PK\x03\x04stable-release-archive")
        return archive

    def test_hash_rejects_hardlinked_release_input(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = self._archive(root)
            alias = root / "archive-hardlink.zip"
            try:
                os.link(source, alias)
            except OSError as error:
                self.skipTest(f"hardlinks unavailable in test environment: {error}")

            with self.assertRaisesRegex(ProvenanceError, "must not be hardlinked"):
                sha256_file(alias)

    def test_hash_rejects_symlinked_directory_ancestry(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            real = root / "real-artifacts"
            real.mkdir()
            archive = self._archive(real)
            alias = root / "redirected-artifacts"
            try:
                alias.symlink_to(real, target_is_directory=True)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"directory symlinks unavailable in test environment: {error}")

            with self.assertRaisesRegex(
                ProvenanceError,
                "directory ancestry must not contain symlinks|junctions|reparse points",
            ):
                sha256_file(alias / archive.name)

    def test_hash_rejects_path_swap_between_lstat_and_open(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = self._archive(root)
            replacement = root / "replacement.zip"
            replacement.write_bytes(b"PK\x03\x04different-release-bytes")
            original_open = os.open
            swapped = False

            def swapping_open(path, flags, *args, **kwargs):
                nonlocal swapped
                if not swapped and Path(path) == archive:
                    swapped = True
                    os.replace(replacement, archive)
                return original_open(path, flags, *args, **kwargs)

            with patch("tools.release_provenance.os.open", side_effect=swapping_open):
                with self.assertRaisesRegex(ProvenanceError, "changed while it was being opened"):
                    sha256_file(archive)

            self.assertTrue(swapped)

    def test_manifest_reader_rejects_oversized_input_before_json_decode(self):
        with tempfile.TemporaryDirectory() as folder:
            manifest = Path(folder) / "release.provenance.json"
            manifest.write_bytes(b"{" + b" " * _MAX_PROVENANCE_MANIFEST_BYTES + b"}")

            with self.assertRaisesRegex(ProvenanceError, "too large"):
                load_manifest(manifest)

    def test_manifest_reader_rejects_symlinked_directory_ancestry(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            real = root / "real-manifests"
            real.mkdir()
            manifest = real / "release.provenance.json"
            manifest.write_text("{}\n", encoding="utf-8")
            alias = root / "redirected-manifests"
            try:
                alias.symlink_to(real, target_is_directory=True)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"directory symlinks unavailable in test environment: {error}")

            with self.assertRaisesRegex(
                ProvenanceError,
                "directory ancestry must not contain symlinks|junctions|reparse points",
            ):
                load_manifest(alias / manifest.name)

    def test_default_dangling_release_evidence_is_not_silently_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = self._archive(root)
            evidence = root / "RELEASE_EVIDENCE.json"
            missing = root / "missing-evidence.json"
            try:
                evidence.symlink_to(missing)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"symlinks unavailable in test environment: {error}")

            with patch("tools.release_provenance.DEFAULT_RELEASE_EVIDENCE", evidence):
                with self.assertRaisesRegex(
                    ProvenanceError,
                    "release evidence must not be a symlink|junction|reparse point",
                ):
                    build_manifest(
                        archive,
                        version="1.0.0",
                        git_commit=COMMIT,
                        workflow_run_id=123,
                        channel="stable",
                        safety_contract_sha256=CONTRACT,
                    )


if __name__ == "__main__":
    unittest.main()
