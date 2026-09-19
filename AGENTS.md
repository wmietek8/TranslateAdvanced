# Zasady pracy nad TranslateAdvanced

- Rozmawiaj z Axelem po polsku, swobodnie i po koleżeńsku, jak przy wspólnym dłubaniu w projekcie. Luźny styl obowiązuje przez całą sesję; nie zastępuje precyzji ani rzetelności.
- Samodzielnie wybieraj rozsądny kierunek pracy. Pytaj tylko wtedy, gdy brakuje informacji niezbędnej do bezpiecznego wykonania zadania.
- Odtwarzaj zgłoszone błędy w testach. Sprawdzaj pełną drogę od ustawień i gestu NVDA do wyniku, także przypadki brzegowe, błędne dane, anulowanie i zamykanie okien podczas pracy w tle.
- Uruchamiaj pytest, odpowiednie testy z prawdziwym wxPython, kontrolę składni i audyt zbudowanego dodatku. Testy usług zewnętrznych opisuj osobno od testów z atrapami. Nie deklaruj sprawdzenia mowy NVDA, jeśli nie zostało wykonane.
- Dokumentuj ustalenia, kolejne etapy, zmiany i wyniki w DZIENNIK_PRAC.md oraz instrukcji użytkownika. Raportuj ograniczenia zgodnie z rzeczywistymi wynikami.
- Dodawaj typy i polskie docstringi do nowych publicznych funkcji oraz klas. Nowe komentarze i objaśnienia pisz po polsku. Zachowuj prawa autorskie i licencję oryginału.
- Konto ChatGPT nie wymaga klucza API. Ustawienia muszą rozróżniać te metody, pamiętać modele i udostępniać standardowe kontrolki dla NVDA.
- Nigdy nie publikuj danych logowania, zawartości schowka ani prywatnej historii rozmów. Nie kopiuj SOUL.md do repozytorium ani paczki dodatku.
- Kod rozwijaj w tym repozytorium. Katalog dodatków działającego NVDA jest instalacją; nie restartuj czytnika ekranu bez ustalenia tego z użytkownikiem.
- Gdy użytkownik zleci publikację, wykonaj commit, push i wydanie z plikiem .nvda-addon oraz sumą SHA-256 po pomyślnym sprawdzeniu zmian.
