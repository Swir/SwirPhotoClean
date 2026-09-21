# Diagnostics Center: qualified Windows Recycle Bin evidence

The **Diagnostics Center → Windows Recycle Bin** tab is the guided GUI path for the same release evidence contract used by the packaged command-line helpers.

## Guided flow

1. Open **View → Diagnostics Center** (`Ctrl+Shift+D`).
2. Select **Windows Recycle Bin**.
3. Choose **Prepare test files**. SwirPhotoClean creates only generated `KEEP-ME.png` and `RECYCLE-ME.png` files plus the verification manifest.
4. Choose **Move generated copy to Recycle Bin**. The app revalidates the bound manifest and uses the production recycle-only backend. There is no permanent-delete fallback.
5. In Windows Recycle Bin, manually choose **Restore** for `RECYCLE-ME.png`.
6. Choose **Verify restored copy** in Diagnostics Center.

A successful final step now uses `photoclean.recycle_evidence`, not the lower-level diagnostics fixture alone. Therefore the GUI session is:

- bound to the exact running release safety-contract SHA-256 at preparation time;
- rejected if the safety-critical runtime/build contract changes before move or verification;
- verified only when the generated original is preserved and the restored copy matches the expected SHA-256 and size;
- exported to `recycle-evidence-report.json`;
- freshly revalidated against the live manifest and both generated files before the GUI reports it ready for acceptance review.

## Resume after restart

The physical Recycle Bin test can now be resumed in the GUI instead of forcing the operator back to CLI helpers after an application restart.

1. Open **Diagnostics Center → Windows Recycle Bin**.
2. Choose **Resume test from manifest…** and select the generated `recycle-verification.json`.
3. SwirPhotoClean reloads the tamper-evident manifest and rejects it when its bound release safety-contract SHA-256 does not match the running build.
4. A `prepared` session re-enables only the guarded move step; a `recycled` session re-enables restore verification; a `restored-verified` session revalidates an existing report or enables safe report regeneration when the report is missing.

Resuming never performs a move, Restore or verification automatically. A `recycled` session remains usable whether `RECYCLE-ME.png` is still in the Windows Recycle Bin or has already been manually restored; the explicit **Verify restored copy** action performs the authoritative file checks.

After successful verification, **Copy report path** copies the final report path. Before the report exists, the same button copies the manifest path so the session can be inspected or resumed again.

## What this does not do

The GUI does **not** restore files automatically, edit `STATUS.md`, mark the 1.0 gate complete, create release attestation by itself, or publish a release. Manual Windows Restore remains mandatory. The final report still contains `acceptance_gate_closed: false` and must be reviewed as genuine physical Windows evidence before the repository checklist can change.

For the full CLI/status/review/attestation workflow and release rules, see [`RECYCLE_RESTORE_EVIDENCE.md`](RECYCLE_RESTORE_EVIDENCE.md) and [`PACKAGED_RELEASE_EVIDENCE.md`](PACKAGED_RELEASE_EVIDENCE.md).
