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
from .executor import SHExecutor, TerminalDataUnavailable
from .hedge_fsm import HEDGE_CLOSE_MAX_TRIES, Basket, HedgeConfig
from .lifecycle import Leg, Position
from .store import SHStore
from .units import SymbolSpec, UnitError

STRATEGIES = ("SCALPING", "HEDGING")
NOT_SH_GATE_REASONS = ("EXECUTION_MODE_SIGNALS", "RISK_LIMITS_NOT_CONFIGURED")
MM = {"NETTING": 0, "EXCHANGE": 1, "HEDGING": 2}
RECON_WAIT_SECONDS = 60.0      # a terminal answering None / a vanished position without its closing deal: plan frozen this long, then
RECON_WAIT_MIN_TICKS = 3       # settled as before with verified=False (the loss never drops out of the daily limit)
RECON_WAIT_GAP_SECONDS = 30.0  # observations further apart are not consecutive (the wait starts again)
CAP_RETRY_SECONDS = 5.0        # pack ratio-cap reduction of the hedge after a rejection: spacing and attempt limit
CAP_RETRY_MAX = 5


def day_start(now: float) -> float:
    d = datetime.fromtimestamp(now, tz=timezone.utc)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()


def _regime_kw(record_sh, snap: dict | None) -> dict:
    """1.46 (D4): {'regime': <regime of this cycle's snapshot>} for a coordinator whose record_sh takes it (DecisionCoordinator), {} for
    an older / stub receiver without the keyword - the call stays valid for both."""
    import inspect
    try:
        ok = "regime" in inspect.signature(record_sh).parameters
    except (TypeError, ValueError):
        ok = False
    reg = snap.get("regime") if isinstance(snap, dict) else None
    return {"regime": reg if isinstance(reg, dict) else None} if ok else {}


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
        self._recon_wait: dict = {}                   # plan_id -> deferred reconciliation (in memory: a restart only restarts the wait)
        self._recon_err: dict = {}                    # plan_id -> terminal not answering (timeout / busy): signalled, never settled on
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
            rec = self.recover(ex, spec, now)
            if not rec.get("incomplete"):                 # terminal data unavailable: recovery is repeated on the next tick
                self.recovered_epoch = epoch
        if q:
            self.manage(ex, spec, q, now, shc)
        self.store.expire_signals(now)
        bars = {tf: [b for b in self.bridge.bars(tf, 400, include_forming=False) if b.get("open_utc")] for tf in ("M1", "M5", "M15", "H1")}
        if getattr(self, "pack", None) is not None:                     # 1.38 pack: longer closed history + M3 (native or complete triples)
            from .pack.engine import NEEDED_BARS
            self.pack_bars = {tf: [b for b in self.bridge.bars(tf, NEEDED_BARS[tf], include_forming=False) if b.get("open_utc")]
                              for tf in NEEDED_BARS}
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
        ep = getattr(self.bridge, "session_epoch", None)
        for k in [k for k in self.snap_cache if k[1] != ep]:   # 1.46: the epoch only grows - entries of an older epoch are never read again
            del self.snap_cache[k]                              # (1.45.0 kept one heavy analysis cache per reconnect for the process lifetime)
        snap = CX.snapshot(bars, q, tick=spec.tick_size, now=now, cfg={"max_bar_age_s": r["max_bar_age_s"], "max_quote_age_s": r["max_quote_age_s"],
                                                                      "max_spread_usd": ic.get("max_spread_usd")}, cache=self.snap_cache.setdefault((inst, ep), {}))
        self.snapshot = snap
        mx = MR.matrix(None, inst)
        evals = {}
        for strat in STRATEGIES:
            prof = C.profile(shc, inst, strat)
            su = SU.evaluate(strat, inst, snap, spec, prof, now=now, models=mx["rows"], config_hash=shc["_hash"], m1=bars["M1"][-20:])
            if su["status"] == "READY" and TM.status(inst, strat).get("status") == "READY":
                pr = TM.predict(inst, strat, TM.features(su, snap))
                su = SU.evaluate(strat, inst, snap, spec, prof, now=now, tp_prob=pr, models=mx["rows"], config_hash=shc["_hash"], m1=bars["M1"][-20:])
            evals[strat] = self._tsfm(self._kronos(su, inst, strat, snap), inst, strat)
        ind = getattr(self, "indicators", None)
        if ind is not None:                                               # PMW-IND-1 context (role OBSERVE: shown + logged, never a gate)
            try:
                ictx = ind.context(None, bars)
            except Exception as exc:  # noqa: BLE001
                ictx = {"indicators": {"status": "ERROR", "reason": f"{type(exc).__name__}: {exc}"[:160]}, "dxy": {"status": "ERROR"}}
            for su in evals.values():
                su["indicator_context"] = dict(ictx, role="OBSERVE", horizon_note="DXY = kontekst H1, nie trigger M1")
        fam = getattr(self, "families", None)
        if fam is not None:                                               # 1.33 families: context; ASSIST may only hold READY -> WAIT
            from ..modelhub.families.service import apply_to_setup
            for k, su in list(evals.items()):
                try:
                    evals[k] = apply_to_setup(su, fam.setup_context(su, inst))
                except Exception as exc:  # noqa: BLE001
                    su["family_context"] = {"error": f"{type(exc).__name__}: {exc}"[:160]}
        pevals = self.pack_cycle(inst, spec, q, acc, now, shc, snap)
        for su in pevals:
            evals[f"{su['strategy_id']}|{su['pack']['signal_tf']}"] = su
        ready = [s for s in evals.values() if s["status"] == "READY"]
        opens = self.store.open_plans(spec.symbol)
        foreign = self.foreign_positions(spec.symbol, shc["magic_number"]) if mode in RK.REAL_MODES else 0
        coord = {(d.get("signal_id") or d["strategy"]): d for d in arbitrate(ready, open_plans=[{"strategy": p["strategy"], "symbol": p["symbol"],
                                                                                                  "side": p["side"], "state": p["state"]} for p in opens],
                                                                           foreign_positions=foreign, cfg=shc, symbol=spec.symbol)}
        for strat, su in evals.items():
            risk = None
            is_pack = bool(su.get("strategy_id"))
            fam = su["strategy"]
            cd = (coord.get(su.get("signal_id")) or (None if is_pack else coord.get(fam))) if su.get("status") == "READY" else None
            if cd:
                su["coordination"] = cd
                if cd["decision"] == "PROCEED":
                    rstate = self.risk_state(spec.symbol, fam, now, foreign)
                    if mode == "AUTO_LIVE":
                        rstate["live_validation"] = self.pack_live_validation(su) if is_pack else self.live_validation(inst, fam)
                    prof = self.vprofile(su, C.profile(shc, inst, fam)) if is_pack else C.profile(shc, inst, fam)
                    risk = RK.evaluate(setup=su, spec=spec, prof=prof, cfg=shc, inst=inst, account=acc,
                                       state=rstate, exec_mode=mode, now=now, quote=q)
                    if is_pack:
                        risk = self.pack_risk_extra(su, risk, prof, spec)
                    su["risk"] = risk
                else:
                    su["status_reason"] = "koordynator: " + cd["reason"]
            if risk and risk["status"] == "PASS" and entry_block:
                su["entry_block"] = list(entry_block)
                su["status_reason"] = "nowe wejścia zablokowane: " + ", ".join(entry_block)
            model_block = None
            arc = getattr(self, "arc", None)
            was_ready = (self.last_saved.get(strat, (None,))[0] == "READY")
            record = (su.get("status") == "READY" or was_ready) if is_pack else \
                (su.get("status") == "READY" or self.last_saved.get(strat, (None,))[0] != su.get("status"))
            if arc is not None and record:
                try:                                                   # PMW-ARC-1 DecisionRecord; REQUIRED models may only hold READY
                    # 1.46: the coordinator result of THIS candidate (coord is keyed by signal_id - coord.get(strat) was always None) with
                    # the "allowed" flag record_sh reads; audit trail only - entries still follow cd["decision"] above
                    rec = arc.record_sh(su, risk, mode, self.bridge.account_key, dict(cd, allowed=cd.get("decision") == "PROCEED") if cd else None,
                                        **_regime_kw(arc.record_sh, snap))
                    su["decision_record"] = {"record_id": rec["record_id"], "final_verdict": rec["final_verdict"]} if rec else None
                    req = [r for r in (rec or {}).get("reason_codes", []) if r.startswith(("MODEL_REQUIRED", "MODEL_QUANT_HOLD"))]
                    if req and su.get("status") == "READY":
                        model_block = req
                        su["status"], su["status_reason"] = "WAIT", "model REQUIRED: " + ", ".join(req)
                except Exception as exc:  # noqa: BLE001 - audit trail; REQUIRED configured -> no entry on a coordinator error
                    if getattr(getattr(self.cfg_store.get(), "decision", None), "required_models", None):
                        model_block = [f"MODEL_COORDINATOR_ERROR_{type(exc).__name__}"]
            self.persist_signal(su, risk, cd, now, key=strat if is_pack else None)
            if not is_pack:
                self.last_eval[strat] = su                                 # full setup (checklist, levels, models) for the panel
            if risk and risk["status"] == "PASS" and mode in ("PAPER",) + RK.REAL_MODES and not entry_block and not model_block:
                res = self.open_plan(ex, su, risk, spec, q, mode, now, shc, inst, snap)
                if is_pack and (res or {}).get("status") in ("OPEN", "ABORTED", "FILLED", "PARTIAL", "REJECTED", "UNKNOWN", "DUPLICATE"):
                    if su.get("basket"):
                        self.basket_consumed(su, res)
                    else:
                        self.pack.consumed(su)
        for fn in list(self.listeners):
            try:
                fn(evals, inst=inst, symbol=spec.symbol, snap=snap, now=now)
            except Exception:  # noqa: BLE001 - an observer never stops the cycle
                logging.getLogger("masterquo.sh").exception("sh listener failed")
        return evals

    # ------------------------------------------------------------------ 1.38 pack (20 variants) - same pipeline, variant identity
    def pack_cycle(self, inst, spec, q, acc, now, shc, snap) -> list[dict]:
        """20 variants on the shared closed bars of this cycle (no second model process, no separate robot). Model receivers (Kronos,
        Chronos-2 / Granite TTM, families) run on READY candidates only, with the family roles; they can only hold READY -> WAIT."""
        pk = getattr(self, "pack", None)
        if pk is None:
            return []
        ic = {k: v for k, v in shc["instruments"][inst].items() if k not in ("SCALPING", "HEDGING")}
        if getattr(pk, "garch_provider", None) is None:
            pk.garch_provider = self.garch_artifact
        try:
            out = pk.evaluate(bars=getattr(self, "pack_bars", {}) or {}, quote=q, spec=spec, inst=inst, ic=ic, now=now,
                              account_currency=acc.get("currency"))
        except Exception as exc:  # noqa: BLE001 - a failing pack never stops the legacy strategies or the management of open plans
            self.log.error("SH", "PACK", f"{type(exc).__name__}: {exc}"[:300])
            return []
        out = list(out) + self.basket_setups(inst, spec, q, now)          # 1.42: FX basket plans enter the SAME pipeline
        fam = getattr(self, "families", None)
        res = []
        for su in out:
            if su["status"] == "READY":
                su = self._tsfm(self._kronos(su, inst, su["strategy"], snap), inst, su["strategy"])
                if fam is not None:
                    try:
                        from ..modelhub.families.service import apply_to_setup
                        su = apply_to_setup(su, fam.setup_context(su, inst))
                    except Exception as exc:  # noqa: BLE001
                        su["family_context"] = {"error": f"{type(exc).__name__}: {exc}"[:160]}
            res.append(su)
        return res

    def garch_artifact(self, inst: str) -> dict:
        """1.39: the ACTIVE, APPROVED VOL_GARCH family artifact (GARCH(1,1) fitted by arch) for HG09 with volatility_method VOL_GARCH."""
        fam = getattr(self, "families", None)
        if fam is None:
            return {"status": "NO_FAMILY_SERVICE"}
        st = fam.status("VOL_GARCH", inst)
        rid = st.get("active_run")
        if st.get("artifact") != "APPROVED" or not rid:
            return {"status": st.get("artifact") or "NOT_TRAINED"}
        art = fam._artifact("VOL_GARCH", inst, rid)
        return {"status": "READY", "run_id": rid, "omega": art["omega"], "alpha": art["alpha"], "beta": art["beta"], "dist": art.get("dist")}

    # ------------------------------------------------------------------ 1.42: FX baskets (FX_SMC / FX_SCALP / FX_HEDGE) -> SH path
    def vprofile(self, su: dict, fam_prof: dict) -> dict:
        return self.basket_profile(su, fam_prof) if su.get("basket") else self.pack.profile(su, fam_prof)

    @staticmethod
    def basket_profile(su: dict, fam_prof: dict) -> dict:
        """Frozen execution profile of a basket plan: its two planned targets (50 / 50), its own timeout, no BE, no SH hedge leg
        (basket hedging stays with the basket hedge planners); risk sizing = the shared SH risk engine with the user's limits."""
        mins = float(su.get("position_max_minutes") or 60)
        return {"shares": list(su.get("shares") or [0.5, 0.5]), "shares_fallback_two": None, "position_max_minutes": mins, "horizon_minutes": mins,
                "be_after": None, "be_rule": None, "min_net_rr": 1.0, "strategy_id": su.get("strategy_id"),
                "strategy_version": (su.get("pack") or {}).get("strategy_version"), "config_hash": None, "_instrument": fam_prof.get("_instrument") or {}}

    def basket_setups(self, inst: str, spec, q, now: float) -> list[dict]:
        bs = getattr(self, "baskets", None)
        if bs is None:
            return []
        try:
            cands = bs.sh_candidates(spec.symbol, now)
        except Exception as exc:  # noqa: BLE001 - the baskets never stop the SH cycle
            self.log.warn("SH", "BASKET_CANDIDATES", f"{type(exc).__name__}: {exc}"[:200])
            return []
        out = []
        for sg in cands:
            try:
                su = self.basket_su(sg, inst, spec, q, now)
            except Exception as exc:  # noqa: BLE001 - a malformed plan is skipped (and consumed), never guessed
                bs.ledger.mark_exec(sg["signal_id"], None, "MALFORMED", f"{type(exc).__name__}: {exc}"[:200])
                continue
            if su["status"] == "INVALIDATED":
                bs.ledger.mark_exec(sg["signal_id"], None, "INVALIDATED", su["status_reason"])
            out.append(su)
        return out

    @staticmethod
    def basket_su(sg: dict, inst: str, spec, q, now: float) -> dict:
        """Basket PositionPlan -> setup-shaped candidate (pack contract) for the shared coordinator / risk / intent / executor path."""
        import hashlib
        from ..baskets import catalog as BCAT
        pl = sg.get("plan") or {}
        side = "BUY" if pl.get("side") == "LONG" else "SELL"
        sgn = 1 if side == "BUY" else -1
        entry, sl = float(pl["entry_ref"]), float(pl["sl"])
        tg = [float(t["price"]) for t in pl.get("targets") or []][:2]
        if not tg:
            raise ValueError("plan bez celów")
        if len(tg) == 1:
            tg = [tg[0], tg[0]]
        status, reason = "READY", f"plan koszyka {sg.get('basket_id')} ({sg.get('strategy_id')}) – przekazany do ścieżki SH"
        if q and q.get("bid") and q.get("ask"):
            px = float(q["ask"] if side == "BUY" else q["bid"])
            if sgn * (px - sl) <= 0:
                status, reason = "INVALIDATED", "cena za SL planu koszyka przed wejściem"
            elif sgn * (tg[0] - px) <= 0:
                status, reason = "INVALIDATED", "cena minęła TP1 planu koszyka przed wejściem – brak pogoni"
        spread = float((q or {}).get("spread") or 0.0)
        R = abs(entry - sl)
        rr = round(abs(tg[0] - entry) / R, 3) if R > 0 else None
        mins = round(int(pl.get("timeout_bars") or 8) * {"M1": 1, "M3": 3, "M5": 5, "M15": 15, "M30": 30, "H1": 60}.get(sg.get("tf"), 5), 1)
        meta = BCAT.BY_ID.get(sg.get("strategy_id")) or {}
        sid = "SH-BK" + hashlib.sha256(str(sg["signal_id"]).encode()).hexdigest()[:20]
        score = (sg.get("scores") or {}).get("setup_score")
        return {"strategy": "SCALPING", "strategy_id": sg.get("strategy_id"), "signal_id": sid, "instrument": inst, "symbol": spec.symbol, "side": side,
                "status": status, "status_reason": reason, "created_at": float(sg.get("created_at") or now), "valid_until": float(sg["valid_until"]),
                "config_hash": None, "setup_version": BCAT.VERSION, "checklist": [],
                "score": {"value": score, "definition": "setup_score koszyka 0–100 – NIE prawdopodobieństwo"},
                "probability": {"value": None, "status": "BRAK_MODELU_ZDARZENIA"},
                "entry_ref": entry, "sl": sl, "invalidation": sl,
                "tps": [{"name": "TP1", "price": tg[0], "share": 0.5}, {"name": "TP2", "price": tg[1], "share": 0.5}], "shares": [0.5, 0.5],
                "horizon_minutes": mins, "position_max_minutes": mins, "be": None, "model_mode": "OGRANICZONA", "mode": "PACK",
                "costs": {"round_trip_price": spread, "commission_known": False, "note": "koszt do sizingu = spread (prowizja wg ustawień instrumentu)"},
                "net_rr": rr, "entry_zone": [entry, entry],
                "basket": {"signal_id": sg["signal_id"], "basket_id": sg.get("basket_id"), "event_id": sg.get("event_id"), "tf": sg.get("tf")},
                "pack": {"contract": "PMW-PLAN-2", "strategy_id": sg.get("strategy_id"), "name": meta.get("name") or sg.get("strategy_id"), "family": "SCALPING",
                         "cluster": sg.get("basket_id"), "setup_group_id": sg.get("event_id"), "signal_tf": sg.get("tf"), "context_tfs": meta.get("context_timeframes") or [],
                         "management_policy_id": None, "strategy_version": meta.get("version"), "config_hash": meta.get("config_hash"),
                         "validation": {"status": "NOT_VALIDATED"}, "reason_code": "OK" if status == "READY" else "PRE_FILL_INVALIDATION",
                         "analytical_state": status, "source": "BASKET_1_42",
                         "economics": {"cost_status": "SPREAD_ONLY", "c_round_trip": spread, "hedge_loss_bound_price": 0.0}}}

    def basket_consumed(self, su: dict, res: dict | None) -> None:
        bs = getattr(self, "baskets", None)
        if bs is not None:
            bs.ledger.mark_exec(su["basket"]["signal_id"], "PL-" + su["signal_id"][3:], str((res or {}).get("status")), (res or {}).get("reason"))

    @staticmethod
    def pack_live_validation(su: dict) -> dict:
        if su.get("basket"):
            return {"ok": False, "reason": f"koszyk {su['basket'].get('basket_id')}: brak walidacji OOS na danych MT5 użytkownika"}
        from .pack import catalog as CAT
        v = CAT.validation_status(su.get("strategy_id"))
        if v.get("status") == "VALIDATED" and v.get("data_kind") == "REAL_USER_DATA":
            return {"ok": True, "source": f"walidacja wariantu {su.get('strategy_id')} {v.get('report_id')}"}
        return {"ok": False, "reason": f"{su.get('strategy_id')}: {v.get('status')} – {v.get('reason') or 'brak walidacji OOS na danych MT5 użytkownika'}"}

    @staticmethod
    def pack_risk_extra(su: dict, risk: dict, prof: dict, spec) -> dict:
        """Variant-specific execution checks after the shared risk engine: both partial volumes valid (else PARTIAL_VOLUME_INFEASIBLE,
        never a bigger lot), the hedge leg volume reachable on HEDGING variants, costs known before READY_TO_EXECUTE."""
        reasons = list(risk.get("reasons") or [])
        if any(r.startswith("split") for r in reasons):
            reasons = ["PARTIAL_VOLUME_INFEASIBLE: " + r for r in reasons if r.startswith("split")] + [r for r in reasons if not r.startswith("split")]
        if risk.get("status") == "PASS" and su["strategy"] == "HEDGING":
            ratio = float((prof.get("hedge") or {}).get("ratio") or 0.5)
            hv = spec.floor_volume(float(risk.get("volume") or 0) * ratio)
            if hv < spec.volume_min - 1e-9:
                risk["checks"].append({"id": "hedge_volume", "ok": False, "detail": f"wolumen nogi hedge {hv} < min lot {spec.volume_min} przy ratio {ratio}"})
                reasons.append(f"HEDGE_VOLUME_INFEASIBLE: {hv} < {spec.volume_min}")
                risk["status"] = "BLOCK"
        risk["reasons"] = reasons
        p = su.get("pack") or {}
        p["ready_to_execute"] = risk.get("status") == "PASS" and (p.get("economics") or {}).get("cost_status") == "KNOWN"
        return risk

    def _kronos(self, su: dict, inst: str, strat: str, snap: dict) -> dict:
        """Kronos context (separate, described). OBSERVE = information only; REQUIRED (after validation + confirmation) can only turn
        READY into WAIT. Any failure here keeps the evaluation as it was in OBSERVE and as WAIT in REQUIRED - never a permission."""
        kr = getattr(self, "kronos", None)
        if kr is None:
            return su
        from ..kronos import predictions as KP
        try:
            preds = self.predictions_provider(inst) if getattr(self, "predictions_provider", None) else []
            ctx = KP.context(kr, inst, strat, side=su.get("side"), other_preds=preds, snap=snap)
        except Exception as exc:  # noqa: BLE001
            use = kr.settings.get().strategy_use[strat].use
            ctx = {"model": KP.model_name(), "timeframe": kr.settings.get().strategy_use[strat].timeframe, "use": use, "use_pl": KP.USE_PL[use],
                   "available": False, "state": "ERROR", "reason": f"kontekst Kronos: {type(exc).__name__}: {exc}"[:200], "forecast": None,
                   "setup_side": su.get("side"), "relation": "BRAK", "vs_models": [], "vs_structure": None, "knows_only": KP.KNOWS_ONLY,
                   "independence": KP.INDEPENDENCE, "validation_report": None}
        return KP.apply_to_setup(su, ctx)

    def _tsfm(self, su: dict, inst: str, strat: str) -> dict:
        """1.37 Chronos-2 / 1.40 Granite TTM receivers (separate, described). OBSERVE = information; ASSIST / REQUIRED (approved) may only turn
        READY into WAIT. A failure here never grants anything: OBSERVE keeps the evaluation, REQUIRED holds it."""
        ts = getattr(self, "tsfm", None)
        if ts is None:
            return su
        from ..tsfm import predictions as TP
        for mid in ("chronos2", "granite_ttm", "tirex2"):                 # 1.42: TiRex-2 receiver too (ASSIST)
            try:
                ctx = TP.context(ts, mid, inst, strat, side=su.get("side"))
            except Exception as exc:  # noqa: BLE001
                use = ts.settings.get().models[mid].use[strat].use
                ctx = {"model": mid, "name": mid, "timeframe": "?", "use": use, "use_configured": use, "use_pl": TP.USE_PL[use], "validation_report": None,
                       "approval": None, "available": False, "state": "ERROR", "reason": f"kontekst {mid}: {type(exc).__name__}: {exc}"[:200],
                       "forecast": None, "setup_side": su.get("side"), "relation": "BRAK", "knows_only": TP.KNOWS_ONLY}
            su = TP.apply_to_setup(su, ctx)
        return su

    def persist_signal(self, su, risk, coord, now, key: str | None = None) -> None:
        """Legacy: every status change. Pack variants: READY candidates (with their risk / coordination, BLOCKED stays in the history) and
        the end of a READY (EXPIRED / INVALIDATED / WAIT) - WAIT evaluations of 20 variants x TF stay in memory (panel), not in the history."""
        k = key or su["strategy"]
        sig = (su.get("status"), su.get("status_reason"), su.get("side"))
        if key is not None:
            prev = self.last_saved.get(k)
            if su["status"] == "READY":
                self.store.save_signal(su, risk=risk, coordination=coord, now=now)
                self.last_saved[k] = sig + (su["signal_id"],)
            elif prev and prev[0] == "READY":
                sid = prev[3]
                row = self.store.signal(sid)
                if row:
                    end = su["status"] if su["status"] in ("EXPIRED", "INVALIDATED") else "EXPIRED"
                    self.store.db.execute("UPDATE sh_signals SET status=?, status_reason=?, updated_at=? WHERE signal_id=? AND status='READY'",
                                          (end, su.get("status_reason") or "koniec gotowości", now, sid))
                self.last_saved[k] = sig + (None,)
            return
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
        is_pack = bool(su.get("strategy_id"))
        prof = self.vprofile(su, C.profile(shc, inst, su["strategy"])) if is_pack else C.profile(shc, inst, su["strategy"])
        plan = {"plan_id": pid, "signal_id": su["signal_id"], "strategy": su["strategy"], "strategy_id": su.get("strategy_id"),
                "pack": su.get("pack") if is_pack else None, "instrument": inst, "symbol": spec.symbol,
                "side": su["side"], "exec_mode": mode, "account_key": self.bridge.account_key, "config_hash": shc["_hash"],
                "setup": {k: su.get(k) for k in ("entry_ref", "sl", "tps", "shares", "be", "invalidation", "entry_zone", "mode", "costs", "net_rr",
                                                 "horizon_minutes", "position_max_minutes", "valid_until", "model_mode", "probability", "score")},
                "risk": {k: risk.get(k) for k in ("volume", "legs", "shares_used", "risk_money", "risk_pct", "money_per_price_per_lot",
                                                  "basket_loss_limit_money", "loss_per_lot")},
                "profile": {k: v for k, v in prof.items() if k != "_instrument"}, "instrument_profile": prof["_instrument"],
                "atr_m5": (snap.get("vol") or {}).get("atr_m5"), "created_at": now}
        arc = getattr(self, "arc", None)
        intent = None
        if arc is not None and mode != "SIGNALS":     # PMW-ARC-1: intent (dedup) + shared atomic risk reservation of BOTH paths
            rec = (getattr(arc, "by_source", {}) or {}).get(su["signal_id"]) or \
                (arc.last.get("SH") if (arc.last.get("SH") or {}).get("source_id") == su["signal_id"] else None)
            # w2 (I0774, tightening only): a HEDGING basket on a hedging account may later open its hedge leg - the entry needs room for
            # both positions in the shared cap (2 slots while in flight); the later hedge-leg check is unchanged (+1, its own intent)
            two = su["strategy"] == "HEDGING" and (self.bridge.account_status() or {}).get("margin_mode") == "HEDGING"
            op = arc.intents.open(path="SH", mode=mode, account_key=self.bridge.account_key, subject=pid, symbol=spec.symbol, side=su["side"],
                                  volume=float(risk["volume"]), risk_money=risk.get("risk_money"), record_id=(rec or {}).get("record_id"),
                                  equity=(getattr(self.bridge, "account", None) or {}).get("equity"), **({"positions": 2} if two else {}))
            if op["status"] == "DUPLICATE":
                return {"status": "DUPLICATE", "reason": "INTENT_ALREADY_EXISTS"}
            if op["status"] == "BLOCKED":
                self.log.info("SH", "ENTRY_RESERVATION_BLOCKED", f"{su['strategy']} {su['side']}: {','.join(op['reasons'])}")
                return {"status": "BLOCKED", "reason": "RESERVATION:" + ",".join(op["reasons"])}
            intent = op["intent"]["intent_id"]
        if not self.store.create_plan(plan, now):
            if intent:
                arc.intents.outcome(intent, {"status": "DUPLICATE"})
            return {"status": "DUPLICATE"}
        tp3 = su["tps"][-1]["price"]
        if intent:
            arc.intents.sent(intent, pid)
        res = ex.open(plan, role="P", side=su["side"], volume=risk["volume"], sl=su["sl"], tp=tp3, mode=mode, quote=q, tag="P",
                      slippage=float(prof["_instrument"].get("slippage_usd") or 0) if mode == "PAPER" else 0.0, now=now)
        if intent:
            try:
                arc.intents.outcome(intent, res)
            except Exception as exc:  # noqa: BLE001 - the plan state is the source of truth; sync() settles the intent later
                self.log.warn("SH", "INTENT_OUTCOME_FAILED", f"{type(exc).__name__}: {exc}"[:200])
        self.store.event(pid, "OPEN_RESULT", res, now)
        if res["status"] in ("FILLED", "PARTIAL"):
            self._notify("trade_opened", {"key": pid, "mode": mode, "symbol": spec.symbol, "side": su["side"], "volume": res.get("volume"),
                                              "price": res.get("price"), "sl": su["sl"], "tp": tp3, "strategy": f"SH {su['strategy']}"})
        if res["status"] not in ("FILLED", "PARTIAL"):
            st = "ENTRY_UNKNOWN" if res["status"] == "UNKNOWN" else "REJECTED"
            self.store.update_plan(pid, state=st, result={"reason": res.get("reason"), "retcode": res.get("retcode")}, now=now)
            self.log.warn("SH", "ENTRY_" + res["status"], f"{su['strategy']} {su['side']}: {res.get('reason')}")
            return res
        return self.bind_fill(ex, plan, res, spec, q, mode, now)

    def bind_fill(self, ex, plan, res, spec, q, mode, now) -> dict:
        """Targets from the ACTUAL fill price (snapped to ticks, never closer than requested); split of the ACTUAL filled volume."""
        if plan.get("pack"):
            return self.bind_fill_pack(ex, plan, res, spec, q, mode, now)
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

    def bind_fill_pack(self, ex, plan, res, spec, q, mode, now) -> dict:
        """Pack plans keep their PLANNED absolute TP1 / TP2 / SL (the plan is not silently moved to hide a slippage). The fill deviation and
        the net RR from the ACTUAL fill are reported; if the slippage breaks the plan (fill beyond SL, a target already passed, or net RR
        below 90 % of the minimum) the pre-defined policy closes the position (ENTRY_ABORT)."""
        from .pack import solver as SV
        pid, side, su, prof, pk = plan["plan_id"], plan["side"], plan["setup"], plan["profile"], plan["pack"]
        fill, vol = float(res["price"]), float(res["volume"])
        sl = float(su["sl"])
        tps = [float(t["price"]) for t in su["tps"]]
        shares = list(prof["shares"])
        sp = spec.split(vol, shares)
        sg = 1 if side == "BUY" else -1
        r = sg * (fill - sl)
        econ = pk.get("economics") or {}
        c = float(econ.get("c_round_trip") or 0.0)
        hl = float(econ.get("hedge_loss_bound_price") or 0.0)
        why = None
        if r <= 0:
            why = "wykonanie po złej stronie SL (poślizg)"
        elif sg * (tps[0] - fill) <= 0:
            why = "wykonanie za TP1 (poślizg) – plan nieważny"
        elif sp["status"] != "OK":
            why = f"PARTIAL_VOLUME_INFEASIBLE: podział wykonanego wolumenu {vol}: {sp.get('reason')}"
        else:
            d1, d2 = sg * (tps[0] - fill), sg * (tps[1] - fill)
            rr = SV.rr_basket(d1, d2, r, c, hl, hl, *shares) if plan["strategy"] == "HEDGING" else SV.rr_plan_net(d1, d2, r, c, c, *shares)
            self.store.event(pid, "FILL_DEVIATION", {"entry_plan": su.get("entry_ref"), "entry_fill": fill, "deviation": round(fill - float(su.get("entry_ref") or fill), 6),
                                                     "rr_at_fill": round(rr, 4), "rr_min": prof["min_net_rr"]}, now)
            if rr < 0.9 * float(prof["min_net_rr"]):
                why = f"poślizg łamie plan: RR netto przy fillu {rr:.2f} < 90 % minimum {prof['min_net_rr']}"
        if why:
            pos = Position(pid, side, fill, vol, sl, [Leg("TP2", tps[-1], vol)])
            self.store.update_plan(pid, state="OPEN", fsm=pos, primary_ticket=res.get("ticket"), now=now)
            act = {"action_id": f"{pid}:CLOSE_RUNNER:ENTRY_ABORT", "plan_id": pid, "kind": "CLOSE_RUNNER", "volume": vol, "reason": why}
            self.store.event(pid, "ENTRY_ABORT", {"reason": why}, now)
            self.process(ex, self.store.plan(pid), pos, [act], spec, q, now)
            return {"status": "ABORTED", "reason": why}
        legs = [Leg("TP1", tps[0], sp["legs"][0]), Leg("TP2", tps[1], sp["legs"][1])]
        pos = Position(pid, side, fill, vol, sl, legs, be_rule="ENTRY", be_offset=0.0, be_reject_policy="CLOSE")
        obj = pos
        if plan["strategy"] == "HEDGING":
            h = prof["hedge"]
            cfg = HedgeConfig(trigger_adverse_usd=1e12, ratio=float(h["ratio"]), max_ratio=float(h["max_ratio"]), max_activations=1,
                              max_hedge_minutes=1e9, unwind_recovery_usd=1e12,
                              basket_loss_limit_money=float(plan["risk"].get("basket_loss_limit_money") or 0.0),
                              basket_max_minutes=float(prof["position_max_minutes"]))
            obj = Basket(pid, pos, cfg, spec.money_per_price(1.0), opened_at=now,
                         policy={"policy_id": h.get("policy_id"), "opened_at": now, "variant": plan.get("strategy_id")})
        self.store.update_plan(pid, state=obj.state, fsm=obj, primary_ticket=res.get("ticket"), now=now)
        self.store.event(pid, "BOUND", {"fill": fill, "volume": vol, "legs": [vars(x) for x in legs], "split": sp, "targets": "PLANNED_ABSOLUTE"}, now)
        acts = [{"action_id": f"{pid}:MODIFY_TP:FILL", "plan_id": pid, "kind": "MODIFY_TP", "tp": legs[-1].price}]
        self.process(ex, self.store.plan(pid), obj, acts, spec, q, now)
        return {"status": "OPEN", "plan_id": pid, "fill": fill, "volume": vol}

    def pack_hedge_step(self, row, b: Basket, spec, q, now) -> list[dict]:
        """Variant hedge policy (policies.py) on the closed M5 after the fill. Priority: hedge timeout / unwind before any new activation;
        a new activation passes the same account / volume / margin checks as the legacy hedge AND an atomic HEDGE intent with a risk
        reservation (IntentLedger / RiskBook) - an opposite leg is never treated as a costless close."""
        from .pack import policies as POL
        plan = row["plan"]
        pk = plan["pack"]
        vid = plan.get("strategy_id")
        p = b.primary
        hedged = bool(b.hedge and b.hedge.status in ("OPEN", "CLOSING"))
        out: list[dict] = []
        # ratio cap after a partial of the base: the hedge never exceeds max_ratio x remaining base volume (after an exit decision the
        # whole leg is being closed - no separate reduction)
        if hedged and b.hedge.status == "OPEN" and b.state != "EXIT_PENDING":
            cap = spec.floor_volume(p.remaining * float(b.cfg.max_ratio))
            excess = round(b.hedge.volume - cap, 8)
            if excess > 1e-9:
                import math
                ex_v = round(math.ceil(excess / spec.volume_step - 1e-9) * spec.volume_step, 8)       # reduce at least the excess
                if b.hedge.volume - ex_v < spec.volume_min - 1e-9:
                    ex_v = b.hedge.volume                                                       # remainder below min lot: close the leg
                # a rejected reduction (its id released by on_hedge_closed) is retried spaced and bounded - never every tick
                nrej = int(b.policy.get("cap_rejects") or 0)
                wait = nrej and (nrej >= CAP_RETRY_MAX or now - float(b.policy.get("cap_last_reject") or 0.0) < CAP_RETRY_SECONDS)
                a = None if wait else b._act("CLOSE_HEDGE", f"CAP{len(p.realized)}", volume=min(b.hedge.volume, ex_v),
                                             reason="limit hedge po częściowym zamknięciu bazy")
                if a:
                    out.append(a)
                    b.policy["cap_reduced"] = True
                    return out
                # reduction in flight / waiting: the variant policy is still evaluated (while hedged only EXIT / UNWIND / HOLD)
        if b.state not in ("PRIMARY_OPEN", "HEDGED"):
            return out
        m5 = self.bridge.bars("M5", 700, include_forming=False)
        h1 = self.bridge.bars("H1", 1050, include_forming=False)
        st = pk.get("structure_view") or {}
        try:
            dec = POL.decision(vid, plan=plan, st=st, pstate=b.policy, m5_bars=m5, h1_bars=h1, quote=q, now=now,
                               primary={"side": p.side, "entry": p.entry, "sl": p.sl, "remaining": p.remaining, "volume": p.volume,
                                        "opened_at": float(b.policy.get("opened_at") or b.opened_at)},
                               hedged=hedged, hedge_opened_at=b.hedge.opened_at if b.hedge else None, activations=b.activations,
                               tick=spec.tick_size, common=(self.pack.ctx.cm if getattr(self.pack, "ctx", None) else {"b_tick_mult": 2, "b_atr_mult": 0.1}))
        except Exception as exc:  # noqa: BLE001 - a broken policy never opens a leg; the basket's own SL / time exits still run
            dec = {"decision": "HOLD", "reason": f"polityka: {type(exc).__name__}: {exc}"[:160]}
        b.policy["last_decision"] = {"decision": dec["decision"], "reason": dec.get("reason"), "progress": dec.get("progress"), "at": now}
        key = f"{dec['decision']}|{str(dec.get('reason'))[:40]}"
        if dec["decision"] != "HOLD" and self.last_saved.get(row["plan_id"]) != key:
            self.store.event(row["plan_id"], "HEDGE_POLICY", dec, now)
            self.last_saved[row["plan_id"]] = key
        if dec["decision"] == "EXIT":
            return b._exit_all(now, dec["reason"])
        if dec["decision"] == "UNWIND":
            return b._unwind(now, dec["reason"], gated=True)
        if dec["decision"] != "HEDGE" or hedged:
            return out                                           # never a new HEDGE intent next to an open / closing leg
        acc = self.account()
        ok, why = True, ""
        if acc.get("margin_mode") != "HEDGING":
            ok, why = False, f"rachunek {acc.get('margin_mode')} nie pozwala na pozycję przeciwną (NETTING ≠ hedge; REDUCE to osobny wariant)"
        hv = spec.floor_volume(p.remaining * min(float(dec.get("ratio") or b.cfg.ratio), float(b.cfg.max_ratio)))
        if ok and hv < spec.volume_min - 1e-9:
            ok, why = False, f"wolumen hedge {hv} < min lot {spec.volume_min}"
        mpl, eq = acc.get("margin_per_lot"), float(acc.get("equity") or 0)
        if ok and mpl and eq and float(acc.get("margin") or 0) + mpl * hv > eq * C.load()["risk"]["max_margin_use_pct"] / 100.0:
            ok, why = False, "brak miejsca w limicie depozytu"
        gate = self.gate()
        if ok and gate["entry_block"]:
            ok, why = False, "nowe ekspozycje zablokowane: " + ",".join(gate["entry_block"])   # STOP blocks new hedges, never exits
        arc = getattr(self, "arc", None)
        if ok and arc is not None and row["exec_mode"] != "SIGNALS":
            op = arc.intents.open(path="SH", mode=row["exec_mode"], account_key=self.bridge.account_key, subject=f"{row['plan_id']}:HEDGE1",
                                  symbol=spec.symbol, side="SELL" if p.side == "BUY" else "BUY", volume=hv,
                                  risk_money=None, record_id=None, equity=acc.get("equity"), kind="HEDGE")
            if op["status"] != "RESERVED":
                ok, why = False, f"intencja HEDGE {op['status']}: {','.join(op.get('reasons') or [])}"
            else:
                b.policy["hedge_intent"] = op["intent"]["intent_id"]
                arc.intents.sent(op["intent"]["intent_id"], row["plan_id"])
        if not ok:
            b.activations += 1                                   # the one activation is consumed: no retry storm, no second attempt later
            b.policy["hedge_refused"] = why
            self.store.event(row["plan_id"], "HEDGE_REFUSED", {"reason": why, "policy": dec.get("reason")}, now)
            return out
        b.cfg.ratio = min(float(dec.get("ratio") or b.cfg.ratio), float(b.cfg.max_ratio))
        return b.request_hedge(now, hv, dec["reason"])

    # ------------------------------------------------------------------ management (every tick)
    NOT_SENT_TTL_S = 60.0                      # w2 (I0739): a NOT_SENT management action is sent again for at most this long

    def manage(self, ex, spec, q, now, shc) -> None:
        lim = (spec.volume_step, spec.volume_min)        # partial closes capped to the volume the position still holds
        for row in self.store.open_plans(spec.symbol):
            obj = row.get("fsm_obj")
            if obj is None:
                continue
            mode = row["exec_mode"]
            confirmed = True
            if mode in RK.REAL_MODES:
                rs = self.reconcile(ex, row, obj, spec, now)
                if rs == "SKIP":
                    continue        # another account / terminal not read / settlement waits for the deal: no action on an unverified state
                confirmed = rs == "CONFIRMED"           # a hedge leg only when fresh data showed the primary with its full volume
            elif mode == "PAPER":
                self.paper_stops(ex, row, obj, spec, q, now)
            acts = self._retry_acts(row, obj, now)
            if isinstance(obj, Basket):
                inval = row["plan"]["setup"].get("invalidation")
                p = obj.primary
                sv = True if inval is None else ((q["bid"] > inval) if p.side == "BUY" else (q["ask"] < inval))
                if row["plan"].get("pack"):
                    if p.state in ("OPEN", "TP1_DONE") and confirmed:
                        acts += self.pack_hedge_step(row, obj, spec, q, now)
                elif obj.state == "PRIMARY_OPEN" and p.state in ("OPEN", "TP1_DONE") and obj.activations < obj.cfg.max_activations and confirmed:
                    acts += self.hedge_step(row, obj, spec, q, now, sv)
                acts += obj.on_quote(now, q["bid"], q["ask"], structure_valid=sv, primary_close_ok=self._primary_close_free(row, obj, ex),
                                     limits=lim)
            else:
                acts += obj.on_quote(q["bid"], q["ask"], limits=lim)
                maxm = float(row["plan"]["profile"].get("position_max_minutes") or 0)
                if maxm and now - row["created_at"] >= 60 * maxm and obj.remaining > 1e-9:
                    acts.append({"action_id": f"{row['plan_id']}:CLOSE_RUNNER:TIME", "plan_id": row["plan_id"], "kind": "CLOSE_RUNNER",
                                 "volume": obj.remaining, "reason": "TIME_LIMIT"})
            seen_ids: set = set()
            acts = [a for a in acts if not (a["action_id"] in seen_ids or seen_ids.add(a["action_id"]))]   # a retried id once per tick
            self.process(ex, row, obj, acts, spec, q, now)

    def _retry_acts(self, row, obj, now) -> list[dict]:
        """w2 (I0739): NOT_SENT management actions of this plan, sent again with the SAME id / volume / level (flag _retry) within
        NOT_SENT_TTL_S. After it the action goes back to the normal evaluation - never a blind send: a partial-close leg returns to
        PENDING (requested again only when its price is crossed again), an unwind (UNWINDING) returns to HEDGED with the leg OPEN;
        every other action stays where it was (as an UNKNOWN one today: no EXIT_PENDING rollback, no BE fallback)."""
        lst = getattr(obj, "_sh_retry", None) or []
        out, keep = [], []
        for ent in lst:
            a = ent.get("action") or {}
            first = ent.get("first_at")
            if now - float(now if first is None else first) <= self.NOT_SENT_TTL_S:
                keep.append(ent)
                out.append(dict(a, _retry=True))
                continue
            self._retry_expired(row, obj, a, now)
        obj._sh_retry = keep
        return out

    def _retry_expired(self, row, obj, a, now) -> None:
        b = obj if isinstance(obj, Basket) else None
        pos = b.primary if b else obj
        k, aid = a.get("kind"), a.get("action_id")
        back = False
        if k == "CLOSE_PARTIAL":
            pos.on_partial_rejected(f"{aid}:ns{now}", aid.split(":")[-1], "NOT_SENT_TTL")
            back = True
        elif k == "CLOSE_HEDGE" and b and b.state == "UNWINDING" and b.hedge and b.hedge.status == "CLOSING":
            b.hedge.status = "OPEN"
            b.issued.discard(aid)
            b._no_new_hedge(now, "zamknięcie nogi hedge nie wysłane do terminala (NOT_SENT_TTL)")   # merge w2: as I0740 - no second leg
            b._go("HEDGED", "zamknięcie hedge nie wysłane do terminala – ocena od nowa", now)
            back = True
        if not back:
            self.store.finish_action(aid, "NOT_SENT_EXPIRED", {"status": "NOT_SENT_EXPIRED", "reason": "NOT_SENT_TTL"}, now)
        self.store.event(row["plan_id"], "ACTION_NOT_SENT_EXPIRED", {"action": aid, "kind": k, "back_to_evaluation": back}, now)

    def _not_sent(self, row, obj, a, res, now) -> bool:
        """True = the result is fully handled here (no state-machine feedback): NOT_SENT keeps / adds the retry entry; a retried
        action that still fails is dropped without any state change (no rollback of EXIT_PENDING, no BE fallback)."""
        lst = getattr(obj, "_sh_retry", None)
        if lst is None:
            lst = obj._sh_retry = []
        aid = a["action_id"]
        ent = next((e for e in lst if (e.get("action") or {}).get("action_id") == aid), None)
        if res.get("status") == "NOT_SENT":
            if ent is None:
                lst.append({"action": {k: v for k, v in a.items() if k != "_retry"}, "first_at": now})
                self.store.event(row["plan_id"], "ACTION_NOT_SENT", {"action": aid, "reason": res.get("reason")}, now)
            return True
        if ent is not None:
            lst.remove(ent)
        return bool(a.get("_retry")) and res.get("status") not in ("FILLED", "PARTIAL", "DONE")

    def _primary_close_free(self, row, b: Basket, ex=None) -> bool:
        """EXIT_PENDING may re-request the close of the primary only when no close of it is in flight: SENT / UNKNOWN in sh_actions, or
        the rest of a PARTIAL answer that the terminal may still be working (RETURN filling)."""
        if b.state != "EXIT_PENDING" or b.primary.remaining <= 1e-9:
            return False
        return not self._closes_in_flight(row, ex)

    @staticmethod
    def _js(v) -> dict:
        if isinstance(v, dict):
            return v
        try:
            return json.loads(v) if v else {}
        except (TypeError, ValueError):
            return {}

    def _closes_in_flight(self, row, ex=None, kinds=("CLOSE_PRIMARY", "CLOSE_RUNNER", "CLOSE_PARTIAL", "CLOSE_PRIMARY_PART")) -> list[dict]:
        """Closes of the primary whose outcome is still open, oldest first: [{action_id, kind, leg, volume (unfilled part of the request),
        row}] - SENT / UNKNOWN / NOT_SENT waiting for its retry (minus what reconciliation already settled on it), and the rest of a
        PARTIAL answer unless the terminal
        cancels such a rest (FOK / IOC; ex.rest_cancelled())."""
        rest_cancelled = True if ex is None else ex.rest_cancelled()
        out = []
        for a in self.store.actions(row["plan_id"]):
            if a["kind"] not in kinds:
                continue
            req, res = self._js(a.get("request")), self._js(a.get("result"))
            rv = float(req.get("volume") or 0)
            rec = float(res.get("reconciled_volume") or 0)
            if a["status"] in ("SENT", "UNKNOWN", "NOT_SENT"):   # merge w2: a NOT_SENT close waits for its retry (same id, I0739)
                left = round(rv - rec, 8) if rv > 0 else float("inf")
            elif a["status"] == "DONE" and res.get("status") == "PARTIAL" and not rest_cancelled:
                left = round(rv - float(res.get("volume") or 0) - rec, 8)
            else:
                continue
            if left > 1e-9:
                out.append({"action_id": a["action_id"], "kind": a["kind"], "volume": left, "row": a,
                            "leg": req.get("leg") or a["action_id"].split(":")[-1].split("#")[0]})
        return out

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
                hi = (b.policy or {}).pop("hedge_intent", None) if b else None
                arc = getattr(self, "arc", None)
                if hi and arc is not None:
                    try:
                        arc.intents.outcome(hi, res)
                    except Exception as exc:  # noqa: BLE001
                        self.log.warn("SH", "HEDGE_INTENT_OUTCOME_FAILED", f"{type(exc).__name__}: {exc}"[:200])
                queue += b.on_hedge_result(a["action_id"] + ":r", now, ok, float(res.get("volume") or 0), float(res.get("price") or 0),
                                           "PARTIAL" if res["status"] == "PARTIAL" else str(res.get("reason") or res["status"]))
                if ok:
                    row["hedge_ticket"] = res.get("ticket")
                    self.store.update_plan(pid, hedge_ticket=res.get("ticket"), now=now)
                continue
            if k == "CLOSE_HEDGE":
                hs = b.hedge.side if b and b.hedge else ("SELL" if pos.side == "BUY" else "BUY")
                res = ex.perform(row["plan"], a, mode=mode, quote=q, ticket=row.get("hedge_ticket"), side_of_position=hs, slippage=slip, now=now)
                if self._not_sent(row, obj, a, res, now):
                    continue
                hvol = float(res.get("volume") or 0)
                if res["status"] in ("FILLED", "PARTIAL") and hvol > 0:
                    b.hedge.status = "OPEN"
                    queue += b.on_hedge_closed(a["action_id"] + ":r", now, hvol, float(res["price"]), action_id=a["action_id"])
                    if res["status"] == "PARTIAL" and b.hedge.status == "OPEN" and ":CLOSE_HEDGE:CAP" not in a["action_id"] \
                            and not ex.rest_cancelled():
                        b.hedge.status = "CLOSING"          # RETURN filling: the rest may still be working - never re-requested;
                        #                                     reconciliation settles the leg when its ticket disappears
                elif res["status"] == "REJECTED":
                    b.hedge.status = "OPEN"
                    st0 = b.state
                    queue += b.on_hedge_closed(a["action_id"] + f":rej{now}", now, 0, 0, ok=False, reason=str(res.get("reason")),
                                               action_id=a["action_id"])
                    if ":CLOSE_HEDGE:CAP" not in a["action_id"] and b.exit_retries >= HEDGE_CLOSE_MAX_TRIES:
                        why = f"zamknięcie nogi hedge odrzucone {b.exit_retries} razy (stan {st0} -> {b.state}): {res.get('reason')}"
                        self.store.event(pid, "HEDGE_CLOSE_FAILED", {"reason": why, "retcode": res.get("retcode")}, now)
                        self.log.error("SH", "HEDGE_CLOSE_FAILED", f"{pid}: {why}"[:300])  # noqa: PLE1205 - application log (source, code, text)
                continue
            res = ex.perform(row["plan"], a, mode=mode, quote=q, ticket=row.get("primary_ticket"), side_of_position=pos.side, slippage=slip, now=now)
            if self._not_sent(row, obj, a, res, now):
                continue
            st = res["status"]
            vol = float(res.get("volume") or 0)
            # an OK answer without an executed volume (or a stored DONE row without it) is an unknown outcome: reconciliation decides
            done = st in ("FILLED", "PARTIAL", "DONE") and vol > 0
            if k == "MODIFY_TP":
                continue
            if k == "MODIFY_SL":
                if st in ("DONE", "REJECTED"):
                    queue += pos.on_sl_result(a["action_id"] + ":r", st == "DONE", q["bid"], q["ask"], str(res.get("reason") or ""))
                elif st == "BLOCKED":
                    queue += pos.on_sl_result(a["action_id"] + ":b", False, q["bid"], q["ask"], res["reason"])
                continue
            if k == "CLOSE_PARTIAL":
                leg = a.get("leg") or a["action_id"].split(":")[-1].split("#")[0]
                if done:
                    ev = a["action_id"] + ":r"
                    rr = st == "PARTIAL" and ex.rest_cancelled()           # rest of a partial fill re-requested only if the terminal dropped it
                    rq = float(a.get("volume") or 0) or None
                    queue += (b.on_primary_fill(ev, now, leg, vol, float(res["price"]), retry_rest=rr, requested=rq) if b
                              else pos.on_fill(ev, leg, vol, float(res["price"]), retry_rest=rr, requested=rq))
                elif st in ("REJECTED", "BLOCKED"):
                    pos.on_partial_rejected(a["action_id"] + f":rej{now}", leg, str(res.get("reason")), action_id=a["action_id"])
                continue
            if k in ("CLOSE_RUNNER", "CLOSE_PRIMARY", "CLOSE_PRIMARY_PART"):
                if done:
                    ev = a["action_id"] + ":r"
                    reason = a.get("reason") or k
                    if k == "CLOSE_RUNNER" and reason == "TP3":
                        queue += (b.on_primary_fill(ev, now, "TP3", vol, float(res["price"])) if b
                                  else pos.on_fill(ev, "TP3", vol, float(res["price"])))
                    else:
                        queue += (b.on_primary_closed(ev, now, vol, float(res["price"]), reason[:40]) if b
                                  else pos.on_closed(ev, vol, float(res["price"]), reason[:40]))
                elif st in ("REJECTED", "BLOCKED"):
                    pos.issued.discard(a["action_id"])                  # allow the same exit to be requested again
                    if b:
                        # 1.46: an exit decision is final - the basket stays EXIT_PENDING (re-requested, spaced) and never returns to
                        # PRIMARY_OPEN / HEDGED, where a hedge step could open a new opposite leg
                        b.on_primary_close_rejected(now, a["action_id"], str(res.get("reason")))
                continue
        self.finish(row, obj, spec, now)

    def _notify(self, kind: str, data: dict) -> None:
        """Opened / closed SH plan for notifications (Telegram). Never allowed to affect the plan or its execution."""
        if self.bus is None:
            return
        try:
            self.bus.publish(kind, data)
        except Exception:
            logging.getLogger("masterquo.sh").exception("SH %s notification failed", kind)

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
        if closed and res and self.bus is not None:
            try:
                cur = (self.account() or {}).get("currency")
            except Exception:
                cur = None
            self._notify("trade_closed", {"key": pid, "mode": row["exec_mode"], "symbol": row.get("symbol") or spec.symbol, "side": row.get("side"),
                                          "volume": pos.volume, "net": res["net_money"], "currency": cur, "r_multiple": res["r_multiple"],
                                          "commission_known": res["commission_known"], "strategy": f"SH {row.get('strategy')}"})

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
        # a close settled without its closing deal (reconciliation after the wait) carries a substitute price
        verified = all(r.get("verified", True) for r in pos.realized)
        if b:
            verified = verified and not any(e["kind"] == "RECONCILED_UNVERIFIED" and (e["payload"] or {}).get("leg") == "HEDGE"
                                            for e in self.store.events(row["plan_id"]))
        gross = prim + hedge
        try:                                                     # 1.46: R from the INITIAL risk (frozen plan SL), never from the current SL
            sl0 = float(((row.get("plan") or {}).get("setup") or {})["sl"])     # (after BE the current SL ~ entry: R was ~7x too big or None)
        except (KeyError, TypeError, ValueError):
            sl0 = pos.sl
        sl_risk = abs(pos.entry - sl0) * pos.volume * mpp
        return {"primary_money": round(prim, 2), "hedge_money": round(hedge, 2), "gross_money": round(gross, 2),
                "commission_money": None if comm_money is None else round(comm_money, 2),
                "net_money": round(gross - (comm_money or 0.0), 2), "commission_known": comm is not None,
                "r_multiple": round((gross - (comm_money or 0.0)) / sl_risk, 3) if sl_risk else None,
                "legs": [vars(x) for x in pos.legs], "realized": pos.realized, "hedge_activations": b.activations if b else 0,
                "price_verified": verified}

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
    def _recon_waited(self, pid: str, kind: str, now: float, detail: str) -> bool:
        """Deferred reconciliation of one plan: False while waiting (the plan is frozen), True once RECON_WAIT_SECONDS of consecutive
        observations passed - then it is settled as before 1.46 (substitute price) with verified=False and an alert."""
        w = self._recon_wait.get(pid)
        if w is None or w["kind"] != kind or now - w["last"] > RECON_WAIT_GAP_SECONDS:
            self._recon_wait[pid] = {"kind": kind, "since": now, "last": now, "n": 1}
            self.store.event(pid, "RECONCILE_WAIT", {"kind": kind, "detail": detail[:200], "max_wait_s": RECON_WAIT_SECONDS}, now)
            return False
        w["last"], w["n"] = now, w["n"] + 1
        if now - w["since"] < RECON_WAIT_SECONDS or w["n"] < RECON_WAIT_MIN_TICKS:
            return False
        self._recon_wait.pop(pid, None)
        self.log.error("SH", "RECONCILED_UNVERIFIED",  # noqa: PLE1205 - application log (source, code, text)
                       f"{pid}: {kind} przez {now - w['since']:.0f} s – rozliczenie ceną zastępczą (verified=False): {detail}"[:300])
        return True

    def _recon_terminal_error(self, pid: str, now: float, detail: str) -> None:
        """No terminal answer (timeout / busy worker) - the plan is skipped (nothing is assumed or settled on it), but visibly: a
        RECONCILE_WAIT event and a warning at the start of an episode, an error once it lasted RECON_WAIT_SECONDS (once per episode)."""
        w = self._recon_err.get(pid)
        if w is None or now - w["last"] > RECON_WAIT_GAP_SECONDS:
            self._recon_err[pid] = {"since": now, "last": now, "n": 1, "alerted": False}
            self.store.event(pid, "RECONCILE_WAIT", {"kind": "TERMINAL_ERROR", "detail": detail[:200], "settles": False}, now)
            self.log.warn("SH", "RECONCILE_WAIT", f"{pid}: terminal nie odpowiada – zarządzanie planem wstrzymane: {detail}"[:300])  # noqa: PLE1205, G010 - application log
            return
        w["last"], w["n"] = now, w["n"] + 1
        if not w["alerted"] and now - w["since"] >= RECON_WAIT_SECONDS and w["n"] >= RECON_WAIT_MIN_TICKS:
            w["alerted"] = True
            self.store.event(pid, "RECONCILE_WAIT", {"kind": "TERMINAL_ERROR", "detail": detail[:200], "settles": False,
                                                     "waiting_s": round(now - w["since"])}, now)
            self.log.error("SH", "RECONCILE_TERMINAL_ERROR",  # noqa: PLE1205 - application log (source, code, text)
                           f"{pid}: terminal nie odpowiada od {now - w['since']:.0f} s – plan bez zarządzania bota: {detail}"[:300])

    def _settle_partials_in_flight(self, ex, row, obj, gone: float, deals: list, px: float, ver: bool, ev: str, now: float):
        """A volume drop of a primary still open: first the partial closes of REQUESTED legs whose outcome is unknown (timeout, OK without
        volume, the working rest of a RETURN partial) take it - in leg order, up to their unfilled request - so the leg completes (TP1_DONE /
        TP2_DONE with BE and the hedge unwind) instead of staying in flight while the same volume is booked again as an external close.
        Returns (actions, the volume left for the external close, settled legs)."""
        b = obj if isinstance(obj, Basket) else None
        pos = b.primary if b else obj
        req = {x.name for x in pos.legs if x.status == "REQUESTED" and x.name != "TP3"}
        acts, done = [], []
        if not req or gone <= 1e-9:
            return acts, gone, done
        for f in self._closes_in_flight(row, ex, kinds=("CLOSE_PARTIAL",)):
            if gone <= 1e-9:
                break
            leg = next((x for x in pos.legs if x.name == f["leg"] and x.name in req and x.status == "REQUESTED"), None)
            if leg is None:
                continue
            v = round(min(gone, f["volume"], max(0.0, leg.volume - leg.fill_volume)), 8)
            if v <= 1e-9:
                continue
            tag = ex.comment(row["plan_id"], f["action_id"].split(":")[-1])
            own = [d for d in deals if d.get("comment") == tag]                  # the leg's own closing deal, when the terminal kept the comment
            lpx = own[-1]["price"] if own else px
            n0 = len(pos.realized)
            e = f"{ev}:{f['action_id'].split(':')[-1]}"
            acts += (b.on_primary_fill(e, now, leg.name, v, lpx, requested=f["volume"]) if b
                     else pos.on_fill(e, leg.name, v, lpx, requested=f["volume"]))
            if not (own or ver):
                for r in pos.realized[n0:]:
                    r["verified"] = False
            gone = round(gone - v, 8)
            a, res = f["row"], self._js(f["row"].get("result"))
            rec = round(float(res.get("reconciled_volume") or 0) + v, 8)
            full = f["volume"] - v <= 1e-9
            st = "DONE" if full or a["status"] == "DONE" else a["status"]
            out = dict(res, reconciled_volume=rec, reconciled_price=lpx, reconciled_verified=bool(own or ver))
            if a["status"] != "DONE" and full:
                out.update(status="FILLED", volume=rec, price=lpx, reconciled=True)          # outcome no longer unknown
            self.store.finish_action(f["action_id"], st, out, now)
            done.append({"leg": leg.name, "action_id": f["action_id"], "volume": v, "price": lpx, "verified": bool(own or ver)})
        return acts, gone, done

    def reconcile(self, ex, row, obj, spec, now) -> str:
        """Terminal plan against the terminal. Returns CONFIRMED (the primary ticket is seen with its full remaining volume), READ
        (terminal read: settled / nothing to confirm) or SKIP (no management of the plan in this tick): a plan of another account is
        managed only on its own account; a terminal answering None (error, not 'no positions') or a vanished primary without its closing
        deal freezes the plan for RECON_WAIT_SECONDS, then it is settled as before with verified=False. A basket with an open hedge leg
        is settled at once (the leg is unwound immediately, as before) - only its price stays unverified. A terminal not answering at all
        (timeout / busy) only skips the plan, signalled (RECONCILE_WAIT, alert after RECON_WAIT_SECONDS) - never settled on. A partial volume
        drop is booked first on the partial closes in flight (unknown outcome), the rest as an external partial close."""
        b = obj if isinstance(obj, Basket) else None
        pos = b.primary if b else obj
        pid = row["plan_id"]
        if row.get("account_key") not in (None, ex.account_key):
            return "SKIP"                                            # open plan still blocks the symbol (coordinator)
        unverified = False
        try:
            term = {p["ticket"]: p for p in ex.terminal_positions(spec.symbol)}
        except TerminalDataUnavailable as exc:
            if not self._recon_waited(pid, "TERMINAL_NONE", now, str(exc)):
                return "SKIP"
            term, unverified = {}, True
        except Exception as exc:  # noqa: BLE001 - no terminal answer: nothing is assumed (signalled, never settled on)
            self._recon_terminal_error(pid, now, f"{type(exc).__name__}: {exc}")
            return "SKIP"
        self._recon_err.pop(pid, None)
        if not unverified and (self._recon_wait.get(pid) or {}).get("kind") == "TERMINAL_NONE":
            self._recon_wait.pop(pid, None)                          # the terminal answers again
        confirmed = False
        tk = row.get("primary_ticket")
        if tk and pos.remaining > 1e-9:
            p = term.get(int(tk))
            vol_t = p["volume"] if p else 0.0
            if vol_t >= pos.remaining - 1e-9:
                confirmed = True
                self._recon_wait.pop(pid, None)
            else:
                try:
                    deals = [] if unverified else ex.closing_deals(int(tk))
                except Exception:  # noqa: BLE001 - per plan: a failing history query never stops the management of other plans
                    deals = []
                hedged = bool(b and b.hedge and b.hedge.status in ("OPEN", "CLOSING"))
                if not deals and not unverified and not hedged and \
                        not self._recon_waited(pid, "NO_CLOSING_DEAL", now, f"terminal {vol_t} < plan {pos.remaining}"):
                    return "SKIP"                                    # frozen until the closing deal arrives (or the wait ends)
                self._recon_wait.pop(pid, None)
                ver = bool(deals)
                px = deals[-1]["price"] if deals else (pos.sl or pos.entry)
                gone = round(pos.remaining - vol_t, 8)
                reason = "BROKER_TP" if pos.legs and abs(px - pos.legs[-1].price) < abs(px - pos.sl) else ("BE" if pos.be_status == "SET" else "SL")
                if p is not None:
                    reason = "ZEWNĘTRZNE_ZAMKNIĘCIE_CZĘŚCI"
                ev = f"{pid}:RECON:{tk}:{round(vol_t, 4)}"
                acts, legs, ext = [], [], gone
                if p is not None:                                    # partial drop: partial closes in flight first (outcome unknown)
                    acts, ext, legs = self._settle_partials_in_flight(ex, row, obj, gone, deals, px, ver, ev, now)
                n0 = len(pos.realized)
                if ext > 1e-9:
                    acts += b.on_primary_closed(ev, now, ext, px, reason) if b else pos.on_closed(ev, ext, px, reason)
                if not ver and len(pos.realized) > n0:
                    pos.realized[-1]["verified"] = False
                info = {"terminal_volume": vol_t, "closed": gone, "price": px, "reason": reason, "verified": ver}
                if legs:
                    info.update(legs_in_flight=legs, closed_external=ext)
                self.store.event(pid, "RECONCILED_PRIMARY", info, now)
                if not ver:
                    self.store.event(pid, "RECONCILED_UNVERIFIED", {**info, "leg": "PRIMARY"}, now)
                if acts:
                    self.process(ex, row, obj, acts, spec, {"bid": px, "ask": px, "spread": 0.0}, now)
                else:
                    self.finish(row, obj, spec, now)
        htk = row.get("hedge_ticket")
        if b and b.hedge and b.hedge.status in ("OPEN", "CLOSING") and htk and int(htk) not in term:
            try:
                deals = [] if unverified else ex.closing_deals(int(htk))
            except Exception:  # noqa: BLE001 - per plan, as above
                deals = []
            px = deals[-1]["price"] if deals else b.hedge.entry
            b.hedge.status = "OPEN"
            b.on_hedge_closed(f"{pid}:RECON_H:{htk}", now, b.hedge.volume, px)
            self.store.event(pid, "RECONCILED_HEDGE", {"price": px, "verified": bool(deals)}, now)
            if not deals:
                self.store.event(pid, "RECONCILED_UNVERIFIED", {"leg": "HEDGE", "price": px}, now)
            self.finish(row, obj, spec, now)
        return "CONFIRMED" if confirmed else "READ"

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
        except Exception as exc:  # noqa: BLE001 - no data: nothing is adopted or rejected, the recovery is repeated (next tick)
            return {**out, "incomplete": f"{type(exc).__name__}: {exc}"[:200]}
        shm = C.load()["magic_number"]
        for r in demo:
            if r.get("account_key") not in (None, ex.account_key):
                continue                                             # decided only on its own account (never rejected from another one)
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
        if row.get("exec_mode") in RK.REAL_MODES and row.get("account_key") not in (None, getattr(self.bridge, "account_key", None)):
            v["flags"] = ["INNY_RACHUNEK"]          # managed only when the plan's own account is connected (the plan still blocks the symbol)
        if isinstance(o, Basket):
            v["basket"] = o.report(q["bid"], q["ask"]) if q else None
            v["position"] = o.primary.snapshot()
        elif o is not None:
            v["position"] = o.snapshot()
        return v

    def public(self) -> dict:
        return {k: v for k, v in self.state.items()}
