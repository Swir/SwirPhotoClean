# Recycle evidence review snapshot

The user-facing `SwirPhotoClean.exe --recycle-restore-status` and `--recycle-restore-review` commands are release-critical because they decide whether a physical Windows Recycle Bin test is ready for human acceptance review. They therefore use the same immutable snapshot intake already used by packaged release attestation.

## Stable report intake

Before either command can print a review-ready marker for a completed restore session, `recycle-evidence-report.json` is read through one bounded file handle. The intake rejects:

- symlinks, junctions and other reparse points,
- hardlinked report aliases,
- non-regular files,
- reports above the evidence size limit,
- a path that resolves to a different file between inspection and open,
- metadata or identity changes while bytes are being read,
- a path that changes after the snapshot read.

Only the bytes captured from that verified handle are parsed. Those exact bytes are then validated against the live tamper-evident manifest and generated KEEP/RECYCLE fixture. A stale or substituted report therefore cannot produce `READY_FOR_REVIEW` / `READY_FOR_MANUAL_ACCEPTANCE_REVIEW` through the supported application entry point.

The snapshot step is read-only. It never moves a photo, changes the manifest stage, rewrites the evidence report, marks `STATUS.md`, or closes the 1.0 gate.

## End-to-end handoff

After the physical Recycle Bin Restore is complete:

```powershell
.\SwirPhotoClean.exe --recycle-restore-verify "C:\...\recycle-verification.json"
.\SwirPhotoClean.exe --recycle-restore-review "C:\...\recycle-evidence-report.json"
```

A successful review now prints the exact packaged next step:

```powershell
.\SwirPhotoClean.exe --recycle-restore-attest "C:\...\recycle-evidence-report.json" --confirm-manual-restore
```

`--confirm-manual-restore` remains explicit. Software can validate disappearance, restored bytes, preserved original, event ordering, safety-contract identity and available filesystem-object continuity, but it must not fabricate the human fact that **Restore** was actually chosen in Windows Recycle Bin.

The packaged attestation writes sanitized `RELEASE_EVIDENCE.json` only after revalidating the report through the same stable snapshot boundary. The resulting JSON still says `acceptance_gate_closed: false`; it is evidence for the qualified release gate, not permission to change the checklist automatically.

## Regression coverage

`tests/test_recycle_review_cli.py` verifies that:

- successful review is read-only and exposes the packaged attestation handoff,
- a hardlinked report is rejected before any ready marker is printed,
- status also refuses a hardlinked completed report,
- non-review commands continue to delegate to the existing authoritative workflow,
- invalid review command arity fails closed.

These tests strengthen the evidence-review path but cannot replace the required physical Windows move → Recycle Bin → Restore test.
