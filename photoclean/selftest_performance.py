"""Packaged smoke extension for final UI wiring and performance-profile persistence."""
from __future__ import annotations

import json
import shutil
import tempfile
import tkinter as tk
from pathlib import Path

from PIL import Image

from .core import scan
from .fullscreen_plus_gui import PhotoCleanApp
from .selftest import run as run_base


def _canonical(result):
    return (
        tuple((photo.path.name, photo.digest, photo.dhash, photo.color) for photo in result.photos),
        tuple((group.kind, tuple(photo.path.name for photo in group.photos)) for group in result.groups),
    )


def run(destination):
    destination = Path(destination)
    code = run_base(destination)
    if code:
        return code
    report = json.loads(destination.read_text(encoding="utf-8"))
    root = None
    try:
        with tempfile.TemporaryDirectory(prefix="swir-photoclean-profile-smoke-") as folder:
            folder = Path(folder)
            image = folder / "a.png"
            Image.new("RGB", (192, 128), "#326e8f").save(image)
            shutil.copy2(image, folder / "b.png")
            eco = scan([folder], performance_profile="eco")
            fast = scan([folder], performance_profile="fast")
            assert _canonical(eco) == _canonical(fast)

            settings = folder / "settings.json"
            root = tk.Tk()
            root.withdraw()
            app = PhotoCleanApp(root, settings)
            assert app.performance_profile.get() == "balanced"
            assert hasattr(app, "review_filter_entry")
            assert hasattr(app, "review_sort_box")
            assert app.review_sort_mode == "recommended"
            assert app.open_fullscreen_compare.__func__.__module__ == "photoclean.fullscreen_plus_gui"
            assert root.bind("<Control-f>")
            app.result = eco
            app.render_groups()
            app.review_filter_var.set("b.png")
            app._apply_review_view()
            assert len(app.files.get_children()) == 1
            assert not app.marked
            app.performance_profile.set("fast")
            app._performance_changed()
            root.update_idletasks()
            assert app.performance_profile.get() == "fast"
            root.after_cancel(app.poll_id)
            root.destroy()
            root = None

            root = tk.Tk()
            root.withdraw()
            app = PhotoCleanApp(root, settings)
            assert app.performance_profile.get() == "fast"
            assert hasattr(app, "performance_menu")
            assert hasattr(app, "review_filter_entry")
            assert app.open_fullscreen_compare.__func__.__module__ == "photoclean.fullscreen_plus_gui"
            root.after_cancel(app.poll_id)
            root.destroy()
            root = None

        report.update(
            performance_profiles_available=True,
            performance_profile_persistence=True,
            performance_profiles_equivalent=True,
            review_filter_available=True,
            keyboard_power_mode_available=True,
            review_filter_non_destructive=True,
            integrated_fullscreen_difference_available=True,
        )
    except Exception as error:
        report["ok"] = False
        report["performance_profile_error"] = repr(error)
    finally:
        if root is not None:
            try:
                root.destroy()
            except tk.TclError:
                pass
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report.get("ok") else 1
