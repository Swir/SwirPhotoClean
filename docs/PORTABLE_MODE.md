# Portable Mode

SWIR PhotoClean can keep its local application state beside the extracted Windows package instead of using the normal per-user settings directory.

## Start portable mode

From the extracted application directory, either run:

```powershell
.\SwirPhotoClean.exe --portable
```

or create an empty file named:

```text
portable.flag
```

beside `SwirPhotoClean.exe` and start the application normally.

## Storage layout

Portable mode resolves the settings path to:

```text
<application folder>\data\settings.json
```

The cleanup-history component derives its local audit file from the same settings location, so its metadata also stays under the portable `data` directory. Saved scan/review session files remain explicit user-selected files; Portable Mode does not silently copy photo libraries or session exports.

The current application does not maintain an on-disk thumbnail/image cache. If such a cache is introduced later, it must follow the same portable data-root policy rather than writing elsewhere without disclosure.

## Safety boundary

Portable Mode changes **only where local application state is stored**. It does not change any cleanup rule:

- exact duplicate detection still relies on full SHA-256 evidence;
- similar-photo matches remain review-only;
- nothing is automatically selected for cleanup;
- every selected target is revalidated before the operation;
- the application must preserve at least one member of each affected group;
- Windows Recycle Bin is still the only cleanup path on Windows;
- there is no permanent-delete fallback;
- network/removable-drive cleanup restrictions remain unchanged.

If the extracted application folder is read-only, settings/history persistence can fail. SWIR PhotoClean must report that failure rather than silently switching the cleanup path or weakening safety.

## CI verification

The Windows workflow runs the packaged executable in both normal and portable self-test modes. The portable smoke verifies that `--portable` composes with `--self-test`, resolves a local `data/settings.json` target and can create/read/remove a settings probe in that directory without touching photo files.
