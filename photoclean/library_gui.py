"""Read-only timeline and camera/device explorer for completed scan results."""
from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from collections import defaultdict
from tkinter import messagebox, ttk

from . import i18n
from .gui import BG, human_size
from .library import LibraryMetadataReport, analyze_library_metadata
from .safe_mode_gui import PhotoCleanApp as SafeModePhotoCleanApp


LIBRARY_EN = {
    "Biblioteka EXIF…": "EXIF library…",
    "Biblioteka EXIF": "EXIF library",
    "Ctrl+Alt+L": "Ctrl+Alt+L",
    "Brak zdjęć do analizy": "No photos to analyze",
    "Najpierw wykonaj lub wczytaj zakończony skan.": "Run or load a completed scan first.",
    "Odczytywanie metadanych…": "Reading metadata…",
    "Analiza: {v0}/{v1}": "Analysis: {v0}/{v1}",
    "Anuluj analizę": "Cancel analysis",
    "Zamknij": "Close",
    "Oś czasu": "Timeline",
    "Aparaty / urządzenia": "Cameras / devices",
    "Okres": "Period",
    "Aparat / urządzenie": "Camera / device",
    "Pliki": "Files",
    "Rozmiar": "Size",
    "Kopiuj ścieżki": "Copy paths",
    "Otwórz pasującą grupę": "Open matching group",
    "Wybierz okres lub urządzenie z listy.": "Select a period or device from the list.",
    "Żaden plik z tego widoku nie należy do grupy duplikatów/podobnych zdjęć.": "No file in this view belongs to a duplicate/similar group.",
    "Gotowe • pliki {v0} • data EXIF {v1} • urządzenie EXIF {v2} • bez daty {v3} • bez urządzenia {v4} • niedostępne {v5}": "Finished • files {v0} • EXIF date {v1} • EXIF device {v2} • no date {v3} • no device {v4} • unavailable {v5}",
    "Analiza anulowana • odczytano {v0} z {v1} • nic nie zmieniono": "Analysis cancelled • read {v0} of {v1} • nothing changed",
    "Nie udało się odczytać metadanych": "Metadata analysis failed",
    "To narzędzie jest lokalne i tylko do odczytu. Oś czasu używa wyłącznie daty EXIF, a grupy urządzeń wyłącznie pól Make/Model; braków nie zgadujemy z nazwy pliku ani czasu modyfikacji.": "This tool is local and read-only. Timeline uses EXIF capture dates only, and device groups use Make/Model only; missing data is never guessed from filenames or filesystem timestamps.",
    "Brak wiarygodnej daty EXIF w przeskanowanych zdjęciach.": "No reliable EXIF capture date was found in the scanned photos.",
    "Brak pól aparatu/urządzenia EXIF w przeskanowanych zdjęciach.": "No EXIF camera/device fields were found in the scanned photos.",
    "Skopiowano {v0} ścieżek": "Copied {v0} paths",
}


def library_tr(message, **values):
    text = LIBRARY_EN.get(message, message) if i18n.language == "en" else message
    return text.format(**values) if values else text


class LibraryExplorerWindow:
    """Cancellable metadata worker with read-only timeline/device group views."""

    def __init__(self, app: "PhotoCleanApp"):
        self.app = app
        self.events: queue.Queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.report: LibraryMetadataReport | None = None
        self.closed = False
        self.timeline_nodes: dict[str, tuple] = {}
        self.device_nodes: dict[str, tuple] = {}

        self.window = tk.Toplevel(app.root)
        self.window.title(library_tr("Biblioteka EXIF"))
        self.window.geometry("1040x650")
        self.window.minsize(760, 470)
        self.window.configure(bg=BG)
        self.window.transient(app.root)
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        outer = ttk.Frame(self.window, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(
            outer,
            text=library_tr(
                "To narzędzie jest lokalne i tylko do odczytu. Oś czasu używa wyłącznie daty EXIF, a grupy urządzeń wyłącznie pól Make/Model; braków nie zgadujemy z nazwy pliku ani czasu modyfikacji."
            ),
            wraplength=980,
        ).pack(anchor="w", pady=(0, 8))

        progress_row = ttk.Frame(outer)
        progress_row.pack(fill="x", pady=(0, 10))
        self.status_var = tk.StringVar(value=library_tr("Odczytywanie metadanych…"))
        ttk.Label(progress_row, textvariable=self.status_var).pack(side="left", fill="x", expand=True)
        self.progress = ttk.Progressbar(progress_row, mode="determinate", maximum=max(1, len(app.result.photos)))
        self.progress.pack(side="right", ipadx=110)

        self.notebook = ttk.Notebook(outer)
        self.notebook.pack(fill="both", expand=True)
        self.timeline_tab = ttk.Frame(self.notebook, padding=6)
        self.device_tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(self.timeline_tab, text=library_tr("Oś czasu"))
        self.notebook.add(self.device_tab, text=library_tr("Aparaty / urządzenia"))

        self.timeline_tree = self._build_tree(self.timeline_tab, library_tr("Okres"))
        self.device_tree = self._build_tree(self.device_tab, library_tr("Aparat / urządzenie"))
        self.timeline_tree.bind("<Double-1>", lambda event: self.open_group())
        self.device_tree.bind("<Double-1>", lambda event: self.open_group())

        buttons = ttk.Frame(outer, padding=(0, 10, 0, 0))
        buttons.pack(fill="x")
        self.open_button = ttk.Button(
            buttons,
            text=library_tr("Otwórz pasującą grupę"),
            command=self.open_group,
            state="disabled",
        )
        self.open_button.pack(side="left")
        self.copy_button = ttk.Button(
            buttons,
            text=library_tr("Kopiuj ścieżki"),
            command=self.copy_paths,
            state="disabled",
        )
        self.copy_button.pack(side="left", padx=8)
        self.cancel_button = ttk.Button(buttons, text=library_tr("Anuluj analizę"), command=self.cancel_event.set)
        self.cancel_button.pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text=library_tr("Zamknij"), command=self.close).pack(side="right")
        self.window.bind("<Escape>", lambda event: self.close())

        self.worker = threading.Thread(target=self._worker, name="SwirPhotoCleanLibraryExplorer", daemon=True)
        self.worker.start()
        self.poll_id = self.window.after(50, self._poll)

    def _build_tree(self, parent, title):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=("count", "size"), show="tree headings", selectmode="browse")
        tree.heading("#0", text=title)
        tree.heading("count", text=library_tr("Pliki"))
        tree.heading("size", text=library_tr("Rozmiar"))
        tree.column("#0", width=470, minwidth=220, stretch=True)
        tree.column("count", width=100, anchor="e", stretch=False)
        tree.column("size", width=120, anchor="e", stretch=False)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        return tree

    def _worker(self):
        try:
            report = analyze_library_metadata(
                self.app.result,
                cancel_event=self.cancel_event,
                progress=lambda done, total: self.events.put(("progress", done, total)),
            )
            self.events.put(("done", report))
        except Exception as error:  # defensive worker boundary
            self.events.put(("error", repr(error)))

    def _poll(self):
        if self.closed or not self.window.winfo_exists():
            return
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "progress":
                    _, done, total = event
                    self.progress.configure(maximum=max(1, total), value=done)
                    self.status_var.set(library_tr("Analiza: {v0}/{v1}", v0=done, v1=total))
                elif kind == "done":
                    self._render(event[1])
                    return
                elif kind == "error":
                    self.cancel_button.configure(state="disabled")
                    messagebox.showerror(library_tr("Nie udało się odczytać metadanych"), event[1], parent=self.window)
                    return
        except queue.Empty:
            pass
        self.poll_id = self.window.after(50, self._poll)

    @staticmethod
    def _size(photos):
        return sum(photo.size for photo in photos)

    def _render(self, report: LibraryMetadataReport):
        self.report = report
        self.cancel_button.configure(state="disabled")
        self.progress.configure(value=report.analyzed_count)
        self._render_timeline(report)
        self._render_devices(report)

        if report.cancelled:
            self.status_var.set(
                library_tr(
                    "Analiza anulowana • odczytano {v0} z {v1} • nic nie zmieniono",
                    v0=report.analyzed_count,
                    v1=len(self.app.result.photos),
                )
            )
        else:
            self.status_var.set(
                library_tr(
                    "Gotowe • pliki {v0} • data EXIF {v1} • urządzenie EXIF {v2} • bez daty {v3} • bez urządzenia {v4} • niedostępne {v5}",
                    v0=report.total_count,
                    v1=report.captured_count,
                    v2=report.device_count,
                    v3=report.missing_capture_count,
                    v4=report.missing_device_count,
                    v5=report.unavailable_count,
                )
            )
        has_nodes = bool(self.timeline_nodes or self.device_nodes)
        state = "normal" if has_nodes else "disabled"
        self.open_button.configure(state=state)
        self.copy_button.configure(state=state)

    def _render_timeline(self, report):
        self.timeline_nodes.clear()
        for item in self.timeline_tree.get_children():
            self.timeline_tree.delete(item)
        if not report.timeline:
            iid = "timeline-empty"
            self.timeline_tree.insert("", "end", iid=iid, text=library_tr("Brak wiarygodnej daty EXIF w przeskanowanych zdjęciach."))
            return

        years = defaultdict(list)
        months = defaultdict(list)
        days = {bucket.day: bucket.photos for bucket in report.timeline}
        for bucket in report.timeline:
            years[bucket.day.year].extend(bucket.photos)
            months[(bucket.day.year, bucket.day.month)].extend(bucket.photos)

        for year in sorted(years, reverse=True):
            yid = f"year:{year}"
            yphotos = tuple(years[year])
            self.timeline_nodes[yid] = yphotos
            self.timeline_tree.insert("", "end", iid=yid, text=str(year), values=(len(yphotos), human_size(self._size(yphotos))), open=True)
            month_numbers = sorted((month for y, month in months if y == year), reverse=True)
            for month in month_numbers:
                mid = f"month:{year:04d}-{month:02d}"
                mphotos = tuple(months[(year, month)])
                self.timeline_nodes[mid] = mphotos
                self.timeline_tree.insert(yid, "end", iid=mid, text=f"{year:04d}-{month:02d}", values=(len(mphotos), human_size(self._size(mphotos))), open=True)
                for day in sorted((d for d in days if d.year == year and d.month == month), reverse=True):
                    did = f"day:{day.isoformat()}"
                    dphotos = tuple(days[day])
                    self.timeline_nodes[did] = dphotos
                    self.timeline_tree.insert(mid, "end", iid=did, text=day.isoformat(), values=(len(dphotos), human_size(self._size(dphotos))))

    def _render_devices(self, report):
        self.device_nodes.clear()
        for item in self.device_tree.get_children():
            self.device_tree.delete(item)
        if not report.devices:
            self.device_tree.insert("", "end", iid="device-empty", text=library_tr("Brak pól aparatu/urządzenia EXIF w przeskanowanych zdjęciach."))
            return
        for index, bucket in enumerate(report.devices):
            iid = f"device:{index}"
            self.device_nodes[iid] = bucket.photos
            self.device_tree.insert("", "end", iid=iid, text=bucket.label, values=(len(bucket.photos), human_size(bucket.total_bytes)))

    def _selected_photos(self):
        if self.notebook.index("current") == 0:
            selection = self.timeline_tree.selection()
            return self.timeline_nodes.get(selection[0], ()) if selection else ()
        selection = self.device_tree.selection()
        return self.device_nodes.get(selection[0], ()) if selection else ()

    def copy_paths(self):
        photos = self._selected_photos()
        if not photos:
            messagebox.showinfo(library_tr("Biblioteka EXIF"), library_tr("Wybierz okres lub urządzenie z listy."), parent=self.window)
            return
        text = "\n".join(str(photo.path) for photo in photos)
        self.app.root.clipboard_clear()
        self.app.root.clipboard_append(text)
        self.status_var.set(library_tr("Skopiowano {v0} ścieżek", v0=len(photos)))

    def open_group(self):
        photos = self._selected_photos()
        if not photos:
            messagebox.showinfo(library_tr("Biblioteka EXIF"), library_tr("Wybierz okres lub urządzenie z listy."), parent=self.window)
            return
        paths = {photo.path for photo in photos}
        for group_index, group in enumerate(self.app.result.groups):
            if any(photo.path in paths for photo in group.photos):
                iid = str(group_index)
                if self.app.groups.exists(iid):
                    self.app.groups.selection_set(iid)
                    self.app.groups.focus(iid)
                    self.app.groups.see(iid)
                    self.app.choose_group()
                    self.window.lift()
                    return
        messagebox.showinfo(
            library_tr("Biblioteka EXIF"),
            library_tr("Żaden plik z tego widoku nie należy do grupy duplikatów/podobnych zdjęć."),
            parent=self.window,
        )

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.cancel_event.set()
        try:
            self.window.after_cancel(self.poll_id)
        except (AttributeError, tk.TclError):
            pass
        if self.window.winfo_exists():
            self.window.destroy()


class PhotoCleanApp(SafeModePhotoCleanApp):
    """Current desktop layer plus read-only EXIF timeline and device grouping."""

    def __init__(self, root, settings_path=None):
        self.library_explorer_view = None
        super().__init__(root, settings_path)

    def _install_session_menu(self):
        super()._install_session_menu()
        self.view_menu.add_separator()
        self.view_menu.add_command(
            label=library_tr("Biblioteka EXIF…"),
            command=self.open_library_explorer,
            accelerator=library_tr("Ctrl+Alt+L"),
        )
        self.root.bind("<Control-Alt-l>", lambda event: self.open_library_explorer())
        self.root.bind("<Control-Alt-L>", lambda event: self.open_library_explorer())

    def open_library_explorer(self):
        if self.busy or self.result.cancelled:
            return
        if not self.result.photos:
            messagebox.showinfo(
                library_tr("Brak zdjęć do analizy"),
                library_tr("Najpierw wykonaj lub wczytaj zakończony skan."),
            )
            return
        if self.library_explorer_view is not None and self.library_explorer_view.window.winfo_exists():
            self.library_explorer_view.close()
        self.library_explorer_view = LibraryExplorerWindow(self)


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
