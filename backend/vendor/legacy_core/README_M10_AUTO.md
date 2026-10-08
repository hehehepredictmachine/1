# MasterQUO M10 Automatic Trigger & Confirmation v1.1.0 — CANDIDATE

Ta paczka zawiera poprzedni, niezmieniony most MT5 M01/M02/M02I/M03E/M09/M10/M14 **oraz nowy adapter M10A**. Adapter nie wykonuje transakcji ani nie deklaruje, że przykładowe warunki to zwalidowana strategia.

## Uruchomienie na Windows

1. Uruchom terminal MetaTrader 5 na koncie DEMO i włącz symbol XAUUSD (lub sprawdź jego nazwę u brokera).
2. W PowerShell, z folderu paczki: `py -3 -m pip install MetaTrader5 numpy`.
3. Podgląd bez strategii: `py -3 RUN_MT5_AUTOMATIC_TRIGGER_READONLY.py --symbol XAUUSD`.
4. Po uzyskaniu **rzeczywistych identyfikatorów dowodów M02/M03**, przygotowaniu kompletnej i zamrożonej w M07 definicji oraz usunięciu markerów testowych z własnej konfiguracji: `py -3 RUN_MT5_AUTOMATIC_TRIGGER_READONLY.py --symbol XAUUSD --strategy-plan MOJA_ZWERYFIKOWANA_STRATEGIA.json`.
5. `START_MT5_AUTOMATIC_TRIGGER_READONLY.bat` uruchamia wariant bez strategii, wyłącznie diagnostyczny. Zatrzymanie przez Ctrl+C.

Wyniki monitorowania są zapisywane do `runtime/MASTERQUO_M10_AUTO_TRIGGER_MONITOR.json`, surowy odczyt do `runtime/MT5_RAW_DIAGNOSTIC.json`, a historia do `runtime/M10_STATE.sqlite`. Program pozostaje uruchomiony jedynie wtedy, gdy proces działa na Twoim komputerze; nie uruchamia się w tle w ChatGPT.

**Przykładowe poziomy w `LIFECYCLE_RULES.example.json` są syntetyczne** i mają `example_only:true` oraz fałszywe `evidence_id`, więc nie włączą rzeczywistego sygnału. Aby testować prawdziwe strategie, potrzebujesz wypełnionych planów M07, faktycznych dowodów M02/M03 i oddzielnej walidacji M06.

## Charakter sygnałów

M10A obserwuje osobne, prawidłowo uporządkowane przejścia na **nowych zamkniętych świecach**. Pojawiający się `CONFIRMED` opisuje wyłącznie potwierdzenie logicznego setupu, nie przewagę statystyczną. Wskaźniki M02I są kontekstem; nie zastępują 5 CORE M03E. Wszystkie zlecenia są blokowane, nie ma funkcji order_send ani screenshotów.

Przerwy sesyjne, brak danych, brak nowych świec, luki w historii, konflikt horyzontów, utrata połączenia i nieciągłość procesu skutkują wstrzymaniem nowych potwierdzeń. Po nierozliczonej luce wymagana jest diagnostyka danych/ponowne przygotowanie procesu; adapter nie odtwarza fikcyjnych stanów rynku.

## Testy

`py -3 -m pip install numpy` (na Windows). `py -3 RUN_ALL_OFFLINE_TESTS.py` uruchamia nowe testy i regresję zachowanych silników. Zestaw używa danych syntetycznych / FakeMT5; nie wysyła zleceń. Wynik PASS nie oznacza rentowności ani zatwierdzenia LIVE.

## Pliki dodane

- `M10_AUTO_TRIGGER_CONFIRM.py` — odczyt reguł, kontrola dostępności świecy, przejścia i dziennik transakcyjny SQLite.
- `RUN_MT5_AUTOMATIC_TRIGGER_READONLY.py` — pętla odczytu MT5 i nowy eksport monitora.
- `M10_AUTO_TRIGGER_TESTS.py` — testy offline LONG/SHORT, replay/restart, M14, priorytety unieważnienia i schematy dowodowe.
- `LIFECYCLE_RULES.example.json` — **wyłącznie ilustracyjny, nieoperacyjny** szablon.
- `M10_AUTO_TRIGGER_CONFIRM_v1.1.0_CANDIDATE.txt` — pełny moduł prompta.
- `M10_AUTO_TRIGGER_INTEGRATION_CONTRACT.md` — kontrakt techniczny.
- `AUDIT_M10_AUTO_TRIGGER.md` — wyniki testów i ograniczenia.

Pozostałe pliki są zachowanym niezmienionym mostem ze wcześniejszego etapu. Nie jest to finalna integracja całego MasterQUO.
