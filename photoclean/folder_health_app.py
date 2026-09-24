"""Final desktop wiring for the read-only Folder Health Center.

This layer intentionally stays above the existing review/session/fullscreen stack.
Folder Health consumes the current ScanResult only; it never changes cleanup marks
or invokes file operations.
"""
from __future__ import annotations

import tkinter as tk

from .compare_insights_gui import PhotoCleanApp as ReviewPhotoCleanApp
from .diagnostics_plus_gui import EnhancedDiagnosticsWindow
from .folder_health_gui import health_tr
from .folder_health_hotspots_gui import FolderHealthHotspotsWindow as FolderHealthWindow
from .modern_theme import install_modern_theme
from .windows_ui import configure_process_dpi_awareness, install_windows_chrome_tracking


class PhotoCleanApp(ReviewPhotoCleanApp):
    """Final app with Folder Health, Diagnostics and final visual polish."""

    def __init__(self, root, settings_path=None):
        self.folder_health_view = None
        super().__init__(root, settings_path)

    def _build(self, root):
        # The base UI owns layout/behavior. Apply final theme tokens afterwards
        # so every language rebuild keeps the same flat Windows 11 presentation.
        super()._build(root)
        install_modern_theme(root)

    def _install_session_menu(self):
        # Base code owns the menu bar and recreates it on language changes. By
        # extending that hook, Folder Health stays localized after every rebuild.
        super()._install_session_menu()
        self.view_menu.add_separator()
        self.view_menu.add_command(
            label=health_tr("Folder Health"),
            command=self.open_folder_health,
            accelerator="Ctrl+H",
        )
        self.root.bind("<Control-h>", lambda event: self.open_folder_health())
        self.root.bind("<Control-H>", lambda event: self.open_folder_health())

    def open_diagnostics(self):
        """Open the enhanced read-only diagnostics view from the final app stack."""

        existing = getattr(self, "diagnostics_view", None)
        if existing is not None:
            try:
                if existing.window.winfo_exists():
                    existing.window.lift()
                    existing.window.focus_set()
                    return
            except tk.TclError:
                pass
        self.diagnostics_view = EnhancedDiagnosticsWindow(self)

    def open_folder_health(self):
        """Open or refresh the report without rescanning or changing marks."""

        if self.busy:
            return
        existing = self.folder_health_view
        if existing is not None:
            try:
                if existing.window.winfo_exists():
                    existing.refresh(self.result)
                    existing.window.deiconify()
                    existing.window.lift()
                    existing.window.focus_set()
                    return
            except tk.TclError:
                pass
        self.folder_health_view = FolderHealthWindow(self.root, self.result)


def main(settings_path=None):
    # DPI mode must be requested before the first Tk window exists. Prefer
    # per-monitor-v2 on modern Windows and fall back safely on older systems.
    configure_process_dpi_awareness()

    root = tk.Tk()
    PhotoCleanApp(root, settings_path=settings_path)
    # Keep native dark title-bar/rounded-corner treatment on the main window and
    # lazily created feature windows without adding Windows dependencies there.
    install_windows_chrome_tracking(root)
    root.mainloop()
