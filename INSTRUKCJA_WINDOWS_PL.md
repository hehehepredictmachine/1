# MasterQUO 1.7 – instrukcja dla Windows

Dwie osobne części:

| Paczka | Dla kogo | Zawiera |
|---|---|---|
| `MasterQUO_KLIENT_1_7_0.zip` | komputer z MetaTrader 5 (użytkownik bota) | bot, monitor, launchery `.bat`. **Bez** serwera licencji, kluczy prywatnych i bazy licencji |
| `MasterQUO_SERWER_LICENCJI_1_7_0.zip` | administrator (VPS albo komputer administratora) | serwer licencji `mqlicense`, panel administratora, pliki wdrożeniowe |

Od wersji 1.7 bot uruchamia się **tylko z ważną licencją**:

- licencja trwa **72 h od wygenerowania** w panelu administratora;
- klucz `MQL72-…` wklejasz **przy każdym** uruchomieniu `masterquo_start.bat`;
- program go nie zapamiętuje.

---

## A. Administrator – serwer licencji i panel

### A1. Instalacja (test lokalny na Windows)

1. Rozpakuj `MasterQUO_SERWER_LICENCJI_1_7_0.zip`, np. do `C:\MasterQUO_SERWER_LICENCJI`. Nie rozpakowuj go do folderu
   klienta.
2. Uruchom `server\INSTALUJ_SERWER.bat`. Skrypt tworzy `.venv-server` i instaluje przypięte pakiety z sumami SHA-256.
   Wymagany jest Python 3.13 lub 3.12 x64 z „py launcher”.
3. Uruchom `server\start_dev_server.bat`. Przy pierwszym starcie skrypt:
   - generuje klucze **deweloperskie** w `server\data\dev\`;
   - wypisuje **klucz publiczny** (`-----BEGIN PUBLIC KEY-----…`), który wpiszesz w konfiguracji klienta;
   - uruchamia serwer pod `http://127.0.0.1:8790`.
4. Utwórz konto administratora: kliknij **`server\UTWORZ_ADMINA.bat`** (serwer może działać w drugim oknie). Podajesz e-mail i hasło,
   dostajesz sekret TOTP i kody odzyskiwania. Ręcznie to samo robi polecenie (tylko raz; publicznej rejestracji nie ma):

   ```
   cd C:\MasterQUO_SERWER_LICENCJI\server
   ..\.venv-server\Scripts\python.exe -m mqlicense --env-file data\dev\dev.env bootstrap-admin --email twoj@email.pl
   ```

   - Hasło (min. 12 znaków) wpisujesz w ukrytym polu.
   - Zeskanuj wypisany adres `otpauth://` w aplikacji TOTP (Aegis, Google Authenticator, 1Password).
   - **Kody odzyskiwania zapisz offline**, nie będą pokazane ponownie.
5. Otwórz `http://127.0.0.1:8790/admin/` i zaloguj się: e-mail, hasło, 6-cyfrowy kod z aplikacji.

Tryb deweloperski służy do testów. Klucze z `data\dev` nie nadają się do produkcji.

### A2. Produkcja (dostęp z innych komputerów)

- Klienci na innych komputerach potrzebują serwera dostępnego przez **HTTPS**. Gotowe kroki dla Linux VPS (Caddy +
  systemd, kopie zapasowe, migracje, restart, rotacja kluczy) są w `server\README_SERWER_PL.md`.
- Na Windows Server można użyć tego samego `python -m mqlicense serve` z Caddy for Windows jako reverse proxy HTTPS.
  Usługę rejestrujesz Harmonogramem zadań („przy starcie systemu”).
- **Uwaga:** serwer nie został przez nas wdrożony na żaden hosting. Wdrożenie wykonujesz Ty.

### A3. Wygenerowanie i przekazanie licencji

**Najszybciej – jeden przycisk:** po zalogowaniu kliknij w górnym pasku panelu **„＋ Generuj licencję 72 h”**. Klucz pojawi się
od razu z przyciskiem **„Kopiuj klucz”** (licencja 72 h, 1 jednoczesna sesja, bez wypełniania formularza).

**Z terminala serwera:** `..\.venv-server\Scripts\python.exe -m mqlicense --env-file data\dev\dev.env new-license --note "Jan"`
(w produkcji bez `--env-file`, w katalogu z `.env`).

**Z opcjami (klient, notatka, limit sesji):**

1. W panelu otwórz **Licencje** → „Nowa licencja”. Opcjonalnie: klient, notatka, limit jednoczesnych sesji (domyślnie 1).
2. Kliknij **Generuj**. Klucz `MQL72-…` jest pokazany **tylko teraz**. Skopiuj go („Kopiuj”) i przekaż użytkownikowi
   bezpiecznym kanałem.
3. Licencja wygasa dokładnie 72 h od tej chwili, według zegara serwera. Kolumna „Pozostało” odlicza czas.

W panelu możesz też:

- **Cofnij** – działa w ≤ 30 s, bot blokuje nowe sygnały i zlecenia;
- **Wydaj ponownie** – nowy klucz, nowe 72 h, stary klucz zostaje cofnięty;
- **Przypisz** do klienta;
- **±** – zmiana limitu sesji;
- **Sesje → Zakończ**;
- **Audyt** – kto, kiedy, co i z jakim wynikiem.

### A4. Kopia zapasowa, restart, rollback serwera

- **Kopia:**

  ```
  ..\.venv-server\Scripts\python.exe -m mqlicense --env-file data\dev\dev.env backup --out C:\kopie\mql_RRRRMMDD.sqlite3
  ```

  W produkcji używaj `deploy/backup.sh`.
- **Restart:** zamknij okno serwera i uruchom `start_dev_server.bat` ponownie. Licencje, cofnięcia i daty wygaśnięcia
  zostają w bazie.
- **Odtworzenie:** zatrzymaj serwer, podmień `data\dev\mqlicense.sqlite3` plikiem kopii, uruchom serwer.

---

## B. Użytkownik – bot MasterQUO (klient)

### B1. Instalacja lub aktualizacja

1. Rozpakuj `MasterQUO_KLIENT_1_7_0.zip` do **nowego** folderu, np. `C:\MasterQUO_AI_1_7`. Nie nadpisuj starej wersji:
   to jest Twój punkt powrotu.
2. Przy aktualizacji skopiuj ze starego folderu cały katalog `data\` (ustawienia, baza, zaszyfrowany klucz Claude).
   Stary folder zostaw bez zmian. Program przy migracji robi też kopię bazy w `data\backups\`.
3. Uruchom `01_INSTALUJ.bat` (tworzy `.venv`, instaluje pakiety z sumami SHA-256), a potem `02_DIAGNOSTYKA.bat`
   (sprawdza MT5, symbol `XAUUSD-`, czas; nie składa zleceń).

### B2. Adres serwera licencji

**Najprościej:** przy pierwszym `masterquo_start.bat` program sam zapyta w terminalu o adres serwera (Enter = `http://127.0.0.1:8790`),
pobierze jego klucz publiczny i pokaże **odcisk** – porównaj go z panelem (Podsumowanie → „klucz podpisu”) i wpisz `T`.
Zmiana później: **`09_KONFIGURACJA_LICENCJI.bat`**. Ręcznie:

Administrator podaje adres serwera i klucz publiczny. Wpisz je w **jeden** z dwóch sposobów:

- w `data\config.json`, sekcja `license`:

  ```json
  "license": {
    "server_url": "https://licencje.twoja-domena.pl",
    "public_key_pem": "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEA...\n-----END PUBLIC KEY-----\n",
    "telemetry_opt_in": false
  }
  ```

- albo w pliku `.env` (wzór: `.env.example`): `MASTERQUO_LICENSE_SERVER_URL=` oraz
  `MASTERQUO_LICENSE_PUBLIC_KEY_FILE=` (ścieżka do pliku `.pem` z kluczem publicznym).

Zasady:

- `http://` działa tylko dla `127.0.0.1`/`localhost` (test z lokalnym serwerem administratora). Inne adresy muszą być
  `https://`.
- **Klucza licencji nie wpisuje się do żadnego pliku.** Program i tak go stamtąd nie odczyta.

### B3. Start – przy każdym uruchomieniu wklej licencję

1. Uruchom `masterquo_start.bat` (albo `03_START_MASTERQUO.bat` – działa w tym samym oknie). Najpierw program pyta o licencję
   **w tym oknie terminala**; serwer główny i monitor startują dopiero po jej przyjęciu.
2. W oknie pojawi się `Wklej licencję MasterQUO (MQL72-…) i naciśnij Enter:`. Wklej klucz prawym przyciskiem myszy
   (znaki nie są wyświetlane) i naciśnij Enter.
3. Przy poprawnej licencji zobaczysz `Licencja aktywna – pozostało … h … min`. Monitor otworzy się pod
   `http://127.0.0.1:8765/`, a w pasku narzędzi widać „Licencja: … h … min”.
4. Gdy klucz jest zły, cofnięty lub wygasły, albo gdy brakuje serwera, program wyświetla przyczynę po polsku, nie
   uruchamia modułów i kończy z kodem 5. Masz 3 próby wklejenia złego klucza.

Każde kolejne uruchomienie znów prosi o klucz. Nie ma opcji „zapamiętaj”. Ponowne uruchomienie nie przedłuża licencji:
liczy się 72 h od wygenerowania.

### B4. W trakcie pracy i po wygaśnięciu

- Program odnawia dostęp co kilka sekund. Gdy licencja wygaśnie, zostanie cofnięta, sesję zakończy administrator albo
  serwer będzie niedostępny dłużej niż 30 s:
  - monitor pokaże planszę „Licencja nieaktywna”;
  - **nowe sygnały, analiza, agent AI, ML i nowe zlecenia** zostaną zablokowane.
- **Otwarte pozycje NIE są zamykane**, a ich SL/TP zostają na serwerze brokera. Ochrona pozycji (PositionManager)
  działa dalej.
- Aby pracować dalej, zatrzymaj program (`04_STOP_MASTERQUO.bat`), poproś administratora o nową licencję i uruchom
  `masterquo_start.bat` ponownie.
- Limit jednoczesnych sesji (domyślnie 1): ta sama licencja nie zadziała na drugim komputerze w tym samym czasie.
  - Po zwykłym STOP slot zwalnia się od razu.
  - Po awarii lub zamknięciu okna slot zwalnia się po ≤ 30 s.

### B5. Tryby i bezpieczeństwo handlu

- Sygnał (także „POTWIERDZONY”) **nie jest** zgodą na automatyczne zlecenia. Zlecenia zależą od trybu wykonania
  (SIGNALS / PAPER / AUTO DEMO / AUTO LIVE) i limitów ryzyka.
- Strategia S11 (EMA20 Pullback 2.5R) ma domyślnie włączone tylko skanowanie, bez handlu.
- Symbol `XAUUSD-` nie jest automatycznie podmieniany. Rachunek „Zero” nie oznacza zerowych kosztów (prowizja za lot).
- Testy (`05_TESTY_OFFLINE.bat`) używają symulatora i nie łączą się z Twoim rachunkiem.

### B6. Weryfikacja strategii na Twoich danych (zalecane przed handlem S11)

```
cd backend
..\.venv\Scripts\python.exe -m masterquo export --from-utc 2025-01-01T00:00:00Z --to-utc 2026-06-01T00:00:00Z --out ..\data\export_xau --dst-model NY_CLOSE
cd ..
.venv\Scripts\python.exe tools\backtest_ema_pullback.py --csv data\export_xau --tf M30 --commission-lot-side <prowizja z terminala>
```

- `--dst-model NY_CLOSE` liczy offset czasu dla każdej świecy (zmiany czasu letniego). Gdy broker nie stosuje tej
  konwencji, eksport zakończy się komunikatem; użyj wtedy `UNIFORM`.
- Wyniki trafiają do `data\results\ema_pullback\…` i `RAPORT_WYNIKOW.md`.

### B7. Rollback klienta

Uruchom poprzednią wersję z jej własnego folderu (patrz B1, krok 1) i przywróć kopię `data\config.json`. Szczegóły:
`ROLLBACK.md`, punkt 7.

### Rozwiązywanie problemów

| Komunikat | Co zrobić |
|---|---|
| `Brak konfiguracji serwera licencji` | Uzupełnij `license.server_url` i `license.public_key_pem` (B2) |
| `Adres serwera licencji musi używać https://` | Poproś administratora o adres https |
| `Brak połączenia z serwerem licencji` | Sprawdź internet i adres. Serwer administratora musi działać |
| `Ta licencja jest już używana…` | Zamknij drugą kopię programu albo odczekaj 30 s po awarii |
| `Odpowiedź serwera licencji nie przeszła weryfikacji podpisu` | Klucz publiczny w konfiguracji nie pasuje do serwera – poproś administratora o aktualny |
| Monitor: „Licencja nieaktywna” | Patrz B4 |
