import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from photoclean.recycle import (
    _file_identity,
    _require_no_reparse_ancestry,
    _require_regular_file_target,
    _require_same_file_content,
    _require_same_regular_file_target,
    _stable_file_sha256,
)


class RecyclePathSafetyTests(unittest.TestCase):
    def test_regular_path_is_preserved_without_resolving_links(self):
        with tempfile.TemporaryDirectory() as folder:
            candidate = Path(folder) / "photo.png"
            candidate.write_bytes(b"safe")

            checked = _require_no_reparse_ancestry(candidate)

            self.assertEqual(checked, candidate.absolute())

    def test_regular_file_target_is_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            candidate = Path(folder) / "photo.png"
            candidate.write_bytes(b"safe")

            checked = _require_regular_file_target(candidate)

            self.assertEqual(checked, candidate.absolute())

    def test_directory_replacement_is_rejected_before_shell_recycle(self):
        with tempfile.TemporaryDirectory() as folder:
            candidate = Path(folder) / "photo.png"
            candidate.mkdir()

            with self.assertRaisesRegex(OSError, "Cel Kosza nie jest zwykłym plikiem"):
                _require_regular_file_target(candidate)

    def test_identity_guard_accepts_unchanged_regular_file(self):
        with tempfile.TemporaryDirectory() as folder:
            candidate = Path(folder) / "photo.png"
            candidate.write_bytes(b"safe")
            expected = _file_identity(candidate)

            checked = _require_same_regular_file_target(candidate, expected)

            self.assertEqual(checked, candidate.absolute())

    def test_identity_guard_rejects_content_mutation_before_shell_dispatch(self):
        with tempfile.TemporaryDirectory() as folder:
            candidate = Path(folder) / "photo.png"
            candidate.write_bytes(b"safe")
            expected = _file_identity(candidate)
            candidate.write_bytes(b"changed-and-longer")

            with self.assertRaisesRegex(OSError, "Plik zmienił się"):
                _require_same_regular_file_target(candidate, expected)

    def test_identity_guard_rejects_path_replacement_before_shell_dispatch(self):
        with tempfile.TemporaryDirectory() as folder:
            candidate = Path(folder) / "photo.png"
            candidate.write_bytes(b"original")
            expected = _file_identity(candidate)
            candidate.unlink()
            candidate.write_bytes(b"replacement-with-different-size")

            with self.assertRaisesRegex(OSError, "Plik zmienił się"):
                _require_same_regular_file_target(candidate, expected)

    def test_stable_digest_accepts_unchanged_regular_file(self):
        with tempfile.TemporaryDirectory() as folder:
            candidate = Path(folder) / "photo.png"
            candidate.write_bytes(b"safe")
            expected_identity = _file_identity(candidate)

            digest = _stable_file_sha256(candidate, expected_identity)

            self.assertEqual(digest, hashlib.sha256(b"safe").hexdigest())

    def test_stable_digest_rejects_different_open_handle(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            candidate = (root / "photo.png").absolute()
            decoy = (root / "decoy.png").absolute()
            candidate.write_bytes(b"safe")
            decoy.write_bytes(b"evil")
            expected_identity = _file_identity(candidate)
            original_open = Path.open

            def redirected_open(path, *args, **kwargs):
                if Path(path) == candidate:
                    return original_open(decoy, *args, **kwargs)
                return original_open(path, *args, **kwargs)

            with patch.object(Path, "open", redirected_open):
                with self.assertRaisesRegex(OSError, "Plik zmienił się"):
                    _stable_file_sha256(candidate, expected_identity)

    def test_content_guard_rejects_digest_mismatch_even_if_metadata_guard_accepts(self):
        with tempfile.TemporaryDirectory() as folder:
            candidate = (Path(folder) / "photo.png").absolute()
            candidate.write_bytes(b"safe")
            expected_identity = _file_identity(candidate)
            expected_digest = hashlib.sha256(b"safe").hexdigest()
            candidate.write_bytes(b"evil")  # same length: exercise the content signal itself

            with patch(
                "photoclean.recycle._require_same_regular_file_target",
                return_value=candidate,
            ):
                with self.assertRaisesRegex(OSError, "Zawartość pliku zmieniła się"):
                    _require_same_file_content(
                        candidate,
                        expected_identity,
                        expected_digest,
                    )

    def test_missing_target_fails_closed_before_shell_recycle(self):
        with tempfile.TemporaryDirectory() as folder:
            candidate = Path(folder) / "missing.png"

            with self.assertRaisesRegex(
                OSError,
                "Nie można bezpiecznie sprawdzić ścieżki przed Koszem",
            ):
                _require_no_reparse_ancestry(candidate)

    def test_unreadable_path_metadata_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            candidate = Path(folder) / "photo.png"
            candidate.write_bytes(b"safe")

            with patch.object(
                Path,
                "lstat",
                side_effect=PermissionError("metadata denied"),
            ):
                with self.assertRaisesRegex(OSError, "metadata denied"):
                    _require_no_reparse_ancestry(candidate)

    def test_reparse_target_is_rejected_before_recycle(self):
        with tempfile.TemporaryDirectory() as folder:
            candidate = (Path(folder) / "RECYCLE-ME.png").absolute()
            candidate.write_bytes(b"fixture")

            with patch(
                "photoclean.recycle._is_link_or_reparse",
                side_effect=lambda path: path == candidate,
            ):
                with self.assertRaisesRegex(OSError, "Dowiązanie w ścieżce"):
                    _require_no_reparse_ancestry(candidate)

    def test_reparse_parent_is_rejected_before_recycle(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder).absolute()
            linked_parent = base / "linked-library"
            linked_parent.mkdir()
            candidate = linked_parent / "photo.png"
            candidate.write_bytes(b"fixture")

            with patch(
                "photoclean.recycle._is_link_or_reparse",
                side_effect=lambda path: path == linked_parent,
            ):
                with self.assertRaisesRegex(OSError, str(linked_parent).replace("\\", "\\\\")):
                    _require_no_reparse_ancestry(candidate)

    def test_check_walks_all_the_way_to_filesystem_root(self):
        with tempfile.TemporaryDirectory() as folder:
            candidate = (Path(folder) / "photo.png").absolute()
            candidate.write_bytes(b"fixture")
            visited = []

            def record(path):
                visited.append(path)
                return False

            with patch("photoclean.recycle._is_link_or_reparse", side_effect=record):
                _require_no_reparse_ancestry(candidate)

            self.assertEqual(visited[0], candidate)
            self.assertEqual(visited[-1], candidate.anchor and Path(candidate.anchor) or visited[-1])
            self.assertGreaterEqual(len(visited), 2)


if __name__ == "__main__":
    unittest.main()
