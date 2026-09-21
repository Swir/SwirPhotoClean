"""Modern electric-cyan desktop theme helpers for the final Windows UI.

The base application still owns layout and behavior. This module only refines
visual presentation and applies the same treatment to widgets created later by
feature windows or a language rebuild.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .gui import ACCENT, BG, MUTED, PANEL, TEXT

SURFACE = "#111b2d"
SURFACE_HOVER = "#1a2b43"
SURFACE_ACTIVE = "#223a58"
BORDER = "#29415f"
BORDER_FOCUS = "#4c7da2"
DISABLED_TEXT = "#6f8199"


def configure_ttk_styles(style: ttk.Style) -> None:
    """Apply the final flat Windows-11-inspired ttk styling."""

    style.configure(".", font=("Segoe UI", 10), background=BG, foreground=TEXT)
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Muted.TLabel", background=BG, foreground=MUTED)
    style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 22, "bold"))

    style.configure(
        "TButton",
        background=SURFACE,
        foreground=TEXT,
        padding=(12, 7),
        borderwidth=1,
        relief="flat",
        bordercolor=BORDER,
        lightcolor=SURFACE,
        darkcolor=SURFACE,
    )
    style.map(
        "TButton",
        background=[
            ("disabled", PANEL),
            ("pressed", SURFACE_ACTIVE),
            ("active", SURFACE_HOVER),
        ],
        foreground=[("disabled", DISABLED_TEXT)],
        bordercolor=[
            ("focus", BORDER_FOCUS),
            ("active", BORDER_FOCUS),
            ("disabled", BORDER),
        ],
        lightcolor=[
            ("pressed", SURFACE_ACTIVE),
            ("active", SURFACE_HOVER),
        ],
        darkcolor=[
            ("pressed", SURFACE_ACTIVE),
            ("active", SURFACE_HOVER),
        ],
    )

    style.configure(
        "Accent.TButton",
        background=ACCENT,
        foreground=BG,
        font=("Segoe UI", 10, "bold"),
        padding=(13, 7),
        borderwidth=1,
        relief="flat",
        bordercolor=ACCENT,
        lightcolor=ACCENT,
        darkcolor=ACCENT,
    )
    style.map(
        "Accent.TButton",
        background=[
            ("disabled", PANEL),
            ("pressed", "#43cdb8"),
            ("active", "#78f3df"),
        ],
        foreground=[("disabled", DISABLED_TEXT)],
        bordercolor=[
            ("disabled", BORDER),
            ("focus", "#a4fff0"),
            ("active", "#a4fff0"),
        ],
        lightcolor=[
            ("pressed", "#43cdb8"),
            ("active", "#78f3df"),
        ],
        darkcolor=[
            ("pressed", "#43cdb8"),
            ("active", "#78f3df"),
        ],
    )

    style.configure(
        "Treeview",
        background=PANEL,
        fieldbackground=PANEL,
        foreground=TEXT,
        rowheight=30,
        borderwidth=0,
        relief="flat",
    )
    style.configure(
        "Treeview.Heading",
        background=SURFACE,
        foreground=MUTED,
        font=("Segoe UI", 9, "bold"),
        padding=(8, 7),
        borderwidth=0,
        relief="flat",
    )
    style.map(
        "Treeview",
        background=[("selected", "#244e6c")],
        foreground=[("selected", "#ffffff")],
    )
    style.map(
        "Treeview.Heading",
        background=[("active", SURFACE_HOVER)],
        foreground=[("active", TEXT)],
    )

    style.configure(
        "TCombobox",
        background=SURFACE,
        fieldbackground=PANEL,
        foreground=TEXT,
        arrowcolor=ACCENT,
        padding=(7, 5),
        borderwidth=1,
        relief="flat",
    )
    style.map(
        "TCombobox",
        fieldbackground=[
            ("readonly", PANEL),
            ("disabled", BG),
        ],
        foreground=[
            ("readonly", TEXT),
            ("disabled", DISABLED_TEXT),
        ],
        selectbackground=[("readonly", PANEL)],
        selectforeground=[("readonly", TEXT)],
        bordercolor=[
            ("focus", BORDER_FOCUS),
            ("active", BORDER_FOCUS),
        ],
    )

    style.configure("TCheckbutton", background=BG, foreground=TEXT, padding=(4, 3))
    style.map(
        "TCheckbutton",
        background=[("active", BG)],
        foreground=[("disabled", DISABLED_TEXT)],
    )

    style.configure(
        "TEntry",
        fieldbackground=PANEL,
        foreground=TEXT,
        padding=(7, 5),
        borderwidth=1,
        relief="flat",
    )
    style.map("TEntry", bordercolor=[("focus", BORDER_FOCUS)])

    style.configure(
        "Horizontal.TProgressbar",
        background=ACCENT,
        troughcolor=SURFACE,
        borderwidth=0,
        thickness=6,
    )
    style.configure(
        "Vertical.TScrollbar",
        background=SURFACE_HOVER,
        troughcolor=BG,
        bordercolor=BG,
        arrowcolor=MUTED,
        borderwidth=0,
        relief="flat",
    )
    style.configure(
        "Horizontal.TScrollbar",
        background=SURFACE_HOVER,
        troughcolor=BG,
        bordercolor=BG,
        arrowcolor=MUTED,
        borderwidth=0,
        relief="flat",
    )
    style.map(
        "Vertical.TScrollbar",
        background=[("active", BORDER_FOCUS), ("pressed", ACCENT)],
    )
    style.map(
        "Horizontal.TScrollbar",
        background=[("active", BORDER_FOCUS), ("pressed", ACCENT)],
    )

    style.configure("TNotebook", background=BG, borderwidth=0)
    style.configure(
        "TNotebook.Tab",
        background=SURFACE,
        foreground=MUTED,
        padding=(12, 7),
        borderwidth=0,
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", SURFACE_ACTIVE), ("active", SURFACE_HOVER)],
        foreground=[("selected", TEXT), ("active", TEXT)],
    )
    style.configure("TLabelframe", background=BG, foreground=TEXT, borderwidth=1, relief="flat")
    style.configure("TLabelframe.Label", background=BG, foreground=MUTED)


def _safe_configure(widget, **values) -> None:
    try:
        widget.configure(**values)
    except (AttributeError, tk.TclError):
        pass


def polish_widget(widget) -> None:
    """Flatten legacy Tk widget chrome without changing widget behavior."""

    try:
        widget_class = widget.winfo_class()
    except (AttributeError, tk.TclError):
        return

    if widget_class in {"Tk", "Toplevel"}:
        _safe_configure(widget, bg=BG)
        return

    if widget_class in {"Frame", "Labelframe"}:
        try:
            relief = str(widget.cget("relief"))
        except (AttributeError, tk.TclError):
            relief = ""
        if relief in {"raised", "sunken", "ridge", "groove"}:
            _safe_configure(
                widget,
                relief="flat",
                bd=0,
                highlightthickness=1,
                highlightbackground=BORDER,
                highlightcolor=BORDER_FOCUS,
            )
        return

    if widget_class == "Listbox":
        _safe_configure(
            widget,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=BORDER_FOCUS,
            activestyle="none",
        )
        return

    if widget_class == "Text":
        _safe_configure(
            widget,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=BORDER_FOCUS,
        )


def polish_widget_tree(root) -> None:
    """Polish existing Tk widgets, including feature-window descendants."""

    stack = [root]
    while stack:
        widget = stack.pop()
        polish_widget(widget)
        try:
            stack.extend(widget.winfo_children())
        except (AttributeError, tk.TclError):
            continue


def apply_modern_theme(root) -> None:
    """Apply ttk styles and lightweight Tk-widget polish to an existing UI."""

    configure_ttk_styles(ttk.Style(root))
    _safe_configure(root, bg=BG)
    for pattern, value in (
        ("*tearOff", False),
        ("*Menu.background", SURFACE),
        ("*Menu.foreground", TEXT),
        ("*Menu.activeBackground", SURFACE_HOVER),
        ("*Menu.activeForeground", TEXT),
        ("*Menu.selectColor", ACCENT),
    ):
        try:
            root.option_add(pattern, value)
        except (AttributeError, tk.TclError):
            pass
    polish_widget_tree(root)


def install_modern_theme(root) -> None:
    """Apply the theme now and keep future Tk widgets visually consistent.

    Language switching rebuilds the client UI in-place. The binding is installed
    only once on the persistent root, while styles are safely re-applied after
    each rebuild.
    """

    apply_modern_theme(root)
    if getattr(root, "_swir_modern_theme_tracking", False):
        return

    def _on_map(event) -> None:
        widget = getattr(event, "widget", None)
        if widget is not None:
            polish_widget(widget)

    try:
        root.bind_all("<Map>", _on_map, add="+")
    except (AttributeError, tk.TclError):
        return
    setattr(root, "_swir_modern_theme_tracking", True)
