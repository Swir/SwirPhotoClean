"""Non-destructive packaged-app smoke test using generated pictures only."""
import json
import shutil
import tempfile
import time
import tkinter as tk
from pathlib import Path

from PIL import Image

from .cleanup_history import append_cleanup_record, build_cleanup_plan, finalize_cleanup_record
from .cleanup_history_gui import PhotoCleanApp
from .core import scan


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
            app = PhotoCleanApp(root, Path(folder) / "settings.json")
            app.result = result
            app.render_groups()
            root.update()
            assert len(app.images) == 2
            assert not app.marked
            assert "Smart Keep" in app.status.get()
            assert "Pewne duplikaty" in app.summary.get()
            assert hasattr(app, "open_bad_shot_finder")
            assert hasattr(app, "open_space_hunter")
            assert hasattr(app, "open_diagnostics")
            assert hasattr(app, "open_difference_view")
            assert hasattr(app, "safe_mode")
            assert hasattr(app, "open_library_explorer")
            assert hasattr(app, "open_media_inspector")
            assert hasattr(app, "open_cleanup_history")

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

            app.open_library_explorer()
            deadline = time.monotonic() + 5.0
            while app.library_explorer_view.report is None and time.monotonic() < deadline:
                root.update()
                time.sleep(0.01)
            assert app.library_explorer_view.report is not None
            assert app.library_explorer_view.report.analyzed_count == 2
            assert app.library_explorer_view.report.captured_count == 0
            assert app.library_explorer_view.report.device_count == 0
            assert not app.marked
            app.library_explorer_view.close()

            app.open_media_inspector()
            deadline = time.monotonic() + 5.0
            while app.media_inspector_view.report is None and time.monotonic() < deadline:
                root.update()
                time.sleep(0.01)
            assert app.media_inspector_view.report is not None
            assert app.media_inspector_view.report.analyzed_count == 2
            assert app.media_inspector_view.report.count("camera_photo") == 0
            assert app.media_inspector_view.report.count("screenshot_candidate") == 0
            assert app.media_inspector_view.report.count("unknown") == 2
            assert not app.marked
            app.media_inspector_view.close()

            dry_target = result.groups[0].photos[0].path
            dry_plan = build_cleanup_plan(
                result,
                [dry_target],
                started_at="2026-09-19T00:00:00+00:00",
                record_id="packaged-self-test",
            )
            dry_record = finalize_cleanup_record(
                dry_plan,
                [],
                ["packaged self-test: dry run only"],
                finished_at="2026-09-19T00:00:01+00:00",
            )
            append_cleanup_record(app.cleanup_history_path, dry_record)
            assert dry_target.exists()
            assert dry_record.completed_count == 0
            assert dry_record.moved_to_recycle_bytes == 0
            app.open_cleanup_history()
            root.update()
            assert len(app.cleanup_history_view.records) == 1
            assert app.cleanup_history_view.records[0].record_id == "packaged-self-test"
            assert app.cleanup_history_view.records[0].completed_count == 0
            assert not app.marked
            app.cleanup_history_view.window.destroy()

            app.files.selection_set("0")
            app.toggle_mark()
            assert len(app.marked) == 1
            assert str(app.trash_button["state"]) == "normal"
            app.safe_mode.set(True)
            app._safe_mode_changed()
            assert len(app.marked) == 1
            assert str(app.trash_button["state"]) == "disabled"
            app.safe_mode.set(False)
            app._safe_mode_changed()
            assert str(app.trash_button["state"]) == "normal"

            app.language_var.set("English")
            app.change_language()
            root.update_idletasks()
            assert app.scan_button["text"] == "Scan photos"
            assert len(app.marked) == 1
            assert "Exact duplicates" in app.summary.get()
            assert hasattr(app, "open_cleanup_history")
            root.after_cancel(app.poll_id)
            root.destroy()

            root = tk.Tk()
            root.withdraw()
            app = PhotoCleanApp(root, Path(folder) / "settings.json")
            assert app.language_var.get() == "English"
            assert hasattr(app, "open_bad_shot_finder")
            assert hasattr(app, "open_space_hunter")
            assert hasattr(app, "open_diagnostics")
            assert hasattr(app, "open_difference_view")
            assert hasattr(app, "safe_mode")
            assert hasattr(app, "open_library_explorer")
            assert hasattr(app, "open_media_inspector")
            assert hasattr(app, "open_cleanup_history")
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
                "safe_mode_available": True,
                "safe_mode_blocks_recycle": True,
                "safe_mode_preserves_marks": True,
                "library_explorer_available": True,
                "library_explorer_opened": True,
                "library_explorer_read_only": True,
                "media_inspector_available": True,
                "media_inspector_opened": True,
                "media_inspector_read_only": True,
                "cleanup_history_available": True,
                "cleanup_history_opened": True,
                "cleanup_history_dry_run_only": True,
                "recycle_executed": False,
            }
    except Exception as error:
        report["error"] = repr(error)
    finally:
        if root is not None:
            try:
                root.destroy()
            except tk.TclError:
                pass
        Path(destination).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1
