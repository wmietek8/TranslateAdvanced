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
- Commit `2f7442cc8ca46b9e9e35b224ce1a566a1b8fe0cd` wypchnięto na `origin/master`. Opublikowano [wydanie 2026.5](https://github.com/wmietek8/TranslateAdvanced/releases/tag/2026.5) z paczką i sumą SHA-256; tag wskazuje ten sam commit.
- Paczkę i sumę pobrano niezależnie z GitHuba do osobnego katalogu. Skrót jest identyczny ze sprawdzonym i lokalnie zainstalowanym artefaktem. Publikacja nie wymaga ręcznej instalacji przez użytkownika na tym komputerze: wystarczy jego restart NVDA.

## Porównanie modeli po zgłoszeniu około 4 sekund oczekiwania

- Użytkownik zapytał o zmianę modelu, ponieważ poprawa 2026.5 nadal nie zapewnia oczekiwanej szybkości. Sprawdzono oficjalne opisy Sola, Terry i Luny oraz zalecenia dotyczące opóźnień. Terra odpowiada klasie mini: https://developers.openai.com/api/docs/models/gpt-5.6-terra.
- W niezmienionym kodzie 2026.5 wykonano dziewięć prób Terry i następnie dziewięć kontrolnych prób Sola, tym samym skryptem i na tych samych trzech syntetycznych tekstach. Każda pierwsza wypowiedź korzystała z jednego HTTPS, a jej powtórka z pamięci tłumaczeń.
- Terra: mediana 1,527 s, zakres 1,387–2,376 s. Sol w nowej serii kontrolnej: mediana 2,418 s, zakres 1,651–3,474 s. Terra korzystała z parametrów dostępnych po zwykłym wyborze modelu w wydaniu 2026.5, bez eksperymentalnego modyfikowania żądań.
- Wynik uzasadnia próbę `gpt-5.6-terra` w ustawieniach, ale nie gwarantuje tego czasu dla innych tekstów i obciążenia usługi. Serie wykonano kolejno, nie jest to duży losowy test porównawczy. Wcześniejsza Luna nie wykazywała wyraźnej przewagi.
- Obie próby potwierdziły zachowanie oryginalnego logowania, komend mowy i katalogu modeli. Nie zmieniono modelu użytkownika, kodu ani instalacji; nie jest potrzebne nowe wydanie. Wybór modelu w oknie OpenAI i przycisk Zapisz działają bez restartu NVDA.

## Samodzielne przygotowanie logowania i próba klucza API — 2026.6

- Użytkownik zlecił automatyczne pobieranie komponentu zamiast wymagania ręcznej instalacji Codexa, schowanie ścieżki oraz rzeczywistą próbę klucza zapisanego w dodatku. W trakcie pracy zgłosił opóźniony angielski odczyt w trybie API.
- Sprawdzono instrukcje projektu, kod wykrywania programu, osobne drogi uwierzytelniania oraz oficjalną dokumentację App Server, katalogu modeli i odpowiedzi API. Potwierdzono dokładne rozmiary i SHA-256 wydania `rust-v0.155.0` dla Windows x64 i ARM64 przez API oficjalnego repozytorium `openai/codex`.
- Próba zapisanego klucza odtworzyła HTTP 200 dla modeli i HTTP 429 dla tłumaczenia. Odczyt samych pól kodu i typu wykazał `credit_balance_exhausted` / `insufficient_quota`, bez wypisywania klucza, identyfikatora organizacji lub pełnej odpowiedzi. Mowa dodatku w takim przypadku wraca do oryginalnego tekstu.
- Dodano instalator korzystający wyłącznie ze standardowej biblioteki. Pobiera przypięte archiwum po HTTPS, ogranicza hosty przekierowań, rozmiary i czas, sprawdza oba skróty, odrzuca dowiązania, zapisuje atomowo i sprząta niepełne pobrania. Weryfikowana kopia pozostaje w profilu NVDA. API nie uruchamia instalatora.
- Pierwsza rzeczywista próba pobierania odrzuciła archiwum, bo zawiera ono także dwa dodatkowe programy. Po sprawdzeniu spisu rozszerzono kontrolę dopuszczalnych nazw; rozpakowywany pozostaje wyłącznie oczekiwany `codex.exe`, ze zweryfikowanym skrótem. Powtórzona próba zakończyła się powodzeniem.
- Dodano przygotowanie programu przed logowaniem, postęp w dostępnym polu statusu, anulowanie oraz ignorowanie spóźnionych odpowiedzi po zamknięciu okna. Nowe konto można sprawdzić bez uruchamiania CLI. Ręczna ścieżka jest schowana pod ustawieniami zaawansowanymi i zachowuje pierwszeństwo.
- Rozróżniono błędy salda od ogólnego limitu API. Bezpieczne metadane błędu wprowadzają minutową przerwę po statusach 401/403/429 w tłumaczeniu w locie. Oryginał i istniejące przekłady pozostają słyszalne bez kolejnych połączeń. Zmiana klucza, modelu lub metody umożliwia próbę od razu; przełączanie aplikacji nie omija przerwy. Klucz nie jest przechowywany w identyfikatorze przerwy.
- Dodano testy komponentu, błędów API, granic czasu i konfiguracji oraz bezpieczny skrypt `live_realtime_api.py`. Pierwszy przebieg wykazał za długi automatyczny identyfikator testu dużej odpowiedzi w środowisku Windows; nadano krótkie identyfikatory. Kontrola dostępności wykazała konflikt Alt+Z z przyciskiem Zapisz; nowy przełącznik otrzymał Alt+W.
- Z wyłączonym wykrywaniem systemowego Codexa rzeczywisty komponent poprawnie rozpoczął i anulował OAuth, odczytał istniejące konto z kopii samego dostępu, pobrał modele i przetłumaczył syntetyczne zdanie na polski. Konto użytkownika zachowało tę samą sumę; proces zamknięto i posprzątano profil testu.
- Rzeczywista próba API po zmianach nadal potwierdziła odmowę rozliczeniową. Pierwsza wypowiedź zajęła 2,076 s, następna nie wykonała żadnego żądania. Nie deklarujemy udanego tłumaczenia API; szczegóły i ograniczenia są w VALIDATION.md. Skrypt oraz testy nie zmieniają konfiguracji i nie korzystają ze schowka.
- Python 3.13 z natywnym wxPython: 499 testów i 148 podtestów zaliczonych. Python 3.11: 498 testów i 148 podtestów zaliczonych, jeden test wx pominięty i pokryty przebiegiem 3.13. Pokrycie instalatora wyniosło 95,9%, okna 94,0%, API 97,5%. Zaktualizowano polskie komunikaty i instrukcje. Przygotowano wersję 2026.6 do budowania i publikacji.

- Końcowy przegląd przywrócił objęcie ochroną mowy także odczytu ustawień przed żądaniem; dodano regresję zachowania oryginału przy takiej awarii oraz walidację bardzo dużej liczby sekund i typu komunikatu. Ponowione pełne przebiegi dały 499 testów na Pythonie 3.13 oraz 498 na 3.11 (jeden test wx pominięty), w obu 148 podtestów.
- SCons zbudował ostateczną paczkę 2026.6: 926728 bajtów, 107 elementów, 49 plików Pythona zgodnych ze źródłami i poprawnych składniowo. Audyt ZIP, polskiego katalogu, pomocy PL/EN, GPL i autora zaliczony. Paczka oraz 184 pliki źródłowe nie zawierają żadnej z pięciu kontrolowanych wartości sekretów. Ruff nowych plików i kontrola różnic Git zaliczone.
- SHA-256 paczki: `eee66495500fb207a6c1d0db157217865ac3fbb7bc0e6faed319fe3492529719`.
- Podmieniono lokalnie 16 plików, a następnie sprawdzono zgodność wszystkich 107 plików paczki. Kopia 2026.5: `%LOCALAPPDATA%\TranslateAdvanced\backups\20260919-204648-310545\TranslateAdvanced-2026.5`. Suma konfiguracji NVDA, pliku kluczy i oryginalnego konta nie zmieniła się. Nie restartowano NVDA; pliki oczekują na restart użytkownika.
- Commit `8b0276e2a3e14a7477f0191b983245d4f8cfd83f` wypchnięto na `origin/master`. Opublikowano [wydanie 2026.6](https://github.com/wmietek8/TranslateAdvanced/releases/tag/2026.6) z paczką i sumą SHA-256. Tag wskazuje dokładnie ten commit.
- Oba pliki pobrano niezależnie z GitHuba. Suma paczki zgadza się z audytem, plikiem sumy i lokalnie zainstalowaną wersją. Repozytorium po publikacji było czyste; ten wpis jedynie dokumentuje zakończoną publikację i nie zmienia paczki.

## Komunikaty gry i blokowanie NVDA — 2026.7

- Użytkownik zgłosił, że opóźnienie 2–3 sekund także na Terrze uniemożliwia granie w Life in Nature. W trakcie pracy potwierdził doładowanie konta i ponowił zgodę na próbę klucza. Sprawdzono tylko wybrane ustawienia i liczby kluczy, bez publikowania sekretów lub komunikatów z gry.
- Klucz API poprawnie przetłumaczył trzy krótkie teksty, z czasem 1,602 / 2,076 / 1,827 s. W kodzie odnaleziono synchroniczne HTTP w obsłudze mowy NVDA. Potwierdzono też brak wyłączenia rozumowania Terry, choć model obsługuje ten parametr: https://developers.openai.com/api/docs/models/gpt-5.6-terra.
- W porównaniu przeplatanym na trzech syntetycznych komunikatach (menu, zadanie, wiadomość serwera) DeepL uzyskał 0,368 / 0,449 / 0,370 s. Sprawdzono Terrę bez zmian, z wyłączonym rozumowaniem oraz z krótszą instrukcją i zwykłym tekstem zamiast schematu. Nie wykazano stałej przewagi ostatniego wariantu. Odpowiedzi w tej próbie nie zawierały tokenów rozumowania także przy domyślnych ustawieniach. Pozostawiono walidację schematu; nie obiecujemy usunięcia opóźnienia samego serwera.
- Dodano ograniczoną kolejkę z dwoma wątkami, wspólną pracą dla identycznych oczekujących tekstów i przekazywaniem wyników przez wx do głównego wątku. Zachowano kolejność, komendy, priorytet przekazywany do NVDA, pamięć i historię. Anulowanie i zmiana kontekstu odrzucają spóźnione wyniki. Przeciążenie oddaje wszystkie oryginały w kolejności, zamiast usuwać wiadomości gry.
- Pierwszy pełny zestaw testów wykazał konieczność uzupełnienia polskiego katalogu i obsługi niepełnej inicjalizacji przy zamykaniu. Obie rzeczy poprawiono. Kontrola źródeł NVDA 2024.1 ujawniła brak `pre_speechCanceled`; w takich wersjach zachowano działającą drogę synchroniczną, co objęto regresją. W zainstalowanym NVDA to powiadomienie jest dostępne.
- Po zmianach wykonano rzeczywiste pomiary przez natywne wxPython: po sześć pojedynczych tłumaczeń oraz po serii trzech komunikatów dla API Terry i DeepL Pro. Powtórki z pamięci nie wykonują nowego żądania. W obu przypadkach sterowanie wraca poniżej 1 ms. Szczegółowe wyniki i ograniczenia znajdują się w VALIDATION.md.
- Osobna rzeczywista próba konta ChatGPT potwierdziła przyjęcie parametru Terry, poprawne PL↔EN, grupowanie, pamięć i katalog po odtworzeniu klienta. Wyniki 1,238–2,885 s potwierdzają zmienność usługi. Oryginalne konto i plik kluczy pozostają identyczne; użyto syntetycznych tekstów i odizolowanej kopii samego dostępu.
- Zapytano jednorazowo o priorytet: minimalny czas z możliwością wyboru DeepL lub pozostanie przy OpenAI. Do chwili przygotowania zmian brak odpowiedzi; rozwijano wspólną poprawkę bez zmiany wybranego silnika. Nie restartowano NVDA ani nie odczytywano rzeczywistej gry.

- Końcowy przebieg z pomiarem pokrycia ujawnił zależność dwóch prób anulowania od bardzo szybkiego zakończenia pracy. Usunięto bezpośrednie przekazanie wyniku wewnątrz submit: wynik zawsze przechodzi przez zdarzenie wx. Dodano regresję tego przypadku i zatrzymywania kolejnych fragmentów po anulowaniu. Ponowione pełne zestawy: Python 3.13 z wxPython — 532 testy i 150 podtestów; Python 3.11 — 531 testów i 150 podtestów, jeden test wx pokryty na 3.13.
- Audyt paczki 2026.7: 933727 bajtów, 108 plików, 50 plików Pythona zgodnych ze źródłami i poprawnych składniowo. Pomoc PL/EN, polski katalog, GPL i autor zachowane. Paczka i 190 plików źródeł nie zawierają żadnej z pięciu sprawdzanych wartości sekretów. Ruff nowych plików i kontrola różnic Git zaliczone; pokrycie kolejki wyniosło 100% linii, menedżera 87,1%.
- SHA-256: `9e0482dc2e2c0e115f5f385f6a922df8566f1c630c32ecfff8b62c91a3100aea`. Podmieniono lokalnie 16 plików i potwierdzono zgodność wszystkich 108 plików z paczką. Kopia 2026.6: `%LOCALAPPDATA%\TranslateAdvanced\backups\20260919-213224-582079\TranslateAdvanced-2026.6`. Konfiguracja NVDA, klucze i oryginalne konto zachowały identyczne sumy. Restart pozostawiono użytkownikowi.
- Commit `9c2fb94241e899a3436c5fef062393d4348c2931` wypchnięto na `origin/master`. Opublikowano [wydanie 2026.7](https://github.com/wmietek8/TranslateAdvanced/releases/tag/2026.7) z paczką i sumą SHA-256. Tag wskazuje ten sam commit. Oba pliki pobrano niezależnie z GitHuba: suma zgadza się z audytem, a wszystkie 108 plików z aktualną instalacją. Nowe pliki czekają na restart NVDA przez użytkownika.
