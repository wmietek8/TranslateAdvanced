"""Exercise source selection through the real manager and provider adapters."""
import importlib.util
import io
import json
import sys
import types
from urllib.parse import parse_qs, urlsplit

import pytest

from nvda_harness import APP, manager_class


@pytest.fixture
def manager():
    module = manager_class()
    instance = module.GestorTranslate.__new__(module.GestorTranslate)
    instance.frame = types.SimpleNamespace(gestor_settings=types.SimpleNamespace(
        choiceOnline=7, choiceLangOrigen='de', choiceLangDestino_microsoft='pl',
        choiceLangDestino_google='pl', chkAltLang=False,
        choiceLangDestino_google_def='pl', choiceLangDestino_google_alt='en',
        _enableTranslation=True, chkCache=False,
    ))
    return instance


@pytest.fixture
def load_provider(monkeypatch):
    def load(name):
        spec = importlib.util.spec_from_file_location(
            'source_routing_' + name, APP / 'src_translations' / (name + '.py'))
        module = importlib.util.module_from_spec(spec)
        module.__dict__['_'] = lambda text: text
        # Restore only these host names, leaving imported stdlib modules intact.
        with monkeypatch.context() as host:
            host.setitem(sys.modules, 'addonHandler', types.SimpleNamespace(initTranslation=lambda: None))
            host.setitem(sys.modules, 'logHandler', types.SimpleNamespace(
                log=types.SimpleNamespace(error=lambda *args, **kwargs: None)))
            spec.loader.exec_module(module)
        return module
    return load


@pytest.fixture
def microsoft_requests(manager, load_provider, monkeypatch):
    module = load_provider('src_microsoft_api_free')
    adapter = module.TranslatorMicrosoftApiFree()
    requests = []

    def https(request):
        requests.append(request)
        response = io.BytesIO(json.dumps([
            {'translations': [{'text': 'Dzień dobry'}]},
        ]).encode('utf-8'))
        response.status = 200
        return response

    monkeypatch.setattr(adapter, '_get_app_key', lambda: 'test-token')
    monkeypatch.setattr(module, 'urlopen', https)
    manager.translate_microsoft_api_free = adapter.translate_microsoft_api_free
    return requests


@pytest.fixture(params=[
    (0, 'src_google_original', 'TranslatorGoogle', 'translate_google'),
    (1, 'src_google_alternative', 'TranslatorGooglealternative', 'translate_google_alternative'),
], ids=['google-0', 'google-1'])
def google_requests(request, manager, load_provider, monkeypatch):
    provider, module_name, class_name, method_name = request.param
    module = load_provider(module_name)
    adapter = getattr(module, class_name)()
    manager.frame.gestor_settings.choiceOnline = provider
    setattr(manager, method_name, getattr(adapter, method_name))
    requests = []

    def https(request):
        requests.append(request)
        return io.BytesIO('<div class="result-container">Dzień dobry</div>'.encode('utf-8'))

    monkeypatch.setattr(module.urllib.request, 'urlopen', https)
    return requests


def test_google_gui_forwards_selected_source(manager, google_requests):
    settings = manager.frame.gestor_settings
    settings.choiceLangOrigen = 'es'
    settings.choiceLangDestino_google = 'es'
    options = manager.translation_options(source='de', target='pl')
    assert manager.translate_with_options('Guten Morgen', options) == 'Dzień dobry'
    assert len(google_requests) == 1
    query = parse_qs(urlsplit(google_requests[0].full_url).query)
    assert query['sl'] == ['de']
    assert query['tl'] == ['pl']
    assert settings.choiceLangOrigen == 'es'
    assert settings.choiceLangDestino_google == 'es'


@pytest.mark.parametrize('request_options', [
    pytest.param({}, id='realtime-default'),
    pytest.param({'source': 'auto'}, id='explicit-gui-auto'),
    pytest.param({'bidirectional': True}, id='clipboard-default'),
])
def test_google_auto_detection_does_not_inherit_realtime_source(
        manager, google_requests, request_options):
    options = manager.translation_options(**request_options)
    assert options['source'] == 'auto'
    assert manager.translate_with_options('Guten Morgen', options) == 'Dzień dobry'
    assert len(google_requests) == 1
    query = parse_qs(urlsplit(google_requests[0].full_url).query)
    assert query['sl'] == ['auto']
    assert query['tl'] == ['pl']
    assert manager.frame.gestor_settings.choiceLangOrigen == 'de'


def test_clipboard_bidirectional_deepl_uses_detection_not_realtime_source(manager, monkeypatch):
    settings = manager.frame.gestor_settings
    settings.choiceOnline = 5
    settings.choiceLangDestino_deepl = 'pl'
    settings.chkAltLang = True
    settings.api_deepl_pro = 0
    manager.frame.gestor_apis = types.SimpleNamespace(
        get_api=lambda service, index: {'key': 'test-token'})
    requests = []

    def https(request, **kwargs):
        payload = json.loads(request.data)
        requests.append(payload)
        translated = 'Good morning' if payload['target_lang'] == 'EN' else 'Dzień dobry'
        return io.BytesIO(json.dumps({'translations': [
            {'text': translated, 'detected_source_language': 'PL'},
        ]}).encode('utf-8'))

    monkeypatch.setattr('urllib.request.urlopen', https)
    options = manager.translation_options(bidirectional=True)
    assert options['source'] == 'auto'
    assert manager.translate_with_options('Dzień dobry', options) == 'Good morning'
    assert [payload['target_lang'] for payload in requests] == ['PL', 'EN']
    assert all('source_lang' not in payload for payload in requests)
    assert settings.choiceLangOrigen == 'de'


def test_realtime_microsoft_keeps_configured_source(manager, microsoft_requests):
    assert manager.translate('Guten Morgen') == 'Dzień dobry'
    assert len(microsoft_requests) == 1
    query = parse_qs(urlsplit(microsoft_requests[0].full_url).query)
    assert query['from'] == ['de']
    assert query['to'] == ['pl']
    assert manager.frame.gestor_settings.choiceLangOrigen == 'de'


@pytest.mark.parametrize(('request_options', 'configured_source'), [
    pytest.param({}, 'auto', id='configured-auto'),
    pytest.param({'source': 'auto', 'target': 'pl'}, 'de', id='explicit-gui-auto'),
    pytest.param({'bidirectional': True}, 'de', id='clipboard-default'),
])
def test_microsoft_auto_detection_omits_source_parameter(
        manager, microsoft_requests, request_options, configured_source):
    manager.frame.gestor_settings.choiceLangOrigen = configured_source
    options = manager.translation_options(**request_options)
    assert options['source'] == 'auto'
    assert manager.translate_with_options('Guten Morgen', options) == 'Dzień dobry'
    assert len(microsoft_requests) == 1
    query = parse_qs(urlsplit(microsoft_requests[0].full_url).query)
    assert 'from' not in query
    assert query['to'] == ['pl']
    assert manager.frame.gestor_settings.choiceLangOrigen == configured_source
