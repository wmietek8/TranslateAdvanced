# -*- coding: utf-8 -*-
# Added by Axel (wmietek8), 2026, for short-response compatibility.
"""Korekta krotkich komunikatow gry i interfejsu po tlumaczeniu."""

from __future__ import annotations

import re

_SHORT_MESSAGE_LIMIT = 260

_ENGLISH_HINTS = (
	"a",
	"an",
	"and",
	"are",
	"be",
	"been",
	"created",
	"exit",
	"has",
	"have",
	"is",
	"no",
	"not",
	"quit",
	"read",
	"sure",
	"the",
	"want",
	"will",
)

_POLISH_EXACT_GAME_UI = {
	"Messages will be read": "Wiadomości będą odczytywane",
	"Messages will no longer be read": "Wiadomości nie będą już odczytywane",
	"Are you sure you want to exit?": "Czy na pewno chcesz wyjść?",
	"Are you sure you want to quit?": "Czy na pewno chcesz wyjść?",
	"Do you want to exit?": "Czy chcesz wyjść?",
	"Do you want to quit?": "Czy chcesz wyjść?",
}


def _language_is_polish(target_lang: str | None) -> bool:
	"""Sprawdza, czy kod jezyka oznacza polski."""
	if not isinstance(target_lang, str):
		return False
	return target_lang.strip().upper().replace("_", "-").startswith("PL")


def _is_short_text(text: str) -> bool:
	"""Sprawdza, czy tekst wyglada jak krotki komunikat."""
	return 0 < len(text.strip()) <= _SHORT_MESSAGE_LIMIT


def _restore_source_whitespace(source_text: str, translated_core: str) -> str:
	"""Przywraca biale znaki z poczatku i konca tekstu zrodlowego."""
	leading = source_text[:len(source_text) - len(source_text.lstrip())]
	trailing = source_text[len(source_text.rstrip()):]
	return leading + translated_core + trailing


def _replace_messages_terms(source_text: str, translated_text: str) -> str:
	"""Poprawia termin messages w krotkich komunikatach gry/czatu."""
	if re.search(r"\bmessages?\b", source_text, re.IGNORECASE) is None:
		return translated_text
	replacements = (
		(r"\b[Kk]omunikaty\b", "Wiadomości"),
		(r"\b[Kk]omunikatów\b", "wiadomości"),
		(r"\b[Kk]omunikatom\b", "wiadomościom"),
		(r"\b[Kk]omunikatami\b", "wiadomościami"),
		(r"\b[Kk]omunikatach\b", "wiadomościach"),
	)
	result = translated_text
	for pattern, replacement in replacements:
		result = re.sub(pattern, replacement, result)
	return result


def _replace_read_terms(source_text: str, translated_text: str) -> str:
	"""Poprawia parafrazy zwiazane z odczytywaniem komunikatow."""
	source = source_text.strip()
	if re.search(r"\bwill\s+no\s+longer\s+be\s+read\b", source, re.IGNORECASE):
		return re.sub(
			r"\bnie\s+będą\s+już\s+(?:ogłaszane|czytane)\b",
			"nie będą już odczytywane",
			translated_text,
			flags=re.IGNORECASE,
		)
	if re.search(r"\bwill\s+be\s+read\b", source, re.IGNORECASE):
		return re.sub(
			r"\bbędą\s+(?:ogłaszane|czytane)\b",
			"będą odczytywane",
			translated_text,
			flags=re.IGNORECASE,
		)
	return translated_text


def _replace_created_terms(source_text: str, translated_text: str) -> str:
	"""Poprawia parafraze has been created jako juz dziala."""
	if not re.search(r"\bhas\s+been\s+created[.!?]*\s*$", source_text.strip(), re.IGNORECASE):
		return translated_text
	match = re.search(r"\s+już działa([.!?]*)\s*$", translated_text, re.IGNORECASE)
	if match is None:
		return translated_text
	punctuation = match.group(1) or "!"
	return translated_text[:match.start()].rstrip() + " zostało utworzone" + punctuation


def _replace_playtime_terms(source_text: str, translated_text: str) -> str:
	"""Poprawia playtime, ktore silniki czasem tlumacza jako odtwarzanie."""
	if re.search(r"\bplay\s*time\b|\bplaytime\b", source_text, re.IGNORECASE) is None:
		return translated_text
	result = re.sub(r"\bczas odtwarzania\b", "czas gry", translated_text, flags=re.IGNORECASE)
	result = re.sub(r"\bodtwarzania\b", "czasu gry", result, flags=re.IGNORECASE)
	return result


def _replace_exit_terms(source_text: str, translated_text: str) -> str:
	"""Poprawia exit/quit, gdy silnik myli wyjscie z wylogowaniem."""
	source = source_text.strip()
	if re.search(r"\b(?:log\s*out|sign\s*out|logout|signout)\b", source, re.IGNORECASE):
		return translated_text
	if re.search(r"\b(?:exit|quit)\b", source, re.IGNORECASE) is None:
		return translated_text

	result = translated_text
	result = re.sub(
		r"\b[Cc]zy\s+na\s+pewno\s+chcesz\s+się\s+wylogować\?",
		"Czy na pewno chcesz wyjść?",
		result,
		flags=re.IGNORECASE,
	)
	result = re.sub(r"\bwylogować\s+się\b", "wyjść", result, flags=re.IGNORECASE)
	result = re.sub(r"\bwylogować\b", "wyjść", result, flags=re.IGNORECASE)
	result = re.sub(r"\bwylogowania\b", "wyjścia", result, flags=re.IGNORECASE)
	return result


def looks_like_english_message(text: str) -> bool:
	"""Sprawdza, czy krotki komunikat prawdopodobnie jest po angielsku."""
	if not isinstance(text, str) or not _is_short_text(text):
		return False
	words = re.findall(r"[A-Za-z]+", text.lower())
	if not words:
		return False
	hit_count = sum(1 for word in words if word in _ENGLISH_HINTS)
	return hit_count >= 1 and len(words) <= 40


def postprocess_short_translation(source_text: str, translated_text: str, target_lang: str | None) -> str:
	"""Poprawia typowe bledy maszynowego tlumaczenia krotkich komunikatow."""
	if not isinstance(source_text, str) or not isinstance(translated_text, str):
		return translated_text
	if not _language_is_polish(target_lang) or not _is_short_text(source_text):
		return translated_text

	stripped_source = source_text.strip()
	exact_translation = _POLISH_EXACT_GAME_UI.get(stripped_source)
	if exact_translation is not None:
		return _restore_source_whitespace(source_text, exact_translation)

	result = translated_text
	result = _replace_messages_terms(source_text, result)
	result = _replace_read_terms(source_text, result)
	result = _replace_created_terms(source_text, result)
	result = _replace_playtime_terms(source_text, result)
	result = _replace_exit_terms(source_text, result)
	return result
