from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any

PROJECT = "SwirPhotoClean"
SCHEMA_VERSION = 2
LEGACY_SCHEMA_VERSION = 1
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RELEASE_EVIDENCE = ROOT / "RELEASE_EVIDENCE.json"
_CHUNK_SIZE = 1024 * 1024
_MAX_PROVENANCE_MANIFEST_BYTES = 64 * 1024
_MAX_RELEASE_EVIDENCE_BYTES = 64 * 1024
_REPARSE_POINT_ATTRIBUTE = 0x400
_GIT_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$"
)


class ProvenanceError(ValueError):
    """Release provenance is missing, malformed, or does not match the package."""


def _absolute_without_resolving(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def _input_identity(info) -> tuple[int, int, int, int, int, int]:
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(getattr(info, "st_nlink", 1)),
        int(info.st_size),
        int(getattr(info, "st_mtime_ns", int(info.st_mtime * 1_000_000_000))),
        int(getattr(info, "st_ctime_ns", int(info.st_ctime * 1_000_000_000))),
    )


def _path_and_handle_identity_match(
    path_identity: tuple[int, int, int, int, int, int],
    handle_identity: tuple[int, int, int, int, int, int],
) -> bool:
    if os.name != "nt":
        return path_identity == handle_identity

    path_inode = path_identity[1]
    handle_inode = handle_identity[1]
    if path_inode <= 0 or handle_inode <= 0 or path_inode != handle_inode:
        return False
    return path_identity[2:5] == handle_identity[2:5]


def _require_safe_input_ancestry(
    directory: Path,
    *,
    label: str,
    allow_missing: bool = False,
) -> None:
    """Reject symlink/junction/reparse ancestry without resolving it away."""
    current = _absolute_without_resolving(directory)
    chain: list[Path] = []
    while True:
        chain.append(current)
        parent = current.parent
        if parent == current:
            break
        current = parent

    for entry in reversed(chain):
        try:
            info = entry.lstat()
        except FileNotFoundError:
            if allow_missing:
                continue
            raise ProvenanceError(f"{label} directory does not exist: {entry}")
        except OSError as error:
            raise ProvenanceError(
                f"cannot safely inspect {label} directory {entry}: {error}"
            ) from error
        if stat.S_ISLNK(info.st_mode) or bool(
            getattr(info, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE
        ):
            raise ProvenanceError(
                f"{label} directory ancestry must not contain symlinks, junctions or reparse points: {entry}"
            )
        if not stat.S_ISDIR(info.st_mode):
            raise ProvenanceError(
                f"{label} directory ancestry contains a non-directory entry: {entry}"
            )


def _require_safe_regular_input(
    path: Path,
    *,
    label: str,
    max_bytes: int | None = None,
):
    try:
        info = path.lstat()
    except OSError as error:
        raise ProvenanceError(f"cannot safely inspect {label} {path}: {error}") from error
    if stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE
    ):
        raise ProvenanceError(f"{label} must not be a symlink, junction or reparse point")
    if not stat.S_ISREG(info.st_mode):
        raise ProvenanceError(f"{label} must be a regular file")
    if int(getattr(info, "st_nlink", 1)) != 1:
        raise ProvenanceError(f"{label} must not be hardlinked")
    if max_bytes is not None and int(info.st_size) > max_bytes:
        raise ProvenanceError(f"{label} is too large: maximum is {max_bytes} bytes")
    return info


def _stable_input_snapshot(
    path: Path,
    *,
    label: str,
    max_bytes: int | None = None,
    capture_bytes: bool = False,
) -> tuple[int, str, bytes | None]:
    """Read/hash one immutable regular-file snapshot through a bound handle."""
    candidate = _absolute_without_resolving(path)
    _require_safe_input_ancestry(candidate.parent, label=label)
    before = _require_safe_regular_input(candidate, label=label, max_bytes=max_bytes)
    before_identity = _input_identity(before)
    expected_size = int(before.st_size)

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(candidate, flags)
    except OSError as error:
        raise ProvenanceError(f"cannot open {label} safely: {error}") from error

    digest = hashlib.sha256()
    chunks: list[bytes] | None = [] if capture_bytes else None
    total = 0
    opened_identity: tuple[int, int, int, int, int, int] | None = None
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ProvenanceError(f"{label} changed to a non-regular file while opening")
        if bool(getattr(opened, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE):
            raise ProvenanceError(f"{label} changed to a reparse point while opening")
        if int(getattr(opened, "st_nlink", 1)) != 1:
            raise ProvenanceError(f"{label} became hardlinked while opening")
        if max_bytes is not None and int(opened.st_size) > max_bytes:
            raise ProvenanceError(f"{label} is too large: maximum is {max_bytes} bytes")

        opened_identity = _input_identity(opened)
        if not _path_and_handle_identity_match(before_identity, opened_identity):
            raise ProvenanceError(f"{label} changed while it was being opened")

        while True:
            remaining = expected_size + 1 - total
            if remaining <= 0:
                raise ProvenanceError(f"{label} grew while it was being read")
            try:
                chunk = os.read(descriptor, min(_CHUNK_SIZE, remaining))
            except OSError as error:
                raise ProvenanceError(f"cannot read {label} safely: {error}") from error
            if not chunk:
                break
            total += len(chunk)
            if total > expected_size:
                raise ProvenanceError(f"{label} grew while it was being read")
            digest.update(chunk)
            if chunks is not None:
                chunks.append(chunk)

        after = os.fstat(descriptor)
        if _input_identity(after) != opened_identity:
            raise ProvenanceError(f"{label} changed while it was being read")
    finally:
        os.close(descriptor)

    if opened_identity is None:
        raise ProvenanceError(f"{label} could not be bound to an open file handle")
    _require_safe_input_ancestry(candidate.parent, label=label)
    final = _require_safe_regular_input(candidate, label=label, max_bytes=max_bytes)
    final_identity = _input_identity(final)
    if final_identity != before_identity:
        raise ProvenanceError(f"{label} path changed while it was being read")
    if not _path_and_handle_identity_match(final_identity, opened_identity):
        raise ProvenanceError(f"{label} path no longer refers to the verified file handle")
    if total != expected_size:
        raise ProvenanceError(f"{label} size changed while it was being read")

    raw = b"".join(chunks) if chunks is not None else None
    return expected_size, digest.hexdigest(), raw


def sha256_file(path: Path) -> str:
    _size, digest, _raw = _stable_input_snapshot(path, label="release input")
    return digest


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
    evidence = _absolute_without_resolving(path)
    size, digest, _raw = _stable_input_snapshot(
        evidence,
        label="release evidence",
        max_bytes=_MAX_RELEASE_EVIDENCE_BYTES,
    )
    return {
        "name": evidence.name,
        "size": size,
        "sha256": digest,
    }


def _resolve_release_evidence(path: Path | None) -> Path | None:
    if path is not None:
        return Path(path)
    try:
        DEFAULT_RELEASE_EVIDENCE.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise ProvenanceError(
            f"cannot safely inspect default release evidence: {error}"
        ) from error
    return DEFAULT_RELEASE_EVIDENCE


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
    archive_path = _absolute_without_resolving(archive)
    archive_size, archive_digest, _raw = _stable_input_snapshot(
        archive_path,
        label="release archive",
    )

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
            "name": archive_path.name,
            "size": archive_size,
            "sha256": archive_digest,
        },
    }


def _provenance_output_identity(path: Path) -> tuple[int, int, int, int, int, int] | None:
    """Return a safe existing output identity or fail closed for aliases."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise ProvenanceError(
            f"cannot safely inspect provenance output path {path}: {error}"
        ) from error
    if stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE
    ):
        raise ProvenanceError(
            "provenance output must not be a symlink, junction or reparse point"
        )
    if not stat.S_ISREG(info.st_mode):
        raise ProvenanceError("provenance output must be a regular file")
    if int(getattr(info, "st_nlink", 1)) != 1:
        raise ProvenanceError("provenance output must not be hardlinked")
    if int(info.st_size) > _MAX_PROVENANCE_MANIFEST_BYTES:
        raise ProvenanceError(
            "provenance output is too large: "
            f"maximum is {_MAX_PROVENANCE_MANIFEST_BYTES} bytes"
        )
    return _input_identity(info)


def _write_manifest_atomically(output: Path, raw: bytes) -> None:
    """Stage, fsync, same-handle verify and atomically replace one manifest."""
    if len(raw) > _MAX_PROVENANCE_MANIFEST_BYTES:
        raise ProvenanceError(
            "provenance manifest is too large: "
            f"maximum is {_MAX_PROVENANCE_MANIFEST_BYTES} bytes"
        )

    candidate = _absolute_without_resolving(output)
    _require_safe_input_ancestry(
        candidate.parent,
        label="provenance output",
        allow_missing=True,
    )
    try:
        candidate.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise ProvenanceError(f"cannot create provenance output directory: {error}") from error
    _require_safe_input_ancestry(candidate.parent, label="provenance output")
    expected_output_identity = _provenance_output_identity(candidate)

    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{candidate.name}.",
            suffix=".tmp",
            dir=candidate.parent,
        )
    except OSError as error:
        raise ProvenanceError(f"cannot create provenance staging file: {error}") from error

    temporary = Path(temporary_name)
    staged_identity: tuple[int, int, int, int, int, int] | None = None
    try:
        try:
            offset = 0
            while offset < len(raw):
                try:
                    written = os.write(descriptor, raw[offset:])
                except OSError as error:
                    raise ProvenanceError(
                        f"cannot write staged provenance safely: {error}"
                    ) from error
                if written <= 0:
                    raise ProvenanceError("cannot write complete staged provenance")
                offset += written
            try:
                os.fsync(descriptor)
            except OSError as error:
                raise ProvenanceError(
                    f"cannot flush staged provenance safely: {error}"
                ) from error

            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise ProvenanceError("staged provenance changed to a non-regular file")
            if bool(getattr(opened, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE):
                raise ProvenanceError("staged provenance changed to a reparse point")
            if int(getattr(opened, "st_nlink", 1)) != 1:
                raise ProvenanceError("staged provenance became hardlinked")
            if int(opened.st_size) != len(raw):
                raise ProvenanceError("staged provenance size differs from serialized manifest")
            staged_identity = _input_identity(opened)

            try:
                os.lseek(descriptor, 0, os.SEEK_SET)
            except OSError as error:
                raise ProvenanceError(
                    f"cannot seek staged provenance safely: {error}"
                ) from error
            chunks: list[bytes] = []
            total = 0
            while True:
                remaining = len(raw) + 1 - total
                if remaining <= 0:
                    raise ProvenanceError("staged provenance grew during verification")
                try:
                    chunk = os.read(descriptor, min(_CHUNK_SIZE, remaining))
                except OSError as error:
                    raise ProvenanceError(
                        f"cannot read staged provenance safely: {error}"
                    ) from error
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > len(raw):
                    raise ProvenanceError("staged provenance grew during verification")
            if b"".join(chunks) != raw:
                raise ProvenanceError("staged provenance differs from serialized manifest")
            after_read = os.fstat(descriptor)
            if _input_identity(after_read) != staged_identity:
                raise ProvenanceError("staged provenance changed during same-handle verification")
        finally:
            os.close(descriptor)

        _require_safe_input_ancestry(candidate.parent, label="provenance output")
        staged_path_identity = _provenance_output_identity(temporary)
        if (
            staged_identity is None
            or staged_path_identity is None
            or not _path_and_handle_identity_match(staged_path_identity, staged_identity)
        ):
            raise ProvenanceError(
                "staged provenance path changed after same-handle verification"
            )
        if _provenance_output_identity(candidate) != expected_output_identity:
            raise ProvenanceError(
                "provenance output changed while validated bytes were staged"
            )
        try:
            os.replace(temporary, candidate)
        except OSError as error:
            raise ProvenanceError(
                f"cannot atomically replace provenance output: {error}"
            ) from error

        _size, _digest, written = _stable_input_snapshot(
            candidate,
            label="provenance manifest",
            max_bytes=_MAX_PROVENANCE_MANIFEST_BYTES,
            capture_bytes=True,
        )
        if written != raw:
            raise ProvenanceError("written provenance differs from validated serialized manifest")
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


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
    raw = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _write_manifest_atomically(output, raw)
    return manifest


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        _size, _digest, raw = _stable_input_snapshot(
            path,
            label="provenance manifest",
            max_bytes=_MAX_PROVENANCE_MANIFEST_BYTES,
            capture_bytes=True,
        )
        if raw is None:
            raise ProvenanceError("provenance manifest snapshot is unavailable")
        payload = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as error:
        raise ProvenanceError(f"cannot read provenance manifest: invalid UTF-8: {error}") from error
    except json.JSONDecodeError as error:
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

    archive_path = _absolute_without_resolving(archive)
    if artifact.get("name") != archive_path.name:
        raise ProvenanceError(
            f"archive name mismatch: manifest={artifact.get('name')!r} actual={archive_path.name!r}"
        )
    expected_size = artifact.get("size")
    if not isinstance(expected_size, int) or isinstance(expected_size, bool) or expected_size < 0:
        raise ProvenanceError("manifest artifact size is invalid")
    expected_digest = _validate_sha256(
        artifact.get("sha256"),
        "manifest artifact SHA-256",
    )
    actual_size, actual_digest, _raw = _stable_input_snapshot(
        archive_path,
        label="release archive",
    )
    if expected_size != actual_size:
        raise ProvenanceError(
            f"archive size mismatch: manifest={expected_size} actual={actual_size}"
        )
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

    evidence = _absolute_without_resolving(release_evidence)
    if name != evidence.name:
        raise ProvenanceError(
            f"release evidence name mismatch: manifest={name!r} actual={evidence.name!r}"
        )
    actual_size, actual_digest, _raw = _stable_input_snapshot(
        evidence,
        label="release evidence",
        max_bytes=_MAX_RELEASE_EVIDENCE_BYTES,
    )
    if size != actual_size:
        raise ProvenanceError(
            f"release evidence size mismatch: manifest={size} actual={actual_size}"
        )
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