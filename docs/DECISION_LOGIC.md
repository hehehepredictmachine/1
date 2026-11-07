# Logika decyzji (PMW-ARC-1)

## Kolejność (każdy krok może tylko zaostrzyć werdykt)

1. **Kandydat strategii** (`StrategyCandidate.base_verdict`)
   * ACTIVE: `execution_permission == ALLOWED` daje ENTER. Daje go też sytuacja, w której jedynym niezaliczonym węzłem jest `MODELS`
     (wtedy kandydat był wejściem, a zatrzymał go model). W pozostałych przypadkach jest WAIT lub NO_TRADE.
   * SH: status `READY` daje ENTER, `WAIT` daje WAIT, a pozostałe statusy NO_TRADE.
2. **Bramki ścieżki** (tryb, konto, STOP, ryzyko, limity portfela, jakość danych, arbitraż SH). Ich kody trafiają do `reason_codes`, a
   werdykt ENTER zmienia się na BLOCKED.
3. **Role modeli** (`evaluate_models`, funkcja czysta, używana także przez replay):

| Rola | Skąd | Wpływ |
|---|---|---|
| OBSERVE | rodzina `use = SHADOW`, Kronos OBSERVE, wskaźniki PMW-IND-1, DXY, SVP | zapis w rekordzie, `influence = NONE` |
| ASSIST | rodzina `use = ASSIST` (tylko APPROVED i dane REAL – PMW-FAM-1) | READY‑owa prognoza kierunku z P(strony przeciwnej) ≥ `families.assist_hold_threshold` (domyślnie 0,60) **wstrzymuje** wejście: `MODEL_ASSIST_HOLD:<rodzina>`. Nigdy nie tworzy wejścia ani nie podnosi WAIT |
| REQUIRED | `decision.required_models` (domyślnie puste) | model musi być READY (inaczej `MODEL_REQUIRED_UNAVAILABLE`), świeży, tj. wiek danych ≤ `decision.required_max_age_s` (inaczej `MODEL_REQUIRED_STALE`), i nie może być przeciwny, czyli P(przeciwny) ≥ 0,5 (inaczej `MODEL_REQUIRED_CONTRARY`). Model, który nie zwrócił prognozy, liczy się jako niedostępny |

4. **Werdykt końcowy** (`final_verdict`)
   * Jeśli kandydat nie jest ENTER, werdykt pozostaje bez zmian.
   * Jeśli kandydat jest ENTER, a pojawił się choćby jeden kod bramki lub modelu, werdykt to BLOCKED.
   * W pozostałych przypadkach werdykt to ENTER.
5. **DecisionRecord** trafia do tabeli `decision_records`. Jest unikalny dla trójki (ścieżka, źródło, hash wejść), a hash nie obejmuje cen,
   bo te zmieniają się co tick.

ACTIVE stosuje role jako węzeł `MODELS` drzewa decyzji (`engine/decision.build(model_gate=...)`), czyli przed wyliczeniem
`content_hash`. Skutki:
* zmiana roli lub stanu modelu daje nową decyzję o nowym `decision_id`;
* bramka wykonania (`gateway._validate`) widzi już werdykt zablokowany;
* karta sygnału pokazuje powód.

Gdy nie ma żadnego modelu w roli ASSIST ani REQUIRED, węzeł `MODELS` jest PASS albo w ogóle go nie ma. Decyzja jest wtedy identyczna jak w 1.32,
co potwierdza replay.

SH zachowuje istniejący odbiornik rodzin (`apply_to_setup`: ASSIST zmienia READY na WAIT). Koordynator dodaje rekord i rolę REQUIRED:
READY zmienia się na WAIT z powodem, a plan nie jest otwierany.

## Wykonanie nowego wejścia (obie ścieżki)

1. **`IntentLedger.open`**
   * `dedup_key = ścieżka:tryb:konto:przedmiot`, gdzie przedmiotem jest `setup_id` (ACTIVE) albo `plan_id` (SH).
   * Jeśli istnieje już intencja w innym stanie niż BLOCKED, wynik to DUPLICATE i nic nie jest wysyłane.
   * Intencja BLOCKED zwalnia klucz, więc to samo wejście można ponowić, gdy zwolni się miejsce.
2. **`RiskBook.reserve`** działa w jednej transakcji `BEGIN IMMEDIATE`, szeregowanej między wątkami i procesami.
   * Wejście: `risk/portfolio.state`, czyli wynik dnia i otwarte pozycje obu ścieżek, plus rezerwacje HELD/UNKNOWN, których przedmiot nie jest
     jeszcze widoczny jako pozycja (bez podwójnego liczenia).
   * Limit pozycji: `otwarte + oczekujące + 1 > min(max_open_positions ACTIVE, SH)` daje `PORTFOLIO_MAX_OPEN_POSITIONS_RESERVED`.
   * Limit dzienny: `wynik_dnia − ryzyko_oczekujące ≤ −min(daily_loss_limit_pct) × equity` daje `PORTFOLIO_DAILY_LOSS_LIMIT_RESERVED`.
   * Limit brakujący w obu konfiguracjach nie jest wymyślany. SIGNALS nigdy nie rezerwuje.
3. **Wysyłka** idzie przez adapter, czyli dotychczasową bramkę ACTIVE albo `SHExecutor`, bez zmian w ich kontrolach (`order_check`, SENDING
   przed wysyłką, brak ponownej wysyłki).
4. **`IntentLedger.outcome`** rozlicza rezerwację:

| Wynik | Rezerwacja |
|---|---|
| FILLED / PARTIAL | CONSUMED (od tej chwili liczy się sama pozycja) |
| REJECTED / BLOCKED / DUPLICATE | RELEASED |
| UNKNOWN | UNKNOWN; liczy się jak otwarta pozycja do czasu rekonsyliacji |

5. **`IntentLedger.sync`** (wywoływany co tick menedżera pozycji) czyta wynik rekonsyliacji adapterów i nigdy nie wysyła ponownie:

| Ścieżka | Stan źródła | Wynik |
|---|---|---|
| ACTIVE | `order_attempts` FILLED | RECONCILED_FILLED |
| ACTIVE | `order_attempts` NOT_FOUND_CHECK_TERMINAL lub REJECTED | RECONCILED_NOT_FOUND |
| SH | `sh_plans` po `recover` | jak wyżej, analogicznie |

6. **TTL.** Rezerwacja HELD bez żadnego wyniku (np. awaria między rezerwacją a wysyłką) po `decision.reservation_ttl_s` przechodzi w EXPIRED.
   UNKNOWN nigdy nie wygasa automatycznie.

Zarządzanie istniejącą pozycją (częściowe zamknięcia, SL/TP, BE, noga hedge, zamknięcie) nie przechodzi przez rezerwację. STOP blokuje
tylko nowe wejścia, jak dotąd.

## Konfiguracja (`config.decision`)

| Klucz | Domyślnie | Znaczenie |
|---|---|---|
| `enabled` | true | koordynator, rekordy i ledger; false przywraca zachowanie 1.32 bez rezerwacji |
| `required_models` | [] | rodziny w roli REQUIRED |
| `required_max_age_s` | 900 | maksymalny wiek danych modelu REQUIRED |
| `assist_on_active` | true | rodziny ASSIST mogą wstrzymać także ścieżkę ACTIVE |
| `reservation_ttl_s` | 180 | wygaśnięcie HELD bez wyniku |

## Testy (`tests/test_decision_arc_u6.py`, 18)

| Obszar | Test |
|---|---|
| kontrakty (pola, typy, enum, NaN, 10 kontraktów) | `TestContracts` |
| OBSERVE bez wpływu, ASSIST tylko wstrzymuje, nic nie podnosi WAIT/NO_TRADE | `TestModelRoles` |
| REQUIRED: brak / nie READY / nieświeży / przeciwny / poprawny | `TestModelRoles` |
| 8 wątków obu ścieżek, limit 1, przechodzi dokładnie jedno wejście | `TestLedger.test_concurrent_threads_of_both_paths_only_one_passes` |
| dedup, zwolnienie klucza po BLOCKED, UNKNOWN liczone do rekonsyliacji | `TestLedger` |
| TTL tylko dla HELD; limit dzienny z ryzykiem oczekującym; SIGNALS bez rezerwacji | `TestLedger` |
| węzeł MODELS ACTIVE, deduplikacja rekordów, REQUIRED w SH | `TestCoordinatorRecords` |
| bramka ACTIVE na FakeMT5: PAPER FILLED → CONSUMED; podwójne kliknięcie → DUPLICATE; limit → BLOCKED bez wysyłki; timeout → UNKNOWN → tick menedżera → RECONCILED_FILLED | `TestGatewayThroughLedger` |
| SH `open_plan` PAPER: intencja FILLED liczona raz; miejsce zajęte przez ACTIVE blokuje SH | `TestSHThroughLedger` |
| replay: wyścig (stara 6/6, nowa 2/6), zapisane decyzje równe bez ról i różne z REQUIRED | `TestReplay` |
