"""Polish coverage for the OpenAI/clipboard additions, without importing NVDA.

Run with ``uv run --no-project --with pytest --with polib python -m pytest
 tests/test_new_localization.py``. polib is a test-only optional dependency.
The fixed pre-feature revision keeps these checks meaningful after a commit;
changed and untracked Python files are discovered afresh on every run.
"""
import ast
from collections import Counter, defaultdict
import gettext
import io
from pathlib import Path
import re
import string
import subprocess

import pytest

polib = pytest.importorskip("polib", reason="Install polib to validate the Polish catalog")

ROOT = Path(__file__).resolve().parents[1]
ADDON = "addon/globalPlugins/TranslateAdvanced"
CATALOG = "addon/locale/pl/LC_MESSAGES/nvda.po"
BASELINE_REVISION = "ea853c2a94b4288b056b6a68380599882b92c100"


def _git(*args, required=True):
    result = subprocess.run(
        ["git", *args], cwd=ROOT, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False,
    )
    if required:
        assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    return result


def _original_source(path):
    result = _git("show", f"{BASELINE_REVISION}:{path}", required=False)
    return result.stdout.decode("utf-8-sig") if result.returncode == 0 else ""


def changed_python_files():
    """Include staged, unstaged and untracked additions, not a stale msgid list."""
    changed = _git("diff", "--name-only", "-z", BASELINE_REVISION, "--", ADDON)
    untracked = _git("ls-files", "--others", "--exclude-standard", "-z", "--", ADDON)
    paths = set((changed.stdout + untracked.stdout).decode("utf-8").split("\0"))
    return sorted(
        path for path in paths
        if path.endswith(".py") and "/data/lib/" not in path and (ROOT / path).is_file()
    )


def literal_gettext_messages(source):
    messages = defaultdict(set)
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_" and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            messages[node.args[0].value].add(node.lineno)
    return messages


def static_error_messages(source, *, manager=False):
    """Resolve safe literals, including local message variables/HTTP branches.

    Never import a backend or inspect credentials/configuration. str(error),
    server output and dynamically formatted private values are not catalog IDs.
    Manager RuntimeError messages are included alongside ValueError messages.
    """
    tree = ast.parse(source)
    assignments = defaultdict(list)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments[target.id].append(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            assignments[node.target.id].append(node.value)

    def literals(node, visited=frozenset()):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return {node.value}
        if isinstance(node, ast.Name) and node.id not in visited:
            result = set()
            for value in assignments[node.id]:
                result.update(literals(value, visited | {node.id}))
            return result
        if isinstance(node, ast.IfExp):
            return literals(node.body, visited) | literals(node.orelse, visited)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "_" and node.args:
                return literals(node.args[0], visited)
            if isinstance(node.func, ast.Attribute) and node.func.attr == "format":
                return literals(node.func.value, visited)
        return set()

    messages = defaultdict(set)
    error_types = {"TranslationError", "CodexError", "RuntimeError"}
    if manager:
        error_types.update({"ValueError", "RuntimeError"})
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in error_types and node.args):
            for message in literals(node.args[0]):
                messages[message].add(node.lineno)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_http_error_message":
            for returned in ast.walk(node):
                if isinstance(returned, ast.Return):
                    for message in literals(returned.value):
                        messages[message].add(returned.lineno)
    return messages


def required_messages():
    """Return msgid -> source locations for current UI and safe backend errors."""
    required = defaultdict(set)
    for path in changed_python_files():
        source = (ROOT / path).read_text(encoding="utf-8-sig")
        current = literal_gettext_messages(source)
        previous = literal_gettext_messages(_original_source(path))
        for message in current.keys() - previous.keys():
            required[message].update((path.removeprefix("addon/"), line) for line in current[message])

    app = ROOT / ADDON / "app"
    backends = {app / "src_translations/src_openai_4o_api.py",
                app / "src_translations/src_deepl_original.py"}
    # Discover split/new HTTPS helpers as well as the account bridge.
    backends.update((app / "utils").glob("utils_codex*.py"))
    backends.update((app / "managers").glob("managers_*.py"))
    for path in sorted(backends):
        source = path.read_text(encoding="utf-8-sig")
        messages = static_error_messages(source, manager=path.parent.name == "managers")
        for message, lines in messages.items():
            required[message].update((path.relative_to(ROOT / "addon").as_posix(), line) for line in lines)
    return dict(required)


def _brace_placeholders(text):
    fields = Counter()
    for _, field, spec, conversion in string.Formatter().parse(text):
        if field is not None:
            fields[(field, spec, conversion)] += 1
            if spec:
                fields.update(_brace_placeholders(spec))
    return fields


_PERCENT_FIELD = re.compile(r"%(?:\([^)]+\))?[#0 +\-]*(?:\d+|\*)?(?:\.(?:\d+|\*))?[hlL]?[diouxXeEfFgGcrsa%]")


def _percent_placeholders(text):
    return Counter(match.group() for match in _PERCENT_FIELD.finditer(text) if match.group() != "%%")


def _mnemonics(text):
    return text.replace("&&", "").count("&")


@pytest.fixture(scope="module")
def catalog():
    return polib.pofile(str(ROOT / CATALOG), encoding="utf-8")


@pytest.fixture(scope="module")
def messages():
    result = required_messages()
    assert result, "No feature messages discovered; check the source extraction"
    return result


@pytest.mark.parametrize('status', [None, 429])
def test_deepl_strict_errors_use_compiled_polish_templates(catalog, monkeypatch, status):
    from test_deepl_direction import load_deepl
    import urllib.error
    module = load_deepl()
    translation = gettext.GNUTranslations(io.BytesIO(catalog.to_binary()))
    monkeypatch.setattr(module, '_', translation.gettext, raising=False)
    error = TimeoutError('private content') if status is None else urllib.error.HTTPError(
        'https://api.deepl.com', status, 'private key', None, io.BytesIO(b'private body'))
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(module.urllib.request, 'urlopen', fail)
    with pytest.raises(RuntimeError) as caught:
        module.TranslatorDeepL().translate_deepl('hello', 'test-key', strict=True)
    expected = 'DeepL: nie udało się przetłumaczyć tekstu.' if status is None else 'DeepL: błąd HTTP 429'
    assert str(caught.value) == expected
    assert 'private' not in str(caught.value)


def test_openai_dialog_mnemonics_do_not_collide(catalog):
    source = (ROOT / ADDON / 'app/guis/guis_openai.py').read_text(encoding='utf-8')
    labels = [message for message in literal_gettext_messages(source) if _mnemonics(message)]
    assert labels
    for language in ('en', 'pl'):
        seen = {}
        for message in labels:
            text = message if language == 'en' else catalog.find(message).msgstr
            plain = text.replace('&&', '')
            key = plain[plain.index('&') + 1].casefold()
            assert key not in seen, f'{language}: {text!r} and {seen.get(key)!r} share Alt+{key}'
            seen[key] = text


def test_new_literal_gettext_and_backend_errors_have_polish_translations(catalog, messages):
    missing = []
    for message in sorted(messages):
        entry = catalog.find(message)
        if entry is None or not entry.msgstr.strip() or entry.fuzzy or entry.obsolete:
            missing.append(message)
    assert not missing, "Missing usable Polish translations:\n" + "\n".join(missing)


def test_new_translations_preserve_format_placeholders_and_mnemonics(catalog, messages):
    for message in sorted(messages):
        entry = catalog.find(message)
        assert entry is not None, f"Missing Polish translation: {message!r}"
        assert _brace_placeholders(message) == _brace_placeholders(entry.msgstr), message
        assert _percent_placeholders(message) == _percent_placeholders(entry.msgstr), message
        assert _mnemonics(message) == _mnemonics(entry.msgstr), message


def test_new_translations_are_available_in_compiled_gettext_catalog(catalog, messages):
    translations = gettext.GNUTranslations(io.BytesIO(catalog.to_binary()))
    for message in sorted(messages):
        entry = catalog.find(message)
        assert entry is not None and entry.msgstr.strip(), message
        assert translations.gettext(message) == entry.msgstr, message


def test_existing_polish_entries_comments_and_metadata_are_unchanged():
    baseline = _git("show", f"{BASELINE_REVISION}:{CATALOG}").stdout.decode("utf-8-sig")
    current = (ROOT / CATALOG).read_text(encoding="utf-8-sig")
    # Universal newlines allow Git's LF/CRLF checkout conversion, not reformatting.
    assert current.startswith(baseline.replace("\r\n", "\n")), (
        "Append new entries only; preserve the user's original translations, "
        "Spanish msgids, comments, order, wrapping and metadata"
    )
    original = polib.pofile(baseline)
    present = polib.pofile(current)
    for entry in original:
        retained = present.find(entry.msgid, msgctxt=entry.msgctxt, include_obsolete_entries=True)
        assert retained is not None, entry.msgid
        assert retained.__dict__ == entry.__dict__, entry.msgid


def test_feature_catalog_has_no_duplicate_msgids(catalog):
    keys = Counter((entry.msgctxt, entry.msgid) for entry in catalog if not entry.obsolete)
    assert not [key for key, count in keys.items() if count > 1]


def test_source_extraction_handles_multiline_literals_and_safe_error_variables():
    source = '''
_("Clipboard " "changed: {0}")
_(str(error))
message = "Safe timeout."
invalid = "Invalid response."
raise TranslationError(message)
raise CodexError(invalid)
raise ValueError(_("Select a model."))
def _http_error_message(status):
    if status == 401:
        return "Authentication failed."
    return "Request failed."
'''
    assert set(literal_gettext_messages(source)) == {"Clipboard changed: {0}", "Select a model."}
    assert set(static_error_messages(source, manager=True)) == {
        "Safe timeout.", "Invalid response.", "Select a model.",
        "Authentication failed.", "Request failed.",
    }


def test_placeholder_signatures_detect_dropped_repeated_and_changed_fields():
    assert _brace_placeholders("{0} {0}") != _brace_placeholders("{0}")
    assert _brace_placeholders("{0}") != _brace_placeholders("{1}")
    assert _brace_placeholders("{amount:.2f}") != _brace_placeholders("{amount:.1f}")
    assert _brace_placeholders("{name!r}") != _brace_placeholders("{name!s}")
    assert _brace_placeholders("{} {}") != _brace_placeholders("{}")
    assert _brace_placeholders("{{literal}} {value:{width}}") == Counter({("value", "{width}", None): 1, ("width", "", None): 1})
    assert _percent_placeholders("%(name)s: %d (%d)") != _percent_placeholders("%(name)s: %d")
    assert _percent_placeholders("100%% %s") == Counter({"%s": 1})
    assert _mnemonics("Save && &close") == 1
