from __future__ import annotations

import unittest
from unittest import mock

from photoclean import modern_theme


class _Style:
    def __init__(self):
        self.configured = {}
        self.mapped = {}

    def configure(self, name, **values):
        self.configured.setdefault(name, {}).update(values)

    def map(self, name, **values):
        self.mapped.setdefault(name, {}).update(values)


class _Widget:
    def __init__(self, widget_class="Tk", *, relief="flat", children=None):
        self.widget_class = widget_class
        self.relief = relief
        self.children = list(children or [])
        self.configured = {}
        self.options = []
        self.bindings = []
        self._swir_modern_theme_tracking = False

    def winfo_class(self):
        return self.widget_class

    def winfo_children(self):
        return list(self.children)

    def cget(self, key):
        if key == "relief":
            return self.relief
        raise KeyError(key)

    def configure(self, **values):
        self.configured.update(values)
        if "relief" in values:
            self.relief = values["relief"]

    def option_add(self, pattern, value):
        self.options.append((pattern, value))

    def bind_all(self, sequence, callback, add=None):
        self.bindings.append((sequence, callback, add))


class ModernThemeTests(unittest.TestCase):
    def test_configure_ttk_styles_flattens_buttons_and_keeps_accent(self):
        style = _Style()
        modern_theme.configure_ttk_styles(style)

        self.assertEqual(style.configured["TButton"]["relief"], "flat")
        self.assertEqual(style.configured["TButton"]["borderwidth"], 1)
        self.assertEqual(
            style.configured["Accent.TButton"]["background"],
            modern_theme.ACCENT,
        )
        self.assertEqual(style.configured["Treeview"]["rowheight"], 30)
        self.assertIn("selected", [state for state, _ in style.mapped["Treeview"]["background"]])

    def test_polish_widget_flattens_legacy_preview_frame(self):
        frame = _Widget("Frame", relief="raised")
        modern_theme.polish_widget(frame)

        self.assertEqual(frame.configured["relief"], "flat")
        self.assertEqual(frame.configured["bd"], 0)
        self.assertEqual(frame.configured["highlightthickness"], 1)
        self.assertEqual(
            frame.configured["highlightbackground"],
            modern_theme.BORDER,
        )

    def test_install_modern_theme_is_idempotent_but_reapplies_styles(self):
        root = _Widget("Tk")
        style = _Style()

        with mock.patch.object(modern_theme.ttk, "Style", return_value=style) as style_factory:
            modern_theme.install_modern_theme(root)
            modern_theme.install_modern_theme(root)

        self.assertEqual(len(root.bindings), 1)
        self.assertEqual(root.bindings[0][0], "<Map>")
        self.assertEqual(root.bindings[0][2], "+")
        self.assertEqual(style_factory.call_count, 2)
        self.assertTrue(root._swir_modern_theme_tracking)
        self.assertIn(("*Menu.selectColor", modern_theme.ACCENT), root.options)

    def test_map_tracking_polishes_widgets_created_later(self):
        root = _Widget("Tk")
        style = _Style()
        with mock.patch.object(modern_theme.ttk, "Style", return_value=style):
            modern_theme.install_modern_theme(root)

        preview = _Widget("Frame", relief="raised")
        callback = root.bindings[0][1]
        callback(type("Event", (), {"widget": preview})())

        self.assertEqual(preview.configured["relief"], "flat")
        self.assertEqual(preview.configured["bd"], 0)


if __name__ == "__main__":
    unittest.main()
