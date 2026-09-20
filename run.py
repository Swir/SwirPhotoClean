import os
import sys
from pathlib import Path


def prepare_frozen_tk():
    """Let Tcl find bundled scripts even when a launcher supplies another cwd."""
    if not getattr(sys, "frozen", False):
        return
    app_dir = Path(sys.executable).resolve().parent
    os.chdir(app_dir)
    internal = app_dir / "_internal"
    tcl = internal / "_tcl_data"
    tk = internal / "_tk_data"
    if tcl.is_dir():
        os.environ["TCL_LIBRARY"] = os.path.relpath(tcl, app_dir)
    if tk.is_dir():
        os.environ["TK_LIBRARY"] = os.path.relpath(tk, app_dir)


if __name__ == "__main__":
    prepare_frozen_tk()

    from photoclean.storage import resolve_runtime_storage

    runtime = resolve_runtime_storage()
    if len(runtime.argv) == 2 and runtime.argv[0] == "--self-test":
        from photoclean.selftest_performance import run

        raise SystemExit(run(runtime.argv[1], settings_path=runtime.settings_path))

    if runtime.argv and runtime.argv[0] in {
        "--recycle-restore-prepare",
        "--recycle-restore-verify",
    }:
        from photoclean.recycle_evidence import cli_main

        raise SystemExit(cli_main(runtime.argv))

    from photoclean.folder_health_app import main

    main(settings_path=runtime.settings_path)
