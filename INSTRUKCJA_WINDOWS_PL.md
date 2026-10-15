# MasterQUO 1.10 – instrukcja dla Windows

Paczka: `MasterQUO_KLIENT_1_11_0.zip` – bot, monitor i launchery `.bat` dla komputera z MetaTrader 5.

**Od wersji 1.9 program nie wymaga licencji** – nie ma serwera licencji, klucza `MQL72-…` ani panelu administratora.
Uruchamiasz `masterquo_start.bat` (albo `03_START_MASTERQUO.bat`) i monitor otwiera się od razu.

---

## Bot MasterQUO

### B1. Instalacja lub aktualizacja

1. Rozpakuj `MasterQUO_KLIENT_1_11_0.zip` do **nowego** folderu, np. `C:\MasterQUO_AI_1_10`. Nie nadpisuj starej wersji:
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
5. Monitor ma trzy strony (menu po lewej, na telefonie przyciski na dole): **Analiza AI** (`#/ai`), **Wykresy bota** (`#/wykresy`),
   **Warunki setupu** (`#/warunki/...`). Działają Wstecz/Dalej, zakładki przeglądarki i odświeżanie. Przeglądanie stron nie zmienia
   trybu handlu, strategii silnika ani dźwigni i nie wysyła płatnych zapytań do AI. Opis: `START_TUTAJ_PL.md`.

### B2c. Scalp M5 Range → M1 Sweep → Retest + hedge + ML/NN (SHADOW)

1. Wpisz prowizję rachunku (za 1 lot na stronę) w `data\config.json`: `"scalp": {"commission_per_lot_side": 3.5}` – bez tego bramka kosztów blokuje READY_SHADOW.
2. `16_EKSPORT_HISTORII_SCALP.bat 6` – MT5 uruchomiony i zalogowany; wynik w `data\scalp\history\` (+ `DATA_QUALITY_REPORT.json`).
3. `19_REPLAY_SCALP.bat 3.5` – replay po kosztach; `17_TRENING_SCALP_ML.bat 3.5` – trening (osobny proces, `.venv_candles` z `10_PROGNOZY_INSTALUJ.bat`).
4. `18_WALIDACJA_SCALP.bat`, `20_START_SCALP_SHADOW.bat`; rollback `21_ROLLBACK_MODELU_SCALP.bat` (lub `… BRAK`). Wyłączenie: `"scalp": {"enabled": false}`.

### B2b. Prognozy świec 5/15/30 min (SHADOW)

1. `10_PROGNOZY_INSTALUJ.bat` – tworzy `.venv_candles` (pakiety z hashami) i uruchamia testy modułu.
2. `11_EKSPORT_HISTORII_XAUUSD.bat` (opcjonalnie liczba miesięcy, np. `6`) – MT5 musi być uruchomiony i zalogowany; wynik w `data\forecast\history\`.
   Sprawdź w `DATA_QUALITY_REPORT.json` liczbę dni handlowych – terminal może zwrócić krótszą historię (Narzędzia → Opcje → Wykresy → Maks. barów).
3. `12_TRENING_MODELI_XAUUSD.bat` – trening w osobnym procesie (bot może działać). Raport: `data\forecast\runs\<run_id>\forecast_validation.json`.
4. Monitor przełącza model przy następnej zamkniętej M5. Rollback: `14_ROLLBACK_MODELU_PROGNOZ.bat`. Wyłączenie: `"forecast": {"enabled": false}`.

### B2a. Walls (HV-proxy / IV) i S12

- Domyślne źródło walls to HV-proxy – zmienność historyczna z D1 brokera (przybliżenie, **nie** zmienność implikowana); etykiety zawsze podają źródło.
- Własne dane IV (CSV/JSON, format w `docs/STRATEGIA_WALLS_RANGE_PATTERNS_PL.md`, przykład `docs\przyklad_iv_import.csv` – tylko przykład):
  ```
  cd backend
  ..\.venv\Scripts\python.exe -m masterquo import-iv ..\data\moje_iv.csv
  ```
  Dane są używane od chwili `available_at` w kolejnych snapshotach (bieżąca sesja ma zamrożony snapshot).
- S12 (rodzina walls/range) jest kandydatem i domyślnie **tylko skanuje** – tak jak S11. Brak wyników OOS: skuteczność nie została oceniona.

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
`ROLLBACK.md`, punkt 9 (1.10 → 1.9).

### Rozwiązywanie problemów

| Komunikat | Co zrobić |
|---|---|
| `MT5_INITIALIZE_FAILED:(-6, 'Terminal: Authorization failed')` | Terminal nie ma zalogowanego rachunku albo broker odrzucił logowanie. Zaloguj rachunek w MT5 (Plik → Zaloguj, „Zapisz hasło”) i kliknij „Połącz ponownie” (Ustawienia → MT5). Jeśli terminal nie pamięta hasła: wpisz login, serwer i hasło w Ustawienia → MT5 (hasło zostaje lokalnie, DPAPI). Przy kilku instalacjach MT5 wpisz ścieżkę `terminal64.exe`. MT5 i MasterQUO uruchamiaj tym samym użytkownikiem (oba bez „jako administrator”). |
| `Brak .venv - uruchom najpierw 01_INSTALUJ.bat` | Uruchom `01_INSTALUJ.bat` |
| `Brak Python 3.13/3.12` | `winget install -e --id Python.Python.3.13 --scope user`, potem ponownie `01_INSTALUJ.bat` |
| Monitor: „BRAK DANYCH” / MT5 niepołączony | Uruchom MetaTrader 5, zaloguj się, potem `02_DIAGNOSTYKA.bat` |
