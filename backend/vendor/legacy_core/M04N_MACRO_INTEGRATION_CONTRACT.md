# Kontrakt M04N/M04/M11/M14/M15 — v1.0.0 CANDIDATE

```text
M04N v1.1 -> [M04N_INTELLIGENCE.json, M04N_M04_CONTEXT_BRIDGE.json]
                  |  (strict as_of, feed age, provenance)
                  v
        M04.calendar_context      M11.evaluate*       M14->M15 technical
                  |                     |                   |
                  +---------------------+-------------------+
                                        v
                            M04N_MACRO_GUARD.py
                                        |
                           guarded macro M15-like report
                                        v
                       M04N_MACRO_VIEWER.py / opt-in macro-only Telegram
```

`*` M11.evaluate wymaga pełnego zewnętrznego payload z rzeczywistej migawki. Domyślnie M11.result_base daje BLOCKED.

## Niezmienniki

1. Źródło ceny: wyłącznie MT5, symbol brokera, bez screen/OCR i bez TradingView jako bid/ask.
2. Nie zmieniaj stanu M10A ani oryginalnego M14. `m14_original_decision` nie jest modyfikowane; `guarded_display_decision` może wyłącznie obniżyć prezentowaną gotowość do `WAIT` lub `NO_TRADE`.
3. `macro_gate` może przyjąć **wyłącznie** `PENDING` albo `BLOCKED`, ponieważ żaden z dostępnych kalendarzy nie certyfikuje całego rynku.
4. HIGH/EXTREME w oknie M04 → BLOCKED; brak feedu, stale, konflikt bridge/report, fałszywe VERIFIED → BLOCKED.
5. Żadna liczba `actual/forecast` z portali trzecich nie służy do liczenia surprise. M04 nie ma `released_at` i `actual_available_at`, dlatego nie policzy niespodzianek.
6. Starsze lub niepewnie datowane newsy nie stanowią pilnego alertu; `FIRST_SEEN` ≠ `PUBLISHED`. Pierwsze załadowanie nie wyzwala Telegrama.
7. Wszystkie końcowe odpowiedzi: `execution_permission=BLOCKED`, `execution_eligible=false`, `live_execution_allowed=false`, `broker_order_sent=false`, `submitted_order_id=null`, `order_actions=[]`.
8. `schema_version=2.0.0`; poprzednie moduły nienaruszone. Zmienione wyłącznie **nowe adaptery**.
9. Dowody syntetyczne z DEMO nie są źródłem sygnałów rynkowych. Nie używać w produkcji bez certyfikacji kolektora i osobnego audytu brokera.
10. Telegram M04N Macro Guard nie służy do dystrybucji wejść na rynek, a do informowania o ryzyku publikacji.

## Nowy raport JSON

`runtime/M04N_GUARDED_MONITOR.json`:
- `as_of` — czas weryfikacji UTC; czas świec, eventów i wiadomości w osobnych polach
- `integrity_status` — `VALID_PARTIAL` / `FAIL_CLOSED`
- `macro_gate` — `PENDING` / `BLOCKED`
- `m04_calendar_context` — faktyczny wynik oryginalnego `M04.calendar_context`
- `m11_risk_gate`, `m11_risk_reason` — wynik rzeczywistego M11 lub BLOCKED gdy brak danych
- `m14_original_decision`, `m14_analysis_id` — oryginalna techniczna decyzja zweryfikowana z eksportem M15
- `guarded_display_decision` — `WAIT`/`NO_TRADE` gdy kontekst makro/monitor nie wystarcza
- `source_health`, `macro_active_events`, `macro_new_high_impact_news` — stan odczytów
- `execution_permission=BLOCKED` — stały kontrakt bez prawa wykonania.

## Uruchamianie

Kolektor, runner MT5 i Macro Guard to odrębne procesy; nawet jeśli proces źródłowy padnie, Guard nadal publikuje `NO_TRADE/BLOCKED` i nie wykorzystuje przeterminowanego pliku.
