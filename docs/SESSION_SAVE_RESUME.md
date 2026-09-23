# Session Save / Resume

SWIR PhotoClean can save a completed scan as a versioned `.swirpc` session and reopen it later for review. Session persistence is deliberately non-destructive and does not weaken the Recycle Bin safety path.

## What a session contains

A session stores scan metadata needed to rebuild the review state: selected roots, similarity settings, file paths and scan-time file signatures, hashes/image signatures, groups and scan warnings.

It does **not** store image bytes, Recycle Bin state, cleanup history as an instruction, or files marked for removal. Opening a session always starts with an empty cleanup selection.

Session writes are atomic: the payload is written to a temporary file, flushed, and then replaced into the destination. The loader applies strict format, version, size, count and reference validation before returning a snapshot.

Session saving also fails closed if the selected destination is, or aliases, any scanned photo. An existing destination must be a regular non-reparse file with a single filesystem link, and its identity is checked again after staging before atomic replacement. This prevents a session save from replacing source image bytes or silently following a destination that was swapped while the payload was being prepared.

The loader enforces the session byte limit while reading from one open file handle instead of trusting a separate size check followed by an unbounded text read. A session that grows or is replaced between metadata inspection and reading therefore cannot bypass `MAX_SESSION_BYTES` and force an unexpectedly large allocation.

## Resume freshness preflight

Before the final desktop UI accepts a saved session for review, it performs a fast read-only freshness audit against the current filesystem:

- missing files are rejected from the resumed review;
- files whose size, modification time, device or inode changed since the saved scan are rejected;
- unavailable files are rejected and reported;
- symlinks, junctions, reparse points and similar unsafe linked entries are rejected;
- a second path that resolves to the same non-zero filesystem device/inode identity as an already accepted member is rejected, preserving the scanner rule that one physical file cannot masquerade as two independent copies;
- groups are rebuilt from surviving members and a group is dropped if fewer than two current members remain;
- stale counts are shown in the resume status and bounded detail is appended to Diagnostics / scan warnings;
- if a formerly non-empty session has no current files left, the final UI refuses to present it as a valid review and asks for a fresh scan.

The audit does not alter any source image.

## Safety boundary

The resume freshness audit is intentionally **not** a replacement for cleanup revalidation. It uses filesystem identity/metadata so a large saved library can be reopened without hashing every file again just to display review results.

Before any file can be moved to the Windows Recycle Bin, the normal cleanup path still performs its stricter content/signature revalidation, requires explicit user marking and confirmation, preserves at least one copy in the affected group, and has no permanent-delete fallback.

Therefore a successfully resumed session means “safe enough to review current members”, not “pre-authorized to recycle them”.

## Large-library behavior

The session schema has explicit bounds for file size, photo count, group count and warning count. The byte limit is enforced during the read itself, so stale file metadata cannot turn loading into an unbounded read. Freshness diagnostics keep a compact summary plus a limited number of per-file details instead of generating an unbounded warning list. This keeps stale-session handling predictable for large libraries while preserving a useful audit trail.

## Language and UX

The final resume status and all-stale error are available in Polish and English. Reopening a session restores scan/review settings, clears cleanup marks and closes any obsolete fullscreen comparison window before presenting the sanitized result.
