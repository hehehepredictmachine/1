# Raport E0 – przygotowanie i inwentaryzacja (PepeMarketWizard 1.41.0 → 1.42.0)

Kod aplikacji **nie został zmieniony**. Jedyna zmiana to plik `frontend/public/assets/cinematic/intro.mp4`, skopiowany z `update_1_42/zasoby/cinematic/` bez zmian (sumy pakietu zgodne z `MANIFEST_SHA256.txt`).

## 1. Kopia i wersja bazowa

- **Kopia:** nie tworzę gałęzi `ui/1.42-cinematic-forex`. Ta sesja może pracować i wypychać zmiany tylko na gałęzi `claude/keen-noether-tl9mzd`. Punktem przywracania jest commit wydania 1.41.0: `adafb1a` (paczki 1.41.0) oraz `a268218` (kod). Stan sprzed 1.42 da się w każdej chwili odtworzyć przez `git checkout adafb1a -- frontend desktop`.
- **Wersja bazowa:** `CHANGELOG.md` – najwyższy wpis 1.41.0, `APP_VERSION = "1.41.0"`. ✅

## 2. Wynik bazowy build/testy

- `npm run build` ✅ (4,6 s), `tsc -b` ✅ bez błędów. Film po buildzie jest w `frontend/dist/assets/cinematic/intro.mp4`. Backend serwuje go pod `/assets/cinematic/intro.mp4`: **200, `video/mp4`, 665 746 B** ✅
- `tools/run_tests.py` na tym samym kodzie (wydanie 1.41.0): **1373 testy**. Dwa padły w pierwszym przebiegu (`test_ui_cult` – zawijanie nazw w Wind Portal, `test_ui_foundation` – nowy model TiRex-2). Oba poprawione i powtórzone z wynikiem OK, pozostałe 1371 OK, 23 pominięte. Po poprawce nie powtarzałem całego zestawu, tylko te dwa pliki.
- Testy, które padały przed zmianami 1.42: **brak**.

## 3. Inwentaryzacja starego UI

Pełna lista plik po pliku: `E0_inwentaryzacja.md`.

| Kategoria | Plików |
|---|---:|
| `frontend/src` razem | 142 |
| STARE UI (archiwum w E8) | 123 – w tym `features/towers/*` (logika warstw wykresu do wydzielenia w `core/` w E3), `features/training-center/*` (akcje i potwierdzenia Centrum, reużyte w E5), `components/Dialogs*` / ustawienia / dźwignia (logika paneli S6 do przeniesienia w E7) |
| INFRASTRUKTURA (zostaje) | 9 – `api.ts`, `store.tsx`, `util.ts`, `telemetry.ts`, `env.d.ts`, `ui.ts`, `main.tsx` / `App.tsx` / `router.ts` (przepisywane w E1/E8) |
| Logika do reużycia (`core/`) | 8 – `chartprefs.ts`, `chartview.ts`, `zones.ts`, `ai.ts`, `ErrorBoundary`, `ChartPanel`, `ChartToolbar`, `ChartSettings` |
| STUDIO (osobny program) | 2 – `studio/main.tsx`, `studio.css` |

- Testy dotykające UI: **29** plików `tests/test_*.py` (Playwright / dist / `#/` / `data-testid`) oraz `tests/js/chartlab_calc.test.mjs`. Lista w `E0_inwentaryzacja.md`.
- Zasoby `frontend/public`: **78** plików – `assets/cult|galaxy|masterquo|neural|towers|wizard|wtc21`, `header_art.webp`, `favicon.svg` i nowy `assets/cinematic/intro.mp4`.
- Odwołania do `Launcher`, `launcherNeeded`, `BootScreen`, `GalaxyMenu`, `galaxyEngine`, `NeuralCityMenu`, `cult-launcher`, `galaxy-menu`, `pmw.boot`, `mq.cult.joined`: **95** miejsc w `frontend/src`, `tests`, `desktop`, `tools` i plikach `.md`.
- Odwołania do obrazów `assets/cult|galaxy|neural`: **29**.
- Uwaga do E8: `tools/build_release.py` bierze pliki z gita. Folder `update_1_42/` (film, zrzuty, HTML) **trzeba wykluczyć z paczek**, tak samo jak `archive/`.

## 4. Tabela S3 – endpointy i pola

Kształty odpowiedzi z trybu syntetycznego (tylko klucze i typy, bez danych rachunku): `E0_ksztalty_api.json`. Wszystkie **26 endpointów → HTTP 200**.

| Endpoint / pole | Wynik |
|---|---|
| `GET /api/v1/models/predictions?instrument=` | ✅ – lista jest w kluczu **`items`** (nie `predictions`); pola `unit`, `calibration.status`, `state`, `horizon`, `data_time` ✅ |
| `GET /api/v1/bot-signals`, `/bot-signals/{id}` | ✅ (`symbol`, `limit`, `rejected`) |
| `GET /api/v1/baskets/settings` → `active_profile` | ✅ |
| `GET /api/v1/candles?tf=` | ✅ `bars[]` + `indicators` (linie i panele RSI…) |
| `GET /api/v1/timeframes` | ✅ `timeframes`, `strategies` |
| `GET /api/v1/market-zones/bars?instrument=BTC&tf=` | ✅ `status/symbol/bars` (w symulatorze 300 świec BTC); `NO_SYMBOL` przy braku symbolu |
| `/api/v1/market-zones`, `/zones/map`, `/svp/status`, `/svp/profiles` | ✅ |
| `GET /api/v1/kronos/forecast` → `direction`, `neutral_band`, `uncertainty`, `horizon_bars` | ⚠️ inna postać: pola są **zagnieżdżone w `forecast`** (`forecast.direction`, `forecast.neutral_band`, `forecast.horizon_bars`…). Gdy Kronos nie jest zainstalowany, `forecast = null`. Pola `uncertainty` nie ma pod tą nazwą – do potwierdzenia w E3 na zainstalowanym Kronosie (w kodzie są `delta_pct`, `direction_pl`, `pred_close_h`). |
| `GET /api/v1/kronos` | ✅ |
| `/plans/chart`, `/sh/chart` | ✅ |
| `/setups`, `/setups/{id}/details`, `/sh/signals`, `/sh/signals/{sid}` | ✅ |
| `/models/catalog?instrument=`, `/eval/report` | ✅ |
| `/sh/scenario`, `/decision` | ✅ |
| `/trainhub/registry`, `/trainhub/version`, `/training/runs/{rid}/report`, `/trainhub/status` (`jobs/queue/data/defaults`), `/trainhub/jobs/{jid}` | ✅ |
| `GET /api/v1/sh/validation` → `status`, `reason` | ⚠️ inna postać: per ścieżka – `strategies.SCALPING.{status,reason}` i `strategies.HEDGING.{status,reason}` |
| `GET /api/v1/montecarlo/status` | ✅ (`validations[]`, `calibrated`, `active_calibration`) |
| `GET /api/v1/stats?mode=` | ✅ `bot.day/week/month/all`, `bot.recent`, `account`, `account_roi`, `engines.per_engine/per_strategy/per_symbol/per_month`, `equity.points/label/status`. Przy braku transakcji `bot.*` ma skróconą postać, a `account_roi` = `{status: NO_DATA, note}`. Pełne pola (`expectancy_r_se`, `max_drawdown`, `roi_pct`…) są w kodzie `stats.py` i pojawiają się, gdy są dane. |

## 5. Rozstrzygnięcia DO WERYFIKACJI

1. **Instrument BTC w CHARTS** – ✅ wystarcza `GET /api/v1/market-zones/bars?instrument=BTC&tf=…` (świece `o/h/l/c/tv`, `closed`). Ograniczenia: bez wskaźników z silnika (`indicators` ma tylko `candles` symbolu silnika) i bez aktualizacji na żywo przez WebSocket – odświeżanie przez polling.
2. **Bramki w SIGNALS** – dają je pola `GET /api/v1/decision`:

   | Bramka | Pole |
   |---|---|
   | DANE | `data_quality` |
   | KONTEKST | `market_state` + `context_tf` |
   | SETUP | `setup.state` + `setup.missing_confirmations` |
   | RYZYKO | `risk.risk_gate` + `risk.sizing_status` + `risk.limits_missing` |
   | AGENT | `agent_gate` |
   | TRYB | `mode_gate` |
   | WYKONANIE | `execution_permission` |
   | Lista kontrolna | `checklist` |
   | Drzewo | `decision_tree` + `reason_codes` |

   Dla SH: `GET /api/v1/sh/scenario` (`setup_status`, `setup_reason`, `trigger`, `invalidation`, `montecarlo`).
3. **Raport walidacji Monte Carlo** – ⚠️ brak endpointu z treścią raportu. `GET /api/v1/montecarlo/status` → `validations[]` zawiera tylko podsumowanie przebiegu (`status`, `verdict`, `variant`, `data_kind`, `dataset_id`, `report_sha256`, ścieżka pliku). Wniosek: diagramu rzetelności / Brier nie da się narysować z API. Ekran pokaże werdykt i status, a diagram jako `NOT_RUN` / „raport tylko w pliku”. Dodanie endpointu GET to zmiana backendu – **wymaga Twojej zgody** (patrz pytanie 2).
4. **Znaczniki wpłat w ROI** – ⚠️ `account` ma tylko **sumy** (`deposits`, `withdrawals`, `balance_operations_count`), bez listy z czasem. Zgodnie z S3 znaczników nie rysuję.
5. **Go ≥ 1.23 i sieć dla `build_desktop.py`** – ✅ `go1.24.7`. Build desktopu 1.41.0 przeszedł w tym środowisku (testy Go OK, `.exe` zbudowany).
6. **Okno Windows** – `desktop/window.go::panelURL` otwiera `?pmw_joined=1#/menu?intro=1` (pierwsze otwarcie) albo `?pmw_joined=1` + ostatni ekran (`app_windows.go:497`). Test `desktop_test.go:435` sprawdza dokładny adres – do aktualizacji w E8.

## 6. Pytania do Ciebie (blokują dalsze etapy częściowo)

1. **Studio** (`studio.html`, `frontend/src/studio/*`, `PepeTrainingStudio.exe`) – zostaje bez zmian? (domyślnie: **tak**)
2. **Raport Monte Carlo** – zgadzasz się na jeden nowy endpoint tylko do odczytu, `GET /api/v1/montecarlo/validations/{run_id}/report` (zwraca istniejący `report.json`)? Bez niego panel MONTE CARLO pokaże tylko werdykt i status, bez diagramu rzetelności. (domyślnie: **bez nowego endpointu**)
3. **Kronos** – pola `forecast.*` zamiast pól na najwyższym poziomie. Przyjmuję, że adapter `chartsData.ts` czyta `forecast.direction / neutral_band / horizon_bars`, a „niepewność” pokazuję z istniejących pól (`delta_pct`, pasmo neutralne), bez dopisywania nowego pola. (domyślnie: **tak**)

Czekam na „dalej” (oraz ewentualne odpowiedzi na pytania 1–3), zanim zacznę **E1 – cinematic i menu główne**.
