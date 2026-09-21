# Windows UI / HiDPI behavior

SwirPhotoClean targets Windows 10/11 and keeps its desktop UI local and native to
the bundled Tk runtime.

## DPI bootstrap

The application requests DPI awareness **before** creating the first Tk window.

1. `PER_MONITOR_AWARE_V2` is preferred on current Windows 10/11 builds.
2. If unavailable, the app falls back to per-monitor awareness through `shcore`.
3. A legacy system-DPI fallback is used only when newer APIs are unavailable.
4. Failure to change DPI mode never blocks startup; Windows/Tk keeps the existing
   process setting.

This is deliberately best-effort because packaged Python/Tk or a host process can
already establish DPI awareness before application code runs.

## Native window chrome

After the main window is built, SwirPhotoClean requests the Windows immersive dark
title bar. Windows 11 rounded top-level corners are also requested when supported.
Unsupported DWM attributes are ignored and never affect scanning, review, cleanup,
or startup.

These calls change no registry settings and persist no system configuration.

## Testing

`tests/test_windows_ui.py` covers:

- non-Windows no-op behavior;
- preference for per-monitor-v2;
- per-monitor and legacy DPI fallbacks;
- dark-title-bar attribute fallback;
- safe no-op behavior outside Windows.

The normal Windows CI still runs the complete unit suite, builds the PyInstaller
onedir package and executes the packaged self-test before an artifact is accepted.
