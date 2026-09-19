"""The scoped NVDA shim must not detach freshly imported stdlib modules."""
from pathlib import Path
import subprocess
import sys


def test_scoped_import_keeps_one_real_urllib_and_no_nvda_stubs():
    # Fresh interpreter matters: a suite that preloads urllib hides the bug.
    program = r'''
import sys
sys.path.insert(0, sys.argv[1])
from nvda_harness import manager_class
before = {name: sys.modules.get(name) for name in ('addonHandler', 'globalVars', 'wx')}
first = manager_class()
import urllib.request
bound_urllib = first.GestorTranslate.translate_deepl.__globals__['urllib']
assert bound_urllib is urllib, 'harness detached the urllib package'
assert bound_urllib.request is urllib.request, 'HTTP mock would miss the real adapter'
from unittest.mock import patch
with patch('urllib.request.urlopen') as transport:
    assert bound_urllib.request.urlopen is transport
second = manager_class()
assert first is not second, 'synthetic provider packages leaked between imports'
assert not any(name.startswith('ta_manager_test') for name in sys.modules)
assert all(sys.modules.get(name) is value for name, value in before.items())
'''
    result = subprocess.run(
        [sys.executable, '-I', '-B', '-c', program, str(Path(__file__).parent)],
        capture_output=True, text=True, check=False, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
