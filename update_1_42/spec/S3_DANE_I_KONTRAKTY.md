# S3 – Dane i kontrakty (każdy element UI → źródło → stan pustych danych)

Zasada nadrzędna: **REF_B pokazuje układ i ruch, nie liczby.** Wszystkie wartości w aplikacji pochodzą z API bota 1.41.0.
Odczyt idzie przez `apiGet` z `frontend/src/api.ts` i zdarzenia ze `store.tsx` (jeden WebSocket). Endpointy oznaczone POTWIERDZONE istnieją w `backend/masterquo/api/app.py`.
Jeśli pole, którego potrzebuje widok, nie występuje w odpowiedzi, **zgłoś to** (warunek zatrzymania) i pokaż stan pusty. Nie wyliczaj go po stronie UI z innych danych bez zgody użytkownika.

## 0. Stany wspólne (słownik etykiet)

| Stan | Kiedy | Wygląd |
|---|---|---|
| `BRAK DANYCH` | endpoint zwraca pustą listę / `status: NO_DATA` / brak pola | tekst szary, bez liczby, bez wykresu zastępczego |
| `NOT_TRAINED` / `NIEWYTRENOWANY` | stan modelu z katalogu | chip szary, gwiazda pusta w obserwatorium |
| `NOT_RUN` | brak raportu walidacji / replay | opis + nazwa .bat, który go tworzy (z pola `reason`) |
| `SMALL_SAMPLE` / „mała próba” | `status: SMALL_SAMPLE` z `stats.py` (n < 30) | chip złotawy |
| `UNCALIBRATED` | `calibration.status` | procent **nie** jest pokazywany jako szansa; pokazujemy „score” |
| `SYNTETYCZNE` | `s.synthetic` | znacznik w nagłówku ekranu |
| `BŁĄD` | wyjątek HTTP / `state: ERROR` | czerwony tekst z `reason`, przycisk „Odśwież” |

Formatowanie liczb: `pl-PL` (przecinek dziesiętny, spacja tysięcy, znak „−”), czas lokalny z dopiskiem strefy (jak `fmt()` w REF_B).

## 1. Ekran FOREX (E2)

| Element | Źródło | Uwagi |
|---|---|---|
| Panel **MODEL A** (kolumna warstw) – status i impuls | **ZAŁOŻENIE:** praca modeli predykcji. `GET /api/v1/models/predictions?instrument=XAUUSD` (kontrakt `PMW-PRED-1`) co 15 s. Impuls warstw, gdy pojawi się nowsza predykcja (zmiana znacznika czasu którejkolwiek pozycji READY) | `ANALIZA` gdy ≥1 pozycja `state=READY`; `OCZEKUJE` gdy są pozycje, ale żadna nie jest READY; `BRAK DANYCH` gdy lista jest pusta; `BŁĄD` przy błędzie HTTP |
| Panel **MODEL B** (wir z planetą) – status i strumień do rdzenia | **ZAŁOŻENIE:** silnik sygnałów. Zdarzenia store `bar_closed` (impuls rdzenia) + `GET /api/v1/bot-signals?limit=1` co 10 s (nowy sygnał = łańcuch cząsteczek do rdzenia) | `ANALIZA` gdy `s.ws==="OPEN"` i przyszło `bar_closed` w ostatnich 2× TF; `OCZEKUJE` w pozostałych przypadkach; `BŁĄD` gdy brak połączenia z silnikiem |
| `aria-label` paneli | jak `updatePanelText()` w REF_B, ale bez „(dane demonstracyjne)” | |
| Nagłówek: aktywny profil | `GET /api/v1/baskets/settings` → `active_profile` (POTWIERDZONE w `baskets/service.py`) | tylko odczyt; ostrzeżenie, gdy ≠ `FOREX_MT5` |
| 4 planety | stałe (nawigacja) | bez danych |

DO WERYFIKACJI: przypisanie MODEL A = predykcje i MODEL B = silnik sygnałów. Opisz w raporcie E2, co faktycznie zasila każdy panel.

## 2. CHARTS (E3)

| Element (REF_B) | Źródło (POTWIERDZONE) | Uwagi |
|---|---|---|
| Świece, TF M1…D1 | `GET /api/v1/candles?tf=…` (`rt.engine.chart(tf)`) + `store.barTick[tf]` na żywo | symbol silnika (`mt5.symbol`). Pole instrumentu XAUUSD/BTC: dla instrumentu innego niż symbol silnika użyj `GET /api/v1/market-zones/bars?instrument=BTC&tf=…` (`NO_SYMBOL` → stan pusty). DO WERYFIKACJI, czy to wystarcza |
| Lista TF | `GET /api/v1/timeframes` | nie koduj listy na sztywno (komentarz w backendzie to wymaga) |
| Wskaźniki (EMA, RSI, MACD, ATR, SAR, AVWAP, BB…) | pola wskaźników w odpowiedzi `candles` + istniejące obliczenia `features/towers/WtcTower.tsx` / `chartlab` | **reużyj** warstw i wzorów z WtcTower/ChartPanel. Formuły z REF_B (`ema`, `rsiF`, `atrF`, `sarF`) służą tylko do kontroli zgodności |
| Strefy, Volume Profile, POC/VAH/VAL | `GET /api/v1/market-zones`, `/api/v1/zones/map`, `/api/v1/svp/*` – jak w WtcTower | |
| Drugi wykres **Kronos** | `GET /api/v1/kronos/forecast?instrument=…&tf=…` (tylko TF M1, M5, M15, M30, H1 – inne → komunikat `TIMEFRAME_NOT_ALLOWED`) | pokazuj `direction`, `neutral_band`, `uncertainty`, `horizon_bars`; status z `GET /api/v1/kronos` (SHADOW, niezainstalowany → stan pusty z instrukcją `33_KRONOS_INSTALUJ.bat`) |
| **Plan bota** na wykresie | `GET /api/v1/plans/chart` (+ `/api/v1/sh/chart` dla SH) | wejście/SL/TP/RR tak, jak zwraca backend |
| **Sygnały AI z % modeli** | `GET /api/v1/models/predictions` | % tylko dla `unit=probability` + `calibration.status=CALIBRATED_DEV`; inaczej „score”/„niekalibrowany” |

## 3. SIGNALS (E4)

| Element | Źródło (POTWIERDZONE) | Uwagi |
|---|---|---|
| Lista sygnałów (źródło: silnik / scenariusze / SH) | `GET /api/v1/bot-signals`, `GET /api/v1/setups`, `GET /api/v1/sh/signals?limit=…` | filtry KIERUNEK / ZAKRES jak w REF_B, liczone po stronie UI na pobranej liście |
| Szczegóły sygnału | `GET /api/v1/bot-signals/{id}`, `GET /api/v1/setups/{id}/details`, `GET /api/v1/sh/signals/{sid}` | |
| **Szansa %** | kontrakt MQ-SIGNAL-1.0.0: `probability_win` wyłącznie od skalibrowanego championa | brak → „—” i opis. Dla SH: pierwszeństwo Legacy ML, potem Monte Carlo z etykietą „symulacja” (jak REF_B). **Scalp B to score innego zdarzenia, nie szansa** |
| Ocena prognozy – wszystkie modele | `GET /api/v1/models/catalog?instrument=…` (rejestr `sh/models.py`) + `GET /api/v1/models/predictions` + `GET /api/v1/eval/report` | każdy model z katalogu ma wiersz; stan z katalogu |
| Bramki ścieżki (DANE · KONTEKST · SETUP · RYZYKO · …) | `GET /api/v1/sh/scenario` / `GET /api/v1/decision` | DO WERYFIKACJI, które pola dają poszczególne bramki |
| Konstelacja (kosmiczny widok) | ta sama lista sygnałów: kąt = czas, promień = TF, jasność = stan | grafika bez nowych danych |

## 4. MODELS & BACKTEST (E5)

| Element | Źródło (POTWIERDZONE) | Uwagi |
|---|---|---|
| Rejestr modeli (lewy panel), stany | `GET /api/v1/models/catalog?instrument=XAUUSD|BTC` | stany mapuj 1:1 na chipy z REF_B (`MB_STATE`); nieznany stan → pokaż surową nazwę |
| Szczegóły: holdout, walk-forward, kalibracja, ważność cech, bramka promocji | `GET /api/v1/trainhub/registry`, `GET /api/v1/trainhub/version`, raport biegu `GET /api/v1/training/runs/{rid}/report` | brak raportu → `NOT_RUN`; bramka promocji tylko z raportu (Brier gain > 2 SE) |
| Trening: pipeline, profile, kolejka | `GET /api/v1/trainhub/status` (`jobs`, `queue`, `data`, `defaults`) + `GET /api/v1/trainhub/jobs/{jid}` | etap i postęp foldów pokazuj, jeśli jest w zadaniu; inaczej sam stan zadania |
| Przyciski TRENUJ / WALIDUJ / AKTYWUJ / ROLLBACK | **istniejące** akcje Centrum treningu (`/api/v1/trainhub/*` POST z dzisiejszym potwierdzeniem) | to samo okno potwierdzenia co w `features/training-center`; jeśli nie da się go użyć, przyciski są nieaktywne z opisem |
| BACKTEST (replay SH: HEDGE / NO_HEDGE / REDUCE) | `GET /api/v1/sh/validation?instrument=…` (`VERIFIED_REPLAY` / `NOT_RUN`) | krzywe i tabela tylko z raportu; `NOT_RUN` → opis z `reason` |
| MONTE CARLO | `GET /api/v1/montecarlo/status` | diagram rzetelności/Brier tylko gdy raport walidacji jest w odpowiedzi; inaczej `NOT_RUN`. DO WERYFIKACJI: czy raport walidacji MC (`montecarlo/validate.py`) ma endpoint odczytu |
| Obserwatorium (gromady) | katalog: grupa = gromada, jasność = skill z raportu (brak → gwiazda przygaszona) | |

## 5. ROI (E6)

Wszystko z jednego wywołania `GET /api/v1/stats?mode=PAPER|AUTO_DEMO|AUTO_LIVE` (POTWIERDZONE, `stats.py`).

| Element | Pole | Uwagi |
|---|---|---|
| Wynik bota (lewy panel) za DZIŚ/TYDZIEŃ/MIESIĄC/CAŁOŚĆ | `bot.day / week / month / all` (`trades, wins, losses, breakeven, net, win_rate, win_rate_all_closed, profit_factor (+profit_factor_note), expectancy_r, expectancy_r_se, max_drawdown, max_drawdown_r, avg_win, avg_loss, commission, swap, status`) | `profit_factor=null` + `BRAK_STRAT` → „brak strat”; `status` → chipy |
| Rachunek | `account` (`deposits, withdrawals, trading_net_all_symbols, balance_operations…`), ostatni punkt `equity.points` (saldo, equity) | `account=null` (PAPER lub brak konta) → sekcja „Kapitał PAPER” / „brak konta” |
| **Oko wiru: ROI rachunku 30 dni** | `account_roi.roi_pct` (+ `method`, `scope`, `sampling_note`, `status`) | etykieta zawsze „cały rachunek – nie ROI samego bota”; `status != OK` → BRAK DANYCH + `note`; w PAPER oko pokazuje `bot.all.net` |
| Księżyce = ścieżki wykonania | `engines.per_engine` (`ACTIVE_S01_S12`, `SH_SCALPING`, `SH_HEDGING`) | rozmiar = `trades`, kolor = znak `net` |
| Tabele ŚCIEŻKI/STRATEGIE/INSTRUMENTY/MIESIĄCE | `engines.per_engine / per_strategy / per_symbol / per_month` | agregaty za cały okres (tak liczy API) |
| Krzywa kapitału | `equity.points` (`ts, balance, equity`), `equity.label`, `equity.status` | wpłaty/wypłaty jako znaczniki: DO WERYFIKACJI źródło znacznika czasu przepływów (dziś `account` ma sumy, nie listę) – bez listy nie rysuj znaczników |
| Historia 20 transakcji | `bot.recent` | |
| Wyniki miesięczne (słupki) | `engines.per_month` | |

Tryb domyślny przełącznika: tryb, w którym bot faktycznie pracuje (`s.mode?.mode` ze store); jeśli brak, `PAPER`.
