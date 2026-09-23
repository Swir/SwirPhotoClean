# Release evidence JSON I/O safety

The Windows Recycle Bin / Restore acceptance workflow writes two kinds of local JSON state: the tamper-evident `recycle-verification.json` manifest and the exported `recycle-evidence-report.json`. The application entry point installs the hardened evidence I/O layer before GUI or evidence CLI modules are loaded, so the runtime keeps the existing evidence schema while using fail-closed readers and writers.

The final sanitized `RELEASE_EVIDENCE.json` produced by `tools/release_evidence.py write` follows the same fail-closed model. It is release-qualification input, so its reader/writer must not be less strict than the runtime evidence files it summarizes.

## Stable read contract

The authoritative Recycle manifest is no longer trusted through a plain `Path.read_text()` handoff in the packaged runtime. The hardened loader preserves the lexical path, inspects every existing parent with `lstat`, rejects symlinks, junctions and other reparse-point ancestry, then rejects a final manifest entry that is a link, special file, hardlink or oversized file.

The manifest is opened once through a bounded read-only descriptor. Path metadata captured before open must match the opened handle, the handle identity/size/timestamps must remain stable until EOF, and both the lexical ancestry and final path identity are checked again after the read. On Windows the comparison uses the stable cross-API file index/link-count/size/last-write fields rather than relying on CRT fields that can legitimately differ between `lstat` and `fstat`.

The same immutable manifest snapshot now drives stage validation, event inspection and report export. The public report validator reads both `recycle-evidence-report.json` and the live manifest through bounded single-handle snapshots, validates the safety-contract binding and restored-file receipt against that snapshot, then compares the report's embedded manifest/inspection with the exact live data that was checked. A path swap, hardlink, redirected parent or content/metadata change therefore fails closed instead of being silently accepted between validation steps.

Limits are deliberately small for these machine-generated files: the local manifest is bounded to 256 KiB and the exported report to 2 MiB. These limits are safety guards, not user-photo limits.

## Write contract

Release-evidence JSON is staged in the destination directory with an exclusive randomized temporary name. The staged bytes are flushed and `fsync`-ed, read back, parsed, and compared with the validated payload before an atomic `os.replace` commits them. Temporary files are removed on failure.

An existing destination is accepted only when it is a single-link regular file. Symlinks, junctions/reparse points, hardlinked outputs, directories and other special filesystem entries fail closed. The destination identity is snapshotted before staging and checked again immediately before replacement, so a path created, removed or swapped while validated bytes are being prepared is rejected instead of silently overwritten.

The writer also validates the **lexical directory ancestry** of the output path without resolving it. Every directory from the filesystem root down to the destination parent must be a real directory; symlinked parents, Windows junctions and other reparse-point ancestors are rejected. This ancestry is checked before the destination snapshot, again immediately before the exclusive staging file is created, and once more before the atomic replacement. A late parent-path redirection therefore aborts the evidence write and the randomized staging file is cleaned up instead of being committed through the redirected path.

For `tools/release_evidence.py write`, missing normal output directories may still be created for convenience, but only after a lexical preflight has inspected every ancestor that already exists. The newly created chain is then checked strictly before the destination is snapshotted and again around staging/commit. Existing hardlinked `RELEASE_EVIDENCE.json` targets are rejected even when they do not alias the raw report.

The exported report also refuses lexical aliases or existing filesystem aliases of the generated `KEEP-ME.png`, `RECYCLE-ME.png` and `recycle-verification.json` fixture files. This prevents the evidence export path from becoming a way to mutate the very files it is meant to attest.

## Safety scope

This hardening does not alter the physical acceptance rule and cannot mark `STATUS.md` complete. A qualified release still requires a real packaged Windows run in which the generated copy is moved through the Recycle Bin-only backend, manually restored through Windows, verified against SHA-256 while the generated original remains intact, reviewed, and converted into the sanitized release attestation.

The I/O layer changes only how local evidence JSON is consumed and committed. It does not add any permanent-delete fallback, does not restore files automatically, and does not weaken the existing safety-contract binding.

## Regression coverage

`tests/test_evidence_io_safety.py` covers normal replacement of an existing report, hardlink rejection without modifying the generated original, final-entry/output-parent symlink rejection, destination identity races, late ancestry rechecks, manifest hardlinks, manifest redirected ancestry, a path swap between `lstat` and `open`, one-snapshot inspection/export consistency, deterministic runtime rebinding, and application-startup ordering.

`tests/test_release_evidence_output_ancestry.py` covers safe nested directory creation for the sanitized attestation, rejection of redirected directory ancestry, rejection of unrelated hardlinked output targets, and cleanup of the randomized staging file when a late ancestry recheck fails.
