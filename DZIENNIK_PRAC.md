# Naprawa logowania ChatGPT i ustawień — 19 września 2026

## Rozpoznanie

- Repozytorium źródłowe: TranslateAdvanced-fork, gałąź master, punkt wyjścia d611328. Zainstalowana wersja 2026.3 ma identyczne pliki Pythona.
- Przejrzano dokumentację, historię repozytorium i odpowiednią lokalną sesję Hermesa. Prywatna rozmowa i plik osobowości pozostają poza repozytorium.
- Testy początkowe: Python 3.13, wxPython, pytest i polib; 346 testów oraz 144 podtesty zakończone powodzeniem.
- Okno OAuth nie odczytuje konta po otwarciu i nie zmienia przycisków po zalogowaniu. Lista modeli istnieje tylko w pamięci okna. Kontrolka modelu pozwala edytować tekst.
- Przycisk „Domyślny” w głównych opcjach wybiera klucz API, lecz pozostaje widoczny w trybie konta ChatGPT. Brakuje wyraźnego rozróżnienia wyboru klucza i silnika.
- Dziennik NVDA potwierdza błędy tłumaczenia w locie, ale zapisuje tylko ogólne niepowodzenie. Wymagane osobne odtworzenie problemu usługi i sprawdzenie ustawień.
- Oficjalna dokumentacja opisuje `useHostedLoginSuccessPage=true` i `appBrand=chatgpt`; własna nazwa klienta jest przekazywana przez `clientInfo`. Strona zgody i uprawnienia nadal należą do dostawcy OAuth: https://learn.chatgpt.com/docs/app-server.

## Plan sprawdzenia

1. Odtworzyć błędy ustawień, odczytu konta, listy modeli i tłumaczenia.
2. Wprowadzić poprawki, polskie komunikaty oraz testy błędów, anulowania i ponownego otwierania.
3. Uruchomić testy regresji, rzeczywiste kontrolki Windows i próbę OAuth na syntetycznym tekście.
4. Zbudować paczkę, porównać ją ze źródłami, opublikować kod i gotowy dodatek na GitHubie.

## Odtworzenie i poprawki

- Osiem nowych testów przed poprawkami zakończyło się niepowodzeniem, odtwarzając brak standardowej listy modeli, widoczny menedżer kluczy przy OAuth, brak sprawdzania konta i pobierania modeli, brak osobnego wyboru silnika, brak zapisu katalogu oraz stary wygląd strony powitalnej.
- Próba na odizolowanej kopii dostępu konta dodatku potwierdziła, że sama usługa tłumaczy. Sprawdzono PL↔EN dla `auto`, `gpt-6-astra` i wskazanego przez użytkownika `gpt-5.6-sol`. Nie kopiowano tokenu odświeżania i nie zmieniono oryginalnego logowania.
- Poprawiono okno OpenAI, rozpoznawanie konta, widoczność przycisków, automatyczne pobieranie katalogu, listę `wx.Choice` i wybór silnika niezależny od menedżera kluczy. Dodano ochronę przed nadpisaniem wyboru silnika przez niezapisany stan głównego okna.
- Katalog jest zapisywany atomowo i przypisany skrótem do konta, bez adresu e-mail lub tokenów w pliku katalogu. Uszkodzony katalog jest odbudowywany, odświeżenie tokenu nie usuwa listy, a wylogowanie ją czyści.
- Logowanie od razu zapisuje metodę ChatGPT. Migracja rozpoznaje lokalną sesję dodatku przy braku wybranego klucza. Błąd pobrania modeli nie jest przedstawiany jako wylogowanie.
- Dodano bezpieczne powiadomienie o niepowodzeniu tłumaczenia w locie, ograniczone do jednego na 30 sekund, oraz pomijanie pustych fragmentów wypowiedzi.
- Uwzględniono nową prośbę użytkownika: `appBrand=chatgpt` i `useHostedLoginSuccessPage=true`. Rzeczywisty start i anulowanie nowego logowania zadziałały. Ekran zgody nadal pozostaje po stronie OpenAI.
- Zmieniono testy oczekujące starego edytowalnego pola lub wygaśnięcia katalogu po minucie, zachowując sprawdzanie oddzielnych modeli i stałego wyboru podczas tłumaczenia długiego tekstu.
- Kontrola polskich tłumaczeń wykryła konflikt Alt+U. Przycisk użycia silnika otrzymał Alt+S. Naprawiono również kodowanie dwóch nowych docstringów zapisanych przez konsolę Windows.

## Sprawdzenia wykonane przed pakowaniem

- Python 3.13 i natywne wxPython: pełny zestaw po głównych poprawkach — 374 testy i 144 podtesty; następnie dodano kolejny test wyboru silnika w oknie nadrzędnym.
- Python 3.11: 373 testy i 144 podtesty, jeden test natywnego wx pominięty, bo jest wykonywany na 3.13.
- Ukryte kontrolki Windows: styl `CBS_DROPDOWNLIST`, brak podrzędnego pola `Edit`, poprawne nazwy dostępności, oddzielne modele obu metod, przywrócenie tłumaczenia po zamknięciu.
- Pełna droga `GestorTranslate.speak` → OpenAI OAuth → przechwycona mowa: PL→EN i EN→PL, `gpt-5.6-sol`, zachowane komendy NVDA i odstępy, ponowne użycie tłumaczenia z pamięci. Schowek i działający NVDA nie były dotykane.
- Aktualne wyniki końcowe, komendy odtworzenia i ograniczenia są utrzymywane w VALIDATION.md.

## Kontrola wydania 2026.4

- Końcowy przebieg Python 3.13: **376 testów i 144 podtesty zaliczone**. Ostatni dodatkowy test potwierdza zapis metody ChatGPT po logowaniu nawet przy późniejszym anulowaniu preferencji.
- Końcowa próba rzeczywistej mowy na granicy NVDA potwierdziła także odczyt katalogu po ponownym utworzeniu klienta bez kolejnego pobierania modeli. Oryginalny plik logowania pozostaje niezmieniony.
- Kontrola Ruff dla importów i nazw w oknie OpenAI, kliencie Codex i nowym skrypcie próby mowy: zaliczona z uwzględnieniem `_` wstrzykiwanego przez NVDA. Różnice Git bez błędów białych znaków.
- SCons zbudował `TranslateAdvanced-2026.4.nvda-addon`. Audyt: 105 elementów ZIP, 47 plików Pythona zgodnych ze źródłami i kompilujących się, pomoc PL/EN, polski katalog, autor i GPL zachowane. Nie znaleziono plików prywatnych ani żadnej z czterech kontrolowanych wartości sekretów.
- Osobna kontrola 177 plików źródłowych przeznaczonych do repozytorium nie znalazła kontrolowanych sekretów.
- SHA-256 paczki: `f891306649cf17f27213eb38f81ded37cdc5c8b08705dbbffd7d32339c2a7ce4`.
- Repozytorium zdalne `wmietek8/TranslateAdvanced`, gałąź `master`, było zgodne z lokalną podstawą zmian. Przygotowano publikację kodu oraz wydania 2026.4 z paczką i sumą SHA-256.

## Publikacja i sprawdzenie pobrania

- Commit kodu `b885ccb8f5a1bd6e23b7de87797418000abbec5d` wypchnięto na `origin/master`.
- GitHub odrzucił skrócony identyfikator commita jako cel wydania; ponowiono utworzenie z pełnym identyfikatorem, bez zmiany kodu lub paczki.
- Opublikowano zwykłe wydanie [2026.4](https://github.com/wmietek8/TranslateAdvanced/releases/tag/2026.4) z plikami `TranslateAdvanced-2026.4.nvda-addon` i `TranslateAdvanced-2026.4.sha256`.
- Paczkę pobrano ponownie z GitHuba do osobnego katalogu. Jej SHA-256 jest identyczne z wcześniej sprawdzonym artefaktem i opublikowanym plikiem sumy. Tag wydania wskazuje dokładnie commit kodu podany powyżej.
- Działający NVDA nie był restartowany ani podmieniany. Użytkownik instaluje opublikowaną paczkę jako aktualizację i następnie uruchamia NVDA ponownie.

## Lokalna podmiana i stała zasada na kolejne zmiany

- Użytkownik zlecił automatyczną aktualizację lokalnej instalacji po zakończonych zmianach, tak aby po jego stronie pozostawał tylko restart NVDA. Zasadę zapisano w AGENTS.md, instrukcji użytkownika oraz lokalnym AGENTS.md w katalogu instalacji, kierującym do repozytorium.
- Przed podmianą instalacja nadal miała wersję 2026.3. Samo wcześniejsze zbudowanie i opublikowanie paczki nie zmieniło plików używanych przez NVDA.
- Sprawdzono SHA-256 opublikowanej paczki 2026.4, integralność ZIP oraz składnię wszystkich 47 plików Pythona. Nie zmieniano kodu dodatku, dlatego nie powtarzano zaliczonych wcześniej 376 testów i 144 podtestów.
- Kopię starej instalacji zapisano lokalnie w `%LOCALAPPDATA%\TranslateAdvanced\backups\20260919-191515-249014\TranslateAdvanced-2026.3`. Pliki podmieniono z możliwością przywrócenia kopii w razie błędu; manifest wersji zastąpiono na końcu.
- Podmieniono 19 plików i usunięto 47 plików pamięci podręcznej Pythona. Po zakończeniu wszystkie 105 plików instalacji należących do paczki są identyczne z wydaniem 2026.4. Lokalny AGENTS.md pozostaje dodatkowym plikiem instrukcji.
- Porównanie skrótów przed i po operacji potwierdziło zachowanie konfiguracji NVDA, pliku kluczy API i logowania ChatGPT. Raport podmiany zapisano obok kopii; nie zawiera wartości kluczy ani tokenów.
- NVDA nie został zamknięty ani zrestartowany. Nowe pliki są gotowe; użytkownik uruchamia NVDA ponownie, aby je załadować. Ta operacja nie zmienia wcześniej opublikowanej paczki ani jej sumy SHA-256.

## Skrócenie oczekiwania na mowę — wersja 2026.5

- Użytkownik zgłosił 7–8 sekund oczekiwania przy tłumaczeniu w locie i ponownie zapytał o tożsamość aplikacji przy OAuth. Potwierdzono zapisany wybór ChatGPT i `gpt-5.6-sol` bez odczytywania prywatnych tekstów użytkownika.
- Dokumentacja OpenAI potwierdza obsługę `reasoning.effort=none` przez Sola. W kodzie opcja była ustawiana tylko dla Luny. Ponadto `speak` wysyłał kolejne żądanie dla każdego tekstowego elementu wypowiedzi.
- Pomiar starego kodu na syntetycznych etykietach odtworzył 8,546 sekundy przy trzech żądaniach; samo wyłączenie rozumowania dało 6,167 sekundy. Czas zawiera transport i obsługę po stronie usługi.
- Testy regresji najpierw wykazały brak grupowania i parametru Sola. Dodano liniowy algorytm łączenia sąsiednich tekstów, z granicami komend, białych znaków, zapamiętanych fragmentów i 3000 znaków. Inne silniki zachowują dotychczasową drogę.
- Dodano brak rozumowania dla Sola i aliasu `gpt-5.6` w obu metodach uwierzytelniania; wybór modelu i silnika pozostaje zachowany.
- Rozszerzono próbę mowy o liczenie HTTPS, trzy fragmenty i powtórzenia. Pierwsza seria ujawniła błędne założenie skryptu o zerowaniu historii. Poprawiono przygotowanie niezależnych prób i zamykanie klienta przed sprzątaniem katalogu, również po nieudanej asercji.
- Wykonano po dziewięć udanych tłumaczeń Sol/Luna i ich powtórzenia z pamięci. Mediany: Sol 1,790 s, Luna 1,885 s. Dla trzech etykiet Sol potrzebował 1,698 / 2,289 / 3,930 s i zawsze jednego żądania. Pełne zakresy i ograniczenia są w VALIDATION.md. Nie wykazano wyraźnej przewagi Luny; nie zmieniono modelu użytkownika.
- Python 3.13 z wxPython: 408 testów i 148 podtestów zaliczonych. Python 3.11: 407 testów i 148 podtestów zaliczonych, jeden test wx pominięty. Ruff nowych plików i próby mowy zaliczony. Przygotowano wydanie 2026.5.
- Doprecyzowano OAuth: `clientInfo` identyfikuje integrację, a `appBrand` wybiera stronę końcową; żaden nie nadaje osobnej tożsamości klienta OAuth NVDA. W sprawdzonej publicznej dokumentacji nie znaleziono rejestracji takiego klienta dla dostępu abonamentowego.
- Dwie wczesne próby pozostawiły lokalne bazy pomocniczego Codexa po kolizji zamykania i sprzątania. Ich pliki `auth.json` zostały usunięte przez sprzątanie próby. Automatyczna kontrola odrzuciła usunięcie katalogu oraz ograniczone usunięcie zweryfikowanych plików, podając tylko `blocked by policy`. Pozostałości zostawiono w katalogach Temp `ta-latency-jpb_tj5z` i `ta-realtime-0z9cslup`; nie trafiają do repozytorium ani paczki.
- SCons zbudował paczkę 2026.5: 913891 bajtów, 106 elementów, 48 plików Pythona zgodnych ze źródłami i poprawnych składniowo. Audyt pomocy, polskiego katalogu, GPL i autora zaliczony. Paczka oraz 179 plików źródłowych nie zawierają żadnej z czterech kontrolowanych wartości sekretów.
- SHA-256: `071c458f3f5518f7ab3c9454f9c19f35b9510356c1b34e68b7e03385a20e1815`.
- Zaktualizowano lokalną instalację: 13 nowych lub zmienionych plików, wszystkie 106 plików paczki identyczne z wydaniem. Kopia 2026.4: `%LOCALAPPDATA%\TranslateAdvanced\backups\20260919-194034-532098\TranslateAdvanced-2026.4`. Konfiguracja, klucze i logowanie pozostały identyczne; restart NVDA pozostawiono użytkownikowi.
