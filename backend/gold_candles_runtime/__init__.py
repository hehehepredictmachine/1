"""MasterQUO integration runtime for the reference module `gold_candles` (runs ONLY in the isolated .venv_candles).

The bot process never imports pandas / gold_candles: it talks to `gold_candles_runtime.worker` over JSON lines and gives
it the bot's own closed M5/M30 bars (no second MT5 session, no initialize()/shutdown() of the shared session).
`gold_candles/` itself is the unmodified reference (its contract hash covers data/patterns/features/model.py)."""
RUNTIME_VERSION = "1.0.0"
