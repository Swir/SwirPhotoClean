# Standalone release-evidence output safety

`tools/release_evidence.py` turns a freshly validated, packaged-Windows Recycle Bin restore report into the sanitized `RELEASE_EVIDENCE.json` consumed by the release gate. The writer is deliberately fail-closed because this file is part of the 1.0 qualification chain.

## Stable-handle write and verification

The staged JSON is written to an exclusive sibling temporary file and validated through the same open file descriptor that received the bytes. Before the atomic replace, the temporary pathname must still identify that validated file. The destination is also checked for symlinks/junctions/reparse points, hardlinks, non-regular objects, unexpected identity changes and oversized content.

After `os.replace`, the final `RELEASE_EVIDENCE.json` is reopened once with a bounded read. The pathname identity is captured before the open, matched to the opened handle and checked again after the read together with the output-directory ancestry. A last-moment path swap therefore fails instead of allowing different bytes to become release evidence.

The sanitized evidence limit is 64 KiB. Reads and writes are bounded and the exact JSON payload is revalidated before the writer reports success.

## What this does not prove

These I/O guards do **not** satisfy the remaining 1.0 acceptance item by themselves. A qualified release still requires real evidence from packaged `SwirPhotoClean.exe` on Windows showing that the generated copy was moved to the Windows Recycle Bin, manually restored, matched by SHA-256, and remained distinct from the preserved original. `STATUS.md` remains the authority for that gate.
