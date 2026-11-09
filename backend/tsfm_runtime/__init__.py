"""Runtime of the additional time-series foundation models Chronos-2 and FinCast (1.37).

Runs in separate processes from the model environments (.venv_chronos2, .venv_fincast). The bot imports only the stdlib parts
(lock, manifest, install.download) - never torch."""
RUNTIME_VERSION = "PMW-TSFM-RT-1"
