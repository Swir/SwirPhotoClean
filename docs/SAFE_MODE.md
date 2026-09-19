# Safe Mode

Safe Mode is an optional review-only guard for SWIR PhotoClean. It lets you continue scanning, comparing, using Smart Keep, reviewing quality, opening Difference View and marking files, while blocking every normal cleanup execution path.

## Enable it

Open **View → Safe Mode — block Recycle Bin**.

When enabled:

- photo scanning and review continue normally;
- you can still mark/unmark candidates to plan a cleanup;
- the **Move selected to Recycle Bin** button remains disabled even when files are marked;
- direct/programmatic calls to the cleanup confirmation path are blocked as a second line of defense;
- no existing marks are cleared or modified merely by switching Safe Mode on or off.

Safe Mode is runtime-only and is intentionally not saved as a persistent preference. Each new application launch starts in the normal guarded mode, where the existing Recycle Bin validation, confirmation and no-permanent-delete rules still apply.

## Why it exists

Safe Mode is useful while auditing a large photo library, demonstrating the application, or preparing a cleanup list when you want a hard guarantee that the normal application workflow cannot start a Recycle Bin move during that session.

It is defense in depth, not a replacement for backups or the existing safety checks. Turning Safe Mode off does not weaken the normal group-survivor rule, file revalidation, explicit confirmation or Recycle-Bin-only policy.
