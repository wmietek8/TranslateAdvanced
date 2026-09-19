"""Sprawdza rzeczywisty protokół Realtime, izolację sesji i obie drogi NVDA."""

from __future__ import annotations

import importlib
import json
import queue
import ssl
import threading
import time
from collections import deque
from typing import Any

import pytest
from test_openai_api import packaged_backend


class Connection:
    """Granica sieciowa: zachowuje kolejność zdarzeń prawdziwego protokołu."""

    def __init__(self, module: Any) -> None:
        """Przygotowuje nową sesję bez dostępu do sieci."""
        self.module = module
        self.state = module.State.OPEN
        self.events = deque([{"type": "session.created", "session": {}}])
        self.sent: list[dict] = []
        self.closed = threading.Event()
        self.fail: Exception | None = None
        self.status = "completed"
        self.release: threading.Event | None = None
        self.entered = threading.Event()
        self.reply = "Witaj"

    def send(self, raw: str) -> None:
        """Odtwarza konfigurację, fragment i końcowy wynik powiązany z żądaniem."""
        request = json.loads(raw)
        self.sent.append(request)
        if request["type"] == "session.update":
            self.events.append({"type": "session.updated", "session": request["session"]})
            return
        self.events.extend([
            {"type": "response.output_text.delta", "delta": "niepełny tekst"},
            {"type": "response.done", "response": {
                "status": self.status, "metadata": request["response"]["metadata"],
                "output": [{"type": "message", "role": "assistant", "status": "completed",
                            "content": [{"type": "output_text", "text": self.reply}]}],
            }},
        ])

    def recv(self, timeout: float) -> str:
        """Dostarcza pojedyncze zdarzenie, ewentualnie symulując przerwanie sieci."""
        assert timeout > 0
        if self.fail:
            raise self.fail
        if self.events[0]["type"] == "response.done":
            self.entered.set()
            if self.release is not None:
                assert self.release.wait(2)
        return json.dumps(self.events.popleft())

    def close(self) -> None:
        """Odblokowuje oczekujące operacje przy zamykaniu sesji."""
        self.closed.set()
        self.state = self.module.State.CLOSED
        if self.release is not None:
            self.release.set()


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch):
    """Ładuje prawdziwy moduł w odizolowanej przestrzeni nazw dodatku."""
    with packaged_backend() as backend:
        module = importlib.import_module("openai_api_test_app.utils.utils_openai_realtime")
        monkeypatch.setattr(module, "_POOL", module.RealtimePool())
        monkeypatch.setattr(module, "_real_connect", module._connect, raising=False)
        connections = []

        def connect(key: str, model: str) -> Connection:
            connection = Connection(module)
            connections.append(connection)
            return connection

        monkeypatch.setattr(module, "_connect", connect)
        try:
            yield module, backend, connections
        finally:
            module.close_realtime_clients()


def test_complete_result_and_reuse_without_conversation_history(runtime) -> None:
    """Ten sam model wykorzystuje połączenie, a każde wejście pozostaje osobne."""
    module, backend, connections = runtime
    translator = backend.TranslatorOpenAI()
    for source in ("Hello", "  Hello\r\n"):
        result = translator.translate_openai("test-key", source, "pl", model="gpt-realtime-2.1")
        assert result == ("Witaj" if source == "Hello" else "  Witaj\r\n")
    assert len(connections) == 1
    setup, first, second = connections[0].sent
    assert setup["session"]["reasoning"] == {"effort": "none"}
    for request, source in ((first, "Hello"), (second, "  Hello\r\n")):
        response = request["response"]
        assert response["conversation"] == "none"
        assert response["output_modalities"] == ["text"]
        assert response["tools"] == [] and response["tool_choice"] == "none"
        assert response["input"] == [{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": source}]}]
        assert "Zawsze tłumacz" in response["instructions"]
        assert source not in response["instructions"]
    assert first["event_id"] != second["event_id"]


def test_bidirectional_source_and_older_model(runtime) -> None:
    """Regionalny kod języka i alternatywa trafiają do jednego żądania."""
    module, backend, connections = runtime
    backend.TranslatorOpenAI().translate_openai(
        "test-key", "Cześć", "pl-PL", source_language="pl", alternate_language="en",
        model="gpt-realtime-1.5",
    )
    setup, request = connections[0].sent
    assert "reasoning" not in setup["session"]
    prompt = request["response"]["instructions"]
    assert "pl-PL" in prompt and "tłumacz na en" in prompt and "źródłowy ma kod pl" in prompt


@pytest.mark.parametrize("source, expected", [("", ""), (" \n\t", " \n\t")])
def test_empty_input_never_opens_connection(runtime, source: str, expected: str) -> None:
    """Puste komunikaty zachowują białe znaki bez żądania do API."""
    module, _, connections = runtime
    assert module.translate_realtime("key", source, "pl", model="gpt-realtime-2.1") == expected
    assert connections == []


@pytest.mark.parametrize("overrides, error", [
    ({"text": None}, TypeError), ({"text": "x" * 3001}, ValueError),
    ({"text": "\ud800"}, ValueError), ({"target_language": None}, ValueError),
    ({"target_language": "pl\ninstrukcja"}, ValueError),
    ({"alternate_language": 3}, ValueError), ({"source_language": []}, ValueError),
])
def test_invalid_input_is_rejected_before_network(runtime, overrides: dict, error: type) -> None:
    """Błędne dane nie tworzą ani sesji, ani płatnej odpowiedzi."""
    module, _, connections = runtime
    arguments = {"api_key": "key", "text": "Hello", "target_language": "pl", "model": "gpt-realtime-2.1"}
    arguments.update(overrides)
    with pytest.raises(error):
        module.translate_realtime(**arguments)
    assert connections == []


@pytest.mark.parametrize("key, model", [(None, "gpt-realtime-2.1"), ("key\n", "gpt-realtime-2.1"),
                                          ("key", "gpt-realtime-translate"), ("key", [])])
def test_invalid_identity_is_safe(runtime, key: Any, model: Any) -> None:
    """Odrzuca nieobsługiwany model i znaki sterujące w kluczu."""
    module, _, connections = runtime
    with pytest.raises(module.RealtimeError):
        with module._POOL.connection(key, model):
            pytest.fail("Niepoprawne dane przeszły walidację.")
    assert connections == []


@pytest.mark.parametrize("status", ["incomplete", "failed", "cancelled", "in_progress"])
def test_partial_output_never_escapes(runtime, status: str) -> None:
    """Otrzymany fragment nie wystarcza do zastąpienia zawartości schowka."""
    module, backend, connections = runtime
    module.warm_realtime("key", "gpt-realtime-2.1")
    connections[0].status = status
    with pytest.raises(backend.TranslationError):
        backend.TranslatorOpenAI().translate_openai("key", "Hello", "pl", model="gpt-realtime-2.1")
    assert connections[0].closed.is_set()


@pytest.mark.parametrize("change", [
    {"output": []}, {"output": None}, {"output": [None]}, {"metadata": None},
    {"metadata": {"translation_id": "inna-wiadomosc"}},
    {"output": [{"type": "function_call"}]},
    {"output": [{"type": "message", "role": "assistant", "status": "completed", "content": []}]},
    {"output": [{"type": "message", "role": "assistant", "status": "completed",
                 "content": [{"type": "refusal", "refusal": "sekret"}]}]},
])
def test_rejects_malformed_and_unrelated_results(runtime, change: dict) -> None:
    """Odmowa, narzędzie i wynik innego żądania nie stają się tłumaczeniem."""
    module, _, _ = runtime
    response = {"status": "completed", "metadata": {"translation_id": "id"}}
    response.update(change)
    with pytest.raises(module.RealtimeError):
        module._result(response, "id")


def test_separate_keys_models_and_expired_connections(runtime) -> None:
    """Klucze i modele nie dzielą sesji; sesję starszą niż 55 minut wymienia się."""
    module, _, connections = runtime
    for key, model in (("a", "gpt-realtime-2.1"), ("b", "gpt-realtime-2.1"), ("b", "gpt-realtime-1.5")):
        module.warm_realtime(key, model)
    assert len(connections) == 3
    module.warm_realtime("c", "gpt-realtime-2.1")
    assert len(connections) == 4 and connections[0].closed.is_set()
    module._POOL._slots[-1].born -= 56 * 60
    module.warm_realtime("c", "gpt-realtime-2.1")
    assert len(connections) == 5 and connections[3].closed.is_set()


def test_failure_closes_session_without_resending_paid_request(runtime) -> None:
    """Awaria nie powtarza zlecenia; kolejne jawne zlecenie otwiera nową sesję."""
    module, backend, connections = runtime
    module.warm_realtime("key", "gpt-realtime-2.1")
    connections[0].fail = OSError("sekret test-key")
    with pytest.raises(backend.TranslationError) as raised:
        backend.TranslatorOpenAI().translate_openai("key", "Hello", "pl", model="gpt-realtime-2.1")
    assert "sekret" not in str(raised.value)
    assert len(connections) == 1 and connections[0].closed.is_set()
    module.warm_realtime("key", "gpt-realtime-2.1")
    assert len(connections) == 2


def test_quota_error_is_sanitized_and_requests_cooldown(runtime) -> None:
    """Brak środków uruchamia istniejącą ochronę przed serią kolejnych żądań."""
    module, backend, connections = runtime
    module.warm_realtime("key", "gpt-realtime-2.1")
    connections[0].events.append({"type": "error", "error": {
        "code": "insufficient_quota", "message": "sekret test-key",
    }})
    with pytest.raises(backend.TranslationError) as raised:
        backend.TranslatorOpenAI().translate_openai("key", "Hello", "pl", model="gpt-realtime-2.1")
    assert raised.value.retry_after == 60 and "sekret" not in str(raised.value)


def test_full_result_waits_and_parallel_inputs_use_other_sessions(runtime) -> None:
    """Równoczesny schowek nie czeka na zablokowaną odpowiedź z gry."""
    module, _, connections = runtime
    module.warm_realtime("key", "gpt-realtime-2.1")
    blocked = connections[0]
    blocked.release = threading.Event()
    results = queue.Queue()
    worker = threading.Thread(target=lambda: results.put(module.translate_realtime(
        "key", "Hello", "pl", model="gpt-realtime-2.1")), daemon=True)
    worker.start()
    try:
        assert blocked.entered.wait(1)
        assert results.empty()
        assert module.translate_realtime("key", "Other", "pl", model="gpt-realtime-2.1") == "Witaj"
        assert len(connections) == 2
        blocked.release.set()
        assert results.get(timeout=2) == "Witaj"
    finally:
        blocked.release.set()
        worker.join(2)


def test_shutdown_prevents_late_connection_and_returns_without_waiting(runtime, monkeypatch) -> None:
    """Zamykanie NVDA nie czeka na sieć ani nie pozostawia spóźnionej sesji."""
    module, _, _ = runtime
    entered, release = threading.Event(), threading.Event()
    connection = Connection(module)
    errors = []

    def connect(*args: Any) -> Connection:
        entered.set()
        assert release.wait(2)
        return connection

    def work() -> None:
        try:
            module.warm_realtime("key", "gpt-realtime-2.1")
        except module.RealtimeError as error:
            errors.append(error)

    monkeypatch.setattr(module, "_connect", connect)
    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    try:
        assert entered.wait(1)
        started = time.monotonic()
        module.close_realtime_clients()
        assert time.monotonic() - started < 0.1
        release.set()
        worker.join(2)
        assert errors and connection.closed.is_set()
        with pytest.raises(module.RealtimeError):
            module.warm_realtime("key", "gpt-realtime-2.1")
    finally:
        release.set()
        worker.join(2)


def test_secure_connector_has_no_redirects_or_sensitive_logging(runtime, monkeypatch) -> None:
    """Sprawdza ustawienia prawdziwej biblioteki, bez globalnej zmiany SSL."""
    module, _, _ = runtime
    connector = module._NoRedirect("wss://api.openai.com/v1/realtime")
    error = OSError("sekret")
    assert connector.process_redirect(error) is error
    captured = {}
    class Connector:
        def __init__(self, url: str, **kwargs: Any) -> None:
            captured.update(url=url, **kwargs)

        def connect(self) -> object:
            return object()

    monkeypatch.setattr(module, "_NoRedirect", Connector)
    module._real_connect("test-key", "gpt-realtime-2.1")
    assert captured["url"] == "wss://api.openai.com/v1/realtime?model=gpt-realtime-2.1"
    assert captured["ssl"].verify_mode == ssl.CERT_REQUIRED and captured["ssl"].check_hostname
    assert captured["max_size"] == 1024 * 1024
    assert captured["logger"].level > 50 and not captured["logger"].propagate


@pytest.mark.parametrize("status, expected", [("completed", "Hello"), ("incomplete", "Cześć")])
def test_real_clipboard_command_accepts_only_complete_realtime(runtime, status: str, expected: str) -> None:
    """Prawdziwy gest schowka stosuje wynik atomowo, a przy błędzie zachowuje źródło."""
    import test_clipboard_translation as clipboard_tests

    module, backend, connections = runtime
    case = clipboard_tests.CommandTests()
    case.setUp()
    try:
        settings = case.settings
        settings.choiceOnline = 9
        settings.api_openai = 0
        settings.openai_auth_mode = "api_key"
        settings.openai_model_api = "gpt-realtime-2.1"
        case.manager.translate_openai = backend.TranslatorOpenAI().translate_openai
        module.warm_realtime("test-key", "gpt-realtime-2.1")
        connections[0].reply = "Hello"
        connections[0].status = status
        case.plugin.script_ClipboardTranslation(None)
        case.complete()
        assert case.clipboard.text == expected
        assert case.clipboard.writes == (["Hello"] if status == "completed" else [])
        assert settings._enableTranslation
    finally:
        case.doCleanups()


def test_background_warmup_shares_work_and_sends_no_user_message(runtime, monkeypatch) -> None:
    """Przygotowanie jest asynchroniczne i nie generuje płatnego tekstu."""
    module, _, connections = runtime
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = module.warm_realtime
    calls = []

    def warm(key: str, model: str) -> None:
        calls.append((key, model))
        entered.set()
        assert release.wait(2)
        original(key, model)
        finished.set()

    monkeypatch.setattr(module, "warm_realtime", warm)
    try:
        module.prepare_realtime("key", "gpt-realtime-2.1")
        assert entered.wait(1)
        module.prepare_realtime("key", "gpt-realtime-2.1")
        module.prepare_realtime(None, "gpt-realtime-2.1")
        module.prepare_realtime("key", [])
        assert len(calls) == 1
        release.set()
        assert finished.wait(1)
        assert [request["type"] for request in connections[0].sent] == ["session.update"]
    finally:
        release.set()


@pytest.mark.parametrize("event", [[], {"type": None}, {"type": "session.created", "session": None}])
def test_invalid_session_events_disconnect_safely(runtime, monkeypatch, event: Any) -> None:
    """Uszkodzony początek sesji nie pozostawia połączenia do ponownego użycia."""
    module, _, _ = runtime
    connection = Connection(module)
    connection.events.clear()
    connection.events.append(event)
    monkeypatch.setattr(module, "_connect", lambda *args: connection)
    with pytest.raises(module.RealtimeError):
        module.warm_realtime("key", "gpt-realtime-2.1")
    assert connection.closed.is_set()


def test_expired_deadline_and_server_timeout_are_sanitized(runtime, monkeypatch) -> None:
    """Upływ czasu kończy żądanie także bez kompletnej odpowiedzi serwera."""
    module, _, _ = runtime
    connection = Connection(module)
    with pytest.raises(TimeoutError):
        module._event(connection, time.monotonic() - 1)
    connection.fail = TimeoutError("test-key")
    monkeypatch.setattr(module, "_connect", lambda *args: connection)
    with pytest.raises(module.RealtimeError, match="czas") as raised:
        module.warm_realtime("key", "gpt-realtime-2.1")
    assert "test-key" not in str(raised.value)


@pytest.mark.parametrize("status, code, pause", [(401, "", 60), (403, "", 60), (429, "insufficient_quota", 60),
                                                (429, "rate_limit_exceeded", 60), (500, "", 0), (302, "", 0)])
def test_real_handshake_errors_never_expose_body(runtime, monkeypatch, status: int, code: str, pause: int) -> None:
    """Błąd negocjacji zachowuje kod rozliczeń, lecz ukrywa klucz i treść serwera."""
    module, _, _ = runtime
    http = importlib.import_module("openai_api_test_app.vendor.websockets.http11")
    headers = importlib.import_module("openai_api_test_app.vendor.websockets.datastructures")
    response = http.Response(status, "test", headers.Headers(),
                             body=json.dumps({"error": {"code": code, "message": "sekret"}}).encode())

    def reject(*args: Any) -> None:
        raise module.InvalidStatus(response)

    monkeypatch.setattr(module, "_connect", reject)
    with pytest.raises(module.RealtimeError) as raised:
        module.warm_realtime("key", "gpt-realtime-2.1")
    assert raised.value.retry_after == pause
    assert "sekret" not in str(raised.value)


def test_three_busy_connections_do_not_allow_unbounded_growth(runtime, monkeypatch) -> None:
    """Czwarta operacja ma ograniczone oczekiwanie i nie otwiera kolejnego gniazda."""
    from contextlib import ExitStack

    module, _, connections = runtime
    monkeypatch.setattr(module, "_POOL_WAIT", 0.01)
    with ExitStack() as stack:
        for _ in range(3):
            stack.enter_context(module._POOL.connection("key", "gpt-realtime-2.1"))
        with pytest.raises(module.RealtimeError, match="zajęte"):
            module.warm_realtime("key", "gpt-realtime-2.1")
    assert len(connections) == 3
    module.warm_realtime("key", "gpt-realtime-2.1")
    assert len(connections) == 3


def test_live_probe_uses_both_paths_without_reading_system_clipboard(runtime, monkeypatch, tmp_path) -> None:
    """Narzędzie pomiarowe przechodzi przez prawdziwy gest, kolejkę i parser protokołu."""
    import sys
    from types import SimpleNamespace

    import live_openai_chat

    events = queue.Queue()

    def dispatch(fn: Any, *args: Any, **kwargs: Any) -> None:
        events.put(lambda: fn(*args, **kwargs))

    def pump() -> None:
        while not events.empty():
            events.get_nowait()()

    app = SimpleNamespace(Yield=pump)
    monkeypatch.setitem(sys.modules, "wx", SimpleNamespace(
        App=SimpleNamespace(Get=lambda: app), CallAfter=dispatch, CallLater=lambda delay, fn, *args: dispatch(fn, *args),
    ))
    path = tmp_path / "apis.json"
    path.write_text(json.dumps({"openai": [{"key": "tylko-test"}]}), encoding="utf-8")
    report = live_openai_chat.probe(path, "gpt-realtime-2.1", 1)
    assert len(report["incoming"]) == len(report["clipboard"]) == 6
    assert report["key_file_unchanged"] and report["main_thread_delivery"]
    assert not report["system_clipboard_used"]
    assert "tylko-test" not in json.dumps(report)


@pytest.mark.parametrize("repetitions", [0, 4, True])
def test_live_probe_rejects_invalid_bounds(tmp_path, repetitions: Any) -> None:
    """Niepoprawne parametry pomiaru nie odczytują klucza ani nie otwierają okna."""
    import live_openai_chat

    with pytest.raises(ValueError):
        live_openai_chat.probe(tmp_path / "nie-istnieje", "gpt-realtime-2.1", repetitions)


@pytest.mark.parametrize("provider, mode, model, terminated, expected", [
    (9, "api_key", "gpt-realtime-2.1", False, True),
    (9, "api_key", "gpt-realtime-2.1", True, False),
    (9, "chatgpt", "gpt-realtime-2.1", False, False),
    (5, "api_key", "gpt-realtime-2.1", False, False),
    (9, "api_key", "gpt-5.6-terra", False, False),
])
def test_manager_prepares_only_selected_realtime(monkeypatch, provider: int, mode: str,
                                                model: str, terminated: bool, expected: bool) -> None:
    """Przygotowanie nie zmienia modelu ani nie otwiera konta innej wybranej usługi."""
    import sys
    from types import SimpleNamespace

    from nvda_harness import manager_class

    module = manager_class()
    calls = []
    monkeypatch.setitem(sys.modules, "ta_manager_test.utils.utils_openai_realtime", SimpleNamespace(
        prepare_realtime=lambda *args: calls.append(args)))
    manager = module.GestorTranslate.__new__(module.GestorTranslate)
    manager.frame = SimpleNamespace(_terminating=terminated, gestor_settings=SimpleNamespace(
        choiceOnline=provider, openai_auth_mode=mode, openai_model_api=model, api_openai=0),
        gestor_apis=SimpleNamespace(get_api=lambda *args: {"key": "tylko-test"}))
    manager.prepare_translation()
    assert calls == ([("tylko-test", model)] if expected else [])


def test_long_document_preserves_chunks_and_reuses_identical_parts(runtime) -> None:
    """Długi dokument nadal przechodzi istniejący podział i kończy się jako całość."""
    _, backend, connections = runtime
    source = ("Hello there.\n" * 700) + "\nAnother sentence."
    parts = backend._translation_chunks(source)
    result = backend.TranslatorOpenAI().translate_openai("key", source, "pl", model="gpt-realtime-2.1")
    expected = "".join(
        part[:len(part) - len(part.lstrip())] + "Witaj" + part[len(part.rstrip()):]
        if part.strip() else part for part in parts)
    assert result == expected
    assert len(connections) == 1
    requests = [request for request in connections[0].sent if request["type"] == "response.create"]
    assert len(requests) == len({part for part in parts if part.strip()})
