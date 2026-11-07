# Wskaźniki PMW-IND-1, relacja XAUUSD × DXY, plany Pepe Scalp/Hedge i SVP – 1.33.0 (specyfikacja IND)

Wszystko w tym dokumencie to **informacja analityczna**. Wskaźniki same nie blokują strategii. Pasma σ nie są przedziałami
prawdopodobieństwa, a strefy nie są zleceniami.

## 1. Kontrakt PMW-IND-1 (`indicators/contract.py`)
Każdy wynik zawiera:
* `indicator_id` i `algorithm_version`;
* `config_hash`;
* `values` z `units`;
* `status` i `reason` (OK / WARMUP / NO_DATA / DISABLED / STALE / ERROR);
* `data_time` (czas źródła);
* `available_at` (kiedy wartość była znana, bez wiedzy wstecznej);
* `sample_count` i `volume_source`.

Liczby są zapisane z 12 cyframi znaczącymi.

## 2. Wskaźniki

| Wskaźnik | Plik | Definicja | Uwagi |
|---|---|---|---|
| AVWAP SESSION / EVENT / MANUAL | `avwap.py` | VWAP od kotwicy (otwarcie sesji profilu, zdarzenie, kotwica ręczna) z pasmami ±1σ/±2σ, odległość w ATR i σ, nachylenie; zdarzenia CROSS_UP/DOWN i RETEST | kotwica ma czas źródła i potwierdzenia oraz wersję; zmiana kotwicy = nowa wersja |
| Spread względem sesji | `spread.py` | próbkowanie stałym zegarem, percentyl (mid-rank) względem tych samych slotów wcześniejszych sesji, flaga „nietypowy” | WARMUP, dopóki nie ma minimum sesji odniesienia |
| Semiwariancja | `semivar.py` | udział wariancji spadkowej 20/60 świec M1, RV | luki w danych przerywają okno |
| XAUUSD × DXY | `dxy.py` | zwroty H1 tylko dla godzin obecnych w **obu** seriach (bez forward-fill); korelacja 24/72/240 h; beta i reszta z liczone na obserwacjach **przed** bieżącą | DXY = kontekst H1, nie trigger M1; seria do wykresu nie jest cechą treningową |
| Mikrostruktura | `ofi.py` | nierównowaga best / głębokości, microprice − mid, OFI (Cont–Kukanov–Stoikov) z resetem po luce | arkusz MT5 (`market_book_*`) przez kolejkę MT5; archiwum do treningu MICROSTRUCTURE |
| Profil sesji | `profile.py` + `zones/dsvie.py` | odległość od POC (ATR), pozycja w VA, RVOL z kontrolą długości historii i pokrycia, migracja POC, kształt | niepełne sesje są odrzucane |

Wskaźniki liczy usługa `IndicatorService` w Runtime (baza `data/indicators/indicators.sqlite`). Trafiają do:
* kontekstu ścieżki ACTIVE (`view.context["indicators"/"dxy"]`);
* SCALPING / HEDGING (rola OBSERVE);
* agenta Claude (narzędzia `get_pmw_indicators`, `get_dxy_relation`);
* panelu: zakładka **Precision → XAUUSD × DXY i wskaźniki PMW** (`#/dxy`) i warstwa **AVWAP** na wykresach M1/M5.

API: `/api/v1/indicators/status|snapshot|refresh|chart|dxy|anchors|manifest`.

**Konfiguracja:**
* `mt5.dxy_symbol` – prawdziwy symbol indeksu u brokera (puste = DXY wyłączony z powodem);
* `indicators.*` – okna, minimalne obserwacje, maksymalny wiek, TF AVWAP, arkusz.

## 3. Plany Pepe Scalp Plan / Pepe Hedge Plan (PMW-PLAN-1, `plans/`)
Plany powstają z planu strategii SH, koordynatora, ryzyka i maszyny stanów. Zawierają:
* poziomy planu (ENTRY, SL, TP1–TP3);
* fill (rzeczywista cena wejścia);
* SL v2 po przesunięciu na BE (z powodem);
* cele z danych wykonania;
* noga HEDGE z poziomem aktywacji (konto NETTING = „niedostępne”; strategia nie jest po cichu zamieniana na inną);
* warunek koszyka (tekstowo, bo jest w pieniądzu).

Stany planu: READY / ACTIVE / CLOSED / EXPIRED / INVALIDATED / WAIT / NO_TRADE.

Panel: na każdym wykresie przyciski **Scalp Plan** i **Hedge Plan** pokazują poziomy jako linie. Przełączenie warstwy nie zmienia
zleceń (sprawdzone testem: brak żądań innych niż GET). API: `/api/v1/plans/chart?layer=SCALP|HEDGE`.

## 4. SVP – Session Volume Profile (PMW-SVP-1, `svp/`)

**Profile.**

| Tryb | Opis |
|---|---|
| SESSION | sesja profilu, IANA, DST |
| RANGE | zakres dat |
| VISIBLE | zakres widoczny |
| LIVE | profil rozwijającej się sesji |
| FROZEN | zapisany snapshot, nigdy przeliczany |

* Siatka cen to wielokrotność ticka. Waga świecy jest zachowana: rozkład w jej zakresie [low, high] daje **estymatę aktywności**, a nie
  footprint transakcji.
* Wynik: POC, VAH/VAL, VA %, HVN/LVN, pokrycie, histogram.

**Strefy.**
* Źródła: MANUAL (ręczne), ALGORITHM (z profilu) i AI (propozycja agenta).
* Wszystkie mają wersje i historię. Można odtworzyć stan „na czas” (`as_of`).
* Propozycja AI jest walidowana względem snapshotu profilu. Wynik spóźniony (starszy niż bieżący profil) jest odrzucany.
* AI LIVE ma limit i deduplikację, a koszt jest zapisywany w `agent_runs`.

**Panel:** **Precision → SVP – Session Volume Profile** (`#/svp`).
* Przyciski: Utwórz, Przelicz, Zamroź, LIVE, AI LIVE, Strefy teraz (algorytm), Propozycja AI, Usuń, dodanie strefy ręcznej, Wyczyść strefy auto.
* Histogram pokazuje VA i POC.
* Warstwa **SVP** na wykresach rysuje granice stref.

API: `/api/v1/svp/*`. Agent: `get_svp_profiles`.
