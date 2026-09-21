# Windows Recycle Bin restore evidence

SWIR PhotoClean 1.0 must not claim the final Recycle Bin acceptance item until a real Windows session proves both parts of the workflow:

1. the generated `RECYCLE-ME.png` is moved through the application’s recycle-only backend while generated `KEEP-ME.png` remains unchanged, and
2. `RECYCLE-ME.png` is manually restored from Windows Recycle Bin to its original path and still matches the preserved original.

The repository already has a tamper-evident verification model in `photoclean.diagnostics`: UUID session identity, ordered stage events, SHA-256, expected file size, distinct-file checks and a manifest fingerprint. The packaged/source CLI is a thin adapter over that same model; it does not introduce a second evidence format and it does **not** close `STATUS.md` automatically.

## Packaged EXE — recommended release-candidate check

From an extracted Windows build, run:

```powershell
.\SwirPhotoClean.exe --recycle-restore-prepare
```

Optionally provide a workspace on a local fixed drive:

```powershell
.\SwirPhotoClean.exe --recycle-restore-prepare "C:\Users\you\Documents\SwirPhotoClean-Recycle-Test"
```

The command creates a unique generated verification folder containing:

- `KEEP-ME.png` — generated original that must remain untouched,
- `RECYCLE-ME.png` — byte-identical generated copy sent through `photoclean.recycle.recycle_file`,
- `recycle-verification.json` — tamper-evident manifest written before the move.

A successful prepare command prints `MOVE_CONFIRMED` only after the recycle backend reports success, the generated original still has the expected SHA-256/size and `RECYCLE-ME.png` is absent from its original path. The manifest is then in stage `recycled`.

If Windows refuses the move, the helper prints `MOVE_NOT_CONFIRMED` plus the exact prepared manifest path. The manifest stays in stage `prepared`, both generated files remain available, and there is still no permanent-delete fallback.

### Retry a failed move without recreating the fixture

A transient Windows/permission problem no longer requires creating a new verification session. After fixing the cause, retry the same prepared fixture:

```powershell
.\SwirPhotoClean.exe --recycle-restore-move "C:\...\recycle-verification.json"
```

The retry reloads and revalidates the tamper-evident manifest, the generated original and the generated copy before invoking the same recycle-only backend. It refuses any manifest that is no longer in the `prepared` stage and does not bypass the fixed-drive or permanent-delete protections.

## Read-only status check

At any point you can inspect the evidence state without changing the manifest or moving files:

```powershell
.\SwirPhotoClean.exe --recycle-restore-status "C:\...\recycle-verification.json"
```

The command validates the manifest fingerprint, ordered event log and current generated-file state. It prints the current stage plus the exact next action:

- `prepared` → retry the guarded move with `--recycle-restore-move`,
- `recycled` → restore `RECYCLE-ME.png` in Windows and run `--recycle-restore-verify`,
- `restored-verified` → validate `recycle-evidence-report.json` against a fresh inspection and show the final read-only review command.

The status command is read-only. An inconsistent/tampered session or stale/tampered report returns `EVIDENCE_FAILED` instead of guessing, repairing evidence or printing `READY_FOR_REVIEW`.

## Manual Windows restore

After `MOVE_CONFIRMED`:

1. open **Windows Recycle Bin**,
2. find `RECYCLE-ME.png` from the generated verification session,
3. choose **Restore** in Windows,
4. do not rename, replace or edit either generated PNG,
5. run the verification command printed by the helper.

Example:

```powershell
.\SwirPhotoClean.exe --recycle-restore-verify "C:\...\SwirPhotoClean-Recycle-Check-...\recycle-verification.json"
```

Successful verification requires:

- the manifest fingerprint and ordered event log to be valid,
- `KEEP-ME.png` to remain the expected regular file with matching size and SHA-256,
- restored `RECYCLE-ME.png` to be a regular file with matching size and SHA-256,
- original and restored copy to remain physically distinct (a hardlink cannot fake restore evidence).

The command then records stage `restored-verified` and writes `recycle-evidence-report.json` beside the manifest. That report deliberately contains `acceptance_gate_closed: false`; repository status changes still require review of real Windows evidence.

### Final read-only report review

Before changing the remaining 1.0 acceptance checkbox, validate the exported report against the **current** tamper-evident manifest and generated files:

```powershell
.\SwirPhotoClean.exe --recycle-restore-review "C:\...\recycle-evidence-report.json"
```

The command performs a fresh fixture inspection and requires all of the following:

- the live manifest is still valid and still at `restored-verified`,
- the exported report still says `acceptance_gate_closed: false`,
- the report’s embedded manifest exactly matches the live manifest,
- the report’s embedded inspection exactly matches a newly computed inspection of both generated files.

A valid report prints `REPORT_VALID` and `READY_FOR_MANUAL_ACCEPTANCE_REVIEW`. A stale, edited, mismatched or malformed report returns `EVIDENCE_FAILED`. The command is read-only: it does not move files, rewrite the manifest/report, or change `STATUS.md`.

### Interrupted report export is recoverable

The `restored-verified` manifest transition is deliberately durable. If verification proves the restore but writing `recycle-evidence-report.json` then fails because of a temporary disk or permission problem, **do not repeat the move/restore cycle** and do not edit the manifest. Run the same `--recycle-restore-verify` command again after fixing the write problem.

The retry performs a fresh read-only validation of the manifest plus both generated files, recreates the report, and does not append a duplicate `restored-verified` event. A changed/missing file or tampered manifest is still rejected. This makes release evidence recovery deterministic without weakening the physical restore requirement.

## From source

The same workflow is available through Python 3.12:

```powershell
py -3.12 run.py --recycle-restore-prepare
py -3.12 run.py --recycle-restore-status "PATH_TO_recycle-verification.json"
py -3.12 run.py --recycle-restore-move "PATH_TO_recycle-verification.json"
py -3.12 run.py --recycle-restore-verify "PATH_TO_recycle-verification.json"
py -3.12 run.py --recycle-restore-review "PATH_TO_recycle-evidence-report.json"
```

## Safety boundaries

- Only generated verification PNGs are involved; personal photos are never selected by this helper.
- The move and move-retry phases use the same recycle-only backend as cleanup.
- There is no `unlink`/permanent-delete fallback in the production move path.
- Local fixed-drive restrictions remain enforced by `photoclean.recycle`.
- A move retry revalidates the original/copy contents and requires the manifest to remain at `prepared`.
- The status and report-review commands are read-only and cannot advance stages.
- A present report is not considered review-ready until it matches the live manifest and a fresh file inspection.
- The helper never empties Windows Recycle Bin.
- The helper never performs restore itself; restore remains an explicit Windows action so the acceptance evidence is physical, not simulated.
- Unit tests use injected temporary-file recyclers only to validate state transitions and failure safety. Those tests cannot close the physical Windows acceptance gate.

## 1.0 evidence rule

Do **not** change the remaining `[ ]` item in `STATUS.md` merely because unit tests, CI, PyInstaller or packaged self-test pass. It may become `[x]` only after a real Windows release-candidate run reaches `restored-verified`, the generated original is preserved, and the evidence manifest/report are reviewed as genuine move-and-restore evidence. `--recycle-restore-review` is a consistency gate for that review; it is not a substitute for the physical Windows restore.
