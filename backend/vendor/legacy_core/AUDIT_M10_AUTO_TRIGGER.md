# M10A v1.1.0 — audyt i raport testów

Status: CANDIDATE / PENDING APPROVAL. Przeznaczenie: automatyczna interpretacja zdarzeń z zamkniętych świec MT5, tylko ANALYSIS_ONLY / READ_ONLY. Nie oznacza walidacji edge, forward DEMO ani autoryzacji brokera.

## Zakres wykonany

1. Wbudowano adapter `M10_AUTO_TRIGGER_CONFIRM.py` bez modyfikacji reduktora `M10_REFERENCE_ENGINE.py` i innych silników `vendor/`.
2. Warunki: jawny snapshot M01, pięć CORE M03E, kandydat M09, reguły poziomów z istniejącymi `evidence_id`, zamknięta świeca MT5, czas dostępności `available_at<=as_of`.
3. Rozdzielono development, qualification, arm, trigger i confirmation; jeden nowy bar umożliwia najwyżej jedno przejście. Po CORE_READY wymagana jest następna świeca. Invalidation jest analizowane pierwsze.
4. Każdy event jest przekazywany do oryginalnego reduktora M10. Wynik potwierdzenia jest przekazywany do oryginalnego decydenta M14; adapter nie wpisuje ręcznie LONG/SHORT.
5. SQLite `m10auto_policy` + `m10auto_ledger`: transakcyjny zapis, wersjonowany hash reguł, detekcja zmienionych już przetworzonych świec, idempotency po restarcie, blokada brakujących kolejnych barów.
6. Oddzielny nowy czytnik Windows i plik monitora; starszy skrypt pozostaje niezmieniony. Brak `order_send`, autoryzacji, screenshotów, zrzutów ekranu, OCR czy połączenia z Telegramem.
7. Tryb `ZERO_SPREAD` jest wyłącznie deklarowany: rzeczywiste Bid/Ask, prowizja, swap, poślizg nie są uznawane za zero.

## Testy rzeczywiście wykonane

| Zestaw | Przypadki | Wynik |
|---|---:|---|
| M10_AUTO_TRIGGER_TESTS | 53 | PASS |
| Poprzednie INTEGRATION_TESTS | 27 | PASS |
| Poprzednie BRIDGE_TESTS | 48 | PASS |
| Poprzednie M10_TESTS | 77 | PASS |
| M01 Contract + Continuous | 60 | PASS |
| M02 | 67 | PASS |
| M02I (bazowe + profile) | 133 | PASS |
| M03 | 64 | PASS |
| M09 | 89 | PASS |
| M14 | 61 | PASS |
| **Razem** | **679** | **PASS** |

Testy M10A obejmują m.in. LONG/SHORT, prawidłową kolejność zmian, restart, powtórzoną świecę, zmianę reguł, rewizję OHLC, konflikt M09, utratę świeżości, problem czasów, brak planu i niedozwolone użycie przykładowych danych. Test demonstracyjny generuje scenariusz `QUALIFIED -> ARMED -> TRIGGERED -> CONFIRMED`, z odpowiedzią M14 `LONG`, `execution_permission=BLOCKED` — jest to jedynie ruch syntetyczny.

## Otwarte ograniczenia i ryzyka

- Brak połączenia z prawdziwym terminalem użytkownika. Testy FakeMT5 i lokalna symulacja nie są testami MT5 DEMO.
- Reguły `close/high/low >/< level` są tylko małą, testowalną klasą detektorów. Nie zastępują kompletnej biblioteki triggerów SMC, MSS, BOS, FVG, stop hunt, VWAP itp. z zamrożonych planów M07; bez planu operacyjnego wynik oczekuje.
- `PASS_WITH_LIMITATIONS` audytu M01 jest ograniczoną kontrolą lokalną, nie certyfikacją danych brokerskich; brak rzeczywistego atestu M08/M11, kosztów transakcji i wykonawcy.
- Przy luce odczytu M10A nie odtwarza całej ścieżki barów. Wymaga ręcznego uzgodnienia kalendarza/brokera i ostrożnego wznowienia badania albo nowego setup_id.
- Stare silniki pozostają kandydatami; zachowanie ich na rozmaitych rzeczywistych konfiguracjach Windows i MT5 nie jest znane.
- Nie wykonano historycznego M06 OOS, walk-forward, Monte Carlo, forward DEMO ani analizy skuteczności.
- M14 `LONG/SHORT` oznacza potwierdzony setup analityczny w znanym horyzoncie, nie zalecenie automatycznego wejścia.

## Integracja do dalszych etapów

Po zatwierdzeniu M10A: M15 Live Monitor Communication dla zdarzeń M10A (EARLY/QUALIFIED/ARMED/TRIGGERED/CONFIRMED/INVALIDATED/EXPIRED) i wersjonowanego outboxu, następnie pełna integracja chronologicznych testów M06 oraz rzeczywiste testy forward DEMO. Cały czas NO AUTO TRADING.
