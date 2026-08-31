import ast
from collections import deque
import pathlib
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "addon" / "globalPlugins" / "TranslateAdvanced" / "__init__.py"
MANAGER = ROOT / "addon" / "globalPlugins" / "TranslateAdvanced" / "app" / "managers" / "managers_translate.py"


def load_method(path, class_name, method_name, globals_dict=None):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    method = next(node for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name)
    method.decorator_list = []
    module = ast.Module(body=[method], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {} if globals_dict is None else dict(globals_dict)
    exec(compile(module, str(path), "exec"), namespace)
    return namespace[method_name]


class Settings:
    def __init__(self):
        self._enableTranslation = False
        self._lastTranslatedText = None
        self.historialOrigen = deque()
        self.historialDestino = deque()
        self.chkAltLang = False
        self.choiceOnline = 5
        self.choiceLangDestino_google = "en"
        self.choiceLangDestino_deepl = "pl"
        self.choiceLangDestino_libretranslate = "pl"
        self.choiceLangDestino_microsoft = "pl"
        self.choiceLangDestino_openai = "pl"
        self.choiceLangDestino_google_def = "pl"
        self.choiceLangDestino_google_alt = "en"


class Clipboard:
    def __init__(self, text):
        self.text = text
        self.writes = []

    def get_clipboard_text(self):
        return self.text

    def set_clipboard_text(self, text):
        self.text = text
        self.writes.append(text)


class ClipboardTranslationTests(unittest.TestCase):
    def test_translate_various_uses_current_configured_engine(self):
        class LegacyGoogle:
            def translate_google_api_free(self, **kwargs):
                return "Legacy Google result"

        method = load_method(
            MANAGER,
            "GestorTranslate",
            "translate_various",
            {
                "braille": types.SimpleNamespace(handler=types.SimpleNamespace(_get_enabled=lambda: False)),
                "postprocess_short_translation": lambda source, translated, lang: translated,
                "TranslatorGoogleApiFree": LegacyGoogle,
            },
        )
        calls = []
        manager = types.SimpleNamespace()
        manager.frame = types.SimpleNamespace(gestor_settings=Settings())
        manager.translate = lambda text: calls.append(text) or "Hello, how are you?"

        result = method(manager, "Siema, jak się czujesz?")

        self.assertEqual("Hello, how are you?", result)
        self.assertEqual(["Siema, jak się czujesz?"], calls)
        self.assertFalse(manager.frame.gestor_settings._enableTranslation)

    def test_direct_translation_uses_alternate_english_without_google_detector(self):
        class ForbiddenGoogleDetector:
            def __init__(self):
                raise AssertionError("Google language detector must not be called")

        method = load_method(
            MANAGER,
            "GestorTranslate",
            "translate_various",
            {
                "braille": types.SimpleNamespace(handler=types.SimpleNamespace(_get_enabled=lambda: False)),
                "DetectorDeIdioma": ForbiddenGoogleDetector,
            },
        )
        settings = Settings()
        settings.chkAltLang = True
        observed_targets = []
        manager = types.SimpleNamespace(
            frame=types.SimpleNamespace(gestor_settings=settings),
        )
        manager.translate = lambda text: observed_targets.append(settings.choiceLangDestino_deepl) or "Download the new package"

        result = method(manager, "Pobierz nową paczkę")

        self.assertEqual("Download the new package", result)
        self.assertEqual(["en"], observed_targets)
        self.assertEqual("pl", settings.choiceLangDestino_deepl)

    def test_clipboard_command_speaks_and_replaces_clipboard_with_translation(self):
        spoken = []
        method = load_method(
            PLUGIN,
            "GlobalPlugin",
            "script_ClipboardTranslation",
            {"ui": types.SimpleNamespace(message=spoken.append)},
        )
        clipboard = Clipboard("Siema, jak się czujesz?")
        settings = Settings()
        plugin = types.SimpleNamespace(
            switch=False,
            chk_banderas=lambda *args: True,
            gestor_portapapeles=clipboard,
            gestor_settings=settings,
            gestor_translate=types.SimpleNamespace(translate_various=lambda text: "Hello, how are you?"),
        )

        method(plugin, None)

        self.assertEqual(["Hello, how are you?"], spoken)
        self.assertEqual(["Hello, how are you?"], clipboard.writes)
        self.assertEqual("Hello, how are you?", clipboard.text)


if __name__ == "__main__":
    unittest.main()
