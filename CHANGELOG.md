# CHANGELOG

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
