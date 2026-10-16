# TEST_REPORT – PepeMarketWizard 1.13.0 (2026-10-16)

## Środowisko
- Linux, Python 3.13, symulator terminala MT5 (dane syntetyczne), Chromium (Playwright) – `/opt/pw-browsers/chromium`.
- `.venv_candles` (izolowane środowisko prognoz/scalp) przez `MQ_CANDLES_PYTHON`.
- **Nie było:** Windows, Twojego terminala MT5, rzeczywistego rachunku, ticków brokera, sieci do `pip-audit` / `npm audit`.

## Polecenia
```
MQ_CANDLES_PYTHON=<.venv_candles>/bin/python python tools/run_tests.py     # pełny zestaw
cd tests && python -m unittest test_ui_signal_card test_app_process         # ponowny przebieg po poprawkach
cd frontend && npm run build                                                 # tsc + vite build
pyflakes backend/masterquo                                                   # bez uwag
```

## Wyniki
| Przebieg | Wynik |
|---|---|
| Pełny `run_tests.py` – testy bota | 378 testów: 376 OK, 1 FAIL, 1 ERROR (szczegóły niżej) |
| Pełny `run_tests.py` – `.venv_candles` | 46 OK |
| Ponowny przebieg `test_ui_signal_card` + `test_app_process` po poprawkach | 18 OK |
| Build frontendu (`tsc`, `vite build`) | OK |
| `pyflakes backend/masterquo` | bez uwag |

**Błędy pełnego przebiegu i przyczyny:**
1. `test_app_process.test_01_health_and_single_instance` – wykrywanie działającej instancji porównywało dosłowną starą nazwę (usterka A-05 w `AUDIT_REPORT.md`). Poprawka w `__main__.cmd_serve` została wprowadzona w trakcie pełnego przebiegu; po niej test przechodzi.
2. `test_ui_signal_card` (setUpClass) – test oczekiwał karty sygnału na stronie startowej, a w 1.13 stroną startową jest Pulpit. Test wchodzi teraz bezpośrednio na `#/ai`; zachowanie programu bez zmian.

## Nowe testy 1.13
- `tests/test_analytics.py` (24):
  - BB/MA – wartości wzorcowe, rozgrzewka, płaskie okno, zgodność z M02I i scalp, niezmienność prefiksu;
  - FFT/EMD/VMD – znane częstotliwości, rekonstrukcja, luki, TIMEOUT, czysty JSON;
  - Double Bottom – 4 statusy, pierwsze rozstrzygnięcie, przyczynowość, wersja EXT;
  - biblioteka – duplikaty, VALIDATE ALL = walidacja pojedyncza, anulowanie, import, ścieżka raportu;
  - integracja serwisu – odrzucenie spóźnionego wyniku, OBSERVE.
- `tests/test_ui_analytics.py` (4) – grupy menu, 12 stron, biblioteka formacji w przeglądarce, 1920/1366/390 px bez przewijania poziomego, brak żądań zmieniających tryb. Zrzuty w `data/logs/ui_analytics/`.

## Atrapy vs integracje
- MT5: wyłącznie symulator (`FakeMT5`). Brak dowodu połączenia z Twoim terminalem.
- Telegram, Claude API: bez wysyłki, bez klucza.
- Wykonanie zleceń: testy na atrapach; nie wysłano żadnego zlecenia do brokera.

## Niewykonane
- Testy na Windows i Twoim MT5 (`02_DIAGNOSTYKA.bat`, strona Diagnostyka).
- Trening i replay na rzeczywistej historii XAUUSD- (BLOCKED_NO_REAL_DATA).
- Audyt podatności zależności (brak sieci do `pip-audit` / `npm audit`).
