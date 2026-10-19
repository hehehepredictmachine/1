"""Manual Trade Pad (PMW-UPD-07 R12) - functional equivalent of a manual execution / practice pad inside the bot (NOT a signal model).

Plan (pure, `plan_math`): side, SL/TP as prices or distances in points, sizing FIXED lots or RISK_PCT of equity/balance. Metadata from
the terminal: tick_size (point is NOT a synonym), digits, volume_min/max/step, stops_level, freeze_level, currencies. SL/TP aligned to
the tick grid in the conservative direction (SL away from the entry, TP towards it) and the aligned values are shown; sizing is done
AFTER the alignment. P&L at SL/TP from the terminal calculator (order_calc_profit, account currency, Ask entry / Bid exit for LONG);
risk % : cash_budget = basis * pct / 100; volume = largest step multiple (rounded DOWN) whose full cost (loss at SL + round-turn
commission + slippage buffer) fits the budget, checked again at the final volume; smallest lot above budget -> MIN_VOLUME_EXCEEDS_RISK.
Commission source BROKER_OBSERVED / USER_CONFIGURED / PACKAGE_DEFAULT / UNKNOWN - UNKNOWN is never turned into 0: the plan shows the
gap and is not eligible for execution. Plan TTL default 5 s; a fresh check is always done again before execution.
Intent / gateway: ManualTradeIntent (own id + version). Source validator MANUAL_USER (no fabricated strategy CONFIRMED or agent ALLOWED);
common controls shared with BOT_SETUP via ExecutionGateway.common_checks (mode gate, Execution Lock, STOP, reconciliation, quote).
The ONLY order_send path stays in the gateway (_send). Idempotency key mode|account|context|intent|action|revision, persisted PREPARED
before any call; a timeout leaves UNKNOWN (reconciled by tag, never re-sent). PAPER uses the shared paper engine. LOCKED blocks every
real account mutation. PRICE_BREAK_EVEN moves SL to entry +- offset and never worsens a better SL (not a zero-cost guarantee).
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import threading
import uuid
from datetime import timedelta

from ..timeutil import iso, parse_iso, utcnow

VERSION = "MQ-MANUAL-PAD-1.0.0"
COMMISSION_SOURCE = {"DEAL_HISTORY": "BROKER_OBSERVED", "FROM_DEAL_HISTORY": "BROKER_OBSERVED", "CONFIGURED": "USER_CONFIGURED",
                     "CONFIGURED_FALLBACK": "USER_CONFIGURED", "PACKAGE_DEFAULT": "PACKAGE_DEFAULT"}


class PlanError(ValueError):
    pass


def _align(price: float, tick: float, mode: str) -> float:
    k = price / tick
    k = math.floor(k + 1e-9) if mode == "down" else math.ceil(k - 1e-9)
    return round(k * tick, 10)


def _floor_step(v: float, step: float) -> float:
    return round(math.floor(v / step + 1e-9) * step, 10)


def plan_math(*, side: str, quote: dict, meta: dict, sl: float | None = None, tp: float | None = None, sl_points: float | None = None,
              tp_points: float | None = None, rr: float | None = None, sizing_mode: str = "RISK_PCT", lots: float | None = None,
              risk_pct: float | None = None, basis_value: float | None = None, risk_basis: str = "equity", calc_profit=None, calc_margin=None,
              commission: dict | None = None, slippage_ticks: float = 2.0, free_margin: float | None = None, max_risk_pct: float = 2.0,
              linear_fallback: bool = False, account_currency: str | None = None) -> dict:
    """Pure plan. calc_profit(side, vol, open, close) / calc_margin(side, vol, price) are the terminal calculators (None -> unavailable)."""
    reasons: list[str] = []
    if side not in ("BUY", "SELL"):
        raise PlanError("SIDE_INVALID")
    tick = float(meta.get("trade_tick_size") or 0)
    point = float(meta.get("point") or 0)
    if tick <= 0 or point <= 0:
        raise PlanError("TICK_OR_POINT_UNKNOWN")
    vmin, vmax, vstep = float(meta.get("volume_min") or 0), float(meta.get("volume_max") or 0), float(meta.get("volume_step") or 0)
    if vmin <= 0 or vstep <= 0 or vmax <= 0:
        raise PlanError("VOLUME_LIMITS_UNKNOWN")
    sgn = 1 if side == "BUY" else -1
    entry = float(quote["ask"] if side == "BUY" else quote["bid"])
    exit_ref = float(quote["bid"] if side == "BUY" else quote["ask"])
    if sl is None and sl_points:
        sl = entry - sgn * sl_points * point
    if sl is None:
        raise PlanError("SL_REQUIRED")
    sl_a = _align(sl, tick, "down" if side == "BUY" else "up")                    # away from the entry (conservative risk)
    if tp is None and tp_points:
        tp = entry + sgn * tp_points * point
    if tp is None and rr:
        tp = entry + sgn * rr * abs(entry - sl_a)
    tp_a = _align(tp, tick, "down" if side == "BUY" else "up") if tp is not None else None   # towards the entry (conservative reward)
    if sgn * (entry - sl_a) <= 0:
        raise PlanError("SL_WRONG_SIDE")
    if tp_a is not None and sgn * (tp_a - entry) <= 0:
        raise PlanError("TP_WRONG_SIDE")
    stops = float(meta.get("trade_stops_level") or 0) * point
    if stops and (abs(entry - sl_a) < stops or (tp_a is not None and abs(tp_a - entry) < stops)):
        reasons.append("STOPS_LEVEL_VIOLATION")
    freeze = float(meta.get("trade_freeze_level") or 0) * point
    slip = slippage_ticks * tick

    def loss_per(vol):
        """Account-currency loss at SL for `vol` lots (positive number), terminal calculator first."""
        p = calc_profit(side, vol, entry, sl_a) if calc_profit else None
        if p is None and linear_fallback:
            cs = float(meta.get("trade_contract_size") or 0)
            if cs <= 0 or (account_currency and meta.get("currency_profit") and meta["currency_profit"] != account_currency):
                return None
            p = sgn * (sl_a - entry) * cs * vol
        return None if p is None else abs(p)

    def slip_cost(vol):
        p = calc_profit(side, vol, entry, entry - sgn * slip) if calc_profit else None
        if p is None and linear_fallback:
            p = slip * float(meta.get("trade_contract_size") or 0) * vol
        return abs(p) if p is not None else None

    com_src = COMMISSION_SOURCE.get((commission or {}).get("source"), "UNKNOWN") if (commission or {}).get("per_lot_per_side") is not None else "UNKNOWN"
    com_side = (commission or {}).get("per_lot_per_side") if com_src != "UNKNOWN" else None
    if com_src == "UNKNOWN":
        reasons.append("COMMISSION_UNKNOWN")

    def full_cost(vol):
        lp, sc = loss_per(vol), slip_cost(vol)
        if lp is None or sc is None:
            return None
        return lp + sc + (2 * com_side * vol if com_side is not None else 0.0)

    budget = None
    if sizing_mode == "RISK_PCT":
        if risk_pct is None or basis_value is None:
            raise PlanError("RISK_PCT_AND_BASIS_REQUIRED")
        if not 0 < risk_pct <= max_risk_pct:
            raise PlanError(f"RISK_PCT_OUT_OF_POLICY (0 < risk ≤ {max_risk_pct}%)")
        budget = basis_value * risk_pct / 100.0
        c1 = full_cost(1.0)
        if c1 is None or c1 <= 0:
            raise PlanError("PRICING_UNAVAILABLE (order_calc_profit)")
        vol = min(_floor_step(budget / c1, vstep), _floor_step(vmax, vstep))
        while vol >= vmin and (full_cost(vol) or float("inf")) > budget + 1e-9:     # verify at the final volume (non-linear safe)
            vol = round(vol - vstep, 10)
        if vol < vmin:
            raise PlanError("MIN_VOLUME_EXCEEDS_RISK")
    elif sizing_mode == "FIXED":
        if not lots:
            raise PlanError("LOTS_REQUIRED")
        if lots > vmax:
            raise PlanError("LOTS_ABOVE_MAX")
        vol = _floor_step(lots, vstep)
        if vol < vmin:
            raise PlanError("LOTS_BELOW_MIN")
    else:
        raise PlanError("SIZING_MODE_INVALID")
    lp = loss_per(vol)
    if lp is None:
        raise PlanError("PRICING_UNAVAILABLE (order_calc_profit)")
    gain = None
    if tp_a is not None:
        g = calc_profit(side, vol, entry, tp_a) if calc_profit else None
        if g is None and linear_fallback:
            g = sgn * (tp_a - entry) * float(meta.get("trade_contract_size") or 0) * vol
        gain = abs(g) if g is not None else None
    comm_rt = 2 * com_side * vol if com_side is not None else None
    sc = slip_cost(vol)
    margin = calc_margin(side, vol, entry) if calc_margin else None
    if margin is not None and free_margin is not None and margin > free_margin:
        reasons.append("INSUFFICIENT_FREE_MARGIN")
    net_risk = lp + (sc or 0) + (comm_rt or 0) if comm_rt is not None else None
    net_gain = gain - (comm_rt or 0) - (sc or 0) if (gain is not None and comm_rt is not None) else None
    rem = round(vol - vstep, 10)
    out = {"version": VERSION, "side": side, "entry": entry, "exit_reference": exit_ref, "sl_requested": sl, "tp_requested": tp, "sl": sl_a, "tp": tp_a,
           "aligned_to_tick": tick, "point": point, "lots": vol, "sizing_mode": sizing_mode, "risk_basis": risk_basis, "risk_pct": risk_pct, "budget": budget,
           "loss_at_sl_gross": round(lp, 2), "gain_at_tp_gross": None if gain is None else round(gain, 2), "commission_round_turn": None if comm_rt is None else round(comm_rt, 2),
           "commission_source": com_src, "slippage_buffer": None if sc is None else round(sc, 2), "slippage_ticks": slippage_ticks, "spread": round(quote["ask"] - quote["bid"], 10),
           "risk_net": None if net_risk is None else round(net_risk, 2), "reward_net": None if net_gain is None else round(net_gain, 2),
           "rr_gross": None if gain is None else round(gain / lp, 3), "rr_net": None if (net_gain is None or not net_risk) else round(net_gain / net_risk, 3),
           "margin": margin, "free_margin": free_margin, "pricing_source": "TERMINAL_CALC" if calc_profit else ("OFFLINE_LINEAR_FALLBACK" if linear_fallback else None),
           "stops_level_price": stops, "freeze_level_price": freeze, "partial_close_min_remaining_ok": rem >= vmin, "volume_limits": [vmin, vmax, vstep],
           "reason_codes": reasons, "execution_eligible": not reasons}
    return out


class ManualPad:
    def __init__(self, cfg_store, bridge, db, bus, applog, modes, paper, gateway, ttl_s: float = 5.0):
        self.cfg_store, self.bridge, self.db, self.bus, self.log = cfg_store, bridge, db, bus, applog
        self.modes, self.paper, self.gateway = modes, paper, gateway
        self.ttl_s = ttl_s
        self._plans: dict[str, dict] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------ plan
    def plan(self, body: dict) -> dict:
        b = self.bridge
        cfg = self.cfg_store.get()
        q = b.quote_status()
        if not q or q.get("age_seconds") is None or q["age_seconds"] > cfg.mt5.max_quote_age_seconds:
            raise PlanError("QUOTE_STALE")
        meta = dict(b.symbol_info or {})
        acc = b.account_status() or {}
        basis = acc.get("equity") if body.get("risk_basis", "equity") == "equity" else acc.get("balance")
        from ..risk.costs import resolve_commission
        with b._lock:
            deals = list(b.deals)
        com = resolve_commission(cfg.costs, deals, cfg.mt5.symbol)
        num = lambda k: None if body.get(k) in (None, "") else float(body[k])  # noqa: E731
        p = plan_math(side=str(body.get("side")), quote=q, meta=meta, sl=num("sl"), tp=num("tp"), sl_points=num("sl_points"), tp_points=num("tp_points"),
                      rr=num("rr"), sizing_mode=str(body.get("sizing_mode") or "RISK_PCT"), lots=num("lots"), risk_pct=num("risk_pct"),
                      basis_value=basis, risk_basis=str(body.get("risk_basis") or "equity"), calc_profit=b.calc_profit, calc_margin=b.calc_margin,
                      commission=com, free_margin=acc.get("free_margin"), max_risk_pct=float(cfg.risk.risk_per_trade_pct or 2.0),
                      account_currency=acc.get("currency"))
        pid = "MPL-" + uuid.uuid4().hex[:12]
        now = utcnow()
        prefs = getattr(self.gateway.engine, "prefs", None)
        p.update(plan_id=pid, instrument=cfg.mt5.symbol, account_key=b.account_key, session_epoch=b.session_epoch, quote_time=q.get("time_utc"),
                 frozen_at=iso(now), expires_at=iso(now + timedelta(seconds=float(body.get("ttl_s") or self.ttl_s))),
                 settings_version=prefs.settings_version() if prefs is not None else None, source_pattern_id=body.get("source_pattern_id"),
                 mode=self.modes.gate(b.account_key)["mode"], execution_lock=cfg.execution.lock)
        with self._lock:
            self._plans[pid] = p
        return p

    # ------------------------------------------------------------ intent
    def create_intent(self, plan_id: str) -> dict:
        p = self._plans.get(plan_id)
        if not p:
            raise PlanError("PLAN_NOT_FOUND_OR_EXPIRED")
        iid = "MTI-" + uuid.uuid4().hex[:12]
        now = iso(utcnow())
        self.db.execute("INSERT INTO manual_intents(intent_id, version, created_at, updated_at, mode, account, instrument, side, state, plan, source_pattern_id) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (iid, 1, now, now, p["mode"], p["account_key"], p["instrument"], p["side"], "PLANNED",
                                                          json.dumps(p), p.get("source_pattern_id")))
        return {"intent_id": iid, "version": 1, "state": "PLANNED", "plan": p}

    def intent(self, iid: str) -> dict | None:
        r = self.db.one("SELECT * FROM manual_intents WHERE intent_id=?", (iid,))
        if r:
            r["plan"] = json.loads(r["plan"])
            r["actions"] = self.db.query("SELECT idempotency_key, action, action_revision, state, created_at, updated_at, result FROM manual_actions "
                                         "WHERE intent_id=? ORDER BY created_at", (iid,))
        return r

    def intents(self, limit: int = 20) -> list[dict]:
        return self.db.query("SELECT intent_id, version, created_at, mode, instrument, side, state, source_pattern_id FROM manual_intents ORDER BY created_at DESC LIMIT ?",
                             (limit,))

    def _validate_manual(self, it: dict) -> tuple[str, dict]:
        """MANUAL_USER source validator + common account / lock / mode / quote controls of the gateway."""
        p = it["plan"]
        b = self.bridge
        if parse_iso(p["expires_at"]) <= utcnow():
            raise PlanError("PLAN_EXPIRED_REPLAN")
        if p["account_key"] != b.account_key or p["session_epoch"] != b.session_epoch:
            raise PlanError("ACCOUNT_OR_SESSION_CHANGED_REPLAN")
        prefs = getattr(self.gateway.engine, "prefs", None)
        if prefs is not None and p.get("settings_version") != prefs.settings_version():
            raise PlanError("SETTINGS_CHANGED_REPLAN")
        if not p["execution_eligible"]:
            raise PlanError("PLAN_NOT_ELIGIBLE:" + ",".join(p["reason_codes"]))
        mode = self.gateway.common_checks(side=p["side"], entry=p["entry"], require_real=False)
        if mode == "SIGNALS":
            raise PlanError("MODE_SIGNALS_NO_EXECUTION")
        return mode, p

    def execute(self, iid: str, action_revision: int = 1) -> dict:
        it = self.intent(iid)
        if not it:
            raise PlanError("INTENT_NOT_FOUND")
        mode_now = self.modes.gate(self.bridge.account_key)["mode"]
        key = f"{mode_now}|{self.bridge.account_key}|{it['instrument']}|{iid}|ENTRY|{int(action_revision)}"
        now = iso(utcnow())
        try:
            self.db.execute("INSERT INTO manual_actions(idempotency_key, intent_id, action, action_revision, state, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                            (key, iid, "ENTRY", int(action_revision), "PREPARED", now, now))
        except sqlite3.IntegrityError:
            ex = self.db.one("SELECT state, result FROM manual_actions WHERE idempotency_key=?", (key,))
            return {"status": "DUPLICATE", "reason": "ACTION_ALREADY_ATTEMPTED", "state": ex["state"], "result": json.loads(ex["result"] or "null")}
        try:
            mode, p = self._validate_manual(it)
        except (PlanError, ValueError) as exc:
            self._act(key, "BLOCKED", {"reason": str(exc)})
            self._intent_state(iid, "BLOCKED")
            self.log.warn("EXECUTION", "MANUAL_BLOCKED", f"Manual Pad: wykonanie zablokowane: {exc}")
            return {"status": "BLOCKED", "reason": str(exc)}
        d = {"decision_id": iid, "symbol": it["instrument"], "analysis_direction": "LONG" if p["side"] == "BUY" else "SHORT",
             "setup": {"setup_id": iid, "strategy_id": "MANUAL_USER", "setup_tf": None}, "levels": {},
             "risk": {"lots": p["lots"], "stop_loss": p["sl"], "entry": p["entry"], "modeled_loss": p["risk_net"],
                      "targets": [{"price": p["tp"], "weight": 1.0}] if p["tp"] is not None else []}}
        attempt_id = "MQO-" + uuid.uuid4().hex[:16]
        with self.db.tx() as c:
            c.execute("""INSERT INTO order_attempts(attempt_id, entry_key, decision_id, setup_id, created_at, updated_at, mode, account_key, symbol, side, volume,
                         price_requested, sl, tp, client_tag, state, initiated_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (attempt_id, "MANUAL:" + key, iid, iid, now, now, mode, self.bridge.account_key, it["instrument"], p["side"], p["lots"], p["entry"],
                       p["sl"], p["tp"], ("MQM:" + iid[4:])[:20], "PREPARED", "MANUAL_USER"))
        self._act(key, "SENDING", {"attempt_id": attempt_id})
        if mode == "PAPER":
            res = self.paper.open(attempt_id=attempt_id, decision=d, side=p["side"], lots=p["lots"], sl=p["sl"], targets=d["risk"]["targets"],
                                  exit_policy=None)
        else:
            res = self.gateway._send(attempt_id, d, p["side"], d["risk"], p["tp"])     # the single order_send path (worker + Execution Lock)
        st = res.get("status")
        self._act(key, st if st in ("FILLED", "PARTIAL", "REJECTED", "UNKNOWN") else "REJECTED", dict(res, attempt_id=attempt_id))
        self._intent_state(iid, {"FILLED": "OPEN", "PARTIAL": "OPEN_PARTIAL", "UNKNOWN": "UNKNOWN_RECONCILE"}.get(st, "REJECTED"))
        self.bus.publish("orders", self.gateway.recent_attempts(10))
        return dict(res, attempt_id=attempt_id, idempotency_key=key, mode=mode)

    def _act(self, key: str, state: str, result: dict) -> None:
        self.db.execute("UPDATE manual_actions SET state=?, result=?, updated_at=? WHERE idempotency_key=?", (state, json.dumps(result, default=str), iso(utcnow()), key))

    def _intent_state(self, iid: str, state: str) -> None:
        self.db.execute("UPDATE manual_intents SET state=?, version=version+1, updated_at=? WHERE intent_id=?", (state, iso(utcnow()), iid))

    # ------------------------------------------------------------ position management (scope = positions of THIS intent)
    def _positions(self, iid: str) -> list[dict]:
        return self.db.query("SELECT * FROM managed_positions WHERE decision_id=? AND state='OPEN'", (iid,))

    def manage(self, iid: str, action: str, action_revision: int, *, offset_points: float = 0.0, volume: float | None = None) -> dict:
        """BREAK_EVEN (PRICE_BREAK_EVEN, never worsens SL), PARTIAL_CLOSE (volume step + min remaining), CLOSE (positions of the intent)."""
        if action not in ("BREAK_EVEN", "PARTIAL_CLOSE", "CLOSE"):
            raise PlanError("ACTION_INVALID")
        it = self.intent(iid)
        if not it:
            raise PlanError("INTENT_NOT_FOUND")
        key = f"{it['mode']}|{it['account']}|{it['instrument']}|{iid}|{action}|{int(action_revision)}"
        now = iso(utcnow())
        try:
            self.db.execute("INSERT INTO manual_actions(idempotency_key, intent_id, action, action_revision, state, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                            (key, iid, action, int(action_revision), "PREPARED", now, now))
        except sqlite3.IntegrityError:
            return {"status": "DUPLICATE", "reason": "ACTION_ALREADY_ATTEMPTED"}
        pos = self._positions(iid)
        if not pos:
            self._act(key, "REJECTED", {"reason": "NO_OPEN_POSITION_FOR_INTENT"})
            return {"status": "REJECTED", "reason": "NO_OPEN_POSITION_FOR_INTENT"}
        meta = self.bridge.symbol_info or {}
        point, vmin, vstep = float(meta.get("point") or 0.01), float(meta.get("volume_min") or 0.01), float(meta.get("volume_step") or 0.01)
        out = []
        for mp in pos:
            if mp["mode"] != "PAPER" and self.cfg_store.execution_locked():
                out.append({"ticket": mp["position_ticket"], "status": "BLOCKED", "reason": "EXECUTION_LOCKED"})
                continue
            if mp["mode"] != "PAPER":
                out.append({"ticket": mp["position_ticket"], **self.gateway.manual_modify(mp, action, offset_points=offset_points, volume=volume)})
                continue
            q = self.bridge.quote_status()
            px = (q["bid"] if mp["side"] == "BUY" else q["ask"]) if q else None
            if action == "BREAK_EVEN":
                new_sl = mp["entry_price"] + (offset_points * point if mp["side"] == "BUY" else -offset_points * point)
                better = (mp["sl"] is not None) and ((mp["side"] == "BUY" and mp["sl"] >= new_sl) or (mp["side"] == "SELL" and mp["sl"] <= new_sl))
                if better:
                    out.append({"ticket": mp["position_ticket"], "status": "UNCHANGED", "reason": "SL_ALREADY_BETTER"})
                    continue
                if px is None or (mp["side"] == "BUY" and new_sl >= px) or (mp["side"] == "SELL" and new_sl <= px):
                    out.append({"ticket": mp["position_ticket"], "status": "REJECTED", "reason": "BE_BEYOND_MARKET"})
                    continue
                self.db.execute("UPDATE managed_positions SET sl=? WHERE position_key=?", (new_sl, mp["position_key"]))
                out.append({"ticket": mp["position_ticket"], "status": "DONE", "sl": new_sl, "kind": "PRICE_BREAK_EVEN"})
            else:
                vol = mp["volume_open"] if action == "CLOSE" else _floor_step(float(volume or 0), vstep)
                left = round(mp["volume_open"] - vol, 10)
                if vol <= 0 or (action == "PARTIAL_CLOSE" and (vol < vmin or (0 < left < vmin))):
                    out.append({"ticket": mp["position_ticket"], "status": "REJECTED", "reason": "VOLUME_STEP_OR_MIN_REMAINING"})
                    continue
                if px is None:
                    out.append({"ticket": mp["position_ticket"], "status": "REJECTED", "reason": "NO_QUOTE"})
                    continue
                net = self.paper.close_part(mp, vol, px, "MANUAL_" + action)
                out.append({"ticket": mp["position_ticket"], "status": "DONE", "closed": vol, "remaining": max(0.0, left), "net": net})
        st = "DONE" if any(o["status"] == "DONE" for o in out) else (out[0]["status"] if out else "REJECTED")
        self._act(key, st, {"items": out})
        return {"status": st, "items": out, "idempotency_key": key}

    def reconcile(self) -> dict:
        """UNKNOWN entries: look for the position by client tag in the terminal; never re-send."""
        rows = self.db.query("SELECT * FROM manual_actions WHERE state='UNKNOWN'")
        fixed = []
        for r in rows:
            res = json.loads(r["result"] or "{}")
            att = self.db.one("SELECT client_tag FROM order_attempts WHERE attempt_id=?", (res.get("attempt_id"),))
            pos = next((p for p in (self.bridge.positions or []) if att and p.get("comment") == att["client_tag"]), None)
            if pos:
                self._act(r["idempotency_key"], "FILLED", dict(res, reconciled_ticket=pos["ticket"]))
                fixed.append(r["idempotency_key"])
        return {"unknown": len(rows), "reconciled": fixed, "resend": "NEVER"}


# ------------------------------------------------------------------ historical practice (hidden future, separate journal)
class Drill:
    """Ordered replay of CLOSED bars with the future hidden; orders are resolved only on revealed bars (SL first when both hit in one
    bar - conservative). Separate journal; never mixed with PAPER live-feed or real fills."""

    def __init__(self, bars: list[dict], start: int, spread: float, tick: float, journal_path=None):
        if start < 1 or start >= len(bars):
            raise PlanError("DRILL_START_INVALID")
        self.bars, self.i, self.spread, self.tick = bars, start, spread, tick
        self.positions, self.journal = [], []
        self.id = "DRL-" + hashlib.sha256(f"{bars[0]['open_utc']}|{start}".encode()).hexdigest()[:10]
        self.path = journal_path

    def visible(self) -> list[dict]:
        return self.bars[: self.i + 1]

    def order(self, side: str, sl: float, tp: float, lots: float) -> dict:
        c = self.bars[self.i]["c"]
        entry = c + (self.spread if side == "BUY" else 0.0)
        if (side == "BUY" and not sl < entry < tp) or (side == "SELL" and not tp < entry < sl):
            raise PlanError("SL_TP_WRONG_SIDE")
        p = {"side": side, "entry": entry, "sl": sl, "tp": tp, "lots": lots, "opened_bar": self.bars[self.i]["open_utc"], "state": "OPEN"}
        self.positions.append(p)
        self._log({"event": "OPEN", **p})
        return p

    def step(self, n: int = 1) -> dict:
        for _ in range(n):
            if self.i + 1 >= len(self.bars):
                break
            self.i += 1
            b = self.bars[self.i]
            for p in self.positions:
                if p["state"] != "OPEN":
                    continue
                lo_x, hi_x = (b["l"], b["h"]) if p["side"] == "BUY" else (b["l"] + self.spread, b["h"] + self.spread)
                hit_sl = lo_x <= p["sl"] if p["side"] == "BUY" else hi_x >= p["sl"]
                hit_tp = hi_x >= p["tp"] if p["side"] == "BUY" else lo_x <= p["tp"]
                if hit_sl or hit_tp:
                    p["state"] = "SL" if hit_sl else "TP"
                    p["ambiguous"] = bool(hit_sl and hit_tp)
                    p["exit"] = p["sl"] if hit_sl else p["tp"]
                    p["closed_bar"] = b["open_utc"]
                    self._log({"event": "CLOSE", **p})
        return {"bar": self.bars[self.i], "index": self.i, "positions": self.positions}

    def _log(self, e: dict) -> None:
        self.journal.append(e)
        if self.path:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(dict(e, drill_id=self.id)) + "\n")
