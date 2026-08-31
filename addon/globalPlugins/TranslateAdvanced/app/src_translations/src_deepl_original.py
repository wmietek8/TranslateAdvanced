# -*- coding: utf-8 -*-
# Modified by Axel (wmietek8), 2026, for the current DeepL API and NVDA runtime.
# Copyright (C) 2024 Hector J. Benitez Corredera <xebolax@gmail.com>
# Este archivo esta cubierto por la Licencia Publica General de GNU.
#
# Carga NVDA
import addonHandler
import logHandler
# Carga Python
import json
import re
import urllib.error
import urllib.request
from typing import Any

from ..utils.utils_short_translation import looks_like_english_message, postprocess_short_translation

# Carga traduccion
addonHandler.initTranslation()


class TranslatorDeepL:
	"""
	Silnik tlumaczen korzystajacy z oficjalnego API DeepL.
	Obsluguje wariant Free oraz Pro.
	"""

	BASE_URL_FREE = "https://api-free.deepl.com/v2"
	BASE_URL_PRO = "https://api.deepl.com/v2"

	def __init__(self) -> None:
		"""
		Inicjalizuje silnik DeepL.
		"""
		self.api_key: str | None = None
		self.base_url: str | None = None

	def _get_base_url(self, use_free_api: bool) -> str:
		"""
		Zwraca adres bazowy API DeepL.
		"""
		return self.BASE_URL_FREE if use_free_api else self.BASE_URL_PRO

	def _get_headers(self, api_key: str) -> dict[str, str]:
		"""
		Zwraca naglowki zgodne z aktualna autoryzacja DeepL.
		"""
		return {
			"Authorization": "DeepL-Auth-Key {}".format(api_key),
			"Content-Type": "application/json",
			"User-Agent": "TranslateAdvanced-NVDA/2024.09.19",
		}

	def _normalize_text(self, text: str | bytes) -> str:
		"""
		Normalizuje tekst przed wyslaniem do API.
		"""
		if isinstance(text, bytes):
			return text.decode("utf-8", "surrogatepass")
		if isinstance(text, str):
			return text
		raise TypeError(_("Tekst do tlumaczenia musi byc typu str albo bytes."))

	def _normalize_language_code(self, language: str) -> str:
		"""
		Normalizuje kod jezyka do formatu oczekiwanego przez DeepL.
		"""
		if not isinstance(language, str):
			raise TypeError(_("Kod jezyka musi byc typu str."))
		normalized = language.strip().replace("_", "-")
		if not normalized:
			raise ValueError(_("Kod jezyka nie moze byc pusty."))
		return normalized.upper()

	def _read_json_response(self, response: Any) -> dict[str, Any]:
		"""
		Czyta odpowiedz JSON z API DeepL.
		"""
		return json.loads(response.read().decode("utf-8"))

	def _read_http_error(self, error: urllib.error.HTTPError) -> str:
		"""
		Czyta tresc bledu HTTP bez ujawniania klucza API.
		"""
		try:
			body = error.read().decode("utf-8", errors="replace")
		except Exception:
			body = ""
		if body:
			return "{} {}: {}".format(error.code, error.reason, body)
		return "{} {}".format(error.code, error.reason)

	def _get_context(self, text: str) -> str | None:
		"""
		Zwraca kontekst pomagajacy unikac parafraz w krotkich komunikatach.
		"""
		if len(text) > 500:
			return None
		return (
			"This is a short screen reader message from a game or user interface. "
			"Translate literally. Preserve tense, event state, numbers, commands, "
			"player names, place names, item names and mixed-language names. "
			"In game and chat UI text, translate 'messages' as Polish 'wiadomości', "
			"not 'komunikaty'. Translate 'will be read' as 'będą odczytywane', "
			"not 'będą ogłaszane'. Translate 'exit' and 'quit' as 'wyjść' or "
			"'zamknąć', not 'wylogować'."
		)

	def _restore_trailing_whitespace(self, source_text: str, translated_text: str) -> str:
		"""
		Przywraca koncowe biale znaki z tekstu zrodlowego.
		"""
		return translated_text + source_text[len(source_text.rstrip()):]

	def _postprocess_translation(self, source_text: str, translated_text: str, target_lang: str) -> str:
		"""
		Poprawia znane parafrazy, ktore zmieniaja sens krotkich komunikatow gry.
		"""
		target = target_lang.strip().upper()
		if not target.startswith("PL"):
			return translated_text
		stripped_source = source_text.strip()
		game_ui_exact = {
			"Messages will be read": "Wiadomości będą odczytywane",
			"Messages will no longer be read": "Wiadomości nie będą już odczytywane",
		}
		exact_translation = game_ui_exact.get(stripped_source)
		if exact_translation is not None:
			return self._restore_trailing_whitespace(source_text, exact_translation)
		if not re.search(r"\bhas been created[.!?]*\s*$", source_text.strip(), re.IGNORECASE):
			return translated_text
		match = re.search(r"\s+już działa([.!?]*)\s*$", translated_text, re.IGNORECASE)
		if match is None:
			return translated_text
		punctuation = match.group(1) or "!"
		return translated_text[:match.start()].rstrip() + " zostało utworzone" + punctuation

	def translate_deepl(
		self,
		text: str | bytes,
		api_key: str,
		use_free_api: bool = True,
		source_lang: str = "auto",
		target_lang: str = "es",
	) -> str:
		"""
		Tlumaczy tekst przez oficjalne API DeepL.
		"""
		if not api_key:
			raise ValueError(_("Se requiere una clave de API para DeepL."))

		self.api_key = api_key
		self.base_url = self._get_base_url(use_free_api)
		normalized_text = self._normalize_text(text)
		payload: dict[str, Any] = {
			"text": [normalized_text],
			"target_lang": self._normalize_language_code(target_lang),
			"preserve_formatting": True,
			"split_sentences": "nonewlines",
		}
		context = self._get_context(normalized_text)
		if context:
			payload["context"] = context
		if source_lang.lower() != "auto":
			payload["source_lang"] = self._normalize_language_code(source_lang)
		elif looks_like_english_message(normalized_text):
			payload["source_lang"] = "EN"

		url = "{}/translate".format(self.base_url)
		data = json.dumps(payload).encode("utf-8")
		req = urllib.request.Request(
			url,
			data=data,
			headers=self._get_headers(self.api_key),
			method="POST",
		)

		try:
			with urllib.request.urlopen(req, timeout=20) as response:
				response_json = self._read_json_response(response)
				translated_text = response_json["translations"][0]["text"]
				translated_text = self._postprocess_translation(normalized_text, translated_text, target_lang)
				return postprocess_short_translation(normalized_text, translated_text, target_lang)
		except urllib.error.HTTPError as error:
			logHandler.log.error(
				_("Error en la traduccion DeepL: {0}").format(self._read_http_error(error)),
			)
			return normalized_text
		except Exception as error:
			logHandler.log.error(_("Error en la traduccion DeepL: {0}").format(str(error)))
			return normalized_text

	def get_usage(self, api_key: str, use_free_api: bool = False) -> str:
		"""
		Zwraca aktualne zuzycie znakow w API DeepL.
		"""
		if not api_key:
			raise ValueError(_("Se requiere una clave de API para DeepL."))

		self.api_key = api_key
		self.base_url = self._get_base_url(use_free_api)
		url = "{}/usage".format(self.base_url)
		req = urllib.request.Request(
			url,
			headers=self._get_headers(self.api_key),
			method="GET",
		)

		try:
			with urllib.request.urlopen(req, timeout=20) as response:
				response_json = self._read_json_response(response)
				character_count = response_json.get(
					"api_key_character_count",
					response_json.get("character_count", 0),
				)
				character_limit = response_json.get(
					"api_key_character_limit",
					response_json.get("character_limit", 0),
				)
				return _("DeepL - uso: {0} / {1}").format(character_count, character_limit)
		except urllib.error.HTTPError as error:
			error_text = self._read_http_error(error)
			logHandler.log.error(_("Error obteniendo uso de DeepL: {0}").format(error_text))
			return _("Error obteniendo uso de DeepL: {0}").format(error_text)
		except Exception as error:
			logHandler.log.error(_("Error obteniendo uso de DeepL: {0}").format(str(error)))
			return _("Error obteniendo uso de DeepL: {0}").format(str(error))
