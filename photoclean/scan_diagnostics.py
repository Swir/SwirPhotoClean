"""Structured, read-only scanner diagnostics with legacy-session compatibility.

New scans carry stable, language-independent issue categories alongside the existing
human-readable ``ScanResult.warnings`` contract. Older saved sessions contain only
warning strings, so Diagnostics Center keeps a conservative PL/EN fallback classifier.
Neither path changes matching, review, or cleanup semantics.
"""
from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from pathlib import Path

from .core import ScanResult
from .diagnostics import build_diagnostics_snapshot

SCHEMA_VERSION = 1

CATEGORY_ORDER = (
    "root_unavailable",
    "reparse_skipped",
    "hardlink_skipped",
    "pixel_limit",
    "multi_frame",
    "changed_during_scan",
    "access_error",
    "walk_error",
    "image_read_error",
    "other",
)

_PATTERNS = {
    "root_unavailable": (
        "folder niedostępny lub dowiązanie",
        "folder unavailable or a link",
    ),
    "reparse_skipped": (
        "dowiązanie / plik chmurowy — pominięty",
        "link / cloud placeholder — skipped",
    ),
    "hardlink_skipped": (
        "drugie dowiązanie do tego samego pliku — pominięte",
        "another hard link to the same file — skipped",
    ),
    "pixel_limit": (
        "obraz przekracza limit 40 megapikseli",
        "image exceeds the 40 megapixel limit",
        "decompressionbomb",
    ),
    "multi_frame": (
        "obraz animowany lub wielostronicowy — pominięty",
        "animated or multi-page image — skipped",
    ),
    "changed_during_scan": (
        "plik zmienił się podczas skanowania",
        "file changed during scanning",
    ),
    "access_error": (
        "permissionerror",
        "permission denied",
        "access is denied",
        "odmowa dostępu",
        "winerror 5",
    ),
    "walk_error": (
        "winerror 3",
        "the system cannot find the path specified",
        "system nie może odnaleźć określonej ścieżki",
    ),
}


def classify_scan_warning(warning: str) -> str:
    """Map one human warning to a stable support category.

    Known scanner messages are matched in both supported UI languages. Unknown
    decoder/filesystem messages remain visible and fall back to ``image_read_error``
    when they are path-prefixed, otherwise ``other``. The function never mutates
    scan state and is deliberately conservative rather than guessing aggressively.
    """

    text = str(warning).strip().lower()
    for category in CATEGORY_ORDER:
        for needle in _PATTERNS.get(category, ()):
            if needle in text:
                return category
    # Most image-open/stat failures are emitted as ``<path>: <error>``. Keep them
    # separate from truly unclassified notices while retaining the raw message.
    if ":" in text:
        return "image_read_error"
    return "other"


def summarize_scan_warnings(warnings) -> tuple[tuple[str, int], ...]:
    """Summarize legacy warning strings for old sessions and compatibility callers."""

    counts = Counter(classify_scan_warning(item) for item in warnings)
    return tuple((category, counts[category]) for category in CATEGORY_ORDER if counts[category])


def scan_issue_records(result: ScanResult) -> tuple[tuple[str, str], ...]:
    """Return stable issue categories, preferring scanner-native structured data.

    New scans populate ``ScanResult.issues`` and therefore do not depend on the
    current UI language. Older saved sessions only contain ``warnings``; those
    keep working through the conservative text classifier. If third-party code
    mutates one list without the other, fall back to warnings so no notice is lost.
    """

    issues = getattr(result, "issues", ())
    if issues and len(issues) == len(result.warnings):
        return tuple(
            (
                issue.category if issue.category in CATEGORY_ORDER else "other",
                str(issue.message),
            )
            for issue in issues
        )
    return tuple((classify_scan_warning(warning), str(warning)) for warning in result.warnings)


def summarize_scan_result(result: ScanResult) -> tuple[tuple[str, int], ...]:
    counts = Counter(category for category, _message in scan_issue_records(result))
    return tuple((category, counts[category]) for category in CATEGORY_ORDER if counts[category])


def build_scan_diagnostics_report(result: ScanResult, marked_count: int = 0) -> dict:
    """Build a JSON-serializable diagnostics report without touching photo files."""

    snapshot = build_diagnostics_snapshot(result, marked_count)
    records = scan_issue_records(result)
    issue_counts = dict(summarize_scan_result(result))
    structured = bool(getattr(result, "issues", ())) and len(result.issues) == len(result.warnings)
    return {
        "schema_version": SCHEMA_VERSION,
        "runtime": {
            "platform": snapshot.platform,
            "python": snapshot.python,
            "packaged_exe": snapshot.frozen,
        },
        "scan": {
            "photos": snapshot.photo_count,
            "exact_groups": snapshot.exact_group_count,
            "similar_groups": snapshot.similar_group_count,
            "warnings": snapshot.warning_count,
            "marked_for_recycle_bin": snapshot.marked_count,
            "cancelled": snapshot.cancelled,
            "issue_source": "structured" if structured else "legacy-warning-fallback",
        },
        "issue_counts": issue_counts,
        "issues": [
            {
                "category": category,
                "message": message,
            }
            for category, message in records
        ],
        "privacy_note": (
            "This explicit diagnostics export may contain local file paths embedded "
            "in scanner messages; it never contains photo bytes."
        ),
    }


def write_scan_diagnostics_report(result: ScanResult, destination, marked_count: int = 0) -> Path:
    """Atomically export support diagnostics selected by the user."""

    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(
                build_scan_diagnostics_report(result, marked_count),
                stream,
                ensure_ascii=False,
                indent=2,
            )
            stream.write("\n")
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target