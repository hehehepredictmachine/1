# CHANGELOG

## 1.22.0 – Mapa stref PMW: High/Low Zone Engine + Daily Session Volume Intelligence + jedna mapa stref (ANALYTICAL_ONLY)
* **HLZE** (`zones/hlze.py`): strefy swingów M5/M15 (pivoty z `strategies/indicators`, istotność w ATR), pivoty prowizoryczne
  vs potwierdzone (`confirmed_at` = zamknięcie świecy pivot + right; nic nie jest datowane wstecz), granice knot–korpus z limitem
  szerokości (WIDE / odrzucenie), cykl życia ACTIVE → TESTED → WEAKENED / SWEPT / BROKEN / EXPIRED (przełamanie wyłącznie zamknięciem,
  sweep = knot + zamknięcie z powrotem, więcej testów = słabsza strefa), zmiana roli w BREAKOUT/BREAKDOWN_LEVEL, równe szczyty/dołki
  (płynność wyłącznie wnioskowana), poziomy poprzedniego dnia, poprzedniej sesji (`analytics/session_engine`), dnia bieżącego, konsolidacji.
* **DSVIE** (`zones/dsvie.py`): źródło wolumenu zawsze podane (TICK_VOLUME = aktywność brokera, nie wolumen globalny ani agresorów;
  order flow / footprint / arkusz = UNAVAILABLE), profile sesji z DST (POC, VAH/VAL 70%, HVN/LVN, ścieżka i migracja POC), stany
  DEVELOPING / COMPLETED / INVALID / STALE, wolumen względny tej samej sesji w tym samym czasie, kontekst sesji, strefy popytu/podaży
  tylko z dowodami (odrzucenie + przemieszczenie + kontekst; typ dowodu przy każdym).
* **UZICE** (`zones/uzice.py`, `zones/engine.py`): jedna mapa stref `PMW-ZONE-1.0` – łączenie tylko tej samej polaryzacji, zachowane
  pochodzenie, konflikty, punktacja 25/25/20/15/10/5 bez podwójnego liczenia, kary; wynik nie jest prawdopodobieństwem
  (`confidence_status` = UNVALIDATED).
* **ZoneService + API:** przeliczenie raz na zamkniętą M5, stabilne id, dziennik zdarzeń bez duplikatów, widok historyczny `as_of`;
  `GET /api/v1/zones/{map,status,events,profiles,context}`.
* **Ocena setupów (SHADOW):** `zone_context` każdego setupu; silna strefa przeciwna bliżej niż 1 R po kosztach → REDUCE w ocenie
  SHADOW (tylko przy danych OK); mapa późniejsza niż decyzja jest odrzucana. **Wykonanie bez zmian.**
* **ML:** schemat cech MQ-FEAT-1.1.0 = 1.0.0 + 26 cech stref z tego samego silnika; trener przyjmuje próbki 1.0.0 i 1.1.0; model 1.0.0
  ładuje się dalej (poprawka: wcześniej zmiana wersji schematu zablokowałaby czempiona). Bez automatycznego retreningu i promocji.
* **Wykres:** opcja „Strefy H/L + profil sesji” (Wykresy bota, Analiza AI) – strefy od chwili potwierdzenia, prowizoryczne przerywane
  z dopiskiem „PROW.”, POC/VAH/VAL, podpowiedź pod kursorem (typ, TF, status, wynik, testy, czas potwierdzenia, źródło wolumenu).
* Dokumenty: `docs/ZONE_ENGINE_ARCHITECTURE.md`, `docs/HIGH_LOW_ZONE_ENGINE.md`, `docs/DAILY_SESSION_VOLUME_ENGINE.md`,
  `docs/ZONE_AI_INTEGRATION.md`, `docs/ZONE_ENGINE_TEST_REPORT.md`. Walidacja predykcyjna na danych klienta – jeszcze niewykonana.

## 1.21.0 – Domknięcie planu po audycie: wspólny strażnik portfela, metryki, rozkład wyników, master models w pętli, O5, O8
* **Wspólny strażnik portfela (§23, Definition of Done 8):** nowe wejścia każdej ścieżki są sprawdzane względem dzisiejszego zrealizowanego
  wyniku i otwartych pozycji **obu** ścieżek (S01–S12 + SCALPING/HEDGING), wobec ostrzejszego z dwóch skonfigurowanych limitów
  (`PORTFOLIO_DAILY_LOSS_LIMIT`, `PORTFOLIO_MAX_OPEN_POSITIONS`). Błąd odczytu stanu portfela = brak nowych wejść. Zarządzanie pozycjami
  i transakcje ręczne bez zmian.
* **Metryki §22** w `/api/v1/stats` → `engines`: średni zysk i strata, maksymalny drawdown (pieniądze i R), błąd standardowy średniego R,
  rozbicie per strategia i per miesiąc.
* **Raport oceny setupów:** empiryczne częstości „TP przed SL / SL przed TP / żaden poziom w horyzoncie” z przedziałem Wilsona,
  mediana czasu utrzymania, log loss obok Briera.
* **Master models (AR-08):** inferencja na każdej zamkniętej świecy M5 we własnym wątku SHADOW (bez luk w ledgerze, także przy
  zamkniętym panelu); dryf kalibracji prognozy GPR liczony przez `mm/drift.py` (od 200 ocenionych prognoz).
* **O8:** promocja legacy ML wymaga zysku Briera ponad wskaźnik bazowy większego niż 2 błędy standardowe (jak `sh_tp_model`);
  modele ocenione przed 1.21 wymagają retreningu przed promocją. Działający czempion bez zmian.
* **O5:** sześć starszych raportów (ARCHITEKTURA, AUDIT, AUDIT_REPORT, AUDYT_MASTERQUO, AUDYT_WEJSCIOWY, RAPORT_1_3) przeniesione do
  `docs/archiwum/` z indeksem; treść bez zmian, odnośniki poprawione.

## 1.20.0 – Decyzje po audycie: ścieżka główna (O1), REDUCE na netting (O3), ocena SHADOW rozszerzona (O2, O4, O6)
* **Zmiana zachowania (O1):** na każdym instrumencie nowe wejścia otwiera tylko wybrana ścieżka główna – S01–S12 albo SCALPING/HEDGING
  (okno Tryb → „4. Ścieżka główna”, `POST /api/v1/mode/primary-path`, zapis w konfiguracji i w `settings_audit`). Druga ścieżka nadal
  analizuje setupy, ale ich nie wykonuje (`NOT_PRIMARY_PATH_*`). **Dopóki ścieżka nie jest wybrana, żadna nie otwiera nowych wejść**
  (`PRIMARY_PATH_NOT_SELECTED`, baner w panelu). Otwarte pozycje obu ścieżek są zarządzane; transakcje ręczne bez zmian.
* **O3:** HEDGING na rachunku NETTING działa bez pozycji przeciwnej – zdarzenie hedge kończy się częściowym zamknięciem (REDUCE).
  Dopuszczone dopiero po zaliczonej walidacji replay wariantu REDUCE na historii klienta (REAL_USER_DATA, n ≥ 30, wynik oczekiwany > 0);
  bez niej HEDGING na netting pozostaje zablokowany z podanym powodem. Profil: `hedge.netting_alternative` (REDUCE | BLOCK).
* **O2:** raport oceny pokazuje gotowość do ASSIST per silnik (cel 200 dojrzałych ocen z prawdopodobieństwem, Brier vs wskaźnik bazowy);
  ocena pozostaje SHADOW.
* **O4:** każda ocena zapisuje reżim obu definicji (MarketRegimeEngine i RegimeMachine v2); raport zestawia pary reżimów z wynikiem planu.
* **O6:** maszyna scalp Range→Sweep→Retest (SHADOW) jest trzecim źródłem ledgera ocen (zdarzenie TP1 przed SL; także kandydaci BLOCKED/MISSED).
* Test `test_ui_lab` (Swing Inspector): czekał na pojawienie się ramki, a nie na treść dociąganą osobnym zapytaniem – pod obciążeniem
  odczytywał „…”; czeka teraz na identyfikator swingu.

## 1.19.0 – Audyt architektury (Faza A) + wspólna ocena setupów (SHADOW)
* **Poprawka bezpieczeństwa (AR-01):** SCALPING/HEDGING respektuje STOP (kill switch), Execution Lock i powody wiązania rachunku z
  `ModeManager` – wcześniej czytał tylko nazwę trybu i po STOP otwierał nowe plany. Otwarte plany są nadal zarządzane. Test: `tests/test_arch_fixes.py`.
* Audyt architektury oparty na grafie importów i pomiarze wykonania (pętla bota 12 min + panel w Chromium): `ARCHITECTURE.md`,
  `COMPONENT_INVENTORY.md`, `INTEGRATION_MAP.md`, `REFACTOR_PLAN.md` (ustalenia AR-01…AR-16, decyzje O1–O8, stan Definition of Done).
* Nowy pakiet `backend/masterquo/evaluation` (SHADOW, bez dostępu do ścieżki zleceń – test statyczny):
  wspólny kontrakt `SetupCandidate`/`SetupAssessment` (lookahead = błąd kontraktu), ocena P nazwanego zdarzenia, EV netto, próg p* = L/(G+L)
  z kosztów i R:R, przedział Wilsona, jakość wykonania, konflikt portfela; ledger każdego setupu obu ścieżek (także zablokowanych) z
  dojrzewaniem wyniku z zamkniętych M1 (TP przed SL, MFE/MAE, wynik planu netto; świeca niejednoznaczna = SL).
* Widok łącznej ekspozycji obu ścieżek (tylko odczyt) i statystyki per silnik + łącznie (`/api/v1/stats` → nowe pole `engines`;
  pole `bot` bez zmian). API: `/api/v1/eval/status|assessments|report|exposure`.
* Test `test_nss` (kolejka NSS): warunek oczekiwania na odrzucenie starego zadania był spełniony przez wcześniejsze odrzucenia, co pod
  obciążeniem dawało wyścig z wątkiem roboczym; test czeka teraz na nowe odrzucenie.
* Zachowanie decyzji S01–S12 i SCALPING/HEDGING bez zmian poza AR-01. Zmiany zmieniające zachowanie bota czekają na decyzję użytkownika
  (`REFACTOR_PLAN.md` §4). LIVE zablokowany.

## 1.18.0 – Master models (XXX.rar): audyt, integracja, trening – SHADOW/OBSERVE
* Nowy pakiet `backend/masterquo/mm`: wspólne kontrakty wyjść (execution_allowed zawsze false), snapshot danych z sha256, splity chronologiczne
  z purge/embargo i jednorazowym holdoutem, niezmienne artefakty (promocja wyłącznie VALIDATED_SHADOW, rollback), ledger predykcji z dojrzewaniem etykiet, drift.
* Moduły: Align Mean, Kalman crossover, Breakout Zones + Robust Volatility, Tick Session Volume Profile, Multi-Indicator Strategy Pro, SMC BoS/IDM/FVG,
  HDC, GPR (Matérn 3/2), event engine (GRU + state stack, OpenCL), S3CE/STFS, STE-FlowNet, BUZOA (+ PSO/DE/Random), Math Fidelity Benchmark, tablica dowodów.
* Orchestrator 16 zadań (`python -m masterquo mm train`), zadanie `master_models` w runnerze treningu, API `/api/v1/mm/*`, ekran „12 Master Models”
  w panelu Neural Cyberpunk, narzędzie agenta `get_master_models` (prompt `MQAI-AGENT-PROMPT-2.1.0`, wiedza MM-K01..K06).
* Native MQL5 (`mql5/MasterModels`, `mql5/MathFidelity`): wskaźniki i EA bez handlu, self-test parytetu, 3 silniki benchmarku – nieskompilowane (brak MetaEditora).
* 6 pozycji bez specyfikacji w paczce (SDOm, Quant Momentum, Renko, H&S v2, Data Grabber, Chart Sync) – BLOCKED.
* Trening wykonany wyłącznie na danych syntetycznych: brak VALIDATED_SHADOW, `NO_VALIDATED_EDGE`. Raport: `docs/MASTER_MODELE_AUDYT_INTEGRACJA_PL.md`.

## 1.17.2 – Neural System: animowany, interaktywny mózg
* Okno Neural System (panel Neural Cyberpunk → Dashboard) powiększone do 640 px, z trybem pełnoekranowym (Esc zamyka).
* Animacja Canvas: sieć neuronów w kształcie mózgu (kontur, bruzdy kory, móżdżek, duże neurony z dendrytami), impulsy na połączeniach,
  paralaksa i „synapsy” do kursora; respektuje `prefers-reduced-motion`.
* Jasne neurony = moduły z rejestru `/api/v1/training/models` (kolor wg gotowości); najechanie pokazuje opis, kliknięcie przypina.
  Tło i impulsy są dekoracją – nie przedstawiają inferencji (opisane w legendzie).

## 1.16.0 – aktualizacje PMW-UPD 02–09, 11, 14 (kod; trening rynkowy i native nieuruchomione)
* Wdrożone sekwencyjnie według rejestru `docs/updates/update_registry.json`. Każda pozycja ma osobne statusy: kod / źródło / dane / trening / artefakty / native / edge.
  * 02 IQ/PAL/SAR (PARTIAL), 03 ML scalp, 04 Neural Scalp, 05 MTF dashboard, 06 heatmapa likwidacji + boxy sesji;
  * 07/08 Structure Intelligence + neutralizacja/SEW/kwotowania;
  * 09 SpikingBrain Finance / MiniRocket v2 (+ native MQL5) / reżim / SMMA / Z-Score;
  * 11 Markov + Heikin Flow + kanały S/R + StopDistance;
  * 14 VAMD + bounded Katz FD + Pullback/SMC (BoS/CHoCH/IDM/x) + Buffer Inspector.
* Nowe launchery 25–29; runner treningu ma 16 zadań; prompt agenta `MQAI-AGENT-PROMPT-2.0.0`.
* Wszystkie nowe modele działają w trybie SHADOW/OBSERVE, bez automatycznej promocji. Execution Lock bez zmian, brak zleceń.
* Bez REAL_USER_DATA i bez MetaEditora: trening rynkowy `NOT_RUN`, native `NOT_EXECUTED`, `NO_VALIDATED_EDGE`.
* **Naprawy treningu po zgłoszeniach (audyt `docs/AUDYT_PACZKI_1_16_PL.md`):**
  * czytelna przyczyna błędu eksportu;
  * akceptacja złota CFD zgłaszanego jako base=USD;
  * kontrola kompletności rozpakowania;
  * budżet RAM 8 GB ze skalowaniem próbki zamiast pomijania zadań;
  * automatyczna instalacja i walidacja `.venv_candles`.
* **`PepeMarketWizard.exe`** – launcher: instalacja, kalibracja + trening, kalibracja kontekstu, diagnostyka, start/stop bota, budżet RAM.
* Specyfikacje 01 (BB), 10, 12, 13 i 15 (EA) nie zostały dostarczone. Status BLOCKED, algorytmów nie rekonstruowano.

## 1.15.0 – instalatory treningu XAUUSD / BTC (`PepeMarketWizard_TRENING_XAUUSD_BTCUSDT.zip`)
* **Jeden wspólny mechanizm** `masterquo/training`, wywoływany przez cienkie launchery:
  * `00_TRENING_START.bat` (menu), `INSTALUJ_TRENING.bat`, `TRENUJ_XAUUSD.bat`, `TRENUJ_BTCUSDT.bat`, `TRENUJ_OBA.bat`, `DIAGNOSTYKA_TRENINGU.bat`;
  * `22_TRENUJ_WSZYSTKIE_MODELE.bat` (zgodność argumentów: prowizja dotyczy teraz tylko XAUUSD);
  * panel: Modele i trening → „Trening XAUUSD / BTC”.
* **Profile instrumentów** (`config/instruments_v1.json`): canonical_asset jest oddzielony od dokładnego symbolu brokera.
  * USD ≠ USDT; XAUT/PAXG/WBTC są odrzucane.
  * Domyślny symbol BTC to `BTCUSDT-`, z weryfikacją w terminalu, bez cichej zamiany.
* **Eksport per instrument** (M1–D1, porcjami, wznawialny, metadane, SHA256, jakość danych, prowizja z historii transakcji).
* **Cały łańcuch dla BTC:**
  * gold_candles (grid 500 jako hipoteza);
  * scalp A/B/C (profil BTC = reguły XAUUSD, wszystkie progi względne);
  * legacy ML (osobna baza `data/instruments/BTC/ml/ml.sqlite`, strumień setupów z symbolem BTC);
  * lab.
  * Osobne rejestry; XAUUSD zostaje w dotychczasowych katalogach.
* **Bot:**
  * ForecastService, ScalpService i ML przełączają model, profil i rejestr razem z aktywnym instrumentem;
  * SHADOW zapisuje kolumnę `instrument` (migracja 0015).
* **Lab:**
  * zapisywany jest **ten sam model, który oceniono** (fit na danych rozwojowych), bez refitu na train+holdout dziedziczącego status;
  * kontrola zgodności loadera i odrzucenia innego aktywa;
  * wskaźnik aktywnego modelu per rodzina i rollback.
* **Prognozy:**
  * zgodność loadera porównuje prawdopodobieństwa z pipeline'em treningowym na tych samych rekordach, nie tylko ich sumę;
  * model odrzucony nie zastępuje aktywnego (dotyczy też scalp).
* **APPROX tylko per zadanie:** `use_backfill_approx` nie jest już włączane w konfiguracji bota. Model z próbek APPROX ma status `RESEARCH_APPROX` i nie zostaje championem.
* **Statusy w trzech osiach** (wykonanie / jakość / integracja), udokumentowane kody wyjścia, wznawianie, anulowanie i blokada drugiego runu.
* **Raport HTML/JSON** z liczbami z bieżącego runu.
* **Dokumenty:** `MAPA_MODELI_I_TRENINGU.md/.json`, `START_TUTAJ_TRENING_PL.md`, `docs/schemas/*.schema.json`.
* **Bez zmian:** trening nie wysyła zleceń (eksport ma zablokowane funkcje zleceń), Execution Lock nienaruszony.

## 1.14.2 – jeden plik do treningu wszystkich modeli: `22_TRENUJ_WSZYSTKIE_MODELE.bat`
* Jedno uruchomienie (`python -m masterquo train-all`) wykonuje po kolei:
  1. start bota w tle, jeśli nie działa, i oczekiwanie na MT5;
  2. prognozy gold_candles: eksport M5/M30, trening z planem, przeładowanie w bocie;
  3. scalp ML/NN A/B/C: eksport M1–H1, trening (prowizja 0,50/lot/stronę lub z parametru), replay wariantów;
  4. ML Decision Tree / XGBoost: próbki z historii (APPROX – jawnie włączone; `--ml-no-approx` wyłącza) i trening;
  5. modele lab dla XAUUSD i BTC: wszystkie rodziny (LOGREG, drzewo, MiniRocket, XGBoost, ResNet1D, SEW-SNN, eksperymenty PCA/GMM/neutralizacja).
* Kroki zablokowane (np. za mało danych) są raportowane i nie zatrzymują kolejnych.
* Raport: `data/logs/trening_wszystkiego_<czas>.json`.
* Bot uruchamia teraz **wszystkie** zapisane modele lab danego aktywa na każdej zamkniętej świecy M5:
  * Pulpit → „Wszystkie modele” (wynik, czas, rola);
  * wybór modelu do wizualizacji; sieć neuronowa jest domyślnie pokazywana jako główna.
* Bez zmian: żadnego zlecenia, Execution Lock nienaruszony, modele bez zaliczonej walidacji działają w trybie badawczym (bez wpływu na decyzje).

## 1.14.1 – bez blokad symboli: bot pracuje na symbolach włączonych na rachunku
* Twoja zgłoszona usterka: na Twoim MT5 pojawiało się „SYMBOL_NOT_ALLOWED:DATA:XAUUSD-”, a dane z terminala przestały płynąć.
  Przyczyna: w 1.14.0 metadane kontraktu `XAUUSD-` u brokera nie przeszły reguły XAU/USD, a to blokowało cały symbol.
* Zmiana na Twoją prośbę:
  * **żadnych blokad po symbolu** – dane, analiza, skaner rynków (Market Watch jak przed 1.14), API i powiadomienia działają na włączonych symbolach;
  * metadane są tylko informacją;
  * gdy zapisanego symbolu nie ma u brokera, bot sam bierze pasujący symbol z rachunku (najpierw z Market Watch, z pominięciem XAUT, PAXG i WBTC);
  * BTC jest wykrywany automatycznie (status `AUTO_DETECTED`), bez potwierdzania;
  * symbol wpisany w Ustawieniach (MT5) znów działa i staje się symbolem aktywnego aktywa.
* **Bez zmian:** Execution Lock (blokada wysyłania zleceń) zostaje domyślnie włączony. Odblokowanie: Ustawienia → Execution Lock.

## 1.14.0 – dwa aktywa XAUUSD / BTC, Execution Lock, moduły badawcze M01–M42, protokół walidacji, panel 7 sekcji, aktywność sieci
* **Dwa aktywa:**
  * `assets/registry.py` – XAUUSD i BTC (allowlista) na wejściu danych (bridge), w API, treningu, skanerze, powiadomieniach i wykonaniu;
  * mapowanie symbolu brokera wyłącznie po metadanych (currency_base/profit, kontrakt), np. XAUT/PAXG ≠ XAU, WBTC ≠ BTC, BTCUSDT nie jest zakładany;
  * potwierdzenie przez użytkownika, fingerprint kontraktu (zmiana blokuje aktywo);
  * przełącznik w górnym pasku przełącza feed, cechy, modele, checklistę, wykresy i statystyki.
* **Execution Lock:**
  * proxy modułu MT5 w workerze odrzuca każde `order_send` (dowolna ścieżka, także bezpośrednie API i Trade Pad);
  * menedżer pozycji tylko odczytuje i rozlicza;
  * bramka i tryby pokazują `EXECUTION_LOCKED`;
  * odblokowanie tylko frazą w Ustawieniach; migracja ustawia LOCKED.
* **Moduły lab** (`lab/`, wszystkie na zamkniętych świecach, z `origin_time`/`confirmed_at`):
  * Markov, mapa reżimów, reżim zmienności, struktura swingów, trendlinie, płynność, sesje (zoneinfo/DST), ICT sweep→MSS→FVG→retest;
  * strefy S/D z trwałym zapisem (transakcja + snapshot + .bak), Memory Sequence;
  * SMMA(3) H/L, hipotezy Z-score, PSAR (wspólna implementacja), Stochastic Daily Breakout, quiet drift;
  * ACD i kinematyka z ticków (`copy_ticks_from`), ekstrapolator Fouriera z archiwum prognoz;
  * Repaint Inspector, drift CUSUM, bootstrap blokowy, Trade Pad (tylko symulacja).
* **Modele** (numpy, bez torch):
  * MiniRocket (clean-room), ResNet1D/ResNeXt (sprawdzenie gradientu), SEW-SNN z LIF, gradientem zastępczym, karą energetyczną i routingiem wg reżimu;
  * LOGREG/TREE/XGB, eksperymenty PCA/GMM/neutralizacja.
* **Protokół walidacji MQ-LAB-VAL-1.0.0:**
  * holdout z hashem i jednorazowym dostępem, walk-forward z purgingiem i embargo;
  * rejestr wszystkich prób, kontrole negatywne, kryteria promocji ustalone wcześniej;
  * werdykty INSUFFICIENT_EVIDENCE / NO_VALIDATED_EDGE;
  * artefakty z manifestem, blokadą aktywa i schematu oraz sumą kontrolną.
* **Scenariusze lab** (dla obu aktywów, tryb cienia): setup_id, checklista, trigger, unieważnienie; kompletność checklisty, wynik modelu i prawdopodobieństwo są rozdzielone.
* **Panel – 7 sekcji:**
  * Pulpit, Wykresy, Setupy, Modele i trening, Badania i walidacja, Dane i diagnostyka, Ustawienia; dotychczasowe strony jako podstrony;
  * Neural Network Activity z telemetrii tej samej inferencji: architektura, aktywacje, raster spike'ów; brak modelu → „Sieć nieaktywna”;
  * odpowiedzi dla nieaktywnego aktywa są odrzucane.
* **Naprawy wykryte przy przełączaniu aktywów:**
  * cache analityki 1.13 bez symbolu;
  * bufory bridge poprzedniego symbolu;
  * S01–S12, scalp i gold_candles dla BTC – jawnie niedostępne.
* **Migracje:** konfiguracja v11 (kopia `config.v10.bak.json`), baza 0014 (`lab_zones`, `lab_forecasts`, `lab_repaint`, `lab_trials`, `lab_holdout_access`, `lab_snapshots`).
* **Dokumenty:** AUDIT, RESEARCH_SOURCES, REQUIREMENTS_TRACEABILITY, ARCHITECTURE, VALIDATION_PROTOCOL, VALIDATION_RESULTS, MODEL_CARDS/, DATA_REQUIREMENTS, RUNBOOK_PL.
* **Ograniczenia:**
  * żaden model ani scenariusz nie jest zwalidowany rynkowo (brak historii MT5 w środowisku budowania);
  * źródła MQL5 i prace naukowe były niedostępne z sieci – implementacje własne.

## 1.13.0 – PepeMarketWizard: panel w grupach, wspólny silnik BB/MA, FFT/EMD/VMD, Double Bottom z biblioteką, audyt
* **Nowa nazwa: PepeMarketWizard** (monitor, tytuły, komunikaty, paczka `PepeMarketWizard_KLIENT_1_13_0.zip`). Pakiet `masterquo`, folder `data\`,
  klucze przeglądarki i nazwy plików `.bat` bez zmian (zgodność z istniejącą konfiguracją i skrótami).
* **Panel:** menu w grupach Rynek / Analiza / Praca bota; nowe strony Pulpit, Kontekst rynku, Indykatory, Analiza sygnału, Formacje i biblioteka,
  Pozycje i ryzyko, Dziennik i wyniki, Testy i raporty, Diagnostyka (istniejące moduły zachowane i wpięte); domyślny motyw złoty (#0F1214 / #D8B45F,
  świece biało-szare) dla nowych instalacji; „DANE PRZYKŁADOWE” w trybie demo; Pulpit startowy.
* **Wspólny silnik BB/MA** `analytics/ta.py` (MQ-TA-1.0.0): BB z odchyleniem populacyjnym, %b bez przycinania, bandwidth ratio/%, squeeze względem
  przeszłości, zdarzenia pasma; SMA/EMA/WMA, przecięcia potwierdzone zamknięciem ze stałym ID, kontekst wg jawnych reguł. Linie EMA/BB na wykresach
  liczone tym samym silnikiem (zgodność z M02I i modułem scalp potwierdzona testem).
* **FFT / EMD / VMD** `analytics/signal.py`: numpy/scipy bez nowych zależności, okno ciągłe (luki → unavailable), metadane wejścia, flagi jakości,
  pomiar rewizji końca okna, limit czasu, wątek roboczy z kolejką i cache, odrzucanie spóźnionych wyników.
* **Double Bottom** `analytics/double_bottom.py` + `library.py`: walidator INVALID/CANDIDATE/CONFIRMED/FAILED (pierwsze rozstrzygnięcie ostateczne),
  biblioteka próbek (zapis z zakresu świec, import/eksport), VALIDATE SELECTED/ALL (job_id, postęp, anulowanie, raport JSON/CSV), SHOW ON CHART ze
  współrzędnymi walidatora, skaner przyczynowy z czasem dostępności i zdarzeniami.
* `AnalyticsService` (tryb OBSERVE), archiwum wyników z chwili decyzji (`analytics_snapshots`), karta „Co wspiera analizę” z wyjaśnieniem
  budowanym wyłącznie z danych strukturalnych. Migracja 0013 (tylko nowe tabele). API `/api/v1/analytics*`, `/api/v1/patterns/*`.
* **Audyt:** `AUDIT_REPORT.md`, `INTEGRATION_MAP.md`, `TEST_REPORT.md`; naprawione ciche wyjątki (start silnika, ładowanie challengerów ML),
  nieużywane importy; ujednolicona implementacja BB.

## 1.12.0 – scalp M5 Range → M1 Sweep/Reclaim → Retest + kontrolowany hedge + ML/NN (wszystko SHADOW)
* Jeden automat **MQ-SCALP-RANGE-SWEEP-1.0.0-RESEARCH** (`backend/masterquo/scalp/`, profil z jednostkami `config/scalp_profile_v1.json`):
  zamrożony zakres M5, sekcja M1 z `known_at`, sweep/reclaim z potwierdzeniem świecy i tick volume, retest ≤3 M1, limit pogoni (MISSED),
  SL/TP1(MID)/TP2, filtr koszt/TP1 i ważonego RR netto, wielkość pozycji w dół do kroku lota, BUY/SELL lustrzane, dziennik stanów.
* Wskaźniki BB SMA20 ±2σ (populacyjne) / %B / BandWidth / percentyl / nachylenie, Parabolic SAR 0.02/0.2, sesje z IANA DST,
  własny silnik świec **SCI-1.0.0** (jeden dowód na rodzinę, ZERO_RANGE, przyczynowe statystyki z shrinkage).
* Adaptery zewnętrzne ze statusami (IQ Gold Gann / FX Gann / Star Lines / Volatility Master / heatmapa: UNAVAILABLE; **PAL02M:
  UNDOCUMENTED_EXTERNAL**) – bez fikcyjnych wartości; opcjonalny mostek plikowy dla licencjonowanego eksportu (UNVALIDATED).
* Kontroler hedge (SHADOW): NETTING → REDUCE, 1 hedge ≤50% base, TTL 3 M1, osierocona noga, timeout → rekonsyliacja, P&L koszyka.
* Replay z Bid/Ask, prowizją, poślizgiem, częściowym TP, konserwatywną kolejnością OHLC; porównanie HOLD/REDUCE/CLOSE/HEDGE_PARTIAL na tej samej ścieżce.
* Serwis SHADOW w bocie: bramki AND (brak informacji = BLOCKED), zapis decyzji przed wynikiem (`scalp_shadow`, migracja 0012), rozliczenie
  hipotetyczne, statusy CODE/DATA/MODEL/STRATEGY/HEDGE_VALID i EXECUTION_AUTHORIZED=false. API `/api/v1/scalp`, `/api/v1/scalp/shadow`.
  Konfiguracja `scalp`: `mode=SHADOW`, `live_trading/ml_execution/hedge_execution` tylko `false`.
* ML/NN w `.venv_candles`: kontrakt cech SCALP-FEAT-1.0.0, zadania A (1/3/5 min, martwa strefa kosztów), B (P(TP1 przed SL) z replayu),
  C (polityki hedge); LR, HistGradientBoosting, **MLP 64/32** z early stopping na późniejszym fragmencie, kwantyle; plan przed treningiem,
  walk-forward, kalibracja, holdout raz, rejestr z checksumami, inference w workerze (`scalp_forecast`).
* Eksport M1/M5/M15/M30/H1 (`export-scalp`), replay CLI (`scalp-replay`), launchery 16–21. Monitor: Wykresy bota → sekcja Scalp (6 widoków).
* **Warianty poprawy win ratio (profil 1.1.0)**: filtry jakości (tick volume, głębokość sweepu, rodziny świec), filtr sesji (godziny UTC,
  po otwarciu Londynu/NY), tryb trendu BOTH/ANY/ANY_PLUS_H1 (H1 dodane do kontekstu), jakość zakresu, close retestu przy krawędzi, wejście
  LIMIT_EDGE, BE + koszty po TP1, wyjście bez postępu, filtr modelu B (P(TP1 przed SL), cechy setupu, LR/HGB/MLP, kalibracja, próg z development).
  Domyślnie zachowanie 1.0.0; `scalp-replay --variants` (i `19_REPLAY_SCALP.bat`) porównuje 15 wariantów: win ratio i expectancy obok siebie,
  wybór po expectancy w development, test raz, stres kosztów +50%. Monitor: tabela wariantów, filtr B, win ratio. Wynik hipotetyczny SHADOW
  w monitorze liczony teraz po prowizji i poślizgu.
* Domyślna prowizja w paczce: **0.50 za 1 lot na stronę** (`scalp.commission_per_lot_side`; launchery 17/19 działają dwuklikiem, argument nadpisuje).
* **Trening i replay na danych rynkowych NIE wykonane – BLOCKED_NO_REAL_DATA.** Hedge vs REDUCE nieoceniony. Nic nie jest dopuszczone do wykonania.
  Raport: `research/scalp/RAPORT_SCALP_HEDGE_ML_NN.md`, opis: `docs/SCALP_HEDGE_ML_NN_PL.md`.

## 1.11.0 – świece i prognozy 5/15/30 min (gold_candles, SHADOW) + Double Retest v2 (badawczo)
* Moduł referencyjny `gold_candles` (MasterQUO_XAUUSD_CANDLES_FORECAST_v2) dołączony **bez zmian** (`backend/gold_candles/`, hashe zgodne z MANIFEST).
  Działa w izolowanym `.venv_candles` (numpy 2.3.5 / pandas 2.2.3 / scikit-learn 1.8.0) – środowisko bota bez zmian.
* Analityka SHADOW w bocie: zamknięte M5/M30 z sesji bota → proces roboczy (bez drugiej sesji MT5) → formacje, prognozy P(spadek/płasko/wzrost)
  i q10/q50/q90 dla 5/15/30 min; statusy NO_CANDLE_ENV / NO_MODEL / WARMUP / STALE_DATA / CONTRACT_MISMATCH / FORECAST_UNAVAILABLE.
  Prognozy zapisywane przed wynikiem (`forecast_shadow`, migracja 0011) i oceniane po upływie horyzontu. Zawsze `execution_permission=false`.
* Eksport historii `python -m masterquo export-candles` (11_EKSPORT_HISTORII_XAUUSD.bat): cutoff zamrożony, porcje z checkpointami, metadane
  ze specyfikacją brokera (tick_size), raport jakości danych. Trening `12_TRENING_MODELI_XAUUSD.bat`: zamrożony plan ze wspólnymi granicami
  UTC dla 5/15/30, purge/embargo, baseline i model bez formacji zadeklarowane przed treningiem, bootstrap bloków dni, statusy, rejestr z
  atomową aktywacją, walidacja (13) i rollback (14).
* Maszyna stanów **MasterQUO Gold Double Retest 5/10/15 v2** (BUY/SELL lustrzane, dwa epizody, reclaim, retest, rodziny REJECTION /
  CONTINUATION z tych samych flag formacji) – tylko badawczo, najwyżej RESEARCH_SETUP_COMPLETE, EXECUTION_STATE=BLOCKED.
* Monitor: Wykresy bota → „Świece i prognozy”. API: `/api/v1/forecast`, `/api/v1/forecast/shadow`, `/api/v1/forecast/reload`.
* **Trening na danych rynkowych nie został wykonany w środowisku budowy (BLOCKED_NO_REAL_DATA)** – wymaga eksportu z Twojego MT5.

## 1.10.1 – połączenie z MT5 po „-6 Terminal: Authorization failed”
* Program nadal łączy się domyślnie z **zalogowanym** terminalem. Nowe: opcjonalny **login i serwer** (Ustawienia → MT5) oraz **hasło** zapisywane
  wyłącznie lokalnie (`MT5_PASSWORD`, Windows DPAPI) – nie trafia do `config.json`, logów, odpowiedzi API ani przeglądarki (maska „•••”).
* Odrzucone logowanie **nie jest ponawiane w pętli** (ochrona przed blokadą rachunku u brokera) – kolejna próba dopiero po zmianie loginu, serwera
  lub hasła; w międzyczasie program próbuje sesji zalogowanej w terminalu.
* Gdy `terminal_path` jest pusty, a domyślny terminal zwraca -6 / błąd IPC, program próbuje **uruchomionych** terminali `terminal64.exe`
  (kilka instalacji MT5) i zapamiętuje ten, który zadziałał. Nie uruchamia innych instalacji. Ustawiona ścieżka nigdy nie jest zastępowana.
* Komunikat błędu z polską podpowiedzią (pasek awarii, Ustawienia → MT5, `02_DIAGNOSTYKA.bat`); przycisk „Połącz ponownie” w Ustawienia → MT5.
* Testy: `test_mt5_login.py` (7). Bez zmian strategii, ryzyka i wykonania.

## 1.10.0 – audyt winrate/ROI z naprawami P0, walls HV/IV + formacje + S12, panel na trzy strony
**Audyt 1.9.0** (`audit/`): reprodukcje A–J w izolacji (`audit/repro/repro_audit.py`) – na 1.9.0 8/8 ODTWORZONE, po naprawach 0/8.
Plan ulepszeń winrate/ROI, protokół walidacji i wyniki testów w `audit/`. Brak danych do oceny skuteczności: **OOS_NOT_RUN / NIE_OCENIONO_SKUTECZNOŚCI**.

**Naprawy P0 (wykonanie, etykiety ML, statystyki):**
* Jedna polityka wyjścia **MQ-EXIT-POLICY-1.0.0** (`execution/policy.py`) zapisywana przy otwarciu i używana przez LIVE, PAPER, etykiety ML i replay:
  wszystkie cele (także środkowy), wagi częściowych wyjść, BE dopiero po POTWIERDZONYM TP1, `time_exit_bars` z planu (jawny brak dla S11), TP od fillu (RR_FROM_FILL).
* Częściowe wyjścia jako maszyna stanów (REQUESTED / UNKNOWN / CONFIRMED / REJECTED / SKIPPED_VOLUME / NOT_FOUND_CHECK_TERMINAL); `trades.status`
  OPEN_PARTIAL / CLOSED / UNSETTLED – statystyki, winrate i R tylko z CLOSED; ROI rachunku pomija wpłaty/wypłaty (typy 2–6).
* Etykiety ML **MQ-LABEL-1.1.0**: kursor po TP1, kolejność wewnątrz świecy z kwotowań, bez nich AMBIGUOUS; koszty **MQ-COST-1.1.0** z tego samego źródła
  prowizji co wykonanie; COST_UNKNOWN wyłączone z treningu; champion oceniany na tych samych próbkach testowych; purge względem każdego późniejszego bloku.
* Migracja bazy **0009** (polityka wyjścia, stan TP1, status transakcji). Pozycje otwarte w 1.9 dostają politykę odtworzoną raz z zapisanych poziomów.

**Walls, formacje, S12:**
* Dostawca walls **MQ-WALLS-1.0.0**: HV_PROXY (zmienność historyczna brokera – przybliżenie, nie IV), IV_MANUAL, import IV (`import-iv`, `POST /api/v1/walls/iv-import`);
  snapshot sesji zamrażany i wersjonowany (migracja **0010**). Etykiety zawsze ze źródłem („HV-proxy”, nigdy „IV” dla HV).
* Silniki formacji: wykresowe **MQ-CHART-1.0.0** (pivoty z `known_at`, stany FORMING / CONFIRMED / INVALIDATED / EXPIRED), świecowe **MQ-CANDLE-1.0.0**
  (zdarzenia dowodowe), strefy S/R **MQ-SR-1.0.0** (W1/MN1 z D1), zakres M5 + strefy M1 **MQ-RANGE-1.0.0**. Definicje: `docs/PATTERN_DEFINITIONS_PL.md`.
* Nowa rodzina **S12 WALLS_RANGE_FAMILY** (RANGE_RECLAIM / WALL_REJECTION / BREAKOUT_RETEST + arbiter) – CANDIDATE, **tylko skanowanie** (jak S11).
  Opis: `docs/STRATEGIA_WALLS_RANGE_PATTERNS_PL.md`; ujednolicenie S01–S12: `docs/MAPA_UJEDNOLICENIA_STRATEGII_PL.md`.
* `data\config.json` v9 → v10: sekcja `walls`, przełącznik S12 `{scan: true, trade: false}`; listy strategii z rejestru.
* API: `GET /api/v1/timeframes`, `GET /api/v1/walls`, `POST /api/v1/walls/iv-import`, `GET /api/v1/structure?tf=`; agent: narzędzie `get_walls_and_patterns`.

**Panel na trzy strony** (`docs/POSTEP_PRZEBUDOWY_PANELU_CLAUDE_CODE.md` – mapa przeniesionych paneli):
* **Analiza AI** (`#/ai`): karta „Sygnał AI” (KUPNO / SPRZEDAŻ / CZEKAJ / BEZ TRANSAKCJI, kierunek, etap, strategia, czas i ważność, strefa, unieważnienie, cele)
  oddzielona od **pozwolenia silnika**; stany: aktualna / wygasła / inny setup / brak klucza / błąd ostatniego przebiegu (historia wyraźnie oznaczona);
  pełne wyjaśnienie (za, przeciw i sprzeczności, aktywacja, unieważnienie, 3 scenariusze, braki danych, dowody); „Analizuj teraz” / „Zapytaj AI” bez
  podwójnych wysyłek; wykresy H1 → M30 → M15 → M5 → M1 z wykresem głównym (domyślnie M5) i przełącznikiem „Siatka 5 wykresów”.
* **Wykresy bota** (`#/wykresy`): wszystkie TF z rejestru backendu (D1…M1) z rolą, stanem danych i wyróżnieniem wymaganych; widoki Wszystkie / Kontekst /
  Setup i wejście / Skupienie; 1–3 kolumny; sekcje: zmienność i walls, reżim, monitor strategii, inne rynki, jakość danych.
* **Warunki setupu** (`#/warunki/<setup_id>`): lista z filtrami i „Wybrany przez bota”, podsumowanie „Spełniono X z Y warunków wymaganych”, checklista w 10 sekcjach
  (Spełnione / Niespełnione / Oczekiwanie / Brak danych / Nie dotyczy, TF i czas), karta triggera i unieważnienia, plan wejścia, „Pokaż na wykresie”.
  **Oglądanie setupu nie zmienia strategii silnika**; zmiana to osobne ustawienie „Działanie bota – wybór strategii silnika”.
* Wspólna rama: kompaktowy pasek (symbol, MT5, dane, tryb, STOP), rozwijane „Konto”, panel „Pozycje i statystyki”, „Logi”, pasek awarii na każdej stronie;
  routing hash (Wstecz/Dalej, link, odświeżenie), pamięć ostatniej strony i układów; jedno połączenie WebSocket; widoki i kolory wykresów z 1.9 migrowane.

## 1.9.0 – wersja bez licencji
* **Licencjonowanie usunięte w całości** (na prośbę użytkownika): serwer licencji i panel administratora (`server/`), moduł klienta
  `backend/masterquo/license`, pytanie o klucz `MQL72-…` w `masterquo_start`, blokady silnika / skanera / sygnałów / ML / agenta / zleceń /
  API / WebSocket, plansza „Licencja nieaktywna” i wskaźnik licencji w monitorze, `09_KONFIGURACJA_LICENCJI.bat`, zmienne
  `MASTERQUO_LICENSE_*`, pakiety `cryptography`/`pyjwt`. Paczka serwera licencji nie jest już budowana.
* Start: `masterquo_start.bat` / `03_START_MASTERQUO.bat` – monitor od razu, bez klucza.
* `data\config.json` v8 → v9: sekcja `license` usuwana, pozostałe ustawienia bez zmian. Baza bez nowych migracji.
* Bez zmian: sygnały, M30/H8, S11, karta BUY/SELL, wybór setupu, szczegóły, dźwignia / limit ekspozycji, ROI rachunku, tryby wykonania.

## 1.8.0 – wybór setupu, szczegóły scenariusza, dźwignia / limit ekspozycji
* **Setup: AUTO / WYBRANY SETUP / WSZYSTKIE** (pasek nad kartą sygnału). AUTO = dotychczasowy wybór silnika; WYBRANY SETUP = silnik
  analizuje i wybiera tylko wskazaną strategię z rejestru (nic nie jest wymuszane – setup musi zostać wykryty i przejść wszystkie bramki);
  WSZYSTKIE = lista scenariuszy (stabilny identyfikator, symbol, kierunek, TF, czas powstania) z przyciskiem „Szczegóły”. Wybór zapisuje się
  w bazie **per rachunek MT5 (serwer:login)** i wraca po odświeżeniu i restarcie; odświeżanie go nie zmienia.
* **Szczegóły setupu**: strategia, symbol, kierunek scenariusza (oddzielony od zgody na wejście), interwały, status scenariusza
  (OCZEKIWANIE / WARUNKI SPEŁNIONE / UNIEWAŻNIONY / BRAK DANYCH), możliwość wejścia (DOSTĘPNE / ZABLOKOWANE + przyczyny), kontekst i uzasadnienie,
  checklista (warunek, próg, wartość, status, powód; warunki świecowe dopiero po zamknięciu), strefa wejścia, trigger, SL, TP, unieważnienie,
  R brutto/netto, wolumen, szacowana strata przy SL, wynik przy TP, margin i wolny margin po wejściu, wiek i aktualizacja, źródło danych,
  zgodność/konflikt interwałów strategii (w tym M30/H8), wynik ACTIVE z opisem (nie prawdopodobieństwo), historia tylko z rozliczonych transakcji.
* **Dźwignia / limit ekspozycji** (Ustawienia → Ryzyko): AUTO (dźwignia rachunku z MT5) albo RĘCZNIE (1:1…1:500, nie więcej niż dźwignia
  rachunku). Pokazywane osobno: dźwignia rachunku, limit użytkownika, efektywna ekspozycja (nominał / equity). To limit planowania bota –
  nie zmienia dźwigni u brokera; margin zawsze z `order_calc_margin`.
* **Wielkość pozycji** = największy wolumen spełniający jednocześnie: budżet ryzyka do SL, wolny margin z buforem i rezerwą zleceń
  oczekujących, limit ekspozycji (pozycje + zlecenia oczekujące), maks./min./krok wolumenu; zaokrąglenie w dół i ponowna weryfikacja
  kalkulatorami brokera. Nominał z `order_calc_profit` (bez założonej wielkości kontraktu). Minimalny lot ponad limit → blokada z powodem.
  Wyższa dźwignia nie zwiększa budżetu ryzyka i nie przesuwa SL/TP. Zlecenia oczekujące liczą się do ryzyka, marginu, ekspozycji i liczby pozycji.
* **Spójność**: wersja ustawień w każdej kalkulacji; przed wysłaniem zlecenia bramka sprawdza wersję ustawień i przelicza ryzyko na bieżącej
  cenie i danych rachunku (`order_check` jak dotąd) – zmiana ustawień lub mniejszy dopuszczalny wolumen blokuje wysyłkę. Istniejące pozycje
  i zlecenia nie są modyfikowane. Tryby wykonania bez zmian.
* **ROI rachunku MT5** (statystyki): metodą Dietza z zapisanych snapshotów equity, wpłaty/wypłaty jako przepływy – brak danych = „brak danych”.
* Migracja bazy 0008 (`account_prefs`).

## 1.7.1 – czytelny monitor: BUY / SELL, karta sygnału, prosta checklista
* **Karta sygnału na górze monitora**: duże BUY (zielone) / SELL (czerwone) tylko dla aktualnego, potwierdzonego sygnału otwarcia,
  który przeszedł reguły strategii i decyzji; OCZEKIWANIE (bursztynowe) z „Plan: BUY/SELL”; BRAK SYGNAŁU, BLOKADA (z powodem),
  NIEAKTUALNY, BRAK DANYCH. Każdy stan ma napis (nie tylko kolor). Wejście / SL / TP / RR dużą czcionką z podpowiedziami skrótów,
  ryzyko i wolumen, czas wygenerowania i ważności z odliczaniem, aktualność danych, jedno zdanie „dlaczego”, trigger, unieważnienie,
  źródło (STRATEGIA / STRATEGIA + AI), widoczne „AI NIEDOSTĘPNE”, rozdzielone: cena odniesienia / planowane wejście / wykonanie.
  „Kopiuj plan” kopiuje dokładnie wartości z karty. Długie uzasadnienia, identyfikatory i diagnostyka – w „Szczegóły”.
* **Prosta checklista** obok karty: spełnione ✓ / niespełnione ✗ / brak danych ?, z opisem i podsumowaniem „Do potwierdzenia brakuje: …”;
  tylko warunki wybranej strategii i bramek decyzji (tryb wykonania nie jest warunkiem potwierdzenia – osobna informacja na karcie).
* **Kontekst interwałów** (M1…D1, w tym M30 i H8): kierunek, rola, ostatnia zamknięta świeca, tworząca się świeca, dostępność danych,
  konflikt z planowanym kierunkiem i jego realny wpływ na kwalifikację.
* **Spójność**: backend buduje jeden model prezentacji (`engine/signal_view.py`, `MQ-SIGNAL-VIEW-1.0.0`) z tej samej decyzji
  (snapshot / decyzja / sygnał); zmiana stanu karty (TTL, blokada, ocena AI) jest wysyłana od razu. Monitor tylko obniża stan:
  po upływie ważności → NIEAKTUALNY, bez połączenia lub przy decyzji starszej niż 2 min → BRAK DANYCH; po ponownym połączeniu karta
  pochodzi z bieżącej decyzji silnika (stara karta nie wraca jako BUY/SELL). Spóźniona odpowiedź AI nie zmienia stanu ani źródła.
* Historia sygnałów: BUY/SELL zamiast LONG/SHORT, przycisk „Kopiuj” w każdym wierszu.
* Bez zmian: logika strategii, progi wejścia, risk engine, tryby wykonania, M30/H8, licencje.

## 1.7.0 – sygnały z planem wejścia, M30/H8, strategia EMA20 Pullback, licencje 72 h, panel administratora
* **Sygnał (kontrakt `MQ-SIGNAL-1.0.0`)**: status (OCZEKIWANIE/POTWIERDZONY/ZABLOKOWANY/UNIEWAŻNIONY/WYGASŁY/BRAK_DANYCH) i osobny stan
  wykonania, ceny (odniesienie, Bid/Ask, planowane wejście, fill dopiero po wykonaniu), SL/TP, ryzyko w pieniądzu i %, wolumen, RR brutto
  i netto z definicjami, spread vs SL, koszty, flagi danych, warunki spełnione/brakujące, wyzwalacz, unieważnienie, powody blokad,
  ocena AI (aktualna / nieaktualna / niedostępna), jakość, prawdopodobieństwo tylko z walidowanego modelu. Blok „Sygnał AI / plan wejścia”
  obok checklisty, zakładka „Historia sygnałów” z filtrami (migracja 0007).
* **M30 i H8** w całym systemie: rejestr interwałów, natywne TIMEFRAME_M30/H8 z MT5, kontrolowany resampling H8 z H1, jakość danych
  (kontekst), karta „Kontekst M30/H8”, układ 8 wykresów, eksport (8 TF, model DST `NY_CLOSE`), narzędzia agenta.
* **Strategia S11 EMA20 Pullback 2.5R**: audyt Pine (14 punktów), poprawiony Pine v6 (nieskompilowany – brak TradingView), port oryginału
  i wersji naprawionej, backtester (model Pine i MT5, walk-forward, test końcowy, bootstrap), RAPORT_WYNIKOW.md (dane syntetyczne).
  Domyślnie tylko skanowanie (bez automatycznego handlu).
* **Statystyki**: winrate netto bez breakeven (BE osobno), PF „brak strat”, oczekiwana wartość w R, ROI Dietza (wpłaty nie są zyskiem),
  statystyki sygnałów oznaczone jako brutto w R.
* **Licencje 72 h**: osobny serwer `server/mqlicense` (SQLite, migracje, Ed25519, Argon2id, TOTP, CSRF, audyt, limity) i panel administratora
  `/admin/`. `masterquo_start.bat` prosi o licencję **przy każdym uruchomieniu**; bez ważnej dzierżawy silnik, skaner, sygnały, ML,
  agent, nowe zlecenia i API/WS monitora są zablokowane (otwarte pozycje i SL/TP bez zmian). Config v8 (sekcja `license`).
* Audyt: `AUDYT_MASTERQUO.md`. Instrukcja: `INSTRUKCJA_WINDOWS_PL.md`. Serwer: `server/README_SERWER_PL.md`.

## 1.6.0 – sygnały bota zamiast sygnałów agenta AI
* Sygnały tworzy **bot**: potwierdzone (CONFIRMED) setupy strategii S01–S10. Na symbolu głównym pochodzą z silnika bota, na pozostałych
  rynkach skaner uruchamia te same strategie (te same progi, parametry i przełączniki). Generowanie sygnałów przez Claude usunięte.
* Walidacja regułami bota: R:R ważony wagami celów ≥ `risk.rr_block_below`, cena nie dalej od wyzwalacza niż `max_distance_atr` strategii,
  SL/TP po właściwej stronie, spread ≤ 50% ryzyka; jeden sygnał na setup i na zdarzenie rynkowe; rozliczanie na M15; statystyki; Telegram.
* Monitor: panel „Sygnały bota · S01–S10”, kolumna „Setup bota” w skanerze, setupy i poziomy sygnałów w oknie rynku.
* Migracja bazy 0006 (kolumny strategii w tabeli sygnałów), konfiguracja v6 (sekcja `signals`; `ai_signals` usunięta), skan co 120 s.
* Poprawki strategii dla rynków o małych cenach (FX): grupowanie poziomów i usuwanie duplikatów celów bez zaokrąglania do 0,01.

## 1.5.0 – skaner wszystkich rynków i sygnały AI
* **Skaner rynków** (`markets/`): symbole z terminala MT5 – Market Watch (domyślnie), własna lista albo wszystkie symbole.
  Dla każdego: trend H1/H4/D1, RSI, ADX, ATR, Donchian, reżim, poziomy dzienne i IV walls, spread vs ATR, obserwacje i ranking do przeglądu.
  Tylko odczyt; strategie i zlecenia bota pozostają na symbolu głównym.
* **Sygnały AI** (`agent/signals.py`): Claude proponuje BUY/SELL/NO_TRADE z wejściem, SL i TP dla dowolnego rynku; walidacja deterministyczna
  (strony SL/TP, ATR, R:R, odległość wejścia, spread), zapis w bazie (migracja 0005), rozliczanie na świecach M15 (WIN/LOSS/EXPIRED/TIMEOUT),
  statystyki. Bez wysyłania zleceń. Automatyczne sygnały dla N najlepszych rynków – opcjonalne, domyślnie wyłączone.
* Monitor: panele „Rynki · skaner” i „Sygnały AI · Claude”, okno rynku z wykresem (M15/H1/H4/D1, IV walls, poziomy sygnału AI),
  linie aktywnego sygnału AI na wykresach symbolu głównego, zakładka ustawień „Rynki / Sygnały AI”.
* Most MT5: odczyt listy symboli, kwotowań i świec dowolnego symbolu. Symulator: kilka syntetycznych rynków.
* Opis: `docs/RYNKI_I_SYGNALY_AI.md`.

## 1.3.1 – zmienność dzienna i IV walls
* **Cofnięte**: konta, serwer licencji, panel administratora i licencje 48 h z wersji 1.4 (na prośbę użytkownika). Plik konfiguracji
  zapisany przez 1.4 (config v4 z sekcjami `central`/`connector`) wczytuje się bez błędu – te sekcje są usuwane.
* **Nowe**: `engine/volzones.py` – Daily Open, High/Low dnia, PDH/PDL, zmienność historyczna (close-to-close / Parkinson, percentyl 1R),
  wycena 1-dniowych opcji Black-76 (straddle ATM, progi rentowności), IV walls ±kσ z premią, deltą, P(zamknięcia za) i P(dotknięcia).
  IV = HV (MT5 nie ma opcji na złoto) albo IV wpisana ręcznie. Opis: `docs/IV_WALLS_ZMIENNOSC_DZIENNA.md`.
* Monitor: strefy i linie na wszystkich wykresach (przełącznik „IV walls / Daily”), panel „Zmienność dzienna · IV walls”, zakładka
  ustawień „Zmienność / IV”, nowe kolory w motywie. API `GET /api/v1/volatility`, narzędzie agenta `get_volatility_levels`. Config v5.
* Poprawki: STOP działa przy otwartej karcie monitora; testy offline nie zależą od dnia tygodnia (symulator rynku otwarty w testach).

## 1.3.0 – kolory, niezależny zoom, Decision Tree + XGBoost, tryby bez READONLY
* **Tryby**: SIGNALS („Analiza warunków”) / PAPER / AUTO_DEMO / AUTO_LIVE – trwały wybór (config v3, migracja DB 0003), konto z terminala,
  niezgodność blokuje z powodem, brak potwierdzania pojedynczych transakcji w AUTO, STOP tylko dla nowych wejść. Trzy niezależne
  ustawienia: wybór strategii, tryb ML (OFF/SHADOW/ASSIST), tryb wykonania.
* **ML** (`backend/masterquo/ml/`): kolektor setupów, FeatureEngine as-of, etykietowanie netto (SL/TP/BE/czas, kwotowania, AMBIGUOUS),
  niezmienne snapshoty, trener DT + XGBoost w osobnym procesie, walidacja chronologiczna z purgingiem/embargo, kalibracja, rejestr
  champion/challenger z regułami promocji i rollbackiem, kontrakt predykcji, dryf, backfill z MT5 (APPROX), węzeł ML w drzewie decyzji,
  ranking AUTO w ASSIST, API `/api/v1/ml/*`. Opis: `docs/ML_DECISION_TREE_XGBOOST.md`.
* **Wykresy**: naprawiony wspólny zoom (przyczyna w `RAPORT_1_3.md`), stan widoku per wykres, przyciski +/−/Dopasuj/Najnowsza/auto-skala,
  grupy synchronizacji, osobny wspólny celownik.
* **Kolory**: pełna paleta tokenów, picker HSV/HEX/RGB/HSL/alfa, presety, własne motywy, import/eksport z walidacją, ostrzeżenia kontrastu,
  nadpisania per wykres, przyciemnienie/przezroczystość GIF.
* **Monitor**: checklista wejścia zamiast sygnałów BUY/SELL, panel ML, osobne chipy MT5/instrument/dane/backend/wykonanie/AUTO/ML.
* Zależności: scikit-learn 1.9.1, xgboost 3.4.1, scipy 1.18.1, joblib 1.6.0, threadpoolctl 3.7.0, narwhals 2.26.0, cloudpickle 3.1.2 (hashe).

## 1.2.0 – ACTIVE, 10 strategii, AUTO wybór strategii, animowany monitor
* **10 strategii S01–S10** (`backend/masterquo/strategies/`): TREND_PULLBACK, ADAPTIVE_TREND (KAMA/ER), CHANNEL_BREAKOUT (Donchian),
  VOLATILITY_COMPRESSION_BREAKOUT, SESSION_RANGE_BREAKOUT (strefy IANA/DST), BREAKOUT_RETEST, FAILED_BREAKOUT_RECLAIM, RANGE_EDGE_REVERSION,
  STATISTICAL_MEAN_REVERSION (z-score), EXHAUSTION_STRUCTURE_REVERSAL. Wspólny kontrakt, LONG/SHORT jedną regułą (odbicie cen),
  status FUNCTIONAL_ONLY_OOS_NOT_RUN. Karty: `docs/PLAYBOOK_10_STRATEGII.md`, źródła: `docs/ZRODLA_I_ADAPTACJE.md`.
* **Profil ACTIVE** (domyślny): etapy WATCH/EARLY/CONFIRMED, punktacja 0–100 (25/25/20/15/10/5), progi 40/55/70 + prawdziwy trigger,
  tworząca się świeca tylko dla WATCH/EARLY, skan co ≥ 2 s przy nowych danych. Profil ORIGINAL = M07/M10A jak w 1.1.
* **MarketRegimeEngine** (TREND/RANGE/COMPRESSION/EXPANSION/EXHAUSTION/TRANSITION/DATA_UNAVAILABLE/STALE) z konfliktami TF i horyzontami.
* **SetupTracker** (tabela `strategy_setups`, migracja 0002): wersje setupów, histereza etapów, natychmiastowe unieważnienie/wygaśnięcie,
  STALE bez tworzenia nowych setupów, rewalidacja po restarcie, karty playbooka (także odwołane setupy).
* **StrategyAutoSelector** (AUTO/MANUAL): ranking, grupowanie event_id, konflikt LONG/SHORT, histereza wyboru, dziennik zmian
  (`strategy_selection_log`). AUTO wybiera strategię, **nie** włącza zleceń; „Skanuj” i „Dopuść do handlu” per strategia.
* Drzewo decyzji: węzeł STRATEGY dla ACTIVE, blokada STRATEGY_TRADE_DISABLED; gateway oznacza ENTERED dla setupów ACTIVE.
* Claude: prompt MQAI-AGENT-PROMPT-1.2.0, narzędzie z rankingiem AUTO, pola `preferred_strategy_id` (walidowane w rejestrze, tylko sugestia)
  i `scenario_still_valid`; wywołania przy zmianie wyboru i EARLY/CONFIRMED wybranego setupu.
* API: `/api/v1/strategy/auto|mode|toggle|profile|selection-log`, `/api/v1/playbook`, `/api/v1/appearance/assets|upload`, `/media/masterquo/{slot}`.
* Monitor: panele „AUTO — wybór strategii”, „Setupy na bieżąco” z „Dlaczego nie ma setupu?”, „Strategie (10) i dziennik AUTO”;
  nagłówek z przełącznikiem AUTO/MANUAL i osobnym statusem „Wykonywanie zleceń”; **animowane tło** (pierwszy GIF – wgrywany, bo dotarł
  jako statyczny WebP) i **tańcząca żaba przy BALANCE** (drugi GIF, oryginał z przezroczystością); tryby FULL/LIGHT/OFF z prawdziwą
  podmianą na kadr, prefers-reduced-motion, Page Visibility; responsywność 1920/1366/wąskie okno.
* Narzędzia: `tools/replay_strategies.py` (replay/OOS, porównanie z ORIGINAL), `tools/make_strategy_cards.py`, `08_PROFIL_ORIGINAL.bat`,
  `python -m masterquo profile ACTIVE|ORIGINAL|show`.
* Poprawka: odbicie cen dla SHORT wokół bieżącej ceny (nie zera) – wskaźniki względne (szerokość BB/średnia) poprawne dla SHORT.

## 1.1.0 – łagodniejsze bramki
Struktura H1_LEAD, RR od 1,0 (1,0–1,5 z połową ryzyka), AI jako weto, brak kalendarza nie blokuje, poślizg 20 pkt, okno wejścia 3 świece;
migracja konfiguracji v1→v2. Szczegóły: MIGRACJA_I_ZMIANY.md.

## 1.0.0 – pierwsze wydanie
Lokalna aplikacja MT5 → MasterQUO → Claude → ryzyko → monitor; READ_ONLY/PAPER/DEMO/LIVE.
