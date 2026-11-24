# O1 – Kryteria odbioru panelu CHARTS

Każdy punkt: ✅ / ❌ / ⚠️ (z opisem). Zrzuty i wyniki w `update_charts/raport/`.

## A. Wygląd 1:1
- [ ] A1 Test `narzedzia/charts_1do1/porownaj.mjs` przechodzi **8/8** (ekran ≤ 0,1 %, każdy obszar ≤ 0,3 %); `wynik.json` i mapy różnic w raporcie.
- [ ] A2 Szum wzorca na tym komputerze = 0 % (`--szum`).
- [ ] A3 Przegląd interakcji z K6 §2 – zrzuty / nagrania obok wzorca.
- [ ] A4 Brak `lightweight-charts` w module ekranu CHARTS; CSS ekranu zgodny z `charts.css` (diff w raporcie – dozwolone tylko prefiksy selektorów).

## B. Sygnały i plan
- [ ] B1 Strategie w koszykach z API, w kolejności `FX_SMC`, `FX_SCALP`, `FX_HEDGE`, `S01–S12`, `SH`; każda ma wiersz ze stanem.
- [ ] B2 Sygnały tylko na TF sygnału strategii; SH na TF ≤ M15.
- [ ] B3 Marker → wybór planu; karta PLAN BOTA zwijana; nowy sygnał z API pojawia się bez przeładowania.
- [ ] B4 TP3 tylko tam, gdzie strategia go definiuje; reszta „brak w kontrakcie strategii”.
- [ ] B5 `res` / `hit` tylko ze stanu w API.
- [ ] B6 Procent szans tylko z modelu skalibrowanego.

## C. Strefy i profile
- [ ] C1 Strefy wyłącznie z wybranego TF; komunikat na TF bez stref.
- [ ] C2 Test zgodności SVP 27/27 na porcie z aplikacji; test w `tools/run_tests.py`.
- [ ] C3 Profile tylko na TF ≤ H1; etykieta `TICK_VOLUME`.

## D. Uczciwość danych
- [ ] D1 `grep -rE "BOTDATA|genM1|genAgg|seriesFor|genBars|loadSeries|genSeeded|seeded\(" <moduł CHARTS>` → 0 trafień w kodzie produkcyjnym.
- [ ] D2 3 wartości z ekranu wskazane w odpowiedziach API (wpisz źródło).
- [ ] D3 W ruchu sieciowym ekranu tylko GET; brak `POST /api/v1/svp/profiles`.
- [ ] D4 `__PMW_TEST__` nie występuje w `frontend/dist`.

## E. Jakość
- [ ] E1 `npm run build` i `tsc -b` bez błędów; `tools/run_tests.py` przechodzi.
- [ ] E2 Konsola bez błędów; 10× wejście / wyjście z ekranu nie zwiększa liczby nasłuchów, timerów ani canvasów.
- [ ] E3 Ograniczenie ruchu działa.
- [ ] E4 Klawiatura: zakładki, przełączniki, TF, karta planu dostępne bez myszy.
- [ ] E5 Średni czas klatki ekranu (1600×900, DPR 1) w raporcie.

## F. Wydanie (K7)
- [ ] F1 Wersja zgodna z tabelą K7, CHANGELOG.
- [ ] F2 Paczki zbudowane narzędziami projektu i zweryfikowane `verify_release.py`.
