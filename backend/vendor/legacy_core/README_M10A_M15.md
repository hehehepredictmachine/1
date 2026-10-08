# MasterQUO M10A → M15 v1.0.0 — read-only integration candidate

## Co zostało zintegrowane

Nowy uruchamiacz **`RUN_MT5_M10A_M15_READONLY.py`** wywołuje zachowany silnik MT5 (M01/M02/M02I/M03E/M09/M10A/M14), wiąże jego wynik z rzeczywistą migawką pochodzącą z tej samej instancji terminala, a następnie publikuje wyniki przy użyciu **niezmienionego kodu M15** z `vendor/M15`. Dodano tylko warstwę adaptera i uruchamiacza. Wersje poprzednich silników nie zostały nadpisane.

**Charakter systemu:** lokalna diagnostyka/analityka XAUUSD. Nie ma wysyłania zleceń, `order_send`, autoryzacji LIVE, screenshotów ani OCR. Przykładowe poziomy i wszystkie testy używają danych syntetycznych. Żaden z modułów nie gwarantuje zarobku ani nie został przetestowany na rzeczywistym rachunku użytkownika.

## Windows — start

1. Uruchom i zaloguj się do **MetaTrader 5** na koncie DEMO. Włącz widoczność symbolu złota u brokera, np. `XAUUSD` lub `XAUUSDm`.
2. Rozpakuj ZIP do nowego katalogu. Otwórz PowerShell w tym katalogu i zainstaluj `py -3 -m pip install MetaTrader5 numpy`.
3. Uruchom: `py -3 RUN_MT5_M10A_M15_READONLY.py --symbol XAUUSD`. Możesz też użyć `START_MT5_M10A_M15_READONLY.bat`.
4. W drugim oknie otwórz: `py -3 M15_SIGNAL_VIEWER.py`, ewentualnie `START_M15_VIEWER.bat`.
5. Aby załadować własną, rzeczywiście zamrożoną i operacyjnie zdefiniowaną strategię: `py -3 RUN_MT5_M10A_M15_READONLY.py --symbol XAUUSD --strategy-plan MOJA_STRATEGIA.json`. Wskazane w niej `evidence_id`, warunki i wersja muszą zgadzać się z bieżącymi danymi M02/M03. Przykładowe pliki ze sztucznymi poziomami **nie są strategią do handlu**.
6. Opcjonalne DXY: użyj argumentu `--dxy-symbol` z dokładną nazwą instrumentu, jeśli jest udostępniany w terminalu. Brak DXY nie zatrzymuje niezależnej analizy XAUUSD.

Program aktualizuje `runtime/M15/M15_MONITOR_SNAPSHOT.json`, `M15_EXPORT_FULL.json`, `M15_COMPACT_PL.txt`, `M15_FULL_PL.txt`, `M15_LAST_DELIVERY_STATUS.json` oraz `runtime/M10_STATE.sqlite`. Zmiany setupów (jeśli M03E wykryje komplet CORE i strategia ma jawne reguły) zapisują się w SQLite. Zatrzymaj Ctrl+C. Podgląd ma zegar żywotności: raport starszy niż **15 sekund** jest pokazywany jako nieaktualny, nie jako bieżący sygnał.

## Telegram — jawna opcja

Domyślnie **NIE MA WYSYŁKI**. Jeśli świadomie chcesz włączyć wyłącznie alerty analityczne:

```powershell
$env:TELEGRAM_BOT_TOKEN = "TOKEN_TWOJEGO_BOTA"
$env:TELEGRAM_CHAT_ID = "TWOJ_CHAT_ID"
py -3 RUN_MT5_M10A_M15_READONLY.py --symbol XAUUSD --strategy-plan MOJA_STRATEGIA.json --telegram-send
```

Nie zapisuj tokenów w plikach JSON, kodzie ani paczce ZIP; umieść je w zmiennych środowiskowych na własnym komputerze. `--telegram-send` **nie włącza handlu**. M15 wyśle tylko rzeczywiste przejście M10 z akceptowalną analizą M14, nie każdy tick. Alerty dla testowych `analysis_id` zostają zablokowane. Powtarzanie tego samego zdarzenia po restarcie jest blokowane przez SQLite. Przy niepewnym wyniku API Telegram status zostaje `UNKNOWN` i nie ma automatycznego retry (żeby nie powielić wiadomości). Brak tokenów daje `QUEUED_MISSING_ENV`; taki sam identyfikator zdarzenia nie będzie automatycznie próbowany ponownie po naprawie ustawień.

**Uwaga:** to kanał zewnętrzny, który może pokazać kierunek i cenę. Przed włączeniem dobierz uprawnienia i prywatność grupy Telegram. System nie może potwierdzić dostarczenia alertu bez odpowiedzi API.

## Weryfikacja i ograniczenia

`py -3 -m unittest M10A_M15_TESTS -q` sprawdza nowy adapter. `py -3 RUN_ALL_M10A_M15_TESTS.py` sprawdza również M15 i zachowane moduły. Testy są offline, korzystają z atrap MT5 i Telegram. W szczególności M01 jest lokalnym audytorem **PASS_WITH_LIMITATIONS**, a nie ukończoną certyfikacją brokerowej historii oraz sesji. M11, M06, M08 i produkcyjne uprawnienia M14 nie są integrowane w adapterze. Warstwa M15 celowo utrzymuje `execution_permission=BLOCKED` we wszystkich wynikach.

Zachowany profil Twojego rachunku MT5: **ZERO_SPREAD_DECLARED_UNVERIFIED**. Spread Bid–Ask może wynosić 0, ale rzeczywiste prowizje, swap, poślizg i inne koszty wciąż wymagają ustalenia na podstawie MT5; M15 nie zgaduje wyniku netto ani wielkości pozycji.

## Status

**v1.0.0-CANDIDATE / PENDING APPROVAL**. To samodzielna integracja M10A → M15, nie finalna wersja całego MasterQUO. Przed użyciem wyników handlowych konieczne są audyt brokera/MT5, operacyjne specyfikacje strategii, OOS i forward DEMO oraz kontrola dostarczenia Telegram na własnym środowisku.
