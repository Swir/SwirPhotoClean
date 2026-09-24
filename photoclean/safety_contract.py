"""Bind qualified Windows evidence to the exact shipped Python runtime contract.

The contract covers the complete application runtime plus the release/build path
that produces and validates the Windows package. A physical move/Restore
verification is valid for a qualified release only while this contract stays
unchanged. Documentation and acceptance bookkeeping stay outside the digest so
they can record already-observed evidence without forcing another physical test.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

SCHEMA_VERSION = 1
KIND = "swir-photoclean-release-safety-contract"
ASSET_NAME = "safety-contract.json"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")

# Keep the complete shipped Python runtime explicit and deterministic. Tests assert
# that every top-level photoclean/*.py module is listed here, so adding a runtime
# module cannot silently escape physical Windows evidence invalidation.
SAFETY_CONTRACT_FILES = (
    ".github/workflows/windows.yml",
    "requirements.txt",
    "requirements-build.txt",
    "run.py",
    "photoclean/__init__.py",
    "photoclean/bad_shots.py",
    "photoclean/bad_shots_gui.py",
    "photoclean/burst.py",
    "photoclean/burst_gui.py",
    "photoclean/classification.py",
    "photoclean/classification_gui.py",
    "photoclean/cleanup_history.py",
    "photoclean/cleanup_history_gui.py",
    "photoclean/compare_insights_gui.py",
    "photoclean/core.py",
    "photoclean/diagnostics.py",
    "photoclean/diagnostics_gui.py",
    "photoclean/diagnostics_plus_gui.py",
    "photoclean/difference.py",
    "photoclean/difference_gui.py",
    "photoclean/evidence_io.py",
    "photoclean/evidence_snapshot.py",
    "photoclean/exif_metadata.py",
    "photoclean/fixture_io.py",
    "photoclean/folder_health_app.py",
    "photoclean/folder_health_gui.py",
    "photoclean/fullscreen_plus_gui.py",
    "photoclean/gui.py",
    "photoclean/i18n.py",
    "photoclean/insights.py",
    "photoclean/library.py",
    "photoclean/library_gui.py",
    "photoclean/modern_theme.py",
    "photoclean/performance.py",
    "photoclean/performance_gui.py",
    "photoclean/pro_gui.py",
    "photoclean/quality.py",
    "photoclean/recycle.py",
    "photoclean/recycle_evidence.py",
    "photoclean/recycle_review_cli.py",
    "photoclean/release_attestation.py",
    "photoclean/release_evidence_cli.py",
    "photoclean/review_power.py",
    "photoclean/review_power_gui.py",
    "photoclean/safe_mode_gui.py",
    "photoclean/safety_contract.py",
    "photoclean/scan_diagnostics.py",
    "photoclean/selftest.py",
    "photoclean/selftest_performance.py",
    "photoclean/session.py",
    "photoclean/space_hunter.py",
    "photoclean/space_hunter_gui.py",
    "photoclean/storage.py",
    "photoclean/windows_ui.py",
    "tools/release_evidence.py",
    "tools/release_gate.py",
    "tools/release_provenance.py",
    "tools/safety_contract.py",
)


class SafetyContractError(ValueError):
    """The release-safety contract is missing, stale or malformed."""


def _canonical_bytes(payload: dict) -> bytes:
    normalized = dict(payload)
    normalized.pop("sha256", None)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _contract_digest(payload: dict) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def build_source_safety_contract(root: str | Path | None = None) -> dict:
    """Hash the exact runtime/release source set from a repository checkout."""
    repository = (
        Path(root).expanduser().resolve()
        if root is not None
        else Path(__file__).resolve().parents[1]
    )
    files = []
    for relative in SAFETY_CONTRACT_FILES:
        path = repository / relative
        try:
            raw = path.read_bytes()
        except OSError as error:
            raise SafetyContractError(
                f"cannot read safety-contract file {relative}: {error}"
            ) from error
        files.append(
            {
                "path": relative,
                "size": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "files": files,
    }
    payload["sha256"] = _contract_digest(payload)
    return payload


def validate_safety_contract(payload: object) -> dict:
    """Validate a generated contract without needing repository source files."""
    if not isinstance(payload, dict):
        raise SafetyContractError("safety contract must contain a JSON object")
    if set(payload) != {"schema_version", "kind", "files", "sha256"}:
        raise SafetyContractError(
            "safety contract contains missing or unsupported fields"
        )
    if payload["schema_version"] != SCHEMA_VERSION:
        raise SafetyContractError("unsupported safety-contract schema version")
    if payload["kind"] != KIND:
        raise SafetyContractError(f"safety contract kind must be {KIND!r}")

    files = payload["files"]
    if not isinstance(files, list):
        raise SafetyContractError("safety contract files must be a list")
    expected_paths = list(SAFETY_CONTRACT_FILES)
    observed_paths = []
    for item in files:
        if not isinstance(item, dict) or set(item) != {"path", "size", "sha256"}:
            raise SafetyContractError("invalid safety-contract file entry")
        relative = item["path"]
        if not isinstance(relative, str):
            raise SafetyContractError("safety-contract path must be text")
        if not isinstance(item["size"], int) or isinstance(item["size"], bool) or item["size"] < 0:
            raise SafetyContractError(f"invalid safety-contract size for {relative}")
        digest = item["sha256"]
        if not isinstance(digest, str) or not _HEX64.fullmatch(digest):
            raise SafetyContractError(f"invalid safety-contract SHA-256 for {relative}")
        observed_paths.append(relative)
    if observed_paths != expected_paths:
        raise SafetyContractError("safety contract file set/order does not match the required contract")

    digest = payload["sha256"]
    if not isinstance(digest, str) or not _HEX64.fullmatch(digest):
        raise SafetyContractError("invalid safety-contract digest")
    if digest != _contract_digest(payload):
        raise SafetyContractError("safety-contract digest mismatch")
    return dict(payload)


def validate_source_safety_contract(payload: object, root: str | Path | None = None) -> dict:
    """Require a generated contract to match the current source checkout exactly."""
    validated = validate_safety_contract(payload)
    current = build_source_safety_contract(root)
    if validated != current:
        raise SafetyContractError(
            "safety contract is stale; regenerate it from the exact current source"
        )
    return validated


def source_safety_contract_sha256(root: str | Path | None = None) -> str:
    return build_source_safety_contract(root)["sha256"]


def runtime_safety_contract_path() -> Path:
    """Return the bundled contract path for a frozen PyInstaller application."""
    if not getattr(sys, "frozen", False):
        raise SafetyContractError("runtime safety-contract asset is only used by a frozen package")
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return bundle_root / "assets" / ASSET_NAME


def runtime_safety_contract() -> dict:
    """Return the exact source contract (source) or bundled build contract (EXE)."""
    if not getattr(sys, "frozen", False):
        return build_source_safety_contract()
    path = runtime_safety_contract_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SafetyContractError(f"cannot read bundled safety contract: {error}") from error
    return validate_safety_contract(payload)


def runtime_safety_contract_sha256() -> str:
    return runtime_safety_contract()["sha256"]
