# Windows Recycle Bin restore evidence

SWIR PhotoClean 1.0 must not claim the final Recycle Bin acceptance item until a real Windows session proves both parts of the workflow:

1. a generated duplicate copy is moved through the application’s recycle-only path while the generated original remains unchanged, and
2. that generated copy is manually restored from Windows Recycle Bin to its original path and still has the same SHA-256 as the preserved original.

The helper in this repository makes that check reproducible without touching personal photos. It does **not** mark `STATUS.md` complete automatically and it does **not** restore or permanently delete anything by itself.

## Packaged EXE — recommended

From an extracted Windows build, run:

```powershell
.\SwirPhotoClean.exe --recycle-restore-prepare
```

Optional: provide a specific local workspace folder as the next argument:

```powershell
.\SwirPhotoClean.exe --recycle-restore-prepare "C:\Users\you\Documents\SwirPhotoClean-Recycle-Test"
```

The command creates two small generated files with identical content: an **original** that must remain in place and a **copy** that is sent through the same recycle-only backend used by cleanup. Before the move request, an evidence JSON is written atomically. A successful prepare step records:

- `phase = "awaiting_restore"`
- `recycle_move_confirmed = true`
- `original_preserved = true`
- the original path, copy path and expected SHA-256

If Windows refuses the Recycle Bin operation, the helper records `phase = "recycle_failed"`; the 1.0 gate remains open.

## Manual restore step

After `MOVE_CONFIRMED` is printed:

1. open **Windows Recycle Bin** normally,
2. find the generated file whose name starts with `SwirPhotoClean-copy-`,
3. choose **Restore** in Windows,
4. do not rename or edit either generated file,
5. run the verification command shown by the helper.

Example:

```powershell
.\SwirPhotoClean.exe --recycle-restore-verify "C:\Users\you\Documents\SwirPhotoClean-Recycle-Restore-Test\SwirPhotoClean-recycle-evidence-XXXXXXXXXX.json"
```

A successful verification prints `RESTORE_VERIFIED` and updates the same evidence JSON to:

- `phase = "verified"`
- `restore_verified = true`
- `original_preserved = true`
- `recycle_move_confirmed = true`

Verification re-hashes both generated files and refuses success if the original disappeared or changed, if the restored copy is missing, or if the restored copy hash differs.

## From source

The same commands work through the source launcher:

```powershell
py -3.12 run.py --recycle-restore-prepare
py -3.12 run.py --recycle-restore-verify "PATH_TO_EVIDENCE.json"
```

## Safety rules

- The helper creates only its own small generated test files.
- It never scans or modifies personal photos.
- The move step calls `photoclean.recycle.recycle_file`; there is no permanent-delete fallback.
- Windows fixed-drive restrictions from the recycle backend still apply. Network or removable locations can be rejected.
- The helper never empties the Recycle Bin.
- Restore remains an explicit Windows action by the user, so the acceptance evidence represents a real restore rather than a simulated application path.
- Unit tests simulate a recycle bin with a temporary directory only to test state handling. Those tests are not sufficient to close the physical Windows acceptance gate.

## Evidence handling

Keep the verified JSON with release-candidate test evidence. It contains only the generated test paths, timestamps and SHA-256 required to prove the acceptance check. After the evidence has been reviewed and retained, the generated files may be removed manually by the tester.

Do **not** change the final checkbox in `STATUS.md` merely because source tests or CI pass. The checkbox should move to `[x]` only after a real Windows run produces verified evidence for the move and manual restore while preserving the generated original.
