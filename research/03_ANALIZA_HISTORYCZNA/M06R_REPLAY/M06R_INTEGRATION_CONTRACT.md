# M06R — kontrakt integracyjny

**Wejście:** katalog z 6 niezależnych CSV MT5 (D1/H4/H1/M15/M5/M1), tym samym dokładnym symbolem, UTC, szeregami OHLC typu BID. Każdy wiersz ma `symbol,time_utc,open,high,low,close,bar_state` i opcjonalnie `tick_volume,available_at_utc`; eksport M06R dodaje też `MT5_EXPORT_MANIFEST.json` z SHA256. Wszystkie wiersze muszą być zamknięte.

**Czas wiedzy:** wiersze po `available_at` nie mogą być widziane wcześniej; eksport MT5 ustala konserwatywną dostępność po otwarciu następnego baru. M06R nie certyfikuje źródła plików z dysku. Migawki wewnętrzne zawsze mają `replay_only=true`, `_fixture_only=true`, `execution_gate=PENDING`.

**Analityka:** zachowane `M02_REFERENCE_ENGINE.analyze`, `M02I_INDICATOR_ENGINE.analyze`, `M03_REFERENCE_ENGINE.analyze` działają z jednym `snapshot_id`. `M07_M03E_PROFILE_DETECTOR.discover` automatycznie wybiera tylko setupy z rzeczywistymi ID dowodów w tej migawce. `M03E_M10_PIPELINE.construct_early`, `M10_AUTO_TRIGGER_CONFIRM.rules_valid/matched` rozpoznają warunki; replay posiada własny **badawczy**, uproszczony dziennik stanów (nie jest produkcyjnym SQLite M10, M09-routowanym czy M14-autoryzowanym przepływem).

**Wyjście:** `M06R_REPLAY_REPORT.json`, `M06R_STAGE_LEDGER.jsonl`, `M06R_CONFIRMED_SIGNALS.jsonl`, `M06R_REPORT_PL.md`. Brak transakcji, kosztów, win-rate, ROI, fill, SL/TP. Samo `CONFIRMED` jest zdarzeniem analitycznym, nie zleceniem ani autoryzacją M14.

**M04N/M06H:** opcjonalne znane w danym momencie wydarzenia z wcześniejszych migawek. Znana publikacja HIGH/EXTREME może oznaczyć potencjalną blokadę; nieobecność wydarzenia = częściowy/niekompletny kalendarz, nie zwolnienie z blokad M04/M11. Zmiany dat dostępne później nie działają wstecz.

**M06:** import do pełnego backtestu wymaga osobnego, zamrożonego planu wejścia/SL/TP i ticków brokera z kosztami; obecne wyjście jest **research signal ledger**, a nie kompletnym `M06` execution packet. Konwersja z brakującymi polami ma zakończyć się `NOT_RUN`, nigdy wypełnieniem dowolną ceną.

**Wersjonowanie:** sam moduł v1.0.0-CANDIDATE, `schema_version=2.0.0`, `prompt_version=4.1.0`. Zachowane silniki nie zostały zmodyfikowane. Brak zamówień, screenshotów, OCR, real-time AI czy autoryzacji LIVE.
