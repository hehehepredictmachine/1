# INTEGRATION_MAP – PepeMarketWizard 1.13 (rzeczywiste połączenia modułów)

**Uruchomienie:** `03_START_MASTERQUO.bat` → `masterquo_start.bat` → `python -m masterquo serve`.
- Serwer: FastAPI i uvicorn, wyłącznie na 127.0.0.1.
- Baza: SQLite w `data/`, migracje 0001–0013.
- Panel: React i Vite (`frontend/dist`). Transport: jeden WebSocket (`/api/v1/ws`) z migawką stanu i zdarzeniami oraz REST `/api/v1/*`.

## Moduły nowe i zmienione w 1.13

| Moduł | Wejście | Wynik | Odbiorcy w kodzie | Weryfikacja |
|---|---|---|---|---|
| `analytics/ta.py` (BB, SMA/EMA/WMA) | zamknięte świece z MarketBridge | kontrakt mq-analytics + linie wykresu | `engine/chartdata.py` (linie EMA/BB na wszystkich wykresach), `AnalyticsService` (Pulpit, Indykatory, Kontekst, wyjaśnienia), `analytics_snapshots` | `test_analytics.TestBBMA` (wartości wzorcowe, rozgrzewka, płaskie okno, zgodność z M02I i scalp, niezmienność prefiksu) |
| `analytics/signal.py` (FFT, EMD, VMD) | ciągłe okno zamkniętych świec | widmo, IMF, mody i jakość | `AnalyticsService` → wątek „analytics-heavy” → Analiza sygnału, karta „Co wspiera analizę”, archiwum | `test_analytics.TestSignal` (znane częstotliwości, rekonstrukcja, luki, płaski sygnał, TIMEOUT, czysty JSON) |
| `analytics/double_bottom.py` | świece próbki albo bieżące (causal) | status, współrzędne, pomiary, dostępność | skaner w `AnalyticsService` → `pattern_events` → Formacje; biblioteka; karta wyjaśnień | `TestDoubleBottom` (4 statusy, pierwsze rozstrzygnięcie, błąd danych ≠ FAILED, przyczynowość, wersja EXT) |
| `analytics/library.py` | próbki w DB, konfiguracja | zadania, wyniki, raporty JSON/CSV | API `/api/v1/patterns/*` → Formacje | `TestLibrary` (duplikaty, równość pojedynczej i zbiorczej, pusta kolekcja, usunięte, anulowanie, import, ścieżka raportu) |
| `analytics/service.py` | MarketBridge (`bars(tf, closed)`) | stan per TF, wyjaśnienia, diagnostyka | WS „analytics”, API `/api/v1/analytics*`, panel | `TestServiceIntegration` (odrzucenie spóźnionego wyniku, archiwum nienadpisywane, OBSERVE), `test_ui_analytics` |
| `scalp/*` (1.12) | MarketBridge M1–H1 | decyzje SHADOW, replay, trening | `scalp_shadow`, API `/api/v1/scalp*`, strona Testy i raporty | `test_scalp_core`, `test_scalp_train`, `test_ui_scalp` |
| Panel – nowe strony | API / WS | Pulpit, Kontekst, Indykatory, Analiza sygnału, Formacje, Pozycje, Dziennik, Testy, Diagnostyka | – | `test_ui_analytics` (render, 1920/1366/390 px, przepływ biblioteki), `test_ui_pages` |

## Przepływ główny – bez zmian

1. **Dane:** MT5 → `mt5/bridge.py`.
   - bufory TF, świeca otwarta osobno od zamkniętych;
   - czas serwera przeliczany na UTC zmierzonym offsetem;
   - reconnect z `session_epoch`.
2. **Silnik:** `engine/service.py`.
   - wejścia: M01 (jakość danych), M02/M02I (wskaźniki), M03 (struktura), strategie S01–S12 i AUTO;
   - wyjścia: `decision`, checklista, sygnał → WS.
3. **Wykonanie:** `risk/engine.py` → `execution/gateway.py`.
   - tryby SIGNALS / PAPER / AUTO_DEMO / AUTO_LIVE;
   - Execution Lock, `order_check` → `execution/manager.py`.
4. **Moduły obserwacyjne:** forecast (gold_candles), scalp (SHADOW) i analytics (OBSERVE).
   - **nie mają referencji** do gateway ani risk;
   - test sprawdza, że serwis scalp nie ma pola gateway;
   - analytics nie importuje modułów wykonania.

## Czego nowe moduły nie dotykają

Strategie S01–S12, reguły checklisty, ryzyko, wielkość pozycji, tryb wykonania, Execution Lock, konfiguracja brokera.
