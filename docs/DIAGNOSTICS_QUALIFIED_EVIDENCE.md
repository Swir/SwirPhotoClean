# Diagnostics Center: qualified Windows Recycle Bin evidence

The **Diagnostics Center → Windows Recycle Bin** tab is the guided GUI path for the same release evidence contract used by the packaged command-line helpers.

## Guided flow

1. Open **View → Diagnostics Center** (`Ctrl+Shift+D`).
2. Select **Windows Recycle Bin**.
3. Choose **Prepare test files**. SwirPhotoClean creates only generated `KEEP-ME.png` and `RECYCLE-ME.png` files plus the verification manifest.
4. Choose **Move generated copy to Recycle Bin**. The app revalidates the bound manifest and uses the production recycle-only backend. There is no permanent-delete fallback.
5. In Windows Recycle Bin, manually choose **Restore** for `RECYCLE-ME.png`.
6. Choose **Verify restored copy** in Diagnostics Center.
7. After the report is freshly validated, choose **Create RELEASE_EVIDENCE…**. Confirm only if you personally performed the manual Windows Restore. The packaged app then revalidates the report again and writes `RELEASE_EVIDENCE.json` in the generated test folder.

A successful verification path uses `photoclean.recycle_evidence`, not the lower-level diagnostics fixture alone. Therefore the GUI session is:

- bound to the exact running release safety-contract SHA-256 at preparation time;
- rejected if the safety-critical runtime/build contract changes before move or verification;
- verified only when the generated original is preserved and the restored copy matches the expected SHA-256 and size;
- exported to `recycle-evidence-report.json`;
- freshly revalidated against the live manifest and both generated files before the GUI reports it ready for acceptance review.

The optional final GUI handoff uses `photoclean.release_attestation.write_packaged_attestation`. It preserves the same fail-closed rules as the packaged CLI path: qualified attestation requires a real frozen Windows build, a matching current safety contract, exactly one recycled and restored event, a preserved original, matching restored SHA-256, a valid fresh report inspection and explicit confirmation that the Restore was performed manually. The resulting `RELEASE_EVIDENCE.json` is written atomically and read back through the attestation validator before the GUI reports success.

## Resume after restart

The physical Recycle Bin test can be resumed in the GUI instead of forcing the operator back to CLI helpers after an application restart.

1. Open **Diagnostics Center → Windows Recycle Bin**.
2. Choose **Resume test from manifest…** and select the generated `recycle-verification.json`.
3. SwirPhotoClean reloads the tamper-evident manifest and rejects it when its bound release safety-contract SHA-256 does not match the running build.
4. A `prepared` session re-enables only the guarded move step; a `recycled` session re-enables restore verification; a `restored-verified` session revalidates an existing report or enables safe report regeneration when the report is missing.
5. When a restored session has a freshly validated report, SwirPhotoClean also checks for an existing `RELEASE_EVIDENCE.json`. If one exists, it is revalidated against the current safety contract **and** cross-checked against the exact resumed session ID, fixture SHA-256, manifest fingerprint and report SHA-256. A matching attestation is adopted without being rewritten and the create button stays disabled. A stale, tampered or unrelated attestation is reported visibly and is never treated as valid evidence. If no attestation exists, **Create RELEASE_EVIDENCE…** remains available and the operator must explicitly reconfirm the manual Restore before creating one.

Resuming never performs a move, Restore, verification or release attestation automatically. A `recycled` session remains usable whether `RECYCLE-ME.png` is still in the Windows Recycle Bin or has already been manually restored; the explicit **Verify restored copy** action performs the authoritative file checks.

Path-copying follows the most advanced validated stage: before the report exists it copies the manifest, after verification it copies `recycle-evidence-report.json`, and after successful or safely resumed packaged attestation it copies `RELEASE_EVIDENCE.json`.

## What this does not do

The GUI does **not** restore files automatically, edit `STATUS.md`, mark the 1.0 gate complete or publish a release. Manual Windows Restore remains mandatory. Both the evidence report and packaged attestation keep `acceptance_gate_closed: false`; genuine physical Windows evidence still requires manual acceptance review before the repository checklist can change.

For the full CLI/status/review/attestation workflow and release rules, see [`RECYCLE_RESTORE_EVIDENCE.md`](RECYCLE_RESTORE_EVIDENCE.md) and [`PACKAGED_RELEASE_EVIDENCE.md`](PACKAGED_RELEASE_EVIDENCE.md).
