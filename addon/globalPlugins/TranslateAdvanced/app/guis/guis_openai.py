# -*- coding: utf-8 -*-
# This file is covered by the GNU General Public License.
"""Dostępne ustawienia OpenAI z odczytem konta i modeli w tle."""

from __future__ import annotations

import os
import threading
import webbrowser
from typing import TYPE_CHECKING, Any, Callable
from urllib.parse import urlsplit

import addonHandler
import globalVars
import ui
import wx

if TYPE_CHECKING:
    from ..utils.utils_codex import CodexClient

addonHandler.initTranslation()


def _validated_auth_url(value: str) -> str:
    """Dopuszcza wyłącznie oficjalne adresy logowania OpenAI."""
    if not isinstance(value, str) or "\\" in value or any(ord(char) <= 32 or ord(char) == 127 for char in value):
        raise ValueError("Untrusted sign-in address")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.netloc.lower() not in (
        "auth.openai.com", "auth.openai.com:443", "chatgpt.com", "chatgpt.com:443",
    ):
        raise ValueError("Untrusted sign-in address")
    return value


def _get_client(codex_home: str, codex_path: str) -> CodexClient:
    # Klient jest pobierany wyłącznie w wątku roboczym.
    from ..utils.utils_codex import get_client
    return get_client(codex_home, codex_path=codex_path)


class _LoginAttempt:
    """Anuluje również logowanie rozpoczęte po zamknięciu okna."""

    def __init__(self) -> None:
        self.cancelled = threading.Event()
        self._lock = threading.Lock()
        self._client = None
        self._login_id = None
        self._cancel_sent = False

    def attach(self, client: CodexClient, login_id: str) -> None:
        """Wiąże żądanie z klientem i uwzględnia wcześniejsze anulowanie."""
        with self._lock:
            self._client, self._login_id = client, login_id
        if self.cancelled.is_set():
            self.cancel_if_ready()

    def complete(self) -> None:
        """Oznacza zakończone logowanie jako niewymagające anulowania."""
        with self._lock:
            self._login_id = None

    def request_cancel(self) -> None:
        """Zleca anulowanie poza wątkiem interfejsu."""
        self.cancelled.set()
        threading.Thread(target=self.cancel_if_ready, daemon=True).start()

    def cancel_if_ready(self) -> None:
        """Anuluje aktywne żądanie najwyżej raz."""
        # This method is only called on workers, never the wx thread.
        with self._lock:
            if self._login_id is None or self._cancel_sent:
                return
            self._cancel_sent = True
            client, login_id = self._client, self._login_id
        try:
            client.cancel_login(login_id)
        except Exception:
            # The UI says cancellation was requested, not that sign-out occurred.
            # No exception text/URLs/credentials may reach logs or screen readers.
            pass


class OpenAISettingsDialog(wx.Dialog):
    """Ustawienia modelu oraz niezależne działania konta ChatGPT."""

    def __init__(self, parent: wx.Window | None, frame: Any, api_index: int | None = None) -> None:
        super().__init__(parent, title=_("OpenAI (API / ChatGPT OAuth)"),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.frame = frame
        settings = frame.gestor_settings
        self.api_index = settings.api_openai if api_index is None else api_index
        self._closed = False
        self._busy = False
        self._operation = 0
        self._login = None
        self._signed_in = None
        self.use_selected_provider = False
        self._codex_home = os.path.join(globalVars.appArgs.configPath, "TranslateAdvanced", "codex")
        self._mode = "chatgpt" if settings.openai_auth_mode == "chatgpt" else "api_key"
        self._models = {"api_key": settings.openai_model_api or "auto",
                        "chatgpt": settings.openai_model_oauth or "auto"}
        # Never imply account access to a hard-coded/stale model. Refresh fills
        # the catalog; _show_model also retains the user's saved literal ID.
        self._choices = {"api_key": ["auto"], "chatgpt": ["auto"]}
        sizer = wx.BoxSizer(wx.VERTICAL)
        self._label(sizer, _("&Authentication:"))
        self.auth_choice = wx.Choice(self, choices=[_("API key"), _("ChatGPT OAuth (Codex CLI)")])
        self.auth_choice.SetName(_("Authentication"))
        self.auth_choice.SetSelection(1 if self._mode == "chatgpt" else 0)
        sizer.Add(self.auth_choice, 0, wx.ALL | wx.EXPAND, 6)
        self._label(sizer, _("Konto ChatGPT nie wymaga klucza API. Po zalogowaniu modele pobierają się automatycznie i są zapamiętywane do wylogowania."))
        self._label(sizer, _("&Model:"))
        self.model_combo = wx.Choice(self)
        self.model_combo.SetName(_("Model"))
        self.model_combo.SetHelpText(_("Wybierz model z listy. Opcja auto dobiera dostępny model. Wybory dla konta ChatGPT i klucza API są zapisywane osobno."))
        sizer.Add(self.model_combo, 0, wx.ALL | wx.EXPAND, 6)
        self.refresh_button = wx.Button(self, label=_("&Refresh models"))
        sizer.Add(self.refresh_button, 0, wx.ALL, 6)
        self.path_label = self._label(sizer, _("Codex &executable path (optional):"))
        self.codex_path = wx.TextCtrl(self, value=settings.openai_codex_path or "")
        self.codex_path.SetName(_("Codex executable path (optional)"))
        self.codex_path.SetHelpText(_("Enter the full path to an installed codex.exe, or leave blank to find it on PATH. Do not enter an API key or token."))
        sizer.Add(self.codex_path, 0, wx.ALL | wx.EXPAND, 6)
        self.codex_help = self._label(sizer, _("Logowanie obsługuje oficjalny program Codex. Zostaw ścieżkę pustą, jeśli jest zainstalowany. Instrukcja: https://developers.openai.com/codex/cli. Tłumaczenie przez konto ChatGPT jest eksperymentalne."))
        login_buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.login_button = wx.Button(self, label=_("&Log in to ChatGPT"))
        self.cancel_login_button = wx.Button(self, label=_("Cancel lo&gin"))
        login_buttons.Add(self.login_button, 0, wx.ALL, 6)
        login_buttons.Add(self.cancel_login_button, 0, wx.ALL, 6)
        sizer.Add(login_buttons, 0, wx.EXPAND)
        account_buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.account_button = wx.Button(self, label=_("Chec&k account"))
        self.logout_button = wx.Button(self, label=_("Log &out"))
        account_buttons.Add(self.account_button, 0, wx.ALL, 6)
        account_buttons.Add(self.logout_button, 0, wx.ALL, 6)
        sizer.Add(account_buttons, 0, wx.EXPAND)
        self._label(sizer, _("Logowanie i wylogowanie działają od razu. Zapisz zachowuje ustawienia; Używaj tego silnika dodatkowo wybiera OpenAI do tłumaczenia. Anuluj nie cofa logowania."))
        self._label(sizer, _("S&tatus:"))
        self.status = wx.TextCtrl(self, value=_("Gotowe."),
                                  style=wx.TE_READONLY | wx.TE_MULTILINE)
        self.status.SetName(_("OpenAI status"))
        sizer.Add(self.status, 1, wx.ALL | wx.EXPAND, 6)
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.use_button = wx.Button(self, label=_("&Używaj tego silnika"))
        self.save_button = wx.Button(self, wx.ID_OK, label=_("&Save"))
        self.cancel_button = wx.Button(self, wx.ID_CANCEL, label=_("&Cancel"))
        buttons.Add(self.use_button, 0, wx.ALL, 6)
        buttons.Add(self.save_button, 0, wx.ALL, 6)
        buttons.Add(self.cancel_button, 0, wx.ALL, 6)
        sizer.Add(buttons, 0, wx.ALIGN_RIGHT)
        self.SetSizerAndFit(sizer)
        self.SetMinSize((650, 580))
        self.SetEscapeId(wx.ID_CANCEL)
        self.CentreOnParent()
        self.auth_choice.Bind(wx.EVT_CHOICE, self.on_auth_choice)
        self.refresh_button.Bind(wx.EVT_BUTTON, self.on_refresh_models)
        self.login_button.Bind(wx.EVT_BUTTON, self.on_login)
        self.cancel_login_button.Bind(wx.EVT_BUTTON, self.on_cancel_login)
        self.account_button.Bind(wx.EVT_BUTTON, self.on_account)
        self.logout_button.Bind(wx.EVT_BUTTON, self.on_logout)
        self.save_button.Bind(wx.EVT_BUTTON, self.on_save)
        self.use_button.Bind(wx.EVT_BUTTON, self.on_use_provider)
        self.cancel_button.Bind(wx.EVT_BUTTON, self.on_cancel)
        self.Bind(wx.EVT_CLOSE, self.on_cancel)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key)
        self.Bind(wx.EVT_WINDOW_DESTROY, self.on_destroy)
        self._show_model()
        self._update_controls()
        self._previous_translation = settings._enableTranslation
        settings._enableTranslation = False
        self.auth_choice.SetFocus()
        self._queue_account_check()

    def _label(self, sizer: wx.Sizer, text: str) -> wx.StaticText:
        label = wx.StaticText(self, label=text)
        label.Wrap(620)
        sizer.Add(label, 0, wx.ALL | wx.EXPAND, 6)
        return label

    def _show_model(self) -> None:
        value = self._models[self._mode]
        self.model_combo.SetItems(list(dict.fromkeys(self._choices[self._mode] + [value])))
        self.model_combo.SetStringSelection(value)

    def _update_controls(self) -> None:
        oauth = self._mode == "chatgpt"
        self.login_button.Show(oauth and self._signed_in is not True)
        self.logout_button.Show(oauth and self._signed_in is True)
        self.account_button.Show(oauth)
        self.cancel_login_button.Show(oauth and self._login is not None)
        self.login_button.Enable(not self._busy and oauth and self._signed_in is not True)
        self.logout_button.Enable(not self._busy and oauth and self._signed_in is True)
        self.account_button.Enable(not self._busy and oauth)
        for widget in (self.path_label, self.codex_path, self.codex_help):
            widget.Show(oauth)
        self.cancel_login_button.Enable(self._login is not None and not self._login.cancelled.is_set())
        for widget in (self.auth_choice, self.codex_path, self.refresh_button, self.save_button, self.use_button, self.model_combo):
            widget.Enable(not self._busy)
        self.Layout()

    def on_auth_choice(self, event: wx.CommandEvent | None) -> None:
        """Przełącza metodę logowania i jej osobny wybór modelu."""
        if self._closed or self._busy:
            return
        self._models[self._mode] = self.model_combo.GetStringSelection() or "auto"
        self._mode = "chatgpt" if self.auth_choice.GetSelection() == 1 else "api_key"
        self._show_model()
        self._update_controls()
        self._queue_account_check()

    def _queue_account_check(self) -> None:
        if self._mode == "chatgpt" and self._signed_in is None:
            wx.CallAfter(self._automatic_account_check, self._operation)

    def _automatic_account_check(self, operation: int) -> None:
        if not self._closed and operation == self._operation and self._mode == "chatgpt":
            self._request_account(announce=False)

    def _set_status(self, text: str, announce: bool = True) -> None:
        # A focusable read-only field exposes results to NVDA without sending
        # speech through the live-translation hook (paused for this dialog).
        self.status.ChangeValue(text)
        if not announce:
            return
        self.status.SetFocus()
        # SetFocus alone may not announce a completion if Status already has
        # focus. Translation stays paused, so ui.message cannot trigger a request.
        ui.message(text)

    def _run(
        self, work: Callable[[], Any], success: Callable[[Any], None],
        progress: str, failure: str, finished: Callable[[], None] | None = None,
        *, announce: bool = True,
    ) -> None:
        """Uruchamia pracę w tle, a kontrolki zmienia przez kolejkę wx."""
        if self._closed or self._busy:
            return
        self._busy = True
        self._operation += 1
        operation = self._operation
        self._update_controls()
        self._set_status(progress, announce=announce)

        def deliver(ok, result):
            if self._closed or operation != self._operation:
                return
            self._busy = False
            if finished is not None:
                finished()
            self._update_controls()
            if ok:
                success(result)
            else:
                # Never expose raw exceptions: they may include keys/OAuth URLs.
                self._set_status(failure, announce=announce)

        def worker():
            try:
                result = work()
            except Exception:
                wx.CallAfter(deliver, False, None)
            else:
                wx.CallAfter(deliver, True, result)

        threading.Thread(target=worker, daemon=True).start()

    def _selected_api_key(self) -> str:
        entries = self.frame.gestor_apis.get_apis("openai")
        index = self.api_index
        if type(index) is not int or not isinstance(entries, list) or not 0 <= index < len(entries):
            return ""
        entry = entries[index]
        key = entry.get("key") if isinstance(entry, dict) else None
        return key.strip() if isinstance(key, str) else ""

    def on_refresh_models(self, event: wx.CommandEvent | None) -> None:
        """Pobiera aktualny katalog wybranej metody logowania."""
        if self._closed or self._busy:
            return
        mode = self._mode
        api_key = self._selected_api_key() if mode == "api_key" else ""
        if mode == "api_key" and not api_key:
            self._set_status(_("Add an OpenAI API key in Options and select it as the default before refreshing API models."))
            return
        codex_path = self.codex_path.GetValue().strip()
        codex_home = self._codex_home
        list_models = self.frame.gestor_translate.list_openai_models

        def work():
            models = list_models(api_key, auth_mode=mode, codex_home=codex_home, codex_path=codex_path)
            if not isinstance(models, list) or any(not isinstance(model, str) for model in models):
                raise ValueError("Invalid model list")
            return sorted({model for model in models if model})

        def success(models):
            self._models[mode] = self.model_combo.GetStringSelection() or "auto"
            self._choices[mode] = ["auto"] + models
            if mode == "chatgpt":
                self._signed_in = True
                self._update_controls()
            self._show_model()
            self._set_status(_("Modele odświeżone. Wybierz model z listy.") if models else _("Usługa nie zwróciła modeli. Spróbuj odświeżyć listę później."))

        failure = (_("Could not refresh API models. Check the selected API key, network connection and account access.")
                   if mode == "api_key" else
                   _("Could not refresh ChatGPT models. Check the Codex executable path, log in and try again. Installation: https://developers.openai.com/codex/cli"))
        self._run(work, success, _("Refreshing models..."), failure)

    def _account_status(self, account: dict, *, announce: bool = True) -> None:
        self._signed_in = isinstance(account, dict) and account.get("type") == "chatgpt"
        self._update_controls()
        if self._signed_in:
            self._set_status(_("Signed in to ChatGPT for this NVDA profile."), announce=announce)
        else:
            self._choices["chatgpt"] = ["auto"]
            self._models["chatgpt"] = "auto"
            self._show_model()
            self._set_status(_("Not signed in to ChatGPT for this NVDA profile. Use Log in to continue."), announce=announce)

    @staticmethod
    def _read_account_models(
        client: CodexClient, account: dict, *, refresh: bool = False,
    ) -> tuple[dict, list[str] | None]:
        if not isinstance(account, dict) or account.get("type") != "chatgpt":
            return account, []
        try:
            models = client.list_models() if refresh else client.cached_models()
            if not isinstance(models, list) or any(not isinstance(model, str) or not model for model in models):
                raise ValueError("Niepoprawna lista modeli")
            return account, list(dict.fromkeys(models))
        except Exception:  # noqa: BLE001 - awaria dostawcy nie może zamknąć okna.
            # Awaria katalogu nie oznacza wylogowania z konta.
            return account, None

    def _apply_account_models(self, result: tuple, *, announce: bool = True) -> None:
        account, models = result
        if models is not None:
            self._choices["chatgpt"] = ["auto"] + models
            self._show_model()
        self._account_status(account, announce=announce)
        if self._signed_in and models is None:
            self._set_status(_("Konto ChatGPT jest zalogowane. Nie udało się pobrać modeli; możesz ponowić odświeżanie."), announce=announce)

    def on_account(self, event: wx.CommandEvent | None) -> None:
        """Sprawdza konto i przywraca jego zapamiętane modele."""
        self._request_account()

    def _request_account(self, *, announce: bool = True) -> None:
        if self._closed or self._busy or self._mode != "chatgpt":
            return
        home, path = self._codex_home, self.codex_path.GetValue().strip()
        def work():
            client = _get_client(home, path)
            return self._read_account_models(client, client.account())

        self._run(work, lambda result: self._apply_account_models(result, announce=announce),
                  _("Checking ChatGPT account..."),
                  _("Could not check the account. Install the official native Codex executable or correct its path. Installation: https://developers.openai.com/codex/cli"), announce=announce)

    def on_login(self, event: wx.CommandEvent | None) -> None:
        """Rozpoczyna jawne logowanie i pobiera modele po jego zakończeniu."""
        if self._closed or self._busy or self._mode != "chatgpt":
            return
        home, path = self._codex_home, self.codex_path.GetValue().strip()
        attempt = self._login = _LoginAttempt()

        def work():
            try:
                client = _get_client(home, path)
                if attempt.cancelled.is_set():
                    return None
                result = client.start_login()
                login_id = result.get("loginId") if isinstance(result, dict) else None
                if not isinstance(login_id, str) or not login_id:
                    raise ValueError("Invalid sign-in response")
                attempt.attach(client, login_id)
                if attempt.cancelled.is_set():
                    return None
                url = _validated_auth_url(result.get("authUrl"))
                if attempt.cancelled.is_set():
                    return None
                if not webbrowser.open(url, new=2):
                    raise RuntimeError("Could not open sign-in browser")
                if attempt.cancelled.is_set():
                    return None
                if not client.wait_login(login_id, timeout=180):
                    if attempt.cancelled.is_set():
                        return None
                    raise RuntimeError("Sign-in did not complete")
                if attempt.cancelled.is_set():
                    return None
                account = client.account()
                if not isinstance(account, dict) or account.get("type") != "chatgpt":
                    raise RuntimeError("ChatGPT account not confirmed")
                attempt.complete()
                return self._read_account_models(client, account, refresh=True)
            finally:
                attempt.cancel_if_ready()

        def finished():
            self._login = None

        def success(result):
            if result is None:
                self._set_status(_("Sign-in cancellation requested. If you completed sign-in in the browser, use Check account or Log out."))
            else:
                settings = self.frame.gestor_settings
                settings.openai_auth_mode = "chatgpt"
                settings.openai_codex_path = path
                settings.guardaConfiguracion()
                self._apply_account_models(result)

        self._run(work, success,
                  _("Opening sign-in in your browser. Complete sign-in there; Cancel login stops waiting."),
                  _("Sign-in did not complete. Check the network and native Codex executable path, then retry or check the account. Installation: https://developers.openai.com/codex/cli"),
                  finished=finished)

    def on_cancel_login(self, event: wx.CommandEvent | None) -> None:
        """Przerywa oczekiwanie na logowanie bez zamykania ustawień."""
        if self._closed or self._login is None:
            return
        self._login.request_cancel()
        self._update_controls()
        self._set_status(_("Requesting sign-in cancellation. You can close this dialog while waiting."))

    def on_logout(self, event: wx.CommandEvent | None) -> None:
        """Wylogowuje konto dodatku i usuwa jego zapamiętane modele."""
        if self._closed or self._busy or self._mode != "chatgpt":
            return
        home, path = self._codex_home, self.codex_path.GetValue().strip()

        def work():
            client = _get_client(home, path)
            client.logout()
            if client.account():
                raise RuntimeError("Sign-out not confirmed")

        def success(result):
            self._account_status({})
            self.frame.gestor_settings.openai_model_oauth = "auto"
            self.frame.gestor_settings.guardaConfiguracion()
            self._set_status(_("Signed out of ChatGPT for this NVDA profile."))

        self._run(work, success,
                  _("Signing out of ChatGPT..."),
                  _("Could not confirm sign-out. Check the Codex executable path and use Check account before retrying."))

    def on_save(self, event: wx.CommandEvent | None) -> None:
        """Zapisuje wybór konta i modelu bez zmiany silnika."""
        if self._closed or self._busy:
            return
        self._models[self._mode] = self.model_combo.GetStringSelection() or "auto"
        settings = self.frame.gestor_settings
        settings.openai_auth_mode = self._mode
        settings.openai_model_api = self._models["api_key"]
        settings.openai_model_oauth = self._models["chatgpt"]
        settings.openai_codex_path = self.codex_path.GetValue().strip()
        settings.guardaConfiguracion()
        self._finish(wx.ID_OK)

    def on_use_provider(self, event: wx.CommandEvent | None) -> None:
        """Wybiera OpenAI jako silnik bez wymagania klucza dla ChatGPT."""
        if self._closed or self._busy:
            return
        self.use_selected_provider = True
        self.frame.gestor_settings.choiceOnline = 9
        self.on_save(event)

    def _cleanup(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._operation += 1
        self.frame.gestor_settings._enableTranslation = self._previous_translation
        if self._login is not None:
            self._login.request_cancel()

    def _finish(self, result: int) -> None:
        self._cleanup()
        self.EndModal(result)

    def on_cancel(self, event: wx.CommandEvent | None) -> None:
        """Zamyka okno i przywraca poprzedni stan tłumaczenia w locie."""
        if not self._closed:
            self._finish(wx.ID_CANCEL)

    def on_key(self, event: wx.KeyEvent) -> None:
        """Obsługuje zamknięcie okna klawiszem Escape."""
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.on_cancel(event)
        else:
            event.Skip()

    def on_destroy(self, event: wx.WindowDestroyEvent) -> None:
        """Sprząta pracę okna również przy zniszczeniu przez rodzica."""
        if event.GetEventObject() is self:
            self._cleanup()
        event.Skip()
