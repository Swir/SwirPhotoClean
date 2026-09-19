"""Final fullscreen review layer with explainable Smart Keep and EXIF context.

This module extends the existing synchronized Fullscreen Compare + Difference View
without changing cleanup state. Quality, Smart Keep and EXIF metadata are review
signals only: no file is marked, moved or rewritten from this window.
"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox

from . import i18n
from .core import Group
from .fullscreen_plus_gui import (
    IntegratedFullscreenCompare,
    PhotoCleanApp as FullscreenPhotoCleanApp,
)
from .library import read_library_metadata
from .pro_gui import session_tr
from .quality import assess_photo, recommend_keeper_with_quality


INSIGHT_EN = {
    "Jakość {v0}/100 • ostrość {v1} • ekspozycja {v2}": (
        "Quality {v0}/100 • sharpness {v1} • exposure {v2}"
    ),
    "Jakość: niedostępna": "Quality: unavailable",
    "Aparat: {v0}": "Camera: {v0}",
    "Wykonano: {v0} ({v1})": "Captured: {v0} ({v1})",
    "EXIF: brak czasu wykonania i danych aparatu": "EXIF: no capture time or camera metadata",
    "Smart Keep: kopie są identyczne bajtowo — zachowaj dowolną jedną kopię": (
        "Smart Keep: byte-identical copies — keep any one copy"
    ),
    "Smart Keep: sugerowana kopia • wynik {v0}/100 • pewność {v1}": (
        "Smart Keep: suggested copy • score {v0}/100 • confidence {v1}"
    ),
    "Smart Keep: alternatywa • porównaj ręcznie przed decyzją": (
        "Smart Keep: alternative • review manually before deciding"
    ),
}

_CONFIDENCE_PL = {
    "high": "wysoka",
    "medium": "średnia",
    "low": "niska",
    "equivalent": "równoważna",
}


def insight_tr(message, **values):
    text = INSIGHT_EN.get(message, message) if i18n.language == "en" else message
    return text.format(**values) if values else text


def _confidence_label(value: str) -> str:
    if i18n.language == "en":
        return value
    return _CONFIDENCE_PL.get(value, value)


class InsightFullscreenCompare(IntegratedFullscreenCompare):
    """Fullscreen comparison enriched with read-only quality and EXIF evidence."""

    def __init__(self, parent, photos, group_kind="similar"):
        photos = tuple(photos)
        if len(photos) != 2:
            raise ValueError(
                session_tr(
                    "Zaznacz dwa zdjęcia w jednej grupie, aby otworzyć porównanie pełnoekranowe."
                )
            )
        self.group_kind = group_kind if group_kind in {"exact", "similar"} else "similar"
        self.quality_by_photo = {photo: assess_photo(photo) for photo in photos}
        self.metadata_by_photo = {}
        for photo in photos:
            try:
                self.metadata_by_photo[photo] = read_library_metadata(photo)
            except (OSError, ValueError):
                self.metadata_by_photo[photo] = None
        self.keeper_recommendation = recommend_keeper_with_quality(
            Group(self.group_kind, photos)
        )
        super().__init__(parent, photos)

    def _quality_line(self, photo):
        assessment = self.quality_by_photo[photo]
        if not assessment.available:
            return insight_tr("Jakość: niedostępna")
        return insight_tr(
            "Jakość {v0}/100 • ostrość {v1} • ekspozycja {v2}",
            v0=f"{assessment.overall_score:.1f}",
            v1=f"{assessment.sharpness_score:.1f}",
            v2=f"{assessment.exposure_score:.1f}",
        )

    def _metadata_lines(self, photo):
        metadata = self.metadata_by_photo.get(photo)
        if metadata is None:
            return (insight_tr("EXIF: brak czasu wykonania i danych aparatu"),)

        lines = []
        if metadata.device_label:
            lines.append(insight_tr("Aparat: {v0}", v0=metadata.device_label))
        if metadata.captured_at is not None:
            lines.append(
                insight_tr(
                    "Wykonano: {v0} ({v1})",
                    v0=metadata.captured_at.strftime("%Y-%m-%d %H:%M:%S"),
                    v1=metadata.capture_source or "EXIF",
                )
            )
        if not lines:
            lines.append(insight_tr("EXIF: brak czasu wykonania i danych aparatu"))
        return tuple(lines)

    def _smart_keep_line(self, photo):
        recommendation = self.keeper_recommendation
        if recommendation.equivalent_exact:
            return insight_tr(
                "Smart Keep: kopie są identyczne bajtowo — zachowaj dowolną jedną kopię"
            )
        if recommendation.photo == photo:
            return insight_tr(
                "Smart Keep: sugerowana kopia • wynik {v0}/100 • pewność {v1}",
                v0=f"{recommendation.score:.1f}",
                v1=_confidence_label(recommendation.confidence),
            )
        return insight_tr("Smart Keep: alternatywa • porównaj ręcznie przed decyzją")

    def _photo_detail(self, photo):
        base = IntegratedFullscreenCompare._photo_detail(photo)
        lines = [base, self._quality_line(photo)]
        lines.extend(self._metadata_lines(photo))
        lines.append(self._smart_keep_line(photo))
        return "\n".join(lines)


class PhotoCleanApp(FullscreenPhotoCleanApp):
    """Final app wiring the explainable fullscreen insight layer."""

    def open_fullscreen_compare(self):
        if self.busy:
            return
        photos = self._selected_compare_photos()
        if len(photos) != 2:
            messagebox.showinfo(
                session_tr("Wybierz dwa zdjęcia"),
                session_tr(
                    "Zaznacz dwa zdjęcia w jednej grupie, aby otworzyć porównanie pełnoekranowe."
                ),
            )
            return
        existing = getattr(self, "compare_view", None)
        if existing is not None and existing.window.winfo_exists():
            existing.window.destroy()
        group_kind = self.active_group.kind if self.active_group is not None else "similar"
        try:
            self.compare_view = InsightFullscreenCompare(
                self.root,
                photos,
                group_kind=group_kind,
            )
        except (OSError, ValueError) as error:
            messagebox.showerror(session_tr("Podgląd niedostępny"), str(error))


def main():
    if os.name == "nt":
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    PhotoCleanApp(root)
    root.mainloop()
