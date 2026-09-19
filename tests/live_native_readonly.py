"""Opt-in REAL Win32 lock/reentrancy probe. Never reads or writes clipboard data."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time


def main():
    import wx
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    path = Path(__file__).resolve().parents[1] / 'addon/globalPlugins/TranslateAdvanced/app/utils/utils_clipboard_win32.py'
    spec = importlib.util.spec_from_file_location('readonly_native_clipboard', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = wx.App(False)
    frame = wx.Frame(None, title='Hidden read-only clipboard probe')
    native = module.Win32Clipboard(lambda: frame.GetHandle())
    calls = []
    def forbid(*args):
        calls.append('data operation')
        raise AssertionError('Clipboard data operations forbidden')
    native.user32.EmptyClipboard = forbid
    native.user32.SetClipboardData = forbid
    native.user32.GetClipboardData = forbid
    report = {'read_only': True, 'live_nvda_modified': False}
    opened = False
    try:
        for _ in range(40):
            opened = native._open()
            if opened:
                break
            time.sleep(0.025)
        assert opened, 'Clipboard stayed busy; nothing changed'
        before = native.sequence()
        report['same_hwnd_raw_open_succeeds'] = bool(native.user32.OpenClipboard(frame.GetHandle()))
        assert native.snapshot() == (None, None)
        report['nested_read_rejected'] = True
        script = ('import ctypes;u=ctypes.windll.user32;v=bool(u.OpenClipboard(None));'
                  'print(int(v));u.CloseClipboard() if v else None')
        probe = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, timeout=10)
        assert probe.returncode == 0 and probe.stdout.strip() == '0'
        report['other_process_still_blocked'] = True
        assert native.sequence() == before
        report['sequence_unchanged_while_locked'] = True
        native._close()
        opened = False
        for _ in range(40):
            opened = native._open()
            if opened:
                break
            time.sleep(0.025)
        assert opened
        report['guard_reusable_after_close'] = True
        assert not calls
        report['clipboard_data_operations'] = 0
    finally:
        if opened:
            native._close()
        frame.Destroy()
    Path(args.output).write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
