# Instrukcja – Administrator (MasterQUO License Manager)

Panel: `https://twoja-domena/admin/`. Logowanie: e-mail + hasło + **kod TOTP** (albo jednorazowy kod odzyskiwania).
Panel służy do kont, licencji i podglądu statystyk. **Nie składa zleceń na rachunkach klientów** – nie ma takich przycisków.

## 1. Pierwsze konto administratora
Na serwerze: `python -m mqcentral bootstrap-admin twoj@email.pl`. Hasło wpisujesz w ukrytym polu (min. 12 znaków).
Program pokaże raz: URI/sekret TOTP (dodaj do Google Authenticator / Aegis / 1Password) i 10 kodów odzyskiwania – zapisz je offline.
Kolejnych administratorów nadaje tylko komenda `python -m mqcentral set-role EMAIL ADMIN` (zapis w audycie, wylogowanie tej osoby).
Konto administratora nie trafia do paczki dla klientów.

## 2. Konto użytkownika
* Użytkownik sam zakłada konto w monitorze bota (Rejestracja) i potwierdza e-mail linkiem; **albo**
* **Użytkownicy → Utwórz konto (zaproszenie)**: wpisz e-mail. Użytkownik dostaje jednorazowy link (72 h) i sam ustawia hasło –
  Ty go nie znasz.
Rejestracja **nie** daje licencji. Ponowne założenie konta nie daje kolejnych 48 godzin.

## 3. Wygenerowanie i przypisanie licencji 48 h
1. **Licencje → Wygeneruj licencję 48h** (albo w szczegółach użytkownika).
2. Wybierz konto, opcjonalnie notatkę, **Utwórz licencję**.
3. Pełny klucz `MQL1-…` jest pokazany **tylko raz** – **Kopiuj klucz** i przekaż go użytkownikowi bezpiecznym kanałem.
   Serwer przechowuje tylko skrót; w panelu zobaczysz identyfikator `MQL1-…XXXX`.
4. Klucz działa tylko dla wybranego konta – inne konto go nie aktywuje.
5. Odliczanie **nie** startuje przy generowaniu ani przypisaniu – dopiero przy pierwszej aktywacji (czas serwera UTC);
   `wygasa = aktywacja + 172 800 s`, także gdy program jest wyłączony.
Zgubiony klucz: **Cofnij** licencję i wygeneruj nową (oba działania w audycie). Nie ma klucza bezterminowego.

## 4. Sprawdzanie klientów
Tabela **Użytkownicy**: e-mail i status konta, rachunek MT5 (login · serwer · DEMO/LIVE), Balance i Equity z walutą, win ratio
(30 dni, liczba W/L/N), stan licencji, aktywacja, wygaśnięcie, pozostały czas, konektor ONLINE/OFFLINE, wiek ostatnich danych.
Wyszukiwanie, filtry (status, licencja), sortowanie (kliknij nagłówek), stronicowanie. Kliknij wiersz → szczegóły:
licencje, stanowiska, urządzenia, połączone rachunki, statystyki z filtrami (7 dni / 30 dni / cały okres / własny przedział,
cały rachunek / tylko bot, symbol XAUUSD-), historia działań.

**Win ratio** = 100 × wygrane / (wygrane + przegrane); jednostka = zakończony cykl transakcji; wynik netto po prowizji, swapie
i opłatach; neutralne (|wynik| ≤ pół najmniejszej jednostki waluty) osobno; wpłaty/wypłaty/korekty wykluczone; brak W i L = N/A.
DEMO i LIVE to osobne rachunki – nie są łączone; PAPER nie jest wysyłany. Dane pochodzą z **konektora MT5 klienta** –
nie są niezależnym audytem brokera. Brak połączenia = ostatni odczyt z wiekiem albo „brak danych” (nigdy 0).

## 5. Cofnięcie i blokada
* **Cofnij** licencję – trwałe; serwer od razu odmawia; bot klienta traci nowe funkcje najpóźniej po końcu ostatniego lease (≤ 60 s).
* **Zablokuj** konto – wylogowuje wszystkie sesje, bot traci nowe funkcje po końcu lease; daty licencji się nie zmieniają.

## 6. Reset stanowiska (wymiana komputera)
Szczegóły użytkownika → **Zwolnij stanowisko**. Stare poświadczenie urządzenia jest unieważnione, klient może aktywować tę samą
licencję na nowym komputerze **tylko do pierwotnego terminu** – nowe 48 h nie startuje.

## 7. Audyt i system
**Audyt**: kto, kiedy, wobec kogo – generowanie, aktywacja, cofnięcie, reset stanowiska, blokada, zmiana roli (bez sekretów).
**System**: czas serwera, anomalia zegara, baza, poczta (w trybie dev – DEV OUTBOX z niewysłanymi e-mailami).
