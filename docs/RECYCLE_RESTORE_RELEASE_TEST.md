# SWIR PhotoClean 1.0 — Windows Recycle/Restore acceptance runbook

This runbook closes only the final manual acceptance item in `STATUS.md`. It does not authorize a release by itself.

## Candidate requirements

Use the exact Windows package produced by a green `main` workflow for the commit intended for 1.0. Extract the whole artifact and keep `SwirPhotoClean.exe` with its bundled files.

Before touching the acceptance checklist, run the packaged self-test:

```powershell
.\SwirPhotoClean.exe --self-test candidate-self-test.json
```

The command must exit with code 0 and the JSON report must contain `"ok": true`.

## Physical Recycle/Restore test

1. Start a fresh generated evidence session from the packaged executable:

```powershell
.\SwirPhotoClean.exe --recycle-restore-prepare
```

2. The command must report `MOVE_CONFIRMED`, `ORIGINAL_PRESERVED` and the manifest path. Do not recreate or rename the generated fixture.

3. Open Windows Recycle Bin and manually choose **Restore** for `RECYCLE-ME.png`.

4. Verify the restored file with the exact manifest printed by step 1:

```powershell
.\SwirPhotoClean.exe --recycle-restore-verify "C:\path\to\recycle-verification.json"
```

5. The command must report `RESTORE_VERIFIED`, `ORIGINAL_PRESERVED`, `FILESYSTEM_IDENTITY_CONTINUITY=yes` when Windows exposes a stable file identity, and an evidence report path.

6. Review the exported report read-only:

```powershell
.\SwirPhotoClean.exe --recycle-restore-review "C:\path\to\recycle-evidence-report.json"
```

7. Only after physically confirming the Restore action, create the packaged attestation:

```powershell
.\SwirPhotoClean.exe --recycle-restore-attest "C:\path\to\recycle-evidence-report.json" --confirm-manual-restore
```

The command must produce a validated `RELEASE_EVIDENCE.json` and still print `ACCEPTANCE_GATE_CLOSED=no`.

## Repository closeout

Copy the validated `RELEASE_EVIDENCE.json` to the repository root. Run:

```powershell
python tools/release_evidence.py verify --file RELEASE_EVIDENCE.json
python tools/readme_progress.py --check
python tools/release_gate.py --check
```

Only after the physical evidence has been reviewed may the final unchecked Recycle/Restore item in `STATUS.md` change to `[x]`. Regenerate the progress SVGs, require exact-head green Windows CI, then use the existing explicit release trigger. The published ZIP, checksum, provenance and embedded runtime evidence must pass the workflow's post-publication verification.

## Failure rule

Any missing original, missing restored copy, hash mismatch, identity mismatch, stale safety contract, invalid report, unsupported drive, or unconfirmed Recycle Bin operation leaves the 1.0 gate open. Never replace the test with a synthetic copy/delete operation and never use permanent deletion as a fallback.
