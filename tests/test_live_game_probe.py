"""Sprawdzenie narzędzia pomiarowego bez kluczy i bez prawdziwej sieci."""

from __future__ import annotations

import json
import queue
import sys
from pathlib import Path
from types import SimpleNamespace

import live_game_latency
import pytest
from nvda_harness import manager_class


@pytest.mark.parametrize("provider,repetitions", [(0, 1), (5, 0), (9, 4), (9, True)])
def test_invalid_probe_arguments(tmp_path: Path, provider: int, repetitions: int) -> None:
    """Błędne parametry są odrzucane przed odczytaniem klucza."""
    with pytest.raises(ValueError):
        live_game_latency.probe(tmp_path / "nie-istnieje", provider, "gpt-5.6-terra", repetitions)


@pytest.mark.parametrize("provider", [5, 9])
def test_probe_checks_async_delivery_cache_burst_and_file_integrity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: int,
) -> None:
    """Raport sprawdza prawdziwy menedżer i kolejkę z kontrolowaną granicą HTTP."""
    events = queue.Queue()

    def dispatch() -> None:
        while not events.empty():
            events.get_nowait()()

    app = SimpleNamespace(Yield=dispatch)
    wx = SimpleNamespace(App=SimpleNamespace(Get=lambda: app), CallAfter=events.put)
    monkeypatch.setitem(sys.modules, "wx", wx)
    module = manager_class()
    monkeypatch.setattr(module.GestorTranslate, "translate_with_options",
                        lambda self, text, options: "Tłumaczenie: " + text)
    monkeypatch.setattr(live_game_latency, "manager_class", lambda: module)
    path = tmp_path / "apis.json"
    path.write_text(json.dumps({name: [{"key": "tylko-test"}] for name in ("openai", "deepL_pro")}), "utf-8")
    report = live_game_latency.probe(path, provider, "gpt-5.6-terra", 1)
    assert report["key_file_unchanged"] and report["main_thread_delivery"]
    assert len(report["cases"]) == 3 and len(report["burst_translations"]) == 3
    assert "tylko-test" not in json.dumps(report)
