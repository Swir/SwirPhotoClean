# Qualified release safety contract

SWIR PhotoClean binds the physical Windows Recycle Bin move/Restore evidence to the exact safety-critical source, release version, runtime-dispatch path and Diagnostics Center attestation flow used by the tested package. This prevents a successful manual test from an older build being reused after cleanup, Recycle, evidence, release-gate, version, argument-routing, qualified GUI or Windows packaging logic changes.

## What is bound

`photoclean/safety_contract.py` defines the explicit safety-critical file set. It includes the cleanup/revalidation path, Recycle backend, generated evidence adapter, runtime launcher, runtime storage/argument dispatch, runtime self-test, release identity/version, release-evidence/gate/provenance code, runtime dependencies, pinned build dependencies, the qualified Diagnostics Center evidence UI and the Windows workflow. The contract is deterministic: every required path contributes its path, size and SHA-256 to one final SHA-256 digest.

Build-tool and verification changes intentionally invalidate qualified physical evidence too. In particular, changing `requirements-build.txt`, `photoclean/selftest.py` or `tools/release_provenance.py` changes the safety-contract digest, so evidence cannot silently survive a PyInstaller/build-recipe change, a packaged self-test change or a release-provenance verifier change.

Release identity and command routing are also intentionally covered. `photoclean/__init__.py` carries the application version and `photoclean/storage.py` resolves Portable Mode and strips runtime switches before the self-test/Recycle-evidence dispatcher runs. Changing either file now changes the contract digest. Therefore a physical Recycle/Restore session from one application version cannot be promoted after bumping the version, and a session cannot silently survive a change to the code that decides which packaged command is actually executed.

The qualified GUI path is covered for the same reason. `photoclean/diagnostics_gui.py` owns the explicit manual-Restore confirmation and writes packaged `RELEASE_EVIDENCE.json`; `photoclean/diagnostics_plus_gui.py` resumes and cross-checks persisted attestation against the exact fixture/report. Any change to either file now invalidates older physical evidence. This prevents a later GUI change from silently weakening, skipping or mis-associating the human confirmation step while reusing an earlier evidence session.

The generated `assets/safety-contract.json` is a build artifact, not a source of truth. Windows CI creates it from the exact PR/main head immediately before PyInstaller, verifies it against the checkout and packages it through the existing `assets` bundle. `SwirPhotoClean.exe --self-test` reads that bundled contract and reports the digest; CI requires it to match the exact-head source contract.

## Physical evidence lifecycle

A new `--recycle-restore-prepare` session records the running package's safety-contract digest inside the tamper-evident `recycle-verification.json` before any Recycle Bin move. The manifest fingerprint covers that field.

All subsequent qualified evidence commands fail closed when the running package/source contract differs from the recorded digest:

- `--recycle-restore-move`
- `--recycle-restore-status`
- `--recycle-restore-verify`
- `--recycle-restore-review`

The Diagnostics Center uses the same contract-bound fixture/report/attestation path. Its Prepare, Resume, Verify and RELEASE_EVIDENCE actions therefore inherit the same invalidation behavior when any safety-contract file changes.

This means an evidence session must be restarted after a safety-critical, release-version, qualified-GUI or runtime-dispatch change. Existing low-level diagnostic manifest support remains readable for regression/backward-compatibility tests, but an unbound legacy manifest cannot enter the qualified CLI/release workflow.

For a qualified Beta/RC/1.x candidate, set the intended candidate version **before** running the physical Windows evidence flow. A later version bump intentionally invalidates the prior safety-contract digest and requires a fresh generated move → manual Restore → verify session. This prevents a package carrying different release identity from borrowing evidence from an earlier candidate.

## Release evidence

`tools/release_evidence.py` writes schema v3 `RELEASE_EVIDENCE.json`. In addition to the generated fixture/report hashes and explicit manual-Restore attestation, it stores `safety_contract_sha256` and requires that value to match the current source checkout.

Qualified Beta/RC/1.x evidence is accepted only when the validated report proves it originated from a **frozen Windows runtime**. Source/interpreter runs and non-Windows simulated runs can still exercise lower-level diagnostics/tests, but they cannot be promoted into release evidence. The sanitized release contract records this as `windows_packaged_runtime_confirmed=true`.

Qualified Beta/RC/1.x publication therefore requires all of these identities/conditions to agree:

1. the physical Recycle/Restore session's recorded safety contract;
2. the current release checkout's deterministic safety contract, including release version, runtime-dispatch code and qualified Diagnostics Center evidence UI;
3. the contract embedded in the exact package that passes pre-publication and post-publication `--self-test`;
4. the physical evidence report identifies a packaged `SwirPhotoClean.exe` running on Windows, not a source/interpreter or non-Windows test harness.

The release workflow compares the package self-test contract to the sanitized runtime evidence before publication and repeats the comparison after downloading the public release archive.

## Intentional invalidation

Changing any file in `SAFETY_CONTRACT_FILES` invalidates prior qualified runtime evidence. That is deliberate. The application version is part of this contract because qualified physical evidence must belong to the exact release identity being published. Runtime storage/argument dispatch is also included because it executes before the evidence command path. The qualified Diagnostics Center evidence files are included because they collect the explicit manual-Restore confirmation and recover persisted attestation used during final acceptance.

Acceptance bookkeeping that does not change executable identity or behavior remains outside the digest: `STATUS.md`, release notes, generated progress SVGs and `RELEASE_EVIDENCE.json` itself do not force another physical test. Complete those only after reviewing genuine evidence from the already-versioned candidate package.

The contract does not replace the manual Windows requirement and never changes `STATUS.md` automatically. The 1.0 acceptance item stays open until a real generated copy is moved to Windows Recycle Bin, manually restored and reviewed while the generated original remains intact.
