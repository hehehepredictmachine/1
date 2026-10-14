# gold_candles – integracja i trening XAUUSD-: stan i blokady (2026-10-14)

**Status: BLOCKED.** Nie wykonano żadnego treningu, nie zapisano żadnego modelu i nie uruchomiono prognoz SHADOW.
Szczegóły maszynowe: `TRAINING_STATUS.json`.

## Blokada 1 – brak pakietu `gold_candles` (BLOCKED_NO_PACKAGE)
Zadanie wymaga archiwum `MasterQUO_XAUUSD_CANDLES_FORECAST_v2.zip` (katalog `MasterQUO_Candles_v2`). Udostępniono tylko trzy dokumenty
(`CLAUDE_CODE_MASTERQUO_INTEGRACJA_TRENING.md`, `MasterQUO_XAUUSD_EXECUTION_LOCK_v2_PROMPT.md`, `MasterQUO_AUDYT_SCALPING_v2.md`).
Przeszukano katalog uploadów i cały system plików – modułu nie ma. Nie odtwarzam go „z opisu”: `Config.contract_hash()` obejmuje dokładną
treść `data.py`, `patterns.py`, `features.py`, `model.py`, więc własna kopia nie byłaby modułem referencyjnym, a jej modele nie byłyby zgodne.

**Co odblokowuje:** wgranie `MasterQUO_XAUUSD_CANDLES_FORECAST_v2.zip` do tej sesji.

## Blokada 2 – brak rzeczywistej historii XAUUSD- (BLOCKED_NO_REAL_DATA)
To środowisko to kontener Linux w chmurze: brak pakietu `MetaTrader5`, brak dostępu do Twojego terminala. W repozytorium są wyłącznie
dane syntetyczne – zgodnie ze specyfikacją nie mogą służyć jako historia finansowa, więc trening syntetyczny nie został uruchomiony.

**Co odblokowuje (jedno z dwóch):**
1. Eksport na Twoim Windows istniejącym poleceniem bota (już działa, czyta zamknięte świece, zapisuje manifest):
   ```
   cd backend
   ..\.venv\Scripts\python.exe -m masterquo export --from-utc 2026-01-01T00:00:00Z --to-utc 2026-10-14T00:00:00Z --out ..\data\export_xau --dst-model NY_CLOSE
   ```
   i wgranie tutaj plików `data\export_xau\M5.csv`, `M30.csv` oraz manifestu (bez `data\config.json` i sekretów);
2. albo uruchomienie całego procesu lokalnie w Claude Code na Windows, gdzie terminal jest dostępny.

## Rozbieżność do rozstrzygnięcia przed treningiem – czas świec MT5
Dokumenty v2 zakładają, że `copy_rates_*` zwraca epoch UTC i zabraniają dodawania offsetu. Bot (od wersji „FUTURE_CANDLE_TIME_FIX”)
traktuje czas świec jako czas serwera brokera i przelicza go zmierzonym offsetem (`mt5/clock.py`, `diagnostics.export_history`),
bo u brokera użytkownika świece „z przyszłości” pojawiały się właśnie przy założeniu UTC. Integracja musi używać jednej konwencji
w eksporcie, treningu i inference; zostanie sprawdzona na rzeczywistym eksporcie (porównanie czasu ostatniej świecy z czasem ticka i UTC).

## Co jest gotowe w bocie i zostanie użyte po odblokowaniu
* zamknięte M5/M30 `XAUUSD-` ze wspólnej sesji MT5 (`mt5/bridge.py`) – adapter nie będzie wywoływał `initialize()/shutdown()`;
* eksport historii z manifestem (`python -m masterquo export`);
* monitor z trzema stronami – miejsce na sekcję „Świece i prognozy” (tryb SHADOW, bez zgody na zlecenia);
* istniejąca ochrona: tryby wykonania, Execution Lock bota, `ML_EXECUTION` wyłączone.
