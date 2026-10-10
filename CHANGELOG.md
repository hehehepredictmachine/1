# CHANGELOG

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
