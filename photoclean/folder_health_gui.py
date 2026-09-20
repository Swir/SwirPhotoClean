"""Read-only Folder Health Center for the desktop application.

The window summarizes scan evidence only. It never marks files, changes source
images or exposes a cleanup action.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import i18n
from .core import ScanResult
from .gui import ACCENT, BG, MUTED, PANEL, TEXT, human_size
from .insights import folder_health


HEALTH_EN = {
    "Folder Health": "Folder Health",
    "Stan biblioteki po skanowaniu": "Library health after scan",
    "Raport tylko do odczytu. Pewne oszczędności obejmują wyłącznie identyczne pliki i zawsze zachowują co najmniej jedną kopię.": (
        "Read-only report. Exact savings include byte-identical files only and always preserve at least one copy."
    ),
    "Zdjęcia": "Photos",
    "Rozmiar biblioteki": "Library size",
    "Pewne duplikaty": "Exact duplicates",
    "Pewne oszczędności": "Exact savings",
    "Podobne do przeglądu": "Similar to review",
    "Poza grupami": "Outside groups",
    "Uwagi skanowania": "Scan notices",
    "{v0} grup • {v1} dodatkowych kopii": "{v0} groups • {v1} extra copies",
    "{v0} grup • {v1} kandydatów": "{v0} groups • {v1} candidates",
    "{v0}% biblioteki": "{v0}% of library",
    "Największe pliki": "Largest files",
    "Nazwa": "Name",
    "Rozmiar": "Size",
    "Wymiary": "Dimensions",
    "Ścieżka": "Path",
    "Brak zeskanowanych zdjęć.": "No scanned photos.",
    "Brak uwag z ostatniego skanu.": "No notices from the latest scan.",
    "Skan został anulowany — wyniki są niepełne i nie mogą służyć do czyszczenia.": (
        "The scan was cancelled — results are incomplete and cannot be used for cleanup."
    ),
    "Ten ekran niczego nie zaznacza ani nie usuwa. Podobne zdjęcia zawsze wymagają ręcznego porównania.": (
        "This screen never marks or removes files. Similar photos always require manual comparison."
    ),
    "Odśwież": "Refresh",
    "Zamknij": "Close",
}


def health_tr(message: str, **values) -> str:
    text = HEALTH_EN.get(message, message) if i18n.language == "en" else message
    return text.format(**values) if values else text


class FolderHealthWindow:
    """Professional read-only summary of the current ScanResult."""

    def __init__(self, parent, result: ScanResult):
        self.parent = parent
        self.result = result
        self.health = folder_health(result, largest_limit=12)
        self.metric_vars: dict[str, tk.StringVar] = {}

        self.window = tk.Toplevel(parent)
        self.window.title(f"{health_tr('Folder Health')} — SwirPhotoClean")
        self.window.configure(bg=BG)
        self.window.geometry("980x700")
        self.window.minsize(820, 580)
        self.window.transient(parent)

        outer = ttk.Frame(self.window, padding=(18, 16))
        outer.pack(fill="both", expand=True)

        ttk.Label(
            outer,
            text=health_tr("Folder Health"),
            style="Title.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            outer,
            text=health_tr("Stan biblioteki po skanowaniu"),
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(0, 4))
        ttk.Label(
            outer,
            text=health_tr(
                "Raport tylko do odczytu. Pewne oszczędności obejmują wyłącznie identyczne pliki i zawsze zachowują co najmniej jedną kopię."
            ),
            style="Muted.TLabel",
            wraplength=920,
        ).pack(anchor="w", pady=(0, 14))

        cards = ttk.Frame(outer)
        cards.pack(fill="x")
        for column in range(3):
            cards.columnconfigure(column, weight=1, uniform="health")
        self._card(cards, 0, 0, "photos", health_tr("Zdjęcia"))
        self._card(cards, 0, 1, "library", health_tr("Rozmiar biblioteki"))
        self._card(cards, 0, 2, "duplicates", health_tr("Pewne duplikaty"))
        self._card(cards, 1, 0, "savings", health_tr("Pewne oszczędności"))
        self._card(cards, 1, 1, "similar", health_tr("Podobne do przeglądu"))
        self._card(cards, 1, 2, "unflagged", health_tr("Poza grupami"))

        ttk.Label(
            outer,
            text=health_tr("Największe pliki"),
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w", pady=(16, 6))

        table_frame = ttk.Frame(outer)
        table_frame.pack(fill="both", expand=True)
        columns = ("name", "size", "dimensions", "path")
        self.files = ttk.Treeview(table_frame, columns=columns, show="headings", height=9)
        self.files.heading("name", text=health_tr("Nazwa"))
        self.files.heading("size", text=health_tr("Rozmiar"))
        self.files.heading("dimensions", text=health_tr("Wymiary"))
        self.files.heading("path", text=health_tr("Ścieżka"))
        self.files.column("name", width=180, minwidth=120)
        self.files.column("size", width=100, minwidth=80, anchor="e")
        self.files.column("dimensions", width=110, minwidth=90, anchor="center")
        self.files.column("path", width=470, minwidth=220)
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.files.yview)
        self.files.configure(yscrollcommand=scrollbar.set)
        self.files.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        ttk.Label(
            outer,
            text=health_tr("Uwagi skanowania"),
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", pady=(14, 6))
        self.notices = tk.Text(
            outer,
            height=5,
            wrap="word",
            bg=PANEL,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            padx=10,
            pady=8,
            font=("Segoe UI", 9),
        )
        self.notices.pack(fill="x")

        footer = ttk.Frame(outer)
        footer.pack(fill="x", pady=(12, 0))
        self.status_var = tk.StringVar()
        ttk.Label(
            footer,
            textvariable=self.status_var,
            style="Muted.TLabel",
        ).pack(side="left", fill="x", expand=True)
        ttk.Button(
            footer,
            text=health_tr("Odśwież"),
            command=lambda: self.refresh(self.result),
        ).pack(side="right", padx=(8, 0))
        ttk.Button(
            footer,
            text=health_tr("Zamknij"),
            command=self.window.destroy,
        ).pack(side="right")

        self.refresh(result)

    def _card(self, parent, row: int, column: int, key: str, title: str) -> None:
        frame = tk.Frame(
            parent,
            bg=PANEL,
            highlightbackground="#30435f",
            highlightthickness=1,
            padx=12,
            pady=10,
        )
        frame.grid(row=row, column=column, sticky="nsew", padx=4, pady=4)
        tk.Label(
            frame,
            text=title,
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        ).pack(fill="x")
        value = tk.StringVar()
        tk.Label(
            frame,
            textvariable=value,
            bg=PANEL,
            fg=ACCENT,
            font=("Segoe UI", 13, "bold"),
            anchor="w",
            justify="left",
        ).pack(fill="x", pady=(5, 0))
        self.metric_vars[key] = value

    def refresh(self, result: ScanResult) -> None:
        """Refresh from an already-produced ScanResult without rescanning."""

        self.result = result
        self.health = folder_health(result, largest_limit=12)
        health = self.health

        self.metric_vars["photos"].set(str(health.total_photos))
        self.metric_vars["library"].set(human_size(health.total_bytes))
        self.metric_vars["duplicates"].set(
            health_tr(
                "{v0} grup • {v1} dodatkowych kopii",
                v0=health.exact_groups,
                v1=health.exact_duplicate_files,
            )
        )
        self.metric_vars["savings"].set(
            f"{human_size(health.exact_reclaimable_bytes)} • "
            + health_tr(
                "{v0}% biblioteki",
                v0=f"{health.exact_reclaimable_percent:.1f}",
            )
        )
        self.metric_vars["similar"].set(
            health_tr(
                "{v0} grup • {v1} kandydatów",
                v0=health.similar_groups,
                v1=health.similar_review_files,
            )
        )
        self.metric_vars["unflagged"].set(str(health.unflagged_files))

        for item in self.files.get_children():
            self.files.delete(item)
        for photo in health.largest_files:
            self.files.insert(
                "",
                "end",
                values=(
                    photo.path.name,
                    human_size(photo.size),
                    f"{photo.width}×{photo.height}",
                    str(photo.path),
                ),
            )
        if not health.largest_files:
            self.files.insert("", "end", values=(health_tr("Brak zeskanowanych zdjęć."), "", "", ""))

        lines = []
        if result.cancelled:
            lines.append(
                health_tr(
                    "Skan został anulowany — wyniki są niepełne i nie mogą służyć do czyszczenia."
                )
            )
        lines.extend(result.warnings[:200])
        if len(result.warnings) > 200:
            lines.append(f"… +{len(result.warnings) - 200}")
        if not lines:
            lines.append(health_tr("Brak uwag z ostatniego skanu."))
        self.notices.configure(state="normal")
        self.notices.delete("1.0", "end")
        self.notices.insert("1.0", "\n".join(lines))
        self.notices.configure(state="disabled")

        self.status_var.set(
            health_tr(
                "Ten ekran niczego nie zaznacza ani nie usuwa. Podobne zdjęcia zawsze wymagają ręcznego porównania."
            )
        )
