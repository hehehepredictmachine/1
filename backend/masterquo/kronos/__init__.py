"""Kronos integration in the bot process (no torch here).

settings.py   own settings file data/kronos/settings.json (validated; the strict AppConfig is not touched, so a rollback stays simple)
calendar.py   empirical trading calendar from closed bars -> future candle timestamps (or a reason why they cannot be set)
quality.py    closed-bar checks: order, duplicates, OHLC geometry, missing values, gaps vs calendar, freshness, volume source
service.py    scheduler on closed bars from the EXISTING bridge, bounded queue + dedup + timeout, worker process (.venv_kronos), ledger
predictions.py  PMW-PRED-1 adapter, strategy context (OBSERVE / REQUIRED gate - fail-closed, never a permission)
validation.py walk-forward on the user's bars vs naive baselines (dev / final test split, non-overlapping horizons)
"""
