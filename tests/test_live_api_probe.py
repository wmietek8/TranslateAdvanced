"""Weryfikuje skrypt jawnej próby bez użycia prawdziwego konta lub klucza."""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path

import live_realtime_api as live
import pytest
from nvda_harness import manager_class
from test_openai_api import completed_response, http_response


def _key_file(tmp_path: Path, data: object) -> Path:
    path = tmp_path / "apis.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_read_key_strips_whitespace_without_changing_file(tmp_path: Path) -> None:
    """Odczyt pozostawia oryginalny zapis bajt po bajcie."""
    path = _key_file(tmp_path, {"openai": [{"key": "  test-secret  "}]})
    original = path.read_bytes()
    assert live.read_api_key(path, 0) == "test-secret"
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "data,index",
    [
        ({}, 0),
        ([], 0),
        ({"openai": []}, 0),
        ({"openai": [{"key": ""}]}, 0),
        ({"openai": [{"key": "k"}]}, 1),
        ({"openai": [None]}, 0),
        ({"openai": [{"key": 1}]}, 0),
        ({}, -1),
    ],
)
def test_invalid_saved_key_is_rejected(
    tmp_path: Path, data: object, index: int
) -> None:
    """Brak klucza i uszkodzone dane mają przewidywalny błąd walidacji."""
    with pytest.raises(ValueError):
        live.read_api_key(_key_file(tmp_path, data), index)


@pytest.mark.parametrize("index", [True, "0", None])
def test_invalid_key_index_type(tmp_path: Path, index: object) -> None:
    """Indeks nie dopuszcza wartości logicznych ani konwersji ze znaków."""
    with pytest.raises(TypeError):
        live.read_api_key(_key_file(tmp_path, {}), index)


def test_probe_checks_translations_and_local_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scenariusz sukcesu sprawdza oba kierunki i grupowanie trzech etykiet."""
    module = manager_class()
    backend = module.TranslatorOpenAI.translate_openai.__globals__

    def transport(request, **kwargs):
        body = json.loads(request.data)
        target = body["text"]["format"]["schema"]["properties"]["target_language"][
            "enum"
        ][0]
        return http_response(
            completed_response(
                "Przekład" if target == "pl" else "Translation", target=target
            )
        )

    monkeypatch.setitem(backend, "_urlopen", transport)
    monkeypatch.setattr(live, "manager_class", lambda: module)
    path = _key_file(tmp_path, {"openai": [{"key": "test-secret"}]})
    report = live.probe(path, 0, "gpt-5.6-luna")
    assert report["all_translations_succeeded"]
    assert len(report["requests"]) == 3
    assert all(case["cache_reused"] for case in report["cases"])
    assert "test-secret" not in json.dumps(report)


def test_probe_handles_quota_failure_without_repeated_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Odmowa salda daje raport lokalny bez sekretów i bez ponawiania mowy."""
    module = manager_class()
    backend = module.TranslatorOpenAI.translate_openai.__globals__

    def transport(request, **kwargs):
        raise urllib.error.HTTPError(
            request.full_url,
            429,
            "test-secret",
            {},
            io.BytesIO(b'{"error":{"code":"credit_balance_exhausted"}}'),
        )

    monkeypatch.setitem(backend, "_urlopen", transport)
    monkeypatch.setattr(live, "manager_class", lambda: module)
    report = live.probe(
        _key_file(tmp_path, {"openai": [{"key": "test-secret"}]}), 0, "gpt-5.6-luna"
    )
    assert not report["all_translations_succeeded"]
    assert len(report["requests"]) == 1
    assert report["cases"][0]["cooldown_reused"]
    assert report["key_file_unchanged"]
    assert "test-secret" not in json.dumps(report)
