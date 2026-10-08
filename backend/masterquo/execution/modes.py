"""Operating modes and the execution permission gate.

READ_ONLY       default; analysis only, no orders (also for a REAL account as data source)
PAPER           local simulation in this application's database (NOT an MT5 demo account)
DEMO_EXECUTION  real order_send on an MT5 *demo* account
LIVE_EXECUTION  real order_send on a REAL account; additionally requires
                execution.allow_live_execution=true in data/config.json

Invariants:
* every application start is READ_ONLY with AUTO TRADING OFF (mode is never restored from disk);
* a change of account, server or terminal resets to READ_ONLY / AUTO OFF;
* switching to an execution mode requires configured risk limits and a typed confirmation
  bound to the account login; LIVE requires the separate local opt-in flag;
* "stop new entries" (kill switch) is independent from closing positions.
"""
from __future__ import annotations

import threading

from ..db.database import dumps
from ..risk.engine import limits_configured
from ..timeutil import iso, utcnow

MODES = ("READ_ONLY", "PAPER", "DEMO_EXECUTION", "LIVE_EXECUTION")


class ModeError(ValueError):
    pass


class ModeManager:
    def __init__(self, config_store, db, bus, applog):
        self.cfg_store = config_store
        self.db = db
        self.bus = bus
        self.log = applog
        self._lock = threading.RLock()
        self.mode = "READ_ONLY"
        self.auto_trading = False
        self.bound_account: str | None = None
        self.kill_switch = False
        self.kill_reason: str | None = None
        self.changed_at = iso(utcnow())

    def status(self) -> dict:
        with self._lock:
            return {"mode": self.mode, "auto_trading": self.auto_trading, "bound_account": self.bound_account,
                    "kill_switch": self.kill_switch, "kill_reason": self.kill_reason, "changed_at": self.changed_at,
                    "allow_live_execution_flag": self.cfg_store.get().execution.allow_live_execution}

    def _publish(self, why: str) -> None:
        self.changed_at = iso(utcnow())
        st = self.status()
        self.db.execute("INSERT INTO settings_audit(ts, change_json) VALUES (?,?)", (self.changed_at, dumps({"mode_change": st, "why": why})))
        self.bus.publish("mode", st)

    def reset(self, reason: str) -> None:
        with self._lock:
            if self.mode == "READ_ONLY" and not self.auto_trading:
                return
            self.mode, self.auto_trading, self.bound_account = "READ_ONLY", False, None
        self.log.warn("MODE", "RESET_READ_ONLY", f"Tryb przełączony na READ_ONLY: {reason}")
        self._publish(reason)

    def set_mode(self, mode: str, *, confirm: str, account: dict | None, account_key: str | None, synthetic: bool) -> dict:
        if mode not in MODES:
            raise ModeError("UNKNOWN_MODE")
        cfg = self.cfg_store.get()
        if mode == "READ_ONLY":
            with self._lock:
                self.mode, self.auto_trading, self.bound_account = "READ_ONLY", False, None
            self.log.info("MODE", "READ_ONLY", "Tryb READ_ONLY")
            self._publish("user")
            return self.status()
        missing = limits_configured(cfg.risk)
        if missing:
            raise ModeError("RISK_LIMITS_NOT_CONFIGURED:" + ",".join(missing))
        if mode in ("DEMO_EXECUTION", "LIVE_EXECUTION"):
            if not account or not account_key:
                raise ModeError("NO_MT5_ACCOUNT")
            login = str(account.get("login"))
            if mode == "DEMO_EXECUTION":
                if account.get("trade_mode") not in ("DEMO", "CONTEST"):
                    raise ModeError("ACCOUNT_IS_NOT_DEMO")
                if confirm.strip() != login:
                    raise ModeError("CONFIRMATION_MUST_EQUAL_ACCOUNT_LOGIN")
            else:
                if synthetic:
                    raise ModeError("LIVE_NOT_AVAILABLE_ON_SYNTHETIC_DATA")
                if account.get("trade_mode") != "REAL":
                    raise ModeError("ACCOUNT_IS_NOT_REAL")
                if not cfg.execution.allow_live_execution:
                    raise ModeError("LIVE_DISABLED_IN_LOCAL_CONFIG_allow_live_execution")
                if confirm.strip() != f"LIVE {login}":
                    raise ModeError("CONFIRMATION_MUST_EQUAL_LIVE_LOGIN")
        elif confirm.strip().upper() != "PAPER":
            raise ModeError("CONFIRMATION_MUST_EQUAL_PAPER")
        with self._lock:
            self.mode = mode
            self.auto_trading = False
            self.bound_account = account_key
        self.log.warn("MODE", mode, f"Tryb {mode} dla rachunku {account_key}. AUTO TRADING: OFF")
        self._publish("user")
        return self.status()

    def set_auto(self, on: bool) -> dict:
        with self._lock:
            if on and self.mode == "READ_ONLY":
                raise ModeError("AUTO_TRADING_REQUIRES_EXECUTION_OR_PAPER_MODE")
            self.auto_trading = bool(on)
        self.log.warn("MODE", "AUTO_ON" if on else "AUTO_OFF", f"AUTO TRADING {'ON' if on else 'OFF'}")
        self._publish("user")
        return self.status()

    def set_kill(self, on: bool, reason: str) -> dict:
        with self._lock:
            self.kill_switch, self.kill_reason = bool(on), (reason if on else None)
            if on:
                self.auto_trading = False
        self.log.warn("MODE", "STOP_NEW_ENTRIES" if on else "RESUME_NEW_ENTRIES",
                      "Zatrzymano nowe wejścia" if on else "Wznowiono możliwość nowych wejść (wymaga ponownych bramek)")
        self._publish(reason)
        return self.status()

    def gate(self, account_key: str | None) -> dict:
        with self._lock:
            reasons = []
            if self.mode == "READ_ONLY":
                reasons.append("READ_ONLY_MODE")
            elif self.bound_account != account_key:
                reasons.append("MODE_BOUND_TO_OTHER_ACCOUNT")
            if self.kill_switch:
                reasons.append("NEW_ENTRIES_STOPPED")
            if limits_configured(self.cfg_store.get().risk):
                reasons.append("RISK_LIMITS_NOT_CONFIGURED")
            return {"mode": self.mode, "allowed": not reasons, "auto_trading": self.auto_trading,
                    "kill_switch": self.kill_switch, "reason_codes": reasons}
