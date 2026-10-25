# START TUTAJ – trening modeli XAUUSD i BTC (PepeMarketWizard 1.16)

Trening działa **offline**. Nie wysyła zleceń, nie zamyka pozycji i nie zmienia Execution Lock. Odczytuje historię z Twojego terminala MT5 przez osobne połączenie: tylko odczyt, a funkcje zleceń są w nim zablokowane. Działający bot dostaje gotowe modele dopiero po walidacji.

## Najprościej: `PepeMarketWizard.exe` (1.16)
Uruchom `PepeMarketWizard.exe` z rozpakowanego folderu. Do wyboru masz:
- **1** – instalacja lub naprawa środowiska;
- **2 / 3 / 4** – kalibracja i trening XAUUSD / BTC / obu;
- **5** – kalibracja wskaźników kontekstu VAMD/FD/SMC i instalacja MQL5;
- **8 / 9** – start / stop bota;
- **R** – budżet RAM treningu (domyślnie 8 GB).

Launcher uruchamia te same pliki `.bat` co poniżej. Nie wysyła zleceń i nie zmienia Execution Lock. Szczegóły i lista napraw: `docs/AUDYT_PACZKI_1_16_PL.md`.

## 1. Jednorazowo: instalacja
1. Rozpakuj `PepeMarketWizard_KLIENT_1_18_0.zip` (cały ZIP – „Wyodrębnij wszystkie”) do dowolnego folderu. Spacje, polskie litery i znak `!` w ścieżce są obsługiwane.
   - Dane z poprzedniej wersji (`data/`) możesz skopiować.
   - Istniejące modele XAUUSD zostają w dotychczasowych katalogach i nadal działają.
2. Uruchom **`INSTALUJ_TRENING.bat`**.
   - Szuka Pythona 3.13 albo 3.12 w wersji 64-bit.
   - Tworzy `.venv` (bot) i `.venv_candles` (prognozy/scalp) tylko wtedy, gdy ich brakuje. Sprawnego środowiska nie nadpisuje.
   - Pakiety instaluje z plików blokad `requirements/requirements-win.txt` i `requirements/requirements-candles-win.txt`, z hashami SHA256.
   - Działa tylko na CPU. Node.js nie jest potrzebny, bo panel jest już zbudowany.
   - Wynik zapisuje w `data/training/install_check.json`.

## 2. Diagnostyka (zalecane przed pierwszym treningiem)
Uruchom **`DIAGNOSTYKA_TRENINGU.bat`** (MT5 uruchomiony i zalogowany). Pokazuje:
- środowisko i zgodność wersji z blokadą;
- terminal, serwer i walutę konta;
- **kandydatów na symbol XAUUSD i BTC** z metadanymi kontraktu: waluta bazowa/kwotowania, tryb wyceny, wielkość kontraktu, tick, cyfry, wolumeny;
- czy bot działa i wynik ostatniego treningu.

**Ważne dla BTC:** proponowany symbol to `BTCUSDT-` (w zleceniu było `btsusdt-`).
- Program nie podmienia go po cichu na `BTCUSD`, a USD i USDT traktuje jako różne waluty kwotowania.
- WBTC, BTCB, XAUT, PAXG itp. są odrzucane jako „podobne, ale inne”.
- Jeśli w terminalu jest `BTSUSDT-` z inną walutą bazową, diagnostyka to pokaże i musisz wskazać symbol Bitcoina.

## 3. Trening
- **`00_TRENING_START.bat`** – menu z opcjami:
  1. instalacja;
  2. trening XAUUSD;
  3. trening BTC;
  4. trening obu instrumentów;
  5. diagnostyka;
  6. wyniki;
  7. wznowienie;
  8. rollback.
- Skróty: `TRENUJ_XAUUSD.bat`, `TRENUJ_BTCUSDT.bat`, `TRENUJ_OBA.bat`.
- **Kreator zapyta o:**
  - **profil:**
    - `TEST INSTALACJI` – kilka minut, krótka historia, modele **nigdy** nie są aktywowane;
    - `PEŁNY TRENING` – domyślnie 12 miesięcy, aktywacja tylko po walidacji;
  - liczbę miesięcy historii (program pokaże zakres, który terminal faktycznie oddał);
  - wybór symbolu z listy kandydatów;
  - **prowizję** za 1 lot na stronę.
    - Enter oznacza: weź medianę z historii transakcji tego symbolu na Twoim koncie.
    - Jeśli dla BTC jej nie ma, zadania scalp i ML dla BTC zostaną pominięte z podanym powodem. Program nie przyjmuje automatycznie 0.50.
- **Kolejność:** najpierw XAUUSD, potem BTC. Każdy instrument przechodzi te kroki:
  1. eksport M1–D1 (porcjami, z punktami kontrolnymi, z metadanymi i SHA256);
  2. kontrola jakości: duplikaty, geometria OHLC, luki, DST, niezamknięte świece;
  3. prognozy gold_candles 5/15/30 min;
  4. scalp A/B/C (C to ocena polityki w replayu, nie sieć);
  5. legacy ML (Decision Tree + XGBoost);
  6. modele lab: LOGREG, TREE, MiniRocket, XGB, ResNet1D, SEW-SNN oraz eksperymenty – **strona LONG**;
  7. aktywacja;
  8. przeładowanie w bocie, jeśli działa (bot nie jest uruchamiany drugi raz).
- `22_TRENUJ_WSZYSTKIE_MODELE.bat [prowizja_XAUUSD]` uruchamia ten sam mechanizm dla obu instrumentów.
- Panel bota → **Modele i trening** → karta „Trening XAUUSD / BTC”. Korzysta z tego samego mechanizmu i pokazuje:
  - wybór instrumentu, start, postęp i anulowanie;
  - wynik;
  - aktywne modele z przyciskiem rollback.

## 4. Jak czytać wynik
Na końcu zobaczysz zdanie w rodzaju „XAUUSD: 9/10 zadań ukończonych; BTC: 8/10 … N modeli dopuszczonych do SHADOW”. Liczby pochodzą z bieżącego runu.

Raport HTML otwiera się automatycznie, a JSON trafia do `data/training/runs/<run>/`. Każde zadanie ma **trzy osobne statusy**:

| Oś | Wartości |
|---|---|
| Wykonanie | ukończone / pominięte (z powodem) / błąd techniczny / anulowane |
| Jakość | zwalidowany SHADOW / częściowo / niezwalidowany / odrzucony / za mało danych / test techniczny |
| Integracja | do badań / aktywny w rejestrze / załadowany do SHADOW / rollback |

„Ukończone” **nie znaczy** „dobry model”. Odrzucone modele zostają do wglądu i nie zastępują aktywnego. Raport nie podaje win rate ani żadnej obietnicy wyniku.

**Kody zakończenia:**

| Kod | Znaczenie |
|---|---|
| 0 | wszystkie zadania wykonane (jakość – patrz raport) |
| 1 | błąd techniczny |
| 2 | zablokowane przed startem (brak MT5, symbolu lub danych; trwa inny trening) |
| 3 | anulowane – wznowienie w menu (7) |
| 4 | część zadań pominięta (brak środowiska, prowizji lub RAM) |

## 5. Wznowienie, anulowanie, rollback
- **Anulowanie:** w panelu albo przez zamknięcie okna. Przy wznowieniu zakończone kroki nie są powtarzane, a eksport kontynuuje od ostatniego zapisanego fragmentu.
- **Rollback** (menu 8 albo panel) dotyczy jednej rodziny jednego instrumentu:
  - `forecast`, `scalp`, `ml` albo `lab:<RODZINA>`, np. `lab:SEW_SNN`;
  - przywraca poprzedni model z rejestru danego instrumentu.

## 6. Gdzie są dane i modele

| Instrument | Dane i modele |
|---|---|
| XAUUSD | dotychczasowe miejsca: `data/forecast`, `data/scalp`, `data/ml` + `masterquo.sqlite`, `data/lab/models/XAUUSD` |
| BTC | `data/instruments/BTC/{forecast,scalp,ml}`, `data/lab/models/BTC` |
| Eksporty | `data/training/datasets/<INSTRUMENT>/<run>` |

Mapę wszystkich modeli (zadanie, TF, horyzont, strona, cechy, etykieta, trainer, loader, artefakt, status) znajdziesz w `MAPA_MODELI_I_TRENINGU.md`.

## 7. Czego trening nie robi
- Nie włącza na stałe `use_backfill_approx`. Próbki APPROX są używane tylko w tym jednym zadaniu ML, a model z nich nie zostaje automatycznie championem.
- Nie zmienia konfiguracji działającego bota ani aktywnego aktywa.
- Nie zapisuje haseł ani kluczy w logach ani w paczce.
- Nie uruchamia AUTO/LIVE i nie odblokowuje Execution Lock.
