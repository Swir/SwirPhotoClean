# Release provenance and post-publication smoke

SWIR PhotoClean release publication uses a fail-closed provenance record in addition to the human-readable `.sha256` sidecar.

For every release archive, `tools/release_provenance.py` binds the exact ZIP bytes to:

- application version,
- full Git commit SHA,
- GitHub Actions workflow run ID,
- release channel (`stable` or `prerelease`),
- archive file name, size and SHA-256 digest.

The manifest is published as `SwirPhotoClean-<version>-Windows.zip.provenance.json`. Verification fails if the archive was renamed, truncated, modified, produced from another commit/run, or paired with the wrong version/channel.

## Release workflow

The Windows release job must complete these steps in order:

1. consume the already-tested Windows onedir artifact from the exact-head build job;
2. create the release ZIP and `.sha256` sidecar;
3. create and verify the provenance manifest;
4. extract that exact ZIP into a clean directory and run `SwirPhotoClean.exe --self-test` before publication;
5. publish ZIP + checksum + provenance to the matching GitHub Release;
6. download those public assets again from GitHub;
7. re-check the public checksum and provenance against the expected version, commit, run ID and channel;
8. extract the downloaded ZIP and run the packaged `--self-test` again.

A failure at any stage fails the release job. Publication safety still depends on `tools/release_gate.py`: stable 1.x remains blocked until the authoritative `STATUS.md` acceptance gate is complete.

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

The `.sha256` sidecar remains useful for standard checksum tools; the provenance JSON adds source/run identity so a checksum from the wrong build cannot be silently treated as release evidence.
