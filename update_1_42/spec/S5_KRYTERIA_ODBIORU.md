# S5 – Kryteria odbioru 1.42.0

Każdy punkt ma wynik: ✅ / ❌ / ⚠️ (z opisem). Zrzuty porównawcze (wzorzec ↔ aplikacja) zapisz w `update_1_42/raport/`.

## A. Start i menu
- [ ] A1 Pierwsze wejście w sesji na `/` (przeglądarka) i z okna Windows: gra **film intro** z `/assets/cinematic/intro.mp4`. Nie ma błędu CSP w konsoli.
- [ ] A2 „PRZEJDŹ DO MENU” / ESC / koniec filmu → wejście 3 s do menu jak w REF_A (zrzut ≈ `A1_menu_glowne_3_planety.png`).
- [ ] A3 Ponowne wejście w tej samej sesji: bez intro. R lub przycisk „Odtwórz intro” odtwarza je ponownie. Ctrl+Alt+B też.
- [ ] A4 Trzy planety: FOREX (pierścień przechodzi przed planetą, 4 księżyce), CRYPTO (bloki + łańcuch), OTC (rdzeń + powłoka z impulsami). Hover, przeciąganie i klawiatura działają.
- [ ] A5 CRYPTO / OTC → ekran „tryb w przygotowaniu” + powrót. **Żadnego** wywołania POST/PUT w zakładce sieć.
- [ ] A6 Brak WebGL (wymuszony) → menu rysuje renderer CPU z tymi samymi planetami.
- [ ] A7 **Cały stary interfejs usunięty**: żaden z 41 starych ekranów, JOIN THE CULT, boot intro, Galaxy V2, wieże, terminale, menu boczne nie są osiągalne. Pliki są w `archive/ui_1_41/`, a archiwum nie wchodzi do `dist` ani do paczek. Każdy stary hash z tabeli S2 §3 przekierowuje poprawnie.
- [ ] A8 Okno startowe Windows w nowym stylu z przyciskiem „WEJDŹ”, protokół Go bez zmian (S6 §5).

## B. Kula FOREX i ekran FOREX
- [ ] B1 FOREX w menu → planeta na środek → przelot 3,2 s bez widocznego skoku między rendererami → ekran FOREX (≈ `S03_ekran_forex.png`).
- [ ] B2 Panele MODEL A / MODEL B: animacje kolumny pierścieni i wiru z planetą. Status wynika z danych (S3 §1), a impuls / łańcuch pojawia się przy prawdziwym zdarzeniu.
- [ ] B3 4 podpisane planety w układzie z REF_B, droga mleczna między nimi, tło w głębi.
- [ ] B4 Wstecz z ekranu FOREX → wynurzenie → menu bez intro.
- [ ] B5 Ostrzeżenie, gdy `active_profile ≠ FOREX_MT5`.

## C. Ekrany planet
- [ ] C1 CHARTS: świece z API dla każdego TF z `/api/v1/timeframes`, wskaźniki/strefy/VP jak w WtcTower, drugi wykres Kronos (TF dozwolone) z poprawnym stanem, gdy Kronos jest niezainstalowany, plan bota i sygnały AI (% tylko skalibrowane).
- [ ] C2 SIGNALS: lista z trzech źródeł, szczegóły, ocena **wszystkich** modeli z katalogu, poprawne etykiety szansa / score / symulacja.
- [ ] C3 MODELS & BACKTEST: rejestr z katalogu, szczegóły z raportów, TRENING z `trainhub/status`, BACKTEST z `sh/validation`, MONTE CARLO z `montecarlo/status`. `NOT_RUN` tam, gdzie brak raportu. Animowany lewy panel.
- [ ] C4 ROI: wszystkie wartości z `/api/v1/stats`, oko = `account_roi` z etykietą „cały rachunek”, PAPER bez ROI, AUTO_LIVE bez transakcji = „BRAK DANYCH” (≈ `S07b_roi_brak_danych.png`).
- [ ] C5 Każdy ekran: przejście wejścia/wyjścia z czasami z S4, bezpośredni link `#/forex?s=…` działa, wstecz wraca na ekran FOREX.

## D. Uczciwość danych
- [ ] D1 `grep -r "genSignals\|genModels\|genRoi\|genBars\|loadSeries\|seeded(" frontend/src` → 0 trafień w kodzie produkcyjnym.
- [ ] D2 Na żadnym ekranie nie ma liczby, której nie da się wskazać w odpowiedzi API (sprawdź po 3 wartości na ekran i wpisz źródło do raportu).
- [ ] D3 W ruchu sieciowym ekranów FOREX są tylko GET, poza akcjami Centrum treningu po potwierdzeniu.

## F. Panele systemowe (S6)
- [ ] F1 Ustawienia, Tryb pracy, STOP, Diagnostyka otwierają się z menu i z każdego ekranu FOREX (szuflada) oraz pod `#/system?p=…`.
- [ ] F2 Każda akcja wysyła żądanie identyczne jak w 1.41.0 (ścieżka, metoda, ciało, potwierdzenie).
- [ ] F3 STOP osiągalny jednym kliknięciem z każdego ekranu; wskaźnik stanu wykonania widoczny na każdym ekranie.
- [ ] F4 Pierwsze uruchomienie otwiera Ustawienia po intro.

## G. Przebudowa aplikacji
- [ ] G1 `release/PepeMarketWizard_1_42_0.zip` i `release/PepeMarketWizard_DESKTOP_1_42_0.zip` zbudowane narzędziami projektu, `verify_release.py` OK.
- [ ] G2 Nowy `PepeMarketWizardDesktop.exe` (wersja 1.42.0 w zasobach) uruchamia: okno startowe → WEJDŹ → intro → menu.
- [ ] G3 Paczki nie zawierają `archive/`, starych zasobów UI ani sekretów (skan build_release).
- [ ] G4 Testy Go (`desktop_test.go`) i `go vet` dla Windows przechodzą.

## E. Jakość
- [ ] E1 `npm run build` i `tsc -b` bez błędów i ostrzeżeń typów. Testy `tools/run_tests.py` przechodzą (testy starego UI przeniesione lub przepisane w E8).
- [ ] E2 Konsola bez błędów na wszystkich ekranach. Brak wycieków: 10× wejście/wyjście FOREX ↔ menu ↔ ekrany nie zwiększa liczby kontekstów WebGL ani nasłuchów.
- [ ] E3 Ograniczenie ruchu działa na każdym ekranie (S4 §5).
- [ ] E4 Klawiatura: od menu do każdego ekranu i z powrotem bez myszy.
- [ ] E5 Średni czas klatki ekranu FOREX i każdego ekranu planety zapisany w raporcie (1600×900, DPR 1).
- [ ] E6 Wersja 1.42.0 w `APP_VERSION`, `frontend/package.json` (jeśli wersjonowane), `CHANGELOG.md`, `SCREEN_MAP`. Manifesty SHA256 zaktualizowane narzędziem projektu (jeśli istnieje).
