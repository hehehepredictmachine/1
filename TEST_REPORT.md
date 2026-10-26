# TEST_REPORT – PepeMarketWizard 1.14.0 (2026-10-17)

## Środowisko
- Linux, Python 3.13, symulator terminala MT5 (dane syntetyczne, `MQ_FAKE_MARKET_ALWAYS_OPEN=1`), Chromium (Playwright).
- `.venv_candles` przez zmienną `MQ_CANDLES_PYTHON`.
- **Nie było:** Windows, Twojego MT5, rachunku, prawdziwych ticków, sieci do mql5.com i arxiv, ani `pip-audit` / `npm audit`.

## Wyniki
| Przebieg | Wynik |
|---|---|
| Pełny `tools/run_tests.py` (po poprawkach) | **427 testów bota OK + 46 testów `.venv_candles` OK** (`data/logs/testy_offline_20261017T160055Z.json`) |
| Pierwszy pełny przebieg 1.14 | 427: 5 FAIL + 1 ERROR – naprawione, opis niżej |
| Build frontendu (`tsc` + `vite build`) | OK |
| `pyflakes backend/masterquo/lab backend/masterquo/assets` | bez uwag |

**Błędy pierwszego przebiegu:**
1. **`is_fake()` nie rozpoznawał symulatora za proxy Execution Lock.** Dane syntetyczne były oznaczane jako MT5. To realna usterka – naprawiona.
2. **Testy migracji oczekiwały `config_version` 10.** Teraz jest 11 – testy zaktualizowane.
3. **Test bramki dźwigni dostawał `EXECUTION_LOCKED`.** Test mechaniki zleceń na atrapie odblokowuje teraz blokadę jawnie.
4. **Test skanera rynków zakładał EURUSD- i inne symbole.** Nowe zasady: tylko XAUUSD- i potwierdzony BTCUSD-, a EURUSD- zwraca 403.

## Nowe testy 1.14
- **`tests/test_lab.py` (35):**
  - blokada symboli w danych, skanerze, mapowaniu, treningu i konfiguracji;
  - metadane XAUT, WBTC i BTCUSDT; fingerprint kontraktu; Execution Lock w workerze i trybach; Trade Pad;
  - przyczynowość (niezmienność prefiksu cech i modułów, pivoty `confirmed_at`, PDH tylko z zamkniętego dnia);
  - multi-TF: zamknięcie H1 nie trafia do decyzji M5; Memory Sequence; DST sesji;
  - ACD (polityka przerw), kinematyka, ticki bez duplikatów; archiwum Fouriera;
  - strefy: uszkodzony snapshot → .bak bez duplikatów, ręczne strefy UNRATED;
  - bootstrap, drift, repaint;
  - sieci: sprawdzenie gradientu, tożsamość SEW, streaming = replay, brak aktualizacji w inferencji;
  - MiniRocket: fit tylko na treningu;
  - protokół: purging, GMM tylko w treningu, INSUFFICIENT_EVIDENCE, holdout jeden raz, artefakt (ponowne wczytanie, złe aktywo lub schemat, suma kontrolna), etykiety;
  - end-to-end XAUUSD → BTC.
- **`tests/test_ui_lab.py` (5):**
  - 7 sekcji; „Sieć nieaktywna” bez artefaktu;
  - blokady w backendzie (Trade Pad execute 403, odblokowanie bez frazy 403, obejście przez `PUT /config` 400, `DOGE`/`EURUSD-` 403);
  - telemetria z tej samej inferencji i raster SNN; macierz 42 pozycji;
  - przełączenie na BTC: wszystkie strony podążają, brak modelu XAUUSD dla BTC;
  - 390 px. Zrzuty w `data/logs/ui_lab/`.

## Atrapy vs integracje
- MT5 to wyłącznie symulator. Ticki są syntetyczne (deterministyczne z minut M1).
- Nie wysłano żadnego zlecenia: Execution Lock był aktywny we wszystkich testach poza testami mechaniki zleceń na atrapie.

## Niewykonane
- Test brokera: Twój MT5, metadane `XAUUSD-`, kontrakt BTC, `copy_ticks_from` na żywo.
  Do uruchomienia u Ciebie: `02_DIAGNOSTYKA.bat`, a potem Ustawienia → Aktywa → Szukaj kandydatów.
- Badania na prawdziwych danych (BLOCKED_NO_REAL_DATA).
- Audyt podatności zależności.

---

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
1. `test_app_process.test_01_health_and_single_instance` – wykrywanie działającej instancji porównywało dosłowną starą nazwę (usterka A-05 w `docs/archiwum/AUDIT_REPORT.md`). Poprawka w `__main__.cmd_serve` została wprowadzona w trakcie pełnego przebiegu; po niej test przechodzi.
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
