"""Persistence for SCALPING / HEDGING: signals with their status history, frozen plans with the serialized state machine,
idempotent actions and position ownership. Everything a restart needs is in the database (no in-memory-only state)."""
from __future__ import annotations

import json
import time

from ..db.database import dumps
from .hedge_fsm import Basket, HedgeConfig, Leg2
from .lifecycle import Leg, Position

SIGNAL_STATUSES = ("READY", "WAIT", "NO_TRADE", "EXPIRED", "INVALIDATED")


# ---------------------------------------------------------------------------- state machine (de)serialization
def pos_dump(p: Position) -> dict:
    d = {k: v for k, v in p.__dict__.items() if k not in ("legs", "seen_events", "issued")}
    d["legs"] = [vars(x) for x in p.legs]
    d["seen_events"], d["issued"] = sorted(p.seen_events), sorted(p.issued)
    return d


def pos_load(d: dict) -> Position:
    d = dict(d)
    legs = [Leg(**x) for x in d.pop("legs")]
    seen, issued = set(d.pop("seen_events", [])), set(d.pop("issued", []))
    p = Position(legs=legs, **{k: v for k, v in d.items() if k != "legs"})
    p.seen_events, p.issued = seen, issued
    return p


def basket_dump(b: Basket) -> dict:
    return {"basket_id": b.basket_id, "primary": pos_dump(b.primary), "cfg": vars(b.cfg), "money_per_price_per_lot": b.money_per_price_per_lot,
            "opened_at": b.opened_at, "state": b.state, "hedge": vars(b.hedge) if b.hedge else None, "activations": b.activations,
            "hedge_realized_money": b.hedge_realized_money, "seen": sorted(b.seen), "issued": sorted(b.issued), "transitions": b.transitions}


def basket_load(d: dict) -> Basket:
    b = Basket(basket_id=d["basket_id"], primary=pos_load(d["primary"]), cfg=HedgeConfig(**d["cfg"]),
               money_per_price_per_lot=d["money_per_price_per_lot"], opened_at=d["opened_at"], state=d["state"],
               hedge=Leg2(**d["hedge"]) if d.get("hedge") else None, activations=d["activations"],
               hedge_realized_money=d["hedge_realized_money"], transitions=d.get("transitions") or [])
    b.seen, b.issued = set(d.get("seen") or []), set(d.get("issued") or [])
    return b


def fsm_dump(obj) -> dict:
    return {"type": "BASKET", "data": basket_dump(obj)} if isinstance(obj, Basket) else {"type": "POSITION", "data": pos_dump(obj)}


def fsm_load(d: dict):
    return basket_load(d["data"]) if d["type"] == "BASKET" else pos_load(d["data"])


# ---------------------------------------------------------------------------- store
class SHStore:
    def __init__(self, db):
        self.db = db

    # signals -------------------------------------------------------------------------------------------------------------
    def save_signal(self, s: dict, *, risk: dict | None = None, coordination: dict | None = None, now: float | None = None) -> None:
        now = time.time() if now is None else now
        self.db.execute("""INSERT INTO sh_signals(signal_id, strategy, instrument, symbol, side, status, status_reason, created_at, updated_at,
                           valid_until, config_hash, payload, risk, coordination) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                           ON CONFLICT(signal_id) DO UPDATE SET status=excluded.status, status_reason=excluded.status_reason,
                           updated_at=excluded.updated_at, payload=excluded.payload, risk=COALESCE(excluded.risk, sh_signals.risk),
                           coordination=COALESCE(excluded.coordination, sh_signals.coordination)""",
                        (s["signal_id"], s["strategy"], s["instrument"], s["symbol"], s.get("side"), s["status"], s.get("status_reason"),
                         s.get("created_at", now), now, s.get("valid_until"), s.get("config_hash"), dumps(s),
                         dumps(risk) if risk else None, dumps(coordination) if coordination else None))

    def expire_signals(self, now: float) -> int:
        return self.db.execute("""UPDATE sh_signals SET status='EXPIRED', status_reason='TTL minął przed wykonaniem', updated_at=?
                                  WHERE status='READY' AND valid_until IS NOT NULL AND valid_until < ?""", (now, now))

    def recent_signals(self, strategy: str | None = None, since: float = 0.0, limit: int = 200) -> list[dict]:
        q = "SELECT signal_id, strategy, instrument, symbol, side, status, status_reason, created_at, valid_until FROM sh_signals WHERE created_at >= ?"
        args: list = [since]
        if strategy:
            q += " AND strategy=?"
            args.append(strategy)
        return self.db.query(q + " ORDER BY created_at DESC LIMIT ?", (*args, limit))

    def signal(self, signal_id: str) -> dict | None:
        r = self.db.one("SELECT * FROM sh_signals WHERE signal_id=?", (signal_id,))
        if r:
            for k in ("payload", "risk", "coordination"):
                r[k] = json.loads(r[k]) if r.get(k) else None
        return r

    # plans ---------------------------------------------------------------------------------------------------------------
    def create_plan(self, plan: dict, now: float | None = None) -> bool:
        """Frozen plan (parameters + config hash). One plan per signal; returns False if it already exists (idempotent)."""
        now = time.time() if now is None else now
        with self.db.tx() as c:
            if c.execute("SELECT 1 FROM sh_plans WHERE plan_id=? OR signal_id=?", (plan["plan_id"], plan["signal_id"])).fetchone():
                return False
            c.execute("""INSERT INTO sh_plans(plan_id, signal_id, strategy, instrument, symbol, side, exec_mode, account_key, state, config_hash,
                         plan, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (plan["plan_id"], plan["signal_id"], plan["strategy"], plan["instrument"], plan["symbol"], plan["side"], plan["exec_mode"],
                       plan.get("account_key"), "PENDING_ENTRY", plan["config_hash"], dumps(plan), now, now))
        return True

    def update_plan(self, plan_id: str, *, state: str | None = None, fsm=None, now: float | None = None, **cols) -> None:
        now = time.time() if now is None else now
        f = {"updated_at": now, **cols}
        if state:
            f["state"] = state
            if state in ("CLOSED", "ERROR_CLOSED", "REJECTED"):
                f.setdefault("closed_at", now)
        if fsm is not None:
            f["fsm"] = dumps(fsm_dump(fsm))
        for k in ("result",):
            if k in f and not isinstance(f[k], str):
                f[k] = dumps(f[k])
        self.db.execute(f"UPDATE sh_plans SET {', '.join(k + '=?' for k in f)} WHERE plan_id=?", (*f.values(), plan_id))

    def plan(self, plan_id: str) -> dict | None:
        r = self.db.one("SELECT * FROM sh_plans WHERE plan_id=?", (plan_id,))
        return self._plan_row(r) if r else None

    @staticmethod
    def _plan_row(r: dict) -> dict:
        r["plan"] = json.loads(r["plan"])
        r["result"] = json.loads(r["result"]) if r.get("result") else None
        r["fsm_obj"] = fsm_load(json.loads(r["fsm"])) if r.get("fsm") else None
        return r

    def open_plans(self, symbol: str | None = None) -> list[dict]:
        q = "SELECT * FROM sh_plans WHERE state NOT IN ('CLOSED','ERROR_CLOSED','REJECTED')"
        args: list = []
        if symbol:
            q += " AND symbol=?"
            args.append(symbol)
        return [self._plan_row(r) for r in self.db.query(q + " ORDER BY created_at", args)]

    def last_close_at(self, symbol: str) -> dict:
        return {r["strategy"]: r["t"] for r in self.db.query(
            "SELECT strategy, MAX(closed_at) AS t FROM sh_plans WHERE symbol=? AND closed_at IS NOT NULL GROUP BY strategy", (symbol,))}

    def realized_since(self, since: float) -> float:
        tot = 0.0
        for r in self.db.query("SELECT result FROM sh_plans WHERE closed_at >= ? AND result IS NOT NULL", (since,)):
            tot += float((json.loads(r["result"]) or {}).get("net_money") or 0.0)
        return tot

    # actions (idempotency) ----------------------------------------------------------------------------------------------
    def claim_action(self, action: dict, now: float | None = None) -> dict:
        """Claim an action id before touching the terminal. Returns {claimed: True} for a new id (or a retry of a REJECTED one),
        otherwise the stored row: DONE -> the stored result is reused, SENT/UNKNOWN -> never resent (reconciliation decides)."""
        now = time.time() if now is None else now
        with self.db.tx() as c:
            r = c.execute("SELECT status, attempts, result FROM sh_actions WHERE action_id=?", (action["action_id"],)).fetchone()
            if r is None:
                c.execute("INSERT INTO sh_actions(action_id, plan_id, kind, status, request, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                          (action["action_id"], action.get("plan_id") or action.get("basket_id"), action["kind"], "SENT", dumps(action), now, now))
                return {"claimed": True, "attempt": 1}
            if r["status"] == "REJECTED":
                c.execute("UPDATE sh_actions SET status='SENT', attempts=attempts+1, updated_at=? WHERE action_id=?", (now, action["action_id"]))
                return {"claimed": True, "attempt": r["attempts"] + 1}
            return {"claimed": False, "status": r["status"], "result": json.loads(r["result"]) if r["result"] else None}

    def finish_action(self, action_id: str, status: str, result: dict, now: float | None = None) -> None:
        self.db.execute("UPDATE sh_actions SET status=?, result=?, updated_at=? WHERE action_id=?",
                        (status, dumps(result), time.time() if now is None else now, action_id))

    def actions(self, plan_id: str) -> list[dict]:
        return self.db.query("SELECT * FROM sh_actions WHERE plan_id=? ORDER BY created_at", (plan_id,))

    def unknown_actions(self) -> list[dict]:
        return self.db.query("SELECT * FROM sh_actions WHERE status IN ('SENT','UNKNOWN')")

    # ownership -----------------------------------------------------------------------------------------------------------
    def own(self, account_key: str, ticket: int, plan_id: str, role: str, now: float | None = None) -> bool:
        """Register the single owner of a terminal position. False if another plan already owns it."""
        with self.db.tx() as c:
            r = c.execute("SELECT plan_id FROM sh_owners WHERE account_key=? AND position_ticket=?", (account_key, int(ticket))).fetchone()
            if r:
                return r["plan_id"] == plan_id
            c.execute("INSERT INTO sh_owners(account_key, position_ticket, plan_id, role, created_at) VALUES (?,?,?,?,?)",
                      (account_key, int(ticket), plan_id, role, time.time() if now is None else now))
            return True

    def owner(self, account_key: str, ticket: int) -> dict | None:
        return self.db.one("SELECT * FROM sh_owners WHERE account_key=? AND position_ticket=?", (account_key, int(ticket)))

    # events --------------------------------------------------------------------------------------------------------------
    def event(self, plan_id: str | None, kind: str, payload: dict, now: float | None = None) -> None:
        self.db.execute("INSERT INTO sh_events(plan_id, t, kind, payload) VALUES (?,?,?,?)",
                        (plan_id, time.time() if now is None else now, kind, dumps(payload)))

    def events(self, plan_id: str, limit: int = 200) -> list[dict]:
        return [dict(r, payload=json.loads(r["payload"])) for r in
                self.db.query("SELECT * FROM sh_events WHERE plan_id=? ORDER BY id DESC LIMIT ?", (plan_id, limit))]
