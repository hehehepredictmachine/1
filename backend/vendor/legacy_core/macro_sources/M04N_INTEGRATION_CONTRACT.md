# Kontrakt integracji — M04N Gold & USD Intelligence Feed

**Wersja:** M04N `1.0.0`; `schema_version=2.0.0`; `prompt_version=4.1.0`. **Stan:** CANDIDATE / PENDING APPROVAL. Nie zastępuje M04.

## Docelowy przepływ

```text
Fed/BLS RSS  ┐
BLS Calendar ICS ┤
GDELT news  ├─ M04N http collector ─ SQLite/provenance ─ M04N_INTELLIGENCE.json ─ M15 VIEW (informacja)
FRED API*   ┘                                     └─ M04N_M04_CONTEXT_BRIDGE.json
                                                             ↓
M01 MT5 candles + M02 regime + M03 structure + M16 health ─ M04 calendar_context ─ M11/M14 gates
```

`*` opcjonalny klucz FRED, `DTWEXBGS` nie jest DXY, nie wykorzystywać wartości FRED do wyznaczania dokładnej ceny wejścia MT5. GDELT może wymagać ograniczenia częstotliwości; błędy są niezależne na poziomie źródła.

### M04N_M04_CONTEXT_BRIDGE.json

```json
{
  "module_id": "M04N",
  "module_version": "1.0.0",
  "as_of": "<UTC now, verified source timestamp>",
  "context_inputs": {
    "macro_events": [
      {"event_id":"CAL:...","name":"Consumer Price Index","impact":"HIGH","scheduled_at":"<UTC>","source_id":"BLS_CALENDAR","available_at":"<UTC first seen>","actual":null,"forecast":null}
    ],
    "calendar_coverage": {"status":"PARTIAL","data_complete":false,"source_id":"BLS_CALENDAR","scope":"BLS_ONLY"},
    "macro_news_context": {"as_of":"<UTC>","fresh_items":[],"source_health":{},"news_coverage_complete":false},
    "fred_observations": []
  },
  "advisory":{"risk":"...","execution_permission":"BLOCKED","does_not_override_m04_m11_m14":true}
}
```

Do M04 można **scalić tylko `context_inputs`** i wyłącznie przy zgodnym `as_of`. Nie podmieniaj `data_snapshot`, `market_state`, `market_evidence`, `runtime_health`. `available_at` wskazuje pierwszy rzeczywisty odczyt kalendarza. Kalendarz BLS jest **PARTIAL**, bez `window_from/to` certyfikującego cały zakres.

- `HIGH` / `EXTREME` ze sprawdzonego czasu harmonogramu może dać w M04 `event_gate=BLOCKED`.
- Brak wpisów przy częściowym kalendarzu lub braku połączenia pozostaje `event_gate=PENDING`. Brak danych NIE jest dowodem `LOW`.
- Nagłówki newsowe mają oddzielną strukturę `macro_news_context`, nie są wpisywane do `macro_events` jako pewne terminy publikacji. Domniemana korelacja i kierunek są **UNKNOWN**.
- `actual` / `forecast` pozostają `null` (nie znamy konsensusu ani faktycznego czasu udostępnienia liczby) — M04 nie liczy niesprawdzonego surprise.
- Potwierdzenie wpływu na XAUUSD można później sprawdzać w M06 przez event-study z synchronizacją zegarów publikacji i brokerowych cen MT5, bez lookahead.
- M14 zachowuje ostateczne uprawnienia do decyzji; `execution_permission` M04N zawsze `BLOCKED`.

### Zasady spójności i bezpieczeństwa

1. Pierwszy import (backfill) nie jest zdarzeniem „just arrived”.
2. Każde źródło ma osobne `HEALTHY` lub `UNAVAILABLE_OR_STALE` i czas ostatniego sukcesu; degradacja nigdy nie oznacza braku wydarzeń.
3. Jedno URL = jedno `NEWS:event_id` w SQLite, niezależnie od liczby pobrań; `seen` nie jest timestampem publikacji.
4. Po awarii źródła utrzymanie starszych wpisów w archiwum jest dozwolone, ale odbiorcy MUSZĄ oceniać świeżość `as_of` i zdrowie źródła.
5. Brak autoryzacji M08, M11, M14 i M06; ten pakiet nie implementuje wysyłki Telegram (połączenie z M15 osobnym następnym etapem).

## Testy integracji z M04

`py -3 -m unittest -v M04N_M04_CONTRACT_TESTS`

W pakiecie `vendor/M04_REFERENCE_ENGINE.py` znajduje się **niezmodyfikowana kopia** referencyjnego kodu M04 tylko do lokalnych testów kontraktu. Żaden istniejący plik MasterQUO nie jest nadpisywany.

## Forex Factory / Metals Mine weekly exports — addendum v1.1.0

- `FF_CALENDAR` oraz `MM_CALENDAR` emitują `calendar.events` po odfiltrowaniu nieaktualnych źródeł. Wspólne wydarzenia w ciągu tej samej minuty, o identycznej walucie i tytule, występują jeden raz, ze wszystkimi `provider_sources` oraz `provider_occurrences`. Źródła są skorelowane (Fair Economy), nie są osobnymi dowodami.
- `context_inputs.macro_events` przenosi scalone wydarzenia oraz oznaczenie pochodzenia. Wszystkie wartości `actual`, `forecast`, `previous` od osób trzecich to **niesprawdzone stringi**; nie wolno wykorzystywać do obliczania liczbowych niespodzianek (surprise) ani automatycznego kierunku.
- `context_inputs.calendar_coverage.status` zawsze PARTIAL albo UNAVAILABLE, `data_complete=false`. Nigdy nie podnosić do VERIFIED wyłącznie na podstawie tych dwóch eksportów.
- Jeśli kanał zbraknie lub straci świeżość, stare wydarzenia pozostają w SQLite jako historia, lecz nie są traktowane jako aktualny czynnik aktywnego `macro_risk`.
- BLS zachowuje własne pochodzenie oficjalne; dokładne duplikaty z obu portali są łączone, ale dane firm trzecich pozostają oddzielne w `provider_occurrences`.
- Żadna aktualizacja news/makro nie może nadawać uprawnienia wykonania M11/M14: `execution_permission=BLOCKED`.
