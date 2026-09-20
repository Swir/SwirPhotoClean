"""Read-only scanner and guarded recycle-bin operations. No permanent deletion."""
from __future__ import annotations

from .i18n import tr
from .performance import PerformanceProfile, get_performance_profile

import csv
import hashlib
import os
import stat
import threading
import time
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PIL import Image, ImageOps

EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
MAX_PIXELS = 40_000_000
_EXIF_ORIENTATION_TAG = 274
_EXIF_TRANSFORMED_ORIENTATIONS = frozenset({2, 3, 4, 5, 6, 7, 8})


class Cancelled(Exception):
    pass


class SafetyError(Exception):
    pass


class ScanIssueError(ValueError):
    """Internal scanner exception carrying a stable, language-independent reason."""

    def __init__(self, category: str, message: str):
        self.category = category
        super().__init__(message)


@dataclass(frozen=True)
class ScanIssue:
    """Structured scanner notice kept alongside the legacy human-readable warning."""

    category: str
    message: str
    path: Path | None = None


@dataclass(frozen=True)
class Photo:
    path: Path
    size: int
    modified_ns: int
    device: int
    inode: int
    digest: str
    width: int
    height: int
    dhash: int
    color: bytes


@dataclass(frozen=True)
class Group:
    kind: str
    photos: tuple[Photo, ...]


@dataclass
class ScanResult:
    photos: list[Photo] = field(default_factory=list)
    groups: list[Group] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    cancelled: bool = False
    issues: list[ScanIssue] = field(default_factory=list)


def record_scan_issue(
    result: ScanResult,
    category: str,
    message: str,
    path: Path | None = None,
) -> None:
    """Append one scanner issue without breaking the historical ``warnings`` API."""

    text = str(message)
    result.warnings.append(text)
    result.issues.append(
        ScanIssue(
            category=str(category),
            message=text,
            path=Path(path) if path is not None else None,
        )
    )


def checkpoint(cancel: threading.Event):
    if cancel.is_set():
        raise Cancelled()


def linked(path: Path) -> bool:
    """Skip symlinks, junctions, cloud placeholders and other reparse points."""
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def signature(info):
    return info.st_size, info.st_mtime_ns, info.st_dev, info.st_ino


def sha256(path: Path, cancel: threading.Event, performance_profile: str | PerformanceProfile | None = None) -> str:
    """Hash a file with profile-specific I/O chunks and cooperative yielding."""
    profile = get_performance_profile(performance_profile)
    digest = hashlib.sha256()
    bytes_since_yield = 0
    with path.open("rb") as stream:
        while chunk := stream.read(profile.hash_chunk_bytes):
            checkpoint(cancel)
            digest.update(chunk)
            if profile.cooperative_yield_bytes:
                bytes_since_yield += len(chunk)
                if bytes_since_yield >= profile.cooperative_yield_bytes:
                    # Yield the worker thread without adding an artificial delay.
                    time.sleep(0)
                    bytes_since_yield = 0
                    checkpoint(cancel)
    return digest.hexdigest()


def _exif_orientation(image: Image.Image) -> int:
    """Return a safe EXIF orientation value without forcing a pixel copy."""

    try:
        value = image.getexif().get(_EXIF_ORIENTATION_TAG, 1)
        return int(value) if value is not None else 1
    except (AttributeError, OSError, TypeError, ValueError):
        return 1


def _analysis_rgb(image: Image.Image) -> Image.Image:
    """Return correctly oriented RGB pixels with minimal full-size buffers.

    The old path always created an oriented copy, an RGBA copy, an RGBA white
    background and then a final RGB copy. Most camera photos are already opaque
    RGB with orientation 1, so those allocations were pure overhead. This helper
    keeps the exact same white-matte behavior when alpha/transparency is present,
    while reusing the source/oriented RGB buffer whenever it is safe to do so.
    """

    orientation = _exif_orientation(image)
    oriented = (
        ImageOps.exif_transpose(image)
        if orientation in _EXIF_TRANSFORMED_ORIENTATIONS
        else image
    )

    has_transparency = oriented.mode in {"RGBA", "LA"} or "transparency" in oriented.info
    if has_transparency:
        rgba = oriented.convert("RGBA")
        background = Image.new("RGBA", rgba.size, "white")
        background.alpha_composite(rgba)
        return background.convert("RGB")
    if oriented.mode == "RGB":
        return oriented
    return oriented.convert("RGB")


def read_photo(path: Path, cancel: threading.Event, performance_profile: str | PerformanceProfile | None = None) -> Photo:
    profile = get_performance_profile(performance_profile)
    checkpoint(cancel)
    before = path.stat()
    digest = sha256(path, cancel, profile)
    checkpoint(cancel)
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(path) as source:
            checkpoint(cancel)
            if source.width * source.height > MAX_PIXELS:
                raise ScanIssueError("pixel_limit", tr('obraz przekracza limit 40 megapikseli'))
            if getattr(source, "n_frames", 1) > 1:
                raise ScanIssueError("multi_frame", tr('obraz animowany lub wielostronicowy — pominięty'))
            rgb = _analysis_rgb(source)
            checkpoint(cancel)
            width, height = rgb.size
            gray = rgb.convert("L").resize((9, 8), Image.Resampling.LANCZOS).tobytes()
            checkpoint(cancel)
            bits = 0
            for y in range(8):
                for x in range(8):
                    bits = (bits << 1) | (gray[y * 9 + x] > gray[y * 9 + x + 1])
            # Low-resolution RGB signature prevents flat, different-color images
            # with identical gradient hashes from becoming false matches.
            color = rgb.resize((8, 8), Image.Resampling.LANCZOS).tobytes()
            checkpoint(cancel)
    after = path.stat()
    if signature(before) != signature(after):
        raise ScanIssueError("changed_during_scan", tr('plik zmienił się podczas skanowania'))
    return Photo(path, *signature(after), digest, width, height, bits, color)


class BKTree:
    """Hamming-distance index; identical hashes are stored in one bucket."""
    def __init__(self):
        self.root = None

    def add(self, value, photo):
        if self.root is None:
            self.root = [value, [photo], {}]
            return
        node = self.root
        while True:
            distance = (node[0] ^ value).bit_count()
            if distance == 0:
                node[1].append(photo)
                return
            if distance not in node[2]:
                node[2][distance] = [value, [photo], {}]
                return
            node = node[2][distance]

    def query(self, value, radius, cancel):
        stack = [self.root] if self.root else []
        while stack:
            checkpoint(cancel)
            node = stack.pop()
            distance = (node[0] ^ value).bit_count()
            if distance <= radius:
                yield from node[1]
            stack.extend(child for edge, child in node[2].items()
                         if distance - radius <= edge <= distance + radius)


def similar(a: Photo, b: Photo, threshold: int) -> bool:
    aspect_a, aspect_b = a.width / a.height, b.width / b.height
    if abs(aspect_a - aspect_b) / max(aspect_a, aspect_b) > 0.06:
        return False
    if (a.dhash ^ b.dhash).bit_count() > threshold:
        return False
    error = sum((x - y) ** 2 for x, y in zip(a.color, b.color)) / len(a.color)
    return error <= (14 + threshold * 2) ** 2


def scan(roots, threshold=6, cancel=None, progress=None, include_similar=True, performance_profile="balanced"):
    cancel = cancel or threading.Event()
    progress = progress or (lambda message: None)
    profile = get_performance_profile(performance_profile)
    result = ScanResult()
    seen_paths, seen_inodes = set(), set()
    if not 0 <= threshold <= 16:
        raise ValueError(tr('Próg podobieństwa musi mieścić się w zakresie 0–16.'))
    try:
        for root in roots:
            root = Path(os.path.abspath(root))
            try:
                root_is_dir = root.is_dir()
                root_is_linked = linked(root) if root_is_dir else False
            except PermissionError as error:
                record_scan_issue(result, "access_error", f"{root}: {error}", root)
                continue
            except OSError as error:
                record_scan_issue(result, "root_unavailable", f"{root}: {error}", root)
                continue
            if not root_is_dir or root_is_linked:
                record_scan_issue(
                    result,
                    "root_unavailable",
                    tr('{v0}: folder niedostępny lub dowiązanie', v0=root),
                    root,
                )
                continue

            def walk_error(error):
                category = "access_error" if isinstance(error, PermissionError) else "walk_error"
                filename = getattr(error, "filename", None)
                record_scan_issue(
                    result,
                    category,
                    str(error),
                    Path(filename) if filename else None,
                )

            for folder, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
                checkpoint(cancel)
                # Sort in place to keep deterministic traversal without allocating a
                # second potentially huge list for large flat folders.
                dirs.sort()
                kept = []
                for name in dirs:
                    checkpoint(cancel)
                    try:
                        if not linked(Path(folder) / name):
                            kept.append(name)
                    except OSError as error:
                        category = "access_error" if isinstance(error, PermissionError) else "walk_error"
                        record_scan_issue(result, category, str(error), Path(folder) / name)
                dirs[:] = kept
                files.sort()
                for name in files:
                    checkpoint(cancel)
                    path = Path(folder) / name
                    if path.suffix.lower() not in EXTENSIONS:
                        continue
                    key = os.path.normcase(str(path))
                    if key in seen_paths:
                        continue
                    seen_paths.add(key)
                    try:
                        if linked(path):
                            record_scan_issue(
                                result,
                                "reparse_skipped",
                                tr('{v0}: dowiązanie / plik chmurowy — pominięty', v0=path),
                                path,
                            )
                            continue
                        info = path.stat()
                        inode = (info.st_dev, info.st_ino)
                        if info.st_ino and inode in seen_inodes:
                            record_scan_issue(
                                result,
                                "hardlink_skipped",
                                tr('{v0}: drugie dowiązanie do tego samego pliku — pominięte', v0=path),
                                path,
                            )
                            continue
                        photo = read_photo(path, cancel, profile)
                        seen_inodes.add(inode)
                        result.photos.append(photo)
                        progress(tr('Odczytano {v0} zdjęć • {v1}', v0=len(result.photos), v1=name))
                    except Cancelled:
                        raise
                    except ScanIssueError as error:
                        record_scan_issue(result, error.category, f"{path}: {error}", path)
                    except PermissionError as error:
                        record_scan_issue(result, "access_error", f"{path}: {error}", path)
                    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
                        record_scan_issue(result, "pixel_limit", f"{path}: {error}", path)
                    except (OSError, ValueError) as error:
                        record_scan_issue(result, "image_read_error", f"{path}: {error}", path)
        exact = defaultdict(list)
        for photo in result.photos:
            checkpoint(cancel)
            exact[photo.digest].append(photo)
        result.groups = [Group("exact", tuple(items)) for items in exact.values() if len(items) > 1]
        if include_similar:
            # Each group has a fixed anchor. We never chain A~B~C into A~C.
            tree = BKTree()
            buckets = {}
            for index, items in enumerate(exact.values()):
                checkpoint(cancel)
                photo = items[0]
                progress(tr('Porównywanie zdjęć • {v0}/{v1}', v0=index + 1, v1=len(exact)))
                checkpoint(cancel)
                anchor = next((candidate for candidate in tree.query(photo.dhash, threshold, cancel)
                               if similar(candidate, photo, threshold)), None)
                if anchor is None:
                    tree.add(photo.dhash, photo)
                    buckets[photo.path] = [photo]
                else:
                    buckets[anchor.path].append(photo)
            for representatives in buckets.values():
                checkpoint(cancel)
                if len(representatives) > 1:
                    result.groups.append(Group("similar", tuple(p for rep in representatives for p in exact[rep.digest])))
        return result
    except Cancelled:
        result.cancelled = True
        result.groups.clear()  # incomplete scans never enable disposal
        return result


def verify_photo(photo, cancel):
    try:
        # Validate every ancestor too, in case a folder was swapped for a junction.
        if any(linked(part) for part in (photo.path, *photo.path.parents)):
            raise SafetyError(tr('Dowiązanie w ścieżce: {v0}', v0=photo.path))
        current = photo.path.stat()
        if signature(current) != (photo.size, photo.modified_ns, photo.device, photo.inode):
            raise SafetyError(tr('Plik zmienił się: {v0}', v0=photo.path))
        if sha256(photo.path, cancel) != photo.digest:
            raise SafetyError(tr('Zawartość pliku zmieniła się: {v0}', v0=photo.path))
    except OSError as error:
        raise SafetyError(tr('Plik niedostępny: {v0}: {v1}', v0=photo.path, v1=error)) from error


def recycle_selected(result, selected, cancel=None, recycle=None, progress=None):
    """Validate the whole plan before disposal; recheck each target/keeper at use."""
    if result.cancelled:
        raise SafetyError(tr('Skan został anulowany. Uruchom pełny skan.'))
    cancel = cancel or threading.Event()
    progress = progress or (lambda message: None)
    selected = {Path(p) for p in selected}
    if not selected:
        return [], []
    known = {p.path: p for group in result.groups for p in group.photos}
    if selected - known.keys():
        raise SafetyError(tr('Zaznaczenie zawiera plik spoza wyników.'))
    keepers = {}
    check = {}
    for group in result.groups:
        members = {p.path: p for p in group.photos}
        targets = selected & members.keys()
        if not targets:
            continue
        remaining = [p for p in group.photos if p.path not in selected]
        if not remaining:
            raise SafetyError(tr('Zostaw co najmniej jedno zdjęcie w każdej grupie.'))
        keeper = remaining[0]
        check[keeper.path] = keeper
        for path in targets:
            keepers.setdefault(path, []).append(keeper)
            check[path] = known[path]
    for photo in check.values():
        progress(tr('Sprawdzanie przed przeniesieniem • {v0}', v0=photo.path.name))
        verify_photo(photo, cancel)
    if recycle is None:
        from .recycle import recycle_file
        recycle = recycle_file
    completed, failed = [], []
    for path in sorted(selected):
        try:
            checkpoint(cancel)
            for keeper in keepers[path]:
                verify_photo(keeper, cancel)
            verify_photo(known[path], cancel)
            recycle(str(path))  # never fall back to unlink/remove
            completed.append(path)
            progress(tr('Przeniesiono do kosza • {v0}', v0=path.name))
        except Cancelled:
            failed.append(tr('Operacja przerwana; część plików mogła już trafić do kosza.'))
            break
        except Exception as error:
            failed.append(f"{path}: {error}")
            break  # stop on the first failure, keep remaining files untouched
    return completed, failed


def export_csv(result, destination):
    def safe(value):
        text = str(value)
        return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text
    with Path(destination).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=";")
        writer.writerow([tr('Grupa'), tr('Typ'), tr('Ścieżka'), tr('Bajty'), tr('Szerokość'), tr('Wysokość'), "SHA256"])
        for index, group in enumerate(result.groups, 1):
            for photo in group.photos:
                writer.writerow(map(safe, [index, group.kind, photo.path, photo.size, photo.width, photo.height, photo.digest]))
