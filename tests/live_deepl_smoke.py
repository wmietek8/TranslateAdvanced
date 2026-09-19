"""Opt-in live DeepL test; never run by unittest discovery.
Run with: python tests/live_deepl_smoke.py --api-file C:/Users/you/apis.json --output PATH
Only the specified sample text is sent. No credentials are printed or written.
"""
import argparse
from collections import deque
import io
import json
from pathlib import Path
import time
import types
import urllib.parse
import urllib.request
from unittest.mock import patch
from nvda_harness import manager_class


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--api-file',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    entries=json.loads(Path(args.api_file).read_text('utf-8'))['deepL_pro']
    key=entries[0]['key']
    cls=manager_class().GestorTranslate; manager=cls.__new__(cls)
    settings=types.SimpleNamespace(choiceOnline=5,api_deepl_pro=0,_enableTranslation=True,chkAltLang=True,
        choiceLangDestino_google_def='pl',choiceLangDestino_google_alt='en',choiceLangDestino_deepl='pl',
        historialOrigen=deque(),historialDestino=deque(),_lastTranslatedText=None)
    manager.frame=types.SimpleNamespace(gestor_settings=settings,gestor_apis=types.SimpleNamespace(get_api=lambda *args: {'key':key}))
    original=urllib.request.urlopen
    calls=[]
    def traced(request,**kwargs):
        payload=json.loads(request.data)
        with original(request,**kwargs) as response:
            data=response.read()
        actual=json.loads(data)
        calls.append({'host':urllib.parse.urlparse(request.full_url).hostname,'target':payload['target_lang'],
            'detected':actual['translations'][0].get('detected_source_language')})
        return io.BytesIO(data)
    samples=[('Siema, jak się czujesz?','PL','EN'),('Hello, how are you?','EN','PL'),
             ('No dobra, a co teraz?','PL','EN')]
    report=[]
    with patch.object(urllib.request,'urlopen',traced):
        for text,expected_detected,expected_target in samples:
            calls.clear(); start=time.monotonic()
            result=manager.translate_various(text)
            assert result.strip() and result != text, 'No translated result'
            assert calls[-1]['target']==expected_target, calls
            assert calls[0]['detected']==expected_detected,calls
            assert all(call['host']=='api.deepl.com' for call in calls), calls
            assert settings._enableTranslation and settings.choiceLangDestino_deepl=='pl'
            report.append({'source':text,'translation':result,'seconds':round(time.monotonic()-start,3),'requests':list(calls),'passed':True})
    Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n','utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
