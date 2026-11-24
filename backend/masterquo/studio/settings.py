"""Studio settings + data directory (separate from the bot). Default data dir: MQ_STUDIO_DATA_DIR, else <app root>/data_studio.
The bot's data dir (shared candle store, inbox, export lock) and port are configured here, never guessed from a 'latest' folder."""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULTS = {"port": 8780, "bot_port": 8765, "bot_data_dir": None, "profile": "smoke", "continue_after_failure": True}
# 1.46: continue_after_failure is RESERVED - nothing reads it yet: the queue always goes on with the next job after a failed one (stopping
# the queue needs a queue-paused state + a resume control in the UI). The key stays (settings files / API keep it).
PROFILES = ("smoke", "research", "full")                     # trainhub / family budgets (frontend studio/main.tsx offers the same three)


def _check(key: str, v):
    """1.46: S.save stored anything - bot_port 'abc' / null broke /api/studio/connections, POST /api/studio/jobs and transfer (500) until
    the file was rewritten. Returns the clean value or raises ValueError (the API answers 400)."""
    if key in ("port", "bot_port"):
        if isinstance(v, bool) or not isinstance(v, (int, str)) or not str(v).strip().isdigit() or not 1 <= int(str(v).strip()) <= 65535:
            raise ValueError(f"{key}: port 1–65535")
        return int(str(v).strip())
    if key == "profile":
        if v not in PROFILES:
            raise ValueError(f"profile: {'|'.join(PROFILES)}")
        return v
    if key == "continue_after_failure":
        if not isinstance(v, bool):
            raise ValueError("continue_after_failure: true|false")
        return v
    if key == "bot_data_dir":
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        if not isinstance(v, str):
            raise ValueError("bot_data_dir: ścieżka katalogu albo null")
        return v
    return v


def data_dir() -> Path:
    from .. import paths
    d = Path(os.environ.get("MQ_STUDIO_DATA_DIR") or (paths.ROOT_DIR / "data_studio"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def bot_data_dir(s: dict | None = None) -> Path:
    s = s or load()
    if s.get("bot_data_dir"):
        return Path(s["bot_data_dir"])
    if os.environ.get("MQ_BOT_DATA_DIR"):
        return Path(os.environ["MQ_BOT_DATA_DIR"])
    from .. import paths
    try:                                         # the SAME rule as the bot (paths.data_dir without an override) - never a guessed folder
        from mq_instruments import default_data_dir
        return Path(default_data_dir(paths.ROOT_DIR))
    except Exception:  # noqa: BLE001 - development checkout without the helper
        return paths.ROOT_DIR / "data"


def load() -> dict:
    p = data_dir() / "settings.json"
    try:
        s = {**DEFAULTS, **json.loads(p.read_text(encoding="utf-8"))}
    except (OSError, ValueError, TypeError):
        return dict(DEFAULTS)
    for k, dv in DEFAULTS.items():           # 1.46: a bad value stored by 1.45.0 (no validation) = the default, never a 500 on every request
        try:
            s[k] = _check(k, s[k])
        except ValueError:
            s[k] = dv
    return s


def save(patch: dict) -> dict:
    clean = {k: _check(k, v) for k, v in patch.items() if k in DEFAULTS}          # 1.46: validated (ValueError -> 400)
    if clean.get("bot_data_dir") is not None and not Path(clean["bot_data_dir"]).is_dir():
        raise ValueError("bot_data_dir: katalog nie istnieje")
    s = {**load(), **clean}
    p = data_dir() / "settings.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=1), encoding="utf-8")
    tmp.replace(p)
    return s


class BotConfig:
    """Read-only holder of the BOT's configuration (same .get() as ConfigStore)."""

    def __init__(self, cfg):
        self._cfg = cfg

    def get(self):
        return self._cfg.model_copy(deep=True)


def bot_config(s: dict | None = None) -> BotConfig | None:
    """1.46: the BOT's config.json (broker symbol mappings, MT5 terminal, family pairs / basket), read-only. 1.45.0 built ConfigStore() in the
    Studio data dir: a default <studio>/config.json was created and the user's mappings were ignored (XAUUSD -> 'XAUUSD-', BTC -> None
    instead of e.g. 'GOLD.pro' / 'BTCUSD.pro'). Migrations run in memory only - Studio never rewrites the bot's file. Missing / unreadable
    = None (UNAVAILABLE: no broker symbol -> MT5 export blocked, never a guessed one)."""
    p = bot_data_dir(s) / "config.json"
    try:
        from ..config import AppConfig, migrate
        raw = json.loads(p.read_text(encoding="utf-8"))
        migrate(raw)
        return BotConfig(AppConfig.model_validate(raw))
    except Exception:  # noqa: BLE001 - no / unreadable / invalid bot config
        return None


def export_lock_path(s: dict | None = None) -> Path:
    """ONE lock file shared by every Studio instance and the bot's export (in the bot's data dir)."""
    return bot_data_dir(s) / "locks" / "pmw_export.lock"


if __name__ == "__main__":
    # 1.46 (I0139): `python -m masterquo.studio.settings` prints the port the Studio server listens on (settings.json of
    # MQ_STUDIO_DATA_DIR) - 36_STUDIO.bat opens the browser on it instead of a hard-coded 8780
    print(load()["port"])
