# Recycle path safety

SWIR PhotoClean treats the Windows Recycle Bin as the only cleanup destination. The production recycle backend therefore validates the target path immediately before handing it to Windows.

## Reparse-aware fail-closed guard

A recycle request is refused when the target itself or any existing component in its path is a symbolic link, junction, mount-style reparse point, or another Windows reparse point. The check intentionally uses the unresolved absolute path: resolving first could hide a junction boundary and make the final operation act on a location different from the path the review workflow validated.

The ancestry check is also **fail closed on metadata errors**. If the target disappears, a component cannot be inspected, or Windows denies metadata access, SWIR PhotoClean refuses the operation instead of assuming the path is a normal file. That keeps stale paths and permission races from reaching the Windows Shell delete request.

## Regular-file boundary

Immediately before the Windows Shell request, the final recycle backend also requires the target itself to still be a **regular file**. A path that was a scanned photo but has since been replaced by a directory or another non-file filesystem object is rejected. This is deliberately enforced at the final production recycle boundary rather than relying only on the earlier scan/review state.

## Last-moment identity stability

The recycle backend now takes a metadata identity snapshot of the verified file and rechecks it after creating the Windows Shell item and again after queueing the delete, immediately before `PerformOperations()`. The comparison includes volume/device identity, file identity, size, modification time and change time. If the file is replaced or modified during that final handoff window, the operation stops instead of letting a stale review decision reach the Shell request.

This does not claim to make arbitrary filesystem races impossible; it deliberately narrows the remaining time-of-check/time-of-use window while preserving the existing fail-closed model. The earlier review workflow still performs its own full-file revalidation, and the final recycle backend independently rechecks path ancestry, file type and last-moment identity.

The existing fixed-local-drive gate remains mandatory after these checks. Network/removable volumes are still blocked, Windows must explicitly report recycle semantics, the source must disappear after a successful operation, and there is no fallback to permanent deletion.

## Release evidence impact

The physical 1.0 Recycle/Restore test uses the same production `photoclean.recycle.recycle_file` backend, so the generated `RECYCLE-ME.png` cannot qualify evidence through an ambiguous reparse/junction path, after being replaced by a non-file object, or after a last-moment file mutation detected before Shell execution. If the check refuses the path, choose an ordinary folder on a local fixed drive and create a fresh evidence session there.

Unit tests cover regular files, directory replacement rejection, missing targets, unreadable path metadata, target-level reparse rejection, ancestor-level rejection, full ancestry traversal, unchanged identity acceptance, content mutation rejection and path replacement rejection. The real Windows move/Restore acceptance item in `STATUS.md` remains unchanged and must still be completed physically before a qualified 1.0 release.
