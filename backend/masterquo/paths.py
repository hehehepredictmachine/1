"""Filesystem layout. Everything is relative to the installation folder.

<root>/backend/masterquo      application package
<root>/backend/vendor         unchanged legacy MasterQUO engines (read-only)
<root>/frontend/dist          built web monitor served by the backend
<root>/data                   user-local: config, database, logs, secrets (never packaged)
"""
from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = PACKAGE_DIR.parent
ROOT_DIR = BACKEND_DIR.parent
VENDOR_DIR = BACKEND_DIR / "vendor"
LEGACY_CORE_DIR = VENDOR_DIR / "legacy_core"
M04N_DIR = VENDOR_DIR / "m04n"
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"
# 1.46 arch (I0125): the ONE default loopback port of the bot (config.ServerConfig.port, CLI fallbacks, Studio's bot port). The Go launcher
# (desktop/engine.go) and the .bat texts keep their own copy of this number - they cannot import Python.
DEFAULT_PORT = 8765


def _same_file(a: str, b: str) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def child_pythonpath(python: str | None = None) -> str:
    """1.42.11: PYTHONPATH procesu potomnego.

    * Proces na Pythonie bota (``sys.executable``; ``python=None`` też oznacza Pythona bota): ``backend`` + biblioteki aplikacji z bieżącego
      PYTHONPATH. W aplikacji DESKTOP biblioteki (numpy, pandas, MetaTrader5 …) leżą w ``<home>\\pyenv\\cp313-*\\site-packages`` i trafiają
      do Pythona tylko przez PYTHONPATH od launchera – dziecko z samym ``backend`` kończyło się ``ModuleNotFoundError: numpy``
      (eksport historii, TrainHub, rodziny modeli).
    * Proces w osobnym środowisku (.venv_candles, .venv_kronos, .venv_granite …): tylko ``backend`` – jego pakiety nie mogą się mieszać
      z bibliotekami bota (inne wersje numpy / inny Python)."""
    import sys
    backend = str(BACKEND_DIR)
    if python is not None and not _same_file(python, sys.executable):
        return backend
    keep = [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p and not _same_file(p, backend)]
    return os.pathsep.join([backend, *keep])


def data_dir() -> Path:
    """Data folder; MASTERQUO_DATA_DIR allows isolated test/demo instances. Without it: <root>/data, or the data folder of the
    Windows app when the program runs from its folder (mq_instruments.default_data_dir - same rules as desktop/layout.go)."""
    override = os.environ.get("MASTERQUO_DATA_DIR")
    if override:
        path = Path(override).resolve()
    else:
        from mq_instruments import default_data_dir
        path = default_data_dir(ROOT_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    p = data_dir() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def backups_dir() -> Path:
    p = data_dir() / "backups"
    p.mkdir(parents=True, exist_ok=True)
    return p
