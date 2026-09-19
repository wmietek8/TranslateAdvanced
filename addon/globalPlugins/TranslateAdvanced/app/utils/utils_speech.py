"""Przygotowanie krótkich grup tekstu do tłumaczenia wypowiedzi NVDA."""

from __future__ import annotations

from collections.abc import Iterable, Mapping


def group_adjacent_text(
    sequence: Iterable[object],
    *,
    cached: Mapping[str, str] | None = None,
    max_chars: int = 3000,
) -> list[object]:
    """Łączy sąsiedni tekst, zachowując komendy i zapamiętane fragmenty.

    Komendy NVDA i samodzielne białe znaki wyznaczają granice grup.
    Pojedynczy tekst dłuższy od limitu pozostaje bez zmian, aby jego
    podziałem zajął się adapter usługi. Koszt jest liniowy względem
    liczby elementów i łącznej długości tekstu.

    Niepoprawny typ argumentu powoduje TypeError, a niedodatni limit
    powoduje ValueError. Funkcja nie zmienia sekwencji ani pamięci.
    """
    if isinstance(sequence, (str, bytes)) or not isinstance(sequence, Iterable):
        raise TypeError("Oczekiwano sekwencji tekstów i komend NVDA.")
    if isinstance(max_chars, bool) or not isinstance(max_chars, int):
        raise TypeError("Limit znaków musi być liczbą całkowitą.")
    if max_chars <= 0:
        raise ValueError("Limit znaków musi być dodatni.")
    if cached is not None and not isinstance(cached, Mapping):
        raise TypeError("Pamięć tłumaczeń musi być mapowaniem.")
    cached = cached if cached is not None else {}
    result: list[object] = []
    fragments: list[str] = []
    length = 0

    for item in sequence:
        known = cached.get(item) if isinstance(item, str) else None
        if not isinstance(item, str) or not item.strip() or (known and known != item):
            if fragments:
                result.append("".join(fragments))
                fragments.clear()
                length = 0
            result.append(item)
            continue
        separator = (
            " "
            if fragments and not fragments[-1][-1].isspace() and not item[0].isspace()
            else ""
        )
        if fragments and length + len(separator) + len(item) > max_chars:
            result.append("".join(fragments))
            fragments.clear()
            length = 0
            separator = ""
        if separator:
            fragments.append(separator)
        fragments.append(item)
        length += len(separator) + len(item)
    if fragments:
        result.append("".join(fragments))
    return result
