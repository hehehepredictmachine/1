# MasterQUO – specyfikacja kanoniczna (REKONSTRUOWANA) v1.0.0

**Status: REKONSTRUKCJA.** Pełny, oryginalny prompt „MasterQUO 4.1.0” (na który powołują się moduły nagłówkami
`PROMPT_VERSION 4.1.0`) **nie został odnaleziony** w paczce `MasterQUO_ALL_IN_ONE_XAUUSD_MINUS_FUTURE_CANDLE_TIME_FIX_V3_READONLY`
ani w żadnym z 42 archiwów. Przeszukano: nazwy plików (`*prompt*`, `*.txt`), treść (`MASTER PROMPT`, `PROMPT_VERSION: 4`, `prompt 4.1`).
Znaleziono 25 specyfikacji modułów (M01–M16, M02I, M06R, M07/M03E, M10A, integracje). Niniejszy dokument składa reguły z tych
specyfikacji w jedną wersjonowaną całość i wskazuje źródło każdej reguły. Gdzie spec był niejednoznaczny – zaznaczono decyzję.

Identyfikator: `MQ-SPEC-RECON-1.0.0` (backend: `version.SPEC_VERSION`). Prompt agenta: `MQAI-AGENT-PROMPT-1.0.0`
(`backend/masterquo/agent/prompts/MASTERQUO_AGENT_SYSTEM_PROMPT.md`).

## 1. Zasady nadrzędne

| # | Reguła | Źródło (archiwum / plik) | Implementacja |
|---|---|---|---|
| G1 | Dane rynkowe i rachunku wyłącznie z terminala MT5 (Bid/Ask, OHLC, ticki, rachunek, deals). TradingView najwyżej kontekst; zero screenshotów/OCR. | M01 v4.2.1 §1–3; M04 §A; M07 I-02/I-03; M14 §1; M15 §1 | `mt5/bridge.py`, brak innych feedów; wykresy rysowane z `/api/v1/candles` |
| G2 | Point-in-time: każda dana ma `available_at ≤ as_of`; brak look-ahead; pivot dostępny dopiero po potwierdzeniu prawymi świecami. | M01 §4; M02 (pivots `available_at`); M03 `available_pivots`; M05.02 | `engine/legacy.py` (snapshot), `engine/lifecycle.py`, test `TestNoLookahead` |
| G3 | Tylko świece ZAMKNIĘTE dowodzą reguł; zamknięcie potwierdza zaobserwowane otwarcie następnej świecy (poprawka FUTURE_CANDLE_AVAILABILITY). | NAPRAWA_FUTURE_CANDLE_AVAILABILITY_PL.md; M10A spec | `bridge._merge_tail`, `Bar.basis` |
| G4 | Rachunek „Zero” = deklaracja profilu; spread, prowizja, swap, poślizg rzeczywiste; spread zawarty w Bid/Ask nie jest odejmowany drugi raz. | M11 §3; M09 §0; M12 §1; M14 §1; M15 §1 | `risk/costs.py`, `risk/engine.py` |
| G5 | Prawdopodobieństwo ≠ score ≠ confidence. Bez skalibrowanego M05P nie podaje się procentów wygranej. | M14 §1; M05; M10A „Nigdy nie podawaj P_LONG…” | UI: „Ocena jakości ≠ prawdopodobieństwo”; schemat agenta bez pól procentowych |
| G6 | ANALYSIS_DECISION ≠ EXECUTION_PERMISSION ≠ ORDER_STATE ≠ BROKER_FILL. Kierunek może być widoczny przy blokadzie. | M14 §1; M11 §1 | `engine/decision.py` (pola rozdzielone), `order_attempts`, `managed_positions` |
| G7 | Brak/nieświeże dane → NO_TRADE/WAIT; PENDING ≠ PASS; brakujące wejście = null + przyczyna. | M01; M11 §4; M12 §0 | `data/quality.py`, `reason_codes` w każdym wyniku |
| G8 | Uczenie kontrolowane: błąd → hipoteza → propozycja → OOS/forward → zatwierdzenie; brak automatycznej mutacji LIVE. | M13 §1–2; M08 | `agent_memory` (PROPOSED / ACCEPTED_FOR_OOS_TEST / REJECTED), brak wpływu na reguły |
| G9 | Telegram/eksport tylko jako publikacja decyzji M14; domyślnie wyłączone, deduplikacja. | M15 | `notify/telegram.py` |

## 2. Przepływ modułów (kanoniczny)

`M01 dane` → `M02 reżim/struktura MTF` → `M02I wskaźniki` → `M03 BOS/CHoCH/MSS/FVG/OB/sweep + 5-CORE (M03E)` →
`M07 profil operacyjny (MVP/SMC/SCALPING) + zamrożenie planu` → `M10A cykl życia` → `poziomy MQAI-LEVELS` → `M11 ryzyko` →
`ocena Claude (AI gate)` → `M14-like drzewo decyzji + tryb` → `gateway` → `M12-like rozliczenie` → `M13-like propozycje`.
Źródło łańcucha: START_TUTAJ_README_PL.md („Łańcuch wersji”), INTEGRATION_MODULE_SPEC_v1.0.0, M07_M03E_OPERATIONAL_SPEC.

## 3. Interwały i role

| TF | Rola (M02I v1.1) | Min. zamkniętych świec | Wskaźniki w profilu |
|---|---|---|---|
| D1 | PRIMARY_TREND (kontekst) | 230 | EMA 50/200, ADX Wilder 14, ATR 14 |
| H4 | HTF_STRUCTURE | 90 | EMA 20/50, ADX 14, RSI 14, ATR 14 |
| H1 | STRATEGY_FILTER | 90 | EMA 20/50, MACD 12/26/9 **sygnał SMA**, ADX 14, ATR 14 |
| M15 | SETUP_DEVELOPMENT | 70 | EMA 20, BB 20/2, RSI 14, ATR 14, tick volume |
| M5 | TRIGGER_CONTEXT | 70 | EMA 9/21, RSI 9, ATR 14, tick volume |
| M1 | ENTRY_TIMING_CONTEXT | 50 | EMA 9/20, ATR 14, tick volume |

Źródło: `M02I_PROFILE_MT5_TIMEFRAMES_v1.1.json`. Wymagania M02 (35) i M03 (5) są niższe; aplikacja przyjmuje maksimum (D1 = 230).
**Rozstrzyganie konfliktu TF (jawna reguła):** kierunek strukturalny = zgodność H4 i H1 (M02, `trading_style=SCALP`); taktyczny = M5;
D1 = kontekst – konflikt D1 jest opisywany (`D1_OPPOSES_H4_H1_STRUCTURE`), a blokuje wejście tylko przy `strategy.d1_conflict_blocks_entry=true`.
Sześć TF nie jest sześcioma niezależnymi głosami (M07_M03E spec „PROHIBITED”). Wskaźniki rysowane na TF, na którym profil ich nie włącza (np. MACD na M1), są oznaczone `*` jako wizualne.

## 4. Definicje struktury (M03 v1.0.0, użyte bez zmian)

* **Pivot** (M02): high/low większe/mniejsze od 2 świec z lewej i 2 z prawej; `available_at` = zamknięcie 2. prawej świecy.
* **BOS / CHoCH / MSS** (M03 `find_breaks`): zamknięcie świecy przez ostatni pivot dostępny przed tą świecą (bufor 0,01). Gdy wcześniejszy reżim (lub układ pivotów HH/HL, LH/LL) jest trendem w tym samym kierunku – BOS; przeciwnym – CHoCH, a z „displacement” (ciało ≥ 65% zasięgu i zasięg ≥ 1,2 ATR liczony as-of) – MSS.
* **Sweep** (BSL/SSL): knot przebija pivot o > 0,01, zamknięcie wraca za poziom.
* **FVG**: luka między high świecy 1 a low świecy 3 (lub odwrotnie) > 0,01; `formed_at` = dostępność 3. świecy; mitigacja z późniejszych świec.
* **OB (kandydat)**: ostatnia przeciwna świeca przed złamaniem z displacement; oznaczony „OB?” – heurystyka, nie dowód zleceń instytucji.
* **Premium/discount**: położenie ceny w ostatnim potwierdzonym zakresie pivotów.
* **5-CORE M03E**: przewaga strukturalna, znacząca lokalizacja (FVG/OB), kontekst płynności (LEVEL/SWEEP), ścieżka rozwoju, znane unieważnienie.

## 5. Strategie (M07/M03E v1.0.0, użyte bez zmian)

| Profil | Strategia | TF setupu | Warunki | Etapy (zamknięte świece) |
|---|---|---|---|---|
| MVP | XAU-S01 Trend Pullback | M15 | FVG zgodny z kierunkiem M02, mitigacja ≤ 65%, wiek ≤ 12, odległość ≤ 2 ATR, poziom płynności | progi: 0,15/0,30/0,45/0,60 ATR |
| SMC | XAU-S14 Sweep+FVG | M15 | jak MVP + sweep przed FVG (≤ 18 świec) | j.w. |
| SCALPING | XAU-S06 Displacement | M5 | BOS/MSS z displacement (≤ 12 świec) + FVG (≤ 8) | 0,20/0,40/0,60/0,80 ATR |

AUTO = stała kolejność SMC > MVP > SCALPING (nie ranking oczekiwanego zysku). Plan zamraża `ResearchPlanLock` (hash).
Kwalifikacja i potwierdzenie na CLOSE, uzbrojenie i trigger na HIGH (LONG)/LOW (SHORT); unieważnienie na CLOSE, sprawdzane przed awansem.

## 6. Cykl życia (M10A v1.1.0)

`EARLY_SETUP → QUALIFIED → ARMED → TRIGGERED → CONFIRMED`; terminalne `INVALIDATED, EXPIRED, MISSED_ENTRY, ENTERED, CANCELLED`.
Jedna zmiana etapu na nową zamkniętą świecę; świece dostępne przed wykryciem setupu nie awansują go; CONFIRMED na świecy późniejszej niż TRIGGERED.
**Rozszerzenia aplikacji (jawne):** TTL = `strategy.setup_ttl_bars` (domyślnie 24 świece TF setupu) – spec M10A mówi o TTL, nie podaje wartości;
okno wejścia po CONFIRMED = 2 świece (potem MISSED_ENTRY). Mapowanie na `signal_stage`: EARLY_SETUP…TRIGGERED → EARLY; CONFIRMED → CONFIRMED.

## 7. Poziomy wykonawcze – MQAI-LEVELS-1.0.0 (ROZSZERZENIE, PROWIZORYCZNE)

M07 nie definiuje TP. Reguła aplikacji: SL = poziom unieważnienia planu (+ spread dla SHORT); TP1/TP2 = najbliższe potwierdzone
poziomy płynności po przeciwnej stronie (M03:LEVEL) na TF setupu / H1, oddalone ≥ 0,5 ATR. Brak poziomu = brak celu = brak wejścia.
Zarządzanie: TP1 zamyka `tp1_weight` (50%) wolumenu, potem SL na BE. **Wymaga walidacji M06R/M06T (OOS) – niezweryfikowane.**

## 8. Ryzyko (M11 v1.0.0)

Budżet = equity × ryzyko%; dostępne = min(budżet, limit dzienny − zużyty, limit portfela − otwarte ryzyko). Kalkulator brokera
`order_calc_profit` dla 1 lota; koszty = prowizja ×2 + stres poślizgu; lot = floor do kroku, nigdy w górę do minimum.
RR netto < 1,5 BLOCKED; 1,5–2,0 CONDITIONAL (bez wykonania); ≥ 2,0 PASS (sam RR nie autoryzuje). Kill switch nie zamyka pozycji.
**„Spread do 40%”** (M01 v4.2.1 §12): mianownik nieustalony w źródłach → `REQUIRES_DEFINITION`, nieużywane jako filtr.

## 9. Makro (M04 / M04N v1.1.0)

Kalendarz częściowy (BLS + Forex Factory/Metals Mine tygodniowo). Brak kalendarza ≠ brak wydarzeń. Okno wydarzenia HIGH
(−45/+30 min, konfiguracja M04N) blokuje wejścia, gdy `risk.macro_block_high_impact=true` (domyślnie), a przy niedostępnym kalendarzu
wejścia są blokowane (M11 §2: „brak zaufanego kalendarza → UNKNOWN, a jeśli polityka go wymaga, blokada live”). Nie liczy się surprise ani sentymentu.
DXY opcjonalny (M02I `required_for_xau_direction=false`); blokuje tylko strategie wpisane w `strategy.strategies_requiring_dxy`.

## 10. Agent AI (nowy element, nie z oryginału)

Claude ocenia kandydatów z silnika; nie ustala lota/SL/TP, nie składa zleceń. AI gate przechodzi tylko dla CONFIRMED setupu, tej samej
sesji/rachunku/stanu setupu, przed wygaśnięciem i przy zgodnym kierunku. Brak AI → blokada wejść wymagających AI (`agent.required_for_entry`).
