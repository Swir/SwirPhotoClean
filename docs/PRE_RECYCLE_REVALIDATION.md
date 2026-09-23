# Pre-Recycle revalidation safety

Before any reviewed item can reach the Windows Recycle Bin path, SWIR PhotoClean revalidates both the selected target and the copy that must remain in its result group.

The revalidation is bound to the exact filesystem identity captured during the scan: file size, modification time, device and file ID/inode. The full SHA-256 is read through one already-open handle whose identity is checked before and after the read. The lexical path ancestry is checked for symlinks, junctions and other reparse points before the handle is opened and again after the read, followed by a final path-identity check.

This closes the gap where a pathname could otherwise be replaced after metadata validation but before a fresh hash open. A changed target or keeper therefore fails closed before disposal. The production Windows Shell layer still performs its own independent scan-bound identity and digest checks immediately before the Recycle Bin operation; this pre-Recycle layer does not replace those final guards.

Regression coverage in `tests/test_core_verify_bound_read.py` includes a substituted same-size/same-time file object, handle metadata mutation during hashing, post-hash reparse ancestry change, stable-file success and a keeper substitution that must prevent the recycle callback from running.

This hardening does **not** satisfy the remaining 1.0 acceptance item by itself. The gate still requires real packaged Windows evidence of moving the generated copy to the Recycle Bin, restoring that same item, verifying its SHA-256 and confirming that the generated original remained intact.
