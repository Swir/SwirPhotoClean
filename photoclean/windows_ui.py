"""Windows-native UI bootstrap helpers.

The helpers are intentionally best-effort: unsupported Windows builds or an
already configured DPI context must never prevent the application from
starting. No registry or persistent system setting is changed.
"""
from __future__ import annotations

import ctypes
import os


_PER_MONITOR_AWARE_V2 = -4
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWCP_ROUND = 2


def configure_process_dpi_awareness() -> str:
    """Request the strongest supported Windows DPI mode before Tk is created.

    Returns a small diagnostic label describing the path that succeeded. The
    function fails closed to ``"unchanged"`` instead of making application
    startup depend on a particular Windows API being available.
    """

    if os.name != "nt":
        return "not-windows"

    try:
        user32 = ctypes.windll.user32
    except (AttributeError, OSError):
        user32 = None

    if user32 is not None:
        setter = getattr(user32, "SetProcessDpiAwarenessContext", None)
        if setter is not None:
            try:
                if setter(ctypes.c_void_p(_PER_MONITOR_AWARE_V2)):
                    return "per-monitor-v2"
            except (OSError, TypeError, ValueError):
                pass

    try:
        shcore = ctypes.windll.shcore
    except (AttributeError, OSError):
        shcore = None
    if shcore is not None:
        setter = getattr(shcore, "SetProcessDpiAwareness", None)
        if setter is not None:
            try:
                if int(setter(2)) == 0:
                    return "per-monitor"
            except (OSError, TypeError, ValueError):
                pass

    if user32 is not None:
        setter = getattr(user32, "SetProcessDPIAware", None)
        if setter is not None:
            try:
                if setter():
                    return "system"
            except (OSError, TypeError, ValueError):
                pass

    return "unchanged"


def apply_windows_chrome(root) -> bool:
    """Request dark native title-bar chrome and rounded Windows 11 corners.

    Tk still owns all client-area rendering. DWM calls are cosmetic and
    best-effort only, so failures never change application behaviour.
    """

    if os.name != "nt":
        return False

    try:
        root.update_idletasks()
        hwnd = int(root.winfo_id())
        if hwnd <= 0:
            return False
        dwmapi = ctypes.windll.dwmapi
    except (AttributeError, OSError, TypeError, ValueError):
        return False

    enabled = ctypes.c_int(1)
    applied = False
    for attribute in (
        _DWMWA_USE_IMMERSIVE_DARK_MODE,
        _DWMWA_USE_IMMERSIVE_DARK_MODE_OLD,
    ):
        try:
            result = int(
                dwmapi.DwmSetWindowAttribute(
                    ctypes.c_void_p(hwnd),
                    attribute,
                    ctypes.byref(enabled),
                    ctypes.sizeof(enabled),
                )
            )
        except (AttributeError, OSError, TypeError, ValueError):
            continue
        if result == 0:
            applied = True
            break

    # Windows 11 supports rounded top-level corners. Older builds simply return
    # an error for this attribute, which is intentionally ignored.
    corner = ctypes.c_int(_DWMWCP_ROUND)
    try:
        dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd),
            _DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(corner),
            ctypes.sizeof(corner),
        )
    except (AttributeError, OSError, TypeError, ValueError):
        pass

    return applied


def install_windows_chrome_tracking(root) -> bool:
    """Apply native chrome to the root and future Tk top-level windows.

    Feature windows are created lazily throughout a review session. A single
    global Map binding keeps Folder Health, Diagnostics, fullscreen comparison
    and other top-level windows visually consistent without coupling those
    feature modules to Windows APIs. The binding is idempotent and cosmetic
    failures are ignored.
    """

    if os.name != "nt":
        return False

    apply_windows_chrome(root)
    if getattr(root, "_swir_windows_chrome_tracking", False):
        return True

    def _on_map(event) -> None:
        widget = getattr(event, "widget", None)
        if widget is None:
            return
        try:
            if widget.winfo_toplevel() is widget:
                apply_windows_chrome(widget)
        except Exception:
            # This callback must never turn a cosmetic DWM failure into an
            # application/runtime failure.
            return

    try:
        root.bind_all("<Map>", _on_map, add="+")
    except Exception:
        return False
    setattr(root, "_swir_windows_chrome_tracking", True)
    return True
