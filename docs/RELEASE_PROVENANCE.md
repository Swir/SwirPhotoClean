# Release provenance and transactional publication

SWIR PhotoClean release publication uses a fail-closed provenance record in addition to the human-readable `.sha256` sidecar.

For every release archive, `tools/release_provenance.py` binds the exact ZIP bytes to:

- application version,
- full Git commit SHA,
- GitHub Actions workflow run ID,
- release channel (`stable` or `prerelease`),
- archive file name, size and SHA-256 digest.

The manifest is published as `SwirPhotoClean-<version>-Windows.zip.provenance.json`. Verification fails if the archive was renamed, truncated, modified, produced from another commit/run, or paired with the wrong version/channel.

Qualified Beta/RC/1.x releases add a second, independent binding: the physical Windows Recycle Bin move/Restore evidence records the deterministic release-safety contract from the package that performed the test. `RELEASE_EVIDENCE.json` must carry the same contract as the current release checkout, and the packaged `--self-test` must report that same digest before and after public download. See `docs/RELEASE_SAFETY_CONTRACT.md`.

The packaged attestation handoff is transactional as well. `SwirPhotoClean.exe --recycle-restore-attest` refuses an output path that aliases the source evidence report, manifest, or generated KEEP/RECYCLE fixture, stages JSON under an unpredictable exclusive temporary name in the destination directory, validates those staged bytes, flushes them to disk, and only then atomically replaces `RELEASE_EVIDENCE.json`. A stale predictable `.tmp` file is never reused, so interrupted or hostile staging state cannot silently overwrite the evidence inputs.

## Release workflow

The Windows release job must complete these steps in order:

1. consume the already-tested Windows onedir artifact from the exact-head build job;
2. create the release ZIP and `.sha256` sidecar;
3. create and verify the provenance manifest;
4. extract that exact ZIP into a clean directory and run `SwirPhotoClean.exe --self-test` before any GitHub Release is published;
5. for a qualified release, require the packaged self-test safety contract to match the reviewed runtime evidence;
6. create the matching GitHub Release as a **draft** and upload ZIP + checksum + provenance (and qualified runtime evidence when required);
7. download the draft assets again and re-check checksum, provenance, runtime evidence and packaged `--self-test` while the release is still non-public;
8. publish the verified draft only after the staged asset checks succeed, preserving the `stable` / `prerelease` decision from `tools/release_gate.py`;
9. download the now-public assets again from GitHub and repeat checksum, provenance, qualified runtime-evidence and packaged `--self-test` verification;
10. if any post-publication verification step fails, immediately return the release to **draft** and fail the job so an unverified release is not intentionally left public.

A failure before publication leaves the release as a draft. A failure after publication triggers the rollback-to-draft path before the workflow reports failure. This makes successful completion of the release job mean that the exact public assets—not just the local archive—passed checksum/provenance and packaged runtime smoke verification.

Publication safety still depends on `tools/release_gate.py`: stable 1.x remains blocked until the authoritative `STATUS.md` acceptance gate is complete, and qualified Beta/RC/1.x additionally requires current physical runtime evidence.

## Manual verification

With the release ZIP and provenance JSON in the same directory:

```powershell
python tools/release_provenance.py verify `
  --archive SwirPhotoClean-1.0.0-Windows.zip `
  --manifest SwirPhotoClean-1.0.0-Windows.zip.provenance.json `
  --expected-version 1.0.0 `
  --expected-commit <40-character-release-commit-sha> `
  --expected-workflow-run-id <github-actions-run-id> `
  --expected-channel stable
```

The `.sha256` sidecar remains useful for standard checksum tools; the provenance JSON adds source/run identity so a checksum from the wrong build cannot be silently treated as release evidence. The safety-contract binding separately prevents valid physical Recycle evidence from being reused after safety-critical source changes.
