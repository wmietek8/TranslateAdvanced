"""Real DeepL adapter; only NVDA and the HTTPS boundary are substituted."""
import builtins
import importlib
import io
import json
from pathlib import Path
import ssl
import sys
import types
import unittest
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1] / 'addon/globalPlugins/TranslateAdvanced/app'


def load_deepl():
    package = types.ModuleType('ta_deepl_test')
    package.__path__ = [str(APP)]
    addon = types.SimpleNamespace(initTranslation=lambda: None)
    logger = types.SimpleNamespace(log=types.SimpleNamespace(error=lambda *a, **k: None))
    with patch.dict(sys.modules, {'ta_deepl_test': package, 'addonHandler': addon, 'logHandler': logger}), patch.object(builtins, '_', lambda s: s, create=True):
        module = importlib.import_module('ta_deepl_test.src_translations.src_deepl_original')
    module.__dict__.setdefault('_', lambda value: value)
    return module


class DeepLDirectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_deepl()

    def test_english_clipboard_is_translated_to_primary_polish(self):
        calls = []
        def transport(request, **kwargs):
            body = json.loads(request.data)
            calls.append(body)
            self.assertEqual('https://api.deepl.com/v2/translate', request.full_url)
            self.assertNotIn('source_lang', body)
            return io.BytesIO(json.dumps({'translations': [{'text': 'Cześć, jak się czujesz?', 'detected_source_language': 'EN'}]}).encode())
        with patch.object(self.module.urllib.request, 'urlopen', transport):
            result = self.module.TranslatorDeepL().translate_deepl('Hello, how are you?', 'unit-test-key', use_free_api=False, target_lang='pl', alternate_lang='en', strict=True)
        self.assertEqual('Cześć, jak się czujesz?', result)
        self.assertEqual(['PL'], [p['target_lang'] for p in calls])


    def test_polish_clipboard_goes_to_english_using_only_deepl_detection(self):
        calls = []
        def transport(request, **kwargs):
            body = json.loads(request.data)
            calls.append(body)
            self.assertEqual(ssl.CERT_REQUIRED, kwargs['context'].verify_mode)
            self.assertTrue(kwargs['context'].check_hostname)
            self.assertNotIn('source_lang', body)
            translated = 'No dobra, a co teraz?' if body['target_lang'] == 'PL' else 'Okay, what now?'
            return io.BytesIO(json.dumps({'translations': [{'text': translated, 'detected_source_language': 'PL'}]}).encode())
        with patch.object(self.module.urllib.request, 'urlopen', transport):
            result = self.module.TranslatorDeepL().translate_deepl('No dobra, a co teraz?', 'unit-test-key', use_free_api=False, target_lang='pl', alternate_lang='en-us', strict=True)
        self.assertEqual('Okay, what now?', result)
        self.assertEqual(['PL', 'EN-US'], [p['target_lang'] for p in calls])
        self.assertEqual(['No dobra, a co teraz?'] * 2, [p['text'][0] for p in calls])


    def test_primary_english_matches_detected_english_variants(self):
        calls = []
        def transport(request, **kwargs):
            payload = json.loads(request.data); calls.append(payload)
            return io.BytesIO(json.dumps({'translations': [{'text':'Witaj' if payload['target_lang']=='PL' else 'Hello', 'detected_source_language':'EN'}]}).encode())
        with patch.object(self.module.urllib.request, 'urlopen', transport):
            result = self.module.TranslatorDeepL().translate_deepl('Hello', 'test', target_lang='en-gb', alternate_lang='pl', strict=True)
        self.assertEqual('Witaj', result)
        self.assertEqual(['EN-GB','PL'], [p['target_lang'] for p in calls])

    def test_empty_missing_metadata_and_malformed_responses_fail_not_echo(self):
        responses = [{}, {'translations': []}, {'translations': [{'text': ''}]},
                     {'translations': [{'text': '   ', 'detected_source_language': 'EN'}]},
                     {'translations': [{'text': 'hej'}]}]
        for response in responses:
            with self.subTest(response=response), patch.object(self.module.urllib.request, 'urlopen', lambda *a, **kw: io.BytesIO(json.dumps(response).encode())):
                with self.assertRaises(RuntimeError):
                    self.module.TranslatorDeepL().translate_deepl('hello', 'secret', target_lang='pl', alternate_lang='en', strict=True)

    def test_error_is_sanitized_and_strict_mode_never_returns_source(self):
        import urllib.error
        for error in [TimeoutError('private clipboard text'), urllib.error.HTTPError('https://api.deepl.com',429,'api-key-secret',None,io.BytesIO(b'sensitive server body'))]:
            with self.subTest(error=type(error).__name__), patch.object(self.module.urllib.request,'urlopen',side_effect=error):
                with self.assertRaises(RuntimeError) as result:
                    self.module.TranslatorDeepL().translate_deepl('private clipboard text','api-key-secret',strict=True)
                self.assertNotIn('private', str(result.exception))
                self.assertNotIn('secret', str(result.exception))
                self.assertNotIn('sensitive', str(result.exception))


    def test_redirect_does_not_forward_api_key_or_accept_redirected_output(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from threading import Thread
        seen = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_POST(self):
                self.rfile.read(int(self.headers.get('Content-Length', 0)))
                self.send_response(302); self.send_header('Location','/redirected'); self.end_headers()
            def do_GET(self):
                seen.append(self.headers.get('Authorization'))
                self.send_response(200); self.end_headers()
                self.wfile.write(b'{"translations":[{"text":"fake redirect output"}]}')
        server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        worker = Thread(target=server.serve_forever,daemon=True); worker.start()
        try:
            client = self.module.TranslatorDeepL()
            client._get_base_url = lambda free: f'http://127.0.0.1:{server.server_port}'
            with self.assertRaises(RuntimeError):
                client.translate_deepl('Hello','unit-test-secret',strict=True)
            self.assertNotIn('DeepL-Auth-Key unit-test-secret',seen)
        finally:
            server.shutdown(); server.server_close(); worker.join(2)


if __name__ == '__main__':
    unittest.main()
