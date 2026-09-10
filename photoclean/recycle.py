from .i18n import tr
"""Windows recycle-only operation, with a callback veto for permanent deletion."""
import os
from pathlib import Path


def recycle_file(path):
    if os.name != "nt":
        raise OSError(tr('Przenoszenie do kosza w tej wersji jest dostępne tylko na Windows.'))
    import ctypes
    import pythoncom
    from win32com.shell import shell, shellcon
    from win32com.server.exception import COMException
    from send2trash.win.IFileOperationProgressSink import FileOperationProgressSink

    absolute = str(Path(path).absolute())
    volume = ctypes.create_unicode_buffer(32768)
    if not ctypes.windll.kernel32.GetVolumePathNameW(absolute, volume, len(volume)):
        raise OSError(tr('Nie można ustalić woluminu pliku.'))
    if ctypes.windll.kernel32.GetDriveTypeW(volume.value) != 3:
        raise OSError(tr('Kosz obsługujemy tylko na lokalnych dyskach stałych. Dysk sieciowy lub wymienny: operacja zablokowana.'))

    class RecycleOnlySink(FileOperationProgressSink):
        def __init__(self):
            super().__init__()
            self.error = None
            self.recycled = False

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
        operation.DeleteItem(item, wrapped)
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
    finally:
        pythoncom.CoUninitialize()
