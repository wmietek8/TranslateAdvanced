"""Ograniczona kolejka tłumaczeń bez zatrzymywania głównego wątku NVDA."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from threading import Condition, Event, Thread
from typing import Any


@dataclass
class _Work:
    key: Hashable
    generation: int
    run: Callable[[], Any] | None = field(repr=False)
    started: bool = False
    ready: bool = False
    result: Any = field(default=None, repr=False)
    error: Exception | None = field(default=None, repr=False)
    users: int = 0


class SpeechQueue:
    """Pracuje w tle, oddaje wyniki w kolejności i scala identyczne żądania.

    ``dispatch`` musi skierować funkcję do głównego wątku NVDA. Metody
    submit, cancel, flush i close wywołuje wyłącznie ten wątek. Wątki robocze
    nie odczytują konfiguracji, pamięci tłumaczeń ani obiektów dostępności.
    Pamięć i kolejka są ograniczone; koszt obsługi wynosi O(max_pending).
    """

    def __init__(
        self,
        dispatch: Callable[[Callable[[], None]], None],
        *,
        workers: int = 2,
        max_pending: int = 32,
    ) -> None:
        """Przygotowuje kolejkę; wątki powstają przy pierwszym zleceniu."""
        if not callable(dispatch):
            raise TypeError("Funkcja przekazywania wyników musi być wywoływalna.")
        if type(workers) is not int or type(max_pending) is not int:
            raise TypeError("Limity kolejki muszą być liczbami całkowitymi.")
        if not 1 <= workers <= 4 or not workers <= max_pending <= 128:
            raise ValueError("Niepoprawne limity kolejki tłumaczeń.")
        self._dispatch = dispatch
        self._workers = workers
        self._max_pending = max_pending
        self._condition = Condition()
        self._jobs: deque[tuple[_Work, Callable]] = deque()
        self._work: dict[Hashable, _Work] = {}
        self._threads: list[Thread] = []
        self._generation = 0
        self._cancel_event = Event()
        self._closed = False

    @property
    def cancel_event(self) -> Event:
        """Zwraca znacznik pozwalający przerwać kolejne części aktualnej pracy."""
        with self._condition:
            return self._cancel_event

    @property
    def pending(self) -> bool:
        """Informuje, czy wcześniejsze wypowiedzi oczekują na przekazanie."""
        with self._condition:
            return bool(self._jobs)

    def submit(
        self,
        key: Hashable,
        run: Callable[[], Any],
        deliver: Callable[[Any, Exception | None], None],
    ) -> bool:
        """Zleca pracę lub zwraca False po zamknięciu bądź zapełnieniu kolejki."""
        if not callable(run) or not callable(deliver):
            raise TypeError("Praca i obsługa wyniku muszą być funkcjami.")
        hash(key)
        with self._condition:
            if self._closed or len(self._jobs) >= self._max_pending:
                return False
            work = self._work.get(key)
            if work is None:
                work = _Work(key, self._generation, run)
                self._work[key] = work
            work.users += 1
            self._jobs.append((work, deliver))
            while len(self._threads) < self._workers:
                thread = Thread(target=self._worker, daemon=True,
                                name="TranslateAdvanced-speech")
                self._threads.append(thread)
                thread.start()
            self._condition.notify_all()
        return True

    def cancel(self) -> None:
        """Unieważnia stare wypowiedzi; późny wynik nie zostanie odczytany."""
        with self._condition:
            self._cancel_event.set()
            self._cancel_event = Event()
            self._generation += 1
            self._jobs.clear()
            self._work.clear()
            self._condition.notify_all()

    def flush(self, error: Exception) -> None:
        """Oddaje wszystkie oczekujące wypowiedzi ścieżką awaryjną, w kolejności."""
        with self._condition:
            deliveries = [deliver for _, deliver in self._jobs]
            self.cancel()
        for deliver in deliveries:
            deliver(None, error)

    def close(self) -> None:
        """Zamyka kolejkę bez oczekiwania na serwer podczas wyłączania NVDA."""
        with self._condition:
            self._closed = True
            self.cancel()

    def _worker(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(
                    lambda: self._closed or any(not work.started for work in self._work.values())
                )
                if self._closed:
                    return
                work = next(work for work in self._work.values() if not work.started)
                work.started = True
                run, work.run = work.run, None
            try:
                result, error = run(), None
            except Exception as failure:
                result, error = None, failure
            finally:
                run = None
            with self._condition:
                if self._closed or work.generation != self._generation:
                    continue
                work.result, work.error, work.ready = result, error, True
            try:
                self._dispatch(self._drain)
            except Exception:
                # NVDA może już zamykać pętlę zdarzeń; niczego nie czytamy z tła.
                self.close()

    def _drain(self) -> None:
        while True:
            with self._condition:
                if not self._jobs or not self._jobs[0][0].ready or self._closed:
                    return
                work, deliver = self._jobs.popleft()
                work.users -= 1
                if not work.users:
                    self._work.pop(work.key, None)
            deliver(work.result, work.error)
