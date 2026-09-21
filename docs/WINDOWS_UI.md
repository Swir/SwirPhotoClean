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

The final app installs one idempotent `Map` observer on the persistent Tk root so
feature windows created later in the session receive the same native chrome. This
covers Folder Health, Diagnostics and other lazily created top-level review tools
without coupling those feature modules to Windows APIs. Language rebuilds do not
stack duplicate observers.

Unsupported DWM attributes are ignored and never affect scanning, review, cleanup,
or startup. These calls change no registry settings and persist no system
configuration.

## Modern client-area theme

The final desktop stack reapplies a flat electric-cyan theme after the base layout
is built. This intentionally changes presentation only:

- raised legacy ttk buttons become flat bordered controls with clear hover,
  pressed, focus and disabled states;
- tables, headings, combo boxes, entries, progress bars, tabs and scrollbars share
  the same dark/electric-cyan palette;
- legacy raised Tk preview frames are flattened into subtle bordered cards;
- list boxes and text/report views receive consistent focus borders;
- the theme is re-applied after a language rebuild and newly mapped Tk widgets are
  polished through one idempotent observer.

The theme does not change selection rules, scanner behavior, cleanup semantics or
the Recycle Bin safety path.

## Testing

`tests/test_windows_ui.py` covers:

- non-Windows no-op behavior;
- preference for per-monitor-v2;
- per-monitor and legacy DPI fallbacks;
- dark-title-bar attribute fallback;
- top-level chrome tracking and idempotency;
- safe no-op behavior outside Windows.

`tests/test_modern_theme.py` covers style tokens, flat preview-card conversion and
idempotent late-widget theme tracking.

The normal Windows CI still runs the complete unit suite, builds the PyInstaller
onedir package and executes the packaged self-test before an artifact is accepted.
