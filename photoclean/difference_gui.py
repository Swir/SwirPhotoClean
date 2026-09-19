"""Read-only Difference View desktop layer for two selected photos."""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox, ttk

from PIL import ImageTk

from . import i18n
from .diagnostics_gui import PhotoCleanApp as DiagnosticsPhotoCleanApp
from .difference import DifferencePreview, build_difference_preview
from .gui import BG, PANEL


DIFF_EN = {
    "Widok różnic…": "Difference view…",
    "Widok różnic": "Difference view",
    "Ctrl+Alt+D": "Ctrl+Alt+D",
    "Wybierz dwa zdjęcia": "Select two photos",
    "Zaznacz dwa zdjęcia w jednej grupie, aby otworzyć widok różnic.": "Select two photos in one group to open the difference view.",
    "Nie można zbudować widoku różnic": "Cannot build difference view",
    "To narzędzie jest tylko do odczytu. Jasne obszary pokazują większe różnice pikseli; nic nie jest automatycznie zaznaczane do Kosza.": "This tool is read-only. Bright areas show larger pixel differences; nothing is automatically selected for the Recycle Bin.",
    "Zmiana pikseli powyżej progu: {v0}% • średnia różnica: {v1}/255 • próg: {v2}": "Pixels above threshold: {v0}% • mean difference: {v1}/255 • threshold: {v2}",
    "Rozmiary zgodne — analiza piksel po pikselu po orientacji EXIF.": "Dimensions match — pixel-by-pixel analysis after EXIF orientation.",
    "Rozmiary różne — obie wersje zostały przeskalowane wyłącznie do bezpiecznego podglądu różnic.": "Dimensions differ — both versions were resampled only for the bounded difference preview.",
    "Brak widocznych różnic powyżej progu podglądu.": "No visible differences above the preview threshold.",
    "Obszar zmian: {v0}": "Change bounds: {v0}",
    "Analiza: {v0}×{v1}": "Analysis: {v0}×{v1}",
    "Dopasuj": "Fit",
    "Zoom {v0}%": "Zoom {v0}%",
    "Kółko myszy / +/-: zoom • przeciągnij: panoramowanie • R: dopasuj • Esc: zamknij": "Mouse wheel / +/-: zoom • drag: pan • R: fit • Esc: close",
}


def diff_tr(message, **values):
    text = DIFF_EN.get(message, message) if i18n.language == "en" else message
    return text.format(**values) if values else text


class DifferenceWindow:
    """Bounded heatmap review window. It never mutates source files or marks."""

    MIN_ZOOM = 1.0
    MAX_ZOOM = 6.0

    def __init__(self, app: "PhotoCleanApp", photos):
        if len(photos) != 2:
            raise ValueError(diff_tr("Zaznacz dwa zdjęcia w jednej grupie, aby otworzyć widok różnic."))
        self.app = app
        self.photos = tuple(photos)
        self.preview: DifferencePreview = build_difference_preview(*self.photos)
        self.zoom = 1.0
        self.center_x = 0.5
        self.center_y = 0.5
        self.tk_image = None
        self._render_pending = False

        self.window = tk.Toplevel(app.root)
        self.window.title(diff_tr("Widok różnic"))
        self.window.geometry("1100x760")
        self.window.minsize(760, 520)
        self.window.configure(bg=BG)
        self.window.transient(app.root)

        outer = ttk.Frame(self.window, padding=12)
        outer.pack(fill="both", expand=True)
        ttk.Label(
            outer,
            text=diff_tr(
                "To narzędzie jest tylko do odczytu. Jasne obszary pokazują większe różnice pikseli; nic nie jest automatycznie zaznaczane do Kosza."
            ),
            wraplength=1040,
        ).pack(anchor="w", pady=(0, 7))

        report = self.preview.report
        ttk.Label(
            outer,
            text=diff_tr(
                "Zmiana pikseli powyżej progu: {v0}% • średnia różnica: {v1}/255 • próg: {v2}",
                v0=f"{report.changed_ratio * 100:.2f}",
                v1=f"{report.mean_delta:.2f}",
                v2=report.threshold,
            ),
        ).pack(anchor="w")
        ttk.Label(
            outer,
            text=diff_tr(
                "Rozmiary różne — obie wersje zostały przeskalowane wyłącznie do bezpiecznego podglądu różnic."
                if report.resampled
                else "Rozmiary zgodne — analiza piksel po pikselu po orientacji EXIF."
            ),
            wraplength=1040,
        ).pack(anchor="w", pady=(2, 7))

        if report.changed_bbox is None:
            bounds_text = diff_tr("Brak widocznych różnic powyżej progu podglądu.")
        else:
            bounds_text = diff_tr("Obszar zmian: {v0}", v0=report.changed_bbox)
        details = (
            f"{self.photos[0].path.name} {report.left_size[0]}×{report.left_size[1]}  ↔  "
            f"{self.photos[1].path.name} {report.right_size[0]}×{report.right_size[1]}  •  "
            f"{diff_tr('Analiza: {v0}×{v1}', v0=report.analysis_size[0], v1=report.analysis_size[1])}  •  {bounds_text}"
        )
        ttk.Label(outer, text=details, wraplength=1040).pack(anchor="w", pady=(0, 7))

        controls = ttk.Frame(outer)
        controls.pack(fill="x", pady=(0, 7))
        ttk.Label(
            controls,
            text=diff_tr("Kółko myszy / +/-: zoom • przeciągnij: panoramowanie • R: dopasuj • Esc: zamknij"),
        ).pack(side="left", fill="x", expand=True)
        self.zoom_var = tk.StringVar(value=diff_tr("Zoom {v0}%", v0=100))
        ttk.Label(controls, textvariable=self.zoom_var).pack(side="right", padx=(12, 8))
        ttk.Button(controls, text=diff_tr("Dopasuj"), command=self.reset_view).pack(side="right")

        frame = tk.Frame(outer, bg=PANEL, highlightbackground="#30435f", highlightthickness=1)
        frame.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(frame, bg="#050812", highlightthickness=0, cursor="fleur")
        self.canvas.pack(fill="both", expand=True)
        path_text = ttk.Label(
            frame,
            text=f"{self.photos[0].path}\n{self.photos[1].path}",
            anchor="w",
        )
        path_text.pack(fill="x", padx=8, pady=6)

        self.canvas.bind("<Configure>", self._schedule_render)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Button-4>", lambda event: self.change_zoom(1))
        self.canvas.bind("<Button-5>", lambda event: self.change_zoom(-1))
        self.canvas.bind("<ButtonPress-1>", self._pan_start)
        self.canvas.bind("<B1-Motion>", self._pan_move)
        self.window.bind("<Escape>", lambda event: self.window.destroy())
        self.window.bind("<plus>", lambda event: self.change_zoom(1))
        self.window.bind("<equal>", lambda event: self.change_zoom(1))
        self.window.bind("<minus>", lambda event: self.change_zoom(-1))
        self.window.bind("<Key-r>", lambda event: self.reset_view())
        self.window.bind("<Key-R>", lambda event: self.reset_view())
        self.window.after_idle(self._render)
        self.window.focus_set()

    def _schedule_render(self, event=None):
        if self._render_pending or not self.window.winfo_exists():
            return
        self._render_pending = True
        self.window.after_idle(self._render)

    def _render(self):
        self._render_pending = False
        if not self.window.winfo_exists():
            return
        width = max(2, self.canvas.winfo_width())
        height = max(2, self.canvas.winfo_height())
        source = self.preview.heatmap
        fit = min((width - 4) / source.width, (height - 4) / source.height)
        scale = max(0.01, fit * self.zoom)
        rendered_size = (
            max(1, int(round(source.width * scale))),
            max(1, int(round(source.height * scale))),
        )
        rendered = source.resize(rendered_size)
        self.tk_image = ImageTk.PhotoImage(rendered, master=self.window)
        region_width = max(width, rendered_size[0])
        region_height = max(height, rendered_size[1])
        x = (region_width - rendered_size[0]) // 2
        y = (region_height - rendered_size[1]) // 2
        self.canvas.delete("all")
        self.canvas.create_image(x, y, anchor="nw", image=self.tk_image)
        self.canvas.configure(scrollregion=(0, 0, region_width, region_height))
        self._apply_center()
        self.zoom_var.set(diff_tr("Zoom {v0}%", v0=int(round(self.zoom * 100))))

    def _apply_center(self):
        x_span = self.canvas.xview()[1] - self.canvas.xview()[0]
        y_span = self.canvas.yview()[1] - self.canvas.yview()[0]
        self.canvas.xview_moveto(max(0.0, min(1.0 - x_span, self.center_x - x_span / 2)))
        self.canvas.yview_moveto(max(0.0, min(1.0 - y_span, self.center_y - y_span / 2)))

    def _capture_center(self):
        x_view = self.canvas.xview()
        y_view = self.canvas.yview()
        self.center_x = (x_view[0] + x_view[1]) / 2
        self.center_y = (y_view[0] + y_view[1]) / 2

    def _pan_start(self, event):
        self.canvas.scan_mark(event.x, event.y)

    def _pan_move(self, event):
        self.canvas.scan_dragto(event.x, event.y, gain=1)
        self._capture_center()

    def _wheel(self, event):
        self.change_zoom(1 if event.delta > 0 else -1)
        return "break"

    def change_zoom(self, direction):
        factor = 1.25 if direction > 0 else 0.8
        self._capture_center()
        self.zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, self.zoom * factor))
        self._render()

    def reset_view(self):
        self.zoom = 1.0
        self.center_x = 0.5
        self.center_y = 0.5
        self._render()


class PhotoCleanApp(DiagnosticsPhotoCleanApp):
    """Final desktop layer with non-destructive Difference View."""

    def _install_session_menu(self):
        super()._install_session_menu()
        self.view_menu.add_separator()
        self.view_menu.add_command(
            label=diff_tr("Widok różnic…"),
            command=self.open_difference_view,
            accelerator=diff_tr("Ctrl+Alt+D"),
        )
        self.root.bind("<Control-Alt-d>", lambda event: self.open_difference_view())
        self.root.bind("<Control-Alt-D>", lambda event: self.open_difference_view())

    def open_difference_view(self):
        if self.busy or not self.active_group:
            return
        photos = self._selected_compare_photos()
        if len(photos) != 2:
            messagebox.showinfo(
                diff_tr("Wybierz dwa zdjęcia"),
                diff_tr("Zaznacz dwa zdjęcia w jednej grupie, aby otworzyć widok różnic."),
            )
            return
        existing = getattr(self, "difference_view", None)
        if existing is not None and existing.window.winfo_exists():
            existing.window.destroy()
        try:
            self.difference_view = DifferenceWindow(self, photos)
        except (OSError, ValueError) as error:
            messagebox.showerror(diff_tr("Nie można zbudować widoku różnic"), str(error))


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
