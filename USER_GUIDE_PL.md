# TranslateAdvanced 2026.4: konto ChatGPT, modele i tłumaczenie w locie

To społecznościowy fork dodatku autorstwa Héctora J. Beníteza Corredera (hxebolax), rozwijany przez Axela (wmietek8). Oryginalne autorstwo i licencja GNU GPL v2 pozostają zachowane. Kod źródłowy: https://github.com/wmietek8/TranslateAdvanced. Szczegóły zmian są w `MODIFICATIONS.md`.

## Instalacja bez tracenia obecnych ustawień

Otwórz paczkę `TranslateAdvanced-2026.4.nvda-addon` i potwierdź aktualizację w NVDA. Uruchom NVDA ponownie dopiero po zakończeniu instalacji. Nie musisz usuwać starego dodatku, istniejących kluczy DeepL ani konfiguracji.

Sama paczka nie zawiera kluczy API ani zalogowanego konta. Przekazanie jej znajomym nie przekazuje dostępu do Twoich usług. Każdy konfiguruje swoje konto lub swój klucz.

## Polski na angielski i angielski na polski

1. W menu NVDA otwórz ustawienia Traductor Avanzado / Tłumacza zaawansowanego.
2. Zostaw wybrany własny silnik, np. **DeepL API Pro**, oraz jego działający klucz.
3. Włącz automatyczną zamianę języka i ustaw język główny na **polski**, a alternatywny na **angielski**. Korzystamy z istniejących ustawień głównego i alternatywnego języka; nie ma drugiej, ukrytej pary.
4. Skopiuj wiadomość i naciśnij **NVDA+Shift+C**. Klawiszem NVDA może być Insert albo Caps Lock, zależnie od Twojej konfiguracji.
5. Po otrzymaniu odpowiedzi dodatek najpierw zastępuje schowek gotowym tłumaczeniem, a następnie przekazuje dokładnie ten sam tekst do wypowiedzenia przez NVDA. Możesz od razu wkleić go przez Ctrl+V.

Przykład: `Siema, jak się czujesz?` zostaje przetłumaczone na angielski. Angielska wiadomość `Hello, how are you?` trafia natomiast na polski. Inny wykryty język trafia na język główny. Po wyłączeniu automatycznej zamiany używany jest zwykły język docelowy wybranego silnika.

**Nie trzeba wyłączać tłumaczenia w locie NVDA+Shift+T przed użyciem schowka.** Tłumaczenie schowka nie przestawia języka przychodzących wiadomości, a wypowiadany wynik nie jest wysyłany ponownie do tłumacza.

Ponowne naciśnięcie NVDA+Shift+C podczas oczekiwania anuluje tę operację. Trwającego żądania HTTP nie zawsze można zatrzymać po stronie usługi, ale jego spóźniona odpowiedź nie trafi do schowka. Usługa może naliczyć opłatę również za anulowane żądanie.

Jeżeli w międzyczasie skopiujesz coś nowego, dodatek zachowa nową zawartość schowka zamiast nadpisywać ją starą odpowiedzią. Błąd sieci, brak klucza lub niepełna odpowiedź również nie powinny zastępować schowka błędem ani udawać udanego tłumaczenia.

### Jak rozpoznawany jest język

- **DeepL API Free / Pro:** język pochodzi z odpowiedzi samego DeepL (`detected_source_language`). Gdy trzeba zmienić kierunek, drugi raz tłumaczony jest oryginał, nie wynik pierwszego tłumaczenia. Nie ma zapytania do detektora Google. W zależności od kierunku mogą być potrzebne dwa żądania DeepL; oba mogą zostać rozliczone przez usługę.
- **OpenAI:** model dostaje regułę wyboru kierunku razem z tekstem. Wynik jest sprawdzany przed użyciem. Bardzo krótkie albo wielojęzyczne wiadomości nadal mogą zostać rozpoznane niejednoznacznie — to ograniczenie rozpoznawania języka, a nie gwarancja bezbłędnego przekładu.
- **Silniki Google:** rozpoznawanie pozostaje w usłudze Google.
- **LibreTranslate, Microsoft i nieoficjalny DeepL:** automatyczny kierunek schowka nie jest w tej wersji obsługiwany. Wyłącz automatyczną zamianę i wybierz stały język docelowy albo użyj DeepL API/OpenAI. Dodatek nie wysyła tekstu ukradkiem do innego dostawcy.

Nowa wspólna ścieżka obsługuje tekst do **24 000 znaków**. Dłuższy tekst trzeba podzielić. Dłuższe żądania OpenAI są wewnętrznie tłumaczone w mniejszych fragmentach; wynik trafia do schowka dopiero po powodzeniu wszystkich fragmentów. Powtarzające się identyczne fragmenty są wykorzystywane ponownie tylko w obrębie tej jednej operacji. Błąd dowolnego fragmentu nie powoduje wklejenia niepełnego tłumaczenia. Granica 3000 znaków nie przełącza już schowka na Google. Zmiana silnika dotyczy też tłumaczenia w oknie dodatku i plików; osobne funkcje rozpoznawania języka oraz pobierania nagrania Google TTS nie są tłumaczeniem tekstu przez wybrany silnik.

## OpenAI z kluczem API

1. W istniejącym menedżerze kluczy API dodaj klucz usługi OpenAI i wybierz go.
2. Wybierz silnik **OpenAI (API / ChatGPT OAuth)**.
3. Otwórz jego dodatkowe ustawienia. W polu uwierzytelniania wybierz **klucz API**.
4. Użyj **Odśwież modele**, aby pobrać listę dostępną dla tego klucza. Wybierz model ze zwykłej listy rozwijanej albo pozostaw `auto`.
5. **Zapisz** zachowuje ustawienia. **Używaj tego silnika** dodatkowo ustawia OpenAI jako silnik tłumaczenia. Główne okno pokazuje wtedy właściwy wybór.

Tryb API używa publicznego OpenAI Responses API i jest rozliczany oddzielnie od abonamentu ChatGPT. Sam abonament ChatGPT nie zapewnia środków na API. Lista `/models` wskazuje widoczne modele, ale nie jest gwarancją, że każdy z nich obsługuje wymagany format odpowiedzi lub że konto ma dostępne środki.

Domyślne **auto** wybiera dostępny model z zalecanej listy. Dla API pierwszą propozycją jest `gpt-5.6-luna`: OpenAI opisuje go jako model do zadań o dużej liczbie żądań i niskim koszcie. To praktyczny wybór do krótkich wiadomości, nie twierdzenie, że wygrywa każdy test tłumaczenia. `gpt-6-astra` można wybrać ręcznie, jeśli konto go udostępnia; większy model nie zawsze jest wart dodatkowego czasu i kosztu przy jednym zdaniu z czatu. Wybrany jawnie model nie jest po błędzie po cichu podmieniany na inny.

## OpenAI przez konto ChatGPT: OAuth, tryb eksperymentalny

**Ważne:** logowaniem i odświeżaniem sesji zarządza oficjalny Codex, ale beznarzędziowy transport tłumaczeń wykorzystuje nieudokumentowany publicznie endpoint ChatGPT/Codex. To nie jest stabilny, oficjalny interfejs OAuth dla dowolnego dodatku. Zmiana usługi może wymagać aktualizacji dodatku. Stabilną alternatywą jest klucz API.

1. Zainstaluj oficjalny **Codex CLI dla Windows** według instrukcji https://developers.openai.com/codex/cli. Jest potrzebny tylko w trybie ChatGPT, nie w trybie klucza API.
2. W dodatkowych ustawieniach OpenAI wybierz **ChatGPT OAuth**. Ścieżkę do `codex.exe` można zostawić pustą, jeśli jest wykrywany automatycznie, albo wskazać pełną ścieżkę do oficjalnego pliku wykonywalnego. W to pole nie wpisuj klucza ani tokenu.
3. Naciśnij **Zaloguj się do ChatGPT**. Dokończ logowanie w przeglądarce na stronie OpenAI. Hasła nie podajesz w dodatku.
4. Po zalogowaniu dodatek automatycznie potwierdza konto, pobiera modele i ukrywa przycisk logowania. Pojawia się przycisk **Wyloguj**. Przy ponownym otwarciu konta nie trzeba sprawdzać ręcznie; okno robi to w tle.
5. Wybierz model ze zwykłej listy **Model** albo zostaw `auto`. Lista jest zapisana w profilu NVDA, także po restarcie, aż do wylogowania lub zmiany konta. **Odśwież modele** służy do ręcznego pobrania nowszej listy, a nie do obowiązkowego klikania przy każdym otwarciu.
6. Naciśnij **Używaj tego silnika**, aby wybrać OpenAI do tłumaczenia. Następnie włącz tłumaczenie w locie gestem **NVDA+Shift+T**. Konto ChatGPT nie wymaga żadnego klucza API. Menedżer kluczy i jego przycisk „Domyślny” są w tym trybie ukryte.

Samo pomyślne logowanie od razu zapisuje metodę ChatGPT i ścieżkę programu obsługującego logowanie. Jeśli wersja 2026.3 zachowała konto, lecz nie zapisała tej metody, aktualizacja rozpoznaje lokalną sesję dodatku przy braku wybranego klucza OpenAI. Nie zmienia przy tym wyboru innych silników.

Dodatek przedstawia się jako **TranslateAdvanced** i prosi oficjalny mechanizm logowania o stronę powitalną **ChatGPT**. Sam proces nadal korzysta z klienta OAuth Codexa; treści ekranu zgody oraz sytuacji wymagających konfiguracji organizacji nie ustala dodatek. Nie wszystkie ekrany OpenAI muszą więc wyświetlać nazwę dodatku.

Logowanie do dodatku jest oddzielone od zwykłej konfiguracji programistycznego Codexa. Dane sesji trafiają do `TranslateAdvanced/codex` w katalogu konfiguracji NVDA, nie do katalogu instalacyjnego dodatku. Wylogowanie dotyczy tej osobnej sesji. Chroń katalog konfiguracji, szczególnie przy przenośnej instalacji NVDA; może zawierać klucze i dane logowania. Nie wysyłaj go znajomym razem z dodatkiem.

Przyciski **Anuluj logowanie** i **Wyloguj** są niezależnymi działaniami konta. Anulowanie edycji preferencji nie cofa już zakończonego logowania ani wylogowania. Zapis w dodatkowym oknie OpenAI działa od razu, niezależnie od późniejszego anulowania głównego okna ustawień.

Model nie dostaje dostępu do plików, terminala, przeglądarki ani narzędzi agenta. Tekst schowka jest danymi do przetłumaczenia, nie poleceniem do uruchomienia na komputerze. W trybie ChatGPT obowiązują uprawnienia i limity konta Codex/ChatGPT, a lista modeli może różnić się od listy API.

## Prywatność i rozwiązywanie problemów

- Tekst jest wysyłany do wybranego dostawcy. Nie tłumacz haseł ani innych informacji, których nie chcesz przekazywać tej usłudze. Historia i opcjonalny cache dodatku mogą zachowywać tłumaczone treści lokalnie.
- Błędy uwierzytelniania wymagają sprawdzenia klucza albo ponownego zalogowania. Błąd limitu wymaga poczekania lub sprawdzenia planu/rozliczeń; dodatek nie obchodzi limitów.
- Przy braku modelu odśwież listę i wybierz dostępny model, np. `gpt-6-astra`. Wcześniejszy zapisany model pozostaje widoczny, dopóki nie wybierzesz innego lub nie wylogujesz konta.
- Jeśli tłumaczenie w locie się nie powiedzie, NVDA odczytuje oryginał i krótki komunikat o błędzie. Powtarzający się błąd jest ograniczony do jednego powiadomienia na pół minuty; treść prywatnych wyjątków nie jest odczytywana.
- Wynik identyczny z oryginałem nie jest ogłaszany jako udane tłumaczenie schowka. Może oznaczać już właściwy język, nazwę własną albo odpowiedź, której model nie zmienił.
- Tłumaczenie schowka odbywa się poza głównym wątkiem NVDA. Tłumaczenie każdej wypowiedzi w locie nadal zależy od szybkości wybranej usługi; duży model OpenAI może wprowadzać zauważalne opóźnienia.
- Po ręcznej aktualizacji plików dodatku konieczne jest ponowne uruchomienie NVDA. Testy poza procesem NVDA nie oznaczają, że uruchomiona już instancja załadowała nową wersję.

## Źródła techniczne

Sprawdzone podczas przygotowywania tej wersji:

- Uwierzytelnianie Codexa: https://developers.openai.com/codex/auth
- Oficjalny protokół app-server, logowanie, anulowanie, konto i lista modeli: https://developers.openai.com/codex/app-server
- Źródła oficjalnego Codexa: https://github.com/openai/codex
- Responses API: https://developers.openai.com/api/reference/resources/responses/methods/create
- Modele OpenAI: https://developers.openai.com/api/docs/models
- GPT-5.6 Luna: https://developers.openai.com/api/docs/models/gpt-5.6-luna
- GPT-6 Astra: https://developers.openai.com/api/docs/models/gpt-6-astra
- Tłumaczenie i wykryty język DeepL: https://developers.deepl.com/api-reference/translate

Przykłady pokazują możliwe przekłady. Model może użyć innego, poprawnego sformułowania; testy nie wymuszają jednego konkretnego brzmienia każdego zdania.
