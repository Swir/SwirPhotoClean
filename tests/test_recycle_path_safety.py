import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from photoclean.recycle import _require_no_reparse_ancestry, _require_regular_file_target


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
