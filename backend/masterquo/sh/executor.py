"""Order execution for SCALPING / HEDGING plans. Honors the execution mode and the Execution Lock:
* SIGNALS  - nothing is executed (signals only; no plan is opened).
* PAPER    - simulated fills on the executable side of the current quote (+ configured slippage); no terminal call.
* AUTO_DEMO - terminal orders through the MT5 worker (Execution Lock checked before EVERY call); demo account required.
* AUTO_LIVE - refused for SH (risk engine) until validation on client data passes.

Every action is claimed in sh_actions before the terminal is touched (idempotency): a repeated event reuses the stored result,
an action whose outcome is unknown (timeout) is never resent - reconciliation with the terminal decides.
Own magic number and comment `SH:<plan>:<leg>` so the legacy position manager never touches SH positions and vice versa.
"""
from __future__ import annotations

from types import SimpleNamespace

OK_CODES = (10008, 10009, 10010)


class SHExecutor:
    def __init__(self, store, *, terminal=None, account_key: str | None = None, magic: int = 41082100, comment_prefix: str = "SH",
                 deviation_points: int = 30, locked=lambda: False, is_demo=lambda: True, symbol_info=None, log=None):
        self.store = store
        self.terminal = terminal                 # callable(fn) -> runs fn(mt5) on the MT5 worker thread (PRIO_TRADE)
        self.account_key = account_key or "PAPER"
        self.magic = int(magic)
        self.prefix = comment_prefix
        self.deviation = int(deviation_points)
        self.locked = locked
        self.is_demo = is_demo
        self.symbol_info = symbol_info or {}
        self.log = log or (lambda *a, **k: None)

    def comment(self, plan_id: str, tag: str) -> str:
        return f"{self.prefix}:{plan_id[-8:]}:{tag}"[:31]

    # ------------------------------------------------------------------ gate
    def _gate(self, mode: str) -> str | None:
        if mode == "SIGNALS":
            return "TRYB_SIGNALS_BEZ_WYKONANIA"
        if mode == "AUTO_LIVE":
            return "AUTO_LIVE_ZABLOKOWANE_DLA_SH"
        if mode == "AUTO_DEMO":
            if self.terminal is None:
                return "BRAK_TERMINALA"
            if self.locked():
                return "EXECUTION_LOCKED"
            if not self.is_demo():
                return "RACHUNEK_NIE_DEMO"
        return None

    # ------------------------------------------------------------------ public
    def open(self, plan: dict, *, role: str, side: str, volume: float, sl: float, tp: float, mode: str, quote: dict, tag: str,
             slippage: float = 0.0, now: float | None = None) -> dict:
        """Open the PRIMARY (role P) or the HEDGE (role H) position. Returns status FILLED / PARTIAL / REJECTED / UNKNOWN / BLOCKED."""
        action = {"action_id": f"{plan['plan_id']}:OPEN:{tag}", "plan_id": plan["plan_id"], "kind": "OPEN_" + role,
                  "side": side, "volume": volume, "sl": sl, "tp": tp}
        return self._run(action, mode, quote, slippage, now, lambda: self._paper_open(action, quote, slippage),
                         lambda: self._mt5_open(plan, action, tag))

    def perform(self, plan: dict, action: dict, *, mode: str, quote: dict, ticket: int | None, side_of_position: str,
                slippage: float = 0.0, now: float | None = None) -> dict:
        """Execute one state-machine action (CLOSE_PARTIAL / CLOSE_RUNNER / CLOSE_PRIMARY / CLOSE_HEDGE / MODIFY_SL)."""
        return self._run(action, mode, quote, slippage, now,
                         lambda: self._paper_action(action, quote, side_of_position, slippage),
                         lambda: self._mt5_action(plan, action, ticket, side_of_position))

    # ------------------------------------------------------------------ core
    def _run(self, action, mode, quote, slippage, now, paper, real) -> dict:
        g = self._gate(mode)
        if g:
            return {"status": "BLOCKED", "reason": g}
        cl = self.store.claim_action(action, now)
        if not cl["claimed"]:
            if cl["status"] == "DONE":
                return {**(cl["result"] or {}), "status": (cl["result"] or {}).get("status", "DONE"), "replayed": True}
            return {"status": "UNKNOWN", "reason": f"akcja {action['action_id']} w stanie {cl['status']} – bez ponownego wysłania"}
        try:
            res = paper() if mode == "PAPER" else real()
        except TimeoutError:
            res = {"status": "UNKNOWN", "reason": "TIMEOUT_ORDER_SEND"}
        except Exception as exc:  # noqa: BLE001 - outcome unknown, never retried blindly
            res = {"status": "UNKNOWN", "reason": f"{type(exc).__name__}: {exc}"[:200]}
        st = {"FILLED": "DONE", "PARTIAL": "DONE", "DONE": "DONE", "REJECTED": "REJECTED"}.get(res["status"], "UNKNOWN")
        self.store.finish_action(action["action_id"], st, res, now)
        self.store.event(action.get("plan_id") or action.get("basket_id"), "ACTION", {"action": action, "result": res}, now)
        return res

    # ------------------------------------------------------------------ paper
    @staticmethod
    def _paper_open(action, quote, slip) -> dict:
        px = quote["ask"] + slip if action["side"] == "BUY" else quote["bid"] - slip
        return {"status": "FILLED", "price": px, "volume": action["volume"], "ticket": None, "simulated": True}

    @staticmethod
    def _paper_action(action, quote, pos_side, slip) -> dict:
        if action["kind"] == "MODIFY_SL":
            px = quote["bid"] if pos_side == "BUY" else quote["ask"]
            ok = (action["sl"] < px) if pos_side == "BUY" else (action["sl"] > px)       # SL must stay on the protective side
            return {"status": "DONE" if ok else "REJECTED", "sl": action["sl"], "reason": None if ok else "INVALID_STOPS (cena już za BE)",
                    "simulated": True}
        close_side_buy = pos_side == "SELL"                                               # closing a SELL buys at Ask
        px = quote["ask"] + slip if close_side_buy else quote["bid"] - slip
        return {"status": "FILLED", "price": px, "volume": action["volume"], "simulated": True}

    # ------------------------------------------------------------------ terminal
    def _filling(self, m):
        fm = int(self.symbol_info.get("filling_mode") or 0)
        return m.ORDER_FILLING_FOK if fm & 1 else (m.ORDER_FILLING_IOC if fm & 2 else m.ORDER_FILLING_RETURN)

    def _result(self, r, req_volume: float) -> dict:
        if r is None:
            return {"status": "UNKNOWN", "reason": "ORDER_SEND_NONE"}
        rc = getattr(r, "retcode", None)
        if rc in OK_CODES and (getattr(r, "volume", 0) or 0) > 0:
            part = rc == 10010 or r.volume < req_volume - 1e-9
            return {"status": "PARTIAL" if part else "FILLED", "price": r.price, "volume": r.volume, "deal": r.deal, "order": r.order, "retcode": rc}
        if rc in OK_CODES:                                                              # SLTP modification
            return {"status": "DONE", "retcode": rc}
        return {"status": "REJECTED", "retcode": rc, "reason": str(getattr(r, "comment", ""))}

    def _mt5_open(self, plan, action, tag) -> dict:
        sym = plan["symbol"]

        def go(m):
            q = m.symbol_info_tick(sym)
            req = {"action": m.TRADE_ACTION_DEAL, "symbol": sym, "volume": float(action["volume"]),
                   "type": m.ORDER_TYPE_BUY if action["side"] == "BUY" else m.ORDER_TYPE_SELL, "price": q.ask if action["side"] == "BUY" else q.bid,
                   "sl": float(action["sl"] or 0), "tp": float(action["tp"] or 0), "deviation": self.deviation, "magic": self.magic,
                   "comment": self.comment(plan["plan_id"], tag), "type_time": m.ORDER_TIME_GTC, "type_filling": self._filling(m)}
            chk = m.order_check(req)
            if chk is None or getattr(chk, "retcode", -1) != 0:
                return SimpleNamespace(retcode=getattr(chk, "retcode", -1), comment="ORDER_CHECK:" + str(getattr(chk, "comment", "")), volume=0), None
            r = m.order_send(req)
            pos = None
            if r is not None and getattr(r, "deal", 0):
                ds = m.history_deals_get(ticket=r.deal) or ()
                pos = getattr(ds[0], "position_id", None) if ds else None
            return r, pos
        r, pos = self.terminal(go)
        out = self._result(r, float(action["volume"]))
        if out["status"] in ("FILLED", "PARTIAL"):
            out["ticket"] = int(pos or r.order)
            if not self.store.own(self.account_key, out["ticket"], plan["plan_id"], action["kind"]):
                out["warning"] = "POZYCJA_MA_INNEGO_WŁAŚCICIELA"
        return out

    def _mt5_action(self, plan, action, ticket, pos_side) -> dict:
        if not ticket:
            return {"status": "REJECTED", "reason": "BRAK_TICKETU"}
        sym = plan["symbol"]
        own = self.store.owner(self.account_key, ticket)
        if not own or own["plan_id"] != plan["plan_id"]:
            return {"status": "REJECTED", "reason": "POZYCJA_NIE_NALEŻY_DO_PLANU"}

        def go(m):
            if action["kind"] == "MODIFY_SL":
                p = (m.positions_get(ticket=ticket) or [None])[0]
                if p is None:
                    return SimpleNamespace(retcode=-1, comment="POSITION_NOT_FOUND", volume=0)
                return m.order_send({"action": m.TRADE_ACTION_SLTP, "symbol": sym, "position": int(ticket), "sl": float(action["sl"]),
                                     "tp": float(p.tp or 0), "magic": self.magic})
            q = m.symbol_info_tick(sym)
            buy = pos_side == "SELL"
            return m.order_send({"action": m.TRADE_ACTION_DEAL, "symbol": sym, "volume": float(action["volume"]), "position": int(ticket),
                                 "type": m.ORDER_TYPE_BUY if buy else m.ORDER_TYPE_SELL, "price": q.ask if buy else q.bid,
                                 "deviation": self.deviation, "magic": self.magic,
                                 "comment": self.comment(plan["plan_id"], action["action_id"].split(":")[-1]),
                                 "type_time": m.ORDER_TIME_GTC, "type_filling": self._filling(m)})
        return self._result(self.terminal(go), float(action.get("volume") or 0))

    # ------------------------------------------------------------------ restart reconciliation
    def terminal_positions(self, symbol: str) -> list[dict]:
        if self.terminal is None:
            return []
        ps = self.terminal(lambda m: m.positions_get(symbol=symbol)) or ()
        return [{"ticket": int(p.ticket), "magic": int(p.magic), "volume": float(p.volume), "type": int(p.type), "price_open": float(p.price_open),
                 "sl": float(p.sl or 0), "tp": float(p.tp or 0), "comment": str(p.comment)} for p in ps]

    def closing_deals(self, ticket: int) -> list[dict]:
        if self.terminal is None:
            return []
        ds = self.terminal(lambda m: m.history_deals_get(position=int(ticket))) or ()
        return [{"ticket": int(d.ticket), "entry": int(d.entry), "volume": float(d.volume), "price": float(d.price), "time": float(d.time),
                 "comment": str(d.comment)} for d in ds if int(d.entry) == 1]

