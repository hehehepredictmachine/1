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
