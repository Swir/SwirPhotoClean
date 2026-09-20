"""Final desktop wiring for Folder Health plus the runtime Safe Mode guard.

This layer intentionally stays above the existing review/session/fullscreen stack.
Folder Health consumes the current ScanResult only; it never changes cleanup marks
or invokes file operations. Safe Mode is runtime-only defense in depth: review and
marking stay available, while every normal cleanup execution path is blocked.
"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox

from .compare_insights_gui import PhotoCleanApp as ReviewPhotoCleanApp
from .folder_health_gui import FolderHealthWindow, health_tr
from .safe_mode_gui import safe_tr


class PhotoCleanApp(ReviewPhotoCleanApp):
    """Final app with Folder Health and the review-only Safe Mode guard."""

    def __init__(self, root, settings_path=None):
        self.folder_health_view = None
        # Runtime-only by design. Each launch starts with the normal guarded
        # Recycle Bin workflow rather than silently persisting Safe Mode state.
        self.safe_mode = tk.BooleanVar(master=root, value=False)
        super().__init__(root, settings_path)

    def _install_session_menu(self):
        # Base code owns the menu bar and recreates it on language changes. By
        # extending that hook, both final-layer tools stay localized after rebuilds.
        super()._install_session_menu()
        self.view_menu.add_separator()
        self.view_menu.add_checkbutton(
            label=safe_tr("Tryb bezpieczny — blokuj Kosz"),
            variable=self.safe_mode,
            command=self._safe_mode_changed,
        )
        self.view_menu.add_command(
            label=health_tr("Folder Health"),
            command=self.open_folder_health,
            accelerator="Ctrl+H",
        )
        self.root.bind("<Control-h>", lambda event: self.open_folder_health())
        self.root.bind("<Control-H>", lambda event: self.open_folder_health())

    def _safe_mode_changed(self):
        self.update_summary()
        if self.safe_mode.get():
            self.status.set(
                safe_tr(
                    "Tryb bezpieczny WŁĄCZONY • możesz analizować i oznaczać zdjęcia, ale przenoszenie do Kosza jest zablokowane."
                )
            )
        else:
            self.status.set(
                safe_tr(
                    "Tryb bezpieczny WYŁĄCZONY • normalne zabezpieczenia Kosza nadal obowiązują."
                )
            )

    def update_summary(self):
        super().update_summary()
        # Defense in depth: preserve review/marking state but never expose an
        # enabled cleanup action while Safe Mode is active.
        if self.safe_mode.get():
            self.trash_button.configure(state="disabled")

    def confirm_recycle(self):
        # Do not rely only on disabled UI state: block direct/programmatic calls too.
        if self.safe_mode.get():
            messagebox.showinfo(
                safe_tr("Tryb bezpieczny"),
                safe_tr(
                    "Przenoszenie do Kosza jest zablokowane przez Tryb bezpieczny. Wyłącz go świadomie w menu Widok, jeśli chcesz wykonać normalną, potwierdzaną operację Kosza."
                ),
            )
            return
        super().confirm_recycle()

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
    if os.name == "nt":
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    PhotoCleanApp(root, settings_path=settings_path)
    root.mainloop()
