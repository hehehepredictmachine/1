# Audyt paczki PepeMarketWizard 1.16.0 (20.10.2026)

Zakres audytu:
- zawartość paczki ZIP;
- instalatory Windows;
- przebieg treningu zgłoszony przez użytkownika (zrzuty ekranu z 20.10);
- zależności;
- testy.

Ten audyt nie obejmuje terminala MT5 ani komputera użytkownika. Nie da się z niego potwierdzić połączenia z kontem ani jakości modeli rynkowych.

## Ustalenia i naprawy

| # | Objaw u użytkownika | Przyczyna | Naprawa |
|---|---|---|---|
| A1 | `BŁĄD – Eksport historii z MT5:` widać tylko ścieżkę komendy | Podsumowanie brało pierwsze 160 znaków logu procesu, a tam stała powtórzona komenda | Pokazywana jest linia `[BLAD]` procesu oraz ścieżka logu (`training/core.py: child_reason`) |
| A2 | `XAUUSD- nie pasuje do profilu XAUUSD (BASE_USD_NOT_XAU)` | Broker CFD podaje dla złota `currency_base=USD`; profil wymagał `XAU` | Symbol jest akceptowany, gdy base = profit, a nazwa symbolu wskazuje instrument. Dotyczy eksportu, rejestru bota i gold_candles. `XAUT`/`PAXG` i symbole z „gold” tylko w opisie są nadal odrzucane |
| A3 | Instalator zgłasza „Nie znaleziono sprawnego Python”, choć Python 3.13/3.12 jest zainstalowany | W folderze programu brakowało `tools\check_python.py` (niepełne rozpakowanie lub skopiowanie części plików) | `01_INSTALUJ`, `INSTALUJ_TRENING`, `00_TRENING_START` i `PepeMarketWizard.exe` najpierw sprawdzają kompletność folderu i podają instrukcję rozpakowania |
| A4 | `ml` i `lab` pominięte: „za mało wolnej pamięci RAM (1708 MB < 2000 MB)” | Twardy próg wolnej pamięci; poniżej progu zadanie było pomijane | Budżet RAM 8 GB (ustawienie użytkownika; `MQ_RAM_BUDGET_MB` lub opcja R w `PepeMarketWizard.exe`). Przy mniejszej wolnej pamięci program czeka do 3 min, potem uruchamia zadanie na proporcjonalnie mniejszej próbce (minimum 25 %). Pomija dopiero poniżej 600 MB. Na Windows Job Object ogranicza każdy proces treningu do budżetu |
| A5 | `forecast` i `Scalp A/B/C` pominięte: „brak środowiska .venv_candles” | `.venv_candles` nie istniało; instalator sprawdzał tylko istnienie pliku `python.exe` | Runner sprawdza środowisko importem (`numpy, pandas, sklearn`). Brakujące lub uszkodzone środowisko instaluje automatycznie raz na run (`10_PROGNOZY_INSTALUJ.bat` bez pauzy). `INSTALUJ_TRENING` waliduje oba środowiska importem |
| A6 | Pełna regresja: 1 błąd (`test_ui_analytics`) | Aktualizacja 07 zmieniła nazwę pola raportu biblioteki formacji | Przywrócono pole `samples_processed` |
| A7 | Brak pliku `.exe` | — | `PepeMarketWizard.exe` (Go, Windows x64, konsola). Menu: instalacja/naprawa, kalibracja + trening XAUUSD / BTC / oba, kalibracja wskaźników kontekstu, menu treningu, diagnostyka, start/stop bota, budżet RAM. Wywołuje te same przetestowane skrypty i nie zawiera logiki handlowej |

## Sprawdzone bez zmian
- Hashe w `requirements-win.txt` i `requirements-candles-win.txt` zgadzają się z plikami na PyPI. Dla cp312 i cp313 win_amd64 nie ma błędnych hashy.
- Wszystkie ścieżki, do których odwołują się `*.bat` i `tools\*.cmd`, istnieją w paczce.
- Paczka powstaje wyłącznie z plików śledzonych w git. Nie zawiera `.venv`, `node_modules`, `data/`, `.env`, baz danych ani kluczy; budowa przerywa się przy wykryciu sekretu.
- Execution Lock, tryb wykonania i limity ryzyka nie są zmieniane przez instalator, trening, kalibrację ani launcher.

## Jak uruchomić
1. Rozpakuj cały ZIP (prawy klik → „Wyodrębnij wszystkie”) do nowego folderu, najlepiej o krótkiej ścieżce, np. `C:\PMW`.
2. Uruchom `PepeMarketWizard.exe` i wybierz **1**: instalacja trwa kilka do kilkunastu minut, pobiera pakiety z PyPI.
3. Przy zalogowanym MT5 i otwartym rynku wybierz **2**: kalibracja i trening XAUUSD. Symbol wybierz z listy, np. `XAUUSD-`.
4. Po zakończeniu otwiera się `report.html` ze statusem każdego zadania.
5. **8** uruchamia bota.

Windows SmartScreen może ostrzec przed niepodpisanym plikiem `.exe` („Więcej informacji → Uruchom mimo to”). Te same funkcje są dostępne bez `.exe` przez pliki `.bat`.

## Czego audyt nie gwarantuje
- **Jakość modeli.** „Wytrenowany” nie znaczy „z przewagą”. Model może dostać status `ODRZUCONY`, `BRAK_PRZESLANEK` albo `NO_VALIDATED_EDGE`, i to jest poprawny wynik, nie błąd.
- **Aktywacja.** Modele aktywują się tylko po walidacji i wyłącznie w trybie SHADOW.
- **Native MQL5.** Kompilacji wskaźników MQL5 nie wykonano. Robi to Twój MetaEditor (menu 5 → opcja 9).
- **Pierwszy pełny run na Twoich danych** nie był tu wykonany. Jeśli któreś zadanie skończy się błędem, raport pokaże teraz linię `[BLAD]` i ścieżkę logu.
