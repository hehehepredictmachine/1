# Structure Intelligence, świece SCI2, Black-76, MITP, biblioteka DB, strefy, sieci SEW/ResNeXt i Manual Trade Pad (PMW-UPD-07)

Wszystkie progi i profile poniżej to **propozycje inżynierskie do kalibracji na części dev**, nie odkryta przewaga. Żaden element nie
wysyła zleceń automatycznie, nie zmienia Execution Lock i nie wybiera modelu sam. Dane syntetyczne służą wyłącznie testom kodu
(artefakty `TEST_ONLY` nie trafiają do SHADOW).

## 1. Struktura i formacje — `STRUCTURE_CAUSAL_V2` (`analysis/structure_v2.py`)
- Dwie warstwy swingów: wewnętrzna 3/3 i nadrzędna 5/5. Pivot jest **znany po zamknięciu prawych świec** (`known_at_bar`); przy równych
  ekstremach wygrywa najwcześniejsza świeca.
- Etykiety HH/HL/LH/LL/EQH/EQL względem poprzedniego swingu tej samej warstwy (tolerancja max(2 ticki, 0.1 ATR) z ATR znanego w chwili swingu).
  Trend UP wymaga HH+HL, DOWN – LH+LL; inny układ to TRANSITION/RANGE, brak historii – UNKNOWN.
- Zdarzenia na zamkniętych świecach względem swingów znanych **przed** świecą (bufor max(2 ticki, 0.1 ATR)): `BOS_UP/DOWN`,
  `STRUCTURE_CHANGE_UP/DOWN` (CHoCH tylko jako etykieta), `SWEEP_CANDIDATE_HIGH/LOW` (knot poza poziomem, zamknięcie z powrotem – nie BOS).
  Każdy poziom wybija się raz (`event_id` trwały).
- Automat instancji formacji: `FORMING → CONFIRMED → RETEST_PENDING → RETEST_HELD/RETEST_FAILED`, osobno `INVALIDATED/EXPIRED`.
  Unieważnienie sprawdzane przed potwierdzeniem; unieważniona instancja nigdy nie „ożywa” (regresja A-07-01: zamknięcia [100,90,101,110],
  invalidation 95, confirm >105 → INVALIDATED; lustro SHORT; TTL). Ta sama świeca dotyka unieważnienia i zamyka się za wybiciem →
  konserwatywnie INVALIDATED + flaga `INTRABAR_ORDER_UNKNOWN`.
- Profil `LEGACY_COMPAT` (stary `analysis/chart_patterns.py`) zostaje bez zmian; `upgrade_patterns` dodaje widok v2 z `geometry_quality`
  (QUALIFIED / PRELIMINARY wg liczby kontaktów).

## 2. Super Candles Intelligence 2 — `MQ_STRUCTURE_CANDLES_V2` (`analysis/sci2.py`)
Rola strukturalna ostatniej zamkniętej świecy: NECKLINE_BREAK, BREAKOUT_FAILURE, RETEST_HOLD, SWEEP_RECLAIM, TREND_PULLBACK, COMPRESSION,
MID_RANGE, STRUCTURE_ONLY, NO_STRUCTURAL_CONTEXT. Geometria świec z `analysis/candles.py`; kilka nazw jednej świecy = **jedna grupa dowodów**.
`supports_role` tylko przy zgodnym kierunku; nigdy sygnał ani procent. Tick volume ≠ wolumen agresorów.

## 3. Zadania prognozy (`lab/structure_task.py`)
- `STRUCTURE_MOVE_M1_V1`: każde kwalifikujące się zamknięcie M1, horyzonty 3/5/15 **świec** M1; `r_h=(C[i+h]−C[i])/ATR14_i`;
  DOWN/FLAT/UP z progiem `b_h=0.15·√h` ATR. Okno z jakąkolwiek luką ≠ 60 s jest wyłączone. Wyjście: p_down/p_flat/p_up + q10/q50/q90;
  poziomy ceny = rozkład **końca** horyzontu (nie high/low, nie trajektoria).
- `SCALP_STRUCTURE_CONTEXT_V1`: tylko rzeczywiste setupy strategii scalp (replay z kosztami): TP1_FIRST / SL_FIRST / TIMEOUT + net_R.
  Brak setupów → `NO_SETUP`.
- Cechy `SMF-1.0.0`: jeden builder dla treningu i inferencji, przyczynowo per świeca (struktura, MITP, geometria, kontekst M5/M15/H1
  point-in-time = ostatnia świeca zamknięta w chwili zamknięcia M1, sesja, jakość danych). Kontekst Black: maska 0 (brak zweryfikowanego źródła).
- Protokół `SI-PROTO-1.0.0`: ostatnie 20% czasu = holdout (nieotwierany w treningu), 4 rozszerzające się foldy na dev, purge po końcu etykiety
  + embargo 15 świec, wewnątrz FIT 60 / TUNE 15 / CALIBRATION 15 / POLICY 10. Temperatura tylko na CALIBRATION.
- Rodziny: CLASS_FREQ, RULE_STRUCTURE, LOGREG, XGB (gdy zainstalowany), `MQ_RESNEXT1D_V2`, `MQ_SEW_RESNET1D_V2`, `MQ_SEW_RESNEXT_EB_V1`.
- Minima dowodowe (organizacyjne, nie moc statystyczna): 20 000 wierszy dev, 60 sesji, 500/klasę; setup head 600 setupów. Poniżej → INSUFFICIENT_EVIDENCE.
- `calibrate-indicators` wybiera parę pivotów i profil MITP **tylko na dev**; po zmianie profilu `train` odmawia na starym datasecie (STALE_DATASET + komenda).
- Holdout: `evaluate-holdout --candidate-id … --protocol-id SI-PROTO-1.0.0` – jedno otwarcie na kandydata, wpis do wspólnego `eval_ledger`; kolejne wywołanie
  zwraca zapisany wynik (ALREADY_EVALUATED).

## 4. Sieci (`lab/structure_nets.py`)
Czysty NumPy z ręcznym backward (testy gradientów: różnice skończone dla gładkich operatorów, niezależny VJP dla BPTT z surrogate arctan).
Splot przyczynowy (lewy padding), układ `(N,C,T)` (adapter NTC). Głowy: softmax 3 klas + kwantyle z wymuszoną kolejnością
(`q10=q50−softplus(a)`, `q90=q50+softplus(b)`). SEW: LIF (β .9, θ 1, reset przez odejmowanie – ścieżka resetu odłączona), SEW ADD bez progowania
sumy, `RESET_EACH_WINDOW`. EB = jawna kara aktywności `λ·Σ w_l·mean(spikes_l)` (gradient do warstw). Telemetria: parametry, MAC, SynOps (proxy),
firing rate, latencja; **energy_j = null (NOT_MEASURED)**. Cardinality niepodzielne → błąd `CARDINALITY_NOT_DIVISOR`.

## 5. Black-76 (`analytics/black76.py`, PMW-BLACK76-2.0.0)
Wycena F/K/σ/T/D, parytet, przypadki zdegenerowane (v=0: delta ATM 0.5D, gamma null NONDIFFERENTIABLE), solver IV z granicami (CONVERGED /
BOUNDARY / NO_SOLUTION / T_ZERO_UNIDENTIFIED), forward z parytetu (tylko europejskie, QA świeżości i skrzyżowań). N(d2) = miara Q modelu;
p_touch nie jest szacowane. Stara ścieżka `engine/volzones` bez zmian. API: `POST /api/v1/black76/{price,iv,forward}`.

## 6. MITP (`analysis/mitp.py`, MQ_MITP_32_V1)
16 baz × (BIAS, SLOPE) = 32 węzły; dwustopniowe potwierdzenie (trigger na high/low świecy zmiany, potwierdzenie zamknięciem **późniejszej** świecy).
Profile STRICT_ALL / GROUP_BALANCED; `NO_ENABLED_SIGNALS`; checkpoint + replay == batch. Parytet z oryginałem R38 = UNVERIFIED_SOURCE_PARITY.

## 7. Biblioteka Double Bottom (Part 85/86)
Zadanie zamraża manifest (id + sha próbki, konfiguracja, wersja reguł). Statusy zadania: RUNNING/COMPLETED/CANCELLED/INTERRUPTED/FAILED_EXECUTION;
po restarcie RUNNING → INTERRUPTED, `POST /api/v1/patterns/jobs/{id}/resume` bez duplikatów. Wynik ma `result_id`, `sample_sha`, `usable_at`
(flaga `DECISIVE_EVENT_PRECEDED_RECOGNITION`). Eksport oddzielny (`/export`, bez walidacji), CSV maszynowy + bezpieczny arkusz `_sheet.csv`.
SHOW ON CHART czyta zapisany wynik (`GET /api/v1/patterns/samples/{id}/result`, `/patterns/results/{result_id}`); REVALIDATE to jawna akcja.
Nowa wersja `DB-1.2.0-BUF` (bufory breakout/failure × ATR, wybór pary); stare wersje bez zmian.

## 8. Strefy Supply/Demand (Part V+, `lab/zones.py` MQ-LAB-ZONES-2.0.0)
SQLite = źródło prawdy; detektor tylko odkrywa strefy (nie nadpisuje cyklu życia). Cykl życia przyrostowo od checkpointu strefy: jedno wejście = jeden test,
idempotentne zdarzenia, `HISTORY_GAP`, `ORDER_UNKNOWN_SAME_BAR`. Rewizje z kontrolą (`PATCH /api/v1/lab/zones/{id}` z `expected_revision`), usunięcie =
tombstone (także w dzienniku zdarzeń – brak „zmartwychwstania” po odtworzeniu). Snapshot JSON z sumą kontrolną, fsync, `.bak`; to eksport, nie drugie źródło.

## 9. Manual Trade Pad (`execution/manual.py`)
Plan: SL/TP wyrównane do ticka (SL od wejścia, TP do wejścia), wielkość po wyrównaniu; ryzyko % liczone kalkulatorem terminala
(`order_calc_profit`), w dół do kroku wolumenu; `MIN_VOLUME_EXCEEDS_RISK`; prowizja BROKER_OBSERVED / USER_CONFIGURED / UNKNOWN – UNKNOWN nigdy = 0
i blokuje kwalifikację planu. TTL planu 5 s. Intencja `ManualTradeIntent`, klucz idempotencji tryb|konto|instrument|intencja|akcja|rewizja,
stan PREPARED/SENDING przed wywołaniem terminala, UNKNOWN uzgadniany po tagu (bez ponownego wysłania). PAPER = wspólny silnik PAPER.
BE = PRICE_BREAK_EVEN, nigdy nie pogarsza SL. Realne tryby przechodzą przez wspólne bramki gatewaya; **LOCKED blokuje każdą zmianę rachunku**.

## 10. Runtime, API, panel, agent
- MTF dashboard: każda kolumna struktury odwołuje się do `parent_snapshot_id` snapshotu MTF; archiwum `si_snapshots`, prognozy `si_forecasts`
  (przed wynikiem) i `si_outcomes` (dojrzewanie).
- API: `GET /api/v1/structure-intelligence`, `/snapshots/{id}`, `/forecasts`, `/models`, `/quality`; `POST /jobs`, `GET /jobs/{id}`, `POST /jobs/{id}/cancel`,
  `POST /models/select|rollback`; Manual Pad `/api/v1/manual/*`.
- Agent: wiedza K01–K18, K36 (`analysis/structure_knowledge.py`, PMW-SI-KNOWLEDGE-1.0.0), narzędzie `get_structure_intelligence`, prompt 1.6.0.
  To instrukcja w promptcie – nie fine-tuning modelu językowego.

## 11. Komendy
```
python -m masterquo structure-intelligence audit --asset XAUUSD
python -m masterquo structure-intelligence dataset --latest --task STRUCTURE_MOVE_M1_V1
python -m masterquo structure-intelligence calibrate-indicators --latest
python -m masterquo structure-intelligence train --latest --task STRUCTURE_MOVE_M1_V1 --profile standard
python -m masterquo structure-intelligence report --latest
python -m masterquo structure-intelligence replay --latest --mode shadow
python -m masterquo structure-intelligence evaluate-holdout --candidate-id <id> --protocol-id SI-PROTO-1.0.0
```
Launcher: `26_STRUCTURE_INTELLIGENCE.bat`. Train-all: etap `structure_intelligence` (quick = niepełny smoke).

## 12. Statusy i ograniczenia
- Kod: zaimplementowany i przetestowany na danych syntetycznych. Trening na danych rzeczywistych: **NOT_RUN** (brak eksportu MT5 w tym środowisku).
- Parytet MITP z R38, zgodność z artykułami MQL5 (Part 85/86/V, Manual Trade Pad, SEW): **UNVERIFIED_SOURCE_PARITY** (własne implementacje).
- Edge: **NOT_EVALUATED**. Energia: **NOT_MEASURED**.
- Rollback: `structure-intelligence rollback`, wybór poprzedniego profilu w `data/structure_intelligence/<inst>/indicator_profiles/`; migracja 0021 jest addytywna
  (downgrade DB tylko z kopii zapasowej tworzonej automatycznie przed migracją).
