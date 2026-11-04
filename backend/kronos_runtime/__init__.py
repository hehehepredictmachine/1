"""Kronos runtime of PepeMarketWizard - runs ONLY in the isolated .venv_kronos (PyTorch, pandas, huggingface_hub).

The bot process (main .venv, no torch) never imports this package: it starts `python -m kronos_runtime.worker` from .venv_kronos and
talks JSON lines over stdin/stdout (masterquo/kronos/service.py). The worker never opens MetaTrader 5 - candles come from the bot's
existing bridge. Model code: vendor/kronos (upstream Kronos, MIT, only a package-relative import changed - see vendor/kronos/UPSTREAM.md).
"""
RUNTIME_VERSION = "kronos_runtime 1.0.0"
