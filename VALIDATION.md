# TranslateAdvanced 2026.4 — sprawdzenia i ograniczenia

Sprawdzenia wykonano na Windows 19 września 2026. Dokument opisuje wyniki prób, bez gwarancji bezbłędnego działania zewnętrznych usług w przyszłości.

## Testy automatyczne

- Python 3.13.15 i natywne wxPython 4.3.1 / wxWidgets 3.3.3: **376 testów oraz 144 podtesty zaliczone**, bez pominięć.
- Python 3.11: pełny przebieg przed ostatnim dodatkowym testem — **374 testy oraz 144 podtesty zaliczone, jeden pominięty**. Po dodaniu ostatniego testu ponownie sprawdzono cały plik ustawień: **57 zaliczonych, jeden pominięty**. Pominięty test wymaga natywnego wxPython i został wykonany w przebiegu 3.13.
- Osiem nowych testów przed zmianami odtworzyło zgłoszone błędy. Następnie rozszerzono zestaw o migrację zapisanej sesji, anulowanie, spóźnione odpowiedzi, ponowne otwieranie, awarię katalogu, zmianę konta, odświeżenie tokenu, zapis katalogu i wybór silnika w oknie nadrzędnym.
- Testy uruchamiają kod dodatku; podmienione są granice NVDA, procesów zewnętrznych i sieci. Testy automatyczne nie czytają rzeczywistych danych konta ani schowka.
- Zachowano regresje dotyczące schowka, kierunku tłumaczenia, formatowania, długiego tekstu, kompletności odpowiedzi, TLS, przekierowań i innych silników.

Odtworzenie na Windows:

```text
uv run --no-project --python 3.13 --with pytest --with polib --with wxPython python -X utf8 -B -m pytest tests -q
uv run --no-project --python 3.11 --with pytest --with polib python -X utf8 -B -m pytest tests -q
uv run --no-project --python 3.13 --with pytest --with wxPython python -X utf8 -B tests/live_openai_ui_smoke.py
```

Zmierzono pokrycie wykonywalnych linii dla 375 testów poprzedzających ostatni dodatkowy przypadek zapisu metody logowania: okno OpenAI 94,2%, klient Codex 89,5%, transport odpowiedzi OAuth 90,3%, menedżer tłumaczeń 81,8%. Pokrycie linii nie zastępuje prób rzeczywistej usługi ani sprawdzenia obsługi przez użytkownika.

Kontrola importów i niezdefiniowanych nazw obejmuje zmieniane moduły okna/klienta oraz nową próbę mowy; `_` jest dostarczane przez NVDA. Nie ogłaszamy całego odziedziczonego projektu jako wolnego od wszystkich ostrzeżeń stylistycznych. Kontrola różnic Git sprawdza również białe znaki.

## Rzeczywiste próby

- `live_codex_smoke.py`: tłumaczenia PL↔EN z wyborem `auto`, `gpt-6-astra` oraz jawnie wskazanym `gpt-5.6-sol`. Każdy wynik był niepusty i różnił się od tekstu źródłowego.
- `live_realtime_oauth.py`: rzeczywista droga `GestorTranslate.speak` → wybrany model OAuth → tekst przekazany do granicy mowy NVDA. PL→EN i EN→PL dla `gpt-5.6-sol`; zachowane komendy mowy oraz odstępy. Ponowna wypowiedź użyła pamięci tłumaczeń. Ponownie utworzony klient odzyskał katalog z dysku bez ponownego `model/list`.
- `live_openai_ui_smoke.py`: natywne, ukryte kontrolki wx/Windows. Potwierdzono typ `wx.Choice`, styl `CBS_DROPDOWNLIST` i brak podrzędnego pola `Edit`, nazwy dostępności, niezależne wybory modeli oraz przywrócenie tłumaczenia po zamknięciu.
- `live_codex_login_smoke.py`: start oficjalnego logowania i jego anulowanie w osobnym profilu. Nowe parametry strony powitalnej zostały przyjęte, a proces pomocniczy poprawnie zamknięty. Przeglądarka nie została otwarta.
- Próby tłumaczenia użyły odizolowanej kopii samego dostępu konta dodatku. Nie kopiowano ani nie obracano tokenu odświeżania. Suma pliku oryginalnego konta pozostała taka sama.
- Próby tej wersji nie odczytywały ani nie zmieniały rzeczywistego schowka i nie przeładowywały działającego NVDA.

## Granice sprawdzenia

- Nie przeprowadzono odsłuchu gestu wewnątrz działającego procesu NVDA. Przechwycenie tekstu na granicy mowy nie jest odsłuchem syntezatora. Nową wersję trzeba zainstalować i uruchomić NVDA ponownie.
- Nie przeprowadzono pełnego nowego logowania użytkownika przez przeglądarkę. Sprawdzenie startu/anulowania oraz istniejącego dostępu nie zastępuje takiej próby.
- `appBrand=chatgpt` wybiera oficjalną stronę powitalną ChatGPT. Ekran zgody, klient OAuth i ewentualna konfiguracja organizacji nadal należą do OpenAI/Codexa; nie obiecujemy usunięcia nazwy Codex z każdego ekranu.
- Tryb konta korzysta z eksperymentalnego, nieudokumentowanego publicznie transportu tłumaczeń ChatGPT/Codex. Oficjalny app-server obsługuje konto i modele; tłumacz nie uruchamia wątku agenta ani narzędzi modelu. Dokumentacja: https://learn.chatgpt.com/docs/app-server.
- Nie wykonywano nowych płatnych wywołań kluczem API OpenAI ani rzeczywistych prób wszystkich pozostałych dostawców. Zachowano ich testy deterministyczne.
- Tłumaczenie w locie nadal czeka na zewnętrzny model. W końcowej próbie dwóch zdań `gpt-5.6-sol` potrzebował 2,747 i 2,927 sekundy na pierwsze tłumaczenie. Czas i jakość zależą od usługi, modelu i tekstu.

## Paczka i publikacja

Paczka jest budowana przez SCons. `tests/audit_addon.py` sprawdza ZIP, wersję, zgodność wszystkich plików Pythona ze źródłami, składnię, polski katalog, pomoc PL/EN, licencję i oryginalnego autora. Audyt odrzuca pliki kont, kluczy, testów, logów i pamięci podręcznej; sprawdza też rzeczywiste wartości przekazanych lokalnie sekretów, nie wypisując ich.

Raporty prób kont i szczegółowe pokrycie pozostają lokalne. Publiczne wydanie zawiera paczkę dodatku i plik z jej sumą SHA-256. Wynik publikacji jest odnotowany w dzienniku prac.
