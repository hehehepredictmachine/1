# Audyt: Monte Carlo, strefy M5/M15, eksport MT5 → trening, strategia XAUUSD- 2,5–10 USD (1.24.1 → 1.25)

Zakres: `PepeMarketWizard_PROMPT_MONTE_CARLO_STREFY_STRATEGIA.md`. Punkt powrotu: commit `0a57370` (lokalny tag `pre-montecarlo-1.24.0`;
serwer nie przyjmuje tagów – commit jest na gałęzi), poprzedni: `ba7a5d5`. Środowisko audytu: Linux, symulator terminala (`FakeMT5`);
**bez Windows, bez zalogowanego MT5, bez historii użytkownika** – wszystko oznaczone niżej jako „sprawdzone na symulatorze” nie jest
sprawdzeniem na Twoim terminalu.

## 1. Stan komponentów (kod, nie jakość modeli)

| Komponent | Plik | Stan przed zmianami |
|---|---|---|
| Eksport historii do treningu | `forecast/export.py` (`export_candles`), `training/cli.py export`, `training/runner.py t_export/t_quality` | **istnieje i działa** (partie 31 dni z punktem kontrolnym, rewizje OHLC odrzucane, geometria, luki, offset serwera → UTC, DST NY_CLOSE/UNIFORM, prowizja z historii transakcji); runner czyta jawny katalog SWOJEGO runu |
| Eksport M5/M30 prognoz, M1–H1 scalp | `export-candles`, `export-scalp`, `11_/16_*.bat` | ten sam kod co wyżej (`kind`) – bez duplikatu |
| Eksport 8 TF M06R | `diagnostics.export_history` (`masterquo export`) | osobny format dla narzędzi M06R (nie dla treningu) |
| Archiwum ticków | `lab/tick_store.py` (przez bridge bota) | istnieje, **niepodpięte do datasetu treningu** |
| Wykrywanie terminali / symboli | `training/cli.py detect/installed_terminals/choose_symbol` | istnieje (bez podmiany symbolu) |
| Markov / Monte Carlo | `lab/flow_context/markov.py` (Markov3, MarkovDiff + 2048 ścieżek) | istnieje, SHADOW, artefakt tylko po `flow-context train-markov`; **symuluje wyłącznie skumulowaną zmianę zamknięć** – brak high/low ścieżki, więc **brak P(TP przed SL)**; brak porównania z modelem bazowym i bootstrapem blokowym |
| Strefy High/Low | `zones/hlze.py` + `zones/uzice.py` + `zones/service.py` | **istnieją i działają**: swing M5/M15 z `confirmed_at` (pivot znany po `right` świecach), PROVISIONAL→ACTIVE→TESTED→WEAKENED→SWEPT→BROKEN→EXPIRED, zmiana roli, równe szczyty/dołki, dzień/sesja, konsolidacja, łączenie M5/M15 z zachowaniem członków, konflikty, zapis map i zdarzeń w SQLite, `as_of` |
| SCALPING / HEDGING | `sh/*`, `config/sh_strategies_v1.json` | istnieje: TP 2,5/3/5 USD (SCALPING), BE po potwierdzonym TP2 = wejście + koszty, udziały 50/30/20 z wariantem 2 części, raport niemożliwego podziału, model zdarzenia P(TP2 przed SL) – trenowany tylko na danych klienta |
| Tablica dowodów modeli | `mm/fusion.py` | istnieje – **nie łączy** procentów różnych zdarzeń (zgodne z wymaganiem) |
| Modele z artefaktami | – | **żaden model nie jest wytrenowany w tym środowisku** (brak historii klienta); wszystkie rodziny: kod gotowy, status „wymaga danych” |

## 2. Odtworzone błędy (eksport / instalacja)

| # | Błąd | Odtworzenie | Skutek |
|---|---|---|---|
| E1 | Folder aplikacji Windows: brak `MANIFEST_SHA256.txt` | zrzut użytkownika (launcher), testy statyczne | launcher i 3 instalatory kończyły pracę – **naprawione w 1.24.1** |
| E2 | `.bat` w folderze aplikacji szukały systemowego Pythona i zapisywały do `<program>\data` | analiza kodu | trening niewidoczny dla aplikacji – **naprawione w 1.24.1** |
| E3 | Eksport `--demo` oznaczany `REAL_USER_DATA` (`is_fake` za proxy) | pełny zestaw testów | **naprawione w 1.24.0** (przed wydaniem) |
| E4 | Uszkodzony plik partii (przerwany zapis) → wznowienie kończy się surowym `JSONDecodeError` | symulator: obcięty plik `chunks/M5_*.json`, ponowny eksport | eksportu nie da się wznowić bez ręcznego usuwania plików |
| E5 | Pliki CSV, metadane i raport zapisywane w miejscu (nie atomowo); po nieudanym ponowieniu zostaje stary `source_metadata.json` | j.w. | **niepełny eksport wygląda na kompletny** |
| E6 | Brak `real_volume` w CSV (MT5 je zwraca) | analiza kodu | brak danych do oceny wolumenu (gdy broker go podaje) |
| E7 | Ticki Bid/Ask nie trafiają do datasetu (`ticks: NOT_EXPORTED`) | analiza kodu | brak tickowej oceny kolejności TP/SL w świecy |
| E8 | Zakres tylko w miesiącach (1–36) | CLI | brak wyboru dat od–do |
| E9 | Brak uprawnień / brak miejsca → surowy wyjątek | analiza kodu | komunikat nie mówi, co zrobić |
| E10 | Brak tabeli „model → wymagane dane → plik → status” dla konkretnego eksportu | panel/CLI | użytkownik nie wie, który model może się trenować |

Nie odtworzono (wymaga Windows/MT5): rzeczywisty limit „Maks. słupków na wykresie”, zachowanie `copy_ticks_range` u brokera, dwie
instalacje MT5, brak uprawnień NTFS, antywirus.

## 3. Plan zmian

1. **Eksport (4A):** atomowy zapis plików i statusu (`EXPORT_STATUS.json`: `IN_PROGRESS` → `COMPLETE` / `FAILED`, metadane zapisywane
   na końcu), odporność na uszkodzone partie (pobranie ponownie), `real_volume`, opcjonalne ticki Bid/Ask (`copy_ticks_range`, partie
   godzinowe, półotwarte zakresy `[od, do)` – ticki o tym samym czasie zostają, kolejność zachowana), zakres `--from/--to`, czytelne błędy
   (uprawnienia, miejsce, terminal, symbol), wymagania modeli + sprawdzenie datasetu (`GOTOWE / BRAK_DANYCH / NIEZGODNY_FORMAT`),
   API + przycisk „Eksportuj dane z MT5” w panelu Modele i trening (postęp, przerwanie, raport, przejście do treningu).
2. **Monte Carlo:** silnik ścieżek świec (OHLC względem otwarcia) z trzema wariantami – bazowy IID, bootstrap blokowy, warunkowany
   reżimem/sesją – oraz istniejący MarkovDiff do porównania; tylko dane przed `as_of`; zdarzenia `P(TP przed SL w H)` dla BUY/SELL po stronie
   Bid/Ask z kosztami; świeca dotykająca TP i SL = niejednoznaczna (ticki, gdy są; inaczej jawna reguła); walidacja walk-forward (Brier,
   log loss, kalibracja) z wyborem wariantu na danych, osobno „prawdopodobieństwo w modelu” i „skalibrowane”.
3. **Strefy:** odtworzenie ostatniej mapy z bazy po restarcie (do pierwszego przeliczenia), status w API; reszta istnieje – testy.
4. **Strategia 2,5–10 USD:** rozszerzenie SCALPING (nie nowy system): scenariusze ruchu 2,5 / 3 / 5 / 7,5 / 10 USD z oceną MC, kalkulator
   (ruch, wolumen, wynik w walucie rachunku z kalkulatora terminala, spread, prowizja, poślizg – brak = „brak danych”), tablica modeli
   (użyte / SHADOW / niewytrenowane) bez łączenia procentów.
