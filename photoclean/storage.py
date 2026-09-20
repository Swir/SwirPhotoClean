"""Runtime storage policy for normal and portable launches.

Portable mode is intentionally narrow: it redirects only local application state
(settings and the cleanup-history file derived from that settings path) to a
writable data directory beside the application. It never changes scan, review or
Recycle Bin safety behavior.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

PORTABLE_SWITCH = "--portable"
PORTABLE_MARKER = "portable.flag"
PORTABLE_DATA_DIR = "data"
PORTABLE_SETTINGS_FILE = "settings.json"


@dataclass(frozen=True)
class RuntimeStorage:
    argv: tuple[str, ...]
    portable: bool
    app_dir: Path
    settings_path: Path | None
    source: str | None


def application_dir() -> Path:
    """Return the directory that owns the runnable application payload."""

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resolve_runtime_storage(
    argv: Iterable[str] | None = None,
    *,
    app_dir: Path | str | None = None,
) -> RuntimeStorage:
    """Resolve portable-mode state without mutating the filesystem.

    Portable mode can be enabled explicitly with ``--portable`` or by placing an
    empty ``portable.flag`` file beside the executable/source launcher. The switch
    is removed before normal command dispatch so it composes with ``--self-test``.
    """

    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(app_dir).resolve() if app_dir is not None else application_dir()
    explicit = PORTABLE_SWITCH in args
    clean_args = tuple(value for value in args if value != PORTABLE_SWITCH)
    marker = (root / PORTABLE_MARKER).is_file()
    portable = explicit or marker
    source = "argument" if explicit else ("marker" if marker else None)
    settings_path = (
        root / PORTABLE_DATA_DIR / PORTABLE_SETTINGS_FILE if portable else None
    )
    return RuntimeStorage(
        argv=clean_args,
        portable=portable,
        app_dir=root,
        settings_path=settings_path,
        source=source,
    )
