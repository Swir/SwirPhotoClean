# Qualified release safety contract

SWIR PhotoClean binds the physical Windows Recycle Bin move/Restore evidence to the exact safety-critical source used by the tested package. This prevents a successful manual test from an older build being reused after cleanup, Recycle, evidence, release-gate or Windows packaging logic changes.

## What is bound

`photoclean/safety_contract.py` defines the explicit safety-critical file set. It includes the cleanup/revalidation path, Recycle backend, generated evidence adapter, runtime launcher, runtime self-test, release-evidence/gate/provenance code, runtime dependencies, pinned build dependencies and the Windows workflow. The contract is deterministic: every required path contributes its path, size and SHA-256 to one final SHA-256 digest.

Build-tool and verification changes intentionally invalidate qualified physical evidence too. In particular, changing `requirements-build.txt`, `photoclean/selftest.py` or `tools/release_provenance.py` now changes the safety-contract digest, so evidence cannot silently survive a PyInstaller/build-recipe change, a packaged self-test change or a release-provenance verifier change.

The generated `assets/safety-contract.json` is a build artifact, not a source of truth. Windows CI creates it from the exact PR/main head immediately before PyInstaller, verifies it against the checkout and packages it through the existing `assets` bundle. `SwirPhotoClean.exe --self-test` reads that bundled contract and reports the digest; CI requires it to match the exact-head source contract.

## Physical evidence lifecycle

A new `--recycle-restore-prepare` session records the running package's safety-contract digest inside the tamper-evident `recycle-verification.json` before any Recycle Bin move. The manifest fingerprint covers that field.

All subsequent qualified evidence commands fail closed when the running package/source contract differs from the recorded digest:

- `--recycle-restore-move`
- `--recycle-restore-status`
- `--recycle-restore-verify`
- `--recycle-restore-review`

This means an evidence session must be restarted after a safety-critical change. Existing low-level diagnostic manifest support remains readable for regression/backward-compatibility tests, but an unbound legacy manifest cannot enter the qualified CLI/release workflow.

## Release evidence

`tools/release_evidence.py` writes schema v2 `RELEASE_EVIDENCE.json`. In addition to the generated fixture/report hashes and explicit manual-Restore attestation, it stores `safety_contract_sha256` and requires that value to match the current source checkout.

Qualified Beta/RC/1.x publication therefore requires all three identities to agree:

1. the physical Recycle/Restore session's recorded safety contract;
2. the current release checkout's deterministic safety contract;
3. the contract embedded in the exact package that passes pre-publication and post-publication `--self-test`.

The release workflow compares the package self-test contract to the sanitized runtime evidence before publication and repeats the comparison after downloading the public release archive.

## Intentional invalidation

Changing any file in `SAFETY_CONTRACT_FILES` invalidates prior qualified runtime evidence. That is deliberate. Non-safety release bookkeeping such as `STATUS.md`, release notes, version metadata or the generated `RELEASE_EVIDENCE.json` itself is not part of the contract, so completing the reviewed acceptance checkbox and preparing release metadata does not force an unnecessary second physical Recycle Bin test.

The contract does not replace the manual Windows requirement and never changes `STATUS.md` automatically. The 1.0 acceptance item stays open until a real generated copy is moved to Windows Recycle Bin, manually restored and reviewed while the generated original remains intact.
