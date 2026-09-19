# -*- coding: utf-8 -*-
# Modified by Axel (wmietek8), 2026: selected-engine routing, cache isolation,
# short-response handling, and direct clipboard translation. Original
# copyright and GPL v2 licensing remain in effect.
# Copyright (C) 2024 Héctor J. Benítez Corredera <xebolax@gmail.com>
# Este archivo está cubierto por la Licencia Pública General de GNU.
#
# Carga NVDA
import addonHandler
import globalVars
import logHandler
import languageHandler
import braille
import speechViewer
import ui
from speech import *
# Carga estándar
import re
import os
import time
# Carga personal
from ..src_translations.src_google_original import TranslatorGoogle
from ..src_translations.src_google_alternative import TranslatorGooglealternative
from ..src_translations.src_google_api_free import TranslatorGoogleApiFree
from ..src_translations.src_google_api_free_alternative import TranslatorGoogleApiFreeAlternative
from ..src_translations.src_deepl_original import TranslatorDeepL
from ..src_translations.src_libretranslate_original import TranslatorLibreTranslate
from ..src_translations.src_microsoft_api_free import TranslatorMicrosoftApiFree
from ..src_translations.src_deepl_free import TranslatorDeepLFree
from ..src_translations.src_openai_4o_api import TranslationError, TranslatorOpenAI
from ..src_translations.src_detect import DetectorDeIdioma
from ..managers.managers_dict import LanguageDictionary
from ..utils.utils_short_translation import postprocess_short_translation
from ..utils.utils_speech import group_adjacent_text

# Carga traducción
addonHandler.initTranslation()

class GestorTranslate(
	TranslatorGoogle, 
	TranslatorGooglealternative, 
	TranslatorDeepL,
	TranslatorLibreTranslate,
	TranslatorMicrosoftApiFree,
	TranslatorOpenAI,
):
	"""
	Clase que gestiona la traducción de texto y el manejo del historial de traducción.
	"""
	def __init__(self, frame):
		"""
		Inicializa la clase con el marco de la aplicación.

		:param frame: El marco principal de la aplicación.
		"""
		super().__init__()
		TranslatorOpenAI.__init__(self)  # Llama explícitamente al constructor de TranslatorOpenAI
		self.frame = frame
		self.data_google = LanguageDictionary(self.frame.gestor_lang.obtener_idiomas("google"))

	def remove_surrogates(self, text):
		"""
		Elimina los caracteres sustitutos de una cadena.

		:param text: La cadena a procesar.
		:return: La cadena sin caracteres sustitutos.
		"""
		# Eliminar caracteres sustitutos de la cadena
		return re.sub(r'[\ud800-\udfff]', '', text)

	def get_choice_lang_destino(self):
		"""
		Devuelve el contenido de la variable choiceLangDestino correspondiente según el valor de choiceOnline.

		Returns:
			El contenido de la variable choiceLangDestino correspondiente o None si choiceOnline no es válido.
		"""
		value = self.frame.gestor_settings.choiceOnline
		if value in [0, 1, 2, 3]:
			return self.frame.gestor_settings.choiceLangDestino_google
		elif value in [4, 5, 8]:
			return self.frame.gestor_settings.choiceLangDestino_deepl
		elif value == 6:
			return self.frame.gestor_settings.choiceLangDestino_libretranslate
		elif value == 7:
			return self.frame.gestor_settings.choiceLangDestino_microsoft
		elif value == 9:
			return self.frame.gestor_settings.choiceLangDestino_openai

	def get_api(self):
		"""Resolve only this provider's selected key, tolerating deleted entries."""
		settings = self.frame.gestor_settings
		if settings.choiceOnline == 9 and getattr(settings, "openai_auth_mode", "api_key") == "chatgpt":
			return None, None
		mapping = {4: ("deepL_free", "api_deepl"), 5: ("deepL_pro", "api_deepl_pro"),
			6: ("libre_translate", "api_libretranslate"), 9: ("openai", "api_openai")}
		if settings.choiceOnline not in mapping:
			return None, None
		service, attribute = mapping[settings.choiceOnline]
		index = getattr(settings, attribute, None)
		if not isinstance(index, int) or isinstance(index, bool) or index < 0:
			return None, None
		entry = self.frame.gestor_apis.get_api(service, index)
		if not isinstance(entry, dict):
			return None, None
		return entry.get("key"), entry.get("url")

	def procesar_listas(self, origen, destino):
		"""
		Procesa dos listas para unificar sus cadenas de texto, eliminar los espacios al final de cada cadena,
		y omitir los elementos que no son cadenas de texto.

		Parámetros:
		origen (list): La lista origen que contiene cadenas de texto y otros tipos de datos.
		destino (list): La lista destino que contiene cadenas de texto y otros tipos de datos.

		Retorna:
		dict: Un diccionario con 'origen' y 'destino' como claves y las listas procesadas como valores.
		"""
		def procesar_lista(lista):
			"""
			Procesa una lista para unificar sus cadenas de texto, eliminar los espacios al final de cada cadena,
			y omitir los elementos que no son cadenas de texto.

			Parámetros:
			lista (list): La lista que contiene cadenas de texto y otros tipos de datos.

			Retorna:
			str: Una cadena de texto unificada sin espacios al final.
			"""
			# Crear una lista para almacenar los textos procesados
			lista_textos = []

			# Recorrer cada elemento en la lista
			for elemento in lista:
				# Verificar si el elemento es una cadena de texto
				if isinstance(elemento, str):
					# Eliminar los espacios al final y añadir a la lista de textos
					lista_textos.append(elemento.rstrip())

			# Unir todos los elementos de texto en una sola cadena con un espacio entre ellos
			texto_unido = ' '.join(lista_textos)

			return texto_unido

		# Procesar las listas origen y destino
		origen_procesado = procesar_lista(origen)
		destino_procesado = procesar_lista(destino)

		# Devolver un diccionario con las listas procesadas
		return {'origen': origen_procesado, 'destino': destino_procesado}

	def detector_idiomas(self, text):
		"""
		Detecta el idioma de un texto dado y muestra el nombre del idioma detectado.

		Parámetros:
			text (str): El texto cuya lengua se desea detectar.

		Acciones:
			1. Utiliza DetectorDeIdioma para detectar el idioma del texto.
			2. Si la detección es exitosa, obtiene el nombre del idioma utilizando los valores de data_google.
			3. Muestra una descripción del idioma detectado si está disponible, de lo contrario, muestra el nombre del idioma.
			4. Si la detección no es exitosa, muestra un mensaje de error.
			5. Desactiva la traducción en gestor_settings.

		Resultado:
			Muestra un mensaje con el nombre o descripción del idioma detectado, o un mensaje de error si la detección falla.
		"""
		result = DetectorDeIdioma().detectar_idioma(text)
		if result["success"]:
			idiomas_name = self.data_google.get_values()
			data = languageHandler.getLanguageDescription(result["data"])
			if data is None:
				ui.message(idiomas_name[self.data_google.get_index_by_key_or_value(result["data"])])
			else:
				ui.message(data)
		else:
			ui.message(_("No se a podido obtener el idioma"))
		self.frame.gestor_settings.is_active_translate = False

	def translation_options(self, *, bidirectional=False, target=None, source=None):
		"""Snapshot a request on the NVDA thread; never mutate shared settings."""
		settings = self.frame.gestor_settings
		provider = settings.choiceOnline
		if source is None:
			# Clipboard direction detection must not inherit the real-time source.
			source = settings.choiceLangOrigen if provider == 7 and not bidirectional else "auto"
		key, url = self.get_api() or (None, None)
		alternate = None
		if bidirectional and settings.chkAltLang:
			target = settings.choiceLangDestino_google_def
			alternate = settings.choiceLangDestino_google_alt
		return {
			"provider": provider, "key": key, "url": url,
			"target": target or self.get_choice_lang_destino(), "source": source,
			"alternate": alternate,
			"auth_mode": getattr(settings, "openai_auth_mode", "api_key"),
			"model": getattr(settings, "openai_model_oauth" if getattr(settings, "openai_auth_mode", "api_key") == "chatgpt" else "openai_model_api", "auto"),
			"codex_path": getattr(settings, "openai_codex_path", ""),
			"codex_home": os.path.join(globalVars.appArgs.configPath, "TranslateAdvanced", "codex"),
		}

	def translate_with_options(self, text, options):
		"""Translate using one captured provider. Errors must not become clipboard text."""
		if not isinstance(text, str) or not text.strip():
			raise ValueError(_("There is no text to translate."))
		if len(text) > 24000:
			raise ValueError(_("Translate up to 24000 characters at a time."))
		provider, target = options["provider"], options["target"]
		alternate, source = options["alternate"], options["source"]
		key, url = options["key"], options["url"]
		if provider in (4, 5, 6) and not key:
			raise ValueError(_("No tiene ninguna API configurada para el servicio que tiene seleccionado."))
		if provider in (4, 5):
			return self.translate_deepl(text, key, use_free_api=provider == 4,
				source_lang=source, target_lang=target, alternate_lang=alternate, strict=True)
		if provider == 9:
			return self.translate_openai(key, text, target_language=target,
				alternate_language=alternate, source_language=source, model=options["model"],
				auth_mode=options["auth_mode"], codex_home=options["codex_home"], codex_path=options["codex_path"])
		if alternate:
			if provider in (0, 1, 2, 3):
				# Google is allowed to detect only when Google itself was selected.
				detection = DetectorDeIdioma().detectar_idioma(text)
				if not detection.get("success"):
					raise RuntimeError(_("Language detection failed. Clipboard was not changed."))
				if detection["data"].lower().split("-")[0] == target.lower().split("-")[0]:
					target = alternate
			else:
				raise ValueError(_("Automatic direction requires DeepL API, OpenAI or Google. Disable automatic language switching for this provider."))
		if provider == 0:
			result = self.translate_google(text.encode("utf-8"), to_language=target, from_language=source)
		elif provider == 1:
			result = self.translate_google_alternative(text.encode("utf-8"), target=target, source=source)
		elif provider in (2, 3):
			engine = TranslatorGoogleApiFree() if provider == 2 else TranslatorGoogleApiFreeAlternative()
			result = engine.translate_google_api_free(lang_from=source, lang_to=target, text=text, chunksize=3000, mostrar_progreso=False)
			if engine.get_error().get("success"):
				raise RuntimeError(_("Translation failed. Clipboard was not changed."))
		elif provider == 6:
			if not url:
				raise ValueError(_("No tiene ninguna API configurada para el servicio que tiene seleccionado."))
			result = self.translate_libretranslate(text, key, source_lang=source, target_lang=target, api_url=url)
		elif provider == 7:
			result = self.translate_microsoft_api_free(source, target, text)
		elif provider == 8:
			engine = TranslatorDeepLFree()
			engine.source_lang, engine.target_lang = source, target
			result = engine.translate(text)
		else:
			raise ValueError(_("Unknown translation provider."))
		if isinstance(result, bytes):
			result = result.decode("utf-8")
		if not isinstance(result, str) or not result.strip():
			raise RuntimeError(_("Translation returned no text."))
		return postprocess_short_translation(text, result, target)

	def record_translation(self, source, result):
		"""Update history and braille on the main NVDA thread only."""
		settings = self.frame.gestor_settings
		settings._lastTranslatedText = result
		if source.rstrip() != result.rstrip() and source not in settings.historialOrigen:
			settings.historialOrigen.appendleft(source)
			settings.historialDestino.appendleft(result)
		if braille.handler._get_enabled():
			braille.handler.message(result)

	def translate_various(self, text):
		"""Direct commands share the selected provider and automatic direction."""
		result = self.translate_with_options(text, self.translation_options(bidirectional=True))
		self.record_translation(text, result)
		return result

	def translate_file(self, text, func_progress):
		"""Files use the selected provider too, never a hidden Google fallback."""
		func_progress(0)
		result = self.translate_with_options(text, self.translation_options())
		func_progress(100)
		return result

	def get_cache_app_name(self):
		"""
		Devuelve la clave de cache para la aplicacion, idioma y motor actuales.
		"""
		try:
			app_name = globalVars.focusObject.appModule.appName
		except:
			app_name = "__global__"
		settings = self.frame.gestor_settings
		key = "{}_{}_{}".format(app_name, self.get_choice_lang_destino(), settings.choiceOnline)
		if settings.choiceOnline == 9:
			mode = getattr(settings, "openai_auth_mode", "api_key")
			model = getattr(settings, "openai_model_oauth" if mode == "chatgpt" else "openai_model_api", "auto")
			key += "_{}_{}".format(mode, model)
		return key

	def translate(self, text):
		"""Real-time translation keeps its fixed target and fails back to speech."""
		settings = self.frame.gestor_settings
		if not settings._enableTranslation:
			self._realtime_error_notice = None
			return text
		if not text.strip():
			return text
		appName = self.get_cache_app_name()
		if settings.chkCache:
			cached = settings._translationCache.setdefault(appName, {}).get(text)
			# Legacy adapters return the source on failure; retry these entries.
			if cached and cached != text:
				return cached
		try:
			translated = self.translate_with_options(text, self.translation_options())
		except Exception as error:
			# Incoming speech must remain audible, but no secrets/text in logs.
			logHandler.log.error("TranslateAdvanced: real-time translation failed; speaking original.")
			self._report_realtime_error(error, appName)
			return text
		self._realtime_error_notice = None
		if settings.chkCache and translated != text:
			settings._translationCache.setdefault(appName, {})[text] = translated
		return translated

	def _report_realtime_error(self, error: Exception, configuration: str) -> None:
		"""Ogłasza bezpieczny błąd poza tłumaczeniem, najwyżej co pół minuty."""
		now = time.monotonic()
		previous = getattr(self, "_realtime_error_notice", None)
		if previous and previous[0] == configuration and now - previous[1] < 30:
			return
		self._realtime_error_notice = (configuration, now)
		message = _("Tłumaczenie w locie nie powiodło się. Sprawdź wybrany silnik i jego ustawienia.")
		if isinstance(error, TranslationError):
			# Ten wyjątek zawiera wyłącznie komunikaty zaufanego adaptera.
			message += " " + _(str(error))
		speak = getattr(self.frame.gestor_settings, "_nvdaSpeak", None)
		if callable(speak):
			speak(speechSequence=[message], priority=None)

	def speak(self, speechSequence: SpeechSequence, priority: Spri = None):
		"""
		Genera una secuencia de habla y la traduce si es necesario.

		:param speechSequence: La secuencia de texto a hablar.
		:param priority: La prioridad de la secuencia de habla (opcional).
		:return: None
		"""
		if not self.frame.gestor_settings._enableTranslation:
			return self.frame.gestor_settings._nvdaSpeak(speechSequence=speechSequence, priority=priority)

		settings = self.frame.gestor_settings
		if settings.choiceOnline == 9:
			# Osobne żądanie dla każdej etykiety sumowało opóźnienia modelu.
			cached = settings._translationCache.get(self.get_cache_app_name(), {}) if settings.chkCache else None
			speechSequence = group_adjacent_text(speechSequence, cached=cached)

		newSpeechSequence = []
		newSpeechSequenceOrigen = []
		newSpeechSequenceDestino = []

		for val in speechSequence:
			if isinstance(val, str):
				v = self.translate(self.remove_surrogates(val))
				newSpeechSequence.append(v if v is not None else val)
				newSpeechSequenceOrigen.append(val)
				newSpeechSequenceDestino.append(v)
			else:
				newSpeechSequence.append(val)

		self.frame.gestor_settings._nvdaSpeak(speechSequence=newSpeechSequence, priority=priority)

		listaorigen = [elemento.rstrip() for elemento in newSpeechSequenceOrigen]
		listadestino = [elemento.rstrip() for elemento in newSpeechSequenceDestino]
		if listaorigen == listadestino:
			return

		temp = self.procesar_listas(newSpeechSequenceOrigen, newSpeechSequenceDestino)
		if temp['origen'] not in self.frame.gestor_settings.historialOrigen:
			self.frame.gestor_settings.historialOrigen.appendleft(temp['origen'])
			self.frame.gestor_settings.historialDestino.appendleft(temp['destino'])
			self.frame.gestor_settings._lastTranslatedText = temp['destino']
			if braille.handler._get_enabled():
				braille.handler.message(self.frame.gestor_settings._lastTranslatedText)

	def mySpeak(self, sequence, *args, **kwargs):
		self.frame.oldSpeak(sequence, *args, **kwargs)
		self.frame.gestor_settings.ultimo_texto = self.getSequenceText(sequence)

	def getSequenceText(self, sequence):
		return speechViewer.SPEECH_ITEM_SEPARATOR.join([x for x in sequence if isinstance(x, str)])
