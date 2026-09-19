"""Cancellable read-only blur/exposure review UI.

The worker performs image analysis off the Tk thread. The window only surfaces
review candidates; it never marks files for disposal or changes the scan result.
"""
from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from . import i18n
from .bad_shots import BadShotCandidate, BadShotScan, find_bad_shot_candidates
from .burst_gui import PhotoCleanApp as BurstPhotoCleanApp
from .gui import BG, PANEL, TEXT


BAD_SHOT_EN = {
    "Możliwe słabe zdjęcia…": "Blur / bad-shot review…",
    "Możliwe słabe zdjęcia": "Blur / bad-shot review",
    "Analizowanie zdjęć…": "Analyzing photos…",
    "Analiza lokalna i tylko do przeglądu. Miękkie, ciemne lub jasne zdjęcie może być zamierzone; nic nie jest zaznaczane do kosza.": "Local review-only analysis. A soft, dark or bright photo may be intentional; nothing is selected for Recycle Bin.",
    "Brak zdjęć do analizy": "No photos to analyze",
    "Najpierw wykonaj lub wczytaj zakończony skan.": "Run or load a completed scan first.",
    "Anuluj analizę": "Cancel analysis",
    "Zamknij": "Close",
    "Kopiuj ścieżkę": "Copy path",
    "Otwórz grupę": "Open group",
    "Wybierz wynik z listy.": "Select a result from the list.",
    "To zdjęcie nie należy do grupy duplikatów/podobnych zdjęć.": "This photo is not part of a duplicate/similar group.",
    "Priorytet": "Priority",
    "Zdjęcie": "Photo",
    "Jakość": "Quality",
    "Ostrość": "Sharpness",
    "Ekspozycja": "Exposure",
    "Powód": "Reason",
    "Ścieżka": "Path",
    "możliwe rozmycie": "possible blur",
    "ryzyko ekspozycji": "exposure risk",
    "niska ocena łączna": "low overall score",
    "Analiza: {v0}/{v1}": "Analysis: {v0}/{v1}",
    "Zakończono • przeanalizowano {v0} • kandydaci {v1} • niedostępne {v2} • nic nie zaznaczono do kosza": "Finished • analyzed {v0} • candidates {v1} • unavailable {v2} • nothing selected for Recycle Bin",
    "Pokazano {v0} z {v1} kandydatów o najwyższym priorytecie.": "Showing {v0} of {v1} highest-priority candidates.",
    "Nie wykryto wyraźnych kandydatów do przeglądu według konserwatywnych progów. To nie oznacza, że wszystkie zdjęcia są dobre.": "No clear review candidates crossed the conservative thresholds. This does not mean every photo is good.",
    "Analiza anulowana • przeanalizowano {v0} zdjęć • nic nie zaznaczono do kosza": "Analysis cancelled • analyzed {v0} photos • nothing selected for Recycle Bin",
    "Nie udało się przeanalizować zdjęć": "Photo analysis failed",
    "Ctrl+Shift+B": "Ctrl+Shift+B",
}


def bad_tr(message, **values):
    text = BAD_SHOT_EN.get(message, message) if i18n.language == "en" else message
    return text.format(**values) if values else text


def _reason_text(candidate: BadShotCandidate) -> str:
    labels = {
        "possible-blur": bad_tr("możliwe rozmycie"),
        "exposure-risk": bad_tr("ryzyko ekspozycji"),
        "low-overall": bad_tr("niska ocena łączna"),
    }
    return ", ".join(labels.get(reason, reason) for reason in candidate.reasons)


class BadShotFinderWindow:
    """Analyze a completed scan in a worker and present read-only candidates."""

    def __init__(self, app: "PhotoCleanApp"):
        self.app = app
        self.events: queue.Queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.scan: BadShotScan | None = None
        self.candidates: dict[str, BadShotCandidate] = {}
        self.closed = False

        self.window = tk.Toplevel(app.root)
        self.window.title(bad_tr("Możliwe słabe zdjęcia"))
        self.window.geometry("1120x600")
        self.window.minsize(820, 440)
        self.window.configure(bg=BG)
        self.window.transient(app.root)
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        outer = ttk.Frame(self.window, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(
            outer,
            text=bad_tr(
                "Analiza lokalna i tylko do przeglądu. Miękkie, ciemne lub jasne zdjęcie może być zamierzone; nic nie jest zaznaczane do kosza."
            ),
            wraplength=1040,
        ).pack(anchor="w", pady=(0, 8))

        progress_row = ttk.Frame(outer)
        progress_row.pack(fill="x", pady=(0, 10))
        self.status_var = tk.StringVar(value=bad_tr("Analizowanie zdjęć…"))
        ttk.Label(progress_row, textvariable=self.status_var).pack(side="left", fill="x", expand=True)
        self.progress = ttk.Progressbar(progress_row, mode="determinate", maximum=max(1, len(app.result.photos)))
        self.progress.pack(side="right", fill="x", expand=False, ipadx=120)

        table_frame = ttk.Frame(outer)
        table_frame.pack(fill="both", expand=True)
        columns = ("priority", "photo", "quality", "sharpness", "exposure", "reason", "path")
        self.table = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        headings = {
            "priority": bad_tr("Priorytet"),
            "photo": bad_tr("Zdjęcie"),
            "quality": bad_tr("Jakość"),
            "sharpness": bad_tr("Ostrość"),
            "exposure": bad_tr("Ekspozycja"),
            "reason": bad_tr("Powód"),
            "path": bad_tr("Ścieżka"),
        }
        widths = {
            "priority": 75,
            "photo": 180,
            "quality": 75,
            "sharpness": 80,
            "exposure": 80,
            "reason": 220,
            "path": 380,
        }
        for column in columns:
            self.table.heading(column, text=headings[column])
            self.table.column(column, width=widths[column], minwidth=60, stretch=column in ("reason", "path"))
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.table.bind("<Double-1>", lambda event: self.open_group())
        self.table.bind("<Return>", lambda event: self.open_group())

        buttons = ttk.Frame(outer, padding=(0, 10, 0, 0))
        buttons.pack(fill="x")
        self.open_button = ttk.Button(buttons, text=bad_tr("Otwórz grupę"), command=self.open_group, state="disabled")
        self.open_button.pack(side="left")
        self.copy_button = ttk.Button(buttons, text=bad_tr("Kopiuj ścieżkę"), command=self.copy_path, state="disabled")
        self.copy_button.pack(side="left", padx=8)
        self.cancel_button = ttk.Button(buttons, text=bad_tr("Anuluj analizę"), command=self.cancel_event.set)
        self.cancel_button.pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text=bad_tr("Zamknij"), command=self.close).pack(side="right")
        self.window.bind("<Escape>", lambda event: self.close())

        self.worker = threading.Thread(target=self._worker, name="SwirPhotoCleanBadShotFinder", daemon=True)
        self.worker.start()
        self.poll_id = self.window.after(50, self._poll)

    def _worker(self):
        try:
            result = find_bad_shot_candidates(
                self.app.result.photos,
                cancel_event=self.cancel_event,
                progress=lambda done, total: self.events.put(("progress", done, total)),
            )
            self.events.put(("done", result))
        except Exception as error:  # defensive boundary; worker must not terminate silently
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
                    self.status_var.set(bad_tr("Analiza: {v0}/{v1}", v0=done, v1=total))
                elif kind == "done":
                    self._render_result(event[1])
                    return
                elif kind == "error":
                    self.cancel_button.configure(state="disabled")
                    messagebox.showerror(bad_tr("Nie udało się przeanalizować zdjęć"), event[1], parent=self.window)
                    return
        except queue.Empty:
            pass
        self.poll_id = self.window.after(50, self._poll)

    def _render_result(self, result: BadShotScan):
        self.scan = result
        self.cancel_button.configure(state="disabled")
        self.progress.configure(value=result.analyzed_count)
        self.candidates.clear()
        for item in self.table.get_children():
            self.table.delete(item)

        for index, candidate in enumerate(result.candidates):
            iid = str(index)
            self.candidates[iid] = candidate
            quality = candidate.quality
            self.table.insert(
                "",
                "end",
                iid=iid,
                values=(
                    int(round(candidate.severity)),
                    candidate.photo.path.name,
                    f"{int(round(quality.overall_score))}/100",
                    f"{int(round(quality.sharpness_score))}/100",
                    f"{int(round(quality.exposure_score))}/100",
                    _reason_text(candidate),
                    str(candidate.photo.path),
                ),
            )

        if result.cancelled:
            self.status_var.set(
                bad_tr(
                    "Analiza anulowana • przeanalizowano {v0} zdjęć • nic nie zaznaczono do kosza",
                    v0=result.analyzed_count,
                )
            )
        elif not result.candidates:
            self.status_var.set(
                bad_tr(
                    "Nie wykryto wyraźnych kandydatów do przeglądu według konserwatywnych progów. To nie oznacza, że wszystkie zdjęcia są dobre."
                )
            )
        else:
            status = bad_tr(
                "Zakończono • przeanalizowano {v0} • kandydaci {v1} • niedostępne {v2} • nic nie zaznaczono do kosza",
                v0=result.analyzed_count,
                v1=result.candidate_count,
                v2=result.unavailable_count,
            )
            if result.candidate_count > len(result.candidates):
                status += "  " + bad_tr(
                    "Pokazano {v0} z {v1} kandydatów o najwyższym priorytecie.",
                    v0=len(result.candidates),
                    v1=result.candidate_count,
                )
            self.status_var.set(status)

        state = "normal" if result.candidates else "disabled"
        self.open_button.configure(state=state)
        self.copy_button.configure(state=state)
        if result.candidates:
            self.table.selection_set("0")
            self.table.focus("0")

    def _selected_candidate(self) -> BadShotCandidate | None:
        selection = self.table.selection()
        if not selection:
            return None
        return self.candidates.get(selection[0])

    def copy_path(self):
        candidate = self._selected_candidate()
        if candidate is None:
            messagebox.showinfo(bad_tr("Możliwe słabe zdjęcia"), bad_tr("Wybierz wynik z listy."), parent=self.window)
            return
        self.app.root.clipboard_clear()
        self.app.root.clipboard_append(str(candidate.photo.path))

    def open_group(self):
        candidate = self._selected_candidate()
        if candidate is None:
            messagebox.showinfo(bad_tr("Możliwe słabe zdjęcia"), bad_tr("Wybierz wynik z listy."), parent=self.window)
            return
        target_path = candidate.photo.path
        for group_index, group in enumerate(self.app.result.groups):
            if any(photo.path == target_path for photo in group.photos):
                iid = str(group_index)
                if self.app.groups.exists(iid):
                    self.app.groups.selection_set(iid)
                    self.app.groups.focus(iid)
                    self.app.groups.see(iid)
                    self.app.choose_group()
                    self.window.lift()
                    return
        messagebox.showinfo(
            bad_tr("Możliwe słabe zdjęcia"),
            bad_tr("To zdjęcie nie należy do grupy duplikatów/podobnych zdjęć."),
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


class PhotoCleanApp(BurstPhotoCleanApp):
    """Final desktop app layer with cancellable bad-shot review."""

    def _install_session_menu(self):
        super()._install_session_menu()
        self.view_menu.add_separator()
        self.view_menu.add_command(
            label=bad_tr("Możliwe słabe zdjęcia…"),
            command=self.open_bad_shot_finder,
            accelerator=bad_tr("Ctrl+Shift+B"),
        )
        self.root.bind("<Control-Shift-B>", lambda event: self.open_bad_shot_finder())
        self.root.bind("<Control-Shift-b>", lambda event: self.open_bad_shot_finder())

    def open_bad_shot_finder(self):
        if self.busy or self.result.cancelled:
            return
        if not self.result.photos:
            messagebox.showinfo(
                bad_tr("Brak zdjęć do analizy"),
                bad_tr("Najpierw wykonaj lub wczytaj zakończony skan."),
            )
            return
        BadShotFinderWindow(self)


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
