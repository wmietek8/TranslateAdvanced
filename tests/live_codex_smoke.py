"""Opt-in live OAuth translation probe using ACCESS-ONLY copied test credentials.
Never imports a refresh token and never changes the user's Codex/NVDA config.
This is a test harness, not a product sign-in path. Explicitly provide --auth-file.
The addon itself signs in via its own UI/official Codex account flow.
"""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys
import tempfile
import time
import types
from nvda_harness import APP


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--auth-file',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--long',action='store_true')
    parser.add_argument('--model', default='auto')
    parser.add_argument('--probe-events',action='store_true',help='Record stream event structure without credentials or input text.')
    parser.add_argument('--probe-response',action='store_true',help='Record safe response structure on unexpected content types; do not use for pass/fail.')
    args=parser.parse_args()
    auth_path=Path(args.auth_file)
    raw=auth_path.read_bytes();before=hashlib.sha256(raw).digest();source=json.loads(raw)
    if source.get('auth_mode') != 'chatgpt':
        raise RuntimeError('An existing ChatGPT sign-in is required for this opt-in test.')
    tokens=source['tokens']
    access_only={'auth_mode':'chatgpt','OPENAI_API_KEY':None,'last_refresh':source.get('last_refresh'),'tokens':{field:tokens[field] for field in ('access_token','id_token','account_id')}}
    access_only['tokens']['refresh_token']=''
    del source,tokens,raw
    package=types.ModuleType('ta_live_codex');package.__path__=[str(APP/'utils')];sys.modules[package.__name__]=package
    codex=importlib.import_module('ta_live_codex.utils_codex')
    report={'refresh_token_copied':False,'live_nvda_modified':False,'cases':[],'rpc_methods':[]}
    actual_reader=codex.responses._read_sse
    def traced_reader(*values,**kwargs):
        started=time.monotonic()
        try:return actual_reader(*values,**kwargs)
        except Exception as error:
            report['read_failure']={'type':type(error).__name__,'seconds':round(time.monotonic()-started,3)}
            raise
    codex.responses._read_sse=traced_reader
    if args.probe_events:
        actual_event=codex.responses._event_result
        def traced_event(data, *args, **kwargs):
            try:
                event=json.loads(data)
                info={'type':event.get('type'),'keys':list(event)}
                if isinstance(event.get('item'),dict):
                    item=event['item'];info['item']={'type':item.get('type'),'status':item.get('status'),'role':item.get('role'),'content':[{'type':v.get('type'),'text_len':len(v.get('text',''))} for v in item.get('content',[]) if isinstance(v,dict)]}
                if isinstance(event.get('response'),dict):
                    response=event['response'];info['response']={'keys':list(response),'status':response.get('status'),'output':[{'type':v.get('type'),'status':v.get('status'),'role':v.get('role'),'content_types':[x.get('type') for x in v.get('content',[]) if isinstance(x,dict)]} for v in response.get('output',[]) if isinstance(v,dict)]}
                if isinstance(event.get('delta'),str):info['delta_len']=len(event['delta'])
                if isinstance(event.get('text'),str):info['text_len']=len(event['text'])
                report.setdefault('events',[]).append(info)
            except ValueError:pass
            return actual_event(data, *args, **kwargs)
        codex.responses._event_result=traced_event
    if args.probe_response:
        base_connection=codex.responses.HTTPSConnection
        class ProbeConnection(base_connection):
            def getresponse(self):
                response=super().getresponse()
                info={'http_status':response.status,'content_type':response.getheader('Content-Type','')}
                if response.status==200 and 'event-stream' not in info['content_type']:
                    data=response.read(2*1024*1024)
                    try:
                        value=json.loads(data)
                        info['json_keys']=list(value) if isinstance(value,dict) else type(value).__name__
                        if isinstance(value,dict):
                            info['status']=value.get('status')
                            info['output_types']=[item.get('type') for item in value.get('output',[]) if isinstance(item,dict)]
                    except ValueError:
                        info['starts_with_sse']=data.startswith((b'data:',b'event:'))
                        info['starts_with_html']=data.lstrip().lower().startswith((b'<!doctype html',b'<html'))
                report.setdefault('http_metadata',[]).append(info)
                return response
        codex.responses.HTTPSConnection=ProbeConnection
    try:
        with tempfile.TemporaryDirectory(prefix='translateadvanced-oauth-test-') as temp:
            home=Path(temp)/'managed';client=codex.CodexClient(str(home),timeout=60)
            try:
                client._prepare_home()
                (home/'auth.json').write_text(json.dumps(access_only),encoding='utf-8')
                del access_only
                actual_rpc=client._rpc
                def tracked(method,params=None,**kwargs):
                    if method=='account/read' and (params or {}).get('refreshToken'):
                        raise AssertionError('A live access-only test must not refresh or rotate credentials.')
                    assert method not in ('thread/start','turn/start','command/exec')
                    report['rpc_methods'].append(method)
                    return actual_rpc(method,params,**kwargs)
                client._rpc=tracked
                report['account_type']=client.account().get('type')
                assert report['account_type']=='chatgpt'
                models=client.list_models();report['models']=models
                assert models
                report['auto_model']=codex.responses.select_model('auto',models)
                samples=[('Siema, jak się czujesz?',args.model),('Hello, how are you?',args.model)]
                if args.model == 'auto' and 'gpt-6-astra' in models:
                    samples.extend([('Zapraszam do gry!','gpt-6-astra'),('Come join the game!','gpt-6-astra')])
                if args.long:samples=[(('To jest długi tekst testowy. Zawiera wiele podobnych zdań.\n')*90,'auto')]
                for text,model in samples:
                    started=time.monotonic()
                    result=client.translate(text,'pl',alternate_language='en',model=model)
                    assert isinstance(result,str) and result.strip() and result!=text
                    report['cases'].append({'source_chars':len(text),'model':model,'translation':result if not args.long else result[-150:],'translation_chars':len(result),'seconds':round(time.monotonic()-started,3),'passed':True})
            finally:
                client.close()
    finally:
        report['personal_auth_unchanged']=before==hashlib.sha256(auth_path.read_bytes()).digest()
        output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        assert report['personal_auth_unchanged']
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
