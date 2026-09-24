"""Enhanced Diagnostics Center with categorized scan issues and explicit JSON export."""
from __future__ import annotations

import hashlib
import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import i18n
from .diagnostics import RecycleVerificationError, load_recycle_verification
from .diagnostics_gui import DiagnosticsWindow, diag_tr
from .evidence_io import hardened_read_json_object
from .evidence_snapshot import _read_stable_report_bytes
from .recycle_evidence import (
    REPORT_NAME,
    _require_runtime_safety_contract,
    validate_restore_evidence_report,
)
from .release_attestation import (
    ATTESTATION_NAME,
    PackagedAttestationError,
    validate_packaged_attestation,
)
from .scan_diagnostics import summarize_scan_result, write_scan_diagnostics_report


PLUS_EN = {
    "Problemy według przyczyny": "Issues by reason",
    "Powód": "Reason",
    "Liczba": "Count",
    "Brak pominięć i błędów w bieżącym skanie.": "No skips or errors in the current scan.",
    "Surowe komunikaty": "Raw messages",
    "Eksport diagnostyki JSON…": "Export diagnostics JSON…",
    "Eksport diagnostyki": "Diagnostics export",
    "Zapisano raport diagnostyczny:\n{v0}\n\nUwaga: raport może zawierać lokalne ścieżki plików, ale nie zawiera danych obrazu.": "Diagnostics report saved:\n{v0}\n\nNote: the report may contain local file paths, but it never contains image data.",
    "Nie udało się zapisać raportu diagnostycznego": "Could not save diagnostics report",
    "Folder niedostępny / dowiązanie": "Unavailable folder / link",
    "Dowiązanie / plik chmurowy": "Link / cloud placeholder",
    "Drugie dowiązanie twarde": "Duplicate hard link",
    "Limit 40 MP / bezpieczeństwo obrazu": "40 MP / image safety limit",
    "Animowany / wielostronicowy obraz": "Animated / multi-page image",
    "Plik zmieniony podczas skanu": "File changed during scan",
    "Błąd dostępu / uprawnień": "Access / permission error",
    "Błąd przechodzenia folderu": "Folder traversal error",
    "Błąd odczytu / dekodowania obrazu": "Image read / decode error",
    "Inny komunikat": "Other notice",
}

CATEGORY_LABELS = {
    "root_unavailable": "Folder niedostępny / dowiązanie",
    "reparse_skipped": "Dowiązanie / plik chmurowy",
    "hardlink_skipped": "Drugie dowiązanie twarde",
    "pixel_limit": "Limit 40 MP / bezpieczeństwo obrazu",
    "multi_frame": "Animowany / wielostronicowy obraz",
    "changed_during_scan": "Plik zmieniony podczas skanu",
    "access_error": "Błąd dostępu / uprawnień",
    "walk_error": "Błąd przechodzenia folderu",
    "image_read_error": "Błąd odczytu / dekodowania obrazu",
    "other": "Inny komunikat",
}


def plus_tr(message, **values):
    text = PLUS_EN.get(message, message) if i18n.language == "en" else message
    return text.format(**values) if values else text


def category_label(category: str) -> str:
    return plus_tr(CATEGORY_LABELS.get(category, "Inny komunikat"))


def _absolute_without_resolving(path: str | Path) -> Path:
    """Return an absolute path while preserving symlink/junction ancestry."""
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def validate_resumed_release_attestation(check, report_path, attestation_path) -> Path:
    """Validate persisted RELEASE_EVIDENCE against the exact resumed report bytes.

    Resume is release-critical too: never hash the report or parse the attestation
    through ordinary path reads. Both inputs are consumed through the same bounded,
    identity-bound readers used by release qualification so symlinks, hardlinks,
    reparse ancestry and path swaps fail closed instead of being silently followed.
    """

    report = _absolute_without_resolving(report_path)
    attestation = _absolute_without_resolving(attestation_path)
    try:
        report_bytes = _read_stable_report_bytes(report)
        payload = hardened_read_json_object(
            attestation,
            max_bytes=256 * 1024,
            label="RELEASE_EVIDENCE.json",
        )
    except RecycleVerificationError as error:
        raise PackagedAttestationError(
            f"cannot safely read persisted release evidence: {error}"
        ) from error

    validated = validate_packaged_attestation(payload)
    expected = {
        "session_id": check.session_id,
        "fixture_sha256": check.digest,
        "manifest_fingerprint": check.manifest_fingerprint,
        "evidence_report_sha256": hashlib.sha256(report_bytes).hexdigest(),
    }
    for field, value in expected.items():
        if validated.get(field) != value:
            raise PackagedAttestationError(
                f"persisted release evidence does not match resumed {field}"
            )
    return attestation


class EnhancedDiagnosticsWindow(DiagnosticsWindow):
    """Diagnostics view that explains skips/errors without altering scan state."""

    def resume_check(self):
        """Resume one qualified session transactionally, then recover its attestation.

        The base window intentionally keeps the previous valid session when a new
        manifest cannot be loaded. Enhanced Diagnostics must not mistake that old
        state for a successful resume and adopt its RELEASE_EVIDENCE after a failed
        file selection. Validate the newly chosen manifest/report completely before
        mutating the active UI state, then recover attestation only for that session.
        """

        manifest = filedialog.askopenfilename(
            title=diag_tr("Wybierz manifest testu Kosza"),
            parent=self.window,
            filetypes=(("JSON", "*.json"), ("All files", "*.*")),
        )
        if not manifest:
            return

        try:
            check = load_recycle_verification(Path(manifest).expanduser().resolve())
            _require_runtime_safety_contract(check)
            report = None
            if check.stage == "restored-verified":
                candidate_report = check.folder / REPORT_NAME
                if candidate_report.is_file():
                    validate_restore_evidence_report(
                        candidate_report,
                        manifest=check.manifest,
                    )
                    report = candidate_report
        except (OSError, RecycleVerificationError) as error:
            messagebox.showerror(
                diag_tr("Nie udało się wykonać testu Kosza"),
                str(error),
                parent=self.window,
            )
            return

        self._apply_check_state(check, report)
        if report is None:
            return

        candidate = check.folder / ATTESTATION_NAME
        if not candidate.is_file():
            return
        try:
            validated = validate_resumed_release_attestation(
                check,
                report,
                candidate,
            )
        except (OSError, PackagedAttestationError) as error:
            messagebox.showerror(
                diag_tr("Nie udało się utworzyć dowodu wydania"),
                str(error),
                parent=self.window,
            )
            return

        self.release_attestation = validated
        self.attest_button.configure(state="disabled")
        self.copy_button.configure(
            text=diag_tr("Kopiuj ścieżkę RELEASE_EVIDENCE"),
            state="normal",
        )
        self.recycle_status.set(
            diag_tr("RELEASE_EVIDENCE gotowy: {v0}", v0=validated)
        )

    def _build_warnings(self, parent):
        self.issue_summary = summarize_scan_result(self.app.result)

        toolbar = ttk.Frame(parent)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Label(toolbar, text=plus_tr("Problemy według przyczyny")).pack(side="left")
        ttk.Button(
            toolbar,
            text=plus_tr("Eksport diagnostyki JSON…"),
            command=self.export_scan_diagnostics,
        ).pack(side="right")

        if self.issue_summary:
            summary = ttk.Treeview(
                parent,
                columns=("reason", "count"),
                show="headings",
                height=min(6, len(self.issue_summary)),
                selectmode="none",
            )
            summary.heading("reason", text=plus_tr("Powód"))
            summary.heading("count", text=plus_tr("Liczba"))
            summary.column("reason", width=420, minwidth=220, stretch=True)
            summary.column("count", width=90, minwidth=70, stretch=False, anchor="center")
            for index, (category, count) in enumerate(self.issue_summary):
                summary.insert("", "end", iid=f"issue:{index}", values=(category_label(category), count))
            summary.pack(fill="x", pady=(0, 10))
        else:
            ttk.Label(parent, text=plus_tr("Brak pominięć i błędów w bieżącym skanie.")).pack(anchor="w", pady=(0, 10))

        ttk.Label(parent, text=plus_tr("Surowe komunikaty")).pack(anchor="w", pady=(0, 4))
        if not self.app.result.warnings:
            return
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        text = tk.Text(frame, wrap="word", height=13, bg="#10182a", fg="#eef4ff", relief="flat")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        text.insert("1.0", "\n".join(self.app.result.warnings))
        text.configure(state="disabled")

    def export_scan_diagnostics(self):
        target = filedialog.asksaveasfilename(
            title=plus_tr("Eksport diagnostyki"),
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            parent=self.window,
        )
        if not target:
            return
        try:
            written = write_scan_diagnostics_report(
                self.app.result,
                target,
                marked_count=len(self.app.marked),
            )
        except OSError as error:
            messagebox.showerror(
                plus_tr("Nie udało się zapisać raportu diagnostycznego"),
                str(error),
                parent=self.window,
            )
            return
        messagebox.showinfo(
            plus_tr("Eksport diagnostyki"),
            plus_tr(
                "Zapisano raport diagnostyczny:\n{v0}\n\nUwaga: raport może zawierać lokalne ścieżki plików, ale nie zawiera danych obrazu.",
                v0=written,
            ),
            parent=self.window,
        )
