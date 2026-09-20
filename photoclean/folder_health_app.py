"""Final desktop wiring for the read-only Folder Health Center.

This layer intentionally stays above the existing review/session/fullscreen stack.
Folder Health consumes the current ScanResult only; it never changes cleanup marks
or invokes file operations.
"""
from __future__ import annotations

import os
import tkinter as tk

from .compare_insights_gui import PhotoCleanApp as ReviewPhotoCleanApp
from .folder_health_gui import FolderHealthWindow, health_tr


class PhotoCleanApp(ReviewPhotoCleanApp):
    """Final app with a persistent, read-only Folder Health Center."""

    def __init__(self, root, settings_path=None):
        self.folder_health_view = None
        super().__init__(root, settings_path)

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


def main():
    if os.name == "nt":
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    PhotoCleanApp(root)
    root.mainloop()
