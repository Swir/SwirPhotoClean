"""User-selectable scanner performance profiles with unchanged detection semantics."""
from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import messagebox

from . import i18n
from .core import ScanResult, scan
from .i18n import tr
from .performance import load_performance_profile, save_performance_profile
from .cleanup_history_gui import PhotoCleanApp as CleanupHistoryPhotoCleanApp


PERFORMANCE_EN = {
    "Profil wydajności": "Performance profile",
    "Eco": "Eco",
    "Zbalansowany": "Balanced",
    "Szybki": "Fast",
    "Profil wydajności: {v0} • zmiana dotyczy następnego skanu.": "Performance profile: {v0} • the change applies to the next scan.",
    "Rozpoczynanie skanowania… • profil {v0}": "Starting scan… • {v0} profile",
    "Nie zapisano profilu wydajności": "Performance profile not saved",
    "Profil działa w tej sesji, ale nie udało się zapisać ustawienia na kolejne uruchomienie.": "The profile works for this session, but the preference could not be saved for the next launch.",
}

PROFILE_LABELS = {"eco": "Eco", "balanced": "Zbalansowany", "fast": "Szybki"}


def performance_tr(message, **values):
    text = PERFORMANCE_EN.get(message, message) if i18n.language == "en" else message
    return text.format(**values) if values else text


class PhotoCleanApp(CleanupHistoryPhotoCleanApp):
    """Adds persisted Eco/Balanced/Fast scan tuning without changing match logic."""

    def __init__(self, root, settings_path=None):
        self.performance_profile = tk.StringVar(
            master=root,
            value=load_performance_profile(settings_path),
        )
        self._performance_settings_source = settings_path
        self.active_scan_profile = None
        super().__init__(root, settings_path)

    def _profile_label(self, key=None):
        key = key or self.performance_profile.get()
        return performance_tr(PROFILE_LABELS.get(key, PROFILE_LABELS["balanced"]))

    def _install_session_menu(self):
        super()._install_session_menu()
        profile_menu = tk.Menu(self.view_menu, tearoff=False)
        for key in ("eco", "balanced", "fast"):
            profile_menu.add_radiobutton(
                label=self._profile_label(key),
                variable=self.performance_profile,
                value=key,
                command=self._performance_changed,
            )
        self.view_menu.add_separator()
        self.view_menu.add_cascade(
            label=performance_tr("Profil wydajności"),
            menu=profile_menu,
        )
        self.performance_menu = profile_menu

    def _performance_changed(self):
        key = self.performance_profile.get()
        try:
            save_performance_profile(self._performance_settings_source, key)
        except OSError:
            messagebox.showwarning(
                performance_tr("Nie zapisano profilu wydajności"),
                performance_tr("Profil działa w tej sesji, ale nie udało się zapisać ustawienia na kolejne uruchomienie."),
            )
        self.status.set(
            performance_tr(
                "Profil wydajności: {v0} • zmiana dotyczy następnego skanu.",
                v0=self._profile_label(key),
            )
        )

    def start_scan(self):
        if self.busy:
            return
        roots = self.folders.get(0, "end")
        if not roots:
            messagebox.showinfo(tr('Wybierz folder'), tr('Najpierw dodaj co najmniej jeden folder.'))
            return
        threshold = self._current_threshold()
        include_similar = self.similarity.get()
        profile = self.performance_profile.get()
        self.active_scan_profile = profile
        self.cancel.clear()
        self.result = ScanResult()
        self.marked.clear()
        self.render_groups()
        self.set_busy(True)
        self.status.set(
            performance_tr(
                "Rozpoczynanie skanowania… • profil {v0}",
                v0=self._profile_label(profile),
            )
        )

        def worker():
            try:
                self.events.put(
                    (
                        "scan",
                        scan(
                            roots,
                            threshold,
                            self.cancel,
                            self.progress,
                            include_similar,
                            performance_profile=profile,
                        ),
                    )
                )
            except Exception as error:
                self.events.put(("error", str(error)))

        threading.Thread(target=worker, daemon=True).start()


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
