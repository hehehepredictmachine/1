# PMW-SH-1 · Etapy 5–6 – Specyfikacja SCALPING i HEDGING

Kod:
* `sh/setup.py`: logika setupu;
* `sh/lifecycle.py`: cykl życia pozycji;
* `sh/hedge_fsm.py`: automat koszyka;
* `sh/service.py`: integracja na żywo;
* `sh/executor.py`: wykonanie.

Konfiguracja: `config/sh_strategies_v1.json` (jedno źródło dla backendu i panelu) plus zmiany z panelu (`/api/v1/sh/config`,
historia i rollback).

Testy:
* `tests/test_sh_core.py`: jednostki, cykl życia, automat koszyka;
* `tests/test_sh_setup.py`: setup;
* `tests/test_sh_risk_state.py`: ryzyko, stan, wykonanie;
* `tests/test_sh_service.py`: odbiór na poziomie serwisu (PAPER, symulowany terminal, restart);
* `tests/test_sh_api.py`: endpointy na prawdziwym procesie serwera.

> Parametry w konfiguracji to **parametry robocze do walidacji** (`status: PARAMETRY_ROBOCZE_DO_WALIDACJI`). Nie są
> zoptymalizowane i nie są obietnicą wyniku. BTC jest **wyłączony** (`enabled: false`) do czasu kalibracji na danych BTC
> klienta. Ustawień XAUUSD nie przenosi się automatycznie na BTC.

## Wspólne zasady

* **Jednostka TP**: bezwzględny ruch ceny instrumentu kwotowanego w USD, liczony od **rzeczywistej ceny wykonania**.
  * Nie jest to procent, punkty MT5 ani zysk rachunku.
  * Symbol kwotowany w innej walucie jest odrzucany (`QUOTE_CURRENCY_*_NEEDS_EXPLICIT_UNIT_CONVERSION`), chyba że profil
    zawiera jawny przelicznik.
  * Cel jest zaokrąglany do siatki ticków konserwatywnie, czyli nigdy bliżej niż żądano: BUY w górę, SELL w dół.
    Różnica jest zapisywana w zdarzeniu `BOUND` (`rounding`) i pokazywana w panelu.
* **Symbol**: rzeczywisty symbol brokera z terminala (np. `XAUUSD-`). Nie ma automatycznej podmiany BTC na
  BTCUSD/BTCUSDT/CFD.
* **Koszty**: spread (bieżący Bid/Ask) + 2× poślizg (profil) + prowizja.
  * Prowizja = `commission_per_lot_side`. Wartość `null` oznacza nieznaną prowizję: koszt jest wtedy niepełny, co widać w
    panelu, a AUTO jest zablokowane.
  * Rachunek typu „Zero” nie oznacza zerowych kosztów.
  * Swap jest pomijany w SCALPING (pozycja maks. 90 min). W HEDGING (maks. 8 h) jest pokazywany jako niewyceniony, bo
    brakuje danych swap w profilu.
* **Statusy sygnału**: READY, WAIT, NO_TRADE, EXPIRED (TTL), INVALIDATED. Sygnał WAIT nigdy nie jest pokazywany jako
  aktywny i nie ma planu TP/SL.
* **Score** (0–100 z checklisty) **nie jest prawdopodobieństwem**. Prawdopodobieństwo „TP2 przed SL w horyzoncie” pokazywane
  jest tylko z modelu zdarzenia READY (`sh_tp_model`).
* **Plan zamrożony**: parametry i hash konfiguracji są zapisywane przy tworzeniu planu. Późniejsza zmiana ustawień nie
  modyfikuje otwartej pozycji.
* **Własność**: magic 41082100 i komentarz `SH:<plan>:<noga>`. Stary menedżer pozycji ich nie dotyka. Jedna pozycja ma
  jednego właściciela (`sh_owners`).
* **BE**: definicje są dwie.
  * „BE ceny wejścia” (`ENTRY`).
  * „BE po kosztach” (`ENTRY_PLUS_COSTS`, domyślnie): wejście ± koszt round-trip.
  * Panel pokazuje definicję i zastrzeżenie: **stop nie gwarantuje braku straty przy luce lub poślizgu**. Test
    `test_gap_through_stop_fills_worse` pokazuje wynik poniżej −1R przy luce.

## Logika setupu (8 kroków, wspólna dla obu strategii, parametry per strategia)

| Krok | Warunek | Wynik przy niespełnieniu |
|---|---|---|
| 0 | instrument dopuszczony, waluta kwotowania USD | NO_TRADE |
| 1 | dane: zamknięte świece, kolejność, NaN, wiek świec i notowania, spread ≤ limit | NO_TRADE |
| 1b | ATR M1/M5 policzone | WAIT (rozgrzewka) |
| 2 | reżim dopuszczony dla strategii | NO_TRADE |
| 2 | TREND → **CONTINUATION** w kierunku trendu M5. Konflikt H1/M15 → WAIT. TRANSITION wymaga zgodności M5 i M15. RANGE → **REVERSAL** | WAIT |
| 3 | CONTINUATION: strefa = ostatni pullback M5 (SMC/pullback, w razie braku swing structure_v2) + `zone_atr_m5`×ATR5; unieważnienie = kotwica ∓ `sl_atr_m1_buffer`×ATR1. REVERSAL: krawędź zakresu M5 (25 % szerokości), środek zakresu → WAIT | WAIT / INVALIDATED |
| 3 | dotknięcie strefy w ostatnich 10 M1 i cena nie dalej niż 0.5 ATR5 od strefy (bez pogoni) | WAIT |
| 4 | CONTINUATION: VAMD M5 zgodny i FD M5 ≠ CHOP. REVERSAL: CHoCH M1 ≤ 10 świec albo świeca odwrócenia (sci2 LONG/SHORT) | WAIT |
| 5 | trigger: zamknięcie ostatniej **zamkniętej** M1 poza ekstremum 2 poprzednich | WAIT |
| 7 | SL = max(odległość do unieważnienia, `sl_min_usd`). SL > `sl_max_usd` → **odrzucenie** (SL nie jest poszerzany pod TP) | NO_TRADE |
| 6 | przeszkoda (swing M5/M15/H1, aktywny poziom SMC) przed TP1 → NO_TRADE; między TP1 a TP2 → argument przeciw; zasięg ATR5·√(H/5) ≥ TP2; przy modelu READY P(TP2 przed SL) ≥ próg | NO_TRADE |
| 7 | RR netto całego cyklu = (Σ udział·TP − koszt)/(SL + koszt) ≥ `min_net_rr` | NO_TRADE |
| 8 | plan: udziały, BE po potwierdzonym TP2, TTL, limit czasu pozycji | – |

Kontynuacja i odwrócenie mają **osobne reguły** strefy, potwierdzenia i unieważnienia. Tryb wybiera reżim, nigdy oba naraz.

## SCALPING

| Parametr | Wartość domyślna |
|---|---|
| TP1 / TP2 / TP3 | **2.50 / 3.00 / 5.00 USD** od fill |
| udziały | 50 / 30 / 20 %; fallback przy min locie 60 / 40 % (TP1 i TP2, TP3 pominięty i pokazany) |
| BE | po **potwierdzonym** wykonaniu częściowym TP2, po kosztach |
| SL | 1.5–4.0 USD z unieważnienia; powyżej limitu odrzucenie |
| horyzont / TTL / limit pozycji | 30 min / 10 min / 90 min |
| reżimy | TREND, RANGE, TRANSITION |

Cykl życia (`lifecycle.Position`):
* Cele są przekraczane po stronie wykonywalnej: BUY zamyka po Bid, SELL po Ask. Kolejność jest zachowana. Luka przez kilka
  celów daje TP1, potem TP2, każdy raz.
* Część jest DONE dopiero po potwierdzonym wykonaniu (deal).
* Odrzucony partial wraca do PENDING i jest ponawiany.
* Odrzucona modyfikacja SL do BE jest ponawiana. Jeśli cena jest już za BE albo próby się wyczerpały, reszta pozycji jest
  zamykana (`RETRY_THEN_CLOSE`), więc nie zostaje bez obiecanej ochrony.
* TP3 to runner. Broker ma ustawiony TP = TP3 od fill jako zabezpieczenie, gdy bot jest offline.
* Limit czasu pozycji zamyka resztę (`TIME_LIMIT`).
* Wynik liczony jest dla **całego cyklu**: trzy części to jedna transakcja, nie trzy wygrane.

## HEDGING

| Parametr | Wartość domyślna |
|---|---|
| TP1 / TP2 / TP3 | **3.50 / 5.00 / 9.00 USD** (TP3 ∈ {9, 10}, wybór przed wejściem, zamrożony w planie) |
| udziały | 40 / 30 / 30 % |
| BE | po potwierdzonym TP2 oraz kontrola nogi hedge (unwind) |
| SL | 3–8 USD; reżim tylko TREND; horyzont 240 min; limit koszyka 480 min |
| zdarzenie hedge | niekorzystny ruch ≥ 0.5 × odległość SL **i** struktura ważna (cena przed unieważnieniem) |
| wolumen hedge | 0.5 × **bieżący** wolumen pozycji głównej (≤ `max_ratio` 0.5). **Brak martingale i siatki**: wolumen nigdy nie rośnie po stracie. |
| aktywacje | maks. 1 (walidacja ≤ 3); nieudana próba zużywa aktywację |
| unwind | odbicie ≥ 1.0 × ATR5 (z chwili wejścia), limit 60 min, potwierdzony TP2 pozycji głównej |
| wyjście koszyka | limit straty koszyka (1 × ryzyko transakcji, musi się mieścić w `risk_per_basket_pct`), unieważnienie, limit czasu |

Uzasadnienie hedge vs redukcja/zamknięcie (`Basket.hedge_decision` + `SHService.hedge_step`):
* struktura unieważniona → **EXIT** (zabezpieczanie straty nie ma uzasadnienia);
* ryzyko nie pozwala (rachunek nie-hedging, min lot, depozyt) → **REDUCE** o `reduce_fraction` z widocznym powodem;
* koszt hedge (spread + 2× poślizg) > `max_hedge_cost_fraction_of_sl` × SL → REDUCE;
* `variant: AUTO_BY_VALIDATION`: jeśli raport walidacji (`data/sh/validation/<inst>_HEDGING.json`, n ≥ 30) wskazuje, że
  wariant REDUCE lub NO_HEDGE ma wyższą wartość oczekiwaną netto niż HEDGE, automat stosuje ten wariant. Bez raportu
  walidacji stosowany jest HEDGE, ale to tryb ograniczony: AUTO jest zablokowane.

Automat stanów: IDLE → PRIMARY_OPEN → HEDGE_PENDING → HEDGED → UNWINDING → PRIMARY_OPEN …, EXIT_PENDING → CLOSED oraz ERROR.
* Odrzucony hedge **wraca do PRIMARY_OPEN**. Stan HEDGED nie występuje bez potwierdzonego wykonania (test
  `test_hedge_rejected_stays_unhedged`).
* Częściowe wykonanie zapisuje rzeczywisty wolumen.
* Noga hedge ma po stronie brokera SL i TP lustrzane do poziomów brokera pozycji głównej. Gdy bot jest offline, obie nogi
  zamykają się na tych samych poziomach, więc nie zostaje samotna pozycja przeciwna.
* Raport rozdziela:
  * pozycję główną (zrealizowane/niezrealizowane);
  * hedge (zrealizowane/niezrealizowane, aktywacje);
  * koszyk (zrealizowane, niezrealizowane, netto po kosztach);
  * ekspozycję brutto i netto;
  * stan ochrony.
* Uwaga w panelu: „SL pozycji głównej na BE nie oznacza, że koszyk jest zabezpieczony na zero”.
* **Rachunek netting/exchange**: HEDGING jest zablokowane w silniku ryzyka (`account_hedging`). Otwarty koszyk (np. PAPER na
  rachunku netting) nigdy nie otwiera hedge, tylko REDUCE z powodem (test `test_netting_never_hedges_silently`). Nie ma cichej
  podmiany.

## Rekonsyliacja i restart (AUTO_DEMO)

* Przy każdym ticku pozycja w terminalu jest porównywana z automatem:
  * brak pozycji albo mniejszy wolumen → zamknięcie przez brokera (SL/TP/BE) albo zewnętrzne, cena z dealów;
  * brak nogi hedge → zamknięcie hedge.
* Po restarcie lub ponownym połączeniu:
  * plan z wynikiem wejścia UNKNOWN jest **przejmowany** z terminala (magic + komentarz `SH:<plan>:P`) albo oznaczany
    REJECTED;
  * pozycje z magic SH bez właściciela są raportowane jako **ORPHANS** i nie są zarządzane automatycznie.
* Akcja o nieznanym wyniku (timeout) nigdy nie jest wysyłana ponownie na ślepo.

## Etapy 5–6 – raport

* **Dodano:**
  * `sh/service.py` (cykl na zamkniętej M1, zarządzanie na każdym ticku, rekonsyliacja, recover);
  * podłączenie w `runtime.py`;
  * 9 endpointów `/api/v1/sh/*`;
  * `variant` i `max_hedge_cost_fraction_of_sl` w konfiguracji;
  * `MODIFY_TP` w executorze.
* **Sprawdzono:**
  * PAPER: pełny cykl SCALPING z BE po potwierdzonym TP2; luka przez SL; SELL i limit czasu; fallback dwóch części; hedge →
    unwind → TP1–3 z rozliczeniem koszyka; wyjście na unieważnieniu; netting bez hedge;
  * symulowany terminal: magic, komentarz i TP brokera od fill; partial raz; odrzucenie BE; restart z pozycją zamkniętą
    offline; adopcja UNKNOWN i ORPHANS; odrzucony hedge; Execution Lock;
  * cykl na prawdziwym MarketBridge (SIGNALS: sygnały zapisane, zero planów);
  * endpointy na procesie serwera.
* **Zablokowane:**
  * jakość strategii (oczekiwana wartość po kosztach) wymaga walidacji na historii klienta (etap 9);
  * prowizja i swap XAUUSD-/BTC są nieznane;
  * test na prawdziwym terminalu demo wymaga MT5 klienta.
