# -*- coding: utf-8 -*-
# GPL v2; see COPYING.txt.
"""Bounded, single-attempt Win32 Unicode clipboard transactions.

wxMSW's OLE clipboard Open/Close only maintain a logical flag. They do NOT
exclude copies by other applications. Never mix wx/OLE calls into these native
transactions. The caller schedules retries on the UI loop, not in this helper.
"""
import ctypes
import threading


CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
MAX_CLIPBOARD_BYTES = 16 * 1024 * 1024
MAX_CLIPBOARD_FORMATS = 128
# Only ordinary text HGLOBALs and registered HGLOBAL formats can be backed up.
# GDI handles, owner-display/private formats, and unknown standard formats are
# deliberately refused before EmptyClipboard, not guessed or silently dropped.
_TEXT_MEMORY_FORMATS = frozenset((1, 7, CF_UNICODETEXT, 16))


class Win32Clipboard:
    def __init__(self, owner, *, user32=None, kernel32=None):
        self._owner = owner
        self._transaction_lock = threading.Lock()
        self.user32 = user32 if user32 is not None else ctypes.WinDLL('user32')
        self.kernel32 = kernel32 if kernel32 is not None else ctypes.WinDLL('kernel32')
        self._bind()

    def _bind(self):
        # Explicit pointer-sized handles/pointers/SIZE_T, including return types:
        # ctypes' default c_int truncates HGLOBAL/HWND on 64-bit NVDA.
        handle, uint, dword, boolean = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int
        for library, name, args, result in (
            (self.user32, 'OpenClipboard', [handle], boolean),
            (self.user32, 'CloseClipboard', [], boolean),
            (self.user32, 'EmptyClipboard', [], boolean),
            (self.user32, 'IsClipboardFormatAvailable', [uint], boolean),
            (self.user32, 'GetClipboardSequenceNumber', [], dword),
            (self.user32, 'GetClipboardData', [uint], handle),
            (self.user32, 'SetClipboardData', [uint, handle], handle),
            (self.user32, 'EnumClipboardFormats', [uint], uint),
            (self.user32, 'IsWindow', [handle], boolean),
            (self.user32, 'GetWindowThreadProcessId', [handle, ctypes.POINTER(dword)], dword),
            (self.kernel32, 'GetCurrentProcessId', [], dword),
            (self.kernel32, 'GlobalAlloc', [uint, ctypes.c_size_t], handle),
            (self.kernel32, 'GlobalLock', [handle], ctypes.c_void_p),
            (self.kernel32, 'GlobalUnlock', [handle], boolean),
            (self.kernel32, 'GlobalSize', [handle], ctypes.c_size_t),
            (self.kernel32, 'GlobalFree', [handle], handle),
            (self.kernel32, 'SetLastError', [dword], None),
            (self.kernel32, 'GetLastError', [], dword),
        ):
            function = getattr(library, name)
            function.argtypes, function.restype = args, result

    def sequence(self):
        try:
            return self.user32.GetClipboardSequenceNumber() or None
        except Exception:
            return None

    def _open(self):
        if not self._transaction_lock.acquire(blocking=False):
            return False
        opened = False
        try:
            hwnd = self._owner()
            if not hwnd or not self.user32.IsWindow(hwnd):
                return False
            process = ctypes.c_uint32()
            if not self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process)):
                return False
            if process.value != self.kernel32.GetCurrentProcessId():
                return False
            # A nested OpenClipboard on this HWND is not reference-counted.
            opened = bool(self.user32.OpenClipboard(hwnd))
            return opened
        finally:
            if not opened:
                self._transaction_lock.release()

    def _close(self):
        try:
            self.user32.CloseClipboard()
        finally:
            self._transaction_lock.release()

    def _read_bytes(self, handle, limit=MAX_CLIPBOARD_BYTES):
        if not handle:
            raise ValueError('Clipboard format could not be rendered')
        size = self.kernel32.GlobalSize(handle)
        if not 0 < size <= limit:
            raise ValueError('Clipboard allocation is unavailable or exceeds the bound')
        pointer = self.kernel32.GlobalLock(handle)
        if not pointer:
            raise ValueError('Clipboard allocation could not be locked')
        try:
            return ctypes.string_at(pointer, size)
        finally:
            # Zero means success when the final lock is released, not failure.
            self.kernel32.GlobalUnlock(handle)

    def _read_text(self):
        data = self._read_bytes(self.user32.GetClipboardData(CF_UNICODETEXT))
        if len(data) % 2:
            raise ValueError('Invalid Unicode clipboard size')
        end = next((i for i in range(0, len(data), 2) if data[i:i + 2] == b'\0\0'), None)
        if end is None:
            raise ValueError('Unterminated Unicode clipboard text')
        return data[:end].decode('utf-16-le')

    def snapshot(self, expected_sequence=None):
        """Return (text, rendered_generation) under a native clipboard lock.

        (None, None) is busy/unavailable; (None, generation) is a copy that
        happened before we acquired the lock. Once locked, GetClipboardData
        may render delayed data and advance the generation without a new copy.
        """
        opened = False
        try:
            opened = self._open()
            if not opened:
                return None, None
            before = self.sequence()
            if before is None:
                return None, None
            if expected_sequence is not None and before != expected_sequence:
                return None, before
            if not self.user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                return '', before
            text = self._read_text()
            after = self.sequence()
            return (text, after) if after is not None else (None, None)
        except Exception:
            return None, None
        finally:
            if opened:
                self._close()

    def _allocate(self, data, pending):
        handle = self.kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            raise MemoryError('Clipboard allocation failed')
        pending.add(handle)
        pointer = self.kernel32.GlobalLock(handle)
        if not pointer:
            raise MemoryError('Clipboard allocation could not be locked')
        try:
            ctypes.memmove(pointer, data, len(data))
        finally:
            self.kernel32.GlobalUnlock(handle)
        return handle

    def _backup(self, pending):
        formats = []
        current = 0
        while True:
            self.kernel32.SetLastError(0)
            current = self.user32.EnumClipboardFormats(current)
            if not current:
                if self.kernel32.GetLastError():
                    raise ValueError('Clipboard format enumeration failed')
                break
            if current in formats or len(formats) >= MAX_CLIPBOARD_FORMATS:
                raise ValueError('Clipboard format enumeration exceeds the bound')
            if current not in _TEXT_MEMORY_FORMATS and not 0xC000 <= current <= 0xFFFF:
                raise ValueError('Clipboard format cannot be safely backed up')
            formats.append(current)
        if CF_UNICODETEXT not in formats:
            raise ValueError('Original Unicode clipboard format is missing')
        # Restore text first if publishing fails. Allocate every backup before
        # doing anything destructive; an unreadable format cancels the update.
        formats.sort(key=lambda value: value != CF_UNICODETEXT)
        backups, remaining = [], MAX_CLIPBOARD_BYTES
        for format in formats:
            data = self._read_bytes(self.user32.GetClipboardData(format), remaining)
            remaining -= len(data)
            backups.append((format, self._allocate(data, pending)))
        return backups

    def _publish(self, format, handle, pending):
        if not self.user32.SetClipboardData(format, handle):
            return False
        # Ownership passes to Windows only on success. Never free that handle.
        pending.remove(handle)
        return True

    def _restore(self, backups, pending):
        # Windows has no rollback API. Make a bounded best-effort restoration
        # from preallocated handles while we still exclude other applications.
        for format, handle in backups:
            try:
                self._publish(format, handle, pending)
            except Exception:
                pass

    def replace(self, original, translated, expected_sequence=None, cancelled=None):
        """Compare and replace with native exclusion; never sleep or use OLE.

        All formats must be safely backed up before EmptyClipboard. If the
        final publish fails, restore them before releasing the lock. A system
        failure that also prevents restoration cannot be made atomic by Win32.
        A failed publish returns 'failed' (terminal); 'unavailable' means no
        destructive update occurred. Rendering can still advance the generation.
        """
        opened, emptied, committed = False, False, False
        pending, backups = set(), []
        try:
            if not isinstance(translated, str) or '\0' in translated:
                return 'unavailable'
            encoded = translated.encode('utf-16-le') + b'\0\0'
            if len(encoded) > MAX_CLIPBOARD_BYTES:
                return 'unavailable'
            opened = self._open()
            if not opened:
                return 'unavailable'
            sequence = self.sequence()
            if sequence is None:
                return 'unavailable'
            if expected_sequence is not None and sequence != expected_sequence:
                return 'changed'
            if self._read_text() != original:
                return 'changed'
            replacement = self._allocate(encoded, pending)
            backups = self._backup(pending)
            # GetClipboardData can dispatch delayed-rendering messages. Honour
            # a command cancellation reentered by those messages before mutation.
            if cancelled is not None and cancelled():
                return 'cancelled'
            if not self.user32.EmptyClipboard():
                return 'unavailable'
            emptied = True
            # EmptyClipboard notifies the former owner, which can also reenter.
            if cancelled is not None and cancelled():
                return 'cancelled'
            committed = self._publish(CF_UNICODETEXT, replacement, pending)
            return 'replaced' if committed else 'failed'
        except Exception:
            return 'failed' if emptied else 'unavailable'
        finally:
            try:
                if emptied and not committed:
                    self._restore(backups, pending)
            finally:
                try:
                    for handle in pending:
                        self.kernel32.GlobalFree(handle)
                finally:
                    if opened:
                        self._close()
