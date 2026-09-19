"""Read-only Large Files / Space Hunter desktop layer.

The window summarizes already-scanned metadata. It never marks files for the
Recycle Bin and never treats visually similar photos as guaranteed savings.
"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox, ttk

from . import i18n
from .bad_shots_gui import PhotoCleanApp as BadShotPhotoCleanApp
from .gui import BG, human_size
from .space_hunter import SpaceFile, build_space_report


SPACE_EN = {
    "Space Hunter…": "Space Hunter…",
    "Space Hunter": "Space Hunter",
    "Ctrl+Shift+L": "Ctrl+Shift+L",
    "Brak zdjęć do analizy miejsca": "No photos for space analysis",
    "Najpierw wykonaj lub wczytaj zakończony skan.": "Run or load a completed scan first.",
    "Analiza jest tylko do odczytu. Pewne oszczędności obejmują wyłącznie identyczne bajt w bajt kopie SHA-256; podobne zdjęcia wymagają ręcznej decyzji.": "This analysis is read-only. Guaranteed savings include only byte-identical SHA-256 copies; similar photos require a manual decision.",
    "Zdjęcia: {v0} • rozmiar biblioteki: {v1} • pewne kopie: {v2} • pewne oszczędności: {v3}": "Photos: {v0} • library size: {v1} • guaranteed duplicate copies: {v2} • guaranteed savings: {v3}",
    "Największe pliki": "Largest files",
    "Największe foldery": "Largest folders",
    "Rozmiar": "Size",
    "Status": "Status",
    "Wymiary": "Dimensions",
    "Plik": "File",
    "Folder": "Folder",
    "Pliki": "Files",
    "Kopiuj ścieżkę": "Copy path",
    "Otwórz grupę": "Open group",
    "Zamknij": "Close",
    "Wybierz pozycję z listy.": "Select an item from the list.",
    "Ten plik nie należy do grupy duplikatów/podobnych zdjęć.": "This file is not part of a duplicate/similar group.",
    "Dokładna grupa ×{v0} • pewny nadmiar grupy {v1}": "Exact group ×{v0} • guaranteed group overhead {v1}",
    "Podobne zdjęcie • tylko do przeglądu": "Similar photo • review only",
    "Brak pewnego odzysku z duplikatów": "No guaranteed duplicate reclaim",
    "Pokazano {v0} największych plików i {v1} folderów. Nic nie zaznaczono do kosza.": "Showing {v0} largest files and {v1} folders. Nothing was selected for Recycle Bin.",
}


def space_tr(message, **values):
    text = SPACE_EN.get(message, message) if i18n.language == "en" else message
    return text.format(**values) if values else text


def _status_text(item: SpaceFile) -> str:
    if item.status == "exact":
        return space_tr(
            "Dokładna grupa ×{v0} • pewny nadmiar grupy {v1}",
            v0=item.exact_group_size,
            v1=human_size(item.exact_group_reclaimable_bytes),
        )
    if item.status == "similar":
        return space_tr("Podobne zdjęcie • tylko do przeglądu")
    return space_tr("Brak pewnego odzysku z duplikatów")


class SpaceHunterWindow:
    """Professional, non-destructive view of large scanned files and folders."""

    FILE_LIMIT = 200
    FOLDER_LIMIT = 50

    def __init__(self, app: "PhotoCleanApp"):
        self.app = app
        self.report = build_space_report(
            app.result,
            file_limit=self.FILE_LIMIT,
            folder_limit=self.FOLDER_LIMIT,
        )
        self.file_items: dict[str, SpaceFile] = {}
        self.folder_paths: dict[str, str] = {}

        self.window = tk.Toplevel(app.root)
        self.window.title(space_tr("Space Hunter"))
        self.window.geometry("1180x680")
        self.window.minsize(860, 500)
        self.window.configure(bg=BG)
        self.window.transient(app.root)

        outer = ttk.Frame(self.window, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(
            outer,
            text=space_tr(
                "Analiza jest tylko do odczytu. Pewne oszczędności obejmują wyłącznie identyczne bajt w bajt kopie SHA-256; podobne zdjęcia wymagają ręcznej decyzji."
            ),
            wraplength=1100,
        ).pack(anchor="w", pady=(0, 8))
        ttk.Label(
            outer,
            text=space_tr(
                "Zdjęcia: {v0} • rozmiar biblioteki: {v1} • pewne kopie: {v2} • pewne oszczędności: {v3}",
                v0=self.report.photo_count,
                v1=human_size(self.report.total_bytes),
                v2=self.report.exact_duplicate_files,
                v3=human_size(self.report.exact_reclaimable_bytes),
            ),
        ).pack(anchor="w", pady=(0, 10))

        self.notebook = ttk.Notebook(outer)
        self.notebook.pack(fill="both", expand=True)
        files_tab = ttk.Frame(self.notebook, padding=6)
        folders_tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(files_tab, text=space_tr("Największe pliki"))
        self.notebook.add(folders_tab, text=space_tr("Największe foldery"))

        self._build_files_table(files_tab)
        self._build_folders_table(folders_tab)

        self.status_var = tk.StringVar(
            value=space_tr(
                "Pokazano {v0} największych plików i {v1} folderów. Nic nie zaznaczono do kosza.",
                v0=len(self.report.largest_files),
                v1=len(self.report.largest_folders),
            )
        )
        ttk.Label(outer, textvariable=self.status_var).pack(anchor="w", pady=(10, 0))

        buttons = ttk.Frame(outer, padding=(0, 10, 0, 0))
        buttons.pack(fill="x")
        ttk.Button(buttons, text=space_tr("Otwórz grupę"), command=self.open_group).pack(side="left")
        ttk.Button(buttons, text=space_tr("Kopiuj ścieżkę"), command=self.copy_path).pack(side="left", padx=8)
        ttk.Button(buttons, text=space_tr("Zamknij"), command=self.window.destroy).pack(side="right")
        self.window.bind("<Escape>", lambda event: self.window.destroy())

    def _build_files_table(self, parent):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        columns = ("size", "status", "dimensions", "file", "folder")
        self.files = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        headings = {
            "size": space_tr("Rozmiar"),
            "status": space_tr("Status"),
            "dimensions": space_tr("Wymiary"),
            "file": space_tr("Plik"),
            "folder": space_tr("Folder"),
        }
        widths = {"size": 100, "status": 300, "dimensions": 110, "file": 220, "folder": 420}
        for column in columns:
            self.files.heading(column, text=headings[column])
            self.files.column(column, width=widths[column], minwidth=70, stretch=column in ("status", "folder"))
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.files.yview)
        self.files.configure(yscrollcommand=scroll.set)
        self.files.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.files.bind("<Double-1>", lambda event: self.open_group())
        self.files.bind("<Return>", lambda event: self.open_group())

        for index, item in enumerate(self.report.largest_files):
            iid = str(index)
            self.file_items[iid] = item
            photo = item.photo
            self.files.insert(
                "",
                "end",
                iid=iid,
                values=(
                    human_size(photo.size),
                    _status_text(item),
                    f"{photo.width}×{photo.height}",
                    photo.path.name,
                    str(photo.path.parent),
                ),
            )
        if self.report.largest_files:
            self.files.selection_set("0")
            self.files.focus("0")

    def _build_folders_table(self, parent):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        columns = ("size", "files", "folder")
        self.folders = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        self.folders.heading("size", text=space_tr("Rozmiar"))
        self.folders.heading("files", text=space_tr("Pliki"))
        self.folders.heading("folder", text=space_tr("Folder"))
        self.folders.column("size", width=120, minwidth=80, stretch=False)
        self.folders.column("files", width=90, minwidth=60, stretch=False)
        self.folders.column("folder", width=760, minwidth=240, stretch=True)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.folders.yview)
        self.folders.configure(yscrollcommand=scroll.set)
        self.folders.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        for index, folder in enumerate(self.report.largest_folders):
            iid = str(index)
            path = str(folder.path)
            self.folder_paths[iid] = path
            self.folders.insert("", "end", iid=iid, values=(human_size(folder.total_bytes), folder.photo_count, path))
        if self.report.largest_folders:
            self.folders.selection_set("0")
            self.folders.focus("0")

    def _selected_file(self) -> SpaceFile | None:
        selection = self.files.selection()
        return self.file_items.get(selection[0]) if selection else None

    def copy_path(self):
        if self.notebook.index(self.notebook.select()) == 0:
            item = self._selected_file()
            path = str(item.photo.path) if item is not None else None
        else:
            selection = self.folders.selection()
            path = self.folder_paths.get(selection[0]) if selection else None
        if not path:
            messagebox.showinfo(space_tr("Space Hunter"), space_tr("Wybierz pozycję z listy."), parent=self.window)
            return
        self.app.root.clipboard_clear()
        self.app.root.clipboard_append(path)

    def open_group(self):
        item = self._selected_file()
        if item is None:
            messagebox.showinfo(space_tr("Space Hunter"), space_tr("Wybierz pozycję z listy."), parent=self.window)
            return
        target = item.photo.path
        for group_index, group in enumerate(self.app.result.groups):
            if any(photo.path == target for photo in group.photos):
                iid = str(group_index)
                if self.app.groups.exists(iid):
                    self.app.groups.selection_set(iid)
                    self.app.groups.focus(iid)
                    self.app.groups.see(iid)
                    self.app.choose_group()
                    self.window.lift()
                    return
        messagebox.showinfo(
            space_tr("Space Hunter"),
            space_tr("Ten plik nie należy do grupy duplikatów/podobnych zdjęć."),
            parent=self.window,
        )


class PhotoCleanApp(BadShotPhotoCleanApp):
    """Final desktop layer with read-only disk-space insights."""

    def _install_session_menu(self):
        super()._install_session_menu()
        self.view_menu.add_command(
            label=space_tr("Space Hunter…"),
            command=self.open_space_hunter,
            accelerator=space_tr("Ctrl+Shift+L"),
        )
        self.root.bind("<Control-Shift-L>", lambda event: self.open_space_hunter())
        self.root.bind("<Control-Shift-l>", lambda event: self.open_space_hunter())

    def open_space_hunter(self):
        if self.busy or self.result.cancelled:
            return
        if not self.result.photos:
            messagebox.showinfo(
                space_tr("Brak zdjęć do analizy miejsca"),
                space_tr("Najpierw wykonaj lub wczytaj zakończony skan."),
            )
            return
        existing = getattr(self, "space_hunter_view", None)
        if existing is not None and existing.window.winfo_exists():
            existing.window.destroy()
        self.space_hunter_view = SpaceHunterWindow(self)


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
