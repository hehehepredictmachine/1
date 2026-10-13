# S12 – rodzina WALLS / RANGE / PATTERNS (1.0.0-CANDIDATE)

## Status

| Pole | Wartość |
|---|---|
| Status funkcjonalny | **FUNCTIONAL** – reguły deterministyczne, pełny przepływ: skan → checklista → ryzyko → PAPER/replay → rozliczenie |
| Status dowodu skuteczności | **CANDIDATE / OOS_NOT_RUN** – brak danych brokera, brak walidacji. Nie jest to strategia zwalidowana |
| Domyślnie | skanowanie **włączone**, handel **wyłączony** (`active.strategies.S12.trade = false`); włączenie to jawna decyzja użytkownika |
| Kod | `backend/masterquo/strategies/s12_walls_range.py`, `backend/masterquo/analysis/*` |

## Przepływ

```
KONTEKST WYŻSZYCH TF (H1/H4/H8/D1, W1/MN1 z D1) → STREFY S/R i WALLS → REŻIM → STRUKTURA (zakres M5 / formacja)
→ ZAMKNIĘTA ŚWIECA TRIGGERA (M1 lub M5) → KOSZTY I RYZYKO (wspólny silnik) → JEDNA DECYZJA (arbiter)
→ WYKONANIE (wspólna bramka) → ROZLICZENIE (wspólna polityka wyjścia MQ-EXIT-POLICY-1.0.0)
```

**Zasady przepływu:**
- Rozpoznana formacja nie oznacza wejścia.
- Jeden ruch daje najwyżej jeden setup na kierunek – decyduje arbiter.
- Pięć nazw jednej świecy to jedno zdarzenie dowodowe.

## Źródło walls (`analysis/walls.py`, MQ-WALLS-1.0.0)

| Źródło | Znaczenie | Kiedy używane |
|---|---|---|
| `IV_SOURCED` | IV z zewnętrznego adaptera (instrument + termin) | **nieskonfigurowane** w tej paczce (brak licencjonowanego feedu) → `NOT_CONFIGURED` |
| `IV_IMPORT` | IV zaimportowana z CSV/JSON (`import-iv`) | tylko od `available_at`, do `valid_until`, jakość OK/ESTIMATED |
| `IV_MANUAL` | IV wpisana ręcznie (Ustawienia → `walls.manual`) z czasem, źródłem, jednostką, terminem i ważnością | gdy aktualna |
| `HV_PROXY` | zmienność **historyczna** z zamkniętych D1 brokera (close-to-close, 20 dni) | gdy brak IV; zawsze oznaczona `PROXY_NOT_IMPLIED_VOLATILITY` |
| `UNAVAILABLE` / `STALE` | brak aktualnego źródła | strategia: `WALL_STALE` / `NO_WALLS` |

**Ograniczenia źródeł:**
- GVZ to 30-dniowa IV opcji na GLD, a opcje CME dotyczą konkretnego kontraktu futures.
- IV innego instrumentu jest oznaczana `IV_FROM_OTHER_INSTRUMENT_PROXY`. Używana jest tylko **liczba** zmienności wokół ceny brokera; strike'i GLD i futures **nie są kopiowane** jako ceny CFD.
- Pozycjonowanie dealerów, gamma i OI to osobny temat, którego **nie** liczymy.

**Model (jeden wariant, ustalony przed badaniem):**
- `anchor` = otwarcie bieżącej sesji brokera (świeca D1), horyzont = 1 sesja.
- `T` = 1/252 dla zmienności rocznej z dni handlowych (`HV_PROXY` albo IV z `TRADING_252`).
- `T` = 1/365 dla IV kalendarzowej (`ACT_365`). Tych konwencji się nie miesza.
- `upper_k = anchor·exp(+k·σ·√T)`, `lower_k = anchor·exp(−k·σ·√T)`, `k ∈ {1, 2}`.
- Strefa = poziom·exp(±0,15·σ·√T).
- To **konwencja pasm log-zwrotu**: nie prognoza high/low dnia i nie prawdopodobieństwo transakcji.

**Snapshot zamrożony na sesję:**
- Te same dane wejściowe dają ten sam `snapshot_id`.
- Nowa IV daje wersję 2 – tylko dla przyszłych setupów.
- `snapshot_id` wchodzi w tożsamość scenariusza S12, więc historyczny trigger i SL nigdy się nie przesuwają.

**Wariant śródsesyjny:** czas pozostały do końca sesji i bieżąca kotwica to osobna hipoteza i **nie** jest danymi wejściowymi handlu.

### Import IV – format (przykład: `docs/przyklad_iv_import.csv`, wartości PRZYKŁADOWE, nie rynkowe)

| Pole | Wymagane | Opis |
|---|---|---|
| `observed_at` | tak | czas obserwacji UTC ISO, np. `2026-10-12T20:00:00Z` |
| `available_at` | tak | od kiedy wartość była publicznie znana (≥ `observed_at`) – badania historyczne używają jej dopiero od tej chwili |
| `underlier` | tak | instrument zmienności (GLD dla GVZ, kod kontraktu GC, XAUUSD-) |
| `source` | tak | źródło (np. „Cboe GVZ close”) |
| `sigma_annual` | tak | wartość |
| `unit` | tak | `percent` (16.4) albo `fraction` (0.164) – nigdy zgadywane |
| `day_count_basis` | tak | `ACT_365` albo `TRADING_252` |
| `tenor_days` lub `expiry` | tak | horyzont zmienności |
| `quality` | tak | `OK` / `ESTIMATED` / `STALE` (tylko OK/ESTIMATED są używane) |
| `valid_until` | nie | domyślnie `available_at` + 3 dni |

**Walidacja:**
- zakres: ułamek 0,01–3, procent 1–300;
- słowniki jednostek i konwencji dni;
- `available_at` ≥ `observed_at`;
- duplikaty (underlier, source, observed_at, tenor) są odrzucane;
- każdy odrzucony wiersz jest raportowany z przyczyną.

**Import:** `python -m masterquo import-iv plik.csv` (w folderze `backend`) albo `POST /api/v1/walls/iv-import`.

## Warianty (reguły LONG; SHORT = ten sam kod na lustrzanym widoku cen, walls lustrzane)

### A. RANGE_RECLAIM (TF setupu M1) – konsolidacja M5, wejście M1 do wnętrza zakresu

1. **Zakres M5** (`analysis/range_m5.py`): okno L ∈ {18, 12, 24} zamkniętych M5, sprawdzane w tej kolejności.
   - Warunki: wysokość 1–6 ATR, ER ≤ 0,35, ≥ 2 niezależne kontakty (≥ 3 świece odstępu) z każdą krawędzią (strefa 20% wysokości).
   - Rozpoznanie następuje w **najwcześniejszym** spełniającym oknie z ostatnich 48 świec. Granice są **zamrażane** i nie podążają za ceną.
   - Zaakceptowane wybicie (2 zamknięcia poza granicą + 0,1 ATR albo 1 zamknięcie > 0,5 ATR) unieważnia handel od krawędzi do krawędzi.
2. **Lokalna strefa M1**:
   - Brane są świece M1 z okresu zakresu, których low ≤ dół + 20% wysokości.
   - `zone_low` = najniższy knot, `zone_high` = najwyższy dół korpusu (reguła knot→korpus); szerokość ≤ 0,6 ATR(M5).
   - Strefa jest zamrażana razem z zakresem. Nie są to min/max wszystkich M1.
3. **Kontakt**: świeca M1 **po** zamrożeniu dochodzi do strefy (low ≤ `zone_high`).
4. **Reakcja** – co najmniej jedno z:
   - sweep poniżej `zone_low`;
   - zdarzenie świecowe LONG (engulfing, pin bar, młot, gwiazda poranna, tweezer, outside-bar rejection, inside-bar break up);
   - wyższy dołek M1.
5. **Trigger**:
   - **zamknięta** M1 > `zone_high` + 0,05 ATR, a poprzednie zamknięcie nie było powyżej (pierwszy reclaim);
   - ≤ 20 świec od kontaktu;
   - to reclaim **lokalnej** strefy, nie wybicie całego zakresu.
6. **Aktywność**:
   - tick volume triggera ≥ 1,2 × mediana 30 poprzednich zamkniętych M1 (bez triggera), korpus/zakres ≥ 0,45, CLV ≥ 0,65;
   - brak tick volume → `ACTIVITY_NO_DATA` (nigdy „spełnione”);
   - `activity_filter = OFF` to osobny, jawny wariant badawczy.
7. **Wejście** (Ask):
   - nie powyżej środka zakresu (`PRICE_IN_MIDDLE`);
   - ≤ 0,5 ATR(M5) nad `zone_high` (`ENTRY_TOO_LATE`).
8. **Poziomy**:
   - SL pod min(sweep, `zone_low`) − 0,15 ATR;
   - TP1 = środek zakresu (50%), TP2 = góra − 10% wysokości (50%);
   - ważone RR brutto ≥ 1,2; RR netto liczy wspólny silnik ryzyka.
9. **Walls** (`use_walls = true`): aktualna **dolna** wall w odległości ≤ 0,5 ATR(M5) od strefy reakcji; w przeciwnym razie `NO_WALL_ALIGNMENT` / `WALL_STALE`.
   - `use_walls = false` → wariant **`RANGE_RECLAIM_BASE`** (baseline bez walls, nigdy nazywany strategią IV).
10. **Wyjście**: BE po potwierdzonym TP1, wyjście czasowe po 90 min.

### B. WALL_REJECTION (TF setupu M5) – odrzucenie strefy zmienności

1. Wymagana jest aktualna dolna wall (najpierw k = 1, potem k = 2).
2. **Przebicie**: zamknięta świeca M5 przebiła **poziom** wall w ostatnich 6 świecach (po kotwicy sesji).
3. **Brak handlu**, gdy:
   - 2 kolejne zamknięcia poniżej strefy (`ACCEPTED_BEYOND_WALL`);
   - świeca ≥ 2,5 ATR od dotknięcia (`EXPANSION_NO_TRADE`).
4. **Trigger**: pierwsze **zamknięcie** M5 z powrotem powyżej strefy wall; aktywność i świeca jak w A.
5. **Kontekst mean reversion**: H1 i H4 DOWN przy reżimie TREND_DOWN → `HTF_CONFLICT`.
6. **Poziomy**:
   - SL = najniższe low od dotknięcia − 0,15 ATR;
   - cele: Daily Open (kotwica walls) i środek zakresu M5, jeśli powyżej; inaczej 1R/2R oznaczone `R_MULTIPLE_NO_STRUCTURE`.
7. Wyjście czasowe: 36 × M5.
8. Samo dotknięcie ±1σ/±2σ **nie** jest sygnałem.

### C. BREAKOUT_RETEST (TF setupu M1) – wybicie, retest, kontynuacja

1. **Wybicie**: zaakceptowane wybicie zamrożonego zakresu; świeca wybicia z korpusem ≥ 50% zakresu i aktywnością.
   - Wariant z walls: zamknięcie wybicia ponad najbliższą górną wall leżącą w odległości ≤ 1 ATR od góry zakresu.
2. **Retest**: low M5 wraca do góry + 0,25 ATR w ≤ 12 świecach (`RETEST_MISSING`).
   - Zamknięcie < góra − 0,25 ATR to `FAILED_BREAKOUT`. Tu nie handlujemy; reclaim opisują A i S07.
3. **Trigger**: pierwsze **zamknięcie** M1 po reteście powyżej najwyższego high od początku retestu.
4. **Poziomy**:
   - SL = low retestu − 0,15 ATR;
   - TP1 = góra + wysokość, TP2 = góra + 2 × wysokość (measured move: propozycja, nie obietnica).
5. Wyjście czasowe: 120 min.

### Arbiter

- Na kierunek zostaje **jeden** draft.
- Kolejność wariantów zależy od reżimu:
  - RANGE / COMPRESSION: A, B, C;
  - EXPANSION / TREND: C, B, A;
  - inne: B, A, C.
- Pierwszeństwo ma najdalszy etap: TRIGGER > EARLY z zamkniętą świecą triggera > EARLY > WATCH.
- **Konflikt**: oba kierunki na EARLY/TRIGGER (odrzucenie vs wybicie) → oba spadają do WATCH z `CONFLICT_REJECTION_VS_BREAKOUT`. Nigdy dwie przeciwne pozycje z jednego zdarzenia.
- Przejście od odrzucenia do zaakceptowanego wybicia tworzy nowy scenariusz (nowy `range_id` lub stan) z dowodem. Nie ma cichego odwrócenia.

### Odrzucenia (kody → panel po polsku)

`NO_RANGE`, `RANGE_ACCEPTED_BREAKOUT`, `NO_M1_REACTION_ZONE`, `PRICE_IN_MIDDLE`, `NO_CONTACT`, `NO_WALL_ALIGNMENT`, `WALL_STALE`,
`NO_CLOSED_TRIGGER`, `NO_REACTION`, `VOLUME_NOT_CONFIRMED`, `ACTIVITY_NO_DATA`, `TRIGGER_CANDLE_WEAK`, `RETEST_MISSING`, `FAILED_BREAKOUT`,
`BREAKOUT_WEAK`, `RR_NET_TOO_LOW`, `ENTRY_TOO_LATE`, `HTF_CONFLICT`, `DATA_MISSING`, `ACCEPTED_BEYOND_WALL`, `EXPANSION_NO_TRADE`,
`TRIGGER_WINDOW_EXPIRED`, `CONFLICT_REJECTION_VS_BREAKOUT`. Tłumaczenia: `REJECT_PL` w kodzie strategii.

## Checklista (strona „Warunki setupu” i „Szczegóły setupu”)

**Elementy:**
- reżim, wall i jej źródło/aktualność, wall przy strefie lub wybicie poza wall;
- zakres M5 i granice, kontakt ze strefą, cena nie w środku;
- reakcja, formacja wykresowa (opcjonalna), zamknięcie triggera;
- aktywność, czas i oddalenie, RR brutto, wyższe TF, arbiter, unieważnienie.

**Pola każdego warunku:** wymaganie, odczyt, TF, status (SPEŁNIONY / NIESPEŁNIONY / OCZEKIWANIE / BRAK DANYCH / NIE DOTYCZY / ODCZYT), czas i powód po polsku. Brak danych nie jest niespełnioną geometrią ani zerowym odczytem.

## Parametry robocze (hipotezy inżynierskie, nie „optymalne”)

**Lista:**
- ATR 14;
- zakres M5: 12/18/24 świece;
- ≥ 2 reakcje na krawędź;
- aktywność: 1,2 × mediana 30;
- korpus/zakres 0,45, CLV 0,65/0,35;
- k = 1, 2, strefa 0,15σ;
- okno triggera 20 × M1, retest 12 × M5, wejście ≤ 0,5 ATR.

**Zmiany:**
- przez `active.params.S12` (np. `{"use_walls": false}`, `{"activity_filter": "OFF"}`, `{"variants": ["RANGE_RECLAIM"]}`);
- w badaniu przez `tools/replay_strategies.py --params-json`.

Nie stroić dziesiątek progów naraz – zob. `audit/PROTOKOL_WALIDACJI.json`.

## Uruchomienie, źródło walls, checklista, rollback

1. Start jak zwykle (`masterquo_start.bat`). S12 skanuje od razu; handel tylko po włączeniu „Dopuść do handlu” dla S12.
2. **Źródło walls**: Ustawienia → `walls.source` (AUTO / HV_PROXY / IV_MANUAL / IV_IMPORT); ręczna IV w `walls.manual`.
   - Import pliku: `python -m masterquo import-iv plik.csv`.
   - Stan: `GET /api/v1/walls`.
3. **Checklista**: strona „Warunki setupu” → wybierz scenariusz S12.
4. **Badanie**: `python tools/replay_strategies.py --csv-dir <eksport> --step-tf M1 --walls hv --params-json "{\"S12\": {\"use_walls\": false}}"` (baseline) itd.
5. **Rollback**: ZIP 1.9.0 w osobnym folderze + kopia `data\`. Config v10 → v9: usuń `walls` i `S12`.
   - Tabele `iv_observations` i `walls_snapshots` nie przeszkadzają starszej wersji.

## Dane potrzebne do OOS

Eksport M1…D1 (plus W1/MN1 przez agregację) z terminala, ticki Bid/Ask, `symbol_info`, historia deals, diagnostyka czasu. Opcjonalnie historyczna IV z `available_at`.

Ablation według `audit/PROTOKOL_WALIDACJI.json`:
1. baseline;
2. RANGE_BASE;
3. +walls HV;
4. +walls IV;
5. +chart;
6. +candle;
7. +aktywność;
8. pełna.

**Bez tych danych: OOS_NOT_RUN** – nie raportujemy winrate, PF ani ROI.
