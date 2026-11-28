"""PMW-FEAT-SCHEMAS-1: registry of the feature schemas of the code (1.46 arch, Etap 4 pkt 2; docs/arch146/ETAP2_PROJEKT.md §3 / §4).

Before: independent feature schemas (ETAP1 rejestry_cech: "co najmniej 25") versioned by NAMES only (constants or a hash of the name
list) - a change of a formula, a seed or a missing-value policy under the same name and version was not detected anywhere (#4).
Coverage is checked, not claimed: scan_labels() reads (AST, nothing imported) every feature-schema label the code declares - constants
FEATURE_SCHEMA* / FEATURE_SET* / *FEATURES_ID anywhere, SCHEMA / VERSION* / SEMANTICS in owner modules (a module-level feature list or a
*features.py file), feature_schema= / model_feature_schema= literals, `"schema"` of a modelhub family DATA - and uncovered() lists the
labels that are neither a registered schema (id / label / alias) nor in NOT_REGISTERED (feature schema WITHOUT a fingerprint, with the
reason) nor in NOT_FEATURE_SCHEMAS (a model / artifact format found by the scan). The test requires uncovered() == {}. Feature builders
that declare no label at all (internal inputs of modelhub statistical families: arima exog, garch, breakout, rl ...) are outside the scan.

This module only DESCRIBES and MEASURES. The builders stay in their owner modules, unchanged; nothing here is called by a model, a
strategy, a gate or a writer (no decision can change):
* SCHEMAS       one entry per schema: id (the owner's schema label; `label` = the exact string artifacts carry when the owner appends
                names or a hash), version, family, owner (`module:function` of the builder), where the owner declares the label (`id_of`)
                and the feature list (`names_of`), the registry of the feature dictionary (features/catalog.py) the names belong to;
* fixture()     ONE frozen synthetic input (PMW-FEAT-FIXTURE-1): an M1 random walk from a fixed integer generator (splitmix64, prices on
                the 0.01 grid), aggregated to M5 / M15 / M30 / H1, plus independent H4 / D1 histories - SYNTHETIC, it checks formulas,
                not the market;
* fingerprint() sha256 (16 hex) of the builder's OUTPUT on that fixture, canonicalised (floats to 7 significant digits, |x| < 1e-12 = 0,
                NaN / inf named) - the identity of the FORMULA, not of the names;
* FINGERPRINTS  the frozen fingerprint of the current code per schema id; tests/test_arch146_e4_features.py recomputes them: a builder
                change without a new schema id (= version) turns the test red. A deliberate change = new version in the owner + new
                entry here (old artifacts keep their id and are never fed the new meaning - IMPL_BRIEF pkt 4);
* tag() / check_manifest()  for artifacts that will record it later: an artifact without a fingerprint is legacy-compatible (as today),
                a different fingerprint under the same id is a mismatch; check_manifest() takes the label an artifact CARRIES (resolve()).
                NOT WIRED in Etap 4 (not_done): no writer records feature_fingerprint and no loader compares it - a new manifest key and a
                load-time decision change files in data/ and loading behaviour, so they are a separate step (plan: an ADDITIVE key
                feature_fingerprint in NEW manifests only, old artifacts = LEGACY exactly as today, MISMATCH reported before it may block).
"""
from __future__ import annotations

import ast
import fnmatch
import hashlib
import importlib
import importlib.util
import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

VERSION = "PMW-FEAT-SCHEMAS-1"
FIXTURE_VERSION = "PMW-FEAT-FIXTURE-1"
SIG_DIGITS = 7                          # 7 significant digits: platform libm / SIMD round-off never reaches them, a formula change does
ZERO_ABS = 1e-12
TICK = 0.01
T0 = 1_772_409_600                      # 2026-03-02T00:00:00Z (Monday) - first M1 bar of the fixture
N_M1 = 8640                             # 6 days of M1 -> T_END = 2026-03-08T00:00:00Z (close of the last M1 bar)
T_END = T0 + N_M1 * 60
TF_MIN = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}


# ---------------------------------------------------------------------------------------------------------------------- fixture
class _Rng:
    """splitmix64: integer arithmetic only, the same stream on every platform / Python version (frozen with FIXTURE_VERSION)."""

    M = (1 << 64) - 1

    def __init__(self, seed: int):
        self.s = seed & self.M

    def u(self) -> float:
        self.s = (self.s + 0x9E3779B97F4A7C15) & self.M
        z = self.s
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & self.M
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & self.M
        return ((z ^ (z >> 31)) >> 11) / 9007199254740992.0

    def n(self) -> float:
        return self.u() + self.u() + self.u() + self.u() - 2.0      # Irwin-Hall(4) - 2: mean 0, sd 0.577 (no libm)


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _bar(t: int, o: float, h: float, lo: float, c: float, tv: float, sp: int | None) -> dict:
    return {"open_utc": _iso(t), "t": t, "o": o, "h": h, "l": lo, "c": c, "tv": tv, "spread": sp,
            "spread_price": None if sp is None else round(sp * TICK, 2), "closed": True}


def _m1() -> list[dict]:
    g = _Rng(146)
    out, p = [], 2650.0
    for k in range(N_M1):
        drift = 0.06 * (1 if (k // 720) % 2 == 0 else -1)          # alternating 12 h trends + noise (ranges, trends, reversals)
        o = p
        c = round(o + drift + 0.55 * g.n(), 2)
        h = round(max(o, c) + 0.35 * g.u(), 2)
        lo = round(min(o, c) - 0.35 * g.u(), 2)
        sp = None if k % 997 == 500 else 12 + int(18 * g.u())      # a few bars without a recorded spread (missing-value paths)
        out.append(_bar(T0 + 60 * k, o, h, lo, c, float(20 + int(140 * g.u())), sp))
        p = c
    return out


def _agg(m1: list[dict], mins: int) -> list[dict]:
    out = []
    for k in range(0, len(m1) - mins + 1, mins):
        g = m1[k:k + mins]
        out.append(_bar(g[0]["t"], g[0]["o"], max(b["h"] for b in g), min(b["l"] for b in g), g[-1]["c"], float(sum(b["tv"] for b in g)),
                        g[-1]["spread"]))
    return out


def _htf(mins: int, n: int, last_close: float, seed: int) -> list[dict]:
    """n closed bars of an independent walk ending at T_END (bar opens on the TF grid), shifted so its last close = last_close."""
    g = _Rng(seed)
    s = mins * 60
    end = T_END - T_END % s
    path, p = [], 0.0
    for _ in range(n):
        o = p
        c = o + 0.4 * (mins ** 0.5) * g.n() + 0.05 * mins ** 0.5
        path.append((o, max(o, c) + 0.2 * mins ** 0.5 * g.u(), min(o, c) - 0.2 * mins ** 0.5 * g.u(), c))
        p = c
    off = last_close - path[-1][3]
    return [_bar(end - s * (n - k), round(o + off, 2), round(h + off, 2), round(lo + off, 2), round(c + off, 2), float(500 + 40 * k), 15)
            for k, (o, h, lo, c) in enumerate(path)]


@lru_cache(maxsize=1)
def fixture() -> dict:
    """{tf: [bar dicts oldest first]} - every bar closed at T_END. Bars carry open_utc / t / o / h / l / c / tv / spread (points) /
    spread_price / closed, the keys the owners' builders read. Cached: callers must not mutate it (each builder gets copies)."""
    m1 = _m1()
    bars = {"M1": m1, **{tf: _agg(m1, TF_MIN[tf]) for tf in ("M5", "M15", "M30", "H1")}}
    bars["H4"] = _htf(240, 140, m1[-1]["c"], 7)
    bars["D1"] = _htf(1440, 90, m1[-1]["c"], 11)
    return bars


def _b(tf: str, n: int | None = None) -> list[dict]:
    src = fixture()[tf]
    return [dict(x) for x in (src[-n:] if n else src)]


def _cols(tf: str, n: int | None = None) -> dict:
    """trainhub / marketdata column layout."""
    b = _b(tf, n)
    return {"time": [x["t"] for x in b], "open": [x["o"] for x in b], "high": [x["h"] for x in b], "low": [x["l"] for x in b],
            "close": [x["c"] for x in b], "tick_volume": [x["tv"] for x in b], "spread": [x["spread"] or 0 for x in b]}


# ---------------------------------------------------------------------------------------------------------------------- canonical form
def canonical(x):
    """JSON-ready canonical form of a builder output: floats to SIG_DIGITS significant digits (|x| < ZERO_ABS -> 0), NaN / inf named,
    numpy arrays / scalars, tuples, sets and datetimes converted, dict keys sorted (by json.dumps)."""
    try:
        import numpy as np
    except ImportError:  # pragma: no cover - numpy is a bot dependency
        np = None
    if np is not None:
        if isinstance(x, np.ndarray):
            return {"__ndarray__": list(x.shape), "v": canonical(x.tolist())}
        if isinstance(x, np.generic):
            x = x.item()
    if isinstance(x, bool) or x is None or isinstance(x, str):
        return x
    if isinstance(x, int):
        return x
    if isinstance(x, float):
        if math.isnan(x):
            return "NaN"
        if math.isinf(x):
            return "Inf" if x > 0 else "-Inf"
        if abs(x) < ZERO_ABS:
            return 0.0
        return float(f"{x:.{SIG_DIGITS}g}")
    if isinstance(x, dict):
        return {str(k): canonical(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [canonical(v) for v in x]
    if isinstance(x, (set, frozenset)):
        return sorted(canonical(v) for v in x)
    if isinstance(x, datetime):
        return x.isoformat()
    if hasattr(x, "__dict__"):
        return canonical(vars(x))
    return repr(x)


def digest(x) -> str:
    return hashlib.sha256(json.dumps(canonical(x), sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------------------------------------------------- owner refs
def _attr(mod: str, name: str):
    def f():
        return getattr(importlib.import_module(mod), name)
    return f


def _literal(mod: str, text: str, value: str | None = None):
    """The id is a literal in the owner's source (no constant): returns `value` (or text) when the literal is still there."""
    def f():
        spec = importlib.util.find_spec(mod)
        src = Path(spec.origin).read_text(encoding="utf-8") if spec and spec.origin else ""
        return (value or text) if text in src else f"LITERAL_MISSING:{mod}:{text}"
    return f


# ---------------------------------------------------------------------------------------------------------------------- builders on the fixture
def _quant_inputs():
    """Three candidates (SH with the SH regime, ACTIVE with an ACTIVE regime, SCALP without one) and prediction records of every kind
    the builders read (direction distribution, log-return regression, score, Kalman *_CANDIDATE filter state, a STALE DXY relation,
    price forecasts with quantiles, an ineligible and a not-READY record)."""
    base = {"entry_price": 2650.0, "stop_loss": 2646.5, "targets": [{"price": 2654.0, "weight": 0.5}, {"price": 2658.0, "weight": 0.5}],
            "horizon_s": 3600, "execution_context": {"cost_price": 0.35, "spread": 0.12, "commission_known": True}, "features": {"atr_m5": 1.9},
            "decision_ts": T_END - 3 * 3600 - 17 * 60, "score": 71, "research_features": {"etc_slope": 0.4, "g7_x": None}}
    cands = [dict(base, direction="LONG", engine="SH_SCALPING", market_regime={"state": "TREND_UP", "source": "sh.context:MQ-REGIME-2.0.0"}),
             dict(base, direction="SHORT", engine="ACTIVE_S01_S12", entry_price=2650.0, stop_loss=2653.0,
                  targets=[{"price": 2645.0, "weight": 1.0}], market_regime={"state": "COMPRESSION", "source": "strategies.regime"},
                  execution_context={"cost_price": 0.3, "spread": None, "commission_known": False}, features={"atr": 2.2}),
             dict(base, direction="LONG", engine="SCALP_SHADOW", market_regime={"state": "RANGE", "source": "scalp.context"})]
    rd = {"state": "READY", "eligibility": {"eligible": True}}
    preds = [dict(rd, canonical_id="trainhub:dir", task="DIR3_H12", timeframe="M5", task_type="CLASS_PROBABILITIES",
                  result={"UP": 0.46, "DOWN": 0.31, "FLAT": 0.23}),
             dict(rd, canonical_id="mm:gpr", task="LOGRET_H12", timeframe="M5", task_type="REGRESSION", unit="log_return",
                  result={"mean": 0.0006, "sd": 0.0021}),
             dict(rd, canonical_id="ml:legacy", task="NET_R", timeframe="M15", task_type="SCORE", result={"raw_score": -0.37}),
             dict(rd, canonical_id="mm:kalman", task="FILTER", timeframe="M5", task_type="FILTER_STATE", result={"state": "BULLISH_CANDIDATE"}),
             dict(rd, canonical_id="mm:kalman2", task="FILTER", timeframe="M15", task_type="FILTER_STATE", result={"state": "BEARISH_CONFIRMED"}),
             dict(rd, canonical_id="analysis:dxy_correlation", task="DXY", timeframe="H1", task_type="STATE",
                  result={"status": "STALE", "corr_72": -0.41, "resid_z_72": 1.3, "beta_72": -0.8}),
             dict(rd, canonical_id="tsfm:chronos2", task="PRICE_PATH_H", timeframe="M5", task_type="REGRESSION", unit="price",
                  result={"last_close": 2650.0, "pred_close": 2652.4, "median": 2652.1, "quantiles_h": {"0.1": 2648.9, "0.9": 2655.6}}),
             dict(rd, canonical_id="kronos:small", task="PRICE_PATH_H", timeframe="M5", task_type="REGRESSION", unit="price",
                  result={"last_close": 2650.0, "pred_close": 2649.1}),
             dict(rd, canonical_id="mm:ineligible", task="X", timeframe="M5", task_type="SCORE", result={"raw_score": 9.0},
                  eligibility={"eligible": False}),
             {"state": "UNAVAILABLE", "canonical_id": "mm:down", "task": "X", "timeframe": "M5", "task_type": "SCORE", "result": {"raw_score": 3.0}}]
    return cands, preds


def _quant(version_attr: str):
    def run():
        from ..quant import features as QF
        cands, preds = _quant_inputs()
        return [QF.build_for(getattr(QF, version_attr), c, preds) for c in cands]
    return run


def _quant_names(version_attr: str):
    def names():
        return sorted(set().union(*(o.keys() for o in _quant(version_attr)())))
    return names


def _ml_view():
    from ..strategies import adapter
    bars = {tf: _b(tf) for tf in ("M5", "M15", "H1", "H4", "D1")}
    last = bars["M5"][-1]["c"]
    v = adapter.build_view(symbol="XAUUSD-", bars_by_tf=bars, bid=last, ask=round(last + 0.12, 2), point=TICK, as_of=_iso(T_END),
                           synthetic=True, max_bars=5000)
    v.context = {"dxy": {"status": "OK", "last_available_at": _iso(T_END - 1800)}}
    return v


def _ml_cands():
    c = fixture()["M15"][-1]["c"]
    return [{"strategy_id": "S01", "direction": "LONG", "timeframe": "M15", "stop_loss": round(c - 3.0, 2), "setup_score": 72,
             "strategy_fit_score": 64, "entry_plan": {"reference_price": c}, "family": "TREND", "countertrend": False,
             "targets": [{"price": round(c + 4.0, 2), "weight": 0.5}, {"price": round(c + 7.5, 2), "weight": 0.5}],
             "score": {"points": {"structure": 20, "formation": 12, "momentum": 15, "trigger": 10, "htf": 5}}},
            {"strategy_id": "S08", "direction": "SHORT", "timeframe": "M5", "stop_loss": round(c + 2.2, 2), "setup_score": 58,
             "entry_plan": {"trigger_level": round(c - 0.3, 2)}, "family": "REVERSION", "countertrend": True,
             "targets": [{"price": round(c - 3.1, 2), "weight": 1.0}]}]


def _ml():
    from ..ml import features as MF
    v, asof = _ml_view(), datetime.fromtimestamp(T_END, UTC)
    return [MF.compute(v, c, asof) for c in _ml_cands()]


def _dt_rank():
    from ..ml import dt_ranker as DT
    base = {"strategy_id": "S01", "source": "ACTIVE", "market": "FOREX", "instrument": "XAUUSD", "timeframe": "M15",
            "decision_ts": float(T_END - 4000), "feature_as_of": float(T_END - 4000), "event_group_id": "G1", "entry": 2650.0, "stop": 2647.0,
            "target": 2656.0, "setup_score": 66.0, "spread": 0.12, "commission_R": 0.03, "slippage_R": 0.01, "funding_R": 0.0, "atr": 2.1}
    cs = [DT.Candidate(candidate_id="C1", direction="LONG", **base),
          DT.Candidate(candidate_id="C2", direction="SHORT", **dict(base, entry=2650.0, stop=2652.5, target=2645.0, timeframe="H1",
                                                                     commission_R=None, atr=None, market="CRYPTO"))]
    return [DT.features(c) for c in cs]


def _zones(semantics_attr: str):
    def run():
        from ..config import ZonesConfig
        from ..zones import engine as ZE
        from ..zones import features as ZF
        sem = getattr(ZE, semantics_attr)
        bars = {tf: _b(tf, 600) for tf in ("M5", "M15", "H1", "D1")}            # the zone block input of ml.features.zone_block
        zm = ZE.compute_map(instrument="XAUUSD", symbol="XAUUSD-", tick=TICK, bars=bars, cfg=ZonesConfig(), as_of=float(T_END), semantics=sem)
        px = bars["M5"][-1]["c"]
        legacy = sem == ZE.LEGACY_SEMANTICS
        feats = [ZF.compute(zm, direction=d, entry=px, stop=round(px - s, 2), cost_price=0.12, legacy=legacy) for d, s in (("LONG", 3.0), ("SHORT", -3.0))]
        return {"map": {k: v for k, v in zm.items() if k != "map_id"}, "features": feats}
    return run


def _setup_machine():
    from ..scalp import strategy as ST
    mach = ST.ScalpMachine(ST.load_profile(), tick=TICK)
    for tf, s in (("M1", mach.m1), ("M5", mach.m5), ("M15", mach.m15), ("M30", mach.m30), ("H1", mach.h1)):
        for b in _b(tf, 400 if tf == "M1" else 300):
            s.append(b)
    a5 = mach.m5.atr()
    c = mach.m1.c[-1]
    mach.range = {"atr_m5": a5, "W": round(4.2 * a5, 2), "L": round(c - 2.5 * a5, 2), "H": round(c + 1.7 * a5, 2), "er10": 0.27,
                  "touches_low": 3, "touches_high": 2, "armed_at": T_END - 47 * 60}
    return mach


def _setup_cases(mach):
    c = mach.m1.c[-1]
    a5 = mach.range["atr_m5"]
    d_buy = {"zone": {"z_low": round(c - 0.9, 2), "z_high": round(c - 0.2, 2)}, "sweep_conf": {"family": "REJECTION", "score": 0.72},
             "sweep_depth": 0.8, "tv_ratio": 1.37}
    d_sell = {"zone": {"z_low": round(c + 0.3, 2), "z_high": round(c + 1.1, 2)}, "sweep_conf": {"family": "DISPLACEMENT", "score": 0.4},
              "sweep_depth": None, "tv_ratio": None}
    return [({"direction": "BUY", "decision_ts": T_END, "sl": round(c - 1.4 * a5, 2), "tp1": round(c + 1.1 * a5, 2)}, d_buy),
            ({"direction": "SELL", "decision_ts": T_END - 300, "sl": round(c + 1.2 * a5, 2), "tp1": round(c - 0.9 * a5, 2)}, d_sell)]


def _scalp_setup():
    from ..scalp import strategy as ST
    mach = _setup_machine()
    i = len(mach.m1) - 1
    return [ST.setup_features(mach, p, d, i, mach.m1.atr()) for p, d in _setup_cases(mach)]


def _scalp_net():
    from ..scalp import strategy as ST
    mach = _setup_machine()
    i = len(mach.m1) - 1
    out = [ST.scalp_net_features(mach, p, d, i, mach.m1.atr()) for p, d in _setup_cases(mach)]
    mach.m1.sp[i] = None                                                    # spread unknown at the signal bar: NaN + spread_known = 0
    out.append(ST.scalp_net_features(mach, *_setup_cases(mach)[0], i, mach.m1.atr()))
    return out


def _extind():
    from ..extind import features as XF
    from ..scalp.strategy import SETUP_FEATURES
    base = dict(zip(SETUP_FEATURES, (round(0.1 * k - 1.0, 3) for k in range(len(SETUP_FEATURES)))))
    base["er10"] = float("nan")
    px = fixture()["M5"][-1]["c"]
    t = datetime.fromtimestamp(T_END, UTC)
    gann = {"levels": [{"kind": "LEVEL", "price": round(px + d, 2)} for d in (-6.5, -2.0, 3.25, 9.0)] + [{"kind": "NOTE", "price": px}],
            "age_s": 5400}
    star = {"levels": [{"kind": "LEVEL", "price": round(px + d, 2)} for d in (-4.0, 1.5)], "available_at": _iso(T_END - 7200), "time_status": "OK",
            "windows": [{"scheduled_start_utc": T_END - 600, "scheduled_end_utc": T_END + 1200},
                        {"scheduled_start_utc": T_END + 5400, "scheduled_end_utc": T_END + 7200}]}
    spec = XF.default_spec(groups=("BASE", "SAR", "IQ_GOLD_GANN", "IQ_STAR_LINES", "PAL02M"))
    snaps = [{"decision_time": t, "side": "BUY", "price": px, "atr_m5": 1.85, "base": base, "bars": {"M5": _b("M5", 450), "M15": _b("M15", 450)},
              "ext": {"IQ_GOLD_GANN": gann, "IQ_STAR_LINES": star}},
             {"decision_time": t, "side": "SELL", "price": px, "atr_m5": 1.85, "base": {}, "bars": {"M5": _b("M5", 3)},
              "ext": {"IQ_GOLD_GANN": None, "IQ_STAR_LINES": dict(star, time_status="TIME_BASIS_UNVERIFIED")}}]
    return [XF.build_indicator_context_features(s, spec) for s in snaps]


def _gold_scalp():
    from gold_candles_runtime import scalp_features as SF
    b = _b("M1", 600)
    X, _a = SF.build([x["t"] for x in b], [x["o"] for x in b], [x["h"] for x in b], [x["l"] for x in b], [x["c"] for x in b],
                     [x["tv"] if k % 211 else None for k, x in enumerate(b)], [x["spread_price"] for x in b])
    return X[-300:]


def _trainhub():
    from ..trainhub import features as TF
    cols = {tf: _cols(tf, 1500) for tf in ("M1", "M5", "M15", "M30")}
    out = {}
    for base in ("M1", "M5", "M15"):
        t, X, nm = TF.build(cols, base, TICK)
        out[base] = {"t": t[-200:], "X": X[-200:], "names": nm}
    return out


def _trainhub_names():
    from ..trainhub import features as TF
    out: list[str] = []
    for b in TF.HTF_OF:
        out += [n for n in TF.names(b) if n not in out]
    return out


def _mm_bars(n: int = 600):
    import numpy as np
    b = _b("M5", n)
    return SimpleNamespace(**{k: np.asarray([x[k] for x in b], float) for k in ("o", "h", "l", "c", "tv")},
                           t=np.asarray([x["t"] for x in b], float))


def _mm_features(names_of: Callable[[], list[str]]):
    def run():
        from ..mm import features as MMF
        return MMF.features(_mm_bars(), list(names_of()))
    return run


def _mm_events_raw() -> dict:
    """Bar-close events of the M1 fixture + one crossed, one duplicate, one late event and a gap (segment reset)."""
    import numpy as np
    b = _b("M1", 1500)
    t = [float(x["t"] + 60) for x in b]
    t[900:] = [x + 3600.0 for x in t[900:]]                                 # > gap_reset_s: a new segment
    mid = [x["c"] for x in b]
    sp = [x["spread_price"] if x["spread_price"] is not None else float("nan") for x in b]
    act = [x["tv"] for x in b]
    t.insert(300, t[299])
    mid.insert(300, mid[299])
    sp.insert(300, sp[299])
    act.insert(300, act[299])                                               # exact duplicate
    t.insert(600, t[598] - 5.0)
    mid.insert(600, mid[598])
    sp.insert(600, 0.2)
    act.insert(600, 1.0)                                                    # late
    a = {k: np.asarray(v, float) for k, v in (("t", t), ("mid", mid), ("spread", sp), ("activity", act))}
    half = np.where(np.isfinite(a["spread"]), a["spread"] / 2, 0.0)
    a["bid"], a["ask"] = a["mid"] - half, a["mid"] + half
    a["ask"][700] = a["bid"][700] - 0.05                                    # crossed
    a["received_at"] = a["t"] + 0.25
    return {**a, "source": "PMW-FEAT-FIXTURE-1", "limits": None}


def _mm_events_acc():
    from ..mm import events as EV
    return EV.from_arrays(_mm_events_raw(), "XAUUSD")


def _mm_events():
    from ..mm import events as EV
    acc = _mm_events_acc()
    f = EV.featurize(acc)
    return {"F": f["F"], "valid": f["valid"], "names": f["names"], "segment": acc["segment"], "counts": acc["counts"]}


def _ste():
    from ..mm import events as EV
    from ..mm import ste_flownet as STE
    acc = _mm_events_acc()
    s = STE.build_samples(acc, EV.featurize(acc), N=8, M=16, h=32)
    return {k: s[k] for k in ("X", "y", "t_obs", "t_label", "end_event", "N", "M", "h", "weighting")}


def _gpr():
    from ..mm import gpr as G
    c = _mm_bars(800).c
    out = [G.samples(c, T, 256, 12) for T in (500, 650, len(c) - 13)]
    return [None if o is None else {"x": o[0], "y": o[1], "k": o[2]} for o in out]


def _lab_fs():
    from ..lab import features as LF
    return LF.feature_matrix(_b("M5", 700), "M5")


def _smf():
    from ..lab import structure_task as SMF
    m1 = _b("M1", 900)
    ctx = {"M5": _b("M5", 300), "M15": _b("M15", 200), "H1": _b("H1", 100)}
    r = SMF.features(m1, ctx, tick=TICK, point=TICK)
    return {"F": r["F"][-400:], "t": r["t"][-400:], "atr": r["atr"][-400:], "schema": r["schema"], "names": r["names"], "seq": r["seq"]}


def _nss():
    from ..lab import nss as NSS
    from ..scalp.strategy import SETUP_FEATURES
    idx = NSS.index_bars({tf: _b(tf, 400) for tf in ("M1", "M5", "M15", "H1")})
    sf = {k: round(0.05 * j - 0.4, 3) for j, k in enumerate(SETUP_FEATURES)}
    out = [NSS.snapshot(idx, float(T_END), sf), NSS.snapshot(idx, float(T_END - 900), dict(sf, er10=float("nan")))]
    return [{k: v for k, v in o.items()} for o in out]


def _sh_tp():
    from ..sh import tpmodel as TP
    setup = {"side": "BUY", "entry_ref": 2650.0, "sl": 2647.6, "tps": [{"distance_actual": 1.4}, {"distance_actual": 3.1}], "mode": "TREND",
             "net_rr": 1.27, "args_against": ["przeszkoda H1 2652"], "created_at": T_END - 2 * 3600}
    snap = {"vol": {"atr_m1": 0.61, "atr_m5": 1.83}, "ctx": {"vamd_m5": 0.42, "vamd_m1": -0.15, "fd_zone_m5": "TREND"},
            "structure_H1": {"major": "UP", "internal": "DOWN"}, "data": {"spread": 0.12}, "regime": {"state": "TREND_UP"}}
    sell = dict(setup, side="SELL", mode="REVERSAL", args_against=[], created_at=T_END - 9 * 3600)
    snap2 = dict(snap, ctx={"fd_zone_m5": "CHOP"}, structure_H1={"major": "RANGE", "internal": "DOWN"}, regime={"state": "RANGE"})
    return [TP.features(setup, snap), TP.features(sell, snap2)]


def _bat():
    from ..mm import bat_encoder as BAT
    return BAT.voxels(_b("M5", 300))


def _etc():
    from ..research import etc as ETC
    b = _b("M5", 420)
    return [{k: s.get(k) for k in ("features", "masks", "state", "channel")} for s in ETC.series_asof(b, start=380)]


def _graph():
    from ..research import graph_ca as GCA
    return [GCA.extract(_b("M5", n), lookback=200) for n in (300, 105)]


def _hdc_names():
    from ..mm import jobs as J
    return list(J.HDC_FEATURES)


def _hdc_id():
    from ..mm import features as MMF
    return MMF.schema_id(_hdc_names())


def _graph_label():
    from ..research import graph_ca as GCA
    return f"{GCA.SCHEMA}:{GCA.ORDER_HASH}"                                 # research/service.py feature_schema_id


def _ste_label():
    """mm/jobs.py manifest: 'STE-SPLITS-8x16:' + ','.join(ste_flownet.CHANNELS) (a literal there, no constant)."""
    from ..mm import ste_flownet as STE
    lit = _literal("masterquo.mm.jobs", '"STE-SPLITS-8x16:" + ",".join(SF.CHANNELS)', "STE-SPLITS-8x16:")()
    return lit + ",".join(STE.CHANNELS) if not lit.startswith("LITERAL_MISSING") else lit


def _flow_context():
    from ..lab.flow_context import task as FT
    r = FT.features(_b("M1", 1500), TICK, TICK)                             # > WARM (1000): the Markov3 / bucket columns are live
    return {"F": r["F"][-600:], "t": r["t"][-600:], "atr": r["atr"][-600:], "schema": r["schema"], "names": r["names"]}


def _context_ind():
    from ..lab.context_ind import task as CT
    r = CT.features(_b("M5", 700), TICK)
    return {"F": r["F"][-500:], "t": r["t"][-500:], "atr": r["atr"][-500:], "smc_hash": r["smc_hash"]}


def _bar_seq():
    from ..modelhub.families import seqdata as SD
    b = _b("M5", 400)
    X, y, idx = SD.build(b, L=64, H=6, cost_rel=0.0001)                     # the SEQ_LSTM / SEQ_GRU defaults (lookback 64, H = 6)
    return {"per_bar": SD.per_bar(b)[-300:], "X": X[-12:], "y": y, "idx": idx, "live": SD.live_window(b, 64)}


def _books() -> list[dict]:
    """Synthetic broker book snapshots (1 s polling) around the last M1 closes: 5 levels per side, a few empty best levels, one-level
    books and a 9 s gap (accumulator reset) - SYNTHETIC like the bars, it checks indicators/ofi.py + micro.features_from_books."""
    g = _Rng(31)
    mid, t, out = fixture()["M1"][-1]["c"], float(T_END - 1300), []
    for k in range(1200):
        t += 9.0 if k == 600 else 1.0
        mid = round(mid + TICK * round(1.6 * g.n()), 2)
        sp = TICK * (1 + int(3 * g.u()))
        bid = round(mid - sp / 2, 2)
        ask = round(bid + sp, 2)
        lv = 1 if k % 53 == 7 else 5
        bids = [(round(bid - TICK * j, 2), round(0.5 + 9 * g.u(), 2)) for j in range(lv)]
        asks = [(round(ask + TICK * j, 2), round(0.5 + 9 * g.u(), 2)) for j in range(lv)]
        if k % 97 == 11:
            bids[0], asks[0] = (bids[0][0], 0.0), (asks[0][0], 0.0)        # empty best sizes: best_imbalance / microprice None
        out.append({"t": t, "bids": bids, "asks": asks})
    return out


def _micro():
    from ..modelhub.families import micro as MI
    books = _books()
    live = MI.features_from_books(books)                                    # window = the live IndicatorService window (training)
    legacy = MI.features_from_books(books, window_s=MI.LEGACY_OFI_WINDOW_S)  # artifacts of 1.33-1.45 (no ofi_window_s in micro.json)
    return {"live_window_s": MI.live_ofi_window_s(), "live": live, "legacy": legacy}


# ---------------------------------------------------------------------------------------------------------------------- registry
@dataclass(frozen=True)
class Schema:
    id: str                                  # the owner's schema label (feature_schema, FEATURE_SET, VERSION ...)
    version: str
    family: str                              # quant | ml | zones | extind | scalp | gold_candles | trainhub | mm | lab | sh | research | modelhub
    owner: str                               # builder 'module:function' - stays in the owner module, unchanged
    id_of: Callable[[], str]                 # the owner's declaration of the id (constant / literal) - must equal `id`
    names_of: Callable[[], list[str]]        # the declared feature list of the owner (or the names produced on the fixture)
    run: Callable[[], object]                # the builder on the frozen fixture
    names_kind: str = "DECLARED"             # DECLARED (owner list) | FIXTURE (names depend on the producers present - Quant) |
                                             # DESCRIBED (the owner has no list constant: names / formulas of its docstring / metrics)
    catalog: str | None = None               # registry of features/catalog.py (PMW-FEAT-DICT-1) the names belong to
    consumers: tuple[str, ...] = ()
    notes: str = ""
    aliases: tuple[str, ...] = field(default=())   # other labels of the SAME schema in the code
    label: str | None = None                 # the exact label in artifacts when it is longer than `id` (names / hash appended)


_Q = "masterquo.quant.features"
_ZONES_OWNER = "masterquo.zones.engine:compute_map + masterquo.zones.features:compute"
SCHEMAS: tuple[Schema, ...] = (
    Schema("PMW-QUANT-FEAT-1", "1", "quant", f"{_Q}:build_for -> build2", _attr(_Q, "VERSION"), _quant_names("VERSION"), _quant("VERSION"),
           "FIXTURE", None, ("quant.metamodel (artefakty sprzed 1.46)",),
           "FEAT-1 i FEAT-2 liczy ten sam build2 (zamrożone 1.41-1.46) - ten sam odcisk; nazwy fc:/fcp:/st:/rm: zależą od producentów"),
    Schema("PMW-QUANT-FEAT-2", "2", "quant", f"{_Q}:build_for -> build2", _attr(_Q, "VERSION2"), _quant_names("VERSION2"), _quant("VERSION2"),
           "FIXTURE", None, ("quant.tabicl", "quant.ledger (wiersze bez feature_version)"), "schema2(); train nigdy nie zapisał FEAT-2"),
    Schema("PMW-QUANT-FEAT-3", "3", "quant", f"{_Q}:build3", _attr(_Q, "VERSION3"), _quant_names("VERSION3"), _quant("VERSION3"),
           "FIXTURE", None, ("quant.metamodel",), "D8 (stan *_CANDIDATE = brak kierunku), D9 (DXY bez READY = brak), D4 (reżim w kandydacie SH)"),
    Schema("PMW-QUANT-FEAT-4", "4", "quant", f"{_Q}:build4", _attr(_Q, "VERSION4"), _quant_names("VERSION4"), _quant("VERSION4"),
           "FIXTURE", None, ("quant.metamodel (CURRENT)", "quant.ledger"), "FEAT-3 + reżim w słowniku źródła (ctx:regime_sh= / ctx:regime_active=)"),
    Schema("MQ-FEAT-1.3.0", "1.3.0", "ml", "masterquo.ml.features:compute", _attr("masterquo.ml.features", "FEATURE_SCHEMA_VERSION"),
           _attr("masterquo.ml.features", "FEATURE_NAMES"), _ml, catalog="ml", consumers=("ml.models (DT/XGB S01-S12)",),
           notes="blok stref SEM-2 + pod _zone_block_sem1 blok SEM-1 dla modeli <= 1.2.0 (odcisk obejmuje oba); zgodne odczyty "
                 "MQ-FEAT-1.0.0/1.1.0/1.2.0 przez Bundle.adapt", aliases=("MQ-FEAT-1.0.0", "MQ-FEAT-1.1.0", "MQ-FEAT-1.2.0")),
    Schema("MQ-DT-RANK-FEAT-1.0.0", "1.0.0", "ml", "masterquo.ml.dt_ranker:features", _attr("masterquo.ml.dt_ranker", "FEATURE_SCHEMA"),
           _attr("masterquo.ml.dt_ranker", "FEATURE_NAMES"), _dt_rank, consumers=("ml.dt_ranker",)),
    Schema("PMW-ZONES-SEM-1", "1", "zones", _ZONES_OWNER, _attr("masterquo.zones.engine", "LEGACY_SEMANTICS"),
           _attr("masterquo.zones.features", "NAMES"), _zones("LEGACY_SEMANTICS"), consumers=("ml.features (modele MQ-FEAT <= 1.2.0)",),
           notes="mapa stref 1.45 + kodowanie bloku PMW-ZONE-FEAT-1 legacy (wiek/retesty 0, sesja -1)", aliases=("PMW-ZONE-FEAT-1",)),
    Schema("PMW-ZONES-SEM-2", "2", "zones", _ZONES_OWNER, _attr("masterquo.zones.engine", "SEMANTICS"),
           _attr("masterquo.zones.features", "NAMES"), _zones("SEMANTICS"), consumers=("ml.features MQ-FEAT-1.3.0", "evaluation ledger", "mapa stref"),
           notes="mapa stref bez look-ahead + kodowanie bloku PMW-ZONE-FEAT-1 (nieznane = NaN)", aliases=("PMW-ZONE-FEAT-1",)),
    Schema("SCALP_INDICATOR_CONTEXT_V2", "2", "extind", "masterquo.extind.features:build_indicator_context_features",
           _attr("masterquo.extind.features", "FEATURE_SCHEMA"),
           lambda: importlib.import_module("masterquo.extind.features").feature_names(
               importlib.import_module("masterquo.extind.features").default_spec(groups=("BASE", "SAR", "IQ_GOLD_GANN", "IQ_STAR_LINES"))),
           _extind, consumers=("extind (model kontekstu wskaźników)",), notes="artefakty V1 ABSTAIN (FEATURE_SCHEMA_MISMATCH) - brak buildera V1"),
    Schema("SCALP-SETUP-FEAT-1.0.0", "1.0.0", "scalp", "masterquo.scalp.strategy:setup_features", _attr("masterquo.scalp.strategy", "SETUP_FEATURES_ID"),
           lambda: list(importlib.import_module("masterquo.scalp.strategy").SETUP_FEATURES), _scalp_setup,
           consumers=("model B (.venv_candles)", "extind BASE", "NSS ctx", "SCALP-NET-FEAT"),
           notes="brak kontekstu -> 0.0; setup_features_fingerprint() w strategy.py to hash NAZW (zostaje), tu odcisk WYJŚCIA"),
    Schema("SCALP-NET-FEAT-1.0.0", "1.0.0", "scalp", "masterquo.scalp.strategy:scalp_net_features", _attr("masterquo.scalp.strategy", "NET_FEATURE_SCHEMA"),
           lambda: list(importlib.import_module("masterquo.scalp.strategy").NET_FEATURES), _scalp_net, consumers=("ml scalp (SCALP_NET_PROFIT_MARKET_V1)",),
           notes="cechy setupu z brakami NaN + flagi *_ok / *_known + blok M1"),
    Schema("SCALP-FEAT-1.0.0", "1.0.0", "gold_candles", "gold_candles_runtime.scalp_features:build", _attr("gold_candles_runtime.scalp_features", "VERSION"),
           lambda: list(importlib.import_module("gold_candles_runtime.scalp_features").FEATURES), _gold_scalp, catalog="scalp",
           consumers=("scalp A (gold_candles_runtime, .venv_candles)",)),
    Schema("PMW-TH-FEAT-1", "1", "trainhub", "masterquo.trainhub.features:build", _attr("masterquo.trainhub.features", "FEATURE_SCHEMA"),
           _trainhub_names, _trainhub, catalog="trainhub", consumers=("trainhub (TH_*)", "fc:* Quant"),
           notes="nazwy zależą od bazowego TF (names(base_tf)); odcisk na bazach M1 / M5 / M15"),
    Schema("PMW-MM-FEATURES-1", "1", "mm", "masterquo.mm.features:features", _attr("masterquo.mm.features", "VERSION"),
           lambda: list(importlib.import_module("masterquo.mm.features").FEATURES),
           _mm_features(lambda: list(importlib.import_module("masterquo.mm.features").FEATURES)), catalog="mm",
           consumers=("mm (modele świecowe)",), notes="artefakty niosą schema_id(names) = 'FS-' + hash podzbioru nazw"),
    Schema("PMW-MM-FEATURES-1/HDC", "1", "mm", "masterquo.mm.features:features", _hdc_id, _hdc_names, _mm_features(_hdc_names), catalog="mm",
           consumers=("mm.hdc",), notes="id artefaktu = mm.features.schema_id(mm.jobs.HDC_FEATURES); w rejestrze pod nazwą czytelną",
           label="FS-c5d70c01e55a"),
    Schema("PMW-MM-EVENT-1", "1", "mm", "masterquo.mm.events:from_arrays + featurize", _attr("masterquo.mm.events", "FEATURE_SCHEMA"),
           lambda: list(importlib.import_module("masterquo.mm.events").FEATURES), _mm_events,
           consumers=("mm.event_engine (event_engine_dir3)", "quant.adapters EventGRU", "modelhub families seq (EVENT_UNITS_V1)"),
           notes="id = 'PMW-MM-EVENT-1:' + nazwy (zapis mm/jobs.py, odczyt quant/adapters); VERSION przetwarzania PMW-MM-EVENTS-1",
           aliases=("PMW-MM-EVENTS-1", "EVENT_UNITS_V1"), label="PMW-MM-EVENT-1:dt_log,dmid,abs_dmid,sgn,spread,dspread,act_log,spread_ok"),
    Schema("STE-SPLITS-8x16", "1", "mm", "masterquo.mm.ste_flownet:build_samples", _ste_label,
           lambda: list(importlib.import_module("masterquo.mm.ste_flownet").CHANNELS), _ste, consumers=("mm.ste_flownet",),
           notes="manifest: 'STE-SPLITS-8x16:' + kanały (literał mm/jobs.py); VERSION modelu PMW-MM-STEFLOW-1", aliases=("PMW-MM-STEFLOW-1",),
           label="STE-SPLITS-8x16:up_count,down_count,sum_dmid,sum_absdmid,spread_mean,dt_mean,act_mean"),
    Schema("GPR_LAG1_LOGRET", "1", "mm", "masterquo.mm.gpr:samples", _literal("masterquo.mm.jobs", '"GPR_LAG1_LOGRET"', "GPR_LAG1_LOGRET"),
           lambda: ["x = ln(C[k]/C[k-1])", "y = ln(C[k+h]/C[k])"], _gpr, "DESCRIBED", consumers=("mm.gpr", "mm.service (kalibracja live)"),
           notes="jedna cecha (lag-1 log-zwrot) i cel; mm/service dopisuje ';retune=N' w ledgerze"),
    Schema("FS-1.0.0", "1.0.0", "lab", "masterquo.lab.features:feature_matrix", _attr("masterquo.lab.features", "FEATURE_SET"),
           _attr("masterquo.lab.features", "FEATURES"), _lab_fs, catalog="lab", consumers=("lab (modele M*, protokół walidacji)",),
           notes="etykiety LBL-TB-1.0.0 osobno; bb_pctb = z20/4 + 0.5 (I0026, bez zmiany)"),
    Schema("SMF-1.0.0", "1.0.0", "lab", "masterquo.lab.structure_task:features", _attr("masterquo.lab.structure_task", "FEATURE_SCHEMA"),
           _attr("masterquo.lab.structure_tab", "TAB"), _smf, consumers=("lab structure intelligence (STRUCTURE_MOVE_M1_V1, SCALP_STRUCTURE_CONTEXT_V1)",),
           notes="etykiety SML-1.0.0 / SML-1.0.1 (wyrównanie SETUP zmienione w 1.46 - etykiety, nie cechy)"),
    Schema("NSS-FEAT-1.0.0", "1.0.0", "lab", "masterquo.lab.nss:snapshot", _attr("masterquo.lab.nss", "FEATURE_SCHEMA"),
           lambda: [f"seq:{c}" for c in importlib.import_module("masterquo.lab.nss").SEQ_CH] + importlib.import_module("masterquo.lab.nss").ctx_names(),
           _nss, consumers=("lab NSS (TCN)",), notes="sekwencje M1/M5 (kanały SEQ_CH) + kontekst M15/H1 + SETUP_FEATURES (brak = NaN)"),
    Schema("SH-TPMODEL-1.0.0", "1.0.0", "sh", "masterquo.sh.tpmodel:features", _attr("masterquo.sh.tpmodel", "VERSION"),
           _attr("masterquo.sh.tpmodel", "FEATURES"), _sh_tp, consumers=("sh.tpmodel (P(TP2 przed SL))",)),
    Schema("PMW-BAT-EVENT-ENCODER-1", "1", "mm", "masterquo.mm.bat_encoder:voxels", _attr("masterquo.mm.bat_encoder", "SCHEMA"),
           lambda: list(importlib.import_module("masterquo.mm.bat_encoder").CHANNELS), _bat, consumers=("mm.bat_encoder (SHADOW)",)),
    Schema("PMW_ETC_FEATURES_V1", "1", "research", "masterquo.research.etc:snapshot / series_asof", _attr("masterquo.research.etc", "SCHEMA"),
           lambda: list(importlib.import_module("masterquo.research.etc").FEATURES), _etc, consumers=("research ETC (rm:* Quant)",),
           notes="rekordy niosą schema_hash(p) = SCHEMA:VERSION:hash parametrów (resolve() po prefiksie 'id:'); odcisk na parametrach domyślnych",
           aliases=("PMW_ETC_SRC_PORT_V1",)),
    Schema("PMW_GRAPH50_V1", "1", "research", "masterquo.research.graph_ca:extract", _graph_label,
           lambda: list(importlib.import_module("masterquo.research.graph_ca").NAMES), _graph, consumers=("research graph CA (rm:* Quant)",),
           notes="id = graph_ca.SCHEMA; rekordy research/service.py niosą SCHEMA:ORDER_HASH (hash kolejności nazw); VERSION portu "
                 "PMW_GRAPH50_PORT_V1 = alias", aliases=("PMW_GRAPH50_PORT_V1",), label="PMW_GRAPH50_V1:1c0ac94e7e25"),
    # Etap 4 review: schemas with working builders the first registry missed (ETAP1 rejestry_cech) - found by scan_labels()
    Schema("FLOW_CONTEXT_V1", "1", "lab", "masterquo.lab.flow_context.task:features", _attr("masterquo.lab.flow_context.task", "SCHEMA"),
           _attr("masterquo.lab.flow_context.task", "FEATS"), _flow_context, consumers=("lab flow context (FLOW_CONTEXT_MOVE_M1_V1)",),
           notes="load_candidate odrzuca artefakt z innym schema / FEATS (nazwy); odcisk na profilu domyślnym właściciela (prof=None), "
                 "M1 > WARM (Markov3 / kubełki)"),
    Schema("FS_VS_CONTEXT_v1", "1", "lab", "masterquo.lab.context_ind.task:features", _attr("masterquo.lab.context_ind.task", "SCHEMA"),
           _attr("masterquo.lab.context_ind.task", "FEATS"), _context_ind, consumers=("lab context indicators (CONTEXT_MOVE_M5_V1, F-17)",),
           notes="VAMD / FD / SMC as-of każdej świecy; odcisk na profilu domyślnym (prof=None) + smc_hash stanu SMC"),
    Schema("BAR_SEQ_V1", "1", "modelhub", "masterquo.modelhub.families.seqdata:build", lambda: importlib.import_module(
           "masterquo.modelhub.families.seq").SeqBase.DATA["schema"],
           lambda: ["ln(C[i]/C[i-1])", "(H-L)/C", "(C-O)/C", "ln(1+tick_volume)"], _bar_seq, "DESCRIBED",
           consumers=("modelhub SEQ_LSTM / SEQ_GRU (.venv_deep)",),
           notes="per_bar + okna L=64 + etykieta H=6 (seqdata.build), okno live (live_window); scaler.json niesie schema BAR_SEQ_V1"),
    Schema("MICROSTRUCTURE", "1", "modelhub", "masterquo.modelhub.families.micro:features_from_books",
           lambda: importlib.import_module("masterquo.modelhub.families.micro").Micro.ID,
           lambda: ["best_imbalance", "depth_imbalance", "ofi_window", "microprice_dev/spread"], _micro, "DESCRIBED",
           consumers=("modelhub MICROSTRUCTURE (klasyfikator reakcji 10 s)",),
           notes="właściciel nie deklaruje etykiety cech: id = ID rodziny (manifest.json family); micro.json niesie ofi_window_s - odcisk "
                 "na syntetycznych migawkach arkusza (_books) dla okna live i LEGACY_OFI_WINDOW_S"),
)
# frozen fingerprints of the CURRENT builders (PMW-FEAT-FIXTURE-1). Never edit a value to make a test pass: a different output under
# the same id means the builder's semantics changed - give the owner a new version and add a new entry instead.
FINGERPRINTS: dict[str, str] = {
    "PMW-QUANT-FEAT-1": "a7337dd6f577fa7d",
    "PMW-QUANT-FEAT-2": "a7337dd6f577fa7d",
    "PMW-QUANT-FEAT-3": "ad83dc7149ac68bb",
    "PMW-QUANT-FEAT-4": "e0717e0853dc5228",
    "MQ-FEAT-1.3.0": "9d306108e2163667",
    "MQ-DT-RANK-FEAT-1.0.0": "d2b531f1cd6530f7",
    "PMW-ZONES-SEM-1": "458d0bc5ce2610fe",
    "PMW-ZONES-SEM-2": "578c357817affc89",
    "SCALP_INDICATOR_CONTEXT_V2": "dc98092b0071c9a2",
    "SCALP-SETUP-FEAT-1.0.0": "10d12711a8ade756",
    "SCALP-NET-FEAT-1.0.0": "a8d1d78ae3b63135",
    "SCALP-FEAT-1.0.0": "79b688db96f4396b",
    "PMW-TH-FEAT-1": "f9b220bd279b05dd",
    "PMW-MM-FEATURES-1": "50cca351d98d6b5b",
    "PMW-MM-FEATURES-1/HDC": "59298df527437de4",
    "PMW-MM-EVENT-1": "3f61574c8209e1ac",
    "STE-SPLITS-8x16": "f87c4bb5da52ec9f",
    "GPR_LAG1_LOGRET": "22f90e8dd5c3c98e",
    "FS-1.0.0": "a80fa4b0952f8bb2",
    "SMF-1.0.0": "311715fa9100ad41",
    "NSS-FEAT-1.0.0": "494dcfdc4b12fbea",
    "SH-TPMODEL-1.0.0": "65319d9ecc5ec4ed",
    "PMW-BAT-EVENT-ENCODER-1": "53dc2009c0d7f7c1",
    "PMW_ETC_FEATURES_V1": "db78a4e8b7d446a3",
    "PMW_GRAPH50_V1": "961710b796d0c941",
    "FLOW_CONTEXT_V1": "73a2557de12f3780",
    "FS_VS_CONTEXT_v1": "99f4e7c0f57dfd84",
    "BAR_SEQ_V1": "7e8a9e5c34b583df",
    "MICROSTRUCTURE": "3608ec9329cd0da5",
}
# feature schemas of the code WITHOUT a fingerprint here - label (exact, or a glob: '*' = a formatted part) -> why
NOT_REGISTERED = {
    "CLOSE_ONLY": "mm/jobs.py job_kalman: wejście = surowe zamknięcia (brak buildera cech do odcisku)",
    "MQ_NEWTONIAN_QUOTES_V2": "lab/tick_store.FEATURES - archiwum kinematyczne z ticków (wymaga migawek kwotowań; nie jest wejściem modelu bota)",
    "KRONOS_OHLCV_TIME_V1": "kronos/predictions.py: surowe OHLCV + znaczniki czasu do zewnętrznego modelu Kronos (tokenizer w .venv_kronos) - "
                            "bot nie liczy cech, brak buildera do odcisku",
    "TSFM_*": "tsfm/predictions.py, tsfm/service.py: TSFM_<profil> (CLOSE_V1 = szereg close, CLOSE_OHLCV_PAST_V1 = close + kowarianty OHLC / "
              "wolumen, tsfm/core.predict_request) - surowe szeregi do zewnętrznych modeli TSFM, bot nie liczy cech",
    "BASKET-FEAT-1": "baskets/catalog.py: opis pola model_feature_schema w katalogu strategii koszyków (setup_score, model_agreement, p_event_raw "
                     "jako osobne pola) - brak buildera i brak modelu trenowanego na tym schemacie",
    "gold-candles-v2.0": "gold_candles/features.py:feature_frame (pandas, .venv_candles): Config.contract_hash() = sha256 BAJTÓW data.py / "
                         "patterns.py / features.py / model.py, sprawdzany przy ładowaniu (model.py: contract_hash) - każda zmiana formuły "
                         "już unieważnia artefakt; etykieta nie jest stałą modułu (literał w data.py), skan jej nie widzi",
}
# labels the scan finds in owner modules that are NOT feature schemas (model / artifact formats) - label -> what it is
NOT_FEATURE_SCHEMAS = {
    "MQ-DT-SIGNAL-RANKER-1.0.0": "ml/dt_ranker.SCHEMA - format artefaktu modelu DT rankera; jego cechy = MQ-DT-RANK-FEAT-1.0.0",
}
BY_ID: dict[str, Schema] = {s.id: s for s in SCHEMAS}
BY_LABEL: dict[str, str] = {s.label: s.id for s in SCHEMAS if s.label}


def get(sid: str) -> Schema:
    if sid not in BY_ID:
        raise KeyError(f"UNKNOWN_FEATURE_SCHEMA:{sid}")
    return BY_ID[sid]


def names(sid: str) -> list[str]:
    return list(get(sid).names_of())


def owner_id(sid: str) -> str:
    """The label the owner's code declares today (constant / literal / schema_id of its names)."""
    return str(get(sid).id_of())


def label(sid: str) -> str:
    """The label artifacts of this schema carry (= id unless the owner appends names / a hash)."""
    s = get(sid)
    return s.label or s.id


def output(sid: str):
    """The builder's output on the frozen fixture (computed by the owner's own function)."""
    return get(sid).run()


def fingerprint(sid: str) -> str:
    """Hash of the OUTPUT only (not of the id): two ids computed by the same builder share it (PMW-QUANT-FEAT-1 / -2 = build2)."""
    return digest({"fixture": FIXTURE_VERSION, "output": output(sid)})


def check(ids: list[str] | None = None) -> list[dict]:
    """Per schema: {id, label, owner_id, frozen, actual, ok} - ok = the owner still declares this label AND the output matches the frozen
    fingerprint (a builder change without a new version -> ok False)."""
    rows = []
    for sid in ids or list(BY_ID):
        oid, act = owner_id(sid), fingerprint(sid)
        rows.append({"id": sid, "label": label(sid), "owner_id": oid, "frozen": FINGERPRINTS.get(sid), "actual": act,
                     "ok": oid == label(sid) and FINGERPRINTS.get(sid) == act})
    return rows


def registry() -> list[dict]:
    """Metadata of every schema (no builder is run): id, version, family, owner, names, consumers, frozen fingerprint."""
    return [{"id": s.id, "label": s.label or s.id, "version": s.version, "family": s.family, "owner": s.owner, "names_kind": s.names_kind, "catalog": s.catalog,
             "names": names(s.id) if s.names_kind in ("DECLARED", "DESCRIBED") else None, "consumers": list(s.consumers), "aliases": list(s.aliases),
             "fingerprint": FINGERPRINTS.get(s.id), "notes": s.notes} for s in SCHEMAS]


def resolve(carried: str | None) -> str | None:
    """Registry id of the label an artifact / record CARRIES: the id, the exact `label`, or the id followed by ':' / ';' and a parameter
    part (PMW_ETC_FEATURES_V1:<VERSION>:<params hash>, GPR_LAG1_LOGRET;retune=N). Aliases are NOT resolved (PMW-ZONE-FEAT-1 is shared by
    SEM-1 and SEM-2; older MQ-FEAT versions are other formulas). None = not a registered schema."""
    if not carried:
        return None
    c = str(carried)
    if c in BY_ID:
        return c
    if c in BY_LABEL:
        return BY_LABEL[c]
    return next((s.id for s in SCHEMAS if c.startswith((s.id + ":", s.id + ";"))), None)


def tag(sid: str) -> dict:
    """What an artifact trained on `sid` (id or carried label) can record - NOT WIRED: no owner writes it (see the module docstring)."""
    rid = resolve(sid) or sid
    get(rid)
    return {"feature_schema_id": label(rid), "feature_fingerprint": FINGERPRINTS.get(rid), "feature_registry": VERSION}


def check_manifest(sid: str, man: dict | None) -> dict:
    """LEGACY (artifact without a fingerprint - accepted as today) | OK | MISMATCH (same id, other formula) | UNKNOWN_SCHEMA.
    `sid` = the registry id or the label the artifact carries (resolve()). NOT WIRED: no loader calls it (see the module docstring)."""
    rid = resolve(sid)
    if rid is None:
        return {"status": "UNKNOWN_SCHEMA", "id": sid}
    fp = (man or {}).get("feature_fingerprint")
    if fp is None:
        return {"status": "LEGACY", "id": rid}
    return {"status": "OK" if fp == FINGERPRINTS.get(rid) else "MISMATCH", "id": rid, "artifact": fp, "code": FINGERPRINTS.get(rid)}


# ---------------------------------------------------------------------------------------------------------------------- coverage guard
SCAN_ROOTS = ("masterquo", "gold_candles", "gold_candles_runtime")      # packages of backend/ (backend/vendor is never scanned)
_NAME_ANY = re.compile(r"^(\w*FEATURE_SCHEMA\w*|FEATURE_SET\w*|\w*FEATURES?_ID)$")          # a feature-schema label wherever it is
_NAME_OWNER = re.compile(r"^(SCHEMA|VERSION\d*|SEMANTICS|LEGACY_SEMANTICS)$")                 # ... and these names in owner modules
_FEATURE_LISTS = {"FEATS", "FEATURES", "FEATURE_NAMES", "NAMES", "CHANNELS", "SETUP_FEATURES", "NET_FEATURES", "SEQ_CH"}
_KEYS = {"feature_schema", "model_feature_schema"}


def _label_of(node) -> str | None:
    """A literal label: a string, 'text' + <expr> -> 'text*', an f-string with a literal start ('*' for each formatted part)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _label_of(node.left)
        return None if left is None else left.rstrip("*") + "*"
    if isinstance(node, ast.JoinedStr):
        out = "".join(v.value if isinstance(v, ast.Constant) else "*" for v in node.values)
        return None if out.startswith("*") else out
    return None


def scan_labels(root: Path | None = None) -> dict[str, list[str]]:
    """{label: ['<file>:<line>:<where>']} of every feature-schema label declared in the sources under `root` (default: backend/). Reads
    the files with ast (nothing is imported or executed). A label is cut at the first space ('BASKET-FEAT-1 (setup_score, ...)')."""
    base = Path(root) if root else Path(__file__).resolve().parents[2]
    found: dict[str, list[str]] = {}

    def add(v, p, line, where):
        if v:
            found.setdefault(v.split(" ")[0], []).append(f"{p.relative_to(base).as_posix()}:{line}:{where}")
    for pkg in SCAN_ROOTS:
        if not (base / pkg).is_dir():
            continue
        for p in sorted((base / pkg).rglob("*.py")):
            if "vendor" in p.relative_to(base).parts:
                continue
            tree = ast.parse(p.read_text(encoding="utf-8"))
            top = {t.id: n for n in tree.body if isinstance(n, ast.Assign | ast.AnnAssign)
                   for t in (n.targets if isinstance(n, ast.Assign) else [n.target]) if isinstance(t, ast.Name)}
            owner = p.name.endswith("features.py") or bool(_FEATURE_LISTS & set(top))
            for name, n in top.items():
                if n.value is not None and (_NAME_ANY.match(name) or (owner and _NAME_OWNER.match(name))):
                    add(_label_of(n.value), p, n.lineno, name)
            for n in ast.walk(tree):
                if isinstance(n, ast.keyword) and n.arg in _KEYS:
                    add(_label_of(n.value), p, n.value.lineno, f"{n.arg}=")
                elif isinstance(n, ast.Dict):
                    for k, v in zip(n.keys, n.values, strict=True):
                        if isinstance(k, ast.Constant) and k.value in _KEYS:
                            add(_label_of(v), p, v.lineno, f'"{k.value}"')
                elif isinstance(n, ast.ClassDef) and "modelhub" in p.parts:
                    for st in n.body:
                        if isinstance(st, ast.Assign) and isinstance(st.value, ast.Dict) and any(isinstance(t, ast.Name) and t.id == "DATA"
                                                                                                for t in st.targets):
                            for k, v in zip(st.value.keys, st.value.values, strict=True):
                                if isinstance(k, ast.Constant) and k.value == "schema":
                                    add(_label_of(v), p, v.lineno, f"{n.name}.DATA schema")
    return found


def covered(lbl: str) -> str | None:
    """Where a scanned label is accounted for: 'schema:<id>' (id / label / alias, '*' matched as a glob) | 'not_registered' |
    'not_feature' | None (a feature schema of the code the registry does not know - the guard fails)."""
    for s in SCHEMAS:
        if any(fnmatch.fnmatchcase(x, lbl) for x in (s.id, s.label or s.id, *s.aliases)):
            return f"schema:{s.id}"
    if lbl in NOT_REGISTERED:
        return "not_registered"
    if lbl in NOT_FEATURE_SCHEMAS:
        return "not_feature"
    return None


def uncovered(root: Path | None = None) -> dict[str, list[str]]:
    """Labels found by scan_labels() that are not accounted for (must be empty: register the schema or describe it in NOT_REGISTERED)."""
    return {k: v for k, v in scan_labels(root).items() if covered(k) is None}
