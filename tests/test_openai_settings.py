"""Exercise real settings/dialog code; replace only NVDA/wx and I/O boundaries."""
import importlib.util
import json
import queue
import threading
import time
import re
import sys
import types
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "addon/globalPlugins/TranslateAdvanced/app"


class NvdaConfig(dict):
    """Small NVDA config boundary, supplying ConfigObj-style spec defaults."""
    def __init__(self):
        super().__init__(general={"language": "pl"}, TranslateAdvanced={"choiceOnline": 5, "api_openai": "0"})
        self.spec = {}
        self.profiles = [self]

    def __getitem__(self, section):
        result = super().__getitem__(section)
        for key, spec in self.spec.get(section, {}).items():
            default = re.search(r"default=([^,)]+)", spec).group(1).strip("'\"")
            if spec.startswith("integer"):
                default = int(default)
            elif spec.startswith("boolean"):
                default = default == "True"
            result.setdefault(key, default)
        return result


@pytest.fixture
def app_modules(monkeypatch, tmp_path):
    """Scoped import namespace: never leave fake NVDA/wx in sys.modules."""
    conf = NvdaConfig()
    messages = []
    boundaries = {
        "addonHandler": types.SimpleNamespace(initTranslation=lambda: None, getCodeAddon=lambda: types.SimpleNamespace(path=str(tmp_path / "addon"))),
        "languageHandler": types.SimpleNamespace(getWindowsLanguage=lambda: "pl", getLanguageDescription=lambda code: code),
        "ui": types.SimpleNamespace(message=messages.append),
        "config": types.SimpleNamespace(conf=conf),
        "globalVars": types.SimpleNamespace(appArgs=types.SimpleNamespace(configPath=str(tmp_path / "nvda"))),
        "logHandler": types.SimpleNamespace(log=types.SimpleNamespace(error=lambda *args: None)),
    }
    for name, module in boundaries.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    for suffix, path in (("", APP), (".managers", APP / "managers"), (".guis", APP / "guis"), (".utils", APP / "utils")):
        package = types.ModuleType("_ta_openai_tests" + suffix)
        package.__path__ = [str(path)]
        monkeypatch.setitem(sys.modules, package.__name__, package)

    def load(relative):
        name = "_ta_openai_tests." + relative.replace("/", ".")
        path = APP / (relative + ".py")
        assert path.exists(), f"Missing implementation: {path.name}"
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        module.__dict__["_"] = lambda text: text
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        return module

    return types.SimpleNamespace(load=load, conf=conf, boundaries=boundaries, tmp_path=tmp_path, messages=messages)


class WxBoundary:
    """In-memory widgets that reject off-thread or post-destruction access."""
    def __init__(self):
        self.owner = threading.get_ident()
        self.pending = queue.Queue()
        self.widgets = []
        self.focus = None
        constants = "ID_ANY ID_OK ID_CANCEL ID_YES VERTICAL HORIZONTAL ALL EXPAND ALIGN_CENTER ALIGN_RIGHT TE_READONLY TE_MULTILINE TE_PASSWORD CB_DROPDOWN DEFAULT_DIALOG_STYLE RESIZE_BORDER EVT_BUTTON EVT_CHOICE EVT_CLOSE EVT_CHAR_HOOK EVT_WINDOW_DESTROY EVT_LISTBOOK_PAGE_CHANGED EVT_CHECKBOX ACCEL_NORMAL WXK_F1 WXK_F2 WXK_F3 WXK_F4 WXK_ESCAPE OK ICON_ERROR ICON_INFORMATION YES_NO NO_DEFAULT ICON_QUESTION".split()
        for index, name in enumerate(constants):
            setattr(self, name, 1 << index)
        self.NOT_FOUND = -1
        wx = self

        class Widget:
            def __init__(self, parent=None, id=None, label="", value="", choices=(), style=0, **kwargs):
                self.parent = parent
                self.label = label
                self.name = kwargs.get("name", "")
                self.value = value
                self.choices = list(choices)
                self.style = style
                self.selection = -1
                self.enabled = True
                self.shown = True
                self.destroyed = False
                self.bindings = {}
                self.result = wx.ID_CANCEL
                self.children = []
                self.pages = []
                wx.widgets.append(self)
                if parent:
                    parent.children.append(self)

            def __getattribute__(self, name):
                value = object.__getattribute__(self, name)
                if name[0].isupper() and callable(value):
                    assert threading.get_ident() == wx.owner, f"wx.{name} on worker"
                    assert not self.destroyed, f"wx.{name} on destroyed widget"
                return value

            def Bind(self, event, callback, id=None): self.bindings[(event, id)] = callback
            def SetName(self, name): self.name = name
            def SetHelpText(self, text): self.help = text
            def SetValue(self, value): self.value = value
            def ChangeValue(self, value): self.value = value
            def GetValue(self): return self.value
            def SetLabel(self, label): self.label = label
            def GetLabel(self): return self.label
            def SetSelection(self, selection): self.selection = selection
            def GetSelection(self): return self.selection
            def GetString(self, index): return self.choices[index]
            def GetStringSelection(self): return self.choices[self.selection] if self.selection >= 0 else ""
            def SetStringSelection(self, text): self.selection = self.choices.index(text)
            def SetItems(self, choices): self.choices = list(choices); self.value = ""
            def Append(self, text): self.choices.append(text)
            def AppendItems(self, choices): self.choices.extend(choices)
            def Clear(self): self.choices.clear(); self.value = ""
            def Enable(self, enabled=True): self.enabled = enabled
            def Disable(self): self.enabled = False
            def Show(self, show=True): self.shown = show
            def SetFocus(self): wx.focus = self
            def SetSizer(self, sizer): self.sizer = sizer
            def SetSizerAndFit(self, sizer): self.sizer = sizer
            def SetMinSize(self, size): pass
            def CenterOnScreen(self): pass
            def CentreOnParent(self): pass
            def Layout(self): pass
            def Fit(self): pass
            def Wrap(self, width): pass
            def SetDefault(self): pass
            def SetEscapeId(self, id): self.escape_id = id
            def SetAffirmativeId(self, id): pass
            def SetAcceleratorTable(self, table): pass
            def GetId(self): return id(self)
            def AddPage(self, page, text): self.pages.append((page, text))
            def GetPageCount(self): return len(self.pages)
            def GetPage(self, index): return self.pages[index][0]
            def GetPageText(self, index): return self.pages[index][1]
            def IsModal(self): return True
            def ShowModal(self): return self.result
            def EndModal(self, result): self.result = result
            def Destroy(self):
                callback = self.bindings.get((wx.EVT_WINDOW_DESTROY, None))
                if callback:
                    callback(types.SimpleNamespace(GetEventObject=lambda: self, Skip=lambda: None))
                for child in self.children:
                    child.Destroy()
                self.destroyed = True

        class Sizer:
            def __init__(self, *args): self.children = []
            def Add(self, widget, *args): self.children.append(widget)
            def AddStretchSpacer(self, *args): pass
            def AddSpacer(self, *args): pass

        for name in ("Dialog", "Panel", "TextCtrl", "ComboBox", "StaticText", "Button", "Choice", "ListBox", "Listbook", "CheckBox", "MessageDialog"):
            setattr(self, name, type(name, (Widget,), {}))
        self.BoxSizer = Sizer
        self.AcceleratorTable = lambda values: values
        self.MessageBox = lambda *args: None

    def CallAfter(self, callback, *args, **kwargs):
        self.pending.put((callback, args, kwargs))

    def pump_until(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while not predicate():
            assert time.monotonic() < deadline, "Timed out waiting for worker/CallAfter"
            try:
                callback, args, kwargs = self.pending.get(timeout=0.02)
            except queue.Empty:
                continue
            callback(*args, **kwargs)

    def drain(self):
        while not self.pending.empty():
            callback, args, kwargs = self.pending.get_nowait()
            callback(*args, **kwargs)


@pytest.fixture
def gui_app(app_modules, monkeypatch):
    wx = WxBoundary()
    monkeypatch.setitem(sys.modules, "wx", wx)
    monkeypatch.setitem(sys.modules, "gui", types.SimpleNamespace(mainFrame=types.SimpleNamespace(postPopup=lambda: None)))
    settings = app_modules.load("managers/managers_settings").GestorSettings(None)
    apis = app_modules.load("managers/managers_apis").APIManager(settings.file_api)
    apis.add_api("openai", "Personal", "test-key-not-real")
    app_modules.load("managers/managers_dict")
    frame = types.SimpleNamespace(
        gestor_settings=settings, gestor_apis=apis,
        gestor_lang=types.SimpleNamespace(obtener_idiomas=lambda service: {"en": "English", "pl": "Polish", "es": "Spanish"}),
        gestor_ayuda=types.SimpleNamespace(ayudas={}, agregar_ayuda=lambda *args: None),
    )
    return types.SimpleNamespace(wx=wx, frame=frame, load=app_modules.load, conf=app_modules.conf, messages=app_modules.messages)


def test_openai_preferences_default_and_round_trip_without_changing_existing_settings(app_modules):
    cls = app_modules.load("managers/managers_settings").GestorSettings
    settings = cls(None)
    expected = {"openai_auth_mode": "api_key", "openai_model_api": "auto", "openai_model_oauth": "auto", "openai_codex_path": ""}
    for key, value in expected.items():
        assert key in app_modules.conf.spec["TranslateAdvanced"], f"Missing setting {key}"
        assert getattr(settings, key) == value
    changed = {"openai_auth_mode": "chatgpt", "openai_model_api": "gpt-4.1-mini", "openai_model_oauth": "gpt-5", "openai_codex_path": "C:/Tools/codex.exe"}
    for key, value in changed.items():
        setattr(settings, key, value)
    settings.guardaConfiguracion()
    loaded = cls(None)
    assert {key: getattr(loaded, key) for key in changed} == changed
    assert loaded.choiceOnline == 5  # Existing DeepL selection is untouched.
    assert loaded.api_openai == 0
    assert loaded.file_api == str(app_modules.tmp_path / "apis.json")
    assert not any("token" in key or "secret" in key for key in app_modules.conf.spec["TranslateAdvanced"])


def test_openai_display_name_keeps_provider_nine_and_original_order(app_modules):
    settings = app_modules.load("managers/managers_settings").GestorSettings(None)
    label = "OpenAI (API / ChatGPT OAuth)"
    assert settings.servers_names[-1] == label
    assert settings.service_map_selection[label] == 9
    assert settings.service_map[label] == "openai"
    assert [settings.service_map_selection[name] for name in settings.servers_names] == [0, 1, 2, 3, 8, 4, 5, 6, 7, 9]


def test_options_exposes_openai_configuration_and_masks_existing_api_crud(gui_app):
    options = gui_app.load("guis/guis_options").ConfigDialog(None, gui_app.frame)
    assert options.openai_button.enabled
    assert "OpenAI" in options.openai_button.label
    assert "&" in options.openai_button.label
    options.translator_choice.SetSelection(9)
    options.on_translator_choice(types.SimpleNamespace(GetString=lambda: "OpenAI (API / ChatGPT OAuth)"))
    assert options.selected_service == "openai"
    assert options.api_listbox.shown
    options.show_api_dialog("Add API key", "add")
    fields = [widget for widget in gui_app.wx.widgets if isinstance(widget, gui_app.wx.TextCtrl)]
    assert any(widget.style & gui_app.wx.TE_PASSWORD for widget in fields)
    assert gui_app.frame.gestor_apis.get_api("openai", 0)["key"] == "test-key-not-real"


def test_dialog_switches_models_without_saving_and_cancel_discards(gui_app):
    cls = gui_app.load("guis/guis_openai").OpenAISettingsDialog
    settings = gui_app.frame.gestor_settings
    settings._enableTranslation = True
    settings.openai_model_api = "my-api-model"
    settings.openai_model_oauth = "my-chatgpt-model"
    dialog = cls(None, gui_app.frame)
    assert not settings._enableTranslation, "Reading settings must not trigger live translation"
    assert dialog.model_combo.GetStringSelection() == "my-api-model"
    assert isinstance(dialog.model_combo, gui_app.wx.Choice)
    assert "auto" in dialog.model_combo.choices
    assert dialog.status.name
    assert not dialog.login_button.enabled
    _choose_model(dialog, "edited-api-model")
    dialog.auth_choice.SetSelection(1)
    dialog.on_auth_choice(None)
    assert dialog.model_combo.GetStringSelection() == "my-chatgpt-model"
    assert dialog.login_button.enabled
    _choose_model(dialog, "edited-oauth-model")
    dialog.auth_choice.SetSelection(0)
    dialog.on_auth_choice(None)
    assert dialog.model_combo.GetStringSelection() == "edited-api-model"
    assert settings.openai_model_api == "my-api-model"
    dialog.codex_path.SetValue("C:/Apps/codex.exe")
    dialog.on_cancel(None)
    dialog.Destroy()
    assert settings.openai_auth_mode == "api_key"
    assert settings.openai_model_oauth == "my-chatgpt-model"
    assert settings.openai_codex_path == ""
    assert settings._enableTranslation


def test_save_applies_both_models_and_path_without_changing_default_provider(gui_app):
    cls = gui_app.load("guis/guis_openai").OpenAISettingsDialog
    settings = gui_app.frame.gestor_settings
    settings.choiceOnline = 5
    dialog = cls(None, gui_app.frame)
    _choose_model(dialog, "custom-api")
    dialog.auth_choice.SetSelection(1)
    dialog.on_auth_choice(None)
    _choose_model(dialog, "custom-oauth")
    dialog.codex_path.SetValue("C:/Apps/codex.exe")
    dialog.on_save(None)
    assert dialog.result == gui_app.wx.ID_OK
    loaded = type(settings)(None)
    assert loaded.openai_auth_mode == "chatgpt"
    assert loaded.openai_model_api == "custom-api"
    assert loaded.openai_model_oauth == "custom-oauth"
    assert loaded.openai_codex_path == "C:/Apps/codex.exe"
    assert loaded.choiceOnline == 5
    assert gui_app.frame.gestor_apis.get_api("openai", 0)["key"] == "test-key-not-real"


def test_refresh_models_is_async_scoped_and_preserves_typed_model(gui_app):
    module = gui_app.load("guis/guis_openai")
    settings = gui_app.frame.gestor_settings
    settings.api_openai = 0
    started, release = threading.Event(), threading.Event()
    calls = []

    def list_models(api_key, **kwargs):
        calls.append((api_key, kwargs, threading.get_ident()))
        started.set()
        assert release.wait(3)
        return ["gpt-account-model", "gpt-account-model", "another-model"]

    gui_app.frame.gestor_translate = types.SimpleNamespace(list_openai_models=list_models)
    dialog = module.OpenAISettingsDialog(None, gui_app.frame)
    dialog.codex_path.SetValue("C:/Apps/codex.exe")
    dialog.on_refresh_models(None)
    assert started.wait(3)
    assert not dialog.refresh_button.enabled
    assert not dialog.save_button.enabled
    assert dialog.cancel_button.enabled
    _choose_model(dialog, "typed-while-refreshing")
    release.set()
    gui_app.wx.pump_until(lambda: not dialog._busy)
    assert dialog.model_combo.GetStringSelection() == "typed-while-refreshing"
    assert dialog.model_combo.choices.count("gpt-account-model") == 1
    assert "auto" in dialog.model_combo.choices
    assert settings.openai_model_api == "auto"
    key, kwargs, worker = calls[0]
    assert key == "test-key-not-real"
    assert kwargs == {"auth_mode": "api_key", "codex_home": str(Path(module.globalVars.appArgs.configPath) / "TranslateAdvanced" / "codex"), "codex_path": "C:/Apps/codex.exe"}
    assert worker != gui_app.wx.owner
    assert gui_app.wx.focus is dialog.status
    assert "test-key-not-real" not in dialog.status.GetValue()


@pytest.mark.parametrize("api_index", [-1, 99, None, "not-an-index", True])
def test_invalid_selected_api_index_does_not_send_or_choose_another_key(gui_app, api_index):
    module = gui_app.load("guis/guis_openai")
    gui_app.frame.gestor_settings.api_openai = api_index
    calls = []
    gui_app.frame.gestor_translate = types.SimpleNamespace(list_openai_models=lambda *args, **kwargs: calls.append(args))
    dialog = module.OpenAISettingsDialog(None, gui_app.frame)
    dialog.on_refresh_models(None)
    assert not calls
    assert not dialog._busy
    assert "API" in dialog.status.GetValue()


def test_chatgpt_model_refresh_never_sends_stored_api_key(gui_app):
    module = gui_app.load("guis/guis_openai")
    gui_app.frame.gestor_settings.api_openai = 0
    gui_app.frame.gestor_settings.openai_auth_mode = "chatgpt"
    calls = []
    gui_app.frame.gestor_translate = types.SimpleNamespace(list_openai_models=lambda key, **kwargs: calls.append((key, kwargs)) or ["oauth-model"])
    dialog = module.OpenAISettingsDialog(None, gui_app.frame)
    assert not calls, "Opening or reading the dialog must not fetch models"
    dialog.on_refresh_models(None)
    gui_app.wx.pump_until(lambda: not dialog._busy)
    assert calls[0][0] == ""
    assert calls[0][1]["auth_mode"] == "chatgpt"
    assert "oauth-model" in dialog.model_combo.choices


def test_late_refresh_result_after_escape_never_touches_destroyed_widgets(gui_app):
    module = gui_app.load("guis/guis_openai")
    settings = gui_app.frame.gestor_settings
    settings._enableTranslation = True
    settings.api_openai = 0
    started, release = threading.Event(), threading.Event()

    def list_models(*args, **kwargs):
        started.set()
        assert release.wait(3)
        return ["late-model"]

    gui_app.frame.gestor_translate = types.SimpleNamespace(list_openai_models=list_models)
    dialog = module.OpenAISettingsDialog(None, gui_app.frame)
    dialog.on_refresh_models(None)
    assert started.wait(3)
    dialog.on_key(types.SimpleNamespace(GetKeyCode=lambda: gui_app.wx.WXK_ESCAPE))
    dialog.Destroy()
    assert settings._enableTranslation
    release.set()
    callback, args, kwargs = gui_app.wx.pending.get(timeout=3)
    callback(*args, **kwargs)  # Fake wx raises on post-destruction widget access.
    gui_app.wx.drain()
    assert dialog.result == gui_app.wx.ID_CANCEL


def test_refresh_failure_is_actionable_without_echoing_secrets(gui_app):
    module = gui_app.load("guis/guis_openai")
    gui_app.frame.gestor_settings.api_openai = 0

    def list_models(*args, **kwargs):
        raise RuntimeError("test-key-not-real https://auth.openai.com/?code=secret")

    gui_app.frame.gestor_translate = types.SimpleNamespace(list_openai_models=list_models)
    dialog = module.OpenAISettingsDialog(None, gui_app.frame)
    dialog.on_refresh_models(None)
    gui_app.wx.pump_until(lambda: not dialog._busy)
    assert "API" in dialog.status.GetValue()
    assert "test-key-not-real" not in dialog.status.GetValue()
    assert "?code=" not in dialog.status.GetValue()
    assert dialog.refresh_button.enabled
    assert dialog.model_combo.GetStringSelection() == "auto"


def test_options_opens_real_dialog_with_current_api_selection(gui_app):
    module = gui_app.load("guis/guis_openai")
    options = gui_app.load("guis/guis_options").ConfigDialog(None, gui_app.frame)
    options.default_api_index["openai"] = 0
    gui_app.frame.gestor_settings._enableTranslation = True
    options.on_openai_settings(None)
    dialogs = [widget for widget in gui_app.wx.widgets if isinstance(widget, module.OpenAISettingsDialog)]
    assert len(dialogs) == 1
    assert dialogs[0].api_index == 0
    assert dialogs[0].destroyed
    assert gui_app.frame.gestor_settings._enableTranslation
    assert gui_app.wx.focus is options.openai_button


def _choose_model(dialog, model: str) -> None:
    """Przygotowuje dostępną pozycję i wybiera ją jak użytkownik."""
    dialog.model_combo.Append(model)
    dialog.model_combo.SetStringSelection(model)


class CodexBoundary:
    """External account/process I/O, not dialog or persistence logic."""
    def __init__(self):
        self.calls = []
        self.account_data = {}
        self.url = "https://auth.openai.com/oauth/authorize?state=not-a-real-secret"
        self.start_release = None
        self.wait_release = None
        self.started = threading.Event()
        self.waiting = threading.Event()
        self.cancelled = threading.Event()
        self.wait_result = True
        self.prepare_release = None
        self.preparing = threading.Event()

    def prepare_runtime(self, *, cancel_event=None, progress=None) -> None:
        """Symuluje przygotowanie programu przed otwarciem przeglądarki."""
        self.calls.append(("prepare", threading.get_ident()))
        self.preparing.set()
        if progress:
            progress("download", 0, 100)
        if self.prepare_release:
            assert self.prepare_release.wait(3)
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("Anulowano przygotowanie")
        if progress:
            progress("ready", 100, 100)

    def account(self):
        self.calls.append(("account", threading.get_ident()))
        return self.account_data

    def cached_models(self) -> list[str]:
        """Udostępnia modele testowego konta bez połączenia z siecią."""
        return ["gpt-5.6-sol", "gpt-5.6-luna"]

    def list_models(self) -> list[str]:
        """Symuluje świeże pobranie modeli po logowaniu."""
        return self.cached_models()

    def start_login(self):
        self.calls.append(("start", threading.get_ident()))
        self.started.set()
        if self.start_release:
            assert self.start_release.wait(3)
        return {"authUrl": self.url, "loginId": "login-test"}

    def wait_login(self, login_id, timeout):
        self.calls.append(("wait", threading.get_ident(), login_id, timeout))
        self.waiting.set()
        if self.wait_release:
            assert self.wait_release.wait(3)
        if self.cancelled.is_set():
            return False
        if self.wait_result:
            self.account_data = {"type": "chatgpt", "email": "test@example.test", "extra": "never-show-me"}
        return self.wait_result

    def cancel_login(self, login_id):
        self.calls.append(("cancel", threading.get_ident(), login_id))
        self.cancelled.set()
        if self.wait_release:
            self.wait_release.set()

    def logout(self):
        self.calls.append(("logout", threading.get_ident()))
        self.account_data = {}


@pytest.fixture
def oauth_app(gui_app, monkeypatch):
    backend = gui_app.load("utils/utils_codex")
    client = CodexBoundary()
    factory_calls = []

    def factory(codex_home, codex_path=""):
        factory_calls.append((codex_home, codex_path, threading.get_ident()))
        return client

    monkeypatch.setattr(backend, "get_client", factory)
    gui_app.frame.gestor_settings.openai_auth_mode = "chatgpt"
    module = gui_app.load("guis/guis_openai")
    opened = []
    # Browser launch is external I/O; no real sign-in, account or credentials.
    import webbrowser
    monkeypatch.setattr(webbrowser, "open", lambda url, **kwargs: opened.append(url) or True)
    return types.SimpleNamespace(app=gui_app, module=module, client=client, opened=opened, factory_calls=factory_calls)


def test_explicit_login_opens_only_trusted_url_and_verifies_account_async(oauth_app):
    env = oauth_app
    app = env.app
    settings = app.frame.gestor_settings
    dialog = env.module.OpenAISettingsDialog(None, app.frame)
    assert not env.factory_calls
    assert not env.client.calls
    assert not env.opened
    dialog.codex_path.SetValue("C:/Tools/codex.exe")
    dialog.on_login(None)
    app.wx.pump_until(lambda: not dialog._busy)
    assert env.opened == [env.client.url]
    assert [call[0] for call in env.client.calls] == ["prepare", "start", "wait", "account"]
    assert all(call[1] != app.wx.owner for call in env.client.calls)
    home, path, thread = env.factory_calls[0]
    assert home == str(Path(env.module.globalVars.appArgs.configPath) / "TranslateAdvanced" / "codex")
    assert path == "C:/Tools/codex.exe"
    assert thread != app.wx.owner
    assert "Signed in" in dialog.status.GetValue()
    assert "never-show-me" not in dialog.status.GetValue()
    assert "state=" not in dialog.status.GetValue()
    assert app.messages[-1] == dialog.status.GetValue()
    assert settings.openai_codex_path == "C:/Tools/codex.exe"
    dialog.on_cancel(None)
    assert env.client.account_data["type"] == "chatgpt", "Cancel preferences must not undo explicit login"


@pytest.mark.parametrize("url", [
    "http://auth.openai.com/authorize", "https://evil.example/", "https://auth.openai.com.evil.example/",
    "https://user:secret@auth.openai.com/", "https://auth.openai.com:444/", "https://auth.openai.com./",
    "https://auth.openai.com\\@evil.example/", "https://auth.openai.com/\n?secret=value", "not-a-url", None,
])
def test_untrusted_oauth_url_never_opens_browser_and_login_is_cancelled(oauth_app, url):
    env = oauth_app
    env.client.url = url
    dialog = env.module.OpenAISettingsDialog(None, env.app.frame)
    dialog.on_login(None)
    env.app.wx.pump_until(lambda: not dialog._busy)
    assert not env.opened
    assert env.client.cancelled.is_set()
    assert not env.client.waiting.is_set()
    assert "Signed in" not in dialog.status.GetValue()
    assert "secret" not in dialog.status.GetValue()


@pytest.mark.parametrize("close_method", ["on_cancel", "destroy"])
def test_close_while_starting_login_cancels_late_login_without_opening_browser(oauth_app, close_method):
    env = oauth_app
    env.client.start_release = threading.Event()
    settings = env.app.frame.gestor_settings
    settings._enableTranslation = True
    dialog = env.module.OpenAISettingsDialog(None, env.app.frame)
    dialog.on_login(None)
    assert env.client.started.wait(3)
    if close_method == "on_cancel":
        dialog.on_cancel(None)
    dialog.Destroy()
    assert settings._enableTranslation
    env.client.start_release.set()
    assert env.client.cancelled.wait(3)
    callback, args, kwargs = env.app.wx.pending.get(timeout=3)
    callback(*args, **kwargs)
    assert not env.opened
    assert [call[0] for call in env.client.calls].count("cancel") == 1


def test_cancel_login_is_async_and_keeps_preferences_dialog_open(oauth_app):
    env = oauth_app
    env.client.wait_release = threading.Event()
    dialog = env.module.OpenAISettingsDialog(None, env.app.frame)
    dialog.on_login(None)
    assert env.client.waiting.wait(3)
    assert dialog.cancel_login_button.enabled
    assert not dialog.logout_button.enabled
    dialog.on_cancel_login(None)
    assert env.client.cancelled.wait(3)
    env.app.wx.pump_until(lambda: not dialog._busy)
    assert not dialog._closed
    assert dialog.login_button.enabled
    assert not dialog.cancel_login_button.enabled
    assert all(call[1] != env.app.wx.owner for call in env.client.calls)
    assert "Signed in" not in dialog.status.GetValue()


def test_login_timeout_does_not_claim_success(oauth_app):
    env = oauth_app
    env.client.wait_result = False
    dialog = env.module.OpenAISettingsDialog(None, env.app.frame)
    dialog.on_login(None)
    env.app.wx.pump_until(lambda: not dialog._busy)
    assert "Signed in" not in dialog.status.GetValue()
    assert dialog.login_button.enabled
    assert env.client.cancelled.is_set()


def test_explicit_account_check_and_logout_verify_state_without_changing_preferences(oauth_app):
    env = oauth_app
    env.client.account_data = {"type": "chatgpt", "extra": "never-show-me"}
    dialog = env.module.OpenAISettingsDialog(None, env.app.frame)
    dialog.on_account(None)
    env.app.wx.pump_until(lambda: not dialog._busy)
    assert "Signed in" in dialog.status.GetValue()
    assert "never-show-me" not in dialog.status.GetValue()
    dialog.on_logout(None)
    env.app.wx.pump_until(lambda: not dialog._busy)
    assert [call[0] for call in env.client.calls] == ["account", "logout", "account"]
    assert all(call[1] != env.app.wx.owner for call in env.client.calls)
    assert "Signed out" in dialog.status.GetValue()
    assert env.app.frame.gestor_settings.openai_auth_mode == "chatgpt"
    assert env.app.frame.gestor_apis.get_api("openai", 0)["key"] == "test-key-not-real"


def test_oauth_warning_and_installation_guidance_are_visible_without_network(gui_app):
    module = gui_app.load("guis/guis_openai")
    dialog = module.OpenAISettingsDialog(None, gui_app.frame)
    labels = " ".join(widget.label for widget in gui_app.wx.widgets)
    assert "eksperymentalne" in labels.lower()
    assert "pobierze oficjalny komponent" in labels
    assert "Codex" in labels
    assert "Anuluj nie cofa logowania" in labels
    assert dialog.codex_path.name


def test_advanced_path_is_hidden_and_survives_mode_changes(oauth_app):
    """Schowana ścieżka pozostaje zapisana, a tryb API nie pokazuje jej nigdy."""
    env = oauth_app
    settings = env.app.frame.gestor_settings
    settings.openai_codex_path = "C:/Custom/codex.exe"
    dialog = env.module.OpenAISettingsDialog(None, env.app.frame)
    assert dialog.advanced_toggle.shown
    assert not dialog.codex_path.shown
    assert not dialog.path_label.shown
    assert dialog.codex_path.GetValue() == settings.openai_codex_path
    dialog.advanced_toggle.SetValue(True)
    dialog.on_advanced(None)
    assert dialog.codex_path.shown
    dialog.auth_choice.SetSelection(0)
    dialog.on_auth_choice(None)
    assert not dialog.advanced_toggle.shown
    assert not dialog.codex_path.shown
    dialog.on_save(None)
    assert settings.openai_codex_path == "C:/Custom/codex.exe"


@pytest.mark.parametrize("close_window", [False, True])
def test_cancel_preparation_never_opens_browser(oauth_app, close_window, monkeypatch):
    """Anulowanie pobierania i zamknięcie okna nie rozpoczynają późnego OAuth."""
    env = oauth_app
    finished = threading.Event()
    call_after = env.app.wx.CallAfter

    def track_delivery(callback, *args, **kwargs):
        if callback.__name__ != "deliver":
            return call_after(callback, *args, **kwargs)

        def deliver():
            try:
                callback(*args, **kwargs)
            finally:
                finished.set()

        call_after(deliver)

    monkeypatch.setattr(env.app.wx, "CallAfter", track_delivery)
    env.client.prepare_release = threading.Event()
    dialog = env.module.OpenAISettingsDialog(None, env.app.frame)
    dialog.on_login(None)
    assert env.client.preparing.wait(3)
    if close_window:
        dialog.on_cancel(None)
        dialog.Destroy()
    else:
        dialog.on_cancel_login(None)
    env.client.prepare_release.set()
    env.app.wx.pump_until(finished.is_set)
    env.app.wx.drain()
    assert not env.opened
    assert [call[0] for call in env.client.calls] == ["prepare"]
    if not close_window:
        assert not dialog._busy
        assert "cancellation" in dialog.status.GetValue()


def test_preparation_failure_keeps_retry_available(oauth_app, monkeypatch):
    """Awaria pobierania przywraca przycisk logowania bez ujawnienia wyjątku."""
    env = oauth_app

    def fail(**kwargs):
        raise OSError("tajny-klucz i prywatna-sciezka")

    monkeypatch.setattr(env.client, "prepare_runtime", fail)
    dialog = env.module.OpenAISettingsDialog(None, env.app.frame)
    dialog.on_login(None)
    env.app.wx.pump_until(lambda: not dialog._busy)
    assert dialog.login_button.enabled
    assert "tajny" not in dialog.status.GetValue()
    assert "Nie udało się przygotować" in dialog.status.GetValue()
    assert not env.opened


def test_preparation_shows_safe_installer_reason(oauth_app, monkeypatch):
    """Stały komunikat instalatora wyjaśnia rzeczywistą przyczynę odmowy."""
    env = oauth_app

    def fail(**kwargs):
        raise env.module.RuntimeInstallError("Logowanie kontem ChatGPT wymaga 64-bitowego systemu Windows.")

    monkeypatch.setattr(env.client, "prepare_runtime", fail)
    dialog = env.module.OpenAISettingsDialog(None, env.app.frame)
    dialog.on_login(None)
    env.app.wx.pump_until(lambda: not dialog._busy)
    assert "64-bitowego" in dialog.status.GetValue()
    assert not env.opened


def test_model_choices_offer_only_auto_and_saved_literal_before_refresh(gui_app):
    settings = gui_app.frame.gestor_settings
    settings.openai_model_oauth = "user-saved-literal-model"
    dialog = gui_app.load("guis/guis_openai").OpenAISettingsDialog(None, gui_app.frame)
    assert dialog.model_combo.choices == ["auto"]
    dialog.auth_choice.SetSelection(1)
    dialog.on_auth_choice(None)
    assert dialog.model_combo.choices == ["auto", "user-saved-literal-model"]


def test_late_cancel_after_close_is_harmless(gui_app):
    dialog = gui_app.load("guis/guis_openai").OpenAISettingsDialog(None, gui_app.frame)
    dialog.on_cancel(None)
    dialog.Destroy()
    dialog.on_cancel(None)
    dialog.on_key(types.SimpleNamespace(GetKeyCode=lambda: gui_app.wx.WXK_ESCAPE))


def test_model_is_standard_noneditable_choice(gui_app):
    """NVDA powinno dostać zwykłą listę, bez pola edycji."""
    dialog = gui_app.load("guis/guis_openai").OpenAISettingsDialog(None, gui_app.frame)
    assert isinstance(dialog.model_combo, gui_app.wx.Choice)
    assert dialog.model_combo.GetStringSelection() == "auto"


def test_oauth_options_hide_key_manager_and_default_key_button(gui_app):
    """Konto ChatGPT nie może żądać wyboru domyślnego klucza."""
    gui_app.frame.gestor_settings.openai_auth_mode = "chatgpt"
    options = gui_app.load("guis/guis_options").ConfigDialog(None, gui_app.frame)
    options.translator_choice.SetSelection(9)
    options.on_translator_choice(types.SimpleNamespace(GetString=lambda: "OpenAI (API / ChatGPT OAuth)"))
    assert not options.api_listbox.shown
    assert not options.default_button.shown
    assert not options.api_label.shown
    options.on_accept(None)
    assert gui_app.frame.gestor_settings.choiceOnline == 9


def test_opening_signed_in_dialog_restores_account_and_models(oauth_app):
    """Ponowne otwarcie rozpoznaje konto bez klikania odświeżania."""
    env = oauth_app
    env.client.account_data = {"type": "chatgpt"}
    env.client.cached_models = lambda: ["gpt-5.6-sol", "gpt-5.6-luna"]
    dialog = env.module.OpenAISettingsDialog(None, env.app.frame)
    env.app.wx.drain()
    env.app.wx.pump_until(lambda: not dialog._busy)
    assert not dialog.login_button.shown
    assert dialog.logout_button.shown
    assert dialog.logout_button.enabled
    assert "gpt-5.6-sol" in dialog.model_combo.choices
    assert env.app.wx.focus is dialog.auth_choice


def test_login_automatically_loads_models_and_activates_account_mode(oauth_app):
    """Jawne logowanie od razu przygotowuje konto do tłumaczenia."""
    env = oauth_app
    loaded = []
    env.client.cached_models = lambda: loaded.append(True) or ["gpt-5.6-sol"]
    dialog = env.module.OpenAISettingsDialog(None, env.app.frame)
    dialog.on_login(None)
    env.app.wx.pump_until(lambda: not dialog._busy)
    assert loaded
    assert "gpt-5.6-sol" in dialog.model_combo.choices
    assert not dialog.login_button.shown
    assert env.app.frame.gestor_settings.openai_auth_mode == "chatgpt"


def test_login_from_api_mode_persists_chatgpt_even_when_preferences_are_cancelled(oauth_app):
    """Sukces logowania nie zostawia tłumacza w trybie pustego klucza API."""
    env = oauth_app
    settings = env.app.frame.gestor_settings
    settings.openai_auth_mode = "api_key"
    settings.api_openai = None
    dialog = env.module.OpenAISettingsDialog(None, env.app.frame)
    dialog.auth_choice.SetSelection(1)
    dialog.on_auth_choice(None)
    dialog.on_login(None)
    env.app.wx.pump_until(lambda: not dialog._busy)
    dialog.on_cancel(None)
    loaded = type(settings)(None)
    assert loaded.openai_auth_mode == "chatgpt"
    assert loaded.api_openai is None
    assert loaded.choiceOnline == 5


def test_use_provider_applies_oauth_without_any_api_key(gui_app):
    """Wybór silnika i domyślnego klucza to osobne operacje."""
    settings = gui_app.frame.gestor_settings
    settings.openai_auth_mode = "chatgpt"
    settings.api_openai = None
    dialog = gui_app.load("guis/guis_openai").OpenAISettingsDialog(None, gui_app.frame)
    dialog.on_use_provider(None)
    assert settings.choiceOnline == 9
    assert settings.openai_auth_mode == "chatgpt"
    assert settings.api_openai is None


def test_use_provider_updates_parent_even_with_unsaved_provider_choice(gui_app, monkeypatch):
    """Rodzic nie może nadpisać jawnego wyboru silnika starą listą."""
    settings = gui_app.frame.gestor_settings
    settings.choiceOnline = 9
    settings.openai_auth_mode = "chatgpt"
    module = gui_app.load("guis/guis_openai")
    options = gui_app.load("guis/guis_options").ConfigDialog(None, gui_app.frame)
    options.select_choice_by_value(5)

    def choose_provider(dialog):
        dialog.on_use_provider(None)
        return gui_app.wx.ID_OK

    monkeypatch.setattr(module.OpenAISettingsDialog, "ShowModal", choose_provider)
    options.on_openai_settings(None)
    assert options.GetSelectionChoice() == 9
    assert not options.default_button.shown


@pytest.mark.parametrize("payload, expected", [
    ({"auth_mode": "chatgpt", "tokens": {"access_token": "test-access", "account_id": "test-account"}}, "chatgpt"),
    ({"auth_mode": "chatgpt", "tokens": {}}, "api_key"),
    ({"auth_mode": "api_key", "OPENAI_API_KEY": "test-key"}, "api_key"),
    (None, "api_key"),
])
def test_existing_account_recovers_missing_auth_preference(app_modules, payload, expected):
    """Ustawienia odzyskują wyłącznie poprawną sesję we własnym profilu."""
    app_modules.conf["TranslateAdvanced"]["api_openai"] = "None"
    backend = app_modules.load("utils/utils_codex_response")
    home = app_modules.tmp_path / "nvda" / "TranslateAdvanced" / "codex"
    home.mkdir(parents=True)
    (home / backend._MARKER).write_text(backend._MARKER_TEXT, encoding="utf-8")
    if payload is not None:
        (home / "auth.json").write_text(json.dumps(payload), encoding="utf-8")
    settings = app_modules.load("managers/managers_settings").GestorSettings(None)
    assert settings.openai_auth_mode == expected


def test_failed_model_fetch_preserves_confirmed_login(oauth_app):
    """Awaria listy modeli nie może udawać wylogowania."""
    env = oauth_app
    env.client.account_data = {"type": "chatgpt"}

    def unavailable() -> list[str]:
        raise OSError("prywatny-token-testowy")

    env.client.cached_models = unavailable
    dialog = env.module.OpenAISettingsDialog(None, env.app.frame)
    env.app.wx.drain()
    env.app.wx.pump_until(lambda: not dialog._busy)
    assert not dialog.login_button.shown
    assert dialog.logout_button.enabled
    assert "zalogowane" in dialog.status.GetValue()
    assert "prywatny" not in dialog.status.GetValue()


def test_auto_check_after_close_does_not_start_process(oauth_app):
    """Zamknięcie okna przed obsłużeniem kolejki nie uruchamia konta."""
    env = oauth_app
    dialog = env.module.OpenAISettingsDialog(None, env.app.frame)
    dialog.on_cancel(None)
    dialog.Destroy()
    env.app.wx.drain()
    assert not env.factory_calls


def test_logout_clears_models_and_restores_login_button(oauth_app):
    """Wylogowanie usuwa stary wybór i udostępnia ponowne logowanie."""
    env = oauth_app
    env.client.account_data = {"type": "chatgpt"}
    dialog = env.module.OpenAISettingsDialog(None, env.app.frame)
    dialog.on_account(None)
    env.app.wx.pump_until(lambda: not dialog._busy)
    dialog.on_logout(None)
    env.app.wx.pump_until(lambda: not dialog._busy)
    assert dialog.login_button.shown and dialog.login_button.enabled
    assert not dialog.logout_button.shown
    assert dialog.model_combo.choices == ["auto"]
    assert dialog.model_combo.GetStringSelection() == "auto"


@pytest.mark.parametrize("url", ["https://chatgpt.com/auth/login", "https://auth.openai.com/oauth/authorize"])
def test_both_official_login_hosts_are_allowed(gui_app, url):
    """Aktualny protokół może rozpocząć logowanie na obu domenach."""
    module = gui_app.load("guis/guis_openai")
    assert module._validated_auth_url(url) == url


@pytest.mark.parametrize("url", ["https://chatgpt.com.evil.test/", "https://chatgpt.com@evil.test/", "https://chatgpt.com:444/", "https://chatgpt.com./", "https://chatgpt.com\\@evil.test/"])
def test_fake_chatgpt_login_hosts_are_rejected(gui_app, url):
    """Podobna nazwa domeny nie wystarcza do otwarcia przeglądarki."""
    module = gui_app.load("guis/guis_openai")
    with pytest.raises(ValueError):
        module._validated_auth_url(url)


def test_missing_codex_error_does_not_echo_tokens_and_explains_installation(oauth_app, monkeypatch):
    env = oauth_app

    def unavailable(*args, **kwargs):
        raise FileNotFoundError("secret-key https://auth.openai.com/?state=secret-state")

    monkeypatch.setattr(sys.modules["_ta_openai_tests.utils.utils_codex"], "get_client", unavailable)
    dialog = env.module.OpenAISettingsDialog(None, env.app.frame)
    dialog.on_account(None)
    env.app.wx.pump_until(lambda: not dialog._busy)
    assert "przygotować komponent" in dialog.status.GetValue()
    assert "zaawansowanych" in dialog.status.GetValue().lower()
    assert "secret" not in dialog.status.GetValue()
    assert not env.client.calls
    assert not env.opened


def test_logout_without_confirmed_signout_does_not_report_success(oauth_app, monkeypatch):
    env = oauth_app
    env.client.account_data = {"type": "chatgpt"}
    monkeypatch.setattr(env.client, "logout", lambda: None)
    dialog = env.module.OpenAISettingsDialog(None, env.app.frame)
    dialog.on_logout(None)
    env.app.wx.pump_until(lambda: not dialog._busy)
    assert "Signed out" not in dialog.status.GetValue()
    assert "Could not confirm" in dialog.status.GetValue()


def test_native_wx_dialog_smoke_when_wx_is_available(app_modules, monkeypatch):
    wx = pytest.importorskip("wx", reason="Native wx smoke needs wxPython; unit tests use scoped wx boundary")
    native = wx.App(False)
    settings = app_modules.load("managers/managers_settings").GestorSettings(None)
    settings._enableTranslation = True
    apis = app_modules.load("managers/managers_apis").APIManager(settings.file_api)
    apis.add_api("openai", "Smoke test only", "not-a-real-key")
    frame = types.SimpleNamespace(
        gestor_settings=settings, gestor_apis=apis,
        gestor_translate=types.SimpleNamespace(list_openai_models=lambda *args, **kwargs: ["native-test-model"]),
    )
    module = app_modules.load("guis/guis_openai")
    parent = wx.Frame(None)
    dialog = module.OpenAISettingsDialog(parent, frame)
    errors = []
    deadline = time.monotonic() + 5

    def after_refresh():
        try:
            if dialog._busy:
                assert time.monotonic() < deadline, "Native wx worker did not finish"
                wx.CallLater(20, after_refresh)
                return
            assert "native-test-model" in dialog.model_combo.GetItems()
            assert dialog.model_combo.GetStringSelection() == "native-custom-oauth"
            assert settings.openai_model_oauth == "auto"
            dialog.on_save(None)
        except Exception as error:
            errors.append(error)
            dialog.on_cancel(None)

    def exercise():
        try:
            assert not settings._enableTranslation
            assert dialog.auth_choice.GetName()
            assert dialog.status.GetWindowStyleFlag() & wx.TE_READONLY
            assert isinstance(dialog.model_combo, wx.Choice)
            assert not dialog.codex_path.IsShown()
            _choose_model(dialog, "native-custom-api")
            dialog.auth_choice.SetSelection(1)
            dialog.on_auth_choice(None)
            assert dialog.login_button.IsEnabled()
            assert not dialog.codex_path.IsShown()
            dialog.advanced_toggle.SetValue(True)
            dialog.on_advanced(None)
            assert dialog.codex_path.IsShown()
            dialog.advanced_toggle.SetValue(False)
            dialog.on_advanced(None)
            assert not dialog.codex_path.IsShown()
            _choose_model(dialog, "native-custom-oauth")
            dialog.on_refresh_models(None)
            wx.CallLater(20, after_refresh)
        except Exception as error:
            errors.append(error)
            dialog.on_cancel(None)

    try:
        print("Native wx:", wx.version(), "dialog size:", tuple(dialog.GetSize()))
        wx.CallAfter(exercise)
        assert dialog.ShowModal() == wx.ID_OK
        assert not errors, errors
        assert settings._enableTranslation
        assert settings.openai_model_api == "native-custom-api"
        assert settings.openai_model_oauth == "native-custom-oauth"
        assert settings.choiceOnline == 5
    finally:
        dialog.Destroy()
        parent.Destroy()
        native.ProcessPendingEvents()
        native.Destroy()
