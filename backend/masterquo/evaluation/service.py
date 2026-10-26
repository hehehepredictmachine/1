"""EvaluationService - SHADOW ledger of every setup from both execution paths (PMW-EVAL-SERVICE-1).

Inputs (listeners, read-only):
  * ActiveEngine scan events: S01-S12 setups at the CONFIRMED stage (new, promoted or revised - every version once);
  * SHService cycles: SCALPING / HEDGING setups that carry levels (status READY), including the ones the coordinator, the risk
    engine or STOP blocked afterwards - logging is never conditional on a gate (no filter-dependent sample).
Each setup -> SetupCandidate (common contract) -> assess() (P of the named event, net EV, p*, uncertainty, execution, portfolio)
-> one row in the shared prediction-ledger format (mm.ledger, own file data/evaluation/ledger.sqlite).
Outcomes mature from CLOSED M1 bars after the horizon (evaluation/outcome.py). The report compares the SHADOW decision with what
happened; it is evidence for a later decision, not a performance claim.

Nothing here sends, sizes, blocks or changes an order: no reference to ExecutionGateway, PaperBroker, PositionManager or SHExecutor,
no terminal calls.
"""
from __future__ import annotations

import json
import logging
import math
import time
from pathlib import Path

from ..mm.ledger import Ledger
from . import contract as K
from . import engine as E
from . import exposure as X
from . import outcome as O

VERSION = "PMW-EVAL-SERVICE-1"
ACTIVE_KINDS = ("NEW_CONFIRMED", "STAGE_CONFIRMED", "PLAN_REVISED")
log = logging.getLogger("masterquo.evaluation")


def _default_dir() -> Path:
    from ..paths import data_dir
    return data_dir() / "evaluation"


class EvaluationService:
    def __init__(self, cfg_store, bridge, db, *, ml=None, data_dir: Path | None = None, clock=time.time):
        self.cfg_store, self.bridge, self.db, self.ml, self.clock = cfg_store, bridge, db, ml, clock
        self.ledger = Ledger(Path(data_dir or _default_dir()) / "ledger.sqlite")
        self.counters = {"logged": 0, "duplicates": 0, "invalid": 0, "errors": 0, "matured": 0}
        self.last_error: str | None = None
        self.last_assessment: dict | None = None
        self._last_mature = 0.0

    # ------------------------------------------------------------------ inputs
    def on_active_events(self, events: list, view) -> None:
        if view is None:
            return
        for kind, r in events:
            if kind not in ACTIVE_KINDS or not r or not r.get("record") or r.get("stage") != "CONFIRMED" or r.get("status") != "ACTIVE":
                continue
            self._guard(self._active, r, view)
        self.mature()

    def on_sh_cycle(self, evals: dict, *, inst: str, symbol: str, snap: dict | None, now: float) -> None:
        for su in (evals or {}).values():
            if su.get("status") == "READY":
                self._guard(self._sh, su, inst, snap, now)
        self.mature(now)

    def _guard(self, fn, *a) -> None:
        try:
            fn(*a)
        except K.ContractError as exc:
            self.counters["invalid"] += 1
            self.last_error = f"CONTRACT:{exc}"
        except Exception as exc:  # noqa: BLE001 - SHADOW never breaks a scan or a cycle
            self.counters["errors"] += 1
            self.last_error = f"{type(exc).__name__}: {exc}"[:300]
            log.exception("evaluation failed")

    # ------------------------------------------------------------------ S01-S12
    def _active(self, r: dict, view) -> None:
        now = self.clock()
        q = {"bid": view.bid, "ask": view.ask}
        info = getattr(self.bridge, "symbol_info", None) or {}
        cost, known = self._active_cost(info)
        c = K.from_active_row(r, symbol=view.symbol, instrument=self._inst(), quote=q, regime=view.regime, now=now,
                              data_status=getattr(view, "data_status", None) or ("OK" if not r.get("stale") else "STALE"),
                              cost_price=cost, commission_known=known).validate()
        self._log(c, self._active_prob(r, view), cost)

    def _active_cost(self, info: dict) -> tuple[float | None, bool | None]:
        """Commission (both sides) + slippage stress in PRICE units for 1 lot; spread is already in the entry price."""
        try:
            from ..risk.costs import resolve_commission
            cfg = self.cfg_store.get()
            with self.bridge._lock:
                deals = list(getattr(self.bridge, "deals", []) or [])
            comm = resolve_commission(cfg.costs, deals, cfg.mt5.symbol).get("per_lot_per_side")
            tv, ts = float(info.get("trade_tick_value") or 0), float(info.get("trade_tick_size") or info.get("point") or 0)
            mpp = tv / ts if tv > 0 and ts > 0 else None
            slip = (cfg.costs.slippage_stress_points or 0.0) * float(info.get("point") or 0.0) * 2
            c = slip + (2 * comm / mpp if comm is not None and mpp else 0.0)
            return c, comm is not None and mpp is not None
        except Exception:  # noqa: BLE001 - unknown cost is reported, not invented
            return None, None

    def _active_prob(self, r: dict, view) -> dict | None:
        """Read-only: the champion's prediction for THIS setup version if the decision path already made one. The evaluation layer
        never calls the model itself - an extra prediction would enter the ML drift sample (live Brier) and could change the ML
        router state, which is a behaviour change, not an observation."""
        if self.ml is None:
            return None
        try:
            mid = self.ml.registry.champion_id
            row = self.ml.db.one("SELECT calibrated_probability AS p, readiness, contract_json FROM ml_predictions WHERE setup_id=? AND "
                                 "setup_version=? AND model_id=? AND role='CHAMPION'", (r["setup_id"], r["version"], mid)) if mid else None
        except Exception:  # noqa: BLE001
            return None
        if not row or row["p"] is None:
            return None
        ct = json.loads(row["contract_json"] or "{}")
        return {"value": float(row["p"]), "calibrated": row["readiness"] == "READY", "event": ct.get("target_definition"),
                "source": mid, "version": ct.get("model_version"), "n_calibration": None, "event_matches": False}

    # ------------------------------------------------------------------ SCALPING / HEDGING
    def _sh(self, su: dict, inst: str, snap: dict | None, now: float) -> None:
        c = K.from_sh_setup(su, regime=(snap or {}).get("regime")).validate()
        costs = su.get("costs") or {}
        extra = None
        if costs.get("round_trip_price") is not None:
            extra = max(0.0, float(costs["round_trip_price"]) - float(costs.get("spread") or 0.0))   # spread already in the Ask/Bid entry
        pr = su.get("probability") or {}
        prob = None
        if pr.get("value") is not None:
            prob = {"value": pr["value"], "calibrated": pr.get("status") == "SKALIBROWANE", "event": pr.get("event"),
                    "source": "sh_tp_model", "version": pr.get("model_version"), "event_matches": True,
                    "n_calibration": self._sh_n_cal(inst, su["strategy"])}
        self._log(c, prob, extra)

    @staticmethod
    def _sh_n_cal(inst: str, strat: str) -> int | None:
        try:
            from ..sh import tpmodel as TM
            reg = json.loads((TM.root(inst, strat) / "registry.json").read_text(encoding="utf-8"))
            run = next((x for x in reg.get("runs") or [] if x.get("run_id") == reg.get("active")), None)
            return int(((run or {}).get("split") or {}).get("cal") or 0) or None
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------ ledger
    def _inst(self) -> str:
        try:
            return self.cfg_store.get().assets.active
        except Exception:  # noqa: BLE001
            return ""

    def _log(self, c: K.SetupCandidate, prob: dict | None, extra_cost: float | None) -> dict:
        items = X.positions(self.db, c.symbol)
        a = E.assess(c, prob=prob, extra_cost=extra_cost, exposure=X.for_candidate(items, c.symbol, c.direction))
        ad = a.to_dict()
        ok = self.ledger.log(pred_id=c.key(), model_id=f"{E.VERSION}/{c.engine}", artifact_id=(prob or {}).get("source"),
                             feature_schema=K.VERSION, symbol=c.symbol, timeframe=c.timeframe, source_ts=c.decision_ts,
                             available_at=c.decision_ts, matures_at=c.decision_ts + c.horizon_s, horizon=f"{int(c.horizon_s)}s",
                             kind="SETUP_ASSESSMENT", payload={"candidate": c.to_dict(), "assessment": ad},
                             quality=(c.data_quality or {}).get("status") or "UNKNOWN")
        self.counters["logged" if ok else "duplicates"] += 1
        if ok:
            self.last_assessment = ad
        return ad

    def mature(self, now: float | None = None) -> int:
        now = self.clock() if now is None else now
        if now - self._last_mature < 30.0:
            return 0
        self._last_mature = now
        try:
            bars = [b for b in self.bridge.bars("M1", include_forming=False) if b.get("open_utc")]
        except Exception:  # noqa: BLE001
            return 0
        if not bars:
            return 0
        first, last_close = O.bar_ts(bars[0]), O.bar_ts(bars[-1]) + O.M1
        sym = getattr(self.bridge, "buffer_symbol", None)
        n = self.ledger.mature(last_close, lambda row: self._resolve(row, bars, first, sym))
        self.counters["matured"] += n
        return n

    @staticmethod
    def _resolve(row: dict, bars: list[dict], first_ts: float, buffer_symbol: str | None) -> dict | None:
        if buffer_symbol and row.get("symbol") and row["symbol"] != buffer_symbol:
            return None                                   # bars of another instrument are buffered now - wait, never mislabel
        pl = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
        c, a = pl["candidate"], pl["assessment"]
        if row["source_ts"] < first_ts - O.M1:
            return {"status": "NO_BARS", "reason": "okno setupu starsze niż bufor M1 (np. po restarcie) – wynik nieznany"}
        out = O.label(c, O.window(bars, row["source_ts"], row["matures_at"]), cost_r=float(a.get("cost_r") or 0.0))
        out["event_hit"] = O.event_hit(c["engine"], out)
        return out

    # ------------------------------------------------------------------ outputs
    def status(self) -> dict:
        return {"version": VERSION, "mode": "SHADOW", "contract": K.VERSION, "engine": E.VERSION, "counters": dict(self.counters),
                "pending": len(self.ledger.pending()), "last_error": self.last_error, "ledger": str(self.ledger.path),
                "note": "ocena każdego setupu obu ścieżek; nie blokuje ani nie wysyła zleceń"}

    def assessments(self, engine: str | None = None, limit: int = 50) -> list[dict]:
        q = "SELECT * FROM predictions WHERE kind='SETUP_ASSESSMENT'" + (" AND model_id=?" if engine else "") + " ORDER BY source_ts DESC LIMIT ?"
        args = ((f"{E.VERSION}/{engine}",) if engine else ()) + (int(limit),)
        with self.ledger._lock:
            rows = [dict(r) for r in self.ledger.c.execute(q, args).fetchall()]
        out = []
        for r in rows:
            pl = json.loads(r["payload"])
            c, a = pl["candidate"], pl["assessment"]
            out.append({"setup_id": c["setup_id"], "engine": c["engine"], "strategy_id": c["strategy_id"], "direction": c["direction"],
                        "decision_ts": c["decision_ts"], "entry": c["entry_price"], "sl": c["stop_loss"], "targets": c["targets"],
                        "horizon_s": c["horizon_s"], "decision": a["decision"], "reasons": a["rejection_reasons"], "event": a["event"],
                        "probability": a["probability"], "probability_status": a["probability_status"],
                        "break_even_probability": a["break_even_probability"], "expected_value_r": a["expected_value_r"],
                        "expected_value_interval_r": a["expected_value_interval_r"], "gain_r": a["gain_r"], "loss_r": a["loss_r"],
                        "cost_r": a["cost_r"], "execution": a["execution_quality"].get("status"),
                        "portfolio": (a["portfolio_risk_status"] or {}).get("status"), "notes": a["notes"],
                        "outcome": json.loads(r["outcome"]) if r["outcome"] else None})
        return out

    def report(self) -> dict:
        """Matured rows per engine x SHADOW decision: event rate, mean plan R (net), Brier where a probability existed."""
        with self.ledger._lock:
            rows = [dict(r) for r in self.ledger.c.execute(
                "SELECT model_id, payload, outcome FROM predictions WHERE kind='SETUP_ASSESSMENT' AND outcome IS NOT NULL").fetchall()]
        groups: dict = {}
        for r in rows:
            pl, out = json.loads(r["payload"]), json.loads(r["outcome"])
            if out.get("status") != "MATURED":
                continue
            a = pl["assessment"]
            g = groups.setdefault((a["engine"], a["decision"]), {"n": 0, "events": 0, "r": [], "brier": [], "ambiguous": 0})
            g["n"] += 1
            g["events"] += 1 if out.get("event_hit") else 0
            g["r"].append(out["plan_r_net"])
            g["ambiguous"] += 1 if out.get("ambiguous_bars") else 0
            if a.get("probability") is not None and out.get("event_hit") is not None:
                g["brier"].append((a["probability"] - (1.0 if out["event_hit"] else 0.0)) ** 2)
        res = []
        for (eng, dec), g in sorted(groups.items()):
            n = g["n"]
            mean_r = sum(g["r"]) / n
            sd = math.sqrt(sum((x - mean_r) ** 2 for x in g["r"]) / (n - 1)) if n > 1 else None
            res.append({"engine": eng, "decision": dec, "n": n, "event_rate": round(g["events"] / n, 4),
                        "mean_plan_r_net": round(mean_r, 4), "mean_plan_r_se": round(sd / math.sqrt(n), 4) if sd is not None else None,
                        "brier": round(sum(g["brier"]) / len(g["brier"]), 4) if g["brier"] else None, "with_probability": len(g["brier"]),
                        "ambiguous_share": round(g["ambiguous"] / n, 4), "status": "OK" if n >= 30 else "SMALL_SAMPLE"})
        return {"groups": res, "matured": sum(g["n"] for g in groups.values()), "mode": "SHADOW",
                "note": "wynik planu bez BE i bez realnego wypełnienia (BINARY_PLAN_APPROX); mała próba nie pozwala wnioskować o skuteczności"}

    def exposure(self) -> dict:
        return X.portfolio(self.db)
