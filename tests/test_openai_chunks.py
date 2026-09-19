"""Real translation facade/serialization; fake HTTP responses, never live calls.

All patches and package imports are scoped to a test. No NVDA, clipboard or
personal credentials are loaded. Response text is a deterministic test fixture,
not evidence of linguistic quality or a live provider response.
"""
from contextlib import contextmanager
import importlib
import importlib.util
import io
import json
from pathlib import Path
import queue
import subprocess
import sys
import time
import types
from unittest import mock

import pytest


APP = Path(__file__).resolve().parents[1] / "addon/globalPlugins/TranslateAdvanced/app"


@pytest.fixture
def backend():
    package = types.ModuleType("openai_chunks_test_app")
    package.__path__ = [str(APP)]
    prefix = package.__name__
    previous = {key: value for key, value in sys.modules.items()
                if key == prefix or key.startswith(prefix + ".")}
    sys.modules[prefix] = package
    try:
        name = prefix + ".src_translations.src_openai_4o_api"
        spec = importlib.util.spec_from_file_location(
            name, APP / "src_translations/src_openai_4o_api.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        # Fresh stdlib imports may already be held by another test's HTTP mocks.
        # Remove only this fixture's package, never roll back all of sys.modules.
        for key in list(sys.modules):
            if key == prefix or key.startswith(prefix + "."):
                sys.modules.pop(key, None)
        sys.modules.update(previous)


def test_fixture_teardown_preserves_unrelated_imports():
    name = "openai_chunks_test_unrelated_import"
    imported = types.ModuleType(name)
    scope = backend.__wrapped__()
    try:
        next(scope)
        sys.modules[name] = imported
        scope.close()
        assert sys.modules.get(name) is imported
        assert "openai_chunks_test_app" not in sys.modules
    finally:
        scope.close()
        sys.modules.pop(name, None)


def fixture_translation(text):
    return text.replace("Hello", "Witaj").replace("world", "świat")


def completed_response(text, source="en", target="pl"):
    return {
        "status": "completed", "error": None,
        "output": [{
            "type": "message", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": json.dumps({
                "translated_text": text, "detected_source_language": source,
                "target_language": target,
            }, ensure_ascii=False)}],
        }],
    }


class APIBoundary:
    """Only urllib's HTTP boundary is replaced; all backend code stays real."""

    def __init__(self, transform=fixture_translation):
        self.transform = transform
        self.requests = []
        self.bodies = []
        self.source = "en"
        self.target = "pl"
        self.catalog_reads = 0
        self.fail_on_piece = None
        self.failure = "timeout"

    def __call__(self, request, *, timeout, context):
        assert context.check_hostname
        assert timeout > 0
        self.requests.append(request)
        if request.full_url == "https://api.openai.com/v1/models":
            # A changing catalog exposes accidental per-chunk auto selection.
            self.catalog_reads += 1
            model = "gpt-5.6-luna" if self.catalog_reads == 1 else "gpt-4.1-mini"
            return io.BytesIO(json.dumps({"data": [{"id": model}]}).encode("utf-8"))
        assert request.full_url == "https://api.openai.com/v1/responses"
        body = json.loads(request.data)
        self.bodies.append(body)
        text = body["input"][0]["content"][0]["text"]
        if len(self.bodies) == self.fail_on_piece:
            if self.failure == "timeout":
                raise TimeoutError("PRIVATE fixture body must not escape")
            return io.BytesIO(json.dumps({"status": "incomplete", "output": []}).encode("utf-8"))
        response = completed_response(self.transform(text), self.source, self.target)
        return io.BytesIO(json.dumps(response, ensure_ascii=False).encode("utf-8"))

    @property
    def inputs(self):
        return [body["input"][0]["content"][0]["text"] for body in self.bodies]


@contextmanager
def api_boundary(backend, **kwargs):
    boundary = APIBoundary(**kwargs)
    with mock.patch.object(backend, "_urlopen", side_effect=boundary):
        yield boundary


@pytest.mark.parametrize("length", [2999, 3000, 3001])
def test_chunking_starts_strictly_above_3000_characters(backend, length):
    text = ("Hello world 中文🙂. " * length)[:length]
    with api_boundary(backend) as wire:
        result = backend.TranslatorOpenAI().translate_openai(
            "test-only-api-key", text, "pl", model="gpt-5.6-luna")
    assert result == fixture_translation(text)
    if length <= 3000:
        assert wire.inputs == [text]
    else:
        assert len(wire.inputs) == 2
        assert all(len(piece) <= 2000 for piece in wire.inputs)


def test_repeated_lines_are_translated_once_with_literal_blank_lines(backend):
    line = "Hello world, zażółć gęślą, 中文、العربية, שלום 🙂 — keep this line."
    gaps = ["\r\n\r\n\t", "\n  ", "\r\n \t\r\n", "\u2028\u2028", "\r"]
    text = " \t" + "".join(line + gaps[i % len(gaps)] for i in range(90)) + "  \n"
    assert 3000 < len(text) <= 24000
    with api_boundary(backend, transform=lambda text: fixture_translation(text.strip())) as wire:
        result = backend.TranslatorOpenAI().translate_openai(
            "test-only-api-key", text, "pl", model="gpt-5.6-luna")
    assert wire.inputs == [line]
    assert result == fixture_translation(text)


@pytest.mark.parametrize("text", [
    "".join("Hello %04d\n" % index for index in range(1000)) * 2,
    "".join(chr(0x4E00 + index) + "\n" for index in range(6000)) * 2,
    "".join(" \tHello %04d\u2003\r\n \t\r\n" % index for index in range(400)) * 2,
    "".join("Hello %04d: preserve this numbered sentence and its newline.\r\n" % index
            for index in range(33)) * 2,
], ids=["1000-numbered-lines", "6000-unicode-lines", "mixed-whitespace", "one-over-request-budget"])
def test_many_distinct_repeated_lines_have_a_bounded_request_plan(backend, document_transport, text):
    wire, params = document_transport
    assert 3000 < len(text) <= 24000
    params["model"] = "auto"
    result = backend.TranslatorOpenAI().translate_openai(text=text, **params)
    assert len(wire.bodies) <= 32
    assert result == fixture_translation(text)
    if params["auth_mode"] == "api_key":
        assert wire.catalog_reads == 1
    else:
        assert sum(message.get("method") == "model/list" for message in wire.rpc_messages) == 1
    assert {body["model"] for body in wire.bodies} == {"gpt-5.6-luna"}
    pieces = list(backend._translation_chunks(text))
    assert "".join(pieces) == text
    assert all(len(piece) <= 2000 for piece in pieces if piece.strip())
    assert len({piece for piece in pieces if piece.strip()}) == len(wire.bodies)


def varied_text():
    return "\n\t" + "".join(
        f"Hello world {index:03d}: Zażółć gęślą jaźń, 中文、العربية, שלום 🙂."
        + ("\r\n\r\n  " if index % 7 == 0 else "\n")
        for index in range(120)
    ) + "\t \n\r\n"


def test_unique_lines_are_grouped_and_words_and_edge_separators_preserved(backend):
    text = varied_text()
    with api_boundary(backend, transform=lambda text: fixture_translation(text.strip())) as wire:
        result = backend.TranslatorOpenAI().translate_openai(
            "test-only-api-key", text, "pl", model="gpt-5.6-luna")
    assert 2 <= len(wire.inputs) <= len(text) // 1200 + 1
    assert all(0 < len(piece) <= 2000 for piece in wire.inputs)
    assert [word for piece in wire.inputs for word in piece.split()] == text.split()
    assert result == fixture_translation(text)


def test_repeated_multiline_paragraphs_keep_context_in_one_request(backend):
    paragraph = (
        "Hello world, this is one paragraph with related lines.\r\n"
        "中文、العربية, שלום 🙂 and the second line has context.\r\n"
        "Last line closes the same paragraph, without changing its order."
    )
    text = "\n" + (paragraph + "\r\n \t\r\n") * 40 + "\t"
    assert 3000 < len(text) <= 24000
    with api_boundary(backend) as wire:
        result = backend.TranslatorOpenAI().translate_openai(
            "test-only-api-key", text, "pl", model="gpt-5.6-luna")
    assert wire.inputs == [paragraph]
    assert result == fixture_translation(text)


def test_no_whitespace_unicode_is_bounded_without_character_loss(backend):
    text = "漢字🙂👩\u200d💻" * 700
    with api_boundary(backend, transform=lambda text: text) as wire:
        result = backend.TranslatorOpenAI().translate_openai(
            "test-only-api-key", text, "pl", model="gpt-5.6-luna")
    assert result == text
    assert 2 <= len(wire.inputs) <= 4
    assert all(len(piece) <= 2000 for piece in wire.inputs)


@pytest.mark.parametrize("model", ["gpt-5.6-luna", "auto"])
def test_all_api_pieces_keep_one_selected_model_key_provider_and_language_pair(backend, model):
    text = varied_text()
    with api_boundary(backend) as wire:
        wire.source, wire.target = "pl", "en"
        result = backend.TranslatorOpenAI().translate_openai(
            "test-only-api-key", text, "pl", model=model, auth_mode="api_key",
            source_language="auto", alternate_language="en",
            mostrar_progreso=False, widget=object(),
            codex_home="unused-home", codex_path="unused-cli",
        )
    assert result == fixture_translation(text)
    assert len(wire.bodies) >= 2
    assert {body["model"] for body in wire.bodies} == {"gpt-5.6-luna"}
    assert wire.catalog_reads == (1 if model == "auto" else 0)
    for request in wire.requests:
        assert request.get_header("Authorization") == "Bearer test-only-api-key"
        assert request.full_url.startswith("https://api.openai.com/v1/")
    for body in wire.bodies:
        assert body["reasoning"] == {"effort": "none"}
        assert body["tools"] == []
        assert body["store"] is False
        assert "The primary target: pl." in body["instructions"]
        assert "The alternate target: en." in body["instructions"]
        assert "Detect the source language" in body["instructions"]


@pytest.mark.parametrize("overrides", [
    {"text": "x" * 24001},
    {"text": " " * 24001},
    {"text": varied_text() + "\ud800"},
    {"text": None}, {"text": b"bytes"},
    {"api_key": None}, {"api_key": "bad\nkey"}, {"api_key": "key with space"},
    {"target_language": "pl\ninjection"}, {"target_language": []},
    {"alternate_language": ""}, {"alternate_language": {}},
    {"source_language": ""}, {"source_language": None},
    {"model": "bad model"}, {"model": []},
    {"auth_mode": "other-provider"}, {"auth_mode": {}},
], ids=[
    "oversize", "oversize-blank", "late-invalid-unicode", "none-input", "bytes-input",
    "missing-key", "newline-key", "space-key", "bad-target", "list-target",
    "empty-alternate", "dict-alternate", "empty-source", "none-source",
    "bad-model", "list-model", "bad-auth", "dict-auth",
])
def test_all_input_validation_precedes_any_api_network(backend, overrides):
    params = dict(api_key="test-only-api-key", text=varied_text(),
                  target_language="pl", model="auto", alternate_language="en")
    params.update(overrides)
    with api_boundary(backend) as wire:
        with pytest.raises(backend.TranslationError):
            backend.TranslatorOpenAI().translate_openai(**params)
    assert wire.requests == []


@pytest.mark.parametrize("model", ["gpt-5.6-luna", "auto"])
def test_unplannable_document_fails_before_api_catalog_or_inference(backend, model):
    with mock.patch.object(backend, "_MAX_TRANSLATION_REQUESTS", 1), api_boundary(backend) as wire:
        with pytest.raises(backend.TranslationError, match="Try a shorter text"):
            backend.TranslatorOpenAI().translate_openai(
                "test-only-api-key", varied_text(), "pl", model=model)
    assert wire.requests == []


def test_exact_24000_character_limit_still_translates(backend):
    text = (varied_text() * 4)[:24000]
    assert len(text) == 24000
    with api_boundary(backend) as wire:
        result = backend.TranslatorOpenAI().translate_openai(
            "test-only-api-key", text, "pl", model="gpt-5.6-luna")
    assert result == fixture_translation(text)
    assert all(len(piece) <= 2000 for piece in wire.inputs)


@pytest.mark.parametrize("failure", ["timeout", "incomplete"])
def test_second_piece_failure_never_returns_partial_output(backend, failure):
    sentinel = object()
    result = sentinel
    with api_boundary(backend) as wire:
        wire.fail_on_piece, wire.failure = 2, failure
        with pytest.raises(backend.TranslationError) as error:
            result = backend.TranslatorOpenAI().translate_openai(
                "test-only-api-key", varied_text(), "pl", model="gpt-5.6-luna")
    assert len(wire.bodies) == 2
    assert result is sentinel
    assert "PRIVATE" not in str(error.value)


def test_identical_chunks_are_never_memoized_across_invocations(backend):
    line = "Hello world 中文🙂 — repeated only within this one invocation."
    text = (line + "\r\n") * 90
    translator = backend.TranslatorOpenAI()
    with api_boundary(backend) as first:
        one = translator.translate_openai("test-only-api-key", text, "pl", model="gpt-5.6-luna")
    with api_boundary(backend, transform=lambda text: text.replace("Hello", "Bonjour")) as second:
        two = translator.translate_openai("test-only-api-key", text, "pl", model="gpt-5.6-luna")
    assert first.inputs == second.inputs == [line]
    assert one == fixture_translation(text)
    assert two == text.replace("Hello", "Bonjour")


class RPCPipe:
    def __init__(self):
        self.items = queue.Queue()
        self.closed = False

    def readline(self, size=-1):
        return self.items.get(timeout=5)

    read = readline

    def close(self):
        if not self.closed:
            self.closed = True
            self.items.put("")


class RPCProcess:
    """Fake process/stdio boundary for the real managed Codex client."""

    def __init__(self, owner):
        self.owner = owner
        self.stdout, self.stderr = RPCPipe(), RPCPipe()
        self.returncode = None
        self.stdin = types.SimpleNamespace(write=self.write, flush=lambda: None, close=lambda: None)

    def write(self, data):
        message = json.loads(data)
        self.owner.rpc_messages.append(message)
        method = message.get("method")
        if method == "initialized":
            return len(data)
        if method == "initialize":
            value = {"userAgent": "test-only-codex/0.155.0"}
        elif method == "account/read":
            value = {"account": {"type": "chatgpt", "email": "fixture@example.invalid"}}
        elif method == "model/list":
            models = ["gpt-5.6-luna", "gpt-4.1-mini"]
            if self.owner.change_catalog and self.owner.bodies:
                models = ["gpt-4.1-mini"]
            value = {"data": [{"id": model, "inputModalities": ["text"]} for model in models], "nextCursor": None}
        else:
            raise AssertionError("Unexpected/unsafe fixture RPC: " + str(method))
        self.stdout.items.put(json.dumps({"id": message["id"], "result": value}) + "\n")
        return len(data)

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = 0
        self.stdout.close()
        self.stderr.close()

    kill = terminate

    def wait(self, timeout=None):
        assert self.returncode is not None
        return self.returncode


class OAuthBoundary:
    """HTTP SSE and managed CLI process fixtures, not a translation stub."""

    def __init__(self, home, exe):
        self.home, self.exe = home, exe
        self.bodies, self.literals, self.headers = [], [], []
        self.connections, self.processes, self.rpc_messages = [], [], []
        self.change_catalog = False
        self.clock_offset = 0
        self.fail_on_piece = None
        self.failure = "incomplete"
        self.transform = fixture_translation

    def clock(self):
        return time.monotonic() + self.clock_offset

    def spawn(self, args, **kwargs):
        assert args[0] == str(self.exe)
        assert kwargs["env"]["CODEX_HOME"] == str(self.home)
        process = RPCProcess(self)
        self.processes.append(process)
        return process

    def connect(self, host, **kwargs):
        assert host == "chatgpt.com"
        assert kwargs["context"].check_hostname
        owner = self

        class Connection:
            sock = None
            closed = False

            def request(self, method, path, body, headers):
                assert (method, path) == ("POST", "/backend-api/codex/responses")
                owner.bodies.append(json.loads(body))
                owner.headers.append(headers)
                literal = json.loads(owner.bodies[-1]["input"][0]["content"][0]["text"])
                owner.literals.append(literal)
                self.text = literal["text"]

            def getresponse(self):
                if owner.change_catalog:
                    owner.clock_offset += 301  # Expire the real client's catalog cache.
                event = {"type": "response.completed", "response": {
                    "status": "completed", "output": [{
                        "type": "message", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": owner.transform(self.text)}],
                    }],
                }}
                if len(owner.bodies) == owner.fail_on_piece:
                    if owner.failure == "timeout":
                        raise TimeoutError("PRIVATE fixture timeout")
                    event = {"type": "response.incomplete"}
                response = io.BytesIO(("data: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode("utf-8"))
                response.status = 200
                response.getheader = lambda name, default=None: "text/event-stream"
                return response

            def close(self):
                self.closed = True

        connection = Connection()
        self.connections.append(connection)
        return connection


@contextmanager
def oauth_boundary(backend, tmp_path):
    root = backend.__package__.split(".")[0]
    codex = importlib.import_module(root + ".utils.utils_codex")
    responses = importlib.import_module(root + ".utils.utils_codex_response")
    home, exe = tmp_path / "test-owned-codex", tmp_path / "codex.exe"
    home.mkdir()
    exe.write_bytes(b"MZ")  # Never launched; Popen and version probe are fake boundaries.
    (home / codex._MARKER_NAME).write_text(codex._MARKER, encoding="utf-8")
    (home / "auth.json").write_text(json.dumps({
        "auth_mode": "chatgpt", "OPENAI_API_KEY": None,
        "tokens": {"access_token": "fixture-oauth-access", "account_id": "fixture-account"},
    }), encoding="utf-8")
    wire = OAuthBoundary(home, exe)
    with mock.patch.object(backend, "_urlopen", side_effect=AssertionError("OAuth must not call the API-key provider")), \
            mock.patch.object(codex.subprocess, "Popen", side_effect=wire.spawn), \
            mock.patch.object(codex.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "codex-cli 0.155.0\n", "")), \
            mock.patch.object(codex, "time", types.SimpleNamespace(monotonic=wire.clock)), \
            mock.patch.object(responses, "HTTPSConnection", side_effect=wire.connect):
        try:
            yield wire
        finally:
            codex.close_clients()


@pytest.fixture(params=["api_key", "chatgpt"])
def document_transport(backend, tmp_path, request):
    boundary = api_boundary(backend) if request.param == "api_key" else oauth_boundary(backend, tmp_path)
    with boundary as wire:
        params = dict(api_key="test-only-api-key", target_language="pl",
                      model="gpt-5.6-luna", auth_mode=request.param)
        if request.param == "chatgpt":
            params.update(api_key=None, codex_home=str(wire.home), codex_path=str(wire.exe))
        yield wire, params


@pytest.mark.parametrize("kind, expected_calls", [
    ("single", 1), ("distinct", 2), ("repeated", 1),
])
def test_output_budget_is_atomic_counts_utf8_and_stops_further_requests(backend, document_transport, kind, expected_calls):
    wire, params = document_transport
    line = "Hello world 中文🙂 — this repeated line must be translated only once."
    text = {
        "single": "Hello",
        "distinct": "a" * 1800 + "\r\n \t" + "b" * 1800 + "\n\n" + "c" * 1800,
        "repeated": (line + "\r\n \t") * 90,
    }[kind]
    output = "🙂" * 16
    # Lower only the aggregate budget; each mocked response is far below the
    # unchanged per-request 8 MiB cap. Count UTF-8 bytes, not code points.
    limit = len(output.encode("utf-8")) - 1 if kind == "single" else 128
    wire.transform = lambda piece: output
    sentinel = object()
    result = sentinel
    with mock.patch.object(backend, "_MAX_TRANSLATED_OUTPUT_BYTES", limit):
        with pytest.raises(backend.TranslationError, match="response that is too large") as error:
            result = backend.TranslatorOpenAI().translate_openai(text=text, **params)
    assert result is sentinel
    assert len(wire.bodies) == expected_calls
    assert {body["model"] for body in wire.bodies} == {"gpt-5.6-luna"}
    assert str(error.value) == "OpenAI returned a response that is too large."


@pytest.mark.parametrize("over_limit", [False, True])
def test_output_budget_includes_literal_whitespace_and_all_memoized_copies(backend, document_transport, over_limit):
    wire, params = document_transport
    line = "Hello world 中文🙂 — preserve every literal separator and repeated line."
    separator = "\r\n \t\u2003"
    text = "\t" + (line + separator) * 90 + " \n"
    expected = "\t" + ("🙂" + separator) * 90 + " \n"
    assert len(text) > 3000
    wire.transform = lambda piece: "🙂"
    limit = len(expected.encode("utf-8")) - int(over_limit)
    with mock.patch.object(backend, "_MAX_TRANSLATED_OUTPUT_BYTES", limit):
        if over_limit:
            with pytest.raises(backend.TranslationError, match="response that is too large"):
                backend.TranslatorOpenAI().translate_openai(text=text, **params)
        else:
            assert backend.TranslatorOpenAI().translate_openai(text=text, **params) == expected
    assert len(wire.bodies) == 1


@pytest.mark.parametrize("model", ["gpt-5.6-luna", "auto"])
@pytest.mark.parametrize("source_language", ["auto", "pl"])
def test_real_lazy_oauth_transport_keeps_selected_provider_and_complete_plain_text(backend, tmp_path, model, source_language):
    text = varied_text()
    with oauth_boundary(backend, tmp_path) as wire:
        result = backend.TranslatorOpenAI().translate_openai(
            "must-not-send-api-key", text, "pl", model=model, auth_mode="chatgpt",
            codex_home=str(wire.home), codex_path=str(wire.exe),
            alternate_language="en", source_language=source_language,
        )
    assert result == fixture_translation(text)
    assert 2 <= len(wire.bodies) <= len(text) // 1200 + 1
    assert len(wire.processes) == 1
    assert all(connection.closed for connection in wire.connections)
    for body, literal, headers in zip(wire.bodies, wire.literals, wire.headers):
        assert len(literal["text"]) <= 2000
        assert literal["source_language"] == source_language
        assert literal["target_language"] == "pl"
        assert literal["alternate_language"] == "en"
        assert body["model"] == "gpt-5.6-luna"
        assert body["reasoning"] == {"effort": "none"}
        assert body["tools"] == []
        assert body["store"] is False
        assert headers["Authorization"] == "Bearer fixture-oauth-access"
        assert headers["ChatGPT-Account-Id"] == "fixture-account"
    assert all(message.get("method") not in ("turn/start", "thread/start") for message in wire.rpc_messages)


def test_oauth_auto_model_stays_pinned_without_refetch_between_pieces(backend, tmp_path):
    """Upływ czasu nie zmienia modelu ani nie wymusza ponownego katalogu."""
    with oauth_boundary(backend, tmp_path) as wire:
        wire.change_catalog = True
        result = backend.TranslatorOpenAI().translate_openai(
            None, varied_text(), "pl", model="auto", auth_mode="chatgpt",
            codex_home=str(wire.home), codex_path=str(wire.exe))
    assert result == fixture_translation(varied_text())
    assert len(wire.bodies) >= 2
    assert {body["model"] for body in wire.bodies} == {"gpt-5.6-luna"}
    assert sum(message.get("method") == "model/list" for message in wire.rpc_messages) == 1


@pytest.mark.parametrize("failure", ["incomplete", "timeout"])
def test_second_oauth_piece_failure_never_returns_first_piece(backend, tmp_path, failure):
    sentinel = object()
    result = sentinel
    with oauth_boundary(backend, tmp_path) as wire:
        wire.fail_on_piece, wire.failure = 2, failure
        with pytest.raises(backend.TranslationError):
            result = backend.TranslatorOpenAI().translate_openai(
                None, varied_text(), "pl", model="gpt-5.6-luna", auth_mode="chatgpt",
                codex_home=str(wire.home), codex_path=str(wire.exe))
    assert result is sentinel
    assert len(wire.bodies) == 2
    assert all(connection.closed for connection in wire.connections)


@pytest.mark.parametrize("separator", ["\r\n\r\n\t", "\n", "  "])
def test_long_prose_prefers_nearby_paragraph_line_or_sentence_boundaries(backend, separator):
    first = ("Hello world. " * 120).rstrip()
    text = first + separator + "another ordinary word " * 130
    with api_boundary(backend) as wire:
        result = backend.TranslatorOpenAI().translate_openai(
            "test-only-api-key", text, "pl", model="gpt-5.6-luna")
    assert wire.inputs[0] == first
    assert result == fixture_translation(text)


@pytest.mark.parametrize("length", [3000, 3001])
def test_oauth_single_call_boundary_preserves_literal_input(backend, tmp_path, length):
    text = ("Hello world 中文🙂. " * length)[:length]
    with oauth_boundary(backend, tmp_path) as wire:
        result = backend.TranslatorOpenAI().translate_openai(
            None, text, "pl", model="gpt-5.6-luna", auth_mode="chatgpt",
            codex_home=str(wire.home), codex_path=str(wire.exe))
    assert result == fixture_translation(text)
    if length <= 3000:
        assert [literal["text"] for literal in wire.literals] == [text]
    else:
        assert len(wire.literals) == 2
        assert all(len(literal["text"]) <= 2000 for literal in wire.literals)


@pytest.mark.parametrize("overrides", [
    {"text": "字" * 24001}, {"text": varied_text() + "\udfff"},
    {"model": "bad model"}, {"target_language": None},
    {"source_language": "bad language"}, {"alternate_language": []},
    # The facade accepts these syntactically, but the OAuth transport caps codes
    # at 48 characters. Reject them before even resolving an automatic model.
    {"target_language": "en-" + "Latn-" * 10 + "US"},
    {"source_language": "en-" + "Latn-" * 10 + "US"},
    {"alternate_language": "en-" + "Latn-" * 10 + "US"},
])
def test_invalid_oauth_input_never_spawns_process_or_calls_http(backend, tmp_path, overrides):
    with oauth_boundary(backend, tmp_path) as wire:
        params = dict(api_key=None, text=varied_text(), target_language="pl",
                      model="auto", auth_mode="chatgpt",
                      codex_home=str(wire.home), codex_path=str(wire.exe))
        params.update(overrides)
        with pytest.raises(backend.TranslationError):
            backend.TranslatorOpenAI().translate_openai(**params)
    assert wire.processes == wire.bodies == []


@pytest.mark.parametrize("model", ["gpt-5.6-luna", "auto"])
def test_unplannable_document_fails_before_oauth_account_catalog_or_inference(backend, tmp_path, model):
    with mock.patch.object(backend, "_MAX_TRANSLATION_REQUESTS", 1), oauth_boundary(backend, tmp_path) as wire:
        with pytest.raises(backend.TranslationError, match="Try a shorter text"):
            backend.TranslatorOpenAI().translate_openai(
                None, varied_text(), "pl", model=model, auth_mode="chatgpt",
                codex_home=str(wire.home), codex_path=str(wire.exe))
    assert wire.processes == wire.rpc_messages == wire.bodies == []


def test_oauth_repeated_lines_make_one_http_request(backend, tmp_path):
    line = "Hello world 中文🙂 — do not ask the LLM to count ninety repeated lines."
    text = "\n\n" + (line + "\r\n \t\r\n") * 90
    with oauth_boundary(backend, tmp_path) as wire:
        result = backend.TranslatorOpenAI().translate_openai(
            None, text, "pl", model="gpt-5.6-luna", auth_mode="chatgpt",
            codex_home=str(wire.home), codex_path=str(wire.exe))
    assert len(wire.bodies) == 1
    assert wire.literals[0]["text"] == line
    assert result == fixture_translation(text)
