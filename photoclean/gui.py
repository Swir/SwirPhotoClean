"""Tk desktop interface. Workers never call Tk; all events go through a queue."""
from __future__ import annotations

from .i18n import tr

import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps, ImageTk

from . import __version__
from . import i18n
from .core import MAX_PIXELS, ScanResult, export_csv, recycle_selected, scan

BG, PANEL, TEXT, MUTED, ACCENT = "#0b1020", "#151f35", "#eef4ff", "#9eafcb", "#62ead1"


def bundled_asset(name):
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "assets" / name


def human_size(size):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024


class PhotoCleanApp:
    def __init__(self, root, settings_path=None):
        self.settings_path = Path(settings_path) if settings_path is not None else i18n.settings_file()
        i18n.language = i18n.load_language(self.settings_path)
        self.root = root
        self.result = ScanResult()
        self.marked = set()
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.closing = False
        self.active_group = None
        self.images = []
        self.progress_pending = ""
        self._build(root)

    def _build(self, root):
        root.title(f"SWIR PhotoClean {__version__}")
        try:
            root.iconbitmap(default=str(bundled_asset("SwirPhotoClean.ico")))
        except tk.TclError:
            pass
        root.geometry("1220x760")
        root.minsize(900, 700)
        root.configure(bg=BG)
        root.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10), background=BG, foreground=TEXT)
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Title.TLabel", font=("Segoe UI", 22, "bold"))
        style.configure("TButton", background=PANEL, padding=(10, 6), borderwidth=2, relief="raised", lightcolor="#344764", darkcolor="#060a13", bordercolor="#273852")
        style.map("TButton", background=[("active", "#2b405a")], foreground=[("disabled", "#76869a")])
        style.configure("Accent.TButton", background=ACCENT, foreground=BG, font=("Segoe UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#77e7d4"), ("disabled", PANEL)])
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT, rowheight=28, borderwidth=0)
        style.configure("Treeview.Heading", background="#22324a", foreground=MUTED, padding=6, relief="flat")
        style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=PANEL, borderwidth=0, thickness=5)
        style.map("TCombobox", fieldbackground=[("readonly", PANEL)], foreground=[("readonly", TEXT)])
        style.map("Treeview", background=[("selected", "#315b78")])
        style.configure("TCheckbutton", background=BG)
        style.map("TCheckbutton", background=[("active", BG)])
        style.configure("TCombobox", fieldbackground=PANEL, foreground=TEXT)
        outer = ttk.Frame(root, padding=(16, 10))
        outer.pack(fill="both", expand=True)
        header = tk.Canvas(outer, height=92, bg=BG, highlightthickness=0)
        header.pack(fill="x", pady=(0, 8))
        def draw_header(event):
            header.delete("all")
            w = event.width
            header.create_rectangle(4, 5, w, 92, fill="#050812", outline="")
            header.create_rectangle(0, 0, w-5, 86, fill="#172440", outline="#344866")
            header.create_line(1, 1, w-6, 1, fill="#577193")
            header.create_text(22, 27, text="SWIR PhotoClean", anchor="w", fill=TEXT, font=("Segoe UI", 22, "bold"))
            header.create_text(23, 62, text=tr('Mniej kopii. Więcej miejsca na wspomnienia.'), anchor="w", fill=MUTED, font=("Segoe UI", 10))
            if w > 720:
                for x,y,c in [(w-151,18,"#263b61"),(w-135,27,"#3a5880"),(w-119,36,"#62ead1")]:
                    header.create_polygon(x,y,x+61,y-6,x+69,y+34,x+8,y+40, fill=c, outline="#86ffee")
                header.create_text(w-184, 25, text=tr('100% lokalnie'), anchor="e", fill=ACCENT, font=("Segoe UI", 10, "bold"))
        header.bind("<Configure>", draw_header)
        self.language_var = tk.StringVar(value="English" if i18n.language == "en" else "Polski")
        self.language_box = ttk.Combobox(header, textvariable=self.language_var, values=("Polski", "English"), state="readonly", width=10)
        self.language_box.place(relx=1, x=-184, y=48, anchor="ne")
        self.language_box.bind("<<ComboboxSelected>>", self.change_language)
        toolbar = ttk.Frame(outer)
        toolbar.pack(fill="x")
        self.add_button = ttk.Button(toolbar, text=tr('+ Dodaj folder'), command=self.add_folder)
        self.add_button.pack(side="left", padx=(0, 8))
        self.remove_button = ttk.Button(toolbar, text=tr('Usuń z listy'), command=self.remove_folder)
        self.remove_button.pack(side="left")
        self.similarity = tk.BooleanVar(value=True)
        self.sim_check = ttk.Checkbutton(toolbar, text=tr('Szukaj też podobnych'), variable=self.similarity)
        self.sim_check.pack(side="left", padx=15)
        self.level = tk.StringVar(value=tr('Standardowy'))
        self.level_box = ttk.Combobox(toolbar, textvariable=self.level, values=[tr('Ścisły'), tr('Standardowy'), tr('Szeroki')], state="readonly", width=15)
        self.level_box.pack(side="left")
        self.scan_button = ttk.Button(toolbar, text=tr('Skanuj zdjęcia'), style="Accent.TButton", command=self.start_scan)
        self.scan_button.pack(side="right")
        self.folders = tk.Listbox(outer, height=1, bg=PANEL, fg=TEXT, selectbackground="#315b78", relief="flat", font=("Segoe UI", 10), exportselection=False)
        self.folders.pack(fill="x", pady=(6, 4))
        status_row = ttk.Frame(outer)
        status_row.pack(fill="x", pady=(0, 4))
        self.status = tk.StringVar(value=tr('Dodaj foldery ze zdjęciami. Skanowanie niczego nie usuwa.'))
        ttk.Label(status_row, textvariable=self.status, style="Muted.TLabel").pack(side="left", fill="x", expand=True)
        self.cancel_button = ttk.Button(status_row, text=tr('Anuluj'), command=self.cancel.set, state="disabled")
        self.cancel_button.pack(side="right")
        self.bar = ttk.Progressbar(outer, mode="indeterminate")
        self.bar.pack(fill="x", pady=(0, 6))
        panes = ttk.Panedwindow(outer, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left, right = ttk.Frame(panes), ttk.Frame(panes)
        panes.add(left, weight=1)
        panes.add(right, weight=3)
        ttk.Label(left, text=tr('GRUPY ZDJĘĆ'), foreground=ACCENT).pack(anchor="w", pady=(0, 4))
        self.groups = ttk.Treeview(left, columns=("count",), show="tree headings", selectmode="browse", height=8)
        self.groups.heading("#0", text=tr('Rodzaj'))
        self.groups.heading("count", text=tr('Pliki'))
        self.groups.column("#0", width=145, minwidth=100)
        self.groups.column("count", width=42, minwidth=36, stretch=False)
        self.groups.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(left, command=self.groups.yview)
        scrollbar.pack(side="right", fill="y")
        self.groups.configure(yscrollcommand=scrollbar.set)
        self.groups.bind("<<TreeviewSelect>>", self.choose_group)
        ttk.Label(right, text=tr('PORÓWNAJ  •  Ctrl + klik: dwa zdjęcia  •  dwuklik podglądu: powiększenie'), style="Muted.TLabel").pack(anchor="w", padx=12)
        file_frame = ttk.Frame(right, padding=(12, 8, 0, 0))
        file_frame.pack(fill="x")
        self.files = ttk.Treeview(file_frame, columns=("marked", "name", "pixels", "size"), show="headings", height=3, selectmode="extended")
        for key, title, width in [("marked", tr('Do kosza'), 65), ("name", tr('Zdjęcie'), 240), ("pixels", tr('Wymiary'), 110), ("size", tr('Rozmiar'), 90)]:
            self.files.heading(key, text=title)
            self.files.column(key, width=width, minwidth=width if key != "name" else 100, stretch=key == "name")
        self.files.pack(side="left", fill="x", expand=True)
        fs = ttk.Scrollbar(file_frame, command=self.files.yview)
        fs.pack(side="right", fill="y")
        self.files.configure(yscrollcommand=fs.set)
        self.files.bind("<<TreeviewSelect>>", self.preview)
        self.files.bind("<space>", lambda event: self.toggle_mark())
        actions = ttk.Frame(right, padding=(12, 5))
        actions.pack(fill="x")
        self.mark_button = ttk.Button(actions, text=tr('Zaznacz / odznacz do kosza'), command=self.toggle_mark, state="disabled")
        self.mark_button.pack(side="left")
        self.clear_button = ttk.Button(actions, text=tr('Odznacz wszystko'), command=self.clear_marks, state="disabled")
        self.clear_button.pack(side="left", padx=8)
        self.copy_button = ttk.Button(actions, text=tr('Kopiuj ścieżkę'), command=self.copy_selected_paths, state="disabled")
        self.copy_button.pack(side="left")
        self.preview_frame = ttk.Frame(right, padding=(12, 0, 0, 0))
        self.preview_frame.pack(fill="both", expand=True)
        self.preview_panels = []
        for col in range(2):
            self.preview_frame.columnconfigure(col, weight=1, uniform="preview")
            panel = tk.Frame(self.preview_frame, bg="#080d19", bd=3, relief="raised", highlightbackground="#30435f", highlightthickness=1)
            panel.grid(row=0, column=col, sticky="nsew", padx=4)
            label = ttk.Label(panel, text=tr('◇\n\nWybierz zdjęcie do porównania'), anchor="center", justify="center", background=PANEL, foreground=MUTED)
            label.bind("<Double-1>", lambda event, slot=col: self.open_preview(slot))
            label.pack(fill="both", expand=True)
            detail = ttk.Label(panel, text="", style="Muted.TLabel", anchor="w")
            detail.pack(fill="x", pady=(3, 0))
            self.preview_panels.append((label, detail))
        self.preview_frame.rowconfigure(0, weight=1)
        footer = ttk.Frame(outer, padding=(0, 6, 0, 0))
        footer.pack(fill="x")
        self.summary = tk.StringVar(value=tr('Brak wyników'))
        ttk.Label(footer, textvariable=self.summary).pack(side="left")
        self.trash_button = ttk.Button(footer, text=tr('Przenieś zaznaczone do kosza'), command=self.confirm_recycle, state="disabled")
        self.trash_button.pack(side="right")
        self.export_button = ttk.Button(footer, text=tr('Eksport CSV'), command=self.export, state="disabled")
        self.export_button.pack(side="right", padx=8)
        self.warning_button = ttk.Button(footer, text=tr('Raport'), command=self.show_warnings)
        self.warning_button.pack(side="right")
        ttk.Label(outer, text=tr('Podobne ≠ identyczne. Sprawdź podgląd. Nic nie jest zaznaczane automatycznie.'), style="Muted.TLabel").pack(anchor="w", pady=(4, 0))
        self.poll_id = self.root.after(100, self.poll)

    def change_language(self, event=None):
        if self.busy:
            return
        selected = "en" if self.language_var.get() == "English" else "pl"
        if selected == i18n.language:
            return
        folders = self.folders.get(0, "end")
        similar, level = self.similarity.get(), self.level_box.current()
        groups, files = self.groups.selection(), self.files.selection()
        geometry = self.root.geometry()
        i18n.language = selected
        self.root.after_cancel(self.poll_id)
        for widget in self.root.winfo_children():
            widget.destroy()
        self._build(self.root)
        self.root.geometry(geometry)
        for folder in folders:
            self.folders.insert("end", folder)
        self.similarity.set(similar)
        self.level_box.current(level)
        self.render_groups()
        if groups:
            self.groups.selection_set(groups)
            self.choose_group()
            self.files.selection_set(files)
            self.preview()
        try:
            i18n.save_language(self.settings_path, selected)
        except OSError:
            messagebox.showwarning(tr("Nie zapisano języka"), tr("Nie można zapisać ustawienia języka. Wybór będzie działał tylko do zamknięcia aplikacji."))

    def add_folder(self):
        folder = filedialog.askdirectory(title=tr('Wybierz folder ze zdjęciami'))
        if folder and folder not in self.folders.get(0, "end"):
            self.folders.insert("end", folder)

    def remove_folder(self):
        for index in reversed(self.folders.curselection()):
            self.folders.delete(index)

    def set_busy(self, value):
        self.busy = value
        for widget in (self.add_button, self.remove_button, self.scan_button, self.sim_check):
            widget.configure(state="disabled" if value else "normal")
        self.level_box.configure(state="disabled" if value else "readonly")
        self.language_box.configure(state="disabled" if value else "readonly")
        self.cancel_button.configure(state="normal" if value else "disabled")
        if value:
            self.bar.start(12)
        else:
            self.bar.stop()
        self.update_summary()

    def progress(self, message):
        # One latest status slot: fast scans cannot flood the GUI queue.
        self.progress_pending = message

    def start_scan(self):
        if self.busy:
            return
        roots = self.folders.get(0, "end")
        if not roots:
            messagebox.showinfo(tr('Wybierz folder'), tr('Najpierw dodaj co najmniej jeden folder.'))
            return
        threshold = {tr('Ścisły'): 3, tr('Standardowy'): 6, tr('Szeroki'): 10}[self.level.get()]
        include_similar = self.similarity.get()
        self.cancel.clear()
        self.result = ScanResult()
        self.marked.clear()
        self.render_groups()
        self.set_busy(True)
        self.status.set(tr('Rozpoczynanie skanowania…'))
        def worker():
            try:
                self.events.put(("scan", scan(roots, threshold, self.cancel, self.progress, include_similar)))
            except Exception as error:
                self.events.put(("error", str(error)))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        if self.progress_pending:
            self.status.set(self.progress_pending)
            self.progress_pending = ""
        try:
            while True:
                kind, value = self.events.get_nowait()
                self.set_busy(False)
                if kind == "scan":
                    self.result = value
                    self.render_groups()
                    if value.cancelled:
                        self.status.set(tr('Skan anulowany. Wyniki niepełne — uruchom skan ponownie.'))
                    else:
                        self.status.set(tr('Gotowe • {v0} zdjęć • {v1} grup • {v2} uwag', v0=len(value.photos), v1=len(value.groups), v2=len(value.warnings)))
                elif kind == "recycle":
                    completed, errors = value
                    self.marked.clear()
                    # A new scan is mandatory after every disposal attempt.
                    self.result = ScanResult(warnings=errors)
                    self.render_groups()
                    self.status.set(tr('Przeniesiono do kosza: {v0}. Uruchom nowy skan. Uwagi: {v1}.', v0=len(completed), v1=len(errors)))
                    if errors and not self.closing:
                        messagebox.showwarning(tr('Przerwano przenoszenie'), "\n".join(errors))
                elif not self.closing:
                    self.status.set(tr('Operacja nie powiodła się.'))
                    messagebox.showerror("SWIR PhotoClean", value)
                self.update_summary()
        except queue.Empty:
            pass
        if self.closing and not self.busy:
            self.root.destroy()
            return
        self.poll_id = self.root.after(100, self.poll)

    def render_groups(self):
        self.groups.delete(*self.groups.get_children())
        self.files.delete(*self.files.get_children())
        self.active_group = None
        self.preview()
        for index, group in enumerate(self.result.groups):
            name = tr('Identyczne') if group.kind == "exact" else tr('Podobne • sprawdź')
            self.groups.insert("", "end", iid=str(index), text=f"{index + 1}. {name}", values=(len(group.photos),))
        if self.result.groups:
            self.groups.selection_set("0")
            self.choose_group()
        self.update_summary()

    def choose_group(self, event=None):
        selection = self.groups.selection()
        if not selection:
            return
        self.active_group = self.result.groups[int(selection[0])]
        self.files.delete(*self.files.get_children())
        for i, photo in enumerate(self.active_group.photos):
            self.files.insert("", "end", iid=str(i), values=(tr('TAK') if photo.path in self.marked else "—", photo.path.name, f"{photo.width} × {photo.height}", human_size(photo.size)))
        self.files.selection_set(self.files.get_children()[:2])
        self.preview()
        self.update_summary()

    def preview(self, event=None):
        self.images.clear()
        chosen = self.files.selection()[:2] if self.active_group else ()
        for index, (label, detail) in enumerate(self.preview_panels):
            label.configure(image="", text=tr('◇\n\nWybierz zdjęcie do porównania'))
            detail.configure(text="")
            if index >= len(chosen):
                continue
            photo = self.active_group.photos[int(chosen[index])]
            try:
                with Image.open(photo.path) as source:
                    if source.width * source.height > MAX_PIXELS:
                        raise ValueError(tr('Obraz przekracza limit podglądu'))
                    im = ImageOps.exif_transpose(source).convert("RGBA")
                    background = Image.new("RGBA", im.size, "white")
                    background.alpha_composite(im)
                    im = background.convert("RGB")
                    im.thumbnail((max(240, label.winfo_width()-16), max(120, label.winfo_height()-16)), Image.Resampling.LANCZOS)
                image = ImageTk.PhotoImage(im)
                self.images.append(image)
                label.configure(image=image, text="")
            except Exception:
                label.configure(text=tr('Podgląd niedostępny'))
            name = photo.path.name
            if len(name) > 20:
                name = f"{name[:9]}…{name[-8:]}"
            detail.configure(text=f"{name} • {photo.width}×{photo.height} • {human_size(photo.size)}")

    def open_preview(self, slot):
        chosen = self.files.selection()[:2] if self.active_group else ()
        if slot >= len(chosen):
            return
        photo = self.active_group.photos[int(chosen[slot])]
        try:
            with Image.open(photo.path) as source:
                if source.width * source.height > MAX_PIXELS:
                    raise ValueError(tr('Obraz przekracza limit podglądu'))
                im = ImageOps.exif_transpose(source).convert("RGBA")
                background = Image.new("RGBA", im.size, "white")
                background.alpha_composite(im)
                im = background.convert("RGB")
                im.thumbnail((self.root.winfo_screenwidth()-160, self.root.winfo_screenheight()-220), Image.Resampling.LANCZOS)
            window = tk.Toplevel(self.root)
            window.title(photo.path.name)
            window.configure(bg=BG)
            picture = ImageTk.PhotoImage(im)
            label = ttk.Label(window, image=picture, background=BG)
            label.image = picture
            label.pack(padx=16, pady=16)
            ttk.Label(window, text=str(photo.path), wraplength=800).pack(padx=16, pady=(0, 10))
            window.bind("<Escape>", lambda event: window.destroy())
        except (OSError, ValueError) as error:
            messagebox.showerror(tr('Podgląd niedostępny'), str(error))

    def copy_selected_paths(self):
        if not self.active_group:
            return
        paths = [str(self.active_group.photos[int(i)].path) for i in self.files.selection()]
        if not paths:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(paths))
        self.status.set(tr('Skopiowano pełne ścieżki wybranych zdjęć.'))

    def toggle_mark(self):
        if self.busy or not self.active_group:
            return
        paths = {self.active_group.photos[int(i)].path for i in self.files.selection()}
        if not paths:
            return
        proposed = self.marked - paths if paths <= self.marked else self.marked | paths
        if any(all(p.path in proposed for p in g.photos) for g in self.result.groups):
            messagebox.showwarning(tr('Zachowaj zdjęcie'), tr('Zostaw przynajmniej jedno zdjęcie w każdej grupie. Zaznacz pojedynczy wiersz, aby wybrać jedną kopię.'))
            return
        self.marked = proposed
        for i in self.files.get_children():
            self.files.set(i, "marked", tr('TAK') if self.active_group.photos[int(i)].path in self.marked else "—")
        self.update_summary()

    def clear_marks(self):
        if self.busy:
            return
        self.marked.clear()
        for i in self.files.get_children():
            self.files.set(i, "marked", "—")
        self.update_summary()

    def update_summary(self):
        size = sum(p.size for p in self.result.photos if p.path in self.marked)
        self.summary.set(tr('Do kosza: {v0} plików • {v1}', v0=len(self.marked), v1=human_size(size)))
        enabled = bool(self.result.groups) and not self.busy and not self.result.cancelled
        for button in (self.mark_button, self.clear_button, self.copy_button, self.export_button):
            button.configure(state="normal" if enabled else "disabled")
        self.trash_button.configure(state="normal" if enabled and self.marked else "disabled")

    def confirm_recycle(self):
        if self.busy or not self.marked:
            return
        names = "\n".join(str(p) for p in sorted(self.marked)[:8])
        if len(self.marked) > 8:
            names += tr('\n… i {v0} kolejnych', v0=len(self.marked) - 8)
        if not messagebox.askyesno(tr('Potwierdź przeniesienie do kosza'), tr('Przenieść {v0} plików do systemowego kosza?\n\n{v1}\n\nPodobne zdjęcia mogą przedstawiać różne ujęcia. Przywracanie odbywa się przez Kosz Windows.', v0=len(self.marked), v1=names), default="no"):
            return
        self.cancel.clear()
        chosen = set(self.marked)
        self.set_busy(True)
        def worker():
            try:
                value = recycle_selected(self.result, chosen, self.cancel, progress=self.progress)
                self.events.put(("recycle", value))
            except Exception as error:
                self.events.put(("recycle", ([], [str(error)])))
        threading.Thread(target=worker, daemon=True).start()

    def export(self):
        target = filedialog.asksaveasfilename(title=tr('Eksport wyników'), defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if target:
            try:
                export_csv(self.result, target)
                self.status.set(tr('Zapisano raport CSV.'))
            except OSError as error:
                messagebox.showerror(tr('Eksport nieudany'), str(error))

    def show_warnings(self):
        window = tk.Toplevel(self.root)
        window.title(tr('Raport skanowania'))
        window.geometry("850x400")
        text = tk.Text(window, wrap="word", bg=PANEL, fg=TEXT, font=("Segoe UI", 10))
        text.pack(fill="both", expand=True)
        text.insert("1.0", "\n\n".join(self.result.warnings) or tr('Brak uwag. Obsługiwane: JPG, PNG, WebP, BMP oraz jednostronicowe TIFF/GIF. HEIC i RAW nie są obsługiwane w tej wersji.'))
        text.configure(state="disabled")

    def close(self):
        if self.busy:
            if not messagebox.askyesno(tr('Trwa operacja'), tr('Przerwać operację i zamknąć po jej bezpiecznym zakończeniu?'), default="no"):
                return
            self.closing = True
            self.cancel.set()
            self.status.set(tr('Kończenie operacji…'))
        else:
            self.root.after_cancel(self.poll_id)
            self.root.destroy()


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
