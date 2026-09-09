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
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        from photoclean.selftest import run
        raise SystemExit(run(sys.argv[2]))
    from photoclean.gui import main
    main()
