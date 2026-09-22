# Recycle path safety

SWIR PhotoClean treats the Windows Recycle Bin as the only cleanup destination. The production recycle backend therefore validates the target path immediately before handing it to Windows.

## Reparse-aware fail-closed guard

A recycle request is refused when the target itself or any existing component in its path is a symbolic link, junction, mount-style reparse point, or another Windows reparse point. The check intentionally uses the unrevolved absolute path: resolving first could hide a junction boundary and make the final operation act on a location different from the path the review workflow validated.

This is an operation-time defense in depth. The scanner already skips reparse points and cloud-placeholder-style entries, but a path can change between scanning and cleanup or a generated Recycle/Restore evidence workspace can be placed below a redirected directory. The final recycle call therefore checks the ancestry again.

The existing fixed-local-drive gate remains mandatory after this check. Network/removable volumes are still blocked, Windows must explicitly report recycle semantics, the source must disappear after a successful operation, and there is no fallback to permanent deletion.

## Release evidence impact

The physical 1.0 Recycle/Restore test uses the same production `photoclean.recycle.recycle_file` backend, so the generated `RECYCLE-ME.png` cannot qualify evidence through an ambiguous reparse/junction path. If the check refuses the path, choose an ordinary folder on a local fixed drive and create a fresh evidence session there.

Unit tests cover regular paths, target-level reparse rejection, ancestor-level rejection, and full ancestry traversal. The real Windows move/Restore acceptance item in `STATUS.md` remains unchanged and must still be completed physically before a qualified 1.0 release.
