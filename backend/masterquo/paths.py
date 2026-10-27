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
DEFAULTS_FILE = ROOT_DIR / "config" / "masterquo.defaults.json"


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
