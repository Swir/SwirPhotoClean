import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.release_provenance import (
    ProvenanceError,
    load_manifest,
    write_manifest,
)


COMMIT = "0123456789abcdef0123456789abcdef01234567"
CONTRACT = "a" * 64


class ReleaseProvenanceOutputSafetyTests(unittest.TestCase):
    def _archive(self, root: Path) -> Path:
        archive = root / "SwirPhotoClean-1.0.0-Windows.zip"
        archive.write_bytes(b"PK\x03\x04stable-release-archive")
        return archive

    def _write(self, root: Path, output: Path):
        return write_manifest(
            output,
            self._archive(root),
            version="1.0.0-rc.1",
            git_commit=COMMIT,
            workflow_run_id=260,
            channel="prerelease",
            safety_contract_sha256=CONTRACT,
        )

    def test_nested_output_is_written_atomically_and_round_trips(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "generated" / "release.provenance.json"

            written = self._write(root, output)

            self.assertEqual(load_manifest(output), written)
            self.assertEqual([], list(output.parent.glob(f".{output.name}.*.tmp")))

    def test_existing_safe_regular_output_can_be_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "release.provenance.json"
            output.write_text("{}\n", encoding="utf-8")

            written = self._write(root, output)

            self.assertEqual(load_manifest(output), written)

    def test_symlink_output_is_rejected_without_touching_target(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / "target.json"
            target.write_bytes(b"do-not-touch")
            output = root / "release.provenance.json"
            try:
                output.symlink_to(target)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"symlinks unavailable in test environment: {error}")

            with self.assertRaisesRegex(
                ProvenanceError,
                "provenance output must not be a symlink|junction|reparse point",
            ):
                self._write(root, output)

            self.assertEqual(target.read_bytes(), b"do-not-touch")

    def test_hardlinked_output_is_rejected_without_touching_peer(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            peer = root / "peer.json"
            peer.write_bytes(b"do-not-touch")
            output = root / "release.provenance.json"
            try:
                os.link(peer, output)
            except OSError as error:
                self.skipTest(f"hardlinks unavailable in test environment: {error}")

            with self.assertRaisesRegex(ProvenanceError, "provenance output must not be hardlinked"):
                self._write(root, output)

            self.assertEqual(peer.read_bytes(), b"do-not-touch")

    def test_symlinked_output_ancestry_is_rejected_before_directory_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            real = root / "real-output"
            real.mkdir()
            alias = root / "redirected-output"
            try:
                alias.symlink_to(real, target_is_directory=True)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"directory symlinks unavailable in test environment: {error}")
            output = alias / "nested" / "release.provenance.json"

            with self.assertRaisesRegex(
                ProvenanceError,
                "provenance output directory ancestry must not contain symlinks|junctions|reparse points",
            ):
                self._write(root, output)

            self.assertFalse((real / "nested").exists())

    def test_destination_swap_while_staging_is_rejected_and_attacker_file_survives(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "release.provenance.json"
            attacker = b'{"attacker": true}\n'
            real_mkstemp = tempfile.mkstemp

            def swapping_mkstemp(*args, **kwargs):
                descriptor, name = real_mkstemp(*args, **kwargs)
                output.write_bytes(attacker)
                return descriptor, name

            with patch(
                "tools.release_provenance.tempfile.mkstemp",
                side_effect=swapping_mkstemp,
            ):
                with self.assertRaisesRegex(
                    ProvenanceError,
                    "provenance output changed while validated bytes were staged",
                ):
                    self._write(root, output)

            self.assertEqual(output.read_bytes(), attacker)
            self.assertEqual([], list(root.glob(f".{output.name}.*.tmp")))


if __name__ == "__main__":
    unittest.main()
