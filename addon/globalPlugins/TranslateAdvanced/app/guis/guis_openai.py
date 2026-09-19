# -*- coding: utf-8 -*-
# This file is covered by the GNU General Public License.
"""Accessible OpenAI preferences; opening or reading this dialog does no I/O."""

import os
import threading
from urllib.parse import urlsplit
import webbrowser

import addonHandler
import globalVars
import ui
import wx

addonHandler.initTranslation()


def _validated_auth_url(value):
    """Do not let an executable's output become an arbitrary browser target."""
    if not isinstance(value, str) or "\\" in value or any(ord(char) <= 32 or ord(char) == 127 for char in value):
        raise ValueError("Untrusted sign-in address")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.netloc.lower() not in ("auth.openai.com", "auth.openai.com:443"):
        raise ValueError("Untrusted sign-in address")
    return value


def _get_client(codex_home, codex_path):
    # Loading this module or reading the dialog must never start a CLI/session.
    from ..utils.utils_codex import get_client
    return get_client(codex_home, codex_path=codex_path)


class _LoginAttempt:
    """Cancellation also covers a login ID that arrives after the dialog closes."""

    def __init__(self):
        self.cancelled = threading.Event()
        self._lock = threading.Lock()
        self._client = None
        self._login_id = None
        self._cancel_sent = False

    def attach(self, client, login_id):
        with self._lock:
            self._client, self._login_id = client, login_id
        if self.cancelled.is_set():
            self.cancel_if_ready()

    def complete(self):
        with self._lock:
            self._login_id = None

    def request_cancel(self):
        self.cancelled.set()
        threading.Thread(target=self.cancel_if_ready, daemon=True).start()

    def cancel_if_ready(self):
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
    """Keep preferences local until Save; account actions are independent."""

    def __init__(self, parent, frame, api_index=None):
        super().__init__(parent, title=_("OpenAI (API / ChatGPT OAuth)"),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.frame = frame
        settings = frame.gestor_settings
        self.api_index = settings.api_openai if api_index is None else api_index
        self._closed = False
        self._busy = False
        self._operation = 0
        self._login = None
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
        self._label(sizer, _("API keys are managed in the existing API manager in Options. ChatGPT sign-in does not require an API key. Nothing is fetched until you request it."))
        self._label(sizer, _("ChatGPT OAuth translation uses an experimental, undocumented ChatGPT endpoint. It may stop working after service changes. The API key option uses the official OpenAI API."))
        self._label(sizer, _("&Model for the selected authentication method:"))
        self.model_combo = wx.ComboBox(self, style=wx.CB_DROPDOWN)
        self.model_combo.SetName(_("Model for the selected authentication method"))
        self.model_combo.SetHelpText(_("Refresh to list available models, or type an exact model ID. 'auto' selects an available model automatically. API and ChatGPT model choices are saved separately."))
        sizer.Add(self.model_combo, 0, wx.ALL | wx.EXPAND, 6)
        self.refresh_button = wx.Button(self, label=_("&Refresh models"))
        sizer.Add(self.refresh_button, 0, wx.ALL, 6)
        self._label(sizer, _("Codex &executable path (optional):"))
        self.codex_path = wx.TextCtrl(self, value=settings.openai_codex_path or "")
        self.codex_path.SetName(_("Codex executable path (optional)"))
        self.codex_path.SetHelpText(_("Enter the full path to an installed codex.exe, or leave blank to find it on PATH. Do not enter an API key or token."))
        sizer.Add(self.codex_path, 0, wx.ALL | wx.EXPAND, 6)
        self._label(sizer, _("ChatGPT requires the official Codex CLI (codex.exe). Install it yourself using https://developers.openai.com/codex/cli, then enter its executable path above if it is not on PATH. No executable is downloaded by this dialog."))
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
        self._label(sizer, _("Save applies these preferences immediately, independently of Options. Cancel discards preference edits. Log in, Cancel login and Log out are separate account actions and are not undone by Cancel. Live translation is paused while this dialog is open."))
        self._label(sizer, _("S&tatus:"))
        self.status = wx.TextCtrl(self, value=_("Ready. No account or model request has been made."),
                                  style=wx.TE_READONLY | wx.TE_MULTILINE)
        self.status.SetName(_("OpenAI status"))
        sizer.Add(self.status, 1, wx.ALL | wx.EXPAND, 6)
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.save_button = wx.Button(self, wx.ID_OK, label=_("&Save"))
        self.cancel_button = wx.Button(self, wx.ID_CANCEL, label=_("&Cancel"))
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
        self.cancel_button.Bind(wx.EVT_BUTTON, self.on_cancel)
        self.Bind(wx.EVT_CLOSE, self.on_cancel)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key)
        self.Bind(wx.EVT_WINDOW_DESTROY, self.on_destroy)
        self._show_model()
        self._update_controls()
        self._previous_translation = settings._enableTranslation
        settings._enableTranslation = False
        self.auth_choice.SetFocus()

    def _label(self, sizer, text):
        label = wx.StaticText(self, label=text)
        label.Wrap(620)
        sizer.Add(label, 0, wx.ALL | wx.EXPAND, 6)

    def _show_model(self):
        value = self._models[self._mode]
        self.model_combo.SetItems(list(dict.fromkeys(self._choices[self._mode] + [value])))
        self.model_combo.SetValue(value)

    def _update_controls(self):
        for widget in (self.login_button, self.account_button, self.logout_button):
            widget.Enable(not self._busy and self._mode == "chatgpt")
        self.cancel_login_button.Enable(self._login is not None and not self._login.cancelled.is_set())
        for widget in (self.auth_choice, self.codex_path, self.refresh_button, self.save_button):
            widget.Enable(not self._busy)

    def on_auth_choice(self, event):
        if self._closed or self._busy:
            return
        self._models[self._mode] = self.model_combo.GetValue().strip() or "auto"
        self._mode = "chatgpt" if self.auth_choice.GetSelection() == 1 else "api_key"
        self._show_model()
        self._update_controls()

    def _set_status(self, text):
        # A focusable read-only field exposes results to NVDA without sending
        # speech through the live-translation hook (paused for this dialog).
        self.status.ChangeValue(text)
        self.status.SetFocus()
        # SetFocus alone may not announce a completion if Status already has
        # focus. Translation stays paused, so ui.message cannot trigger a request.
        ui.message(text)

    def _run(self, work, success, progress, failure, finished=None):
        """Only CallAfter's delivery callback may access wx controls."""
        if self._closed or self._busy:
            return
        self._busy = True
        self._operation += 1
        operation = self._operation
        self._update_controls()
        self._set_status(progress)

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
                self._set_status(failure)

        def worker():
            try:
                result = work()
            except Exception:
                wx.CallAfter(deliver, False, None)
            else:
                wx.CallAfter(deliver, True, result)

        threading.Thread(target=worker, daemon=True).start()

    def _selected_api_key(self):
        entries = self.frame.gestor_apis.get_apis("openai")
        index = self.api_index
        if type(index) is not int or not isinstance(entries, list) or not 0 <= index < len(entries):
            return ""
        entry = entries[index]
        key = entry.get("key") if isinstance(entry, dict) else None
        return key.strip() if isinstance(key, str) else ""

    def on_refresh_models(self, event):
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
            return sorted(set(model for model in models if model))

        def success(models):
            self._models[mode] = self.model_combo.GetValue().strip() or "auto"
            self._choices[mode] = ["auto"] + models
            self._show_model()
            self._set_status(_("Models refreshed. Select a model or type its exact ID. Availability depends on your account.") if models else _("No models were returned. Keep 'auto' or enter an available model ID."))

        failure = (_("Could not refresh API models. Check the selected API key, network connection and account access.")
                   if mode == "api_key" else
                   _("Could not refresh ChatGPT models. Check the Codex executable path, log in and try again. Installation: https://developers.openai.com/codex/cli"))
        self._run(work, success, _("Refreshing models..."), failure)

    def _account_status(self, account):
        if isinstance(account, dict) and account.get("type") == "chatgpt":
            self._set_status(_("Signed in to ChatGPT for this NVDA profile."))
        else:
            self._set_status(_("Not signed in to ChatGPT for this NVDA profile. Use Log in to continue."))

    def on_account(self, event):
        if self._closed or self._busy or self._mode != "chatgpt":
            return
        home, path = self._codex_home, self.codex_path.GetValue().strip()
        self._run(lambda: _get_client(home, path).account(), self._account_status,
                  _("Checking ChatGPT account..."),
                  _("Could not check the account. Install the official native Codex executable or correct its path. Installation: https://developers.openai.com/codex/cli"))

    def on_login(self, event):
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
                return account
            finally:
                attempt.cancel_if_ready()

        def finished():
            self._login = None

        def success(account):
            if account is None:
                self._set_status(_("Sign-in cancellation requested. If you completed sign-in in the browser, use Check account or Log out."))
            else:
                self._account_status(account)

        self._run(work, success,
                  _("Opening sign-in in your browser. Complete sign-in there; Cancel login stops waiting."),
                  _("Sign-in did not complete. Check the network and native Codex executable path, then retry or check the account. Installation: https://developers.openai.com/codex/cli"),
                  finished=finished)

    def on_cancel_login(self, event):
        if self._closed or self._login is None:
            return
        self._login.request_cancel()
        self._update_controls()
        self._set_status(_("Requesting sign-in cancellation. You can close this dialog while waiting."))

    def on_logout(self, event):
        if self._closed or self._busy or self._mode != "chatgpt":
            return
        home, path = self._codex_home, self.codex_path.GetValue().strip()

        def work():
            client = _get_client(home, path)
            client.logout()
            if client.account():
                raise RuntimeError("Sign-out not confirmed")

        self._run(work, lambda result: self._set_status(_("Signed out of ChatGPT for this NVDA profile.")),
                  _("Signing out of ChatGPT..."),
                  _("Could not confirm sign-out. Check the Codex executable path and use Check account before retrying."))

    def on_save(self, event):
        if self._closed or self._busy:
            return
        self._models[self._mode] = self.model_combo.GetValue().strip() or "auto"
        settings = self.frame.gestor_settings
        settings.openai_auth_mode = self._mode
        settings.openai_model_api = self._models["api_key"]
        settings.openai_model_oauth = self._models["chatgpt"]
        settings.openai_codex_path = self.codex_path.GetValue().strip()
        settings.guardaConfiguracion()
        self._finish(wx.ID_OK)

    def _cleanup(self):
        if self._closed:
            return
        self._closed = True
        self._operation += 1
        self.frame.gestor_settings._enableTranslation = self._previous_translation
        if self._login is not None:
            self._login.request_cancel()

    def _finish(self, result):
        self._cleanup()
        self.EndModal(result)

    def on_cancel(self, event):
        if not self._closed:
            self._finish(wx.ID_CANCEL)

    def on_key(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.on_cancel(event)
        else:
            event.Skip()

    def on_destroy(self, event):
        if event.GetEventObject() is self:
            self._cleanup()
        event.Skip()
