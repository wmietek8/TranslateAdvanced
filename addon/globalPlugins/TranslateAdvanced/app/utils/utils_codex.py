"""Isolated, managed Codex OAuth over an owned stdio app-server.

The installed app-server has no hard all-tools disable switch. Shell feature
flags and read-only sandboxing still leave builtins registered. Therefore this
module NEVER sends source text to an agent thread/turn. The official CLI handles
login, refresh and model discovery; utils_codex_response sends pure HTTPS
inference with tools=[], tool_choice=none, no history and no execution loop.
That internal Codex endpoint is not a public API compatibility contract.

Account protocol: https://learn.chatgpt.com/docs/app-server
Source audit: https://github.com/openai/codex/tree/rust-v0.155.0/codex-rs
Only stdlib is used, so the module is independently testable outside NVDA.
"""
import hashlib
import json
import math
import os
import platform
import re
import shutil
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from . import utils_codex_response as responses
from .utils_codex_response import CodexError

_MARKER_NAME = ".translateadvanced-managed"
_MARKER = "TranslateAdvanced Codex OAuth storage v1\n"
_MAX_LINE = 1024 * 1024
_ALLOWED_METHODS = frozenset({
    "initialize", "account/read", "account/login/start", "account/login/cancel",
    "account/logout", "model/list",
})
# These are defense in depth for AUTH/METADATA ONLY, not a tool sandbox.
# Values/flags were checked against the installed release's config schema.
_CONFIG_OVERRIDES = (
    'model_provider="openai"',
    'cli_auth_credentials_store="file"',
    'forced_login_method="chatgpt"',
    'chatgpt_base_url="https://chatgpt.com/backend-api/"',
    'sandbox_mode="read-only"',
    'approval_policy="never"',
    'web_search="disabled"',
    'mcp_servers={}',
    'notify=[]',
    'history.persistence="none"',
    'analytics.enabled=false',
    'otel.exporter="none"',
    'otel.trace_exporter="none"',
    'otel.metrics_exporter="none"',
    'otel.log_user_prompt=false',
    'project_doc_max_bytes=0',
    'skills.include_instructions=false',
    'skills.bundled.enabled=false',
    'tools.update_plan.enabled=false',
    'features.skip_host_skill_discovery=true',
) + tuple('features.' + name + '=false' for name in (
    'shell_tool', 'shell_snapshot', 'shell_snapshot_v2', 'shell_zsh_fork',
    'apply_patch_freeform', 'apps', 'connectors', 'plugins', 'remote_plugin',
    'recommended_plugins', 'hooks', 'codex_hooks', 'plugin_hooks',
    'external_agent_memory_import', 'external_migration', 'memories', 'memory_tool',
    'skill_mcp_dependency_install', 'skill_env_var_dependency_prompt', 'skill_search',
    'browser_use', 'browser_use_external', 'computer_use', 'image_generation',
    'imagegenext', 'view_image', 'js_repl', 'code_mode', 'code_mode_only',
    'code_mode_prewarm', 'multi_agent', 'multi_agent_v2', 'collab', 'enable_fanout',
    'request_permissions', 'request_permissions_tool', 'remote_control',
    'web_search', 'web_search_request', 'web_search_cached', 'standalone_web_search',
    'tool_search', 'tool_suggest', 'respect_system_proxy',
))


def resolve_codex_executable(codex_path=""):
    """Resolve a native EXE, including npm's shim, without executing the shim."""
    try:
        value = codex_path
        if not value:
            value = shutil.which("codex.exe") or shutil.which("codex")
            if not value:
                value = str(Path(os.environ.get("APPDATA", "")) / "npm/codex.CMD")
        path = Path(value)
        if not path.is_absolute() or not path.is_file():
            raise ValueError()
        if path.name.lower() == "codex.exe":
            return str(path.resolve())
        if path.name.lower() not in ("codex.cmd", "codex.ps1", "codex"):
            raise ValueError()
        arm = platform.machine().lower() in ("arm64", "aarch64")
        arch = "arm64" if arm else "x64"
        triple = "aarch64-pc-windows-msvc" if arm else "x86_64-pc-windows-msvc"
        package = path.parent / "node_modules/@openai/codex"
        candidates = (
            package / ("node_modules/@openai/codex-win32-" + arch) / "vendor" / triple / "bin/codex.exe",
            path.parent / ("node_modules/@openai/codex-win32-" + arch) / "vendor" / triple / "bin/codex.exe",
            package / "vendor" / triple / "bin/codex.exe",
        )
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate.resolve())
    except (OSError, ValueError, TypeError):
        pass
    raise CodexError("Native Codex executable not found. Install the official Codex CLI or select codex.exe (not a command line).") from None


def _safe_string(value, limit=512):
    return isinstance(value, str) and 0 < len(value) <= limit and not any(ord(c) < 32 for c in value)


def _timeout(value, maximum=300):
    try:
        value = float(value)
        if not math.isfinite(value) or value <= 0 or value > maximum:
            raise ValueError()
        return value
    except (TypeError, ValueError, OverflowError):
        raise CodexError("Invalid Codex timeout.") from None


class CodexClient:
    """Lazy client; only start_login initiates the official OAuth listener.

    The supplied home must be a new/previously bridge-owned directory. Never
    pass ~/.codex or copy any other client's credentials into it. Codex owns
    persistence, callback handling, refresh and revocation. The pure inference
    transport reads only the access token from this dedicated managed home.
    """

    def __init__(self, codex_home, codex_path="", timeout=30):
        self._home_value = codex_home
        self._path_value = codex_path
        self._timeout = _timeout(timeout)
        self._op_lock = threading.RLock()
        self._wire_lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._state = threading.Condition(threading.RLock())
        self._closed = False
        self._closing = False
        self._broken = False
        self._process = None
        self._runtime = None
        self._readers = []
        self._next_id = 0
        self._pending = {}
        self._login_results = {}
        self._known_logins = set()
        self._active_login = None
        self._http_cancel = threading.Event()
        self._model_cache = None

    @property
    def closed(self):
        with self._state:
            return self._closed or self._closing or self._broken

    @contextmanager
    def _operation(self):
        if not self._op_lock.acquire(timeout=self._timeout):
            raise CodexError("Codex operation timed out while waiting for another request.")
        try:
            if self.closed:
                raise CodexError("Codex client is closed. Reconnect to try again.")
            yield
        finally:
            self._op_lock.release()

    def _prepare_home(self):
        try:
            raw = Path(self._home_value)
            if not raw.is_absolute() or raw.is_symlink():
                raise ValueError()
            home = raw.resolve()
            personal = (Path.home() / ".codex").resolve()
            if home == personal or home in personal.parents or personal in home.parents:
                raise ValueError()
            marker = home / _MARKER_NAME
            if home.exists() and any(home.iterdir()):
                if marker.is_symlink() or not marker.is_file() or marker.stat().st_size > 100:
                    raise ValueError()
                if marker.read_text(encoding="utf-8") != _MARKER:
                    raise ValueError()
            # Do not merge provider overrides, MCP definitions, or credential symlinks.
            if (home / "config.toml").exists() or (home / "config.toml").is_symlink() or (home / "auth.json").is_symlink():
                raise ValueError()
            home.mkdir(parents=True, exist_ok=True)
            if not marker.exists():
                with marker.open("x", encoding="utf-8") as stream:
                    stream.write(_MARKER)
            return home
        except (OSError, ValueError, TypeError):
            raise CodexError("Use a fresh, dedicated TranslateAdvanced Codex home without custom config or shared credentials; never use your personal .codex directory.") from None

    def _environment(self, home, root, executable):
        # Allowlist, not a blacklist: removes all provider URLs/keys, proxy,
        # loader-injection, logging and inherited Codex auth/config variables.
        env = {}
        for key in ("SYSTEMROOT", "WINDIR", "SYSTEMDRIVE"):
            if os.environ.get(key):
                env[key] = os.environ[key]
        for name in ("profile", "appdata", "localappdata", "tmp"):
            (root / name).mkdir()
        profile = str(root / "profile")
        env.update({
            "CODEX_HOME": str(home), "HOME": profile, "USERPROFILE": profile,
            "APPDATA": str(root / "appdata"), "LOCALAPPDATA": str(root / "localappdata"),
            "TEMP": str(root / "tmp"), "TMP": str(root / "tmp"),
            "XDG_CONFIG_HOME": str(root / "appdata"),
            "XDG_DATA_HOME": str(root / "localappdata"),
            "XDG_CACHE_HOME": str(root / "tmp"),
            "RUST_LOG": "off", "NO_COLOR": "1",
        })
        paths = [str(Path(executable).parent)]
        if env.get("SYSTEMROOT"):
            paths.append(str(Path(env["SYSTEMROOT"]) / "System32"))
        env["PATH"] = os.pathsep.join(paths)
        return env

    def _ensure_started(self):
        if self.closed:
            raise CodexError("Codex client is closed. Reconnect to try again.")
        if self._process is not None:
            return
        home = self._prepare_home()
        executable = resolve_codex_executable(self._path_value)
        try:
            self._runtime = tempfile.TemporaryDirectory(prefix="translateadvanced-codex-")
            root = Path(self._runtime.name)
            cwd = root / "empty"
            cwd.mkdir()
            env = self._environment(home, root, executable)
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            version = subprocess.run(
                [executable, "--version"], stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                env=env, cwd=str(cwd), shell=False, text=True, encoding="utf-8",
                errors="replace", timeout=min(self._timeout, 10), creationflags=flags,
            )
            if version.returncode or not re.fullmatch(r"codex-cli [0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?", version.stdout.strip()):
                raise CodexError("The selected executable is not a recognized official Codex CLI. Check the installation.")
            args = [executable, "app-server", "--listen", "stdio://"]
            for override in _CONFIG_OVERRIDES:
                args.extend(["-c", override])
            with self._state:
                if self.closed:
                    raise CodexError("Codex client is closed.")
                self._process = subprocess.Popen(
                    args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    cwd=str(cwd), env=env, shell=False, text=True, encoding="utf-8",
                    errors="replace", bufsize=1, creationflags=flags, close_fds=True,
                )
            for target, name in ((self._read_stdout, "codex-stdio"), (self._drain_stderr, "codex-stderr")):
                thread = threading.Thread(target=target, name=name, daemon=True)
                self._readers.append(thread)
                thread.start()
            self._rpc("initialize", {
                "clientInfo": {"name": "translateadvanced", "title": "TranslateAdvanced", "version": "1.0"},
                "capabilities": {"experimentalApi": False},
            })
            self._write({"method": "initialized"})
        except CodexError:
            self.close()
            raise
        except (OSError, ValueError, subprocess.SubprocessError):
            self.close()
            raise CodexError("Could not start the isolated Codex app-server. Check the official CLI installation.") from None

    def _write(self, message):
        try:
            data = json.dumps(message, ensure_ascii=True, separators=(",", ":")) + "\n"
            with self._wire_lock:
                process = self._process
                if process is None or process.poll() is not None:
                    raise OSError()
                process.stdin.write(data)
                process.stdin.flush()
        except (OSError, ValueError, TypeError):
            raise CodexError("Codex connection closed unexpectedly.") from None

    def _rpc(self, method, params=None, timeout=None, closing=False):
        # No generic public RPC escape hatch: especially no thread/turn/exec/fs.
        if method not in _ALLOWED_METHODS:
            raise CodexError("This Codex operation is disabled for safety.")
        with self._state:
            if self._broken or self._closed or (self._closing and not closing):
                raise CodexError("Codex client is closed.")
            self._next_id += 1
            request_id = self._next_id
            holder = {"event": threading.Event(), "result": None, "failed": False}
            self._pending[request_id] = holder
        try:
            self._write({"id": request_id, "method": method, "params": {} if params is None else params})
            if not holder["event"].wait(self._timeout if timeout is None else timeout):
                self._abort()
                raise CodexError("Codex request timed out. Reconnect and try again.")
            if holder["failed"] or not isinstance(holder["result"], dict):
                raise CodexError("Codex request failed. Check sign-in status or reconnect; private server details were withheld.")
            return holder["result"]
        finally:
            with self._state:
                self._pending.pop(request_id, None)

    def _read_stdout(self):
        try:
            while True:
                line = self._process.stdout.readline(_MAX_LINE + 1)
                if not line or len(line) > _MAX_LINE or not line.endswith("\n"):
                    break
                message = json.loads(line)
                if not isinstance(message, dict):
                    break
                if "method" in message and "id" in message:
                    # Reject every server-initiated request, including approvals,
                    # tools, elicitation, and externally managed token refresh.
                    self._write({"id": message["id"], "error": {
                        "code": -32601, "message": "Client-side execution is disabled.",
                    }})
                    break
                if "id" in message:
                    request_id = message["id"]
                    if type(request_id) is not int:
                        break
                    with self._state:
                        holder = self._pending.get(request_id)
                        if holder is not None:
                            holder["failed"] = "error" in message
                            holder["result"] = message.get("result")
                            holder["event"].set()
                elif message.get("method") == "account/login/completed":
                    params = message.get("params")
                    if not isinstance(params, dict):
                        break
                    login_id = params.get("loginId")
                    if _safe_string(login_id, 256):
                        with self._state:
                            self._model_cache = None
                            if len(self._login_results) >= 16:
                                self._login_results.pop(next(iter(self._login_results)))
                            self._login_results[login_id] = params.get("success") is True
                            if self._active_login == login_id:
                                self._active_login = None
                            self._state.notify_all()
                elif message.get("method") == "account/updated":
                    with self._state:
                        self._model_cache = None
                # Other notifications are deliberately discarded, never logged.
        except (OSError, ValueError, TypeError, CodexError):
            pass
        finally:
            self._abort()

    def _drain_stderr(self):
        try:
            while self._process.stderr.read(4096):
                pass  # Drain to prevent pipe deadlock; never retain or log it.
        except (OSError, ValueError):
            pass

    def _stop_owned_process(self):
        process = self._process
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait(timeout=1)
            except (OSError, subprocess.SubprocessError):
                pass
        except OSError:
            pass

    def _abort(self):
        with self._state:
            self._broken = True
            self._http_cancel.set()
            self._model_cache = None
            self._state.notify_all()
        self._stop_owned_process()
        with self._state:
            for holder in self._pending.values():
                holder["failed"] = True
                holder["event"].set()

    def account(self):
        """Return {} or only type/email. No auth.json access or token refresh."""
        with self._operation():
            self._ensure_started()
            result = self._rpc("account/read", {"refreshToken": False})
            value = result.get("account")
            if value is None:
                return {}
            if not isinstance(value, dict) or value.get("type") not in ("chatgpt", "apiKey", "amazonBedrock"):
                raise CodexError("Codex returned an unsupported account type.")
            safe = {"type": value["type"]}
            email = value.get("email")
            if value["type"] == "chatgpt" and _safe_string(email, 320) and re.fullmatch(r"[^\s@]+@[^\s@]+", email):
                safe["email"] = email
            return safe

    def list_models(self):
        """Full, deduplicated text-model catalog; not proof of entitlement/cost."""
        with self._operation():
            account = self.account()
            if account.get("type") != "chatgpt":
                raise CodexError("Sign in to ChatGPT before loading Codex models.")
            cache_key = self._catalog_key(account)
            deadline = time.monotonic() + self._timeout
            cursor, seen_cursors, models = None, set(), {}
            for _ in range(100):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CodexError("Codex model listing timed out; no partial catalog was returned.")
                result = self._rpc("model/list", {"cursor": cursor, "limit": 100, "includeHidden": False}, timeout=remaining)
                entries = result.get("data")
                if not isinstance(entries, list) or len(entries) > 10000:
                    raise CodexError("Codex returned an invalid model catalog.")
                for entry in entries:
                    if not isinstance(entry, dict) or not _safe_string(entry.get("id"), 256):
                        raise CodexError("Codex returned an invalid model catalog.")
                    modalities = entry.get("inputModalities", ["text"])
                    if not isinstance(modalities, list) or not all(isinstance(item, str) for item in modalities):
                        raise CodexError("Codex returned invalid model capabilities.")
                    if not entry.get("hidden", False) and "text" in modalities:
                        models[entry["id"]] = None
                cursor = result.get("nextCursor")
                if cursor is None:
                    result_models = list(models)
                    with self._state:
                        self._model_cache = (time.monotonic(), cache_key, tuple(result_models))
                    self._store_model_catalog(cache_key, result_models)
                    return result_models
                if not _safe_string(cursor, 4096) or cursor in seen_cursors:
                    raise CodexError("Codex returned invalid model pagination; no partial catalog was returned.")
                seen_cursors.add(cursor)
            raise CodexError("Codex model catalog exceeded the safe pagination limit.")

    def _catalog_key(self, account):
        try:
            tokens = responses._managed_auth(self._home_value)["tokens"]
            return (account.get("type"), account.get("email"), tokens["account_id"])
        except CodexError:
            # Uszkodzone dane nigdy nie pasują do katalogu poprawnego konta.
            pass
        try:
            info = (Path(self._home_value) / "auth.json").stat()
            stamp = (info.st_mtime_ns, info.st_size, info.st_ino)
        except OSError:
            stamp = None
        return (account.get("type"), account.get("email"), stamp)

    def _model_catalog_path(self) -> Path:
        return self._prepare_home() / "translateadvanced-models.json"

    @staticmethod
    def _catalog_fingerprint(key: tuple) -> str:
        return hashlib.sha256(repr(key).encode("utf-8")).hexdigest()

    def _load_model_catalog(self, key: tuple) -> list[str] | None:
        try:
            path = self._model_catalog_path()
            if path.is_symlink() or path.stat().st_size > 262144:
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
            if (not isinstance(data, dict) or data.get("version") != 1
                    or data.get("account") != self._catalog_fingerprint(key)):
                return None
            models = data.get("models")
            if (not isinstance(models, list) or len(models) > 10000
                    or any(not isinstance(model, str)
                           or not responses._MODEL.fullmatch(model) for model in models)):
                return None
            return list(dict.fromkeys(models))
        except (OSError, ValueError, UnicodeError, RecursionError):
            return None

    def _store_model_catalog(self, key: tuple, models: list[str]) -> None:
        temporary = None
        try:
            path = self._model_catalog_path()
            if path.is_symlink():
                return
            data = {"version": 1, "account": self._catalog_fingerprint(key), "models": models}
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                prefix=".models-", suffix=".tmp", delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump(data, stream, ensure_ascii=True)
            os.replace(temporary, path)
        except OSError:
            # Brak zapisu pamięci podręcznej nie unieważnia pobranej listy.
            pass
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def _clear_model_catalog(self) -> None:
        with self._state:
            self._model_cache = None
        try:
            self._model_catalog_path().unlink(missing_ok=True)
        except OSError:
            pass

    def cached_models(self) -> list[str]:
        """Zwraca zapamiętane modele konta; pobiera je przy braku katalogu."""
        with self._operation():
            return self._catalog_for_translation()

    def _catalog_for_translation(self):
        account = self.account()  # Cheap local check; never refreshes credentials.
        if account.get("type") != "chatgpt":
            self._clear_model_catalog()
            raise CodexError("Sign in to ChatGPT before translating.")
        key = self._catalog_key(account)
        with self._state:
            cache = self._model_cache
            if cache and cache[1] == key:
                return list(cache[2])
        stored = self._load_model_catalog(key)
        if stored is not None:
            with self._state:
                self._model_cache = (time.monotonic(), key, tuple(stored))
            return stored
        return self.list_models()  # Public refresh always enumerates live pages.

    def translate(self, text, target_language, alternate_language=None, source_language="auto", model="auto"):
        """Literal translation, never an agent turn. Explicit ids never fallback."""
        # Validate input before any process, model lookup, or credential read.
        responses.validate_request(text, target_language, alternate_language, source_language, model)
        with self._operation():
            if not text:
                return ""
            selected = responses.select_model(model, self._catalog_for_translation())
            home = self._prepare_home()
            if responses.needs_refresh(home):
                # 0.155.0 refreshToken=True asks the authority to refresh; it is
                # NOT a cheap refresh-if-needed switch. Never call on every read.
                refreshed = self._rpc("account/read", {"refreshToken": True}).get("account")
                if not isinstance(refreshed, dict) or refreshed.get("type") != "chatgpt":
                    raise CodexError("Codex session could not be refreshed. Sign in again.")
                if responses.needs_refresh(home):
                    raise CodexError("Codex session could not be refreshed. Sign in again.")
            return responses.translate_response(
                home, text, target_language, alternate_language=alternate_language,
                source_language=source_language, model=selected, timeout=self._timeout,
                cancel_event=self._http_cancel,
            )

    def start_login(self):
        """Start official CLI-managed ChatGPT OAuth; caller may open authUrl.

        Call only on an explicit user action. The bridge itself opens no browser.
        The returned URL is sensitive transient state: do not log/persist it.
        """
        with self._operation():
            self._ensure_started()
            if self._active_login is not None:
                self.cancel_login(self._active_login)
            result = self._rpc("account/login/start", {
                "type": "chatgpt", "codexStreamlinedLogin": False,
                "useHostedLoginSuccessPage": True, "appBrand": "chatgpt",
            })
            login_id, url = result.get("loginId"), result.get("authUrl")
            try:
                parts = urlsplit(url) if isinstance(url, str) else None
                valid = (result.get("type") == "chatgpt" and _safe_string(login_id, 256)
                         and _safe_string(url, 16384) and parts.scheme == "https"
                         and parts.netloc.lower() in (
                             "auth.openai.com", "auth.openai.com:443",
                             "chatgpt.com", "chatgpt.com:443",
                         ) and "\\" not in url and not any(ord(char) <= 32 or ord(char) == 127 for char in url)
                         and parts.username is None and parts.password is None)
            except ValueError:
                valid = False
            if not valid:
                self.close()  # Also tears down any malformed/pending OAuth flow.
                raise CodexError("Codex returned an invalid official sign-in response.")
            with self._state:
                if self.closed:
                    raise CodexError("Codex client is closed.")
                self._known_logins.add(login_id)
                if login_id not in self._login_results:
                    self._active_login = login_id
            return {"loginId": login_id, "authUrl": url}

    def cancel_login(self, login_id):
        with self._operation():
            if not _safe_string(login_id, 256) or login_id not in self._known_logins:
                raise CodexError("Unknown Codex sign-in request.")
            result = self._rpc("account/login/cancel", {"loginId": login_id})
            if result.get("status") not in ("canceled", "notFound"):
                self.close()
                raise CodexError("Could not confirm cancellation of Codex sign-in.")
            with self._state:
                self._login_results[login_id] = False
                if self._active_login == login_id:
                    self._active_login = None
                self._state.notify_all()

    def wait_login(self, login_id, timeout=120):
        timeout = _timeout(timeout, maximum=600)
        deadline = time.monotonic() + timeout
        # Do not hold _op_lock while waiting: cancel/logout/close must work.
        with self._state:
            if not _safe_string(login_id, 256) or login_id not in self._known_logins:
                raise CodexError("Unknown Codex sign-in request.")
            while login_id not in self._login_results and not self.closed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._state.wait(remaining)
            if self.closed:
                return False
            result = self._login_results.get(login_id)
        try:
            if result is None:
                self.cancel_login(login_id)
                return False
            if not result:
                return False
            return self.account().get("type") == "chatgpt"
        except CodexError:
            if self.closed:
                return False
            raise

    def logout(self):
        with self._operation():
            self._ensure_started()
            self._model_cache = None
            if self._active_login is not None:
                self.cancel_login(self._active_login)
            self._rpc("account/logout")
            if self.account():
                raise CodexError("Codex did not confirm sign-out. Reconnect and check account status.")
            self._clear_model_catalog()

    def close(self):
        """Cancel pending login, terminate only our process, release waiters."""
        with self._close_lock:
            with self._state:
                if self._closed:
                    return
                self._closing = True
                self._http_cancel.set()
                login_id = self._active_login
                self._state.notify_all()
            if login_id is not None and not self._broken:
                try:
                    self._rpc("account/login/cancel", {"loginId": login_id}, timeout=min(self._timeout, 1), closing=True)
                except CodexError:
                    pass
            self._abort()
            for reader in self._readers:
                if reader is not threading.current_thread():
                    reader.join(timeout=1)
            if self._process is not None:
                for stream in (self._process.stdin, self._process.stdout, self._process.stderr):
                    try:
                        stream.close()
                    except (OSError, ValueError):
                        pass
            if self._runtime is not None:
                try:
                    self._runtime.cleanup()
                except OSError:
                    pass
            with self._state:
                self._closed = True
                self._active_login = None
                self._state.notify_all()


_clients = {}
_clients_lock = threading.Lock()
_clients_epoch = object()


def get_client(codex_home, codex_path=""):
    """One lazy client per dedicated home/native-path selection."""
    epoch = _clients_epoch
    try:
        key = (os.path.normcase(str(Path(codex_home).resolve())), os.path.normcase(str(codex_path)))
    except (OSError, ValueError, TypeError):
        raise CodexError("Invalid dedicated Codex home.") from None
    with _clients_lock:
        if epoch is not _clients_epoch:
            raise CodexError("Codex client is closed.")
        # Changing the selected executable must not leave two OAuth owners for
        # the same credential directory (refresh-token rotation is exclusive).
        for existing_key in list(_clients):
            if existing_key[0] == key[0] and existing_key != key:
                _clients.pop(existing_key).close()
        client = _clients.get(key)
        if client is None or client.closed:
            if client is not None:
                client.close()
            client = CodexClient(codex_home, codex_path)
            _clients[key] = client
        return client


def close_clients():
    """Close all bridge-owned sessions; never touches an external CLI process."""
    global _clients_epoch
    with _clients_lock:
        try:
            for client in list(_clients.values()):
                client.close()
        finally:
            _clients.clear()
            # Acquisitions queued before/during teardown must not resurrect it.
            # A fresh request after teardown may start a new plugin lifetime.
            _clients_epoch = object()
