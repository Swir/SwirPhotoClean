from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from photoclean import windows_ui


class _TrackedWindow:
    def __init__(self, top=None):
        self._top = self if top is None else top
        self.bindings = []
        self._swir_windows_chrome_tracking = False

    def winfo_toplevel(self):
        return self._top

    def bind_all(self, sequence, callback, add=None):
        self.bindings.append((sequence, callback, add))


class WindowsUiTests(unittest.TestCase):
    def test_non_windows_dpi_bootstrap_is_noop(self):
        with mock.patch.object(windows_ui.os, "name", "posix"):
            self.assertEqual(windows_ui.configure_process_dpi_awareness(), "not-windows")

    def test_prefers_per_monitor_v2(self):
        context = mock.Mock(return_value=1)
        shcore = mock.Mock()
        fake = SimpleNamespace(
            user32=SimpleNamespace(SetProcessDpiAwarenessContext=context),
            shcore=SimpleNamespace(SetProcessDpiAwareness=shcore),
        )
        with (
            mock.patch.object(windows_ui.os, "name", "nt"),
            mock.patch.object(windows_ui.ctypes, "windll", fake, create=True),
        ):
            self.assertEqual(
                windows_ui.configure_process_dpi_awareness(),
                "per-monitor-v2",
            )
        context.assert_called_once()
        shcore.assert_not_called()

    def test_falls_back_to_shcore_per_monitor(self):
        context = mock.Mock(return_value=0)
        shcore = mock.Mock(return_value=0)
        legacy = mock.Mock()
        fake = SimpleNamespace(
            user32=SimpleNamespace(
                SetProcessDpiAwarenessContext=context,
                SetProcessDPIAware=legacy,
            ),
            shcore=SimpleNamespace(SetProcessDpiAwareness=shcore),
        )
        with (
            mock.patch.object(windows_ui.os, "name", "nt"),
            mock.patch.object(windows_ui.ctypes, "windll", fake, create=True),
        ):
            self.assertEqual(
                windows_ui.configure_process_dpi_awareness(),
                "per-monitor",
            )
        shcore.assert_called_once_with(2)
        legacy.assert_not_called()

    def test_falls_back_to_legacy_system_dpi(self):
        context = mock.Mock(return_value=0)
        shcore = mock.Mock(return_value=-1)
        legacy = mock.Mock(return_value=1)
        fake = SimpleNamespace(
            user32=SimpleNamespace(
                SetProcessDpiAwarenessContext=context,
                SetProcessDPIAware=legacy,
            ),
            shcore=SimpleNamespace(SetProcessDpiAwareness=shcore),
        )
        with (
            mock.patch.object(windows_ui.os, "name", "nt"),
            mock.patch.object(windows_ui.ctypes, "windll", fake, create=True),
        ):
            self.assertEqual(
                windows_ui.configure_process_dpi_awareness(),
                "system",
            )
        legacy.assert_called_once_with()

    def test_dark_titlebar_falls_back_to_legacy_attribute(self):
        set_attribute = mock.Mock(side_effect=[1, 0, 0])
        fake = SimpleNamespace(
            dwmapi=SimpleNamespace(DwmSetWindowAttribute=set_attribute)
        )
        root = mock.Mock()
        root.winfo_id.return_value = 4242
        with (
            mock.patch.object(windows_ui.os, "name", "nt"),
            mock.patch.object(windows_ui.ctypes, "windll", fake, create=True),
        ):
            self.assertTrue(windows_ui.apply_windows_chrome(root))
        root.update_idletasks.assert_called_once_with()
        self.assertEqual(set_attribute.call_args_list[0].args[1], 20)
        self.assertEqual(set_attribute.call_args_list[1].args[1], 19)
        self.assertEqual(set_attribute.call_args_list[2].args[1], 33)

    def test_dark_titlebar_is_noop_off_windows(self):
        root = mock.Mock()
        with mock.patch.object(windows_ui.os, "name", "posix"):
            self.assertFalse(windows_ui.apply_windows_chrome(root))
        root.update_idletasks.assert_not_called()

    def test_chrome_tracking_styles_future_toplevels_once(self):
        root = _TrackedWindow()
        child = _TrackedWindow(top=root)
        feature_window = _TrackedWindow()

        with (
            mock.patch.object(windows_ui.os, "name", "nt"),
            mock.patch.object(windows_ui, "apply_windows_chrome", return_value=True) as apply,
        ):
            self.assertTrue(windows_ui.install_windows_chrome_tracking(root))
            self.assertEqual(len(root.bindings), 1)
            self.assertEqual(root.bindings[0][0], "<Map>")
            self.assertEqual(root.bindings[0][2], "+")

            callback = root.bindings[0][1]
            callback(SimpleNamespace(widget=child))
            self.assertEqual(apply.call_count, 1)

            callback(SimpleNamespace(widget=feature_window))
            self.assertEqual(apply.call_count, 2)
            apply.assert_called_with(feature_window)

            # Re-installing after a language rebuild must not stack callbacks.
            self.assertTrue(windows_ui.install_windows_chrome_tracking(root))
            self.assertEqual(len(root.bindings), 1)
            self.assertEqual(apply.call_count, 3)

    def test_chrome_tracking_is_noop_off_windows(self):
        root = _TrackedWindow()
        with (
            mock.patch.object(windows_ui.os, "name", "posix"),
            mock.patch.object(windows_ui, "apply_windows_chrome") as apply,
        ):
            self.assertFalse(windows_ui.install_windows_chrome_tracking(root))
        self.assertEqual(root.bindings, [])
        apply.assert_not_called()


if __name__ == "__main__":
    unittest.main()
