"""Native transaction regressions without accessing the real clipboard."""
import ctypes
import importlib.util
from pathlib import Path

import pytest

from clipboard_win32_fake import Win32ClipboardFake

PATH = Path(__file__).resolve().parents[1] / 'addon/globalPlugins/TranslateAdvanced/app/utils/utils_clipboard_win32.py'


@pytest.fixture
def native(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Real WinDLL is forbidden in unit tests')
    monkeypatch.setattr(ctypes, 'WinDLL', forbidden, raising=False)
    monkeypatch.setattr(ctypes, 'windll', None, raising=False)
    spec = importlib.util.spec_from_file_location('clipboard_win32_under_test', PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fake = Win32ClipboardFake()
    clipboard = module.Win32Clipboard(lambda: fake.HWND, user32=fake.user32, kernel32=fake.kernel32)
    yield module, clipboard, fake
    fake.assert_clean()


def test_reentrant_read_cannot_release_the_outer_native_lock(native):
    module, clipboard, fake = native
    real_open = fake.user32.OpenClipboard
    def open_again(hwnd):
        if fake.opened:
            return True
        return real_open(hwnd)
    fake.user32.OpenClipboard = open_again
    nested = []
    def read_during_render():
        nested.append(clipboard.snapshot())
        assert fake.opened, 'Nested reader released the outer native lock'
        assert not fake.copy('newer copy')
    fake.on_get = read_during_render
    assert clipboard.snapshot() == ('Cześć', 21)
    assert nested == [(None, None)]
    assert fake.clipboard.opens == fake.clipboard.closes == 1
    assert clipboard.snapshot() == ('Cześć', 21)


def test_native_compare_and_replace_blocks_copy_at_the_final_write(native):
    module, clipboard, fake = native
    def copy_during_publish():
        assert not fake.copy('new copy')
    fake.on_set = copy_during_publish
    assert clipboard.replace('Cześć', 'Hello 🦊', 21) == 'replaced'
    assert fake.clipboard.text == 'Hello 🦊'
    assert 'copy-blocked' in fake.trace
    assert fake.clipboard.opens == fake.clipboard.closes == 1
    assert fake.trace.index('alloc') < fake.trace.index('empty')


def test_recopy_before_native_open_is_rejected_even_when_text_is_identical(native):
    module, clipboard, fake = native
    fake.before_open = lambda: fake.copy('Cześć')
    assert clipboard.snapshot(21) == (None, 22)
    assert 'empty' not in fake.trace


def test_recopy_during_replacement_allocation_is_never_overwritten(native):
    module, clipboard, fake = native
    fake.on_alloc = lambda: fake.copy('new copy')
    status = clipboard.replace('Cześć', 'Hello', 21)
    if 'copy' in fake.trace:
        assert status == 'changed'
        assert fake.clipboard.text == 'new copy'
    else:
        assert status == 'replaced'
        assert 'copy-blocked' in fake.trace


def test_snapshot_accepts_generation_established_by_delayed_rendering(native):
    module, clipboard, fake = native
    fake.on_get = lambda: setattr(fake.clipboard, 'sequence', 22)
    assert clipboard.snapshot(21) == ('Cześć', 22)
    assert fake.clipboard.opens == fake.clipboard.closes == 1
    assert clipboard.replace('Cześć', 'Hello', 22) == 'replaced'


@pytest.mark.parametrize('owner', ['null', 'invalid', 'foreign'])
def test_writer_requires_valid_window_owned_by_this_process(native, owner):
    module, clipboard, fake = native
    if owner == 'null':
        fake.HWND = 0
    elif owner == 'invalid':
        fake.valid_hwnd = False
    else:
        fake.pid += 1
    assert clipboard.replace('Cześć', 'Hello', 21) == 'unavailable'
    assert fake.clipboard.text == 'Cześć'
    assert 'empty' not in fake.trace
    assert fake.clipboard.opens == 0


@pytest.mark.parametrize('failure', ['fail_alloc', 'fail_lock', 'fail_empty'])
def test_precommit_failures_leave_original_formats_untouched(native, failure):
    module, clipboard, fake = native
    fake.add_format(0xC123, b'{\\rtf1 original}')
    original = fake.format_bytes()
    setattr(fake, failure, True)
    assert clipboard.replace('Cześć', 'Hello', 21) == 'unavailable'
    assert fake.format_bytes() == original
    assert fake.clipboard.text == 'Cześć'


def test_failed_publish_restores_original_unicode_and_registered_formats(native):
    module, clipboard, fake = native
    fake.add_format(1, b'Czesc\0')
    fake.add_format(16, b'\x15\x04\0\0')
    fake.add_format(0xC123, b'{\\rtf1 original}')
    original = fake.format_bytes()
    fake.fail_sets = 1
    assert clipboard.replace('Cześć', 'Hello', 21) == 'failed'
    assert fake.clipboard.text == 'Cześć'
    assert fake.format_bytes() == original
    assert fake.clipboard.opens == fake.clipboard.closes == 1


def test_exception_after_empty_also_attempts_restore_before_closing(native):
    module, clipboard, fake = native
    original = fake.format_bytes()
    def fail():
        raise OSError('simulated native boundary failure')
    fake.on_set = fail
    assert clipboard.replace('Cześć', 'Hello', 21) == 'failed'
    assert fake.format_bytes() == original


@pytest.mark.parametrize('format', [2, 3, 9, 14, 0x80, 0x200, 0x300])
def test_formats_without_safe_memory_backup_fail_before_empty(native, format):
    module, clipboard, fake = native
    fake.add_format(format, b'not an HGLOBAL format')
    original = fake.format_bytes()
    assert clipboard.replace('Cześć', 'Hello', 21) == 'unavailable'
    assert 'empty' not in fake.trace
    assert fake.format_bytes() == original


def test_registered_format_cannot_be_locked_leaves_clipboard_untouched(native):
    module, clipboard, fake = native
    fake.add_format(0xC123, b'rich text')
    fake.sizes[fake.formats[0xC123]] = 0
    assert clipboard.replace('Cześć', 'Hello', 21) == 'unavailable'
    assert 'empty' not in fake.trace
    assert fake.clipboard.text == 'Cześć'


@pytest.mark.parametrize('data', [b'\x00', b'A\0B\0', b'\0\xd8\0\0'])
def test_malformed_unicode_is_unavailable_not_an_unbounded_read(native, data):
    module, clipboard, fake = native
    fake.on_get = lambda: fake.add_format(13, data)
    assert clipboard.snapshot() == (None, None)


def test_oversized_global_memory_is_rejected_without_locking(native):
    module, clipboard, fake = native
    fake.on_get = lambda: fake.sizes.__setitem__(fake.formats[13], module.MAX_CLIPBOARD_BYTES + 2)
    assert clipboard.snapshot() == (None, None)
    assert 'lock' not in fake.trace


def test_read_exception_unlocks_memory_and_closes_native_clipboard(native, monkeypatch):
    module, clipboard, fake = native
    def fail(*args):
        raise ValueError('cannot copy buffer')
    monkeypatch.setattr(module.ctypes, 'string_at', fail)
    assert clipboard.snapshot() == (None, None)
    assert fake.clipboard.closes == 1
    assert 'unlock' in fake.trace


def test_enumeration_error_fails_before_empty(native):
    module, clipboard, fake = native
    def fail(previous):
        fake.last_error = 5
        return 0
    fake.user32.EnumClipboardFormats.function = fail
    assert clipboard.replace('Cześć', 'Hello', 21) == 'unavailable'
    assert 'empty' not in fake.trace


def test_native_busy_does_not_sleep_or_close_someone_elses_lock(native):
    module, clipboard, fake = native
    fake.clipboard.open_ok = False
    assert clipboard.snapshot(21) == (None, None)
    assert clipboard.replace('Cześć', 'Hello', 21) == 'unavailable'
    assert fake.clipboard.closes == 0


@pytest.mark.parametrize('stage', ['before_empty', 'after_empty'])
def test_cancellation_never_publishes_translation_and_restores_if_needed(native, stage):
    module, clipboard, fake = native
    original = fake.format_bytes()
    if stage == 'before_empty':
        cancelled = lambda: True
    else:
        cancelled = lambda: 'empty' in fake.trace
    assert clipboard.replace('Cześć', 'Hello', 21, cancelled) == 'cancelled'
    assert fake.clipboard.writes == []
    assert fake.clipboard.text == 'Cześć'
    assert fake.format_bytes() == original
    assert ('empty' in fake.trace) == (stage == 'after_empty')


def test_failed_lock_of_allocated_replacement_frees_memory_without_emptying(native):
    module, clipboard, fake = native
    lock = fake.kernel32.GlobalLock.function
    fake.kernel32.GlobalLock.function = lambda handle: lock(handle) if handle in fake.owned else 0
    assert clipboard.replace('Cześć', 'Hello', 21) == 'unavailable'
    assert 'free' in fake.trace
    assert 'empty' not in fake.trace


def test_copy_to_allocated_replacement_exception_unlocks_and_frees(native, monkeypatch):
    module, clipboard, fake = native
    def fail(*args):
        raise ValueError('cannot copy buffer')
    monkeypatch.setattr(module.ctypes, 'memmove', fail)
    assert clipboard.replace('Cześć', 'Hello', 21) == 'unavailable'
    assert fake.trace[-3:] == ['unlock', 'free', 'close']
    assert 'empty' not in fake.trace


def test_backup_allocation_failure_frees_earlier_allocations_without_emptying(native):
    module, clipboard, fake = native
    allocate = fake.kernel32.GlobalAlloc.function
    calls = []
    def allocate_once(flags, size):
        calls.append(size)
        return allocate(flags, size) if len(calls) == 1 else 0
    fake.kernel32.GlobalAlloc.function = allocate_once
    assert clipboard.replace('Cześć', 'Hello', 21) == 'unavailable'
    assert len(calls) == 2
    assert 'free' in fake.trace
    assert 'empty' not in fake.trace


def test_backups_have_a_bounded_total_and_format_count(native, monkeypatch):
    module, clipboard, fake = native
    monkeypatch.setattr(module, 'MAX_CLIPBOARD_BYTES', 32)
    fake.add_format(0xC123, b'R' * 32)
    assert clipboard.replace('Cześć', 'Hello', 21) == 'unavailable'
    assert 'empty' not in fake.trace
    monkeypatch.setattr(module, 'MAX_CLIPBOARD_FORMATS', 1)
    assert clipboard.replace('Cześć', 'Hello', 21) == 'unavailable'
    assert 'empty' not in fake.trace


@pytest.mark.parametrize('translated', ['Hello\0hidden', '\ud800'])
def test_invalid_replacement_is_rejected_without_touching_original(native, translated):
    module, clipboard, fake = native
    assert clipboard.replace('Cześć', translated, 21) == 'unavailable'
    assert fake.clipboard.opens == 0
    assert fake.clipboard.text == 'Cześć'


def test_restore_prioritizes_unicode_even_if_another_format_cannot_be_restored(native):
    module, clipboard, fake = native
    fake.add_format(0xC123, b'original rich text')
    publish = fake.user32.SetClipboardData.function
    fake.fail_sets = 1
    fake.user32.SetClipboardData.function = lambda fmt, handle: 0 if fmt == 0xC123 else publish(fmt, handle)
    assert clipboard.replace('Cześć', 'Hello', 21) == 'failed'
    assert fake.clipboard.text == 'Cześć'
    assert fake.clipboard.writes == []


def test_ctypes_signatures_are_pointer_sized_for_both_handle_and_memory_results(native):
    module, clipboard, fake = native
    for name in ('GetClipboardData', 'SetClipboardData'):
        function = getattr(fake.user32, name)
        assert ctypes.sizeof(function.restype) == ctypes.sizeof(ctypes.c_void_p)
    for name in ('GlobalAlloc', 'GlobalLock', 'GlobalFree', 'GlobalSize'):
        function = getattr(fake.kernel32, name)
        assert ctypes.sizeof(function.restype) == ctypes.sizeof(ctypes.c_void_p)
    assert ctypes.sizeof(fake.user32.OpenClipboard.argtypes[0]) == ctypes.sizeof(ctypes.c_void_p)
    assert ctypes.sizeof(fake.user32.SetClipboardData.argtypes[1]) == ctypes.sizeof(ctypes.c_void_p)
    assert ctypes.sizeof(fake.kernel32.GlobalAlloc.argtypes[1]) == ctypes.sizeof(ctypes.c_void_p)
    for name in ('GlobalLock', 'GlobalUnlock', 'GlobalFree', 'GlobalSize'):
        assert ctypes.sizeof(getattr(fake.kernel32, name).argtypes[0]) == ctypes.sizeof(ctypes.c_void_p)
    assert ctypes.sizeof(fake.user32.GetClipboardSequenceNumber.restype) == 4
