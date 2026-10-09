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

## 5. Konta i licencje (1.4) → wersja 1.3
* Dane klienta zostają: migracja bazy bota `0004` dodaje tylko kolumnę `order_attempts.authorized_at`; kopia sprzed migracji
  w `data/backups/`. Historia transakcji, modele ML (`data/ml/`) i ustawienia nie są usuwane.
* Konfiguracja: 1.4 zapisuje `config_version: 4` i sekcję `central`. Wersja 1.3 odrzuca nieznane pola – przed jej uruchomieniem
  przywróć `data/config.json` z `data/backups/` albo usuń sekcję `central` i ustaw `"config_version": 3`.
* Poświadczenie urządzenia (`MQ_DEVICE_ED25519` w magazynie DPAPI) i `data/license/` nie przeszkadzają wersji 1.3.
* Serwer centralny jest osobną instalacją – jego wyłączenie nie zmienia danych bota. Odtworzenie serwera z kopii (`pg_restore`)
  zachowuje daty licencji (`activated_at`, `expires_at`); restart ani migracja ich nie przesuwają.
