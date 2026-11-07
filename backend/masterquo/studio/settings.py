"""Studio settings + data directory (separate from the bot). Default data dir: MQ_STUDIO_DATA_DIR, else <app root>/data_studio.
The bot's data dir (shared candle store, inbox, export lock) and port are configured here, never guessed from a 'latest' folder."""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULTS = {"port": 8780, "bot_port": 8765, "bot_data_dir": None, "profile": "smoke", "continue_after_failure": True}


def data_dir() -> Path:
    from .. import paths
    d = Path(os.environ.get("MQ_STUDIO_DATA_DIR") or (paths.ROOT_DIR / "data_studio"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def bot_data_dir(s: dict | None = None) -> Path:
    s = s or load()
    if s.get("bot_data_dir"):
        return Path(s["bot_data_dir"])
    from .. import paths
    return Path(os.environ.get("MQ_BOT_DATA_DIR") or (paths.ROOT_DIR / "data"))


def load() -> dict:
    p = data_dir() / "settings.json"
    try:
        return {**DEFAULTS, **json.loads(p.read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save(patch: dict) -> dict:
    s = {**load(), **{k: v for k, v in patch.items() if k in DEFAULTS}}
    p = data_dir() / "settings.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=1), encoding="utf-8")
    tmp.replace(p)
    return s


def export_lock_path(s: dict | None = None) -> Path:
    """ONE lock file shared by every Studio instance and the bot's export (in the bot's data dir)."""
    return bot_data_dir(s) / "locks" / "pmw_export.lock"
