# Audyt MasterQUO 1.7 – sygnały, M30/H8, EMA20 Pullback, statystyki

Data: 2026-10-11. Zakres: kod w tym repozytorium (backend `backend/masterquo`, monitor `frontend`),
załączona strategia Pine „EMA20 Pullback + 2.5R” i instrukcja PDF.

Środowisko audytu to kontener Linux z symulatorem terminala (`mt5/fake.py`). **Nie było połączenia z Twoim terminalem MT5
ani z rachunkiem.** Nie złożono żadnego zlecenia. Strony TradingView i MQL5 były zablokowane przez proxy, więc Pine
**nie został skompilowany** w TradingView.

Statusy: **NAPRAWIONE** (zmiana w kodzie + test) · **ZMIENIONE ZACHOWANIE** · **OTWARTE** (opisane, nienaprawione, z powodem) · **OK** (sprawdzone, bez zmian).

## 1. Strategia EMA20 Pullback + 2.5R (plik Pine użytkownika)

- Oryginał: `backend/masterquo/strategies/pine/EMA20_Pullback_2.5R_ORIGINAL.pine` (sha256 `6c14dbd0…`, kopia 1:1).
- Poprawiony Pine v6: `…/EMA20_Pullback_2.5R_FIXED.pine` – **NIE skompilowany** (brak dostępu do TradingView); skompiluj
  go i porównaj na swoim wykresie.
- Python:
  - `ema_pullback_core.py`: `run_original` to replika z wadami, `run_fixed` to wersja poprawiona;
  - strategia S11: `s11_ema_pullback.py`;
  - backtester: `ema_pullback_backtest.py`, runner: `tools/backtest_ema_pullback.py`.

Numeracja jak w promptcie. Typ: **K** = błąd w kodzie, **W** = model wykonania, **H** = hipoteza poprawy strategii,
**P** = prezentacja i diagnostyka.

| # | Typ | Ustalenie (oryginał) | Skutek / dowód | Naprawa (FIXED Pine + `run_fixed` / S11) |
|---|---|---|---|---|
| 1 | K | `confirmLong/Short` używa `wasWaiting*` bez ponownego sprawdzenia `trendUp/Down`. | Wejście przeciw trendowi po przecięciu EMA. Na wspólnych świecach: 144 potwierdzeń oryginału wbrew trendowi (RAPORT_WYNIKOW). | Potwierdzenie wymaga ważnego trendu. Zmiana trendu daje stan UNIEWAŻNIONY przed oceną potwierdzenia. Test `test_ema_pullback` (granice/defekty). |
| 2 | K | Każde dotknięcie zeruje `barsWaiting*`. | Stary setup przedłużany ponownym dotknięciem (24 przypadki). | Setup otwiera tylko pierwsze dotknięcie (id = świeca dotknięcia). Kolejne dotknięcia w trakcie oczekiwania nie przedłużają ważności. |
| 3 | K | Migawka `wasWaiting` jest robiona przed wygaszeniem. | Możliwe potwierdzenie na świecy, na której upłynął limit. | Kolejność: unieważnienie → wygaśnięcie → potwierdzenie. Potwierdzenie dozwolone na świecach dotknięcie+1 … dotknięcie+N. `maxPullbackBars=0` = bez limitu. Granice w testach. |
| 4 | H | `low <= EMA·tol` / `high >= EMA/tol` jest jednostronne. Nie dowodzi kontaktu świecy ze strefą ani kierunku podejścia. | Dotknięciem jest też świeca daleko pod EMA. | Kandydat C1 `ZONE_ATR`: kontakt zakresu świecy ze strefą EMA±k·ATR, podejście z właściwej strony, maks. głębokość. Oceniony regułą promocji ustaloną przed testem – **nie spełnił jej** na danych syntetycznych, więc domyślnie wyłączony. |
| 5 | H | `close > EMA` nie wymaga powrotu z właściwej strony. | Potwierdzenie bez faktycznego odzyskania poziomu. | Kandydat C2 `RECLAIM`: poprzednie zamknięcie po drugiej stronie, bieżące z powrotem. **Nie spełnił** reguły promocji (blisko progu), więc wyłączony. Crossover nie jest dodawany automatycznie. |
| 6 | K | Dotknięcie i potwierdzenie na jednej świecy. | W oryginale zablokowane migawką. W FIXED zachowane jawnie. | `bar_index > touchBar`. Decyzja tylko na zamkniętej świecy. Dotknięcie na świecy tworzącej się to podgląd (EARLY, `TOUCH_ON_FORMING_BAR_PREVIEW`). |
| 7 | K | `ta.lowest/ta.highest` wewnątrz bloków `if`. | Niespójna historia serii (ostrzeżenie Pine), błędny SL. | Liczone na każdej świecy. Warm-up `3·EMA50`. Te same okna w Pythonie. |
| 8 | W | `entryPrice = close` traktowane jak wykonanie. Wejście następuje na otwarciu kolejnej świecy + poślizg. | RR ≠ 2,5, SL/TP niezgodne z fill. | Cena sygnału, planowane wejście i fill są rozdzielone. TP przeliczany z fill (`position_avg_price`; w S11 i kontrakcie sygnału od Ask/Bid). Backtester MT5: wejście po Ask/Bid następnej świecy, luki. |
| 9 | W | `f_positionSize` = kwota / dystans ceny, bez `pointvalue`, waluty i kroku. | Ryzyko w pieniądzu ≠ 1%. | Pine: `syminfo.pointvalue`, krok w dół, minimum. MT5: strata do SL z `order_calc_profit` w walucie rachunku + koszty (risk engine, `tests/test_risk_execution.py`). |
| 10 | K/W | NaN, niepełna historia, zero ATR, zły SL, min/max/step wolumenu, margin, stops/freeze level. | Wejście z nieprawidłowymi danymi albo ryzykiem. | Brak danych lub warm-up daje brak kwalifikacji z powodem. Wolumen w dół do kroku. Minimalny lot ponad budżet ryzyka oznacza odrzucenie (nigdy zwiększenie ryzyka). Margin i stops level w risk engine. |
| 11 | W | `allowOnlyOnePosition`, pyramiding, odwracanie przez `strategy.entry`, cooldown. | Przy `false` sygnał przeciwny odwraca pozycję. „Entries” liczy zlecenia, nie fille. Cooldown liczony od zlecenia. | Jedna pozycja. Cooldown od **wypełnienia**. Osobne liczniki: zlecenia, fille, blokady. |
| 12 | K | Potwierdzony setup zablokowany przez pozycję lub cooldown. | Niejasne, czy może zostać wykonany później. | Setup jest **zużyty** (nigdy wykonywany z opóźnieniem). W bocie sygnał ma TTL, a po restarcie ma status WYGASŁY. |
| 13 | W | Prowizja 0,02% wartości, slippage 3 ticki, brak spreadu. | Przy ok. 2400 USD daje to ok. 48 USD/lot/stronę vs ok. 3,5 USD u brokera (koszty: 2237 vs 200 w raporcie). SHORT bez spreadu. | Model MT5: prowizja za lot, spread (SHORT zatrzymywany po Ask), poślizg w tickach. Oba modele w raporcie. Jednostki rozdzielone: punkty, ticki, cena, waluta. |
| 14 | P | Etykiety `#.##`. Diagnostyka bez wygaśnięć, unieważnień, blokad i filli. Deklaracja „42,86% / PF 1,52” bez okresu, kosztów i liczby transakcji. | Zła precyzja instrumentu. Lejek nie pokazuje przyczyn. Wynik niemożliwy do odtworzenia. | `format.mintick`. Tabela: dotknięcia, potwierdzenia, wygasłe, unieważnione, zablokowane (filtr/pozycja/cooldown), zlecenia, fille, trend H8. Deklaracja oznaczona jako **niezweryfikowana**. |

Pozostałe uwagi:

- Instrukcja PDF jest wewnętrznie sprzeczna: Krok 3 mówi o świecy następnej, a kod Pine dopuszcza potwierdzenie na
  późniejszej świecy. Przyjęto regułę z kodu: potwierdzenie na świecy późniejszej niż dotknięcie.
- Opcje „dzienny limit transakcji” i „zamknięcie przed weekendem” z PDF nie istnieją w Pine i nie zostały dodane.
  Dodanie ich zmieniłoby strategię bez danych do oceny.

Wyniki: `RAPORT_WYNIKOW.md`. Uruchomienie było na **danych syntetycznych** symulatora, bo w repozytorium nie ma historii
XAUUSD- z Twojego terminala. Raport nie jest dowodem przewagi strategii. Instrukcja uruchomienia na Twoich danych jest w
raporcie i w `INSTRUKCJA_WINDOWS_PL.md`.

**S11 w bocie:**

- `scan=True`, `trade=False` domyślnie (`registry.DEFAULT_NO_TRADE`): sygnały i monitor działają, automatyczne wykonanie
  jest wyłączone do czasu walidacji na Twoich danych.
- Status walidacji: `FUNCTIONAL_ONLY_OOS_NOT_RUN`.

## 2. Interwały M30 i H8

| Obszar | Stan |
|---|---|
| Rejestr TF (`timeutil.TF_REGISTRY`): sekundy, stała MT5, kod Pine, rola, `core` | NAPRAWIONE – jedno źródło dla bridge, silnika, skanera, agenta, eksportu |
| MT5: natywne `TIMEFRAME_M30`/`TIMEFRAME_H8` | NAPRAWIONE. Gdy H8 jest pusty, kontrolowany resampling z H1 (kubełki dnia serwera), oznaczony `source=resampled`, `parts` |
| Brak H8 przy włączonym filtrze H8 | `BRAK_DANYCH_H8`. Potwierdzenie jest blokowane, filtr nigdy nie jest „przepuszczany” |
| Lookahead | Trend H8 tylko z **zamkniętych** świec (as-of join po czasie zamknięcia). Pine: `expr[1]` + `lookahead_on`. Testy w `test_ema_pullback.py` |
| Świeca otwarta vs zamknięta | Monitor pokazuje oddzielnie. Dotknięcie na świecy tworzącej się to tylko podgląd (faza EARLY), nigdy potwierdzenie |
| Jakość danych | Bramka analizy liczy się tylko z TF podstawowych. M30/H8 mają statusy kontekstowe (`CONTEXT_M30_*`) i nie blokują całego silnika |
| Monitor | Karta „Kontekst M30 / H8” (źródło, czas, otwarta/zamknięta, kierunek, reżim, poziomy, wpływ), układ 8 wykresów, panel 4: M30/H8 |
| Eksport historii | NAPRAWIONE: 8 TF. Pliki M30/H8 są w `context_files` manifestu, bo niezmieniony loader M06R wymaga dokładnie 6 TF |
| Agent AI | Narzędzia przyjmują wszystkie 8 TF z rejestru |
| ML | OTWARTE: schemat cech `MQ-FEAT-1.0.0` nie ma kategorii S11 ani M30 (one-hot = zera). Zmiana schematu unieważnia wytrenowane modele, więc wymaga nowej wersji schematu i ponownego treningu na Twoich danych |

## 3. Sygnały – kontrakt `MQ-SIGNAL-1.0.0`

- `engine/signal_contract.py`, testy w `tests/test_signal_contract.py`.
- Statusy sygnału: OCZEKIWANIE / POTWIERDZONY / ZABLOKOWANY / UNIEWAŻNIONY / WYGASŁY / BRAK_DANYCH.
- `execution_state` jest osobno: BRAK / WYSŁANO / WYKONANO / ODRZUCONO.
- Ceny:
  - planowane wejście z Ask (LONG) lub Bid (SHORT);
  - `fill_price` = null do czasu potwierdzonego wypełnienia;
  - poziomy niespójne z bieżącą ceną dają ZABLOKOWANY (`LEVELS_INCONSISTENT_WITH_LIVE_PRICE`).
- Źródło: STRATEGIA albo STRATEGIA + AI. Etykieta AI pojawia się tylko przy **aktualnej** ocenie tego samego stanu setupu.
  Spóźniona odpowiedź (inny `state_changed_at`) ma status NIEAKTUALNA i nie nadpisuje nowszego stanu.
- Bez klucza status to `AI_NIEDOSTEPNE`.
- Prawdopodobieństwo jest pokazywane tylko z modelu ML w stanie READY, ze skalibrowanym wynikiem. W każdym innym
  przypadku pole jest puste (`null`).
- TTL: po `valid_until` status to WYGASŁY. Po restarcie wcześniejsze sygnały są oznaczane jako wygasłe.
- Wartość filtra AI jest mierzona osobno (ZGODA / BRAK_ZGODY / BRAK_OCENY w historii sygnałów). Wynik strategii nie jest
  mieszany z oceną AI.

## 4. Statystyki – jednolite definicje

| Problem | Status |
|---|---|
| Winrate bota liczony jako wygrane / wszystkie, więc breakeven obniżał winrate | NAPRAWIONE: wygrane / (wygrane + przegrane) po kosztach. BE (\|R\| ≤ 0,05) osobno |
| PF przy braku strat = puste pole bez wyjaśnienia | NAPRAWIONE: `BRAK_STRAT` (nie nieskończoność) |
| Brak oczekiwanej wartości w R | NAPRAWIONE: `expectancy_r` |
| ROI a wpłaty/wypłaty | Operacje balance są wykazywane osobno (nie są zyskiem). NAPRAWIONE w 1.8: ROI rachunku MT5 metodą Dietza z zapisanych snapshotów equity (`stats.account_roi`), wpłaty/wypłaty jako przepływy; bez danych – „brak danych” |
| Statystyki sygnałów (wszystkie rynki) | ZMIENIONE: oznaczone jako BRUTTO w R (bez spreadu i prowizji), BE osobno, PF w R |
| Backtester EMA | Te same definicje. Bootstrap blokowy (90% CI). Liczba testowanych wariantów jest jawna (ryzyko przeuczenia) |

Testy: `tests/test_stats_definitions.py`.

## 5. Dane, czas, wykonanie

| Obszar | Stan |
|---|---|
| Symbol `XAUUSD-` | OK – dokładna nazwa, bez automatycznej podmiany (test `test_no_wrong_default_symbol_in_active_code`) |
| Rachunek „Zero” | OK – koszty nie są zerowe (prowizja za lot, spread rzeczywisty, stres poślizgu) |
| Eksport historii a DST | NAPRAWIONE: `--dst-model NY_CLOSE` liczy offset per świeca (Nowy Jork + 7 h). Jest odrzucany, gdy nie zgadza się z offsetem zmierzonym dziś. Każdy wiersz ma `time_server_raw` i `offset_seconds`. UNIFORM ma ograniczenie zapisane w manifeście |
| Limit spreadu | OK – `risk.max_spread_points` w punktach, porównywany z `spread_points` kwotowania |
| Idempotencja zleceń | OK – `entry_key = tryb:rachunek:setup` (unikalny). Timeout daje UNKNOWN bez ponowienia, potem rekonsyliacja |
| TP dla S11 | NAPRAWIONE: przeliczany z planowanej ceny wejścia (Ask/Bid) |
| Tryby | OK – sygnał nie daje zgody na auto-handel. Wykonanie zależy od trybu i limitów. Testy nie wysyłają realnych zleceń |
| Checklista | NAPRAWIONE: kody kierunku (LONG:/SHORT:) tłumaczone na polski |
| Nieaktualne testy (wersja configu 6, 10 strategii) | NAPRAWIONE: oczekiwania 8 / 11 |

## 6. Licencje – wycofane w 1.9.0

Na prośbę użytkownika licencjonowanie z 1.7–1.8 zostało w całości usunięte: serwer `server/mqlicense`, panel administratora,
moduł klienta `backend/masterquo/license`, pytanie o klucz w `masterquo_start`, blokady silnika/skanera/sygnałów/ML/agenta/zleceń/API/WS
i plansza w monitorze. Pakiety `cryptography`/`pyjwt` usunięto z wymagań. Istniejący `data\config.json` (v8) migruje do v9 – sekcja
`license` jest usuwana, pozostałe ustawienia bez zmian. Wszystkie pozostałe funkcje (sygnały, M30/H8, S11, karta sygnału, wybór setupu,
dźwignia, ROI) działają jak w 1.8.

## 7. Testy

- Pełny zestaw: `python tools/run_tests.py` (Windows: `05_TESTY_OFFLINE.bat`).
- Raport: `RAPORT_TESTOW.md` i `data/logs/testy_offline_*.json`.
- Mapowanie scenariuszy 1–12 z promptu na testy: `RAPORT_TESTOW.md`, sekcja 1.7.
