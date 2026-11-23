"""DECISION_TREE_SIGNAL_RANKER (Apollo23 TASK 005) - a separate family / schema / registry namespace; the legacy DECISION_TREE, XGBOOST,
MLService.rank_adjust, StrategyAutoSelector and DecisionCoordinator are untouched.

Two CART heads on one candidate-set snapshot:
  net_r_regressor  (DecisionTreeRegressor)   -> expected after-cost net_R of the exact candidate plan (costs are in the label, never re-subtracted)
  positive_net_r   (DecisionTreeClassifier)  -> P(net_R > 0), calibrated (sigmoid) only on a strictly later block, else UNCALIBRATED
rank_utility = expected_net_R - lambda x uncertainty_R; conservative_net_R = leaf mean - z x leaf standard error (event-group support).
NO_TRADE / ABSTAIN are first-class outputs. Default mode SHADOW (never changes selection); ASSIST may only reorder / abstain among
eligibility-passing candidates. No signal creation, no entry / SL / TP / size change, no order path.
"""
from __future__ import annotations

import hashlib
import json
import math
import numbers
from dataclasses import asdict, dataclass, field

SCHEMA = "MQ-DT-SIGNAL-RANKER-1.0.0"
FEATURE_SCHEMA = "MQ-DT-RANK-FEAT-1.0.0"
LABEL_VERSION = "MQ-DT-NETR-LABEL-1"
MARKETS = ("FOREX", "CRYPTO", "INDICES", "FOMO_STOCK_PERPS")
DEFAULT_POLICY = {"mode": "SHADOW", "lambda_uncertainty": 0.5, "min_leaf_events": 30, "min_conservative_net_r": 0.0, "z": 1.645,
                  "max_depth": 5, "ccp_alphas": [0.0, 0.0005, 0.002, 0.01], "purge_s": 0, "embargo_s": 0, "calib_min": 1000}


class CandidateError(ValueError):
    pass


def _real(v, finite: bool = True) -> bool:
    """A real number (bool is not a number; numpy scalars are); `finite` also rejects NaN / inf."""
    return isinstance(v, numbers.Real) and not isinstance(v, bool) and (not finite or math.isfinite(v))


def _missing_inputs(c: Candidate) -> list[str]:
    # 1.46: unknown spread / slippage / funding (None or non-finite) was silently priced as 0.0 - only commission_R was checked
    out = []
    if not all(_real(v) for v in (c.spread, c.commission_R, c.slippage_R, c.funding_R)):
        out.append("COST_UNKNOWN")
    if not _real(c.setup_score):
        out.append("SETUP_SCORE_MISSING")
    return out


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    strategy_id: str
    source: str                      # ACTIVE / SH / SCALP / PACK / QUANT / BASKET
    market: str
    instrument: str
    timeframe: str
    direction: str                   # LONG / SHORT
    decision_ts: float
    feature_as_of: float
    event_group_id: str
    entry: float
    stop: float
    target: float
    setup_score: float = 0.0
    spread: float = 0.0
    commission_R: float | None = None
    slippage_R: float | None = 0.0
    funding_R: float | None = 0.0
    atr: float | None = None
    trade_allowed: bool = True
    expires_at: float | None = None
    status: str = "READY"
    extra: dict = field(default_factory=dict)

    def validate(self) -> list[str]:
        bad = []
        if self.direction not in ("LONG", "SHORT"):
            bad.append("BAD_DIRECTION")
        if self.market not in MARKETS:
            bad.append("UNSUPPORTED_MARKET")
        vals = (self.entry, self.stop, self.target)
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in vals):
            bad.append("NON_FINITE_PLAN")
            return bad
        s = 1 if self.direction == "LONG" else -1
        if s * (self.entry - self.stop) <= 0:
            bad.append("STOP_WRONG_SIDE")
        if s * (self.target - self.entry) <= 0:
            bad.append("TARGET_WRONG_SIDE")
        if self.feature_as_of > self.decision_ts + 1.0:
            bad.append("FUTURE_FEATURE")
        if self.expires_at is not None and self.expires_at <= self.decision_ts:
            bad.append("EXPIRED")
        if self.status != "READY":
            bad.append(f"SOURCE_{self.status}")
        bad.extend(_missing_inputs(self))                               # 1.46: any unknown cost component -> COST_UNKNOWN (was commission only)
        if not self.trade_allowed:
            bad.append("TRADE_NOT_ALLOWED")
        return bad

    @property
    def risk(self) -> float:
        return abs(self.entry - self.stop)


def features(c: Candidate) -> list[float]:
    """Point-in-time plan / cost / context features (no outcome, no future bar, no hindsight)."""
    r = c.risk or 1e-12
    rr = abs(c.target - c.entry) / r
    miss = _missing_inputs(c)                                           # 1.46: unknown cost / score is NaN, never a 0.0 (under-stated cost_R)
    cost_R = math.nan if "COST_UNKNOWN" in miss else (c.spread / r) + c.commission_R + c.slippage_R + c.funding_R
    score = math.nan if "SETUP_SCORE_MISSING" in miss else c.setup_score
    tf_min = {"M1": 1, "M3": 3, "M5": 5, "M10": 10, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "H8": 480, "D1": 1440}.get(c.timeframe.upper(), 0)
    hour = int((c.decision_ts % 86400) // 3600)
    return [rr, cost_R, score, (r / c.atr) if c.atr else -1.0, 1.0 if c.direction == "LONG" else -1.0, math.log1p(tf_min),
            float(MARKETS.index(c.market)), math.sin(2 * math.pi * hour / 24), math.cos(2 * math.pi * hour / 24)]


FEATURE_NAMES = ["rr", "cost_R", "setup_score", "risk_atr", "dir", "log_tf_min", "market_code", "hour_sin", "hour_cos"]


def net_r_label(c: Candidate, exit_price: float | None, filled: bool = True) -> dict:
    """net_R = gross_R - spread_R - commission_R - slippage_R - funding_R (each component kept for audit)."""
    if not filled:
        return {"label_status": "NO_ENTRY", "net_R": None}
    if "COST_UNKNOWN" in _missing_inputs(c):                            # 1.46: unknown slippage / funding / spread no longer labelled as 0 cost
        return {"label_status": "COST_UNKNOWN", "net_R": None}
    if exit_price is None:
        return {"label_status": "UNRESOLVED", "net_R": None}
    s = 1 if c.direction == "LONG" else -1
    gross = s * (exit_price - c.entry) / c.risk
    spread_R = c.spread / c.risk
    net = gross - spread_R - c.commission_R - c.slippage_R - c.funding_R
    return {"label_status": "LABELED", "label_version": LABEL_VERSION, "gross_R": gross, "spread_R": spread_R, "commission_R": c.commission_R,
            "slippage_R": c.slippage_R, "funding_or_borrow_R": c.funding_R, "net_R": net, "positive_net_R": net > 0}


def chrono_split(samples: list[dict], fractions=(0.6, 0.2, 0.2), purge_s: float = 0.0, embargo_s: float = 0.0) -> dict:
    """samples: {decision_ts, label_end_ts, event_group_id, ...}. Whole event groups stay in one split; rows whose label interval overlaps the
    next split's start (purge) or lie within the embargo after a split are dropped."""
    groups: dict[str, list[dict]] = {}
    for s in samples:
        groups.setdefault(s["event_group_id"], []).append(s)
    order = sorted(groups, key=lambda g: min(x["decision_ts"] for x in groups[g]))
    n = len(order)
    cut1, cut2 = int(n * fractions[0]), int(n * (fractions[0] + fractions[1]))
    parts = [order[:cut1], order[cut1:cut2], order[cut2:]]
    out = []
    for k, gs in enumerate(parts):
        rows = [x for g in gs for x in groups[g]]
        if k + 1 < len(parts) and parts[k + 1]:
            nxt = min(x["decision_ts"] for g in parts[k + 1] for x in groups[g])
            rows = [x for x in rows if x["label_end_ts"] + purge_s < nxt]
        if k > 0 and parts[k - 1]:
            prev_end = max(x["label_end_ts"] for g in parts[k - 1] for x in groups[g])
            rows = [x for x in rows if x["decision_ts"] > prev_end + embargo_s]
        out.append(rows)
    return {"fit": out[0], "calib": out[1], "test": out[2]}


class RankerBundle:
    def __init__(self, reg, clf, calib, leaf_stats: dict, manifest: dict):
        self.reg, self.clf, self.calib, self.leaf_stats, self.manifest = reg, clf, calib, leaf_stats, manifest

    def predict(self, c: Candidate, z: float | None = None) -> dict:
        import numpy as np
        z = DEFAULT_POLICY["z"] if z is None else float(z)             # 1.46: policy z was ignored (always DEFAULT_POLICY["z"])
        x = np.array([features(c)])
        leaf = int(self.reg.apply(x)[0])
        st = self.leaf_stats.get(leaf, {"events": 0, "mean": 0.0, "std": float("inf")})
        exp = float(self.reg.predict(x)[0])
        raw_p = float(self.clf.predict_proba(x)[0][list(self.clf.classes_).index(True)]) if True in list(self.clf.classes_) else 0.0
        if self.calib is not None:
            a, b = self.calib
            p, pst = 1 / (1 + math.exp(-(a * raw_p + b))), "CALIBRATED"
        else:
            p, pst = None, "UNCALIBRATED"
        se = st["std"] / math.sqrt(st["events"]) if st["events"] > 0 and math.isfinite(st["std"]) else float("inf")
        return {"expected_net_R": exp, "p_positive_net_R": p, "probability_status": pst, "leaf_id": leaf, "leaf_support_events": st["events"],
                "leaf_net_r": st, "uncertainty_R": se, "conservative_net_R": st["mean"] - z * se if math.isfinite(se) else None}


def _fit_sigmoid(p, y):
    """Platt scaling on (raw_p, y) by Newton iterations; returns (a, b)."""
    a, b = 1.0, 0.0
    for _ in range(50):
        ga = gb = haa = hab = hbb = 0.0
        for pi, yi in zip(p, y):
            q = 1 / (1 + math.exp(-(a * pi + b)))
            d = q - yi
            w = q * (1 - q) + 1e-9
            ga += d * pi
            gb += d
            haa += w * pi * pi
            hab += w * pi
            hbb += w
        det = haa * hbb - hab * hab
        if abs(det) < 1e-12:
            break
        a -= (hbb * ga - hab * gb) / det
        b -= (-hab * ga + haa * gb) / det
    return a, b


def train(samples: list[dict], policy: dict | None = None) -> dict:
    """samples: {candidate: Candidate, net_R, positive_net_R, decision_ts, label_end_ts, event_group_id}. Only LABELED, mature rows."""
    import numpy as np
    from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor
    pol = {**DEFAULT_POLICY, **(policy or {})}
    rows = [s for s in samples if s.get("net_R") is not None]
    n_lab = len(rows)
    rows = [s for s in rows if not _missing_inputs(s["candidate"])]    # 1.46: unknown cost / score rows were trained as 0-cost (NaN features)
    excluded = n_lab - len(rows)
    sp = chrono_split(rows, purge_s=pol["purge_s"], embargo_s=pol["embargo_s"])
    fit, cal, test = sp["fit"], sp["calib"], sp["test"]
    if len({s["event_group_id"] for s in fit}) < 2 * pol["min_leaf_events"]:
        return {"status": "NOT_READY", "reason": "INSUFFICIENT_EVENT_GROUPS", "counts": {k: len(v) for k, v in sp.items()},
                "excluded_missing_inputs": excluded}
    X = np.array([features(s["candidate"]) for s in fit])
    y = np.array([s["net_R"] for s in fit])
    yb = np.array([bool(s["net_R"] > 0) for s in fit])
    n_groups = len({s["event_group_id"] for s in fit})
    min_leaf = max(5, int(pol["min_leaf_events"] * len(fit) / max(1, n_groups)))
    best = None
    for alpha in pol["ccp_alphas"]:                                    # pruning chosen on the calibration (inner validation) block
        reg = DecisionTreeRegressor(max_depth=pol["max_depth"], min_samples_leaf=min_leaf, ccp_alpha=alpha, random_state=0).fit(X, y)
        if cal:
            Xc = np.array([features(s["candidate"]) for s in cal])
            mse = float(np.mean((reg.predict(Xc) - np.array([s["net_R"] for s in cal])) ** 2))
        else:
            mse = float("inf")
        if best is None or mse < best[0] - 1e-12:
            best = (mse, alpha, reg)
    _, alpha, reg = best
    clf = DecisionTreeClassifier(max_depth=pol["max_depth"], min_samples_leaf=min_leaf, ccp_alpha=0.0, random_state=0).fit(X, yb)
    leaves = reg.apply(X)
    leaf_stats = {}
    for lf in set(int(v) for v in leaves):
        idx = [i for i, v in enumerate(leaves) if int(v) == lf]
        grp = {}
        for i in idx:                                                   # one value per independent event group
            grp.setdefault(fit[i]["event_group_id"], []).append(fit[i]["net_R"])
        vals = [sum(v) / len(v) for v in grp.values()]
        m = sum(vals) / len(vals)
        sd = math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1)) if len(vals) > 1 else float("inf")
        leaf_stats[lf] = {"events": len(vals), "rows": len(idx), "mean": m, "std": sd}
    calib = None
    if len(cal) >= pol["calib_min"]:
        raw = [float(clf.predict_proba(np.array([features(s["candidate"])]))[0][list(clf.classes_).index(True)]) for s in cal]
        calib = _fit_sigmoid(raw, [1.0 if s["net_R"] > 0 else 0.0 for s in cal])
    manifest = {"schema": SCHEMA, "feature_schema": FEATURE_SCHEMA, "label_version": LABEL_VERSION, "ccp_alpha": alpha, "min_samples_leaf": min_leaf,
                "policy": pol, "split": {k: len(v) for k, v in sp.items()}, "excluded_missing_inputs": excluded,
                "data_hash": hashlib.sha256(json.dumps([[s["event_group_id"], s["decision_ts"], s["net_R"]] for s in rows]).encode()).hexdigest()[:16]}
    bundle = RankerBundle(reg, clf, calib, leaf_stats, manifest)
    return {"status": "READY", "bundle": bundle, "manifest": manifest, "test": test,
            "evaluation": evaluate_policies(bundle, test, pol) if test else None}


def rank(bundle: RankerBundle | None, candidates: list[Candidate], policy: dict | None = None) -> dict:
    pol = {**DEFAULT_POLICY, **(policy or {})}
    out = {"schema": SCHEMA, "mode": pol["mode"], "apply_to_selection": pol["mode"] == "ASSIST", "ranked_candidates": [], "selected_candidate_id": None,
           "decision": "NO_TRADE", "reason_codes": []}
    if not candidates:
        return {**out, "reason_codes": ["NO_CANDIDATES"]}
    if bundle is None:
        return {**out, "decision": "FALLBACK_BASELINE", "reason_codes": ["MODEL_NOT_READY"]}
    elig = []
    for c in candidates:
        bad = c.validate()
        row = {"candidate_id": c.candidate_id, "strategy_id": c.strategy_id, "eligible": not bad, "reason_codes": bad}
        if not bad:
            pr = bundle.predict(c, z=pol["z"])
            if pr["leaf_support_events"] < pol["min_leaf_events"]:
                row["reason_codes"].append("LOW_LEAF_SUPPORT")
            if pr["conservative_net_R"] is None or pr["conservative_net_R"] <= pol["min_conservative_net_r"]:
                row["reason_codes"].append("CONSERVATIVE_NET_R_BELOW_MIN")
            row.update(pr, rank_utility=pr["expected_net_R"] - pol["lambda_uncertainty"] * (pr["uncertainty_R"] if math.isfinite(pr["uncertainty_R"]) else 1e9))
            row["eligible"] = not row["reason_codes"]
        out["ranked_candidates"].append(row)
        if row["eligible"]:
            elig.append(row)
    dirs = {next(c.direction for c in candidates if c.candidate_id == r["candidate_id"]) for r in elig}
    if len(dirs) > 1:
        groups = {}
        elig_ids = {r["candidate_id"] for r in elig}
        for c in candidates:
            if c.candidate_id in elig_ids:                              # 1.46: an ineligible (e.g. EXPIRED) opposite candidate forced ABSTAIN
                groups.setdefault(c.event_group_id, set()).add(c.direction)
        if any(len(v) > 1 for v in groups.values()):
            return {**out, "decision": "ABSTAIN", "reason_codes": ["SAME_EVENT_OPPOSING_CANDIDATES"]}
    # 1.46: `rank_utility or -1e18` sorted a real 0.0 like a missing value (behind negative utilities)
    out["ranked_candidates"].sort(key=lambda r: (-r["rank_utility"] if r.get("rank_utility") is not None else math.inf, r["candidate_id"]))
    if not elig:
        codes = sorted({c for r in out["ranked_candidates"] for c in r["reason_codes"]})
        return {**out, "decision": "ABSTAIN" if any(r.get("leaf_id") is not None for r in out["ranked_candidates"]) else "NO_TRADE", "reason_codes": codes}
    top = max(elig, key=lambda r: (r["rank_utility"], r["candidate_id"]))
    return {**out, "selected_candidate_id": top["candidate_id"], "decision": "SELECT"}


def evaluate_policies(bundle: RankerBundle, test: list[dict], pol: dict) -> dict:
    """Same candidate sets for: NO_TRADE, setup_score baseline, ranker. One action per event group (policy net R), coverage."""
    sets: dict[str, list[dict]] = {}
    for s in test:
        sets.setdefault(s["event_group_id"], []).append(s)
    res = {"NO_TRADE": [], "SETUP_SCORE_BASELINE": [], "DT_RANKER": []}
    for g in sets.values():
        res["NO_TRADE"].append(0.0)
        best = max(g, key=lambda s: (s["candidate"].setup_score, s["candidate"].candidate_id))
        res["SETUP_SCORE_BASELINE"].append(best["net_R"])
        r = rank(bundle, [s["candidate"] for s in g], {**pol, "mode": "SHADOW"})
        pick = next((s for s in g if s["candidate"].candidate_id == r["selected_candidate_id"]), None)
        res["DT_RANKER"].append(pick["net_R"] if pick else None)
    def summ(v):
        acted = [x for x in v if x is not None]
        return {"sets": len(v), "acted": len(acted), "coverage": len(acted) / len(v) if v else None, "total_net_R": sum(acted),
                "mean_net_R_per_action": sum(acted) / len(acted) if acted else None}
    return {k: summ(v) for k, v in res.items()}


_STR_FIELDS = ("candidate_id", "strategy_id", "source", "market", "instrument", "timeframe", "direction", "event_group_id", "status")
_TIME_FIELDS = ("decision_ts", "feature_as_of")                         # required, finite (NaN would pass the FUTURE_FEATURE check)
_PLAN_FIELDS = ("entry", "stop", "target")                              # required numbers; non-finite is reported by validate() (NON_FINITE_PLAN)
_OPT_FINITE = ("expires_at", "atr")                                     # optional, finite when given
_OPT_REAL = ("setup_score", "spread", "commission_R", "slippage_R", "funding_R")   # optional numbers; non-finite -> COST_UNKNOWN / SETUP_SCORE_MISSING
_UNKNOWN_IF_ABSENT = ("setup_score", "spread", "slippage_R", "funding_R")


def candidate_from_dict(d: dict) -> Candidate:
    if not isinstance(d, dict):                                         # 1.46: a non-object raised a raw TypeError (500), not CandidateError
        raise CandidateError("CANDIDATE_NOT_OBJECT")
    keys = {f for f in Candidate.__dataclass_fields__}
    bad = [k for k in d if k not in keys]
    if bad:
        raise CandidateError(f"UNKNOWN_FIELDS: {bad}")
    # 1.46: field types were not checked - e.g. decision_ts "abc" crashed validate() / features() inside rank() (500)
    wrong = [k for k in _STR_FIELDS if k in d and not isinstance(d[k], str)]
    wrong += [k for k in _TIME_FIELDS if k in d and not _real(d[k])]
    wrong += [k for k in _PLAN_FIELDS if k in d and not _real(d[k], finite=False)]
    wrong += [k for k in _OPT_FINITE if d.get(k) is not None and not _real(d[k])]
    wrong += [k for k in _OPT_REAL if d.get(k) is not None and not _real(d[k], finite=False)]
    wrong += [k for k, t in (("trade_allowed", bool), ("extra", dict)) if k in d and not isinstance(d[k], t)]
    if wrong:
        raise CandidateError(f"BAD_FIELD_TYPES: {wrong}")
    # 1.46: a cost / score field absent from the payload is UNKNOWN (None -> COST_UNKNOWN), not the 0.0 dataclass default
    d = {**{k: None for k in _UNKNOWN_IF_ABSENT}, **d}
    try:
        return Candidate(**d)
    except TypeError as exc:
        raise CandidateError(str(exc)) from None


def to_dict(c: Candidate) -> dict:
    return asdict(c)
