# Release provenance input safety

`tools/release_provenance.py` is part of the qualified release path, so its archive, runtime-evidence and provenance-manifest inputs are treated as security-sensitive filesystem objects rather than ordinary paths.

## Stable-handle contract

Before hashing or reading an input, the provenance tool keeps the lexical absolute path, rejects symlink/junction/reparse ancestry, requires a regular single-link file, snapshots its identity and then opens it with a bound file handle. The path identity and opened-handle identity must match before bytes are trusted. The handle is checked again after the read, then the lexical ancestry and final pathname are revalidated after close.

Archive hashing is streamed and bounded by the file size captured before opening, so a file that grows, shrinks, is replaced, becomes hardlinked or changes metadata during verification fails closed instead of producing provenance for ambiguous bytes. `RELEASE_EVIDENCE.json` uses the same stable-handle path plus the existing 64 KiB release-evidence ceiling.

## Provenance manifest reads

Provenance manifests are read through the same immutable snapshot path with a 64 KiB maximum before UTF-8/JSON decoding. This prevents oversized, redirected, hardlinked or path-swapped manifests from entering release verification.

The repository-root runtime evidence auto-detection uses `lstat`: a dangling symlink or other unsafe existing entry is not treated as if evidence were simply absent.

## Release status

This hardening does not complete the 1.0 acceptance gate by itself. Qualified Beta/1.0 publication still requires the real packaged-Windows Recycle Bin move, manual Restore, preserved original, validated runtime evidence, exact-head release gate, package checksums/provenance and post-publication smoke verification.
