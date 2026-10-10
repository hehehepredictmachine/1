"""ActiveEngine - profile ACTIVE inside the single EngineService flow.

bridge bars (closed + forming) + quote -> MarketView + MarketRegimeEngine -> scan S01-S10
-> SetupTracker (versions, hysteresis, invalidation, expiry) -> StrategyAutoSelector
-> setup/levels for the existing decision tree, risk engine and execution gateway.

Scanning is event driven: at most every `scan_min_interval_seconds` and only when market data
changed (closed bars or quote); a full cycle (bar close / reconnect) always rescans.
STALE/unavailable data never creates new setups; existing ones are flagged STALE.
"""
from __future__ import annotations

import collections
import threading
import time

from ..strategies import adapter, registry
from ..strategies.selector import StrategyAutoSelector
from ..strategies.tracker import SetupTracker, public
from ..timeutil import TIMEFRAMES, iso, utcnow

CONTRACT = "mq-auto-1.0.0"


class ActiveEngine:
    def __init__(self, db, cfg_store, bridge, applog, bus):
        self.db = db
        self.cfg_store = cfg_store
        self.bridge = bridge
        self.log = applog
        self.bus = bus
        self.tracker = SetupTracker(db)
        self.selector = StrategyAutoSelector(db)
        self._lock = threading.RLock()
        self._last_fp = None
        self._last_scan = 0.0
        self.last_scan_ms: float | None = None
        self.last_scan_at: str | None = None
        self.view = None
        self.scan_result: dict = {"candidates": [], "per_strategy": {}, "regime": None}
        self.data_status = "UNKNOWN"
        self.funnel = collections.defaultdict(collections.Counter)
        self.scans = 0
        self._startup_reset_done = False
        self.ml = None                           # MLService (collector + ASSIST ranking), set by the runtime

    # ------------------------------------------------------------ helpers
    def _data_status(self, dq: dict, quote: dict | None) -> str:
        if not dq.get("analysis_allowed"):
            return "UNAVAILABLE"
        max_age = self.cfg_store.get().mt5.max_quote_age_seconds
        if dq.get("market_state") != "OPEN" or not quote or quote.get("age_seconds") is None or quote["age_seconds"] > max_age:
            return "STALE"
        return "OK"

    def _fingerprint(self, bars: dict, quote: dict | None):
        last = tuple((tf, next((b["open_utc"] for b in reversed(bars.get(tf) or []) if b.get("closed")), None)) for tf in TIMEFRAMES)
        q = (quote or {}).get("time_msc") or (quote or {}).get("bid")
        return last, q

    # ------------------------------------------------------------ scan
    def maybe_scan(self, bars: dict, dq: dict, quote: dict | None, *, force: bool, snapshot_id: str | None) -> list[tuple[str, dict]]:
        cfg = self.cfg_store.get()
        ac = cfg.active
        if ac.profile != "ACTIVE":
            return []
        fp = self._fingerprint(bars, quote)
        new_data = fp != self._last_fp
        if not force and (not new_data or time.monotonic() - self._last_scan < ac.scan_min_interval_seconds):
            return []
        with self._lock:
            t0 = time.monotonic()
            self._last_scan = t0
            self._last_fp = fp
            now = utcnow()
            sym = cfg.mt5.symbol
            account_key = self.bridge.account_key
            if not self._startup_reset_done:
                # after (re)start no previous recommendation is valid until re-detected on fresh data
                n = self.tracker.cancel_all(sym, account_key, "RESTART_REVALIDATION", iso(now))
                if n:
                    self.log.info("AUTO", "RESTART_REVALIDATION", f"Po restarcie {n} wcześniejszych setupów oznaczono do ponownej weryfikacji na świeżych danych.")
                self._startup_reset_done = True
            status = self._data_status(dq, quote)
            self.data_status = status
            info = self.bridge.symbol_info or {}
            view = adapter.build_view(symbol=sym, bars_by_tf=bars, bid=(quote or {}).get("bid"), ask=(quote or {}).get("ask"),
                                      point=info.get("point"), as_of=iso(now), synthetic=self.bridge.synthetic,
                                      regime_params=ac.regime, data_status=status)
            enabled = {sid: t.scan for sid, t in ac.strategies.items()}
            data_ok = status == "OK"
            res = registry.scan(view, enabled=enabled, overrides=ac.params, thresholds=ac.thresholds.model_dump(),
                                account_key=account_key) if data_ok else {"candidates": [], "per_strategy": {
                                    sid: {"status": "DATA_" + status, "reasons": ["DATA_" + status], "drafts": 0, "published": {}}
                                    for sid in registry.STRATEGIES}, "regime": view.regime.get("state")}
            scanned = {sid for sid, ps in res["per_strategy"].items() if ps["status"] == "OK"}
            events = self.tracker.update(res["candidates"], view=view, symbol=sym, account_key=account_key, data_ok=data_ok,
                                         new_data=new_data, now=now, cfg=ac, scanned=scanned if data_ok else set(registry.STRATEGIES))
            if self.ml is not None:
                self.ml.on_setup_events(events, view, now)
            self.selector.configure(ac)
            rows = self.tracker.active(sym, account_key)
            prev_sel = (self.selector.selected or {}).get("setup_id")
            self.selector.select(rows, cfg=ac, regime=view.regime, data_ok=data_ok, new_data=new_data, now=now, snapshot_id=snapshot_id,
                                 account_key=account_key, per_strategy=res["per_strategy"],
                                 ml_bonus=(lambda r: self.ml.rank_adjust(r, view)) if self.ml is not None and self.ml.cfg.mode == "ASSIST" else None)
            cur_sel = (self.selector.selected or {}).get("setup_id")
            if cur_sel != prev_sel:
                events.append(("SELECTION_CHANGED", self.tracker.get(cur_sel) if cur_sel else {"setup_id": None}))
            for sid, ps in res["per_strategy"].items():
                f = self.funnel[sid]
                f["scans"] += 1
                f["drafts"] += ps.get("drafts", 0)
                f["below_watch"] += ps.get("below_watch", 0)
                for st, n in (ps.get("published") or {}).items():
                    f["published_" + st] += n
                if ps["status"] != "OK":
                    f["not_scanned_" + ps["status"]] += 1
            for kind, r in events:
                if r and r.get("record"):
                    sid = r["record"]["strategy_id"]
                    self.funnel[sid]["event_" + kind] += 1
            self.view = view
            self.scan_result = res
            self.scans += 1
            self.last_scan_at = iso(now)
            self.last_scan_ms = round((time.monotonic() - t0) * 1000, 1)
        for kind, r in events:
            if kind in ("NEW_EARLY", "NEW_CONFIRMED", "STAGE_EARLY", "STAGE_CONFIRMED", "INVALIDATED", "EXPIRED", "MISSED_ENTRY") and r and r.get("record"):
                rec = r["record"]
                self.log.info("AUTO", kind, f"{rec['strategy_id']} {rec['direction']} {rec['timeframe']}: {kind} (wynik {rec.get('setup_score')})",
                              {"setup_id": r["setup_id"]})
        self.bus.publish("auto", self.status(compact=True))
        return events

    # ------------------------------------------------------------ outputs for the decision
    def selected_row(self) -> dict | None:
        sel = self.selector.selected
        if not sel:
            return None
        r = self.tracker.get(sel["setup_id"])
        return r if r and r["status"] == "ACTIVE" and not r["stale"] else None

    def decision_inputs(self) -> tuple[dict | None, dict | None, dict]:
        """(setup, levels, active) for decision.build."""
        cfg = self.cfg_store.get().active
        r = self.selected_row()
        st = self.selector.state
        reg = st.get("regime") or {}
        local_dir = ((reg.get("per_tf") or {}).get(reg.get("local_tf") or "M15") or {}).get("direction")
        bias = {"UP": "LONG", "DOWN": "SHORT"}.get(local_dir, "NEUTRAL")
        if r is None:
            return None, None, {"regime": reg, "bias": bias, "trade_allowed": True, "reason_codes": st.get("reason_codes")}
        rec = r["record"]
        setup = {"setup_id": r["setup_id"], "created_at": r["first_seen_at"], "strategy_id": rec["strategy_id"], "strategy_version": rec["strategy_version"],
                 "strategy_name": rec.get("strategy_name"), "profile": "ACTIVE", "setup_tf": rec["timeframe"], "direction": rec["direction"],
                 "state": r["stage"], "signal_stage": r["stage"], "state_changed_at": r["stage_changed_at"], "version": r["version"],
                 "setup_score": rec.get("setup_score"), "horizon": rec.get("horizon"), "countertrend": rec.get("countertrend"),
                 "invalidation_level": rec.get("invalidation_level"), "missing_confirmations": rec.get("missing_confirmations"),
                 "entry_plan": rec.get("entry_plan"), "event_id": rec.get("event_id"), "synthetic": rec.get("synthetic")}
        levels = {"rule_version": f"{rec['strategy_id']}-{rec['strategy_version']}", "status": "AVAILABLE" if rec.get("targets") and rec.get("stop_loss") else "UNAVAILABLE",
                  "side": rec["direction"], "stop_loss": rec.get("stop_loss"), "invalidation_level": rec.get("invalidation_level"),
                  "entry_zone": (rec.get("entry_plan") or {}).get("zone"), "targets": rec.get("targets") or [], "exit_rules": rec.get("exit_rules"),
                  "reasons": [] if rec.get("targets") else ["NO_VALID_TARGET"]}
        toggle = cfg.strategies.get(rec["strategy_id"])
        return setup, levels, {"regime": reg, "bias": rec["direction"], "trade_allowed": True if toggle is None else toggle.trade,
                               "reason_codes": st.get("reason_codes")}

    def hypothetical_entry(self) -> float | None:
        r = self.selected_row()
        if not r:
            return None
        ep = r["record"].get("entry_plan") or {}
        return ep.get("trigger_level") or ep.get("reference_price")

    def mark_entered(self, setup_id: str, reason: str) -> None:
        self.tracker.mark_entered(setup_id, reason, iso(utcnow()))

    # ------------------------------------------------------------ API
    def status(self, compact: bool = False) -> dict:
        cfg = self.cfg_store.get()
        ac = cfg.active
        st = dict(self.selector.state)
        sel = st.get("selected")
        sel_row = self.tracker.get(sel["setup_id"]) if sel else None
        out = {"contract": CONTRACT, "profile": ac.profile, "strategy_mode": ac.strategy_mode, "manual_strategy_id": ac.manual_strategy_id,
               "system_state": st.get("system_state") if ac.profile == "ACTIVE" else "DISABLED_PROFILE_ORIGINAL",
               "regime": st.get("regime"), "selected_strategy_id": (sel or {}).get("strategy_id"),
               "selected_strategy_version": (sel or {}).get("strategy_version"), "selected": public(sel_row),
               "selection_reason_codes": st.get("reason_codes"), "candidate_ranking": st.get("candidate_ranking") or [],
               "alternative": st.get("alternative"), "selected_at": st.get("selected_at"), "last_evaluated_at": st.get("last_evaluated_at"),
               "snapshot_id": st.get("snapshot_id"), "data_status": self.data_status, "last_change": st.get("last_change"),
               "manual_fit": st.get("manual_fit"), "scan_ms": self.last_scan_ms, "scans": self.scans,
               "per_strategy": st.get("per_strategy") or self.scan_result.get("per_strategy")}
        if not compact:
            out["setups"] = [public(r) for r in self.tracker.recent(60)]
            out["funnel"] = {k: dict(v) for k, v in self.funnel.items()}
            out["strategies"] = [{**d, "scan": (ac.strategies.get(d["strategy_id"]).scan if ac.strategies.get(d["strategy_id"]) else True),
                                  "trade": (ac.strategies.get(d["strategy_id"]).trade if ac.strategies.get(d["strategy_id"]) else True)}
                                 for d in registry.describe()]
            out["why_no_setup"] = self.why_no_setup()
        return out

    def why_no_setup(self) -> list[str]:
        st = self.selector.state
        out = []
        if self.data_status != "OK":
            out.append(f"Dane: {self.data_status} – nowe setupy nie są tworzone")
        reg = st.get("regime") or {}
        if reg.get("state"):
            out.append(f"Reżim {reg.get('state')} ({reg.get('reason') or ''})")
        for sid, ps in (st.get("per_strategy") or {}).items():
            if ps.get("status") != "OK":
                out.append(f"{sid}: {ps['status']} {', '.join(ps.get('reasons') or [])[:80]}")
            elif not ps.get("published"):
                out.append(f"{sid}: {', '.join(ps.get('reasons') or ['brak struktury'])[:90]}")
        for rc in st.get("reason_codes") or []:
            out.append("Selektor: " + rc)
        return out[:16]

    def selection_log(self, limit: int = 30) -> list[dict]:
        return self.db.query("SELECT id, at, strategy_mode, previous_strategy, selected_strategy, selected_setup, reason, snapshot_id FROM strategy_selection_log ORDER BY id DESC LIMIT ?",
                             (limit,))
