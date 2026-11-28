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
import time
import uuid

from ..db.database import dumps
from ..mt5.worker import PRIO_TRADE, MT5CallTimeout
from ..timeutil import iso, parse_iso, utcnow
from . import policy as exit_policy

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


def snap_tick(info: dict, price: float, mode: str) -> float:
    """Align a price to trade_tick_size: mode 'down' / 'up' / 'nearest' (F-05: SL/TP/BE were only rounded to 6 decimals)."""
    import math
    tick = float((info or {}).get("trade_tick_size") or (info or {}).get("point") or 0)
    if not price or tick <= 0:
        return float(price or 0.0)
    q = price / tick
    n = math.floor(q + 1e-9) if mode == "down" else math.ceil(q - 1e-9) if mode == "up" else math.floor(q + 0.5)
    return round(n * tick, int((info or {}).get("digits") or 8))


def align_stops(info: dict, side: str, sl: float, tp: float) -> tuple[float, float]:
    """Conservative alignment: the SL never moves closer to the entry (BUY down, SELL up) and the TP never closer (BUY up, SELL down)."""
    buy = side in ("BUY", "LONG")
    return (snap_tick(info, sl, "down" if buy else "up") if sl else 0.0, snap_tick(info, tp, "up" if buy else "down") if tp else 0.0)


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
        self.arc = None            # DecisionCoordinator (PMW-ARC-1): intent + shared atomic risk reservation before any NEW entry
        self._lock = threading.Lock()

    # ------------------------------------------------------------ validation
    def _validate(self, decision_id: str) -> tuple[dict, dict]:
        """-> (decision, gate). w2 (I0725): the gate checked here (its mode) is the one execute() uses - the mode is not read again."""
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
        gate = self.modes.gate(b.account_key, path="ACTIVE")       # bot decisions = path ACTIVE (O1)
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
        # settings / account / limits re-check right before sending (never use a stale calculation)
        prefs = getattr(self.engine, "prefs", None)
        if prefs is not None and risk.get("settings_version") != prefs.settings_version():
            raise ExecutionError("SETTINGS_CHANGED_RECALC")
        recheck = getattr(self.engine, "recheck_risk", None)
        if recheck is not None:
            fresh = recheck(d)
            if fresh.get("risk_gate") != "PASS" or not fresh.get("lots"):
                raise ExecutionError("RISK_RECHECK_FAILED:" + ",".join((fresh.get("reason_codes") or [])[:6]))
            if fresh["lots"] + 1e-9 < float(risk["lots"]):
                raise ExecutionError("LIMITS_CHANGED_SIZE_SMALLER_RECALC")
        return d, gate

    # ------------------------------------------------------------ common controls (shared by BOT_SETUP and MANUAL_USER sources)
    def common_checks(self, *, side: str, entry: float, require_real: bool = False, source: str | None = None) -> str:
        """Mode gate (account / DEMO-LIVE / STOP / risk limits), reconciliation, quote freshness and drift.
        Returns the mode; raises ExecutionError with the concrete reason. Source-specific checks stay in each validator.
        w2 (I0782): source MANUAL_USER also passes the shared portfolio guard of both paths (risk/portfolio: daily loss of the day,
        open positions) - called directly, NOT through gate(path=...), so the primary-path rule (O1) and autobind are not involved."""
        b = self.bridge
        gate = self.modes.gate(b.account_key)
        mode = gate["mode"]
        if mode == "SIGNALS":
            return mode
        if not gate["allowed"]:
            raise ExecutionError("MODE_GATE:" + ",".join(gate["reason_codes"]))
        if source == "MANUAL_USER":
            try:
                from ..risk import portfolio as PF
                from ..sh import config as SHC
                st = PF.state(self.db, mode, b.account_key, time.time())
                pf = PF.check(st, equity=(b.account_status() or {}).get("equity"), legacy_limits=self.cfg_store.get().risk,
                              sh_limits=SHC.load().get("risk"))
            except Exception as exc:  # noqa: BLE001 - unknown portfolio state = no new entry (never skipped)
                raise ExecutionError(f"PORTFOLIO_GUARD_ERROR:{type(exc).__name__}") from None
            if pf:
                raise ExecutionError("PORTFOLIO:" + ",".join(pf))
        if require_real and mode == "PAPER":
            raise ExecutionError("REAL_MODE_REQUIRED")
        if mode != "PAPER" and self.manager is not None and self.manager.reconciled_epoch != b.session_epoch:
            raise ExecutionError("RECONCILIATION_WITH_TERMINAL_PENDING")
        q = b.quote_status()
        cfg = self.cfg_store.get()
        if not q or q.get("age_seconds") is None or q["age_seconds"] > cfg.mt5.max_quote_age_seconds:
            raise ExecutionError("QUOTE_STALE")
        point = float((b.symbol_info or {}).get("point") or 0)
        px = q["ask"] if side == "BUY" else q["bid"]
        if point and abs(px - entry) > cfg.execution.deviation_points * point:
            raise ExecutionError("PRICE_DRIFT_REPLAN")
        return mode

    def manual_modify(self, mp: dict, action: str, *, offset_points: float = 0.0, volume: float | None = None) -> dict:
        """Real-account management of ONE managed position (own ticket only; netting share is refused)."""
        b = self.bridge
        if mp["account_key"] != b.account_key:
            return {"status": "REJECTED", "reason": "OTHER_ACCOUNT"}
        p = next((x for x in b.positions if x["ticket"] == mp["position_ticket"]), None)
        if not p:
            return {"status": "REJECTED", "reason": "POSITION_NOT_FOUND"}
        if abs(float(p["volume"]) - float(mp["volume_open"])) > 1e-9:
            return {"status": "REJECTED", "reason": "NETTING_SHARE_MISMATCH (pozycja zawiera inne transakcje)"}
        cfg = self.cfg_store.get()
        info = b.symbol_info or {}
        point = float(info.get("point") or 0)
        try:
            if action == "BREAK_EVEN":
                new_sl = snap_tick(info, mp["entry_price"] + (offset_points * point if mp["side"] == "BUY" else -offset_points * point),
                                   "up" if mp["side"] == "BUY" else "down")
                cur = p.get("sl") or mp.get("sl")
                if cur and ((mp["side"] == "BUY" and cur >= new_sl) or (mp["side"] == "SELL" and cur <= new_sl)):
                    return {"status": "UNCHANGED", "reason": "SL_ALREADY_BETTER"}
                r = b.raw_call(lambda m: m.order_send({"action": m.TRADE_ACTION_SLTP, "symbol": mp["symbol"], "position": p["ticket"], "sl": new_sl,
                                                       "tp": p.get("tp") or 0.0, "magic": int(cfg.mt5.magic_number)}), PRIO_TRADE,
                               timeout=cfg.execution.order_timeout_seconds)
            else:
                vol = float(p["volume"]) if action == "CLOSE" else float(volume or 0)
                if action != "CLOSE":
                    import math
                    step, vmin = float(info.get("volume_step") or 0.01), float(info.get("volume_min") or 0.01)
                    vol = round(math.floor(vol / step + 1e-9) * step, 8)
                    rest = round(float(p["volume"]) - vol, 8)
                    if vol < vmin - 1e-9:
                        return {"status": "REJECTED", "reason": f"VOLUME_BELOW_MIN ({vol} < {vmin})"}
                    if 1e-9 < rest < vmin - 1e-9:
                        return {"status": "REJECTED", "reason": f"REMAINDER_BELOW_MIN ({rest} < {vmin}) – zamknij całą pozycję"}

                def req(m):
                    t = m.symbol_info_tick(mp["symbol"])
                    return {"action": m.TRADE_ACTION_DEAL, "symbol": mp["symbol"], "volume": vol, "position": p["ticket"],
                            "type": m.ORDER_TYPE_SELL if mp["side"] == "BUY" else m.ORDER_TYPE_BUY, "price": t.bid if mp["side"] == "BUY" else t.ask,
                            "deviation": int(cfg.execution.deviation_points), "magic": int(cfg.mt5.magic_number), "comment": "MQ:MANUAL",
                            "type_time": m.ORDER_TIME_GTC, "type_filling": m.ORDER_FILLING_FOK if int(info.get("filling_mode") or 0) & 1 else m.ORDER_FILLING_IOC}
                r = b.raw_call(lambda m: m.order_send(req(m)), PRIO_TRADE, timeout=cfg.execution.order_timeout_seconds)
        except MT5CallTimeout:
            return {"status": "UNKNOWN", "reason": "TIMEOUT_CHECK_TERMINAL"}
        except Exception as exc:  # noqa: BLE001 - worker unavailable / validation: refused, nothing was sent
            return {"status": "REJECTED", "reason": type(exc).__name__}
        rc = getattr(r, "retcode", None)
        return {"status": "DONE" if rc in OK_CODES else "REJECTED", "retcode": RETCODES.get(rc, rc)}

    # ------------------------------------------------------------ public
    def execute(self, decision_id: str, initiated_by: str = "USER") -> dict:
        with self._lock:
            try:
                d, gate0 = self._validate(decision_id)
            except ExecutionError as exc:
                if initiated_by == "USER":
                    self.log.warn("EXECUTION", "BLOCKED", f"Wykonanie zablokowane: {exc}")
                return {"status": "BLOCKED", "reason": str(exc)}
            mode = gate0["mode"]                    # w2 (I0725): the validated mode (was read again without `allowed` - SIGNALS reached _send)
            setup = d["setup"]
            risk = d["risk"]
            side = "BUY" if d["analysis_direction"] == "LONG" else "SELL"
            entry_key = f"{mode}:{self.bridge.account_key}:{setup['setup_id']}"
            attempt_id = "MQO-" + uuid.uuid4().hex[:16]
            targets = risk["targets"]
            tp_final = targets[-1]["price"]
            now = iso(utcnow())
            intent = None
            if self.arc is not None:
                op = self.arc.intents.open(path="ACTIVE", mode=mode, account_key=self.bridge.account_key, subject=setup["setup_id"],
                                           reserve_subject=attempt_id, symbol=d["symbol"], side=side, volume=float(risk["lots"]),
                                           risk_money=risk.get("modeled_loss"), record_id=(d.get("decision_record") or {}).get("record_id"),
                                           equity=(self.bridge.account or {}).get("equity"))
                if op["status"] == "DUPLICATE":
                    return {"status": "DUPLICATE", "reason": "INTENT_ALREADY_EXISTS_FOR_THIS_SETUP", "intent": op["intent"]["intent_id"]}
                if op["status"] == "BLOCKED":
                    if initiated_by == "USER":
                        self.log.warn("EXECUTION", "BLOCKED", f"Wykonanie zablokowane (rezerwacja ryzyka): {','.join(op['reasons'])}")
                    return {"status": "BLOCKED", "reason": "RESERVATION:" + ",".join(op["reasons"])}
                intent = op["intent"]["intent_id"]
            # w2 (I0725): the mode gate once more right before anything is persisted / sent - a mode switch (or a new block) after the
            # validation never sends under another mode (nor in SIGNALS)
            now_gate = self.modes.gate(self.bridge.account_key, path="ACTIVE")
            if now_gate["mode"] != mode or not now_gate["allowed"] or mode == "SIGNALS":
                res = {"status": "BLOCKED", "reason": "MODE_CHANGED_DURING_EXECUTION"}
                if intent:
                    self.arc.intents.outcome(intent, res)
                if initiated_by == "USER":
                    self.log.write("WARNING", "EXECUTION", "BLOCKED", f"Wykonanie zablokowane: tryb zmienił się w trakcie ({mode} -> {now_gate['mode']})")
                return res
            try:
                with self.db.tx() as c:
                    c.execute("""INSERT INTO order_attempts(attempt_id, entry_key, decision_id, setup_id, created_at, updated_at, mode, account_key, symbol,
                                 side, volume, price_requested, sl, tp, client_tag, state, initiated_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                              (attempt_id, entry_key, d["decision_id"], setup["setup_id"], now, now, mode, self.bridge.account_key, d["symbol"],
                               side, risk["lots"], risk["entry"], risk["stop_loss"], tp_final, client_tag(setup["setup_id"]), "PREPARED", initiated_by))
            except sqlite3.IntegrityError:
                ex = self.db.one("SELECT attempt_id, state FROM order_attempts WHERE entry_key=?", (entry_key,))
                if intent:
                    self.arc.intents.outcome(intent, {"status": "DUPLICATE", "reason": "ENTRY_ALREADY_ATTEMPTED_FOR_THIS_SETUP"})
                return {"status": "DUPLICATE", "reason": "ENTRY_ALREADY_ATTEMPTED_FOR_THIS_SETUP", "attempt": ex}
            self._record_decision_copy(attempt_id, d, side, risk, tp_final)      # 1.46 arch (I0777): audit only, never raises
            if intent:
                self.arc.intents.sent(intent, attempt_id)
            self.log.info("EXECUTION", "PREPARED", f"{mode}: {side} {risk['lots']} {d['symbol']} SL {risk['stop_loss']} TP {tp_final} ({initiated_by})",
                          {"attempt_id": attempt_id, "decision_id": d["decision_id"]})
            if mode == "PAPER":
                res = self.paper.open(attempt_id=attempt_id, decision=d, side=side, lots=risk["lots"], sl=risk["stop_loss"], targets=targets,
                                      exit_policy=self.plan_policy(d))
            else:
                res = self._send(attempt_id, d, side, risk, tp_final)
            if intent:
                try:
                    self.arc.intents.outcome(intent, res)
                except Exception as exc:  # noqa: BLE001 - the order outcome itself is already persisted in order_attempts
                    self.log.warn("EXECUTION", "INTENT_OUTCOME_FAILED", f"{type(exc).__name__}: {exc}"[:200])
            if res.get("status") in ("FILLED", "PARTIAL"):
                self.engine.mark_entered(setup["setup_id"], f"{mode}_{res['status']}")
            self.bus.publish("orders", self.recent_attempts(10))
            return res

    def plan_policy(self, d: dict, fill: float | None = None) -> dict:
        """Exit policy of THIS decision's setup (targets + weights + exit_rules), frozen with the position at open."""
        cfg = self.cfg_store.get()
        risk = d.get("risk") or {}
        lv = d.get("levels") or {}
        return exit_policy.from_plan(side=d["analysis_direction"], stop_loss=float(risk["stop_loss"]), targets=risk.get("targets") or [],
                                     exit_rules=lv.get("exit_rules"), timeframe=(d.get("setup") or {}).get("setup_tf"),
                                     tp1_weight_default=cfg.strategy.tp1_weight, be_default=cfg.strategy.move_sl_to_breakeven_after_tp1, entry=fill)

    def _record_decision_copy(self, attempt_id: str, d: dict, side: str, risk: dict, tp_final: float) -> None:
        """1.46 arch (I0777): order_attempts.decision_json = a copy of the decision used for THIS attempt. The decision id / content hash
        do not cover SL / TP / volume / setup version and decisions keeps its first record (INSERT OR IGNORE), so decisions.record_json may
        show other levels than the order. Audit only: the MT5 request, _validate and the dedup (entry_key / intents) are untouched; a
        serialisation or write error stores an error marker (or nothing) and never blocks, delays past the write or changes the send."""
        try:
            setup = d.get("setup") or {}
            lv = d.get("levels") or {}
            snap = {"decision_id": d.get("decision_id"), "content_hash": d.get("content_hash"), "snapshot_id": d.get("snapshot_id"),
                    "as_of_utc": d.get("as_of_utc"), "expires_at_utc": d.get("expires_at_utc"),
                    "setup": {k: setup.get(k) for k in ("setup_id", "version", "state", "state_changed_at", "strategy_id", "profile")},
                    "levels": {k: lv.get(k) for k in ("entry", "stop_loss", "targets")} if isinstance(lv, dict) else None,
                    "risk": {k: risk.get(k) for k in ("lots", "entry", "stop_loss", "targets", "modeled_loss", "risk_gate")},
                    "sent": {"side": side, "volume": risk.get("lots"), "price_requested": risk.get("entry"), "sl": risk.get("stop_loss"),
                             "tp": tp_final}}
            text = dumps(snap)
        except Exception as exc:  # noqa: BLE001 - audit copy only (e.g. NaN in a plan level)
            text = dumps({"status": "DECISION_COPY_FAILED", "error": type(exc).__name__, "decision_id": d.get("decision_id")})
        try:
            self.db.execute("UPDATE order_attempts SET decision_json=? WHERE attempt_id=?", (text, attempt_id))
        except Exception as exc:  # noqa: BLE001 - an audit write never stops the order path
            import contextlib
            with contextlib.suppress(Exception):                   # the log may sit on the same broken database
                self.log.write("WARNING", "EXECUTION", "DECISION_COPY_FAILED", f"{type(exc).__name__}: {exc}"[:200])

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
            sl_px, tp_px = align_stops(info, side, float(risk["stop_loss"]), float(tp_final))
            return {"action": m.TRADE_ACTION_DEAL, "symbol": sym, "volume": float(risk["lots"]),
                    "type": m.ORDER_TYPE_BUY if side == "BUY" else m.ORDER_TYPE_SELL, "price": price,
                    "sl": sl_px, "tp": tp_px, "deviation": int(cfg.execution.deviation_points),
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
            pos = self._position_of_deal(res.deal) or res.order       # netting/exchange: position id != order ticket
            self._set(attempt_id, state=state, retcode=rc, retcode_text=RETCODES.get(rc), order_ticket=res.order, deal_ticket=res.deal,
                      position_ticket=pos, fill_price=res.price, filled_volume=res.volume, result_json=dumps(rd))
            self._register_position(attempt_id, d, side, pos, res.volume, res.price, risk)
            self.log.info("EXECUTION", state, f"Zlecenie wykonane: {side} {res.volume} @ {res.price} (pozycja {pos})")
            return {"status": state, "ticket": pos, "price": res.price, "volume": res.volume}
        self._set(attempt_id, state="REJECTED", retcode=rc, retcode_text=RETCODES.get(rc, str(rc)) + ":" + str(getattr(res, "comment", "")),
                  result_json=dumps(rd))
        self.log.warn("EXECUTION", "REJECTED", f"Broker odrzucił zlecenie: {RETCODES.get(rc, rc)} {getattr(res, 'comment', '')}")
        return {"status": "REJECTED", "retcode": rc, "reason": RETCODES.get(rc, str(rc))}

    def _position_of_deal(self, deal_ticket) -> int | None:
        """Position id of the entry deal (on netting/exchange accounts the order ticket is NOT the position ticket)."""
        if not deal_ticket:
            return None
        try:
            deals = self.bridge.raw_call(lambda m: m.history_deals_get(ticket=deal_ticket))
            pid = getattr((deals or [None])[0], "position_id", None)
            return int(pid) if pid else None
        except Exception:  # noqa: BLE001 - never fatal; reconciliation uses deal.position_id anyway
            return None

    def _register_position(self, attempt_id, d, side, ticket, volume, price, risk) -> None:
        # w2 (I0725): the mode the order was SENT under (order_attempts, both the bot and the manual path) - never read again from the
        # mode manager after order_send (a switch to PAPER meanwhile registered a real position as PAPER)
        row = self.db.one("SELECT mode FROM order_attempts WHERE attempt_id=?", (attempt_id,))
        mode = (row or {}).get("mode")
        if mode not in ("AUTO_DEMO", "AUTO_LIVE"):
            mode = "AUTO_LIVE" if (self.bridge.account_status() or {}).get("trade_mode") == "REAL" else "AUTO_DEMO"
        pol = self.plan_policy(d, fill=price)
        t = pol["targets"]
        self.db.execute("""INSERT OR IGNORE INTO managed_positions(position_key, mode, account_key, position_ticket, attempt_id, decision_id, setup_id,
                           strategy_id, symbol, side, volume_initial, volume_open, entry_price, sl, tp1, tp2, state, opened_at, planned_risk_money, exit_policy_json)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (f"{mode}:{self.bridge.account_key}:{ticket}", mode, self.bridge.account_key, ticket, attempt_id, d["decision_id"],
                         d["setup"]["setup_id"], d["setup"]["strategy_id"], d["symbol"], side, volume, volume, price, risk["stop_loss"],
                         t[0]["price"] if len(t) > 1 else None, t[-1]["price"], "OPEN", iso(utcnow()), risk.get("modeled_loss"), dumps(pol)))

    def recent_attempts(self, limit: int = 30) -> list[dict]:
        return self.db.query("SELECT attempt_id, decision_id, setup_id, created_at, updated_at, mode, symbol, side, volume, price_requested, sl, tp, "
                             "state, retcode, retcode_text, order_ticket, position_ticket, fill_price, filled_volume, initiated_by "
                             "FROM order_attempts ORDER BY created_at DESC LIMIT ?", (limit,))
