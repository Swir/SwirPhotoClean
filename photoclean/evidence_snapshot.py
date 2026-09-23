"""Immutable snapshot validation for Recycle Bin release evidence.

Release attestation must be derived from the exact report bytes that were
validated. Reading a report once for validation and again for attestation leaves
a time-of-check/time-of-use gap where the file can change between those steps.
This helper snapshots the report bytes first, validates that immutable snapshot
against the live manifest and generated fixture, and returns those same bytes to
the attestation layer for hashing and sanitization.

The source report is itself release-critical input. Snapshot intake therefore
fails closed on links/reparse points, hardlinks, non-regular files, oversized
reports and identity/content metadata changes observed while one file handle is
being read.
"""
from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path

from .diagnostics import RecycleVerificationError
from .recycle_evidence import validate_restore_evidence_report

MAX_EVIDENCE_REPORT_BYTES = 2 * 1024 * 1024
_REPARSE_POINT_ATTRIBUTE = 0x400
_READ_CHUNK_BYTES = 64 * 1024


def _absolute_without_resolving(path: str | os.PathLike) -> Path:
    """Return an absolute path while preserving the final filesystem entry."""
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def _file_identity(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    """Return metadata that must remain stable across one snapshot read."""
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
    """Compare lstat/fstat identity without Windows API representation noise.

    CPython on Windows can expose different ``st_dev`` / creation-time details for
    a path stat versus an already-open CRT handle even when both refer to the same
    file.  The file index (``st_ino``), link count, size and last-write timestamp
    are the stable cross-API fields we require there.  Same-API comparisons before
    and after the read still use the complete identity tuple.
    """
    if os.name != "nt":
        return path_identity == handle_identity

    path_inode = path_identity[1]
    handle_inode = handle_identity[1]
    if path_inode <= 0 or handle_inode <= 0 or path_inode != handle_inode:
        return False
    return path_identity[2:5] == handle_identity[2:5]


def _require_safe_report_entry(path: Path) -> os.stat_result:
    """Inspect a report path without following its final filesystem entry."""
    try:
        info = path.lstat()
    except OSError as error:
        raise RecycleVerificationError(
            f"Cannot safely inspect recycle evidence report: {error}"
        ) from error

    if stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE
    ):
        raise RecycleVerificationError(
            "Recycle evidence report must not be a symlink, junction or reparse point"
        )
    if not stat.S_ISREG(info.st_mode):
        raise RecycleVerificationError("Recycle evidence report must be a regular file")
    if int(getattr(info, "st_nlink", 1)) != 1:
        raise RecycleVerificationError("Recycle evidence report must not be hardlinked")
    if int(info.st_size) > MAX_EVIDENCE_REPORT_BYTES:
        raise RecycleVerificationError(
            "Recycle evidence report is too large to validate safely"
        )
    return info


def _read_stable_report_bytes(report: Path) -> bytes:
    """Read one bounded report handle and reject identity/metadata races."""
    before = _require_safe_report_entry(report)
    before_identity = _file_identity(before)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(report, flags)
    except OSError as error:
        raise RecycleVerificationError(
            f"Cannot open recycle evidence report safely: {error}"
        ) from error

    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise RecycleVerificationError(
                "Recycle evidence report changed to a non-regular file while opening"
            )
        if bool(getattr(opened, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE):
            raise RecycleVerificationError(
                "Recycle evidence report changed to a reparse point while opening"
            )
        if int(getattr(opened, "st_nlink", 1)) != 1:
            raise RecycleVerificationError(
                "Recycle evidence report became hardlinked while opening"
            )
        opened_identity = _file_identity(opened)
        if not _path_and_handle_identity_match(before_identity, opened_identity):
            raise RecycleVerificationError(
                "Recycle evidence report changed while it was being opened"
            )

        chunks: list[bytes] = []
        total = 0
        while True:
            remaining = MAX_EVIDENCE_REPORT_BYTES + 1 - total
            if remaining <= 0:
                raise RecycleVerificationError(
                    "Recycle evidence report is too large to validate safely"
                )
            try:
                chunk = os.read(descriptor, min(_READ_CHUNK_BYTES, remaining))
            except OSError as error:
                raise RecycleVerificationError(
                    f"Cannot read recycle evidence report safely: {error}"
                ) from error
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_EVIDENCE_REPORT_BYTES:
                raise RecycleVerificationError(
                    "Recycle evidence report is too large to validate safely"
                )

        after = os.fstat(descriptor)
        if _file_identity(after) != opened_identity:
            raise RecycleVerificationError(
                "Recycle evidence report changed while snapshot bytes were being read"
            )
    finally:
        os.close(descriptor)

    final = _require_safe_report_entry(report)
    if _file_identity(final) != before_identity:
        raise RecycleVerificationError(
            "Recycle evidence report path changed while snapshot bytes were being read"
        )

    raw = b"".join(chunks)
    if len(raw) != int(before.st_size):
        raise RecycleVerificationError(
            "Recycle evidence report size changed while snapshot bytes were being read"
        )
    return raw


def load_validated_restore_evidence_snapshot(
    report_path: str | Path,
    *,
    manifest: str | Path | None = None,
) -> tuple[object, Path, bytes, dict]:
    """Return one validated report snapshot and the exact bytes that were checked.

    The original report is read through one bounded file descriptor. A temporary
    copy containing those exact bytes is then passed to the authoritative report
    validator while the live manifest/fixture remains authoritative. Downstream
    attestation code must hash and sanitize ``raw``/``payload`` returned here
    rather than re-reading the mutable source path.
    """
    report = _absolute_without_resolving(report_path)
    manifest_path = (
        Path(manifest).expanduser().resolve()
        if manifest is not None
        else report.parent / "recycle-verification.json"
    )

    raw = _read_stable_report_bytes(report)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RecycleVerificationError(
            f"Cannot snapshot recycle evidence report: {error}"
        ) from error
    if not isinstance(payload, dict):
        raise RecycleVerificationError("Recycle evidence report must contain an object")

    try:
        with tempfile.TemporaryDirectory(prefix="swirphotoclean-evidence-") as folder:
            snapshot = Path(folder) / "recycle-evidence-report.json"
            snapshot.write_bytes(raw)
            check, _validated_snapshot = validate_restore_evidence_report(
                snapshot,
                manifest=manifest_path,
            )
    except OSError as error:
        raise RecycleVerificationError(
            f"Cannot validate immutable recycle evidence snapshot: {error}"
        ) from error

    return check, report, raw, payload
