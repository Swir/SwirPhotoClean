"""Non-destructive packaged-app smoke test using generated pictures only."""
import json
import shutil
import tempfile
import tkinter as tk
from pathlib import Path

from PIL import Image

from .core import scan
from .gui import PhotoCleanApp


def run(destination):
    report = {"ok": False}
    root = None
    try:
        with tempfile.TemporaryDirectory(prefix="swir-photoclean-smoke-") as folder:
            image = Path(folder) / "a.png"
            Image.new("RGB", (128, 96), "teal").save(image)
            shutil.copy(image, Path(folder) / "b.png")
            result = scan([folder])
            assert len(result.groups) == 1
            root = tk.Tk()
            root.withdraw()
            app = PhotoCleanApp(root, Path(folder) / 'settings.json')
            app.result = result
            app.render_groups()
            root.update()
            assert len(app.images) == 2
            assert not app.marked
            app.files.selection_set("0")
            app.toggle_mark()
            assert len(app.marked) == 1
            app.language_var.set('English')
            app.change_language()
            root.update_idletasks()
            assert app.scan_button['text'] == 'Scan photos'
            assert len(app.marked) == 1
            root.after_cancel(app.poll_id)
            root.destroy()
            root = tk.Tk()
            root.withdraw()
            app = PhotoCleanApp(root, Path(folder) / 'settings.json')
            assert app.language_var.get() == 'English'
            root.after_cancel(app.poll_id)
            report = {"ok": True, "exact_groups": 1, "previews": 2, "languages": ["pl", "en"], "language_persistence": True, "recycle_executed": False}
    except Exception as error:
        report["error"] = repr(error)
    finally:
        if root is not None:
            root.destroy()
        Path(destination).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1
