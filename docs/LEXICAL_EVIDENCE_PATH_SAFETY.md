# Lexical release-evidence path safety

SwirPhotoClean treats the Windows Recycle Bin / Restore evidence chain as release-critical input. User-supplied manifest, report and attestation paths therefore remain **lexical absolute paths** until the hardened I/O layer has inspected them.

## Why this matters

Calling `Path.resolve()` before safety validation follows symlinks, junctions and other reparse ancestry. That can erase the path component the hardened reader needs to reject. The packaged evidence commands now normalize paths with `abspath` without resolving filesystem links, so `photoclean.evidence_io` and the immutable snapshot reader can inspect the original ancestry and fail closed.

The immutable report snapshot also checks its parent ancestry before and after the bounded single-handle read. A redirected report directory is rejected rather than silently followed. Explicit manifest paths passed into snapshot validation are likewise preserved without pre-resolution.

The repository-side `RELEASE_EVIDENCE.json` readers now apply the same rule. Both the standalone evidence verifier and the qualified publication gate inspect every lexical parent before opening the file and repeat that ancestry check after the bounded identity-bound read. A symlink, junction or other reparse parent therefore cannot redirect release authorization to evidence outside the path that was reviewed.

## Covered command surfaces

The rule applies to the packaged workflow used for:

- prepare / move / verify / status / review of Recycle Bin evidence;
- immutable report snapshot validation;
- `--recycle-restore-attest`, including an explicit `--output` path;
- standalone repository `RELEASE_EVIDENCE.json` verification;
- the qualified release/build gate that consumes runtime evidence.

This is defense-in-depth only. It does **not** mark the Windows Recycle Bin acceptance item complete and does not change `STATUS.md` progress. Stable 1.0 still requires real packaged-Windows evidence of move to Recycle Bin, manual Restore, preserved original, validated report/attestation and the release gates described in `docs/RECYCLE_RESTORE_EVIDENCE.md`.