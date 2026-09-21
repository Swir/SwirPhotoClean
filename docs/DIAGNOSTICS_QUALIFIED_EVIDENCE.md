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

After successful verification, **Copy report path** copies the final report path. Before the report exists, the same button copies the manifest path so a prepared/recycled session can still be inspected or resumed.

## What this does not do

The GUI does **not** restore files automatically, edit `STATUS.md`, mark the 1.0 gate complete, create release attestation by itself, or publish a release. Manual Windows Restore remains mandatory. The final report still contains `acceptance_gate_closed: false` and must be reviewed as genuine physical Windows evidence before the repository checklist can change.

For the full CLI/status/review/attestation workflow and release rules, see [`RECYCLE_RESTORE_EVIDENCE.md`](RECYCLE_RESTORE_EVIDENCE.md) and [`PACKAGED_RELEASE_EVIDENCE.md`](PACKAGED_RELEASE_EVIDENCE.md).
