# Powrót do poprzedniej konfiguracji

## 1. Profil ORIGINAL (bez reinstalacji)
Wykrywanie wraca do dotychczasowego M07/M10A (jak w wersji 1.1). Tryb pracy, limity i historia zostają.
* w monitorze: ⚙ Ustawienia → **AUTO / ACTIVE** → Profil wykrywania = `ORIGINAL` → Zapisz, albo
* zatrzymaj program (`04_STOP_MASTERQUO.bat`) i uruchom `08_PROFIL_ORIGINAL.bat` (ponowne włączenie: `08_PROFIL_ORIGINAL.bat ACTIVE`).
Kopia ustawień obu profili: `config/profiles/ACTIVE.json`, `config/profiles/ORIGINAL.json` (fragmenty sekcji `active`).

## 2. Łagodne bramki 1.1 → ścisłe reguły MasterQUO 1.0
Ustawienia → Strategia M07 → Kierunek struktury `STRICT_H4_H1`; Ryzyko → RR 1,5 / 2,0 i „RR pomiędzy progami” wyłączone;
Agent Claude → Rola AI `REQUIRED`; Ryzyko → „Brak kalendarza makro blokuje wejścia” włączone.

## 3. Poprzednia wersja programu
Rozpakuj poprzedni ZIP do osobnego folderu. Baza `data/masterquo.sqlite` jest migrowana (0002 dodaje tabele, niczego nie usuwa);
kopia sprzed migracji: `data/backups/`. Wersja 1.1 ignoruje nowe tabele. Plik `data/config.json` z sekcją `active` należy w 1.1
zastąpić kopią z `data/backups/` albo usunąć sekcję `active` (1.1 odrzuca nieznane pola).

## 4. Wygląd
Ustawienia → Wygląd → OFF (statyczne kadry). Wgrane GIF-y: usuń pliki z `data/assets/masterquo/`.

## 5. Wersja 1.3.1 → 1.3.0
* Strefy można wyłączyć bez cofania wersji: przełącznik „IV walls / Daily” albo `"volatility": {"enabled": false}`.
* Powrót do 1.3.0: 1.3.1 zapisuje `config_version: 5` i sekcję `volatility` – przed uruchomieniem 1.3.0 usuń tę sekcję
  i ustaw `"config_version": 3` (albo przywróć `data\config.json` z kopii). Baza danych nie została zmieniona.

## 6. Wersja 1.6.0 → 1.3.1
* Bez cofania wersji: skaner i sygnały wyłączysz w **Ustawienia → Rynki / Sygnały bota** (`markets.enabled`, `signals.enabled`).
* Powrót do 1.3.1: usuń z `data\config.json` sekcje `markets` i `signals` i ustaw `"config_version": 5`. Tabela sygnałów (migracje 0005, 0006)
  nie przeszkadza wersji 1.3.1; kopia bazy sprzed migracji jest w `data\backups\`.

## 7. Wersja 1.7.0 → 1.6.0
* Punkt powrotu: przed migracją 0007 program kopiuje bazę do `data\backups\` (jak przy poprzednich migracjach); `data\config.json`
  z wersji 1.6 – zachowaj kopię przed pierwszym startem 1.7 (1.7 zapisuje `config_version: 8`, dodaje `license` i przełącznik S11).
* Powrót: rozpakuj ZIP 1.6.0 do osobnego folderu, przywróć `data\config.json` z kopii (albo usuń sekcję `license`, wpis `S11`
  w `active.strategies` i ustaw `"config_version": 6`). Tabela `signal_history` i kolumna `ai_verdict` (0007) nie przeszkadzają 1.6.

## 8. Wersja 1.9.0 → 1.8.0
* 1.9.0 usuwa licencjonowanie i zapisuje `config_version: 9` (bez sekcji `license`); baza bez nowych migracji.
* Powrót do 1.8.0 (wymaga licencji i serwera licencji): rozpakuj ZIP 1.8.0 do osobnego folderu i przywróć kopię `data\config.json`
  sprzed 1.9 albo ustaw `"config_version": 8` – 1.8 poprosi o konfigurację serwera licencji przy starcie.

## 9. Wersja 1.10.0 → 1.9.0
* 1.10.0 zapisuje `config_version: 10` (sekcja `walls`, wpis `S12` w `active.strategies`) i dodaje migracje bazy **0009** (polityka wyjścia,
  stan TP1, `trades.status`) i **0010** (`iv_observations`, `walls_snapshots`) – tylko nowe kolumny i tabele; kopia bazy sprzed migracji w `data\backups\`.
* Bez cofania wersji: S12 wyłączysz w Ustawienia → AUTO / ACTIVE (domyślnie i tak tylko skanuje); źródło walls ustawisz w `"walls": {"source": "HV_PROXY"}`
  (walls są wejściem tylko dla S12 i wykresów, nie zmieniają S01–S11).
* Powrót: rozpakuj ZIP 1.9.0 do osobnego folderu, przywróć `data\config.json` z kopii sprzed 1.10 (albo usuń sekcję `walls`, wpis `S12`
  i ustaw `"config_version": 9`) oraz bazę z `data\backups\` – 1.9 nie zna statusu OPEN_PARTIAL/UNSETTLED i liczyłaby je jak zamknięte.
* Preferencje monitora 1.10 (strony, układy, widoki `ai-*`/`bot-*`) są w przeglądarce; 1.9 ich nie używa, a jej widoki `panelN` zostały zachowane.

## 11. Wersja 1.25.0 → 1.24.1
* Punkt powrotu w repozytorium: commit `a10d97a` (wydanie 1.24.1). Kod eksportu sprzed zmian (użyty w porównaniu przed/po): `0a57370`.
  1.25 nie zmienia schematu konfiguracji (`config_version` 12) ani nie dodaje migracji bazy – powrót = uruchomienie paczki 1.24.1 na tych
  samych danych.
* Nowe pliki danych, które 1.24.1 ignoruje: `data\montecarlo\` (walidacje i kalibracje Monte Carlo), w eksportach `EXPORT_STATUS.json`,
  `MODEL_DATA_READINESS.json`, `ticks\`. Eksport 1.25 ma dodatkową kolumnę `real_volume` na końcu CSV – czytniki 1.24 biorą kolumny po
  nazwie i jej nie używają.
* Bez cofania wersji: kalibracja Monte Carlo – `python -m masterquo montecarlo rollback --instrument XAUUSD` (wraca do poprzedniej
  aktywnej albo do „bez kalibracji”); TP3 SCALPING – Strategie → Ustawienia SCALPING → TP3 5 USD albo „Przywróć poprzednią”
  (`POST /api/v1/sh/config/rollback`). Scenariusz 2,5–10 USD niczego nie zleca – nie wymaga wyłączania.

## 10. Wersja 1.24.0 → 1.23.x
* Punkt powrotu w repozytorium: commit `ba7a5d5` (stan przed przebudową desktop; lokalny tag `pre-desktop-1.23.0`). 1.24 nie dodaje migracji bazy.
* Konfiguracja: 1.24 zapisuje `config_version: 12` (Execution Lock wycofany, pole `execution.mode_note`, Telegram: `send_trades`,
  `send_stats`, `stats_hour_utc`, `language`). Kopia sprzed migracji: `data\config.v11.bak.json` – przed uruchomieniem 1.23 przywróć ją
  jako `data\config.json` (1.23 odrzuca nieznane pola).
* Aplikacja `PepeMarketWizardDesktop.exe` pracuje na kopii danych w `%LOCALAPPDATA%\PepeMarketWizard\data` – stary folder
  instalacji zostaje bez zmian, więc powrót = uruchomienie poprzedniej wersji z tamtego folderu. Kopie danych sprzed aktualizacji
  aplikacji: `%LOCALAPPDATA%\PepeMarketWizard\backups\<RRRRMMDD_GGMMSS>_<etykieta>`. Usunięcie aplikacji: Centrum sterowania → Praca aplikacji →
  wyłącz autostart, zamknij aplikację (ikona przy zegarze → Zamknij aplikację) i usuń jej folder; dane w `%LOCALAPPDATA%` usuń ręcznie,
  jeśli nie są potrzebne.
* Bez cofania wersji: strategie „tylko sygnały” (S11, S12) i przełączniki handlu per strategia – Ustawienia → AUTO / ACTIVE;
  polityka AI – Ustawienia → Agent Claude (`VETO` / `REQUIRED`); Telegram – Centrum sterowania → MT5 i połączenia (wyłącz).
