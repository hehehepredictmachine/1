"""Strategy presets of the Control Tower / Strategy Lab (1.32: "Save Preset", "Load", "Reset" of the STRATEGY CONTROL CENTER).

A preset is a named copy of the strategy-control fields of the REAL configuration (strategy selection, setup thresholds, trade
filters). Loading it writes those fields back through the same validated path as every settings change (PUT /api/v1/config); Reset
writes the defaults of the configuration model. Nothing else is touched (no execution mode, no risk limits, no account data).
Stored in <data>/presets/strategy.json."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

FIELDS: list[tuple[str, str]] = [
    ("active", "strategy_mode"), ("active", "manual_strategy_id"), ("active", "thresholds"),
    ("risk", "macro_block_high_impact"), ("risk", "max_spread_points"), ("risk", "rr_block_below"), ("risk", "rr_pass_from"),
    ("strategy", "d1_conflict_blocks_entry"),
]
NAME_RX = re.compile(r"^[A-Za-z0-9ĄĆĘŁŃÓŚŹŻąćęłńóśźż _.\-]{1,40}$")
MAX_PRESETS = 30


def _get(cfg_dict: dict, sec: str, key: str):
    return (cfg_dict.get(sec) or {}).get(key)


def snapshot(cfg_dict: dict) -> dict:
    return {f"{s}.{k}": _get(cfg_dict, s, k) for s, k in FIELDS}


def patch_of(values: dict) -> dict:
    """{"active.thresholds": …} -> {"active": {"thresholds": …}} (only known fields)."""
    out: dict = {}
    for s, k in FIELDS:
        name = f"{s}.{k}"
        if name in values:
            out.setdefault(s, {})[k] = values[name]
    return out


def defaults() -> dict:
    from .config import AppConfig
    return snapshot(AppConfig().model_dump(mode="json"))


class PresetStore:
    def __init__(self, data_dir: str | Path):
        self.path = Path(data_dir) / "presets" / "strategy.json"

    def _load(self) -> dict:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, d: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def list(self) -> list[dict]:
        return [{"name": n, **v} for n, v in sorted(self._load().items(), key=lambda kv: -kv[1].get("saved_at", 0))]

    def save(self, name: str, cfg_dict: dict) -> dict:
        name = (name or "").strip()
        if not NAME_RX.match(name):
            raise ValueError("NAZWA: 1–40 znaków (litery, cyfry, spacja, _ . -)")
        d = self._load()
        if name not in d and len(d) >= MAX_PRESETS:
            raise ValueError(f"LIMIT: najwyżej {MAX_PRESETS} presetów")
        d[name] = {"values": snapshot(cfg_dict), "saved_at": time.time()}
        self._save(d)
        return {"name": name, **d[name]}

    def get(self, name: str) -> dict | None:
        return self._load().get(name)
