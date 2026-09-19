"""Real clipboard manager/command; only OS, NVDA and HTTPS are substituted."""
import ast
import builtins
import ctypes
from collections import deque
import importlib.util
import io
import json
import pathlib
import queue
import sys
import threading
import types
import unittest
from unittest.mock import patch

from nvda_harness import manager_class
from clipboard_win32_fake import Win32ClipboardFake

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'addon/globalPlugins/TranslateAdvanced/__init__.py'
APP = PLUGIN.parent / 'app'


def load_method(path, class_name, method_name, globals_dict=None):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == method_name)
    method.decorator_list = []
    module = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
    namespace = dict(globals_dict or {})
    exec(compile(module, str(path), 'exec'), namespace)
    return namespace[method_name]


def load_class(path, class_name, namespace):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    cls.decorator_list = []
    for method in cls.body:
        if isinstance(method, ast.FunctionDef):
            method.decorator_list = []
    module = ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[]))
    exec(compile(module, str(path), 'exec'), namespace)
    return namespace[class_name]


class TextData:
    def __init__(self, text=''):
        self.text = text

    def GetText(self):
        return self.text

    def SetText(self, text):
        self.text = text


class Timer:
    def __init__(self, milliseconds, fn, *args):
        assert milliseconds > 0
        self.fn, self.args = fn, args
        self.stopped = False

    def Stop(self):
        self.stopped = True

    def fire(self):
        if not self.stopped:
            self.stopped = True
            self.fn(*self.args)


class FakeClipboard:
    def __init__(self, text='Cześć'):
        self.text, self.sequence = text, 21
        self.open_ok = self.get_ok = self.set_ok = True
        self.has_text = True
        self.is_open = False  # wxMSW Open is a logical flag, not an OS lock.
        self.native_open = False
        self.opens = self.closes = 0
        self.writes = []
        self.owner = threading.get_ident()

    def Open(self):
        assert threading.get_ident() == self.owner, 'Clipboard accessed by worker'
        self.opens += 1
        self.is_open = self.open_ok
        return self.open_ok

    def Close(self):
        assert self.is_open, 'Close without successful Open'
        self.closes += 1
        self.is_open = False

    def IsSupported(self, format):
        assert self.is_open
        return self.has_text

    def GetData(self, data):
        assert self.is_open
        data.SetText(self.text)
        return self.get_ok

    def SetData(self, data):
        assert self.is_open
        if self.set_ok:
            self.text = data.GetText()
            self.sequence += 1
            self.writes.append(self.text)
        return self.set_ok

    def Flush(self):
        assert self.is_open
        return True

    def copy(self, text):
        assert not self.native_open
        self.text = text
        self.sequence += 1


class ClipboardFixture(unittest.TestCase):
    def setUp(self):
        # An incomplete fake must fail, never access a Windows user's clipboard.
        for name, replacement in (
                ('WinDLL', lambda *args, **kwargs: self.fail('Real WinDLL is forbidden in unit tests')),
                ('windll', None)):
            guard = patch.object(ctypes, name, replacement, create=True)
            guard.start()
            self.addCleanup(guard.stop)
        self.clipboard = FakeClipboard()
        self.wx = types.SimpleNamespace(
            Clipboard=types.SimpleNamespace(Get=lambda: self.clipboard),
            TextDataObject=TextData, DataFormat=lambda value: value, DF_TEXT=1, DF_UNICODETEXT=13,
        )
        package = types.ModuleType('clipboard_test_app')
        package.__path__ = [str(APP)]
        self.native = Win32ClipboardFake(self.clipboard)
        spec = importlib.util.spec_from_file_location('clipboard_test_app.managers.managers_clipboard', APP / 'managers/managers_clipboard.py')
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
            'clipboard_test_app': package,
            'wx': self.wx,
            'addonHandler': types.SimpleNamespace(initTranslation=lambda: None),
            'logHandler': types.SimpleNamespace(log=types.SimpleNamespace(error=lambda *a: None)),
        }), patch.object(builtins, '_', lambda s: s, create=True):
            spec.loader.exec_module(self.module)
        self.module.__dict__['_'] = lambda s: s
        # Fail closed: every native dependency is replaced before constructing
        # the monitor. This suite must NEVER fall through to the OS clipboard.
        native_class = self.module.Win32Clipboard
        self.module.Win32Clipboard = lambda owner: native_class(
            lambda: self.native.HWND, user32=self.native.user32, kernel32=self.native.kernel32)
        self.monitor = self.module.ClipboardMonitor(None)
        self.addCleanup(self.native.assert_clean)


class ClipboardSafetyTests(ClipboardFixture):
    def test_wx_logical_open_cannot_exclude_a_copy_before_setdata(self):
        original_set_text = TextData.SetText
        newer_copies = []
        def set_text(data, text):
            if text == 'Hello':
                self.clipboard.copy('newer user copy')
                newer_copies.append(text)
            original_set_text(data, text)
        # The old implementation lets this copy through wx.Open, then destroys it.
        with patch.object(TextData, 'SetText', set_text):
            status = self.monitor.replace_clipboard_text('Cześć', 'Hello', 21)
        if newer_copies:
            self.assertNotEqual('replaced', status)
            self.assertEqual('newer user copy', self.clipboard.text)
        else:
            self.assertEqual('replaced', status)

    def test_compare_and_replace_is_one_locked_clipboard_transaction(self):
        self.assertTrue(hasattr(self.monitor, 'replace_clipboard_text'), 'Safe compare-and-replace is missing')
        status = self.monitor.replace_clipboard_text('Cześć', 'Hello', expected_sequence=21)
        self.assertEqual('replaced', status)
        self.assertEqual(['Hello'], self.clipboard.writes)
        self.assertEqual((1, 1), (self.clipboard.opens, self.clipboard.closes))

    def test_newer_copy_even_identical_text_is_preserved(self):
        for text in ('new copy', 'Cześć'):
            with self.subTest(text=text):
                self.clipboard.copy(text)
                self.assertEqual('changed', self.monitor.replace_clipboard_text('Cześć', 'Hello', 21))
                self.assertEqual([], self.clipboard.writes)

    def test_false_open_getdata_setdata_are_unavailable_and_close_only_if_open(self):
        for field in ('open_ok', 'get_ok', 'set_ok'):
            with self.subTest(field=field):
                self.setUp()
                setattr(self.clipboard, field, False)
                status = 'failed' if field == 'set_ok' else 'unavailable'
                self.assertEqual(status, self.monitor.replace_clipboard_text('Cześć', 'Hello', 21))
                self.assertEqual([], self.clipboard.writes)
                self.assertEqual('Cześć', self.clipboard.text)
                self.assertEqual(0 if field == 'open_ok' else 1, self.clipboard.closes)

    def test_snapshot_reads_text_and_generation_while_open(self):
        def sequence():
            self.assertTrue(self.native.opened)
            return self.clipboard.sequence
        self.native.user32.GetClipboardSequenceNumber.function = sequence
        self.assertTrue(hasattr(self.monitor, 'get_clipboard_snapshot'), 'Atomic snapshot is missing')
        self.assertEqual(('Cześć', 21), self.monitor.get_clipboard_snapshot())
        self.assertEqual((1, 1), (self.clipboard.opens, self.clipboard.closes))

    def test_read_checks_false_open_and_getdata(self):
        for field in ('open_ok', 'get_ok'):
            with self.subTest(field=field):
                self.setUp()
                setattr(self.clipboard, field, False)
                self.assertIsNone(self.monitor.get_clipboard_text())
                self.assertEqual(0 if field == 'open_ok' else 1, self.clipboard.closes)

    def test_write_reports_false_open_or_setdata(self):
        for field in ('open_ok', 'set_ok', None):
            with self.subTest(field=field):
                self.setUp()
                if field:
                    setattr(self.clipboard, field, False)
                self.assertIs(field is None, self.monitor.set_clipboard_text('Hello'))
                self.assertEqual(0 if field == 'open_ok' else 1, self.clipboard.closes)

    def test_clear_checks_open_and_closes_only_after_success(self):
        self.clipboard.Clear = lambda: setattr(self.clipboard, 'text', '')
        self.clipboard.open_ok = False
        self.assertIs(False, self.monitor.clear_clipboard())
        self.assertEqual(0, self.clipboard.closes)
        self.clipboard.open_ok = True
        self.assertIs(True, self.monitor.clear_clipboard())
        self.assertEqual('', self.clipboard.text)
        self.assertEqual(1, self.clipboard.closes)

    def test_new_generation_without_readable_text_is_changed_not_retryable(self):
        self.clipboard.copy('new data')
        self.clipboard.get_ok = False
        self.assertEqual('changed', self.monitor.replace_clipboard_text('Cześć', 'Hello', 21))
        self.assertEqual([], self.clipboard.writes)


class CommandTests(ClipboardFixture):
    def setUp(self):
        super().setUp()
        self.main_thread = threading.get_ident()
        self.callbacks = queue.Queue()
        self.wx.CallAfter = lambda fn, *a, **kw: self.callbacks.put((fn, a, kw))
        self.timers = deque()
        def later(delay, fn, *args):
            timer = Timer(delay, fn, *args)
            self.timers.append(timer)
            return timer
        self.wx.CallLater = later
        self.spoken = []
        self.settings = types.SimpleNamespace(
            choiceOnline=5, chkAltLang=True, choiceLangDestino_deepl='pl',
            choiceLangDestino_google='es', choiceLangDestino_google_def='pl',
            choiceLangDestino_google_alt='en', choiceLangDestino_openai='pl',
            api_deepl_pro=0, _enableTranslation=True, chkCache=False,
            historialOrigen=deque(), historialDestino=deque(), _lastTranslatedText=None,
            IS_WinON=False, is_active_translate=False,
        )
        self.manager_module = manager_class()
        self.manager = self.manager_module.GestorTranslate.__new__(self.manager_module.GestorTranslate)
        self.manager.frame = types.SimpleNamespace(gestor_settings=self.settings,
            gestor_apis=types.SimpleNamespace(get_api=lambda *a: {'key': 'test-key'}))
        def message(text):
            self.assertEqual(self.main_thread, threading.get_ident())
            self.spoken.append((text, self.clipboard.text, self.settings._enableTranslation))
        def forbidden_preflight():
            raise AssertionError('Clipboard must not call synchronous internet preflight')
        self.namespace = {
            '_': lambda s: s, 'Thread': threading.Thread, 'Event': threading.Event,
            'wx': self.wx, 'ui': types.SimpleNamespace(message=message),
            'globalPluginHandler': types.SimpleNamespace(GlobalPlugin=type('Base', (), {'terminate': lambda s: None})),
            'check_internet_connection': forbidden_preflight,
        }
        plugin_class = load_class(PLUGIN, 'GlobalPlugin', self.namespace)
        self.plugin = plugin_class.__new__(plugin_class)
        self.plugin.switch = False
        self.plugin.IS_OK = False
        self.plugin._terminating = False
        self.plugin._clipboard_job = None
        self.plugin.gestor_settings = self.settings
        self.plugin.gestor_portapapeles = self.monitor
        self.plugin.gestor_translate = self.manager
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()
        self.network_error = None
        self.enterContext(patch('urllib.request.urlopen', self.https))
        def cleanup_worker():
            self.release.set()
            job = getattr(self.plugin, '_clipboard_job', None)
            if job is not None:
                job.set()
            worker = getattr(self.plugin, '_clipboard_thread', None)
            if worker is not None:
                worker.join(3)
        self.addCleanup(cleanup_worker)

    def https(self, request, **kwargs):
        self.assertNotEqual(self.main_thread, threading.get_ident(), 'Provider ran on NVDA thread')
        self.assertTrue(threading.current_thread().daemon)
        self.assertTrue(self.settings._enableTranslation, 'Worker changed incoming live translation')
        payload = json.loads(request.data)
        self.calls.append((request.full_url, payload, kwargs))
        self.entered.set()
        self.assertTrue(self.release.wait(3), 'Test did not release provider')
        if self.network_error:
            raise self.network_error
        source = payload['text'][0]
        lang = 'EN' if source == 'Hello' else 'PL'
        result = 'Cześć' if lang == 'EN' else 'Hello'
        if payload['target_lang'] == lang:
            result = source
        return io.BytesIO(json.dumps({'translations': [{
            'text': result, 'detected_source_language': lang,
        }]}).encode())

    def test_short_direct_provider_errors_are_localized_sanitized_and_release_busy(self):
        self.plugin.chk_banderas = lambda *args: not self.settings.is_active_translate
        self.settings.ultimo_texto = 'Cześć'
        self.namespace['api'] = types.SimpleNamespace(
            getNavigatorObject=lambda: types.SimpleNamespace(name='Cześć'))
        generic = 'No se ha podido obtener la traducción de lo seleccionado.'
        self.namespace['_'] = lambda text: {generic: 'Nie udało się uzyskać tłumaczenia.'}.get(text, text)
        def failure(text):
            self.assertTrue(self.settings.is_active_translate)
            self.assertFalse(self.settings._enableTranslation)
            raise RuntimeError('Authorization: Bearer secret-test-key; private input')
        self.manager.translate_various = failure
        for name in ('script_obj_translate', 'script_speackLastTranslation'):
            with self.subTest(command=name):
                self.settings.is_active_translate = False
                self.settings._enableTranslation = True
                self.spoken.clear()
                getattr(self.plugin, name)(None)
                self.assertFalse(self.settings.is_active_translate)
                self.assertTrue(self.settings._enableTranslation)
                self.assertEqual([('Nie udało się uzyskać tłumaczenia.', 'Cześć', False)], self.spoken)
                self.assertIsNone(self.plugin._clipboard_job)
                self.assertEqual([], self.clipboard.writes)
                self.assertEqual([], list(self.settings.historialDestino))

    def test_short_direct_commands_restore_previous_mode_even_if_speech_fails(self):
        self.plugin.chk_banderas = lambda *args: not self.settings.is_active_translate
        self.settings.ultimo_texto = 'Cześć'
        self.namespace['api'] = types.SimpleNamespace(
            getNavigatorObject=lambda: types.SimpleNamespace(name='Cześć'))
        self.manager.translate_various = lambda text: 'Hello'
        def speak(text):
            self.assertTrue(self.settings.is_active_translate)
            self.assertFalse(self.settings._enableTranslation)
            self.assertEqual('Hello', text)
            raise OSError('speech unavailable')
        self.namespace['ui'].message = speak
        for command in ('script_obj_translate', 'script_speackLastTranslation'):
            for enabled in (True, False):
                with self.subTest(command=command, enabled=enabled):
                    self.settings._enableTranslation = enabled
                    with self.assertRaisesRegex(OSError, 'speech unavailable'):
                        getattr(self.plugin, command)(None)
                    self.assertFalse(self.settings.is_active_translate)
                    self.assertEqual(enabled, self.settings._enableTranslation)

    def test_translated_errors_before_start_are_spoken_in_ui_language(self):
        def bad_options(**kwargs):
            raise RuntimeError('Example backend error')
        self.manager.translation_options = bad_options
        self.namespace['_'] = lambda text: {'Example backend error':'Przykładowy błąd usługi'}.get(text, text)
        self.plugin.script_ClipboardTranslation(None)
        self.assertEqual('Przykładowy błąd usługi', self.spoken[-1][0])
        self.assertEqual('Cześć', self.clipboard.text)

    def test_translated_errors_after_worker_are_formatted_in_ui_language(self):
        def failure(text, options):
            raise RuntimeError('Example backend error')
        self.manager.translate_with_options = failure
        self.namespace['_'] = lambda text: {
            'Example backend error':'Przykładowy błąd usługi',
            'Translation failed. Clipboard was not changed. {0}':'Błąd tłumaczenia. Schowek bez zmian. {0}',
        }.get(text, text)
        self.plugin.script_ClipboardTranslation(None)
        self.complete()
        self.assertEqual('Błąd tłumaczenia. Schowek bez zmian. Przykładowy błąd usługi', self.spoken[-1][0])
        self.assertEqual('Cześć', self.clipboard.text)

    def complete(self):
        worker = getattr(self.plugin, '_clipboard_thread', None)
        self.assertIsNotNone(worker, 'Clipboard translation did not start a worker')
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.drain()

    def drain(self):
        for _ in range(30):
            if not self.callbacks.empty():
                fn, args, kwargs = self.callbacks.get_nowait()
                fn(*args, **kwargs)
            elif self.timers:
                self.timers.popleft().fire()
            else:
                return
        self.fail('Unbounded clipboard retries')

    def test_real_command_async_both_directions_all_length_paths(self):
        for source in ('Cześć', 'Hello', 'x' * 2999, 'x' * 3000, 'x' * 4000):
            with self.subTest(length=len(source), start=source[:5]):
                self.clipboard.copy(source)
                self.clipboard.writes.clear()
                self.spoken.clear()
                self.calls.clear()
                self.entered.clear()
                self.release.clear()
                try:
                    with patch('urllib.request.urlopen', self.https):
                        self.plugin.script_ClipboardTranslation(None)
                        self.assertTrue(self.entered.wait(1))
                        self.assertEqual([], self.spoken)
                        self.assertEqual([], self.clipboard.writes)
                        self.assertTrue(self.settings._enableTranslation)
                        self.release.set()
                        self.complete()
                finally:
                    self.release.set()
                expected = 'Cześć' if source == 'Hello' else 'Hello'
                self.assertEqual([expected], self.clipboard.writes)
                self.assertEqual([(expected, expected, False)], self.spoken)
                self.assertIn(expected, self.settings.historialDestino)
                self.assertTrue(self.settings._enableTranslation)
                self.assertFalse(self.settings.is_active_translate)
                self.assertIsNone(self.plugin._clipboard_job)
                self.assertTrue(all(url == 'https://api.deepl.com/v2/translate' for url, _, _ in self.calls))

    def test_failures_and_timeout_never_copy_or_record(self):
        for error in (TimeoutError('provider timeout'), RuntimeError('bad response')):
            with self.subTest(error=type(error).__name__):
                self.network_error = error
                self.spoken.clear()
                with patch('urllib.request.urlopen', self.https):
                    self.plugin.script_ClipboardTranslation(None)
                    self.complete()
                self.assertEqual([], self.clipboard.writes)
                self.assertEqual([], list(self.settings.historialDestino))
                self.assertEqual(1, len(self.spoken))
                self.assertNotEqual('Cześć', self.spoken[0][0])
                self.assertTrue(self.settings._enableTranslation)
                self.assertFalse(self.settings.is_active_translate)

    def test_new_copy_is_not_overwritten_or_spoken_as_translation(self):
        for text in ('new content', 'Cześć'):
            with self.subTest(text=text):
                self.clipboard.copy('Cześć')
                self.spoken.clear()
                with patch('urllib.request.urlopen', self.https):
                    self.plugin.script_ClipboardTranslation(None)
                    self.plugin._clipboard_thread.join(3)
                    self.clipboard.copy(text)
                    self.complete()
                self.assertEqual(text, self.clipboard.text)
                self.assertEqual([], self.clipboard.writes)
                self.assertEqual([], list(self.settings.historialDestino))
                self.assertEqual(1, len(self.spoken))
                self.assertIn('changed', self.spoken[0][0])

    def test_cannot_copy_means_no_success_speech(self):
        with patch('urllib.request.urlopen', self.https):
            self.plugin.script_ClipboardTranslation(None)
            self.plugin._clipboard_thread.join(3)
            self.clipboard.set_ok = False
            self.complete()
        self.assertEqual([], self.clipboard.writes)
        self.assertIn('unavailable', self.spoken[0][0])
        self.assertEqual([], list(self.settings.historialDestino))

    def test_settings_snapshot_is_not_changed_during_provider_request(self):
        self.release.clear()
        try:
            with patch('urllib.request.urlopen', self.https):
                self.plugin.script_ClipboardTranslation(None)
                self.assertTrue(self.entered.wait(1))
                self.settings.choiceOnline = 9
                self.settings.choiceLangDestino_google_def = 'uk'
                self.settings.choiceLangDestino_google_alt = 'de'
                self.release.set()
                self.complete()
        finally:
            self.release.set()
        self.assertEqual(['PL', 'EN'], [payload['target_lang'] for _, payload, _ in self.calls])
        self.assertEqual((9, 'uk', 'de'), (self.settings.choiceOnline,
            self.settings.choiceLangDestino_google_def, self.settings.choiceLangDestino_google_alt))

    def test_over_limit_is_explicit_not_truncated_and_no_request(self):
        self.clipboard.copy('x' * 24001)
        with patch('urllib.request.urlopen', self.https):
            self.plugin.script_ClipboardTranslation(None)
            self.complete()
        self.assertEqual([], self.calls)
        self.assertEqual([], self.clipboard.writes)
        self.assertIn('24000', self.spoken[0][0])
        self.assertFalse(self.settings.is_active_translate)

    def test_repeat_cancels_and_late_completion_cannot_affect_next_job(self):
        with patch('urllib.request.urlopen', self.https):
            self.plugin.script_ClipboardTranslation(None)
            first_job = self.plugin._clipboard_job
            self.plugin._clipboard_thread.join(3)
            self.plugin.script_ClipboardTranslation(None)
            self.assertTrue(first_job.is_set(), 'Repeat shortcut did not cancel')
            self.assertIsNone(self.plugin._clipboard_job)
            self.assertFalse(self.settings.is_active_translate)
            self.spoken.clear()
            self.clipboard.copy('Hello')
            self.plugin.script_ClipboardTranslation(None)
            self.complete()
        self.assertEqual(['Cześć'], self.clipboard.writes)
        self.assertEqual([('Cześć', 'Cześć', False)], self.spoken)

    def test_terminate_cancels_pending_callbacks_and_closes_codex_clients(self):
        closed = []
        self.namespace['__package__'] = 'ta_clipboard_plugin'
        codex = types.ModuleType('ta_clipboard_plugin.app.utils.utils_codex')
        codex.close_clients = lambda: closed.append(True)
        with patch('urllib.request.urlopen', self.https), patch.dict(sys.modules, {codex.__name__: codex}):
            self.plugin.script_ClipboardTranslation(None)
            job = self.plugin._clipboard_job
            self.plugin._clipboard_thread.join(3)
            self.plugin.terminate()
            self.plugin.terminate()
            self.assertTrue(job.is_set(), 'Unload did not cancel')
            self.assertTrue(self.plugin._terminating)
            self.assertEqual([True], closed)
            self.plugin.gestor_settings = None  # queued callbacks must not dereference destroyed NVDA
            self.plugin.gestor_portapapeles = None
            self.drain()
        self.assertEqual([], self.clipboard.writes)
        self.assertEqual([], self.spoken)

    def test_speech_exception_restores_live_switch_and_clears_busy(self):
        def fail(text):
            raise RuntimeError('speech unavailable')
        self.namespace['ui'].message = fail
        with patch('urllib.request.urlopen', self.https):
            self.plugin.script_ClipboardTranslation(None)
            with self.assertRaisesRegex(RuntimeError, 'speech unavailable'):
                self.complete()
        self.assertTrue(self.settings._enableTranslation)
        self.assertFalse(self.settings.is_active_translate)
        self.assertIsNone(self.plugin._clipboard_job)

    def test_busy_snapshot_retries_asynchronously_then_translates(self):
        for field in ('open_ok', 'get_ok'):
            with self.subTest(field=field):
                self.setUp()
                setattr(self.clipboard, field, False)
                with patch('urllib.request.urlopen', self.https):
                    self.plugin.script_ClipboardTranslation(None)
                    self.assertTrue(self.settings.is_active_translate)
                    self.assertEqual([], self.spoken)
                    self.assertEqual([], self.calls)
                    self.assertEqual(1, len(self.timers), 'Busy read was not scheduled for retry')
                    setattr(self.clipboard, field, True)
                    self.timers.popleft().fire()
                    self.complete()
                self.assertEqual(['Hello'], self.clipboard.writes)
                self.assertEqual([('Hello', 'Hello', False)], self.spoken)

    def test_busy_read_retries_are_bounded_and_report_unavailable_not_empty(self):
        self.clipboard.open_ok = False
        self.plugin.script_ClipboardTranslation(None)
        self.drain()
        self.assertGreater(self.clipboard.opens, 1)
        self.assertLessEqual(self.clipboard.opens, 6)
        self.assertEqual([], self.clipboard.writes)
        self.assertEqual(1, len(self.spoken))
        self.assertIn('unavailable', self.spoken[0][0])
        self.assertFalse(self.settings.is_active_translate)
        self.assertIsNone(self.plugin._clipboard_job)

    def test_cancel_during_native_replace_does_not_copy_or_speak(self):
        self.plugin.script_ClipboardTranslation(None)
        self.plugin._clipboard_thread.join(3)
        self.native.on_get = self.plugin._cancel_clipboard_translation
        self.complete()
        self.assertEqual('Cześć', self.clipboard.text)
        self.assertEqual([], self.clipboard.writes)
        self.assertEqual([], self.spoken)
        self.assertEqual([], list(self.settings.historialDestino))
        self.assertFalse(self.settings.is_active_translate)

    def test_cancel_during_delayed_render_does_not_start_a_stale_worker(self):
        self.native.on_get = self.plugin._cancel_clipboard_translation
        self.plugin.script_ClipboardTranslation(None)
        worker = getattr(self.plugin, '_clipboard_thread', None)
        if worker is not None:
            worker.join(3)
        self.assertEqual([], self.calls)
        self.assertEqual([], self.clipboard.writes)
        self.assertEqual([], self.spoken)
        self.assertFalse(self.settings.is_active_translate)
        self.assertIsNone(self.plugin._clipboard_job)

    def test_new_copy_between_precheck_and_native_lock_is_not_translated(self):
        self.native.before_open = lambda: self.clipboard.copy('Cześć')
        self.plugin.script_ClipboardTranslation(None)
        self.assertEqual([], self.calls)
        self.assertEqual([], self.clipboard.writes)
        self.assertEqual([], list(self.timers))
        self.assertIn('changed', self.spoken[0][0])
        self.assertFalse(self.settings.is_active_translate)

    def test_new_copy_after_rendered_snapshot_is_preserved_at_commit(self):
        self.native.on_get = lambda: setattr(self.clipboard, 'sequence', self.clipboard.sequence + 1)
        self.release.clear()
        self.plugin.script_ClipboardTranslation(None)
        try:
            self.assertTrue(self.entered.wait(1))
            self.clipboard.copy('Cześć')
        finally:
            self.release.set()
        self.complete()
        self.assertEqual([], self.clipboard.writes)
        self.assertEqual('Cześć', self.clipboard.text)
        self.assertIn('changed', self.spoken[0][0])
        self.assertFalse(self.settings.is_active_translate)

    def test_delayed_rendering_establishes_generation_and_is_translated(self):
        def rendered():
            self.clipboard.sequence += 1
        self.native.on_get = rendered
        self.plugin.script_ClipboardTranslation(None)
        self.assertTrue(self.entered.wait(1), 'Valid delayed render was mistaken for a new copy')
        self.complete()
        self.assertEqual(['Hello'], self.clipboard.writes)
        self.assertFalse(self.settings.is_active_translate)

    def test_successful_nontext_read_is_not_retried_as_busy(self):
        self.clipboard.has_text = False
        self.plugin.script_ClipboardTranslation(None)
        self.assertEqual([], list(self.timers))
        self.assertEqual([], self.calls)
        self.assertEqual(1, len(self.spoken))
        self.assertIn('No hay nada', self.spoken[0][0])
        self.assertFalse(self.settings.is_active_translate)

    def test_new_copy_even_same_text_during_read_retry_is_never_translated(self):
        self.clipboard.open_ok = False
        self.plugin.script_ClipboardTranslation(None)
        self.clipboard.copy('Cześć')
        self.clipboard.open_ok = True
        with patch('urllib.request.urlopen', self.https):
            self.drain()
        self.assertEqual([], self.calls)
        self.assertEqual([], self.clipboard.writes)
        self.assertIn('changed', self.spoken[-1][0])
        self.assertFalse(self.settings.is_active_translate)

    def test_busy_final_replace_retries_then_copies_before_speaking(self):
        with patch('urllib.request.urlopen', self.https):
            self.plugin.script_ClipboardTranslation(None)
            self.plugin._clipboard_thread.join(3)
            self.clipboard.open_ok = False
            fn, args, kwargs = self.callbacks.get_nowait()
            fn(*args, **kwargs)
            self.assertTrue(self.settings.is_active_translate)
            self.assertEqual([], self.spoken)
            self.assertEqual(1, len(self.timers))
            self.clipboard.open_ok = True
            self.drain()
        self.assertEqual(['Hello'], self.clipboard.writes)
        self.assertEqual([('Hello', 'Hello', False)], self.spoken)
        self.assertFalse(self.settings.is_active_translate)

    def test_repeat_cancels_pending_read_retry_and_suppresses_already_queued_timer(self):
        self.clipboard.open_ok = False
        self.plugin.script_ClipboardTranslation(None)
        self.assertEqual(1, len(self.timers))
        timer = self.timers[0]
        self.plugin.script_ClipboardTranslation(None)
        self.assertTrue(timer.stopped)
        self.assertFalse(self.settings.is_active_translate)
        self.spoken.clear()
        self.clipboard.open_ok = True
        timer.fn(*timer.args)  # A timer callback might already be queued by wx.
        self.assertEqual([], self.spoken)
        self.assertEqual([], self.calls)
        self.assertEqual([], self.clipboard.writes)

    def test_terminate_cancels_final_replace_retry_without_touching_destroyed_nvda(self):
        with patch('urllib.request.urlopen', self.https):
            self.plugin.script_ClipboardTranslation(None)
            self.plugin._clipboard_thread.join(3)
            self.clipboard.open_ok = False
            fn, args, kwargs = self.callbacks.get_nowait()
            fn(*args, **kwargs)
        self.assertEqual(1, len(self.timers))
        timer = self.timers[0]
        self.plugin.terminate()
        self.assertTrue(timer.stopped)
        self.plugin.gestor_settings = self.plugin.gestor_portapapeles = None
        timer.fn(*timer.args)
        self.assertEqual([], self.clipboard.writes)
        self.assertEqual([], self.spoken)

    def test_real_command_openai_responses_both_directions_and_long_input(self):
        self.settings.choiceOnline = 9
        self.settings.api_openai = 0
        self.settings.openai_auth_mode = 'api_key'
        self.settings.openai_model_api = 'gpt-4.1-mini'
        requests = []
        def responses(opener, request, **kwargs):
            self.assertNotEqual(self.main_thread, threading.get_ident())
            self.assertTrue(self.settings._enableTranslation)
            payload = json.loads(request.data)
            requests.append((request.full_url, payload))
            source = payload['input'][0]['content'][0]['text']
            detected, target, result = ('en', 'pl', 'Cześć') if source == 'Hello' else ('pl', 'en', 'Hello')
            if source and set(source) == {'x'}:
                # HTTP fixture maps each character, so lost/duplicated chunk text
                # changes the final clipboard value instead of yielding "Hello".
                result = source.replace('x', 'y')
            document = {'translated_text': result, 'detected_source_language': detected, 'target_language': target}
            return io.BytesIO(json.dumps({'status': 'completed', 'output': [{
                'type': 'message', 'role': 'assistant', 'status': 'completed',
                'content': [{'type': 'output_text', 'text': json.dumps(document)}],
            }]}).encode())
        for source in ('Cześć', 'Hello', 'x' * 4000):
            with self.subTest(length=len(source)):
                self.clipboard.copy(source)
                self.clipboard.writes.clear()
                self.spoken.clear()
                requests.clear()
                with patch('urllib.request.OpenerDirector.open', responses):
                    self.plugin.script_ClipboardTranslation(None)
                    self.complete()
                expected = source.replace('x', 'y') if len(source) > 3000 else ('Cześć' if source == 'Hello' else 'Hello')
                self.assertEqual([expected], self.clipboard.writes)
                self.assertEqual([(expected, expected, False)], self.spoken)
                pieces = [payload['input'][0]['content'][0]['text'] for _, payload in requests]
                if len(source) <= 3000:
                    self.assertEqual([source], pieces)
                else:
                    self.assertGreater(len(pieces), 1)
                    self.assertTrue(all(0 < len(piece) <= 2000 for piece in pieces))
                    self.assertTrue(all(piece in source for piece in pieces))
                    self.assertEqual(len(pieces), len(set(pieces)), 'Duplicate chunks must use request-local memo')
                for url, payload in requests:
                    self.assertEqual('https://api.openai.com/v1/responses', url)
                    self.assertEqual('gpt-4.1-mini', payload['model'])
                    self.assertIn('primary target: pl', payload['instructions'])
                    self.assertIn('alternate target: en', payload['instructions'])
                self.assertTrue(self.settings._enableTranslation)

    def test_incomplete_openai_response_is_not_copied_or_spoken(self):
        self.settings.choiceOnline = 9
        self.settings.api_openai = 0
        self.settings.openai_model_api = 'gpt-4.1-mini'
        with patch('urllib.request.OpenerDirector.open', return_value=io.BytesIO(json.dumps({
            'status': 'incomplete', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'partial'}]}],
        }).encode())):
            self.plugin.script_ClipboardTranslation(None)
            self.complete()
        self.assertEqual([], self.clipboard.writes)
        self.assertEqual('Cześć', self.clipboard.text)
        self.assertEqual([], list(self.settings.historialDestino))
        self.assertNotIn('partial', self.spoken[0][0])
        self.assertFalse(self.settings.is_active_translate)

    def test_new_copy_while_final_replace_retries_is_preserved(self):
        self.plugin.script_ClipboardTranslation(None)
        self.plugin._clipboard_thread.join(3)
        self.clipboard.open_ok = False
        fn, args, kwargs = self.callbacks.get_nowait()
        fn(*args, **kwargs)
        self.assertEqual(1, len(self.timers))
        self.clipboard.copy('Cześć')
        self.clipboard.open_ok = True
        self.drain()
        self.assertEqual([], self.clipboard.writes)
        self.assertIn('changed', self.spoken[0][0])
        self.assertEqual([], list(self.settings.historialDestino))
        self.assertFalse(self.settings.is_active_translate)

    def test_worker_construction_failure_releases_busy_state(self):
        def fail(**kwargs):
            raise OSError('worker unavailable')
        self.namespace['Thread'] = fail
        self.plugin.script_ClipboardTranslation(None)
        self.assertFalse(self.settings.is_active_translate)
        self.assertIsNone(self.plugin._clipboard_job)
        self.assertEqual([], self.clipboard.writes)
        self.assertIn('worker unavailable', self.spoken[0][0])


if __name__ == '__main__':
    unittest.main()
