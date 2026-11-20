# O1 – Kryteria odbioru animacji startowej

Każdy punkt: ✅ / ❌ / ⚠️ (z opisem). Wyniki w `update_intro3d/raport/`.

## A. Scenariusz i wygląd 1:1
- [ ] A1 Test `narzedzia/intro_1do1/porownaj.mjs` przechodzi **9/9** (różne piksele ≤ 0,5 %, średni błąd ≤ 0,12 na kanał); `wynik.json` i mapy różnic w raporcie.
- [ ] A2 Szum wzorca na tym komputerze = 0 (`--szum`).
- [ ] A3 Nagranie całej animacji z aplikacji (okno 1280×720) obok nagrania REF_C – w raporcie.
- [ ] A4 Kolejność zdarzeń zgodna z SC1: czerń → galaktyka → 3 postacie w garniturach (środkowa w czerwonej kominiarce) → zatrzymanie w połowie drogi → 3 planety → dłoń na planetach → przejście do menu.

## B. Integracja
- [ ] B1 Po końcu animacji menu wchodzi płynnie (faza `enter`), planety menu działają.
- [ ] B2 „PRZEJDŹ DO MENU”, Esc, „Odtwórz intro”, R, Ctrl+Alt+B działają.
- [ ] B3 Intro raz na sesję; pomijane przy ograniczeniu ruchu i w testach (`navigator.webdriver`).
- [ ] B4 Brak WebGL / utrata kontekstu → komunikat i menu, bez czarnego ekranu.
- [ ] B5 `intro.mp4` nie ma w `frontend/dist` ani w paczce wydania; przycisk dźwięku ukryty.

## C. Jakość i wydajność
- [ ] C1 Konsola bez błędów, brak naruszeń CSP.
- [ ] C2 Średni czas klatki na komputerze użytkownika (okno Windows) zapisany w raporcie; poziomy jakości z I3 działają.
- [ ] C3 10× „Odtwórz intro” → wejście do menu nie zwiększa liczby kontekstów WebGL ani pamięci GPU (po `dispose`).
- [ ] C4 `__PMW_TEST__` nie występuje w `frontend/dist`.
- [ ] C5 `npm run build`, `tsc -b`, `tools/run_tests.py` bez błędów.

## D. Wydanie
- [ ] D1 Wersja i CHANGELOG zgodne z I5; paczki zbudowane narzędziami projektu i zweryfikowane.
