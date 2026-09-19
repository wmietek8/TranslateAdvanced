# TranslateAdvanced 2026.6 — sprawdzenia i ograniczenia

Sprawdzenia wykonano na Windows 19 września 2026. Dokument opisuje wyniki prób, bez gwarancji bezbłędnego działania zewnętrznych usług w przyszłości.

## Testy automatyczne

- Python 3.13.15 i natywne wxPython 4.3.1 / wxWidgets 3.3.3: **499 testów oraz 148 podtestów zaliczonych**, bez pominięć.
- Python 3.11: **498 testów oraz 148 podtestów zaliczonych, jeden pominięty**. Pominięty test wymaga natywnego wxPython i został wykonany w przebiegu 3.13.
- Regresje 2026.6 obejmują integralność i limity rozmiarów pobierania, przekierowania HTTPS, odrzucanie dowiązań i nieoczekiwanych elementów ZIP, anulowanie także w kolejce, ponawianie po awarii, ponowne użycie komponentu, rozpoznawanie architektury, pierwszeństwo ręcznej ścieżki, zamykanie okna, skróty klawiaturowe oraz brak dodatkowych żądań po odmowie API. Sprawdzono granice czasu przerwy i reset po zmianie klucza, modelu lub metody.
- Nowe regresje 2026.5 odtworzyły osobne żądania dla sąsiednich fragmentów wypowiedzi oraz brak parametru rozumowania Sola. Sprawdzono puste dane, białe znaki, tożsamość i kolejność komend, pamięć, granice 3000 znaków, błędne typy, awarię usługi i niezmienioną drogę innych silników.
- Osiem nowych testów przed zmianami odtworzyło zgłoszone błędy. Następnie rozszerzono zestaw o migrację zapisanej sesji, anulowanie, spóźnione odpowiedzi, ponowne otwieranie, awarię katalogu, zmianę konta, odświeżenie tokenu, zapis katalogu i wybór silnika w oknie nadrzędnym.
- Testy uruchamiają kod dodatku; podmienione są granice NVDA, procesów zewnętrznych i sieci. Testy automatyczne nie czytają rzeczywistych danych konta ani schowka.
- Zachowano regresje dotyczące schowka, kierunku tłumaczenia, formatowania, długiego tekstu, kompletności odpowiedzi, TLS, przekierowań i innych silników.

Odtworzenie na Windows:

```text
uv run --no-project --python 3.13 --with pytest --with polib --with wxPython python -X utf8 -B -m pytest tests -q
uv run --no-project --python 3.11 --with pytest --with polib python -X utf8 -B -m pytest tests -q
uv run --no-project --python 3.13 --with pytest --with wxPython python -X utf8 -B tests/live_openai_ui_smoke.py
```

Pokrycie wykonywalnych linii w przebiegu 2026.6: instalator komponentu 95,9%, okno OpenAI 94,0%, klient Codex 89,7%, adapter API 97,5%, menedżer tłumaczeń 83,8%. Pokrycie linii nie zastępuje prób rzeczywistej usługi ani sprawdzenia obsługi przez użytkownika.

Kontrola Ruff dla importów i niezdefiniowanych nazw obejmuje instalator komponentu, nowe testy i próbę API oraz moduł grupowania. Nie ogłaszamy całego odziedziczonego projektu jako wolnego od wszystkich ostrzeżeń stylistycznych. Kontrola różnic Git sprawdza również białe znaki.

## Rzeczywiste próby 2026.6

- Pobrano oficjalne archiwum Windows x64 `rust-v0.155.0` z `openai/codex`, zgodne z przypiętymi metadanymi wydania. Kontrole SHA-256 archiwum i pliku wykonywalnego przeszły. Zapisano wyłącznie program potrzebny klientowi; dodatkowe narzędzia wykonywania komend i konfiguracji piaskownicy nie zostały rozpakowane. Kolejna próba korzysta z zapisanej kopii.
- Wyłączono wykrywanie systemowego Codexa i sprawdzono użycie zarządzanego komponentu: brak konta bez uruchamiania procesu, przygotowanie programu, start oficjalnego OAuth, anulowanie i zamknięcie procesu. Przeglądarka nie została otwarta.
- Na odizolowanej kopii samego dostępu istniejącego konta ten sam komponent potwierdził konto, pobrał pięć modeli i przetłumaczył `The door is open.` na `Drzwi są otwarte.`. Nie kopiowano tokenu odświeżania i nie zezwalano na jego odnowienie. Oryginalny plik konta pozostał identyczny, a profil próby usunięto po zamknięciu procesu.
- Próba rzeczywistego klucza API potwierdziła działanie katalogu modeli (HTTP 200), ale tłumaczenie zostało odrzucone przez usługę (HTTP 429, `credit_balance_exhausted`, `insufficient_quota`). Nie jest to wynik pozytywnego tłumaczenia ani dowód wygaśnięcia klucza.
- `tests/live_realtime_api.py` sprawdził pełną drogę mowy przy tej odmowie: pierwsza wypowiedź około 2,076 s z katalogiem, kolejna bez dodatkowego żądania i poniżej rozdzielczości raportu 0,1 ms. Został odczytany oryginał, a błąd nie trafił do pamięci przekładów. Nie zmieniono pliku kluczy, konfiguracji ani schowka. Te liczby opisują obsługę odmowy, nie szybkość tłumaczenia API.
- Powtarzalna próba po zapewnieniu dostępnego salda: `tests/live_realtime_api.py --api-file <apis.json> --index 0 --model auto --output <raport.json>`. Skrypt wysyła najwyżej trzy krótkie teksty testowe, a po odmowie sprawdza przerwę i kończy pracę. Raporty lokalne nie zawierają klucza ani surowych odpowiedzi błędów.

## Rzeczywiste pomiary 2026.5

Wykonano 18 tłumaczeń przez rzeczywiste konto dodatku: po dziewięć na Solu i Lunie, z syntetycznymi tekstami PL→EN, EN→PL i trzema etykietami jednej wypowiedzi. Każda próba startowała bez zapamiętanego tłumaczenia, a jej powtórzenie potwierdzało brak dodatkowego żądania HTTPS. Katalog przygotowano przed pomiarem mowy; trwało to odpowiednio 0,530 i 0,885 sekundy.

| Model | Najkrótszy czas | Mediana 9 prób | Najdłuższy czas | Trzy fragmenty jednej wypowiedzi |
| --- | --- | --- | --- | --- |
| gpt-5.6-sol | 1,588 s | 1,790 s | 3,930 s | 1,698 / 2,289 / 3,930 s |
| gpt-5.6-luna | 1,370 s | 1,885 s | 3,955 s | 2,418 / 2,268 / 3,955 s |

W próbie starego kodu ta sama trzyczęściowa wypowiedź zajęła 8,546 sekundy przy trzech kolejnych żądaniach. Samo wymuszenie braku rozumowania, bez łączenia tekstu, dało 6,167 sekundy. Nowa droga wysyła jedno żądanie. To mała próba, bez podstaw do ogólnego rankingu modeli lub obietnicy stałego czasu. Luna nie miała wyraźnej przewagi.

Sprawdzono komendę NVDA, białe znaki, historię oraz ponowny odczyt katalogu bez `model/list`. Próby użyły kopii samego dostępu, bez tokenu odświeżania. Oryginalne logowanie nie zmieniło się, a rzeczywisty schowek i proces NVDA nie były używane do pomiarów. Odtworzenie: `tests/live_realtime_oauth.py --auth-file <plik-konta-dodatku> --output <raport.json> --model gpt-5.6-sol --repetitions 3`.

## Dodatkowe próby wykonane dla 2026.4

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
- Nie potwierdzono udanego tłumaczenia na rzeczywistym kluczu API: próba została odrzucona z przyczyny rozliczeniowej. Droga poprawnej odpowiedzi, kierunki, pamięć i grupowanie mają testy z kontrolowaną granicą HTTPS. Nie wykonywano nowych rzeczywistych prób wszystkich pozostałych dostawców.
- Rzeczywisty komponent uruchomiono na Windows x64. Dobór wersji ARM64 i scenariusza 32-bitowego NVDA na 64-bitowym Windows sprawdzono w testach logiki; nie deklarujemy prób na fizycznym urządzeniu ARM64 lub w natywnym procesie x86.
- Tłumaczenie w locie nadal czeka na zewnętrzną usługę. Grupowanie nie łączy tekstów rozdzielonych komendami NVDA ani osobnych wypowiedzi; może więc pozostać kilka żądań. Nie wdrożono asynchronicznej przebudowy mowy ani gwarancji szybkości DeepL.
- Dla Sola i aliasu `gpt-5.6` ustawiono udokumentowane `reasoning.effort=none`: https://developers.openai.com/api/docs/models/gpt-5.6-sol. W realnej próbie usługa przyjęła ten parametr. Nie narzucamy go nieznanym modelom bez potwierdzenia obsługi.

## Paczka i publikacja

Paczka jest budowana przez SCons. `tests/audit_addon.py` sprawdza ZIP, wersję, zgodność wszystkich plików Pythona ze źródłami, składnię, polski katalog, pomoc PL/EN, licencję i oryginalnego autora. Audyt odrzuca pliki kont, kluczy, testów, logów i pamięci podręcznej; sprawdza też rzeczywiste wartości przekazanych lokalnie sekretów, nie wypisując ich.

Raporty prób kont i szczegółowe pokrycie pozostają lokalne. Publiczne wydanie zawiera paczkę dodatku i plik z jej sumą SHA-256. Wynik publikacji jest odnotowany w dzienniku prac.
