"""Sprawdzenia łączenia fragmentów bez zmiany kolejności komend NVDA."""

from __future__ import annotations

import importlib.util
from collections import deque
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from nvda_harness import APP, manager_class

Grouping = Callable[..., list[object]]
ManagerFixture = tuple[Any, SimpleNamespace, list[dict[str, Any]]]


@pytest.fixture
def grouping() -> Grouping:
    """Ładuje funkcję bez uruchamiania NVDA lub usług sieciowych."""
    path = APP / "utils" / "utils_speech.py"
    spec = importlib.util.spec_from_file_location("ta_speech_grouping", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.group_adjacent_text


@pytest.mark.parametrize(
    ("sequence", "expected"),
    [
        ([], []),
        (["Hello"], ["Hello"]),
        (
            ["Sound settings", "dialog", "Volume slider"],
            ["Sound settings dialog Volume slider"],
        ),
        (["First ", "second", "\tthird"], ["First second\tthird"]),
        (["First", " ", "second", ""], ["First", " ", "second", ""]),
        ([" ", "\n", ""], [" ", "\n", ""]),
        (["Hello\nworld", "again"], ["Hello\nworld again"]),
    ],
)
def test_adjacent_text_keeps_content(
    grouping: Grouping, sequence: list[object], expected: list[object]
) -> None:
    """Łączenie zachowuje tekst, białe znaki i puste wypowiedzi."""
    original = list(sequence)
    assert grouping(sequence) == expected
    assert sequence == original


def test_commands_remain_in_order_and_keep_identity(grouping: Grouping) -> None:
    """Komendy języka, indeksu i głosu pozostają granicami tekstu."""
    first, second = object(), object()
    sequence = [first, "One", "two", second, "Three", "four", first]
    assert grouping(sequence) == [first, "One two", second, "Three four", first]


def test_cached_fragments_do_not_create_new_requests(grouping: Grouping) -> None:
    """Zapamiętany fragment nie jest włączany do nowego tłumaczenia."""
    cache = {"dialog": "okno dialogowe", "unchanged": "unchanged", "empty": ""}
    assert grouping(["Settings", "dialog", "Volume", "slider"], cached=cache) == [
        "Settings",
        "dialog",
        "Volume slider",
    ]
    assert grouping(["unchanged", "empty"], cached=cache) == ["unchanged empty"]


@pytest.mark.parametrize(
    ("sequence", "limit", "expected"),
    [
        (["ab", "cd"], 5, ["ab cd"]),
        (["ab", "cd"], 4, ["ab", "cd"]),
        (["abcdef", "g", "h"], 3, ["abcdef", "g h"]),
        (["a", "b", "c"], 1, ["a", "b", "c"]),
    ],
)
def test_group_limit_avoids_unnecessary_chunking(
    grouping: Grouping, sequence: list[object], limit: int, expected: list[object]
) -> None:
    """Grupa nie przekracza limitu; długi pojedynczy tekst nie jest cięty."""
    assert grouping(sequence, max_chars=limit) == expected


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, "3000"])
def test_invalid_limits_are_rejected(grouping: Grouping, limit: object) -> None:
    """Niepoprawny limit wywołuje przewidywalny błąd walidacji."""
    with pytest.raises((TypeError, ValueError)):
        grouping(["Hello"], max_chars=limit)


@pytest.mark.parametrize("sequence", ["Hello", b"Hello", None, 42])
def test_invalid_sequences_are_rejected(grouping: Grouping, sequence: object) -> None:
    """Sam tekst nie może zostać omyłkowo podzielony na znaki."""
    with pytest.raises(TypeError):
        grouping(sequence)


def test_invalid_cache_is_rejected(grouping: Grouping) -> None:
    """Nieprawidłowa pamięć nie daje przypadkowego błędu przy iteracji."""
    with pytest.raises(TypeError):
        grouping(["Hello"], cached=[])


def test_uncached_speech_still_groups_without_enabling_cache(
    manager: ManagerFixture,
) -> None:
    """Wyłączona pamięć nie wyłącza łączenia fragmentów wypowiedzi."""
    instance, settings, spoken = manager
    settings.chkCache = False
    calls = []
    instance.translate_openai = lambda key, text, **kwargs: (
        calls.append(text) or "Ustawienia dźwięku"
    )
    instance.speak(["Sound", "settings"])
    assert calls == ["Sound settings"]
    assert settings._translationCache == {}
    assert spoken[0]["speechSequence"] == ["Ustawienia dźwięku"]


@pytest.fixture
def manager() -> ManagerFixture:
    """Tworzy rzeczywisty menedżer z przechwyceniem granicy mowy."""
    module = manager_class()
    spoken = []
    settings = SimpleNamespace(
        choiceOnline=9,
        api_openai=None,
        openai_auth_mode="chatgpt",
        openai_model_oauth="gpt-5.6-sol",
        openai_codex_path="",
        choiceLangDestino_openai="pl",
        choiceLangOrigen="auto",
        chkAltLang=False,
        chkCache=True,
        _translationCache={},
        _enableTranslation=True,
        _lastTranslatedText=None,
        historialOrigen=deque(),
        historialDestino=deque(),
        _nvdaSpeak=lambda **kwargs: spoken.append(kwargs),
    )
    instance = module.GestorTranslate.__new__(module.GestorTranslate)
    instance.frame = SimpleNamespace(gestor_settings=settings)
    return instance, settings, spoken


def test_openai_speech_makes_one_request_and_reuses_cache(
    manager: ManagerFixture,
) -> None:
    """Trzy fragmenty dają jedno żądanie, a powtórka nie daje żadnego."""
    instance, settings, spoken = manager
    calls = []
    instance.translate_openai = lambda key, text, **kwargs: (
        calls.append(text) or "Ustawienia dźwięku, okno, suwak głośności"
    )
    sequence = ["Sound settings", "dialog", "Volume slider"]
    instance.speak(sequence)
    instance.speak(sequence)
    assert calls == ["Sound settings dialog Volume slider"]
    assert len(spoken) == 2
    assert spoken[0] == spoken[1]
    assert len(settings.historialOrigen) == 1


def test_openai_speech_keeps_cached_text_and_command_boundaries(
    manager: ManagerFixture,
) -> None:
    """Dwa nowe fragmenty są łączone, zapisany tekst i komendy zachowane."""
    instance, settings, spoken = manager
    command = object()
    settings._translationCache[instance.get_cache_app_name()] = {"dialog": "okno"}
    calls = []
    instance.translate_openai = lambda key, text, **kwargs: (
        calls.append(text) or "Głośność suwak"
    )
    instance.speak(["dialog", command, "Volume", "slider"])
    assert calls == ["Volume slider"]
    assert spoken[0]["speechSequence"] == ["okno", command, "Głośność suwak"]


def test_disabled_translation_keeps_original_sequence(manager: ManagerFixture) -> None:
    """Wyłączenie tłumaczenia zachowuje oryginalną strukturę mowy."""
    instance, settings, spoken = manager
    settings._enableTranslation = False
    sequence = ["Sound settings", "dialog"]
    instance.speak(sequence)
    assert spoken[0]["speechSequence"] is sequence


def test_other_providers_keep_individual_fragments(manager: ManagerFixture) -> None:
    """Optymalizacja OpenAI nie zmienia drogi innych dostawców."""
    instance, settings, spoken = manager
    settings.choiceOnline = 5
    calls = []
    instance.translate = lambda text: calls.append(text) or text
    instance.speak(["Sound settings", "dialog"])
    assert calls == ["Sound settings", "dialog"]
    assert spoken[0]["speechSequence"] == calls


def test_group_failure_preserves_original_content_and_commands(
    manager: ManagerFixture,
) -> None:
    """Błąd usługi zachowuje słyszalny oryginał bez częściowego wyniku."""
    instance, settings, spoken = manager
    command = object()

    def fail(*args: object, **kwargs: object) -> str:
        raise RuntimeError("prywatna-tresc-nie-moze-byc-odczytana")

    instance.translate_with_options = fail
    instance.speak(["Sound settings", "dialog", command, " "])
    assert spoken[-1]["speechSequence"] == ["Sound settings dialog", command, " "]
    assert "prywatna" not in repr(spoken)
    assert not settings._translationCache[instance.get_cache_app_name()]
