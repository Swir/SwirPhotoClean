"""Professional insight layer for the desktop UI.

Keeps the existing tested Tk workflow intact while surfacing read-only Smart
Keep and Folder Health information. No automatic marking or disposal is added.
"""
from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from . import i18n
from .gui import BG, PANEL, TEXT, PhotoCleanApp as BasePhotoCleanApp, human_size
from .i18n import tr
from .insights import folder_health, recommend_keeper
from .session import SessionError, SessionSnapshot, load_session, save_session


SESSION_EXTENSION = ".swirpc"
THRESHOLDS = (3, 6, 10)


class PhotoCleanApp(BasePhotoCleanApp):
    """Existing desktop app plus non-destructive review insights and sessions."""

    def __init__(self, root, settings_path=None):
        super().__init__(root, settings_path)
        self._install_session_menu()

    def _install_session_menu(self):
        menu = tk.Menu(self.root)
        session_menu = tk.Menu(menu, tearoff=False)
        session_menu.add_command(
            label=tr('Otwórz sesję…'),
            command=self.load_session_dialog,
            accelerator="Ctrl+O",
        )
        session_menu.add_command(
            label=tr('Zapisz sesję…'),
            command=self.save_session_dialog,
            accelerator="Ctrl+S",
        )
        menu.add_cascade(label=tr('Sesja'), menu=session_menu)
        self.root.configure(menu=menu)
        self.session_menu = session_menu
        self.root.bind("<Control-o>", lambda event: self.load_session_dialog())
        self.root.bind("<Control-s>", lambda event: self.save_session_dialog())

    def change_language(self, event=None):
        previous = i18n.language
        super().change_language(event)
        if i18n.language != previous:
            self._install_session_menu()

    def _current_threshold(self):
        index = self.level_box.current()
        return THRESHOLDS[index] if 0 <= index < len(THRESHOLDS) else 6

    def _set_threshold_control(self, threshold):
        nearest = min(range(len(THRESHOLDS)), key=lambda index: abs(THRESHOLDS[index] - threshold))
        self.level_box.current(nearest)

    def save_session_dialog(self):
        """Save a completed review snapshot without any Recycle Bin marks."""
        if self.busy:
            return
        if self.result.cancelled or not self.result.photos:
            messagebox.showinfo(
                tr('Brak sesji do zapisania'),
                tr('Najpierw ukończ skanowanie. Niepełnych lub pustych wyników nie zapisujemy jako sesji.'),
            )
            return
        target = filedialog.asksaveasfilename(
            title=tr('Zapisz sesję'),
            defaultextension=SESSION_EXTENSION,
            filetypes=[(tr('Sesja SWIR PhotoClean'), f"*{SESSION_EXTENSION}"), ("JSON", "*.json")],
        )
        if not target:
            return
        snapshot = SessionSnapshot(
            roots=tuple(Path(item) for item in self.folders.get(0, "end")),
            threshold=self._current_threshold(),
            include_similar=bool(self.similarity.get()),
            result=self.result,
        )
        try:
            save_session(snapshot, target)
        except (OSError, SessionError) as error:
            messagebox.showerror(tr('Nie zapisano sesji'), str(error))
            return
        self.status.set(
            tr(
                'Zapisano sesję • {v0} zdjęć • {v1} grup • bez zaznaczeń do kosza',
                v0=len(self.result.photos),
                v1=len(self.result.groups),
            )
        )

    def load_session_dialog(self):
        """Load a validated snapshot for review; destructive marks stay empty."""
        if self.busy:
            return
        source = filedialog.askopenfilename(
            title=tr('Otwórz sesję'),
            filetypes=[(tr('Sesja SWIR PhotoClean'), f"*{SESSION_EXTENSION}"), ("JSON", "*.json"), (tr('Wszystkie pliki'), "*.*")],
        )
        if not source:
            return
        try:
            snapshot = load_session(source)
        except (OSError, SessionError) as error:
            messagebox.showerror(tr('Nie można otworzyć sesji'), str(error))
            return

        self.folders.delete(0, "end")
        for root in snapshot.roots:
            self.folders.insert("end", str(root))
        self.similarity.set(snapshot.include_similar)
        self._set_threshold_control(snapshot.threshold)
        self.result = snapshot.result
        self.marked.clear()
        self.render_groups()
        self.status.set(
            tr(
                'Wczytano sesję • {v0} zdjęć • {v1} grup • zaznaczenia do kosza wyczyszczone',
                v0=len(self.result.photos),
                v1=len(self.result.groups),
            )
        )

    def choose_group(self, event=None):
        super().choose_group(event)
        if not self.active_group:
            return

        recommendation = recommend_keeper(self.active_group)
        if not recommendation.equivalent_exact:
            for index, photo in enumerate(self.active_group.photos):
                iid = str(index)
                if not self.files.exists(iid):
                    continue
                values = list(self.files.item(iid, "values"))
                if photo.path == recommendation.photo.path and len(values) >= 2:
                    values[1] = "★ " + str(values[1])
                    self.files.item(iid, values=values)

        if recommendation.equivalent_exact:
            self.status.set(tr('Smart Keep • kopie są identyczne bajt w bajt — zachowaj dowolną.'))
        else:
            confidence = tr({'high': 'wysoka', 'medium': 'średnia', 'low': 'niska'}[recommendation.confidence])
            self.status.set(
                tr(
                    'Smart Keep • sugerowane zachowanie: {v0} • wynik {v1}/100 • pewność: {v2}',
                    v0=recommendation.photo.path.name,
                    v1=int(round(recommendation.score)),
                    v2=confidence,
                )
            )

    def update_summary(self):
        super().update_summary()
        health = folder_health(self.result)
        selected_size = sum(photo.size for photo in self.result.photos if photo.path in self.marked)
        self.summary.set(
            tr(
                'Do kosza: {v0} plików • {v1}  |  Pewne duplikaty: {v2} • {v3}',
                v0=len(self.marked),
                v1=human_size(selected_size),
                v2=health.exact_duplicate_files,
                v3=human_size(health.exact_reclaimable_bytes),
            )
        )

    def show_warnings(self):
        window = tk.Toplevel(self.root)
        window.title(tr('Raport skanowania'))
        window.geometry("850x400")
        text = tk.Text(window, wrap="word", bg=PANEL, fg=TEXT, font=("Segoe UI", 10))
        text.pack(fill="both", expand=True)

        health = folder_health(self.result)
        overview = tr(
            'Folder Health • zdjęcia: {v0} • dokładne duplikaty: {v1} • podobne do przeglądu: {v2} • pewne oszczędności: {v3} • uwagi: {v4}',
            v0=health.total_photos,
            v1=health.exact_duplicate_files,
            v2=health.similar_review_files,
            v3=human_size(health.exact_reclaimable_bytes),
            v4=health.warning_count,
        )
        notices = "\n\n".join(self.result.warnings) or tr(
            'Brak uwag. Obsługiwane: JPG, PNG, WebP, BMP oraz jednostronicowe TIFF/GIF. HEIC i RAW nie są obsługiwane w tej wersji.'
        )
        text.insert("1.0", overview + "\n\n" + notices)
        text.configure(state="disabled")


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
