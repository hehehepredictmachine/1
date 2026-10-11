"""User preferences per trading account (MT5 server:login) - one source for the engine and the monitor.

  setup_view  {"mode": AUTO | SELECTED | ALL, "strategy_id": "S01".."S11" | None, "focus_setup_id": str | None}
      AUTO      engine's automatic selection (unchanged behaviour)
      SELECTED  the engine analyses / selects only the chosen strategy (same gates; nothing is forced)
      ALL       engine selection stays AUTO; the monitor lists every scenario and shows the details of focus_setup_id
  leverage    {"mode": AUTO | MANUAL, "limit": int | None}
      AUTO      exposure limit = account leverage read from MT5 (account_info().leverage)
      MANUAL    planning / exposure limit chosen by the user (1..account leverage); NOT a change of the broker leverage

`settings_version()` changes whenever anything that affects sizing changes (prefs, risk/cost config, account): a decision
computed with an older version is never executed (the gateway re-checks it).
"""
from __future__ import annotations

import hashlib
import json
import threading

from .db.database import dumps
from .strategies import registry
from .timeutil import iso, utcnow

NO_ACCOUNT = "__NO_ACCOUNT__"
LEVERAGE_CHOICES = (1, 2, 5, 10, 20, 30, 50, 100, 200, 500)
DEFAULTS = {"setup_view": {"mode": "AUTO", "strategy_id": None, "focus_setup_id": None},
            "leverage": {"mode": "AUTO", "limit": None}}


class PrefsError(ValueError):
    pass


class AccountPrefs:
    def __init__(self, db, bridge, cfg_store):
        self.db, self.bridge, self.cfg_store = db, bridge, cfg_store
        self._lock = threading.Lock()
        self.listeners: list = []

    def _key(self) -> str:
        return self.bridge.account_key or NO_ACCOUNT

    def get(self, name: str, account_key: str | None = None) -> dict:
        row = self.db.one("SELECT value_json FROM account_prefs WHERE account_key=? AND key=?", (account_key or self._key(), name))
        val = dict(DEFAULTS[name])
        if row:
            try:
                val.update(json.loads(row["value_json"]))
            except ValueError:
                pass
        return val

    def all(self) -> dict:
        return {"account_key": self._key(), "setup_view": self.get("setup_view"), "leverage": self.get("leverage"),
                "settings_version": self.settings_version()}

    def set(self, name: str, value: dict) -> dict:
        v = self.validate(name, value)
        with self._lock:
            self.db.execute("""INSERT INTO account_prefs(account_key, key, value_json, updated_at) VALUES (?,?,?,?)
                               ON CONFLICT(account_key, key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at""",
                            (self._key(), name, dumps(v), iso(utcnow())))
        for fn in self.listeners:
            try:
                fn(name, v)
            except Exception:
                pass
        return v

    def validate(self, name: str, value: dict) -> dict:
        if name == "setup_view":
            mode = value.get("mode")
            if mode not in ("AUTO", "SELECTED", "ALL"):
                raise PrefsError("SETUP_MODE_INVALID")
            sid = value.get("strategy_id")
            if mode == "SELECTED":
                if sid not in registry.STRATEGIES:
                    raise PrefsError("STRATEGY_NOT_IN_REGISTRY")
            focus = value.get("focus_setup_id")
            if focus is not None and (not isinstance(focus, str) or len(focus) > 120):
                raise PrefsError("FOCUS_SETUP_INVALID")
            return {"mode": mode, "strategy_id": sid if mode == "SELECTED" else (sid if sid in registry.STRATEGIES else None),
                    "focus_setup_id": focus if mode == "ALL" else None}
        if name == "leverage":
            mode = value.get("mode")
            if mode not in ("AUTO", "MANUAL"):
                raise PrefsError("LEVERAGE_MODE_INVALID")
            if mode == "AUTO":
                return {"mode": "AUTO", "limit": None}
            lim = value.get("limit")
            if not isinstance(lim, int) or isinstance(lim, bool) or not 1 <= lim <= 1000:
                raise PrefsError("LEVERAGE_LIMIT_INVALID")
            acc = account_leverage(self.bridge.account_status())
            if acc and lim > acc:
                raise PrefsError(f"LEVERAGE_LIMIT_ABOVE_ACCOUNT_1_{acc}")
            return {"mode": "MANUAL", "limit": lim}
        raise PrefsError("UNKNOWN_PREF")

    def exposure_limit(self) -> dict:
        """Effective exposure limit for sizing (one source: engine, details, gateway re-check)."""
        lev = self.get("leverage")
        acc = account_leverage(self.bridge.account_status())
        if lev["mode"] == "MANUAL" and lev["limit"]:
            limit = min(lev["limit"], acc) if acc else lev["limit"]
            note = "limit użytkownika (planowanie i ekspozycja) – nie zmienia dźwigni u brokera"
            if acc and lev["limit"] > acc:
                note += f"; obniżony do dźwigni rachunku 1:{acc}"
            return {"mode": "MANUAL", "account_leverage": acc, "user_limit": lev["limit"], "limit": limit, "note": note}
        return {"mode": "AUTO", "account_leverage": acc, "user_limit": None, "limit": acc,
                "note": "dźwignia rachunku z MT5" if acc else "dźwignia rachunku nieznana – limit ekspozycji nieaktywny (obowiązuje margin brokera)"}

    def settings_version(self) -> str:
        cfg = self.cfg_store.get()
        payload = {"account": self._key(), "leverage": self.get("leverage"), "setup_view": self.get("setup_view"),
                   "risk": cfg.risk.model_dump(mode="json"), "costs": cfg.costs.model_dump(mode="json"), "symbol": cfg.mt5.symbol}
        return "SV-" + hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:12]


def account_leverage(account: dict | None) -> int | None:
    try:
        v = int((account or {}).get("leverage") or 0)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None
