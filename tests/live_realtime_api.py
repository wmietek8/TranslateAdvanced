"""Jawna próba zapisanym kluczem API, bez schowka i bez zmiany ustawień NVDA.

Wysyła najwyżej trzy krótkie teksty testowe. Przy odmowie usługi sprawdza
przerwę w ponawianiu i kończy próbę. Nie zapisuje klucza ani treści błędu serwera.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from nvda_harness import manager_class


def read_api_key(path: Path, index: int) -> str:
    """Odczytuje wskazany klucz bez zmieniania pliku i bez ujawniania zawartości."""
    if type(index) is not int:
        raise TypeError("Indeks klucza musi być liczbą całkowitą.")
    if index < 0 or path.stat().st_size > 1024 * 1024:
        raise ValueError("Niepoprawny indeks lub rozmiar pliku kluczy.")
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("openai") if isinstance(data, dict) else None
    if not isinstance(entries, list) or index >= len(entries):
        raise ValueError("Nie znaleziono wybranego klucza OpenAI.")
    entry = entries[index]
    key = entry.get("key") if isinstance(entry, dict) else None
    if not isinstance(key, str) or not key.strip():
        raise ValueError("Wybrany wpis nie zawiera klucza OpenAI.")
    return key.strip()


def probe(api_file: Path, index: int, model: str) -> dict[str, Any]:
    """Sprawdza rzeczywistą usługę, kierunek mowy, pamięć i reakcję na odmowę."""
    original_digest = hashlib.sha256(api_file.read_bytes()).digest()
    key = read_api_key(api_file, index)
    module = manager_class()
    backend = module.TranslatorOpenAI.translate_openai.__globals__
    request_json = backend["_request_json"]
    codex_call = backend["_codex_call"]
    report: dict[str, Any] = {
        "auth_mode": "api_key",
        "model": model,
        "requests": [],
        "cases": [],
    }

    def request(api_key: str, path: str, body: dict | None = None) -> dict:
        record = {"endpoint": path, "model": body.get("model") if body else None}
        report["requests"].append(record)
        started = time.monotonic()
        try:
            result = request_json(api_key, path, body)
            record["success"] = True
            if isinstance(result, dict) and isinstance(result.get("usage"), dict):
                usage = result["usage"]
                record["tokens"] = {
                    name: usage[name]
                    for name in ("input_tokens", "output_tokens")
                    if type(usage.get(name)) is int
                }
            return result
        except module.TranslationError as error:
            record.update(
                success=False, error=str(error), retry_after=error.retry_after
            )
            raise
        finally:
            record["seconds"] = round(time.monotonic() - started, 3)

    def reject_oauth(*args: object, **kwargs: object) -> None:
        raise AssertionError("Tryb klucza API nie może używać konta ChatGPT.")

    backend["_request_json"] = request
    backend["_codex_call"] = reject_oauth
    spoken: list[dict] = []
    settings = SimpleNamespace(
        choiceOnline=9,
        api_openai=0,
        openai_auth_mode="api_key",
        openai_model_api=model,
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
    manager = module.GestorTranslate.__new__(module.GestorTranslate)
    manager.frame = SimpleNamespace(
        gestor_settings=settings,
        gestor_apis=SimpleNamespace(get_api=lambda *args: {"key": key}),
    )
    try:
        for sources, target in (
            (["The player is waiting near the gate."], "pl"),
            (["Gracz czeka przy bramie."], "en"),
            (["Sound settings", "dialog", "Volume slider"], "pl"),
        ):
            settings.choiceLangDestino_openai = target
            settings._lastTranslatedText = None
            command = object()
            started = time.monotonic()
            manager.speak([*sources, command, " "])
            elapsed = time.monotonic() - started
            sequence = spoken[-1]["speechSequence"]
            assert sequence[1] is command and sequence[2] == " "
            success = settings._lastTranslatedText is not None
            case = {"target": target, "success": success, "seconds": round(elapsed, 3)}
            report["cases"].append(case)
            calls = len(report["requests"])
            if not success:
                assert sequence[0] == " ".join(sources)
                started = time.monotonic()
                manager.speak(["Another test message."])
                case["next_speech_seconds"] = round(time.monotonic() - started, 4)
                case["cooldown_reused"] = len(report["requests"]) == calls
                assert not settings._translationCache.get(manager.get_cache_app_name())
                break
            assert sequence[0] != " ".join(sources)
            case["translation"] = sequence[0]
            manager.speak([*sources, command, " "])
            assert len(report["requests"]) == calls
            assert spoken[-1]["speechSequence"] == sequence
            case["cache_reused"] = True
        report["all_translations_succeeded"] = all(
            case["success"] for case in report["cases"]
        )
        report["oauth_used"] = False
    finally:
        backend["_request_json"] = request_json
        backend["_codex_call"] = codex_call
        report["key_file_unchanged"] = (
            original_digest == hashlib.sha256(api_file.read_bytes()).digest()
        )
        assert report["key_file_unchanged"], (
            "Plik kluczy został zmieniony w trakcie próby."
        )
    return report


def main() -> int:
    """Uruchamia jawną próbę i zapisuje wyłącznie oczyszczony raport."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-file", type=Path, required=True)
    parser.add_argument("--index", type=int, default=0)
    parser.add_argument("--model", default="auto")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = probe(args.api_file, args.index, args.model)
    result = json.dumps(report, ensure_ascii=False, indent=2)
    args.output.write_text(result, encoding="utf-8")
    print(result)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print("Próba nie powiodła się: " + type(error).__name__, file=sys.stderr)
        raise SystemExit(1) from None
