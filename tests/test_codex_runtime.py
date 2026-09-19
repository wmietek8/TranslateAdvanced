"""Sprawdza pobieranie, integralność, anulowanie i ponowne użycie komponentu."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import sys
import threading
import urllib.error
import urllib.request
import zipfile
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from nvda_harness import APP


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Ładuje sam instalator, bez NVDA i bez prawdziwej sieci."""
    spec = importlib.util.spec_from_file_location(
        "ta_runtime_tests",
        APP / "utils/utils_codex_runtime.py",
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def download(
    runtime: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> SimpleNamespace:
    """Zastępuje tylko transport małym archiwum o znanej sumie SHA-256."""
    executable = b"MZ" + b"poprawny-komponent" * 40
    asset = runtime._ASSETS["x64"]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr(asset.executable_name, executable)
        bundle.writestr("codex-command-runner.exe", b"nie rozpakowuj")
        bundle.writestr("codex-windows-sandbox-setup.exe", b"nie uruchamiaj")
    archive = buffer.getvalue()
    asset = replace(
        asset,
        archive_size=len(archive),
        archive_sha256=hashlib.sha256(archive).hexdigest(),
        executable_size=len(executable),
        executable_sha256=hashlib.sha256(executable).hexdigest(),
    )
    state = SimpleNamespace(
        runtime=runtime,
        asset=asset,
        archive=archive,
        executable=executable,
        home=tmp_path / "TranslateAdvanced/codex",
        requests=[],
        progress=[],
        final_url="https://release-assets.githubusercontent.com/official-asset",
        status=200,
        failure=None,
        cancel=None,
    )

    class Response(io.BytesIO):
        """Granica HTTPS z możliwością zasymulowania anulowania transmisji."""

        status = 200

        def geturl(self) -> str:
            """Zwraca końcowy adres po przekierowaniu."""
            return state.final_url

        def read(self, size: int = -1) -> bytes:
            """Odczytuje fragment i opcjonalnie zgłasza anulowanie."""
            data = super().read(size)
            if state.cancel:
                state.cancel.set()
            return data

    def open_archive(request: urllib.request.Request, *, timeout: int) -> Response:
        assert timeout <= 10
        assert not request.get_header("Authorization")
        state.requests.append(request)
        if state.failure:
            raise state.failure
        response = Response(state.archive)
        response.status = state.status
        return response

    monkeypatch.setattr(runtime, "_asset", lambda: state.asset)
    monkeypatch.setattr(
        runtime.urllib.request,
        "build_opener",
        lambda *args: SimpleNamespace(open=open_archive),
    )
    return state


def test_download_verifies_and_reuses_component(download: SimpleNamespace) -> None:
    """Pierwsza próba instaluje sam program, następna nie pobiera go ponownie."""
    state = download
    runtime = state.runtime
    result = Path(
        runtime.ensure_managed_executable(
            state.home,
            progress=lambda *args: state.progress.append(args),
        )
    )
    assert result.read_bytes() == state.executable
    assert result.name == "codex.exe"
    assert [item.name for item in result.parent.iterdir()] == ["codex.exe"]
    assert state.requests[0].full_url == state.asset.url
    assert state.progress[0] == ("download", 0, state.asset.archive_size)
    assert state.progress[-1][0] == "ready"
    assert runtime.find_managed_executable(state.home) == str(result)
    assert runtime.ensure_managed_executable(state.home) == str(result)
    assert len(state.requests) == 1


def test_missing_component_probe_never_downloads(download: SimpleNamespace) -> None:
    """Samo sprawdzenie stanu nie tworzy plików i nie uruchamia pobierania."""
    assert download.runtime.find_managed_executable(download.home) is None
    assert download.requests == []
    assert not download.home.parent.exists()


@pytest.mark.parametrize("damage", ["short", "long", "hash", "exe_hash", "zip"])
def test_damaged_download_never_becomes_executable(
    download: SimpleNamespace, damage: str
) -> None:
    """Uszkodzone archiwum lub program są odrzucane, a pozostałości sprzątane."""
    state = download
    if damage == "short":
        state.archive = state.archive[:-1]
    elif damage == "long":
        state.archive += b"nadmiar"
    elif damage == "hash":
        state.asset = replace(state.asset, archive_sha256="0" * 64)
    elif damage == "exe_hash":
        state.asset = replace(state.asset, executable_sha256="0" * 64)
    else:
        state.archive = b"nie jest ZIP"
        state.asset = replace(
            state.asset,
            archive_size=len(state.archive),
            archive_sha256=hashlib.sha256(state.archive).hexdigest(),
        )
    with pytest.raises(state.runtime.RuntimeInstallError):
        state.runtime.ensure_managed_executable(state.home)
    assert not list(state.home.parent.rglob("*.exe"))
    assert not list(state.home.parent.rglob("download-*"))


@pytest.mark.parametrize(
    "name", ["../codex.exe", "/codex.exe", "codex.exe", "unexpected.dll"]
)
def test_archive_paths_cannot_escape_staging(
    download: SimpleNamespace, name: str
) -> None:
    """Nieoczekiwane elementy ZIP nie mogą zapisywać plików na zewnątrz."""
    state = download
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr(name, state.executable)
    state.archive = buffer.getvalue()
    state.asset = replace(
        state.asset,
        archive_size=len(state.archive),
        archive_sha256=hashlib.sha256(state.archive).hexdigest(),
    )
    with pytest.raises(state.runtime.RuntimeInstallError, match="zawartość"):
        state.runtime.ensure_managed_executable(state.home)
    assert not list(state.home.parent.rglob("*.exe"))


@pytest.mark.parametrize("phase", ["before", "download", "verify"])
def test_cancel_does_not_leave_partial_program(
    download: SimpleNamespace, phase: str
) -> None:
    """Anulowanie przed siecią, podczas transmisji i przed rozpakowaniem działa."""
    state = download
    event = threading.Event()
    if phase == "before":
        event.set()
    if phase == "download":
        state.cancel = event

    def progress(step: str, done: int, total: int) -> None:
        if phase == "verify" and step == "verify":
            event.set()

    with pytest.raises(state.runtime.RuntimeInstallCancelled):
        state.runtime.ensure_managed_executable(
            state.home, cancel_event=event, progress=progress
        )
    assert not list(state.home.parent.rglob("*.exe"))
    assert len(state.requests) == (0 if phase == "before" else 1)


def test_tampered_saved_component_is_repaired(download: SimpleNamespace) -> None:
    """Zmiana zapisanej kopii unieważnia kontrolę i wymusza poprawne pobranie."""
    state = download
    path = Path(state.runtime.ensure_managed_executable(state.home))
    path.write_bytes(b"X" * len(state.executable))
    assert state.runtime.find_managed_executable(state.home) is None
    state.runtime.ensure_managed_executable(state.home)
    assert path.read_bytes() == state.executable
    assert len(state.requests) == 2


@pytest.mark.parametrize(
    "failure",
    [
        TimeoutError("sekret"),
        urllib.error.URLError("sekret"),
        PermissionError("sekret"),
    ],
)
def test_download_errors_are_safe_and_retryable(
    download: SimpleNamespace, failure: Exception
) -> None:
    """Awaria nie ujawnia szczegółów ani nie blokuje późniejszej udanej próby."""
    state = download
    state.failure = failure
    with pytest.raises(state.runtime.RuntimeInstallError) as caught:
        state.runtime.ensure_managed_executable(state.home)
    assert "sekret" not in str(caught.value)
    state.failure = None
    assert Path(state.runtime.ensure_managed_executable(state.home)).is_file()


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/a",
        "https://evil.test/a",
        "https://github.com.evil.test/a",
        "https://user@github.com/a",
        "https://github.com:443/a",
        "https://github.com/a\\b",
    ],
)
def test_untrusted_redirects_are_rejected(runtime: ModuleType, url: str) -> None:
    """Przekierowania nie wychodzą poza jawnie dopuszczone hosty HTTPS."""
    redirect = runtime._DownloadRedirect()
    with pytest.raises(runtime.RuntimeInstallError):
        redirect.redirect_request(
            urllib.request.Request("https://github.com/a"), None, 302, "", {}, url
        )


def test_official_redirect_is_allowed(runtime: ModuleType) -> None:
    """Pobranie może przejść do magazynu plików wydania GitHuba."""
    result = runtime._DownloadRedirect().redirect_request(
        urllib.request.Request("https://github.com/a"),
        None,
        302,
        "",
        {},
        "https://release-assets.githubusercontent.com/asset?signature=synthetic",
    )
    assert result.full_url.startswith("https://release-assets.githubusercontent.com/")


@pytest.mark.parametrize(
    "machine, expected", [("AMD64", "x64"), ("ARM64", "arm64"), ("x86_64", "x64")]
)
def test_architecture_uses_native_system(
    runtime: ModuleType, monkeypatch: pytest.MonkeyPatch, machine: str, expected: str
) -> None:
    """32-bitowy proces NVDA na 64-bitowym Windows dobiera natywny program."""
    monkeypatch.setattr(runtime.platform, "system", lambda: "Windows")
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "x86")
    monkeypatch.setenv("PROCESSOR_ARCHITEW6432", machine)
    assert runtime._asset() == runtime._ASSETS[expected]


def test_unsupported_architecture_explains_api_alternative(
    runtime: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows x86 otrzymuje jasny komunikat, zanim zacznie się pobieranie."""
    monkeypatch.setattr(runtime.platform, "system", lambda: "Windows")
    monkeypatch.delenv("PROCESSOR_ARCHITEW6432", raising=False)
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "x86")
    with pytest.raises(runtime.RuntimeInstallError, match="klucza API"):
        runtime._asset()


def test_relative_storage_is_rejected(download: SimpleNamespace) -> None:
    """Nieprawidłowa konfiguracja ścieżki nie powoduje przypadkowego zapisu."""
    with pytest.raises(ValueError):
        download.runtime.ensure_managed_executable("relative/codex")
    assert not download.requests


def test_symlinked_storage_is_rejected(
    download: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Instalator odrzuca również dowiązania w katalogu nadrzędnym."""
    state = download
    original = Path.is_symlink
    monkeypatch.setattr(
        Path, "is_symlink", lambda path: path.name == "codex-runtime" or original(path)
    )
    with pytest.raises(state.runtime.RuntimeInstallError, match="dowiązaniem"):
        state.runtime.ensure_managed_executable(state.home)
    assert not state.requests


def test_timeout_releases_installation_lock(
    download: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Przekroczenie czasu pozwala na późniejsze ponowienie pobrania."""
    monkeypatch.setattr(download.runtime, "_DOWNLOAD_SECONDS", 0)
    with pytest.raises(download.runtime.RuntimeInstallError, match="czas"):
        download.runtime.ensure_managed_executable(download.home)
    assert not download.runtime._INSTALL_LOCK.locked()


def test_second_download_can_be_cancelled_while_waiting(
    download: SimpleNamespace,
) -> None:
    """Oczekiwanie na inny instalator reaguje na anulowanie bez żądania sieciowego."""
    state = download
    cancelled = threading.Event()
    cancelled.set()
    state.runtime._INSTALL_LOCK.acquire()
    try:
        with pytest.raises(state.runtime.RuntimeInstallCancelled):
            state.runtime.ensure_managed_executable(state.home, cancel_event=cancelled)
        assert state.runtime._INSTALL_LOCK.locked()
        assert state.requests == []
    finally:
        state.runtime._INSTALL_LOCK.release()


def test_http_failure_closes_response_and_hides_server_message(
    download: SimpleNamespace,
) -> None:
    """Odmowa GitHuba zwalnia połączenie i nie ujawnia surowej odpowiedzi."""
    body = io.BytesIO(b"prywatny-komunikat")
    download.failure = urllib.error.HTTPError(
        download.asset.url, 503, "sekret", {}, body
    )
    with pytest.raises(download.runtime.RuntimeInstallError, match="GitHub") as caught:
        download.runtime.ensure_managed_executable(download.home)
    assert "sekret" not in str(caught.value)
    assert body.closed


@pytest.mark.parametrize("change", ["status", "url"])
def test_unexpected_response_does_not_install(
    download: SimpleNamespace, change: str
) -> None:
    """Odpowiedź końcowa musi pochodzić z GitHuba i mieć status sukcesu."""
    if change == "status":
        download.status = 206
    else:
        download.final_url = "https://evil.test/asset"
    with pytest.raises(download.runtime.RuntimeInstallError):
        download.runtime.ensure_managed_executable(download.home)
    assert not list(download.home.parent.rglob("*.exe"))
