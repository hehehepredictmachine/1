# PepeMarketWizard – START TUTAJ

> **1.13: nowa nazwa programu – PepeMarketWizard** (dawniej MasterQUO AI). Pliki startowe (`03_START_MASTERQUO.bat`, `04_STOP_MASTERQUO.bat`,
> `masterquo_start.bat`), folder `data\` i wewnętrzny pakiet `masterquo` mają **dawne nazwy celowo** – Twoja konfiguracja, baza, klucze
> i skróty działają bez zmian. „MasterQUO” pozostaje nazwą silnika strategii (S01–S12, specyfikacja MQ-SPEC).

## Nowe w 1.25 – eksport MT5 do treningu, Monte Carlo, scenariusz XAUUSD- 2,5–10 USD
Kolejność pracy (wszystko na rachunku DEMO albo w trybie SIGNALS / PAPER, dopóki sam nie zdecydujesz inaczej):
1. **Diagnostyka:** `02_DIAGNOSTYKA.bat` (terminal, symbol, czas serwera) i `DIAGNOSTYKA_TRENINGU.bat` (środowisko treningu).
2. **Eksport:** panel **AI Neural Lab → Trening → „Eksportuj dane z MT5”**: symbol brokera dokładnie taki jak w MT5 (np. `XAUUSD-`),
   okres (miesiące albo daty od–do), interwały (dla wszystkich modeli: M1, M5, M15, M30, H1, H4, D1), opcjonalnie ticki Bid/Ask z
   ostatnich dni. Postęp i „Przerwij” w karcie. Po zakończeniu tabela pokazuje dla każdego modelu: wymagane dane, plik, liczbę
   wierszy i stan (`GOTOWE` / `BRAK_DANYCH` / …). Przerwany eksport ma stan „przerwany” i **nie** jest proponowany do treningu – uruchom
   go ponownie do tego samego folderu, a dokończy się od miejsca przerwania. Wiersz poleceń (z folderu `backend`, `.venv`):
   `python -m masterquo training export --instrument XAUUSD --symbol XAUUSD- --months 12 --out "<folder>" [--from 2026-01-01 --to 2026-06-30] [--ticks-days 5]`.
3. **Trening na tym eksporcie:** w karcie „Użyj do treningu” (albo wybór eksportu w formularzu treningu), z wiersza poleceń
   `tools\trening.cmd run --instruments XAUUSD --dataset-xauusd "<folder eksportu>"`. Bez wskazania eksportu trening robi własny eksport
   jak dotąd (`00_TRENING_START.bat`). Modele aktywują się tylko po walidacji na Twoich danych.
4. **Walidacja Monte Carlo:** `31_MONTE_CARLO_WALIDACJA.bat` (przeciągnij folder eksportu na plik). Raport: wybrany wariant, Brier /
   log loss wobec modelu bazowego, krzywa kalibracji, werdykt. Kalibracja włącza się tylko przy przewadze na prawdziwych danych;
   cofnięcie: `python -m masterquo montecarlo rollback --instrument XAUUSD`. Bez kalibracji panel pisze „prawdopodobieństwo w modelu –
   nieskalibrowane”.
5. **Scenariusz XAUUSD- 2,5–10 USD:** **Trading Intelligence → „Scenariusz ruchu 2,5–10 USD”**. Poziomy 2,5 / 3 / 5 USD to TP1–TP3
   strategii SCALPING (zlecenia częściowe), 7,5 i 10 USD – tylko analiza. Osobno: ruch ceny, wolumen części, wynik w walucie rachunku,
   spread, prowizja, poślizg, P(TP przed SL) jako przedział (świeca, która dotknęła TP i SL, nie ma znanej kolejności), BE po
   potwierdzonym TP2. **Ruch ceny to nie zysk rachunku.** Prowizja nieznana = wynik netto „N/A” – wpisz prowizję swojego konta
   (Strategie → Ustawienia SCALPING → „Prowizja … na 1 lot na stronę”; AUTO DEMO / AUTO LIVE SCALPING i tak jej wymaga), konto Zero
   nie oznacza zerowych kosztów. TP3 SCALPING wybierzesz z 5 / 7,5 / 10 USD (Strategie →
   Ustawienia SCALPING). Karta niczego nie zleca – zlecenia składa cykl SCALPING zgodnie z wybranym trybem, przyciskiem STOP i limitami.
6. **Strefy High/Low M5/M15** po restarcie pokazują ostatnią zapisaną mapę z oznaczeniem „odtworzona / nieaktualna” do pierwszego przeliczenia.

## Nowe w 1.24 – aplikacja Windows `PepeMarketWizardDesktop.exe`
Paczka `PepeMarketWizard_DESKTOP_1_24_0.zip`: rozpakuj do **nowego** folderu (np. `C:\PepeMarketWizard_Desktop`) i uruchom
`PepeMarketWizardDesktop.exe`. Nie instalujesz Pythona ani Node.js – Python jest w paczce, składniki silnika aplikacja pobiera sama
przy pierwszym starcie (ok. 110 MB z PyPI, sprawdzane sumami SHA-256; wariant OFFLINE ma je w paczce).
* **Własne okno** z panelem: Trading Intelligence, AI Neural Lab, Centrum sterowania (plus wszystkie dotychczasowe widoki w menu).
* **Pierwszy start:** jeśli obok jest poprzednia instalacja, możesz skopiować jej dane (oryginał zostaje bez zmian) albo zacząć od
  zera. Tryb AUTO z kopii zamienia się na PAPER – tryb automatyczny wybierasz ponownie w Centrum sterowania.
* **Dane** są w `%LOCALAPPDATA%\PepeMarketWizard\data` (aktualizacja programu ich nie nadpisuje; przed nową wersją aplikacja robi
  kopię w `...\backups`). Tryb przenośny: plik `portable.txt` obok EXE.
* **Zamknięcie okna:** pytanie „działać w tle?” (ikona przy zegarze; tam „Zamknij aplikację”). Domyślne zachowanie i **autostart
  z Windows (domyślnie wyłączony)** ustawisz w Centrum sterowania → Praca aplikacji.
* **Telegram (opcjonalnie):** Centrum sterowania → MT5 i połączenia → Telegram – token bota (zapisywany lokalnie, szyfrowany), chat ID,
  język EN + 中文, sygnały / otwarcie i zamknięcie pozycji / dzienne podsumowanie, przycisk testu. Stan pokazuje, czy Telegram naprawdę
  przyjął wiadomość.
* Okno potrzebuje składnika Microsoft Edge **WebView2** (Windows 11 – wbudowany). Brak = aplikacja zaproponuje instalator albo otworzy
  panel w przeglądarce. EXE nie jest podpisany – SmartScreen może zapytać przy pierwszym uruchomieniu („Więcej informacji → Uruchom”).
* Dotychczasowe `PepeMarketWizard.exe` i pliki `.bat` nadal działają (trening, diagnostyka) – to wcześniejszy launcher, nie nowa aplikacja.
  W folderze aplikacji Windows używają **Pythona z paczki** (`runtime\python`, bez instalowania Pythona) i **tych samych danych co
  aplikacja** (`%LOCALAPPDATA%\PepeMarketWizard\data`; przy `portable.txt` – folder programu). Bota uruchamiaj przez
  `PepeMarketWizardDesktop.exe`; `03_START_MASTERQUO.bat` przy działającej aplikacji tylko otworzy jej panel.
  Szczegóły: `docs/DESKTOP_ARCHITEKTURA.md`.

## Najprościej: `PepeMarketWizard.exe` (1.16)
Uruchom `PepeMarketWizard.exe` z rozpakowanego folderu. Do wyboru masz:
- **1** – instalacja lub naprawa środowiska;
- **2 / 3 / 4** – kalibracja i trening XAUUSD / BTC / obu;
- **5** – kalibracja wskaźników kontekstu VAMD/FD/SMC i instalacja MQL5;
- **8 / 9** – start / stop bota;
- **R** – budżet RAM treningu (domyślnie 8 GB).

Launcher uruchamia te same pliki `.bat` co poniżej. Sam nie wysyła zleceń. Szczegóły i lista napraw: `docs/AUDYT_PACZKI_1_16_PL.md`.

## Nowe w 1.24 – Execution Lock wycofany (Twoja decyzja)
* Nie ma już osobnej blokady wykonania ani frazy odblokowania. O wysyłce zleceń decydują wyłącznie:
  * **tryb wykonania** – SIGNALS (bez zleceń), PAPER (symulacja), AUTO DEMO, AUTO LIVE; tryby AUTO wybierasz raz, z potwierdzeniem
    rachunku (AUTO LIVE: wpisz `LIVE <login>`), wybór jest pamiętany po restarcie;
  * **STOP** – zatrzymuje tylko nowe wejścia; otwarte pozycje są dalej prowadzone (BE, częściowe zamknięcia, zamknięcie);
  * limity ryzyka, aktualne notowania i warunki brokera.
* **Aktualizacja z wcześniejszej wersji:** jeśli zapisany był tryb AUTO DEMO / AUTO LIVE, który blokada dotąd wstrzymywała, program
  ustawia **PAPER** i pokazuje komunikat – tryb automatyczny wybierasz ponownie świadomie. Kopia starej konfiguracji:
  `data\config.v11.bak.json`. Tryb AUTO, który był już odblokowany, działa jak wcześniej.
* Tryb wykonania nie zmienia się przez zwykły zapis ustawień – tylko w Centrum sterowania → Tryb pracy lub przyciskiem „Wykonanie” (z potwierdzeniem).
* SCALPING / HEDGING w AUTO LIVE: nowe plany dopiero po zaliczonej walidacji tej strategii na Twojej historii (raport z
  `30_SH_WALIDACJA.bat`: dane z Twojego terminala, znana prowizja, co najmniej 30 cykli, dodatni wynik po kosztach). Bez tego panel
  pokazuje dokładny powód. Otwarte plany są zawsze prowadzone.

## Nowe w 1.14 – dwa aktywa (XAUUSD i BTC), laboratorium modeli
* *(Execution Lock z wersji 1.14 został wycofany w 1.24 – patrz wyżej.)*
* **1.14.2: `22_TRENUJ_WSZYSTKIE_MODELE.bat`** – jeden plik trenuje wszystkie modele (prognozy, scalp, ML, sieci lab XAUUSD/BTC) i uruchamia je w bocie.
* **1.14.1: bez blokad symboli.** Bot bierze symbole włączone na Twoim rachunku; gdy zapisanego nie ma, wybiera pasujący z Market Watch. BTC wykrywa się sam.
* **Aktywa w przełączniku: XAUUSD i BTC** (moduły lab, scenariusze i modele liczone per aktywo).
  * XAUUSD = Twój dotychczasowy symbol (`XAUUSD-`).
  * BTC trzeba raz potwierdzić: Ustawienia → Aktywa → BTC → „Szukaj kandydatów” → „Potwierdź”. Program pokazuje tylko symbole, których metadane terminala to BTC/USD.
  * Przełącznik XAUUSD/BTC jest w górnym pasku.
* **Menu ma 7 sekcji:** Pulpit, Wykresy, Setupy, Modele i trening, Badania i walidacja, Dane i diagnostyka, Ustawienia. Dawne strony są podstronami.
* **Pulpit pokazuje:**
  * kartę scenariusza – co spełnione, czego brakuje, unieważnienie;
  * aktywność modelu. Bez wytrenowanego modelu: „Sieć nieaktywna”.
* **Silnik S01–S12, scalp i gold_candles działają tylko dla XAUUSD.** Dla BTC działają scenariusze lab (tryb cienia).
* **Modele:** Modele i trening → „Uruchom badanie”. Wynik bez przewagi to `NO_VALIDATED_EDGE` – to uczciwy wynik, nie błąd.
* Szczegóły: `RUNBOOK_PL.md`, `VALIDATION_PROTOCOL.md`, `REQUIREMENTS_TRACEABILITY.md`, `DATA_REQUIREMENTS.md`.

## Nowe w 1.13 – panel w grupach, analityka BB/MA, FFT/EMD/VMD, Double Bottom
* Menu po lewej w trzech grupach: **Rynek** (Pulpit, Wykresy MTF, Kontekst rynku), **Analiza** (Setupy, Analiza AI, Indykatory,
  Analiza sygnału, Formacje i biblioteka), **Praca bota** (Pozycje i ryzyko, Dziennik i wyniki, Testy i raporty, Diagnostyka); Ustawienia na dole.
  Pierwsza strona to **Pulpit**. Dawne linki `#/ai`, `#/wykresy`, `#/warunki` działają.
* Nowy domyślny motyw „PepeMarketWizard – złoty” (ciemne tło, złote akcenty, świece biało-szare). Twój zapisany motyw zostaje; zmiana w 🎨 Wygląd.
* Analityka działa **obserwacyjnie** (nie zmienia decyzji, ryzyka ani blokady wykonania). Opis: `docs/ANALITYKA_BB_MA_VMD_FFT_EMD_DOUBLE_BOTTOM_PL.md`.

Lokalna aplikacja Windows: Twój terminal MetaTrader 5 → silnik MasterQUO → agent Claude → ryzyko → monitor w przeglądarce
`http://127.0.0.1:8765`. Tryb wykonania wybierasz sam (SIGNALS „Analiza warunków” / PAPER / AUTO DEMO / AUTO LIVE) i program go pamięta;
przy pierwszym starcie jest **PAPER** (symulacja – żadnych zleceń do brokera).
Od wersji 1.20 wybierasz też **ścieżkę główną** dla instrumentu (okno Tryb → „4. Ścieżka główna”): **S01–S12** albo **SCALPING / HEDGING**.
Tylko ścieżka główna otwiera nowe wejścia, druga jedynie analizuje. **Dopóki jej nie wybierzesz, bot nie otwiera żadnych nowych wejść**
(baner na górze panelu przypomina o wyborze); otwarte pozycje są dalej prowadzone.

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
4. Kliknij **`masterquo_start.bat`** (albo `03_START_MASTERQUO.bat`) – przeglądarka otwiera monitor. Licencja nie jest potrzebna (od 1.9).
5. Przy pierwszym uruchomieniu monitor pokaże kreator: limity ryzyka, koszty (prowizja), klucz Claude i model.
   * Klucz wpisujesz **tylko w monitorze** (pole hasła) albo w oknie konsoli: `.venv\Scripts\python -m masterquo set-key` w folderze `backend`.
     Jest szyfrowany Windows DPAPI w `data\secrets.dpapi.json`. Nie wklejaj go nigdzie indziej.
   * Model: wybierz z listy pobranej z Twojego konta (przycisk „Testuj połączenie”) albo wpisz w `ANTHROPIC_MODEL`.
6. Zamknięcie przeglądarki **nie** zatrzymuje programu. Zatrzymanie: **`04_STOP_MASTERQUO.bat`** (zatrzymuje tylko MasterQUO,
   nie inne programy Pythona ani terminal MT5).

## Nowe w 1.12 – scalp M5 Range → M1 Sweep → Retest + hedge + ML/NN (SHADOW)
1. `16_EKSPORT_HISTORII_SCALP.bat` – przy zalogowanym MT5 pobiera zamknięte M1/M5/M15/M30/H1 `XAUUSD-` (domyślnie 6 miesięcy).
2. `19_REPLAY_SCALP.bat` – replay po kosztach (też stres +50% i NETTING); `17_TRENING_SCALP_ML.bat` – trening A/B/C
   (LR, boosting, sieć MLP 64/32, kwantyle); `18_…` walidacja, `21_…` rollback. Prowizja domyślnie 0.50 za 1 lot na stronę (inna: argument, np. `17_TRENING_SCALP_ML.bat 3.5`).
3. `20_START_SCALP_SHADOW.bat` – monitor; Wykresy bota → „Scalp M5 Range → M1 Sweep → Retest + hedge” (MTF, Setup, Wskaźniki, Prognozy, Hedge/ryzyko, Trening).
Moduł **nie wysyła zleceń** (EXECUTION_AUTHORIZED=false). Opis: `docs/SCALP_HEDGE_ML_NN_PL.md`, raport: `research/scalp/RAPORT_SCALP_HEDGE_ML_NN.md`.

## Nowe w 1.11 – świece i prognozy 5/15/30 min (SHADOW)
1. `10_PROGNOZY_INSTALUJ.bat` – osobne środowisko dla modułu prognoz (główne `.venv` bez zmian).
2. `11_EKSPORT_HISTORII_XAUUSD.bat` – przy zalogowanym MT5 pobiera zamknięte M5/M30 `XAUUSD-` (domyślnie 12 miesięcy) i raport jakości danych.
3. `12_TRENING_MODELI_XAUUSD.bat` – trening i walidacja prognoz 5/15/30 min; `13_…` ponowna walidacja; `14_…` rollback modelu.
4. Monitor → Wykresy bota → „Świece i prognozy”: formacje, prognozy z oznaczeniem SHADOW i status modelu, checklista setupu Double Retest v2.
Prognoza **nie jest sygnałem** i nie daje zgody na zlecenie. Opis: `docs/PROGNOZY_SWIECE_GOLD_CANDLES_PL.md`.

## Nowe w 1.10 – trzy strony monitora
Menu po lewej (na telefonie – trzy przyciski na dole):
1. **Analiza AI** – co proponuje AI, dlaczego, na co czeka; wykresy H1, M30, M15, M5, M1. Obok karta „Pozwolenie silnika” – sama propozycja AI nie składa zleceń.
   Bez klucza ANTHROPIC_API_KEY karta pokazuje „AI niedostępne” (klucz ustawiasz lokalnie). Analiza AI uruchamia się tylko przyciskiem „Analizuj teraz”.
2. **Wykresy bota** – wszystkie interwały, których używa silnik (D1…M1), z rolą i stanem danych. Kliknij TF na pasku, aby go powiększyć (Skupienie).
3. **Warunki setupu** – lista setupów i pełna checklista: „Spełniono X z Y warunków wymaganych”, co brakuje, trigger, unieważnienie, plan.
   Klikanie setupów tylko je pokazuje; strategię silnika zmieniasz wyłącznie w karcie „Działanie bota – wybór strategii silnika”.
Pozycje, zlecenia i statystyki: przycisk **Pozycje i statystyki** u góry; dziennik: **Logi**; rachunek i AUTO/MANUAL: **Konto ▾**.
Walls: źródło jest zawsze na etykiecie – HV-proxy (przybliżenie z historii brokera) albo IV (import / ręcznie). S12 i S11 domyślnie tylko skanują.

## Nowe w 1.7 – sygnały z planem wejścia, M30/H8, EMA20 Pullback
Blok „Sygnał AI / plan wejścia” obok checklisty, historia sygnałów, kontekst M30/H8 i układ 8 wykresów, strategia S11 (tylko skanowanie).
Od 1.9 program działa bez licencji. Szczegóły: `CHANGELOG.md`, `INSTRUKCJA_WINDOWS_PL.md`, `docs/archiwum/AUDYT_MASTERQUO.md`.

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
4. **Ścieżka główna** (per instrument): S01–S12 albo SCALPING / HEDGING – tylko ona otwiera nowe wejścia; bez wyboru żadna.
   Na rachunku typu NETTING strategia HEDGING działa dopiero po walidacji replay na Twojej historii (zamiast pozycji przeciwnej
   częściowo zamyka pozycję – REDUCE); do tego czasu jest zablokowana z podanym powodem.
* Od 1.21 limity dziennej straty i liczby otwartych pozycji obejmują **obie ścieżki łącznie** (obowiązuje ostrzejszy z ustawionych
  limitów); po ich osiągnięciu bot nie otwiera nowych wejść do końca dnia UTC lub do zamknięcia pozycji.

## Jak czytać monitor
* Pełna checklista konkretnego setupu jest na stronie **Warunki setupu**; checklista 12A silnika – tamże, sekcja „Sygnał silnika”.
* Zamiast sygnałów BUY/SELL checklista wejścia pokazuje: (1) co jest spełnione – z odczytami, (2) czego brakuje – z dokładnym
  zdarzeniem, na które czekamy („brak danych”, gdy brak danych), (3) wyzwalacz – poziom/strefa, interwał, wymóg zamkniętej świecy,
  (4) unieważnienie – poziom, zdarzenie, czas. Gdy nic nie ma: „Brak aktualnego scenariusza”. Otwarte pozycje są w zakładce Pozycje.
* Drzewo decyzji ma 8 bramek: dane, rynek, strategia, wyzwalacz, ryzyko, AI, **ML**, tryb – przy każdej powód blokady.
* „Jakość” to ocena punktowa, **nie** prawdopodobieństwo wygranej.
* Domyślne bramki są łagodne (kierunek z H1, RR od 1,0, Claude tylko jako weto). Wersję ścisłą MasterQUO włączysz w Ustawieniach – szczegóły w `MIGRACJA_I_ZMIANY.md`.
* Od 1.22 na stronie **Wykresy bota** (i w Analizie AI) jest przełącznik **„Strefy H/L + profil sesji”**: strefy szczytów/dołków M5/M15,
  poziomy dnia i sesji, POC/VAH/VAL. Strefa jest rysowana od chwili potwierdzenia; prowizoryczna ma przerywaną ramkę i dopisek „PROW.”.
  Najedź kursorem na strefę, by zobaczyć typ, status, wynik, testy i źródło wolumenu. Wolumen to aktywność tickowa brokera (nie wolumen
  giełdowy), a wynik 0–100 to opis zbieżności, **nie** prawdopodobieństwo. Strefy nie składają zleceń – szczegóły w
  `docs/ZONE_ENGINE_ARCHITECTURE.md`.
* Od 1.23 jest **nowy monitor** (Trading Intelligence, AI Neural Lab, System Control Center): w bocznym menu kliknij **„Nowe panele”**
  albo otwórz adres monitora z końcówką `#/trading-intelligence`. Nagłówek pokazuje środowisko (LIVE / DEMO / SYNTHETIC / HISTORY /
  UNKNOWN), stan MT5 (kliknij, by zobaczyć szczegóły połączenia), świeżość danych, instrument, tryb wykonania i stan STOP – wszystko
  z backendu bota; bez połączenia z botem stany zmieniają się na DISCONNECTED / UNKNOWN zamiast pokazywać stare wartości. To **etap 1**:
  sekcje paneli są jeszcze puste i oznaczone „etap N – nie zintegrowane” (wykresy, sygnały, modele 3D i sterowanie dochodzą w kolejnych
  etapach). Nowy monitor niczego nie zmienia w pracy bota; dotychczasowy monitor działa jak wcześniej (link „Istniejące widoki”).

## Gdy coś nie działa
* „Brak .venv” → uruchom `01_INSTALUJ.bat`.
* „Terminal niepołączony” → uruchom i zaloguj MT5, potem przycisk „Połącz ponownie”.
* „-6 Terminal: Authorization failed” → zaloguj rachunek w MT5 („Zapisz hasło”) albo podaj login / serwer / hasło w Ustawienia → MT5 (hasło tylko lokalnie);
  przy kilku instalacjach MT5 wpisz ścieżkę `terminal64.exe`.
* „Symbol XAUUSD- niedostępny” → dodaj go w Market Watch; program **nie** zamienia go na inny symbol.
* Czas „UNKNOWN/STORED_UNVERIFIED” → normalne przy zamkniętym rynku; `06_DIAGNOZA_CZASU_MT5.bat` przy otwartym rynku.
* Port 8765 zajęty → zmień `server.port` w `data\config.json`.
* Dokumenty: `ARCHITECTURE.md`, `COMPONENT_INVENTORY.md`, `REFACTOR_PLAN.md`, `MAPA_WYMAGAN.md`, `RAPORT_TESTOW.md`, `ZNANE_OGRANICZENIA.md`, `MIGRACJA_I_ZMIANY.md`; starsze raporty w `docs/archiwum/`.

Aplikacja jest narzędziem badawczym. Strategie i modele nie mają zweryfikowanej skuteczności na Twoim rachunku – zacznij od SIGNALS i PAPER.
