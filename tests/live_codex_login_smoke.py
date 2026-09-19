"""Opt-in start/cancel probe for the official login flow; no browser or tokens.
Never touches a user's existing Codex or NVDA configuration.
"""
import argparse
import importlib
import json
from pathlib import Path
import sys
import tempfile
import types
from urllib.parse import urlsplit

from nvda_harness import APP


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    package = types.ModuleType('ta_login_probe')
    package.__path__ = [str(APP / 'utils')]
    sys.modules[package.__name__] = package
    codex = importlib.import_module(package.__name__ + '.utils_codex')
    report = {'browser_opened': False, 'browser_completion_tested': False,
              'existing_accounts_modified': False}
    with tempfile.TemporaryDirectory(prefix='ta-login-probe-') as temporary:
        client = codex.CodexClient(str(Path(temporary) / 'managed'), timeout=30)
        process = None
        try:
            assert not client.account(), 'Fresh isolated home was already signed in.'
            process = client._process
            login = client.start_login()
            parsed = urlsplit(login['authUrl'])
            assert parsed.scheme == 'https' and parsed.hostname == 'auth.openai.com'
            report['official_login_started'] = True
            client.cancel_login(login['loginId'])
            assert client.wait_login(login['loginId'], timeout=5) is False
            assert not client.account()
            report['cancellation_confirmed'] = True
            del login, parsed
        finally:
            client.close()
            report['child_process_reaped'] = process is not None and process.poll() is not None
            target = Path(args.output)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, indent=2), encoding='utf-8')
        assert report['child_process_reaped']
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
