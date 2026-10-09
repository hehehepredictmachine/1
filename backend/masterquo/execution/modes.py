"""Execution mode and the execution permission gate (MQ-EXECUTION-MODES-2.0.0).

Three independent settings (never derived from each other):
  strategy_mode  AUTO / MANUAL                 config.active.strategy_mode   (which strategy)
  ml_mode        OFF / SHADOW / ASSIST         config.ml.mode                 (role of the models)
  execution_mode SIGNALS / PAPER / AUTO_DEMO / AUTO_LIVE   config.execution.mode  (how setups are executed)

  SIGNALS    "Analiza warunków" - setups are evaluated and shown as a checklist, no orders
  PAPER      automatic local simulation (never calls the broker's trading functions)
  AUTO_DEMO  automatic orders, only on an account the terminal reports as DEMO/CONTEST
  AUTO_LIVE  automatic orders on an account the terminal reports as REAL

* There is no READ_ONLY / research-only switch any more. The chosen execution mode is stored in the
  configuration and restored after restart. Without an explicit user choice the mode is PAPER.
* Account type and identity are read from the terminal (account_info.trade_mode / login / server),
  never guessed from the server name. A mismatch (DEMO mode on a real account, account changed since the
  mode was confirmed, LIVE on synthetic data) blocks sending and reports the concrete reason - it does
  not silently switch modes.
* Switching to AUTO_DEMO / AUTO_LIVE is confirmed once by typing the login (LIVE: "LIVE <login>");
  individual trades are not confirmed. Risk limits, data quality, broker restrictions and STOP still apply.
* STOP (kill switch) stops NEW entries only; closing positions is a separate operation.
"""
from __future__ import annotations

import threading

from ..db.database import dumps
from ..risk.engine import limits_configured
from ..timeutil import iso, utcnow

MODES = ("SIGNALS", "PAPER", "AUTO_DEMO", "AUTO_LIVE")
ORDER_MODES = ("AUTO_DEMO", "AUTO_LIVE")          # modes that talk to the broker
LABEL_PL = {"SIGNALS": "Analiza warunków", "PAPER": "PAPER (symulacja)", "AUTO_DEMO": "AUTO DEMO", "AUTO_LIVE": "AUTO LIVE"}
LEGACY = {"READ_ONLY": "SIGNALS", "DEMO_EXECUTION": "AUTO_DEMO", "LIVE_EXECUTION": "AUTO_LIVE"}


class ModeError(ValueError):
    pass


class ModeManager:
    def __init__(self, config_store, db, bus, applog, account_provider=None):
        self.cfg_store = config_store
        self.db = db
        self.bus = bus
        self.log = applog
        self.account_provider = account_provider          # () -> (account_dict | None, account_key | None, synthetic)
        self._lock = threading.RLock()
        ex = config_store.get().execution
        self.mode = LEGACY.get(ex.mode, ex.mode)
        self.bound_account: str | None = ex.bound_account
        self.kill_switch = False
        self.kill_reason: str | None = None
        self.changed_at = iso(utcnow())

    # ------------------------------------------------------------ state
    @property
    def auto_trading(self) -> bool:
        """Every mode except SIGNALS executes automatically (no per-trade confirmation)."""
        return self.mode != "SIGNALS" and not self.kill_switch

    def status(self) -> dict:
        with self._lock:
            return {"mode": self.mode, "mode_label": LABEL_PL.get(self.mode, self.mode), "auto_trading": self.auto_trading,
                    "bound_account": self.bound_account, "kill_switch": self.kill_switch, "kill_reason": self.kill_reason,
                    "changed_at": self.changed_at, "strategy_mode": self.cfg_store.get().active.strategy_mode,
                    "ml_mode": self.cfg_store.get().ml.mode}

    def _persist_and_publish(self, why: str) -> None:
        self.changed_at = iso(utcnow())
        self.cfg_store.update({"execution": {"mode": self.mode, "bound_account": self.bound_account}})
        st = self.status()
        self.db.execute("INSERT INTO settings_audit(ts, change_json) VALUES (?,?)", (self.changed_at, dumps({"mode_change": st, "why": why})))
        self.bus.publish("mode", st)

    def reset(self, reason: str) -> None:
        """Account/terminal changed: the mode stays as chosen; the gate blocks until the account matches again."""
        self.log.warn("MODE", "ACCOUNT_CONTEXT_CHANGED", f"{reason}: tryb {self.mode} bez zmian; wysyłka zleceń zablokowana, dopóki rachunek "
                      "nie zgadza się z potwierdzonym (powód widoczny w drzewie decyzji).")
        self.bus.publish("mode", self.status())

    def set_mode(self, mode: str, *, confirm: str = "", account: dict | None, account_key: str | None, synthetic: bool) -> dict:
        mode = LEGACY.get(mode, mode)
        if mode not in MODES:
            raise ModeError("UNKNOWN_MODE")
        bound = None
        if mode in ORDER_MODES:
            if not account or not account_key:
                raise ModeError("NO_MT5_ACCOUNT")
            login = str(account.get("login"))
            if mode == "AUTO_DEMO":
                if account.get("trade_mode") not in ("DEMO", "CONTEST"):
                    raise ModeError("ACCOUNT_IS_NOT_DEMO")
                if confirm.strip() != login:
                    raise ModeError("CONFIRMATION_MUST_EQUAL_ACCOUNT_LOGIN")
            else:
                if synthetic:
                    raise ModeError("LIVE_NOT_AVAILABLE_ON_SYNTHETIC_DATA")
                if account.get("trade_mode") != "REAL":
                    raise ModeError("ACCOUNT_IS_NOT_REAL")
                if confirm.strip() != f"LIVE {login}":
                    raise ModeError("CONFIRMATION_MUST_EQUAL_LIVE_LOGIN")
            bound = account_key
        with self._lock:
            self.mode = mode
            self.bound_account = bound
        self.log.warn("MODE", mode, f"Tryb wykonania: {LABEL_PL[mode]}" + (f" (rachunek {account_key})" if bound else ""))
        self._persist_and_publish("user")
        return self.status()

    def set_auto(self, on: bool) -> dict:
        """Compatibility endpoint: OFF = STOP new entries, ON = resume (the execution mode is not changed)."""
        return self.set_kill(not on, "USER_AUTO_SWITCH")

    def set_kill(self, on: bool, reason: str) -> dict:
        with self._lock:
            self.kill_switch, self.kill_reason = bool(on), (reason if on else None)
        self.log.warn("MODE", "STOP_NEW_ENTRIES" if on else "RESUME_NEW_ENTRIES",
                      "STOP: zatrzymano nowe wejścia (pozycje bez zmian)" if on else "Wznowiono możliwość nowych wejść (pozostałe bramki obowiązują)")
        self.changed_at = iso(utcnow())
        st = self.status()
        self.db.execute("INSERT INTO settings_audit(ts, change_json) VALUES (?,?)", (self.changed_at, dumps({"mode_change": st, "why": reason})))
        self.bus.publish("mode", st)
        return st

    # ------------------------------------------------------------ gate
    def gate(self, account_key: str | None, account: dict | None = None, synthetic: bool | None = None) -> dict:
        if account is None and self.account_provider is not None:
            account, _k, synth = self.account_provider()
            synthetic = synth if synthetic is None else synthetic
        with self._lock:
            reasons = []
            mode = self.mode
            if mode == "SIGNALS":
                reasons.append("EXECUTION_MODE_SIGNALS")
            if mode in ORDER_MODES:
                tm = (account or {}).get("trade_mode")
                if not account_key or not account:
                    reasons.append("NO_MT5_ACCOUNT")
                elif self.bound_account != account_key:
                    reasons.append("ACCOUNT_DIFFERS_FROM_CONFIRMED_" + str(self.bound_account))
                if mode == "AUTO_DEMO" and account and tm not in ("DEMO", "CONTEST"):
                    reasons.append(f"AUTO_DEMO_BUT_ACCOUNT_IS_{tm}")
                if mode == "AUTO_LIVE" and account and tm != "REAL":
                    reasons.append(f"AUTO_LIVE_BUT_ACCOUNT_IS_{tm}")
                if mode == "AUTO_LIVE" and synthetic:
                    reasons.append("AUTO_LIVE_ON_SYNTHETIC_DATA")
            if self.kill_switch:
                reasons.append("NEW_ENTRIES_STOPPED")
            missing = limits_configured(self.cfg_store.get().risk)
            if missing and mode != "SIGNALS":
                reasons.append("RISK_LIMITS_NOT_CONFIGURED")
            return {"mode": mode, "allowed": not reasons, "auto_trading": self.auto_trading and not reasons,
                    "kill_switch": self.kill_switch, "reason_codes": reasons}
