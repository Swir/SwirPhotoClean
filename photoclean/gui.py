"""Tk desktop interface. Workers never call Tk; all events go through a queue."""
from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps, ImageTk

from . import __version__
from .core import MAX_PIXELS, ScanResult, export_csv, recycle_selected, scan

BG, PANEL, TEXT, MUTED, ACCENT = "#101723", "#192436", "#eef4ff", "#aebdd1", "#49d4bd"


def human_size(size):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024


class PhotoCleanApp:
    def __init__(self, root):
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
        root.title(f"SWIR PhotoClean {__version__}")
        root.geometry("1220x820")
        root.minsize(1000, 700)
        root.configure(bg=BG)
        root.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10), background=BG, foreground=TEXT)
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Title.TLabel", font=("Segoe UI", 25, "bold"))
        style.configure("TButton", background=PANEL, padding=(12, 8), borderwidth=0)
        style.map("TButton", background=[("active", "#2b405a")], foreground=[("disabled", "#76869a")])
        style.configure("Accent.TButton", background=ACCENT, foreground=BG, font=("Segoe UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#77e7d4"), ("disabled", PANEL)])
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT, rowheight=30, borderwidth=0)
        style.configure("Treeview.Heading", background="#22324a", foreground=TEXT, padding=6)
        style.map("Treeview", background=[("selected", "#315b78")])
        style.configure("TCheckbutton", background=BG)
        style.map("TCheckbutton", background=[("active", BG)])
        style.configure("TCombobox", fieldbackground=PANEL, foreground=TEXT)
        outer = ttk.Frame(root, padding=20)
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer)
        header.pack(fill="x")
        ttk.Label(header, text="SWIR PhotoClean", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="LOKALNIE  •  BEZ ABONAMENTU", foreground=ACCENT).pack(side="right")
        ttk.Label(outer, text="Odzyskaj miejsce. Porównaj zdjęcia. Zachowaj te, które chcesz.", style="Muted.TLabel").pack(anchor="w", pady=(2, 15))
        toolbar = ttk.Frame(outer)
        toolbar.pack(fill="x")
        self.add_button = ttk.Button(toolbar, text="+ Dodaj folder", command=self.add_folder)
        self.add_button.pack(side="left", padx=(0, 8))
        self.remove_button = ttk.Button(toolbar, text="Usuń folder z listy", command=self.remove_folder)
        self.remove_button.pack(side="left")
        self.similarity = tk.BooleanVar(value=True)
        self.sim_check = ttk.Checkbutton(toolbar, text="Szukaj też podobnych", variable=self.similarity)
        self.sim_check.pack(side="left", padx=15)
        self.level = tk.StringVar(value="Standardowy")
        self.level_box = ttk.Combobox(toolbar, textvariable=self.level, values=["Ścisły", "Standardowy", "Szeroki"], state="readonly", width=15)
        self.level_box.pack(side="left")
        self.scan_button = ttk.Button(toolbar, text="Skanuj zdjęcia", style="Accent.TButton", command=self.start_scan)
        self.scan_button.pack(side="right")
        self.folders = tk.Listbox(outer, height=3, bg=PANEL, fg=TEXT, selectbackground="#315b78", relief="flat", font=("Segoe UI", 10), exportselection=False)
        self.folders.pack(fill="x", pady=(10, 8))
        status_row = ttk.Frame(outer)
        status_row.pack(fill="x", pady=(0, 8))
        self.status = tk.StringVar(value="Dodaj foldery ze zdjęciami. Skanowanie niczego nie usuwa.")
        ttk.Label(status_row, textvariable=self.status, style="Muted.TLabel", wraplength=900).pack(side="left")
        self.cancel_button = ttk.Button(status_row, text="Anuluj", command=self.cancel.set, state="disabled")
        self.cancel_button.pack(side="right")
        self.bar = ttk.Progressbar(outer, mode="indeterminate")
        self.bar.pack(fill="x", pady=(0, 12))
        panes = ttk.Panedwindow(outer, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left, right = ttk.Frame(panes), ttk.Frame(panes)
        panes.add(left, weight=1)
        panes.add(right, weight=3)
        ttk.Label(left, text="GRUPY ZDJĘĆ", foreground=ACCENT).pack(anchor="w", pady=(0, 8))
        self.groups = ttk.Treeview(left, columns=("count",), show="tree headings", selectmode="browse", height=8)
        self.groups.heading("#0", text="Rodzaj")
        self.groups.heading("count", text="Pliki")
        self.groups.column("#0", width=180, minwidth=120)
        self.groups.column("count", width=50, stretch=False)
        self.groups.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(left, command=self.groups.yview)
        scrollbar.pack(side="right", fill="y")
        self.groups.configure(yscrollcommand=scrollbar.set)
        self.groups.bind("<<TreeviewSelect>>", self.choose_group)
        ttk.Label(right, text="Wybierz do dwóch wierszy do porównania (Ctrl + klik).", style="Muted.TLabel").pack(anchor="w", padx=12)
        file_frame = ttk.Frame(right, padding=(12, 8, 0, 0))
        file_frame.pack(fill="x")
        self.files = ttk.Treeview(file_frame, columns=("marked", "name", "pixels", "size"), show="headings", height=5, selectmode="extended")
        for key, title, width in [("marked", "Do kosza", 65), ("name", "Zdjęcie", 240), ("pixels", "Wymiary", 110), ("size", "Rozmiar", 90)]:
            self.files.heading(key, text=title)
            self.files.column(key, width=width, minwidth=width if key != "name" else 100, stretch=key == "name")
        self.files.pack(side="left", fill="x", expand=True)
        fs = ttk.Scrollbar(file_frame, command=self.files.yview)
        fs.pack(side="right", fill="y")
        self.files.configure(yscrollcommand=fs.set)
        self.files.bind("<<TreeviewSelect>>", self.preview)
        self.files.bind("<space>", lambda event: self.toggle_mark())
        actions = ttk.Frame(right, padding=(12, 8))
        actions.pack(fill="x")
        self.mark_button = ttk.Button(actions, text="Zaznacz / odznacz do kosza", command=self.toggle_mark, state="disabled")
        self.mark_button.pack(side="left")
        self.clear_button = ttk.Button(actions, text="Odznacz wszystko", command=self.clear_marks, state="disabled")
        self.clear_button.pack(side="left", padx=8)
        self.preview_frame = ttk.Frame(right, padding=(12, 0, 0, 0))
        self.preview_frame.pack(fill="both", expand=True)
        self.preview_panels = []
        for col in range(2):
            self.preview_frame.columnconfigure(col, weight=1, uniform="preview")
            panel = ttk.Frame(self.preview_frame)
            panel.grid(row=0, column=col, sticky="nsew", padx=4)
            label = ttk.Label(panel, text="Wybierz zdjęcie", anchor="center", background=PANEL)
            label.pack(fill="both", expand=True)
            detail = ttk.Label(panel, text="", style="Muted.TLabel", wraplength=290, justify="left")
            detail.pack(fill="x", pady=5)
            self.preview_panels.append((label, detail))
        self.preview_frame.rowconfigure(0, weight=1)
        footer = ttk.Frame(outer, padding=(0, 12, 0, 0))
        footer.pack(fill="x")
        self.summary = tk.StringVar(value="Brak wyników")
        ttk.Label(footer, textvariable=self.summary).pack(side="left")
        self.trash_button = ttk.Button(footer, text="Przenieś zaznaczone do kosza", command=self.confirm_recycle, state="disabled")
        self.trash_button.pack(side="right")
        self.export_button = ttk.Button(footer, text="Eksport CSV", command=self.export, state="disabled")
        self.export_button.pack(side="right", padx=8)
        self.warning_button = ttk.Button(footer, text="Raport", command=self.show_warnings)
        self.warning_button.pack(side="right")
        ttk.Label(outer, text="Podobne ≠ identyczne. Sprawdź podgląd. Nic nie jest zaznaczane automatycznie.", style="Muted.TLabel").pack(anchor="w", pady=(8, 0))
        self.poll_id = self.root.after(100, self.poll)

    def add_folder(self):
        folder = filedialog.askdirectory(title="Wybierz folder ze zdjęciami")
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
            messagebox.showinfo("Wybierz folder", "Najpierw dodaj co najmniej jeden folder.")
            return
        threshold = {"Ścisły": 3, "Standardowy": 6, "Szeroki": 10}[self.level.get()]
        include_similar = self.similarity.get()
        self.cancel.clear()
        self.result = ScanResult()
        self.marked.clear()
        self.render_groups()
        self.set_busy(True)
        self.status.set("Rozpoczynanie skanowania…")
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
                        self.status.set("Skan anulowany. Wyniki niepełne — uruchom skan ponownie.")
                    else:
                        self.status.set(f"Gotowe • {len(value.photos)} zdjęć • {len(value.groups)} grup • {len(value.warnings)} uwag")
                elif kind == "recycle":
                    completed, errors = value
                    self.marked.clear()
                    # A new scan is mandatory after every disposal attempt.
                    self.result = ScanResult(warnings=errors)
                    self.render_groups()
                    self.status.set(f"Przeniesiono do kosza: {len(completed)}. Uruchom nowy skan. Uwagi: {len(errors)}.")
                    if errors and not self.closing:
                        messagebox.showwarning("Przerwano przenoszenie", "\n".join(errors))
                elif not self.closing:
                    self.status.set("Operacja nie powiodła się.")
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
            name = "Identyczne" if group.kind == "exact" else "Podobne • sprawdź"
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
            self.files.insert("", "end", iid=str(i), values=("TAK" if photo.path in self.marked else "—", photo.path.name, f"{photo.width} × {photo.height}", human_size(photo.size)))
        self.files.selection_set(self.files.get_children()[:2])
        self.preview()
        self.update_summary()

    def preview(self, event=None):
        self.images.clear()
        chosen = self.files.selection()[:2] if self.active_group else ()
        for index, (label, detail) in enumerate(self.preview_panels):
            label.configure(image="", text="Wybierz zdjęcie")
            detail.configure(text="")
            if index >= len(chosen):
                continue
            photo = self.active_group.photos[int(chosen[index])]
            try:
                with Image.open(photo.path) as source:
                    if source.width * source.height > MAX_PIXELS:
                        raise ValueError("Obraz przekracza limit podglądu")
                    im = ImageOps.exif_transpose(source).convert("RGB")
                    im.thumbnail((310, 225), Image.Resampling.LANCZOS)
                image = ImageTk.PhotoImage(im)
                self.images.append(image)
                label.configure(image=image, text="")
            except Exception:
                label.configure(text="Podgląd niedostępny")
            detail.configure(text=f"{photo.path}\n{photo.width} × {photo.height} px • {human_size(photo.size)}")

    def toggle_mark(self):
        if self.busy or not self.active_group:
            return
        paths = {self.active_group.photos[int(i)].path for i in self.files.selection()}
        if not paths:
            return
        proposed = self.marked - paths if paths <= self.marked else self.marked | paths
        if any(all(p.path in proposed for p in g.photos) for g in self.result.groups):
            messagebox.showwarning("Zachowaj zdjęcie", "Zostaw przynajmniej jedno zdjęcie w każdej grupie. Zaznacz pojedynczy wiersz, aby wybrać jedną kopię.")
            return
        self.marked = proposed
        for i in self.files.get_children():
            self.files.set(i, "marked", "TAK" if self.active_group.photos[int(i)].path in self.marked else "—")
        self.update_summary()

    def clear_marks(self):
        self.marked.clear()
        for i in self.files.get_children():
            self.files.set(i, "marked", "—")
        self.update_summary()

    def update_summary(self):
        size = sum(p.size for p in self.result.photos if p.path in self.marked)
        self.summary.set(f"Do kosza: {len(self.marked)} plików • {human_size(size)}")
        enabled = bool(self.result.groups) and not self.busy and not self.result.cancelled
        for button in (self.mark_button, self.clear_button, self.export_button):
            button.configure(state="normal" if enabled else "disabled")
        self.trash_button.configure(state="normal" if enabled and self.marked else "disabled")

    def confirm_recycle(self):
        if self.busy or not self.marked:
            return
        names = "\n".join(str(p) for p in sorted(self.marked)[:8])
        if len(self.marked) > 8:
            names += f"\n… i {len(self.marked) - 8} kolejnych"
        if not messagebox.askyesno("Potwierdź przeniesienie do kosza", f"Przenieść {len(self.marked)} plików do systemowego kosza?\n\n{names}\n\nPodobne zdjęcia mogą przedstawiać różne ujęcia. Przywracanie odbywa się przez Kosz Windows.", default="no"):
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
        target = filedialog.asksaveasfilename(title="Eksport wyników", defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if target:
            try:
                export_csv(self.result, target)
                self.status.set("Zapisano raport CSV.")
            except OSError as error:
                messagebox.showerror("Eksport nieudany", str(error))

    def show_warnings(self):
        window = tk.Toplevel(self.root)
        window.title("Raport skanowania")
        window.geometry("850x400")
        text = tk.Text(window, wrap="word", bg=PANEL, fg=TEXT, font=("Segoe UI", 10))
        text.pack(fill="both", expand=True)
        text.insert("1.0", "\n\n".join(self.result.warnings) or "Brak uwag. Obsługiwane: JPG, PNG, WebP, BMP oraz jednostronicowe TIFF/GIF. HEIC i RAW nie są obsługiwane w tej wersji.")
        text.configure(state="disabled")

    def close(self):
        if self.busy:
            if not messagebox.askyesno("Trwa operacja", "Przerwać operację i zamknąć po jej bezpiecznym zakończeniu?", default="no"):
                return
            self.closing = True
            self.cancel.set()
            self.status.set("Kończenie operacji…")
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
