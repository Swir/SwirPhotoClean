"""Non-destructive packaged-app smoke test using generated pictures only."""
import json
import shutil
import tempfile
import tkinter as tk
from pathlib import Path

from PIL import Image

from .core import scan
from .difference_gui import PhotoCleanApp


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
            assert 'Smart Keep' in app.status.get()
            assert 'Pewne duplikaty' in app.summary.get()
            assert hasattr(app, 'open_bad_shot_finder')
            assert hasattr(app, 'open_space_hunter')
            assert hasattr(app, 'open_diagnostics')
            assert hasattr(app, 'open_difference_view')
            app.open_space_hunter()
            root.update()
            assert app.space_hunter_view.report.photo_count == 2
            assert app.space_hunter_view.report.exact_duplicate_files == 1
            assert app.space_hunter_view.report.exact_reclaimable_bytes == image.stat().st_size
            assert not app.marked
            app.space_hunter_view.window.destroy()
            app.open_diagnostics()
            root.update()
            assert app.diagnostics_view.snapshot.photo_count == 2
            assert app.diagnostics_view.snapshot.exact_group_count == 1
            assert app.diagnostics_view.snapshot.marked_count == 0
            app.diagnostics_view.window.destroy()
            app.open_difference_view()
            root.update()
            assert app.difference_view.preview.report.changed_ratio == 0.0
            assert app.difference_view.preview.report.mean_delta == 0.0
            assert not app.marked
            app.difference_view.window.destroy()
            app.files.selection_set("0")
            app.toggle_mark()
            assert len(app.marked) == 1
            app.language_var.set('English')
            app.change_language()
            root.update_idletasks()
            assert app.scan_button['text'] == 'Scan photos'
            assert len(app.marked) == 1
            assert 'Exact duplicates' in app.summary.get()
            root.after_cancel(app.poll_id)
            root.destroy()
            root = tk.Tk()
            root.withdraw()
            app = PhotoCleanApp(root, Path(folder) / 'settings.json')
            assert app.language_var.get() == 'English'
            assert hasattr(app, 'open_bad_shot_finder')
            assert hasattr(app, 'open_space_hunter')
            assert hasattr(app, 'open_diagnostics')
            assert hasattr(app, 'open_difference_view')
            root.after_cancel(app.poll_id)
            report = {
                "ok": True,
                "exact_groups": 1,
                "previews": 2,
                "languages": ["pl", "en"],
                "language_persistence": True,
                "smart_keep_visible": True,
                "folder_health_visible": True,
                "bad_shot_finder_available": True,
                "space_hunter_available": True,
                "space_hunter_opened": True,
                "diagnostics_available": True,
                "diagnostics_opened": True,
                "difference_view_available": True,
                "difference_view_opened": True,
                "difference_view_read_only": True,
                "recycle_executed": False,
            }
    except Exception as error:
        report["error"] = repr(error)
    finally:
        if root is not None:
            root.destroy()
        Path(destination).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1
