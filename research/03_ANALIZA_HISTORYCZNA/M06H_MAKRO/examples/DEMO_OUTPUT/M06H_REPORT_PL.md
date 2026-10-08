# MasterQUO M06H — raport badawczy

**Status:** RESEARCH_ONLY · **Symbol:** XAUUSD · **Moduł:** 1.0.0-CANDIDATE

Zaobserwowane zamknięte świece M1: **1260**. Zdarzenia: **2**.

**DANE SYNTETYCZNE — WYŁĄCZNIE DEMONSTRACJA**

## Wpływ publikacji — opisowy, nie PnL

| Fold | Rola | Horyzont | Liczba zdarzeń | Mediana bezwzględnego ruchu (bp) | Pary kontrolne | Śr. nadwyżka abs. ruchu (bp) |
|---|---|---:|---:|---:|---:|---:|
| dev | DEVELOPMENT | 5m | 1 | 25.03 | 1 | 24.995146 |
| dev | DEVELOPMENT | 15m | 1 | 25.08 | 0 | N/A |
| dev | DEVELOPMENT | 60m | 1 | 25.30 | 0 | N/A |
| oos | FINAL_OOS | 5m | 1 | 25.02 | 1 | 24.987652 |
| oos | FINAL_OOS | 15m | 1 | 25.07 | 1 | 24.987668 |
| oos | FINAL_OOS | 60m | 1 | 25.29 | 1 | 24.987747 |

## Walidacja strategii i kosztów

**SYNTHETIC_DEMONSTRATION_ONLY** — NO_FORWARD_DEMO, PARTIAL_EVENT_CALENDAR_COVERAGE, NO_LIVE_AUTHORIZATION, SYNTHETIC_QUOTES_NOT_MARKET_EVIDENCE, COSTS_SCENARIO_ONLY.

| Fold | Baseline trades | Filter trades | Średni net R baseline | Średni net R filter |
|---|---:|---:|---:|---:|
| dev | 0 | 0 | None | None |
| oos | 1 | 1 | 1.14118793 | 1.14118793 |

### Według zamrożonych profili strategii

| Strategia | Fold | N przed filtrem | N po filtrze | R netto przed | R netto po | OOS minimum |
|---|---|---:|---:|---:|---:|---|
| XAU-S01@0.0.1 | dev | 0 | 0 | None | None | False |
| XAU-S01@0.0.1 | oos | 1 | 1 | 1.14118793 | 1.14118793 | True |

## Ograniczenia i blokady
- Wyniki syntetyczne lub z plików użytkownika NIE są zweryfikowaną przewagą strategii.
- Retrospektywne ruchy świec M1 NIE oznaczają możliwego wykonania transakcji ani kierunku przyszłego ruchu.
- Dzisiejszy kalendarz portali nie odtwarza historycznej wiedzy sprzed daty jego pobrania.
- Domyślne okna newsowe to wstępne założenia, a nie zoptymalizowane progi.
- Bez pełnego historycznego sygnału oraz ticków Bid/Ask i prowizji wynik netto = NOT_RUN.
- Brak pokrycia wydarzeń przez feed nie upoważnia do zniesienia blokady M04/M11/M14.
- Status wykonania: BLOCKED; wymagana dalsza walidacja OOS i forward DEMO.

Powody ostrożności: INSUFFICIENT_FINAL_OOS_EVENTS, SYNTHETIC_EVENTS_EXCLUDED_FROM_IMPACT_STUDY, GLOBAL_CALENDAR_COVERAGE_PARTIAL, BAR_PROVENANCE_EXTERNAL_NOT_CRYPTOGRAPHICALLY_CERTIFIED.
