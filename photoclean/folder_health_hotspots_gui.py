"""Read-only exact-duplicate hotspot drill-down for Folder Health."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk

from . import i18n
from .core import ScanResult
from .folder_health_gui import FolderHealthWindow as BaseFolderHealthWindow
from .folder_hotspots import duplicate_hotspots
from .gui import BG, MUTED, PANEL, TEXT, human_size


HOTSPOT_EN = {
    "Hotspoty duplikatów…": "Duplicate hotspots…",
    "Hotspoty dokładnych duplikatów": "Exact duplicate hotspots",
    "Foldery z największą liczbą zbędnych kopii SHA-256": "Folders with the most redundant SHA-256 copies",
    "Raport tylko do odczytu. Każdy digest zachowuje co najmniej jedną kopię; podobne zdjęcia nie są tu liczone.": (
        "Read-only report. Every digest keeps at least one copy; similar photos are never counted here."
    ),
    "Folder": "Folder",
    "Grupy": "Groups",
    "Dodatkowe kopie": "Extra copies",
    "Potencjalne oszczędności": "Potential savings",
    "Brak hotspotów dokładnych duplikatów.": "No exact-duplicate hotspots.",
    "Pokazano {v0} folderów • {v1} dodatkowych kopii • {v2}": "Showing {v0} folders • {v1} extra copies • {v2}",
    "Kopiuj ścieżkę folderu": "Copy folder path",
    "Zamknij": "Close",
    "Ctrl+Shift+H": "Ctrl+Shift+H",
}


def hotspot_tr(message: str, **values) -> str:
    text = HOTSPOT_EN.get(message, message) if i18n.language == "en" else message
    return text.format(**values) if values else text


class ExactDuplicateHotspotsWindow:
    """Compact read-only ranking of folders with redundant exact copies."""

    def __init__(self, parent, result: ScanResult):
        self.parent = parent
        self.result = result
        self.hotspots = ()
        self._row_folders: dict[str, Path] = {}

        self.window = tk.Toplevel(parent)
        self.window.title(f"{hotspot_tr('Hotspoty dokładnych duplikatów')} — SwirPhotoClean")
        self.window.configure(bg=BG)
        self.window.geometry("900x500")
        self.window.minsize(700, 400)
        self.window.transient(parent)

        outer = ttk.Frame(self.window, padding=(18, 16))
        outer.pack(fill="both", expand=True)
        ttk.Label(
            outer,
            text=hotspot_tr("Hotspoty dokładnych duplikatów"),
            style="Title.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            outer,
            text=hotspot_tr("Foldery z największą liczbą zbędnych kopii SHA-256"),
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(0, 4))
        ttk.Label(
            outer,
            text=hotspot_tr(
                "Raport tylko do odczytu. Każdy digest zachowuje co najmniej jedną kopię; podobne zdjęcia nie są tu liczone."
            ),
            style="Muted.TLabel",
            wraplength=840,
        ).pack(anchor="w", pady=(0, 12))

        table_frame = ttk.Frame(outer)
        table_frame.pack(fill="both", expand=True)
        columns = ("folder", "groups", "copies", "bytes")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("folder", text=hotspot_tr("Folder"))
        self.tree.heading("groups", text=hotspot_tr("Grupy"))
        self.tree.heading("copies", text=hotspot_tr("Dodatkowe kopie"))
        self.tree.heading("bytes", text=hotspot_tr("Potencjalne oszczędności"))
        self.tree.column("folder", width=500, minwidth=240, stretch=True)
        self.tree.column("groups", width=80, minwidth=70, anchor="center", stretch=False)
        self.tree.column("copies", width=120, minwidth=100, anchor="center", stretch=False)
        self.tree.column("bytes", width=140, minwidth=110, anchor="e", stretch=False)
        yscroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        footer = ttk.Frame(outer)
        footer.pack(fill="x", pady=(12, 0))
        self.status_var = tk.StringVar()
        ttk.Label(footer, textvariable=self.status_var, style="Muted.TLabel").pack(
            side="left", fill="x", expand=True
        )
        self.copy_button = ttk.Button(
            footer,
            text=hotspot_tr("Kopiuj ścieżkę folderu"),
            command=self.copy_selected_folder,
            state="disabled",
        )
        self.copy_button.pack(side="right", padx=(8, 0))
        ttk.Button(footer, text=hotspot_tr("Zamknij"), command=self.window.destroy).pack(side="right")

        self.tree.bind("<<TreeviewSelect>>", self._selection_changed)
        self.tree.bind("<Double-1>", lambda event: self.copy_selected_folder())
        self.window.bind("<Escape>", lambda event: self.window.destroy())
        self.window.bind("<Control-c>", lambda event: self.copy_selected_folder())
        self.refresh(result)

    def refresh(self, result: ScanResult) -> None:
        self.result = result
        self.hotspots = duplicate_hotspots(result, limit=20)
        self._row_folders.clear()
        for item in self.tree.get_children():
            self.tree.delete(item)

        if not self.hotspots:
            self.tree.insert(
                "",
                "end",
                iid="empty",
                values=(hotspot_tr("Brak hotspotów dokładnych duplikatów."), "", "", ""),
            )
            self.copy_button.configure(state="disabled")
            self.status_var.set(hotspot_tr("Brak hotspotów dokładnych duplikatów."))
            return

        total_copies = 0
        total_bytes = 0
        for index, hotspot in enumerate(self.hotspots):
            iid = f"hotspot:{index}"
            self._row_folders[iid] = hotspot.folder
            total_copies += hotspot.duplicate_files
            total_bytes += hotspot.reclaimable_bytes
            self.tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    str(hotspot.folder),
                    hotspot.exact_groups,
                    hotspot.duplicate_files,
                    human_size(hotspot.reclaimable_bytes),
                ),
            )

        first = self.tree.get_children()[0]
        self.tree.selection_set(first)
        self.tree.focus(first)
        self.copy_button.configure(state="normal")
        self.status_var.set(
            hotspot_tr(
                "Pokazano {v0} folderów • {v1} dodatkowych kopii • {v2}",
                v0=len(self.hotspots),
                v1=total_copies,
                v2=human_size(total_bytes),
            )
        )

    def _selection_changed(self, _event=None) -> None:
        selected = self.tree.selection()
        self.copy_button.configure(
            state="normal" if selected and selected[0] in self._row_folders else "disabled"
        )

    def copy_selected_folder(self) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        folder = self._row_folders.get(selected[0])
        if folder is None:
            return
        self.window.clipboard_clear()
        self.window.clipboard_append(str(folder))


class FolderHealthHotspotsWindow(BaseFolderHealthWindow):
    """Folder Health with a read-only exact-duplicate hotspot drill-down."""

    def __init__(self, parent, result: ScanResult):
        self.hotspot_view: ExactDuplicateHotspotsWindow | None = None
        super().__init__(parent, result)

        outer_children = self.window.winfo_children()
        if outer_children:
            outer = outer_children[0]
            children = outer.winfo_children()
            if children:
                footer = children[-1]
                ttk.Button(
                    footer,
                    text=hotspot_tr("Hotspoty duplikatów…"),
                    command=self.open_hotspots,
                ).pack(side="right", padx=(8, 0))
        self.window.bind("<Control-Shift-H>", lambda event: self.open_hotspots())
        self.window.bind("<Control-Shift-h>", lambda event: self.open_hotspots())

    def refresh(self, result: ScanResult) -> None:
        super().refresh(result)
        view = getattr(self, "hotspot_view", None)
        if view is None:
            return
        try:
            if view.window.winfo_exists():
                view.refresh(result)
        except tk.TclError:
            self.hotspot_view = None

    def open_hotspots(self) -> None:
        view = self.hotspot_view
        if view is not None:
            try:
                if view.window.winfo_exists():
                    view.refresh(self.result)
                    view.window.deiconify()
                    view.window.lift()
                    view.window.focus_set()
                    return
            except tk.TclError:
                pass
        self.hotspot_view = ExactDuplicateHotspotsWindow(self.window, self.result)
