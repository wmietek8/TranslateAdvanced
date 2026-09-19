"""Exercise real progress/GUI classes with main-thread wx and HTTPS boundaries."""
import io
import json
import queue
import threading
import types
import unittest
from collections import deque
from unittest.mock import patch

from nvda_harness import manager_class
from test_clipboard_translation import APP, PLUGIN, load_class, load_method


class Widget:
    def __init__(self, *args, **kwargs):
        self.owner = threading.get_ident()
        self.value = ''
        self.bindings = {}
        self.destroyed = False

    def check(self):
        assert self.owner == threading.get_ident(), 'wx widget touched by worker'
        assert not self.destroyed, 'wx widget touched after destruction'

    def Bind(self, event, fn):
        self.check()
        self.bindings[event] = fn

    def SetValue(self, value):
        self.check()
        self.value = value

    def GetValue(self):
        self.check()
        return self.value

    def Clear(self):
        self.SetValue('')

    def SetFocus(self):
        self.check()

    def GetStringSelection(self):
        return self.GetValue()


class Dialog(Widget):
    def __init__(self, *args, **kwargs):
        super().__init__()
        self.modal_result = None
        self.finish_calls = 0

    def SetTitle(self, title):
        self.check()

    def SetSizer(self, sizer):
        self.check()

    def CenterOnScreen(self):
        self.check()

    def IsModal(self):
        self.check()
        return True

    def EndModal(self, result):
        self.check()
        self.finish_calls += 1
        self.modal_result = result

    def Destroy(self):
        self.check()
        self.destroyed = True
        return True

    def Close(self):
        self.check()
        self.bindings['close'](None)

    def ShowModal(self):
        self.check()
        while self.modal_result is None:
            fn, args, kwargs = self.callback_queue.get(timeout=3)
            fn(*args, **kwargs)
        return self.modal_result


class Sizer:
    def Add(self, *args, **kwargs):
        pass


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.main_thread = threading.get_ident()
        self.callbacks = queue.Queue()
        self.wx = types.SimpleNamespace(
            Dialog=Dialog, Gauge=Widget, Button=Widget, BoxSizer=lambda *a: Sizer(),
            VERTICAL=1, EXPAND=2, ALL=4, ALIGN_CENTER=8, EVT_BUTTON='button',
            EVT_CLOSE='close', EVT_WINDOW_DESTROY='destroy', ID_OK=1, ID_CANCEL=0,
            OK=1, ICON_INFORMATION=2, ICON_WARNING=4, ICON_ERROR=8,
            CallAfter=lambda fn, *a, **kw: self.callbacks.put((fn, a, kw)),
        )
        self.settings = types.SimpleNamespace(choiceOnline=5, chkAltLang=True,
            choiceLangDestino_deepl='pl', choiceLangDestino_google='es',
            choiceLangDestino_google_def='pl', choiceLangDestino_google_alt='en',
            api_deepl_pro=0, _enableTranslation=True, historialOrigen=deque(),
            historialDestino=deque(), _lastTranslatedText=None, is_active_translate=True)
        self.manager_module = manager_class()
        self.manager = self.manager_module.GestorTranslate.__new__(self.manager_module.GestorTranslate)
        self.frame = types.SimpleNamespace(gestor_settings=self.settings, gestor_translate=self.manager,
            gestor_apis=types.SimpleNamespace(get_api=lambda *a: {'key': 'test-key'}), _terminating=False)
        self.manager.frame = self.frame
        def forbidden(*a, **kw):
            raise AssertionError('Unselected Google/detector must not be used')
        self.namespace = {'wx': self.wx, 'threading': threading, '_': lambda s: s,
            'TranslatorGoogleApiFree': forbidden, 'DetectorDeIdioma': forbidden,
            'TextToSpeechGoogle': forbidden}
        self.Progress = load_class(APP / 'guis/guis_progress.py', 'ProgressDialog', self.namespace)
        self.Progress.callback_queue = self.callbacks
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def https(self, request, **kwargs):
        self.assertNotEqual(self.main_thread, threading.get_ident())
        self.assertTrue(threading.current_thread().daemon)
        data = json.loads(request.data)
        self.calls.append((request.full_url, data))
        self.entered.set()
        self.assertTrue(self.release.wait(3))
        source = data['text'][0]
        translated = source if data['target_lang'] == 'PL' else 'Translated GUI text'
        return io.BytesIO(json.dumps({'translations': [{
            'text': translated, 'detected_source_language': 'PL',
        }]}).encode())

    def complete(self, dialog):
        dialog.translate_thread.join(3)
        self.assertFalse(dialog.translate_thread.is_alive())
        while not self.callbacks.empty():
            fn, args, kwargs = self.callbacks.get_nowait()
            fn(*args, **kwargs)

    def choices(self, source='auto', target='en'):
        result = types.SimpleNamespace(choice_origen=Widget(), choice_destino=Widget())
        result.choice_origen.SetValue('Source - ' + source)
        result.choice_destino.SetValue('Target - ' + target)
        return result

    def test_long_text_uses_selected_provider_and_bidirectional_snapshot(self):
        text = 'x' * 4000
        with patch('urllib.request.urlopen', self.https):
            dialog = self.Progress(self.frame, text)
            self.complete(dialog)
        self.assertTrue(dialog.completed)
        self.assertEqual('Translated GUI text', dialog.traduccion_resultado)
        self.assertEqual(['PL', 'EN'], [data['target_lang'] for _, data in self.calls])
        self.assertTrue(all(url == 'https://api.deepl.com/v2/translate' for url, _ in self.calls))
        self.assertEqual(1, dialog.finish_calls)
        self.assertEqual(self.wx.ID_OK, dialog.modal_result)

    def test_gui_explicit_source_and_target_are_read_once_before_worker(self):
        choices = self.choices('pl', 'de')
        self.release.clear()
        try:
            with patch('urllib.request.urlopen', self.https):
                dialog = self.Progress(self.frame, 'Cześć', interfaz=True, secundary_frame=choices)
                self.assertTrue(self.entered.wait(1))
                choices.choice_origen.SetValue('French - fr')
                choices.choice_destino.SetValue('English - en')
                self.release.set()
                self.complete(dialog)
        finally:
            self.release.set()
        self.assertTrue(dialog.completed)
        self.assertEqual(1, len(self.calls))
        self.assertEqual(('PL', 'DE'), (self.calls[0][1]['source_lang'], self.calls[0][1]['target_lang']))
        self.assertEqual(1, dialog.finish_calls)

    def test_cancel_close_is_idempotent_and_late_callbacks_ignore_destroyed_widgets(self):
        self.release.clear()
        try:
            with patch('urllib.request.urlopen', self.https):
                dialog = self.Progress(self.frame, 'Cześć')
                self.assertTrue(self.entered.wait(1))
                dialog.update_progress(50)
                dialog.on_cancel(None)
                dialog.on_cancel(None)
                self.assertEqual(1, dialog.finish_calls)
                self.assertFalse(self.settings.is_active_translate)
                self.assertEqual(self.wx.ID_CANCEL, dialog.modal_result)
                dialog.Destroy()
                dialog.progress_bar.destroyed = True
                self.release.set()
                self.complete(dialog)
        finally:
            self.release.set()
        self.assertFalse(dialog.completed)
        self.assertEqual([], list(self.settings.historialDestino))
        self.assertEqual(1, dialog.finish_calls)

    def test_direct_destroy_invalidates_queued_success_and_progress(self):
        with patch('urllib.request.urlopen', self.https):
            dialog = self.Progress(self.frame, 'Cześć')
            dialog.translate_thread.join(3)
            dialog.update_progress(60)
            dialog.Destroy()
            dialog.progress_bar.destroyed = True
            self.complete(dialog)
        self.assertFalse(dialog.completed)
        self.assertFalse(self.settings.is_active_translate)
        self.assertEqual([], list(self.settings.historialDestino))

    def test_success_finish_runs_once_and_late_progress_is_ignored(self):
        with patch('urllib.request.urlopen', self.https):
            dialog = self.Progress(self.frame, 'Cześć')
            self.complete(dialog)
        dialog.onFinish()
        self.assertEqual(1, dialog.finish_calls)
        dialog.Destroy()
        dialog.progress_bar.destroyed = True
        dialog.update_progress(5)
        self.complete(dialog)
        self.assertFalse(self.settings.is_active_translate)

    def test_timeout_and_oversized_requests_fail_without_result_or_busy_leak(self):
        def timeout(*args, **kwargs):
            raise TimeoutError('provider timeout')
        for text, expected in (('Cześć', 'failed'), ('x' * 24001, '24000')):
            with self.subTest(size=len(text)):
                self.settings.is_active_translate = True
                with patch('urllib.request.urlopen', timeout):
                    dialog = self.Progress(self.frame, text)
                    self.complete(dialog)
                self.assertFalse(dialog.completed)
                self.assertFalse(dialog.traduccion_resultado)
                self.assertIn(expected, dialog.error)
                self.assertEqual(1, dialog.finish_calls)
                self.assertFalse(self.settings.is_active_translate)
                self.assertTrue(self.settings._enableTranslation)

    def test_real_google_tts_is_separate_from_selected_translation_provider(self):
        import urllib.request
        import urllib.parse
        tts = load_class(APP / 'src_translations/src_google_tts.py', 'TextToSpeechGoogle', {
            'threading': threading, 'urllibRequest': urllib.request, 'urllib': __import__('urllib'),
            'sleep': lambda *a: None, 'randint': lambda *a: 1, '_': lambda s: s,
        })
        self.namespace['TextToSpeechGoogle'] = tts
        urls = []
        def audio(url):
            self.assertNotEqual(self.main_thread, threading.get_ident())
            urls.append(url)
            return io.BytesIO(b'test-audio-bytes')
        with patch('urllib.request.urlopen', audio):
            dialog = self.Progress(self.frame, 'Hello', tts=True, lang_tts='en')
            self.complete(dialog)
        self.assertTrue(dialog.completed)
        self.assertEqual(b'test-audio-bytes', dialog.traduccion_resultado)
        self.assertEqual(1, len(urls))
        self.assertIn('translate.google.com/translate_tts', urls[0])
        self.assertEqual([], list(self.settings.historialDestino))

    def test_actual_gui_button_uses_provider_with_auto_without_google_preflight(self):
        messages = []
        def forbidden(*a, **kw):
            raise AssertionError('GUI translation must not preflight Google')
        translate = load_method(APP / 'guis/guis_guitrans.py', 'TranslateDialog', 'traducir', {
            '_': lambda s: s, 'wx': self.wx, 'ProgressDialog': self.Progress,
            'gui': types.SimpleNamespace(messageBox=lambda *a: messages.append(a)),
            'DetectorDeIdioma': forbidden, 'check_internet_connection': forbidden,
        })
        for text in ('Cześć', 'x' * 4000):
            with self.subTest(length=len(text)):
                choices = self.choices()
                gui_frame = types.SimpleNamespace(frame=self.frame, texto_origen=Widget(), texto_destino=Widget(),
                    texto_traducido_anterior='', lang_anterior='', **vars(choices))
                gui_frame.texto_origen.SetValue(text)
                with patch('urllib.request.urlopen', self.https):
                    translate(gui_frame, None)
                self.assertEqual('Translated GUI text', gui_frame.texto_destino.GetValue())
                self.assertTrue(gui_frame.progress_dialog.destroyed)
                self.assertEqual([], messages)
                self.assertEqual(text, self.calls[-1][1]['text'][0])
                self.assertNotIn('source_lang', self.calls[-1][1])
                self.assertEqual('EN', self.calls[-1][1]['target_lang'])

    def test_gui_validation_preserved_without_detector_or_network(self):
        messages = []
        def forbidden(*a, **kw):
            raise AssertionError('Invalid text must not reach network or progress dialog')
        translate = load_method(APP / 'guis/guis_guitrans.py', 'TranslateDialog', 'traducir', {
            '_': lambda s: s, 'wx': self.wx, 'ProgressDialog': forbidden,
            'gui': types.SimpleNamespace(messageBox=lambda *a: messages.append(a)),
            'DetectorDeIdioma': forbidden, 'check_internet_connection': forbidden,
        })
        for text, previous, source, target in (('', '', 'auto', 'en'), ('Cześć', 'Cześć', 'auto', 'en'),
                ('Cześć', '', 'pl', 'pl'), ('x' * 24001, '', 'auto', 'en')):
            with self.subTest(length=len(text), same_language=source == target):
                choices = self.choices(source, target)
                gui_frame = types.SimpleNamespace(frame=self.frame, texto_origen=Widget(), texto_destino=Widget(),
                    texto_traducido_anterior=previous, lang_anterior=target, **vars(choices))
                gui_frame.texto_origen.SetValue(text)
                translate(gui_frame, None)
                self.assertTrue(messages)
                if len(text) > 24000:
                    self.assertIn('24000', messages[-1][0])

    def test_unload_cancels_registered_progress_before_nvda_is_destroyed(self):
        namespace = {'_': lambda s: s,
            'globalPluginHandler': types.SimpleNamespace(GlobalPlugin=type('Base', (), {'terminate': lambda s: None}))}
        plugin_class = load_class(PLUGIN, 'GlobalPlugin', namespace)
        plugin = plugin_class.__new__(plugin_class)
        vars(plugin).update(vars(self.frame), _clipboard_job=None, IS_OK=False)
        with patch('urllib.request.urlopen', self.https):
            dialog = self.Progress(plugin, 'Cześć')
            dialog.translate_thread.join(3)
            plugin.terminate()
            self.assertTrue(dialog.canceled)
            self.assertTrue(dialog._closed)
            plugin.gestor_settings = plugin.gestor_translate = None
            dialog.Destroy()
            dialog.progress_bar.destroyed = True
            self.complete(dialog)
        self.assertEqual([], list(self.settings.historialDestino))
        self.assertEqual(1, dialog.finish_calls)

    def test_constructor_snapshot_failure_finishes_cleanly_and_clears_busy(self):
        def broken_store(*a):
            raise OSError('settings store unavailable')
        self.frame.gestor_apis.get_api = broken_store
        dialog = self.Progress(self.frame, 'Cześć')
        self.complete(dialog)
        self.assertFalse(dialog.completed)
        self.assertIn('settings store unavailable', dialog.error)
        self.assertEqual(1, dialog.finish_calls)
        self.assertFalse(self.settings.is_active_translate)
        self.assertEqual(set(), self.frame._translation_dialogs)

    def test_thread_start_failure_finishes_cleanly_and_clears_busy(self):
        with patch.object(threading.Thread, 'start', side_effect=OSError('worker unavailable')):
            dialog = self.Progress(self.frame, 'Cześć')
        while not self.callbacks.empty():
            fn, args, kwargs = self.callbacks.get_nowait()
            fn(*args, **kwargs)
        self.assertFalse(dialog.completed)
        self.assertIn('worker unavailable', dialog.error)
        self.assertEqual(1, dialog.finish_calls)
        self.assertFalse(self.settings.is_active_translate)
        self.assertEqual(set(), self.frame._translation_dialogs)

    def test_destroy_notification_after_finish_cannot_clear_a_new_jobs_busy_flag(self):
        with patch('urllib.request.urlopen', self.https):
            dialog = self.Progress(self.frame, 'Cześć')
            self.complete(dialog)
        self.settings.is_active_translate = True  # A newer job now owns the flag.
        event = types.SimpleNamespace(GetEventObject=lambda: dialog, Skip=lambda: None)
        dialog._on_destroy(event)
        self.assertTrue(self.settings.is_active_translate)

    def test_actual_long_command_routes_and_destroys_progress_dialog(self):
        from test_clipboard_translation import ClipboardFixture
        clipboard = ClipboardFixture('setUp')
        clipboard.setUp()
        messages, spoken = [], []
        self.settings.chkResults = True
        self.frame.gestor_portapapeles = clipboard.monitor
        launch = load_class(PLUGIN, 'LaunchThread', {
            '_': lambda s: s, 'Thread': threading.Thread, 'wx': self.wx,
            'ProgressDialog': self.Progress, 'mute': lambda delay, text: spoken.append(text),
            'gui': types.SimpleNamespace(messageBox=lambda *a: messages.append(a)),
        })(self.frame, 5, 'x' * 4000)
        with patch('urllib.request.urlopen', self.https):
            launch.run()
            fn, args, kwargs = self.callbacks.get_nowait()
            fn(*args, **kwargs)
        self.assertTrue(launch.progress_dialog.destroyed)
        self.assertEqual(['Translated GUI text'], clipboard.clipboard.writes)
        self.assertEqual([], messages)
        self.assertFalse(self.settings.is_active_translate)
        self.assertEqual(['PL', 'EN'], [payload['target_lang'] for _, payload in self.calls])

    def test_long_command_does_not_show_cancel_message_after_unload(self):
        messages = []
        launch = load_class(PLUGIN, 'LaunchThread', {
            '_': lambda s: s, 'Thread': threading.Thread, 'wx': self.wx,
            'ProgressDialog': self.Progress,
            'gui': types.SimpleNamespace(messageBox=lambda *a: messages.append(a)),
        })(self.frame, 5, 'Cześć')
        def close_on_unload(dialog):
            self.frame._terminating = True
            dialog.on_cancel(None)
            return self.wx.ID_CANCEL
        with patch('urllib.request.urlopen', self.https), patch.object(Dialog, 'ShowModal', close_on_unload):
            launch.run()
            fn, args, kwargs = self.callbacks.get_nowait()
            fn(*args, **kwargs)
            self.complete(launch.progress_dialog)
        self.assertEqual([], messages)
        self.assertTrue(launch.progress_dialog.destroyed)
        self.assertFalse(self.settings.is_active_translate)


if __name__ == '__main__':
    unittest.main()
