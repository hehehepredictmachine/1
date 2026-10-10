# CHANGELOG

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
