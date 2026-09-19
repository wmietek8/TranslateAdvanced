"""Pobiera sprawdzoną wersję oficjalnego Codexa do katalogu dodatku.

Metadane pochodzą z wydania rust-v0.155.0 w openai/codex na GitHubie.
Nie wykonuje instalatorów, skryptów powłoki ani plików przed kontrolą SHA-256.
Nie używa konta OpenAI, kluczy API ani katalogu osobistego Codexa.
"""

from __future__ import annotations

import hashlib
import http.client
import os
import platform
import ssl
import stat
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from email.message import Message
from pathlib import Path
from urllib.parse import urlsplit

Progress = Callable[[str, int, int], None]
VERSION = "0.155.0"
_BASE_URL = f"https://github.com/openai/codex/releases/download/rust-v{VERSION}/"
_BLOCK_SIZE = 256 * 1024
_DOWNLOAD_SECONDS = 600
_INSTALL_LOCK = threading.Lock()
_VERIFIED: dict[str, tuple[int, int, int, int]] = {}


class RuntimeInstallError(RuntimeError):
    """Bezpieczny komunikat o nieudanym przygotowaniu komponentu."""


class RuntimeInstallCancelled(RuntimeInstallError):
    """Oznacza jawne anulowanie przygotowania komponentu."""


@dataclass(frozen=True)
class RuntimeAsset:
    """Niezmienne rozmiary i skróty oficjalnego archiwum oraz programu."""

    triple: str
    archive_size: int
    archive_sha256: str
    executable_size: int
    executable_sha256: str

    @property
    def executable_name(self) -> str:
        """Zwraca nazwę programu wewnątrz oficjalnego archiwum."""
        return f"codex-{self.triple}.exe"

    @property
    def url(self) -> str:
        """Zwraca przypięty adres pobierania archiwum."""
        return _BASE_URL + self.executable_name + ".zip"


_ASSETS = {
    "x64": RuntimeAsset(
        "x86_64-pc-windows-msvc",
        107589902,
        "b8c4c83b3da224b1d0dac10fcc886cc79adec2e945802cb74a4b88ca4b0ac5af",
        307150128,
        "e4c11374bd9de8ad5c3b7617fd4654bb7839901edb0863f9930666863c7a021b",
    ),
    "arm64": RuntimeAsset(
        "aarch64-pc-windows-msvc",
        99052213,
        "dd0da6cf1345494edba56685c2baabb32cd37b92182585abec1b81092a70073a",
        258786096,
        "9d7759c63b3fe00200ca7f5610f9388251807e1234b7a17745268b13fcfebf38",
    ),
}


def _asset() -> RuntimeAsset:
    if platform.system() != "Windows":
        raise RuntimeInstallError("Automatyczne logowanie wymaga systemu Windows.")
    machine = (
        os.environ.get("PROCESSOR_ARCHITEW6432")
        or os.environ.get("PROCESSOR_ARCHITECTURE")
        or platform.machine()
    ).lower()
    if machine in ("arm64", "aarch64"):
        return _ASSETS["arm64"]
    if machine in ("amd64", "x86_64", "x64"):
        return _ASSETS["x64"]
    raise RuntimeInstallError(
        "Logowanie kontem ChatGPT wymaga 64-bitowego systemu Windows. "
        "Na tym systemie możesz korzystać z klucza API."
    )


def _checked_path(path: Path) -> Path:
    # Odrzucamy także dowiązania katalogów nadrzędnych i punkty połączeń Windows.
    for part in (path, *path.parents):
        try:
            attributes = getattr(part.lstat(), "st_file_attributes", 0)
        except FileNotFoundError:
            attributes = 0
        if part.is_symlink() or attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise RuntimeInstallError("Katalog komponentu nie może być dowiązaniem.")
    return path


def _destination(codex_home: str | Path, asset: RuntimeAsset) -> Path:
    home = Path(codex_home)
    if not home.is_absolute() or ".." in home.parts:
        raise ValueError("Katalog konta musi mieć pełną, jednoznaczną ścieżkę.")
    root = _checked_path(home.parent / "codex-runtime")
    return _checked_path(root / f"{VERSION}-{asset.triple}" / "codex.exe")


def _check_cancel(cancel_event: threading.Event | None, deadline: float) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeInstallCancelled("Anulowano przygotowanie logowania.")
    if time.monotonic() >= deadline:
        raise RuntimeInstallError(
            "Upłynął czas pobierania komponentu. Spróbuj ponownie."
        )


def _valid_executable(path: Path, asset: RuntimeAsset) -> bool:
    _checked_path(path)
    if not path.is_file():
        return False
    stat = path.stat()
    signature = (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino)
    if stat.st_size != asset.executable_size:
        return False
    if _VERIFIED.get(str(path)) == signature:
        return True
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(_BLOCK_SIZE), b""):
            digest.update(block)
    if digest.hexdigest() != asset.executable_sha256:
        return False
    _VERIFIED[str(path)] = signature
    return True


def find_managed_executable(codex_home: str | Path) -> str | None:
    """Zwraca zweryfikowany zapisany program, bez pobierania czegokolwiek."""
    try:
        asset = _asset()
        path = _destination(codex_home, asset)
        return str(path) if _valid_executable(path, asset) else None
    except OSError:
        raise RuntimeInstallError("Nie można odczytać komponentu logowania.") from None


def _trusted_download_url(url: str) -> bool:
    parsed = urlsplit(url)
    return (
        parsed.scheme == "https"
        and parsed.netloc in ("github.com", "release-assets.githubusercontent.com")
        and not any(ord(char) <= 32 or ord(char) == 127 for char in url)
        and "\\" not in url
    )


class _DownloadRedirect(urllib.request.HTTPRedirectHandler):
    """Dopuszcza przekierowanie wyłącznie do oficjalnego magazynu GitHuba."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: Message,
        newurl: str,
    ) -> urllib.request.Request | None:
        """Sprawdza docelowy adres przed utworzeniem kolejnego żądania."""
        if not _trusted_download_url(newurl):
            raise RuntimeInstallError("Odrzucono nieoczekiwany adres pobierania.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download(
    path: Path,
    asset: RuntimeAsset,
    cancel_event: threading.Event | None,
    progress: Progress | None,
    deadline: float,
) -> None:
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        _DownloadRedirect(),
    )
    request = urllib.request.Request(
        asset.url,
        headers={"User-Agent": "TranslateAdvanced-Codex-Setup/1"},
    )
    digest = hashlib.sha256()
    downloaded = 0
    last_progress = 0
    with opener.open(request, timeout=10) as response, path.open("xb") as stream:
        if response.status != 200 or not _trusted_download_url(response.geturl()):
            raise RuntimeInstallError("Nie udało się pobrać oficjalnego komponentu.")
        while True:
            _check_cancel(cancel_event, deadline)
            block = response.read(_BLOCK_SIZE)
            if not block:
                break
            downloaded += len(block)
            if downloaded > asset.archive_size:
                raise RuntimeInstallError("Pobrany komponent ma nieprawidłowy rozmiar.")
            digest.update(block)
            stream.write(block)
            percent = downloaded * 100 // asset.archive_size
            if progress is not None and percent // 10 != last_progress:
                progress("download", downloaded, asset.archive_size)
                last_progress = percent // 10
    if downloaded != asset.archive_size or digest.hexdigest() != asset.archive_sha256:
        raise RuntimeInstallError(
            "Kontrola SHA-256 pobranego komponentu nie powiodła się."
        )


def _unpack(
    archive: Path,
    output: Path,
    asset: RuntimeAsset,
    cancel_event: threading.Event | None,
    deadline: float,
) -> None:
    # Otwieramy tylko oczekiwany element, nigdy nie rozpakowujemy ścieżek ZIP.
    digest = hashlib.sha256()
    copied = 0
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        names = [entry.filename for entry in entries]
        allowed = {
            asset.executable_name,
            "codex-command-runner.exe",
            "codex-windows-sandbox-setup.exe",
        }
        if (
            len(names) != len(set(names))
            or asset.executable_name not in names
            or not set(names) <= allowed
        ):
            raise RuntimeInstallError("Archiwum komponentu ma nieoczekiwaną zawartość.")
        # Narzędzia wykonywania komend i konfiguracji piaskownicy nie są potrzebne.
        entry = bundle.getinfo(asset.executable_name)
        if entry.file_size != asset.executable_size or entry.flag_bits & 1:
            raise RuntimeInstallError(
                "Program w archiwum ma nieprawidłowy rozmiar lub format."
            )
        with bundle.open(entry) as source, output.open("xb") as target:
            while True:
                _check_cancel(cancel_event, deadline)
                block = source.read(_BLOCK_SIZE)
                if not block:
                    break
                copied += len(block)
                if copied > asset.executable_size:
                    raise RuntimeInstallError(
                        "Program w archiwum przekracza dozwolony rozmiar."
                    )
                digest.update(block)
                target.write(block)
    if copied != asset.executable_size or digest.hexdigest() != asset.executable_sha256:
        raise RuntimeInstallError(
            "Kontrola SHA-256 programu logowania nie powiodła się."
        )


def ensure_managed_executable(
    codex_home: str | Path,
    *,
    cancel_event: threading.Event | None = None,
    progress: Progress | None = None,
) -> str:
    """Przygotowuje program w tle; ponownie używa poprawnej zapisanej kopii.

    Wywołuj po jawnym kliknięciu logowania. Anulowanie lub awaria nie pozostawia
    częściowego programu. Nie wymaga uprawnień administratora ani zmiany PATH.
    """
    asset = _asset()
    destination = _destination(codex_home, asset)
    deadline = time.monotonic() + _DOWNLOAD_SECONDS
    while not _INSTALL_LOCK.acquire(timeout=0.1):
        _check_cancel(cancel_event, deadline)
    try:
        _check_cancel(cancel_event, deadline)
        if _valid_executable(destination, asset):
            return str(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        _checked_path(destination)
        if progress is not None:
            progress("download", 0, asset.archive_size)
        with tempfile.TemporaryDirectory(
            prefix="download-", dir=destination.parent
        ) as staging:
            stage = Path(staging).resolve()
            if stage.parent != destination.parent.resolve():
                raise RuntimeInstallError(
                    "Nieprawidłowy katalog tymczasowy komponentu."
                )
            archive = stage / "codex.zip"
            output = stage / "codex.exe"
            _download(archive, asset, cancel_event, progress, deadline)
            if progress is not None:
                progress("verify", asset.archive_size, asset.archive_size)
            _unpack(archive, output, asset, cancel_event, deadline)
            _check_cancel(cancel_event, deadline)
            _checked_path(destination)
            # Drugi proces mógł już przygotować tę samą, poprawną wersję.
            if not _valid_executable(destination, asset):
                os.replace(output, destination)
            if not _valid_executable(destination, asset):
                raise RuntimeInstallError(
                    "Nie udało się zapisać poprawnego komponentu."
                )
        if progress is not None:
            progress("ready", asset.archive_size, asset.archive_size)
        return str(destination)
    except urllib.error.HTTPError as error:
        error.close()
        raise RuntimeInstallError(
            "GitHub nie udostępnił komponentu. Spróbuj ponownie później."
        ) from None
    except (
        OSError,
        http.client.HTTPException,
        zipfile.BadZipFile,
        RuntimeError,
    ) as error:
        if isinstance(error, RuntimeInstallError):
            raise
        raise RuntimeInstallError(
            "Nie udało się przygotować komponentu logowania. "
            "Sprawdź połączenie, wolne miejsce i dostęp do katalogu profilu NVDA."
        ) from None
    finally:
        _INSTALL_LOCK.release()
