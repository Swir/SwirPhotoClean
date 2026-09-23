# Recycle path safety

SWIR PhotoClean treats the Windows Recycle Bin as the only cleanup destination. The production recycle backend therefore validates the target path immediately before handing it to Windows.

## Reparse-aware fail-closed guard

A recycle request is refused when the target itself or any existing component in its path is a symbolic link, junction, mount-style reparse point, or another Windows reparse point. The check intentionally uses the unresolved absolute path: resolving first could hide a junction boundary and make the final operation act on a location different from the path the review workflow validated.

The ancestry check is also **fail closed on metadata errors**. If the target disappears, a component cannot be inspected, or Windows denies metadata access, SWIR PhotoClean refuses the operation instead of assuming the path is a normal file. That keeps stale paths and permission races from reaching the Windows Shell delete request.

## Regular-file boundary

Immediately before the Windows Shell request, the final recycle backend also requires the target itself to still be a **regular file**. A path that was a scanned photo but has since been replaced by a directory or another non-file filesystem object is rejected. This is deliberately enforced at the final production recycle boundary rather than relying only on the earlier scan/review state.

## Scan-to-Shell continuity

The normal cleanup path now carries the target's **scan-time identity** (`size`, `mtime_ns`, device and inode/file id) and full scan-time **SHA-256** into the final `recycle_file` layer. The final backend requires the live path to match that scanner/review identity before creating its own local recycle snapshot, hashes the object through the already identity-bound read path, and requires the digest to equal the scan-time digest.

This closes the narrow handoff gap where a path could previously be replaced after `core.recycle_selected()` revalidated the reviewed `Photo` but before `recycle_file()` created a fresh baseline. A replacement is no longer allowed to become the new trusted baseline simply because it is stable from that later point onward. The scan signature is checked again around Shell queuing, while the existing full-content guard still runs immediately before `PerformOperations()`.

Injected recycle callbacks used by unit tests keep the historical single-path calling convention. The production Windows backend is the path that receives and enforces scan-bound identity and digest evidence.

## Last-moment identity and content stability

The recycle backend takes a metadata identity snapshot of the verified file and rechecks it after creating the Windows Shell item and again during the final handoff. The comparison includes volume/device identity, file identity, size, modification time and change time. If the file is replaced or modified during that window, the operation stops instead of letting a stale review decision reach the Shell request.

The full **SHA-256 content snapshot** is now collected through one opened file handle that is explicitly rebound to the already-verified path identity before any bytes are trusted. If the path is swapped between the metadata check and `open()`, the opened handle must still match the expected filesystem object or the operation fails closed. The handle is rechecked after the read and the path is revalidated again after closing, so a digest from a different object cannot become recycle-safety evidence merely because the visible path was swapped back afterwards.

Windows can expose minor path-vs-handle metadata representation differences. The binding therefore requires a positive matching Windows file id plus stable size/mtime rather than trusting noisy device/change-time fields; on other platforms the full normalized identity must match. This mirrors the release-evidence gate's fail-closed Windows compatibility strategy without weakening the requirement that the opened object itself is the reviewed target.

After the Shell delete request has been queued but immediately before `PerformOperations()`, the backend hashes the same target again and requires the digest to match the earlier snapshot. This adds an independent content signal for same-size or metadata-preserving mutations in the last handoff window.

This does not claim to make arbitrary filesystem races impossible; it deliberately narrows the remaining time-of-check/time-of-use window while preserving the existing fail-closed model. The earlier review workflow still performs its own full-file SHA-256 revalidation, and the final recycle backend independently rechecks path ancestry, file type, metadata identity and full content before Windows executes the operation.

The existing fixed-local-drive gate remains mandatory after these checks. Network/removable volumes are still blocked, Windows must explicitly report recycle semantics, the source must disappear after a successful operation, and there is no fallback to permanent deletion.

## Release evidence impact

The physical 1.0 Recycle/Restore test uses the same production `photoclean.recycle.recycle_file` backend, so the generated `RECYCLE-ME.png` cannot qualify evidence through an ambiguous reparse/junction path, after being replaced by a non-file object, after a last-moment identity change, after an open-handle substitution, or after a content mutation detected before Shell execution. If the check refuses the path, choose an ordinary folder on a local fixed drive and create a fresh evidence session there.

Unit tests cover regular files, directory replacement rejection, missing targets, unreadable path metadata, target-level reparse rejection, ancestor-level rejection, full ancestry traversal, unchanged identity acceptance, content mutation rejection, path replacement rejection, stable SHA-256 collection, open-handle substitution rejection, independent final digest mismatch rejection, scan-time identity forwarding, unchanged scan-bound snapshots and same-metadata content replacement rejection. The real Windows move/Restore acceptance item in `STATUS.md` remains unchanged and must still be completed physically before a qualified 1.0 release.
