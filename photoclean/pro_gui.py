"""Professional insight layer for the desktop UI.

Keeps the existing tested Tk workflow intact while surfacing read-only Smart
Keep and Folder Health information. No automatic marking or disposal is added.
"""
from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps, ImageTk

from . import i18n
from .core import MAX_PIXELS
from .gui import BG, PANEL, TEXT, PhotoCleanApp as BasePhotoCleanApp, human_size
from .i18n import tr
from .insights import folder_health, recommend_keeper
from .session import SessionError, SessionSnapshot, load_session, save_session


SESSION_EXTENSION = ".swirpc"
THRESHOLDS = (3, 6, 10)
SESSION_EN = {
    "Sesja": "Session",
    "Widok": "View",
    "Otwórz sesję…": "Open session…",
    "Zapisz sesję…": "Save session…",
    "Otwórz sesję": "Open session",
    "Zapisz sesję": "Save session",
    "Sesja SWIR PhotoClean": "SWIR PhotoClean session",
    "Wszystkie pliki": "All files",
    "Brak sesji do zapisania": "No session to save",
    "Najpierw ukończ skanowanie. Niepełnych lub pustych wyników nie zapisujemy jako sesji.": "Finish a scan first. Incomplete or empty results are not saved as sessions.",
    "Nie zapisano sesji": "Session not saved",
    "Nie można otworzyć sesji": "Cannot open session",
    "Zapisano sesję • {v0} zdjęć • {v1} grup • bez zaznaczeń do kosza": "Session saved • {v0} photos • {v1} groups • Recycle Bin selections excluded",
    "Wczytano sesję • {v0} zdjęć • {v1} grup • zaznaczenia do kosza wyczyszczone": "Session loaded • {v0} photos • {v1} groups • Recycle Bin selections cleared",
    "Porównaj pełny ekran": "Fullscreen compare",
    "Porównanie pełnoekranowe": "Fullscreen comparison",
    "Wybierz dwa zdjęcia": "Select two photos",
    "Zaznacz dwa zdjęcia w jednej grupie, aby otworzyć porównanie pełnoekranowe.": "Select two photos in one group to open fullscreen comparison.",
    "Kółko myszy / +/-: zoom • przeciągnij: panoramowanie • R: dopasuj • Esc: zamknij": "Mouse wheel / +/-: zoom • drag: pan • R: fit • Esc: close",
    "Dopasuj": "Fit",
    "Zoom {v0}%": "Zoom {v0}%",
    "Podgląd niedostępny": "Preview unavailable",
}


def session_tr(message, **values):
    text = SESSION_EN.get(message, message) if i18n.language == "en" else message
    return text.format(**values) if values else text


class FullscreenCompare:
    """Two-photo review window with synchronized relative zoom and pan."""

    MIN_ZOOM = 1.0
    MAX_ZOOM = 4.0

    def __init__(self, parent, photos):
        if len(photos) != 2:
            raise ValueError(session_tr('Zaznacz dwa zdjęcia w jednej grupie, aby otworzyć porównanie pełnoekranowe.'))
        self.parent = parent
        self.photos = tuple(photos)
        self.zoom = 1.0
        self.center_x = 0.5
        self.center_y = 0.5
        self._render_pending = False
        self.source_images = tuple(self._load_photo(photo) for photo in self.photos)
        self.tk_images = [None, None]
        self.canvases = []

        self.window = tk.Toplevel(parent)
        self.window.title(session_tr('Porównanie pełnoekranowe'))
        self.window.configure(bg=BG)
        self.window.geometry(
            f"{max(900, parent.winfo_screenwidth() - 80)}x{max(650, parent.winfo_screenheight() - 120)}+20+20"
        )
        try:
            self.window.state("zoomed")
        except tk.TclError:
            pass

        header = ttk.Frame(self.window, padding=(12, 10))
        header.pack(fill="x")
        ttk.Label(
            header,
            text=session_tr('Kółko myszy / +/-: zoom • przeciągnij: panoramowanie • R: dopasuj • Esc: zamknij'),
        ).pack(side="left", fill="x", expand=True)
        self.zoom_var = tk.StringVar(value=session_tr('Zoom {v0}%', v0=100))
        ttk.Label(header, textvariable=self.zoom_var).pack(side="right", padx=(12, 8))
        ttk.Button(header, text=session_tr('Dopasuj'), command=self.reset_view).pack(side="right")

        body = ttk.Frame(self.window, padding=(8, 0, 8, 8))
        body.pack(fill="both", expand=True)
        for column, photo in enumerate(self.photos):
            body.columnconfigure(column, weight=1, uniform="compare")
            frame = tk.Frame(body, bg="#050812", highlightbackground="#30435f", highlightthickness=1)
            frame.grid(row=0, column=column, sticky="nsew", padx=4)
            canvas = tk.Canvas(frame, bg="#050812", highlightthickness=0, cursor="fleur")
            canvas.pack(fill="both", expand=True)
            detail = ttk.Label(
                frame,
                text=f"{photo.path.name} • {photo.width}×{photo.height} • {human_size(photo.size)}\n{photo.path}",
                anchor="w",
            )
            detail.pack(fill="x", padx=8, pady=6)
            self.canvases.append(canvas)
            canvas.bind("<Configure>", self._schedule_render)
            canvas.bind("<MouseWheel>", self._wheel)
            canvas.bind("<Button-4>", lambda event: self.change_zoom(1))
            canvas.bind("<Button-5>", lambda event: self.change_zoom(-1))
            canvas.bind("<ButtonPress-1>", lambda event, index=column: self._pan_start(index, event))
            canvas.bind("<B1-Motion>", lambda event, index=column: self._pan_move(index, event))
        body.rowconfigure(0, weight=1)

        self.window.bind("<Escape>", lambda event: self.window.destroy())
        self.window.bind("<plus>", lambda event: self.change_zoom(1))
        self.window.bind("<equal>", lambda event: self.change_zoom(1))
        self.window.bind("<minus>", lambda event: self.change_zoom(-1))
        self.window.bind("<Key-r>", lambda event: self.reset_view())
        self.window.bind("<Key-R>", lambda event: self.reset_view())
        self.window.after_idle(self._render_all)
        self.window.focus_set()

    @staticmethod
    def _load_photo(photo):
        with Image.open(photo.path) as source:
            if source.width * source.height > MAX_PIXELS:
                raise ValueError(session_tr('Podgląd niedostępny'))
            image = ImageOps.exif_transpose(source).convert("RGBA")
            background = Image.new("RGBA", image.size, "white")
            background.alpha_composite(image)
            return background.convert("RGB")

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
            source = self.source_images[index]
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
        self.zoom_var.set(session_tr('Zoom {v0}%', v0=int(round(self.zoom * 100))))

    def _apply_center(self, canvas):
        x_span = canvas.xview()[1] - canvas.xview()[0]
        y_span = canvas.yview()[1] - canvas.yview()[0]
        canvas.xview_moveto(max(0.0, min(1.0 - x_span, self.center_x - x_span / 2)))
        canvas.yview_moveto(max(0.0, min(1.0 - y_span, self.center_y - y_span / 2)))

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
        factor = 1.25 if direction > 0 else 0.8
        self.zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, self.zoom * factor))
        self._render_all()

    def reset_view(self):
        self.zoom = 1.0
        self.center_x = 0.5
        self.center_y = 0.5
        self._render_all()


class PhotoCleanApp(BasePhotoCleanApp):
    """Existing desktop app plus non-destructive review insights and sessions."""

    def __init__(self, root, settings_path=None):
        super().__init__(root, settings_path)
        self.compare_view = None
        self._install_session_menu()

    def _install_session_menu(self):
        menu = tk.Menu(self.root)
        view_menu = tk.Menu(menu, tearoff=False)
        view_menu.add_command(
            label=session_tr('Porównaj pełny ekran'),
            command=self.open_fullscreen_compare,
            accelerator="F11",
        )
        menu.add_cascade(label=session_tr('Widok'), menu=view_menu)

        session_menu = tk.Menu(menu, tearoff=False)
        session_menu.add_command(
            label=session_tr('Otwórz sesję…'),
            command=self.load_session_dialog,
            accelerator="Ctrl+O",
        )
        session_menu.add_command(
            label=session_tr('Zapisz sesję…'),
            command=self.save_session_dialog,
            accelerator="Ctrl+S",
        )
        menu.add_cascade(label=session_tr('Sesja'), menu=session_menu)
        self.root.configure(menu=menu)
        self.session_menu = session_menu
        self.view_menu = view_menu
        self.root.bind("<Control-o>", lambda event: self.load_session_dialog())
        self.root.bind("<Control-s>", lambda event: self.save_session_dialog())
        self.root.bind("<F11>", lambda event: self.open_fullscreen_compare())

    def change_language(self, event=None):
        previous = i18n.language
        super().change_language(event)
        if i18n.language != previous:
            self._install_session_menu()

    def _current_threshold(self):
        index = self.level_box.current()
        return THRESHOLDS[index] if 0 <= index < len(THRESHOLDS) else 6

    def _set_threshold_control(self, threshold):
        nearest = min(range(len(THRESHOLDS)), key=lambda index: abs(THRESHOLDS[index] - threshold))
        self.level_box.current(nearest)

    def save_session_dialog(self):
        """Save a completed review snapshot without any Recycle Bin marks."""
        if self.busy:
            return
        if self.result.cancelled or not self.result.photos:
            messagebox.showinfo(
                session_tr('Brak sesji do zapisania'),
                session_tr('Najpierw ukończ skanowanie. Niepełnych lub pustych wyników nie zapisujemy jako sesji.'),
            )
            return
        target = filedialog.asksaveasfilename(
            title=session_tr('Zapisz sesję'),
            defaultextension=SESSION_EXTENSION,
            filetypes=[(session_tr('Sesja SWIR PhotoClean'), f"*{SESSION_EXTENSION}"), ("JSON", "*.json")],
        )
        if not target:
            return
        snapshot = SessionSnapshot(
            roots=tuple(Path(item) for item in self.folders.get(0, "end")),
            threshold=self._current_threshold(),
            include_similar=bool(self.similarity.get()),
            result=self.result,
        )
        try:
            save_session(snapshot, target)
        except (OSError, SessionError) as error:
            messagebox.showerror(session_tr('Nie zapisano sesji'), str(error))
            return
        self.status.set(
            session_tr(
                'Zapisano sesję • {v0} zdjęć • {v1} grup • bez zaznaczeń do kosza',
                v0=len(self.result.photos),
                v1=len(self.result.groups),
            )
        )

    def load_session_dialog(self):
        """Load a validated snapshot for review; destructive marks stay empty."""
        if self.busy:
            return
        source = filedialog.askopenfilename(
            title=session_tr('Otwórz sesję'),
            filetypes=[
                (session_tr('Sesja SWIR PhotoClean'), f"*{SESSION_EXTENSION}"),
                ("JSON", "*.json"),
                (session_tr('Wszystkie pliki'), "*.*"),
            ],
        )
        if not source:
            return
        try:
            snapshot = load_session(source)
        except (OSError, SessionError) as error:
            messagebox.showerror(session_tr('Nie można otworzyć sesji'), str(error))
            return

        self.folders.delete(0, "end")
        for root in snapshot.roots:
            self.folders.insert("end", str(root))
        self.similarity.set(snapshot.include_similar)
        self._set_threshold_control(snapshot.threshold)
        self.result = snapshot.result
        self.marked.clear()
        self.render_groups()
        self.status.set(
            session_tr(
                'Wczytano sesję • {v0} zdjęć • {v1} grup • zaznaczenia do kosza wyczyszczone',
                v0=len(self.result.photos),
                v1=len(self.result.groups),
            )
        )

    def _selected_compare_photos(self):
        if not self.active_group:
            return ()
        chosen = self.files.selection()[:2]
        return tuple(self.active_group.photos[int(item)] for item in chosen)

    def open_preview(self, slot):
        photos = self._selected_compare_photos()
        if len(photos) == 2:
            self.open_fullscreen_compare()
            return
        super().open_preview(slot)

    def open_fullscreen_compare(self):
        photos = self._selected_compare_photos()
        if len(photos) != 2:
            messagebox.showinfo(
                session_tr('Wybierz dwa zdjęcia'),
                session_tr('Zaznacz dwa zdjęcia w jednej grupie, aby otworzyć porównanie pełnoekranowe.'),
            )
            return
        if self.compare_view is not None and self.compare_view.window.winfo_exists():
            self.compare_view.window.destroy()
        try:
            self.compare_view = FullscreenCompare(self.root, photos)
        except (OSError, ValueError) as error:
            messagebox.showerror(session_tr('Podgląd niedostępny'), str(error))

    def choose_group(self, event=None):
        super().choose_group(event)
        if not self.active_group:
            return

        recommendation = recommend_keeper(self.active_group)
        if not recommendation.equivalent_exact:
            for index, photo in enumerate(self.active_group.photos):
                iid = str(index)
                if not self.files.exists(iid):
                    continue
                values = list(self.files.item(iid, "values"))
                if photo.path == recommendation.photo.path and len(values) >= 2:
                    values[1] = "★ " + str(values[1])
                    self.files.item(iid, values=values)

        if recommendation.equivalent_exact:
            self.status.set(tr('Smart Keep • kopie są identyczne bajt w bajt — zachowaj dowolną.'))
        else:
            confidence = tr({'high': 'wysoka', 'medium': 'średnia', 'low': 'niska'}[recommendation.confidence])
            self.status.set(
                tr(
                    'Smart Keep • sugerowane zachowanie: {v0} • wynik {v1}/100 • pewność: {v2}',
                    v0=recommendation.photo.path.name,
                    v1=int(round(recommendation.score)),
                    v2=confidence,
                )
            )

    def update_summary(self):
        super().update_summary()
        health = folder_health(self.result)
        selected_size = sum(photo.size for photo in self.result.photos if photo.path in self.marked)
        self.summary.set(
            tr(
                'Do kosza: {v0} plików • {v1}  |  Pewne duplikaty: {v2} • {v3}',
                v0=len(self.marked),
                v1=human_size(selected_size),
                v2=health.exact_duplicate_files,
                v3=human_size(health.exact_reclaimable_bytes),
            )
        )

    def show_warnings(self):
        window = tk.Toplevel(self.root)
        window.title(tr('Raport skanowania'))
        window.geometry("850x400")
        text = tk.Text(window, wrap="word", bg=PANEL, fg=TEXT, font=("Segoe UI", 10))
        text.pack(fill="both", expand=True)

        health = folder_health(self.result)
        overview = tr(
            'Folder Health • zdjęcia: {v0} • dokładne duplikaty: {v1} • podobne do przeglądu: {v2} • pewne oszczędności: {v3} • uwagi: {v4}',
            v0=health.total_photos,
            v1=health.exact_duplicate_files,
            v2=health.similar_review_files,
            v3=human_size(health.exact_reclaimable_bytes),
            v4=health.warning_count,
        )
        notices = "\n\n".join(self.result.warnings) or tr(
            'Brak uwag. Obsługiwane: JPG, PNG, WebP, BMP oraz jednostronicowe TIFF/GIF. HEIC i RAW nie są obsługiwane w tej wersji.'
        )
        text.insert("1.0", overview + "\n\n" + notices)
        text.configure(state="disabled")


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
