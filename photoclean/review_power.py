"""Pure helpers for deterministic, non-destructive review filtering and sorting."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence


SORT_MODES = ("recommended", "original", "name", "size_desc", "resolution_desc")


def _normalized_terms(query: str) -> tuple[str, ...]:
    return tuple(term.casefold() for term in query.split() if term.strip())


def _search_text(photo) -> str:
    path = Path(photo.path)
    return " ".join(
        (
            str(path).casefold(),
            path.name.casefold(),
            path.suffix.casefold(),
            f"{photo.width}x{photo.height}",
            f"{photo.width}×{photo.height}",
            str(photo.size),
        )
    )


def filter_sort_photo_indices(
    photos: Sequence,
    query: str = "",
    sort_mode: str = "recommended",
    recommended_path=None,
) -> tuple[int, ...]:
    """Return original photo indices for the current review view.

    This helper never mutates the source group. Filtering is AND-based across
    whitespace-separated terms and sorting is deterministic. ``recommended``
    only affects presentation order; it never selects or marks a file.
    """
    if sort_mode not in SORT_MODES:
        raise ValueError(f"Unsupported review sort mode: {sort_mode}")

    terms = _normalized_terms(query)
    indexed = [
        (index, photo)
        for index, photo in enumerate(photos)
        if all(term in _search_text(photo) for term in terms)
    ]

    recommended = Path(recommended_path) if recommended_path is not None else None

    def path_key(photo):
        return str(Path(photo.path)).casefold()

    if sort_mode == "original":
        key = lambda item: (item[0],)
    elif sort_mode == "name":
        key = lambda item: (Path(item[1].path).name.casefold(), path_key(item[1]), item[0])
    elif sort_mode == "size_desc":
        key = lambda item: (-item[1].size, Path(item[1].path).name.casefold(), item[0])
    elif sort_mode == "resolution_desc":
        key = lambda item: (
            -(item[1].width * item[1].height),
            -item[1].size,
            Path(item[1].path).name.casefold(),
            item[0],
        )
    else:
        key = lambda item: (
            0 if recommended is not None and Path(item[1].path) == recommended else 1,
            item[0],
        )

    indexed.sort(key=key)
    return tuple(index for index, _photo in indexed)


def move_selection(children: Iterable[str], current: str | None, direction: int) -> str | None:
    """Return the adjacent visible tree item, clamped to the current view."""
    items = tuple(children)
    if not items:
        return None
    step = 1 if direction >= 0 else -1
    if current not in items:
        return items[0] if step > 0 else items[-1]
    position = items.index(current)
    return items[max(0, min(len(items) - 1, position + step))]
