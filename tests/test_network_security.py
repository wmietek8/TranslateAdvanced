"""Network invariants: imported legacy providers must not disable global TLS."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'addon/globalPlugins/TranslateAdvanced'


class NetworkSecurityTests(unittest.TestCase):
    def test_no_provider_replaces_default_tls_context_with_unverified(self):
        offenders = []
        for path in ROOT.rglob('*.py'):
            tree = ast.parse(path.read_text('utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Attribute) and target.attr == '_create_default_https_context':
                            offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual([], offenders)


if __name__ == '__main__':
    unittest.main()
