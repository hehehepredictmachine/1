# Panel Neural Cyberpunk (handoff V1) – stan wdrożenia

Panel w bocie: **Pulpit → Neural Cyberpunk** albo adres `#/nc` (np. `http://127.0.0.1:<port>/#/nc?p=market`).
Kod: `frontend/src/nc/NeuralCyberpunk.tsx` i `nc.css`; endpoint `GET /api/v1/sh/validation`.
Test: `tests/test_nc_panel.py` (prawdziwy proces serwera i Chromium, 11 ekranów, szerokości 1440 i 390 px).
Zrzuty ekranów: `data/logs/ui_nc/`.

Handoff zawierał starter UI z danymi **syntetycznymi** i specyfikację. W bocie żaden ekran nie używa danych z startera. Każdy
blok pokazuje status źródła:

| Status | Znaczenie |
|---|---|
| VERIFIED | podłączony terminal MT5 (rachunek rzeczywisty lub demo brokera) ze świeżym notowaniem, albo artefakt z rejestru |
| DEMO | bot uruchomiony na symulatorze terminala (`--demo`): prawdziwy kod, syntetyczny rynek |
| STALE / DISCONNECTED | notowanie zbyt stare albo brak połączenia |
| UNAVAILABLE / NOT_RUN / NOT_IMPLEMENTED / ERROR | elementu nie ma – panel go nie rysuje i nie podstawia wartości |

## Ekrany i źródła danych

| # | Ekran | Źródło w bocie | Uwagi |
|---|---|---|---|
| 01 | Dashboard | `/api/v1/sh` (karty SCALPING/HEDGING, checklista), stan WS, `/api/v1/execution/lock`, `/api/v1/training/models` | Neural System: węzły i połączenia to wyłącznie stan rejestru modeli; brak losowej „aktywności” |
| 02 | Market Analysis | `/api/v1/candles` (M1–D1), overlays M03 (FVG / OB / sweep / BOS-CHoCH), notowanie | EMA20/50 liczone z zamkniętych świec MT5; rysowanie poziomów kliknięciem; zoom i przesuwanie (lightweight-charts, Apache-2.0); VWAP/RSI/MACD: NOT_IMPLEMENTED |
| 03 | Pattern Intelligence | `/api/v1/structure`, `/api/v1/patterns/live`, overlays M03 | 36 nazw przypisanych do detektorów bota (32). Brak detektora: Bullish/Bearish Harami, Piercing Line, Dark Cloud Cover (NOT_IMPLEMENTED). Win rate wzorca: NOT_RUN |
| 04 | Validation & OOS | `/api/v1/sh/validation`, `/api/v1/stats` | raport replay tylko z danych terminala; bez raportu: NOT_RUN |
| 05 | Neural Training | panel treningu (rejestr, gotowość, postęp, historia, eksport/import) | ten sam backend co w klasycznym panelu |
| 06 | AI Decision | ocena setupu SH, specyfikacja symbolu, equity rachunku | kalkulator pomocniczy; „Symuluj decyzję” nie wysyła zlecenia |
| 07 | MT5 & Safety | połączenie, rachunek, specyfikacja symbolu, Execution Lock, pozycje, plany SH, rekonsyliacja | jedyna akcja to istniejący STOP (zatrzymanie nowych wejść); odblokowanie Lock tylko w klasycznych Ustawieniach |
| 08 | Liquidity & Flow | `/api/v1/liquidity/heatmap`, `/sessions`, istniejący panel heatmapy | szacowane poziomy likwidacji od dostawcy (wymaga klucza), nie arkusz zleceń |
| 09 | Statistics | `/api/v1/stats` | statystyki z historii transakcji bota i deali rachunku |
| 10 | System Monitor | `/api/v1/diagnostics`, `/api/v1/training`, `/api/v1/sh`, dziennik WS | |
| 11 | Settings | `/api/v1/config`, klasyczne okno Ustawień | RBAC: NOT_IMPLEMENTED; licencje 48 h usunięte (wersja 1.4); Telegram EN+简体中文: NOT_IMPLEMENTED (obecnie komunikaty po polsku) |

## Nieobjęte (blokery lub zakres)

* Algorytmy 4 brakujących wzorców świecowych i wskaźniki VWAP/RSI/MACD (handoff wymaga osobnej implementacji z testami
  i walidacją OOS).
* Telegram w dwóch językach.
* RBAC administratora.
* Stan VERIFIED dla danych rynku wymaga uruchomienia bota z terminalem MT5. W tym środowisku testowym dostępny był tylko
  symulator, więc testy potwierdzają status DEMO.
