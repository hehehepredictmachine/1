"""EngineService - the single canonical execution flow of MasterQUO AI.

  MT5 bridge bars/quote -> data quality (M01 role) -> legacy snapshot -> M02 -> M02I -> M03
  -> M07 + plan lock -> M10A lifecycle (SQLite) -> levels (MQAI-LEVELS) -> M11 risk
  -> Claude AI gate -> mode gate -> decision tree -> persisted decision -> (gateway if allowed)

Full cycle: on newly closed bars (any TF), config/session change, or every 60 s.
Light cycle: every second - data freshness, live quote risk for a CONFIRMED setup, decision.
Analysis never blocks the bridge (own thread) and Claude runs asynchronously (own loop).
"""
from __future__ import annotations

import collections
import hashlib
import logging
import threading
import time
from datetime import timedelta

from .. import paths
from ..data import quality
from ..db.database import dumps
from ..risk import engine as risk_engine
from ..risk.costs import resolve_commission
from ..timeutil import TIMEFRAMES, iso, parse_iso, utcnow
from . import chartdata, decision as decision_mod, lifecycle, targets
from .active import ActiveEngine
from .legacy import LegacyEngines, build_snapshot

log = logging.getLogger("masterquo.engine")
ANALYSIS_MIN_BARS = 260


class EngineService:
    def __init__(self, cfg_store, bridge, db, bus, applog, modes, news, pcclock):
        self.cfg_store = cfg_store
        self.bridge = bridge
        self.db = db
        self.bus = bus
        self.log = applog
        self.modes = modes
        self.news = news
        self.pcclock = pcclock
        self.agent = None          # set by runtime
        self.gateway = None        # set by runtime
        self.ml = None             # MLService, set by runtime
        self.legacy = LegacyEngines(paths.data_dir() / "legacy_m07_plan_lock.sqlite")
        self.required = self.legacy.profiles.required_closed_bars()
        self.lifecycle = lifecycle.LifecycleStore(db)
        self.active = ActiveEngine(db, cfg_store, bridge, applog, bus)
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._dirty = True
        self._seen_epoch = -1
        self.dq: dict | None = None
        self.last_full: dict | None = None
        self.decision: dict | None = None
        self.charts: dict[str, dict] = {}
        self.contexts: collections.OrderedDict[str, dict] = collections.OrderedDict()
        self.cycle_ms: float | None = None
        self.full_count = 0
        self.last_error: str | None = None
        self._last_decision_hash: str | None = None
        self._last_full_mono = 0.0
        self._last_h1_agent = 0.0
        bridge.add_listener(self._on_bridge)

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        threading.Thread(target=self._loop, name="engine", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def mark_dirty(self) -> None:
        self._dirty = True
        self._wake.set()

    def _on_bridge(self, kind: str, data: dict) -> None:
        if kind in ("bars_closed", "connected", "account_changed"):
            if kind == "account_changed":
                self.modes.reset("ACCOUNT_OR_TERMINAL_CHANGED")
                self.legacy.reset_memory()
                with self._lock:
                    self.decision = None
            self.mark_dirty()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(1.0)
            self._wake.clear()
            try:
                if self._dirty or self.bridge.session_epoch != self._seen_epoch or time.monotonic() - self._last_full_mono > 60:
                    time.sleep(0.3)  # coalesce simultaneous closes of several TFs
                    self._dirty = False
                    self.full_cycle()
                else:
                    self.light_cycle()
                self.last_error = None
            except Exception as exc:
                log.exception("engine cycle failed")
                self.last_error = f"{type(exc).__name__}: {exc}"[:300]
                self.bus.publish("engine_error", {"error": self.last_error})

    # ------------------------------------------------------------ helpers
    def _bars(self) -> dict[str, list[dict]]:
        return {tf: self.bridge.bars(tf) for tf in TIMEFRAMES}

    def _assess(self, bars: dict) -> dict:
        cfg = self.cfg_store.get()
        return quality.assess(symbol=cfg.mt5.symbol, bars_by_tf=bars, required=self.required, quote=self.bridge.quote_status(),
                              clock=self.bridge.clock.evidence.as_dict(), connection_state=self.bridge.state, now=utcnow(),
                              max_quote_age=cfg.mt5.max_quote_age_seconds, pc_clock=self.pcclock.snapshot(),
                              symbol_status=self.bridge.symbol_status)

    def _primary_setup(self, account_key: str | None, symbol: str) -> dict | None:
        act = self.lifecycle.active(account_key, symbol)
        if act:
            act.sort(key=lambda r: (lifecycle.ORDER.index(r["state"]), r["created_at"]))
            return act[-1]
        recent = self.db.one("SELECT setup_id FROM setups WHERE symbol=? AND IFNULL(account_key,'')=IFNULL(?, '') ORDER BY state_changed_at DESC LIMIT 1",
                             (symbol, account_key))
        if recent:
            rec = self.lifecycle.get(recent["setup_id"])
            if rec and parse_iso(rec["state_changed_at"]) > utcnow() - timedelta(hours=2):
                return rec
        return None

    # ------------------------------------------------------------ full cycle
    def full_cycle(self) -> None:
        t0 = time.monotonic()
        cfg = self.cfg_store.get()
        sym, alias = cfg.mt5.symbol, cfg.mt5.analytical_alias
        epoch = self.bridge.session_epoch
        self._seen_epoch = epoch
        self._last_full_mono = time.monotonic()
        account_key = self.bridge.account_key
        bars = self._bars()
        dq = self._assess(bars)
        now = utcnow()
        as_of = iso(now)
        sid = "SNP-" + hashlib.sha256(f"{account_key}|{epoch}|{as_of}".encode()).hexdigest()[:16]
        closed = {tf: [b for b in bars[tf] if b["closed"] and b.get("open_utc") and b.get("close_confirmed_utc")][-max(ANALYSIS_MIN_BARS, self.required[tf] + 30):]
                  for tf in TIMEFRAMES}
        legacy_out: dict = {"errors": []}
        if dq["analysis_allowed"]:
            snap = build_snapshot(snapshot_id=sid, analysis_id=f"MQAI-{self.bus.boot_id}", as_of=as_of, symbol=sym, alias=alias,
                                  closed_bars=closed, analysis_status="PASS_WITH_LIMITATIONS", reason_codes=dq["reason_codes"])
            legacy_out = self.legacy.run(snap, cfg.strategy.mode, cfg.strategy.structure_policy)
        else:
            legacy_out["errors"].append("ANALYSIS_NOT_ALLOWED_BY_DATA_GATE")
        transitions = []
        plan = legacy_out.get("m07_plan")
        if plan and dq["analysis_allowed"]:
            last_open = closed[plan["setup_tf"]][-1]["open_utc"] if closed[plan["setup_tf"]] else None
            rec, created = self.lifecycle.register(plan, account_key=account_key, symbol=sym, detected_at=as_of,
                                                   last_closed_open=last_open, ttl_bars=cfg.strategy.setup_ttl_bars,
                                                   synthetic=self.bridge.synthetic)
            if created:
                self.log.info("ENGINE", "SETUP_NEW", f"Nowy setup {rec['strategy_id']} {rec['profile']} {rec['direction']} na {rec['setup_tf']} ({rec['state']})",
                              {"setup_id": rec["setup_id"]})
                transitions.append(("SETUP_NEW", rec))
        if dq["analysis_allowed"]:
            current_ids = {lifecycle.setup_id_for(plan, account_key)} if plan else set()
            for rec in self.lifecycle.active(account_key, sym):
                rec, trs = self.lifecycle.evaluate(rec["setup_id"], closed[rec["setup_tf"]], cfg.strategy.confirmed_window_bars)
                for tr in trs:
                    self.log.info("ENGINE", "SETUP_" + tr["state"], f"Setup {rec['strategy_id']} {rec['direction']}: {tr['from']} → {tr['state']} ({tr['reason']})",
                                  {"setup_id": rec["setup_id"]})
                    transitions.append(("SETUP_" + tr["state"], rec))
                if (rec["state"] in ("EARLY_SETUP", "QUALIFIED", "ARMED") and rec["setup_id"] not in current_ids
                        and "m07" in legacy_out and not legacy_out["errors"]):
                    rec = self.lifecycle.terminate(rec["setup_id"], "EXPIRED", "M07_PLAN_LOCK_NO_LONGER_VALID", as_of)
                    transitions.append(("SETUP_EXPIRED", rec))
        # chart caches
        m02, m03 = legacy_out.get("m02") or {}, legacy_out.get("m03") or {}
        charts = {}
        tp = self.legacy.profiles.m02i.get("timeframe_profiles", {})
        for tf in TIMEFRAMES:
            cl = [b for b in bars[tf] if b["closed"] and b.get("open_utc")]
            charts[tf] = {"indicators": chartdata.indicator_series(tf, cl, tp.get(tf)),
                          "overlays": chartdata.overlays(tf, (m03.get("timeframes") or {}).get(tf), (m02.get("timeframes") or {}).get(tf)),
                          "quality": dq["timeframes"][tf], "snapshot_id": sid}
        with self._lock:
            self.dq = dq
            self.charts = charts
            self.last_full = {"snapshot_id": sid, "as_of": as_of, "epoch": epoch, "account_key": account_key, "legacy": legacy_out,
                              "closed": closed}
        self.full_count += 1
        self._persist_snapshot(sid, as_of, account_key, epoch, sym, dq, legacy_out)
        self.bus.publish("analysis", self.analysis_summary())
        active_events = self.active.maybe_scan(bars, dq, self.bridge.quote_status(), force=True, snapshot_id=sid)
        self.light_cycle(force_publish=True)
        self._active_agent_triggers(active_events, sid)
        self.cycle_ms = round((time.monotonic() - t0) * 1000, 1)
        # agent triggers (after the decision/context for this snapshot exists)
        if self.agent and cfg.active.profile == "ORIGINAL":
            for kind, rec in transitions:
                trig = {"SETUP_NEW": "SETUP_NEW", "SETUP_TRIGGERED": "SETUP_TRIGGERED", "SETUP_CONFIRMED": "SETUP_CONFIRMED"}.get(kind)
                if kind in ("SETUP_INVALIDATED", "SETUP_EXPIRED", "SETUP_MISSED_ENTRY"):
                    trig = "SETUP_TERMINAL"
                if trig:
                    self.agent.request(trig, snapshot_id=sid, setup_id=rec["setup_id"], setup_state=rec["state"])
        if self.agent:
            if not transitions and time.monotonic() - self._last_h1_agent > 3600 and dq["analysis_allowed"]:
                self._last_h1_agent = time.monotonic()
                if cfg.active.profile == "ACTIVE":
                    sel = self.active.selected_row()
                    self.agent.request("CONTEXT_HOURLY", snapshot_id=sid, setup_id=sel["setup_id"] if sel else None, setup_state=sel["stage"] if sel else None)
                else:
                    prim = self._primary_setup(account_key, sym)
                    self.agent.request("CONTEXT_HOURLY", snapshot_id=sid, setup_id=prim["setup_id"] if prim and prim["state"] in lifecycle.ACTIVE else None,
                                       setup_state=prim["state"] if prim else None)

    def _active_agent_triggers(self, events: list, sid: str) -> None:
        """Claude is asked only on significant changes of the SELECTED setup (rate limits apply in the agent)."""
        if not self.agent or not events:
            return
        sel = (self.active.selector.selected or {}).get("setup_id")
        for kind, r in events:
            if not r or not r.get("setup_id"):
                continue
            if kind == "SELECTION_CHANGED" or (r["setup_id"] == sel and kind in ("NEW_EARLY", "STAGE_EARLY", "NEW_CONFIRMED", "STAGE_CONFIRMED")):
                trig = "SETUP_CONFIRMED" if r.get("stage") == "CONFIRMED" else "SETUP_NEW"
                self.agent.request(trig, snapshot_id=sid, setup_id=r["setup_id"], setup_state=r.get("stage"))
            elif r["setup_id"] == sel and kind in ("INVALIDATED", "EXPIRED", "MISSED_ENTRY", "CANCELLED"):
                self.agent.request("SETUP_TERMINAL", snapshot_id=sid, setup_id=r["setup_id"], setup_state=kind)

    def _persist_snapshot(self, sid, as_of, account_key, epoch, sym, dq, legacy_out) -> None:
        m02 = legacy_out.get("m02") or {}
        summary = {"dq": {k: dq[k] for k in ("data_quality", "market_state", "reason_codes", "analysis_allowed", "entries_allowed")},
                   "m02": {"status": m02.get("status"), "structural_direction": m02.get("structural_direction"),
                           "regime_conflict": m02.get("regime_conflict")},
                   "m02i": (legacy_out.get("m02i") or {}).get("status"), "m03": (legacy_out.get("m03") or {}).get("status"),
                   "m07": {k: (legacy_out.get("m07") or {}).get(k) for k in ("candidate_status", "reason_codes")},
                   "plan_hash": (legacy_out.get("m07_plan") or {}).get("frozen_plan_hash"), "errors": legacy_out.get("errors")}
        self.db.execute("INSERT OR REPLACE INTO analysis_snapshots(snapshot_id, created_at, account_key, session_epoch, symbol, data_quality, synthetic, summary_json) VALUES (?,?,?,?,?,?,?,?)",
                        (sid, as_of, account_key, epoch, sym, dq["data_quality"], int(self.bridge.synthetic), dumps(summary)))
        if self.full_count % 200 == 0:
            self.db.execute("DELETE FROM analysis_snapshots WHERE snapshot_id NOT IN (SELECT snapshot_id FROM analysis_snapshots ORDER BY created_at DESC LIMIT 20000)")

    # ------------------------------------------------------------ light cycle
    def light_cycle(self, force_publish: bool = False) -> None:
        with self._lock:
            full = self.last_full
        if not full:
            return
        cfg = self.cfg_store.get()
        sym = cfg.mt5.symbol
        bars = self._bars()
        dq = self._assess(bars)
        account_key = self.bridge.account_key
        epoch = self.bridge.session_epoch
        legacy_out = full["legacy"] if full["epoch"] == epoch else {"errors": ["SESSION_CHANGED_REANALYSIS_PENDING"]}
        quote = self.bridge.quote_status()
        levels = risk = None
        active_ctx = None
        events: list = []
        if cfg.active.profile == "ACTIVE":
            events = self.active.maybe_scan(bars, dq, quote, force=False, snapshot_id=full["snapshot_id"])
            setup, levels, active_ctx = self.active.decision_inputs()
            if setup and levels and levels["status"] == "AVAILABLE":
                live = setup["state"] == "CONFIRMED" and quote is not None
                risk = self._risk(setup["direction"], levels, quote, live, self.active.hypothetical_entry())
        else:
            rec = self._primary_setup(account_key, sym)
            setup = lifecycle.public_setup(rec)
            if rec and rec["state"] in lifecycle.ACTIVE and legacy_out.get("m03"):
                atr = ((legacy_out.get("m02") or {}).get("timeframes") or {}).get(rec["setup_tf"], {}).get("atr")
                live = rec["state"] == "CONFIRMED" and quote is not None
                entry = (quote["ask"] if rec["direction"] == "LONG" else quote["bid"]) if live else None
                levels = targets.derive_levels(rec["plan"], legacy_out["m03"], atr, entry=entry, spread=(quote or {}).get("spread"),
                                               tp1_weight=cfg.strategy.tp1_weight, min_target_distance_atr=cfg.strategy.min_target_distance_atr)
                risk = self._risk(rec["direction"], levels, quote, live, float(rec["plan"]["lifecycle_rules"]["confirmation"]["level"]))
        now_iso = iso(utcnow())
        agent_gate = self.agent.gate_for(setup, session_epoch=epoch, account_key=account_key, now_iso=now_iso) if self.agent \
            else {"status": "UNAVAILABLE", "reason_codes": ["AGENT_NOT_RUNNING"]}
        mode_gate = self.modes.gate(account_key)
        macro = self.news.macro() if self.news else {"status": "DISABLED"}
        d = decision_mod.build(snapshot_id=full["snapshot_id"], as_of=now_iso, symbol=sym, account_key=account_key, session_epoch=epoch,
                               dq=dq, legacy=legacy_out, setup=setup, levels=levels, risk=risk, agent_gate=agent_gate, mode_gate=mode_gate,
                               macro=macro, strategy_cfg=cfg.strategy, risk_cfg=cfg.risk, dxy_status=self.bridge.dxy_status,
                               synthetic=self.bridge.synthetic, active=active_ctx, ml_gate=self._ml_gate(setup))
        with self._lock:
            self.dq = dq
            self.decision = d
        self._store_context(full, dq, setup, levels, risk, quote, macro)
        if d["content_hash"] != self._last_decision_hash or force_publish:
            changed = d["content_hash"] != self._last_decision_hash
            self._last_decision_hash = d["content_hash"]
            if changed:
                self.db.execute("""INSERT OR IGNORE INTO decisions(decision_id, created_at, snapshot_id, setup_id, account_key, session_epoch, symbol, synthetic,
                                   analysis_direction, signal_stage, decision, execution_permission, expires_at, record_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                (d["decision_id"], d["as_of_utc"], d["snapshot_id"], (setup or {}).get("setup_id"), account_key, epoch, sym,
                                 int(self.bridge.synthetic), d["analysis_direction"], d["signal_stage"], d["decision"], d["execution_permission"],
                                 d["expires_at_utc"], dumps(d)))
            self.bus.publish("decision", d)
        else:
            self.bus.publish("dq", {k: dq[k] for k in ("data_quality", "market_state", "reason_codes", "entries_allowed", "analysis_allowed")})
        if events:
            self._active_agent_triggers(events, full["snapshot_id"])
        if (d["execution_permission"] == "ALLOWED" and mode_gate.get("auto_trading") and self.gateway is not None):
            try:
                self.gateway.execute(d["decision_id"], initiated_by="AUTO")
            except Exception as exc:
                self.log.error("EXECUTION", "AUTO_EXECUTE_FAILED", f"Automatyczne wykonanie nieudane: {exc}")

    def _ml_gate(self, setup: dict | None) -> dict | None:
        if self.ml is None or self.cfg_store.get().active.profile != "ACTIVE":
            return None
        try:
            row = self.active.tracker.get(setup["setup_id"]) if setup else None
            return self.ml.gate(row, self.active.view)
        except Exception as exc:                     # the model never freezes the bot: fall back to strategies only
            return {"status": "PASS", "mode": self.ml.cfg.mode, "codes": [f"ML_ERROR_FALLBACK_{type(exc).__name__}"], "prediction": None}

    def _risk(self, direction: str, levels: dict, quote: dict | None, live: bool, hypo_level: float | None) -> dict:
        cfg = self.cfg_store.get()
        b = self.bridge
        q = quote
        basis = "LIVE_QUOTE"
        if not live:
            if hypo_level is None:
                return {"risk_gate": "PREVIEW", "reason_codes": ["NO_HYPOTHETICAL_ENTRY_LEVEL"], "entry_basis": "NONE"}
            lvl = float(hypo_level)
            spr = (quote or {}).get("spread") or 0.0
            q = {"bid": lvl if direction == "SHORT" else lvl - spr, "ask": lvl + spr if direction == "SHORT" else lvl,
                 "spread_points": (quote or {}).get("spread_points")}
            basis = "HYPOTHETICAL_AT_TRIGGER_LEVEL"
        with b._lock:
            positions = list(b.positions)
            deals = list(b.deals)
        commission = resolve_commission(cfg.costs, deals, cfg.mt5.symbol)
        day_start = b.server_day_start_utc()
        day_start_raw = (day_start.timestamp() + b.clock.offset) if (day_start and b.clock.offset is not None) else None
        peak = self.db.one("SELECT MAX(equity) AS p FROM equity_snapshots WHERE account_key=? AND mode='ACCOUNT'", (b.account_key,))

        def pos_risk(p):
            try:
                return b.calc_profit(p["side"], p["volume"], p["price_current"], p["sl"])
            except Exception:
                return None
        try:
            orisk = risk_engine.open_risk(positions, pos_risk)
            last_loss = self.db.one("SELECT closed_at FROM trades WHERE source='BOT' AND net_pnl < 0 AND IFNULL(account_key,'')=IFNULL(?, '') ORDER BY closed_at DESC LIMIT 1",
                                    (b.account_key,))
            res = risk_engine.evaluate(side=direction, levels=levels, quote=q, symbol_info=b.symbol_info, account=b.account_status(),
                                       limits=cfg.risk, costs_cfg=cfg.costs, commission=commission,
                                       profit_fn=lambda s, v, o, c: b.calc_profit(s, v, o, c), margin_fn=lambda s, v, p: b.calc_margin(s, v, p),
                                       positions=positions, deals=deals, day_start_raw=day_start_raw,
                                       equity_peak=(peak or {}).get("p"), open_risk_info=orisk, margin_mode=(b.account or {}).get("margin_mode"),
                                       last_bot_loss_at=parse_iso(last_loss["closed_at"]) if last_loss else None, now=utcnow(),
                                       max_spread_points=cfg.risk.max_spread_points, symbol=cfg.mt5.symbol)
        except Exception as exc:  # terminal call failure etc. -> blocked, never guessed
            res = {"risk_gate": "BLOCKED", "reason_codes": ["RISK_EVALUATION_FAILED:" + type(exc).__name__]}
        res["entry_basis"] = basis
        if not live:
            res["risk_gate"] = "BLOCKED" if res.get("risk_gate") == "BLOCKED" else "PREVIEW"
        return res

    # ------------------------------------------------------------ contexts for the agent
    def _store_context(self, full, dq, setup, levels, risk, quote, macro) -> None:
        sid = full["snapshot_id"]
        acct = self.bridge.account_status() or {}
        news = self.news.summary() if self.news else {}
        hist = [lifecycle.public_setup(r) for r in self.lifecycle.recent(15)]
        lessons = [dict(r) for r in self.db.query("SELECT created_at, kind, setup_id, status, content_json FROM agent_memory ORDER BY id DESC LIMIT 15")]
        ctx = {"snapshot_id": sid, "as_of": full["as_of"], "symbol": self.cfg_store.get().mt5.symbol,
               "alias": self.cfg_store.get().mt5.analytical_alias, "session_epoch": full["epoch"], "account_key": full["account_key"],
               "account_currency": acct.get("currency"), "account_trade_mode": acct.get("trade_mode"),
               "dq": dq, "quote": quote, "legacy": full["legacy"], "closed_bars": full["closed"], "setup": setup, "levels": levels,
               "risk": risk, "macro": macro, "headlines": news.get("news", []), "upcoming_events": news.get("calendar", []),
               "history": [{k: h.get(k) for k in ("setup_id", "created_at", "strategy_id", "profile", "direction", "state", "terminal_reason")} for h in hist if h],
               "lessons": lessons, "auto": self.active.status(compact=True) if self.cfg_store.get().active.profile == "ACTIVE" else None}
        with self._lock:
            if sid in self.contexts:
                self.contexts.move_to_end(sid)
            self.contexts[sid] = ctx
            while len(self.contexts) > 12:
                self.contexts.popitem(last=False)

    def context(self, snapshot_id: str | None) -> dict | None:
        with self._lock:
            if snapshot_id is None:
                return next(reversed(self.contexts.values()), None) if self.contexts else None
            return self.contexts.get(snapshot_id)

    # ------------------------------------------------------------ read API
    def analysis_summary(self) -> dict | None:
        with self._lock:
            full = self.last_full
            dq = self.dq
        if not full:
            return None
        lo = full["legacy"]
        m02 = lo.get("m02") or {}
        m02i = lo.get("m02i") or {}
        return {"snapshot_id": full["snapshot_id"], "as_of": full["as_of"], "errors": lo.get("errors"), "cycle_ms": self.cycle_ms,
                "data_quality": dq, "required_bars": self.required,
                "m02": {"status": m02.get("status"), "structural_direction": m02.get("structural_direction"),
                        "tactical_direction": m02.get("tactical_direction"), "regime_conflict": m02.get("regime_conflict"),
                        "per_tf": {tf: {k: v.get(k) for k in ("status", "structure_regime", "direction", "volatility_level", "efficiency", "atr")}
                                   for tf, v in (m02.get("timeframes") or {}).items()}},
                "m02i": {"status": m02i.get("status"), "per_tf": {tf: {"status": v.get("status"), "role": v.get("profile_role"),
                                                                        "interpretation": v.get("interpretation")} for tf, v in (m02i.get("timeframes") or {}).items()}},
                "m03": {"status": (lo.get("m03") or {}).get("status"), "early": (lo.get("m03") or {}).get("early_evidence")},
                "m07": {k: (lo.get("m07") or {}).get(k) for k in ("candidate_status", "reason_codes", "mode", "selection_reason")}}

    def chart(self, tf: str) -> dict:
        with self._lock:
            c = self.charts.get(tf) or {}
        bars = self.bridge.bars(tf, limit=self.cfg_store.get().mt5.chart_bars)
        return {"tf": tf, "symbol": self.cfg_store.get().mt5.symbol, "bars": bars, **c,
                "clock": self.bridge.clock.evidence.as_dict(), "synthetic": self.bridge.synthetic}

    def mark_entered(self, setup_id: str, reason: str) -> None:
        if setup_id.startswith("MQA-"):
            self.active.mark_entered(setup_id, reason)
        else:
            self.lifecycle.terminate(setup_id, "ENTERED", reason)

    def current_decision(self) -> dict | None:
        with self._lock:
            return self.decision
