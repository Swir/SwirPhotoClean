from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

PROJECT = "SwirPhotoClean"
SCHEMA_VERSION = 2
LEGACY_SCHEMA_VERSION = 1
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RELEASE_EVIDENCE = ROOT / "RELEASE_EVIDENCE.json"
_CHUNK_SIZE = 1024 * 1024
_GIT_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
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


def _validate_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        raise ProvenanceError(f"{label} must be 64 lowercase hexadecimal characters")
    return value


def _current_safety_contract_sha256() -> str:
    """Hash the exact source/build contract that produced this provenance."""
    try:
        from photoclean.safety_contract import source_safety_contract_sha256

        return source_safety_contract_sha256(ROOT)
    except (OSError, ValueError) as error:
        raise ProvenanceError(
            f"cannot evaluate current release safety contract: {error}"
        ) from error


def _release_evidence_metadata(path: Path) -> dict[str, Any]:
    evidence = Path(path)
    if not evidence.is_file():
        raise ProvenanceError(f"release evidence does not exist: {evidence}")
    return {
        "name": evidence.name,
        "size": evidence.stat().st_size,
        "sha256": sha256_file(evidence),
    }


def _resolve_release_evidence(path: Path | None) -> Path | None:
    if path is not None:
        return Path(path)
    if DEFAULT_RELEASE_EVIDENCE.is_file():
        return DEFAULT_RELEASE_EVIDENCE
    return None


def build_manifest(
    archive: Path,
    *,
    version: str,
    git_commit: str,
    workflow_run_id: str | int,
    channel: str,
    safety_contract_sha256: str | None = None,
    release_evidence: Path | None = None,
) -> dict[str, Any]:
    if not archive.is_file():
        raise ProvenanceError(f"release archive does not exist: {archive}")

    contract = (
        _validate_sha256(safety_contract_sha256, "safety contract SHA-256")
        if safety_contract_sha256 is not None
        else _current_safety_contract_sha256()
    )
    evidence_path = _resolve_release_evidence(release_evidence)
    evidence = (
        _release_evidence_metadata(evidence_path)
        if evidence_path is not None
        else None
    )

    return {
        "schema": SCHEMA_VERSION,
        "project": PROJECT,
        "version": _validate_version(version),
        "git_commit": _normalize_commit(git_commit),
        "workflow_run_id": _validate_workflow_run_id(workflow_run_id),
        "channel": _validate_channel(channel),
        "safety_contract_sha256": contract,
        "release_evidence": evidence,
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
    safety_contract_sha256: str | None = None,
    release_evidence: Path | None = None,
) -> dict[str, Any]:
    manifest = build_manifest(
        archive,
        version=version,
        git_commit=git_commit,
        workflow_run_id=workflow_run_id,
        channel=channel,
        safety_contract_sha256=safety_contract_sha256,
        release_evidence=release_evidence,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProvenanceError(f"cannot read provenance manifest: {error}") from error
    if not isinstance(payload, dict):
        raise ProvenanceError("provenance manifest root must be an object")
    return payload


def _validate_artifact(manifest: dict[str, Any], archive: Path) -> None:
    artifact = manifest.get("artifact")
    if not isinstance(artifact, dict):
        raise ProvenanceError("manifest artifact section is missing")
    if set(artifact) != {"name", "size", "sha256"}:
        raise ProvenanceError("manifest artifact section contains missing or unsupported fields")
    if not archive.is_file():
        raise ProvenanceError(f"release archive does not exist: {archive}")
    if artifact.get("name") != archive.name:
        raise ProvenanceError(
            f"archive name mismatch: manifest={artifact.get('name')!r} actual={archive.name!r}"
        )
    expected_size = artifact.get("size")
    if not isinstance(expected_size, int) or isinstance(expected_size, bool) or expected_size < 0:
        raise ProvenanceError("manifest artifact size is invalid")
    actual_size = archive.stat().st_size
    if expected_size != actual_size:
        raise ProvenanceError(
            f"archive size mismatch: manifest={expected_size} actual={actual_size}"
        )
    expected_digest = _validate_sha256(
        artifact.get("sha256"),
        "manifest artifact SHA-256",
    )
    actual_digest = sha256_file(archive)
    if expected_digest != actual_digest:
        raise ProvenanceError(
            f"archive SHA-256 mismatch: manifest={expected_digest} actual={actual_digest}"
        )


def _validate_release_evidence_binding(
    value: object,
    release_evidence: Path | None,
) -> None:
    if value is None:
        if release_evidence is not None:
            raise ProvenanceError(
                "provenance does not bind the supplied RELEASE_EVIDENCE.json"
            )
        return
    if not isinstance(value, dict) or set(value) != {"name", "size", "sha256"}:
        raise ProvenanceError(
            "manifest release_evidence must be null or contain exactly name, size and sha256"
        )
    name = value.get("name")
    if not isinstance(name, str) or not name:
        raise ProvenanceError("manifest release evidence name is invalid")
    size = value.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise ProvenanceError("manifest release evidence size is invalid")
    digest = _validate_sha256(
        value.get("sha256"),
        "manifest release evidence SHA-256",
    )
    if release_evidence is None:
        return

    evidence = Path(release_evidence)
    if not evidence.is_file():
        raise ProvenanceError(f"release evidence does not exist: {evidence}")
    if name != evidence.name:
        raise ProvenanceError(
            f"release evidence name mismatch: manifest={name!r} actual={evidence.name!r}"
        )
    actual_size = evidence.stat().st_size
    if size != actual_size:
        raise ProvenanceError(
            f"release evidence size mismatch: manifest={size} actual={actual_size}"
        )
    actual_digest = sha256_file(evidence)
    if digest != actual_digest:
        raise ProvenanceError(
            f"release evidence SHA-256 mismatch: manifest={digest} actual={actual_digest}"
        )


def verify_manifest(
    manifest_path: Path,
    archive: Path,
    *,
    expected_version: str | None = None,
    expected_commit: str | None = None,
    expected_workflow_run_id: str | int | None = None,
    expected_channel: str | None = None,
    expected_safety_contract_sha256: str | None = None,
    release_evidence: Path | None = None,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    schema = manifest.get("schema")
    if schema not in {LEGACY_SCHEMA_VERSION, SCHEMA_VERSION}:
        raise ProvenanceError(f"unsupported provenance schema: {schema!r}")
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
    if not isinstance(workflow_run_id, (str, int)) or isinstance(workflow_run_id, bool):
        raise ProvenanceError("manifest workflow_run_id is missing")
    if not isinstance(channel, str):
        raise ProvenanceError("manifest channel is missing")

    _validate_version(version)
    normalized_commit = _normalize_commit(commit)
    normalized_run_id = _validate_workflow_run_id(workflow_run_id)
    _validate_channel(channel)
    _validate_artifact(manifest, archive)

    resolved_evidence = _resolve_release_evidence(release_evidence)
    if schema == SCHEMA_VERSION:
        expected_keys = {
            "schema",
            "project",
            "version",
            "git_commit",
            "workflow_run_id",
            "channel",
            "safety_contract_sha256",
            "release_evidence",
            "artifact",
        }
        if set(manifest) != expected_keys:
            raise ProvenanceError(
                "schema 2 provenance contains missing or unsupported top-level fields"
            )
        recorded_contract = _validate_sha256(
            manifest.get("safety_contract_sha256"),
            "manifest safety contract SHA-256",
        )
        current_contract = (
            _validate_sha256(
                expected_safety_contract_sha256,
                "expected safety contract SHA-256",
            )
            if expected_safety_contract_sha256 is not None
            else _current_safety_contract_sha256()
        )
        if recorded_contract != current_contract:
            raise ProvenanceError(
                "safety contract mismatch: "
                f"manifest={recorded_contract} expected={current_contract}"
            )
        _validate_release_evidence_binding(
            manifest.get("release_evidence"),
            resolved_evidence,
        )
    else:
        legacy_keys = {
            "schema",
            "project",
            "version",
            "git_commit",
            "workflow_run_id",
            "channel",
            "artifact",
        }
        if set(manifest) != legacy_keys:
            raise ProvenanceError(
                "legacy provenance contains missing or unsupported top-level fields"
            )
        if expected_safety_contract_sha256 is not None or release_evidence is not None:
            raise ProvenanceError(
                "legacy provenance does not bind safety contract or release evidence"
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
    parser.add_argument(
        "--expected-safety-contract-sha256",
        help=(
            "expected exact source/build safety-contract SHA-256; "
            "defaults to the current checkout"
        ),
    )
    parser.add_argument(
        "--release-evidence",
        type=Path,
        help=(
            "RELEASE_EVIDENCE.json to bind/verify; when omitted, the repository-root "
            "file is used automatically if present"
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create or verify fail-closed release provenance bound to the archive, "
            "exact safety contract and qualified runtime evidence."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    write_parser = subparsers.add_parser(
        "write",
        help="hash an archive and write its provenance",
    )
    write_parser.add_argument("--archive", required=True, type=Path)
    write_parser.add_argument("--output", required=True, type=Path)
    write_parser.add_argument("--version", required=True)
    write_parser.add_argument("--commit", required=True)
    write_parser.add_argument("--workflow-run-id", required=True)
    write_parser.add_argument(
        "--channel",
        required=True,
        choices=("stable", "prerelease"),
    )
    write_parser.add_argument(
        "--safety-contract-sha256",
        help="override exact source safety-contract SHA-256 (normally auto-detected)",
    )
    write_parser.add_argument(
        "--release-evidence",
        type=Path,
        help=(
            "RELEASE_EVIDENCE.json to bind; when omitted, the repository-root "
            "file is used automatically if present"
        ),
    )

    verify_parser = subparsers.add_parser(
        "verify",
        help="verify provenance against an archive",
    )
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
                safety_contract_sha256=args.safety_contract_sha256,
                release_evidence=args.release_evidence,
            )
            evidence_state = (
                manifest["release_evidence"]["sha256"]
                if manifest["release_evidence"] is not None
                else "none"
            )
            print(
                f"release provenance written: {args.output} "
                f"sha256={manifest['artifact']['sha256']} "
                f"safety_contract={manifest['safety_contract_sha256']} "
                f"release_evidence={evidence_state}"
            )
            return 0

        verify_manifest(
            args.manifest,
            args.archive,
            expected_version=args.expected_version,
            expected_commit=args.expected_commit,
            expected_workflow_run_id=args.expected_workflow_run_id,
            expected_channel=args.expected_channel,
            expected_safety_contract_sha256=args.expected_safety_contract_sha256,
            release_evidence=args.release_evidence,
        )
        print(f"release provenance ok: {args.archive}")
        return 0
    except (OSError, ProvenanceError) as error:
        raise SystemExit(f"release provenance failed: {error}") from error


if __name__ == "__main__":
    raise SystemExit(main())
