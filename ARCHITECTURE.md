# ARCHITECTURE – PepeMarketWizard 1.14

Jedna ścieżka (opis przepływu, nie mikroserwisy):

```
MT5 (terminal użytkownika) ──► MT5Worker (1 wątek, proxy Execution Lock) ──► MarketBridge (bufory TF, zegar serwera→UTC,
   allowlista SymbolRegistry, buffer_symbol, ticki copy_ticks_from)
        │
        ├─► EngineService (XAUUSD: M01–M07 + S01–S12 + AUTO; BTC: LEGACY_ENGINE_XAUUSD_ONLY) ──► decyzja / checklista silnika
        ├─► AnalyticsService 1.13 (BB/MA, FFT/EMD/VMD, Double Bottom) – OBSERVE
        └─► LabService 1.14 (aktywne aktywo)
              kontrola jakości (zamknięte świece, dedup, świeżość notowania)
              → reżim (M10, M11) → struktura i wzorce (M12–M16, M18, M22–M25, M27, M29) → ticki (M28, M31)
              → model z artefaktu aktywa/horyzontu (lub jawna abstencja) + telemetria
              → scenariusze (setup_id, checklista, trigger, unieważnienie) → koszt (spread/ATR) → API / WS „lab” → panel
LabTrainer (wątek): protokół VP → badanie per aktywo → rejestr prób → holdout (raz) → artefakt z manifestem
ExecutionGateway / PositionManager: Execution Lock + allowlista; LabService nie ma referencji do wykonania.
```

## Kontrakty

**Rekordy kanoniczne (nazwy dopasowane do istniejącego schematu):**

| Rekord | Pola | Gdzie |
|---|---|---|
| Tick | `t` (UTC event), `bid`, `ask`, `flags`; `received_at_utc` dla odczytu; `source` | `bridge.ticks` |
| Bar | `open_utc`, `close_confirmed_utc`, `available_at`, OHLC, `tv`, `rv`, `spread`, `closed`, `basis`, `revision`, `source` | bridge (1.0+) |
| Feature | `feature_set` FS-1.0.0, `t_event` (= `available_at` zamknięcia), `warmup` | `lab/features.py` |
| Pattern / Zone | stabilne ID, `origin_time`, `confirmed_at`, status, `rules_version`; strefy w `lab_zones` z historią | |
| Wynik modułu | kontrakt `mq-analytics-1.0.0` + `canonical_asset`, `decision_role` | |
| Scenariusz | `setup_id`, `version` MQ-LAB-SCN-1.0.0, `asset`, `side`, `tf`, `created_at`, `expires_at`, `checklist`, `checklist_completeness`, `model` (osobno), `trace_id`, `history` | |
| Telemetria inferencji | `trace_id`, `inference_id`, `instrument_id`, `canonical_asset`, `as_of_time`, `input_available_at`, `model_id`, `model_version`, `model_role`, `architecture_id`, `state_mode`, `feature_groups`, `layer_summaries`, `spike_metrics`, `output_schema`, `raw_output`, `calibrated_output` (null + powód), `latency_ms`, `telemetry_overhead_ms`, `quality`, `warnings`, `expires_at` | |
| Artefakt modelu | katalog `data/lab/models/<asset>/<model_id>/` z plikami `model.pkl` i `manifest.json` | |

Manifest artefaktu zawiera: asset, instrument, źródło, horyzont, schemat cech, odcięcie, parametry, seedy, wersję kodu, metryki, zależności i sha256. Ładowanie z błędnym aktywem, schematem lub sumą kontrolną jest odrzucane.

**Transport WebSocket:**
- zdarzenia `lab` (asset, seq, trace_id), `assets`, `execution_lock`;
- snapshot po ponownym połączeniu: `/api/v1/state` zawiera `assets`, `execution_lock` i `lab`;
- panel odrzuca odpowiedzi dla innego aktywa niż aktywne (`useLab` – licznik żądań plus porównanie `asset`).

## Obszary kodu

| Obszar | Pliki |
|---|---|
| rejestr symboli | `assets/registry.py` |
| adaptery danych | `mt5/bridge.py`, `mt5/fake.py` |
| cechy | `lab/features.py` |
| wzorce i reżimy | `lab/market.py`, `lab/sessions.py`, `lab/zones.py`, `analytics/*` |
| ticki | `lab/ticks.py` |
| modele | `lab/nets.py`, `lab/minirocket.py`, sklearn/xgboost |
| trening i walidacja | `lab/protocol.py` |
| scenariusze | `lab/scenarios.py` |
| narzędzia przewagi | `lab/edge.py` (bootstrap, drift, repaint, trade pad) |
| telemetria | `lab/service.py::_infer` |
| API | `api/app.py` (`/api/v1/assets*`, `/execution/lock`, `/lab*`) |
| frontend | `pages/LabPages.tsx`, `components/layout/AppShell.tsx`, `router.ts` |

## Menu panelu (B13)

| Sekcja | Zawartość |
|---|---|
| Pulpit | aktywo, notowanie, scenariusz, aktywność modelu, przegląd |
| Wykresy | MTF, Kontekst, BB/MA, Analiza sygnału |
| Setupy | scenariusze lab, setup silnika S01–S12, Analiza AI, Pozycje, Dziennik |
| Modele i trening | badania, zadania, artefakty; Testy scalp/prognozy |
| Badania i walidacja | ostatnie badanie, rejestr prób, macierz M01–M42; Formacje |
| Dane i diagnostyka | ticki, repaint, strefy, archiwum, źródła; Diagnostyka systemu |
| Ustawienia | mapowanie aktywów, Execution Lock, pozostałe ustawienia |
