"""Shared, read-only EXIF metadata helpers used by review features.

The parser prefers the standard nested Exif IFD for capture-time tags and keeps
compatibility with older/top-level layouts. It never guesses capture evidence
from filenames, directory names, or filesystem timestamps.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import ExifTags, Image

_EXIF_IFD = ExifTags.IFD.Exif
_DATETIME_TAGS = (
    (36867, 37521, "DateTimeOriginal"),
    (36868, 37522, "DateTimeDigitized"),
    (306, 37520, "DateTime"),
)
_EXIF_FORMAT = "%Y:%m:%d %H:%M:%S"
_MAKE_TAG = 271
_MODEL_TAG = 272
_MAX_METADATA_TEXT = 200


@dataclass(frozen=True)
class ExifMetadata:
    """Small explainable subset of embedded metadata used by the application."""

    captured_at: datetime | None
    capture_source: str | None
    camera_make: str | None
    camera_model: str | None

    @property
    def device_label(self) -> str | None:
        make = self.camera_make
        model = self.camera_model
        if make and model:
            if model.casefold().startswith(make.casefold()):
                return model
            return f"{make} {model}"
        return model or make


def clean_exif_text(value) -> str | None:
    """Normalize bounded EXIF text without interpreting missing/garbled values."""

    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    text = " ".join(str(value).replace("\x00", " ").split()).strip()
    if not text:
        return None
    return text[:_MAX_METADATA_TEXT]


def parse_exif_datetime(value, subsecond=None) -> datetime | None:
    """Parse the standard EXIF timestamp plus an optional fractional second."""

    text = clean_exif_text(value)
    if not text or len(text) < 19:
        return None
    try:
        parsed = datetime.strptime(text[:19], _EXIF_FORMAT)
    except ValueError:
        return None

    fraction = clean_exif_text(subsecond)
    if fraction:
        digits = []
        for character in fraction:
            if not character.isdigit():
                break
            digits.append(character)
        if digits:
            microsecond = int(("".join(digits) + "000000")[:6])
            parsed = parsed.replace(microsecond=microsecond)
    return parsed


def _nested_exif_ifd(exif) -> dict:
    """Return the standard nested Exif IFD, tolerating malformed metadata."""

    try:
        nested = exif.get_ifd(_EXIF_IFD)
    except (AttributeError, KeyError, OSError, TypeError, ValueError):
        return {}
    if not nested:
        return {}
    try:
        return dict(nested)
    except (TypeError, ValueError):
        return {}


def _first_value(primary: dict, secondary, tag: int):
    value = primary.get(tag)
    return value if value is not None else secondary.get(tag)


def metadata_from_exif(exif) -> ExifMetadata:
    """Extract capture time and camera identity from a Pillow Exif object."""

    nested = _nested_exif_ifd(exif)
    captured_at = None
    capture_source = None

    for tag, subsecond_tag, source in _DATETIME_TAGS:
        # DateTimeOriginal / DateTimeDigitized normally live in the nested Exif
        # IFD. DateTime commonly lives in IFD0. Supporting both layouts keeps
        # compatibility with files written by older tools without weakening the
        # evidence rule.
        if tag == 306:
            value = exif.get(tag)
            if value is None:
                value = nested.get(tag)
            subsecond = exif.get(subsecond_tag)
            if subsecond is None:
                subsecond = nested.get(subsecond_tag)
        else:
            value = _first_value(nested, exif, tag)
            subsecond = _first_value(nested, exif, subsecond_tag)
        captured_at = parse_exif_datetime(value, subsecond)
        if captured_at is not None:
            capture_source = source
            break

    return ExifMetadata(
        captured_at=captured_at,
        capture_source=capture_source,
        camera_make=clean_exif_text(exif.get(_MAKE_TAG)),
        camera_model=clean_exif_text(exif.get(_MODEL_TAG)),
    )


def read_exif_metadata(path: Path) -> ExifMetadata:
    """Read the metadata subset without decoding the full image pixel payload."""

    with Image.open(path) as image:
        return metadata_from_exif(image.getexif())
