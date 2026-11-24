# PepeMarketWizard 1.41.0 – pełna aktualizacja: złoto zachowane, AI (TiRex-2, TabICLv2), moduły MQL5, trzy rynki, 90 strategii

## 1. Start (co zrobić po instalacji)

1. Rozpakuj `PepeMarketWizard_DESKTOP_1_41_0.zip` w miejsce poprzedniej wersji i uruchom `PepeMarketWizard.exe` jak dotąd.
   Ustawienia, historia, ledger, aktywne modele i konto **zostają** (migracja 1.41 robi tylko kopię zapasową i raporty).
2. Po ok. 60 s od startu bot sam (w tle, raz na 24 h, bez wstrzymywania handlu):
   * zapisuje raporty `data/reports/strategy_inventory_after.json`, `model_inventory_after.json`, `strategy_preservation.json`,
   * instaluje **TiRex-2** i **TabICLv2**, jeśli ich brak (pobranie wag z Hugging Face z kontrolą SHA-256; ręcznie:
     `41_AI_TABICL_TIREX_INSTALUJ.bat` albo przycisk „Zainstaluj” w panelu).
3. Moduły MQL5 i koszyki startują same (`DIRECT_USER_REQUEST`) – potrzebują tylko zamkniętych świec.
4. Gold OTC: podłącz własny, dopuszczony konektor (`POST /api/v1/baskets/otc/ticks`) albo wrzuć eksport notowań do `data/otc/import/`
   (CSV/JSONL), a w panelu „Gold OTC” wpisz bieżący payout i dozwolone czasy expiry. Do tego czasu profil pokazuje `WAITING_FOR_OTC_FEED`.

Panele: **Wykresy bota** → „Koszyki strategii 1.41”, „Moduły MQL5”, „Modele prognoz … TiRex-2” (+ karta TabICLv2);
**Modele i trening → Centrum treningu** → „Komponenty 1.41”. Menu nie zostało przebudowane.

## 2. Zachowanie strategii złota (najważniejsze)

* Inwentaryzacja przed/po: 38 wpisów (S01–S12, LEGACY SCALPING/HEDGING per instrument, paczka PMW_SC/HG01–10, profil
  MQ-SCALP-RANGE-SWEEP-1.1.0-RESEARCH, DOUBLE_RETEST_V2) – id, parametry, statusy, mapowanie XAUUSD/XAUUSD-, historia bez zmian.
* Nowe 90 strategii **nie zastępują** ani nie wyłączają starych, nie dodają im nowych bramek i nie tworzą drugiej trasy wykonania
  (`duplicate_execution_routes = []`). Raport `strategy_preservation.json` liczy `missing_strategy_ids`, `unexpected_config_changes`,
  `duplicate_execution_routes`, `orphaned_history_keys`.
* Rollback: `data/backups/pre-1.41.0` (konfiguracja; ledgery nie są cofane).

## 3. Stan AI – rzeczywisty

| Element | Stan po starcie | Uwagi |
|---|---|---|
| Kronos-base, Chronos-2, Granite TTM | bez zmian | jak w 1.40.6 |
| **TiRex-2** (NX-AI/TiRex-2, 82,5 mln param., pin rewizji + SHA-256) | instaluje się w tle; potem prognozy | ścieżki HOLD domyślnie OBSERVE (zachowanie złota); ASSIST dostępny jednym przełącznikiem (DIRECT_USER_REQUEST, bez SHADOW / win-rate) |
| **TabICLv2** (jingang/TabICL, classifier v2) | instaluje się w tle; estymator confidence Quant | `confidence_score = 100 × p_event_raw`, **UNCALIBRATED**; kontekst z ledgera lub przyczynowej rekonstrukcji SH; brak kontekstu = brak wartości (nie 50%) |
| SDformerFlow (port PyTorch, 702 917 param.) | brak gotowych wag w źródle → automatyczny trening bootstrap na prawdziwych H1 (≥ 600 świec) w środowisku z torch 2.14.1 | wynik `DIRECTION_SCORE_RAW` (nie prawdopodobieństwo); trening/fine-tune/resume/anuluj w Centrum |
| Graf cech (Cellular 10K, 50 cech) | od pierwszej zamkniętej świecy, start deterministyczny (COLD_START) | uczy się tylko na dojrzałych etykietach (każda raz) |
| G7 SMC Radar | od razu | `rule_confluence_score` 0–100 – reguła, nie prawdopodobieństwo; brak DXY ≠ 0 |
| Exponential Trend Channel | od razu (konfiguracja bazowa) | 12 cech as-of + maski; job OPTIMIZE w Centrum |
| COA → BChimp | co ≥ 300 s po ≥ 64 dojrzałych etykietach (≥ 16 nowych) | optymalizują tylko wagi analitycznego kompozytu (nie ryzyko, nie wielkość pozycji); atomowa publikacja, `STALE_PROPOSAL` |

Żaden moduł nie raportuje fikcyjnej skuteczności: metryki, których nie liczono, mają `null` / `NOT_RUN`.

## 4. Trzy rynki, 9 koszyków, 90 strategii

| Profil | Dane | Wykonanie |
|---|---|---|
| `FOREX_MT5` | bridge MT5 (dokładny symbol brokera, np. `XAUUSD-`) | **sygnały + plany** (koszyki nie składają zleceń; zlecenia nadal tylko istniejącą ścieżką bota) |
| `CRYPTO_FOMO_PERPS` (fomo.family) | publiczne Hyperliquid Info API: katalog (core + Trade[XYZ] `xyz:`), świece z wolumenem, mark/oracle, funding (1 h), OI, L2, agresor | `MANUAL_ONLY` – ticket do wykonania w FOMO (brak udokumentowanego API konta) |
| `OTC_GOLD_POCKETOPTION` | wyłącznie własny feed Gold OTC | `MANUAL_ONLY`; bez feedu `WAITING_FOR_OTC_FEED` |

* Koszyki: FX_SMC / FX_SCALP / FX_HEDGE, CP_SMC / CP_SCALP / CP_HEDGE, OTC_SMC / OTC_SCALP / OTC_HEDGE – po 10 kanonicznych ID,
  w każdym koszyku 10 różnych rodzin reguł (żadnych aliasów). Karty: `docs/koszyki_1_41/KARTY_STRATEGII.md`, parametry:
  `docs/koszyki_1_41/MANIFEST_9_KOSZYKOW_90_STRATEGII.json`.
* Wspólne detektory DET-1 (ATR, b, pivoty z opóźnionym potwierdzeniem, BOS/CHoCH, sweep, EQL, FVG, OB, breaker, OTE, BB, ADX, RSI2,
  RVOL, VWAP) liczone raz na instrument/TF/świecę.
* Wybór strategii `OFF / AUTO / MANUAL_SELECT` (osobno od trybu zleceń); AUTO kieruje reguły wg reżimu (trend / range / kompresja).
* Jedno zdarzenie = jeden plan główny (pozostałe strategie jako uzasadnienia); przeciwne kierunki → `CONFLICT` (WAIT).
* Ilość/stawka = `null`, dopóki nie skonfigurujesz kapitału profilu (nic nie jest zgadywane).
* HEDGING: planery działają tylko na istniejącej ekspozycji (FOREX – pozycje bota; FOMO/OTC – deklarowane ręcznie, `MANUAL_DECLARED`);
  bez niej `NO_EXPOSURE`. Na rachunku netting przeciwna transakcja = `REDUCE`, nie hedge.
* **OTC_PAYOFF_GATE**: pełna funkcja wypłaty grupy po przedziałach i remisach; CALL 100 + PUT 100 przy 80% = **−20** (remis 0),
  CALL nad PUT (Kc > Kp) = −200 między strikes; różne expiry nie są łączone; ochrona tylko przy poprawie najgorszego wyniku.
* Wyniki koszyków to `SIGNAL_SIMULATION` (przebieg sygnału na świecach), oddzielnie od PnL konta; OTC: WIN/LOSS/REFUND/UNKNOWN
  (brak ceny ≠ LOSS).

**Zaimplementowane: 90. Wykonalne w danej chwili: zależnie od danych** – licznik w panelu (FOREX: wszystkie TF z bridge; FOMO: od razu
z publicznych danych, warianty z L2 tylko dla instrumentu przepływu; OTC: po podłączeniu feedu). To nie jest 90 niezależnych przewag.

## 5. Centrum treningu – nowe komponenty

* `TH_SDFORMERFLOW` (TRAINABLE_SEQUENCE_MODEL): przygotuj dane, trening od zera, fine-tune, resume (ten sam dataset + pełny stan),
  anuluj (bez aktywacji), import/eksport ZIP (walidowany, bez skryptów), aktywacja z testem ładowania i skończoności, rollback.
* `ETC_LOG_CHANNEL` (FEATURE_TRANSFORM): przygotuj cechy, **OPTIMIZE** (COA → BChimp; cel: |udział zamknięć +10 świec w kanale − 0,90|),
  wersje, aktywacja w następnej generacji snapshotu, rollback, import/eksport.
* Wynik joba osobno: obliczenia / artefakt / aktywacja. Aktywacja nie nadpisuje nowszej decyzji użytkownika.

## 6. API (nowe)

`/api/v1/research-modules` (+ `/settings`, `/features`, `/feature-graph`, `/optimizer/jobs|run`, `/parameters/rollback`,
`/sdformerflow/train|cancel`), `/api/v1/baskets` (+ `/catalog`, `/settings`, `/signals`, `/declared/{profile}`, `/otc`, `/otc/meta`,
`/otc/ticks`, `/otc/payoff`), `/api/v1/trainhub/components` (+ `/{id}/jobs|cancel|activate|rollback|export.zip|import`),
`/api/v1/quant/tabicl` (+ `/install`, `/reconstruct`), `PUT /api/v1/quant/estimator`.

## 7. Ograniczenia (uczciwie)

* Środowisko budowy nie ma Windows ani MT5: ścieżka Windows sprawdzona testami jednostkowymi, symulatorem terminala i weryfikacją paczki;
  pierwszy prawdziwy start na Twoim komputerze pokaże stany w panelach.
* Licencje materiałów MQL5 (artykuły/CodeBase) nie są jawnie open-source: porty mają własne identyfikatory i atrybucję autorów,
  oryginalne archiwa nie są dołączone (`license_verified = false`).
* Brak API konta FOMO i Pocket Option → tylko tickety ręczne; feed Gold OTC musi dostarczyć użytkownik.
* p_event_raw jest nieskalibrowane; setup_score to jawna skala warunków, nie szansa wygranej.
