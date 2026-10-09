# Instrukcja – Użytkownik (konto MasterQUO i licencja 48 h)

Konto MasterQUO (e-mail + hasło) i rachunek MT5 to **dwie różne rzeczy**. MasterQUO nigdy nie prosi o hasło do rachunku brokera.

## 1. Rejestracja
1. Uruchom bota (`03_START_MASTERQUO.bat`). W monitorze wpisz adres serwera kont (od administratora, `https://…`) → **Zapisz**.
2. **Rejestracja**: e-mail, hasło (min. 12 znaków) → **Załóż konto**.
3. Otwórz e-mail i link „potwierdź adres” → **Potwierdź adres**.
Rejestracja nie daje darmowej licencji.

## 2. Logowanie
**Logowanie** → e-mail i hasło. Bez ważnej licencji zobaczysz ekran aktywacji, status konta i instrukcję podłączenia terminala.
Nie pamiętasz hasła → **Nie pamiętam hasła** (link ważny 1 h, jednorazowy). Zmiana hasła wylogowuje inne sesje,
ale nie zmienia licencji ani poświadczenia komputera.

## 3. Aktywacja licencji
Wklej klucz `MQL1-…` od administratora → **Aktywuj licencję** (wymaga internetu). Po chwili zobaczysz monitor i pasek:
konto, status licencji, pozostały czas, rachunek, połączenie.

### Jak liczą się 48 godzin
* Start = **pierwsza aktywacja** (czas serwera, nie Twojego komputera).
* Koniec = start + 48 h. Czas płynie także, gdy program jest wyłączony, w nocy i w weekend – to 48 kolejnych godzin, nie 48 godzin pracy.
* Ponowna aktywacja, reinstalacja, zmiana hasła czy wylogowanie **nie** przedłużają terminu. Zmiana strefy czasowej zmienia tylko sposób wyświetlania.
* Godzinę i 10 minut przed końcem zobaczysz ostrzeżenie.
* Jedna licencja = jedna instalacja. Kilka kart przeglądarki tego samego monitora jest w porządku.
  Nowy komputer → poproś administratora o zwolnienie stanowiska (termin się nie wydłuża).

### Gdy licencja wygaśnie lub zostanie cofnięta
Nowe analizy, checklista, nowe setupy, trening ML, agent Claude i **nowe otwarcia** zostają zatrzymane. Dane, historia i modele
zostają. Otwarte wcześniej pozycje bota **nie są zamykane automatycznie**: mają SL/TP po stronie brokera i dotychczasową
obsługę ochronną (TP1, stop na BE); możesz je zamknąć na ekranie blokady. Oczekujące zlecenia otwierające bota są anulowane.
Wpisz nowy klucz – funkcje wracają bez reinstalacji; stare zlecenia nie są ponawiane.
Bez internetu bot działa najwyżej do końca ostatniego potwierdzenia z serwera (do 60 s) – potem blokuje nowe funkcje.

## 4. Podłączenie MT5 i przesyłanie danych (opcjonalne)
1. Uruchom MetaTrader 5 i zaloguj się na wybrany rachunek (np. `XAUUSD-` w Market Watch).
2. W pasku licencji: **Dane do serwera → Włącz…**. Przeczytaj informację: właściciel usługi zobaczy **saldo, equity, walutę,
   typ rachunku, serwer, login i historię transakcji tego jednego rachunku** oraz status połączenia. Hasło brokera nie jest
   odczytywane ani wysyłane. Inne rachunki na komputerze nie są skanowane.
3. Po zmianie rachunku w terminalu przesyłanie się zatrzymuje – włącz je ponownie świadomie (nowy rachunek = osobna historia).
**Wyłącz** zatrzymuje wysyłanie; ostatni odczyt zostaje u administratora oznaczony jako nieaktualny.

## 5. Tryby nie zmieniają się same
Logowanie i aktywacja **nie przełączają** bota na handel LIVE. Wybór strategii, tryb ML i tryb wykonania
(SIGNALS / PAPER / AUTO DEMO / AUTO LIVE) zostają takie, jak je ustawiłeś. Licencja to uprawnienie do produktu, nie sygnał wejścia.

## 6. Wylogowanie / zmiana osoby
**Wyloguj** czyści dane z monitora (strona przeładowuje się bez danych poprzedniej osoby). Jedna instalacja obsługuje jedno
konto naraz – inna osoba potrzebuje własnej licencji.
