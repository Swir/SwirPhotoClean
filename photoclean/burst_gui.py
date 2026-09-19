"""Burst Cleaner and photo-quality UI layered on the professional review interface."""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox, ttk

from . import i18n
from .burst import BurstSequence, burst_sequences
from .gui import BG, PANEL, TEXT, human_size
from .pro_gui import PhotoCleanApp as ProPhotoCleanApp, session_tr
from .quality import assess_photo, recommend_keeper_with_quality


BURST_EN = {
    "Burst Cleaner…": "Burst Cleaner…",
    "Burst Cleaner": "Burst Cleaner",
    "Brak pewnych serii": "No confident bursts",
    "Nie znaleziono serii potwierdzonych czasem wykonania z EXIF. Pliki bez EXIF nie są zgadywane na podstawie nazw ani czasu modyfikacji.": "No burst sequences backed by EXIF capture time were found. Files without EXIF are not guessed from filenames or modification time.",
    "Seria": "Burst",
    "Grupa": "Group",
    "Klatki": "Frames",
    "Czas": "Span",
    "Sugerowane zachowanie": "Suggested keep",
    "Wykryto {v0} serii • tylko podobne zdjęcia + czas wykonania EXIF • nic nie jest zaznaczane automatycznie": "Found {v0} bursts • similar photos + EXIF capture time only • nothing is selected automatically",
    "Otwórz grupę": "Open group",
    "Zamknij": "Close",
    "Wybierz serię z listy.": "Select a burst from the list.",
    "Burst Cleaner • seria {v0} • {v1} klatek • sugerowane zachowanie: {v2} • nic nie zaznaczono do kosza": "Burst Cleaner • burst {v0} • {v1} frames • suggested keep: {v2} • nothing selected for Recycle Bin",
    "sek": "sec",
    "Ctrl+B": "Ctrl+B",
    "Jakość zdjęć…": "Photo quality…",
    "Jakość zdjęć": "Photo quality",
    "Najpierw wybierz grupę zdjęć.": "Select a photo group first.",
    "Ocena jakości to lokalna heurystyka do przeglądu — nie jest automatyczną decyzją o usunięciu.": "Quality score is a local review heuristic — it is not an automatic deletion decision.",
    "Zdjęcie": "Photo",
    "Jakość": "Quality",
    "Ostrość": "Sharpness",
    "Ekspozycja": "Exposure",
    "Uwagi": "Notes",
    "niedostępna": "unavailable",
    "miękkie / możliwe rozmycie": "soft / possible blur",
    "ucięte cienie": "clipped shadows",
    "ucięte światła": "clipped highlights",
    "zbalansowane": "balanced",
    "Smart Keep + Quality • sugerowane zachowanie: {v0} • wynik {v1}/100 • przeanalizowano {v2}/{v3} • nic nie zaznaczono do kosza": "Smart Keep + Quality • suggested keep: {v0} • score {v1}/100 • analyzed {v2}/{v3} • nothing selected for Recycle Bin",
    "Kopie są identyczne bajt w bajt; ocena jakości nie rozstrzyga, którą kopię zachować.": "Copies are byte-identical; quality scoring does not decide which copy to keep.",
    "Ctrl+Q": "Ctrl+Q",
}


def burst_tr(message, **values):
    text = BURST_EN.get(message, message) if i18n.language == "en" else message
    return text.format(**values) if values else text


def _quality_notes(notes):
    labels = {
        "soft": burst_tr("miękkie / możliwe rozmycie"),
        "dark-clipping": burst_tr("ucięte cienie"),
        "light-clipping": burst_tr("ucięte światła"),
        "balanced": burst_tr("zbalansowane"),
        "unavailable": burst_tr("niedostępna"),
    }
    return ", ".join(labels.get(note, note) for note in notes)


class PhotoQualityWindow:
    """Read-only sharpness/exposure inspector for the selected result group."""

    def __init__(self, app: "PhotoCleanApp"):
        self.app = app
        self.group = app.active_group
        self.window = tk.Toplevel(app.root)
        self.window.title(burst_tr("Jakość zdjęć"))
        self.window.geometry("980x520")
        self.window.minsize(760, 420)
        self.window.configure(bg=BG)
        self.window.transient(app.root)

        outer = ttk.Frame(self.window, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(
            outer,
            text=burst_tr(
                "Ocena jakości to lokalna heurystyka do przeglądu — nie jest automatyczną decyzją o usunięciu."
            ),
        ).pack(anchor="w", pady=(0, 10))

        recommendation = recommend_keeper_with_quality(self.group)
        if recommendation.equivalent_exact:
            summary = burst_tr(
                "Kopie są identyczne bajt w bajt; ocena jakości nie rozstrzyga, którą kopię zachować."
            )
        else:
            summary = burst_tr(
                "Smart Keep + Quality • sugerowane zachowanie: {v0} • wynik {v1}/100 • przeanalizowano {v2}/{v3} • nic nie zaznaczono do kosza",
                v0=recommendation.photo.path.name,
                v1=int(round(recommendation.score)),
                v2=recommendation.analyzed_count,
                v3=len(self.group.photos),
            )
        ttk.Label(outer, text=summary).pack(anchor="w", pady=(0, 10))

        table_frame = ttk.Frame(outer)
        table_frame.pack(fill="both", expand=True)
        columns = ("keep", "photo", "quality", "sharpness", "exposure", "notes")
        table = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        headings = {
            "keep": "★",
            "photo": burst_tr("Zdjęcie"),
            "quality": burst_tr("Jakość"),
            "sharpness": burst_tr("Ostrość"),
            "exposure": burst_tr("Ekspozycja"),
            "notes": burst_tr("Uwagi"),
        }
        widths = {"keep": 45, "photo": 300, "quality": 90, "sharpness": 90, "exposure": 90, "notes": 260}
        for column in columns:
            table.heading(column, text=headings[column])
            table.column(column, width=widths[column], minwidth=40, stretch=column in ("photo", "notes"))
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=table.yview)
        table.configure(yscrollcommand=scrollbar.set)
        table.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for index, photo in enumerate(self.group.photos):
            quality = assess_photo(photo)
            if quality.available:
                values = (
                    "★" if (not recommendation.equivalent_exact and photo.path == recommendation.photo.path) else "",
                    str(photo.path),
                    f"{int(round(quality.overall_score))}/100",
                    f"{int(round(quality.sharpness_score))}/100",
                    f"{int(round(quality.exposure_score))}/100",
                    _quality_notes(quality.notes),
                )
            else:
                values = (
                    "",
                    str(photo.path),
                    burst_tr("niedostępna"),
                    "—",
                    "—",
                    quality.error or burst_tr("niedostępna"),
                )
            table.insert("", "end", iid=str(index), values=values)

        buttons = ttk.Frame(outer, padding=(0, 10, 0, 0))
        buttons.pack(fill="x")
        ttk.Button(buttons, text=burst_tr("Zamknij"), command=self.window.destroy).pack(side="right")
        self.window.bind("<Escape>", lambda event: self.window.destroy())


class BurstCleanerWindow:
    """Read-only overview of EXIF-confirmed burst candidates."""

    def __init__(self, app: "PhotoCleanApp", sequences: tuple[BurstSequence, ...]):
        self.app = app
        self.sequences = sequences
        self.window = tk.Toplevel(app.root)
        self.window.title(burst_tr("Burst Cleaner"))
        self.window.geometry("980x520")
        self.window.minsize(760, 420)
        self.window.configure(bg=BG)
        self.window.transient(app.root)

        outer = ttk.Frame(self.window, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(
            outer,
            text=burst_tr(
                "Wykryto {v0} serii • tylko podobne zdjęcia + czas wykonania EXIF • nic nie jest zaznaczane automatycznie",
                v0=len(sequences),
            ),
        ).pack(anchor="w", pady=(0, 10))

        table_frame = ttk.Frame(outer)
        table_frame.pack(fill="both", expand=True)
        columns = ("burst", "group", "frames", "span", "keeper")
        self.table = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        headings = {
            "burst": burst_tr("Seria"),
            "group": burst_tr("Grupa"),
            "frames": burst_tr("Klatki"),
            "span": burst_tr("Czas"),
            "keeper": burst_tr("Sugerowane zachowanie"),
        }
        widths = {"burst": 70, "group": 70, "frames": 70, "span": 160, "keeper": 360}
        for column in columns:
            self.table.heading(column, text=headings[column])
            self.table.column(column, width=widths[column], minwidth=60, stretch=column == "keeper")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for index, sequence in enumerate(sequences):
            start = sequence.started_at.strftime("%Y-%m-%d %H:%M:%S")
            span = f"{start} • {sequence.span_seconds:.1f} {burst_tr('sek')}"
            keeper = sequence.keeper.photo
            quality = sequence.keeper.quality
            quality_text = f" • Q {int(round(quality.overall_score))}/100" if quality is not None else ""
            keeper_text = f"{keeper.path.name} • {keeper.width}×{keeper.height} • {human_size(keeper.size)}{quality_text}"
            self.table.insert(
                "",
                "end",
                iid=str(index),
                values=(index + 1, sequence.group_index + 1, len(sequence.photos), span, keeper_text),
            )

        if sequences:
            self.table.selection_set("0")
            self.table.focus("0")
        self.table.bind("<Double-1>", lambda event: self.open_group())
        self.table.bind("<Return>", lambda event: self.open_group())

        buttons = ttk.Frame(outer, padding=(0, 10, 0, 0))
        buttons.pack(fill="x")
        ttk.Button(buttons, text=burst_tr("Otwórz grupę"), command=self.open_group).pack(side="left")
        ttk.Button(buttons, text=burst_tr("Zamknij"), command=self.window.destroy).pack(side="right")
        self.window.bind("<Escape>", lambda event: self.window.destroy())

    def open_group(self):
        selection = self.table.selection()
        if not selection:
            messagebox.showinfo(burst_tr("Burst Cleaner"), burst_tr("Wybierz serię z listy."), parent=self.window)
            return
        sequence_index = int(selection[0])
        sequence = self.sequences[sequence_index]
        group_iid = str(sequence.group_index)
        if not self.app.groups.exists(group_iid):
            return
        self.app.groups.selection_set(group_iid)
        self.app.groups.focus(group_iid)
        self.app.groups.see(group_iid)
        self.app.choose_group()
        self.app.status.set(
            burst_tr(
                "Burst Cleaner • seria {v0} • {v1} klatek • sugerowane zachowanie: {v2} • nic nie zaznaczono do kosza",
                v0=sequence_index + 1,
                v1=len(sequence.photos),
                v2=sequence.keeper.photo.path.name,
            )
        )
        self.window.destroy()
        self.app.root.focus_force()


class PhotoCleanApp(ProPhotoCleanApp):
    """Professional app with conservative Burst Cleaner and quality review."""

    def _install_session_menu(self):
        super()._install_session_menu()
        self.view_menu.add_separator()
        self.view_menu.add_command(
            label=burst_tr("Burst Cleaner…"),
            command=self.open_burst_cleaner,
            accelerator=burst_tr("Ctrl+B"),
        )
        self.view_menu.add_command(
            label=burst_tr("Jakość zdjęć…"),
            command=self.open_photo_quality,
            accelerator=burst_tr("Ctrl+Q"),
        )
        self.root.bind("<Control-b>", lambda event: self.open_burst_cleaner())
        self.root.bind("<Control-q>", lambda event: self.open_photo_quality())

    def open_burst_cleaner(self):
        if self.busy or self.result.cancelled:
            return
        sequences = burst_sequences(self.result)
        if not sequences:
            messagebox.showinfo(
                burst_tr("Brak pewnych serii"),
                burst_tr(
                    "Nie znaleziono serii potwierdzonych czasem wykonania z EXIF. Pliki bez EXIF nie są zgadywane na podstawie nazw ani czasu modyfikacji."
                ),
            )
            return
        BurstCleanerWindow(self, sequences)

    def open_photo_quality(self):
        if self.busy or self.result.cancelled:
            return
        if not self.active_group:
            messagebox.showinfo(burst_tr("Jakość zdjęć"), burst_tr("Najpierw wybierz grupę zdjęć."))
            return
        PhotoQualityWindow(self)


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
