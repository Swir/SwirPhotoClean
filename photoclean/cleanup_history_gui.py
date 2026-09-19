"""Cleanup history and conservative before/after summaries."""
from __future__ import annotations

import os
import queue
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from . import i18n
from .classification_gui import PhotoCleanApp as ClassificationPhotoCleanApp
from .cleanup_history import (
    CleanupPlan,
    CleanupRecord,
    append_cleanup_record,
    build_cleanup_plan,
    finalize_cleanup_record,
    history_path,
    load_cleanup_history,
)
from .core import recycle_selected
from .gui import BG, MUTED, PANEL, human_size
from .i18n import tr


HISTORY_EN = {
    "Historia czyszczenia…": "Cleanup history…",
    "Historia czyszczenia": "Cleanup history",
    "Ctrl+Alt+H": "Ctrl+Alt+H",
    "Brak zapisanych sesji czyszczenia.": "No cleanup sessions recorded yet.",
    "Historia jest lokalna. Zapisuje ścieżki, rozmiary, SHA-256 i wynik operacji — nigdy zawartość zdjęć.": "History is local. It stores paths, sizes, SHA-256 and operation outcomes — never image contents.",
    "Bajty przeniesione do Kosza nie są wolnym miejscem. „Pewne po opróżnieniu Kosza” liczy tylko ukończone, identyczne bajt w bajt duplikaty z zachowaną kopią.": "Bytes moved to the Recycle Bin are not free space. “Guaranteed after emptying Bin” counts only completed byte-identical duplicate moves with a surviving copy.",
    "Czas": "Time",
    "Wynik": "Result",
    "Przeniesiono": "Moved",
    "Do Kosza": "To Bin",
    "Pewne po opróżnieniu": "Guaranteed after emptying",
    "pełna": "complete",
    "częściowa": "partial",
    "brak zmian": "no moves",
    "Przed": "Before",
    "Po (snapshot)": "After (snapshot)",
    "Żądano": "Requested",
    "Bajty żądane": "Requested bytes",
    "Bajty przeniesione do Kosza": "Bytes moved to Recycle Bin",
    "Pewne bajty do odzyskania po opróżnieniu Kosza": "Guaranteed bytes reclaimable after emptying Recycle Bin",
    "Błędy": "Errors",
    "Pliki sesji": "Session files",
    "przeniesiono": "moved",
    "nie przeniesiono": "not moved",
    "Kopiuj przeniesione ścieżki": "Copy moved paths",
    "Otwórz Kosz Windows": "Open Windows Recycle Bin",
    "Zamknij": "Close",
    "Skopiowano {v0} ścieżek": "Copied {v0} paths",
    "Nie można otworzyć Kosza Windows": "Cannot open Windows Recycle Bin",
    "Kosz Windows można otworzyć tylko w systemie Windows.": "Windows Recycle Bin can only be opened on Windows.",
    "Nie można odczytać historii czyszczenia": "Cannot read cleanup history",
    "Nie zapisano historii czyszczenia": "Cleanup history was not saved",
    "Pliki zostały obsłużone przez normalny bezpieczny tor Kosza, ale lokalny zapis historii nie powiódł się:\n\n{v0}": "Files were handled through the normal safe Recycle Bin path, but the local history record could not be saved:\n\n{v0}",
    "Podsumowanie czyszczenia": "Cleanup summary",
    "Przed: {v0} zdjęć\nPrzeniesiono do Kosza: {v1} • {v2}\nPo (snapshot skanu): {v3} zdjęć\nPewne po opróżnieniu Kosza: {v4}\n\nKosz nadal zajmuje miejsce na dysku, dopóki nie zostanie opróżniony. Przywracanie odbywa się przez Kosz Windows.": "Before: {v0} photos\nMoved to Recycle Bin: {v1} • {v2}\nAfter (scan snapshot): {v3} photos\nGuaranteed after emptying Recycle Bin: {v4}\n\nThe Recycle Bin still uses disk space until it is emptied. Restore files through Windows Recycle Bin.",
}


def history_tr(message, **values):
    text = HISTORY_EN.get(message, message) if i18n.language == "en" else message
    return text.format(**values) if values else text


def _display_time(value: str) -> str:
    return value.replace("T", " ").replace("+00:00", " UTC")


class CleanupHistoryWindow:
    """Read-only local audit browser. It never performs restore or cleanup."""

    def __init__(self, app: "PhotoCleanApp", records: tuple[CleanupRecord, ...]):
        self.app = app
        self.records = tuple(reversed(records))
        self.record_nodes: dict[str, CleanupRecord] = {}
        self.window = tk.Toplevel(app.root)
        self.window.title(history_tr("Historia czyszczenia"))
        self.window.geometry("1080x650")
        self.window.minsize(780, 500)
        self.window.configure(bg=BG)
        self.window.transient(app.root)

        outer = ttk.Frame(self.window, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(
            outer,
            text=history_tr("Historia jest lokalna. Zapisuje ścieżki, rozmiary, SHA-256 i wynik operacji — nigdy zawartość zdjęć."),
            wraplength=1030,
        ).pack(anchor="w")
        ttk.Label(
            outer,
            text=history_tr("Bajty przeniesione do Kosza nie są wolnym miejscem. „Pewne po opróżnieniu Kosza” liczy tylko ukończone, identyczne bajt w bajt duplikaty z zachowaną kopią."),
            style="Muted.TLabel",
            wraplength=1030,
        ).pack(anchor="w", pady=(3, 10))

        panes = ttk.Panedwindow(outer, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left = ttk.Frame(panes, padding=(0, 0, 6, 0))
        right = ttk.Frame(panes, padding=(6, 0, 0, 0))
        panes.add(left, weight=2)
        panes.add(right, weight=3)

        self.tree = ttk.Treeview(
            left,
            columns=("time", "result", "moved", "bytes", "guaranteed"),
            show="headings",
            selectmode="browse",
        )
        headings = (
            ("time", history_tr("Czas"), 170),
            ("result", history_tr("Wynik"), 90),
            ("moved", history_tr("Przeniesiono"), 80),
            ("bytes", history_tr("Do Kosza"), 100),
            ("guaranteed", history_tr("Pewne po opróżnieniu"), 125),
        )
        for key, label, width in headings:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=60, stretch=key == "time")
        scrollbar = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda event: self._render_detail())

        self.detail = tk.Text(
            right,
            wrap="word",
            bg=PANEL,
            fg="#eef4ff",
            insertbackground="#eef4ff",
            relief="flat",
            padx=10,
            pady=10,
            font=("Consolas", 10),
        )
        detail_scroll = ttk.Scrollbar(right, orient="vertical", command=self.detail.yview)
        self.detail.configure(yscrollcommand=detail_scroll.set)
        self.detail.pack(side="left", fill="both", expand=True)
        detail_scroll.pack(side="right", fill="y")

        buttons = ttk.Frame(outer, padding=(0, 10, 0, 0))
        buttons.pack(fill="x")
        self.copy_button = ttk.Button(buttons, text=history_tr("Kopiuj przeniesione ścieżki"), command=self.copy_paths, state="disabled")
        self.copy_button.pack(side="left")
        self.recycle_button = ttk.Button(buttons, text=history_tr("Otwórz Kosz Windows"), command=self.open_recycle_bin)
        self.recycle_button.pack(side="left", padx=8)
        if os.name != "nt":
            self.recycle_button.configure(state="disabled")
        ttk.Button(buttons, text=history_tr("Zamknij"), command=self.window.destroy).pack(side="right")
        self.window.bind("<Escape>", lambda event: self.window.destroy())

        self._populate()

    def _populate(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        self.record_nodes.clear()
        for index, record in enumerate(self.records):
            iid = f"session:{index}"
            self.record_nodes[iid] = record
            if record.fully_completed:
                result = history_tr("pełna")
            elif record.completed_count:
                result = history_tr("częściowa")
            else:
                result = history_tr("brak zmian")
            self.tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    _display_time(record.finished_at),
                    result,
                    f"{record.completed_count}/{record.requested_count}",
                    human_size(record.moved_to_recycle_bytes),
                    human_size(record.guaranteed_reclaimable_after_bin_empty),
                ),
            )
        children = self.tree.get_children()
        if children:
            self.tree.selection_set(children[0])
            self.tree.focus(children[0])
            self._render_detail()
        else:
            self.detail.configure(state="normal")
            self.detail.delete("1.0", "end")
            self.detail.insert("1.0", history_tr("Brak zapisanych sesji czyszczenia."))
            self.detail.configure(state="disabled")

    def _selected_record(self):
        selection = self.tree.selection()
        return self.record_nodes.get(selection[0]) if selection else None

    def _render_detail(self):
        record = self._selected_record()
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        if record is None:
            self.copy_button.configure(state="disabled")
            self.detail.configure(state="disabled")
            return
        lines = [
            f"{history_tr('Przed')}: {record.scan_photo_count_before}",
            f"{history_tr('Po (snapshot)')}: {record.scan_photo_count_after_snapshot}",
            f"{history_tr('Żądano')}: {record.requested_count}",
            f"{history_tr('Przeniesiono')}: {record.completed_count}",
            f"{history_tr('Bajty żądane')}: {human_size(record.requested_bytes)}",
            f"{history_tr('Bajty przeniesione do Kosza')}: {human_size(record.moved_to_recycle_bytes)}",
            f"{history_tr('Pewne bajty do odzyskania po opróżnieniu Kosza')}: {human_size(record.guaranteed_reclaimable_after_bin_empty)}",
            "",
            f"{history_tr('Pliki sesji')}:"
        ]
        for item in record.entries:
            state = history_tr("przeniesiono") if item.status == "moved" else history_tr("nie przeniesiono")
            lines.append(f"[{state}] {item.path}\n  SHA-256: {item.digest}\n  {human_size(item.size)}")
        if record.errors:
            lines.extend(("", f"{history_tr('Błędy')}:", *record.errors))
        self.detail.insert("1.0", "\n".join(lines))
        self.detail.configure(state="disabled")
        self.copy_button.configure(state="normal" if record.moved_paths else "disabled")

    def copy_paths(self):
        record = self._selected_record()
        if record is None or not record.moved_paths:
            return
        self.app.root.clipboard_clear()
        self.app.root.clipboard_append("\n".join(record.moved_paths))
        self.app.status.set(history_tr("Skopiowano {v0} ścieżek", v0=len(record.moved_paths)))

    def open_recycle_bin(self):
        if os.name != "nt":
            messagebox.showinfo(history_tr("Historia czyszczenia"), history_tr("Kosz Windows można otworzyć tylko w systemie Windows."), parent=self.window)
            return
        try:
            subprocess.Popen(["explorer.exe", "shell:RecycleBinFolder"], close_fds=True)
        except OSError as error:
            messagebox.showerror(history_tr("Nie można otworzyć Kosza Windows"), str(error), parent=self.window)


class PhotoCleanApp(ClassificationPhotoCleanApp):
    """Final desktop layer with local cleanup audit/history."""

    def __init__(self, root, settings_path=None):
        self.cleanup_history_path = history_path(settings_path)
        self.cleanup_history_view = None
        self.last_cleanup_record: CleanupRecord | None = None
        self._audit_events: queue.Queue = queue.Queue()
        super().__init__(root, settings_path)

    def _install_session_menu(self):
        super()._install_session_menu()
        self.view_menu.add_separator()
        self.view_menu.add_command(
            label=history_tr("Historia czyszczenia…"),
            command=self.open_cleanup_history,
            accelerator=history_tr("Ctrl+Alt+H"),
        )
        self.root.bind("<Control-Alt-h>", lambda event: self.open_cleanup_history())
        self.root.bind("<Control-Alt-H>", lambda event: self.open_cleanup_history())

    def open_cleanup_history(self):
        try:
            records = load_cleanup_history(self.cleanup_history_path)
        except ValueError as error:
            messagebox.showerror(history_tr("Nie można odczytać historii czyszczenia"), str(error))
            return
        try:
            if self.cleanup_history_view is not None and self.cleanup_history_view.window.winfo_exists():
                self.cleanup_history_view.window.destroy()
        except tk.TclError:
            pass
        self.cleanup_history_view = CleanupHistoryWindow(self, records)

    def confirm_recycle(self):
        if self.safe_mode.get():
            return super().confirm_recycle()
        if self.busy or not self.marked:
            return
        names = "\n".join(str(path) for path in sorted(self.marked)[:8])
        if len(self.marked) > 8:
            names += tr("\n… i {v0} kolejnych", v0=len(self.marked) - 8)
        if not messagebox.askyesno(
            tr("Potwierdź przeniesienie do kosza"),
            tr(
                "Przenieść {v0} plików do systemowego kosza?\n\n{v1}\n\nPodobne zdjęcia mogą przedstawiać różne ujęcia. Przywracanie odbywa się przez Kosz Windows.",
                v0=len(self.marked),
                v1=names,
            ),
            default="no",
        ):
            return
        self.cancel.clear()
        chosen = set(self.marked)
        try:
            plan = build_cleanup_plan(self.result, chosen)
        except ValueError as error:
            messagebox.showerror("SWIR PhotoClean", str(error))
            return
        self.set_busy(True)

        def worker():
            try:
                completed, errors = recycle_selected(self.result, chosen, self.cancel, progress=self.progress)
            except Exception as error:
                completed, errors = [], [str(error)]
            try:
                record = finalize_cleanup_record(plan, completed, errors)
                self.last_cleanup_record = record
                try:
                    append_cleanup_record(self.cleanup_history_path, record)
                    self._audit_events.put(("record", record, None))
                except (OSError, ValueError) as history_error:
                    self._audit_events.put(("record", record, str(history_error)))
            finally:
                self.events.put(("recycle", (completed, errors)))

        threading.Thread(target=worker, name="SwirPhotoCleanRecycleAudit", daemon=True).start()

    def poll(self):
        super().poll()
        try:
            root_exists = bool(self.root.winfo_exists())
        except tk.TclError:
            root_exists = False
        if not root_exists:
            return
        try:
            while True:
                kind, record, history_error = self._audit_events.get_nowait()
                if kind != "record":
                    continue
                self.last_cleanup_record = record
                if history_error and not self.closing:
                    messagebox.showwarning(
                        history_tr("Nie zapisano historii czyszczenia"),
                        history_tr(
                            "Pliki zostały obsłużone przez normalny bezpieczny tor Kosza, ale lokalny zapis historii nie powiódł się:\n\n{v0}",
                            v0=history_error,
                        ),
                    )
                if record.completed_count and not self.closing:
                    messagebox.showinfo(
                        history_tr("Podsumowanie czyszczenia"),
                        history_tr(
                            "Przed: {v0} zdjęć\nPrzeniesiono do Kosza: {v1} • {v2}\nPo (snapshot skanu): {v3} zdjęć\nPewne po opróżnieniu Kosza: {v4}\n\nKosz nadal zajmuje miejsce na dysku, dopóki nie zostanie opróżniony. Przywracanie odbywa się przez Kosz Windows.",
                            v0=record.scan_photo_count_before,
                            v1=record.completed_count,
                            v2=human_size(record.moved_to_recycle_bytes),
                            v3=record.scan_photo_count_after_snapshot,
                            v4=human_size(record.guaranteed_reclaimable_after_bin_empty),
                        ),
                    )
        except queue.Empty:
            pass


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
