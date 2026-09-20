import tempfile
import unittest
from pathlib import Path
from unittest import mock

from photoclean.storage import (
    PORTABLE_DATA_DIR,
    PORTABLE_MARKER,
    PORTABLE_SETTINGS_FILE,
    PORTABLE_SWITCH,
    resolve_runtime_storage,
)


class RuntimeStorageTests(unittest.TestCase):
    def test_normal_launch_keeps_arguments_and_user_storage(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            runtime = resolve_runtime_storage(["--example"], app_dir=root)
        self.assertEqual(runtime.argv, ("--example",))
        self.assertFalse(runtime.portable)
        self.assertIsNone(runtime.settings_path)
        self.assertIsNone(runtime.source)

    def test_portable_switch_is_removed_before_command_dispatch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            runtime = resolve_runtime_storage(
                [PORTABLE_SWITCH, "--self-test", "report.json"],
                app_dir=root,
            )
        self.assertEqual(runtime.argv, ("--self-test", "report.json"))
        self.assertTrue(runtime.portable)
        self.assertEqual(runtime.source, "argument")
        self.assertEqual(
            runtime.settings_path,
            root.resolve() / PORTABLE_DATA_DIR / PORTABLE_SETTINGS_FILE,
        )

    def test_marker_enables_portable_mode_without_cli_switch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / PORTABLE_MARKER).write_text("", encoding="utf-8")
            runtime = resolve_runtime_storage([], app_dir=root)
        self.assertTrue(runtime.portable)
        self.assertEqual(runtime.source, "marker")
        self.assertEqual(
            runtime.settings_path,
            root.resolve() / PORTABLE_DATA_DIR / PORTABLE_SETTINGS_FILE,
        )

    def test_explicit_switch_wins_when_marker_also_exists(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / PORTABLE_MARKER).write_text("", encoding="utf-8")
            runtime = resolve_runtime_storage([PORTABLE_SWITCH], app_dir=root)
        self.assertTrue(runtime.portable)
        self.assertEqual(runtime.source, "argument")

    def test_resolver_does_not_create_data_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            runtime = resolve_runtime_storage([PORTABLE_SWITCH], app_dir=root)
            self.assertFalse((root / PORTABLE_DATA_DIR).exists())
            self.assertFalse(runtime.settings_path.exists())

    def test_application_directory_is_injectable_without_touching_sys_frozen(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with mock.patch("sys.argv", ["run.py", PORTABLE_SWITCH]):
                runtime = resolve_runtime_storage(app_dir=root)
        self.assertTrue(runtime.portable)
        self.assertEqual(runtime.app_dir, root.resolve())


if __name__ == "__main__":
    unittest.main()
