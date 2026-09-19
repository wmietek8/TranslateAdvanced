"""Rozróżnia brak środków, limit żądań i niepoprawny klucz bez ujawniania danych."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest
from test_openai_api import load_backend


@pytest.mark.parametrize(
    "detail",
    [
        {"code": "credit_balance_exhausted", "type": "insufficient_quota"},
        {"code": "insufficient_quota"},
        {"code": "billing_hard_limit_reached"},
        {"type": "insufficient_quota", "code": None},
    ],
)
def test_quota_failure_has_polish_reason_and_cooldown(
    monkeypatch: pytest.MonkeyPatch, detail: dict
) -> None:
    """Znane odmowy rozliczeń dają jasny komunikat i ograniczają ponawianie."""
    backend = load_backend()
    detail["message"] = "tajny-klucz i prywatny-tekst"
    error = urllib.error.HTTPError(
        "https://api.openai.com/v1/responses",
        429,
        "sekret",
        {},
        io.BytesIO(json.dumps({"error": detail}).encode()),
    )

    def fail(*args: object, **kwargs: object) -> None:
        raise error

    monkeypatch.setattr(backend, "_urlopen", fail)
    with pytest.raises(backend.TranslationError) as caught:
        backend.TranslatorOpenAI().translate_openai(
            "klucz-testowy", "Hello", model="gpt-5.6-luna"
        )
    assert "Brak dostępnych środków" in str(caught.value)
    assert "Abonament ChatGPT" in str(caught.value)
    assert "tajny" not in str(caught.value)
    assert "prywatny" not in str(caught.value)
    assert caught.value.retry_after == 60


@pytest.mark.parametrize(
    "raw",
    [b"[]", b"{}", b"null", b"not JSON", b'{"error": []}', b"\xff", b"x" * 65537],
    ids=["lista", "obiekt", "null", "tekst", "blad-lista", "utf8", "za-duze"],
)
def test_invalid_error_body_keeps_generic_reason(
    monkeypatch: pytest.MonkeyPatch, raw: bytes
) -> None:
    """Niepoprawna odpowiedź błędu nie maskuje statusu ani nie wywołuje awarii."""
    backend = load_backend()
    error = urllib.error.HTTPError(
        "https://api.openai.com/v1/responses", 429, "sekret", {}, io.BytesIO(raw)
    )

    def fail(*args: object, **kwargs: object) -> None:
        raise error

    monkeypatch.setattr(backend, "_urlopen", fail)
    with pytest.raises(backend.TranslationError, match="rate limit") as caught:
        backend.TranslatorOpenAI().translate_openai(
            "klucz-testowy", "Hello", model="gpt-5.6-luna"
        )
    assert caught.value.retry_after == 60


@pytest.mark.parametrize(
    "value, expected",
    [
        (True, TypeError),
        ("60", TypeError),
        (-1, ValueError),
        (301, ValueError),
        (float("nan"), ValueError),
        (float("inf"), ValueError),
    ],
)
def test_invalid_cooldown_is_rejected(value: object, expected: type[Exception]) -> None:
    """Metadane błędu mają skończony i ograniczony czas ponawiania."""
    with pytest.raises(expected):
        load_backend().TranslationError("Błąd", retry_after=value)


@pytest.mark.parametrize("value", [0, 0.5, 300])
def test_valid_cooldown_boundaries(value: float) -> None:
    """Zerowa, ułamkowa i maksymalna przerwa zachowują zwykły komunikat."""
    error = load_backend().TranslationError("Błąd", retry_after=value)
    assert str(error) == "Błąd"
    assert error.retry_after == value


def test_arbitrarily_large_cooldown_has_validation_error() -> None:
    """Zbyt duża liczba całkowita nie przepełnia konwersji na float."""
    with pytest.raises(ValueError):
        load_backend().TranslationError("Błąd", retry_after=10**400)


@pytest.mark.parametrize("message", [None, 42, []])
def test_error_message_requires_text(message: object) -> None:
    """Metadane nie zamieniają przypadkowych obiektów w wypowiadany komunikat."""
    with pytest.raises(TypeError):
        load_backend().TranslationError(message)
