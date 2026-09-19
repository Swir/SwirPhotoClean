"""Enhanced fullscreen review with an integrated, read-only Difference View."""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox, ttk

from PIL import Image, ImageOps, ImageTk

from . import i18n
from .core import MAX_PIXELS
from .difference import build_difference_preview
from .gui import BG, human_size
from .pro_gui import session_tr
from .review_power_gui import PhotoCleanApp as ReviewPowerPhotoCleanApp


FULLSCREEN_EN = {
    "Różnice": "Differences",
    "Zdjęcie": "Photo",
    "Tryb różnic jest tylko do odczytu i nigdy nie zaznacza plików do Kosza.": (
        "Difference mode is read-only and never marks files for the Recycle Bin."
    ),
    "Różnice • zmienione: {v0}% • średnia: {v1}/255 • próg: {v2}": (
        "Differences • changed: {v0}% • mean: {v1}/255 • threshold: {v2}"
    ),
    "Analiza {v0}×{v1} • tylko podgląd • D: wróć do zdjęcia": (
        "Analysis {v0}×{v1} • preview only • D: return to photo"
    ),
    "Kółko myszy / +/-: zoom • przeciągnij: panorama • R: dopasuj • D: różnice • Esc: zamknij": (
        "Mouse wheel / +/-: zoom • drag: pan • R: fit • D: differences • Esc: close"
    ),
    "Nie można zbudować widoku różnic": "Cannot build difference view",
}


def fullscreen_tr(message, **values):
    text = FULLSCREEN_EN.get(message, message) if i18n.language == "en" else message
    return text.format(**values) if values else text


class IntegratedFullscreenCompare:
    """Two-photo fullscreen review with synchronized pan/zoom and Difference View.

    The right pane can be toggled between the second source photo and a bounded
    heatmap. Building the heatmap is lazy and read-only; no cleanup mark or file
    operation is reachable from this window.
    """

    MIN_ZOOM = 1.0
    MAX_ZOOM = 4.0

    def __init__(self, parent, photos):
        if len(photos) != 2:
            raise ValueError(
                session_tr(
                    "Zaznacz dwa zdjęcia w jednej grupie, aby otworzyć porównanie pełnoekranowe."
                )
            )
        self.parent = parent
        self.photos = tuple(photos)
        self.zoom = 1.0
        self.center_x = 0.5
        self.center_y = 0.5
        self._render_pending = False
        self.source_images = tuple(self._load_photo(photo) for photo in self.photos)
        self.difference_preview = None
        self.difference_visible = False
        self.tk_images = [None, None]
        self.canvases = []
        self.detail_vars = []

        self.window = tk.Toplevel(parent)
        self.window.title(session_tr("Porównanie pełnoekranowe"))
        self.window.configure(bg=BG)
        self.window.geometry(
            f"{max(900, parent.winfo_screenwidth() - 80)}x"
            f"{max(650, parent.winfo_screenheight() - 120)}+20+20"
        )
        try:
            self.window.state("zoomed")
        except tk.TclError:
            pass

        header = ttk.Frame(self.window, padding=(12, 10))
        header.pack(fill="x")
        ttk.Label(
            header,
            text=fullscreen_tr(
                "Kółko myszy / +/-: zoom • przeciągnij: panorama • R: dopasuj • D: różnice • Esc: zamknij"
            ),
        ).pack(side="left", fill="x", expand=True)
        self.zoom_var = tk.StringVar(value=session_tr("Zoom {v0}%", v0=100))
        ttk.Label(header, textvariable=self.zoom_var).pack(side="right", padx=(12, 8))
        ttk.Button(header, text=session_tr("Dopasuj"), command=self.reset_view).pack(
            side="right"
        )
        self.mode_button = ttk.Button(
            header,
            text=fullscreen_tr("Różnice"),
            command=self.toggle_difference,
        )
        self.mode_button.pack(side="right", padx=(0, 8))

        body = ttk.Frame(self.window, padding=(8, 0, 8, 8))
        body.pack(fill="both", expand=True)
        for column, photo in enumerate(self.photos):
            body.columnconfigure(column, weight=1, uniform="compare")
            frame = tk.Frame(
                body,
                bg="#050812",
                highlightbackground="#30435f",
                highlightthickness=1,
            )
            frame.grid(row=0, column=column, sticky="nsew", padx=4)
            canvas = tk.Canvas(
                frame, bg="#050812", highlightthickness=0, cursor="fleur"
            )
            canvas.pack(fill="both", expand=True)
            detail_var = tk.StringVar(value=self._photo_detail(photo))
            ttk.Label(
                frame,
                textvariable=detail_var,
                anchor="w",
                justify="left",
            ).pack(fill="x", padx=8, pady=6)
            self.canvases.append(canvas)
            self.detail_vars.append(detail_var)
            canvas.bind("<Configure>", self._schedule_render)
            canvas.bind("<MouseWheel>", self._wheel)
            canvas.bind("<Button-4>", lambda event: self.change_zoom(1))
            canvas.bind("<Button-5>", lambda event: self.change_zoom(-1))
            canvas.bind(
                "<ButtonPress-1>",
                lambda event, index=column: self._pan_start(index, event),
            )
            canvas.bind(
                "<B1-Motion>",
                lambda event, index=column: self._pan_move(index, event),
            )
        body.rowconfigure(0, weight=1)

        footer = ttk.Frame(self.window, padding=(12, 0, 12, 8))
        footer.pack(fill="x")
        ttk.Label(
            footer,
            text=fullscreen_tr(
                "Tryb różnic jest tylko do odczytu i nigdy nie zaznacza plików do Kosza."
            ),
        ).pack(anchor="w")

        self.window.bind("<Escape>", lambda event: self.window.destroy())
        self.window.bind("<plus>", lambda event: self.change_zoom(1))
        self.window.bind("<equal>", lambda event: self.change_zoom(1))
        self.window.bind("<minus>", lambda event: self.change_zoom(-1))
        self.window.bind("<Key-r>", lambda event: self.reset_view())
        self.window.bind("<Key-R>", lambda event: self.reset_view())
        self.window.bind("<Key-d>", lambda event: self.toggle_difference())
        self.window.bind("<Key-D>", lambda event: self.toggle_difference())
        self.window.after_idle(self._render_all)
        self.window.focus_set()

    @staticmethod
    def _photo_detail(photo):
        return (
            f"{photo.path.name} • {photo.width}×{photo.height} • "
            f"{human_size(photo.size)}\n{photo.path}"
        )

    @staticmethod
    def _load_photo(photo):
        with Image.open(photo.path) as source:
            if source.width * source.height > MAX_PIXELS:
                raise ValueError(session_tr("Podgląd niedostępny"))
            image = ImageOps.exif_transpose(source).convert("RGBA")
            background = Image.new("RGBA", image.size, "white")
            background.alpha_composite(image)
            return background.convert("RGB")

    def _difference_detail(self):
        report = self.difference_preview.report
        return (
            fullscreen_tr(
                "Różnice • zmienione: {v0}% • średnia: {v1}/255 • próg: {v2}",
                v0=f"{report.changed_ratio * 100:.2f}",
                v1=f"{report.mean_delta:.2f}",
                v2=report.threshold,
            )
            + "\n"
            + fullscreen_tr(
                "Analiza {v0}×{v1} • tylko podgląd • D: wróć do zdjęcia",
                v0=report.analysis_size[0],
                v1=report.analysis_size[1],
            )
        )

    def _active_source(self, index):
        if index == 1 and self.difference_visible and self.difference_preview is not None:
            return self.difference_preview.heatmap
        return self.source_images[index]

    def toggle_difference(self):
        if not self.difference_visible and self.difference_preview is None:
            try:
                self.difference_preview = build_difference_preview(*self.photos)
            except (OSError, ValueError) as error:
                messagebox.showerror(
                    fullscreen_tr("Nie można zbudować widoku różnic"),
                    str(error),
                    parent=self.window,
                )
                return "break"

        if self.canvases:
            self._capture_center(self.canvases[0])
        self.difference_visible = not self.difference_visible
        if self.difference_visible:
            self.mode_button.configure(text=fullscreen_tr("Zdjęcie"))
            self.detail_vars[1].set(self._difference_detail())
        else:
            self.mode_button.configure(text=fullscreen_tr("Różnice"))
            self.detail_vars[1].set(self._photo_detail(self.photos[1]))
        self._render_all()
        return "break"

    def _schedule_render(self, event=None):
        if self._render_pending or not self.window.winfo_exists():
            return
        self._render_pending = True
        self.window.after_idle(self._render_all)

    def _render_all(self):
        self._render_pending = False
        if not self.window.winfo_exists():
            return
        for index, canvas in enumerate(self.canvases):
            width = max(2, canvas.winfo_width())
            height = max(2, canvas.winfo_height())
            source = self._active_source(index)
            fit = min((width - 4) / source.width, (height - 4) / source.height)
            scale = max(0.01, fit * self.zoom)
            rendered_size = (
                max(1, int(round(source.width * scale))),
                max(1, int(round(source.height * scale))),
            )
            rendered = source.resize(rendered_size, Image.Resampling.LANCZOS)
            picture = ImageTk.PhotoImage(rendered, master=self.window)
            self.tk_images[index] = picture

            region_width = max(width, rendered_size[0])
            region_height = max(height, rendered_size[1])
            x = (region_width - rendered_size[0]) // 2
            y = (region_height - rendered_size[1]) // 2
            canvas.delete("all")
            canvas.create_image(x, y, anchor="nw", image=picture)
            canvas.configure(scrollregion=(0, 0, region_width, region_height))
            self._apply_center(canvas)
        self.zoom_var.set(session_tr("Zoom {v0}%", v0=int(round(self.zoom * 100))))

    def _apply_center(self, canvas):
        x_span = canvas.xview()[1] - canvas.xview()[0]
        y_span = canvas.yview()[1] - canvas.yview()[0]
        canvas.xview_moveto(
            max(0.0, min(1.0 - x_span, self.center_x - x_span / 2))
        )
        canvas.yview_moveto(
            max(0.0, min(1.0 - y_span, self.center_y - y_span / 2))
        )

    def _capture_center(self, canvas):
        x_view = canvas.xview()
        y_view = canvas.yview()
        self.center_x = (x_view[0] + x_view[1]) / 2
        self.center_y = (y_view[0] + y_view[1]) / 2

    def _sync_from(self, source):
        self._capture_center(source)
        for canvas in self.canvases:
            if canvas is not source:
                self._apply_center(canvas)

    def _pan_start(self, index, event):
        self.canvases[index].scan_mark(event.x, event.y)

    def _pan_move(self, index, event):
        source = self.canvases[index]
        source.scan_dragto(event.x, event.y, gain=1)
        self._sync_from(source)

    def _wheel(self, event):
        self.change_zoom(1 if event.delta > 0 else -1)
        return "break"

    def change_zoom(self, direction):
        if self.canvases:
            self._capture_center(self.canvases[0])
        factor = 1.25 if direction > 0 else 0.8
        self.zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, self.zoom * factor))
        self._render_all()

    def reset_view(self):
        self.zoom = 1.0
        self.center_x = 0.5
        self.center_y = 0.5
        self._render_all()


class PhotoCleanApp(ReviewPowerPhotoCleanApp):
    """Final UI layer wiring enhanced fullscreen compare into the mature app."""

    def open_fullscreen_compare(self):
        if self.busy:
            return
        photos = self._selected_compare_photos()
        if len(photos) != 2:
            messagebox.showinfo(
                session_tr("Wybierz dwa zdjęcia"),
                session_tr(
                    "Zaznacz dwa zdjęcia w jednej grupie, aby otworzyć porównanie pełnoekranowe."
                ),
            )
            return
        existing = getattr(self, "compare_view", None)
        if existing is not None and existing.window.winfo_exists():
            existing.window.destroy()
        try:
            self.compare_view = IntegratedFullscreenCompare(self.root, photos)
        except (OSError, ValueError) as error:
            messagebox.showerror(session_tr("Podgląd niedostępny"), str(error))


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
