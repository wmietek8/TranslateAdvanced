import io
import json
import types
import unittest
from collections import deque
from unittest.mock import patch
from nvda_harness import manager_class


class RoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = manager_class()

    def setUp(self):
        self.settings = types.SimpleNamespace(choiceOnline=5, chkAltLang=True,
            choiceLangDestino_deepl='pl', choiceLangDestino_google='es', choiceLangDestino_google_def='pl',
            choiceLangDestino_google_alt='en', choiceLangOrigen='auto', choiceLangDestino_openai='pl',
            api_deepl_pro=0, _enableTranslation=True, chkCache=True, _translationCache={},
            historialOrigen=deque(), historialDestino=deque(), _lastTranslatedText='old')
        self.manager = self.module.GestorTranslate.__new__(self.module.GestorTranslate)
        self.manager.frame = types.SimpleNamespace(gestor_settings=self.settings,
            gestor_apis=types.SimpleNamespace(get_api=lambda service, index: {'key':'unit-test-key'}))

    def test_clipboard_both_directions_reach_selected_deepl_and_preserve_settings(self):
        before = vars(self.settings).copy()
        calls = []
        def https(request, **kwargs):
            data = json.loads(request.data)
            calls.append((request.full_url, data))
            source = data['text'][0]
            if source == 'Cześć, jak się czujesz?':
                lang, translated = 'PL', ('Hello, how are you?' if data['target_lang'] == 'EN' else source)
            else:
                lang, translated = 'EN', ('Cześć, jak się czujesz?' if data['target_lang'] == 'PL' else source)
            return io.BytesIO(json.dumps({'translations':[{'text':translated, 'detected_source_language':lang}]}).encode())
        with patch('urllib.request.urlopen', https):
            self.assertEqual('Hello, how are you?', self.manager.translate_various('Cześć, jak się czujesz?'))
            self.assertEqual('Cześć, jak się czujesz?', self.manager.translate_various('Hello, how are you?'))
        self.assertEqual(['PL', 'EN', 'PL'], [d['target_lang'] for u, d in calls])
        self.assertTrue(all(u == 'https://api.deepl.com/v2/translate' for u, d in calls))
        for key in ('_enableTranslation', 'choiceLangDestino_deepl', 'choiceLangDestino_google', 'choiceOnline'):
            self.assertEqual(before[key], getattr(self.settings,key))


    def test_openai_oauth_without_api_key_uses_selected_model_and_primary_target(self):
        self.settings.choiceOnline = 9
        self.settings.api_openai = None
        self.settings.openai_auth_mode = 'chatgpt'
        self.settings.openai_model_oauth = 'gpt-6-astra'
        calls = []
        self.manager.translate_openai = lambda key, text, **kw: calls.append((key, text, kw)) or 'Witaj'
        self.assertEqual('pl', self.manager.get_choice_lang_destino())
        result = self.manager.translate_with_options('Hello', self.manager.translation_options())
        self.assertEqual('Witaj', result)
        self.assertIsNone(calls[0][0])
        self.assertEqual('gpt-6-astra', calls[0][2]['model'])
        self.assertEqual('chatgpt', calls[0][2]['auth_mode'])
        self.assertIsNone(calls[0][2]['alternate_language'])

    def test_openai_realtime_cache_separates_language_model_and_login_mode(self):
        self.settings.choiceOnline = 9
        self.settings.api_openai = None
        self.settings.openai_auth_mode = 'chatgpt'
        self.settings.openai_model_oauth = 'model-a'
        first = self.manager.get_cache_app_name()
        self.settings.openai_model_oauth = 'model-b'
        self.assertNotEqual(first, self.manager.get_cache_app_name())
        first = self.manager.get_cache_app_name()
        self.settings.choiceLangDestino_openai = 'en'
        self.assertNotEqual(first, self.manager.get_cache_app_name())

    def test_snapshot_survives_settings_changes_while_network_runs(self):
        options = self.manager.translation_options(bidirectional=True)
        self.settings.choiceOnline = 9
        self.settings.choiceLangDestino_google_alt = 'de'
        self.settings.choiceLangDestino_google_def = 'uk'
        self.assertEqual((5, 'pl', 'en'), (options['provider'],options['target'],options['alternate']))


    def test_realtime_openai_oauth_uses_same_selected_model_without_api_key(self):
        self.settings.choiceOnline = 9
        self.settings.api_openai = None
        self.settings.openai_auth_mode = 'chatgpt'
        self.settings.openai_model_oauth = 'gpt-6-astra'
        calls = []
        self.manager.translate_openai = lambda key, text, **kw: calls.append(kw) or 'Witaj'
        self.assertEqual('Witaj', self.manager.translate('Hello'))
        self.assertEqual('gpt-6-astra', calls[0]['model'])
        self.assertIsNone(calls[0]['alternate_language'])
        self.assertEqual('pl', calls[0]['target_language'])

    def test_missing_stale_key_is_rejected_cleanly_not_indexed(self):
        self.manager.frame.gestor_apis.get_api = lambda *a: None
        self.assertEqual((None, None), self.manager.get_api())
        with self.assertRaisesRegex(ValueError, 'API'):
            self.manager.translate_various('Hello')

    def test_explicit_file_translation_uses_selected_provider_not_google(self):
        calls = []
        self.manager.translate_deepl = lambda text, key, **kw: calls.append(kw) or 'Translated text'
        progress = []
        self.assertEqual('Translated text', self.manager.translate_file('Source text', progress.append))
        self.assertEqual('pl', calls[0]['target_lang'])
        self.assertEqual(100, progress[-1])


if __name__ == '__main__':
    unittest.main()
