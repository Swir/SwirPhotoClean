# Cleanup History and Before/After summary

SWIR PhotoClean keeps a **local audit record** after a confirmed cleanup attempt. The feature is designed to make Recycle Bin operations easier to review without weakening the existing recycle-only safety path.

## What is recorded

For each attempted cleanup session the app records:

- start and finish timestamps;
- scan photo/group counts before the operation;
- requested and completed file counts;
- each selected path, size and SHA-256 captured from the completed scan;
- whether each planned item was actually reported as moved by the existing recycle workflow;
- errors returned by the operation;
- a conservative before/after **scan snapshot** count.

The history file contains metadata only. It does not contain thumbnails or image bytes.

By default it is stored next to the normal per-user settings as `cleanup-history.json` and keeps the most recent 100 sessions.

## Space accounting

The app deliberately distinguishes three different values:

1. **Requested bytes** — files the user asked to recycle.
2. **Moved-to-Recycle-Bin bytes** — files for which the existing recycle workflow completed.
3. **Guaranteed reclaimable after emptying Recycle Bin** — only completed, byte-identical SHA-256 duplicates for which an unselected exact copy remained in the scan.

Moving a file to the Windows Recycle Bin does **not** immediately free that disk space. SWIR PhotoClean therefore never labels moved-to-bin bytes as already recovered space.

Similar-photo candidates never increase the guaranteed reclaimable figure.

## Before / After Cleanup

After at least one file is successfully moved to the Recycle Bin, the desktop app shows a small session summary:

- photo count before the operation;
- number and bytes moved to the Recycle Bin;
- the scan-snapshot count after subtracting completed moves;
- conservative exact-duplicate bytes that could be reclaimed **after the Recycle Bin is emptied**.

A fresh scan is still mandatory after every disposal attempt. The after value is explicitly a snapshot derived from the verified operation result, not a claim that the filesystem has already been rescanned.

## Cleanup History window

`View -> Cleanup history...` (`Ctrl+Alt+H`) shows recent sessions and their per-file outcomes. It can:

- show moved/not-moved state;
- show the recorded SHA-256 and size;
- copy paths that were moved;
- open the normal Windows Recycle Bin.

It cannot permanently delete files and does not implement a private restore mechanism.

## Undo / restore safety

SWIR PhotoClean intentionally does **not** claim a programmatic Undo before 1.0. Restoration remains a Windows Recycle Bin action, because recreating/restoring files independently would risk collisions, wrong destinations, or bypassing Windows Recycle Bin semantics.

The history window provides exact paths and hashes so a restore can be audited. The separate Diagnostics Center generated-file verification remains the authoritative helper for the final 1.0 Recycle Bin move-and-manual-restore evidence.

## Failure behavior

Cleanup history is secondary to file safety:

- the existing core still revalidates targets and survivors before the Recycle Bin call;
- the existing recycle implementation still refuses a permanent-delete fallback;
- history is written only after the operation returns an outcome;
- a history-write failure is reported to the user but does not rewrite the real recycle outcome;
- failed/not-attempted files are never counted as moved;
- partial operations are represented as partial, not successful whole-session cleanups.

## Packaged self-test

The packaged `SwirPhotoClean.exe --self-test` exercises the final Cleanup History UI using a **dry-run audit record only**. It never invokes the Windows Recycle Bin in self-test mode and reports `recycle_executed: false`.
