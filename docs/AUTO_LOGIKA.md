# AUTO — wybór strategii (MQ-AUTO-SELECT-1.0.0)

## Definicje
* `strategy_mode = AUTO` – bot ocenia rynek, skanuje wszystkie strategie z włączonym skanowaniem, wybiera główną i aktualizuje wybór.
* `strategy_mode = MANUAL` – rozważana jest tylko wskazana strategia; nadal obowiązują jej warunki, dane i unieważnienia; niedopasowanie do reżimu jest pokazywane.
* **AUTO nie składa zleceń.** Wykonanie zależy od osobnych ustawień: tryb (READ_ONLY/PAPER/DEMO/LIVE), przełącznik „Wykonywanie zleceń”,
  limity ryzyka, bramka AI, zgoda strategii na handel („Dopuść do handlu”). Zmiana AUTO/MANUAL nie zmienia żadnego z nich (test `test_06_auto_strategy_api_separate_from_execution`).
* Profil `ACTIVE` (domyślny) = S01–S10 + AUTO. Profil `ORIGINAL` = wyłącznie dotychczasowy M07/M10A (jak w 1.1).

## Przepływ (jeden silnik, ten sam kod live i replay)
```
MT5 bars (zamknięte + tworząca się) + Bid/Ask
  -> MarketView -> MarketRegimeEngine (stan per TF, konflikty z horyzontem)
  -> skan S01–S10 (warunki konieczne -> fazy WATCH/EARLY/TRIGGER; punktacja 0–100; etap)
  -> SetupTracker (setup_id, wersje, histereza etapów, unieważnienie/wygaśnięcie natychmiast, STALE)
  -> StrategyAutoSelector (ranking, grupowanie event_id, konflikt LONG/SHORT, histereza wyboru)
  -> drzewo decyzji (7 węzłów) -> moduł ryzyka -> bramka AI -> tryb -> gateway
```
Skan: przy nowej świecy (pełny cykl) oraz co ≥ `scan_min_interval_seconds` (2 s) **tylko gdy zmieniły się dane** (świece lub tick).
Sam upływ czasu bez nowego ticka nie jest nowymi danymi. Średni czas skanu 10 strategii: ~85–120 ms (symulator).

## MarketRegimeEngine (MQ-REGIME-1.0.0)
Na zamkniętych świecach każdego TF: ER(20), nachylenie EMA20 w ATR/świecę, percentyl szerokości Bollingera (120), ATR5/ATR50,
odległość od EMA20 w ATR, słabnący histogram MACD. Kolejność stanów (pierwszy pasujący): DATA_UNAVAILABLE → EXHAUSTION_OR_REVERSAL_CANDIDATE
→ EXPANSION → COMPRESSION → TREND_UP/DOWN → RANGE → TRANSITION. Reżim główny = M15 (lokalny); M5 = mikro, H1 = kontekst, H4/D1 = tło.
Konflikty (np. M15 UP vs H1 DOWN) są raportowane z horyzontem, nie usuwają kandydatów. Progi: `strategies/regime.py: DEFAULTS`,
nadpisanie: `active.regime` w konfiguracji. Brak danych → `DATA_UNAVAILABLE`, nieświeże → `STALE`.

## Ranking (deterministyczny)
```
rank = 0,35 × strategy_fit_score + 0,65 × setup_score + bonus etapu (WATCH 0 / EARLY 4 / CONFIRMED 8) − 5 (COUNTERTREND)
strategy_fit_score = dopasowanie reżimu z rejestru × 100   (obie skale 0–100; żadna nie jest prawdopodobieństwem)
```
Historia wyników **nie** wpływa na ranking (brak zweryfikowanej próby OOS) – to jawna reguła, nie przeoczenie.
Brak poprawnego kandydata → `selected_strategy_id = null`, stan `SCANNING` z przyczynami („Dlaczego nie ma setupu?”).

## Histereza i stabilność
| Parametr | Start | Znaczenie |
|---|---|---|
| `min_switch_margin` | 8 pkt | przewaga rankingu potrzebna do zmiany |
| `switch_confirm_updates` | 2 | kolejne aktualizacje z NOWYMI danymi |
| `min_selection_hold_seconds` | 60 s | minimalny czas utrzymania wyboru |
| `conflict_margin` | 5 pkt | LONG vs SHORT w tym samym horyzoncie bliżej niż margines → brak wyboru |
| `downgrade_confirm_updates` | 2 | obniżenie etapu setupu dopiero po 2 nowych odczytach |
| `cancel_after_misses` | 3 | setup niewykrywany 3 razy z rzędu → CANCELLED (zostaje w historii) |
Unieważnienie, wygaśnięcie, utrata danych i wyłączenie strategii działają **natychmiast** (histereza nie przetrzymuje nieważnego setupu).
Replay: rozkład przyczyn zmian wyboru w raporcie porównania.

## Pozycje i zlecenia
Zmiana wyboru dotyczy tylko nowych okazji. Otwarta pozycja zachowuje `strategy_id`, wersję, SL i TP z chwili otwarcia
(test `test_selected_confirmed_setup_executes_once_in_paper`). Jedno wejście na setup (UNIQUE entry_key), timeout → UNKNOWN bez ponowienia.

## Claude
Otrzymuje ranking, reżim, wybrany setup i alternatywę (`get_strategy_candidates`). Wywoływany przy zmianie wyboru i nowym EARLY/CONFIRMED
wybranego setupu (limity częstotliwości i budżetu). Może zaproponować `preferred_strategy_id` – tylko z rejestru, tylko jako sugestia.
Odpowiedź jest związana ze snapshot_id/setup_id/etapem; spóźnione odpowiedzi nie są stosowane. Bez klucza selektor działa normalnie.

## Kontrakt API `mq-auto-1.0.0`
`GET /api/v1/strategy/auto` → `strategy_mode, system_state, regime, selected_strategy_id, selected_strategy_version, selected,
selection_reason_codes, candidate_ranking, alternative, selected_at, last_evaluated_at, snapshot_id, data_status, last_change,
per_strategy, setups, funnel, strategies, why_no_setup`; `ai_status` i `execution_permission` – w rekordzie decyzji (`GET /api/v1/decision`).
`POST /api/v1/strategy/mode {strategy_mode, manual_strategy_id}` · `POST /api/v1/strategy/toggle {strategy_id, scan?, trade?}` ·
`POST /api/v1/strategy/profile {profile}` · `GET /api/v1/strategy/selection-log` · `GET /api/v1/playbook`. Zmiany wymagają sesji, Origin i CSRF.
Zdarzenie WebSocket `auto` niesie skrócony stan. Po restarcie: tryb i ustawienia są odtwarzane, ale wcześniejsze setupy są oznaczane
`RESTART_REVALIDATION` i wracają dopiero po ponownym wykryciu na świeżych danych.
