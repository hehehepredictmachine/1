# Licencje offline PMW1 – generator właściciela (1.43.0)

Ustawienia → zakładka **GENERATOR LICENCJI** (panel systemowy, obok Diagnostyki i Centrum Treningowego). Narzędzie właściciela:
bez logowania i haseł, działa w pełni offline. Niczego nie blokuje w bocie – sprawdzanie licencji po stronie klienta to osobny krok.

## 1. Para kluczy (Ed25519, PyNaCl / libsodium)
* **Utwórz parę kluczy** – tylko gdy kluczy jeszcze nie ma (druga para unieważniłaby wszystkie wydane licencje).
* Klucz prywatny: `%APPDATA%\PepeMarketWizard\owner\private.key` (poza folderem programu; na innych systemach
  `~/.config/PepeMarketWizard/owner`). Nigdy nie jest wkompilowany w kod ani wysyłany – opuszcza dysk tylko przez
  **Eksportuj kopię zapasową klucza prywatnego** (okno „Zapisz jako”). `.gitignore` i weryfikator paczek blokują `private.key`,
  `*.key`, `licenses.db` oraz treść klucza.
* **Klucz publiczny** (64 znaki hex) + **Kopiuj** – posłuży aplikacji klienta do weryfikacji.
* **Importuj klucz prywatny** – przywrócenie z kopii. Gdy na komputerze jest INNY klucz, import wymaga potwierdzenia
  („Zastąp klucz”), a poprzedni klucz zostaje zachowany jako `private.key.bak-<data>`.
* Format pliku klucza:
  ```
  PMW-OWNER-ED25519-PRIVATE-KEY v1
  seed: <32 bajty ziarna Ed25519, hex>
  public: <32 bajty klucza publicznego, hex>
  created: <data UTC>
  ```
  Import przyjmuje też samo ziarno (64 hex) albo ziarno + klucz publiczny (128 hex, jak w libsodium).

## 2. Klucz licencji
```
PMW1-<base64url bez '='>( payload || podpis )
payload = {"v":1,"u":"<użytkownik>","hw":"<HWID>"|null,"iat":<unix s>,"exp":<unix s>|null}   (JSON UTF-8, bez spacji, stała kolejność)
podpis  = Ed25519( "PMW1|" + payload )   – 64 bajty na końcu
```
* `iat` – data wydania, `exp` – wygaśnięcie (7 / 30 / 90 / 365 dni od wydania, własna data = 23:59:59 wybranego dnia czasu
  tego komputera) albo `null` (bezterminowa). `hw` – HWID albo `null` (bez przypisania – działa na każdym komputerze).
* Notatka trafia tylko do historii, nie do klucza.
* Weryfikacja (wystarczy klucz publiczny): prefiks `PMW1-` → zapis kanoniczny base64url (każda zmiana znaku zmienia bajty) →
  podpis Ed25519 → pola → `exp` (wygasła?) → `hw` (zgodny z HWID komputera?). Kod: `backend/masterquo/licensing/license_key.py`
  (`read_license(key, public_key, now=…, hwid=…)`).

## 3. HWID
`get_hwid()` = SHA-256(`"PMW-HWID-v1|" + MachineGuid + "|" + UUID płyty głównej`) → pierwsze 100 bitów → Base32 Crockford →
`XXXXX-XXXXX-XXXXX-XXXXX` (cyfry i litery bez I, L, O, U). MachineGuid z rejestru (`HKLM\SOFTWARE\Microsoft\Cryptography`),
UUID z tabeli SMBIOS (jak `Win32_ComputerSystemProduct.UUID`). W generatorze: **Wklej** i **Użyj HWID tego komputera** (do testów).
Pole HWID przyjmuje tylko ten format. Kod: `backend/masterquo/licensing/hwid.py`.

## 4. Historia i sprawdzanie
* Historia: `%APPDATA%\PepeMarketWizard\owner\licenses.db` (SQLite) – użytkownik, HWID, wydana, wygasa, notatka, klucz;
  status (aktywna / wygasła) liczony z daty. Wyszukiwanie, sortowanie po kolumnach, kopiowanie klucza, usuwanie wpisu
  (usunięcie wpisu nie unieważnia licencji offline).
* **Sprawdź klucz**: odczytane dane, poprawność podpisu, wygaśnięcie, przypisany HWID (ten / inny komputer).

## 5. API (tylko 127.0.0.1; zmiany i eksport klucza – POST/DELETE z tokenem CSRF)
`GET /api/v1/owner/license/state` · `POST /api/v1/owner/license/keys` · `POST …/keys/export` · `POST …/keys/import {content, replace}` ·
`GET …/hwid` · `POST …/generate {user, hwid, no_hwid, validity:{kind:"days",days}|{kind:"date",date}|{kind:"perpetual"}, note}` ·
`POST …/check {key}` · `GET /api/v1/owner/licenses` · `DELETE /api/v1/owner/licenses/{id}`.

## 6. Testy
`tests/test_licensing.py` – generowanie i odczyt, zmiana 1 znaku na każdej pozycji = klucz nieważny, zapis niekanoniczny,
wygasły, bezterminowy, z HWID i bez, inny klucz właściciela, HWID (format, SMBIOS), magazyn kluczy (utwórz / eksport / import /
zastąpienie), walidacja formularza, historia, API z CSRF.
