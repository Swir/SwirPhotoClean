"""Performance profiles for scanning without changing detection semantics."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PerformanceProfile:
    """Scanner I/O/scheduler tuning. Detection thresholds remain unchanged."""

    key: str
    hash_chunk_bytes: int
    cooperative_yield_bytes: int


PROFILES = {
    "eco": PerformanceProfile("eco", 256 * 1024, 1 * 1024 * 1024),
    "balanced": PerformanceProfile("balanced", 1024 * 1024, 8 * 1024 * 1024),
    "fast": PerformanceProfile("fast", 4 * 1024 * 1024, 0),
}
DEFAULT_PROFILE = "balanced"


def get_performance_profile(value: str | PerformanceProfile | None = None) -> PerformanceProfile:
    if isinstance(value, PerformanceProfile):
        return value
    key = DEFAULT_PROFILE if value is None else str(value).strip().lower()
    try:
        return PROFILES[key]
    except KeyError as error:
        raise ValueError(f"Unknown performance profile: {value!r}") from error


def performance_settings_path(settings_path=None) -> Path:
    if settings_path is None:
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".config")) / "SwirPhotoClean" / "settings.json"
    else:
        base = Path(settings_path)
    return base.with_name("performance.json")


def load_performance_profile(settings_path=None) -> str:
    path = performance_settings_path(settings_path)
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("performance_profile")
        return value if value in PROFILES else DEFAULT_PROFILE
    except (OSError, ValueError, AttributeError):
        return DEFAULT_PROFILE


def save_performance_profile(settings_path, value: str) -> None:
    profile = get_performance_profile(value)
    path = performance_settings_path(settings_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({"performance_profile": profile.key}, stream)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
