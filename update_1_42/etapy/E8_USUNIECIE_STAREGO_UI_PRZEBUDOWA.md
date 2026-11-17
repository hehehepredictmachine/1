# E8 – Pełne usunięcie starego interfejsu i przebudowa aplikacji 1.42.0

**Spec:** `spec/S2_ROUTING_I_ZAMIANA_MOTYWOW.md` (§0–§3), `spec/S6_PANELE_SYSTEMOWE.md` §5.
**Decyzja użytkownika (POTWIERDZONE):** usunąć w pełni stary interfejs, wprowadzić nowy i w pełni przebudować aplikację.

## Zakres
1. **App i router:**
   - `App.tsx` renderuje tylko nowy interfejs (`menu`, `forex`, `system`);
   - `main.tsx` bez `BootScreen`, `ThemeProvider`/`AppearanceProvider` (jeśli niepotrzebne nowemu UI);
   - `router.ts` z `Page = "menu" | "forex" | "system"` i `LEGACY_REDIRECTS` (S2 §3).
2. **Przeniesienie starego UI do `archive/ui_1_41/`** zgodnie z S2 §2. Najpierw wydziel do `frontend/src/core/` wszystko, czego używa nowe UI. Po przeniesieniu:
   - `tsc -b` i `npm run build` przechodzą;
   - `grep` po nazwach starych ekranów i komponentów w `frontend/src` → 0 trafień (poza `LEGACY_REDIRECTS` i komentarzem historycznym);
   - `archive/` jest wykluczony z buildu i z paczek wydania (sprawdź `tools/build_release.py`, listę plików / manifest).
3. **Zasoby:** usuń z `public/` obrazy starego UI (przenieś do archiwum). Zostaje `intro.mp4` i `favicon.svg`.
4. **Okno Windows:** nowy `desktop/splash.html` (S6 §5), komentarze w `app_windows.go` zaktualizowane bez zmian logiki.
5. **Testy:**
   - testy UI starych ekranów (`tests/test_ui_*.py`, `test_launchers.py` w części UI, `test_desktop_app.py` w części splash; pełna lista z E0) przenieś do `archive/ui_1_41/tests/` albo przepisz na nowy interfejs, jeśli sprawdzają funkcję, która przetrwała (STOP, tryb, ustawienia, przekierowania);
   - dodaj testy nowego UI:
     - (a) `/` → `#/menu`, `[data-testid=cinematic-menu]`;
     - (b) 3 planety-przyciski;
     - (c) CRYPTO/OTC bez żądań zapisu;
     - (d) `#/forex` z 4 planetami i 2 panelami;
     - (e) `[data-testid=forex-charts|forex-signals|forex-models|forex-roi]`;
     - (f) panele systemowe (S6 §4);
     - (g) `LEGACY_REDIRECTS`: każdy wiersz tabeli S2 §3;
     - (h) adaptery `toViewModel()` dla pustych odpowiedzi → stany puste (JS, wzorem `tests/js/chartlab_calc.test.mjs`).
   - Testy silnika bez zmian i muszą przejść.
6. **Wersja i dokumentacja:**
   - 1.42.0 w `APP_VERSION`, `tools/build_release.py` (`VERSION`), `tools/build_desktop.py` (jeśli ma wersję), zasobach exe (`desktop/winres/winres.json`);
   - `CHANGELOG.md`: sekcja „1.42.0 – nowy interfejs: cinematic, kula FOREX, panele systemowe; stary interfejs usunięty”, z listą przekierowań i informacją, że silnik, strategie i MQL5 są bez zmian;
   - `docs/AKTUALIZACJA_1_42_PL.md` dla użytkownika;
   - `START_TUTAJ_PL.md` / `RUNBOOK_PL.md`: zaktualizuj opisy ekranów i zrzutów, jeśli odwołują się do starego UI.
7. **Pełna przebudowa:**
   1. `cd frontend && npm ci && npm run build` → `frontend/dist`;
   2. `python tools/build_release.py` → `release/PepeMarketWizard_1_42_0.zip` (+ `.sha256`, MANIFEST);
   3. `python tools/build_desktop.py` → `release/PepeMarketWizard_DESKTOP_1_42_0.zip` z nowym `PepeMarketWizardDesktop.exe` (Go ≥ 1.23; testy Go i `go vet` uruchamia skrypt);
   4. `python tools/verify_release.py` dla obu paczek.
   5. Brak Go albo sieci (NuGet / proxy Go) → zatrzymaj się i podaj dokładnie, czego brakuje. Nie podmieniaj exe ręcznie.

## Kryteria odbioru E8
S5 grupy A7–A8, E1, E6, G1–G4. Lista przeniesionych plików i wyniki budowania w raporcie.
