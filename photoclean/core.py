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


@dataclass(frozen=True, slots=True)
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


def _sha256_stream(stream, cancel: threading.Event, profile: PerformanceProfile) -> str:
    """Hash one already-open file handle with cooperative cancellation/yielding."""

    stream.seek(0)
    digest = hashlib.sha256()
    bytes_since_yield = 0
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


def sha256(path: Path, cancel: threading.Event, performance_profile: str | PerformanceProfile | None = None) -> str:
    """Hash a file with profile-specific I/O chunks and cooperative yielding."""
    profile = get_performance_profile(performance_profile)
    with path.open("rb") as stream:
        return _sha256_stream(stream, cancel, profile)


def _changed_during_scan(path: Path) -> ScanIssueError:
    return ScanIssueError("changed_during_scan", tr('plik zmienił się podczas skanowania'))


def _require_bound_scan_stream(path: Path, expected, stream):
    """Bind one opened scanner handle to the pre-open filesystem object.

    Exact hashing and pixel analysis must describe the same file object. A pathname
    can otherwise be replaced between the hash open and Pillow's later path open.
    Use the scanner's existing size/mtime/device/inode identity for the binding and
    fail closed into the structured ``changed_during_scan`` diagnostic.
    """

    opened = os.fstat(stream.fileno())
    if not stat.S_ISREG(opened.st_mode) or signature(opened) != signature(expected):
        raise _changed_during_scan(path)
    return opened


def _require_stable_scan_stream(path: Path, expected, stream) -> None:
    """Fail if the bound file handle changed while hash/decode work was running."""

    current = os.fstat(stream.fileno())
    if not stat.S_ISREG(current.st_mode) or signature(current) != signature(expected):
        raise _changed_during_scan(path)


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


def read_photo(
    path: Path,
    cancel: threading.Event,
    performance_profile: str | PerformanceProfile | None = None,
    analysis_cache: dict[str, Photo] | None = None,
) -> Photo:
    """Read one stable file object and reuse analysis for verified exact copies.

    One bound binary handle now supplies both the full SHA-256 digest and, for a
    previously unseen digest, Pillow's pixel decode. This prevents a pathname swap
    from making the exact hash describe one object while dimensions/dHash/color
    describe another. The handle and pathname are revalidated afterwards. Exact
    duplicate semantics remain full-file SHA-256 and cached copies still skip only
    redundant pixel decoding, never hashing.
    """

    profile = get_performance_profile(performance_profile)
    checkpoint(cancel)
    before = path.stat()

    with path.open("rb") as stream:
        opened = _require_bound_scan_stream(path, before, stream)
        digest = _sha256_stream(stream, cancel, profile)
        _require_stable_scan_stream(path, opened, stream)
        checkpoint(cancel)

        cached = analysis_cache.get(digest) if analysis_cache is not None else None
        if cached is not None:
            width, height, bits, color = cached.width, cached.height, cached.dhash, cached.color
            checkpoint(cancel)
        else:
            stream.seek(0)
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(stream) as source:
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
            _require_stable_scan_stream(path, opened, stream)

    after = path.stat()
    if signature(opened) != signature(after):
        raise _changed_during_scan(path)
    return Photo(path, *signature(after), digest, width, height, bits, color)


@dataclass(slots=True)
class _BKNode:
    """Compact BK-tree node with lazily allocated collision/child containers."""

    value: int
    photo: Photo
    collisions: list[Photo] | None = None
    children: dict[int, "_BKNode"] | None = None


class BKTree:
    """Hamming-distance index optimized for mostly unique perceptual hashes."""

    def __init__(self):
        self.root: _BKNode | None = None

    def add(self, value, photo):
        if self.root is None:
            self.root = _BKNode(value=value, photo=photo)
            return
        node = self.root
        while True:
            distance = (node.value ^ value).bit_count()
            if distance == 0:
                if node.collisions is None:
                    node.collisions = [photo]
                else:
                    node.collisions.append(photo)
                return
            if node.children is None:
                node.children = {distance: _BKNode(value=value, photo=photo)}
                return
            child = node.children.get(distance)
            if child is None:
                node.children[distance] = _BKNode(value=value, photo=photo)
                return
            node = child

    def query(self, value, radius, cancel):
        stack = [self.root] if self.root else []
        while stack:
            checkpoint(cancel)
            node = stack.pop()
            distance = (node.value ^ value).bit_count()
            if distance <= radius:
                yield node.photo
                if node.collisions:
                    yield from node.collisions
            if node.children:
                stack.extend(
                    child
                    for edge, child in node.children.items()
                    if distance - radius <= edge <= distance + radius
                )


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
    # One representative per exact SHA-256 digest doubles as the safe pixel-analysis
    # cache. Only duplicate digests allocate a members list, avoiding one list object
    # per unique photo on large libraries.
    representatives: dict[str, Photo] = {}
    duplicate_members: dict[str, list[Photo]] = {}
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
                        photo = read_photo(path, cancel, profile, representatives)
                        seen_inodes.add(inode)
                        representative = representatives.get(photo.digest)
                        if representative is None:
                            representatives[photo.digest] = photo
                        else:
                            members = duplicate_members.get(photo.digest)
                            if members is None:
                                duplicate_members[photo.digest] = [representative, photo]
                            else:
                                members.append(photo)
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

        # Preserve exact-group order by first digest appearance while allocating
        # member lists only for actual duplicates.
        result.groups = [
            Group("exact", tuple(duplicate_members[digest]))
            for digest in representatives
            if digest in duplicate_members
        ]
        if include_similar:
            # Each group has a fixed anchor. We never chain A~B~C into A~C.
            tree = BKTree()
            # Allocate member lists only for anchors that actually gain a match;
            # mostly-unique libraries therefore avoid one dict/list pair per photo.
            similar_members: dict[Path, list[Photo]] = {}
            unique_count = len(representatives)
            for index, photo in enumerate(representatives.values()):
                checkpoint(cancel)
                progress(tr('Porównywanie zdjęć • {v0}/{v1}', v0=index + 1, v1=unique_count))
                checkpoint(cancel)
                anchor = next((candidate for candidate in tree.query(photo.dhash, threshold, cancel)
                               if similar(candidate, photo, threshold)), None)
                if anchor is None:
                    tree.add(photo.dhash, photo)
                else:
                    members = similar_members.get(anchor.path)
                    if members is None:
                        similar_members[anchor.path] = [anchor, photo]
                    else:
                        members.append(photo)
            for representatives_in_group in similar_members.values():
                checkpoint(cancel)
                expanded = []
                for representative in representatives_in_group:
                    members = duplicate_members.get(representative.digest)
                    if members is None:
                        expanded.append(representative)
                    else:
                        expanded.extend(members)
                result.groups.append(Group("similar", tuple(expanded)))
        return result
    except Cancelled:
        result.cancelled = True
        result.groups.clear()  # incomplete scans never enable disposal
        return result


def _require_safe_photo_path(path: Path) -> None:
    """Reject a reviewed path if any lexical component is now a reparse point."""

    if any(linked(part) for part in (path, *path.parents)):
        raise SafetyError(tr('Dowiązanie w ścieżce: {v0}', v0=path))


def verify_photo(photo, cancel):
    """Revalidate one reviewed photo through a scan-bound immutable read.

    The safety decision must cover the same filesystem object that was scanned.
    Checking path metadata and then hashing through a fresh pathname leaves a
    replacement window between those operations. Bind the hash handle directly to
    the scan-time size/mtime/device/inode identity, keep that handle stable through
    EOF, then recheck the lexical ancestry and final path identity. This protects
    both recycle targets and keeper copies before any disposal is attempted.
    """

    expected = (photo.size, photo.modified_ns, photo.device, photo.inode)
    profile = get_performance_profile(None)
    checkpoint(cancel)
    try:
        _require_safe_photo_path(photo.path)
        current = photo.path.stat()
        if signature(current) != expected:
            raise SafetyError(tr('Plik zmienił się: {v0}', v0=photo.path))

        with photo.path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or bool(getattr(opened, "st_file_attributes", 0) & 0x400)
                or signature(opened) != expected
            ):
                raise SafetyError(tr('Plik zmienił się: {v0}', v0=photo.path))

            digest = _sha256_stream(stream, cancel, profile)
            after_read = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(after_read.st_mode)
                or bool(getattr(after_read, "st_file_attributes", 0) & 0x400)
                or signature(after_read) != expected
            ):
                raise SafetyError(tr('Plik zmienił się: {v0}', v0=photo.path))

        _require_safe_photo_path(photo.path)
        after = photo.path.stat()
        if signature(after) != expected:
            raise SafetyError(tr('Plik zmienił się: {v0}', v0=photo.path))
        # A second ancestry check narrows a final path-swap window between stat and
        # return; the production Shell layer performs its own independent binding.
        _require_safe_photo_path(photo.path)
        if digest != photo.digest:
            raise SafetyError(tr('Zawartość pliku zmieniła się: {v0}', v0=photo.path))
    except OSError as error:
        raise SafetyError(tr('Plik niedostępny: {v0}: {v1}', v0=photo.path, v1=error)) from error


def recycle_selected(result, selected, cancel=None, recycle=None, progress=None):
    """Validate the whole plan before disposal; recheck each target/keeper at use.

    The production Windows path also passes the target's scan-time filesystem
    identity and full SHA-256 into ``recycle_file``. That prevents a replacement
    between this core revalidation and the Shell layer from becoming a fresh,
    trusted recycle baseline. Injected callbacks keep the historical one-argument
    contract for tests and non-production harnesses.
    """
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

    default_recycle = recycle is None
    if default_recycle:
        from .recycle import recycle_file

    completed, failed = [], []
    for path in sorted(selected):
        try:
            checkpoint(cancel)
            for keeper in keepers[path]:
                verify_photo(keeper, cancel)
            target = known[path]
            verify_photo(target, cancel)
            if default_recycle:
                recycle_file(
                    str(path),
                    expected_scan_signature=(
                        target.size,
                        target.modified_ns,
                        target.device,
                        target.inode,
                    ),
                    expected_scan_digest=target.digest,
                )
            else:
                recycle(str(path))  # injected seam; production never falls back to unlink/remove
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
