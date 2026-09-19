"""Review ergonomics and keyboard-first workflow for the final desktop layer."""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox, ttk

from . import i18n
from .gui import human_size
from .i18n import tr
from .insights import recommend_keeper
from .performance_gui import PhotoCleanApp as PerformancePhotoCleanApp
from .review_power import filter_sort_photo_indices, move_selection


REVIEW_EN = {
    "Filtr:": "Filter:",
    "Sortuj:": "Sort:",
    "Pokazuj:": "Show:",
    "Wszystkie": "All",
    "Tylko zaznaczone": "Marked only",
    "Tylko niezaznaczone": "Unmarked only",
    "Smart Keep najpierw": "Smart Keep first",
    "Kolejność skanu": "Scan order",
    "Nazwa A→Z": "Name A→Z",
    "Największy plik": "Largest file",
    "Największa rozdzielczość": "Highest resolution",
    "Widoczne {v0}/{v1} • do Kosza {v2}": "Visible {v0}/{v1} • marked {v2}",
    "Tryb klawiaturowy…": "Keyboard Power Mode…",
    "Tryb klawiaturowy": "Keyboard Power Mode",
    "Skróty przyspieszają review, ale nie mają skrótu do przenoszenia plików do Kosza. Operacja Kosza nadal wymaga jawnego przycisku i potwierdzenia.": (
        "Shortcuts speed up review, but there is deliberately no shortcut for moving files to the Recycle Bin. "
        "Cleanup still requires the explicit button and confirmation."
    ),
    "Ctrl+F — filtr bieżącej grupy\nCtrl+1 / Ctrl+2 / Ctrl+3 — wszystkie / zaznaczone / niezaznaczone\nCtrl+↑ / Ctrl+↓ — poprzednia / następna grupa\nAlt+↑ / Alt+↓ — poprzedni / następny widoczny plik\nCtrl+M — zaznacz / odznacz wybrane do Kosza\nCtrl+Shift+M — wyczyść wszystkie zaznaczenia\nCtrl+C — kopiuj ścieżki (gdy aktywna jest lista plików)\nF11 — pełnoekranowe porównanie dwóch wybranych zdjęć\nF1 — ta pomoc": (
        "Ctrl+F — filter the current group\n"
        "Ctrl+1 / Ctrl+2 / Ctrl+3 — all / marked / unmarked rows\n"
        "Ctrl+↑ / Ctrl+↓ — previous / next group\n"
        "Alt+↑ / Alt+↓ — previous / next visible file\n"
        "Ctrl+M — mark / unmark selected files for Recycle Bin\n"
        "Ctrl+Shift+M — clear all marks\n"
        "Ctrl+C — copy paths (when the file list is focused)\n"
        "F11 — fullscreen compare for two selected photos\n"
        "F1 — this help"
    ),
}


def review_tr(message, **values):
    text = REVIEW_EN.get(message, message) if i18n.language == "en" else message
    return text.format(**values) if values else text


class PhotoCleanApp(PerformancePhotoCleanApp):
    """Final app layer with deterministic review filter/sort and safe shortcuts."""

    SORT_LABEL_KEYS = (
        ("recommended", "Smart Keep najpierw"),
        ("original", "Kolejność skanu"),
        ("name", "Nazwa A→Z"),
        ("size_desc", "Największy plik"),
        ("resolution_desc", "Największa rozdzielczość"),
    )
    SCOPE_LABEL_KEYS = (
        ("all", "Wszystkie"),
        ("marked", "Tylko zaznaczone"),
        ("unmarked", "Tylko niezaznaczone"),
    )

    def __init__(self, root, settings_path=None):
        self.review_filter_var = tk.StringVar(master=root, value="")
        self.review_sort_mode = "recommended"
        self.review_scope = "all"
        self.review_sort_label = tk.StringVar(master=root)
        self.review_scope_label = tk.StringVar(master=root)
        self.review_visible_var = tk.StringVar(master=root)
        self.review_sort_labels = {}
        self.review_scope_labels = {}
        super().__init__(root, settings_path)

    def _build(self, root):
        super()._build(root)
        self._install_review_controls()

    def _install_review_controls(self):
        # Keep review controls on their own row. The primary mark/copy actions
        # remain usable at the supported 900 px minimum window width and HiDPI.
        actions = self.mark_button.master
        review_row = ttk.Frame(actions.master, padding=(12, 0, 0, 4))
        review_row.pack(fill="x", before=self.preview_frame)
        self.review_controls = review_row

        self.review_sort_labels = {
            review_tr(label): mode for mode, label in self.SORT_LABEL_KEYS
        }
        self.review_scope_labels = {
            review_tr(label): mode for mode, label in self.SCOPE_LABEL_KEYS
        }
        current_sort_label = next(
            (
                label
                for label, mode in self.review_sort_labels.items()
                if mode == self.review_sort_mode
            ),
            review_tr("Smart Keep najpierw"),
        )
        current_scope_label = next(
            (
                label
                for label, mode in self.review_scope_labels.items()
                if mode == self.review_scope
            ),
            review_tr("Wszystkie"),
        )
        self.review_sort_label.set(current_sort_label)
        self.review_scope_label.set(current_scope_label)
        self.review_visible_var.set(
            review_tr("Widoczne {v0}/{v1} • do Kosza {v2}", v0=0, v1=0, v2=0)
        )

        ttk.Label(review_row, text=review_tr("Filtr:"), style="Muted.TLabel").pack(
            side="left"
        )
        self.review_filter_entry = ttk.Entry(
            review_row, textvariable=self.review_filter_var, width=18
        )
        self.review_filter_entry.pack(side="left", fill="x", expand=True, padx=(4, 10))
        self.review_filter_entry.bind(
            "<KeyRelease>", lambda event: self._apply_review_view()
        )
        self.review_filter_entry.bind("<Escape>", self._clear_review_filter)

        ttk.Label(review_row, text=review_tr("Sortuj:"), style="Muted.TLabel").pack(
            side="left"
        )
        self.review_sort_box = ttk.Combobox(
            review_row,
            textvariable=self.review_sort_label,
            values=tuple(self.review_sort_labels),
            state="readonly",
            width=19,
        )
        self.review_sort_box.pack(side="left", padx=(4, 10))
        self.review_sort_box.bind("<<ComboboxSelected>>", self._review_sort_changed)

        ttk.Label(review_row, text=review_tr("Pokazuj:"), style="Muted.TLabel").pack(
            side="left"
        )
        self.review_scope_box = ttk.Combobox(
            review_row,
            textvariable=self.review_scope_label,
            values=tuple(self.review_scope_labels),
            state="readonly",
            width=16,
        )
        self.review_scope_box.pack(side="left", padx=(4, 10))
        self.review_scope_box.bind("<<ComboboxSelected>>", self._review_scope_changed)

        self.review_visible_label = ttk.Label(
            review_row, textvariable=self.review_visible_var, style="Muted.TLabel"
        )
        self.review_visible_label.pack(side="right")

    def _install_session_menu(self):
        super()._install_session_menu()
        self.view_menu.add_separator()
        self.view_menu.add_command(
            label=review_tr("Tryb klawiaturowy…"),
            command=self.show_keyboard_help,
            accelerator="F1",
        )
        self.root.bind("<Control-f>", self._focus_review_filter)
        self.root.bind("<Control-F>", self._focus_review_filter)
        self.root.bind("<Control-Key-1>", lambda event: self._scope_shortcut("all"))
        self.root.bind("<Control-Key-2>", lambda event: self._scope_shortcut("marked"))
        self.root.bind("<Control-Key-3>", lambda event: self._scope_shortcut("unmarked"))
        self.root.bind("<Control-Up>", lambda event: self._move_group(-1))
        self.root.bind("<Control-Down>", lambda event: self._move_group(1))
        self.root.bind("<Alt-Up>", lambda event: self._move_file(-1))
        self.root.bind("<Alt-Down>", lambda event: self._move_file(1))
        self.root.bind("<Control-m>", self._toggle_mark_shortcut)
        self.root.bind("<Control-Shift-M>", self._clear_marks_shortcut)
        self.root.bind("<F1>", lambda event: self.show_keyboard_help())
        self.files.bind("<Control-c>", self._copy_shortcut)
        self.files.bind("<Control-C>", self._copy_shortcut)

    def _review_sort_changed(self, event=None):
        self.review_sort_mode = self.review_sort_labels.get(
            self.review_sort_label.get(), "recommended"
        )
        self._apply_review_view()

    def _review_scope_changed(self, event=None):
        self.review_scope = self.review_scope_labels.get(
            self.review_scope_label.get(), "all"
        )
        self._apply_review_view()

    def _focus_review_filter(self, event=None):
        self.review_filter_entry.focus_set()
        self.review_filter_entry.selection_range(0, "end")
        return "break"

    def _clear_review_filter(self, event=None):
        if self.review_filter_var.get():
            self.review_filter_var.set("")
            self._apply_review_view()
        self.files.focus_set()
        return "break"

    def _typing_focus(self):
        focus = self.root.focus_get()
        if focus is None:
            return False
        try:
            return focus.winfo_class() in {
                "Entry",
                "TEntry",
                "TCombobox",
                "Text",
                "Spinbox",
                "TSpinbox",
            }
        except tk.TclError:
            return False

    def _scope_shortcut(self, scope):
        if self.busy or self._typing_focus():
            return None
        for label, mode in self.review_scope_labels.items():
            if mode == scope:
                self.review_scope = scope
                self.review_scope_label.set(label)
                self._apply_review_view()
                self.files.focus_set()
                break
        return "break"

    def _recommended_path(self):
        if not self.active_group:
            return None
        recommendation = recommend_keeper(self.active_group)
        return None if recommendation.equivalent_exact else recommendation.photo.path

    def _apply_review_view(self):
        if not self.active_group:
            self.review_visible_var.set(
                review_tr("Widoczne {v0}/{v1} • do Kosza {v2}", v0=0, v1=0, v2=0)
            )
            return

        previous = tuple(self.files.selection())
        indices = filter_sort_photo_indices(
            self.active_group.photos,
            self.review_filter_var.get(),
            self.review_sort_mode,
            self._recommended_path(),
            self.marked,
            self.review_scope,
        )
        keeper = self._recommended_path()

        self.files.delete(*self.files.get_children())
        for index in indices:
            photo = self.active_group.photos[index]
            name = photo.path.name
            if keeper is not None and photo.path == keeper:
                name = "★ " + name
            self.files.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    tr("TAK") if photo.path in self.marked else "—",
                    name,
                    f"{photo.width} × {photo.height}",
                    human_size(photo.size),
                ),
            )

        visible = {str(index) for index in indices}
        restored = tuple(item for item in previous if item in visible)
        if restored:
            self.files.selection_set(restored[:2])
        elif indices:
            self.files.selection_set(tuple(str(index) for index in indices[:2]))
        marked_in_group = sum(
            photo.path in self.marked for photo in self.active_group.photos
        )
        self.review_visible_var.set(
            review_tr(
                "Widoczne {v0}/{v1} • do Kosza {v2}",
                v0=len(indices),
                v1=len(self.active_group.photos),
                v2=marked_in_group,
            )
        )
        self.preview()

    def choose_group(self, event=None):
        super().choose_group(event)
        self._apply_review_view()

    def render_groups(self):
        super().render_groups()
        if not self.result.groups:
            self.review_visible_var.set(
                review_tr("Widoczne {v0}/{v1} • do Kosza {v2}", v0=0, v1=0, v2=0)
            )

    def toggle_mark(self):
        before = set(self.marked)
        super().toggle_mark()
        if self.active_group and (self.marked != before or self.review_scope != "all"):
            self._apply_review_view()

    def clear_marks(self):
        had_marks = bool(self.marked)
        super().clear_marks()
        if self.active_group and (had_marks or self.review_scope != "all"):
            self._apply_review_view()

    def _move_group(self, direction):
        if self.busy or self._typing_focus():
            return None
        children = self.groups.get_children()
        selection = self.groups.selection()
        target = move_selection(children, selection[0] if selection else None, direction)
        if target is None:
            return "break"
        self.groups.selection_set(target)
        self.groups.focus(target)
        self.groups.see(target)
        self.choose_group()
        self.groups.focus_set()
        return "break"

    def _move_file(self, direction):
        if self.busy or self._typing_focus():
            return None
        children = self.files.get_children()
        selection = self.files.selection()
        current = selection[-1] if selection else None
        target = move_selection(children, current, direction)
        if target is None:
            return "break"
        self.files.selection_set(target)
        self.files.focus(target)
        self.files.see(target)
        self.preview()
        self.files.focus_set()
        return "break"

    def _toggle_mark_shortcut(self, event=None):
        if self._typing_focus():
            return None
        self.toggle_mark()
        return "break"

    def _clear_marks_shortcut(self, event=None):
        if self._typing_focus():
            return None
        self.clear_marks()
        return "break"

    def _copy_shortcut(self, event=None):
        self.copy_selected_paths()
        return "break"

    def show_keyboard_help(self):
        messagebox.showinfo(
            review_tr("Tryb klawiaturowy"),
            review_tr(
                "Skróty przyspieszają review, ale nie mają skrótu do przenoszenia plików do Kosza. Operacja Kosza nadal wymaga jawnego przycisku i potwierdzenia."
            )
            + "\n\n"
            + review_tr(
                "Ctrl+F — filtr bieżącej grupy\nCtrl+1 / Ctrl+2 / Ctrl+3 — wszystkie / zaznaczone / niezaznaczone\nCtrl+↑ / Ctrl+↓ — poprzednia / następna grupa\nAlt+↑ / Alt+↓ — poprzedni / następny widoczny plik\nCtrl+M — zaznacz / odznacz wybrane do Kosza\nCtrl+Shift+M — wyczyść wszystkie zaznaczenia\nCtrl+C — kopiuj ścieżki (gdy aktywna jest lista plików)\nF11 — pełnoekranowe porównanie dwóch wybranych zdjęć\nF1 — ta pomoc"
            ),
        )


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
