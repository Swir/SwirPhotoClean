"""Optional Safe Mode that blocks every cleanup execution path while preserving review marks."""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox

from . import i18n
from .difference_gui import PhotoCleanApp as DifferencePhotoCleanApp


SAFE_EN = {
    "Tryb bezpieczny — blokuj Kosz": "Safe Mode — block Recycle Bin",
    "Tryb bezpieczny WŁĄCZONY • możesz analizować i oznaczać zdjęcia, ale przenoszenie do Kosza jest zablokowane.": "Safe Mode ON • you can review and mark photos, but moving files to the Recycle Bin is blocked.",
    "Tryb bezpieczny WYŁĄCZONY • normalne zabezpieczenia Kosza nadal obowiązują.": "Safe Mode OFF • normal Recycle Bin safeguards still apply.",
    "Tryb bezpieczny": "Safe Mode",
    "Przenoszenie do Kosza jest zablokowane przez Tryb bezpieczny. Wyłącz go świadomie w menu Widok, jeśli chcesz wykonać normalną, potwierdzaną operację Kosza.": "Moving files to the Recycle Bin is blocked by Safe Mode. Deliberately turn it off in the View menu if you want to perform the normal confirmed Recycle Bin operation.",
}


def safe_tr(message, **values):
    text = SAFE_EN.get(message, message) if i18n.language == "en" else message
    return text.format(**values) if values else text


class PhotoCleanApp(DifferencePhotoCleanApp):
    """Final desktop layer with a defense-in-depth, review-only Safe Mode."""

    def __init__(self, root, settings_path=None):
        # Runtime-only by design: changing Safe Mode never alters saved user settings.
        self.safe_mode = tk.BooleanVar(master=root, value=False)
        super().__init__(root, settings_path)

    def _install_session_menu(self):
        super()._install_session_menu()
        self.view_menu.add_separator()
        self.view_menu.add_checkbutton(
            label=safe_tr("Tryb bezpieczny — blokuj Kosz"),
            variable=self.safe_mode,
            command=self._safe_mode_changed,
        )

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
                safe_tr("Tryb bezpieczny WYŁĄCZONY • normalne zabezpieczenia Kosza nadal obowiązują.")
            )

    def update_summary(self):
        super().update_summary()
        # Defense in depth: keep review/marking enabled but never expose an active
        # cleanup button while Safe Mode is on.
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
