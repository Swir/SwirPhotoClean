"""Professional insight layer for the desktop UI.

Keeps the existing tested Tk workflow intact while surfacing read-only Smart
Keep and Folder Health information. No automatic marking or disposal is added.
"""
from __future__ import annotations

import os
import tkinter as tk

from . import i18n
from .gui import BG, PANEL, TEXT, PhotoCleanApp as BasePhotoCleanApp, human_size
from .i18n import tr
from .insights import folder_health, recommend_keeper


class PhotoCleanApp(BasePhotoCleanApp):
    """Existing desktop app plus non-destructive review insights."""

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
