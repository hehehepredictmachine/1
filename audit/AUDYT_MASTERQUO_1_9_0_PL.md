# Audyt MasterQUO 1.9.0 – kod, strategie, ML, koszty, wykonanie, statystyki

**Data:** 2026-10-13.

**Zakres:** aktywny kod repozytorium w commicie `318ce0d` (wersja `1.9.0`, `backend/masterquo/version.py`). Paczka referencyjna to
`release/MasterQUO_KLIENT_1_9_0.zip`, SHA-256 `be18f5440fc4f63a6131419b0bb28cd0be4edf2f9e672b3646cbd514c0dc94d0`.

**Tryb pracy:** AUDYT + REPRODUKCJE + PLAN.
- Reprodukcje działają na kopii danych w katalogu tymczasowym, na atrapach terminala MT5 i bez żadnego zlecenia.
- Poprawki opisane w sekcji 8 zostały wdrożone **osobno**, w wersji 1.10.0 (patrz `CHANGELOG.md`). Ten raport opisuje stan 1.9.0.
- Wynik reprodukcji po poprawkach jest w osobnym pliku: `audit/repro/wyniki_1_10_0_po_naprawach.json`.

**Oznaczenia ustaleń:**
- POTWIERDZONE_W_KODZIE – widać w kodzie;
- ODTWORZONE_TESTEM – odtworzone skryptem;
- HIPOTEZA_DO_TESTU – wymaga danych;
- BRAK_DANYCH;
- NIE_DOTYCZY.

**Oznaczenia wyników:** wszystkie wyniki w tym raporcie to **SYNTHETIC_FUNCTIONAL**, czyli sprawdzenie działania kodu, a nie zyskowności. Wyników IN_SAMPLE, VALIDATION, UNTOUCHED_OOS i FORWARD brak, bo brak historii brokera.

---

## 1. Stan systemu i środowisko audytu

| Element | Stan |
|---|---|
| Wersja | 1.9.0 (licencjonowanie usunięte); git czysty, gałąź `claude/masterquo-ai-bot-mt5-f7uaht` |
| Interpreter audytu | Python 3.13.16 (Linux), scikit-learn 1.9.1, xgboost 3.4.1, numpy 2.5.3, fastapi 0.141.1 |
| Terminal MT5 | **brak** (Linux, kontener). Połączenie z Twoim terminalem **nie jest potwierdzone**. Użyto symulatora `FakeMT5` i atrap |
| `data/config.json` użytkownika | **brak w repozytorium**. Raport opisuje wartości **domyślne** z `config.py`. Nie twierdzę, że Twój bot działa z tymi wartościami |
| Symbol | `XAUUSD-` (dokładnie, z sufiksem; brak automatycznej podmiany – `config.py`, `mt5/bridge.py`) |
| Profil „Zero” | `costs.account_profile = ZERO_DECLARED_COSTS_UNVERIFIED` – deklaracja, nie dowód zerowych kosztów |

**Skuteczna konfiguracja domyślna** (odczytana przez `ConfigStore().get()` w izolowanym katalogu):

- profil `ACTIVE`, tryb wykonania `PAPER`, `allow_live_execution=False`;
- S11: `scan=True`, `trade=False` – **potwierdzone w skutecznej konfiguracji** (`config.py:242`, `strategies/registry.py:25`);
- `structure_policy=H1_LEAD`;
- `rr_block_below=1.0`, `rr_pass_from=1.5`, `conditional_rr_executes=True`, `conditional_risk_factor=0.5`;
- `macro_calendar_required=False`;
- `agent.gate_policy=VETO`;
- `ml.mode=SHADOW`, `ml.collect=True`;
- `commission_mode=FROM_DEAL_HISTORY`, `commission_per_lot_per_side=None`;
- `slippage_stress_points=20`;
- `spread_40pct_rule=REQUIRES_DEFINITION`;
- `tp1_weight=0.5`, `move_sl_to_breakeven_after_tp1=True`.

**Moduły aktywne a nieaktywne:**
- Aktywny kod: `backend/masterquo/*`, `frontend/src`, `tools/*.py`.
- `backend/vendor/legacy_core` jest **wywoływany** w profilu ORIGINAL (silnik M01–M07 przez `engine/legacy.py`) i w części ACTIVE (m02/m03 w snapshotach). Przeczytano interfejs `engine/legacy.py`; wnętrza vendor nie audytowano linia po linii.
- `research/`, `archive/` i stare ZIP-y w `release/` nie są wywoływane.

## 2. Łańcuch decyzji (stan 1.9.0)

```
MT5 (mt5/bridge.py, worker.py, clock.py)
 -> jakość/czas (data/quality.py, mt5/clock.py: offset mierzony z ticków; bez offsetu: TIME_OFFSET_UNVERIFIED, wejścia zablokowane)
 -> MarketView (strategies/base.py: tylko ZAMKNIĘTE świece + osobno świeca tworząca się)
 -> wskaźniki / reżim (strategies/indicators.py, regime.py)
 -> wykrycie setupu S01–S11 (strategies/sNN_*.py -> Draft) -> punktacja + etap (base.finalize: WATCH/EARLY/CONFIRMED)
 -> tracker wersji (strategies/tracker.py) -> selektor AUTO (strategies/selector.py; AUTO = wybór STRATEGII, nie wykonanie)
 -> poziomy (engine/active.levels_for; S11: engine/service._tp_from_entry RR_FROM_FILL)
 -> ryzyko i koszty (risk/engine.evaluate, risk/costs.resolve_commission)
 -> bramki ML / Claude / tryb (ml/service.gate, agent/service.gate_for, execution/modes.gate) -> decision.build
 -> gateway (execution/gateway.py: ponowna walidacja, order_check, idempotencja entry_key, UNKNOWN bez ponowień)
 -> zarządzanie pozycją (execution/manager.py: TP1 częściowe, BE, rekonsyliacja; PAPER: execution/paper.py)
 -> rozliczenie (manager._settle_mt5 z historii deals; PAPER: paper._accumulate) -> statystyki/ROI (stats.py)
```

**Moment dostępności informacji:**
- Strategie widzą tylko zamknięte świece. Świeca tworząca się może podnieść etap najwyżej do EARLY (`base.finalize`: TRIGGER na świecy tworzącej się → EARLY, `TRIGGER_BAR_NOT_CLOSED`).
- H8 dla S11 jest wyrównywany as-of (`ema_pullback_core.asof_h8_trend`). Cechy ML są cięte as-of (`ml/features.py`, nagłówek).
- Te reguły są **POTWIERDZONE_W_KODZIE** i pokryte testami `test_ema_pullback` oraz `test_bridge_engine`.

**Ścieżki składania zleceń:** jedyna ścieżka `order_send` dla wejścia to `ExecutionGateway._send`. Ścieżki wyjścia:
- `PositionManager._partial_close` (TP1),
- `_move_be` (SLTP),
- `close_positions` (ręczne).

PAPER nie dotyka funkcji handlowych terminala. To jest **POTWIERDZONE_W_KODZIE**.

**AUTO wyboru a AUTO wykonania:**
- Selektor wybiera strategię.
- Wykonanie automatyczne zachodzi tylko gdy `mode_gate.auto_trading` (AUTO_DEMO/AUTO_LIVE) – `engine/service.py` w `light_cycle`.
- Sygnały skanera innych rynków (`markets/signals.py`) nie trafiają do gateway. To jest POTWIERDZONE_W_KODZIE.

## 3. Punkty startowe A–J – weryfikacja

Odtworzenia: skrypt `audit/repro/repro_audit.py`. Wynik dla 1.9.0 jest w pliku `audit/repro/wyniki_1_9_0_przed_naprawami.json` – **8/8 REPRODUCED**.

### A. Koszt prowizji w ML ≠ koszt wykonania — **ODTWORZONE_TESTEM**, P0

**Dowód w kodzie:** `ml/service.py:124-140` (`MLService._cost`).
- Funkcja bierze tylko `costs.commission_per_lot_per_side`.
- Przy `None` dodaje `COMMISSION_UNKNOWN_ASSUMED_0` i liczy prowizję 0.
- Wykonanie (`risk/costs.py:146 resolve_commission`, `execution/paper.py:52`) przy domyślnym `FROM_DEAL_HISTORY` bierze medianę z historii deals.

**Reprodukcja:** prowizja 3,5 USD/lot/stronę w historii, pole ręczne puste.
- Wykonanie: `3.5 (DEAL_HISTORY_MEDIAN)`.
- Etykieta ML: `0.0` + flaga `COMMISSION_UNKNOWN_ASSUMED_0`.

**Dodatkowe problemy:**
- Próbka powstaje z `quality="HIGH"` (`ml/service.py:113`).
- `dataset.eligible()` (`ml/dataset.py:100`) nie filtruje flag kosztów, więc próbki z kosztem 0 trafiają do treningu jako wysokiej jakości.
- Konwersja `cps / trade_contract_size` zakłada, że waluta rachunku = waluta kwotowania (USD). Dla rachunku w innej walucie wynik jest błędny. To jest HIPOTEZA_DO_TESTU, bo brak danych rachunku.
- Mediana prowizji per deal (`risk/costs.py:142`) zniekształca taryfę naliczaną tylko na otwarciu lub tylko na zamknięciu. Wtedy połowa deali ma 0, a mediana może wyjść 0. To jest POTWIERDZONE_W_KODZIE i dotyczy wykonania oraz PAPER.

**Wpływ:**
- Przy konfiguracji domyślnej (pole ręczne puste) **każda** etykieta ML zawyża wynik netto o 2 × prowizję.
- Na złocie 3,5 USD/lot/stronę i SL 5 USD/oz to ok. 0,014 R na transakcję.
- Etykiety na granicy BE zmieniają klasę.

**Pewność:** wysoka.

### B. PAPER wlicza częściowo zamkniętą pozycję — **ODTWORZONE_TESTEM**, P0

**Dowód w kodzie:**
- `execution/paper.py:90-115` (`_accumulate`) tworzy wiersz `trades` z `closed_at` już przy pierwszym częściowym wyjściu.
- `stats.py:65 bot_stats` czyta `trades` bez sprawdzenia `managed_positions.state`.

**Reprodukcja:** wejście 2000,2, TP1 2005,1 (0,05 lota), potem reszta stopem.
- Po TP1, przy pozycji `OPEN`, statystyki pokazują `trades=1, wins=1`.
- Po zamknięciu reszty: `trades=1, losses=1, net=-26,5`.

**Wpływ:** w trakcie życia pozycji winrate, PF i krzywa wyniku zamkniętych transakcji są zawyżone. Wiersz jest nadpisywany przy kolejnych wyjściach, więc ta sama transakcja nie jest liczona dwa razy, ale „wygrana” jest raportowana przed końcem pozycji.

**Pewność:** wysoka.

### C. TP1 → BE w jednej świecy M1 — **ODTWORZONE_TESTEM**, P0

**Dowód w kodzie:** `ml/labels.py:99-123`.
- Po trafieniu celu (`tgt_hit`) pętla `while` ustawia `state["stop"] = entry` (linia 119).
- Ponownie wywołuje `_touch` na **całej** świecy, więc minimum sprzed TP1 trafia nowy stop.

**Reprodukcja** (przypadek z promptu):
- Dane: LONG 100, SL 90, TP1 105 (waga 0,5), TP2 110 (waga 0,5), świeca o=100 h=106 l=99 c=106, ticki 100→99→105→106.
- Wynik: `BREAKEVEN_STOP, remaining=0, outcome_r=0.25`.
- Poprawnie: po TP1 pozycja 0,5 nadal otwarta, SL = 100, brak wyniku końcowego w tej minucie.

**Wpływ:** etykiety zaniżają wynik strategii z BE po TP1 (zamykają resztę na BE, choć cena nie wróciła). Model uczy się na zniekształconych klasach.

**Pewność:** wysoka.

### D. S11: `time_exit_bars=None` — **ODTWORZONE_TESTEM**, P0

**Dowód w kodzie:**
- `strategies/s11_ema_pullback.py:121` ustawia `time_exit_bars: None`.
- `ml/labels.py:152`: `int(None)` daje `TypeError`.
- `tools/replay_strategies.py:108`: `None * int` daje `TypeError`.

**Realna ścieżka:** `ml/service.on_setup_events` łapie wyjątek (linia 115), zapisuje `last_error=COLLECTOR:TypeError` i **pomija próbkę**. Skutek:
- S11 nigdy nie trafia do zbioru ML (cicha selekcja);
- replay S11 przerywa się wyjątkiem.

**Dodatkowo:**
- Etykieta liczy TP z rekordu setupu (cena z zamknięcia świecy sygnału), a nie od rzeczywistego fillu. Plan S11 to `RR_FROM_FILL` (`engine/service.py:354 _tp_from_entry`), więc etykieta ≠ wykonanie.
- `ml/features.py:23` opis schematu kategorii obejmuje tylko S01–S10 i M1/M5/M15/H1. **Weryfikacja:** kodowanie (`ml/prep.py:39`) używa kategorii **zaobserwowanych w treningu**, więc S11 i M30 są kodowane, gdy występują w danych. To jest wyłącznie niekompletna dokumentacja schematu (NIE_DOTYCZY jako błąd modelu).

**Pewność:** wysoka.

### E. Reguły wyjścia nie są wspólne — **ODTWORZONE_TESTEM**, P0

**Dowód w kodzie:**
- `execution/manager.py:137,147,254,258` używa globalnych `cfg.strategy.tp1_weight` i `move_sl_to_breakeven_after_tp1`.
- `gateway._register_position` (`gateway.py:209`) i `manager._register_from_attempt` (`manager.py:114`) zapisują tylko `tp1=t[0]` i `tp2=t[-1]`. **Cel środkowy znika.**
- Brak obsługi `time_exit_bars` i `trailing` (np. S02 `KAMA_STATE_FLIP`) w zarządzaniu na żywo.
- Etykiety ML i replay używają `exit_rules` setupu, więc live/PAPER ≠ etykiety/replay.

**Reprodukcja:** 3 cele z wagami 0,3/0,3/0,4 i `be_after_tp1=False`.
- PAPER zamknął 0,05 lota (waga globalna 0,5 zamiast 0,3).
- Przesunął SL na BE (wbrew planowi).
- Zapisał tylko cele 2004 i 2012.

**Zmiana ustawień w trakcie pozycji:** zmiana `tp1_weight` lub BE w konfiguracji zmienia zarządzanie **otwartą** pozycją, bo polityka nie jest zapisana przy otwarciu.

**Pewność:** wysoka.

### F. Stan TP1 przed potwierdzeniem `order_send` — **ODTWORZONE_TESTEM**, P0

**Dowód w kodzie:** `execution/manager.py:160-170` – `tp1_done=1` jest ustawiane **przed** `order_send`.

**Reprodukcja:** broker odrzuca częściowe zamknięcie (10006 REJECT).
- Zostaje `tp1_done=1`, wolumen 0,10 (nic nie zamknięto).
- W następnym ticku wysłane zostaje przesunięcie SL na BE.
- Skutek: pozycja „po TP1” bez zrealizowanego zysku.

**Częściowy fill (10010) i timeout:** brak stanu pośredniego (REQUESTED/UNKNOWN) i brak rekonsyliacji wolumenu z historią deals dla wyjścia TP1. Wolumen jest jedynie aktualizowany z pozycji (`manager.py:133`).

**Restart po timeout:** `tp1_done=1`, więc nie będzie drugiego wysłania (zamierzone). Brak jednak informacji, czy zamknięcie się odbyło.

**Pewność:** wysoka.

### G. Podziały ML i promocja — **ODTWORZONE_TESTEM** (zbiór championa), reszta POTWIERDZONE_W_KODZIE / HIPOTEZA

**Zbiór championa ≠ zbiór challengera:**
- `ml/registry.py:104-122 _champion_brier_on` wybiera próbki testowe **oknem dat** `[w0, w1]`.
- `validation.split` przypisuje próbkę do bloku zdarzenia (event grouping). Próbka z datą w oknie testu może należeć do bloku CALIB.
- **Reprodukcja:** blok testu ma 19 próbek, okno dat 20 (dodatkowo `S081` z bloku CALIB). Champion i challenger są oceniani na różnych zbiorach.

**Purging tylko między sąsiednimi blokami** (`validation.py:52-58`):
- Gdy blok TUNE jest pusty, `if not blocks[b]: continue` pomija purging FIT względem kolejnych bloków. To jest POTWIERDZONE_W_KODZIE.
- Przy niepustych blokach purging jest przechodni (koniec etykiety FIT ≤ start TUNE − embargo < start CALIB), więc w typowym przypadku przecieku nie ma.

**Purging po `label_end_utc`, nie po `label_known_utc`:** `label_known_utc ≥ label_end_utc`, więc różnica dotyczy tylko opóźnienia odczytu. To jest HIPOTEZA o niskim wpływie.

**`last_test_end()`** (`registry.py:61-65`, `LIMIT 20`):
- Okna testów rosną monotonicznie, więc maksimum z ostatnich 20 rekordów praktycznie równa się maksimum globalnemu.
- Ryzyko ponownego użycia holdoutu jest niskie, ale zależy od kolejności `created_at`, a nie od jawnego rejestru zużytych okien. To jest HIPOTEZA o niskim wpływie.

**Promocja:**
- `registry._rules` porównuje `avg_r` z polityką bez ML oraz `max_dd_r` (`registry.py:139-147`) i Brier.
- `validation.policy_eval` (`validation.py:123`) to „jedna pozycja naraz, wszystkie setupy CONFIRMED”. **Nie** odtwarza selektora AUTO, bramek ryzyka i trybu ani limitów kapitału.
- Wyższe `avg_r` przy mniejszej liczbie wejść może dać niższy wynik w tym samym okresie.
- To jest POTWIERDZONE_W_KODZIE; wpływ to HIPOTEZA_DO_TESTU.

### H. Łagodniejsze progi domyślne — **HIPOTEZA_DO_TESTU**

Wartości `H1_LEAD`, `rr_block_below=1.0`, `rr_pass_from=1.5`, `conditional_rr_executes=True`, `conditional_risk_factor=0.5`, `macro_calendar_required=False` i `gate_policy=VETO` są POTWIERDZONE w skutecznej konfiguracji domyślnej.

**Nie są błędami.** Ich wpływ na expectancy i ROI jest nieznany (BRAK_DANYCH). Protokół porównania jest w `PROTOKOL_WALIDACJI.json` (warianty `H-STRICT-*`).

### I. Kontrakt czasu — **BRAK_DANYCH** (terminal), logika POTWIERDZONE_W_KODZIE

**Co jest w kodzie:**
- `mt5/clock.py` mierzy offset `raw − utc_now` z ticków.
- Przyjmuje go tylko przy zgodności próbek i wyrównaniu do 15 minut.
- Bez offsetu bary są oznaczone `TIME_OFFSET_UNVERIFIED`, a wejścia blokowane.
- Dokumentacja MetaTrader5 Python opisuje czasy jako UTC. Kod zakłada, że broker może podawać czas ścienny serwera jako epoch, i **mierzy** to, zamiast zakładać.

**Bez surowych logów Twojego terminala nie da się rozstrzygnąć:**
- czy offset jest właściwy;
- czy nie występuje podwójne przesunięcie;
- zachowania w weekend i przy DST.

**Potrzebne dane:** `06_DIAGNOZA_CZASU_MT5.bat` (eksport `time`/`time_msc`, UTC PC, czas odbioru) z kilku sesji, w tym po zmianie czasu.

Etykiety ML (`labels.py:82`) traktują lukę ≥ 50 min jako przerwę sesji, a 15–50 min jako MISSING_DATA. Sama długość luki nie dowodzi legalnej przerwy. To jest POTWIERDZONE_W_KODZIE; wpływ to HIPOTEZA.

### J. PAPER nie jest dowodem jakości filli — **ODTWORZONE_TESTEM** (P/L=None→0), reszta POTWIERDZONE_W_KODZIE

**`_profit(...)=None → 0`:** `execution/paper.py:79` – `gross = ... or 0.0`.
- **Reprodukcja:** brak kalkulatora daje transakcję `gross=0, net=0`, zaliczaną w statystykach jako BE.
- Powinna być **nierozliczona**.

**Brak modelu w PAPER:**
- dodatkowego poślizgu,
- swapu,
- opłat,
- latencji,
- odrzuceń.

Fill to bieżący Bid/Ask w chwili odczytu co ≈ 1 s (`manager._loop`).

**Fill przy przejściu SL i TP:**
- SL po luce jest wypełniany gorszą ceną (poprawne).
- TP po przeskoku jest wypełniany ceną bieżącą, czyli lepszą od TP (`manager.py:250`).
- Przy broker-side TP w MT5 wykonanie po luce też jest rynkowe, więc nie jest to błąd. Przy próbkowaniu 1 s może jednak zawyżać wynik. To jest HIPOTEZA_DO_TESTU.

**Przeskok przez TP1 i TP2 między odczytami:** cała pozycja zamyka się na TP2 (sprawdzanie TP2 przed TP1). To odpowiada zachowaniu brokera, który ma ustawiony tylko TP końcowy.

## 4. Dane, wskaźniki, setupy

**Świece i dostępność:**
- `TFView` przyjmuje tylko świece `closed`. Świeca tworząca się jest osobno (`base.py:32-44`).
- Pivoty potwierdzone („3/3”) w S06 i S10 są rozpoznawane po prawych świecach.
- `features.confirmed_index` jest liczony as-of.
- To jest POTWIERDZONE_W_KODZIE. Pokrycie: `test_strategies`, `test_ema_pullback` (brak lookahead H8).

**W1/MN1:** w 1.9.0 nie są pobierane. Strefy tygodniowe i miesięczne nie istnieją, czyli NIE_DOTYCZY dla S01–S11.

**Hipotezy S01–S11** (z kodu, bez oceny skuteczności – BRAK_DANYCH):

| ID | Rodzina | Hipoteza ekonomiczna | Trigger (zamknięta świeca) | Unieważnienie | Wyjście | Kiedy traci sens |
|---|---|---|---|---|---|---|
| S01 | TREND | kontynuacja trendu po korekcie | zamknięcie powyżej high poprzedniej świecy po kontakcie ze strefą EMA20/50 | zamknięcie pod dołkiem korekty − 0,2 ATR | TP1 szczyt impulsu, TP2 measured move, BE, time-exit 36 | trend nieefektywny (ER niski), głęboka korekta |
| S02 | TREND | zmiana stanu trendu (KAMA/ER) | stan UP po świecy nie-UP | zamknięcie pod KAMA − pasmo | 1,5R/3R, **trailing KAMA (niezaimplementowany na żywo)** | rynek boczny, piła |
| S03 | BREAKOUT | wybicie kanału Donchiana | zamknięcie nad górą + bufor, świeca ≤ max ATR | zamknięcie pod środkiem kanału | measured move 0,5/1,0 szer. | fałszywe wybicia w range |
| S04 | BREAKOUT | ekspansja po kompresji | zamknięcie nad boxem + bufor, ≤ max_entry_atr | zamknięcie pod środkiem boxa | 1×/2× wys. boxa | brak wcześniejszej kompresji |
| S05 | BREAKOUT | wybicie zakresu otwarcia sesji | zamknięcie M5 nad high zakresu + bufor | zamknięcie pod środkiem | 1×/2× zakresu, koniec okna sesji | niska aktywność sesji |
| S06 | BREAKOUT | wybicie → retest → reakcja | zamknięcie nad high świecy retestu | zamknięcie pod poziom − fail_atr | TP1 max od wybicia, TP2 2R | brak retestu, powrót do zakresu |
| S07 | REVERSION | nieudane wybicie i powrót | zamknięcie nad poziomem + bufor | zamknięcie pod ekstremum wyjścia | środek / przeciwna krawędź | silny trend (akceptacja poza) |
| S08 | REVERSION | odrzucenie krawędzi konsolidacji | świeca odrzucenia w strefie krawędzi | zamknięcie pod dołem − 0,3 ATR | środek / przeciwna krawędź | wybicie zakresu |
| S09 | REVERSION | powrót po odchyleniu z-score | min z ≤ −2, z rośnie, świeca wzrostowa | SMA − stop_z × σ | SMA − σ / SMA, time-exit 20 | efektywny trend (ER) |
| S10 | REVERSAL | wyczerpanie + zmiana struktury | zamknięcie nad CHoCH + bufor | zamknięcie pod ekstremum | 50%/78,6% impulsu | impuls trwa bez dywergencji |
| S11 | TREND | EMA20 pullback, 2,5R | zamknięcie nad EMA20 na świecy późniejszej niż dotknięcie | zmiana trendu / timeout | RR 2,5 od fillu, bez TP1/BE/time-exit | ADX niski, range |

**Powielenia między strategiami:**
- S03, S04 i S06 to rodzina wybić z podobnym triggerem zamknięcia poza poziomem.
- S07 i S08 to rewersja na krawędziach zakresu.
- W jednym ruchu mogą dawać kilka setupów. Grupowanie `event_id` (`common.level_bucket`) łączy je w jedno zdarzenie dla ML i sygnałów, ale tracker wciąż pokazuje kilka setupów.
- To jest POTWIERDZONE_W_KODZIE; korelacja wyników to BRAK_DANYCH.

**Punktacja 0–100 (`base.score`):** służy do rankingu i nie jest prawdopodobieństwem (opis w `setup_details`). To jest POTWIERDZONE.

**Tick volume:** nazywany „aktywnością feedu brokera” (`base.py:42`, `features.py`). To jest POTWIERDZONE.

**Volzones (`engine/volzones.py`):**
- HV z D1 jest nazywane w UI „IV walls”. Moduł zapisuje źródło (`HV`/`MANUAL`), ale **nazwa warstwy sugeruje IV**.
- Moduł podaje `p_close_beyond` i `p_touch` z Black-76 przy sigma z HV i forwardzie = spot. To są wielkości modelowe, a nie rynkowe prawdopodobieństwa.
- Strategie ich nie używają – tylko agent i UI.
- To jest POTWIERDZONE_W_KODZIE, ryzyko interpretacyjne. Poprawka w 1.10.0: rozdzielenie IV_SOURCED/IV_MANUAL/HV_PROXY.

## 5. Koszty, sizing, wykonanie

**Spread:**
- Wejście LONG po Ask, SHORT po Bid; wyjście po stronie przeciwnej.
- Spread nie jest doliczany drugi raz (`risk/costs.py` nagłówek, `risk/engine.py`).
- To jest POTWIERDZONE, test `test_risk_execution.test_spread_not_double_counted_and_rr_net`.

**Kalkulatory brokera:**
- Strata i zysk z `order_calc_profit`, margin z `order_calc_margin`.
- Nominał z `order_calc_profit(1 lot, ±1%) × 100` – bez założonej wielkości kontraktu.
- Istniejące pozycje i zlecenia oczekujące są liczone osobno (`engine/service.portfolio_snapshot`).
- `order_check` wywoływany jest przed `order_send`.
- To jest POTWIERDZONE (1.8, `test_leverage_sizing`).

**Zaokrąglenia i limity:**
- Loty zaokrąglane w dół; minimalny lot ponad budżet → BLOCKED.
- Dźwignia nie zwiększa budżetu.
- To jest POTWIERDZONE, testy.

**`spread_40pct_rule = REQUIRES_DEFINITION`:** nie jest filtrem, co jest poprawne. `markets/signals.py` stosuje „spread ≤ 50% ryzyka” tylko w skanerze innych rynków. Propozycje jawnych miar są w planie (P1-8).

**Idempotencja i UNKNOWN:**
- Wejście ma `UNIQUE entry_key`.
- Wynik UNKNOWN rozstrzygany jest z terminala bez ponownego wysłania (`manager._resolve_unknown`).
- To jest POTWIERDZONE.

**Wyjścia (TP1/BE):** brak idempotencji na poziomie stanu (usterka F).

**Konto netting:** `margin_mode` jest przekazywany do ryzyka. Częściowe zamknięcie na netting działa przez `position=ticket`. To jest HIPOTEZA_DO_TESTU na prawdziwym terminalu.

**SL/TP chronione u brokera a TP1/BE aplikacji:**
- SL i TP końcowy są wysyłane w zleceniu wejścia (`gateway._send`), więc chronią pozycję także po zamknięciu programu.
- TP1 i BE wykonuje działająca aplikacja (manager).
- Rozróżnienie jest POTWIERDZONE, ale nieopisane w UI. Opis dodano w 1.10.0.

## 6. Metryki i ich definicje

**Winrate, BE i PF** (`stats.py`):
- winrate = wins/(wins+losses);
- BE to |R| ≤ 0,05 po kosztach, raportowane osobno;
- PF = zyski / |straty|, przy braku strat brak wartości.
- Definicje są POTWIERDZONE w `stats.DEFINITIONS`.
- Brakuje raportu wins/wszystkie zamknięte. Dodane w 1.10.0 jako `win_rate_all_closed`.

**R:** `r_multiple = net / planned_risk_money` (ryzyko planowane przy otwarciu). R planowane i R z fillu nie są rozdzielone. To jest POTWIERDZONE_W_KODZIE.

**ROI rachunku** (`stats.account_roi`):
- Metoda Dietza ze snapshotów equity co 60 s.
- Operacje balance są przepływami. **Credit/bonus** (typy deal 3 i 6) nie są traktowane jako przepływy (tylko typ 2). To jest POTWIERDZONE_W_KODZIE, HIPOTEZA wpływu.
- ROI całego rachunku (z ręcznymi transakcjami) **nie jest** ROI bota. UI to opisuje.
- Drawdown z próbkowania co 60 s może pomijać głębsze obsunięcia wewnątrz minuty.

**BOT/ADOPTED, tryby, synthetic:** rozdzielone w `trades.mode/source` i `ml_samples.synthetic`. To jest POTWIERDZONE.

## 7. ML, self-learning, agent Claude

**Cel ML:** `label = 1 if net R > 0`. Zgodność z wykonywaną polityką jest naruszona przez usterki C, D i E. Koszty: usterka A.

**Kategorie cech:** opis schematu (`features.py:23`) nie wymienia S11 i M30. Kodowanie korzysta jednak z kategorii zaobserwowanych w treningu (`prep.py:39`), więc nie jest to błąd modelu (zweryfikowane). Lista w opisie schematu jest teraz wyprowadzana z rejestru (bez zmiany wersji schematu).

**Podział:** chronologiczny, z grupowaniem zdarzeń, purgingiem i embargo; patrz G.

**Kalibracja i próg:**
- Kalibracja i próg handlowy są dopasowywane na bloku CALIB, czyli na tym samym bloku (`validation.py` nagłówek).
- To ryzyko optymistycznego progu. Przy małej próbie: HIPOTEZA_DO_TESTU.
- Propozycja: cross-fitting lub osobny blok progu (plan P2-21).

**Agent Claude:**
- Ocena przypięta do `setup_id` (`agent/service.by_setup`), sesji i rachunku (`_strict_gate`).
- VETO czeka `ai_wait_seconds`, potem przepuszcza. Spóźnione weto po wejściu nie cofa pozycji. Tak jest zaprojektowane, ale skutek nie jest raportowany.
- Wkład agenta w wynik: BRAK_DANYCH. Rekomendacja: SHADOW.

## 8. Ustalenia według priorytetu

### P0 – wiarygodność i poprawność

| ID | Ustalenie | Status | Dowód | Naprawa (1.10.0) | Test akceptacji |
|---|---|---|---|---|---|
| P0-1 | Prowizja ML z pola ręcznego (0 przy domyślnej konfiguracji); próbki z nieznanym kosztem jako HIGH | ODTWORZONE (A) | `ml/service.py:124-140`, `ml/dataset.py:100` | wspólne `risk/costs.resolve_commission`; nieznany koszt → `quality=COST_UNKNOWN`, wykluczone z treningu | `repro A` NOT_REPRODUCED; `test_audit_fixes.test_ml_cost_*` |
| P0-2 | PAPER: wiersz `trades` przy częściowym wyjściu | ODTWORZONE (B) | `execution/paper.py:90-115`, `stats.py:66` | `trades.status` OPEN_PARTIAL/CLOSED; statystyki tylko CLOSED | `repro B`; `test_audit_fixes.test_paper_partial_*` |
| P0-3 | TP1→BE na minimum sprzed TP1 | ODTWORZONE (C) | `ml/labels.py:99-123` | kursor tick-po-ticku od momentu TP1; bez ticków → `AMBIGUOUS_AFTER_TP1` | `repro C`; `test_audit_fixes.test_labels_*` |
| P0-4 | S11 `None` w etykietach/replay; TP nie od fillu | ODTWORZONE (D) | `ml/labels.py:152`, `tools/replay_strategies.py:108` | `None` = brak time-exit (horyzont = limit danych); `RR_FROM_FILL` w etykiecie i replay | `repro D`; `test_audit_fixes.test_s11_*` |
| P0-5 | Polityka wyjścia globalna, cele środkowe gubione, brak time-exit | ODTWORZONE (E) | `execution/manager.py:137-258`, `gateway.py:209` | `execution/policy.py` (MQ-EXIT-POLICY-1.0.0) zapisana przy otwarciu (`exit_policy_json`); wszystkie cele; time-exit | `repro E`; `test_audit_fixes.test_policy_*` |
| P0-6 | `tp1_done` przed `order_send` | ODTWORZONE (F) | `execution/manager.py:160-170` | `tp1_state` REQUESTED/UNKNOWN/CONFIRMED/REJECTED; BE tylko po CONFIRMED; rekonsyliacja wolumenu | `repro F`; `test_audit_fixes.test_tp1_state_*` |
| P0-7 | Champion oceniany innym zbiorem | ODTWORZONE (G) | `ml/registry.py:104-122` | ocena po `sample_id` bloku testu zapisanych w wyniku | `repro G`; `test_audit_fixes.test_champion_same_ids` |
| P0-8 | P/L None → 0 w PAPER | ODTWORZONE (J) | `execution/paper.py:79` | część nierozliczona: `trades.status=UNSETTLED`, poza statystykami | `repro J` |
| P0-9 | Opis schematu kategorii bez S11/M30 (kodowanie z danych – **nie** błąd modelu) | ZWERYFIKOWANE – tylko dokumentacja | `ml/features.py:23`, `ml/prep.py:39` | lista w opisie z rejestru | – |
| P0-10 | Kontrakt czasu na Twoim terminalu | BRAK_DANYCH | `mt5/clock.py` | eksport diagnostyki czasu | protokół `I` |

### P1 i P2

Pełna tabela z mechanizmem, eksperymentem, kompromisem i kryterium odrzucenia jest w `PLAN_ULEPSZEN_WINRATE_ROI_PL.md`.

## 9. Testy wykonane i niewykonane

Szczegóły: `audit/WYNIKI_TESTOW.json`.

**Wykonane:**
- `python tools/run_tests.py` na 1.9.0 (commit `318ce0d`, nowe uruchomienie 2026-10-13): **224 testy, OK, exit 0**.
- `python audit/repro/repro_audit.py` na 1.9.0: **8/8 REPRODUCED**.

**Niewykonane:**
- Uruchomienie `.bat` na Windows – brak Windows (sprawdzone statycznie, `test_launchers`).
- Twój terminal MT5, `XAUUSD-`, kalkulatory brokera, czas serwera – brak terminala (**połączenie niepotwierdzone**).
- Backtest, OOS i forward na historii XAUUSD- – brak eksportu z Twojego terminala. Stąd **NIE_OCENIONO_SKUTECZNOŚCI**.
- Prawdziwe API Claude – brak klucza (testy z atrapą).
- Obciążenie skanera 30+ rynków na prawdziwym terminalu – BRAK_DANYCH. Na symulatorze skaner działa (`test_markets_signals`).

## 10. Dane potrzebne do oceny skuteczności

Eksport z Twojego terminala obejmuje:
1. OHLC + tick volume + spread dla M1–D1, a także W1 i MN1, z zakresem co najmniej 18 miesięcy:
   ```
   python -m masterquo export --from-utc ... --to-utc ... --out data\export_xau --dst-model NY_CLOSE
   ```
2. Ticki Bid/Ask, jeśli to możliwe: `copy_ticks_range` dla okresów testowych.
3. `symbol_info` (point, tick_size, tick_value, contract_size, volume_*, stops_level, filling).
4. Historia deals rachunku (prowizja, swap, fee, typ, entry).
5. Diagnostyka czasu (`06_DIAGNOZA_CZASU_MT5.bat`).
6. Opcjonalnie historyczna IV (CSV zgodny z `docs/STRATEGIA_WALLS_RANGE_PATTERNS_PL.md`, z `available_at`).

Bez tych danych **nie podaję winrate, PF, ROI ani procentu poprawy**.

## 11. Kolejność wdrażania i rollback

1. **Naprawy pomiaru P0-1…P0-9 (1.10.0).** Każda ma osobny test. Metryki po naprawie mogą wyglądać **gorzej** (uczciwe koszty, poprawne BE).
   - Rollback: ZIP 1.9.0 w osobnym folderze + kopia `data\`.
   - Migracja 0009 dodaje kolumny i nie usuwa danych.
2. Ponowne zebranie próbek ML od nowa: nowa wersja polityki etykiet `MQ-LABEL-1.1.0` i kosztów `MQ-COST-1.1.0`. Stare próbki zostają oznaczone starą wersją i nie są mieszane.
3. Eksport danych brokera → baseline dokładnie 1.10.0 → ablation jednej zmiany naraz (protokół).
4. Forward SHADOW/PAPER z zamrożoną polityką.
5. Dopiero potem ewentualne zmiany progów (H) i ML/ASSIST.
