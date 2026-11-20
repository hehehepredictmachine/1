# Licencja PepeMarketWizard (wersja klienta, 1.44.0)

## Aktywacja
1. Przy pierwszym uruchomieniu – zanim pojawi się intro i menu – zobaczysz ekran **AKTYWACJA LICENCJI**.
2. Kliknij **KOPIUJ** przy **TWÓJ HWID** i wyślij ten kod wydawcy programu. Klucz jest wydawany dla tego jednego komputera.
3. Wklej otrzymany klucz (zaczyna się od `PMW1-`) przyciskiem **WKLEJ** albo Ctrl+V i kliknij **AKTYWUJ**.
4. Po komunikacie **Licencja aktywna** program przechodzi do intro i menu. Klucz zostaje zapisany w
   `%APPDATA%\PepeMarketWizard\license.dat` – kolejne uruchomienia pomijają ekran aktywacji.

## Status i zmiana klucza
Panel systemowy → zakładka **LICENCJA**: użytkownik, typ (czasowa / bezterminowa), data wygaśnięcia, liczba pozostałych dni,
HWID tego komputera (**Kopiuj**) i **Zmień klucz** (to samo okno aktywacji). Na 3 dni przed końcem licencji na ekranie pojawia się
ostrzeżenie. Zły nowy klucz nie usuwa obecnego.

## Komunikaty
| Komunikat | Co zrobić |
|---|---|
| Nieprawidłowy klucz – zły format / podpis się nie zgadza | Skopiuj cały klucz jeszcze raz (od `PMW1-` do końca). |
| Licencja wygasła (data) | Poproś wydawcę o nowy klucz i wklej go w **Zmień klucz** / na ekranie aktywacji. |
| Klucz jest przypisany do innego komputera | Wyślij wydawcy HWID **tego** komputera. |
| Wykryto cofnięcie zegara systemowego | Ustaw poprawną datę i godzinę w Windows (Ustawienia → Czas i język → Ustaw czas automatycznie). |
| Błąd zegara systemowego (różnica z czasem z internetu) | Jak wyżej – zegar komputera różni się od czasu z internetu o ponad dobę. |

## Jak działa sprawdzanie
* Licencja działa **offline**. Przy każdym starcie (i co 10 minut) program sprawdza: klucz → podpis wydawcy → wersję → datę
  wygaśnięcia → HWID komputera.
* Gdy jest internet, datę bierze z czasu z internetu (nagłówek Date odpowiedzi HTTPS, limit 3 s). Bez internetu używa zegara komputera
  i pilnuje, by nie był cofnięty o ponad dobę względem ostatniego uruchomienia.
* Bez ważnej licencji tryby FOREX, CRYPTO, OTC i handel nie startują. Otwarte pozycje dalej chroni SL/TP po stronie brokera.
