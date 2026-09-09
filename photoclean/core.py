"""Read-only scanner and guarded recycle-bin operations. No permanent deletion."""
from __future__ import annotations

import csv
import hashlib
import os
import stat
import threading
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PIL import Image, ImageOps

EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
MAX_PIXELS = 40_000_000


class Cancelled(Exception):
    pass


class SafetyError(Exception):
    pass


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
    color: tuple[float, ...]


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


def checkpoint(cancel: threading.Event):
    if cancel.is_set():
        raise Cancelled()


def linked(path: Path) -> bool:
    """Skip symlinks, junctions, cloud placeholders and other reparse points."""
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def signature(info):
    return info.st_size, info.st_mtime_ns, info.st_dev, info.st_ino


def sha256(path: Path, cancel: threading.Event) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            checkpoint(cancel)
            digest.update(chunk)
    return digest.hexdigest()


def read_photo(path: Path, cancel: threading.Event) -> Photo:
    checkpoint(cancel)
    before = path.stat()
    digest = sha256(path, cancel)
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(path) as source:
            if source.width * source.height > MAX_PIXELS:
                raise ValueError("obraz przekracza limit 40 megapikseli")
            if getattr(source, "n_frames", 1) > 1:
                raise ValueError("obraz animowany lub wielostronicowy — pominięty")
            im = ImageOps.exif_transpose(source).convert("RGBA")
            background = Image.new("RGBA", im.size, "white")
            background.alpha_composite(im)
            rgb = background.convert("RGB")
            width, height = rgb.size
            gray = list(rgb.convert("L").resize((9, 8), Image.Resampling.LANCZOS).get_flattened_data())
            bits = 0
            for y in range(8):
                for x in range(8):
                    bits = (bits << 1) | (gray[y * 9 + x] > gray[y * 9 + x + 1])
            # Low-resolution RGB signature prevents flat, different-color images
            # with identical gradient hashes from becoming false matches.
            color = tuple(rgb.resize((8, 8), Image.Resampling.LANCZOS).get_flattened_data())
            color = tuple(float(c) for pixel in color for c in pixel)
    after = path.stat()
    if signature(before) != signature(after):
        raise ValueError("plik zmienił się podczas skanowania")
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


def scan(roots, threshold=6, cancel=None, progress=None, include_similar=True):
    cancel = cancel or threading.Event()
    progress = progress or (lambda message: None)
    result = ScanResult()
    seen_paths, seen_inodes = set(), set()
    if not 0 <= threshold <= 16:
        raise ValueError("Próg podobieństwa musi mieścić się w zakresie 0–16.")
    try:
        for root in roots:
            root = Path(os.path.abspath(root))
            if not root.is_dir() or linked(root):
                result.warnings.append(f"{root}: folder niedostępny lub dowiązanie")
                continue
            def walk_error(error):
                result.warnings.append(str(error))
            for folder, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
                checkpoint(cancel)
                kept = []
                for name in sorted(dirs):
                    try:
                        if not linked(Path(folder) / name):
                            kept.append(name)
                    except OSError as error:
                        result.warnings.append(str(error))
                dirs[:] = kept
                for name in sorted(files):
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
                            result.warnings.append(f"{path}: dowiązanie / plik chmurowy — pominięty")
                            continue
                        info = path.stat()
                        inode = (info.st_dev, info.st_ino)
                        if info.st_ino and inode in seen_inodes:
                            result.warnings.append(f"{path}: drugie dowiązanie do tego samego pliku — pominięte")
                            continue
                        photo = read_photo(path, cancel)
                        seen_inodes.add(inode)
                        result.photos.append(photo)
                        progress(f"Odczytano {len(result.photos)} zdjęć • {name}")
                    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
                        result.warnings.append(f"{path}: {error}")
        exact = defaultdict(list)
        for photo in result.photos:
            exact[photo.digest].append(photo)
        result.groups = [Group("exact", tuple(items)) for items in exact.values() if len(items) > 1]
        if include_similar:
            # Each group has a fixed anchor. We never chain A~B~C into A~C.
            tree = BKTree()
            buckets = {}
            for index, items in enumerate(exact.values()):
                checkpoint(cancel)
                photo = items[0]
                progress(f"Porównywanie zdjęć • {index + 1}/{len(exact)}")
                checkpoint(cancel)
                anchor = next((candidate for candidate in tree.query(photo.dhash, threshold, cancel)
                               if similar(candidate, photo, threshold)), None)
                if anchor is None:
                    tree.add(photo.dhash, photo)
                    buckets[photo.path] = [photo]
                else:
                    buckets[anchor.path].append(photo)
            for representatives in buckets.values():
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
            raise SafetyError(f"Dowiązanie w ścieżce: {photo.path}")
        current = photo.path.stat()
        if signature(current) != (photo.size, photo.modified_ns, photo.device, photo.inode):
            raise SafetyError(f"Plik zmienił się: {photo.path}")
        if sha256(photo.path, cancel) != photo.digest:
            raise SafetyError(f"Zawartość pliku zmieniła się: {photo.path}")
    except OSError as error:
        raise SafetyError(f"Plik niedostępny: {photo.path}: {error}") from error


def recycle_selected(result, selected, cancel=None, recycle=None, progress=None):
    """Validate the whole plan before disposal; recheck each target/keeper at use."""
    if result.cancelled:
        raise SafetyError("Skan został anulowany. Uruchom pełny skan.")
    cancel = cancel or threading.Event()
    progress = progress or (lambda message: None)
    selected = {Path(p) for p in selected}
    if not selected:
        return [], []
    known = {p.path: p for group in result.groups for p in group.photos}
    if selected - known.keys():
        raise SafetyError("Zaznaczenie zawiera plik spoza wyników.")
    keepers = {}
    check = {}
    for group in result.groups:
        members = {p.path: p for p in group.photos}
        targets = selected & members.keys()
        if not targets:
            continue
        remaining = [p for p in group.photos if p.path not in selected]
        if not remaining:
            raise SafetyError("Zostaw co najmniej jedno zdjęcie w każdej grupie.")
        keeper = remaining[0]
        check[keeper.path] = keeper
        for path in targets:
            keepers.setdefault(path, []).append(keeper)
            check[path] = known[path]
    for photo in check.values():
        progress(f"Sprawdzanie przed przeniesieniem • {photo.path.name}")
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
            progress(f"Przeniesiono do kosza • {path.name}")
        except Cancelled:
            failed.append("Operacja przerwana; część plików mogła już trafić do kosza.")
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
        writer.writerow(["Grupa", "Typ", "Ścieżka", "Bajty", "Szerokość", "Wysokość", "SHA256"])
        for index, group in enumerate(result.groups, 1):
            for photo in group.photos:
                writer.writerow(map(safe, [index, group.kind, photo.path, photo.size, photo.width, photo.height, photo.digest]))
