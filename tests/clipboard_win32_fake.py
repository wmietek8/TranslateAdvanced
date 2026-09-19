"""In-memory Win32 boundary: native locks exclude copies, wx.Open does not.

No function in this module opens or reads the operating system clipboard.
Handles intentionally exceed 32 bits on 64-bit Python; buffers are real ctypes
allocations so production code exercises bounded GlobalLock reads/writes.
"""
import ctypes
import threading
import types


class Function:
    def __init__(self, function):
        self.function = function
        self.argtypes = self.restype = None

    def __call__(self, *args):
        return self.function(*args)


class Win32ClipboardFake:
    HWND = 0x1234
    PID = 321

    def __init__(self, clipboard=None, text='Cześć'):
        self.clipboard = clipboard or types.SimpleNamespace(
            text=text, sequence=21, open_ok=True, get_ok=True, set_ok=True,
            has_text=True, opens=0, closes=0, writes=[])
        self.thread = threading.get_ident()
        self.opened = False
        self.valid_hwnd = True
        self.pid = self.PID
        self.blocks = {}
        self.sizes = {}
        self.locks = set()
        self.owned = set()
        self.freed = []
        self.formats = {}
        self.next_handle = (1 << 40) if ctypes.sizeof(ctypes.c_void_p) == 8 else 0x10000
        self.trace = []
        self.before_open = self.on_alloc = self.on_get = self.on_set = None
        self.fail_alloc = self.fail_lock = self.fail_empty = False
        self.fail_sets = 0
        self.last_error = 0
        self.user32 = types.SimpleNamespace(**{
            name: Function(getattr(self, name)) for name in (
                'OpenClipboard', 'CloseClipboard', 'GetClipboardSequenceNumber',
                'GetClipboardData', 'SetClipboardData', 'EmptyClipboard',
                'EnumClipboardFormats', 'IsClipboardFormatAvailable',
                'IsWindow', 'GetWindowThreadProcessId')})
        self.kernel32 = types.SimpleNamespace(**{
            name: Function(getattr(self, name)) for name in (
                'GlobalAlloc', 'GlobalLock', 'GlobalUnlock', 'GlobalSize', 'GlobalFree',
                'GetCurrentProcessId', 'GetLastError', 'SetLastError')})
        self._sync_text()

    def _new_block(self, data, owned=False):
        self.next_handle += 16
        handle = self.next_handle
        self.blocks[handle] = ctypes.create_string_buffer(data, len(data))
        self.sizes[handle] = len(data)
        if owned:
            self.owned.add(handle)
        return handle

    def _sync_text(self):
        if self.clipboard.has_text:
            self.formats[13] = self._new_block(self.clipboard.text.encode('utf-16-le') + b'\x00\x00', True)
        else:
            self.formats.pop(13, None)

    def add_format(self, format, data):
        self.formats[format] = self._new_block(data, True)

    def format_bytes(self):
        return {fmt: bytes(self.blocks[handle]) for fmt, handle in self.formats.items()}

    def assert_clean(self):
        assert not self.opened
        assert not self.locks
        assert not set(self.blocks).difference(self.owned), 'Leaked caller-owned HGLOBAL'

    def copy(self, text):
        if self.opened:
            self.trace.append('copy-blocked')
            return False
        self.clipboard.text = text
        self.clipboard.has_text = True
        self.clipboard.sequence += 1
        self._sync_text()
        self.trace.append('copy')
        return True

    def GetClipboardSequenceNumber(self):
        return self.clipboard.sequence

    def IsWindow(self, hwnd):
        return self.valid_hwnd and hwnd == self.HWND

    def GetWindowThreadProcessId(self, hwnd, pid):
        pid._obj.value = self.pid
        return 55

    def GetCurrentProcessId(self):
        return self.PID

    def SetLastError(self, value):
        self.last_error = value

    def GetLastError(self):
        return self.last_error

    def OpenClipboard(self, hwnd):
        assert threading.get_ident() == self.thread, 'Native clipboard accessed by worker'
        assert hwnd == self.HWND, 'A valid owned HWND is required, never NULL'
        self.trace.append('open')
        self.clipboard.opens += 1
        if self.before_open:
            hook, self.before_open = self.before_open, None
            hook()
        if self.opened or not self.clipboard.open_ok:
            return False
        self._sync_text()
        self.original_text = self.clipboard.text
        self.opened = True
        if hasattr(self.clipboard, 'native_open'):
            self.clipboard.native_open = True
        return True

    def CloseClipboard(self):
        assert self.opened
        assert not self.locks
        self.trace.append('close')
        self.opened = False
        if hasattr(self.clipboard, 'native_open'):
            self.clipboard.native_open = False
        self.clipboard.closes += 1
        return True

    def IsClipboardFormatAvailable(self, format):
        assert self.opened
        return format in self.formats

    def GetClipboardData(self, format):
        assert self.opened
        self.trace.append(('get', format))
        if self.on_get:
            hook, self.on_get = self.on_get, None
            hook()
        return self.formats.get(format, 0) if self.clipboard.get_ok else 0

    def EnumClipboardFormats(self, previous):
        assert self.opened
        formats = list(self.formats)
        if not previous:
            return formats[0] if formats else 0
        index = formats.index(previous) + 1
        return formats[index] if index < len(formats) else 0

    def EmptyClipboard(self):
        assert self.opened
        self.trace.append('empty')
        if self.fail_empty:
            return False
        for handle in self.formats.values():
            self.blocks.pop(handle, None)
            self.sizes.pop(handle, None)
            self.owned.discard(handle)
        self.formats.clear()
        self.clipboard.text = ''
        self.clipboard.sequence += 1
        return True

    def SetClipboardData(self, format, handle):
        assert self.opened
        assert handle not in self.locks
        assert handle in self.blocks
        self.trace.append(('set', format))
        if self.on_set:
            hook, self.on_set = self.on_set, None
            hook()
        if self.fail_sets:
            self.fail_sets -= 1
            return 0
        data = bytes(self.blocks[handle])
        if not self.clipboard.set_ok and format == 13 and data.decode('utf-16-le').rstrip('\0') != self.original_text:
            return 0
        self.formats[format] = handle
        self.owned.add(handle)
        self.clipboard.sequence += 1
        if format == 13:
            self.clipboard.text = data.decode('utf-16-le').split('\0', 1)[0]
            if self.clipboard.text != self.original_text:
                self.clipboard.writes.append(self.clipboard.text)
        return handle

    def GlobalAlloc(self, flags, size):
        assert flags & 2, 'SetClipboardData needs GMEM_MOVEABLE'
        self.trace.append('alloc')
        if self.on_alloc:
            hook, self.on_alloc = self.on_alloc, None
            hook()
        if self.fail_alloc:
            return 0
        return self._new_block(b'\0' * size)

    def GlobalLock(self, handle):
        self.trace.append('lock')
        if self.fail_lock:
            return 0
        self.locks.add(handle)
        return ctypes.addressof(self.blocks[handle])

    def GlobalUnlock(self, handle):
        assert handle in self.locks
        self.locks.remove(handle)
        self.trace.append('unlock')
        return False  # Win32 returns zero on a successful final unlock.

    def GlobalSize(self, handle):
        return self.sizes.get(handle, 0)

    def GlobalFree(self, handle):
        self.trace.append('free')
        assert handle not in self.owned, 'Free after ownership transfer'
        assert handle not in self.locks
        self.blocks.pop(handle)
        self.sizes.pop(handle, None)
        self.freed.append(handle)
        return 0
