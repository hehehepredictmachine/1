# Definicje formacji (MQ-CHART-1.0.0, MQ-CANDLE-1.0.0) i ograniczenia detekcji

**Zasady wspólne:**
- Formacje są liczone wyłącznie z OHLC brokera i **potwierdzonych** pivotów. Zrzuty ekranu nie są źródłem.
- Tolerancje są wyrażone w ATR14 danego TF. Linie to dopasowanie najmniejszych kwadratów przez pivoty z kontrolą reszt (max reszta ≤ 0,5 ATR).
- Wynik `geometric_score` / `score` (0–1) opisuje **jakość dopasowania geometrii**, nie szansę wygranej.
- Nazwa formacji nie wyznacza kierunku. Kierunek daje dopiero potwierdzone zamknięcie (wybicie lub neckline) i wariant strategii.

**Kod:** `backend/masterquo/analysis/chart_patterns.py`, `candles.py`, `levels.py`, `range_m5.py`.

## Pivoty i moment dostępności

**Definicja pivota:** swing high lub low z `left = right = 3` świecami (dla W1/MN1: 2/2). Pivot na świecy p jest **znany** dopiero po zamknięciu świecy p+3 (`known_at`).

**Momenty w czasie:**
- Formacja nie jest datowana wcześniej niż moment poznania jej ostatniego pivota (`detected_at`).
- Potwierdzenie to **zamknięta** świeca po tym momencie (`available_at`).
- Na wykresie pivot pokazuje oba czasy: kiedy powstał i kiedy stał się znany.

## Stany formacji

| Stan | Znaczenie |
|---|---|
| FORMING | geometria kompletna na znanych pivotach, brak zamknięcia potwierdzającego. To tylko **podgląd**, nigdy samodzielny sygnał |
| CONFIRMED | zamknięta świeca przełamała granicę / neckline w kierunku formacji |
| INVALIDATED (BROKEN) | po potwierdzeniu zamknięcie za poziomem unieważnienia albo przed nim zamknięcie za ekstremum formacji |
| EXPIRED | brak potwierdzenia w `ttl_bars` (30) od wykrycia albo potwierdzenie starsze niż `ttl_bars` |

**Ograniczenia skanu:**
- okno 150 świec;
- maks. 2 kandydatów na rodzinę;
- aktualizacja przy każdym nowym zamknięciu.

## Formacje wykresowe

| Rodzina | Pivoty / punkty | Tolerancja / geometria | Granica / trigger | Unieważnienie | Cel (propozycja) | Kierunek |
|---|---|---|---|---|---|---|
| RECTANGLE (range) | ≥ 2 H i ≥ 2 L | oba nachylenia ≤ 0,03 ATR/świecę, wysokość ≥ 1,5 ATR, rozpiętość ≥ 12 świec | zamknięcie poza linią ± 0,1 ATR | zamknięcie po drugiej stronie | ± wysokość | z wybicia |
| BREAKOUT_RETEST | prostokąt + wybicie | powrót do granicy ≤ 0,3 ATR | zamknięcie po stronie wybicia ponad high/low świecy retestu | ekstremum retestu ± 0,1 ATR | measured move | strona wybicia |
| FAILED_BREAKOUT_RECLAIM | prostokąt + wybicie | powrót do środka ≤ 5 świec | zamknięcie z powrotem w zakresie | ekstremum wybicia | przeciwna granica | przeciwny do wybicia |
| DOUBLE TOP / BOTTOM | 2 szczyty (dołki) + dołek (szczyt) między | różnica szczytów ≤ 0,5 ATR, odstęp ≥ 5 świec, głębokość ≥ 1 ATR | zamknięcie poza neckline | zamknięcie poza ekstremum | neckline ∓ głębokość | SHORT / LONG |
| TRIPLE TOP / BOTTOM | 3 szczyty (dołki) | jw. | neckline = niższy dołek (wyższy szczyt) | jw. | jw. | SHORT / LONG |
| HEAD & SHOULDERS / INVERSE | LS < H > RS + T1, T2 | głowa ≥ 0,5 ATR ponad barki, barki ≤ 1 ATR różnicy, neckline \|nachylenie\| ≤ 0,1 ATR/świecę | zamknięcie poza neckline | zamknięcie poza głową (prawym barkiem − bufor) | neckline ∓ wysokość głowy | SHORT / LONG |
| TRIANGLE ASC / DESC / SYM | ≥ 2 H, ≥ 2 L | zbieżność: szerokość końcowa ≤ 0,75 początkowej; ASC: płaskie H + rosnące L; DESC: malejące H + płaskie L; SYM: malejące H + rosnące L | zamknięcie poza linią ± 0,1 ATR | przeciwna linia | ± szerokość | **tylko z wybicia** |
| WEDGE RISING / FALLING | ≥ 2 H, ≥ 2 L | obie linie w tę samą stronę, zbieżne | jw. | jw. | jw. | tylko z wybicia |
| CHANNEL ASC / DESC | ≥ 2 H, ≥ 2 L | równoległe (różnica nachyleń ≤ 0,02 ATR/świecę) | jw. | jw. | jw. | tylko z wybicia |
| FLAG / PENNANT | maszt ≥ 3 ATR w ≤ 10 świecach + konsolidacja 5–15 świec ≤ 0,5 masztu | FLAG = pudełko / kanał, PENNANT = zbieżność | zamknięcie poza konsolidacją w kierunku masztu (`FLAG_BREAK_*`) | przeciwna granica konsolidacji | ± długość masztu | kierunek masztu po wybiciu |

**Dopuszczalne reżimy** wynikają ze strategii, która używa formacji, a nie z samej formacji. W S12 formacje są **opcjonalną** strukturą: zwiększają składnik „structure”, ale nie są warunkiem wejścia.

## Formacje świecowe (na zamkniętych świecach; świeca w trakcie = PREVIEW)

**Geometria świecy:**
- range = h − l;
- body = |c − o|;
- knoty górny i dolny;
- CLV = (c − l)/range.

Świeca bez zakresu (h = l) nie ma geometrii (`ZERO_RANGE`).

| Formacja | Definicja (LONG; SHORT lustrzanie) | Kierunek hipotezy | Wymagane następne potwierdzenie |
|---|---|---|---|
| ENGULFING_BULL/BEAR | poprzednia spadkowa, bieżąca wzrostowa, korpus ≥ poprzedni i ≥ 0,3 ATR, open ≤ poprzednie close + 0,05 ATR, close ≥ poprzednie open; **wariant NO_GAP_CFD** (bez wymogu luki) | LONG/SHORT | brak zamknięcia za ekstremum |
| PIN_BAR_BULL/BEAR | dolny knot ≥ 0,6 zakresu, korpus ≤ 0,3, CLV ≥ 0,6, zakres ≥ 0,5 ATR (sama geometria) | LONG/SHORT | zamknięcie powyżej high |
| HAMMER / SHOOTING_STAR | pin bar + kontekst: wcześniejszy ruch spadkowy (wzrostowy) | LONG/SHORT | jw. |
| MORNING / EVENING_STAR | świeca −2 z korpusem ≥ 0,6 ATR, świeca −1 z korpusem ≤ 0,3 × korpus(−2), bieżąca zamyka za połową korpusu −2; **NO_GAP_CFD** | LONG/SHORT | brak zamknięcia za środkową świecą |
| INSIDE_BAR | high ≤ high matki i low ≥ low matki: **tylko kompresja** | NEUTRAL | zamknięcie poza matką |
| INSIDE_BAR_BREAK_UP/DOWN | późniejsze (≤ 3 świece) **zamknięcie** poza high/low matki – osobny rekord | LONG/SHORT | brak powrotu za drugą krawędź |
| OUTSIDE_BAR_EXPANSION | high > poprzedni high i low < poprzedni low, korpus ≥ 0,6, zamknięcie w skrajnych 30% | LONG/SHORT | brak powrotu do połowy |
| OUTSIDE_BAR_REJECTION | jw., ale zamknięcie z powrotem w zakresie poprzedniej świecy, knot ≥ 0,4 po stronie odrzucenia | LONG/SHORT | zamknięcie kolejnej świecy w kierunku odrzucenia |
| DOJI / LONG_LEGGED_DOJI | korpus ≤ 0,1 zakresu; long-legged: oba knoty ≥ 0,3 i zakres ≥ 1 ATR – **równowaga/niepewność** | NEUTRAL | kierunek dopiero po kolejnej świecy |
| MARUBOZU_DISPLACEMENT | korpus ≥ 0,85 zakresu, zakres ≥ 1,2 ATR | kierunek korpusu | brak powrotu za połowę korpusu |
| TWEEZER_BOTTOM/TOP | \|low − poprzednie low\| ≤ 0,1 ATR, poprzednia spadkowa, bieżąca wzrostowa | LONG/SHORT | zamknięcie powyżej high pary |
| THREE_WHITE_SOLDIERS / BLACK_CROWS | 3 kolejne wzrostowe, rosnące zamknięcia, open w poprzednim korpusie, korpusy ≥ 0,5 ATR, górny knot ≤ 0,3 korpusu | LONG/SHORT | brak zamknięcia pod open trzeciej |

**Ograniczenia:**
- Engulfing w środku zakresu jest raportowany z kontekstem i nie jest triggerem.
- Doji nie wybiera kierunku.
- Inside bar pozostaje kompresją do potwierdzonego wybicia.
- Formacje wieloświecowe wymagają kompletu warunków.
- **Zdarzenie dowodowe**: nazwy na tej samej świecy (lub ostatniej świecy) w tym samym kierunku to **jedno** `evidence_event` (`evidence_events()`).
- Role w strategii: formacja wykresowa = struktura, świecowa = reakcja/trigger, walls i S/R = lokalizacja, ryzyko = osobne pozwolenie.

## Strefy S/R (MQ-SR-1.0.0)

**Budowa stref:**
- Pivoty TF są klastrowane z tolerancją 0,25 ATR (≥ 2 punkty).
- Strefa zapisuje: TF pochodzenia, granice, liczbę **niezależnych** reakcji, pierwszą i ostatnią reakcję, wiek, świeżość (≤ 60 świec = FRESH), stan (INTACT / BROKEN_UP / BROKEN_DOWN / RECLAIMED) i `available_at`.

**W1/MN1:**
- Są agregowane z zamkniętych D1. Data brokera = data (open_utc + 12 h).
- Miesiąc ma granice kalendarzowe, nie „30 dni”.
- Okres jest dostępny dopiero po jego zakończeniu.
- Za krótka historia daje **BRAK_DANYCH**; nic nie jest fabrykowane.

**Rodzaje poziomów:** S/R, FVG/OB (M03) i walls to różne typy poziomów. Ich bliskość jest cechą konfluencji.

## Czego detekcja nie robi

- nie przewiduje przyszłości i nie używa narysowanych scenariuszy jako danych;
- nie używa finalnego high/low/close tworzącego się H4/H8/D1/W1/MN1;
- nie zamienia rozpoznania formacji w zlecenie (decyzja: strategia → ryzyko → bramka → tryb);
- testy (`tests/test_patterns_walls.py`) to kontrola kodu na danych syntetycznych, **nie** dowód skuteczności.
