# Boksy sesji i heatmapa likwidacji (PMW-UPD-06)

## Jak włączyć
Wykresy → Wykresy MTF → zaznacz **Boksy sesji** i/lub **Heatmapa likwidacji**. Obie warstwy są obserwacyjne (OBSERVE): nie tworzą sygnału,
nie są bramką wejścia, nie zmieniają TP1 (= MID zakresu M5), SL, wielkości pozycji, kosztów ani Execution Lock.

## Boksy sesji – wspólny silnik
`analytics/session_engine.py` liczy boksy raz dla scalp, lab, wykresów i agenta. Profile (wybór w Ustawieniach `liquidity.scalp_profile`):

| Profil | ASIA | LONDON/EUROPE | NEW_YORK/US |
|---|---|---|---|
| SCALP_OPENING_V1 (domyślny scalp) | 09:00–15:00 Asia/Tokyo | 08:00–12:00 Europe/London | 08:00–12:00 America/New_York |
| LAB_XAU_REFERENCE_V1 | 09:00–15:00 Asia/Tokyo | 08:00–16:30 Europe/London | 08:20–13:30 America/New_York |
| LAB_BTC_REFERENCE_V1 | 08:00–16:00 Asia/Singapore | 08:00–16:30 Europe/London | 09:30–16:00 America/New_York |

To robocze definicje projektu, nie uniwersalne godziny handlu. Okno `[start, end)` w strefie IANA (DST z `zoneinfo`), geometria z jednego
bazowego TF (domyślnie M1); ten sam profil daje ten sam boks (ten sam `box_id`) na każdym wykresie.

Stany: **DEVELOPING** (zakres w trakcie – brak końcowych high/low), **FINAL** (okno zakończone i wszystkie oczekiwane świece obecne;
`known_at` = koniec okna lub późniejsza dostępność danych), **INCOMPLETE** (brakujące świece – nigdy pełny boks), **NO_DATA**.
Bez potwierdzonego kalendarza brokera pokrycie ma podstawę CALENDAR_UNKNOWN (brak świecy jest pokazany, nie interpolowany).

Zdarzenia (po FINAL, potwierdzone zamknięciem świecy, dostępne najwcześniej w `known_at`):
* **SWEEP_HIGH / SWEEP_LOW** – przekroczenie jednej krawędzi i zamknięcie z powrotem w boksie,
* **SWEEP_BOTH_AMBIGUOUS** – obie krawędzie w jednej świecy, zamknięcie w środku: kolejność nieznana, brak kierunku,
* **BREAKOUT_UP / BREAKOUT_DOWN** – zamknięcie poza boksem (kontekst kontynuacji, nie fade),
* **RETURN_INSIDE_AFTER_BREAK** – powrót po wybiciu (osobny epizod, nie „wcześniejszy sweep”).
Krawędzie: UNTOUCHED → SWEPT / BROKEN → EXPIRED (następny start tej samej sesji). Równość high z krawędzią to nie sweep.

## Heatmapa likwidacji
* Źródło: **CoinGlass API v4 model1** (wariant PAIR = para+giełda albo AGGREGATED = moneta; aktywny jest jeden, mapy nie są sumowane)
  lub import pliku `data/liquidity/inbox/*.json` (schemat `pmw-liq-export-1`). Plan z dostępem do model1 (wg dokumentacji Professional/
  Enterprise) **nie jest zakładany** – brak uprawnień daje ENTITLEMENT_REQUIRED, brak klucza MISSING_API_KEY.
* Klucz: panel → Heatmapa likwidacji → Ustawienia źródła → „Zapisz klucz” (SecretStore, DPAPI na Windows) albo zmienna `COINGLASS_API_KEY`.
  Klucz nigdy nie wraca do panelu, URL ani logów.
* Znaczenie: **szacowane poziomy likwidacji** modelu dostawcy (ESTIMATED_LIQUIDATION_LEVELS) – nie rejestr stopów brokera ani pewny cel ceny.
  Kolor = log1p intensywności (`provider_intensity`, bez założonego „$”); brak komórki = nieznane (nie zero).
* **XAUT ≠ XAUUSD-**, BTC perpetual ≠ BTC CFD brokera: mapa obcego instrumentu jest pokazywana w osobnym panelu z osią ceny źródła
  (MAPPING_UNVALIDATED). Nałożenie na cenę brokera wymaga zweryfikowanego adaptera basis – w tej wersji niedostępne.
* Archiwum point-in-time: każdy nowy payload = nowy niezmienny snapshot z `first_received_at` nadanym przy odbiorze; ten sam payload
  ponownie tylko odświeża `last_seen_at`. Decyzja w chwili D widzi wyłącznie snapshot otrzymany do D. Import pliku z deklarowaną dawną datą
  dostaje zaufanie DECLARED_UNVERIFIED (czas odbioru = czas importu).
* Strefy analityczne: kwantyl 0,85 dodatnich intensywności ostatniego przekroju, łączenie sąsiednich koszyków, maks. 15 stref – heurystyka
  RESEARCH, nie prawdopodobieństwo. Zmiana zoomu/palety/LOD nie zmienia stref.

## Jak bot to odczytuje (reguły LQ-K01–K14, `analytics/liquidity_context.py`)
Karta „Boksy sesji i heatmapa – jak bot to odczytuje” i narzędzie agenta `get_liquidity_context` pokazują reason codes:
SESSION_DEVELOPING, SESSION_EDGE_NEAR, SESSION_LOW_REJECTION (kontekst dla istniejącego BUY), SESSION_HIGH_REJECTION (dla SELL),
SESSION_BREAKOUT_CONTEXT, SESSION_RETURN_AFTER_BREAK, SESSION_BOTH_SIDES_AMBIGUOUS, LIQ_ESTIMATED_ZONE, LIQ_ZONE_CONTACT
(tylko przy zweryfikowanym mapowaniu), LIQ_SESSION_CONFLUENCE_RESEARCH, LIQ_CONTEXT_UNKNOWN (z przyczyną). Ten sam knot opisany przez kilka
narzędzi to jeden epizod (evidence family), nie kilka dowodów. Wiedza LQ-K jest dołączana do promptu agenta (wersja w `prompt_version`).

## Ocena B0–B3 (czy to pomaga?)
`25_LIQUIDITY.bat` → 5, albo `python -m masterquo liquidity evaluate --asset XAUUSD`. Ten sam strumień okazji scalp (replay z kosztami),
warianty jako filtry decyzji w pełnym chronologicznym replayu: B0 baseline, B1 + odrzucenie krawędzi sesji (≤0,15 ATR M5, wiek ≤30 min),
B2 + strefa heatmapy (tylko zweryfikowane mapowanie i snapshot otrzymany przed decyzją), B3 = B1 i B2. Raport: transakcje, expectancy na
transakcję i na okazję, drawdown, dni, sparowany bootstrap dni względem B0, osobno ostatnie 20 % (zarezerwowane we wspólnym `eval_ledger`).
Statusy: FIXTURE_ONLY, INSUFFICIENT_EVIDENCE, BLOCKED / BLOCKED_NO_POINT_IN_TIME_HISTORY, NO_VALIDATED_EDGE albo
LIMITED_POSITIVE_RESULT_THIS_PERIOD – żaden wynik nie promuje wariantu do LIVE.

## Stan w środowisku budowy
Kod, testy na fixture i UI: gotowe. Klucz/uprawnienia CoinGlass: brak → MISSING_API_KEY. MT5: brak (NOT_RUN_MT5_UNAVAILABLE).
Archiwum heatmapy: puste → B2/B3 zablokowane. Przewaga: NOT_EVALUATED.

## Rollback
Odznacz warstwy; `liquidity.sources.*.enabled=false`. Archiwum `liq_heatmap_snapshots` i `mtf`/`scalp` dane pozostają nienaruszone.
