# Packaged Windows release-evidence handoff

This document covers the final handoff after the **real** Windows Recycle Bin
move/Restore test. It does not replace the physical test and it never closes the
1.0 acceptance checkbox automatically.

The authoritative physical workflow is documented in
[`RECYCLE_RESTORE_EVIDENCE.md`](RECYCLE_RESTORE_EVIDENCE.md).

## Why this exists

A qualified Beta/RC/1.x release requires a small sanitized
`RELEASE_EVIDENCE.json` that is bound to the exact release safety contract. The
physical test itself already runs from packaged `SwirPhotoClean.exe`; the
attestation can now be created from that same packaged executable, so the person
performing the Windows test does not need a Python checkout just to hand the
verified evidence back to the repository.

## 1. Complete and review the physical test

After Windows Recycle Bin **Restore** has really been performed:

```powershell
.\SwirPhotoClean.exe --recycle-restore-verify "C:\...\recycle-verification.json"
.\SwirPhotoClean.exe --recycle-restore-review "C:\...\recycle-evidence-report.json"
```

Continue only when the review command prints:

```text
REPORT_VALID
READY_FOR_MANUAL_ACCEPTANCE_REVIEW
```

## 2. Create the sanitized attestation with the packaged EXE

Run:

```powershell
.\SwirPhotoClean.exe --recycle-restore-attest `
  "C:\...\recycle-evidence-report.json" `
  --confirm-manual-restore
```

`--confirm-manual-restore` is mandatory. It is an explicit human attestation
that **Restore** was actually selected in Windows Recycle Bin; code cannot infer
that user action from file hashes alone.

By default the command writes:

```text
C:\...\RELEASE_EVIDENCE.json
```

next to the validated evidence report.

To choose another destination:

```powershell
.\SwirPhotoClean.exe --recycle-restore-attest `
  "C:\...\recycle-evidence-report.json" `
  --confirm-manual-restore `
  --output "C:\Temp\RELEASE_EVIDENCE.json"
```

A successful command prints `RELEASE_EVIDENCE_VALID=yes`. The file is written
atomically and then re-read through the same strict validator before success is
reported.

## 3. What the packaged attestation validates

The command fails closed unless all of these are true:

- the report matches the live tamper-evident manifest and a fresh fixture
  inspection;
- the exact report bytes used for the attestation are first captured as one
  immutable snapshot and that same snapshot is what the authoritative validator
  checks; the attestation SHA-256 is calculated from those exact bytes rather
  than from a second read of a mutable report path;
- the manifest reached `restored-verified`;
- the generated original stayed intact;
- the restored copy matches the expected SHA-256 and is physically distinct;
- the evidence says it came from frozen `SwirPhotoClean.exe` on Windows;
- the report is bound to the exact runtime safety-contract SHA-256;
- the manual Restore confirmation flag is explicitly present.

This snapshot handoff removes the validation/attestation time-of-check gap: if
the source report is changed after the snapshot is captured, those later bytes
cannot silently replace the bytes that were validated and hashed into
`RELEASE_EVIDENCE.json`.

The sanitized JSON contains no local photo-library data and does not copy the
generated PNG files or local evidence paths.

## 4. Repository handoff

Copy the validated `RELEASE_EVIDENCE.json` to the repository root without
editing it. From a source checkout it can still be verified with:

```powershell
py -3.12 tools\release_evidence.py verify
```

The qualified release gate will revalidate it again. The Windows release
workflow also compares the evidence contract with the packaged application,
embeds the file in the ZIP, publishes it as a sidecar and verifies both copies.

Release provenance schema 2 additionally binds the ZIP to the exact
`safety_contract_sha256` and, when qualified runtime evidence is present, to the
name, size and SHA-256 of `RELEASE_EVIDENCE.json`. A later code-contract change
or evidence replacement therefore makes provenance verification fail closed
instead of leaving a checksum/provenance record that only proves the ZIP bytes.
Historical schema-1 provenance remains readable for older releases, but it
cannot satisfy the new safety-contract/evidence binding.

## Safety rule

Creating `RELEASE_EVIDENCE.json` is **not** permission to mark the remaining
`STATUS.md` item complete. The checkbox changes only after the real Windows
Recycle Bin move and manual Restore have been reviewed as genuine runtime
evidence. The attestation deliberately retains:

```json
"acceptance_gate_closed": false
```

until repository review updates the authoritative acceptance state.
