# Biblioteki dołączone do dodatku

`websockets` 17.1, autorzy: Aymeric Augustin i współtwórcy. Licencja BSD 3-Clause znajduje się w `websockets/LICENSE`. Oficjalny projekt: https://github.com/python-websockets/websockets. Dokumentacja: https://websockets.readthedocs.io/.

Dołączono niezmienione pliki `.py` z dystrybucji PyPI `websockets==17.1`, bez modułów binarnych. Pakiet wymaga Pythona 3.11 lub nowszego, zgodnie z obsługiwanymi wersjami NVDA. Własna przestrzeń nazw dodatku zapobiega zastępowaniu bibliotek innych rozszerzeń. Szybszy moduł binarny jest opcjonalny; dodatek korzysta z implementacji w Pythonie.

Kod dodatku wyłącza przekierowania, kompresję i logowanie treści. Łączy się bezpośrednio z `api.openai.com`, sprawdza TLS oraz ogranicza czas, rozmiar i liczbę połączeń. Systemowe serwery proxy nie są używane przez tę ścieżkę. Oryginalna licencja GPL dodatku i osobna licencja biblioteki pozostają zachowane.
