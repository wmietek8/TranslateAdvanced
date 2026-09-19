"""Regresje opóźnień, kolejności i anulowania komunikatów gry."""

from __future__ import annotations

import importlib.util
import queue
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from nvda_harness import APP, manager_class
from test_clipboard_translation import PLUGIN, load_method


@pytest.fixture
def queue_type() -> type:
    """Ładuje rzeczywistą kolejkę bez uruchamiania czytnika ekranu."""
    spec = importlib.util.spec_from_file_location(
        "ta_queue_test", APP / "utils/utils_speech_queue.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        yield module.SpeechQueue
    finally:
        sys.modules.pop(spec.name, None)


def pump(events: queue.Queue, condition: Callable[[], bool]) -> None:
    """Obsługuje zdarzenia do uzyskania wyniku, z ograniczonym czasem testu."""
    deadline = time.monotonic() + 3
    while not condition():
        remaining = deadline - time.monotonic()
        assert remaining > 0, "Nie przekazano oczekiwanego wyniku."
        events.get(timeout=remaining)()


def test_workers_keep_order_and_share_pending_request(queue_type: type) -> None:
    """Szybszy drugi wynik nie przeskakuje pierwszego; duplikat nie kosztuje API."""
    events = queue.Queue()
    scheduler = queue_type(events.put)
    release = threading.Event()
    entered = threading.Event()
    second_done = threading.Event()
    calls, results = [], []

    def slow() -> str:
        calls.append("pierwszy")
        entered.set()
        assert release.wait(3)
        return "pierwszy"

    def fast() -> str:
        calls.append("drugi")
        second_done.set()
        return "drugi"

    try:
        started = time.monotonic()
        assert scheduler.submit("a", slow, lambda value, error: results.append(value))
        assert time.monotonic() - started < 0.1
        assert entered.wait(1)
        assert scheduler.submit("b", fast, lambda value, error: results.append(value))
        assert scheduler.submit("a", slow, lambda value, error: results.append(value))
        assert second_done.wait(1)
        events.get(timeout=1)()
        assert results == []
        release.set()
        pump(events, lambda: len(results) == 3)
        assert results == ["pierwszy", "drugi", "pierwszy"]
        assert calls == ["pierwszy", "drugi"]
        assert not scheduler.pending
    finally:
        release.set()
        scheduler.close()


def test_cancel_rejects_late_result_and_allows_next_request(queue_type: type) -> None:
    """Przerwanie mowy usuwa poprzednie zlecenia, także gotowe zdarzenia wx."""
    events = queue.Queue()
    scheduler = queue_type(events.put)
    results = []
    try:
        scheduler.submit("a", lambda: "stare", lambda value, error: results.append(value))
        event = events.get(timeout=1)
        scheduler.cancel()
        event()
        scheduler.submit("a", lambda: "nowe", lambda value, error: results.append(value))
        pump(events, lambda: bool(results))
        assert results == ["nowe"]
        scheduler.close()
        assert not scheduler.submit("b", lambda: "x", lambda *args: None)
    finally:
        scheduler.close()


def test_limit_flush_preserves_every_message_and_handles_failure(queue_type: type) -> None:
    """Przeciążenie oddaje wszystkie oryginały w kolejności, bez dalszych zleceń."""
    events = queue.Queue()
    scheduler = queue_type(events.put, workers=1, max_pending=2)
    release = threading.Event()
    results = []
    error = ValueError("Kontrolowany błąd")
    try:
        for index in range(2):
            assert scheduler.submit(index, lambda: release.wait(3),
                                    lambda value, failure, i=index: results.append((i, failure)))
        assert not scheduler.submit(3, lambda: None, lambda *args: None)
        scheduler.flush(error)
        assert results == [(0, error), (1, error)]
        assert not scheduler.pending
    finally:
        release.set()
        scheduler.close()


def test_error_is_delivered_on_calling_thread(queue_type: type) -> None:
    """Awaria usługi jest obsługiwana na wątku odbiorcy, bez awarii pracownika."""
    events = queue.Queue()
    scheduler = queue_type(events.put)
    results = []
    owner = threading.get_ident()

    def fail() -> None:
        assert threading.get_ident() != owner
        raise ValueError("Kontrolowany błąd")

    try:
        scheduler.submit("a", fail, lambda value, error: results.append((threading.get_ident(), error)))
        pump(events, lambda: bool(results))
        assert results[0][0] == owner
        assert isinstance(results[0][1], ValueError)
    finally:
        scheduler.close()


def test_even_immediate_result_waits_for_dispatch(queue_type: type) -> None:
    """Gotowy wynik nie wywołuje obsługi mowy wewnątrz submit przed zdarzeniem wx."""
    events = queue.Queue()
    scheduler = queue_type(events.put)
    results = []
    try:
        scheduler.submit("a", lambda: "gotowe", lambda value, error: results.append(value))
        event = events.get(timeout=1)
        assert results == []
        event()
        assert results == ["gotowe"]
    finally:
        scheduler.close()


@pytest.mark.parametrize("kwargs", [
    {"workers": 0}, {"workers": 5}, {"workers": True},
    {"max_pending": 0}, {"max_pending": 129}, {"max_pending": "32"},
])
def test_invalid_limits(queue_type: type, kwargs: dict) -> None:
    """Niepoprawne parametry są odrzucane przed uruchomieniem wątków."""
    with pytest.raises((TypeError, ValueError)):
        queue_type(lambda fn: None, **kwargs)


def test_invalid_callbacks_and_closed_event_loop(queue_type: type) -> None:
    """Zamykanie wx nie pozwala na odczyt z wątku roboczego ani ponowne zlecenie."""
    with pytest.raises(TypeError):
        queue_type(None)
    failed = threading.Event()

    def dispatch(function: Callable) -> None:
        failed.set()
        raise RuntimeError("Pętla zamknięta")

    scheduler = queue_type(dispatch)
    try:
        with pytest.raises(TypeError):
            scheduler.submit("x", None, lambda *args: None)
        with pytest.raises(TypeError):
            scheduler.submit([], lambda: None, lambda *args: None)
        scheduler.submit("a", lambda: "wynik", lambda *args: pytest.fail("Odczyt z tła"))
        assert failed.wait(1)
        # Zamknięcie jest idempotentne, także podczas obsługi błędu dispatch.
        scheduler.close()
        assert not scheduler.pending
    finally:
        scheduler.close()


@pytest.mark.parametrize("pre_cancel_available", [True, False])
def test_plugin_connects_early_cancel_and_supports_older_nvda(
    monkeypatch: pytest.MonkeyPatch, pre_cancel_available: bool,
) -> None:
    """Stary NVDA bez wczesnego powiadomienia zachowuje działającą drogę mowy."""
    registered, enabled = [], []
    hook = SimpleNamespace(register=registered.append)
    extensions = SimpleNamespace()
    if pre_cancel_available:
        extensions.pre_speechCanceled = hook
    monkeypatch.setitem(sys.modules, "speech", SimpleNamespace(extensions=extensions))
    dispatch = lambda function: None
    manager = SimpleNamespace(enable_speech_queue=enabled.append, cancel_pending_speech=lambda: None)
    plugin = SimpleNamespace(gestor_translate=manager)
    initialize = load_method(PLUGIN, "GlobalPlugin", "_initialize_speech_queue",
                             {"wx": SimpleNamespace(CallAfter=dispatch)})
    initialize(plugin)
    assert enabled == ([dispatch] if pre_cancel_available else [])
    assert registered == ([manager.cancel_pending_speech] if pre_cancel_available else [])


@pytest.fixture
def manager() -> Any:
    """Przechwytuje mowę, zachowując rzeczywisty menedżer i wątki tłumaczenia."""
    module = manager_class()
    events, spoken = queue.Queue(), []
    settings = SimpleNamespace(
        choiceOnline=9, api_openai=0, api_deepl_pro=0,
        openai_auth_mode="api_key", openai_model_api="gpt-5.6-terra",
        openai_codex_path="", choiceLangDestino_openai="pl",
        choiceLangDestino_deepl="pl", choiceLangOrigen="auto", chkAltLang=False,
        chkCache=True, _translationCache={}, _enableTranslation=True,
        _lastTranslatedText=None, historialOrigen=deque(), historialDestino=deque(),
        _nvdaSpeak=lambda **kwargs: spoken.append(kwargs),
    )
    instance = module.GestorTranslate.__new__(module.GestorTranslate)
    instance.frame = SimpleNamespace(
        gestor_settings=settings,
        gestor_apis=SimpleNamespace(get_api=lambda *args: {"key": "testowy-klucz"}),
    )
    instance.enable_speech_queue(events.put)
    try:
        yield instance, settings, events, spoken
    finally:
        instance.close_speech_queue()


@pytest.mark.parametrize("provider", [5, 9])
def test_game_messages_do_not_block_and_cached_menu_needs_no_worker(
    manager: Any, provider: int,
) -> None:
    """API działa poza NVDA, a pamięć, komendy i historia działają na jego wątku."""
    instance, settings, events, spoken = manager
    settings.choiceOnline = provider
    owner = threading.get_ident()
    release = threading.Event()
    entered = threading.Event()
    calls = []

    def translate(text: str, options: dict) -> str:
        assert threading.get_ident() != owner
        assert options["provider"] == provider
        calls.append(text)
        entered.set()
        assert release.wait(3)
        return "Ekwipunek"

    instance.translate_with_options = translate
    command = object()
    try:
        started = time.monotonic()
        instance.speak(["Inventory", command, " "], priority=17)
        assert time.monotonic() - started < 0.1
        assert entered.wait(1)
        assert spoken == []
        release.set()
        pump(events, lambda: bool(spoken))
        assert spoken == [{"speechSequence": ["Ekwipunek", command, " "], "priority": 17}]
        assert settings._lastTranslatedText.strip() == "Ekwipunek"
        instance.speak(["Inventory", command, " "], priority=17)
        assert len(spoken) == 2
        assert calls == ["Inventory"]
        assert len(settings.historialOrigen) == 1
    finally:
        release.set()


@pytest.mark.parametrize("change", ["cancel", "disabled", "model", "language", "app", "close"])
def test_stale_translation_is_not_spoken_or_saved(manager: Any, change: str) -> None:
    """Po zmianie okna, ustawień lub anulowaniu stary komunikat nie wraca."""
    instance, settings, events, spoken = manager
    instance.translate_with_options = lambda text, options: "Stary wynik"
    instance.speak(["Old message"])
    event = events.get(timeout=1)
    if change == "cancel":
        instance.cancel_pending_speech()
    elif change == "disabled":
        settings._enableTranslation = False
    elif change == "model":
        settings.openai_model_api = "gpt-5.6-sol"
    elif change == "language":
        settings.choiceLangDestino_openai = "en"
    elif change == "app":
        instance.get_cache_app_name = lambda: "inna_aplikacja"
    else:
        instance.close_speech_queue()
    event()
    assert spoken == []
    assert not settings.historialOrigen
    assert not any(settings._translationCache.values())


def test_burst_preserves_order_and_deduplicates_requests(manager: Any) -> None:
    """Powtarzane menu i wiadomość z serwera nie są gubione ani przestawiane."""
    instance, settings, events, spoken = manager
    calls = []
    release = threading.Event()

    def translate(text: str, options: dict) -> str:
        calls.append(text)
        assert release.wait(3)
        return {"Inventory": "Ekwipunek", "Server message": "Wiadomość serwera"}[text]

    instance.translate_with_options = translate
    try:
        for text in ("Inventory", "Server message", "Inventory"):
            instance.speak([text])
        release.set()
        pump(events, lambda: len(spoken) == 3)
        assert [value["speechSequence"][0] for value in spoken] == [
            "Ekwipunek", "Wiadomość serwera", "Ekwipunek",
        ]
        assert sorted(calls) == ["Inventory", "Server message"]
    finally:
        release.set()


def test_api_refusal_flushes_pending_originals_and_pauses_new_calls(manager: Any) -> None:
    """Błąd salda nie tworzy kolejki powtarzanych odmów ani nie gubi tekstu."""
    instance, settings, events, spoken = manager
    error_type = instance.translate.__globals__["TranslationError"]
    calls = []

    def fail(text: str, options: dict) -> str:
        calls.append(text)
        raise error_type("Brak salda.", retry_after=60)

    instance.translate_with_options = fail
    instance.speak(["First"])
    instance.speak(["Second"])
    pump(events, lambda: len(spoken) >= 3)
    count = len(calls)
    instance.speak(["Third"])
    assert len(calls) == count
    assert [item["speechSequence"][0] for item in spoken[-3:]] == ["First", "Second", "Third"]
    assert "testowy-klucz" not in repr(instance._realtime_retry)
    assert not settings.historialOrigen


def test_broken_configuration_returns_original_without_worker(manager: Any) -> None:
    """Błąd konfiguracji nie usuwa tekstu i nie dociera do NVDA jako wyjątek."""
    instance, settings, events, spoken = manager

    def fail() -> dict:
        raise ValueError("prywatne ustawienia")

    instance.translation_options = fail
    instance.speak(["Inventory"])
    assert spoken == [{"speechSequence": ["Inventory"], "priority": None}]
    assert not instance._speech_queue.pending


def test_overload_reads_all_originals_without_losing_game_events(manager: Any) -> None:
    """Przekroczenie limitu kolejki zachowuje każdy komunikat w poprawnej kolejności."""
    instance, settings, events, spoken = manager
    instance._speech_queue._max_pending = 2
    release = threading.Event()
    instance.translate_with_options = lambda text, options: release.wait(3) and "wynik"
    try:
        for text in ("First", "Second", "Third"):
            instance.speak([text])
        assert [item["speechSequence"][0] for item in spoken[-3:]] == ["First", "Second", "Third"]
        assert not instance._speech_queue.pending
    finally:
        release.set()


def test_cancel_stops_remaining_parts_of_speech(manager: Any) -> None:
    """Ctrl nie tylko odrzuca wynik: zatrzymuje wysyłanie kolejnych etykiet."""
    instance, settings, events, spoken = manager
    scheduler_type = type(instance._speech_queue)
    instance.close_speech_queue()
    instance._speech_queue = scheduler_type(events.put, workers=1)
    settings.choiceOnline = 5
    entered, release = threading.Event(), threading.Event()
    calls = []

    def translate(text: str, options: dict) -> str:
        calls.append(text)
        if text == "First":
            entered.set()
            assert release.wait(3)
        return "Wynik: " + text

    instance.translate_with_options = translate
    try:
        instance.speak(["First", "Second", "Third"])
        assert entered.wait(1)
        instance.cancel_pending_speech()
        release.set()
        instance.speak(["New"])
        pump(events, lambda: bool(spoken))
        assert calls == ["First", "New"]
        assert spoken == [{"speechSequence": ["Wynik: New"], "priority": None}]
    finally:
        release.set()
