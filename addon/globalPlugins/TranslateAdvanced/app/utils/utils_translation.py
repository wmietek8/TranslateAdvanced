# -*- coding: utf-8 -*-
# Added by Axel (wmietek8), 2026, for NVDA translation compatibility.
"""Fallback tlumaczen dodatku TranslateAdvanced."""

from __future__ import annotations

import builtins
import gettext
import inspect
import locale
from pathlib import Path
from typing import Callable

import addonHandler
import languageHandler

_ORIGINAL_INIT_TRANSLATION: Callable | None = None
_TRANSLATIONS: dict[tuple[str, ...], gettext.NullTranslations] = {}
_ENGLISH_TRANSLATION: gettext.NullTranslations | None = None


def _get_locale_dir() -> Path:
	"""Zwraca katalog locale dodatku."""
	return Path(__file__).resolve().parents[4] / "locale"


def _get_addon_dir() -> Path:
	"""Zwraca katalog glowny dodatku."""
	return Path(__file__).resolve().parents[4]


def _add_language_candidate(candidates: list[str], language: str | None) -> None:
	"""Dodaje kod jezyka i jego wariant bazowy do listy kandydatow."""
	if not language:
		return
	language = language.replace("-", "_").split(".", 1)[0]
	if not language or language.lower() in {"windows", "system", "default"}:
		return
	if language not in candidates:
		candidates.append(language)
	base_language = language.split("_", 1)[0]
	if base_language and base_language not in candidates:
		candidates.append(base_language)


def _get_language_candidates() -> tuple[str, ...]:
	"""Zwraca jezyki NVDA/systemu zakonczone angielskim fallbackiem."""
	candidates: list[str] = []
	try:
		nvda_language = languageHandler.getLanguage()
	except Exception:
		nvda_language = None
	_add_language_candidate(candidates, nvda_language)
	use_system_language = not nvda_language or str(nvda_language).lower() in {"windows", "system", "default"}
	if use_system_language:
		try:
			_add_language_candidate(candidates, languageHandler.getWindowsLanguage())
		except Exception:
			pass
		try:
			_add_language_candidate(candidates, locale.getlocale()[0])
		except Exception:
			pass
	_add_language_candidate(candidates, "en")
	return tuple(candidates)


def _get_english_translation() -> gettext.NullTranslations:
	"""Zwraca angielski katalog tlumaczen."""
	global _ENGLISH_TRANSLATION
	if _ENGLISH_TRANSLATION is None:
		_ENGLISH_TRANSLATION = gettext.translation(
			"nvda",
			localedir=str(_get_locale_dir()),
			languages=["en"],
			fallback=True,
		)
	return _ENGLISH_TRANSLATION


def _get_current_translation() -> gettext.NullTranslations:
	"""Zwraca katalog tlumaczen dla aktualnego jezyka NVDA lub systemu."""
	candidates = _get_language_candidates()
	translation = _TRANSLATIONS.get(candidates)
	if translation is None:
		translation = gettext.translation(
			"nvda",
			localedir=str(_get_locale_dir()),
			languages=list(candidates),
			fallback=True,
		)
		_TRANSLATIONS[candidates] = translation
	return translation


def translate(message: str) -> str:
	"""Tlumaczy komunikat dodatku z fallbackiem do angielskiego."""
	translated = _get_current_translation().gettext(message)
	if translated != message:
		return translated
	english_translation = _get_english_translation().gettext(message)
	if english_translation != message:
		return english_translation
	return message


def _wrap_with_english_fallback(primary_gettext: Callable[[str], str]) -> Callable[[str], str]:
	"""Tworzy funkcje tlumaczaca z fallbackiem do angielskiego."""
	english = _get_english_translation().gettext

	def translate_with_fallback(message: str) -> str:
		translated = primary_gettext(message)
		if translated != message:
			return translated
		addon_translation = translate(message)
		if addon_translation != message:
			return addon_translation
		english_translation = english(message)
		if english_translation != message:
			return english_translation
		return message

	return translate_with_fallback


def _is_addon_module(module_globals: dict) -> bool:
	"""Sprawdza, czy slownik globalny nalezy do modulu TranslateAdvanced."""
	module_file = module_globals.get("__file__")
	if not module_file:
		return False
	try:
		Path(module_file).resolve().relative_to(_get_addon_dir())
	except ValueError:
		return False
	except Exception:
		return False
	return True


def install_module_translation(module_globals: dict) -> None:
	"""Instaluje lokalna funkcje _ dla modulu dodatku."""
	if _is_addon_module(module_globals):
		module_globals["_"] = translate


def _install_caller_translation() -> None:
	"""Instaluje lokalna funkcje _ w module, ktory wywolal initTranslation."""
	frame = inspect.currentframe()
	if frame is None:
		return
	caller = frame.f_back.f_back if frame.f_back and frame.f_back.f_back else None
	if caller is None:
		return
	install_module_translation(caller.f_globals)


def _install_builtins_translation(primary_gettext: Callable[[str], str]) -> None:
	"""Instaluje bezpieczny fallback w builtins._."""
	builtins._ = _wrap_with_english_fallback(primary_gettext)


def install_translation_fallback() -> None:
	"""Instaluje fallback i lokalne tlumaczenia modulow dodatku."""
	global _ORIGINAL_INIT_TRANSLATION
	if _ORIGINAL_INIT_TRANSLATION is not None:
		return

	_ORIGINAL_INIT_TRANSLATION = addonHandler.initTranslation

	def init_translation_with_fallback(*args, **kwargs):
		result = _ORIGINAL_INIT_TRANSLATION(*args, **kwargs)
		primary_gettext = getattr(builtins, "_", lambda message: message)
		_install_builtins_translation(primary_gettext)
		_install_caller_translation()
		return result

	addonHandler.initTranslation = init_translation_with_fallback
	addonHandler.initTranslation()
	install_module_translation(globals())
