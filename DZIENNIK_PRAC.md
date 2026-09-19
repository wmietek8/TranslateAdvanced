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
