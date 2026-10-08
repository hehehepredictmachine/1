# Kontrakt M06T v1.0.0-CANDIDATE

**Źródła:** M06R `M06R_CONFIRMED_SIGNALS.jsonl`, `M06R_STAGE_LEDGER.jsonl` (niezmieniona historia stanów), eksport ticków M06H `symbol,time_utc,bid,ask,source_id,available_at`, zamrożony protokół, opcjonalne wydarzenia M06H / M04N archive. M06T nie pobiera danych z internetu i nie wykonuje zleceń.

**Tożsamość:** `setup_id`, `strategy_id`, `strategy_version`, `direction`, `mode` i czasy potwierdzeń identyczne w M06R. Wymagane pełne sześć faz, monotoniczne `available_at` i brak powielonych `bar_evidence_id`. `frozen_at <= DISCOVER.available_at` oraz zgodność profilu z sygnałem. Nie zmienia się historii ani kodu M06R.

**Przeniesienie do M06:** hipotetyczne warunki `MARKET_NEXT_AVAILABLE_TICK` z zamrożonymi dystansami SL/TP względem znanego historycznego midquote; `source=MT5_DERIVED`, `bar_state=CLOSED`, dowody point-in-time. Zachowany `M06_REFERENCE_ENGINE.validate_config`, `prepare_ticks`, `trade_one`, `metric`. Indeksowanie binarne jest jedynie optymalizacją doboru fragmentu ticków, a nie alternatywnym kalkulatorem P&L. Tranzakcje oznaczone `simulation_only=true` i `execution_permission=BLOCKED`.

**Filtry makro:** importer `M06H_RESEARCH_ENGINE.load_events`. Używa tylko wydarzeń, których `known_at` i `impact_known_at` nie są późniejsze niż sygnał. Jedna publikacja może występować u FF/MM/BLS; M06H deduplikuje wspólne zdarzenia. `NOT_PROVIDED` i syntetyczny kalendarz nie mogą prowadzić do fałszywego wyniku porównania. Gdy historyczny kalendarz jest częściowy, porównanie `EXPLORATORY_PARTIAL_COVERAGE`.

**Walidacja:** oddzielne DEV/OOS i purge transakcji przekraczających granice prób realizuje M06. Dodatkowo M06T eliminuje wyniki z nieciągłą ścieżką tickową. Niska próba OOS i niezweryfikowane parametry rachunku blokują wszelkie wnioski LIVE.

**Wyjście:** `M06T_REPORT.json`, `M06T_REPORT_PL.md`; schemat v2.0.0, `live_eligible=false`, `execution_permission=BLOCKED`. Brak mutacji innych modułów oraz brak integracji LIVE. Status `CANDIDATE/PENDING APPROVAL`.
