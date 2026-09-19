"""Opt-in Windows/wx/HTTPS smoke; does NOT reload or modify live NVDA.
Runs the actual GlobalPlugin class/command, real manager, real wx event loop and
Windows clipboard; speech is recorded at the NVDA boundary, not synthesized.
Backs up every HGLOBAL clipboard format and restores only if nobody copied new
data during the test. Refuses unsupported GDI/owner-display formats up front.
"""
import argparse
import atexit
import hashlib
import tempfile
import builtins
from collections import deque
import ctypes
from ctypes import wintypes
import importlib.util
import json
from pathlib import Path
import sys
import threading
import time
import types
from unittest.mock import patch
import wx
from nvda_harness import manager_class
from test_clipboard_translation import load_class, PLUGIN, APP

U=ctypes.WinDLL('user32',use_last_error=True)
K=ctypes.WinDLL('kernel32',use_last_error=True)
for name, args, result in [
    ('OpenClipboard',[wintypes.HWND],wintypes.BOOL),
    ('CloseClipboard',[],wintypes.BOOL),('EmptyClipboard',[],wintypes.BOOL),
    ('EnumClipboardFormats',[wintypes.UINT],wintypes.UINT),
    ('GetClipboardData',[wintypes.UINT],wintypes.HANDLE),
    ('SetClipboardData',[wintypes.UINT,wintypes.HANDLE],wintypes.HANDLE),
    ('GetClipboardSequenceNumber',[],wintypes.DWORD),
    ('GetClipboardOwner',[],wintypes.HWND)]:
    fn=getattr(U,name); fn.argtypes=args; fn.restype=result
for name,args,result in [('GlobalSize',[wintypes.HANDLE],ctypes.c_size_t),
    ('GlobalLock',[wintypes.HANDLE],ctypes.c_void_p),('GlobalUnlock',[wintypes.HANDLE],wintypes.BOOL),
    ('GlobalAlloc',[wintypes.UINT,ctypes.c_size_t],wintypes.HANDLE),('GlobalFree',[wintypes.HANDLE],wintypes.HANDLE)]:
    fn=getattr(K,name);fn.argtypes=args;fn.restype=result


def backup_clipboard(include_owner=False):
    for attempt in range(40):
        if U.OpenClipboard(None): break
        time.sleep(0.025)
    else: raise RuntimeError('Clipboard busy; no data changed.')
    try:
        data=[];fmt=0
        while True:
            fmt=U.EnumClipboardFormats(fmt)
            if not fmt: break
            if fmt in (2,3,9,14) or 0x80 <= fmt <= 0x8f:
                raise RuntimeError('Unsupported non-memory clipboard format; no data changed.')
            handle=U.GetClipboardData(fmt); size=K.GlobalSize(handle)
            if not handle or not 0<size<=32*1024*1024:
                raise RuntimeError('Cannot safely back up clipboard format; no data changed.')
            pointer=K.GlobalLock(handle)
            if not pointer: raise RuntimeError('Clipboard backup lock failed; no data changed.')
            try: data.append((fmt,ctypes.string_at(pointer,size)))
            finally: K.GlobalUnlock(handle)
        result=(data,U.GetClipboardSequenceNumber())
        return result+(U.GetClipboardOwner(),) if include_owner else result
    finally: U.CloseClipboard()


def restore_clipboard(data, expected, owner):
    handles=[]
    try:
        for fmt,content in data:
            handle=K.GlobalAlloc(0x0002,len(content))
            if not handle: raise RuntimeError('Clipboard restore allocation failed.')
            handles.append([fmt,handle])
            pointer=K.GlobalLock(handle)
            if not pointer: raise RuntimeError('Clipboard restore lock failed.')
            try: ctypes.memmove(pointer,content,len(content))
            finally: K.GlobalUnlock(handle)
        for attempt in range(40):
            if U.OpenClipboard(owner): break
            time.sleep(0.025)
        else: raise RuntimeError('Clipboard busy; saved backup retained.')
        try:
            if U.GetClipboardSequenceNumber()!=expected: return False
            if not U.EmptyClipboard(): raise RuntimeError('Clipboard restore could not clear test data.')
            for row in handles:
                if not U.SetClipboardData(row[0],row[1]): raise RuntimeError('Clipboard format restore failed.')
                row[1]=None
        finally: U.CloseClipboard()
        restored,_=backup_clipboard()
        return sorted(restored)==sorted(data)
    finally:
        for _,handle in handles:
            if handle: K.GlobalFree(handle)


def main():
    import subprocess
    parser=argparse.ArgumentParser();parser.add_argument('--api-file');parser.add_argument('--output',required=True)
    parser.add_argument('--provider',choices=['deepl','openai'],default='deepl')
    parser.add_argument('--auth-file');parser.add_argument('--model',default='auto');parser.add_argument('--long',action='store_true');parser.add_argument('--check-recovery',action='store_true')
    parser.add_argument('--varied',action='store_true')
    parser.add_argument('--verify-lock',action='store_true')
    args=parser.parse_args()
    if args.varied: args.long=True
    key=json.loads(Path(args.api_file).read_text('utf-8'))['deepL_pro'][0]['key'] if args.provider=='deepl' else ''
    codex=None;temporary=None;auth_path=None;auth_digest=None
    app=wx.App(False)
    owner=wx.Frame(None,title="TranslateAdvanced hidden clipboard test")
    native_package=types.ModuleType('ta_native_app');native_package.__path__=[str(APP)]
    sys.modules[native_package.__name__]=native_package
    spec=importlib.util.spec_from_file_location('ta_native_app.managers.managers_clipboard',APP/'managers/managers_clipboard.py')
    clipmodule=importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules,{'addonHandler':types.SimpleNamespace(initTranslation=lambda:None),
        'logHandler':types.SimpleNamespace(log=types.SimpleNamespace(error=lambda *a:None))}),patch.object(builtins,'_',lambda s:s,create=True):
        spec.loader.exec_module(clipmodule)
    clipmodule.__dict__['_']=lambda s:s
    # Substitute NVDA's owner window with a real hidden window in this process.
    clipmodule.ClipboardMonitor._clipboard_owner=staticmethod(lambda:owner.GetHandle())
    clipboard=clipmodule.ClipboardMonitor(None)
    module=manager_class();cls=module.GestorTranslate; manager=cls.__new__(cls)
    settings=types.SimpleNamespace(choiceOnline=5,chkAltLang=True,choiceLangDestino_deepl='pl',
        choiceLangDestino_google_def='pl',choiceLangDestino_google_alt='en',api_deepl_pro=0,
        _enableTranslation=True,chkCache=False,historialOrigen=deque(),historialDestino=deque(),
        _lastTranslatedText=None,IS_WinON=False,is_active_translate=False)
    manager.frame=types.SimpleNamespace(gestor_settings=settings,gestor_apis=types.SimpleNamespace(get_api=lambda *a:{'key':key}))
    if args.provider=='openai':
        # Retain actual production package paths for the adapter's lazy import.
        root_name=module.__name__.split('.managers.')[0]
        for name,path in [(root_name,APP),(root_name+'.utils',APP/'utils')]:
            package=types.ModuleType(name);package.__path__=[str(path)];sys.modules[name]=package
        codex=importlib.import_module(root_name+'.utils.utils_codex')
        temporary=tempfile.TemporaryDirectory(prefix='ta-native-access-only-');atexit.register(temporary.cleanup)
        atexit.register(codex.close_clients)
        module.globalVars.appArgs.configPath=temporary.name
        home=Path(temporary.name)/'TranslateAdvanced'/'codex'
        client=codex.get_client(home);client._prepare_home()
        auth_path=Path(args.auth_file).resolve();auth_digest=hashlib.sha256(auth_path.read_bytes()).digest()
        saved=json.loads(auth_path.read_text('utf-8'));tokens=saved['tokens']
        isolated={'auth_mode':'chatgpt','tokens':{name:tokens[name] for name in ('access_token','id_token','account_id')}}
        isolated['tokens']['refresh_token']=''
        if 'last_refresh' in saved: isolated['last_refresh']=saved['last_refresh']
        (home/'auth.json').write_text(json.dumps(isolated),encoding='utf-8');del isolated,saved,tokens
        rpc=client._rpc
        def guarded(method,params=None,**kwargs):
            assert not (method=='account/read' and (params or {}).get('refreshToken'))
            assert method not in ('account/login/start','account/logout','thread/start','turn/start','command/exec')
            return rpc(method,params,**kwargs)
        client._rpc=guarded
        settings.choiceOnline=9;settings.choiceLangDestino_openai='pl';settings.api_openai=None
        settings.openai_auth_mode='chatgpt';settings.openai_model_oauth=args.model;settings.openai_codex_path=''
        assert client.account()['type']=='chatgpt'
    spoken=[]
    def message(text):
        assert wx.IsMainThread()
        observed=clipboard.get_clipboard_text()
        spoken.append({'text':text,'write_completed_before_speech':owned['text']==text,'immediate_read':None if observed is None else observed==text,'live_translation_suppressed':not settings._enableTranslation})
    namespace={'_':lambda s:s,'Thread':threading.Thread,'Event':threading.Event,'wx':wx,
        'ui':types.SimpleNamespace(message=message),'globalPluginHandler':types.SimpleNamespace(GlobalPlugin=type('Base',(),{'terminate':lambda self:None}))}
    plugin_class=load_class(PLUGIN,'GlobalPlugin',namespace);plugin=plugin_class.__new__(plugin_class)
    plugin.switch=False;plugin.IS_OK=False;plugin._terminating=False;plugin._clipboard_job=None
    plugin.gestor_settings=settings;plugin.gestor_translate=manager;plugin.gestor_portapapeles=clipboard
    report={'provider':args.provider,'model':args.model,'python':sys.version,'wx':wx.version(),'live_nvda_modified':False,'speech_boundary_only':True,'cases':[]}
    original,last_owned=backup_clipboard()
    # Keep a private recovery file until restoration is verified. Never bundle,
    # print, or send these bytes. A failed assertion must not lose the backup.
    import base64
    recovery_dir=Path(tempfile.mkdtemp(prefix='ta-clipboard-recovery-'))
    recovery_file=recovery_dir/'clipboard.json'
    recovery_file.write_text(json.dumps([[fmt,base64.b64encode(data).decode('ascii')] for fmt,data in original]),encoding='utf-8')
    owned={'sequence':last_owned,'text':None,'window':None}
    native_clipboard=wx.Clipboard.Get()
    native_set=native_clipboard.SetData;native_flush=native_clipboard.Flush
    def tracked_set(data):
        value=data.GetText()
        ok=native_set(data)
        if ok:
            owned['sequence']=U.GetClipboardSequenceNumber()
            owned['text']=value
        return ok
    def tracked_flush():
        ok=native_flush()
        if ok:
            owned['sequence']=U.GetClipboardSequenceNumber()
            owned['window']=U.GetClipboardOwner()
        return ok
    # These wrappers observe actual Windows writes while the clipboard is still
    # locked. They never manufacture success or substitute any clipboard data.
    native_clipboard.SetData=tracked_set;native_clipboard.Flush=tracked_flush
    # Observe the real native commit too: wx is now only used for test setup.
    native_backend=clipboard._native()
    win32=native_backend
    win32.user32.GetOpenClipboardWindow.restype=ctypes.c_void_p
    raw_open=win32.user32.OpenClipboard;raw_close=win32.user32.CloseClipboard
    report['native_lock_events']=[]
    def trace_open(window):
        ok=raw_open(window)
        report['native_lock_events'].append(['open',bool(ok),win32.user32.GetOpenClipboardWindow()])
        return ok
    def trace_close():
        ok=raw_close()
        report['native_lock_events'].append(['close',bool(ok),win32.user32.GetOpenClipboardWindow()])
        return ok
    win32.user32.OpenClipboard=trace_open;win32.user32.CloseClipboard=trace_close
    original_backup=win32._backup
    def trace_backup(*args,**kwargs):
        try: return original_backup(*args,**kwargs)
        except Exception as exc:
            report.setdefault('native_backup_errors',[]).append(type(exc).__name__+': '+str(exc))
            raise
    win32._backup=trace_backup
    native_publish=native_backend.user32.SetClipboardData
    report['native_lock_probes']=[]
    def tracked_native_publish(format,handle):
        if args.verify_lock:
            probe=subprocess.run([sys.executable,'-I','-c',
                'import ctypes;u=ctypes.windll.user32;opened=bool(u.OpenClipboard(None));print(int(opened));u.CloseClipboard() if opened else None'],
                capture_output=True,text=True,timeout=10,check=True)
            blocked=probe.stdout.strip()=='0'
            report['native_lock_probes'].append(blocked)
            assert blocked,'Another process acquired the clipboard inside the native transaction.'
        result=native_publish(format,handle)
        if result:
            owned['sequence']=U.GetClipboardSequenceNumber()
            if format==13:
                owned['text']=native_backend._read_text()
                owned['window']=U.GetClipboardOwner()
        return result
    native_backend.user32.SetClipboardData=tracked_native_publish
    try:
        samples=['Siema, jak się czujesz?','Hello, how are you?'] if not args.long else [('To jest długi tekst testowy. Zawiera wiele podobnych zdań.\n'*90),('This is a long test text. It contains many similar sentences.\n'*90)]
        if args.varied:
            samples=[
                '\n\n'.join(f'[M{i:03d}] Gracz numer {i} czeka przy bramie. Zabierz trzy mikstury i dołącz do naszej drużyny przed kolejną rundą.' for i in range(1,41)),
                '\n\n'.join(f'[M{i:03d}] Player number {i} is waiting at the gate. Take three potions and join our team before the next round.' for i in range(1,41)),
            ]
        for text in samples:
            if U.GetClipboardSequenceNumber()!=last_owned: raise RuntimeError('Another application changed clipboard; stopping safely.')
            assert clipboard.set_clipboard_text(text)
            last_owned=owned['sequence'];spoken.clear()
            if args.check_recovery: raise AssertionError('Intentional recovery safety test')
            started=time.monotonic();plugin.script_ClipboardTranslation(None)
            launch_time=time.monotonic()-started
            assert launch_time<0.2, 'Command blocked before starting worker.'
            deadline=time.monotonic()+60
            # wx.Yield alone does not dispatch CallLater timers on MSW. Run the
            # actual GUI event loop (owner stays hidden; no focus change).
            def poll_completion():
                if not settings.is_active_translate or time.monotonic()>=deadline:
                    app.ExitMainLoop()
                else:
                    wx.CallLater(10,poll_completion)
            wx.CallAfter(poll_completion)
            app.MainLoop()
            assert not settings.is_active_translate,'Worker failed to finish.'
            for attempt in range(40):
                result=clipboard.get_clipboard_text()
                if result is not None: break
                time.sleep(0.025)
            if not (spoken and spoken[-1]['text']==result and result!=text):
                report['failure']={'sample':text,'spoken':spoken,'clipboard_still_contains_sample':result==text,'clipboard_unavailable':result is None,'sequence_changed':U.GetClipboardSequenceNumber()!=last_owned}
            assert spoken and spoken[-1]['text']==result and result!=text
            assert all(row['write_completed_before_speech'] and row['immediate_read'] is not False and row['live_translation_suppressed'] for row in spoken)
            assert settings._enableTranslation
            last_owned=U.GetClipboardSequenceNumber()
            if args.long:
                assert len(text)>3000 and len(result)>3000, 'Long result was truncated.'
                assert result.count('\n')==text.count('\n'), 'Line structure was changed.'
            if args.varied:
                markers=[f'[M{i:03d}]' for i in range(1,41)]
                assert all(result.count(marker)==1 for marker in markers), 'A marked paragraph was lost or duplicated.'
                positions=[result.index(marker) for marker in markers]
                assert positions==sorted(positions), 'Paragraph order changed.'
            report['cases'].append({'source':text if not args.long else text[:80], 'source_chars':len(text),'translation':result if not args.long else result[:120], 'translation_chars':len(result), 'command_return_seconds':round(launch_time,4),'total_seconds':round(time.monotonic()-started,3),'clipboard_equals_spoken':True,'passed':True})
    except AssertionError as error:
        if not (args.check_recovery and str(error)=='Intentional recovery safety test'): raise
        report['intentional_failure_test']=True
    finally:
        native_clipboard.SetData=native_set;native_clipboard.Flush=native_flush
        native_backend.user32.SetClipboardData=native_publish
        plugin._cancel_clipboard_translation()
        if codex:
            codex.close_clients();temporary.cleanup()
            report['personal_auth_unchanged']=hashlib.sha256(auth_path.read_bytes()).digest()==auth_digest
        report['last_owned_sequence']=owned['sequence']
        try:
            # A generation observed inside SetClipboardData can precede the
            # final close/rendering update. Refresh it ONLY while the snapshot
            # still belongs to our own window and holds our exact output.
            # A recopy by another application, even identical text, fails this.
            current,sequence,current_owner=backup_clipboard(include_owner=True)
            current_text=next((data.decode('utf-16-le').rstrip('\0') for format,data in current if format==13),None)
            if owned['window'] and current_owner==owned['window'] and current_text==owned['text']:
                owned['sequence']=sequence
                report['rendered_owned_sequence']=sequence
            report['original_clipboard_formats_restored']=restore_clipboard(original,owned['sequence'],owner.GetHandle())
        except Exception as restore_error:
            report['original_clipboard_formats_restored']=False
            report['restore_error']=type(restore_error).__name__+': '+str(restore_error)
        if report['original_clipboard_formats_restored']:
            recovery_file.unlink();recovery_dir.rmdir()
        else:
            report['private_recovery_file']=str(recovery_file)
        target=Path(args.output);target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    assert report['original_clipboard_formats_restored']
    if args.verify_lock: assert report['native_lock_probes'] and all(report['native_lock_probes'])
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
