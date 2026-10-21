# PMW-SH-1 · Etap 1: audyt architektury, rejestr modeli i ustaleń (21.10.2026)

Zakres: kod w `backend/masterquo`, `backend/gold_candles_runtime`, `backend/gold_candles`, frontend `frontend/src`, konfiguracja `config/`.

Metoda:
- przegląd kodu (ścieżki i linie podane przy ustaleniach);
- testy offline;
- symulator MT5 (`mt5/fake.py`).

Audyt nie obejmuje terminala użytkownika, jego brokera ani rzeczywistych artefaktów modeli: w repozytorium nie ma wytrenowanych modeli. Nie twierdzę, że wykryto wszystkie błędy. Pokryty zakres opisuje sekcja 5.

## 1. Procesy i punkty wejścia

| Proces | Wejście | Rola |
|---|---|---|
| Bot (FastAPI + wątki) | `python -m masterquo serve` (`03_START_MASTERQUO.bat`, `PepeMarketWizard.exe` → 8) | `runtime.Runtime`: bridge MT5, silnik, ryzyko, wykonanie, serwisy SHADOW, API/WS |
| Worker MT5 | wątek `mt5/worker.py` | Jedyny kanał do terminala. Execution Lock egzekwowany na `order_send` |
| Worker prognoz | osobny proces `.venv_candles` (`gold_candles_runtime/worker.py`) | Inferencja gold_candles / scalp A-B / setup quality |
| Trening | `python -m masterquo training run` (proces potomny; launchery, panel, exe) | 16 zadań. Każde zadanie to osobny proces z limitem RAM |
| CLI modułów | `structure-intelligence`, `flow-context`, `context-indicators`, `ml-scalp`, `neural-scalp`, `indicator-context` | Dataset, trening, ewaluacja, wybór SHADOW |

## 2. Przepływ danych (stan zastany)

```
MT5 (worker, bary 6+ TF, tick, konto, deale)
  → MarketBridge (bufory TF, jakość, zegar serwera)
  → EngineService.light_cycle
      → strategie S01–S12 (regime, indicators, setup_score heurystyczny)
      → selector (rank_score) → tracker setupów
      → decision.build: DATA → MARKET → STRATEGY → TRIGGER → RISK → AI(weto) → ML(legacy, tylko ASSIST) → PERMISSION
      → ExecutionGateway.execute (PAPER / AUTO_DEMO / AUTO_LIVE; Lock na workerze)
      → PositionManager (partial na dotknięciu, BE po potwierdzonym TP1, rekonsyliacja UNKNOWN)
      → trades / historia → dataset ML legacy → trening
  równolegle, SHADOW/OBSERVE (bez wpływu na decyzję):
      ForecastService, ScalpService (+hedge controller), Lab, NSS, ML-scalp, indicator_context,
      Structure Intelligence (+flow, context_ind, market_v2), Liquidity, Analytics
```

**Wniosek kluczowy.** Decyzję o wejściu buduje jedno miejsce: `engine/decision.py:36`. Z modeli wpływ mają na nią tylko:
- legacy ML (Decision Tree / XGBoost), i tylko w trybie ASSIST;
- weto agenta Claude.

Pozostałe 11 modeli i wszystkie moduły analityczne są wyłącznie obserwacyjne. Silnik S01–S12 nie działa dla BTC (`LEGACY_ENGINE_XAUUSD_ONLY`).

## 3. Rejestr modeli (stan zastany)

| # | Model / zadanie | Kod (trening / inferencja) | Wyjście (zdarzenie) | Rejestr / kontrola zgodności | Inferencja na żywo | Udział w decyzji | Instrumenty |
|---|---|---|---|---|---|---|---|
| 1 | gold_candles forecast (LR + kalibrator; GBR kwantyle) | `gold_candles/model.py:113` / worker `analyze` | P(DOWN/FLAT/UP) zamknięcia za 5/15/30 min + kwantyle | `data/forecast/registry.json`; sha256 + contract_hash + symbol/tick | ForecastService | SHADOW | XAUUSD, BTC |
| 2 | Scalp A (LR/HGB/MLP + Platt) | `scalp_train.py` / worker `scalp_forecast` | P(DOWN/FLAT/UP) po kosztach, 1/3/5 M1 | `data/scalp/registry.json`; sha256, contract_hash | ScalpService.forecasts | wyświetlanie | XAUUSD, BTC |
| 3 | Scalp B setup quality | `scalp_train.py:507` / worker `setup_quality` | P(TP1 przed SL) setupu Range→Sweep→Retest | jw. | ScalpService.setup_quality | filtr SHADOW (domyślnie wyłączony) | XAUUSD, BTC |
| 4 | Scalp C | replay polityk (nie model) | porównanie HOLD/REDUCE/HEDGE | brak artefaktu | — | — | — |
| 5 | Legacy ML DT + XGBoost | `ml/models.py` / `ml/service.py:534` | P(setup S01–S12 kończy się net R > 0), kalibrowane | tabela `ml_models`, promocja Brier. **Ładowanie bez sprawdzenia hash i schematu cech** (ustalenie F-12) | MLService | węzeł ML (tylko ASSIST) + `probability_win` | XAUUSD (BTC: baza, brak setupów) |
| 6 | Lab: LOGREG/TREE/MiniRocket/XGB/ResNet1D/SEW-SNN (+PCA/GMM/NEUTRALIZED) | `lab/protocol.py` / LabService | surowy score triple-barrier LONG (TP 1.5 ATR przed SL 1.0 ATR, 12 M5) – **nieskalibrowany** | `ACTIVE.json` per rodzina; sha256, features | LabService | scenariusze SHADOW | XAUUSD, BTC |
| 7 | Indicator context (LR/HGB + Platt) | `extind/trainer.py:264` / ScalpService | P(TP1 przed SL) w zamrożonej polityce scalp | registry + sha + parity | ScalpService.indicator_context | obserwacja | XAUUSD, BTC |
| 8 | ML scalp (XGB per strona) | `ml/scalp_task.py:228` / MLService.on_scalp_candidate | P(cykl net_R > 0), E[net_R] per LONG/SHORT | registry `selected[side]` OBSERVE/SHADOW_GATE; hash | tak | nigdy bramka | XAUUSD, BTC |
| 9 | Neural Scalp System (TCN) | `lab/nss.py:353` / NeuralScalpService | P(TP1_FIRST/SL_FIRST/TIMEOUT), E[net_R] | registry `selected`; model_hash | tak (instrument z chwili startu) | OBSERVE | XAUUSD, BTC |
| 10 | Structure Intelligence (LOGREG/XGB/ResNeXt/SEW/SEW-EB/MiniRocket v2/SpikingBrain) | `lab/structure_task.py:546` / `Forecaster` | P(DOWN/FLAT/UP) + kwantyle r_h/ATR, h = 3/5/15 M1 | `shadow[task]`; model_hash, schema, instrument, profil | SI service (tylko TASK_MOVE) | MTF dashboard, agent | XAUUSD, BTC |
| 11 | Flow context reaction + Markov3/Diff | `lab/flow_context/task.py:217`, `markov.py` | P(DOWN/FLAT/UP) M1; rozkład stanów | `shadow`, `markov/latest.txt` | **reaction: brak inferencji**; Markov: wyświetlanie | — | XAUUSD, BTC |
| 12 | Context indicators (LOGREG/XGB) | `lab/context_ind/task.py:224` | P(DOWN/FLAT/UP) M5 h = 3/6/12 | artefakty bez wyboru SHADOW | **brak inferencji** | — | XAUUSD, BTC |
| 13 | Agent Claude | `agent/service.py` | BUY/SELL/WAIT/NO_TRADE (bez prawdopodobieństwa) | prompt wersjonowany | tak | weto (VETO) | XAUUSD |

**Score i confidence.**
- `setup_score` (0–100) to heurystyka, **nieskalibrowana** (`strategies/base.py:341`).
- `probability_win` występuje tylko z legacy ML w stanie READY i z kalibracją.
- Lab nie ma kalibratora.

**Moduły deterministyczne (nie wymagają treningu):**
- regime (`strategies/regime.py`), wskaźniki, S01–S12;
- structure_v2, wzorce (`chart_patterns`, `candles`, `sci2`), MITP, neutralizacja;
- market_v2 (reżim, MBA, SMMA, Z-score);
- flow (Heikin, kanały S/R, StopDistance);
- context_ind (VAMD, FD, SMC);
- liquidity (sesje, heatmapa CoinGlass);
- analytics (BB/MA, FFT/EMD/VMD, Double Bottom);
- volzones/walls (Black-76/HV);
- zegar i jakość danych.

Ich kalibracja (wybór parametrów na danych rozwojowych) nie jest treningiem.

## 4. Rejestr ustaleń

Ważność:
- **K**: krytyczne dla bezpieczeństwa lub poprawności wykonania;
- **W**: wysokie;
- **Ś**: średnie;
- **N**: niskie.

Dowód weryfikacji uzupełniam przy naprawach (`docs/strategie_sh/05_TESTY.md`).

| ID | Waga | Plik | Ustalenie | Reprodukcja | Naprawa |
|---|---|---|---|---|---|
| F-01 | K | `mt5/worker.py`, `mt5/bridge.py` | Długie zapytanie historii (>15 s) brane za martwy terminal → 3 błędy w <1 s → reconnect + przeładowanie historii (pętla). Zgłoszenie użytkownika „co chwilę traci połączenie” | `test_bridge_engine.TestSlowTerminal` | **naprawione** (3f69493): MT5Busy, okno 20 s, sonda terminala |
| F-02 | K | `forecast/export.py`, `diagnostics.py`, `training/cli.py`, `mt5/bridge.py` | `initialize()` z loginem/hasłem przelogowuje konto i zrywa sesję działającego bota | `test_mt5_login.test_same_account_…` | **naprawione** (3f69493): najpierw dołączenie do zalogowanej sesji |
| F-03 | W | `risk/engine.py:174` | Rachunek EXCHANGE (tryb 1) nie traktowany jak netting | przegląd | **naprawione** (etap 2) |
| F-04 | W | `execution/gateway.py:272` | `position_ticket = order` – błędne na netting/exchange | przegląd | **naprawione** (etap 2): position_id z dealu |
| F-05 | W | `engine/targets.py:75`, `execution/manager.py:_move_be`, `gateway.manual_modify` | SL/TP/BE nie wyrównane do `trade_tick_size` (tylko `round(...,6)`) | przegląd | **naprawione**: `align_stops`/`snap_tick` (SL i TP nigdy bliżej), BE w managerze i ręczny BE na siatce; `test_sh_fixes.TickAlignment` |
| F-06 | W | `execution/manager.py:340` | `_move_be` po odrzuceniu ponawia co sekundę bez licznika i bez obsługi wyjątków | przegląd | **naprawione**: maks. 6 prób z odstępem 5 s→300 s, potem ostrzeżenie; `test_sh_fixes.ManagerBeAndManualPartial` |
| F-07 | W | `execution/gateway.py:158` | `manual_modify` PARTIAL_CLOSE na realnym rachunku bez kontroli `volume_step/min` i pozostałego wolumenu | przegląd | **naprawione**: floor do kroku, odrzucenie przy wolumenie lub reszcie < min |
| F-08 | Ś | `execution/manager.py`, `gateway.py` | Ścieżki wyjścia łapią tylko `MT5CallTimeout`; `ExecutionLocked`/`MT5WorkerUnavailable` przy zmianie Locka między sprawdzeniem a wywołaniem wyciekają z pętli | przegląd | **naprawione**: odmowa przed wysłaniem = odrzucenie (partial, close, TP sync, BE, ręczne) |
| F-09 | Ś | `execution/gateway.py:196` | Jedno odrzucenie (requote) blokuje setup na zawsze (`entry_key` UNIQUE → DUPLICATE) | przegląd | udokumentowane; nowe strategie mają kontrolowany retry per akcja |
| F-10 | Ś | `engine/service.py` (cooldown) | Cooldown po stracie czyta `trades` bez filtra trybu (straty PAPER wpływają na AUTO) | przegląd | **naprawione**: filtr `mode` = bieżący tryb |
| F-11 | Ś | `risk/engine.py:202`, `engine/service.py:436` | `max_open_positions` liczy pozycje wszystkich symboli i ręczne; ryzyko otwarte wyceniane kalkulatorem głównego symbolu | przegląd | udokumentowane; wspólny silnik ryzyka SH liczy per symbol |
| F-12 | W | `ml/models.py:155` | Model legacy ML ładowany bez sprawdzenia sha256 i schematu cech (ryzyko niezgodnej kolejności cech i niezweryfikowanego pickle) | przegląd | **naprawione**: `integrity.json` przy zapisie; weryfikacja przed otwarciem pliku; pickle bez manifestu odrzucany; kontrola wersji schematu i kolumn; `test_sh_fixes.MlIntegrity` |
| F-13 | Ś | `config.py` `RiskLimits.max_spread_points=None` | Brak bramki spreadu w ścieżce bota, dopóki użytkownik jej nie ustawi | przegląd | wspólny silnik SH wymaga limitu spreadu per instrument |
| F-14 | Ś | `execution/manager.py:150` | Partial na dotknięciu notowania (poll 1 s); BE poprawnie po potwierdzonym TP1. Trailing nigdy nie wykonywany | przegląd | bez zmian w legacy; strategie SH: BE po potwierdzonym TP2, brak trailingu |
| F-15 | N | `scalp/strategy.py:584`, `_rt` | `size()` bez ponownego floor po `min(vmax)`; zaokrąglenie do najbliższego ticka | przegląd | **naprawione** floor po vmax (`test_sh_fixes.ScalpSize`); zaokrąglenie ticka w SHADOW bez zmian |
| F-16 | N | `scalp/service.py:219` | Hedge controller wołany z `adverse_signal=None` → zawsze HOLD (martwa logika) | przegląd | zastąpione automatem HEDGING (etap 6) |
| F-17 | Ś | `lab/flow_context`, `lab/context_ind` | Modele reakcji trenowane, ale bez żadnej inferencji na żywo (trening bez konsumenta) | przegląd | etap 3: status NIEPODŁĄCZONY w rejestrze; konsument opcjonalny |
| F-18 | N | `execution/gateway.py:36` | `client_tag` obcięty do 20 znaków – przy id „MQA-” zostaje 13 znaków hex, możliwe dwuznaczności `startswith` | przegląd | nowe strategie: krótki, unikalny tag z licznikiem i ścisłym dopasowaniem |
| F-19 | W | `sh/tpmodel.py` (nowy kod, etap 3) | Bramka holdoutu „Brier < bazowy” przepuszczała model z czystego szumu | `test_sh_setup.TpModel` (dane z szumem) | **naprawione**: wymagana istotna poprawa > 2 SE różnicy sparowanej |
| F-20 | K | `sh/lifecycle.py` (nowy kod, etap 5) | Luka przez TP1–TP3 w jednym notowaniu: zamknięcie runnera zlecane pełnym pozostałym wolumenem przed wykonaniem partiali (próba zamknięcia większego wolumenu niż pozycja) | `test_sh_core.GapThroughAllTargets`, replay | **naprawione**: runner = pozostało − oczekujące partiale |
| F-21 | Ś | `sh/context.py` (nowy kod) | Reżim M5 przeliczany od zera na 400 świecach przy każdej świecy M5 (replay 12 mies. > 2 h) | profilowanie replay | **naprawione**: przyrostowa maszyna `IncRegime`, identyczne stany jak `regime_series` (400/400) |

## 5. Pokryty zakres i ograniczenia
**Sprawdzone:**
- ścieżki wykonania (gateway, manager, manual, paper);
- ryzyko, tryby, Execution Lock;
- połączenie MT5;
- rejestry modeli i miejsca ładowania;
- decyzja i score;
- serwisy SHADOW;
- panel treningu (`frontend/src/pages/LabPages.tsx` `TrainingCard`, endpointy `/api/v1/training*`).

**Niesprawdzone:**
- zachowanie u konkretnego brokera;
- rzeczywiste spready i prowizje;
- jakość wytrenowanych modeli (artefaktów brak);
- wydajność na Windows;
- przegląd wszystkich ~45 tys. linii linia po linii. Poza zakresem wskazanym wyżej przegląd był wybiórczy.
