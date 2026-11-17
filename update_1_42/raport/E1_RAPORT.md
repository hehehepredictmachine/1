# Raport E1 – cinematic (film) i menu główne 3 planet

## Twoje decyzje z E0
1. Studio zostaje bez zmian. ✅
2. Raport Monte Carlo: dodany endpoint tylko do odczytu `GET /api/v1/montecarlo/validations/{run_id}/report` (`backend/masterquo/api/app.py`). Zwraca zapisany `report.json` przebiegu z rejestru instrumentu. Niczego nie liczy ani nie zmienia. Sprawdzone na trybie syntetycznym:
   - nieznany przebieg → **404 `NOT_RUN`**;
   - niepoprawny identyfikator → **400**.

   Ekran MONTE CARLO (E5) użyje go do diagramu rzetelności.
3. Kronos: adapter czyta `forecast.*`. **Wybór interwałów pracy Kronosa**:
   - backend już go ma: ustawienie `timeframes` (M1, M3, M5, M15, M30, H1; domyślnie M5 + M15), zapis przez istniejące `PUT /api/v1/kronos/settings`;
   - w E3 na ekranie CHARTS dodam panel „Kronos – interwały pracy”: 6 przełączników, zapis przez ten sam endpoint z potwierdzeniem i komunikatem, że zmiana działa od następnej prognozy.

## Co zrobione
| Plik | Zmiana |
|---|---|
| `frontend/src/features/cinematic/menuShaders.ts` | **nowy** – 7 stałych GLSL ze wzorca REF_A przeniesionych 1:1 skryptem (`vertexShared`, `particleFrag`, `meshFrag`, `starVert/Frag`, `streakVert/Frag`) |
| `frontend/src/features/cinematic/menuEngine.ts` | **nowy** – port skryptu REF_A: `mountMenu(elements, opts) → dispose`. Zachowane 1:1: fazy `boot → enter → menu → selecting → selected → returning`, liczby cząsteczek 110k/94k/66k, gwiazdy, pył, smugi, okluzja siatką, renderer CPU, przeciąganie, hover, strzałki, `webglcontextlost/restored`, `visibilitychange`, `AbortController` |
| `frontend/src/features/cinematic/introGate.ts` | **nowy** – kiedy grać intro: raz na sesję, `webdriver` bez intro (chyba że `pmw.cinematic.force=1`), ograniczenie ruchu → od razu menu, zapamiętany wybór ruchu (`pmw.motion`) |
| `frontend/src/features/cinematic/CinematicMenu.tsx` | **nowy** – trasa `#/menu`: markup REF_A jako JSX, wideo z `/assets/cinematic/intro.mp4`, piąte narzędzie „Ustawienia”, znacznik SYNTETYCZNE |
| `frontend/src/features/cinematic/cinematic.css` | **nowy** – style REF_A w zakresie `.app-cinematic` (identyfikatory zamienione na klasy `cin-*`, bez kolizji z resztą aplikacji) |
| `frontend/src/App.tsx` | `#/menu` renderuje `CinematicMenu`. Flaga `CINEMATIC_START = true` wyłącza launcher JOIN THE CULT (jego pliki usuwa E8). Pierwsze uruchomienie otwiera Ustawienia **po** intro (S5 F4) |
| `frontend/src/main.tsx` | boot intro 1.39 nie jest montowany przy `CINEMATIC_START` (plik usuwa E8) |
| `backend/masterquo/api/app.py` | endpoint raportu Monte Carlo (decyzja 2) |

Zmiany poza wzorcem (uzasadnione):
- `dispose` zwalnia kontekst WebGL od razu (`WEBGL_lose_context`). Bez tego każde wejście do menu zostawiało kontekst do czasu odśmiecenia pamięci.
- Spadek jakości jak w S1 §3.7: średnia klatka > 28 ms przez 3 s → DPR 1.
- Ctrl+Alt+B odtwarza intro (wymóg A3).
- Napis w lewym dolnym rogu to wersja aplikacji zamiast „PMW / INTERAKTYWNA PREZENTACJA”.
- `PMW_PREVIEW` zastąpiony przez `window.__PMW_TEST__.menu`, dostępny tylko w trybie testów.
- Usunięte zdarzenie `pmw:mode-preview-selected`, potrzebne tylko w podglądzie.

## Kryteria odbioru (Chromium + Playwright, tryb syntetyczny, 1600×900, DPR 1)
| Pkt | Wynik |
|---|---|
| A1 film z pliku, bez CSP | ✅ `currentSrc = /assets/cinematic/intro.mp4`, gra (`readyState 4`), 0 błędów konsoli i CSP. Z okna Windows – sprawdzam w E8/E9 (protokół Go bez zmian) |
| A2 „PRZEJDŹ DO MENU” / ESC / koniec filmu → wejście 3 s | ✅ zrzut `E1_menu_3_planety.png` ≈ `A1_menu_glowne_3_planety.png` (układ, wielkości i napisy zgodne; różnią się tylko pozycje księżyców, bo to inna chwila animacji) |
| A3 bez intro w tej samej sesji; R, przycisk, Ctrl+Alt+B | ✅ (`sessionStorage pmw.cinematic.seen`) |
| A4 trzy planety, hover, przeciąganie, klawiatura | ✅ pierścień FOREX przed planetą, 4 księżyce, łańcuch CRYPTO, powłoka OTC (`E1_menu_hover_forex.png`); strzałka w prawo z FOREX → fokus na CRYPTO |
| A5 CRYPTO / OTC → „tryb w przygotowaniu” + powrót, zero POST/PUT | ✅ `E1_crypto_w_przygotowaniu.png`, 0 żądań innych niż GET w całym przebiegu |
| A6 bez WebGL → renderer CPU | ✅ `#/menu?renderer=cpu` → „CPU full geometry”, te same planety (`E1_menu_cpu.png`) |
| 10× wejście/wyjście z `#/menu` | ✅ po 10 cyklach **1 żywy kontekst WebGL** (11 utworzonych, 10 zwolnionych), 1 płótno |
| F4 pierwsze uruchomienie | ✅ Ustawienia otwierają się po wejściu do menu, nie na filmie (`E1_pierwsze_uruchomienie_ustawienia.png`). Okno ma jeszcze stary wygląd – nowy panel to E7 |

- **FOREX** w E1 kończy się na ekranie „wybrany tryb FOREX” z dopiskiem, że ekran FOREX powstaje w E2 (`E1_forex_wybrany.png`). Wywołanie `onForexReady(pose)` z pozą planety jest gotowe dla E2.
- **Czas klatki:** w tym kontenerze WebGL działa programowo (SwiftShader), średnio ok. 180 ms. To nie jest miara dla Twojego komputera. Pomiar na prawdziwej karcie dopisuję w E9.
- `npm run build` ✅, `tsc -b` ✅.

## Do wiadomości
Stare ekrany są nadal osiągalne pod swoimi adresami (np. `#/wykresy`). Usuwa je i przekierowuje dopiero E8, zgodnie z kolejnością etapów.

Czekam na „dalej” – następny etap **E2: przelot i ekran FOREX** (panele MODEL A / MODEL B, droga mleczna, 4 planety).
