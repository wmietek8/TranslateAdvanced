# -*- coding: utf-8 -*-
# Copyright (C) 2024 Héctor J. Benítez Corredera <xebolax@gmail.com>
# Este archivo está cubierto por la Licencia Pública General de GNU.
#
# Carga NVDA
import addonHandler
# Carga Python
import wx
import threading
# Carga personal
from ..src_translations.src_google_tts import TextToSpeechGoogle

# Carga traducción
addonHandler.initTranslation()

class ProgressDialog(wx.Dialog):
	"""
	Diálogo de progreso para la traducción de textos.
	"""
	def __init__(self, frame, texto_a_traducir, interfaz=False, secundary_frame=None, tts=None, lang_tts=None):
		"""
		Inicializa el diálogo de progreso.

		:param frame: El marco principal de la aplicación.
		:param texto_a_traducir: El texto que se va a traducir.
		:param interfaz: Si viene de una gui.
		"""
		super(ProgressDialog, self).__init__(None, title=_("Progreso de la Traducción"), size=(600, 200))

		self.frame = frame
		self.texto_a_traducir = texto_a_traducir
		self.interfaz = interfaz
		self.secundary_frame = secundary_frame
		self.tts = tts
		if self.tts:
			self.SetTitle(_("Progreso de la obtención del audio"))
		self.lang_tts = lang_tts
		self.canceled = False
		self.completed = False
		self._closed = False
		self._destroy_requested = False
		self._cancel_event = threading.Event()
		self.error = None
		self.traduccion_resultado = ""
		self.translator = None
		self._startup_error = None
		try:
			if self.tts:
				self.translator = TextToSpeechGoogle()
			else:
				# wx choices and mutable settings belong to the main thread.
				if self.interfaz:
					self.options = frame.gestor_translate.translation_options(
						source=secundary_frame.choice_origen.GetStringSelection().split(' - ')[-1],
						target=secundary_frame.choice_destino.GetStringSelection().split(' - ')[-1],
					)
				else:
					self.options = frame.gestor_translate.translation_options(bidirectional=True)
				self._translate = frame.gestor_translate.translate_with_options
		except Exception as error:
			self._startup_error = str(error)

		# Crear widgets
		self.progress_bar = wx.Gauge(self, range=100)
		self.cancel_button = wx.Button(self, label=_("Cancelar"))

		# Layout
		sizer = wx.BoxSizer(wx.VERTICAL)
		sizer.Add(self.progress_bar, 0, wx.EXPAND | wx.ALL, 10)
		sizer.Add(self.cancel_button, 0, wx.ALL | wx.ALIGN_CENTER, 10)
		self.SetSizer(sizer)

		# Bindings
		self.cancel_button.Bind(wx.EVT_BUTTON, self.on_cancel)
		self.Bind(wx.EVT_CLOSE, self.on_cancel)
		self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)

		self.CenterOnScreen()

		# Keep pending dialogs cancellable when the plug-in unloads.
		if not hasattr(frame, "_translation_dialogs"):
			frame._translation_dialogs = set()
		frame._translation_dialogs.add(self)
		# Iniciar hilo de traducción
		try:
			self.translate_thread = threading.Thread(target=self.translate_text, daemon=True)
			self.translate_thread.start()
		except Exception as error:
			wx.CallAfter(self._translation_finished, None, str(error))

	def on_cancel(self, event):
		"""Cancel without joining a possibly blocked network request."""
		if self._closed:
			return
		self.canceled = True
		self._cancel_event.set()
		try:
			if self.translator is not None:
				self.translator.stop()
		finally:
			self.onFinish()

	def translate_text(self):
		"""Provider I/O only: no wx widgets or shared settings in this worker."""
		if self._cancel_event.is_set():
			return
		result, error = None, None
		try:
			if self._startup_error is not None:
				raise RuntimeError(self._startup_error)
			if self.tts:
				result = self.translator.obtener_audio(
					self.texto_a_traducir, self.lang_tts, mostrar_progreso=True,
					widget=self.update_progress,
				)
				status = self.translator.get_error()
				if status["success"]:
					raise RuntimeError(status["data"])
			else:
				result = self._translate(self.texto_a_traducir, self.options)
		except Exception as failure:
			error = str(failure)
		if not self._cancel_event.is_set():
			wx.CallAfter(self._translation_finished, result, error)

	def _translation_finished(self, result, error):
		if self._closed or self._cancel_event.is_set() or getattr(self.frame, "_terminating", False):
			return
		self.traduccion_resultado = result if error is None else ""
		self.error = error
		self.completed = error is None
		try:
			if self.completed:
				self.progress_bar.SetValue(100)
				if not self.tts:
					self.frame.gestor_translate.record_translation(self.texto_a_traducir, result)
		finally:
			self.onFinish()

	def update_progress(self, progreso):
		if not self._cancel_event.is_set():
			wx.CallAfter(self._apply_progress, int(progreso))

	def _apply_progress(self, progreso):
		if not self._closed and not self._cancel_event.is_set() and not getattr(self.frame, "_terminating", False):
			self.progress_bar.SetValue(max(0, min(100, progreso)))

	def _release(self):
		if self._closed:
			return
		self._closed = True
		self._cancel_event.set()
		getattr(self.frame, "_translation_dialogs", set()).discard(self)
		if not self.interfaz and getattr(self.frame, "gestor_settings", None) is not None:
			self.frame.gestor_settings.is_active_translate = False

	def _on_destroy(self, event):
		if event.GetEventObject() is self:
			if not self._closed:
				self.canceled = True
				if self.translator is not None:
					self.translator.stop()
			self._release()
			self._destroy_requested = True
		event.Skip()

	def Destroy(self):
		if self._destroy_requested:
			return False
		self._destroy_requested = True
		if not self._closed:
			self.canceled = True
			if self.translator is not None:
				self.translator.stop()
			self._release()
		return super(ProgressDialog, self).Destroy()

	def onFinish(self):
		"""End the modal exactly once, before any queued callbacks can run."""
		if self._closed:
			return
		self._release()
		if self.IsModal():
			self.EndModal(wx.ID_OK if not self.canceled else wx.ID_CANCEL)
		else:
			self.Destroy()
