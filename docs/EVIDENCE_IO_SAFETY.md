# Release evidence JSON I/O safety

The Windows Recycle Bin / Restore acceptance workflow writes two kinds of local JSON state: the tamper-evident `recycle-verification.json` manifest and the exported `recycle-evidence-report.json`. The application entry point installs the hardened persistence layer before GUI or evidence CLI modules are loaded, so both paths keep the existing evidence schema while using the stricter writer.

## Write contract

Release-evidence JSON is staged in the destination directory with an exclusive randomized temporary name. The staged bytes are flushed and `fsync`-ed, read back, parsed, and compared with the validated payload before an atomic `os.replace` commits them. Temporary files are removed on failure.

An existing destination is accepted only when it is a single-link regular file. Symlinks, junctions/reparse points, hardlinked outputs, directories and other special filesystem entries fail closed. The destination identity is snapshotted before staging and checked again immediately before replacement, so a path created, removed or swapped while validated bytes are being prepared is rejected instead of silently overwritten.

The exported report also refuses lexical aliases or existing filesystem aliases of the generated `KEEP-ME.png`, `RECYCLE-ME.png` and `recycle-verification.json` fixture files. This prevents the evidence export path from becoming a way to mutate the very files it is meant to attest.

## Safety scope

This hardening does not alter the physical acceptance rule and cannot mark `STATUS.md` complete. A qualified release still requires a real packaged Windows run in which the generated copy is moved through the Recycle Bin-only backend, manually restored through Windows, verified against SHA-256 while the generated original remains intact, reviewed, and converted into the sanitized release attestation.

The persistence layer changes only how local evidence JSON is committed. It does not add any permanent-delete fallback, does not restore files automatically, and does not weaken the existing safety-contract binding.

## Regression coverage

`tests/test_evidence_io_safety.py` covers normal replacement of an existing report, hardlink rejection without modifying the generated original, symlink rejection where the platform permits symlink creation, fail-closed behavior when destination identity changes during staging, deterministic installer rebinding, and application-startup ordering.
