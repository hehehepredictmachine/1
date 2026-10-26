# PEPE_UI_IMPLEMENTATION_PLAN – plan wdrożenia nowych paneli (Etap 0)

Specyfikacja: [PEPE_UI_IMPLEMENTATION_SPEC.md](PEPE_UI_IMPLEMENTATION_SPEC.md) · audyt: [PEPE_UI_AUDIT.md](PEPE_UI_AUDIT.md) ·
mapa API: [PEPE_UI_API_MAP.md](PEPE_UI_API_MAP.md) · testy: [PEPE_UI_TEST_PLAN.md](PEPE_UI_TEST_PLAN.md).

Każdy etap kończy się testami, raportem i **zatrzymaniem do akceptacji**. Żaden etap nie zmienia strategii, parametrów modeli, silnika
ryzyka ani ścieżki wysyłania zleceń bez osobnej, jawnej zgody.

## Zasady architektoniczne (z audytu)

1. **Ten sam stos**: React 19 + Vite + TypeScript, istniejący router hash (`#/<strona>`), istniejący store i **jedno** połączenie WS,
   istniejący klient `api.ts` (sesja + CSRF), lightweight-charts dla wykresów.
2. **Nowe trasy obok starych**: `#/trading-intelligence`, `#/ai-neural-lab`, `#/system-control`. Wszystkie 22 dotychczasowe strony
   i `#/nc` działają bez zmian; nowy shell otacza wyłącznie nowe trasy.
3. **Kod w `frontend/src/features/`** (`shell/`, `trading-intelligence/`, `ai-neural-lab/`, `system-control/`) – łatwy rollback
   (usunięcie katalogu i trzech wpisów w routerze).
4. **Backend**: w etapie 1 bez zmian. Nowe trasy tylko tam, gdzie mapa API pokazuje brak (N2–N6), każda po akceptacji w swoim etapie.
5. **Brak danych ≠ 0**: wspólne komponenty stanów (`loading`, `empty`, `error`, `stale`, `disconnected`, `permission denied`) i formatter
   wartości nieznanych (`N/A` / `UNKNOWN`).
6. **3D tylko w AI Neural Lab i tylko leniwie** (osobny chunk) – pozostałe strony nie płacą kosztu bundla.

## Etap 1 – nowy szkielet aplikacji (do akceptacji)

Zakres: shell (sidebar stały i zwijany, globalny nagłówek), motyw grafit/szmaragd ograniczony do nowych tras, routing, puste widoki trzech
obszarów z jawnym oznaczeniem „nie zintegrowane – etap N”, kontekst aplikacji wyprowadzony z istniejącego store. **Bez** nowych endpointów,
**bez** nowych zależności npm, **bez** egzekucji.

### Pliki – nowe

| Plik | Zawartość |
|---|---|
| `frontend/src/features/shell/TerminalShell.tsx` | układ: sidebar + header + obszar treści, skip-link do treści, obsługa zwinięcia (zapamiętane lokalnie), nakładka `disconnected` |
| `frontend/src/features/shell/TerminalSidebar.tsx` | nawigacja: Trading Intelligence, AI Neural Lab, System Control Center, sekcja „Istniejące widoki” (linki do dotychczasowych stron) |
| `frontend/src/features/shell/TerminalHeader.tsx` | branding, środowisko (LIVE / DEMO / SYNTHETIC / HISTORY / UNKNOWN – wg D2), status MT5 z panelem szczegółów (stan, heartbeat, epoka, ostatni błąd, wiek kwotowania), świeżość danych, instrument (wg D1 – w etapie 1 tylko wyświetlenie), powiadomienia (WARN/ERROR z logów), diagnostyka, ustawienia (istniejący `SettingsModal`) |
| `frontend/src/features/shell/useTerminalContext.ts` | wspólny kontekst z `useStore()`: instrument, środowisko, MT5, świeżość, tryb, Execution Lock, STOP, ostrzeżenia; **żadnego drugiego store ani WS** |
| `frontend/src/features/shell/StateView.tsx` | komponenty stanów + `fmtUnknown` (null → `N/A`) |
| `frontend/src/features/shell/terminal.css` | tokeny motywu pod `.pmw-terminal` (grafit, szmaragd, cienkie obramowania), fokus, `prefers-reduced-motion`, punkty łamania |
| `frontend/src/features/trading-intelligence/pages/TradingIntelligencePage.tsx` | pusty widok z sekcjami: Market Overview 2×2, Signal Intelligence, Risk & Performance, Order Preview – każda z plakietką „etap 2 – nie zintegrowane” |
| `frontend/src/features/ai-neural-lab/pages/AiNeuralLabPage.tsx` | pusty widok: Neural Network 3D, katalog modeli, Training & Deployment – „etap 3” |
| `frontend/src/features/system-control/pages/SystemControlPage.tsx` | pusty widok: LIVE, MT5, wdrożenia modeli, błędy i rozłączenia – „etap 4” (bez przycisków zmieniających stan) |
| `tests/test_ui_terminal_shell.py` | testy Playwright (lista w PEPE_UI_TEST_PLAN §2) |

### Pliki – zmieniane

| Plik | Zmiana |
|---|---|
| `frontend/src/router.ts` | 3 nowe identyfikatory stron w `Page`/`PAGES` + `TERMINAL_PAGE_IDS`; **bez** nowej grupy w `GROUPS` (istniejące testy UI sprawdzają menu 7 sekcji, a 8. pozycja paska mobilnego groziła poziomym przewijaniem przy 390 px) |
| `frontend/src/App.tsx` | dla 3 nowych tras renderowanie `TerminalShell` zamiast `AppShell` (bez tła animowanego i starego baneru – shell ma własny pasek SYNTHETIC i stopkę z atrybucją); pozostałe trasy bez zmian |
| `frontend/src/components/layout/AppShell.tsx` | **jedna** pozycja w bocznym menu starego shellu: „Nowe panele” (`data-testid=nav-terminal`) – jedyne wejście ze starego UI do nowych paneli |
| `frontend/dist/*` | przebudowany build |
| `docs/PEPE_UI_*.md`, `CHANGELOG.md` | stan po etapie 1 |

Nie zmieniane: cały `backend/`, strony i komponenty istniejących widoków, `store.tsx`, `api.ts`, motywy istniejących widoków.

### Bramka etapu 1

`npm run typecheck`, `npm run build`, `test_ui_terminal_shell` + regresja UI (`test_ui_pages`, `test_ui_monitor`, `test_nc_panel` i pozostałe
`test_ui_*`), pełny `tools/run_tests.py`, przegląd UI (zrzuty 1600×1000 i 760×900), lint wg decyzji D7.

## Etap 2 – Trading Intelligence

1. Market Overview 2×2 (M5/M15/H1/H4) na istniejącym `ChartPanel` (lightweight-charts) i `/api/v1/candles`, wspólne dane stref
   (jedno pobranie mapy na cykl dla czterech wykresów zamiast czterech).
2. Warstwy tylko z rzeczywistych danych (mapa API §2.1), z etykietą źródła: obliczone / zewnętrzne / koncepcyjne.
3. Signal Intelligence: lista zunifikowana (kontrakt N2 po akceptacji mapowania statusów z mapy API §2.3), szczegóły: argumentacja
   (checklista), modele (ML / SH / NSS), tablica dowodów MM (bez fałszywego „konsensusu”), ocena SHADOW, ryzyko, świeżość.
4. Risk & Performance: pozycje, próby zleceń (UNKNOWN widoczne), ekspozycja, equity, DD, ROI z metodą i walutą, osobno PAPER / DEMO / LIVE;
   filtry dat – po stronie klienta albo rozszerzenie `/stats` (decyzja w etapie 2).
5. Order Preview na istniejących kontraktach: `GET /decision` → `POST /execute` (S01–S12) oraz `manual/plan` → `manual/intents` →
   `.../execute` (szablon z sygnału, źródło `MANUAL_USER`); brak wysyłki przy otwarciu podglądu, brak automatycznego ponawiania.
6. Testy integracji i scenariusze ryzyka (PEPE_UI_TEST_PLAN §3–§5).

## Etap 3 – AI Neural Lab

1. Zależności (D6): `three`, `@react-three/fiber@9`, `@react-three/drei` – ładowane dynamicznie; ocena rozmiaru chunku przed włączeniem.
2. Endpoint struktury modeli N3 (po akceptacji): Decision Tree z `tree_structure.json`, XGBoost z `get_dump(json)` z limitem drzew i głębokości,
   NSS warstwy, MLP z JSON zapisanego przy treningu (zmiana w `gold_candles_runtime/scalp_train.py` tylko zapisuje strukturę – bez wpływu
   na trening; osobna akceptacja).
3. Wizualizacje: Decision Tree / Boosting Cascade (prawdziwe drzewa), Neural Constellation (warstwy NSS + **rzeczywista telemetria**),
   Probability Nebula (Monte Carlo z `flow-context/markov` + N4), Random Forest – stan `MISSING` (D4). Animacje bez telemetrii oznaczone
   `Illustrative visualization`.
4. Interakcje 3D, tryby Structure / Data Flow / Decision Path, Replay tylko z danych „as of” (bez przyszłości), instancing, limit węzłów,
   zwalnianie zasobów GPU.
5. Metryki modeli (`N/A` dla nieznanych) z istniejących raportów treningu.

## Etap 4 – System Control Center

1. Panel MT5 (stały), tryby LIVE/DEMO na istniejącym `POST /api/v1/mode` (fraza `LIVE <login>` sprawdzana w backendzie) – podsumowanie
   rachunku, środowiska, MT5, ryzyka i zabezpieczeń przed potwierdzeniem.
2. Błędy i rozłączenia: blokada operacji w UI dodatkowo do blokad backendu, dane `stale` do `resync`, ponowna walidacja po reconnect
   (backend: `session_epoch` – już istnieje).
3. Wdrożenia modeli: po decyzji D3 – kontrakt N5 (kandydat → SHADOW → ręczna akceptacja LIVE) w miejsce auto-promocji `ml` i `sh_tp_model`.
4. Alerty ze statusem (N6) – po akceptacji migracji.

## Etap 5 – regresja i stabilizacja

Wszystkie trasy (stare i nowe), build produkcyjny, WS (reconnect, duplikaty), błędy, responsywność, dostępność (klawiatura, fokus,
kontrast), wydajność (rozmiar chunków, pamięć sceny 3D), raport końcowy wg specyfikacji §11, nowa wersja i paczka.

## Rollback

* Etap 1–3: zmiany UI izolowane w `frontend/src/features/` + 3 wpisy w `router.ts`/`App.tsx`; powrót = `git revert` commitu etapu
  (stary UI działa przez cały czas równolegle).
* Etapy z backendem (N2–N6): nowe trasy dodawane obok istniejących; zmiana zachowania (N5) za flagą konfiguracyjną z wartością
  domyślną = obecne zachowanie, dopóki nie zostanie zaakceptowana.

## Decyzje (szczegóły w audycie §16)

| ID | Wymagana przed | Treść |
|---|---|---|
| D1 | etapem 1 (wyświetlanie) / 2 (przełączanie) | semantyka globalnego wyboru instrumentu; `BTC` vs `BTCUSDT` |
| D2 | etapem 1 | mapowanie środowiska (LIVE / DEMO / SYNTHETIC / HISTORY / UNKNOWN) |
| D7 | etapem 1 | lint: `tsc` strict czy ESLint |
| D8 | etapem 1 | zakres motywu (tylko nowe trasy) |
| D5 | etapem 2 | Order Preview na istniejących kontraktach |
| D4, D6 | etapem 3 | Random Forest; zależności 3D |
| D3 | etapem 4 | auto-promocja modeli |
