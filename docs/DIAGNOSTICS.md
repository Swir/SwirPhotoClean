# Diagnostics Center and Recycle Bin verification

The Diagnostics Center is a non-destructive support view for SWIR PhotoClean. It summarizes the current scan and provides an explicit generated-file workflow for the final Windows Recycle Bin restore acceptance check.

## What the Diagnostics Center shows

- Windows / Python runtime information and whether the app is running from source or a packaged EXE.
- Current photo count, exact-group count, similar-group count and scan-warning count.
- Number of files currently marked for the Recycle Bin.
- Whether the current scan was cancelled.
- Existing scan warnings without modifying the scan result.
- A Recycle Bin preflight that checks Windows, required shell dependencies and the selected local fixed drive.

None of these checks automatically select, move, rename or rewrite user photos.

## Generated Recycle Bin verification

The helper exists to make the remaining 1.0 acceptance check easy to perform without touching personal photos.

1. Open **View → Diagnostics Center…**.
2. Choose **Prepare test files…** and select a normal folder on a local fixed drive.
3. SWIR PhotoClean creates a new `SwirPhotoClean-Recycle-Check-*` folder containing two byte-identical generated PNG files:
   - `KEEP-ME.png`
   - `RECYCLE-ME.png`
4. Choose **Move generated copy to Recycle Bin** and confirm the explicit prompt.
5. The program routes only `RECYCLE-ME.png` through the same guarded recycle-only implementation used by cleanup. `KEEP-ME.png` must remain unchanged.
6. Restore `RECYCLE-ME.png` manually from the Windows Recycle Bin to the generated test folder.
7. Choose **Verify restored copy**.
8. Verification succeeds only if both generated files exist and both still match the original SHA-256 digest.

The local `recycle-verification.json` manifest records the generated digest and the stages that were actually observed. It is evidence for review, not an automatic repository-status change.

## Safety properties

- Personal photos are never used by the helper.
- Preparing the test pair performs no destructive operation.
- Moving the test copy requires an explicit user confirmation.
- The normal `recycle_file()` path is used; there is no permanent-delete fallback.
- A failed recycle attempt must not be treated as a successful acceptance result.
- Restore verification cannot pass before a successful recycle stage has been recorded.
- The original generated file must remain present and SHA-256-identical throughout the workflow.
- The repository 1.0 checklist remains unchanged until the evidence is actually reviewed.

## Troubleshooting

If preflight is blocked, use a folder on a local internal drive and make sure the packaged application has all of its accompanying files. Network and removable drives are intentionally rejected for Recycle Bin cleanup.

If the recycle move fails, keep the generated folder for diagnostics. The application must never fall back to permanent deletion.
