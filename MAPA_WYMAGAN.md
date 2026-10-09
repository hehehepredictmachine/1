# Mapa wymagań

Legenda stanów: **I** – istnieje w kodzie · **P** – podłączone do kanonicznego przepływu · **O** – sprawdzone offline (testy automatyczne
lub uruchomienie na symulatorze) · **M** – sprawdzone na Twoim MT5 (Windows). Kolumna M wszędzie = **NIE**: nie miałem dostępu do Windows,
Twojego terminala ani klucza Claude. Do weryfikacji M służą `02_DIAGNOSTYKA.bat` i `06_DIAGNOZA_CZASU_MT5.bat`.

| # | Wymaganie | Źródło | Implementacja | Test | I | P | O | M |
|---|---|---|---|---|---|---|---|---|
| 1 | Połączenie z zalogowanym terminalem, opcjonalna ścieżka terminala, bez hasła | zlecenie §4 | `mt5/bridge.py connect()`, `mt5.terminal_path` | `test_connect_six_timeframes_exact_symbol` | T | T | T | NIE |
| 2 | Jeden worker MT5 z kolejką priorytetową | §3 | `mt5/worker.py` | wszystkie testy bridge | T | T | T | NIE |
| 3 | Rachunek, serwer, demo/real, waluta, netting/hedging | §4 | `_account_dict`, `accounts_seen` | `test_connect…`, `test_mode_requires_confirmation…` | T | T | T | NIE |
| 4 | Dokładny `XAUUSD-`, błąd z listą kandydatów, bez podmiany | §1, §4 | `_check_symbol`, `config.MT5Config` | `test_symbol_not_found_no_substitution`, `test_exact_symbol_kept`, `test_no_wrong_default_symbol_in_active_code` | T | T | T | NIE |
| 5 | Bid/Ask, czas ticka, point, digits, tick size, wolumeny, stops/freeze, tryb handlu | §4 | `_check_symbol`, `_poll_quote` | `test_connect…` | T | T | T | NIE |
| 6 | OHLC, tick_volume, real_volume dla M1…D1 niezależnie od widoku | §4 | `_load_all_history`, `poll()` | `test_connect…` | T | T | T | NIE |
| 7 | Balance/equity/margin, pozycje, zlecenia, deals | §4 | `_poll_account`, `_poll_deals` | `test_timeout_unknown…` (reconcyliacja z pozycji) | T | T | T | NIE |
| 8 | Zrzut historii, bieżąca świeca, nowa zamknięta, uzupełnienie luk | §4, §5 | `_merge_tail` (gap fill), `Bar.basis` | `test_gap_fill_after_missed_polls` | T | T | T | NIE |
| 9 | Heartbeat, backoff, diagnostyka, zmiana rachunku/terminala → wygaszenie decyzji | §4 | `poll()`, `_handle_failure`, `session_epoch`, `ModeManager.reset` | `test_disconnect_reconnect_and_account_change` | T | T | T | NIE |
| 10 | WARMING_UP / INSUFFICIENT_HISTORY z instrukcją, bufor z wymagań | §4 | `data/quality.assess_tf`, `Profiles.required_closed_bars` | `test_insufficient_history…`, `test_history_requirements_from_profiles` | T | T | T | NIE |
| 11 | Kontrakt czasu: offset serwera mierzony, nie zgadywany; UTC wewnętrznie; s vs ms | §5 | `mt5/clock.py`, `timeutil.py` | `TestClock` (5 testów) | T | T | T | NIE |
| 12 | FUTURE_CANDLE_AVAILABILITY: zamknięcie = zaobserwowana następna świeca; available_at live vs historyczne | §5 | `bridge._merge_tail`, `_bar_json` | `test_connect…` (`close_confirmed_utc == next open`) | T | T | T | NIE |
| 13 | Walidacja OHLC, duplikaty, kolejność, luki, przyszłe znaczniki, wiek quote/historii per TF | §5 | `data/quality.py` | `TestQuality` (7 testów) | T | T | T | NIE |
| 14 | Weekend i przerwy sesji rozpoznawane, bez dorabiania świec | §5 | `SessionModel` | `test_weekend_gap_is_recognised`, demo (SESSION_BREAK) | T | T | T | NIE |
| 15 | STALE przy złym czasie/rozłączeniu, blokada wejść, przyczyna widoczna | §5 | `quality.assess`, odznaki STALE w UI | `test_stale_quote_blocks_entries…`, zrzuty UI | T | T | T | NIE |
| 16 | Diagnostyka czasu z surowymi wartościami | §5 | `python -m masterquo clock`, `06_DIAGNOZA_CZASU_MT5.bat` | uruchamiane tylko na Windows | T | T | NIE | NIE |
| 17 | Logika MasterQUO jako wykonywalne reguły (M02/M02I/M03/M07) | §6 | `engine/legacy.py` (silniki bez zmian) | `TestVendoredEnginesUnchanged`, uruchomienie demo | T | T | T | NIE |
| 18 | Profile wskaźników bez zmiany metody (Wilder, MACD SMA) | §6 | profil M02I v1.1, `chartdata.py` | `test_macd_signal_is_sma_in_profile` | T | T | T | NIE |
| 19 | Pivot/struktura bez look-ahead | §6 | M02/M03 + snapshot | `TestNoLookahead` | T | T | T | NIE |
| 20 | Pola analysis_direction / signal_stage / decision / execution_permission / reason_codes | §6 | `engine/decision.py` | `TestDecisionSeparation` | T | T | T | NIE |
| 21 | Jawne drzewo decyzji z warunkami spełnionymi/niespełnionymi | §6 | `decision.build` (7 węzłów) | `test_full_chain_to_paper_execution` | T | T | T | NIE |
| 22 | Cykl życia setupu (M10A), trwały | §6 | `engine/lifecycle.py`, tabela `setups` | `TestLifecycle` (5 testów) | T | T | T | NIE |
| 23 | DXY opcjonalny, blokuje tylko strategie, które go wymagają | §6, §11 | `bridge._load_dxy`, `strategy.strategies_requiring_dxy` | — (konfiguracja) | T | T | NIE | NIE |
| 24 | Agent Claude przez oficjalne SDK, model z konfiguracji | §7 | `agent/service.py` | `TestAgent` (atrapa klienta) | T | T | T (atrapa) | NIE |
| 25 | Edytowalny, wersjonowany prompt + mapa pochodzenia | §7 | `agent/prompts/…md`, `docs/MASTERQUO_SPEC_REKONSTRUKCJA_v1.0.0.md` | `test_tool_loop…` (prompt_version) | T | T | T | — |
| 26 | Narzędzia read-only + pętla tool_use/tool_result + walidacja argumentów | §7 | `agent/tools.py` | `test_tool_loop…`, `test_tool_argument_validation` | T | T | T | NIE |
| 27 | Structured outputs + walidacja + jedna naprawa | §7 | `OUTPUT_SCHEMA`, `AgentAssessment` | `test_invalid_json_repaired_once_then_fails` | T | T | T | NIE |
| 28 | Kontrakt decyzji AI (decision_id, snapshot_id, expires, model_id, prompt_version…) | §7 | `agent/schema.record` | `test_tool_loop…` | T | T | T | NIE |
| 29 | Odrzucenie starego snapshotu, innego rachunku, wygasłej decyzji, spóźnionej odpowiedzi | §7 | `gate_for`, `_started_seq` | `test_gate_rules`, `test_snapshot_mismatch_rejected`, `test_late_answer…` | T | T | T | NIE |
| 30 | Zdarzeniowe wyzwalanie, limit częstotliwości, budżet, koszt jako szacunek | §7 | `request`, `_preflight`, `_cost` | `test_budget_exhausted` | T | T | T | NIE |
| 31 | Brak klucza / zły klucz / timeout / limit / brak modelu / brak sieci | §7 | `run_once` (łańcuch wyjątków) | `test_timeout_rate_limit_auth_model`, `test_no_key…`, `test_model_must_be_configured…` | T | T | T | NIE |
| 32 | Newsy jako dane, nie instrukcje | §7 | `UNTRUSTED_EXTERNAL_DATA`, prompt | `test_tool_loop…` | T | T | T | — |
| 33 | Tryby READ_ONLY/PAPER/DEMO/LIVE, start READ_ONLY+AUTO OFF, potwierdzenie, LIVE flaga lokalna | §8 | `execution/modes.py` | `test_mode_requires_confirmation_and_limits`, `test_02_security` | T | T | T | NIE |
| 34 | Ryzyko M11: świeżość, koszty, RR netto, SL/TP, lot (floor, bez zaokrąglania w górę), margin, stops, netting | §8 | `risk/engine.py` | `TestRisk` (7 testów) | T | T | T | NIE |
| 35 | Limity: ryzyko/trade, suma, dzienna strata, DD, pozycje, cooldown, makro; definicja dnia | §8 | `RiskLimits`, `daily_loss_used` | `test_daily_loss_excludes_balance_operations` | T | T | T | NIE |
| 36 | Zero ≠ zero kosztów; spread nie liczony podwójnie | §8 | `risk/costs.py` | `test_spread_not_double_counted_and_rr_net` | T | T | T | NIE |
| 37 | „Spread 40%” – REQUIRES_DEFINITION, nieużywany | §8 | `CostConfig.spread_40pct_rule` | `test_defaults_safe` | T | T | T | — |
| 38 | Gateway: walidacja, order_check, retcode, częściowe, odrzucenie, rekonsyliacja, idempotencja, UNKNOWN | §8 | `execution/gateway.py`, `manager._resolve_unknown` | `TestExecution` (7 testów) | T | T | T (symulator) | NIE |
| 39 | SL/TP1/TP2 w gatewayu, SL→BE, tylko własne/przejęte pozycje, stop wejść ≠ zamknięcie | §8 | `gateway._send`, `manager._partial_close/_move_be`, `close_positions`, `adopt` | `test_demo_execution_once_with_sl_tp_and_restart`, `test_tp1_partial_and_breakeven_demo_and_paper` | T | T | T (symulator) | NIE |
| 40 | Monitor wg zdjęcia: układ, panele 1–6, newsy/ryzyko/log, H4/D1 przełącznik i 6 wykresów | §9 | `frontend/src` | zrzuty Playwright 1920×1080, 1366×768, 800×1000 | T | T | T | — |
| 41 | Wykresy z danych MT5: świece, tick volume, wskaźniki, RSI/MACD, strefy, entry/SL/TP, markery | §9 | `ChartPanel.tsx`, `zones.ts` | zrzuty | T | T | T | NIE |
| 42 | Synchronizacja, pełny ekran, zapamiętany układ | §9 | `ChartPanel` SYNC, `usePersisted` | interakcja Playwright (pełny ekran, 6 wykresów) | T | T | częściowo | — |
| 43 | Panel sygnałów (propozycja/zlecenie/pozycja/rozliczenie), EXECUTE z powodem blokady | §9 | `SignalsPanel.tsx` | zrzuty | T | T | T | NIE |
| 44 | Panel agenta: stan, analiza, scenariusze, pytania | §9 | `AgentDrawer.tsx` | zrzut (stan bez klucza) | T | T | częściowo | NIE |
| 45 | Statystyki z rozliczonych zdarzeń, bez liczb ze zdjęcia, equity ze snapshotów | §9 | `stats.py`, `StatsPanel.tsx` | `test_no_demo_numbers…` | T | T | T | NIE |
| 46 | Wersjonowane API + WS z seq i resynchronizacją | §10 | `api/app.py`, `events.py`, `api.ts` | `test_05_websocket_auth_and_resync` | T | T | T | — |
| 47 | Trwałość: migracje, kopia zapasowa, odtworzenie po restarcie | §10 | `db/database.py` | `test_migrations_and_backup`, `test_demo_execution…restart` | T | T | T | NIE |
| 48 | Loopback, Host/Origin, CSRF, autoryzacja WS | §10 | `api/security.py` | `test_02_security`, `test_05…` | T | T | T | — |
| 49 | Klucz API tylko w backendzie (DPAPI), nigdy w API/logach | §10 | `secrets_store.py` | `test_04_secret_never_returned` | T | T | T (bez DPAPI – Linux) | NIE |
| 50 | M04N: statusy, deduplikacja, brak „brak wydarzeń” | §11 | `news/service.py` | uruchomienie (sieć zablokowana → UNAVAILABLE pokazane uczciwie) | T | T | częściowo | NIE |
| 51 | Replay/rozliczenia/badania jako narzędzia | §11 | `research/`, `python -m masterquo export` | `test_export_loads_in_m06r` | T | T | T | NIE |
| 52 | Kontrolowane uczenie: propozycje z wersją, bez mutacji LIVE | §11 | `agent_memory`, UI akceptacji do OOS | `test_tool_loop…` (zapis), ręcznie | T | T | częściowo | — |
| 53 | Telegram opcjonalny, wyłączony, deduplikacja | §11 | `notify/telegram.py` | — | T | T | NIE | NIE |
| 54 | Launchery 01–06, venv, x64, 3.13, log, bez globalnego pip | §12 | `*.bat`, `tools/check_python.py`, `requirements/requirements-win.txt` | `pip download --require-hashes` win_amd64 cp313/cp312 OK; BAT nieuruchomione | T | T | częściowo | NIE |
| 55 | Pojedyncza instancja, STOP tylko tego projektu | §12 | `__main__.py` (lock, token) | `test_01…`, `test_99_stop_only_this_server` | T | T | T | NIE |
| 56 | Kreator pierwszego uruchomienia (terminal, symbol, klucz, model, test) | §12 | `SettingsModal` | zrzut | T | T | T | NIE |
| 57 | Tryb demonstracyjny DANE SYNTETYCZNE, osobna baza | §12 | `--demo`, `mt5/fake.py`, baner | zrzuty | T | T | T | — |
| 58 | Eksport historii 6 TF z czasem UTC | §11 | `diagnostics.export_history` | `test_export_loads_in_m06r` | T | T | T | NIE |
| 59 | (1.1) Mniej restrykcyjne bramki: polityka struktury H1_LEAD/H1_H4_NOT_OPPOSING/STRICT, kod M02 bez zmian | prośba użytkownika | `engine/legacy.resolve_structure`, `strategy.structure_policy` | `TestStructurePolicy` | T | T | T | NIE |
| 60 | (1.1) RR warunkowy wykonywany ze zmniejszonym ryzykiem, progi konfigurowalne | prośba użytkownika | `risk/engine.py`, `risk.conditional_*` | `test_rr_thresholds` | T | T | T | NIE |
| 61 | (1.1) Rola AI: VETO (domyślnie) / REQUIRED / ADVISORY, czekanie na weto | prośba użytkownika | `agent/service.gate_for` | `test_veto_policy`, `test_gate_rules`, `test_no_key_means_unavailable_gate` | T | T | T | NIE |
| 62 | (1.1) Brak kalendarza makro nie blokuje (okno wydarzenia nadal tak), okno wejścia konfigurowalne, migracja config v1→v2 | prośba użytkownika | `engine/decision.py`, `engine/lifecycle.py`, `config.migrate` | `TestDecisionRelaxed`, `test_confirmed_window_configurable`, `TestConfigMigration` | T | T | T | NIE |
| 63 | (1.2) AUTO wybór strategii oddzielony od trybu i wykonywania zleceń; AUTO/MANUAL w backendzie | prompt AUTO §2, §11 | `strategies/selector.py`, `/api/v1/strategy/mode` | `test_06_auto_strategy_api_separate_from_execution`, `test_auto_selection_runs_without_ai_or_dxy_and_never_enables_orders` | T | T | T | NIE |
| 64 | (1.2) MarketRegimeEngine – stany, konflikty TF, STALE | prompt AUTO §4 | `strategies/regime.py` | `test_auto_selection…` (stan), `test_stale_after_mt5_loss_then_reconnect` | T | T | T | NIE |
| 65 | (1.2) Ranking, histereza, natychmiastowe odrzucenie nieważnego, event_id, konflikt LONG/SHORT | prompt AUTO §5–6 | `selector.py` | `TestSelector` (3 testy) | T | T | T | NIE |
| 66 | (1.2) 10 kompletnych strategii LONG/SHORT, WATCH/EARLY/CONFIRMED, SL/TP/wyjście | prompt 10 strategii §4–6 | `strategies/s01…s10` | `TestRulesPerStrategy` (×10), `TestTracker` (×10) | T | T | T | NIE |
| 67 | (1.2) Punktacja 0–100 bez sztucznego mianownika, skorelowane wskaźniki jako jedna kategoria | prompt ACTIVE §3 | `strategies/base.py score` | `TestScoringAndStages` | T | T | T | NIE |
| 68 | (1.2) Świeca tworząca się tylko dla WATCH/EARLY; brak look-ahead | prompt ACTIVE §6 | `finalize`, `indicators.py` | `test_unclosed_trigger_bar_never_confirms`, `TestNoLookAhead` | T | T | T | NIE |
| 69 | (1.2) Pozycja zachowuje strategię po zmianie wyboru; brak duplikatów zleceń | prompt AUTO §6 | gateway, managed_positions | `test_selected_confirmed_setup_executes_once_in_paper` | T | T | T | NIE |
| 70 | (1.2) Tło GIF + żaba przy BALANCE, FULL/LIGHT/OFF, prefers-reduced-motion, Page Visibility | prompt AUTO §8–10 | `appearance.tsx`, `Header.tsx`, `styles.css` | Playwright: kadry FULL różne, OFF identyczne, brak nakładania, brak poziomego scrolla (3 rozdzielczości); `test_08_gif_assets_and_upload` | T | T | częściowo (animowane tło wymaga wgrania oryginału) | NIE |
| 71 | (1.2) Replay/OOS runner, porównanie ORIGINAL vs ACTIVE | prompt 10 strategii §11, ACTIVE §10 | `tools/replay_strategies.py` | przebieg syntetyczny; dane brokera NOT_RUN | T | T | syntetycznie | NIE |
| 72 | (1.3) Pełna paleta kolorów, motywy, import/eksport, kontrast | prompt Kolory §1 | `theme.tsx`, `ThemeDialog.tsx`, `styles.css` | `test_ui_monitor` 04/06/07 | T | T | T | NIE |
| 73 | (1.3) Niezależny zoom per wykres, przyciski, stan widoku, grupy sync | prompt Zoom §2 | `ChartPanel.tsx`, `chartview.ts` | `test_ui_monitor` 01–06 | T | T | T | NIE |
| 74 | (1.3) Decision Tree + XGBoost: dane, etykiety, walidacja, rejestr, predykcje, dryf | prompt ML §3–5 | `backend/masterquo/ml/*` | `test_ml` (24) | T | T | syntetycznie | NIE (dane z Twojego MT5) |
| 75 | (1.3) Tryby SIGNALS/PAPER/AUTO_DEMO/AUTO_LIVE bez READONLY | prompt §6 | `execution/modes.py`, `config.py`, migracja 0003 | `test_risk_execution`, `test_app_process` | T | T | T | NIE |
| 76 | (1.3) Checklista 12A, panel ML 12B, osobne statusy | prompt §12 | `engine/checklist.py`, `Checklist.tsx`, `MLPanel.tsx`, `Header.tsx` | `test_checklist`, `test_ui_monitor` 08 | T | T | T | NIE |
