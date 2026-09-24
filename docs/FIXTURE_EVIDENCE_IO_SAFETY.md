# Generated fixture I/O safety

The `KEEP-ME.png` / `RECYCLE-ME.png` pair used for Windows Recycle Bin acceptance evidence is release-critical input, not ordinary user-photo data.

Before a move, restore verification or evidence inspection, SwirPhotoClean now validates each generated fixture from one bounded file descriptor. The lexical parent chain and final entry are checked before open; symlinks, junctions/reparse points and hardlinks fail closed; the opened handle must match the inspected path; metadata must remain stable while SHA-256 is calculated; and the path plus ancestry are checked again after the read.

This closes the path-stat / hash-open TOCTOU gap in the evidence fixture workflow. The hardened reader is installed at application startup before evidence commands are dispatched and is part of the release safety contract, so changing it invalidates older physical Windows evidence.

This hardening does **not** close the 1.0 acceptance gate. A qualified packaged Windows build must still physically move the generated copy to the Recycle Bin, preserve the original, be manually restored, and pass the report/attestation/release gates described in `RECYCLE_RESTORE_EVIDENCE.md`.
