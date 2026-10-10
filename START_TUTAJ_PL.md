# MasterQUO AI – START TUTAJ

Lokalna aplikacja Windows: Twój terminal MetaTrader 5 → silnik MasterQUO → agent Claude → ryzyko → monitor w przeglądarce
`http://127.0.0.1:8765`. Tryb wykonania wybierasz sam (SIGNALS „Analiza warunków” / PAPER / AUTO DEMO / AUTO LIVE) i program go pamięta;
przy pierwszym starcie jest **PAPER** (symulacja – żadnych zleceń do brokera).

## Wymagania
* Windows 10/11 64-bit, **Python 3.13 x64** (albo 3.12) z python.org z zaznaczonym „py launcher”.
* MetaTrader 5 zainstalowany, **uruchomiony i zalogowany**, symbol `XAUUSD-` widoczny w „Market Watch”.
* W MT5: Narzędzia → Opcje → Doradcy Expert → „Zezwalaj na handel algorytmiczny” – potrzebne dopiero do trybu DEMO/LIVE.
* Klucz API Anthropic (opcjonalny – bez niego działa wszystko poza agentem Claude).
* Node.js **nie** jest potrzebny (monitor jest już zbudowany).

## Kroki
1. Rozpakuj ZIP do nowego folderu, np. `C:\MasterQUO_AI` (nie nadpisuj starej paczki).
2. Kliknij **`01_INSTALUJ.bat`** – tworzy `.venv` w folderze projektu i instaluje przypięte pakiety. Log: `data\logs\instalacja_*.log`.
3. Kliknij **`02_DIAGNOSTYKA.bat`** – sprawdza Python, pakiety, połączenie z terminalem, symbol, rachunek, czas, klucz Claude.
   Nie składa zleceń. Wynik zapisuje w `data\logs`.
4. Kliknij **`03_START_MASTERQUO.bat`** – serwer startuje w osobnym oknie, przeglądarka otwiera monitor.
5. Przy pierwszym uruchomieniu monitor pokaże kreator: limity ryzyka, koszty (prowizja), klucz Claude i model.
   * Klucz wpisujesz **tylko w monitorze** (pole hasła) albo w oknie konsoli: `.venv\Scripts\python -m masterquo set-key` w folderze `backend`.
     Jest szyfrowany Windows DPAPI w `data\secrets.dpapi.json`. Nie wklejaj go nigdzie indziej.
   * Model: wybierz z listy pobranej z Twojego konta (przycisk „Testuj połączenie”) albo wpisz w `ANTHROPIC_MODEL`.
6. Zamknięcie przeglądarki **nie** zatrzymuje programu. Zatrzymanie: **`04_STOP_MASTERQUO.bat`** (zatrzymuje tylko MasterQUO,
   nie inne programy Pythona ani terminal MT5).

## Nowe w 1.2 – AUTO, 10 strategii, animowany monitor
* **AUTO — wybór strategii** (nagłówek): bot sam ocenia rynek (reżim), porównuje 10 strategii S01–S10 i wybiera główną. Kliknięcie
  przełącza AUTO/MANUAL. **Nie włącza zleceń** – to robi osobny tryb wykonania.
* Panele pod wykresami: „AUTO — wybór strategii” (reżim, wybrana strategia, powód, 3 najlepsze kandydatury, alternatywa, blokady),
  „Setupy na bieżąco” (WATCH/EARLY/CONFIRMED, punktacja, brakujące potwierdzenia, „Dlaczego nie ma setupu?”),
  „Strategie (10)” – przełączniki **Skanuj** i **Dopuść do handlu** dla każdej strategii.
* Żaba tańczy obok BALANCE. **Tło**: otrzymałem je jako statyczny obraz – aby było animowane, wgraj oryginalny GIF
  w ⚙ Ustawienia → **Wygląd** (tam FULL / LIGHT / OFF; przyciemnienie i widoczność GIF-ów – w 🎨).
* Powrót do poprzedniego zachowania: `ROLLBACK.md` (profil ORIGINAL: `08_PROFIL_ORIGINAL.bat`).

## Nowe w 1.3 – kolory, niezależny zoom, Decision Tree + XGBoost
* **Kolory** (🎨 w nagłówku): każdy kolor interfejsu i wykresów (tła, teksty, liczby, ikony, ramki, przyciski i ich stany, siatka, osie,
  celownik, korpusy/knoty/obrysy świec, wolumen, każda linia wskaźnika, wejście/SL/TP, statusy, checklista, PnL, połączenie). Picker
  HSV + HEX/RGB/HSL + przezroczystość, podgląd na żywo, **Zastosuj / Anuluj / Przywróć domyślne**, presety (Matrix zielony, Ciemny,
  Jasny, Wysoki kontrast), własne motywy, eksport/import JSON, ostrzeżenie o niskim kontraście. „Zakres zmian → Tylko wykres N”
  zmienia kolory jednego wykresu. Kolory zapisują się w przeglądarce i przetrwają odświeżenie i restart.
* **Jeden wykres = jeden zoom**: kółko/gładzik/przeciąganie działa tylko na wykresie pod kursorem. Przyciski nad wykresem: **+**, **−**,
  **Dopasuj**, **⇥ Najnowsza** (wraca do śledzenia nowych świec), **A** (auto-skala ceny), **⤢** pełny ekran. Synchronizacja zakresu
  jest domyślnie wyłączona – wybierz tę samą „grupę A/B” na wybranych wykresach; „Wspólny celownik” to osobny przełącznik.
  Nowe ticki, nowe świece, odświeżenie, zmiana koloru, zmiana rozmiaru okna nie resetują ręcznego widoku.
* **ML** (panel 7): zbiera każdy setup CONFIRMED (także odrzucone), sam etykietuje wynik netto wg planu setupu, trenuje Decision Tree
  i XGBoost w osobnym procesie, waliduje chronologicznie i promuje model tylko po spełnieniu kryteriów. **„Gotowy do nauki” ≠ wytrenowany.**
  Szczegóły: `docs/ML_DECISION_TREE_XGBOOST.md`.

## Nowe w 1.6 – wszystkie rynki i sygnały bota
Panel **Rynki · skaner** analizuje symbole z okna Market Watch Twojego terminala (trend, zmienność, IV walls) i uruchamia na nich
**strategie bota S01–S10** – kolumna „Setup bota”. Kliknij wiersz, żeby zobaczyć wykres rynku.
Panel **Sygnały bota** pokazuje potwierdzone setupy strategii (na XAUUSD- z silnika bota, na innych rynkach z tych samych strategii):
wejście, SL, TP, R:R; każdy sygnał jest rozliczany (win rate, wynik w R). Zlecenia składa nadal tylko symbol główny zgodnie z trybem wykonania.
Szczegóły: `docs/RYNKI_I_SYGNALY_BOTA.md`.

## Nowe w 1.3.1 – zmienność dzienna i IV walls
Na wykresach: **Daily Open**, **Daily High/Low** (oczekiwany zakres dnia ±1σ), PDH/PDL, High/Low dnia, progi straddle i **strefy IV walls ±1σ/±2σ**
(przełącznik „IV walls / Daily”). Panel „Zmienność dzienna · IV walls” pokazuje HV, IV, wycenę opcji 1-dniowych (premia, delta,
prawdopodobieństwa). MT5 nie ma opcji na złoto, więc IV = zmienność historyczna, chyba że wpiszesz IV w **Ustawienia → Zmienność / IV**.
To poziomy informacyjne – nie zmieniają strategii ani zleceń. Szczegóły: `docs/IV_WALLS_ZMIENNOSC_DZIENNA.md`.

## ML – krok po kroku
1. **Zbieraj dane** jest włączone domyślnie. Każdy potwierdzony setup to próbka; wynik (etykieta) pojawia się po zamknięciu scenariusza.
2. Opcjonalnie **Backfill z MT5 (30 dni)** – ta sama logika na historii z terminala; jakość APPROX, domyślnie *poza* treningiem.
3. Pierwszy trening startuje sam przy ≥ 1000 unikalnych setupów z etykietą i ≥ 100 w każdej klasie; kolejne po 250 nowych etykietach
   i ≥ 6 h. Postęp i dokładne braki widać w panelu („ETYKIETY_412/1000…”). **Trenuj teraz** pomija tylko czas oczekiwania –
   nie minimalne liczności bloków walidacji.
4. Model jest gotowy, gdy panel pokazuje **SHADOW** (liczy, nie wpływa) albo **ACTIVE** (tryb ML ASSIST). DEGRADED = jakość spadła,
   bot wraca do strategii bez ML. **Przywróć poprzedni model** cofa całość (model + preprocessing + kalibrator).

## Pozostałe skróty
* `05_TESTY_OFFLINE.bat` – testy na symulatorze (nie dotyka Twojego MT5); `05_TESTY_OFFLINE.bat --legacy` dodaje testy oryginalnej paczki.
* `06_DIAGNOZA_CZASU_MT5.bat` – surowe czasy ticków/świec i zmierzony offset serwera (uruchom przy otwartym rynku).
* `07_START_DEMO_DANE_SYNTETYCZNE.bat` – pokaz na danych z symulatora (wyraźny napis DANE SYNTETYCZNE, osobna baza).

## Trzy niezależne ustawienia (chip „WYKONANIE” w nagłówku)
1. **Wybór strategii**: AUTO / MANUAL – która strategia jest główna (nie składa zleceń).
2. **Tryb ML**: OFF / SHADOW (model liczy, nie wpływa) / ASSIST (model może odrzucić setup poniżej zwalidowanego progu).
3. **Tryb wykonania**:

| Tryb | Co robi | Jak włączyć |
|---|---|---|
| SIGNALS – „Analiza warunków” | tylko checklista, żadnych zleceń | jedno kliknięcie |
| PAPER | automatyczne wirtualne zlecenia na prawdziwych notowaniach | jedno kliknięcie (domyślny przy 1. starcie) |
| AUTO DEMO | automatyczne zlecenia na rachunku DEMO | rachunek DEMO odczytany z terminala + jednorazowo wpisz jego numer |
| AUTO LIVE | automatyczne zlecenia na prawdziwym rachunku | rachunek REAL odczytany z terminala + jednorazowo wpisz `LIVE <numer>` |

* W trybach AUTO **nie ma** potwierdzania każdej transakcji – obowiązują limity ryzyka i wszystkie bramki.
* Typ rachunku jest czytany z terminala. Gdy terminal przełączy się na inny rachunek albo typ się nie zgadza (np. AUTO DEMO na rachunku REAL),
  zlecenia są blokowane z dokładnym powodem – wybrany tryb zostaje zapamiętany.
* **STOP** zatrzymuje tylko nowe wejścia; zamykanie pozycji to osobny przycisk (⏻).

## Jak czytać monitor
* Zamiast sygnałów BUY/SELL panel 5 pokazuje **checklistę wejścia**: (1) co jest spełnione – z odczytami, (2) czego brakuje – z dokładnym
  zdarzeniem, na które czekamy („brak danych”, gdy brak danych), (3) wyzwalacz – poziom/strefa, interwał, wymóg zamkniętej świecy,
  (4) unieważnienie – poziom, zdarzenie, czas. Gdy nic nie ma: „Brak aktualnego scenariusza”. Otwarte pozycje są w zakładce Pozycje.
* Drzewo decyzji ma 8 bramek: dane, rynek, strategia, wyzwalacz, ryzyko, AI, **ML**, tryb – przy każdej powód blokady.
* „Jakość” to ocena punktowa, **nie** prawdopodobieństwo wygranej.
* Domyślne bramki są łagodne (kierunek z H1, RR od 1,0, Claude tylko jako weto). Wersję ścisłą MasterQUO włączysz w Ustawieniach – szczegóły w `MIGRACJA_I_ZMIANY.md`.

## Gdy coś nie działa
* „Brak .venv” → uruchom `01_INSTALUJ.bat`.
* „Terminal niepołączony” → uruchom i zaloguj MT5, potem przycisk „Połącz ponownie”.
* „Symbol XAUUSD- niedostępny” → dodaj go w Market Watch; program **nie** zamienia go na inny symbol.
* Czas „UNKNOWN/STORED_UNVERIFIED” → normalne przy zamkniętym rynku; `06_DIAGNOZA_CZASU_MT5.bat` przy otwartym rynku.
* Port 8765 zajęty → zmień `server.port` w `data\config.json`.
* Dokumenty: `ARCHITEKTURA.md`, `MAPA_WYMAGAN.md`, `RAPORT_TESTOW.md`, `ZNANE_OGRANICZENIA.md`, `MIGRACJA_I_ZMIANY.md`, `AUDYT_WEJSCIOWY.md`.

Aplikacja jest narzędziem badawczym. Strategie i modele nie mają zweryfikowanej skuteczności na Twoim rachunku – zacznij od SIGNALS i PAPER.
