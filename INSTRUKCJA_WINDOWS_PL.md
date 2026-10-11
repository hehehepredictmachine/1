# MasterQUO 1.9 – instrukcja dla Windows

Paczka: `MasterQUO_KLIENT_1_9_0.zip` – bot, monitor i launchery `.bat` dla komputera z MetaTrader 5.

**Od wersji 1.9 program nie wymaga licencji** – nie ma serwera licencji, klucza `MQL72-…` ani panelu administratora.
Uruchamiasz `masterquo_start.bat` (albo `03_START_MASTERQUO.bat`) i monitor otwiera się od razu.

---

## Bot MasterQUO

### B1. Instalacja lub aktualizacja

1. Rozpakuj `MasterQUO_KLIENT_1_9_0.zip` do **nowego** folderu, np. `C:\MasterQUO_AI_1_9`. Nie nadpisuj starej wersji:
   to jest Twój punkt powrotu.
2. Przy aktualizacji skopiuj ze starego folderu cały katalog `data\` (ustawienia, baza, zaszyfrowany klucz Claude).
   Stary folder zostaw bez zmian. Program przy migracji robi też kopię bazy w `data\backups\`.
3. Uruchom `01_INSTALUJ.bat` (tworzy `.venv`, instaluje pakiety z sumami SHA-256), a potem `02_DIAGNOSTYKA.bat`
   (sprawdza MT5, symbol `XAUUSD-`, czas; nie składa zleceń).

### B2. Start

1. Uruchom `masterquo_start.bat` (w tym oknie) albo `03_START_MASTERQUO.bat` (osobne okno „MasterQUO server”).
2. Monitor otwiera się pod `http://127.0.0.1:8765/`. Zamknięcie przeglądarki nie zatrzymuje programu.
3. Zatrzymanie: `04_STOP_MASTERQUO.bat` – kończy tylko procesy tego projektu. Otwarte pozycje NIE są zamykane,
   a ich SL/TP zostają na serwerze brokera.
4. Opcja `masterquo_start.bat --demo` uruchamia program na danych syntetycznych (symulator, osobna baza) – bez rachunku.

### B3. Tryby i bezpieczeństwo handlu

- Sygnał (także „POTWIERDZONY”) **nie jest** zgodą na automatyczne zlecenia. Zlecenia zależą od trybu wykonania
  (SIGNALS / PAPER / AUTO DEMO / AUTO LIVE) i limitów ryzyka.
- Strategia S11 (EMA20 Pullback 2.5R) ma domyślnie włączone tylko skanowanie, bez handlu.
- Symbol `XAUUSD-` nie jest automatycznie podmieniany. Rachunek „Zero” nie oznacza zerowych kosztów (prowizja za lot).
- Testy (`05_TESTY_OFFLINE.bat`) używają symulatora i nie łączą się z Twoim rachunkiem.

### B4. Weryfikacja strategii na Twoich danych (zalecane przed handlem S11)

```
cd backend
..\.venv\Scripts\python.exe -m masterquo export --from-utc 2025-01-01T00:00:00Z --to-utc 2026-06-01T00:00:00Z --out ..\data\export_xau --dst-model NY_CLOSE
cd ..
.venv\Scripts\python.exe tools\backtest_ema_pullback.py --csv data\export_xau --tf M30 --commission-lot-side <prowizja z terminala>
```

- `--dst-model NY_CLOSE` liczy offset czasu dla każdej świecy (zmiany czasu letniego). Gdy broker nie stosuje tej
  konwencji, eksport zakończy się komunikatem; użyj wtedy `UNIFORM`.
- Wyniki trafiają do `data\results\ema_pullback\…` i `RAPORT_WYNIKOW.md`.

### B5. Rollback klienta

Uruchom poprzednią wersję z jej własnego folderu (patrz B1, krok 1) i przywróć kopię `data\config.json`. Szczegóły:
`ROLLBACK.md`, punkt 7.

### Rozwiązywanie problemów

| Komunikat | Co zrobić |
|---|---|
| `Brak .venv - uruchom najpierw 01_INSTALUJ.bat` | Uruchom `01_INSTALUJ.bat` |
| `Brak Python 3.13/3.12` | `winget install -e --id Python.Python.3.13 --scope user`, potem ponownie `01_INSTALUJ.bat` |
| Monitor: „BRAK DANYCH” / MT5 niepołączony | Uruchom MetaTrader 5, zaloguj się, potem `02_DIAGNOSTYKA.bat` |
