"""SCALPING / HEDGING runtime service (PMW-SH-1). One loop, two strategies, one shared analysis snapshot.

Per new CLOSED M1 bar: snapshot -> setup per strategy -> signal persisted (READY / WAIT / NO_TRADE / INVALIDATED / EXPIRED)
-> coordinator -> shared risk engine -> plan (frozen with the config hash) -> execution in the CURRENT mode (SIGNALS: nothing;
PAPER: simulated; AUTO_DEMO: terminal; AUTO_LIVE: terminal, new plans only after a passed validation on the client's history).
Every tick (quote): open plans are managed by their state machines - partials, BE after the CONFIRMED TP2, runner, time limit,
hedge decision / unwind / basket exits - from CONFIRMED fills only. Terminal plans (AUTO_DEMO / AUTO_LIVE) are reconciled with the
terminal on every tick (broker-side SL/TP, external closes, unknown outcomes) and after a restart / reconnect.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone

from .. import paths
from . import config as C
from . import context as CX
from . import models as MR
from . import risk as RK
from . import setup as SU
from . import tpmodel as TM
from .coordinator import arbitrate
from .executor import SHExecutor
from .hedge_fsm import Basket, HedgeConfig
from .lifecycle import Leg, Position
from .store import SHStore
from .units import SymbolSpec, UnitError

STRATEGIES = ("SCALPING", "HEDGING")
NOT_SH_GATE_REASONS = ("EXECUTION_MODE_SIGNALS", "RISK_LIMITS_NOT_CONFIGURED")
MM = {"NETTING": 0, "EXCHANGE": 1, "HEDGING": 2}


def day_start(now: float) -> float:
    d = datetime.fromtimestamp(now, tz=timezone.utc)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()


class SHService:
    def __init__(self, cfg_store, bridge, db, bus, log, modes, *, clock=time.time, terminal=None):
        self.cfg_store, self.bridge, self.bus, self.log, self.modes = cfg_store, bridge, bus, log, modes
        self.store = SHStore(db)
        self.clock = clock
        self._terminal = terminal                     # tests inject a direct callable; runtime uses the MT5 worker
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.RLock()
        self.last_bar_key = None
        self.recovered_epoch = None
        self.last_eval: dict = {}
        self.last_saved: dict = {}
        self.listeners: list = []                  # fn(evals, inst=, symbol=, snap=, now=) after each cycle - read-only observers
        self.snapshot: dict | None = None
        self.snap_cache: dict = {}                    # per (instrument, session epoch): no M5 analysis carried across a switch
        self.state: dict = {"status": "STARTING", "updated_at": None, "warnings": []}

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="sh-strategies", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 - a failing cycle never stops management of the next tick
                self._set("ERROR_RECOVERY", f"{type(exc).__name__}: {exc}"[:300])
                self.log.error("SH", "TICK", f"{type(exc).__name__}: {exc}"[:300])
            self._stop.wait(1.0)

    def _set(self, status: str, reason: str | None = None, **kw) -> None:
        self.state.update(status=status, reason=reason, updated_at=self.clock(), **kw)
        if self.bus is not None:
            self.bus.publish("sh", {k: v for k, v in self.state.items() if k != "snapshot"})

    # ------------------------------------------------------------------ inputs
    def instrument(self) -> str:
        cfg = self.cfg_store.get()
        return getattr(getattr(cfg, "assets", None), "active", None) or "XAUUSD"

    def terminal(self):
        if self._terminal is not None:
            return self._terminal
        from ..mt5.worker import PRIO_TRADE

        def run(fn):
            return self.bridge.raw_call(fn, PRIO_TRADE, timeout=float(self.cfg_store.get().execution.order_timeout_seconds))
        return run

    def mode(self) -> str:
        return self.gate()["mode"]

    def gate(self) -> dict:
        """Execution mode + reasons that forbid NEW plans now, from the shared ModeManager: the user's STOP (kill switch), the
        a missing / unconfirmed / wrong-type account in AUTO_DEMO / AUTO_LIVE, SH not being the primary path (O1). Open plans
        are always managed. Not applied:
        SIGNALS (never opens plans) and the legacy RiskLimits of the S01-S12 engine (SH enforces its own limits, sh/risk.py)."""
        try:
            g = self.modes.gate(self.bridge.account_key, path="SH")
        except Exception as exc:  # noqa: BLE001 - unknown gate state = no new entries
            return {"mode": "SIGNALS", "entry_block": [f"MODE_GATE_ERROR:{type(exc).__name__}"]}
        return {"mode": g["mode"], "entry_block": [r for r in g.get("reason_codes") or [] if r not in NOT_SH_GATE_REASONS]}

    def account(self) -> dict:
        a = self.bridge.account_status() or {}
        price = (self.bridge.quote_status() or {}).get("ask")
        mpl = None
        if price:
            try:
                mpl = self.bridge.calc_margin("BUY", 1.0, float(price))
            except Exception:  # noqa: BLE001
                mpl = None
        return {"equity": a.get("equity"), "margin": a.get("margin"), "margin_free": a.get("free_margin"), "margin_mode": a.get("margin_mode"),
                "trade_mode": a.get("trade_mode"), "margin_per_lot": mpl, "currency": a.get("currency")}

    def spec(self, acc: dict) -> SymbolSpec:
        info = self.bridge.symbol_info or {}
        return SymbolSpec.from_mt5(info, {"margin_mode": MM.get(str(acc.get("margin_mode")))})

    def quote(self, now: float) -> dict | None:
        q = self.bridge.quote_status()
        if not q or q.get("bid") is None:
            return None
        age = q.get("age_seconds")
        return {"bid": float(q["bid"]), "ask": float(q["ask"]), "spread": float(q["ask"]) - float(q["bid"]), "age_s": age,
                "time": now - (age if age is not None else 1e9)}

    def executor(self, spec: SymbolSpec) -> SHExecutor:
        cfg = self.cfg_store.get()
        sh = C.load()
        acc = self.bridge.account_status() or {}
        return SHExecutor(self.store, terminal=self.terminal(), account_key=self.bridge.account_key or "PAPER", magic=sh["magic_number"],
                          comment_prefix=sh["comment_prefix"], deviation_points=int(cfg.execution.deviation_points),
                          is_demo=lambda: acc.get("trade_mode") == "DEMO", is_live=lambda: acc.get("trade_mode") == "REAL",
                          live_check=lambda strategy: self.live_validation(self.instrument(), strategy),
                          symbol_info=self.bridge.symbol_info or {})

    # ------------------------------------------------------------------ main step
    def tick(self) -> None:
        with self._lock:                                  # the API (manual close) and the loop never act on a plan concurrently
            self._tick()

    def close_plan(self, plan_id: str, reason: str = "MANUAL_CLOSE") -> dict:
        """Explicit close of one SH plan (all legs) through its own state machine and executor - idempotent."""
        with self._lock:
            row = self.store.plan(plan_id)
            if not row or row["state"] in ("CLOSED", "REJECTED", "ERROR_CLOSED"):
                return {"ok": False, "error": "PLAN_NOT_OPEN"}
            obj = row.get("fsm_obj")
            if obj is None:
                return {"ok": False, "error": "PLAN_WITHOUT_POSITION"}
            now = self.clock()
            acc = self.account()
            spec = self.spec(acc)
            q = self.quote(now)
            if not q:
                return {"ok": False, "error": "NO_QUOTE"}
            if isinstance(obj, Basket):
                acts = obj._exit_all(now, reason)
            else:
                acts = [{"action_id": f"{plan_id}:CLOSE_RUNNER:MANUAL", "plan_id": plan_id, "kind": "CLOSE_RUNNER", "volume": obj.remaining,
                         "reason": reason}] if obj.remaining > 1e-9 else []
            self.store.event(plan_id, "MANUAL_CLOSE_REQUEST", {"reason": reason}, now)
            self.process(self.executor(spec), row, obj, acts, spec, q, now)
            st = self.store.plan(plan_id)
            return {"ok": st["state"] == "CLOSED", "state": st["state"]}

    def _tick(self) -> None:
        now = self.clock()
        inst = self.instrument()
        shc = C.load()
        if inst not in (shc.get("instruments") or {}):
            self._set("UNSUPPORTED_INSTRUMENT", f"brak profilu SH dla {inst}")
            return
        acc = self.account()
        try:
            spec = self.spec(acc)
        except UnitError as exc:
            self._set("NO_SYMBOL", str(exc))
            return
        q = self.quote(now)
        gate = self.gate()
        mode = gate["mode"]
        ex = self.executor(spec)
        epoch = getattr(self.bridge, "session_epoch", None)
        if self.recovered_epoch != epoch:
            self.recover(ex, spec, now)
            self.recovered_epoch = epoch
        if q:
            self.manage(ex, spec, q, now, shc)
        self.store.expire_signals(now)
        bars = {tf: [b for b in self.bridge.bars(tf, 400, include_forming=False) if b.get("open_utc")] for tf in ("M1", "M5", "M15", "H1")}
        if not bars["M1"]:
            self._set("NO_DATA", "brak zamkniętych świec M1", mode=mode, instrument=inst)
            return
        key = (bars["M1"][-1]["open_utc"], epoch, inst)
        if key != self.last_bar_key:
            self.last_bar_key = key
            self.cycle(inst, bars, q, spec, acc, mode, now, shc, ex, entry_block=gate["entry_block"])
        self._set("RUNNING", None, mode=mode, entry_block=gate["entry_block"], instrument=inst, symbol=spec.symbol, account_margin_mode=acc.get("margin_mode"),
                  open_plans=[self.plan_view(p, q) for p in self.store.open_plans(spec.symbol)], last_eval=self.last_eval,
                  config_hash=shc["_hash"])

    # ------------------------------------------------------------------ evaluation cycle (new closed M1)
    def cycle(self, inst, bars, q, spec, acc, mode, now, shc, ex, entry_block: list | None = None) -> dict:
        r = shc["risk"]
        ic = shc["instruments"][inst]
        snap = CX.snapshot(bars, q, tick=spec.tick_size, now=now, cfg={"max_bar_age_s": r["max_bar_age_s"], "max_quote_age_s": r["max_quote_age_s"],
                                                                      "max_spread_usd": ic.get("max_spread_usd")}, cache=self.snap_cache.setdefault((inst, getattr(self.bridge, "session_epoch", None)), {}))
        self.snapshot = snap
        mx = MR.matrix(None, inst)
        evals = {}
        for strat in STRATEGIES:
            prof = C.profile(shc, inst, strat)
            su = SU.evaluate(strat, inst, snap, spec, prof, now=now, models=mx["rows"], config_hash=shc["_hash"], m1=bars["M1"][-20:])
            if su["status"] == "READY" and TM.status(inst, strat).get("status") == "READY":
                pr = TM.predict(inst, strat, TM.features(su, snap))
                su = SU.evaluate(strat, inst, snap, spec, prof, now=now, tp_prob=pr, models=mx["rows"], config_hash=shc["_hash"], m1=bars["M1"][-20:])
            evals[strat] = su
        ready = [s for s in evals.values() if s["status"] == "READY"]
        opens = self.store.open_plans(spec.symbol)
        foreign = self.foreign_positions(spec.symbol, shc["magic_number"]) if mode in RK.REAL_MODES else 0
        coord = {d["strategy"]: d for d in arbitrate(ready, open_plans=[{"strategy": p["strategy"], "symbol": p["symbol"], "side": p["side"],
                                                                          "state": p["state"]} for p in opens],
                                                   foreign_positions=foreign, cfg=shc, symbol=spec.symbol)}
        for strat, su in evals.items():
            risk = None
            if strat in coord:
                su["coordination"] = coord[strat]
                if coord[strat]["decision"] == "PROCEED":
                    rstate = self.risk_state(spec.symbol, strat, now, foreign)
                    if mode == "AUTO_LIVE":
                        rstate["live_validation"] = self.live_validation(inst, strat)
                    risk = RK.evaluate(setup=su, spec=spec, prof=C.profile(shc, inst, strat), cfg=shc, inst=inst, account=acc,
                                       state=rstate, exec_mode=mode, now=now, quote=q)
                    su["risk"] = risk
                else:
                    su["status_reason"] = "koordynator: " + coord[strat]["reason"]
            if risk and risk["status"] == "PASS" and entry_block:
                su["entry_block"] = list(entry_block)
                su["status_reason"] = "nowe wejścia zablokowane: " + ", ".join(entry_block)
            self.persist_signal(su, risk, coord.get(strat), now)
            self.last_eval[strat] = su                                     # full setup (checklist, levels, models) for the panel
            if risk and risk["status"] == "PASS" and mode in ("PAPER",) + RK.REAL_MODES and not entry_block:
                self.open_plan(ex, su, risk, spec, q, mode, now, shc, inst, snap)
        for fn in list(self.listeners):
            try:
                fn(evals, inst=inst, symbol=spec.symbol, snap=snap, now=now)
            except Exception:  # noqa: BLE001 - an observer never stops the cycle
                logging.getLogger("masterquo.sh").exception("sh listener failed")
        return evals

    def persist_signal(self, su, risk, coord, now) -> None:
        k = su["strategy"]
        sig = (su.get("status"), su.get("status_reason"), su.get("side"))
        if su["status"] == "READY" or self.last_saved.get(k) != sig:
            self.store.save_signal(su, risk=risk, coordination=coord, now=now)
            self.last_saved[k] = sig

    def risk_state(self, symbol: str, strat: str, now: float, foreign: int) -> dict:
        opens = self.store.open_plans(symbol)
        plans = []
        for p in opens:
            o = p.get("fsm_obj")
            if isinstance(o, Basket):
                plans.append({"plan_id": p["plan_id"], "strategy": p["strategy"], "symbol": symbol, "side": p["side"], "state": p["state"],
                              "volume": o.primary.remaining, "hedge_volume": o.hedge.volume if o.hedge and o.hedge.status == "OPEN" else 0.0})
            else:
                plans.append({"plan_id": p["plan_id"], "strategy": p["strategy"], "symbol": symbol, "side": p["side"], "state": p["state"],
                              "volume": o.remaining if o else (p["plan"].get("risk") or {}).get("volume", 0.0), "hedge_volume": 0.0})
        r = C.load()["risk"]
        recent = [s for s in self.store.recent_signals(since=now - 60 * r["duplicate_window_minutes"])
                  if s["status"] == "READY" and self.store.db.one("SELECT 1 FROM sh_plans WHERE signal_id=?", (s["signal_id"],))]
        return {"open_plans": plans, "daily_realized_money": self.store.realized_since(day_start(now)),
                "last_close_at": self.store.last_close_at(symbol), "recent_signals": recent, "foreign_positions": foreign,
                "netting_reduce_validation": self.netting_reduce_validation(self.instrument()) if strat == "HEDGING" else None}

    def foreign_positions(self, symbol: str, magic: int) -> int:
        try:
            ps = self.terminal()(lambda m: m.positions_get(symbol=symbol)) or ()
        except Exception:  # noqa: BLE001
            return 0
        return sum(1 for p in ps if int(p.magic) != int(magic))

    # ------------------------------------------------------------------ plan opening
    def open_plan(self, ex, su, risk, spec, q, mode, now, shc, inst, snap) -> dict:
        pid = "PL-" + su["signal_id"][3:]
        prof = C.profile(shc, inst, su["strategy"])
        plan = {"plan_id": pid, "signal_id": su["signal_id"], "strategy": su["strategy"], "instrument": inst, "symbol": spec.symbol,
                "side": su["side"], "exec_mode": mode, "account_key": self.bridge.account_key, "config_hash": shc["_hash"],
                "setup": {k: su.get(k) for k in ("entry_ref", "sl", "tps", "shares", "be", "invalidation", "entry_zone", "mode", "costs", "net_rr",
                                                 "horizon_minutes", "position_max_minutes", "valid_until", "model_mode", "probability", "score")},
                "risk": {k: risk.get(k) for k in ("volume", "legs", "shares_used", "risk_money", "risk_pct", "money_per_price_per_lot",
                                                  "basket_loss_limit_money", "loss_per_lot")},
                "profile": {k: v for k, v in prof.items() if k != "_instrument"}, "instrument_profile": prof["_instrument"],
                "atr_m5": (snap.get("vol") or {}).get("atr_m5"), "created_at": now}
        if not self.store.create_plan(plan, now):
            return {"status": "DUPLICATE"}
        tp3 = su["tps"][-1]["price"]
        res = ex.open(plan, role="P", side=su["side"], volume=risk["volume"], sl=su["sl"], tp=tp3, mode=mode, quote=q, tag="P",
                      slippage=float(prof["_instrument"].get("slippage_usd") or 0) if mode == "PAPER" else 0.0, now=now)
        self.store.event(pid, "OPEN_RESULT", res, now)
        if res["status"] not in ("FILLED", "PARTIAL"):
            st = "ENTRY_UNKNOWN" if res["status"] == "UNKNOWN" else "REJECTED"
            self.store.update_plan(pid, state=st, result={"reason": res.get("reason"), "retcode": res.get("retcode")}, now=now)
            self.log.warn("SH", "ENTRY_" + res["status"], f"{su['strategy']} {su['side']}: {res.get('reason')}")
            return res
        return self.bind_fill(ex, plan, res, spec, q, mode, now)

    def bind_fill(self, ex, plan, res, spec, q, mode, now) -> dict:
        """Targets from the ACTUAL fill price (snapped to ticks, never closer than requested); split of the ACTUAL filled volume."""
        pid, side, su, prof = plan["plan_id"], plan["side"], plan["setup"], plan["profile"]
        fill, vol = float(res["price"]), float(res["volume"])
        sl = float(su["sl"])
        shares = list((plan["risk"].get("shares_used") or {}).get("shares") or prof["shares"])
        dists = [t["distance_requested"] for t in su["tps"]][:len(shares)]
        sp = spec.split(vol, shares)
        if sp["status"] != "OK" and prof.get("shares_fallback_two"):
            shares, dists = list(prof["shares_fallback_two"]), [t["distance_requested"] for t in su["tps"]][:2]
            sp = spec.split(vol, shares)
        wrong_side = (fill <= sl) if side == "BUY" else (fill >= sl)
        if sp["status"] != "OK" or wrong_side:
            why = "wykonanie po złej stronie SL (poślizg)" if wrong_side else f"podział wykonanego wolumenu {vol} niewykonalny: {sp.get('reason')}"
            pos = Position(pid, side, fill, vol, sl, [Leg("TP3", fill, vol)])
            self.store.update_plan(pid, state="OPEN", fsm=pos, primary_ticket=res.get("ticket"), now=now)
            act = {"action_id": f"{pid}:CLOSE_RUNNER:ENTRY_ABORT", "plan_id": pid, "kind": "CLOSE_RUNNER", "volume": vol, "reason": why}
            self.store.event(pid, "ENTRY_ABORT", {"reason": why}, now)
            self.process(ex, self.store.plan(pid), pos, [act], spec, q, now)
            return {"status": "ABORTED", "reason": why}
        names = ["TP1", "TP2", "TP3"][:len(shares)] if len(shares) == 3 else ["TP1", "TP2"]
        legs = []
        for name, d, v in zip(names, dists, sp["legs"]):
            t = spec.target(fill, side, d)
            legs.append(Leg(name, t["price"], v))
        be_off = float((su.get("be") or {}).get("offset_price") or 0.0)
        pos = Position(pid, side, fill, vol, sl, legs, be_rule="ENTRY_PLUS_COSTS" if be_off else "ENTRY", be_offset=be_off,
                       be_reject_policy=prof.get("be_reject_policy", "RETRY_THEN_CLOSE"))
        obj = pos
        if plan["strategy"] == "HEDGING":
            h = prof["hedge"]
            sl_dist = abs(fill - sl)
            cfg = HedgeConfig(trigger_adverse_usd=h["trigger_fraction_of_sl"] * sl_dist, ratio=h["ratio"], max_ratio=h["max_ratio"],
                              max_activations=h["max_activations"], max_hedge_minutes=h["max_hedge_minutes"],
                              unwind_recovery_usd=h["unwind_recovery_atr_m5"] * float(plan.get("atr_m5") or sl_dist),
                              basket_loss_limit_money=float(plan["risk"].get("basket_loss_limit_money") or 0.0),
                              basket_max_minutes=prof["position_max_minutes"])
            obj = Basket(pid, pos, cfg, spec.money_per_price(1.0), opened_at=now)
        self.store.update_plan(pid, state=obj.state, fsm=obj, primary_ticket=res.get("ticket"), now=now)
        self.store.event(pid, "BOUND", {"fill": fill, "volume": vol, "legs": [vars(x) for x in legs], "split": sp,
                                        "rounding": [{"leg": lg.name, "requested": d, "actual": round(abs(lg.price - fill), 10)} for lg, d in zip(legs, dists)]}, now)
        # broker-side TP = last target from the actual fill (backstop if the bot is offline)
        last = legs[-1]
        acts = [{"action_id": f"{pid}:MODIFY_TP:FILL", "plan_id": pid, "kind": "MODIFY_TP", "tp": last.price}]
        self.process(ex, self.store.plan(pid), obj, acts, spec, q, now)
        return {"status": "OPEN", "plan_id": pid, "fill": fill, "volume": vol}

    # ------------------------------------------------------------------ management (every tick)
    def manage(self, ex, spec, q, now, shc) -> None:
        for row in self.store.open_plans(spec.symbol):
            obj = row.get("fsm_obj")
            if obj is None:
                continue
            mode = row["exec_mode"]
            if mode in RK.REAL_MODES:
                self.reconcile(ex, row, obj, spec, now)
            elif mode == "PAPER":
                self.paper_stops(ex, row, obj, spec, q, now)
            acts = []
            if isinstance(obj, Basket):
                inval = row["plan"]["setup"].get("invalidation")
                p = obj.primary
                sv = True if inval is None else ((q["bid"] > inval) if p.side == "BUY" else (q["ask"] < inval))
                if obj.state == "PRIMARY_OPEN" and p.state in ("OPEN", "TP1_DONE") and obj.activations < obj.cfg.max_activations:
                    acts += self.hedge_step(row, obj, spec, q, now, sv)
                acts += obj.on_quote(now, q["bid"], q["ask"], structure_valid=sv)
            else:
                acts += obj.on_quote(q["bid"], q["ask"])
                maxm = float(row["plan"]["profile"].get("position_max_minutes") or 0)
                if maxm and now - row["created_at"] >= 60 * maxm and obj.remaining > 1e-9:
                    acts.append({"action_id": f"{row['plan_id']}:CLOSE_RUNNER:TIME", "plan_id": row["plan_id"], "kind": "CLOSE_RUNNER",
                                 "volume": obj.remaining, "reason": "TIME_LIMIT"})
            self.process(ex, row, obj, acts, spec, q, now)

    def hedge_step(self, row, b: Basket, spec, q, now, structure_valid) -> list[dict]:
        prof = row["plan"]["profile"]
        h = prof["hedge"]
        acc = self.account()
        ok, why = True, ""
        if acc.get("margin_mode") != "HEDGING":                 # PAPER mirrors the connected account type too
            ok, why = False, f"rachunek {acc.get('margin_mode')} nie pozwala na pozycję przeciwną"
        hv = b.hedge_volume(spec.floor_volume)
        if hv < spec.volume_min - 1e-9:
            ok, why = False, f"wolumen hedge {hv} < min lot {spec.volume_min}"
        mpl = acc.get("margin_per_lot")
        eq = float(acc.get("equity") or 0)
        lim = C.load()["risk"]["max_margin_use_pct"]
        if ok and mpl and eq and float(acc.get("margin") or 0) + mpl * hv > eq * lim / 100.0:
            ok, why = False, "brak miejsca w limicie depozytu"
        ic = row["plan"]["instrument_profile"]
        cost = q["spread"] + 2 * float(ic.get("slippage_usd") or 0)
        cap = float(h.get("max_hedge_cost_fraction_of_sl", 0.25)) * abs(b.primary.entry - b.primary.sl)
        dec = b.hedge_decision(q["bid"], q["ask"], structure_valid=structure_valid, risk_ok=ok, risk_reason=why,
                               hedge_cost_price=cost, reduce_cost_price=cap)
        if dec["decision"] == "HEDGE":
            v = self.validated_variant(row["instrument"])
            if v and v["best"] != "HEDGE":
                dec = {"decision": "REDUCE" if v["best"] == "REDUCE" else "HOLD",
                       "reason": f"walidacja replay: wariant {v['best']} lepszy niż HEDGE ({v['source']})"}
        key = f"{dec['decision']}|{dec['reason'][:40]}"
        if dec["decision"] != "HOLD" and self.last_saved.get(row["plan_id"]) != key:
            self.store.event(row["plan_id"], "HEDGE_DECISION", dec, now)
            self.last_saved[row["plan_id"]] = key
        if dec["decision"] == "HEDGE":
            return b.request_hedge(now, hv, dec["reason"])
        if dec["decision"] == "EXIT":
            return b._exit_all(now, dec["reason"])
        if dec["decision"] == "REDUCE":
            vol = spec.floor_volume(b.primary.remaining * float(h.get("reduce_fraction", 0.5)))
            b.activations += 1                                  # one decision per activation budget: no repeated reductions
            b._go("PRIMARY_OPEN", "redukcja zamiast hedge: " + dec["reason"], now)
            if vol >= spec.volume_min and b.primary.remaining - vol >= spec.volume_min - 1e-9:
                return [{"action_id": f"{row['plan_id']}:REDUCE:R{b.activations}", "plan_id": row["plan_id"], "kind": "CLOSE_PRIMARY_PART",
                         "volume": vol, "reason": dec["reason"]}]
        return []

    @staticmethod
    def netting_reduce_validation(inst: str) -> dict:
        """O3: HEDGING on a NETTING account (hedge event -> REDUCE) only after the REDUCE variant passed the replay validation on
        the client's own history: report on REAL_USER_DATA, n >= 30 cycles, positive net expectancy (R, after costs)."""
        p = paths.data_dir() / "sh" / "validation" / f"{inst}_HEDGING.json"
        if not p.exists():
            return {"ok": False, "reason": "brak raportu walidacji replay HEDGING (panel Trening → walidacja SCALPING/HEDGING)"}
        try:
            v = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "reason": f"raport walidacji nieczytelny ({type(exc).__name__})"}
        kind = (v.get("dataset") or {}).get("data_kind")
        red = (v.get("variants") or {}).get("REDUCE") or {}
        n, e = int(red.get("n") or 0), red.get("expectancy")
        if kind != "REAL_USER_DATA":
            return {"ok": False, "reason": f"walidacja na danych {kind or 'nieznanego pochodzenia'} – wymagana historia klienta (REAL_USER_DATA)"}
        if n < 30:
            return {"ok": False, "reason": f"wariant REDUCE: {n} cykli < 30"}
        if e is None or e <= 0:
            return {"ok": False, "reason": f"wariant REDUCE: oczekiwany wynik {e} R ≤ 0"}
        return {"ok": True, "source": f"walidacja {v.get('created_at')}: n={n}, wynik oczekiwany {e:.3f} R"}

    @staticmethod
    def live_validation(inst: str, strategy: str | None) -> dict:
        """AUTO_LIVE entries of an SH strategy (user decision 1.24, replaces the unconditional refusal): only after its replay validation
        on the client's own history passed - report on REAL_USER_DATA, known commission, n >= 30 cycles, positive net expectancy (R, after
        costs). Without it the entry is refused with this reason (shown in the panel); management of open plans is not affected."""
        if strategy not in ("SCALPING", "HEDGING"):
            return {"ok": False, "reason": f"nieznana strategia SH: {strategy}"}
        p = paths.data_dir() / "sh" / "validation" / f"{inst}_{strategy}.json"
        if not p.exists():
            return {"ok": False, "reason": f"brak raportu walidacji {strategy} {inst} na danych z terminala (30_SH_WALIDACJA.bat)"}
        try:
            v = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "reason": f"raport walidacji nieczytelny ({type(exc).__name__})"}
        kind = v.get("data_kind") or (v.get("dataset") or {}).get("data_kind")
        if kind != "REAL_USER_DATA":
            return {"ok": False, "reason": f"walidacja na danych {kind or 'nieznanego pochodzenia'} – wymagana historia klienta (REAL_USER_DATA)"}
        if v.get("commission_source") == "NIEZNANA":
            return {"ok": False, "reason": "prowizja nieznana w walidacji – wynik zawyżony; ustaw prowizję i powtórz walidację"}
        m = v.get("metrics") or {}
        n, e = int(m.get("n") or 0), m.get("expectancy")
        if n < 30:
            return {"ok": False, "reason": f"{strategy}: {n} cykli < 30"}
        if e is None or e <= 0:
            return {"ok": False, "reason": f"{strategy}: oczekiwany wynik {e} R ≤ 0 po kosztach"}
        return {"ok": True, "source": f"walidacja {v.get('created_at')}: n={n}, wynik oczekiwany {e:.3f} R po kosztach"}

    @staticmethod
    def validated_variant(inst: str) -> dict | None:
        p = paths.data_dir() / "sh" / "validation" / f"{inst}_HEDGING.json"
        if not p.exists():
            return None
        try:
            v = json.loads(p.read_text(encoding="utf-8"))
            comp = v.get("variants") or {}
            ok = {k: x for k, x in comp.items() if (x.get("n") or 0) >= 30}
            if not ok:
                return None
            best = max(ok, key=lambda k: ok[k].get("expectancy") or -1e9)
            return {"best": best, "source": f"walidacja {v.get('created_at')}"}
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------ action execution + feedback into the state machines
    def process(self, ex, row, obj, acts, spec, q, now) -> None:
        if row is None:
            return
        pid, mode = row["plan_id"], row["exec_mode"]
        slip = float(row["plan"]["instrument_profile"].get("slippage_usd") or 0) if mode == "PAPER" else 0.0
        b = obj if isinstance(obj, Basket) else None
        pos = b.primary if b else obj
        queue = list(acts)
        guard = 0
        while queue and guard < 50:
            guard += 1
            a = queue.pop(0)
            k = a["kind"]
            if k == "OPEN_HEDGE":
                # broker-side protection of the hedge leg mirrors the primary's broker stops: both legs close at the same levels
                hsl = pos.legs[-1].price if pos.legs else 0.0
                res = ex.open(row["plan"], role="H", side=a["side"], volume=a["volume"], sl=hsl, tp=pos.sl, mode=mode, quote=q,
                              tag=a["action_id"].split(":")[-1], slippage=slip, now=now)
                ok = res["status"] in ("FILLED", "PARTIAL")
                if res["status"] in ("UNKNOWN", "BLOCKED") and not ok:
                    self.store.event(pid, "HEDGE_" + res["status"], res, now)
                queue += b.on_hedge_result(a["action_id"] + ":r", now, ok, float(res.get("volume") or 0), float(res.get("price") or 0),
                                           "PARTIAL" if res["status"] == "PARTIAL" else str(res.get("reason") or res["status"]))
                if ok:
                    row["hedge_ticket"] = res.get("ticket")
                    self.store.update_plan(pid, hedge_ticket=res.get("ticket"), now=now)
                continue
            if k == "CLOSE_HEDGE":
                hs = b.hedge.side if b and b.hedge else ("SELL" if pos.side == "BUY" else "BUY")
                res = ex.perform(row["plan"], a, mode=mode, quote=q, ticket=row.get("hedge_ticket"), side_of_position=hs, slippage=slip, now=now)
                if res["status"] in ("FILLED", "PARTIAL"):
                    b.hedge.status = "OPEN"
                    queue += b.on_hedge_closed(a["action_id"] + ":r", now, float(res["volume"]), float(res["price"]))
                elif res["status"] == "REJECTED":
                    b.hedge.status = "OPEN"
                    queue += b.on_hedge_closed(a["action_id"] + f":rej{now}", now, 0, 0, ok=False, reason=str(res.get("reason")))
                continue
            res = ex.perform(row["plan"], a, mode=mode, quote=q, ticket=row.get("primary_ticket"), side_of_position=pos.side, slippage=slip, now=now)
            st = res["status"]
            done = st in ("FILLED", "PARTIAL", "DONE")
            if k == "MODIFY_TP":
                continue
            if k == "MODIFY_SL":
                if st in ("DONE", "REJECTED"):
                    queue += pos.on_sl_result(a["action_id"] + ":r", st == "DONE", q["bid"], q["ask"], str(res.get("reason") or ""))
                elif st == "BLOCKED":
                    queue += pos.on_sl_result(a["action_id"] + ":b", False, q["bid"], q["ask"], res["reason"])
                continue
            if k == "CLOSE_PARTIAL":
                leg = a["action_id"].split(":")[-1]
                if done:
                    ev = a["action_id"] + ":r"
                    queue += (b.on_primary_fill(ev, now, leg, float(res["volume"]), float(res["price"])) if b
                              else pos.on_fill(ev, leg, float(res["volume"]), float(res["price"])))
                elif st in ("REJECTED", "BLOCKED"):
                    pos.on_partial_rejected(a["action_id"] + f":rej{now}", leg, str(res.get("reason")))
                continue
            if k in ("CLOSE_RUNNER", "CLOSE_PRIMARY", "CLOSE_PRIMARY_PART"):
                if done:
                    ev = a["action_id"] + ":r"
                    reason = a.get("reason") or k
                    if k == "CLOSE_RUNNER" and reason == "TP3":
                        queue += (b.on_primary_fill(ev, now, "TP3", float(res["volume"]), float(res["price"])) if b
                                  else pos.on_fill(ev, "TP3", float(res["volume"]), float(res["price"])))
                    else:
                        queue += (b.on_primary_closed(ev, now, float(res["volume"]), float(res["price"]), reason[:40]) if b
                                  else pos.on_closed(ev, float(res["volume"]), float(res["price"]), reason[:40]))
                elif st in ("REJECTED", "BLOCKED"):
                    pos.issued.discard(a["action_id"])                  # allow the same exit to be requested again
                    if b:
                        b.issued.discard(a["action_id"])
                        if b.state == "EXIT_PENDING":
                            b.state = "HEDGED" if b.hedge and b.hedge.status in ("OPEN", "CLOSING") else "PRIMARY_OPEN"
                continue
        self.finish(row, obj, spec, now)

    def finish(self, row, obj, spec, now) -> None:
        pid = row["plan_id"]
        b = obj if isinstance(obj, Basket) else None
        pos = b.primary if b else obj
        closed = (b.state == "CLOSED") if b else (pos.state == "CLOSED")
        if b and pos.state == "CLOSED" and not (b.hedge and b.hedge.status in ("OPEN", "CLOSING")) and b.state != "CLOSED":
            b._go("CLOSED", "wszystkie nogi zamknięte", now)
            closed = True
        state = b.state if b else pos.state
        res = None
        if closed:
            res = self.cycle_result(row, obj, spec)
        self.store.update_plan(pid, state="CLOSED" if closed else state, fsm=obj, result=res, now=now)

    def cycle_result(self, row, obj, spec) -> dict:
        """Whole-cycle accounting: one plan = one result (partials are not separate wins). Spread/slippage are inside the fill
        prices; commission is added when known."""
        b = obj if isinstance(obj, Basket) else None
        pos = b.primary if b else obj
        mpp = spec.money_per_price(1.0)
        comm = row["plan"]["instrument_profile"].get("commission_per_lot_side")
        vols = pos.volume
        hedge_vol = 0.0
        if b:
            for e in self.store.events(row["plan_id"]):
                if e["kind"] == "ACTION" and e["payload"]["action"]["kind"] == "OPEN_H" and e["payload"]["result"].get("volume"):
                    hedge_vol += float(e["payload"]["result"]["volume"])
        comm_money = (2 * float(comm) * (vols + hedge_vol)) if comm is not None else None
        prim = sum(r["volume"] * r["move"] for r in pos.realized) * mpp
        hedge = b.hedge_realized_money if b else 0.0
        gross = prim + hedge
        sl_risk = abs(pos.entry - pos.sl) * pos.volume * mpp
        return {"primary_money": round(prim, 2), "hedge_money": round(hedge, 2), "gross_money": round(gross, 2),
                "commission_money": None if comm_money is None else round(comm_money, 2),
                "net_money": round(gross - (comm_money or 0.0), 2), "commission_known": comm is not None,
                "r_multiple": round((gross - (comm_money or 0.0)) / sl_risk, 3) if sl_risk else None,
                "legs": [vars(x) for x in pos.legs], "realized": pos.realized, "hedge_activations": b.activations if b else 0}

    # ------------------------------------------------------------------ PAPER: broker-side stops are simulated
    def paper_stops(self, ex, row, obj, spec, q, now) -> None:
        b = obj if isinstance(obj, Basket) else None
        pos = b.primary if b else obj
        if pos.remaining <= 1e-9:
            return
        px = q["bid"] if pos.side == "BUY" else q["ask"]
        hit = (px <= pos.sl) if pos.side == "BUY" else (px >= pos.sl)
        if hit:
            fill = min(px, pos.sl) if pos.side == "BUY" else max(px, pos.sl)       # a gap fills beyond the stop, never better
            ev = f"{row['plan_id']}:PAPER_SL:{round(now)}"
            reason = "BE" if pos.be_status == "SET" else "SL"
            acts = b.on_primary_closed(ev, now, pos.remaining, fill, reason) if b else pos.on_closed(ev, pos.remaining, fill, reason)
            self.store.event(row["plan_id"], "PAPER_STOP", {"price": fill, "reason": reason}, now)
            self.process(ex, row, obj, acts, spec, q, now)

    # ------------------------------------------------------------------ AUTO_DEMO / AUTO_LIVE: reconciliation with the terminal
    def reconcile(self, ex, row, obj, spec, now) -> None:
        b = obj if isinstance(obj, Basket) else None
        pos = b.primary if b else obj
        try:
            term = {p["ticket"]: p for p in ex.terminal_positions(spec.symbol)}
        except Exception:  # noqa: BLE001 - no terminal answer: nothing is assumed
            return
        tk = row.get("primary_ticket")
        if tk and pos.remaining > 1e-9:
            p = term.get(int(tk))
            vol_t = p["volume"] if p else 0.0
            if vol_t < pos.remaining - 1e-9:
                deals = ex.closing_deals(int(tk))
                px = deals[-1]["price"] if deals else (pos.sl or pos.entry)
                gone = round(pos.remaining - vol_t, 8)
                reason = "BROKER_TP" if pos.legs and abs(px - pos.legs[-1].price) < abs(px - pos.sl) else ("BE" if pos.be_status == "SET" else "SL")
                if p is not None:
                    reason = "ZEWNĘTRZNE_ZAMKNIĘCIE_CZĘŚCI"
                ev = f"{row['plan_id']}:RECON:{tk}:{round(vol_t, 4)}"
                acts = b.on_primary_closed(ev, now, gone, px, reason) if b else pos.on_closed(ev, gone, px, reason)
                self.store.event(row["plan_id"], "RECONCILED_PRIMARY", {"terminal_volume": vol_t, "closed": gone, "price": px, "reason": reason}, now)
                if acts:
                    self.process(ex, row, obj, acts, spec, {"bid": px, "ask": px, "spread": 0.0}, now)
                else:
                    self.finish(row, obj, spec, now)
        htk = row.get("hedge_ticket")
        if b and b.hedge and b.hedge.status in ("OPEN", "CLOSING") and htk and int(htk) not in term:
            deals = ex.closing_deals(int(htk))
            px = deals[-1]["price"] if deals else b.hedge.entry
            b.hedge.status = "OPEN"
            b.on_hedge_closed(f"{row['plan_id']}:RECON_H:{htk}", now, b.hedge.volume, px)
            self.store.event(row["plan_id"], "RECONCILED_HEDGE", {"price": px}, now)
            self.finish(row, obj, spec, now)

    def recover(self, ex, spec, now) -> dict:
        """After a restart / reconnect: plans whose entry outcome is unknown are adopted from the terminal (own magic + comment)
        or rejected; terminal positions with the SH magic and no owner are reported as ORPHANS (never managed implicitly)."""
        out = {"adopted": [], "rejected": [], "orphans": []}
        rows = self.store.open_plans(spec.symbol)
        demo = [r for r in rows if r["exec_mode"] in RK.REAL_MODES]
        if not demo and not rows:
            return out
        try:
            term = ex.terminal_positions(spec.symbol) if ex.terminal is not None else []
        except Exception:  # noqa: BLE001
            return out
        shm = C.load()["magic_number"]
        for r in demo:
            if r["state"] == "ENTRY_UNKNOWN":
                tag = ex.comment(r["plan_id"], "P")
                hit = next((p for p in term if p["magic"] == shm and p["comment"] == tag), None)
                if hit:
                    self.store.own(ex.account_key, hit["ticket"], r["plan_id"], "OPEN_P", now)
                    self.store.event(r["plan_id"], "ADOPTED", hit, now)
                    self.bind_fill(ex, r["plan"], {"status": "FILLED", "price": hit["price_open"], "volume": hit["volume"], "ticket": hit["ticket"]},
                                   spec, self.quote(now) or {"bid": hit["price_open"], "ask": hit["price_open"], "spread": 0.0}, r["exec_mode"], now)
                    out["adopted"].append(r["plan_id"])
                else:
                    self.store.update_plan(r["plan_id"], state="REJECTED", result={"reason": "brak pozycji w terminalu po wyniku UNKNOWN"}, now=now)
                    out["rejected"].append(r["plan_id"])
        for p in term:
            if p["magic"] == shm and not self.store.owner(ex.account_key, p["ticket"]):
                out["orphans"].append(p["ticket"])
        if out["orphans"]:
            self.log.warn("SH", "ORPHANS", f"pozycje z magic SH bez planu: {out['orphans']} – nie są zarządzane automatycznie")
        self.state["recovery"] = {**out, "at": now}
        return out

    # ------------------------------------------------------------------ views
    def plan_view(self, row: dict, q: dict | None) -> dict:
        o = row.get("fsm_obj")
        v = {k: row.get(k) for k in ("plan_id", "signal_id", "strategy", "symbol", "side", "exec_mode", "state", "config_hash", "primary_ticket",
                                     "hedge_ticket", "created_at", "updated_at")}
        v["plan"] = row["plan"]
        if isinstance(o, Basket):
            v["basket"] = o.report(q["bid"], q["ask"]) if q else None
            v["position"] = o.primary.snapshot()
        elif o is not None:
            v["position"] = o.snapshot()
        return v

    def public(self) -> dict:
        return {k: v for k, v in self.state.items()}
