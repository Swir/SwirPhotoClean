# Qualified release safety contract

SWIR PhotoClean binds the physical Windows Recycle Bin move/Restore evidence to the exact shipped Python runtime plus the release/build path used by the tested package. This prevents a successful manual test from an older runtime from being reused after scanner, review, GUI, cleanup, Recycle, evidence, version, argument-routing, packaging or publication logic changes.

## What is bound

`photoclean/safety_contract.py` defines an explicit deterministic file set. It now includes **every top-level `photoclean/*.py` runtime module**, together with `run.py`, runtime/build requirements, the Windows workflow and release evidence/gate/provenance tooling. Every required path contributes its path, size and SHA-256 to one final SHA-256 digest.

This is intentionally stricter than a hand-picked safety subset. A change to Smart Keep/review code, session handling, localization, theme/window behavior, Folder Health, Burst Cleaner, scanner/core logic, Diagnostics, Recycle handling or another shipped Python module invalidates earlier qualified physical evidence. The reason is simple: the final release must prove the manual Windows test belongs to the exact application runtime being shipped, not merely to a compatible Recycle helper.

A regression test enumerates the repository's top-level `photoclean/*.py` files and fails if a new runtime module is not present in `SAFETY_CONTRACT_FILES`. This makes future runtime expansion fail closed instead of silently escaping evidence invalidation.

Build-tool and verification changes intentionally invalidate qualified physical evidence too. Changing `requirements-build.txt`, `photoclean/selftest.py`, `.github/workflows/windows.yml` or `tools/release_provenance.py` changes the contract digest, so evidence cannot silently survive a PyInstaller/build-recipe change, a packaged self-test change or a release-provenance verifier change.

Release identity and command routing are also covered. `photoclean/__init__.py` carries the application version and `photoclean/storage.py` resolves Portable Mode and strips runtime switches before the self-test/Recycle-evidence dispatcher runs. Changing either file changes the contract digest. Therefore a physical Recycle/Restore session from one application version cannot be promoted after bumping the version, and a session cannot silently survive a change to the code that decides which packaged command is actually executed.

The qualified GUI path is covered as part of the complete runtime. `photoclean/diagnostics_gui.py` owns the explicit manual-Restore confirmation and writes packaged `RELEASE_EVIDENCE.json`; `photoclean/diagnostics_plus_gui.py` resumes and cross-checks persisted attestation against the exact fixture/report; `photoclean/folder_health_app.py` is the final packaged application router that selects `EnhancedDiagnosticsWindow`. Any change to these files invalidates older physical evidence.

The generated `assets/safety-contract.json` is a build artifact, not a source of truth. Windows CI creates it from the exact PR/main head immediately before PyInstaller, verifies it against the checkout and packages it through the existing `assets` bundle. `SwirPhotoClean.exe --self-test` reads that bundled contract and reports the digest; CI requires it to match the exact-head source contract.

## Physical evidence lifecycle

A new `--recycle-restore-prepare` session records the running package's safety-contract digest inside the tamper-evident `recycle-verification.json` before any Recycle Bin move. The manifest fingerprint covers that field.

All subsequent qualified evidence commands fail closed when the running package/source contract differs from the recorded digest:

- `--recycle-restore-move`
- `--recycle-restore-status`
- `--recycle-restore-verify`
- `--recycle-restore-review`

The Diagnostics Center uses the same contract-bound fixture/report/attestation path. Its Prepare, Resume, Verify and RELEASE_EVIDENCE actions therefore inherit the same invalidation behavior when any runtime/release-contract file changes.

This means an evidence session must be restarted after a shipped Python runtime, release-version, build, workflow or release-verification change. Existing low-level diagnostic manifest support remains readable for regression/backward-compatibility tests, but an unbound or stale manifest cannot enter the qualified CLI/release workflow.

For a qualified Beta/RC/1.x candidate, set the intended candidate version **before** running the physical Windows evidence flow. A later runtime or version change intentionally invalidates the prior safety-contract digest and requires a fresh generated move → manual Restore → verify session.

## Release evidence

`tools/release_evidence.py` writes schema v3 `RELEASE_EVIDENCE.json`. In addition to the generated fixture/report hashes and explicit manual-Restore attestation, it stores `safety_contract_sha256` and requires that value to match the current source checkout.

Qualified Beta/RC/1.x evidence is accepted only when the validated report proves it originated from a **frozen Windows runtime**. Source/interpreter runs and non-Windows simulated runs can still exercise lower-level diagnostics/tests, but they cannot be promoted into release evidence. The sanitized release contract records this as `windows_packaged_runtime_confirmed=true`.

Qualified Beta/RC/1.x publication therefore requires all of these identities/conditions to agree:

1. the physical Recycle/Restore session's recorded full-runtime safety contract;
2. the current release checkout's deterministic contract, including the complete shipped Python runtime, release version and build/release path;
3. the contract embedded in the exact package that passes pre-publication and post-publication `--self-test`;
4. the physical evidence report identifies a packaged `SwirPhotoClean.exe` running on Windows, not a source/interpreter or non-Windows test harness.

The release workflow compares the package self-test contract to the sanitized runtime evidence before publication and repeats the comparison after downloading the public release archive.

## Intentional invalidation

Changing any file in `SAFETY_CONTRACT_FILES` invalidates prior qualified runtime evidence. That is deliberate. The complete top-level application runtime is included so a qualified physical test cannot be borrowed by a later package whose scanner, review workflow, UI/runtime behavior or safety path has changed.

Acceptance bookkeeping and documentation that do not change executable identity remain outside the digest: `STATUS.md`, release notes, generated progress SVGs, docs and `RELEASE_EVIDENCE.json` itself do not force another physical test. These files may record and publish evidence already obtained from the exact versioned/runtime-qualified candidate.

The contract does not replace the manual Windows requirement and never changes `STATUS.md` automatically. The 1.0 acceptance item stays open until a real generated copy is moved to Windows Recycle Bin, manually restored and reviewed while the generated original remains intact.
