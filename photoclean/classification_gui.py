"""Read-only media-type inspector with conservative screenshot/graphic hints."""
from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from . import i18n
from .classification import MediaInspectionReport, analyze_media_types
from .gui import BG, human_size
from .library_gui import PhotoCleanApp as LibraryPhotoCleanApp


MEDIA_EN = {
    "Typy obrazu…": "Media types…",
    "Analiza typów obrazu": "Media type inspector",
    "Ctrl+Alt+M": "Ctrl+Alt+M",
    "Brak zdjęć do analizy": "No photos to analyze",
    "Najpierw wykonaj lub wczytaj zakończony skan.": "Run or load a completed scan first.",
    "Analizowanie typów obrazu…": "Inspecting media types…",
    "Analiza: {v0}/{v1}": "Analysis: {v0}/{v1}",
    "Anuluj analizę": "Cancel analysis",
    "Zamknij": "Close",
    "Kategoria": "Category",
    "Pliki": "Files",
    "Rozmiar": "Size",
    "Nazwa pliku": "File name",
    "Wymiary": "Dimensions",
    "Format": "Format",
    "Pewność": "Confidence",
    "Powód": "Reason",
    "Kopiuj ścieżki": "Copy paths",
    "Otwórz pasującą grupę": "Open matching group",
    "Wybierz kategorię z listy.": "Select a category from the list.",
    "Żaden plik z tego widoku nie należy do grupy duplikatów/podobnych zdjęć.": "No file in this view belongs to a duplicate/similar group.",
    "Gotowe • pliki {v0} • aparat {v1} • screenshot kandydaci {v2} • grafiki {v3} • nieokreślone {v4} • niedostępne {v5}": "Finished • files {v0} • camera {v1} • screenshot candidates {v2} • graphics {v3} • unknown {v4} • unavailable {v5}",
    "Analiza anulowana • odczytano {v0} z {v1} • nic nie zmieniono": "Analysis cancelled • read {v0} of {v1} • nothing changed",
    "Nie udało się przeanalizować typów obrazu": "Media type analysis failed",
    "To narzędzie działa lokalnie i tylko do odczytu. „Screenshot” oznacza konserwatywnego kandydata, nie pewną diagnozę. Zdjęcia z EXIF aparatu mają pierwszeństwo; memów nie oznaczamy automatycznie bez wiarygodnego lokalnego sygnału.": "This tool is local and read-only. “Screenshot” means a conservative candidate, not a certain diagnosis. Camera EXIF takes precedence; memes are not auto-labeled without reliable local evidence.",
    "Zdjęcia z aparatu": "Camera photos",
    "Kandydaci: screenshot": "Screenshot candidates",
    "Grafiki": "Graphics",
    "Nieokreślone": "Unknown",
    "wysoka": "high",
    "średnia": "medium",
    "niska": "low",
    "EXIF aparatu": "camera EXIF",
    "data wykonania EXIF": "EXIF capture timestamp",
    "popularny rozmiar ekranu": "common screen dimensions",
    "format PNG/WebP": "PNG/WebP format",
    "brak EXIF aparatu": "no camera EXIF",
    "kanał alfa": "alpha channel",
    "tryb paletowy": "palette mode",
    "format graficzny": "graphic-friendly format",
    "za mało wiarygodnych sygnałów": "insufficient reliable evidence",
    "plik niedostępny": "file unavailable",
    "Skopiowano {v0} ścieżek": "Copied {v0} paths",
}


_CATEGORY_TEXT = {
    "camera_photo": "Zdjęcia z aparatu",
    "screenshot_candidate": "Kandydaci: screenshot",
    "graphic_candidate": "Grafiki",
    "unknown": "Nieokreślone",
}
_CONFIDENCE_TEXT = {"high": "wysoka", "medium": "średnia", "low": "niska"}
_REASON_TEXT = {
    "camera_metadata": "EXIF aparatu",
    "capture_timestamp": "data wykonania EXIF",
    "common_screen_dimensions": "popularny rozmiar ekranu",
    "screen_friendly_format": "format PNG/WebP",
    "no_camera_metadata": "brak EXIF aparatu",
    "alpha_channel": "kanał alfa",
    "palette_mode": "tryb paletowy",
    "graphic_friendly_format": "format graficzny",
    "insufficient_evidence": "za mało wiarygodnych sygnałów",
    "unavailable": "plik niedostępny",
}


def media_tr(message, **values):
    text = MEDIA_EN.get(message, message) if i18n.language == "en" else message
    return text.format(**values) if values else text


def category_text(category: str) -> str:
    return media_tr(_CATEGORY_TEXT.get(category, category))


def confidence_text(confidence: str) -> str:
    return media_tr(_CONFIDENCE_TEXT.get(confidence, confidence))


def reasons_text(reasons) -> str:
    return ", ".join(media_tr(_REASON_TEXT.get(reason, reason)) for reason in reasons)


class MediaInspectorWindow:
    """Cancellable, read-only classification window for a completed scan."""

    def __init__(self, app: "PhotoCleanApp"):
        self.app = app
        self.events: queue.Queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.report: MediaInspectionReport | None = None
        self.closed = False
        self.category_nodes: dict[str, tuple] = {}
        self.item_nodes: dict[str, object] = {}

        self.window = tk.Toplevel(app.root)
        self.window.title(media_tr("Analiza typów obrazu"))
        self.window.geometry("1120x690")
        self.window.minsize(820, 520)
        self.window.configure(bg=BG)
        self.window.transient(app.root)
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        outer = ttk.Frame(self.window, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(
            outer,
            text=media_tr(
                "To narzędzie działa lokalnie i tylko do odczytu. „Screenshot” oznacza konserwatywnego kandydata, nie pewną diagnozę. Zdjęcia z EXIF aparatu mają pierwszeństwo; memów nie oznaczamy automatycznie bez wiarygodnego lokalnego sygnału."
            ),
            wraplength=1060,
        ).pack(anchor="w", pady=(0, 8))

        progress_row = ttk.Frame(outer)
        progress_row.pack(fill="x", pady=(0, 10))
        self.status_var = tk.StringVar(value=media_tr("Analizowanie typów obrazu…"))
        ttk.Label(progress_row, textvariable=self.status_var).pack(side="left", fill="x", expand=True)
        self.progress = ttk.Progressbar(progress_row, mode="determinate", maximum=max(1, len(app.result.photos)))
        self.progress.pack(side="right", ipadx=110)

        panes = ttk.Panedwindow(outer, orient="horizontal")
        panes.pack(fill="both", expand=True)

        left = ttk.Frame(panes, padding=(0, 0, 6, 0))
        right = ttk.Frame(panes, padding=(6, 0, 0, 0))
        panes.add(left, weight=1)
        panes.add(right, weight=3)

        self.category_tree = ttk.Treeview(
            left,
            columns=("category", "count", "size"),
            show="headings",
            selectmode="browse",
        )
        self.category_tree.heading("count", text=media_tr("Pliki"))
        self.category_tree.heading("size", text=media_tr("Rozmiar"))
        self.category_tree.column("count", width=80, anchor="e", stretch=False)
        self.category_tree.column("size", width=100, anchor="e", stretch=False)
        self.category_tree.heading("category", text=media_tr("Kategoria"))
        self.category_tree.column("category", width=210, minwidth=150, stretch=True)
        self.category_tree.pack(fill="both", expand=True)

        item_frame = ttk.Frame(right)
        item_frame.pack(fill="both", expand=True)
        self.item_tree = ttk.Treeview(
            item_frame,
            columns=("dimensions", "format", "confidence", "reason"),
            show="tree headings",
            selectmode="browse",
        )
        self.item_tree.heading("#0", text=media_tr("Nazwa pliku"))
        self.item_tree.heading("dimensions", text=media_tr("Wymiary"))
        self.item_tree.heading("format", text=media_tr("Format"))
        self.item_tree.heading("confidence", text=media_tr("Pewność"))
        self.item_tree.heading("reason", text=media_tr("Powód"))
        self.item_tree.column("#0", width=230, minwidth=130, stretch=True)
        self.item_tree.column("dimensions", width=105, anchor="center", stretch=False)
        self.item_tree.column("format", width=80, anchor="center", stretch=False)
        self.item_tree.column("confidence", width=90, anchor="center", stretch=False)
        self.item_tree.column("reason", width=360, minwidth=180, stretch=True)
        item_scroll = ttk.Scrollbar(item_frame, orient="vertical", command=self.item_tree.yview)
        self.item_tree.configure(yscrollcommand=item_scroll.set)
        self.item_tree.pack(side="left", fill="both", expand=True)
        item_scroll.pack(side="right", fill="y")

        self.category_tree.bind("<<TreeviewSelect>>", lambda event: self._render_selected_category())
        self.item_tree.bind("<Double-1>", lambda event: self.open_group())

        buttons = ttk.Frame(outer, padding=(0, 10, 0, 0))
        buttons.pack(fill="x")
        self.open_button = ttk.Button(
            buttons,
            text=media_tr("Otwórz pasującą grupę"),
            command=self.open_group,
            state="disabled",
        )
        self.open_button.pack(side="left")
        self.copy_button = ttk.Button(
            buttons,
            text=media_tr("Kopiuj ścieżki"),
            command=self.copy_paths,
            state="disabled",
        )
        self.copy_button.pack(side="left", padx=8)
        self.cancel_button = ttk.Button(buttons, text=media_tr("Anuluj analizę"), command=self.cancel_event.set)
        self.cancel_button.pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text=media_tr("Zamknij"), command=self.close).pack(side="right")
        self.window.bind("<Escape>", lambda event: self.close())

        self.worker = threading.Thread(target=self._worker, name="SwirPhotoCleanMediaInspector", daemon=True)
        self.worker.start()
        self.poll_id = self.window.after(50, self._poll)

    def _worker(self):
        try:
            report = analyze_media_types(
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
                    self.status_var.set(media_tr("Analiza: {v0}/{v1}", v0=done, v1=total))
                elif kind == "done":
                    self._render(event[1])
                    return
                elif kind == "error":
                    self.cancel_button.configure(state="disabled")
                    messagebox.showerror(
                        media_tr("Nie udało się przeanalizować typów obrazu"),
                        event[1],
                        parent=self.window,
                    )
                    return
        except queue.Empty:
            pass
        self.poll_id = self.window.after(50, self._poll)

    def _render(self, report: MediaInspectionReport):
        self.report = report
        self.cancel_button.configure(state="disabled")
        self.progress.configure(value=report.analyzed_count)
        self.category_nodes.clear()
        for row in self.category_tree.get_children():
            self.category_tree.delete(row)

        for index, bucket in enumerate(report.buckets):
            iid = f"category:{index}"
            self.category_nodes[iid] = bucket.photos
            self.category_tree.insert(
                "",
                "end",
                iid=iid,
                values=(category_text(bucket.category), len(bucket.photos), human_size(bucket.total_bytes)),
            )

        if report.cancelled:
            self.status_var.set(
                media_tr(
                    "Analiza anulowana • odczytano {v0} z {v1} • nic nie zmieniono",
                    v0=report.analyzed_count,
                    v1=len(self.app.result.photos),
                )
            )
        else:
            self.status_var.set(
                media_tr(
                    "Gotowe • pliki {v0} • aparat {v1} • screenshot kandydaci {v2} • grafiki {v3} • nieokreślone {v4} • niedostępne {v5}",
                    v0=report.total_count,
                    v1=report.count("camera_photo"),
                    v2=report.count("screenshot_candidate"),
                    v3=report.count("graphic_candidate"),
                    v4=report.count("unknown"),
                    v5=report.unavailable_count,
                )
            )

        children = self.category_tree.get_children()
        if children:
            preferred = next(
                (
                    iid
                    for iid in children
                    if self.category_tree.set(iid, "category") == category_text("screenshot_candidate")
                ),
                children[0],
            )
            self.category_tree.selection_set(preferred)
            self.category_tree.focus(preferred)
            self._render_selected_category()
            self.copy_button.configure(state="normal")
            self.open_button.configure(state="normal")
        else:
            self.copy_button.configure(state="disabled")
            self.open_button.configure(state="disabled")

    def _selected_category_photos(self):
        selection = self.category_tree.selection()
        return self.category_nodes.get(selection[0], ()) if selection else ()

    def _render_selected_category(self):
        if self.report is None:
            return
        selected = {photo.path for photo in self._selected_category_photos()}
        self.item_nodes.clear()
        for row in self.item_tree.get_children():
            self.item_tree.delete(row)
        if not selected:
            return
        visible = [item for item in self.report.items if item.photo.path in selected]
        visible.sort(key=lambda item: str(item.photo.path).casefold())
        for index, item in enumerate(visible):
            iid = f"item:{index}"
            self.item_nodes[iid] = item
            self.item_tree.insert(
                "",
                "end",
                iid=iid,
                text=item.photo.path.name,
                values=(
                    item.dimensions,
                    item.image_format or "?",
                    confidence_text(item.confidence),
                    reasons_text(item.reasons),
                ),
            )

    def copy_paths(self):
        photos = self._selected_category_photos()
        if not photos:
            messagebox.showinfo(
                media_tr("Analiza typów obrazu"),
                media_tr("Wybierz kategorię z listy."),
                parent=self.window,
            )
            return
        text = "\n".join(str(photo.path) for photo in photos)
        self.app.root.clipboard_clear()
        self.app.root.clipboard_append(text)
        self.status_var.set(media_tr("Skopiowano {v0} ścieżek", v0=len(photos)))

    def open_group(self):
        item_selection = self.item_tree.selection()
        if item_selection:
            item = self.item_nodes.get(item_selection[0])
            paths = {item.photo.path} if item is not None else set()
        else:
            paths = {photo.path for photo in self._selected_category_photos()}
        if not paths:
            messagebox.showinfo(
                media_tr("Analiza typów obrazu"),
                media_tr("Wybierz kategorię z listy."),
                parent=self.window,
            )
            return
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
            media_tr("Analiza typów obrazu"),
            media_tr("Żaden plik z tego widoku nie należy do grupy duplikatów/podobnych zdjęć."),
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


class PhotoCleanApp(LibraryPhotoCleanApp):
    """Current desktop layer plus read-only media-type inspection."""

    def __init__(self, root, settings_path=None):
        self.media_inspector_view = None
        super().__init__(root, settings_path)

    def _install_session_menu(self):
        super()._install_session_menu()
        self.view_menu.add_command(
            label=media_tr("Typy obrazu…"),
            command=self.open_media_inspector,
            accelerator=media_tr("Ctrl+Alt+M"),
        )
        self.root.bind("<Control-Alt-m>", lambda event: self.open_media_inspector())
        self.root.bind("<Control-Alt-M>", lambda event: self.open_media_inspector())

    def open_media_inspector(self):
        if self.busy or self.result.cancelled:
            return
        if not self.result.photos:
            messagebox.showinfo(
                media_tr("Brak zdjęć do analizy"),
                media_tr("Najpierw wykonaj lub wczytaj zakończony skan."),
            )
            return
        if self.media_inspector_view is not None and self.media_inspector_view.window.winfo_exists():
            self.media_inspector_view.close()
        self.media_inspector_view = MediaInspectorWindow(self)


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
