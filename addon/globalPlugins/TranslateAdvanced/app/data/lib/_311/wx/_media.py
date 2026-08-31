# -*- coding: utf-8 -*-
# Added by Axel (wmietek8), 2026, for NVDA 2026 AMD64 compatibility.
"""Zgodny silnik multimedialny dla dodatku TranslateAdvanced.

Stara wersja dodatku zawierala binarny modul wx.media skompilowany dla
Pythona 3.11 i 32 bitow. NVDA 2026.1.1 uzywa Pythona 3.13 i wersji
64-bitowej, dlatego tamten modul nie moze zostac zaladowany. Ten plik
udostepnia minimalny zestaw API uzywany przez dodatek, oparty o MCI w
systemie Windows.
"""

from __future__ import annotations

import builtins
import ctypes
import itertools
import os
from ctypes import wintypes
from typing import Any

import wx

try:
	from .....utils.utils_translation import translate as _translate
except Exception:
	_translate = None

wxEVT_MEDIA_LOADED = wx.NewEventType()
wxEVT_MEDIA_STOP = wx.NewEventType()
wxEVT_MEDIA_FINISHED = wx.NewEventType()
wxEVT_MEDIA_STATECHANGED = wx.NewEventType()
wxEVT_MEDIA_PLAY = wx.NewEventType()
wxEVT_MEDIA_PAUSE = wx.NewEventType()

MC_NO_AUTORESIZE = 0

_ALIAS_COUNTER = itertools.count(1)
_winmm = ctypes.WinDLL("winmm")
_mci_send_string = _winmm.mciSendStringW
_mci_send_string.argtypes = [
	ctypes.c_wchar_p,
	ctypes.c_wchar_p,
	wintypes.UINT,
	wintypes.HANDLE,
]
_mci_send_string.restype = wintypes.DWORD
_mci_get_error_string = _winmm.mciGetErrorStringW
_mci_get_error_string.argtypes = [wintypes.DWORD, ctypes.c_wchar_p, wintypes.UINT]
_mci_get_error_string.restype = wintypes.BOOL


def _(message: str) -> str:
	"""Zwraca tlumaczenie, gdy gettext NVDA jest juz gotowy."""
	if _translate is not None:
		return _translate(message)
	return getattr(builtins, "_", lambda text: text)(message)


class MCIError(RuntimeError):
	"""Blad zwrocony przez systemowy interfejs MCI."""


def _quote_path(path: str) -> str:
	"""Zwraca sciezke w cudzyslowie wymaganym przez polecenia MCI."""
	return '"' + path.replace('"', '""') + '"'


def _mci_error_text(code: int) -> str:
	"""Zwraca opis bledu MCI."""
	buffer = ctypes.create_unicode_buffer(512)
	if _mci_get_error_string(code, buffer, len(buffer)):
		return buffer.value
	return _("Error desconocido: {}").format("MCI {}".format(code))


def _send(command: str, buffer_size: int = 0) -> str:
	"""Wykonuje polecenie MCI i zwraca odpowiedz tekstowa."""
	buffer = ctypes.create_unicode_buffer(buffer_size) if buffer_size else None
	code = _mci_send_string(command, buffer, buffer_size, None)
	if code:
		raise MCIError(_mci_error_text(code))
	return buffer.value if buffer is not None else ""


class MediaCtrl(wx.Window):
	"""Minimalna implementacja kontrolki multimedialnej uzywanej przez dodatek."""

	def __init__(self, parent: wx.Window, id: int = wx.ID_ANY, style: int = 0, **kwargs: Any) -> None:
		"""Tworzy ukryta kontrolke zgodna z wybranymi metodami wx.media.MediaCtrl."""
		super().__init__(parent, id=id, size=(1, 1), style=style, **kwargs)
		self._alias = "ta_media_{}".format(next(_ALIAS_COUNTER))
		self._filepath: str | None = None
		self._loaded = False
		self._playing = False
		self._playback_rate = 1.0
		self._finish_timer = wx.Timer(self)
		self.Bind(wx.EVT_TIMER, self._on_finish_timer, self._finish_timer)

	def Load(self, fileName: str) -> bool:
		"""Laduje plik audio do odtworzenia."""
		self._close_mci()
		if not fileName or not os.path.isfile(fileName):
			return False
		self._filepath = os.path.abspath(fileName)
		try:
			self._open_media_file()
			_send("set {} time format milliseconds".format(self._alias))
		except MCIError:
			self._close_mci()
			return False
		self._loaded = True
		self._post_media_event(wxEVT_MEDIA_LOADED)
		return True

	def Play(self) -> bool:
		"""Rozpoczyna albo wznawia odtwarzanie."""
		if not self._loaded:
			return False
		try:
			_send("play {}".format(self._alias))
		except MCIError:
			return False
		self._playing = True
		self._post_media_event(wxEVT_MEDIA_PLAY)
		self._post_media_event(wxEVT_MEDIA_STATECHANGED)
		self._schedule_finish_timer()
		return True

	def Pause(self) -> bool:
		"""Wstrzymuje odtwarzanie."""
		if not self._loaded:
			return False
		try:
			_send("pause {}".format(self._alias))
		except MCIError:
			return False
		self._playing = False
		self._finish_timer.Stop()
		self._post_media_event(wxEVT_MEDIA_PAUSE)
		self._post_media_event(wxEVT_MEDIA_STATECHANGED)
		return True

	def Stop(self) -> bool:
		"""Zatrzymuje odtwarzanie i wraca na poczatek pliku."""
		if not self._loaded:
			return False
		try:
			_send("stop {}".format(self._alias))
			_send("seek {} to start".format(self._alias))
		except MCIError:
			return False
		self._playing = False
		self._finish_timer.Stop()
		self._post_media_event(wxEVT_MEDIA_STOP)
		self._post_media_event(wxEVT_MEDIA_STATECHANGED)
		return True

	def SetVolume(self, volume: float) -> bool:
		"""Ustawia glosnosc w zakresie od 0.0 do 1.0."""
		if not self._loaded:
			return False
		value = int(max(0.0, min(1.0, volume)) * 1000)
		try:
			_send("setaudio {} volume to {}".format(self._alias, value))
		except MCIError:
			return False
		return True

	def SetPlaybackRate(self, rate: float) -> bool:
		"""Zapamietuje predkosc odtwarzania, jesli MCI jej nie obsluguje."""
		self._playback_rate = max(0.1, float(rate))
		if not self._loaded:
			return False
		try:
			_send("set {} speed {}".format(self._alias, int(self._playback_rate * 1000)))
		except MCIError:
			return False
		return True

	def Tell(self) -> int:
		"""Zwraca aktualna pozycje odtwarzania w milisekundach."""
		return self._query_int("status {} position".format(self._alias))

	def Length(self) -> int:
		"""Zwraca dlugosc pliku w milisekundach."""
		return self._query_int("status {} length".format(self._alias))

	def Seek(self, milliseconds: int) -> bool:
		"""Przesuwa pozycje odtwarzania do wskazanej milisekundy."""
		if not self._loaded:
			return False
		total = self.Length()
		position = max(0, min(int(milliseconds), total if total > 0 else int(milliseconds)))
		was_playing = self._playing
		try:
			_send("seek {} to {}".format(self._alias, position))
			if was_playing:
				_send("play {}".format(self._alias))
				self._schedule_finish_timer()
		except MCIError:
			return False
		return True

	def Destroy(self) -> bool:
		"""Zwalnia zasoby kontrolki i zamyka uchwyt MCI."""
		self._close_mci()
		return super().Destroy()

	def _query_int(self, command: str) -> int:
		"""Wykonuje zapytanie MCI i zwraca liczbe calkowita."""
		if not self._loaded:
			return 0
		try:
			value = _send(command, 128).strip()
		except MCIError:
			return 0
		try:
			return int(value)
		except ValueError:
			return 0

	def _open_media_file(self) -> None:
		"""Otwiera plik, probujac typy potrzebne dla Google TTS."""
		if self._filepath is None:
			raise MCIError(_("No hay ningún archivo para abrir."))
		quoted_path = _quote_path(self._filepath)
		commands = [
			"open {} alias {}".format(quoted_path, self._alias),
			"open {} type mpegvideo alias {}".format(quoted_path, self._alias),
			"open {} type waveaudio alias {}".format(quoted_path, self._alias),
		]
		last_error: MCIError | None = None
		for command in commands:
			try:
				_send(command)
				return
			except MCIError as error:
				last_error = error
				try:
					_send("close {}".format(self._alias))
				except MCIError:
					pass
		if last_error is not None:
			raise last_error
		raise MCIError(_("No se puede abrir el archivo de audio."))

	def _schedule_finish_timer(self) -> None:
		"""Uruchamia zegar sprawdzajacy koniec odtwarzania."""
		remaining = max(250, self.Length() - self.Tell())
		self._finish_timer.StartOnce(remaining + 250)

	def _on_finish_timer(self, event: wx.TimerEvent) -> None:
		"""Wysyla zdarzenie zakonczenia, gdy odtwarzanie doszlo do konca."""
		if not self._loaded:
			return
		if self.Length() > 0 and self.Tell() >= self.Length() - 50:
			self._playing = False
			self._post_media_event(wxEVT_MEDIA_STOP)
			self._post_media_event(wxEVT_MEDIA_FINISHED)
			self._post_media_event(wxEVT_MEDIA_STATECHANGED)
			return
		if self._playing:
			self._schedule_finish_timer()

	def _post_media_event(self, event_type: int) -> None:
		"""Publikuje zdarzenie wx zgodne z wiazaniami wx.media."""
		event = wx.PyCommandEvent(event_type, self.GetId())
		event.SetEventObject(self)
		wx.PostEvent(self, event)

	def _close_mci(self) -> None:
		"""Zamyka aktualnie zaladowany plik MCI."""
		self._finish_timer.Stop()
		if self._loaded:
			try:
				_send("close {}".format(self._alias))
			except MCIError:
				pass
		self._loaded = False
		self._playing = False
		self._filepath = None
