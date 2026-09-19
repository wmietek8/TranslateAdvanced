"""Opt-in hidden native wx controls smoke: no sign-in, no network, no live NVDA writes."""
import builtins
import importlib
import json
from pathlib import Path
import sys
import tempfile
import types
from unittest.mock import patch
import wx
from nvda_harness import APP


def main():
    app=wx.App(False); owner=wx.Frame(None,title='TranslateAdvanced hidden UI test')
    package=types.ModuleType('native_ta_ui');package.__path__=[str(APP)]
    spoken=[];saved=[]
    with tempfile.TemporaryDirectory(prefix='translateadvanced-ui-') as home:
        with patch.dict(sys.modules,{'native_ta_ui':package,'addonHandler':types.SimpleNamespace(initTranslation=lambda:None),'globalVars':types.SimpleNamespace(appArgs=types.SimpleNamespace(configPath=home)),'ui':types.SimpleNamespace(message=spoken.append)}),patch.object(builtins,'_',lambda s:s,create=True):
            module=importlib.import_module('native_ta_ui.guis.guis_openai')
        module.__dict__['_']=lambda s:s
        settings=types.SimpleNamespace(api_openai=None,openai_auth_mode='api_key',openai_model_api='auto',openai_model_oauth='auto',openai_codex_path='',_enableTranslation=True,guardaConfiguracion=lambda:saved.append(True))
        frame=types.SimpleNamespace(gestor_settings=settings,gestor_apis=types.SimpleNamespace(get_api=lambda *a:None))
        module._get_client=lambda *a,**k:(_ for _ in ()).throw(AssertionError('Opening settings must not start account requests'))
        dialog=module.OpenAISettingsDialog(owner,frame)
        # Product uses ShowModal; keep this smoke hidden and record only the end-modal boundary.
        ended=[];dialog.EndModal=lambda code:ended.append(code)
        assert isinstance(dialog.auth_choice,wx.Choice)
        assert isinstance(dialog.model_combo,wx.ComboBox)
        assert isinstance(dialog.status,wx.TextCtrl)
        assert dialog.status.HasFlag(wx.TE_READONLY)
        assert all(control.GetName() for control in (dialog.auth_choice,dialog.model_combo,dialog.codex_path,dialog.status))
        assert not settings._enableTranslation
        assert not dialog.login_button.IsEnabled()
        assert dialog.model_combo.GetItems()==['auto']
        dialog.model_combo.SetValue('gpt-6-astra')
        dialog.auth_choice.SetSelection(1);dialog.on_auth_choice(None)
        assert dialog.login_button.IsEnabled()
        assert dialog.model_combo.GetValue()=='auto'
        dialog.model_combo.SetValue('gpt-5.6-luna')
        dialog.auth_choice.SetSelection(0);dialog.on_auth_choice(None)
        assert dialog.model_combo.GetValue()=='gpt-6-astra'
        dialog.on_save(None)
        assert ended==[wx.ID_OK] and saved==[True]
        assert settings._enableTranslation
        assert settings.openai_model_api=='gpt-6-astra' and settings.openai_model_oauth=='gpt-5.6-luna'
        dialog.Destroy();app.Yield();owner.Destroy()
        print(json.dumps({'wx':wx.version(),'hidden_native_controls':True,'accessible_names':True,'separate_model_preferences':True,'live_translation_restored':True,'save_boundary':True,'network_requests':0,'live_nvda_modified':False},indent=2))


if __name__=='__main__':main()
