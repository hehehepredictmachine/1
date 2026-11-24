# I0 – Przygotowanie

**Nie zmieniasz kodu aplikacji.**

1. **Kopia:** gałąź `ui/intro-3d` albo kopia `frontend/src`, `frontend/public`, `frontend/package*.json`, `CHANGELOG.md` do `archive/intro3d_backup_<data>/`.
2. **Wariant bazy** (zapisz w raporcie):

   | Wariant | Jak rozpoznać | Co robisz |
   |---|---|---|
   | **A** – menu kinowe już jest | istnieje `features/cinematic/` (menuEngine, CinematicMenu) z filmem `intro.mp4` | zamieniasz film na Intro3D na miejscu |
   | **A′** – pełny pakiet 1.42.0 w trakcie | E1 jeszcze nie zrobiony lub w trakcie | ten pakiet **zmienia E1**: zamiast `<video>` – Intro3D (SC3 §3); kopiowanie `intro.mp4` w E0 pomijasz |
   | **B** – czysta wersja 1.41.0 | brak `features/cinematic/` | **zatrzymaj się i zapytaj**: (1) najpierw wdrożyć pełny pakiet do E1, czy (2) uruchamiać Intro3D w istniejącym ekranie startowym (`BootScreen`) z przejściem do obecnego menu |

3. **Wersja bazowa** (`CHANGELOG.md`, `APP_VERSION`), stan bazowy: `npm run build`, `tsc -b`, `tools/run_tests.py` (testy padające przed zmianą – osobno).
4. **Narzędzia testu 1:1:** `npm i -D playwright`, `npx playwright install chromium`, potem:
   ```
   node update_intro3d/narzedzia/intro_1do1/wzorzec.mjs
   node update_intro3d/narzedzia/intro_1do1/porownaj.mjs --szum
   ```
   Szum ma wynosić 0 we wszystkich 9 klatkach.
5. **Otwórz `referencje/REF_C_intro_3d_i_menu.html`** w Edge/Chrome, obejrzyj całość i zapisz w raporcie średni czas klatki z DevTools (Performance) na tym komputerze.
6. **DO WERYFIKACJI:** dostępność WebGL2 w WebView2 (okno Windows); czy menu używa obiektu wideo przez inne pola niż w SC3 §3.

Raport I0 + pytania (maks. 3). **Czekaj na „dalej”.**
