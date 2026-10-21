"""Read-only MT5 access. The wrapper exposes ONLY reading functions of the MetaTrader5 package; any order function
(order_send, order_check, positions_close, ...) raises - the statistics engine can never place, modify or close trades.

Attaching: by default the bot attaches to the terminal that is already running and logged in, and checks that the logged-in
account is the configured one (it never logs the terminal into another account unless sync.allow_login_switch is enabled AND the
account has a stored password). A separate terminal_path per account lets several accounts run in separate terminals.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

READ_ONLY = {"initialize", "shutdown", "last_error", "terminal_info", "account_info", "positions_get", "positions_total", "history_deals_get",
             "symbol_info", "symbol_info_tick", "symbol_select", "version"}


class ReadOnlyMT5:
    def __init__(self, module):
        self._m = module

    def __getattr__(self, name):
        if name not in READ_ONLY:
            raise PermissionError(f"READ_ONLY_MT5: {name} is not allowed")
        return getattr(self._m, name)


def _row(x) -> dict:
    return x._asdict() if hasattr(x, "_asdict") else dict(x)


class MT5Source:
    """One account at a time; connect() -> (ok, reason)."""

    def __init__(self, module=None, allow_login_switch: bool = False):
        if module is None:
            import MetaTrader5 as module  # type: ignore  # noqa: N813 - Windows only
        self.m = ReadOnlyMT5(module)
        self.allow_login_switch = allow_login_switch
        self.connected_login = None

    def connect(self, acc: dict, password: str | None) -> tuple[bool, str]:
        kw = {"path": acc["terminal_path"]} if acc.get("terminal_path") else {}
        if not self.m.initialize(**kw):
            return False, f"INITIALIZE_FAILED:{self.m.last_error()}"
        a = self.m.account_info()
        if a is None:
            return False, f"NO_ACCOUNT_INFO:{self.m.last_error()}"
        a = _row(a)
        if int(a.get("login") or 0) == int(acc["login"]) and str(a.get("server")) == str(acc["server"]):
            self.connected_login = acc["login"]
            return True, "ATTACHED"
        if not (self.allow_login_switch and password):
            return False, "TERMINAL_LOGGED_INTO_OTHER_ACCOUNT"
        if not self.m.initialize(login=int(acc["login"]), password=password, server=acc["server"], **kw):
            return False, f"LOGIN_FAILED:{self.m.last_error()}"
        a = _row(self.m.account_info() or {})
        if int(a.get("login") or 0) != int(acc["login"]):
            return False, "LOGIN_MISMATCH"
        self.connected_login = acc["login"]
        return True, "LOGGED_IN"

    def account(self) -> dict:
        a = _row(self.m.account_info())
        return {"currency": a.get("currency"), "balance": a.get("balance"), "equity": a.get("equity"), "margin": a.get("margin"),
                "free_margin": a.get("margin_free"), "margin_mode": {0: "NETTING", 1: "EXCHANGE", 2: "HEDGING"}.get(a.get("margin_mode"), "UNKNOWN"),
                "login": a.get("login"), "server": a.get("server")}

    def positions(self) -> list[dict]:
        out = []
        for p in self.m.positions_get() or ():
            r = _row(p)
            out.append({"ticket": r["ticket"], "identifier": r.get("identifier", r["ticket"]), "symbol": r["symbol"], "side": "BUY" if r["type"] == 0 else "SELL",
                        "volume": r["volume"], "price_open": r["price_open"], "sl": r.get("sl") or None, "tp": r.get("tp") or None, "magic": r.get("magic"),
                        "time": r.get("time")})
        return out

    def deals(self, frm_server: float, to_server: float) -> list[dict] | None:
        res = self.m.history_deals_get(datetime.fromtimestamp(frm_server, timezone.utc), datetime.fromtimestamp(to_server, timezone.utc))
        if res is None:
            return None
        keys = ("ticket", "order", "time", "time_msc", "type", "entry", "magic", "position_id", "volume", "price", "profit", "commission", "swap",
                "fee", "symbol", "reason")
        return [{k: _row(d).get(k) for k in keys} for d in res]

    def digits(self, symbol: str) -> int:
        s = self.m.symbol_info(symbol)
        return int(_row(s).get("digits", 2)) if s is not None else 2

    def point(self, symbol: str) -> float:
        s = self.m.symbol_info(symbol)
        return float(_row(s).get("point", 0.01)) if s is not None else 0.01

    def server_offset(self, symbols: list[str]) -> float | None:
        """Server time - UTC (seconds), from a fresh tick (residual < 60 s, |offset| <= 14 h); a
        stale tick on a closed market can mislead the detection, so a fixed offset in the configuration is recommended; rounded to 15 minutes. None when no fresh tick exists."""
        now = time.time()
        for s in symbols:
            t = self.m.symbol_info_tick(s)
            if t is None:
                continue
            off = float(_row(t)["time"]) - now
            if abs(off) <= 14 * 3600 + 60 and abs(off - round(off / 900) * 900) < 60:
                return round(off / 900) * 900
        return None

    def shutdown(self) -> None:
        try:
            self.m.shutdown()
        except Exception:  # noqa: BLE001
            pass
