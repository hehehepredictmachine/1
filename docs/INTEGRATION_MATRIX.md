# Macierz integracji – PepeMarketWizard 1.33.0

Wygenerowane przez `tools/integration_matrix.py` (jedno źródło z `integration_manifest.json`). Każdy wiersz: wymaganie specyfikacji → moduł → podłączenie w Runtime → odbiorcy (analiza / strategie / panel / trening / agent) → testy. Ścieżki, trasy API i pliki testów są sprawdzane przy generowaniu.

Wymagania: **37/37** zaimplementowane i podłączone; brakujące: brak. Rodziny modeli zarejestrowane: 15/15.

## AUD – audyt modeli, 15 rodzin, trening

| ID | Wymaganie | Moduły | Runtime | Odbiorcy | API | Testy | Stan |
|---|---|---|---|---|---|---|---|
| AUD-01 | Kontrakt predykcji PMW-PRED-2 (liczby skończone, schematy wyników per zadanie, horyzont, proweniencja) | `modelhub/contract.py` | każdy producent prognoz (modelhub.adapters, families, kronos, trainhub) | panel / SH / agent / koordynator | – | `test_integration_u1` (8: OK)<br>`test_families_u4` (19: OK) | IMPLEMENTED |
| AUD-02 | Interwał M3 w całym łańcuchu (rejestr TF, most MT5, fallback M1→M3, eksport, TrainHub, Kronos) | `timeutil.py`<br>`mt5/bridge.py`<br>`mt5/fake.py` | bridge TF_POLL / rejestr TF | analiza, wykresy, trening | – | `test_integration_u1` (8: OK)<br>`test_bridge_engine` (17: OK)<br>`test_ui_pages` (8: OK)<br>`test_ui_signal_card` (9: OK) | IMPLEMENTED |
| AUD-03 | dxy_missing = rzeczywista dostępność DXY (MQ-FEAT-1.2.0 + adapter starszych modeli) | `ml/features.py` | MLService | bramka ML ścieżki ACTIVE | – | `test_integration_u1` (8: OK) | IMPLEMENTED |
| AUD-04 | Kronos REQUIRED powiązany z odciskiem (symbol, horyzont, ustawienia, pasmo, rewizje) – nieaktualne dopuszczenie wstrzymuje | `kronos/predictions.py`<br>`kronos/service.py` | runtime.kronos → sh.kronos | SCALPING / HEDGING | – | `test_kronos_bot` (17: OK)<br>`test_integration_u1` (8: OK) | IMPLEMENTED |
| AUD-05 | Wspólny adapter rodzin PMW-FAM-1: 3 osie stanu, magazyn artefaktów (manifest, sumy, próbka), aktywacja, rollback, role OFF/SHADOW/ASSIST | `modelhub/families/base.py`<br>`modelhub/families/service.py` | runtime.families (FamilyService) | SH (kontekst + ASSIST), ACTIVE (węzeł MODELS), panel, agent | `/api/v1/families`<br>`/api/v1/families/{fid}/activate`<br>`/api/v1/families/{fid}/rollback`<br>`/api/v1/families/{fid}/use` | `test_families_u4` (19: OK) | IMPLEMENTED |
| AUD-06 | Izolowane środowisko .venv_deep i proces roboczy (PyTorch / Gymnasium / SB3) | `backend/deep_runtime/worker.py`<br>`modelhub/families/deep.py`<br>`tools/deep_setup.py`<br>`requirements/requirements-deep-win.txt`<br>`34_DEEP_INSTALUJ.bat` | FamilyService → deep worker (MQ_DEEP_PYTHON) | trening / inferencja LSTM, GRU, PPO | – | `test_families_u4` (19: OK) | IMPLEMENTED |
| AUD-07 | TrainHub: TH_RF, TH_SVM (kalibrowane), XGB natywny JSON, profile smoke/research/full, unikalne wersje, test wyniku po kalibracji | `trainhub/learn.py`<br>`trainhub/pipeline.py`<br>`trainhub/cli.py` | runtime.trainhub / trainhub_inference | Centrum treningu, SH | – | `test_trainhub` (22: OK) | IMPLEMENTED |
| AUD-08 | Instrukcje i skrypty treningu (35_RODZINY_MODELI.bat, menu 32 opcje 7 i 8, CLI families) | `35_RODZINY_MODELI.bat`<br>`32_CENTRUM_TRENINGU.bat`<br>`modelhub/families/cli.py`<br>`docs/INSTRUKCJA_TRENINGU_PL.md` | – | użytkownik | – | `test_families_u4` (19: OK) | IMPLEMENTED |
| AUD-09 | Sekcja „Rodziny modeli 1.33” w Centrum treningu (stan, trening, aktywacja, rollback, użycie) | `fe/features/pmw133/FamiliesSection.tsx` | panel → /api/v1/families/* | panel | `/api/v1/families/train-all`<br>`/api/v1/families/predictions` | `test_ui_pmw133` (3: OK)<br>`test_ui_training_center` (1: OK) | IMPLEMENTED |

## IND – wskaźniki, DXY, plany Scalp/Hedge, SVP

| ID | Wymaganie | Moduły | Runtime | Odbiorcy | API | Testy | Stan |
|---|---|---|---|---|---|---|---|
| IND-01 | Kontrakt wskaźników PMW-IND-1 (wartości, jednostki, czas źródła/dostępności, hash konfiguracji) | `indicators/contract.py` | IndicatorService | kontekst analizy / SH / agent | – | `test_indicators_u2` (30: OK) | IMPLEMENTED |
| IND-02 | AVWAP SESSION / EVENT / MANUAL z pasmami σ, zdarzenia CROSS/RETEST, wersje kotwic | `indicators/avwap.py` | IndicatorService.compute | kontekst ACTIVE (view.context), SH OBSERVE, wykres | `/api/v1/indicators/chart`<br>`/api/v1/indicators/anchors` | `test_indicators_u2` (30: OK)<br>`test_ui_pmw133` (3: OK) | IMPLEMENTED |
| IND-03 | Spread względem tych samych slotów wcześniejszych sesji (próbkowanie stałym zegarem, percentyl) | `indicators/spread.py` | IndicatorService (próbki spread_samples) | kontekst / panel | `/api/v1/indicators/snapshot` | `test_indicators_u2` (30: OK) | IMPLEMENTED |
| IND-04 | Semiwariancja 20/60 M1 z obsługą luk | `indicators/semivar.py` | IndicatorService | kontekst / panel | – | `test_indicators_u2` (30: OK) | IMPLEMENTED |
| IND-05 | Relacja XAUUSD × DXY na zwrotach H1 bez forward-fill (korelacja, beta bez bieżącej obserwacji, reszta z) | `indicators/dxy.py` | IndicatorService (dxy_bars) | kontekst, agent get_dxy_relation, panel #/dxy | `/api/v1/indicators/dxy` | `test_indicators_u2` (30: OK)<br>`test_ui_pmw133` (3: OK) | IMPLEMENTED |
| IND-06 | Mikrostruktura: OFI, nierównowaga, microprice z arkusza MT5 (market_book_* przez kolejkę MT5) + archiwum | `indicators/ofi.py`<br>`mt5/fake.py` | IndicatorService BookAdapter | rodzina MICROSTRUCTURE, panel | – | `test_indicators_u2` (30: OK)<br>`test_families_u4` (19: OK) | IMPLEMENTED |
| IND-07 | Cechy profilu sesji z DSVIE + RVOL z kontrolą historii i pokrycia | `indicators/profile.py`<br>`zones/dsvie.py` | IndicatorService / ZonesService | kontekst / strefy | – | `test_indicators_u2` (30: OK)<br>`test_zones` (42: OK) | IMPLEMENTED |
| IND-08 | Plany Pepe Scalp Plan / Pepe Hedge Plan (PMW-PLAN-1): plan vs fill, SL v2 po BE, noga HEDGE, NETTING = niedostępne | `plans/contract.py`<br>`plans/service.py` | SHService → plans.collect | panel (warstwy wykresu) | `/api/v1/plans/chart` | `test_plans_svp_u3` (21: OK)<br>`test_ui_pmw133` (3: OK) | IMPLEMENTED |
| IND-09 | SVP PMW-SVP-1: profile SESSION/RANGE/VISIBLE/LIVE/FROZEN, strefy MANUAL/ALGORITHM/AI z wersjami, AI z walidacją snapshotu | `svp/engine.py`<br>`svp/zones.py`<br>`svp/service.py`<br>`agent/service.py` | runtime.svp (SVPService) | agent get_svp_profiles, panel #/svp, warstwa SVP | `/api/v1/svp/profiles`<br>`/api/v1/svp/zones`<br>`/api/v1/svp/profiles/{pid}/ai-propose` | `test_plans_svp_u3` (21: OK)<br>`test_ui_pmw133` (3: OK) | IMPLEMENTED |
| IND-10 | Narzędzia agenta: get_pmw_indicators, get_dxy_relation, get_svp_profiles (zamrożony snapshot) | `agent/tools.py` | engine.indicators_provider / svp_provider | agent Claude | – | `test_indicators_u2` (30: OK)<br>`test_plans_svp_u3` (21: OK) | IMPLEMENTED |
| IND-11 | Panel: #/dxy (XAUUSD × DXY i wskaźniki), #/svp (narzędzie SVP), warstwy Scalp Plan / Hedge Plan / AVWAP / SVP w każdym wykresie | `fe/features/pmw133/DxyPage.tsx`<br>`fe/features/pmw133/SvpPage.tsx`<br>`fe/features/pmw133/overlays.tsx`<br>`fe/components/ChartPanel.tsx` | panel | użytkownik | – | `test_ui_pmw133` (3: OK)<br>`test_ui_chart_prefs` (6: OK) | IMPLEMENTED |

## STU – Data & Training Studio

| ID | Wymaganie | Moduły | Runtime | Odbiorcy | API | Testy | Stan |
|---|---|---|---|---|---|---|---|
| STU-01 | Osobna aplikacja Studio (proces, port 8780, własny katalog danych), bez Runtime bota i bez zleceń | `studio/app.py`<br>`studio/settings.py`<br>`__main__.py`<br>`36_STUDIO.bat` | `python -m masterquo studio` | trening / dane | `/api/studio/health` | `test_studio_u5` (7: OK) | IMPLEMENTED |
| STU-02 | Blokada międzyprocesowa (O_EXCL + heartbeat) i wspólna blokada eksportu bota i Studio | `studio/lock.py`<br>`marketdata/export.py` | Studio + eksport bota | dane | – | `test_studio_u5` (7: OK)<br>`test_export_mt5` (10: OK) | IMPLEMENTED |
| STU-03 | Rejestr 72 zadań (TRAINHUB / FAMILY / RUNNER_GROUP / DETERMINISTIC / PRETRAINED) + MODEL_DATA_MATRIX.json | `studio/registry.py`<br>`docs/MODEL_DATA_MATRIX.json` | Studio | trening | `/api/studio/matrix` | `test_studio_u5` (7: OK) | IMPLEMENTED |
| STU-04 | Kolejka zadań (pauza, anulowanie, wznowienie, przesunięcie, przeniesienie) z trwałym stanem | `studio/queue.py`<br>`studio/jobrun.py` | Studio | trening | `/api/studio/jobs` | `test_studio_u5` (7: OK) | IMPLEMENTED |
| STU-05 | Paczka per model: etapy RAW → walidacja → dataset → trening → ocena → test ładowania, atomowe zatwierdzenia i sumy | `studio/package.py`<br>`studio/pipeline.py`<br>`studio/verify.py` | Studio | trening | – | `test_studio_u5` (7: OK) | IMPLEMENTED |
| STU-06 | Import paczki do bota (kandydat, nigdy auto-aktywacja), rollback, inbox przy starcie | `studio/importer.py`<br>`api/app.py`<br>`runtime.py` | Runtime: process_inbox() przy starcie | modele bota | `/api/v1/studio/import`<br>`/api/v1/studio/imports` | `test_studio_u5` (7: OK) | IMPLEMENTED |
| STU-07 | PepeTrainingStudio.exe (tryb studio launchera Go) w paczce DESKTOP | `desktop/main.go`<br>`desktop/engine.go`<br>`desktop/layout.go`<br>`tools/build_desktop.py` | launcher Go | użytkownik | – | `go test ./desktop` | IMPLEMENTED |
| STU-08 | Przycisk „Studio” ze stanem w menu bota (pasek górny, menu CULT), uruchomienie jako osobny proces | `fe/features/pmw133/StudioButton.tsx`<br>`api/app.py` | API bota | panel | `/api/v1/studio/status`<br>`/api/v1/studio/launch` | `test_ui_pmw133` (3: OK) | IMPLEMENTED |
| STU-09 | Frontend Studio (studio.html, 6 obszarów) | `frontend/studio.html`<br>`fe/studio/main.tsx` | Studio | użytkownik | – | `test_studio_u5` (7: OK) | IMPLEMENTED |

## ARC – architektura analizy i decyzji

| ID | Wymaganie | Moduły | Runtime | Odbiorcy | API | Testy | Stan |
|---|---|---|---|---|---|---|---|
| ARC-01 | 10 kontraktów typowanych (InstrumentSpec … ExecutionOutcome) | `decision/contracts.py` | decision/* | koordynator / ledger | – | `test_decision_arc_u6` (18: OK) | IMPLEMENTED |
| ARC-02 | Role modeli OBSERVE / ASSIST / REQUIRED dla obu ścieżek (węzeł MODELS w drzewie ACTIVE, REQUIRED w SH) | `decision/coordinator.py`<br>`engine/decision.py`<br>`engine/service.py`<br>`sh/service.py` | engine.arc / sh.arc | strategie ACTIVE i SH | – | `test_decision_arc_u6` (18: OK) | IMPLEMENTED |
| ARC-03 | Jeden Decision Coordinator i DecisionRecord obu ścieżek | `decision/coordinator.py`<br>`db/migrations/0025_decision_arc.sql`<br>`runtime.py` | runtime.arc (wspólny dla engine/gateway/SH/manager) | audyt, panel #/decyzje | `/api/v1/decision/status`<br>`/api/v1/decision/records/{record_id}` | `test_decision_arc_u6` (18: OK)<br>`test_risk_execution` (21: OK) | IMPLEMENTED |
| ARC-04 | Wspólny portfel/ryzyko z atomową rezerwacją (BEGIN IMMEDIATE) obu ścieżek | `decision/ledger.py`<br>`execution/gateway.py`<br>`sh/service.py` | gateway.arc / sh.arc | wykonanie nowych wejść | – | `test_decision_arc_u6` (18: OK) | IMPLEMENTED |
| ARC-05 | Intencje wykonania: deduplikacja, UNKNOWN liczony do rekonsyliacji, rozliczanie z adapterów (bez ponownej wysyłki) | `decision/ledger.py`<br>`execution/manager.py` | manager.tick → arc.sync() | wykonanie | – | `test_decision_arc_u6` (18: OK)<br>`test_risk_execution` (21: OK)<br>`test_sh_service` (13: OK) | IMPLEMENTED |
| ARC-06 | Replay stary (1.32) vs nowy (1.33): zapisane decyzje + scenariusz wyścigu | `decision/replay.py` | `python -m masterquo.decision.replay` | walidacja | – | `test_decision_arc_u6` (18: OK) | IMPLEMENTED |
| ARC-07 | Panel #/decyzje: ostatnie decyzje, rezerwacje, intencje, rekordy z rolami modeli | `fe/features/pmw133/DecisionPage.tsx` | panel | użytkownik | – | `test_ui_pmw133` (3: OK) | IMPLEMENTED |
| ARC-08 | Execution Lock NIE przywrócony; tryby SIGNALS/PAPER/AUTO DEMO/AUTO LIVE, STOP i limity bez zmian | `execution/modes.py` | ModeManager | wykonanie | – | `test_execution_lock_withdrawn` (11: OK) | IMPLEMENTED |

## Rodziny modeli (AUD)

| Rodzina | Zarejestrowana |
|---|---|
| TS_ARIMA | tak |
| TS_SARIMAX | tak |
| VOL_GARCH | tak |
| MICROSTRUCTURE | tak |
| PAIR_COINT | tak |
| STATARB | tak |
| KALMAN_LS | tak |
| BREAKOUT | tak |
| TH_RF | tak |
| TH_SVM | tak |
| TH_XGB | tak |
| SEQ_LSTM | tak |
| SEQ_GRU | tak |
| RL_PPO | tak |
| NLP_SENTIMENT | tak |

Migracje bazy: 24 (nowa: `0025_decision_arc.sql`, addytywna). Nowe sekcje konfiguracji: `indicators`, `families`, `decision` – wersja 1.32 ich nie zna (patrz instrukcja rollbacku).
