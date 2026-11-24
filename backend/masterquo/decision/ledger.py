"""Shared risk reservation + execution-intent ledger (PMW-ARC-1) - the single gate in front of BOTH order adapters
(execution/gateway.py for ACTIVE, sh/executor.py for SH). Neither adapter may send a NEW entry without a reservation here.

RiskBook.reserve() runs inside ONE SQLite write transaction (BEGIN IMMEDIATE - serialised across threads AND processes): it reads
the portfolio of both paths (risk/portfolio.state) plus the reservations that are not yet visible as positions and refuses the
entry when the stricter of the two configured limits would be exceeded. Two paths asking at the same moment can therefore never
both pass a limit that has room for one (before 1.33 each path checked the guard and sent on its own - a race window).

States: HELD (sending) -> CONSUMED (filled: the position itself is counted from now on) / RELEASED (rejected/blocked) /
UNKNOWN (no answer from order_send: counted as an open position until reconciliation decides) / EXPIRED (HELD without any outcome
after reservation_ttl_s - a crash between reserve and send; never applied to UNKNOWN).

IntentLedger: one ENTRY intent per dedup_key (path:mode:account:subject). A repeated request returns the existing intent
(DUPLICATE), an UNKNOWN intent is never re-sent - sync() reads the adapters' own reconciliation (order_attempts / sh_plans) and
settles the intent and its reservation.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid

from ..timeutil import iso, utcnow
from . import contracts as K

LIVE = ("HELD", "UNKNOWN")


def _now_iso() -> str:
    return iso(utcnow())


class RiskBook:
    def __init__(self, db, cfg_store, *, sh_limits=None, clock=time.time):
        self.db = db
        self.cfg_store = cfg_store
        self.sh_limits = sh_limits or self._sh_limits
        self.clock = clock

    @staticmethod
    def _sh_limits() -> dict:
        try:
            from ..sh import config as SHC
            return SHC.load().get("risk") or {}
        except Exception:  # noqa: BLE001 - SH config unreadable: only the main limits apply
            return {}

    def _ttl(self) -> float:
        d = getattr(self.cfg_store.get(), "decision", None)
        return float(getattr(d, "reservation_ttl_s", 180.0))

    @staticmethod
    def _pending(c, mode: str, account_key: str | None) -> list[dict]:
        """Live reservations whose subject is NOT yet counted by risk/portfolio.state (no double counting)."""
        q = """SELECT r.* FROM risk_reservations r WHERE r.state IN ('HELD','UNKNOWN') AND r.mode=?
               AND NOT EXISTS (SELECT 1 FROM sh_plans p WHERE r.path='SH' AND p.plan_id=r.subject AND p.state NOT IN ('CLOSED','ERROR_CLOSED','REJECTED'))
               AND NOT EXISTS (SELECT 1 FROM managed_positions m WHERE r.path='ACTIVE' AND m.attempt_id=r.subject AND m.state='OPEN')"""
        args: list = [mode]
        if mode != "PAPER" and account_key:
            q += " AND r.account_key=?"
            args.append(account_key)
        return [dict(x) for x in c.execute(q, args).fetchall()]

    def _expire(self, c) -> None:
        cut = self.clock() - self._ttl()
        c.execute("UPDATE risk_reservations SET state='EXPIRED', updated_at=?, note='TTL_NO_OUTCOME' WHERE state='HELD' AND created_ts < ?",
                  (_now_iso(), cut))

    def reserve(self, *, path: str, subject: str, mode: str, account_key: str | None, risk_money: float | None,
                equity: float | None) -> dict:
        """-> {ok, reservation_id, reasons, portfolio}. SIGNALS never reserves (nothing is executed)."""
        if mode == "SIGNALS":
            return {"ok": False, "reservation_id": None, "reasons": ["SIGNALS_NO_EXECUTION"]}
        from ..risk import portfolio as PF
        key = f"{path}:{mode}:{account_key or '-'}:{subject}"
        legacy = self.cfg_store.get().risk
        sh = self.sh_limits() or {}
        rid = "RSV-" + uuid.uuid4().hex[:16]
        with self.db.tx() as c:
            self._expire(c)
            st = PF.state(self.db, mode, account_key, self.clock())          # same thread -> same connection, inside this transaction
            pend = self._pending(c, mode, account_key)
            pend_risk = sum(float(x["risk_money"] or 0.0) for x in pend)
            view = {**st, "pending_reservations": len(pend), "pending_risk": round(pend_risk, 2)}
            reasons = []
            caps = [int(x) for x in (getattr(legacy, "max_open_positions", None), sh.get("max_open_positions")) if x]
            if caps and st["open_positions"] + len(pend) + 1 > min(caps):
                reasons.append("PORTFOLIO_MAX_OPEN_POSITIONS_RESERVED")
            pcts = [float(x) for x in (getattr(legacy, "daily_loss_limit_pct", None), sh.get("daily_loss_limit_pct")) if x]
            if pcts and equity and float(equity) > 0 and st["realized_today"] - pend_risk <= -min(pcts) / 100.0 * float(equity):
                reasons.append("PORTFOLIO_DAILY_LOSS_LIMIT_RESERVED")
            if reasons:
                return {"ok": False, "reservation_id": None, "reasons": reasons, "portfolio": view}
            try:
                now = _now_iso()
                c.execute("""INSERT INTO risk_reservations(reservation_id, reservation_key, created_at, created_ts, updated_at, path, subject, mode,
                             account_key, risk_money, positions, state) VALUES (?,?,?,?,?,?,?,?,?,?,1,'HELD')""",
                          (rid, key, now, self.clock(), now, path, subject, mode, account_key,
                           None if risk_money is None else float(risk_money)))
            except sqlite3.IntegrityError:
                return {"ok": False, "reservation_id": None, "reasons": ["RESERVATION_ALREADY_LIVE_FOR_SUBJECT"], "portfolio": view}
        return {"ok": True, "reservation_id": rid, "reasons": [], "portfolio": view}

    def settle(self, reservation_id: str | None, outcome: str, note: str | None = None) -> None:
        if not reservation_id:
            return
        state = {"FILLED": "CONSUMED", "PARTIAL": "CONSUMED", "RECONCILED_FILLED": "CONSUMED", "UNKNOWN": "UNKNOWN"}.get(outcome, "RELEASED")
        self.db.execute("UPDATE risk_reservations SET state=?, updated_at=?, note=? WHERE reservation_id=? AND state IN ('HELD','UNKNOWN')",
                        (state, _now_iso(), note or outcome, reservation_id))

    def live(self) -> list[dict]:
        return self.db.query("SELECT * FROM risk_reservations WHERE state IN ('HELD','UNKNOWN') ORDER BY created_at")


class IntentLedger:
    def __init__(self, db, book: RiskBook):
        self.db = db
        self.book = book

    def open(self, *, path: str, mode: str, account_key: str | None, subject: str, symbol: str, side: str, volume: float | None,
             risk_money: float | None, record_id: str | None, equity: float | None, reserve_subject: str | None = None, kind: str = "ENTRY") -> dict:
        """Create the ENTRY (or 1.38: HEDGE leg) intent and reserve risk for it. -> {status: RESERVED|DUPLICATE|BLOCKED, intent, reasons}.
        subject = what is deduplicated (ACTIVE setup_id / SH plan_id); reserve_subject = what becomes the open position (default subject).
        A BLOCKED intent frees its dedup key (the entry may be asked again once there is room), every other state keeps it."""
        dedup = f"{path}:{mode}:{account_key or '-'}:{subject}"
        ex = self.db.one("SELECT * FROM execution_intents WHERE dedup_key=?", (dedup,))
        if ex:
            return {"status": "DUPLICATE", "intent": ex, "reasons": ["INTENT_ALREADY_EXISTS"]}
        iid = "INT-" + uuid.uuid4().hex[:16]
        K.make("ExecutionIntent", intent_id=iid, dedup_key=dedup, record_id=record_id, path=path, kind=kind, mode=mode,
               account_key=account_key, symbol=symbol, side=side if side in K.SIDES else "NONE", volume=volume, risk_money=risk_money, state="NEW")
        now = _now_iso()
        try:
            self.db.execute("""INSERT INTO execution_intents(intent_id, dedup_key, created_at, updated_at, path, kind, record_id, mode, account_key,
                               symbol, side, volume, risk_money, state) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'NEW')""",
                            (iid, dedup, now, now, path, kind, record_id, mode, account_key, symbol, side, volume, risk_money))
        except sqlite3.IntegrityError:
            return {"status": "DUPLICATE", "intent": self.db.one("SELECT * FROM execution_intents WHERE dedup_key=?", (dedup,)),
                    "reasons": ["INTENT_ALREADY_EXISTS"]}
        r = self.book.reserve(path=path, subject=reserve_subject or subject, mode=mode, account_key=account_key, risk_money=risk_money, equity=equity)
        if not r["ok"]:
            self._set(iid, state="BLOCKED", dedup_key=f"{dedup}:BLOCKED:{iid}", outcome_json=json.dumps({"reasons": r["reasons"]}))
            return {"status": "BLOCKED", "intent": self.get(iid), "reasons": r["reasons"], "portfolio": r.get("portfolio")}
        self._set(iid, state="RESERVED", reservation_id=r["reservation_id"])
        return {"status": "RESERVED", "intent": self.get(iid), "reasons": [], "portfolio": r.get("portfolio")}

    def get(self, intent_id: str) -> dict | None:
        return self.db.one("SELECT * FROM execution_intents WHERE intent_id=?", (intent_id,))

    def _set(self, intent_id: str, **f) -> None:
        f["updated_at"] = _now_iso()
        self.db.execute(f"UPDATE execution_intents SET {', '.join(k + '=?' for k in f)} WHERE intent_id=?", (*f.values(), intent_id))

    def sent(self, intent_id: str, source_ref: str) -> None:
        self._set(intent_id, state="SENT", source_ref=source_ref)

    def outcome(self, intent_id: str, res: dict) -> dict:
        """Record the adapter's answer (FILLED / PARTIAL / REJECTED / BLOCKED / UNKNOWN / DUPLICATE) and settle the reservation."""
        st = res.get("status") if res.get("status") in K.OUTCOMES else "UNKNOWN"
        out = K.make("ExecutionOutcome", intent_id=intent_id, status=st, ticket=_int(res.get("ticket")), price=_num(res.get("price")),
                     volume=_num(res.get("volume")), reason=None if res.get("reason") is None else str(res.get("reason"))[:200], at=_now_iso())
        it = self.get(intent_id) or {}
        self._set(intent_id, state=st, outcome_json=json.dumps(out))
        self.book.settle(it.get("reservation_id"), st)
        return out

    def unknown(self) -> list[dict]:
        return self.db.query("SELECT * FROM execution_intents WHERE state IN ('UNKNOWN','SENT')")

    def sync(self) -> dict:
        """Settle UNKNOWN/SENT intents from the adapters' reconciliation (never by re-sending)."""
        done = {"filled": 0, "not_found": 0}
        for it in self.unknown():
            ref = it.get("source_ref")
            if not ref:
                continue
            final = None
            if it["path"] == "ACTIVE":
                a = self.db.one("SELECT state FROM order_attempts WHERE attempt_id=?", (ref,))
                s = (a or {}).get("state")
                final = "RECONCILED_FILLED" if s in ("FILLED", "PARTIAL", "RECONCILED_FILLED") else (
                    "RECONCILED_NOT_FOUND" if s in ("REJECTED", "NOT_FOUND_CHECK_TERMINAL") else None)
            else:
                p = self.db.one("SELECT state FROM sh_plans WHERE plan_id=?", (ref,))
                s = (p or {}).get("state")
                final = None if s in (None, "ENTRY_UNKNOWN", "PENDING_ENTRY") else ("RECONCILED_NOT_FOUND" if s == "REJECTED" else "RECONCILED_FILLED")
            if final:
                self._set(it["intent_id"], state=final)
                self.book.settle(it.get("reservation_id"), "RECONCILED_FILLED" if final == "RECONCILED_FILLED" else "RELEASED", note=final)
                done["filled" if final == "RECONCILED_FILLED" else "not_found"] += 1
        return done

    def recent(self, limit: int = 50) -> list[dict]:
        return self.db.query("SELECT * FROM execution_intents ORDER BY created_at DESC LIMIT ?", (limit,))


def _num(v):
    try:
        f = float(v)
        return f if f == f and abs(f) != float("inf") else None
    except (TypeError, ValueError):
        return None


def _int(v):
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None
