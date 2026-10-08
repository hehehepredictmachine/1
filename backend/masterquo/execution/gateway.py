"""Execution gateway - the only code path that can place orders.

Guarantees:
* pre-send revalidation of the *current* decision (same id, ALLOWED, not expired, same account
  and session epoch, setup still CONFIRMED, fresh quote, price drift within deviation);
* idempotency: one entry per (mode, account, setup) enforced by a UNIQUE key in SQLite -
  a double click, reconnect or restart cannot open a second position for the same decision;
* `order_check` before `order_send`; the attempt is persisted as SENDING before the call;
* a timeout or `None` from `order_send` leaves the attempt UNKNOWN for reconciliation with the
  terminal - it is never re-sent automatically;
* PAPER mode never touches the terminal's trading functions.
"""
from __future__ import annotations

import sqlite3
import threading
import uuid

from ..db.database import dumps
from ..mt5.worker import PRIO_TRADE, MT5CallTimeout
from ..timeutil import iso, parse_iso, utcnow

RETCODES = {10004: "REQUOTE", 10006: "REJECT", 10007: "CANCEL", 10008: "PLACED", 10009: "DONE", 10010: "DONE_PARTIAL",
            10011: "ERROR", 10012: "TIMEOUT", 10013: "INVALID", 10014: "INVALID_VOLUME", 10015: "INVALID_PRICE",
            10016: "INVALID_STOPS", 10017: "TRADE_DISABLED", 10018: "MARKET_CLOSED", 10019: "NO_MONEY", 10020: "PRICE_CHANGED",
            10021: "PRICE_OFF", 10022: "INVALID_EXPIRATION", 10023: "ORDER_CHANGED", 10024: "TOO_MANY_REQUESTS",
            10025: "NO_CHANGES", 10026: "SERVER_DISABLES_AT", 10027: "CLIENT_DISABLES_AT", 10028: "LOCKED", 10029: "FROZEN",
            10030: "INVALID_FILL", 10031: "CONNECTION", 10032: "ONLY_REAL", 10033: "LIMIT_ORDERS", 10034: "LIMIT_VOLUME",
            10035: "INVALID_ORDER", 10036: "POSITION_CLOSED", 10038: "INVALID_CLOSE_VOLUME", 10039: "CLOSE_ORDER_EXIST",
            10040: "LIMIT_POSITIONS", 10041: "REJECT_CANCEL", 10042: "LONG_ONLY", 10043: "SHORT_ONLY", 10044: "CLOSE_ONLY",
            10045: "FIFO_CLOSE", 0: "CHECK_OK"}
OK_CODES = (10008, 10009, 10010)


def client_tag(setup_id: str) -> str:
    return ("MQ:" + setup_id.replace("MQS-", ""))[:20]


class ExecutionError(ValueError):
    pass


class ExecutionGateway:
    def __init__(self, cfg_store, bridge, db, bus, applog, modes, engine, paper):
        self.cfg_store = cfg_store
        self.bridge = bridge
        self.db = db
        self.bus = bus
        self.log = applog
        self.modes = modes
        self.engine = engine
        self.paper = paper
        self.manager = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------ validation
    def _validate(self, decision_id: str) -> dict:
        d = self.engine.current_decision()
        if not d:
            raise ExecutionError("NO_CURRENT_DECISION")
        if d["decision_id"] != decision_id:
            raise ExecutionError("DECISION_SUPERSEDED_REFRESH_AND_RETRY")
        if d["execution_permission"] != "ALLOWED":
            raise ExecutionError("EXECUTION_BLOCKED:" + ",".join(d["reason_codes"][:8]))
        if parse_iso(d["expires_at_utc"]) <= utcnow():
            raise ExecutionError("DECISION_EXPIRED")
        b = self.bridge
        if d["account_key"] != b.account_key or d["session_epoch"] != b.session_epoch:
            raise ExecutionError("ACCOUNT_OR_SESSION_CHANGED")
        gate = self.modes.gate(b.account_key)
        if not gate["allowed"]:
            raise ExecutionError("MODE_GATE:" + ",".join(gate["reason_codes"]))
        if self.manager is not None and self.manager.reconciled_epoch != b.session_epoch:
            raise ExecutionError("RECONCILIATION_WITH_TERMINAL_PENDING")
        setup = d.get("setup") or {}
        if setup.get("state") != "CONFIRMED":
            raise ExecutionError("SETUP_NOT_CONFIRMED")
        risk = d.get("risk") or {}
        if risk.get("risk_gate") != "PASS" or not risk.get("lots"):
            raise ExecutionError("RISK_NOT_PASS_OR_NO_SIZE")
        q = b.quote_status()
        cfg = self.cfg_store.get()
        if not q or q.get("age_seconds") is None or q["age_seconds"] > cfg.mt5.max_quote_age_seconds:
            raise ExecutionError("QUOTE_STALE")
        point = float((b.symbol_info or {}).get("point") or 0)
        px = q["ask"] if d["analysis_direction"] == "LONG" else q["bid"]
        if point and abs(px - risk["entry"]) > cfg.execution.deviation_points * point:
            raise ExecutionError("PRICE_MOVED_SINCE_RISK_CHECK_WAIT_FOR_RECALC")
        return d

    # ------------------------------------------------------------ public
    def execute(self, decision_id: str, initiated_by: str = "USER") -> dict:
        with self._lock:
            try:
                d = self._validate(decision_id)
            except ExecutionError as exc:
                if initiated_by == "USER":
                    self.log.warn("EXECUTION", "BLOCKED", f"Wykonanie zablokowane: {exc}")
                return {"status": "BLOCKED", "reason": str(exc)}
            mode = self.modes.gate(self.bridge.account_key)["mode"]
            setup = d["setup"]
            risk = d["risk"]
            side = "BUY" if d["analysis_direction"] == "LONG" else "SELL"
            entry_key = f"{mode}:{self.bridge.account_key}:{setup['setup_id']}"
            attempt_id = "MQO-" + uuid.uuid4().hex[:16]
            targets = risk["targets"]
            tp_final = targets[-1]["price"]
            now = iso(utcnow())
            try:
                with self.db.tx() as c:
                    c.execute("""INSERT INTO order_attempts(attempt_id, entry_key, decision_id, setup_id, created_at, updated_at, mode, account_key, symbol,
                                 side, volume, price_requested, sl, tp, client_tag, state, initiated_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                              (attempt_id, entry_key, d["decision_id"], setup["setup_id"], now, now, mode, self.bridge.account_key, d["symbol"],
                               side, risk["lots"], risk["entry"], risk["stop_loss"], tp_final, client_tag(setup["setup_id"]), "PREPARED", initiated_by))
            except sqlite3.IntegrityError:
                ex = self.db.one("SELECT attempt_id, state FROM order_attempts WHERE entry_key=?", (entry_key,))
                return {"status": "DUPLICATE", "reason": "ENTRY_ALREADY_ATTEMPTED_FOR_THIS_SETUP", "attempt": ex}
            self.log.info("EXECUTION", "PREPARED", f"{mode}: {side} {risk['lots']} {d['symbol']} SL {risk['stop_loss']} TP {tp_final} ({initiated_by})",
                          {"attempt_id": attempt_id, "decision_id": d["decision_id"]})
            if mode == "PAPER":
                res = self.paper.open(attempt_id=attempt_id, decision=d, side=side, lots=risk["lots"], sl=risk["stop_loss"], targets=targets)
            else:
                res = self._send(attempt_id, d, side, risk, tp_final)
            if res.get("status") in ("FILLED", "PARTIAL"):
                self.engine.lifecycle.terminate(setup["setup_id"], "ENTERED", f"{mode}_{res['status']}")
            self.bus.publish("orders", self.recent_attempts(10))
            return res

    def _set(self, attempt_id: str, **fields) -> None:
        fields["updated_at"] = iso(utcnow())
        cols = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE order_attempts SET {cols} WHERE attempt_id=?", (*fields.values(), attempt_id))

    def _send(self, attempt_id: str, d: dict, side: str, risk: dict, tp_final: float) -> dict:
        b = self.bridge
        cfg = self.cfg_store.get()
        info = b.symbol_info or {}
        fm = int(info.get("filling_mode") or 0)
        sym = d["symbol"]
        tag = client_tag(d["setup"]["setup_id"])

        def build(m):
            q = m.symbol_info_tick(sym)
            price = q.ask if side == "BUY" else q.bid
            filling = m.ORDER_FILLING_FOK if fm & 1 else (m.ORDER_FILLING_IOC if fm & 2 else m.ORDER_FILLING_RETURN)
            return {"action": m.TRADE_ACTION_DEAL, "symbol": sym, "volume": float(risk["lots"]),
                    "type": m.ORDER_TYPE_BUY if side == "BUY" else m.ORDER_TYPE_SELL, "price": price,
                    "sl": float(risk["stop_loss"]), "tp": float(tp_final), "deviation": int(cfg.execution.deviation_points),
                    "magic": int(cfg.mt5.magic_number), "comment": tag, "type_time": m.ORDER_TIME_GTC, "type_filling": filling}
        try:
            req = b.raw_call(build, PRIO_TRADE)
            chk = b.raw_call(lambda m: m.order_check(req), PRIO_TRADE)
        except Exception as exc:
            self._set(attempt_id, state="REJECTED", retcode_text=f"PRECHECK_FAILED:{type(exc).__name__}")
            return {"status": "REJECTED", "reason": "PRECHECK_FAILED"}
        if chk is None or getattr(chk, "retcode", -1) != 0:
            rc = getattr(chk, "retcode", None)
            self._set(attempt_id, state="REJECTED", retcode=rc, retcode_text="ORDER_CHECK:" + RETCODES.get(rc, str(rc)) + ":" + str(getattr(chk, "comment", "")),
                      request_json=dumps(req))
            self.log.warn("EXECUTION", "ORDER_CHECK_REJECTED", f"order_check odrzucił zlecenie: {RETCODES.get(rc, rc)} {getattr(chk, 'comment', '')}")
            return {"status": "REJECTED", "reason": "ORDER_CHECK", "retcode": rc}
        self._set(attempt_id, state="SENDING", request_json=dumps(req), price_requested=req["price"])
        try:
            res = b.raw_call(lambda m: m.order_send(req), PRIO_TRADE, timeout=cfg.execution.order_timeout_seconds)
        except MT5CallTimeout:
            self._set(attempt_id, state="UNKNOWN", retcode_text="ORDER_SEND_TIMEOUT_CHECK_TERMINAL")
            self.log.error("EXECUTION", "UNKNOWN", "Brak odpowiedzi order_send – stan UNKNOWN. Sprawdź terminal; brak ponownego wysłania.")
            return {"status": "UNKNOWN", "reason": "ORDER_SEND_TIMEOUT"}
        except Exception as exc:
            self._set(attempt_id, state="UNKNOWN", retcode_text=f"ORDER_SEND_EXCEPTION:{type(exc).__name__}")
            self.log.error("EXECUTION", "UNKNOWN", f"Wyjątek order_send ({type(exc).__name__}) – stan UNKNOWN, rekonsyliacja z terminalem.")
            return {"status": "UNKNOWN", "reason": "ORDER_SEND_EXCEPTION"}
        if res is None:
            self._set(attempt_id, state="UNKNOWN", retcode_text="ORDER_SEND_RETURNED_NONE")
            return {"status": "UNKNOWN", "reason": "ORDER_SEND_RETURNED_NONE"}
        rc = res.retcode
        rd = {k: getattr(res, k, None) for k in ("retcode", "deal", "order", "volume", "price", "bid", "ask", "comment", "request_id")}
        if rc in OK_CODES and (res.volume or 0) > 0:
            state = "PARTIAL" if rc == 10010 or res.volume < float(risk["lots"]) - 1e-9 else "FILLED"
            self._set(attempt_id, state=state, retcode=rc, retcode_text=RETCODES.get(rc), order_ticket=res.order, deal_ticket=res.deal,
                      position_ticket=res.order, fill_price=res.price, filled_volume=res.volume, result_json=dumps(rd))
            self._register_position(attempt_id, d, side, res.order, res.volume, res.price, risk)
            self.log.info("EXECUTION", state, f"Zlecenie wykonane: {side} {res.volume} @ {res.price} (ticket {res.order})")
            return {"status": state, "ticket": res.order, "price": res.price, "volume": res.volume}
        self._set(attempt_id, state="REJECTED", retcode=rc, retcode_text=RETCODES.get(rc, str(rc)) + ":" + str(getattr(res, "comment", "")),
                  result_json=dumps(rd))
        self.log.warn("EXECUTION", "REJECTED", f"Broker odrzucił zlecenie: {RETCODES.get(rc, rc)} {getattr(res, 'comment', '')}")
        return {"status": "REJECTED", "retcode": rc, "reason": RETCODES.get(rc, str(rc))}

    def _register_position(self, attempt_id, d, side, ticket, volume, price, risk) -> None:
        mode = self.modes.gate(self.bridge.account_key)["mode"]
        t = risk["targets"]
        self.db.execute("""INSERT OR IGNORE INTO managed_positions(position_key, mode, account_key, position_ticket, attempt_id, decision_id, setup_id,
                           strategy_id, symbol, side, volume_initial, volume_open, entry_price, sl, tp1, tp2, state, opened_at, planned_risk_money)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (f"{mode}:{self.bridge.account_key}:{ticket}", mode, self.bridge.account_key, ticket, attempt_id, d["decision_id"],
                         d["setup"]["setup_id"], d["setup"]["strategy_id"], d["symbol"], side, volume, volume, price, risk["stop_loss"],
                         t[0]["price"] if len(t) > 1 else None, t[-1]["price"], "OPEN", iso(utcnow()), risk.get("modeled_loss")))

    def recent_attempts(self, limit: int = 30) -> list[dict]:
        return self.db.query("SELECT attempt_id, decision_id, setup_id, created_at, updated_at, mode, symbol, side, volume, price_requested, sl, tp, "
                             "state, retcode, retcode_text, order_ticket, position_ticket, fill_price, filled_volume, initiated_by "
                             "FROM order_attempts ORDER BY created_at DESC LIMIT ?", (limit,))
