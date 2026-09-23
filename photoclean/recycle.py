from .i18n import tr
"""Windows recycle-only operation, with a callback veto for permanent deletion."""
import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path


_REPARSE_POINT_ATTRIBUTE = 0x400
_HASH_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class RecycleReceipt:
    """Receipt returned only after Windows confirms a recycle-only move.

    ``source_device`` and ``source_inode`` describe the exact filesystem object
    handed to the Shell operation. ``recycled_shell_path`` is the parsing name
    reported by Windows for the newly-created Recycle Bin item. Release evidence
    can use this to distinguish a real restore from a byte-identical recreated
    file without weakening the normal cleanup path.
    """

    source_device: int
    source_inode: int
    recycled_shell_path: str


def _safe_lstat(path: Path):
    """Read path metadata for a safety decision; never treat failure as safe."""
    try:
        return path.lstat()
    except OSError as error:
        raise OSError(
            tr(
                'Nie można bezpiecznie sprawdzić ścieżki przed Koszem: {v0}: {v1}',
                v0=str(path),
                v1=error,
            )
        ) from error


def _is_link_or_reparse(path: Path) -> bool:
    """Return True for links/reparse points and fail closed on unreadable metadata."""
    info = _safe_lstat(path)
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE
    )


def _require_no_reparse_ancestry(path) -> Path:
    """Reject recycle targets whose path crosses a link/reparse boundary.

    ``Path.resolve()`` is intentionally not used here because resolving first would
    hide the very junction/symlink boundary this safety check is meant to detect.
    Every path component must also be inspectable. Missing or permission-denied
    metadata therefore fails closed instead of being treated as a regular path.
    The production scanner already avoids reparse points; this is a second,
    operation-time guard so stale state or an externally changed path still fails
    closed before Windows receives a delete request.
    """
    candidate = Path(path).absolute()
    current = candidate
    while True:
        if _is_link_or_reparse(current):
            raise OSError(tr('Dowiązanie w ścieżce: {v0}', v0=str(current)))
        parent = current.parent
        if parent == current:
            break
        current = parent
    return candidate


def _require_regular_file_target(path) -> Path:
    """Return a safe absolute recycle target and reject non-file replacements.

    The cleanup UI only ever intends to recycle files that were part of a verified
    photo result. A stale path can nevertheless be replaced with a directory or
    another filesystem object after the scan. Keep that object from reaching the
    Windows Shell delete request even if an earlier scanner-level revalidation has
    already happened.
    """
    candidate = _require_no_reparse_ancestry(path)
    info = _safe_lstat(candidate)
    if not stat.S_ISREG(info.st_mode):
        raise OSError(tr('Cel Kosza nie jest zwykłym plikiem: {v0}', v0=str(candidate)))
    return candidate


def _file_identity(path: Path) -> tuple[int, int, int, int, int]:
    """Return metadata used to detect a last-moment target replacement/mutation."""
    info = _safe_lstat(path)
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_size),
        int(getattr(info, "st_mtime_ns", int(info.st_mtime * 1_000_000_000))),
        int(getattr(info, "st_ctime_ns", int(info.st_ctime * 1_000_000_000))),
    )


def _require_same_regular_file_target(path, expected_identity) -> Path:
    """Fail closed if the recycle target changed since the safety snapshot."""
    candidate = _require_regular_file_target(path)
    if _file_identity(candidate) != expected_identity:
        raise OSError(tr('Plik zmienił się: {v0}', v0=str(candidate)))
    return candidate


def _stable_file_sha256(path, expected_identity) -> str:
    """Hash a recycle target only while it remains the same verified regular file.

    Metadata identity catches normal replacements cheaply, but a second content
    signal closes the gap where a same-size mutation might otherwise preserve the
    fields used by the final Shell handoff checks. The identity is validated both
    before and after the read so a digest collected across a replacement is never
    accepted as release-safety evidence.
    """
    candidate = _require_same_regular_file_target(path, expected_identity)
    digest = hashlib.sha256()
    try:
        with candidate.open("rb") as stream:
            while chunk := stream.read(_HASH_CHUNK_BYTES):
                digest.update(chunk)
    except OSError as error:
        raise OSError(
            tr(
                'Nie można bezpiecznie sprawdzić ścieżki przed Koszem: {v0}: {v1}',
                v0=str(candidate),
                v1=error,
            )
        ) from error
    _require_same_regular_file_target(candidate, expected_identity)
    return digest.hexdigest()


def _require_same_file_content(path, expected_identity, expected_digest) -> Path:
    """Fail closed if full file content differs from the recycle safety snapshot."""
    candidate = _require_same_regular_file_target(path, expected_identity)
    if _stable_file_sha256(candidate, expected_identity) != expected_digest:
        raise OSError(tr('Zawartość pliku zmieniła się: {v0}', v0=str(candidate)))
    return candidate


def recycle_file(path):
    if os.name != "nt":
        raise OSError(tr('Przenoszenie do kosza w tej wersji jest dostępne tylko na Windows.'))
    import ctypes
    import pythoncom
    from win32com.shell import shell, shellcon
    from win32com.server.exception import COMException
    from send2trash.win.IFileOperationProgressSink import FileOperationProgressSink

    absolute_path = _require_regular_file_target(path)
    expected_identity = _file_identity(absolute_path)
    absolute = str(absolute_path)
    volume = ctypes.create_unicode_buffer(32768)
    if not ctypes.windll.kernel32.GetVolumePathNameW(absolute, volume, len(volume)):
        raise OSError(tr('Nie można ustalić woluminu pliku.'))
    if ctypes.windll.kernel32.GetDriveTypeW(volume.value) != 3:
        raise OSError(tr('Kosz obsługujemy tylko na lokalnych dyskach stałych. Dysk sieciowy lub wymienny: operacja zablokowana.'))

    # Only fixed local targets reach the full-content safety snapshot. This avoids
    # expensive reads on network/removable paths that the cleanup policy blocks.
    expected_digest = _stable_file_sha256(absolute_path, expected_identity)

    class RecycleOnlySink(FileOperationProgressSink):
        def __init__(self):
            super().__init__()
            self.error = None
            self.recycled = False
            self.newItem = ""

        def PreDeleteItem(self, flags, item):
            if not flags & shellcon.TSF_DELETE_RECYCLE_IF_POSSIBLE:
                self.error = tr('Windows nie potwierdził dostępności kosza; plik pozostawiono na miejscu.')
                raise COMException(desc=tr('Trwałe usuwanie jest zabronione'), scode=-2147467260)
            return 0

        def PostDeleteItem(self, flags, item, hr_delete, newly_created):
            if hr_delete & 0x80000000 and not self.error:
                self.error = tr('Błąd kosza Windows: {v0}', v0=hr_delete)
            if newly_created is not None:
                self.recycled = True
                self.newItem = newly_created.GetDisplayName(shellcon.SHGDN_FORPARSING)

    pythoncom.CoInitialize()
    try:
        sink = RecycleOnlySink()
        wrapped = pythoncom.WrapObject(sink, shell.IID_IFileOperationProgressSink)
        operation = pythoncom.CoCreateInstance(shell.CLSID_FileOperation, None, pythoncom.CLSCTX_ALL, shell.IID_IFileOperation)
        operation.SetOperationFlags(shellcon.FOF_SILENT | shellcon.FOF_NOERRORUI |
                                    shellcon.FOF_NOCONFIRMATION | shellcon.FOF_ALLOWUNDO | 0x00100000 |
                                    0x20000000 | 0x00080000)
        item = shell.SHCreateItemFromParsingName(absolute, None, shell.IID_IShellItem)
        _require_same_regular_file_target(absolute_path, expected_identity)
        operation.DeleteItem(item, wrapped)
        _require_same_file_content(absolute_path, expected_identity, expected_digest)
        try:
            result = operation.PerformOperations()
        except pythoncom.com_error as error:
            raise OSError(sink.error or str(error)) from error
        if result or operation.GetAnyOperationsAborted() or sink.error:
            raise OSError(sink.error or tr('Windows przerwał przenoszenie do kosza.'))
        if not sink.recycled:
            raise OSError(tr('Windows nie zwrócił potwierdzenia umieszczenia pliku w koszu.'))
        if Path(absolute).exists():
            raise OSError(tr('Plik pozostał na miejscu; kosz nie potwierdził przeniesienia.'))
        return RecycleReceipt(
            source_device=expected_identity[0],
            source_inode=expected_identity[1],
            recycled_shell_path=str(sink.newItem or ""),
        )
    finally:
        pythoncom.CoUninitialize()
