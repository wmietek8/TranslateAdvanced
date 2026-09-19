# -*- coding: utf-8 -*-
# Copyright (C) 2024 Héctor J. Benítez Corredera <xebolax@gmail.com>
# Este archivo está cubierto por la Licencia Pública General de GNU.
#
# Carga NVDA
import addonHandler
import logHandler
# Carga Python
import wx
from ..utils.utils_clipboard_win32 import Win32Clipboard
import threading
from time import sleep

# Carga traducción
addonHandler.initTranslation()

class ClipboardMonitor:
	"""
	Clase para monitorizar el portapapeles y detectar cambios de contenido de texto en tiempo real.
	"""
	def __init__(self, frame, check_interval=0.5):
		"""
		Inicializa una nueva instancia de la clase ClipboardMonitor.

		:param check_interval: Intervalo de tiempo en segundos para verificar el portapapeles.
		"""
		self.frame = frame
		self.check_interval = check_interval
		self.last_content = ""
		self._running = False
		self._initial_check = True
		self._native_clipboard = None

	@staticmethod
	def _clipboard_owner():
		# GlobalPlugin is not a wx window; NVDA's main frame is our owned HWND.
		import gui
		return gui.mainFrame.GetHandle()

	def _native(self):
		if self._native_clipboard is None:
			self._native_clipboard = Win32Clipboard(self._clipboard_owner)
		return self._native_clipboard

	def get_clipboard_sequence_number(self):
		"""Generation is available even when another application holds the lock."""
		try:
			return self._native().sequence()
		except Exception:
			return None

	def get_clipboard_snapshot(self, expected_sequence=None):
		"""Capture text and its rendered generation under a real Win32 lock.

		(None, None) means unavailable. (None, generation) rejects a copy before
		acquiring the lock. Delayed rendering *under* the lock is accepted and
		establishes the generation for the final compare-and-replace.
		"""
		try:
			return self._native().snapshot(expected_sequence)
		except Exception:
			return None, None

	def get_clipboard_text(self):
		"""Read Unicode text without sleeping/retrying on the NVDA thread."""
		return self.get_clipboard_snapshot()[0]

	def set_clipboard_text(self, text):
		"""Copy text, returning whether SetData actually succeeded."""
		clipboard = wx.Clipboard.Get()
		opened = False
		try:
			opened = clipboard.Open()
			if not opened:
				return False
			data = wx.TextDataObject()
			data.SetText(text)
			if not clipboard.SetData(data):
				return False
			clipboard.Flush()
			return True
		except Exception:
			return False
		finally:
			if opened:
				clipboard.Close()

	def replace_clipboard_text(self, original, translated, expected_sequence=None, cancelled=None):
		"""Compare and replace under one actual OS lock, never a wx/OLE flag."""
		try:
			return self._native().replace(original, translated, expected_sequence, cancelled)
		except Exception:
			return "unavailable"

	def clear_clipboard(self):
		"""Clear only after acquiring the clipboard; report actual success."""
		clipboard = wx.Clipboard.Get()
		opened = False
		try:
			opened = clipboard.Open()
			if not opened:
				return False
			clipboard.Clear()
			return True
		except Exception:
			return False
		finally:
			if opened:
				clipboard.Close()

	def has_clipboard_changed(self):
		"""
		Verifica si el contenido del portapapeles ha cambiado.

		:return: True si el contenido del portapapeles ha cambiado, False en caso contrario.
		"""
		current_content = self.get_clipboard_text()
		if current_content is not None and current_content != self.last_content:
			self.last_content = current_content
			return True
		return False

	def start_monitoring(self):
		"""
		Inicia la monitorización del portapapeles en un hilo separado.
		"""
		self._running = True
		thread = threading.Thread(target=self._monitor_clipboard)
		thread.daemon = True
		thread.start()

	def stop_monitoring(self):
		"""
		Detiene la monitorización del portapapeles.
		"""
		self._running = False

	def _monitor_clipboard(self):
		"""
		Método interno que monitoriza el portapapeles periódicamente.
		"""
		while self._running:
			if self.has_clipboard_changed():
				if not self._initial_check:
					logHandler.log.info(_("El contenido del portapapeles ha cambiado: {0}").format(self.last_content))
				else:
					self._initial_check = False
			sleep(self.check_interval)

	def get_last_clipboard_text(self):
		"""
		Obtiene el último contenido de texto conocido del portapapeles.

		:return: El último contenido de texto del portapapeles.
		"""
		return self.last_content
