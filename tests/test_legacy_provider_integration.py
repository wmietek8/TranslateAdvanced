"""Legacy provider contracts through the real manager; only HTTPS/NVDA are fake."""
import importlib.util
import io
import json
import sys
import types
from collections import deque
from datetime import datetime
from urllib.parse import parse_qs, urlsplit

import pytest

from nvda_harness import APP, manager_class


@pytest.fixture
def manager_module():
    return manager_class()


@pytest.fixture
def manager(manager_module):
    instance = manager_module.GestorTranslate.__new__(manager_module.GestorTranslate)
    instance.frame = types.SimpleNamespace(gestor_settings=types.SimpleNamespace(
        choiceOnline=7, choiceLangOrigen='de', choiceLangDestino_microsoft='pl',
        choiceLangDestino_google='pl', chkAltLang=False,
        _enableTranslation=True, chkCache=True, _translationCache={},
        historialOrigen=deque(), historialDestino=deque(), _lastTranslatedText=None,
    ))
    return instance


@pytest.fixture
def load_provider(monkeypatch):
    def load(name):
        spec = importlib.util.spec_from_file_location(
            'legacy_integration_' + name, APP / 'src_translations' / (name + '.py'))
        module = importlib.util.module_from_spec(spec)
        module.__dict__['_'] = lambda text: text
        # Do not restore the entire sys.modules mapping: urllib must stay attached.
        with monkeypatch.context() as host:
            host.setitem(sys.modules, 'addonHandler', types.SimpleNamespace(initTranslation=lambda: None))
            host.setitem(sys.modules, 'logHandler', types.SimpleNamespace(
                log=types.SimpleNamespace(error=lambda *args, **kwargs: None)))
            spec.loader.exec_module(module)
        return module
    return load


@pytest.fixture(params=[
    (2, 'src_google_api_free', 'TranslatorGoogleApiFree'),
    (3, 'src_google_api_free_alternative', 'TranslatorGoogleApiFreeAlternative'),
], ids=['google-2', 'google-3-alternative'])
def google(request, manager_module, manager, load_provider, monkeypatch):
    provider, module_name, class_name = request.param
    module = load_provider(module_name)
    adapter_class = getattr(module, class_name)
    monkeypatch.setattr(manager_module, class_name, adapter_class)
    manager.frame.gestor_settings.choiceOnline = provider
    replies, urls = deque(), []

    def https(url):
        urls.append(url)
        reply = replies.popleft()
        if isinstance(reply, Exception):
            raise reply
        return io.BytesIO(reply)

    monkeypatch.setattr(module.urllibRequest, 'build_opener', lambda: types.SimpleNamespace(open=https))
    payload = ({'src': 'de', 'sentences': [{'trans': 'Dzień dobry'}]} if provider == 2 else
               [[['Dzień dobry', 'Guten Morgen', None, None]], None, 'de'])
    return types.SimpleNamespace(
        adapter_class=adapter_class, replies=replies, urls=urls,
        success=json.dumps(payload).encode('utf-8'),
    )


@pytest.fixture
def microsoft(manager, load_provider, monkeypatch):
    module = load_provider('src_microsoft_api_free')
    adapter = module.TranslatorMicrosoftApiFree()
    adapter.access_info = {'Token': 'test-token', 'Expire': datetime.max}
    manager.translate_microsoft_api_free = adapter.translate_microsoft_api_free
    replies, requests = deque(), []

    def https(request):
        requests.append(request)
        reply = replies.popleft()
        if isinstance(reply, Exception):
            raise reply
        response = io.BytesIO(reply)
        response.status = 200
        return response

    monkeypatch.setattr(module, 'urlopen', https)
    return types.SimpleNamespace(
        replies=replies, requests=requests,
        success=json.dumps([{'translations': [{'text': 'Dzień dobry'}]}]).encode('utf-8'),
    )


def test_real_google_adapter_succeeds_through_manager(manager, google):
    google.replies.append(google.success)
    options = manager.translation_options(source='de', target='pl')

    assert manager.translate_with_options('Guten Morgen', options) == 'Dzień dobry'
    assert len(google.urls) == 1
    query = parse_qs(urlsplit(google.urls[0]).query)
    assert query['sl'] == ['de']
    assert query['tl'] == ['pl']
    assert query['q'] == ['Guten Morgen']


@pytest.mark.parametrize('reply', [TimeoutError('temporary outage'), b'not JSON'],
                         ids=['timeout', 'invalid-json'])
def test_real_google_failure_is_rejected_by_manager(manager, google, reply):
    google.replies.append(reply)
    options = manager.translation_options(source='de', target='pl')

    with pytest.raises(RuntimeError, match='Translation failed. Clipboard was not changed.'):
        manager.translate_with_options('Guten Morgen', options)
    assert len(google.urls) == 1


def test_real_google_error_status_is_replaced_after_recovery(google):
    adapter = google.adapter_class()
    google.replies.extend([TimeoutError('temporary outage'), google.success])
    assert adapter.get_error() == {'success': False, 'data': None}

    assert adapter.translate_google_api_free('de', 'pl', 'Guten Morgen') == 'Guten Morgen'
    assert adapter.get_error()['success'] is True
    assert adapter.get_error()['data']

    assert adapter.translate_google_api_free('de', 'pl', 'Guten Morgen') == 'Dzień dobry'
    assert adapter.get_error() == {'success': False, 'data': None}
    assert len(google.urls) == 2


@pytest.mark.parametrize('reply', [TimeoutError('temporary outage'), b'not JSON'],
                         ids=['timeout', 'invalid-json'])
def test_realtime_recovers_from_microsoft_fallback_and_caches_success(manager, microsoft, reply):
    microsoft.replies.extend([reply, microsoft.success])

    assert manager.translate('Guten Morgen') == 'Guten Morgen'
    assert len(microsoft.requests) == 1
    assert manager.translate('Guten Morgen') == 'Dzień dobry'
    assert len(microsoft.requests) == 2
    assert manager.translate('Guten Morgen') == 'Dzień dobry'
    assert len(microsoft.requests) == 2
    cache = manager.frame.gestor_settings._translationCache[manager.get_cache_app_name()]
    assert cache['Guten Morgen'] == 'Dzień dobry'


def test_realtime_ignores_existing_source_equal_cache_entry(manager, microsoft):
    cache = {'Guten Morgen': 'Guten Morgen'}
    manager.frame.gestor_settings._translationCache[manager.get_cache_app_name()] = cache
    microsoft.replies.append(microsoft.success)

    assert manager.translate('Guten Morgen') == 'Dzień dobry'
    assert len(microsoft.requests) == 1
    assert cache['Guten Morgen'] == 'Dzień dobry'


@pytest.mark.parametrize('reply', [
    TimeoutError('temporary outage'),
    json.dumps([{'translations': [{'text': 'Guten Morgen'}]}]).encode('utf-8'),
], ids=['error-fallback', 'unchanged-success'])
def test_realtime_returns_source_equal_result_without_caching_it(manager, microsoft, reply):
    microsoft.replies.append(reply)

    assert manager.translate('Guten Morgen') == 'Guten Morgen'
    assert len(microsoft.requests) == 1
    cache = manager.frame.gestor_settings._translationCache[manager.get_cache_app_name()]
    assert 'Guten Morgen' not in cache
