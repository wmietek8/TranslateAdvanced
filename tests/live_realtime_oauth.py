"""Jawna próba tłumaczenia wypowiedzi na rzeczywistym koncie dodatku.

Używa syntetycznego tekstu i kopii samego dostępu. Nie odświeża tokenu,
nie uruchamia NVDA i nie dotyka schowka. Mowę przechwytuje na granicy NVDA.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
import tempfile
import time
import types
from collections import deque
from pathlib import Path

from nvda_harness import APP, manager_class


def main() -> int:
    """Sprawdza pełną drogę mowy i zapisuje raport bez danych konta."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auth-file", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", default="gpt-5.6-sol")
    args = parser.parse_args()
    auth_path = Path(args.auth_file)
    raw = auth_path.read_bytes()
    original_digest = hashlib.sha256(raw).digest()
    auth = json.loads(raw)
    access_only = {
        "auth_mode": "chatgpt", "OPENAI_API_KEY": None,
        "last_refresh": auth.get("last_refresh"),
        "tokens": {name: auth["tokens"][name]
                   for name in ("access_token", "id_token", "account_id")},
    }
    access_only["tokens"]["refresh_token"] = ""
    del raw, auth
    module = manager_class()
    root = module.__name__.split(".managers.")[0]
    for name, path in ((root, APP), (root + ".utils", APP / "utils")):
        package = types.ModuleType(name)
        package.__path__ = [str(path)]
        sys.modules[name] = package
    codex = importlib.import_module(root + ".utils.utils_codex")
    report = {"cases": [], "rpc_methods": [], "refresh_token_copied": False,
              "running_nvda_modified": False, "clipboard_accessed": False}
    try:
        with tempfile.TemporaryDirectory(prefix="ta-realtime-") as directory:
            home = Path(directory) / "TranslateAdvanced" / "codex"
            client = codex.get_client(str(home))
            client._prepare_home()
            (home / "auth.json").write_text(json.dumps(access_only), encoding="utf-8")
            del access_only
            actual_rpc = client._rpc

            def tracked_rpc(method: str, params: dict | None = None, **kwargs):
                assert method not in ("thread/start", "turn/start", "command/exec")
                assert not (method == "account/read" and (params or {}).get("refreshToken"))
                report["rpc_methods"].append(method)
                return actual_rpc(method, params, **kwargs)

            client._rpc = tracked_rpc
            module.globalVars.appArgs.configPath = directory
            spoken = []
            settings = types.SimpleNamespace(
                choiceOnline=9, api_openai=None, openai_auth_mode="chatgpt",
                openai_model_oauth=args.model, openai_codex_path="",
                choiceLangDestino_openai="pl", choiceLangOrigen="auto",
                chkAltLang=False, chkCache=True, _translationCache={},
                _enableTranslation=True, _lastTranslatedText=None,
                historialOrigen=deque(), historialDestino=deque(),
                _nvdaSpeak=lambda **kwargs: spoken.append(kwargs),
            )
            manager = module.GestorTranslate.__new__(module.GestorTranslate)
            manager.frame = types.SimpleNamespace(gestor_settings=settings)
            for source, target in (("The player is waiting near the gate.", "pl"),
                                   ("Gracz czeka przy bramie.", "en")):
                spoken.clear()
                command = object()
                settings.choiceLangDestino_openai = target
                started = time.monotonic()
                manager.speak([source, command, " "], priority=None)
                seconds = time.monotonic() - started
                assert len(spoken) == 1, "Tłumaczenie zgłosiło błąd."
                sequence = spoken[0]["speechSequence"]
                assert sequence[0].strip() and sequence[0] != source
                assert sequence[1] is command and sequence[2] == " "
                assert settings._lastTranslatedText.strip() == sequence[0].strip()
                calls = len(report["rpc_methods"])
                manager.speak([source, command, " "], priority=None)
                assert len(report["rpc_methods"]) == calls
                assert spoken[-1]["speechSequence"] == sequence
                report["cases"].append({"target": target, "model": args.model,
                                        "translation": sequence[0], "seconds": round(seconds, 3),
                                        "speech_commands_preserved": True, "cache_reused": True})
            codex.close_clients()
            restarted = codex.get_client(str(home))
            actual_rpc = restarted._rpc
            restarted._rpc = tracked_rpc
            before = report["rpc_methods"].count("model/list")
            assert restarted.cached_models()
            assert (home / "translateadvanced-models.json").is_file()
            report["catalog_survived_restart"] = True
            assert report["rpc_methods"].count("model/list") == before
            codex.close_clients()
    finally:
        codex.close_clients()
        report["original_auth_unchanged"] = original_digest == hashlib.sha256(auth_path.read_bytes()).digest()
        assert report["original_auth_unchanged"]
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, RuntimeError, AssertionError) as error:
        print("Próba nie powiodła się: " + type(error).__name__, file=sys.stderr)
        raise SystemExit(1) from None
