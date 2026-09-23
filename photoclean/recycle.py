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


def _identity_from_stat(info) -> tuple[int, int, int, int, int]:
    """Normalize metadata used to bind a verified path to an opened file handle."""
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_size),
        int(getattr(info, "st_mtime_ns", int(info.st_mtime * 1_000_000_000))),
        int(getattr(info, "st_ctime_ns", int(info.st_ctime * 1_000_000_000))),
    )


def _scan_signature_from_stat(info) -> tuple[int, int, int, int]:
    """Normalize the scanner identity stored on ``Photo`` records.

    The order intentionally matches ``photoclean.core.signature`` and the fields
    persisted on ``Photo``: size, mtime_ns, device, inode. Keeping this separate
    from the stronger local recycle identity lets the final Shell layer prove that
    it is still operating on the exact object that was scanned and reviewed.
    """
    return (
        int(info.st_size),
        int(getattr(info, "st_mtime_ns", int(info.st_mtime * 1_000_000_000))),
        int(info.st_dev),
        int(info.st_ino),
    )


def _normalize_scan_signature(expected_scan_signature) -> tuple[int, int, int, int] | None:
    if expected_scan_signature is None:
        return None
    try:
        normalized = tuple(int(value) for value in expected_scan_signature)
    except (TypeError, ValueError) as error:
        raise OSError(tr('Nieprawidłowa sygnatura pliku ze skanu.')) from error
    if len(normalized) != 4:
        raise OSError(tr('Nieprawidłowa sygnatura pliku ze skanu.'))
    return normalized


def _require_scan_signature(path, expected_scan_signature) -> Path:
    """Fail closed unless the live path still matches the scanner/review identity."""
    candidate = _require_regular_file_target(path)
    expected = _normalize_scan_signature(expected_scan_signature)
    if expected is None:
        return candidate
    if _scan_signature_from_stat(_safe_lstat(candidate)) != expected:
        raise OSError(tr('Plik zmienił się: {v0}', v0=str(candidate)))
    return candidate


def _file_identity(path: Path) -> tuple[int, int, int, int, int]:
    """Return metadata used to detect a last-moment target replacement/mutation."""
    return _identity_from_stat(_safe_lstat(path))


def _path_and_handle_identity_match(
    expected_identity: tuple[int, int, int, int, int],
    opened_info,
) -> bool:
    """Bind an open handle to the path identity without Windows CRT false alarms.

    Windows may expose small path-vs-handle metadata representation differences.
    Require a real positive file-id match there and bind size/mtime as well; on
    other platforms the full normalized identity must match exactly.
    """
    opened_identity = _identity_from_stat(opened_info)
    if os.name != "nt":
        return opened_identity == expected_identity

    expected_inode = int(expected_identity[1])
    opened_inode = int(opened_identity[1])
    if expected_inode <= 0 or opened_inode <= 0 or expected_inode != opened_inode:
        return False
    return expected_identity[2:4] == opened_identity[2:4]


def _require_same_regular_file_target(path, expected_identity) -> Path:
    """Fail closed if the recycle target changed since the safety snapshot."""
    candidate = _require_regular_file_target(path)
    if _file_identity(candidate) != expected_identity:
        raise OSError(tr('Plik zmienił się: {v0}', v0=str(candidate)))
    return candidate


def _stable_file_sha256(path, expected_identity) -> str:
    """Hash exactly the verified recycle target through one bound open handle.

    A path can be swapped after the pre-open metadata check but before ``open``.
    Bind the resulting handle back to the expected filesystem identity before any
    bytes are trusted, verify the handle remains stable during the read, then
    revalidate the path after closing. A digest from a different file object is
    therefore rejected instead of becoming recycle-safety evidence.
    """
    candidate = _require_same_regular_file_target(path, expected_identity)
    digest = hashlib.sha256()
    try:
        with candidate.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode):
                raise OSError(tr('Cel Kosza nie jest zwykłym plikiem: {v0}', v0=str(candidate)))
            if bool(getattr(opened, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE):
                raise OSError(tr('Dowiązanie w ścieżce: {v0}', v0=str(candidate)))
            if not _path_and_handle_identity_match(expected_identity, opened):
                raise OSError(tr('Plik zmienił się: {v0}', v0=str(candidate)))

            opened_identity = _identity_from_stat(opened)
            while chunk := stream.read(_HASH_CHUNK_BYTES):
                digest.update(chunk)

            after_read = os.fstat(stream.fileno())
            if not _path_and_handle_identity_match(opened_identity, after_read):
                raise OSError(tr('Plik zmienił się: {v0}', v0=str(candidate)))
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


def _scan_bound_snapshot(path, expected_scan_signature=None, expected_scan_digest=None):
    """Bind the recycle baseline to the exact object captured by the scanner.

    ``recycle_file`` used to start from a fresh identity snapshot after the core
    revalidation. A path replacement in that narrow gap could therefore become the
    new trusted baseline. When scan evidence is supplied, require the live object
    to match it before and after the bound full-file hash and require the digest to
    equal the scan-time SHA-256. The returned local identity remains the stronger
    last-moment baseline used by the Shell dispatch guards.
    """
    candidate = _require_scan_signature(path, expected_scan_signature)
    expected_identity = _file_identity(candidate)
    digest = _stable_file_sha256(candidate, expected_identity)
    _require_scan_signature(candidate, expected_scan_signature)
    if expected_scan_digest is not None and digest.lower() != str(expected_scan_digest).lower():
        raise OSError(tr('Zawartość pliku zmieniła się: {v0}', v0=str(candidate)))
    return candidate, expected_identity, digest


def recycle_file(path, *, expected_scan_signature=None, expected_scan_digest=None):
    if os.name != "nt":
        raise OSError(tr('Przenoszenie do kosza w tej wersji jest dostępne tylko na Windows.'))
    import ctypes
    import pythoncom
    from win32com.shell import shell, shellcon
    from win32com.server.exception import COMException
    from send2trash.win.IFileOperationProgressSink import FileOperationProgressSink

    absolute_path = _require_scan_signature(path, expected_scan_signature)
    absolute = str(absolute_path)
    volume = ctypes.create_unicode_buffer(32768)
    if not ctypes.windll.kernel32.GetVolumePathNameW(absolute, volume, len(volume)):
        raise OSError(tr('Nie można ustalić woluminu pliku.'))
    if ctypes.windll.kernel32.GetDriveTypeW(volume.value) != 3:
        raise OSError(tr('Kosz obsługujemy tylko na lokalnych dyskach stałych. Dysk sieciowy lub wymienny: operacja zablokowana.'))

    # Only fixed local targets reach the full-content safety snapshot. This avoids
    # expensive reads on network/removable paths that the cleanup policy blocks.
    # When called from the scanner cleanup workflow this snapshot is additionally
    # pinned to the scan-time identity and full SHA-256, so a replacement cannot
    # silently become a fresh trusted baseline between core review and Shell use.
    absolute_path, expected_identity, expected_digest = _scan_bound_snapshot(
        absolute_path,
        expected_scan_signature=expected_scan_signature,
        expected_scan_digest=expected_scan_digest,
    )

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
        _require_scan_signature(absolute_path, expected_scan_signature)
        _require_same_regular_file_target(absolute_path, expected_identity)
        operation.DeleteItem(item, wrapped)
        _require_scan_signature(absolute_path, expected_scan_signature)
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
