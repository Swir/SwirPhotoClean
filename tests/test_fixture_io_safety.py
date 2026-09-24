import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from photoclean import diagnostics
from photoclean.fixture_io import (
    hardened_matches_expected_file,
    hardened_require_expected_file,
    install_hardened_fixture_io,
)


class FixtureIOSafetyTests(unittest.TestCase):
    def test_generated_fixture_is_hashed_from_stable_handle(self):
        with tempfile.TemporaryDirectory() as folder:
            check = diagnostics.create_recycle_verification(folder)
            hardened_require_expected_file(
                check.original,
                check.digest,
                "Original verification file",
                check.file_size,
            )
            matches, problem = hardened_matches_expected_file(
                check.copy,
                check.digest,
                check.file_size,
            )
            self.assertTrue(matches)
            self.assertIsNone(problem)

    def test_hardlinked_fixture_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            check = diagnostics.create_recycle_verification(folder)
            alias = Path(folder) / "fixture-hardlink.png"
            try:
                os.link(check.original, alias)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"hardlinks unavailable: {error}")

            with self.assertRaisesRegex(
                diagnostics.RecycleVerificationError,
                "must not be hardlinked",
            ):
                hardened_require_expected_file(
                    check.original,
                    check.digest,
                    "Original verification file",
                    check.file_size,
                )

    def test_fixture_path_swap_between_lstat_and_open_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            check = diagnostics.create_recycle_verification(folder)
            original = check.original
            replacement = Path(folder) / "replacement.png"
            shutil.copy2(original, replacement)
            original_open = os.open
            swapped = False

            def swap_then_open(path, flags):
                nonlocal swapped
                if not swapped and Path(path) == original:
                    swapped = True
                    backup = Path(folder) / "original-before-swap.png"
                    original.replace(backup)
                    replacement.replace(original)
                return original_open(path, flags)

            with mock.patch(
                "photoclean.fixture_io.os.open",
                side_effect=swap_then_open,
            ):
                with self.assertRaisesRegex(
                    diagnostics.RecycleVerificationError,
                    "changed while it was being opened",
                ):
                    hardened_require_expected_file(
                        original,
                        check.digest,
                        "Original verification file",
                        check.file_size,
                    )

    def test_move_rejects_hardlinked_copy_before_recycler_runs(self):
        with tempfile.TemporaryDirectory() as folder:
            check = diagnostics.create_recycle_verification(folder)
            alias = Path(folder) / "copy-hardlink.png"
            try:
                os.link(check.copy, alias)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"hardlinks unavailable: {error}")

            old_require = diagnostics._require_expected_file
            old_matches = diagnostics._matches_expected_file
            recycler = mock.Mock()
            try:
                install_hardened_fixture_io()
                with self.assertRaisesRegex(
                    diagnostics.RecycleVerificationError,
                    "must not be hardlinked",
                ):
                    diagnostics.move_generated_copy_to_recycle(
                        check,
                        recycler=recycler,
                    )
                recycler.assert_not_called()
                self.assertTrue(check.original.is_file())
                self.assertTrue(check.copy.is_file())
            finally:
                diagnostics._require_expected_file = old_require
                diagnostics._matches_expected_file = old_matches

    def test_install_rebinds_fixture_validators(self):
        old_require = diagnostics._require_expected_file
        old_matches = diagnostics._matches_expected_file
        try:
            install_hardened_fixture_io()
            self.assertIs(
                diagnostics._require_expected_file,
                hardened_require_expected_file,
            )
            self.assertIs(
                diagnostics._matches_expected_file,
                hardened_matches_expected_file,
            )
        finally:
            diagnostics._require_expected_file = old_require
            diagnostics._matches_expected_file = old_matches


if __name__ == "__main__":
    unittest.main()
