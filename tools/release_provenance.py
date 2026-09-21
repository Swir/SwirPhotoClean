from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

PROJECT = "SwirPhotoClean"
SCHEMA_VERSION = 1
_CHUNK_SIZE = 1024 * 1024
_GIT_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$"
)


class ProvenanceError(ValueError):
    """Release provenance is missing, malformed, or does not match the package."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_commit(value: str) -> str:
    if not _GIT_SHA.fullmatch(value):
        raise ProvenanceError("git commit must be a full 40-character hexadecimal SHA")
    return value.lower()


def _validate_version(value: str) -> str:
    if not _SEMVER.fullmatch(value):
        raise ProvenanceError(f"invalid semantic version: {value!r}")
    return value


def _validate_channel(value: str) -> str:
    if value not in {"stable", "prerelease"}:
        raise ProvenanceError(f"invalid release channel: {value!r}")
    return value


def _validate_workflow_run_id(value: str | int) -> str:
    text = str(value)
    if not text.isdigit() or int(text) <= 0:
        raise ProvenanceError("workflow run id must be a positive integer")
    return text


def build_manifest(
    archive: Path,
    *,
    version: str,
    git_commit: str,
    workflow_run_id: str | int,
    channel: str,
) -> dict[str, Any]:
    if not archive.is_file():
        raise ProvenanceError(f"release archive does not exist: {archive}")

    return {
        "schema": SCHEMA_VERSION,
        "project": PROJECT,
        "version": _validate_version(version),
        "git_commit": _normalize_commit(git_commit),
        "workflow_run_id": _validate_workflow_run_id(workflow_run_id),
        "channel": _validate_channel(channel),
        "artifact": {
            "name": archive.name,
            "size": archive.stat().st_size,
            "sha256": sha256_file(archive),
        },
    }


def write_manifest(
    output: Path,
    archive: Path,
    *,
    version: str,
    git_commit: str,
    workflow_run_id: str | int,
    channel: str,
) -> dict[str, Any]:
    manifest = build_manifest(
        archive,
        version=version,
        git_commit=git_commit,
        workflow_run_id=workflow_run_id,
        channel=channel,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProvenanceError(f"cannot read provenance manifest: {error}") from error
    if not isinstance(payload, dict):
        raise ProvenanceError("provenance manifest root must be an object")
    return payload


def verify_manifest(
    manifest_path: Path,
    archive: Path,
    *,
    expected_version: str | None = None,
    expected_commit: str | None = None,
    expected_workflow_run_id: str | int | None = None,
    expected_channel: str | None = None,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    if manifest.get("schema") != SCHEMA_VERSION:
        raise ProvenanceError(f"unsupported provenance schema: {manifest.get('schema')!r}")
    if manifest.get("project") != PROJECT:
        raise ProvenanceError(f"unexpected project: {manifest.get('project')!r}")

    version = manifest.get("version")
    commit = manifest.get("git_commit")
    workflow_run_id = manifest.get("workflow_run_id")
    channel = manifest.get("channel")
    if not isinstance(version, str):
        raise ProvenanceError("manifest version is missing")
    if not isinstance(commit, str):
        raise ProvenanceError("manifest git_commit is missing")
    if not isinstance(workflow_run_id, (str, int)):
        raise ProvenanceError("manifest workflow_run_id is missing")
    if not isinstance(channel, str):
        raise ProvenanceError("manifest channel is missing")

    _validate_version(version)
    normalized_commit = _normalize_commit(commit)
    normalized_run_id = _validate_workflow_run_id(workflow_run_id)
    _validate_channel(channel)

    artifact = manifest.get("artifact")
    if not isinstance(artifact, dict):
        raise ProvenanceError("manifest artifact section is missing")
    if not archive.is_file():
        raise ProvenanceError(f"release archive does not exist: {archive}")
    if artifact.get("name") != archive.name:
        raise ProvenanceError(
            f"archive name mismatch: manifest={artifact.get('name')!r} actual={archive.name!r}"
        )
    expected_size = artifact.get("size")
    if not isinstance(expected_size, int) or expected_size < 0:
        raise ProvenanceError("manifest artifact size is invalid")
    actual_size = archive.stat().st_size
    if expected_size != actual_size:
        raise ProvenanceError(
            f"archive size mismatch: manifest={expected_size} actual={actual_size}"
        )
    expected_digest = artifact.get("sha256")
    if not isinstance(expected_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
        raise ProvenanceError("manifest artifact SHA-256 is invalid")
    actual_digest = sha256_file(archive)
    if expected_digest != actual_digest:
        raise ProvenanceError(
            f"archive SHA-256 mismatch: manifest={expected_digest} actual={actual_digest}"
        )

    if expected_version is not None and version != _validate_version(expected_version):
        raise ProvenanceError(
            f"version mismatch: manifest={version!r} expected={expected_version!r}"
        )
    if expected_commit is not None:
        normalized_expected = _normalize_commit(expected_commit)
        if normalized_commit != normalized_expected:
            raise ProvenanceError(
                f"commit mismatch: manifest={normalized_commit} expected={normalized_expected}"
            )
    if expected_workflow_run_id is not None:
        normalized_expected_run_id = _validate_workflow_run_id(expected_workflow_run_id)
        if normalized_run_id != normalized_expected_run_id:
            raise ProvenanceError(
                "workflow run mismatch: "
                f"manifest={normalized_run_id} expected={normalized_expected_run_id}"
            )
    if expected_channel is not None:
        normalized_expected_channel = _validate_channel(expected_channel)
        if channel != normalized_expected_channel:
            raise ProvenanceError(
                f"channel mismatch: manifest={channel!r} expected={normalized_expected_channel!r}"
            )

    return manifest


def _add_expectations(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--expected-version")
    parser.add_argument("--expected-commit")
    parser.add_argument("--expected-workflow-run-id")
    parser.add_argument("--expected-channel", choices=("stable", "prerelease"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create or verify a fail-closed provenance manifest for a release archive."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    write_parser = subparsers.add_parser("write", help="hash an archive and write its provenance")
    write_parser.add_argument("--archive", required=True, type=Path)
    write_parser.add_argument("--output", required=True, type=Path)
    write_parser.add_argument("--version", required=True)
    write_parser.add_argument("--commit", required=True)
    write_parser.add_argument("--workflow-run-id", required=True)
    write_parser.add_argument("--channel", required=True, choices=("stable", "prerelease"))

    verify_parser = subparsers.add_parser("verify", help="verify provenance against an archive")
    verify_parser.add_argument("--archive", required=True, type=Path)
    verify_parser.add_argument("--manifest", required=True, type=Path)
    _add_expectations(verify_parser)

    args = parser.parse_args()
    try:
        if args.command == "write":
            manifest = write_manifest(
                args.output,
                args.archive,
                version=args.version,
                git_commit=args.commit,
                workflow_run_id=args.workflow_run_id,
                channel=args.channel,
            )
            print(
                f"release provenance written: {args.output} "
                f"sha256={manifest['artifact']['sha256']}"
            )
            return 0

        verify_manifest(
            args.manifest,
            args.archive,
            expected_version=args.expected_version,
            expected_commit=args.expected_commit,
            expected_workflow_run_id=args.expected_workflow_run_id,
            expected_channel=args.expected_channel,
        )
        print(f"release provenance ok: {args.archive}")
        return 0
    except (OSError, ProvenanceError) as error:
        raise SystemExit(f"release provenance failed: {error}") from error


if __name__ == "__main__":
    raise SystemExit(main())
