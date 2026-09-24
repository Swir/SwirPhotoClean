# Release provenance I/O safety

`tools/release_provenance.py` is part of the qualified release path, so its archive, runtime-evidence, provenance-manifest inputs and generated provenance output are treated as security-sensitive filesystem objects rather than ordinary paths.

## Stable-handle inputs

Before hashing or reading an input, the provenance tool keeps the lexical absolute path, rejects symlink/junction/reparse ancestry, requires a regular single-link file, snapshots its identity and then opens it with a bound file handle. The path identity and opened-handle identity must match before bytes are trusted. The handle is checked again after the read, then the lexical ancestry and final pathname are revalidated after close.

Archive hashing is streamed and bounded by the file size captured before opening, so a file that grows, shrinks, is replaced, becomes hardlinked or changes metadata during verification fails closed instead of producing provenance for ambiguous bytes. `RELEASE_EVIDENCE.json` uses the same stable-handle path plus the existing 64 KiB release-evidence ceiling.

## Provenance manifest reads

Provenance manifests are read through the same immutable snapshot path with a 64 KiB maximum before UTF-8/JSON decoding. This prevents oversized, redirected, hardlinked or path-swapped manifests from entering release verification.

The repository-root runtime evidence auto-detection uses `lstat`: a dangling symlink or other unsafe existing entry is not treated as if evidence were simply absent.

## Provenance manifest writes

Manifest publication now uses a guarded same-directory staging file instead of writing directly through the destination pathname. The lexical output ancestry is checked before and after directory creation, and an existing destination must be an ordinary single-link regular file rather than a symlink, junction, reparse point or hardlink.

The serialized manifest is bounded to 64 KiB, written through the exclusive staging descriptor, flushed with `fsync`, then read back and compared through that same still-open handle. After closing the handle, the staging pathname must still identify the verified file and the destination identity must be unchanged from the pre-staging snapshot. Only then is the staging file moved into place with `os.replace`.

After replacement the final manifest is read once more through the stable-handle input path and must exactly match the bytes that were staged. Destination swaps, redirected ancestry, output aliases, hardlinks, staging-path replacement, growth/shrink and malformed final bytes therefore fail closed; abandoned staging files are cleaned up best-effort.

Atomic filesystem replacement protects the provenance file construction step only. It does not authorize or publish a GitHub Release by itself.

## Release status

This hardening does not complete the 1.0 acceptance gate by itself. Qualified Beta/1.0 publication still requires the real packaged-Windows Recycle Bin move, manual Restore, preserved original, validated runtime evidence, exact-head release gate, package checksums/provenance and post-publication smoke verification.
