# Raport 1.25.0 – eksport MT5 → trening, Monte Carlo, strefy M5/M15, scenariusz XAUUSD- 2,5–10 USD

Zakres: `PepeMarketWizard_PROMPT_MONTE_CARLO_STREFY_STRATEGIA.md`. Audyt przed zmianami: `docs/AUDYT_MC_STREFY_EKSPORT_PL.md`.
Punkt powrotu: commit `a10d97a` (1.24.1); kod eksportu użyty jako „przed” w porównaniu: `0a57370`.

**Środowisko prac:** Linux, symulator terminala (`FakeMT5`), Chromium do testów panelu. **Nie było** Windows, zalogowanego MT5,
Twojej historii notowań ani rachunku DEMO. Każda liczba poniżej pochodzi z danych syntetycznych (`SYNTHETIC_TEST`) i sprawdza kod,
a nie rynek. Żaden model nie został wytrenowany na Twoich danych; żadne zlecenie (DEMO ani LIVE) nie zostało wysłane.

## 1. Co zbudowano i które pliki zmieniono

| Obszar | Co działa teraz | Pliki |
|---|---|---|
| Eksport MT5 → dataset (4A) | plik stanu `EXPORT_STATUS.json`; zapis atomowy; `source_metadata.json` usuwany na starcie i zapisywany jako ostatni; wznowienie po uszkodzonej partii; `real_volume`; ticki Bid/Ask (partie 1 h, ticki o tym samym czasie zachowane); zakres dat; sprawdzenie konwencji czasu serwera (DST) na historii; czytelne błędy | `backend/masterquo/forecast/export.py`, `training/cli.py`, `__main__.py`, `mt5/fake.py` (symulator: `copy_ticks_range`) |
| Wymagania modeli | `MODEL_DATA_READINESS.json` w każdym eksporcie: model → interwały / ticki → plik → wiersze → stan | `training/requirements.py` |
| Trening na gotowym eksporcie | `--dataset-xauusd` / `--dataset-btc`, wybór eksportu w panelu, zadanie `monte_carlo` w runnerze | `training/runner.py`, `training/cli.py`, `api/app.py` |
| Eksport z panelu | karta „Eksportuj dane z MT5” (postęp, przerwanie, tabela gotowości, „Użyj do treningu”), proces potomny tylko do odczytu | `training/export_job.py`, `frontend/.../ai-neural-lab/components/ExportCard.tsx`, `AiNeuralLabPage.tsx`, `terminal.css` |
| Monte Carlo (nowy moduł) | ścieżki z całych świec (IID / blokowe / reżim ATR + godzina sesji), tylko dane sprzed oceny, P(TP przed SL) po stronie Bid/Ask, przedział dla świecy z TP i SL, błąd z liczby ścieżek; walidacja walk-forward z embargo vs klimatologia, Brier / log loss / kalibracja / CI, kalibrator izotoniczny, rejestr + rollback; własny wątek w bocie; API + CLI | `backend/masterquo/montecarlo/{engine,validate,service,cli}.py`, `runtime.py`, `api/app.py`, `31_MONTE_CARLO_WALIDACJA.bat` |
| Strefy High/Low M5/M15 | po restarcie ostatnia mapa z bazy, `RESTORED` + `STALE` do pierwszego przeliczenia (nie potwierdza decyzji); reszta (swing z `confirmed_at`, cykl życia, łączenie M5/M15, konflikty, zapis) istniała i ma testy | `zones/service.py` |
| Scenariusz SCALPING 2,5–10 USD | poziomy 2,5 / 3 / 5 (TP1–TP3) i 7,5 / 10 (analiza); osobno ruch, wolumen części, wynik w walucie rachunku, spread, prowizja, poślizg; P(TP przed SL) ostrożnie–optymistycznie; BE po potwierdzonym TP2; modele każdy ze swoim zdarzeniem; brak łączenia procentów; powód braku zlecenia | `sh/scenario.py`, `api/app.py` (`GET /api/v1/sh/scenario`), `frontend/.../trading-intelligence/components/ScenarioCard.tsx` |
| Konfiguracja SCALPING | TP3 XAUUSD z listy 5 / 7,5 / 10 USD (domyślnie 5 – bez zmian), poziomy scenariusza, **pole prowizji w panelu** (puste = nieznana); walidacja; BTC bez progów XAUUSD | `config/sh_strategies_v1.json`, `sh/config.py`, `frontend/src/components/ShPanels.tsx` |
| Porównanie przed / po | skrypt odtwarzający scenariusze eksportu na dowolnej wersji kodu + replay SCALPING z TP3 5 / 7,5 / 10 | `audit/repro/porownanie_przed_po_1_25.py`, `audit/repro/wyniki_1_25_*.json` |
| Testy | nowe: `test_export_mt5` (10), `test_ui_export` (4), `test_montecarlo` (13), `test_sh_scenario` (10); rozszerzone: `test_zones`, `test_ui_terminal_shell`, `test_sh_api`, `test_forecast_integration` | `tests/` |
| Dokumentacja | `CHANGELOG.md`, `START_TUTAJ_PL.md`, `ROLLBACK.md` §11, `MAPA_MODELI_I_TRENINGU.md/.json` (+ Monte Carlo), `INTEGRATION_MAP.md`, `docs/PEPE_UI_API_MAP.md` §8, ten raport | – |
| Wersja i paczki | 1.25.0: `version.py`, launcher `PepeMarketWizard.exe` (ten sam stary launcher, przebudowany z numerem 1.25.0), aplikacja `PepeMarketWizardDesktop.exe` | `tools/build_release.py`, `tools/launcher/main.go`, `desktop/main.go`, `desktop/winres/winres.json` |

Nie zmieniono: trybów SIGNALS / PAPER / AUTO DEMO / AUTO LIVE, przycisku STOP nowych wejść, limitów użytkownika, logiki zleceń SCALPING
(`sh/setup.py`, `replay.py`, `lifecycle.py`, `risk.py`, `executor.py`, `service.py` – identyczne z 1.24.1). Execution Lock nie wraca.

## 2. Modele: działające / SHADOW / niewytrenowane / wymagające danych

Stan na koniec prac **w tym środowisku** (bez Twoich danych). „Działa” = kod liczy wynik na bieżących danych bota; nie oznacza, że
wynik ma wartość prognostyczną.

| Grupa | Modele / moduły | Stan |
|---|---|---|
| Deterministyczne – działają bez treningu | jakość danych, silnik ryzyka SH, kalendarz makro, reżim `regime_v2`, struktura `structure_v2`, pullback + SMC, VAMD, Katz FD, ATR + StopDistance, świece i formacje, płynność (sesje, heatmapa), Heikin Flow + S/R, FFT/EMD/VMD, strefy HLZE / DSVIE / UZICE, modele MM (Align Mean, Kalman, Breakout + RobustVol, Multi-Indicator, SMC FVG/IDM) | działają (MM tylko obserwacja – nie głosują) |
| Monte Carlo ścieżek | `montecarlo` | działa jako **prawdopodobieństwo w modelu – nieskalibrowane**; kalibracja możliwa dopiero po `montecarlo validate` na Twoim eksporcie z przewagą nad modelem bazowym |
| SHADOW (kod gotowy, w bocie tylko obserwacja / ocena) | prognozy gold_candles, Scalp A/B/C, Lab (LOGREG/TREE/MiniRocket/XGB/ResNet1D/SEW-SNN), kontekst SAR + IQ, Scalp ML XGBoost, Neural Scalp TCN, Structure Intelligence, Flow context, Context indicators, MM (GPR, HDC, event engine, STE-FlowNet), legacy ML (DT + XGBoost) | **niewytrenowane na Twoich danych** – po treningu pozostają SHADOW do pozytywnej walidacji |
| Model zdarzenia strategii | `sh_tp_model` – P(TP2 przed SL) SCALPING / HEDGING | **NOT_TRAINED** – bez niego SCALPING działa w trybie OGRANICZONYM (score, nie prawdopodobieństwo); AUTO LIVE wymaga tego modelu |
| Wymagające danych | wszystkie trenowalne – wymagania per model w tabeli §3 i w `MODEL_DATA_READINESS.json` Twojego eksportu | eksport z Twojego MT5 |

## 3. Błędy instalacji, eksportu i treningu – odtworzone i naprawione

### 3.1 Porównanie przed / po (ten sam skrypt, ten sam symulator)
Polecenie: `python audit/repro/porownanie_przed_po_1_25.py export --backend <kod>/backend --out <plik>`; wyniki:
`audit/repro/wyniki_1_25_eksport_przed.json` (kod `0a57370`) i `..._po.json` (1.25).

| # | Błąd (audyt) | Przed (odtworzone) | Po |
|---|---|---|---|
| E1 | folder aplikacji bez `MANIFEST_SHA256.txt` – launcher i instalatory przerywały pracę (Twój zrzut ekranu) | błąd „Niekompletny folder programu” | naprawione w 1.24.1; paczka 1.25.0 też ma manifest (test statyczny) |
| E2 | `.bat` w folderze aplikacji szukały systemowego Pythona i zapisywały do innego `data` | analiza kodu | naprawione w 1.24.1 (Python z paczki, wspólny folder danych) |
| E3 | eksport na symulatorze oznaczony `REAL_USER_DATA` | 9 testów czerwonych | naprawione w 1.24.0 + test regresji |
| E4 | awaria w trakcie eksportu + uszkodzona partia → wznowienie | `JSONDecodeError: Expecting ',' delimiter` – wznowienie niemożliwe bez ręcznego kasowania | wznowienie kończy się kodem 0, stan `COMPLETE`, partia pobrana ponownie (test: pliki identyczne z eksportem bez awarii) |
| E5 | nieudany ponowny eksport do użytego folderu | wyjątek, ale **`source_metadata.json` ze starego eksportu zostaje – folder wygląda na kompletny** | kod 8, `EXPORT_STATUS.json` = `FAILED`, metadane usunięte, `usable = false`; trening odmawia |
| E6 | brak `real_volume` | kolumny brak | kolumna `real_volume` na końcu CSV (puste, gdy terminal jej nie zwraca; dla CFD zwykle 0 lub puste – opis w raporcie jakości; `tick_volume` opisany jako liczba ticków, nie wolumen) |
| E7 | ticki nie trafiają do datasetu | `TypeError` (brak opcji) | `--ticks-days N`: 1 558 ticków z 0,1 dnia, 183 sąsiednie ticki o tym samym czasie zachowane, 0 cofnięć czasu |
| E8 | zakres tylko w miesiącach | `TypeError` (brak opcji) | `--from / --to` (test z przełączeniem DST 2026-03-08) |
| E9 | brak uprawnień / miejsca / terminala → surowy wyjątek | analiza kodu | komunikat z przyczyną i zalecanym krokiem (testy: brak terminala, symbolu, prawa zapisu) |
| E10 | brak informacji „który model może się trenować z tego eksportu” | brak pliku | `MODEL_DATA_READINESS.json` + tabela w panelu |
| nowy | AUTO DEMO / AUTO LIVE SCALPING wymagają znanej prowizji, a panel nie miał pola prowizji (tylko API) | brak pola | pole „Prowizja … na 1 lot na stronę” w ustawieniach strategii (puste = nieznana; < 0 odrzucone) |
| nowy | `30_SH_WALIDACJA.bat`: przy braku `.venv` komunikat zawierał `^&` – skrypt **nie kończył się** i próbował uruchomić brakujący Python | analiza skryptu | blok `if … ( … exit /b 2 )` |
| nowy | nazwa modelu „SMC … (73%)” mogła wyglądać na skuteczność | – | „głębokość cofnięcia 73% – parametr, nie skuteczność” |

Nie odtworzono (wymaga Windows / Twojego MT5): limit „Maks. słupków na wykresie”, `copy_ticks_range` u Twojego brokera, dwie instalacje
MT5, uprawnienia NTFS, antywirus.

### 3.2 Model → wymagane dane MT5 → faktyczny eksport → wynik treningu
Przebieg rzeczywisty (nie opis): eksport syntetyczny 2 mies. XAUUSD- (wszystkie interwały + ticki 1 dzień) →
`python -m masterquo training run --demo --profile TEST_INSTALACJI --instruments XAUUSD --dataset-xauusd <eksport>`.
Run `TR-20261027T193553Z-d334`: **18/19 zadań ukończonych, 0 modeli dopuszczonych do SHADOW, brak aktywacji** (dane syntetyczne =
modele techniczne). Pominięte: przekazanie do bota (bot nie działał). Prowizja w eksporcie: nieznana.

Faktyczny eksport: M1 87 570 · M5 17 514 · M15 5 838 · M30 2 919 · H1 1 459 · H4 364 · D1 59 świec; ticki 16 559 (2 072 o tym samym
czasie – zachowane); rewizje 0, błędna geometria 0. Gotowość: wszystkie 13 zadań `GOTOWE`, przy M5 uwaga „< 20 000 zalecanych”.

| Model (zadanie) | Wymagane dane MT5 (zalecane wiersze) | Eksport (stan) | Wynik treningu na danych syntetycznych |
|---|---|---|---|
| Prognozy gold_candles (`forecast`) | M5 + M30 (20 000 M5) | GOTOWE, M5 poniżej zalecanych | ukończone; horyzont 1 świeca: SHADOW_UNVALIDATED, 3 i 6: odrzucone; loader zgodny |
| Scalp A / B / C (`scalp`) | M1 (60 000) | GOTOWE | A: SHADOW_UNVALIDATED (1/3/5 min); B: za mało danych (0 cykli z cechami); C: za mało danych (0 decyzji w holdout) |
| Legacy ML DT + XGBoost (`ml`) | M1, M5, M15, H1, H4, D1 (60 000) | GOTOWE | 1 356 etykiet; oba modele odrzucone przez walidację |
| Lab (`lab`) | M5 (20 000) | GOTOWE, M5 poniżej zalecanych | NO_VALIDATED_EDGE; 2 rodziny zapisane tylko do badań |
| Kontekst SAR + IQ (`indicator_context`) | M1, M5, M15 (60 000) | GOTOWE | za mało danych (0 cykli); warianty SAR/IQ wymagają archiwum wskaźników z MT5 |
| Scalp ML XGBoost (`ml_scalp`) | M1 (60 000) | GOTOWE | za mało dowodów (0 kandydatów) |
| Neural Scalp TCN (`neural_scalp`) | M1, M5, M15, H1 (60 000) | GOTOWE | za mało dowodów (0 próbek) |
| Structure Intelligence (`structure_intelligence`) | M1, M5, M15, H1 (60 000) | GOTOWE | wszystkie zadania: za mało dowodów |
| Flow context (`flow_context`) | M1 (60 000) | GOTOWE | za mało dowodów / brak przewagi |
| Context indicators (`context_indicators`) | M5 (20 000) | GOTOWE, M5 poniżej zalecanych | kalibracja wykonana; brak zwalidowanej przewagi |
| SCALPING / HEDGING (`sh_models`) | M1 (+ M5/M15/H1 opcjonalnie, ticki opcjonalnie) (60 000) | GOTOWE | replay ograniczony w profilu testowym do 6 000 M1: SCALPING 3 setupy, HEDGING 1 – model zdarzenia: za mało danych → **sh_tp_model nie powstał** |
| Master models (`master_models`) | M1, M5 (+ M15, M30) (60 000) | GOTOWE | 6 modeli wytrenowanych technicznie; żaden nie przeszedł walidacji |
| Monte Carlo (`monte_carlo`) | M1 (+ ticki) (40 000) | GOTOWE | wariant BLOCK; Brier skalibrowany 0,2134 vs bazowy 0,2048, CI95 różnicy [0,0007; 0,0167] – **gorzej od modelu bazowego** → kalibracja nieaktywna |

Wniosek: łańcuch eksport → dataset → trening → zapis w rejestrze → raport działa dla wszystkich 13 rodzin; na danych syntetycznych
żaden model nie ma przewagi (tak powinno być – symulator nie zawiera przewidywalnej struktury). Wynik na Twoich danych wymaga
eksportu z Twojego MT5 i profilu `PELNY_TRENING` (12 mies.).

## 4. Jak uruchomić

Wszystko na rachunku **DEMO** albo w trybie SIGNALS / PAPER. Nie wklejaj nigdzie hasła ani klucza – program ich nie potrzebuje
(MT5 musi być zalogowany w terminalu).

| Krok | Panel | Plik / wiersz poleceń (folder `backend`, `.venv`) |
|---|---|---|
| Diagnostyka | Centrum sterowania → Diagnostyka | `02_DIAGNOSTYKA.bat`, `DIAGNOSTYKA_TRENINGU.bat` |
| Eksport | AI Neural Lab → Trening → „Eksportuj dane z MT5” | `python -m masterquo training export --instrument XAUUSD --symbol XAUUSD- --months 12 --out "<folder>" [--from 2026-01-01 --to 2026-06-30] [--ticks-days 5]` |
| Trening | „Użyj do treningu” albo wybór eksportu w formularzu | `tools\trening.cmd run --instruments XAUUSD --dataset-xauusd "<folder eksportu>"` (bez eksportu: `00_TRENING_START.bat`) |
| Walidacja modeli | AI Neural Lab → Walidacja / raport runu | raport `data\training\runs\<run>\report.html` |
| Walidacja Monte Carlo | – | `31_MONTE_CARLO_WALIDACJA.bat` (przeciągnij folder eksportu) albo `python -m masterquo montecarlo validate --dataset "<folder>"`; cofnięcie: `python -m masterquo montecarlo rollback --instrument XAUUSD` |
| Monte Carlo na żywo | Trading Intelligence → karta scenariusza | `GET /api/v1/montecarlo/scenarios?horizon=60`, `POST /api/v1/montecarlo/run` |
| Strategia XAUUSD- | Trading Intelligence → „Scenariusz ruchu 2,5–10 USD”; Strategie → SCALPING (setup, plan, ustawienia TP3 i prowizji) | `GET /api/v1/sh/scenario?strategy=SCALPING&volume=0.1` |

## 5. Testy uruchomione, porównanie przed / po, ograniczenia

_W toku: pełny zestaw `tools/run_tests.py` – wynik zostanie uzupełniony po zakończeniu przebiegu._

### 5.1 Monte Carlo – walidacja na danych syntetycznych
Polecenie `python -m masterquo montecarlo validate` na eksporcie syntetycznym 3 mies. (M1 + M5 + M15 + H1, ticki 2 dni), zdarzenia
BUY/SELL × TP 2,5 / 5 USD przy SL 3 USD, horyzont 60 świec M1, krok 30, 500 ścieżek, walk-forward CAL 50 % / TEST 50 % z embargo.
Wynik: `audit/repro/wyniki_1_25_montecarlo_walidacja_syntetyczna.json`.

| Wariant | Brier CAL | Brier TEST | log loss TEST |
|---|---|---|---|
| model bazowy (klimatologia) | 0,2225 | 0,2182 | 0,6269 |
| IID (wybrany na CAL) | 0,2222 | 0,2201 | 0,6320 |
| blokowy | 0,2232 | 0,2180 | 0,6263 |
| reżim | 0,2460 | 0,2394 | 0,7476 |
| IID + kalibracja izotoniczna | – | **0,2153** | 0,6200 |

Różnica Brier (skalibrowany − bazowy) na TEST: 95 % CI [−0,0057; −0,00004] – minimalnie lepiej od klimatologii, ale na danych
syntetycznych (błądzenie losowe symulatora). Werdykt: **TEST_TECHNICZNY** – kalibracja niezapisana jako aktywna, nic nie mówi o rynku
złota. Warunek aktywacji pozostaje: Twoje dane + przewaga nad modelem bazowym.

### 5.2 SCALPING – replay z TP3 = 5 / 7,5 / 10 USD (dane syntetyczne)
Ten sam kod co na żywo, zmienia się tylko TP3; 30 000 ostatnich świec M1 eksportu syntetycznego; spread ze świec, poślizg 0,05 USD na
stronę, **prowizja nieznana – nieuwzględniona**. Wynik: `audit/repro/wyniki_1_25_scalping_tp3_syntetyczne.json`.

| TP3 | cykle | wynik średni R (CI90) | trafienie TP1 / TP2 / TP3 | wyjścia | model naiwny R (CI90) |
|---|---|---|---|---|---|
| 5 USD (domyślnie) | 16 | +0,41 (−0,16; +1,01) | 50 % / 50 % / 44 % | TP3 7, SL 8, BE 1 | −0,02 (−0,13; +0,09) |
| 7,5 USD | 15 | +0,56 (−0,11; +1,22) | 53 % / 53 % / 20 % | TP3 3, SL 7, BE 2, czas 3 | +0,01 (−0,10; +0,13) |
| 10 USD | 15 | +0,54 (−0,13; +1,19) | 53 % / 53 % / 13 % | TP3 2, SL 7, BE 3, czas 3 | +0,03 (−0,08; +0,15) |

Wniosek: przy 15–16 cyklach każdy przedział obejmuje 0 – **brak dowodu przewagi** którejkolwiek opcji TP3, a dane są syntetyczne.
Domyślne TP3 = 5 USD pozostaje; 7,5 i 10 USD są do wyboru i do sprawdzenia replayem na Twoim eksporcie.

### 5.3 Ograniczenia
* Brak Windows, MT5, Twojej historii, rachunku DEMO – eksport, trening, Monte Carlo i strategia sprawdzone na symulatorze.
* Kolejność TP/SL w jednej świecy jest znana tylko z ticków; bez ticków panel pokazuje przedział, replay liczy ostrożnie (SL).
* Wynik w walucie rachunku liczony z `trade_tick_value` terminala (odpowiednik `order_calc_profit` dla bieżącego kursu); różnica
  kursowa waluty rachunku i swap nie są uwzględnione w scenariuszu.
* `real_volume` dla CFD na złoto zwykle wynosi 0 u brokera – wtedy nie ma wolumenu giełdowego; `tick_volume` nie jest wolumenem.
* Model `sh_tp_model` niewytrenowany – SCALPING w trybie OGRANICZONYM; AUTO LIVE niedostępny do czasu treningu i walidacji.

## 6. Co wymaga Twojego Windows, MT5, rachunku DEMO lub dodatkowych danych; jak cofnąć zmiany

1. **Windows + MT5:** rozpakuj paczkę 1.25.0, uruchom `PepeMarketWizardDesktop.exe` (albo dotychczasowy folder i `01_INSTALUJ.bat`),
   zaloguj MT5, `02_DIAGNOSTYKA.bat`.
2. **Eksport z Twojego MT5:** karta „Eksportuj dane z MT5”, symbol dokładnie `XAUUSD-`, 12 mies., wszystkie interwały, ticki 5–10 dni.
   W MT5: Narzędzia → Opcje → Wykresy → „Maks. słupków na wykresie” ustaw na „Unlimited” (inaczej M1 będzie krótsze – raport to pokaże).
3. **Prowizja:** Strategie → Ustawienia SCALPING → prowizja Twojego konta na 1 lot na stronę (z umowy / historii transakcji).
4. **Trening + walidacja:** „Użyj do treningu” → raport runu; `31_MONTE_CARLO_WALIDACJA.bat` na tym samym eksporcie.
5. **DEMO:** dopiero po Twojej decyzji – tryb AUTO DEMO w Centrum sterowania (potwierdzenie rachunku); wcześniej SIGNALS / PAPER.
6. **Cofnięcie:** `ROLLBACK.md` §11 – paczka 1.24.1 na tych samych danych (bez migracji konfiguracji i bazy); kalibracja Monte Carlo:
   `montecarlo rollback`; TP3 / prowizja: Strategie → Ustawienia → „Przywróć poprzednią”.
