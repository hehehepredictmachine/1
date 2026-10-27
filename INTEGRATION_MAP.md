# INTEGRATION_MAP – PepeMarketWizard 1.18 (+ uzupełnienia 1.25) · mapa zależności (DEPENDENCY_MAP), 26.10.2026

Zastępuje opis 1.13. Źródła: statyczny graf importów (`ast`, 281 modułów `backend/`, importy modułowe i wewnątrz funkcji), okablowanie w
`backend/masterquo/runtime.py` i pomiar działania (`ARCHITECTURE.md` §1).

## 1. Procesy

| Proces | Start | Rola | Połączenie z botem |
|---|---|---|---|
| bot | `python -m masterquo serve` (`03_START_MASTERQUO.bat`, `PepeMarketWizard.exe`) | FastAPI 127.0.0.1 + wątki serwisów | – |
| worker prognoz | potomny `.venv_candles` (`gold_candles_runtime.worker`) | inferencja gold_candles / Scalp A-B | stdin/stdout JSON (`forecast/service.py`) |
| trening | `python -m masterquo training run` (proces potomny na zadanie) | 17 zadań, artefakty | pliki w `data/`; bot przeładowuje rejestry |
| CLI modułów | `mm`, `structure-intelligence`, `flow-context`, `context-indicators`, `ml-scalp`, `neural-scalp`, `indicator-context` | dataset, trening, ewaluacja | pliki w `data/` |
| eksport MT5 (1.25) | panel „Eksportuj dane z MT5” → `training/export_job.py` uruchamia `python -m masterquo training export` (proces potomny, terminal przez `NoOrders`) | dataset + `EXPORT_STATUS.json` + `MODEL_DATA_READINESS.json` | stan z plików eksportu (`/api/v1/export/*`); bot nie czeka na eksport |
| walidacja Monte Carlo (1.25) | `python -m masterquo montecarlo validate` / `31_MONTE_CARLO_WALIDACJA.bat` / zadanie runnera `monte_carlo` | raport + kalibrator | `data/montecarlo/<INST>/registry.json`; bot czyta aktywny kalibrator |
| terminal MT5 | użytkownik | dane, konto, zlecenia | tylko przez `MT5Worker` |

## 2. Okablowanie w runtime (kto ma referencję do kogo)

```
Runtime
 ├─ MT5Worker (jedyny wątek wywołań terminala; Execution Lock wycofany w 1.24)
 ├─ MarketBridge(worker) ◄─ AssetRegistry
 ├─ ModeManager(account_provider = bridge)          ◄── używany przez EngineService, gateway, manager, SHService (AR-01);
 │                                                      gate(path=ACTIVE|SH) = reguła ścieżki głównej (O1) + strażnik portfela (risk/portfolio.py)
 ├─ EngineService(bridge, modes, news, pcclock)
 │    ├─ ActiveEngine (S01–S12, tracker, selector) ─ listeners: BotSignalService, EvaluationService (SHADOW)
 │    ├─ gateway  = ExecutionGateway(engine, paper)   ──► PositionManager
 │    ├─ agent    = ClaudeAgent(context=engine.context)
 │    ├─ ml       = MLRouter                          (bramka tylko w ASSIST)
 │    └─ si / liquidity / extind / mm_provider        (kontekst dla agenta, tylko odczyt)
 ├─ SHService(bridge, modes)  ── własne: context, setup, coordinator, risk, executor, store ─ listeners: EvaluationService (SHADOW)
 ├─ EvaluationService(cfg, bridge, db) ── tylko odczyt: managed_positions, sh_plans, ml_predictions, bufor M1; własny ledger;
 │     źródła: ActiveEngine, SHService, ScalpService (O6); regime_sources: widok A + snapshot SH (O4); zone_provider = ZoneService (1.22)
 ├─ ZoneService(cfg, bridge, bus) ── 1.22: mapa stref PMW (HLZE + DSVIE + UZICE) na każdej zamkniętej M5, tylko odczyt świec
 │     (bridge.symbol_bars M5/M15, bufory H1/D1), własna baza data/zones/zones.sqlite; ANALYTICAL_ONLY
 │     1.25: po restarcie ostatnia mapa z bazy jako RESTORED + STALE do pierwszego przeliczenia
 ├─ MonteCarloService(cfg, bridge) ── 1.25: własny wątek (1 worker), tylko zamknięte świece M1 bufora bota; cache per świeca i plan;
 │     kalibrator z data/montecarlo (aktywny tylko po walidacji na danych użytkownika); bez referencji do gateway / SHExecutor
 │     sh/scenario.build(rt) (API /api/v1/sh/scenario) = SHService.last_eval + MonteCarloService + SymbolSpec + rejestr modeli – tylko odczyt
 ├─ SHADOW: ForecastService, ScalpService(+nss, mtf, liquidity, extind, ml), LabService, NSS, SI, Liquidity, Analytics,
 │          MarketScanner+BotSignalService, MMService (na żądanie API), WallsService
 └─ API (FastAPI) – czyta wszystkie serwisy; zapisuje tylko konfigurację, tryb, STOP, ręczne akcje i trening
```

Serwisy SHADOW nie mają referencji do `gateway`, `manager`, `paper` ani `SHExecutor` (sprawdzane testami: scalp, analytics, mm, evaluation, zones).

## 3. Zależności pakietów (`backend/masterquo/<pakiet>` → pakiety, z których importuje)

Pominięto wspólne narzędzia `version`, `paths`, `timeutil`.

| Pakiet | Importuje |
|---|---|
| `__main__` | analysis, analytics, api, config, db, diagnostics, extind, forecast, lab, ml, mm, runtime, scalp, sh, train_all, training |
| `agent` | analysis, analytics, db, extind, lab, mm, strategies |
| `analysis` | lab, strategies |
| `analytics` | config, db, extind, ml, mq_instruments, scalp, secrets_store |
| `api` | analysis, analytics, engine, evaluation, execution, extind, lab, media, ml, mm, mq_instruments, prefs, runtime, scalp, sh, stats, strategies, training |
| `config` | strategies |
| `diagnostics` | config, data, db, mt5, secrets_store |
| `engine` | analysis, analytics, data, db, extind, risk, scalp, stats, strategies |
| `evaluation` | mm, paths, risk (`costs`), sh (`store`, `tpmodel`) |
| `events` | db |
| `execution` | db, engine, mt5, risk, sh |
| `extind` | config, db, mq_instruments, scalp |
| `forecast` | config, db, diagnostics, mq_instruments, mt5 |
| `gold_candles_runtime` | gold_candles, mq_instruments, scalp |
| `lab` | analysis, analytics, db, extind, ml, mq_instruments, scalp, strategies |
| `markets` | db, engine, strategies |
| `ml` | config, db, execution, extind, mq_instruments, mt5, risk, scalp, strategies |
| `mm` | lab, mq_instruments, mt5, scalp, stats, strategies |
| `mt5` | config |
| `prefs` | db, strategies |
| `runtime` | agent, analytics, assets, config, data, db, engine, evaluation, events, execution, extind, forecast, lab, markets, ml, mm, mt5, news, notify, prefs, scalp, secrets_store, sh |
| `scalp` | analysis, analytics, config, extind, mq_instruments |
| `sh` | analysis, db, lab, mm, mq_instruments, mt5 |
| `strategies` | analysis, db |
| `train_all` | training |
| `training` | __main__, config, db, diagnostics, forecast, lab, ml, mq_instruments, mt5, sh, train_all |

**Cykle na poziomie pakietów** (rozwiązane importami wewnątrz funkcji; ryzyko kolejności inicjalizacji – AR-15):
`analysis ↔ lab`, `analysis ↔ strategies`, `analytics ↔ scalp`, `extind ↔ scalp`, `training ↔ __main__`, `training ↔ train_all`.

**Uwagi o kierunku zależności:**
* `execution → sh` (`execution/manager.py:531`): menedżer legacy czyta konfigurację SH (magic number), żeby nie dotykać pozycji SH.
* `ml → execution` (`ml/labels.py`): etykiety ML używają tej samej polityki wyjścia co wykonanie (dobrze – jedna definicja).
* `sh → mm`: rejestr modeli SH zawiera wpisy master models (rola OBSERVATION).
* `evaluation` (nowy) importuje `mm.ledger`, `sh.store`, `sh.tpmodel`, `risk.costs` (czysta funkcja prowizji) i `paths`; nie importuje
  `execution`, `risk.engine`, `engine.decision`, `sh.executor` ani `mt5.worker` i nie odwołuje się do `order_send`, gateway, PaperBroker,
  PositionManager ani SHExecutor (test statyczny `tests/test_evaluation.py` `Isolation`).
* `zones` (1.22) importuje `strategies` (pivoty, ATR, TFView), `analytics.session_engine`, `analysis` (`levels`, `range_m5`),
  `timeutil`, `paths`; konsumenci: `evaluation` (przez `zone_provider`, bez importu), `ml.features` (`zone_block`), `api`, `runtime`.
  Te same zakazy importu co `evaluation` (test `tests/test_zones.py` `Isolation`).

## 4. Moduły bez wywołań w procesie bota (z grafu i pomiaru)

| Moduł | Gdzie jest używany | Wniosek |
|---|---|---|
| `gold_candles_runtime.*` (`plan_train`, `scalp_train`, `validate`, `registry_cli`, `scalp_registry`) | procesy potomne z runnera i launchery `.bat` | aktywne poza botem |
| `gold_candles.cli`, `gold_candles.mt5_reader` | referencyjny pakiet źródłowy | nieużywane w ścieżce bota |
| `strategies/ema_pullback_backtest.py` | `tools/backtest_ema_pullback.py` | narzędzie badawcze |
| `mm/drift.py` | od 1.21 `MMService._gpr` (dryf kalibracji) | używany (AR-08) |
| `scalp/hedge.py` (logika decyzji) | wywoływany z `adverse_signal=None` | **martwa logika** (F-16, AR-09) |
| `mm/*` (poza `service.py`) | od 1.21 wątek `mm-shadow` na każdej zamkniętej M5 + `/api/v1/mm/live` + orchestrator treningu | inferencja ciągła, SHADOW (AR-08) |

## 5. Duplikaty (AR-10)

| Obszar | Implementacje | Propozycja |
|---|---|---|
| reżim rynku | `strategies/regime.py` (ścieżka A), `lab/market_v2.py` + `sh/context.py IncRegime` (ścieżka B), `lab/market.py`, `lab/context_ind/fractal.py` | jeden kanoniczny reżim do routingu (decyzja O4), pozostałe jako cechy |
| jakość danych | `data/quality.py`, `sh/context.py` | wspólna funkcja, dwa profile progów |
| koszty | `risk/costs.py`, `sh/units.py`+`sh/setup.py`, `scalp/replay.py` | jeden model kosztów z prowizją z historii i poślizgiem per instrument |
| rejestry cech | `lab/features.py` (FS-1.0.0), `ml/features.py`, `mm/features.py`, `extind/features.py` | rejestr wspólny z wersjonowanym schematem |
| ledgery predykcji | 10 tabel + `data/mm/*/ledger.sqlite` | ledger oceny setupów (nowy) jako wspólny format; migracja reszty stopniowo |
| rejestry modeli | `sh/models.py` (żywy), `MAPA_MODELI_I_TRENINGU.*` (statyczny, 1.15), `mm/inventory.py` | `sh/models.py` jako jedyne źródło; mapa generowana z niego |
| wejście po sweepie płynności | S07/S12 RANGE_RECLAIM, SH SCALPING (odwrócenie), scalp Range→Sweep→Retest (SHADOW) | zachować; porównać w jednym ledgerze zanim cokolwiek usunąć |
