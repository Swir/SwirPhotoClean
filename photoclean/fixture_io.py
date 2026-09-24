"""Stable, fail-closed reads for generated Recycle Bin verification files.

The Windows Recycle Bin / Restore acceptance fixture is release-critical. The
manifest can prove which bytes are expected only when KEEP-ME.png and
RECYCLE-ME.png are themselves read from one verified filesystem handle. This
module replaces the legacy path-based size/hash checks before runtime dispatch.
"""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from . import diagnostics
from .evidence_io import (
    _READ_CHUNK_BYTES,
    _REPARSE_POINT_ATTRIBUTE,
    _absolute_without_resolving,
    _file_identity,
    _path_and_handle_identity_match,
    _require_safe_directory_ancestry,
    _safe_input_info,
)

_MAX_FIXTURE_BYTES = 4 * 1024 * 1024


def _stable_fixture_sha256(
    path: str | os.PathLike,
    *,
    label: str,
    expected_size: int = 0,
) -> str:
    """Hash one fixture handle while rejecting links, races and path swaps."""
    source = _absolute_without_resolving(path)
    if expected_size < 0 or expected_size > _MAX_FIXTURE_BYTES:
        raise diagnostics.RecycleVerificationError(
            f"{label} size exceeds the generated-fixture safety bound"
        )

    _require_safe_directory_ancestry(source.parent)
    before = _safe_input_info(
        source,
        max_bytes=_MAX_FIXTURE_BYTES,
        label=label,
    )
    if expected_size and int(before.st_size) != expected_size:
        raise diagnostics.RecycleVerificationError(f"{label} size changed: {source}")
    before_identity = _file_identity(before)

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(source, flags)
    except OSError as error:
        raise diagnostics.RecycleVerificationError(
            f"Cannot open {label} safely: {error}"
        ) from error

    digest = hashlib.sha256()
    total = 0
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise diagnostics.RecycleVerificationError(
                f"{label} changed to a non-regular file while opening"
            )
        if bool(getattr(opened, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE):
            raise diagnostics.RecycleVerificationError(
                f"{label} changed to a reparse point while opening"
            )
        if int(getattr(opened, "st_nlink", 1)) != 1:
            raise diagnostics.RecycleVerificationError(
                f"{label} became hardlinked while opening"
            )
        opened_identity = _file_identity(opened)
        if not _path_and_handle_identity_match(before_identity, opened_identity):
            raise diagnostics.RecycleVerificationError(
                f"{label} changed while it was being opened"
            )

        while True:
            remaining = _MAX_FIXTURE_BYTES + 1 - total
            if remaining <= 0:
                raise diagnostics.RecycleVerificationError(
                    f"{label} is too large to validate safely"
                )
            try:
                chunk = os.read(descriptor, min(_READ_CHUNK_BYTES, remaining))
            except OSError as error:
                raise diagnostics.RecycleVerificationError(
                    f"Cannot read {label} safely: {error}"
                ) from error
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
            if total > _MAX_FIXTURE_BYTES:
                raise diagnostics.RecycleVerificationError(
                    f"{label} is too large to validate safely"
                )

        after = os.fstat(descriptor)
        if _file_identity(after) != opened_identity:
            raise diagnostics.RecycleVerificationError(
                f"{label} changed while it was being read"
            )
    finally:
        os.close(descriptor)

    _require_safe_directory_ancestry(source.parent)
    final = _safe_input_info(
        source,
        max_bytes=_MAX_FIXTURE_BYTES,
        label=label,
    )
    if _file_identity(final) != before_identity:
        raise diagnostics.RecycleVerificationError(
            f"{label} path changed while it was being read"
        )
    if total != int(before.st_size):
        raise diagnostics.RecycleVerificationError(
            f"{label} size changed while it was being read"
        )
    return digest.hexdigest()


def hardened_require_expected_file(
    path: Path,
    digest: str,
    label: str,
    expected_size: int = 0,
) -> None:
    """Require the exact generated fixture bytes from one stable file handle."""
    actual = _stable_fixture_sha256(
        path,
        label=label,
        expected_size=expected_size,
    )
    if actual != digest:
        raise diagnostics.RecycleVerificationError(f"{label} content changed: {path}")


def hardened_matches_expected_file(
    path: Path,
    digest: str,
    expected_size: int,
) -> tuple[bool, str | None]:
    """Read-only inspection adapter preserving the existing result contract."""
    source = _absolute_without_resolving(path)
    try:
        source.lstat()
    except FileNotFoundError:
        return False, "missing"
    except OSError as error:
        return False, str(error)

    try:
        hardened_require_expected_file(source, digest, "Generated verification file", expected_size)
    except diagnostics.RecycleVerificationError as error:
        return False, str(error)
    return True, None


def install_hardened_fixture_io() -> None:
    """Bind generated-fixture validation before any evidence workflow executes."""
    diagnostics._require_expected_file = hardened_require_expected_file
    diagnostics._matches_expected_file = hardened_matches_expected_file
