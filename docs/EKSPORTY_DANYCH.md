# Eksporty danych Apollo23 (1.46)

Jeden wspólny moduł `backend/masterquo/exports/`:

- `core.py` – zapis CSV i JSONL, plik `manifest.json`, SHA-256, kontrola sekretów, atomowy folder;
- `sources.py` – odczyt z istniejących magazynów, bez drugiego rejestru;
- `registry.py` – tabela eksporterów, która obsługuje CLI, API i testy;
- `tlg_import.py` – import kopii zapasowej TraderLifeGame.

## Uruchomienie

```
python -m masterquo export-list
python -m masterquo export-<nazwa> [--out FOLDER] [--format csv|jsonl|both] [parametry]
python -m masterquo import-trader-life-game --from FOLDER_EKSPORTU [--dry-run]
```

| Polecenie | Opis |
|---|---|
| `export-list` | Lista eksporterów i 15 ostatnich eksportów |
| `export-<nazwa>` | Eksport do `<dane>/exports` albo do `--out` |
| `import-trader-life-game` | Import kopii zapasowej gry |

API, czyli monitor ze swoją sesją:

- `GET /api/v1/exports` – lista eksporterów z parametrami i ostatnie eksporty;
- `GET /api/v1/exports/<nazwa>?parametr=…&format=csv|jsonl|both` – zapisuje **wyłącznie** do `<dane>/exports/<id>`, bez parametru ścieżki;
- `GET /api/v1/exports/<nazwa>/<id>/manifest` – manifest plus ponowna weryfikacja hashy;
- `POST /api/v1/exports/trader-life-game/import {"export_id": "...", "dry_run": false}` – wymaga Origin i CSRF; czyta tylko folder eksportu wskazany po zwalidowanym id.

Kody wyjścia CLI:

| Kod | Znaczenie |
|---|---|
| 0 | OK lub pusty eksport |
| 2 | Zły parametr albo błąd |
| 3 | `UNAVAILABLE`: źródło istnieje tylko w pamięci działającej aplikacji, a aplikacja nie działa |

Eksporter oznaczony „wymaga działającej aplikacji” uruchomiony z CLI prosi o eksport działającą aplikację przez lokalne API. Gotowy folder jest kopiowany do `--out`.

## Format wspólny

- Każdy zbiór danych zapisywany jest jako `<zbiór>.csv` i `<zbiór>.jsonl` (UTF-8).
- W JSONL wartości `null` są prawdziwe. W CSV puste pole oznacza `null`, czyli brak danych, a nigdy 0.
- NaN i Inf zapisywane są jako `null`.
- Czas zapisywany jest w UTC ISO-8601 w kolumnach `*_utc`.
- Dane MT5 mogą mieć dodatkowo czas serwera brokera w kolumnach `*_server`. Każda kolumna czasu ma etykietę w `manifest.files[].time_columns` (`UTC` / `BROKER_SERVER_TIME` / `UTC_EPOCH_SECONDS`).
- Jeśli offset serwera nie jest zweryfikowany, czas UTC wynosi `null`. Program go nie zgaduje.
- Jeden plik zawiera jeden rodzaj danych (`data_kind`): `REAL`, `DEMO`, `VIRTUAL`, `SIMULATED`, `SYNTHETIC`, `GAME`, `USER_NOTE`, `DERIVED`, `REFERENCE`, `CONFIG`, `STATE` lub `PROVIDER`. Dane realne i wirtualne nigdy nie trafiają do jednego pliku.

`manifest.json` (schemat `PMW-EXPORT-1.0.0`) zawiera:

- `export_id`, `export_name`, `status` (`OK` / `EMPTY` / `PARTIAL` / `UNAVAILABLE`), `created_at_utc`, `app`;
- `provenance` (źródło, wersje silników i metadanych, polityki), `params`;
- `date_range` (`from_utc`, `to_utc`, kolumny bazowe), `row_counts`, `total_rows`;
- `files` (ścieżka, format, liczba wierszy, bajty, SHA-256, `data_kind`, kolumny, kolumny czasu);
- `redactions`, `notes`.

Sekrety: wartości z SecretStore (klucz Claude, token Telegram, hasło MT5 i inne) oraz wzorce tokenów zastępowane są przez `[REDACTED]` jeszcze przed zapisem. Każda zapisana linia jest sprawdzana ponownie. Eksport z wykrytym sekretem jest usuwany i kończy się błędem.

Folder powstaje atomowo (`.<id>.partial` → `<id>`) i nigdy nie jest nadpisywany.

## Eksportery

| Nazwa | Źródło (odczyt) | Zbiory | Uwagi |
|---|---|---|---|
| `orderflow` | `TradeLedger` działającej aplikacji (TASK 004) + most rynku (Hyperliquid) | `trades`, `footprint`, `volume_profile`, `dom_snapshot`, `heatmap` | Wymaga działającej aplikacji. Strona agresora tylko zweryfikowana (Hyperliquid: `UNKNOWN`, delta = `null`). |
| `market-candles` | `markets.universe.*Bridge.candles` (TASK 003) | `candles_<symbol>_<TF>` dla 10 TF (`1d…1m`, `10m` z `5m`) | `--market CRYPTO\|INDICES\|FOMO_STOCK_PERPS`, `--instruments`, `--timeframes`, `--n`. INDICES i FOMO mają status RESEARCH_ONLY. |
| `fomo-universe` | seed FOMO 101 + aktualne metadane venue | `fomo_101_resolution` (101 wierszy), `metadata_versions` | SHA-256 seeda i `metadata_version` w provenance. |
| `strategy-roi` | `evaluation.strategy_roi` nad tabelą `trades` (tylko odczyt, `mode=ro`) | `roi_paper` (VIRTUAL), `roi_auto_demo` (DEMO), `roi_auto_live` (REAL) | Konto zamaskowane (`server:***123`). Brak bazy daje pusty eksport, a baza nie jest tworzona. |
| `sfb-snapshots` | `StrategyFilterBucket.snapshots` (pamięć, ostatnie 200) | `sfb_snapshots`, `sfb_items` | Wymaga działającej aplikacji. `apply_to_execution = false`. |
| `asge-trials` | `apollo.asge.TrialLedger` – od 1.46 trwały plik `<dane>/apollo/asge_trials.jsonl` (append-only) | `asge_trials` | Każda próba z rodowodem, `execution_allowed = false`. Działa też z CLI bez aplikacji. |
| `change-points` | PELT na zamkniętych świecach MT5 | `segments`, `change_points` | Wymaga działającej aplikacji. Czas UTC i czas serwera z etykietą. |
| `long-horizon` | prognoza 24/36/48/72 h na zamkniętych świecach MT5 | `forecasts` | Wymaga działającej aplikacji. Bez zweryfikowanego offsetu czasu status `UNAVAILABLE`. |
| `association-rules` | reguły asocjacyjne na zamkniętych świecach MT5 | `rules`, `assessment` | Wymaga działającej aplikacji. Tryb OBSERVE. |
| `pt-skill` | dziennik wyników `POST /api/v1/models/pt/evaluate` od startu aplikacji | `pt_results` | Wymaga działającej aplikacji. Dane wejściowe zapisane tylko jako SHA-256. |
| `dt-ranker` | dziennik wyników `POST /api/v1/models/dt-ranker/rank` (SHADOW) | `dt_rankings` | Wymaga działającej aplikacji. |
| `telegram-center` | pliki `<dane>/telegram_account/*.json` | `config`, `outbox_pending`, `sent_events`, `positions_state`, `seen_deals`, `center_state` | Token NIE jest eksportowany. Konto zamaskowane w kluczach i treściach. |
| `trader-life-game` | `<dane>/trader_life_game/game.sqlite` (tylko odczyt) | 15 tabel, np. `profile`, `xp_ledger`, `gold_ledger`, `quest_claims`, `journal`, `notes`, `sim_sessions`, `sim_trades`, `inventory` | Kopia zapasowa użytkownika (patrz import niżej). |
| `bootstrap` | `<dane>/bootstrap_state.json` | `components` | Brak pliku daje pusty eksport. |
| `store-tables` | trwałe magazyny SQLite bez eksportu zbiorczego | jedna tabela = jeden plik, rozdzielony według trybu | `--store main\|svp\|indicators\|baskets\|zones\|market-zones\|evaluation\|mm\|quant\|trainhub\|news`, `--tables`. Tabele z danymi osobowymi są wyłączone. |

Szczegóły `store-tables`:

- Wyłączone tabele: `accounts_seen`, `account_prefs`, `agent_runs`, `agent_memory`, `notifications_sent`, `settings_audit`.
- Magazyn `indicators` zawiera m.in. snapshoty DOM MT5 (`book_snapshots`).
- Tabele z kolumną `mode`/`exec_mode` dzielone są na pliki według trybu: PAPER = VIRTUAL, AUTO_DEMO = DEMO, AUTO_LIVE = REAL, inne = DERIVED.
- Wiersze z `synthetic = 1` trafiają do osobnego pliku `…__synthetic` (SYNTHETIC).

Eksporty istniejące wcześniej działają bez zmian:

- `export` – M06R, UTC + surowy czas serwera, `<dane>/export_mt5_utc`;
- `export-candles`, `export-scalp`;
- `training export` / `POST /api/v1/export/start`;
- `trainhub export` (magazyn `marketdata`);
- paczki ZIP treningu;
- eksport biblioteki wzorców.

## Import kopii TraderLifeGame

`python -m masterquo import-trader-life-game --from <folder eksportu trader-life-game>` albo `POST /api/v1/exports/trader-life-game/import`.

- Najpierw weryfikowany jest manifest, czyli schemat, SHA-256 i liczba wierszy każdego pliku. Wymagany jest JSONL.
- **Import jest addytywny i idempotentny.** Wiersze wstawiane są jako `INSERT OR IGNORE` po kluczach tabel (klucze idempotencji ledgerów, klucze główne). Istniejący wiersz nie jest zmieniany ani usuwany, istniejący profil zostaje. Powtórny import tej samej kopii nic nie zmienia.
- **Import jest odwracalny.** Przed pierwszym zapisem bieżąca baza kopiowana jest do `<dane>/backups/tlg-before-import-<UTC>.sqlite`. Żeby cofnąć import, zatrzymaj aplikację i skopiuj ten plik w miejsce `game.sqlite`.
- Nazwy kolumn sprawdzane są z `PRAGMA table_info`. Cały import odbywa się w jednej transakcji.
- `--dry-run` pokazuje podgląd bez zapisu.

## Czego nie da się wyeksportować i dlaczego

- **EventBus, wyniki skanera rynków, stany `IndicatorEngine`, encoder BAT:** to bufory w pamięci, odtwarzane od startu, bez stanu do zachowania.
- **Ledger orderflow, snapshoty SFB, dziennik PT/DT:** istnieją tylko w pamięci działającej aplikacji. Eksport działa przez API albo przez CLI połączone z działającą aplikacją.
- **Sekrety** (`secrets.*.json`) **oraz klucz i baza licencji właściciela** są celowo poza zakresem eksportu.
