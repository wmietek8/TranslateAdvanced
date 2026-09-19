"""Load real add-on classes, substituting only NVDA and unused providers.
All sys.modules changes are scoped to a single import; no collection-time pollution.
"""
import builtins
import importlib
from pathlib import Path
import sys
import types
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1] / 'addon/globalPlugins/TranslateAdvanced/app'


def manager_class():
    package = types.ModuleType('ta_manager_test')
    package.__path__ = [str(APP)]
    stubs = {'ta_manager_test': package}
    def init_translation():
        # Match NVDA: initialize the calling add-on module, not a temporary
        # builtins entry that disappears before a later worker handles errors.
        sys._getframe(1).f_globals['_'] = lambda value: value
    stubs['addonHandler'] = types.SimpleNamespace(initTranslation=init_translation)
    stubs['globalVars'] = types.SimpleNamespace(appArgs=types.SimpleNamespace(configPath='test-config'))
    stubs['logHandler'] = types.SimpleNamespace(log=types.SimpleNamespace(error=lambda *a, **k: None))
    stubs['languageHandler'] = types.SimpleNamespace()
    stubs['braille'] = types.SimpleNamespace(handler=types.SimpleNamespace(_get_enabled=lambda: False))
    stubs['speechViewer'] = types.SimpleNamespace(SPEECH_ITEM_SEPARATOR=' ')
    stubs['ui'] = types.SimpleNamespace(message=lambda *a: None)
    speech = types.ModuleType('speech')
    speech.SpeechSequence = list
    speech.Spri = object
    stubs['speech'] = speech
    for module, name in [('src_google_original', 'TranslatorGoogle'), ('src_google_alternative','TranslatorGooglealternative'), ('src_google_api_free','TranslatorGoogleApiFree'), ('src_google_api_free_alternative','TranslatorGoogleApiFreeAlternative'), ('src_libretranslate_original','TranslatorLibreTranslate'), ('src_microsoft_api_free','TranslatorMicrosoftApiFree'), ('src_deepl_free','TranslatorDeepLFree'), ('src_detect','DetectorDeIdioma')]:
        mod = types.ModuleType('ta_manager_test.src_translations.' + module)
        setattr(mod, name, type(name, (), {}))
        stubs[mod.__name__] = mod
    # Until the new pure-stdlib OpenAI adapter lands, its legacy imports need these.
    stubs['wx'] = types.SimpleNamespace(CallAfter=lambda fn, *a: fn(*a))
    # Restore only the shim's own names. patch.dict(sys.modules) would also
    # remove freshly imported stdlib modules and detach urllib from later mocks.
    def owned(name):
        return name in stubs or name == 'ta_manager_test' or name.startswith('ta_manager_test.')
    previous = {name: value for name, value in sys.modules.copy().items() if owned(name)}
    try:
        sys.modules.update(stubs)
        with patch.object(builtins, '_', lambda s: s, create=True):
            module = importlib.import_module('ta_manager_test.managers.managers_translate')
    finally:
        for name in tuple(sys.modules):
            if owned(name):
                sys.modules.pop(name, None)
        sys.modules.update(previous)
    module.__dict__['_'] = lambda s: s
    return module
