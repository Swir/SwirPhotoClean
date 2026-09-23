# Session Save / Resume safety

SwirPhotoClean session files store review metadata only. Loading or resuming a session never deletes, restores, or moves photos, and it never restores a previous cleanup selection.

Before a saved photo is admitted back into review, the resume preflight now verifies the complete path ancestry for symlink/junction/reparse components, compares the saved filesystem signature with the live path, opens the file read-only, binds the check to that exact handle with `fstat`, and checks the path again while the handle is still open. Missing, replaced, unavailable, linked/reparse, or duplicate physical identities are dropped from the resumed snapshot; affected groups are rebuilt or removed when fewer than two valid members remain.

This preflight deliberately does **not** replace cleanup safety. It is a fast stale-session filter for review. Every later Recycle Bin operation still performs the normal full content/hash revalidation immediately before dispatch, preserves at least one copy, and has no permanent-delete fallback.

The 1.0 acceptance status does not change because of this hardening. Physical Windows Recycle Bin move + Restore evidence remains a separate manual/runtime gate tracked in `STATUS.md`.
