"""Jawny pomiar komunikatów gry przez API i rzeczywistą pętlę wxPython.

Wysyła wyłącznie wbudowane teksty syntetyczne. Nie uruchamia syntezatora,
nie odczytuje gry, schowka ani konta ChatGPT i nie zmienia konfiguracji NVDA.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import time
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from nvda_harness import manager_class

SAMPLES = (
    "Inventory",
    "Collect 12 branches and bring them to the camp before sunset.",
    "A player has joined the server. Your shelter has been repaired.",
)


def probe(api_file: Path, provider: int, model: str, repetitions: int = 2) -> dict[str, Any]:
    """Mierzy czas oddania sterowania, wynik i pamięć dla wybranej usługi."""
    if provider not in (5, 9) or type(repetitions) is not int or not 1 <= repetitions <= 3:
        raise ValueError("Niepoprawny silnik albo liczba powtórzeń.")
    import wx

    app = wx.App.Get() or wx.App(False)
    original = hashlib.sha256(api_file.read_bytes()).digest()
    entries = json.loads(api_file.read_text(encoding="utf-8"))
    service = "openai" if provider == 9 else "deepL_pro"
    key = entries[service][0]["key"]
    module = manager_class()
    owner = threading.get_ident()
    spoken = []

    def speak(**kwargs: Any) -> None:
        assert threading.get_ident() == owner
        spoken.append((time.perf_counter(), kwargs["speechSequence"]))

    settings = SimpleNamespace(
        choiceOnline=provider, api_openai=0, api_deepl_pro=0,
        openai_auth_mode="api_key", openai_model_api=model, openai_codex_path="",
        choiceLangDestino_openai="pl", choiceLangDestino_deepl="pl",
        choiceLangOrigen="auto", chkAltLang=False, chkCache=True,
        _translationCache={}, _enableTranslation=True, _lastTranslatedText=None,
        historialOrigen=deque(), historialDestino=deque(), _nvdaSpeak=speak,
    )
    manager = module.GestorTranslate.__new__(module.GestorTranslate)
    manager.frame = SimpleNamespace(
        gestor_settings=settings,
        gestor_apis=SimpleNamespace(get_api=lambda *args: {"key": key}),
    )
    manager.enable_speech_queue(wx.CallAfter)
    report: dict[str, Any] = {"provider": provider, "model": model, "cases": []}

    def wait_for(count: int) -> None:
        deadline = time.monotonic() + 60
        while len(spoken) < count:
            app.Yield()
            if time.monotonic() > deadline:
                raise TimeoutError("Nie nadeszło tłumaczenie w czasie próby.")
            time.sleep(0.001)

    try:
        for source in SAMPLES * repetitions:
            settings._translationCache.clear()
            settings._lastTranslatedText = None
            spoken.clear()
            command = object()
            started = time.perf_counter()
            manager.speak([source, command, " "])
            returned = time.perf_counter() - started
            wait_for(1)
            completed, sequence = spoken[0]
            assert len(spoken) == 1 and settings._lastTranslatedText is not None
            assert sequence[0] != source and sequence[1] is command and sequence[2] == " "
            started_cache = time.perf_counter()
            manager.speak([source, command, " "])
            assert len(spoken) == 2 and spoken[-1][1] == sequence
            row = {"source": source, "translation": sequence[0],
                   "return_ms": round(returned * 1000, 3),
                   "translation_seconds": round(completed - started, 3),
                   "cached_ms": round((time.perf_counter() - started_cache) * 1000, 3)}
            report["cases"].append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
        settings._translationCache.clear()
        spoken.clear()
        started = time.perf_counter()
        for source in SAMPLES:
            manager.speak([source])
        report["burst_return_ms"] = round((time.perf_counter() - started) * 1000, 3)
        wait_for(3)
        assert len(spoken) == 3 and all(item[1][0] != source for item, source in zip(spoken, SAMPLES))
        report["burst_translations"] = [item[1][0] for item in spoken]
        report["burst_complete_seconds"] = round(spoken[-1][0] - started, 3)
        report["main_thread_delivery"] = True
    finally:
        manager.close_speech_queue()
        report["key_file_unchanged"] = original == hashlib.sha256(api_file.read_bytes()).digest()
        assert report["key_file_unchanged"]
    return report


def main() -> int:
    """Zapisuje oczyszczony raport rzeczywistego pomiaru wybranej usługi."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-file", type=Path, required=True)
    parser.add_argument("--provider", type=int, choices=(5, 9), required=True)
    parser.add_argument("--model", default="gpt-5.6-terra")
    parser.add_argument("--repetitions", type=int, choices=(1, 2, 3), default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = probe(args.api_file, args.provider, args.model, args.repetitions)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print("Próba nie powiodła się: " + type(error).__name__, file=sys.stderr)
        raise SystemExit(1) from None
