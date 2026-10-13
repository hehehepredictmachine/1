# Mapa ujednolicenia strategii S01–S12 (1.10)

## Cel

S01–S11 zostają różnymi hipotezami i zachowują swoje `strategy_id`, historię oraz jawne różnice. Ujednolicone są **kontrakty i semantyka**, nie znaczenie strategii.

**Co jest wspólne dla wszystkich:**
- jeden kontrakt `Strategy` / `MarketView` / `Draft` (`strategies/base.py`);
- jeden skaner (`registry.scan`), jeden tracker etapów, jeden selektor AUTO;
- jeden silnik ryzyka, jedna bramka wykonania;
- **jedna polityka wyjścia** zapisywana przy otwarciu (`execution/policy.py`, MQ-EXIT-POLICY-1.0.0).

Nie ma drugiego, konkurencyjnego silnika ani toru `order_send`.

## Wspólna semantyka

| Element | Wspólna definicja | Gdzie |
|---|---|---|
| Etapy | WATCH / EARLY / CONFIRMED (tracker) + terminalne INVALIDATED / EXPIRED / MISSED_ENTRY / CANCELLED / ENTERED | `strategies/base.finalize`, `tracker.py` |
| Dostępność informacji | tylko zamknięte świece; świeca w trakcie podnosi najwyżej do EARLY; pivoty po `right` świecach; wyższe TF as-of | `base.TFView`, `indicators.pivots`, `analysis/*` |
| Plan | entry (zone, trigger, max oddalenie w ATR, max czekanie), SL, cele z wagami, `exit_rules` | `common.plan`, `common.valid_targets` |
| RR po kosztach | wspólny silnik (Ask/Bid, kalkulatory brokera, prowizja z historii, stres poślizgu) | `risk/engine.py`, `risk/costs.py` |
| TP1 / BE / time-exit / trailing | z planu setupu, **zamrożone przy otwarciu**; BE dopiero po potwierdzonym TP1; trailing deklarowany przez S02 nie jest wykonywany w żadnej ścieżce (spójnie) | `execution/policy.py`, `manager.py`, `paper.py`, `ml/labels.py`, `tools/replay_strategies.py` |
| Deduplikacja | `setup_id` = symbol + konto + strategia + kierunek + TF + struktura; `event_id` = zdarzenie rynkowe (kubełek poziomu) – jedno zdarzenie dla ML/sygnałów | `registry.setup_id_for/event_id_for` |
| Plan vs fill | `order_attempts.price_requested` / `fill_price`; RR_FROM_FILL przelicza TP od fillu | `gateway.py`, `policy.rebase_on_fill` |
| Braki danych i odmowy | `missing_confirmations` / `reason_codes`; S12 ma jawną listę odrzuceń per wariant | strategia, `registry.scan` |
| Punktacja | ranking 0–100 – **nie** prawdopodobieństwo; nie zastępuje warunków koniecznych | `base.score` |

## OLD_STRATEGY_ID → rodzina / reżim → wspólne moduły → reguły specyficzne → zgodność po migracji

| ID | Rodzina / reżim (fit) | Wspólne moduły | Reguły specyficzne (bez zmian) | Zgodność po migracji 1.10 |
|---|---|---|---|---|
| S01 TREND_PULLBACK | TREND / TREND_UP-DOWN | base, indicators (EMA, ATR, ER), common.plan/targets, policy | korekta w strefie EMA20–50, trigger nad high poprzedniej | ID i historia zachowane; wyjście: BE i time-exit 36 z **planu** (wcześniej BE z ustawień) |
| S02 ADAPTIVE_TREND | TREND | jw. + KAMA | zmiana stanu KAMA/ER | trailing `KAMA_STATE_FLIP` zadeklarowany, **niewykonywany** w żadnej ścieżce (`trailing_executed=False`) – jawna różnica |
| S03 CHANNEL_BREAKOUT | BREAKOUT / EXPANSION | jw. + donchian_prior | kanał z poprzednich N świec | bez zmian reguł; polityka wyjścia z planu |
| S04 VOLATILITY_COMPRESSION_BREAKOUT | BREAKOUT / COMPRESSION | jw. + bb_width, percentile | box kompresji | jw. |
| S05 SESSION_RANGE_BREAKOUT | BREAKOUT | jw. + strefy czasowe sesji | zakres otwarcia sesji | `session_end_utc` w planie; zakończenie sesji nie jest wykonywane jako wyjście (spójnie we wszystkich ścieżkach) |
| S06 BREAKOUT_RETEST | BREAKOUT | jw. + pivots | poziom → wybicie → retest → reakcja | podobna idea do S12-C, ale **inna definicja** (poziom pivota, TF M5/M15); obie zostają, `event_id` grupuje wspólne zdarzenia |
| S07 FAILED_BREAKOUT_RECLAIM | REVERSION | jw. | wyjście poza poziom i powrót | koncepcyjnie bliska S12-A (reclaim), ale inny poziom (Donchian) i TF |
| S08 RANGE_EDGE_REVERSION | REVERSION / RANGE | jw. | odrzucenie krawędzi zakresu na M5/M15 | podobna do S12-A; S12 dodaje strefy M1, walls i aktywność – zostają osobno, porównanie w ablation |
| S09 STATISTICAL_MEAN_REVERSION | REVERSION | jw. + zscore | z-score ≤ −2 i odwrócenie | bez zmian; time-exit 20 z planu |
| S10 EXHAUSTION_STRUCTURE_REVERSAL | REVERSAL | jw. + RSI, pivots | wyczerpanie + CHoCH | bez zmian |
| S11 EMA20_PULLBACK_2_5R | TREND (FIXED Pine) | jw. + ema_pullback_core | RR 2,5 od fillu, bez TP1/BE/time-exit | `time_exit_bars=None` obsługiwane jawnie (etykiety, replay, polityka); TP od fillu także w etykietach i replay |
| S12 WALLS_RANGE_FAMILY | RANGE_WALLS (3 warianty + arbiter) | base, analysis/range_m5, walls, candles, chart_patterns, levels, policy | RANGE_RECLAIM / WALL_REJECTION / BREAKOUT_RETEST | nowa, CANDIDATE, scan-only |

## Usunięte powielenia i rozbieżne definicje (1.10)

| Problem 1.9 | Rozwiązanie |
|---|---|
| Wagi TP1 i BE brane z globalnych ustawień w zarządzaniu pozycją, a z planu w etykietach ML i replay | jedna polityka `execution/policy.py`, zapisana przy otwarciu |
| Cel środkowy (3 cele) gubiony przy rejestracji pozycji | wszystkie cele w polityce, częściowe wyjścia na każdym celu pośrednim |
| `time_exit_bars` ignorowany na żywo, domyślne 24 w etykietach i replay, `None` = błąd | jedna interpretacja: wartość z planu albo jawny brak |
| Koszt prowizji w ML z innego źródła niż wykonanie | `resolve_commission` wszędzie |
| Listy strategii zakodowane na sztywno (walidatory S01–S11, API S01–S10) | wyprowadzane z `registry.STRATEGIES` (config, API toggle, toggles domyślne) |

## Jawne, zachowane różnice

- **Trailing S02 i koniec sesji S05:** w planie, ale niewykonywane. Spójnie we wszystkich ścieżkach. Wdrożenie wymaga stanu strategii po otwarciu pozycji, co jest osobnym zadaniem.
- **Rozstrzyganie wewnątrz świecy:**
  - etykiety ML: zarejestrowane kwotowania (kursor po TP1), bez nich AMBIGUOUS;
  - replay: M5 OHLC, SL najpierw, a cel + BE w jednej świecy daje AMBIGUOUS.
  Oba podejścia są konserwatywne, ale inne. Przy tych samych danych bez ticków obie ścieżki zwracają AMBIGUOUS lub ten sam wynik.
