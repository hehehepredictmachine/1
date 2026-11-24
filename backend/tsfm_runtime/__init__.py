"""Runtime of the additional time-series foundation models Chronos-2 (1.37), Granite TTM (1.40) and TiRex-2 (1.41).

Runs in separate processes from the model environments (.venv_chronos2, .venv_granite, .venv_tirex2). The bot imports only the stdlib
parts (lock, manifest, install.download) - never torch. FinCast is RETIRED (wycofany w 1.40, replaced by Granite TTM; used 1.37-1.39): its pin
stays in lock.py for the forecast history only; it is never installed, loaded or scheduled (no .venv of it is used)."""
RUNTIME_VERSION = "PMW-TSFM-RT-1"
