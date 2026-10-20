"""PMW-UPD-09 R22-R25 shared cores (closed bars, causal, own engineering profiles - not copies of the cited MQL5 codes):

R22 MQ_REGIME_MULTI_V2 - ER_n and ATR-normalised OLS slope for n in {8,20,50}, agreement, structure bias (HH/HL vs LH/LL from the Market
    Behavior projection known at the bar), candidate TREND_UP/TREND_DOWN/RANGE/TRANSITION + deterministic hysteresis on NEW closed bars,
    separate volatility axis (ATR14/C percentile vs the PREVIOUS 200 observations, min 100) shared with M11 (vol_axis). Strength = own
    versioned evidence formula, NOT a probability. Missing history = WARMING_UP (never RANGE); full flat = RANGE + FLAT branch.
R23 MARKET_BEHAVIOR (STRUCTURE_CAUSAL_V2 pivots): raw pivot events (known after right closed bars), one alternating projection with sealed
    anchors and one developing tail (TAIL_REPLACED revisions), legs FINAL only when sealed; EQH/EQL tolerance frozen at the pivot
    max(tick, 0.05 ATR); outside bar that is both a high and a low pivot -> AMBIGUOUS_ORDER (kept raw, skipped in the projection);
    min_dist_points (same kind) and min_leg_ticks (opposite anchors) are separate filters; units price/points/ticks and pips only with an
    explicit pip_size (else NO_PIP_DEFINITION); roles vs the bias known BEFORE the leg; retracement keeps values > 100 (OVER_RETRACE).
R24 MQ_SMMA_HL3_V2 - SMA seed + Wilder recursion for High and Low, CURRENT_CLOSED / PREVIOUS_BOUNDARY profiles, analytical lag >= 0,
    deadband (1 tick), location ABOVE/BELOW/INSIDE/BAND_TOUCH separate from the cross event UP/DOWN/NONE with a stable id; gap > continuity
    resets the seed (no cross through a gap).
R25 MQ_ZSCORE_V2 - INCLUSIVE_N (C_{t-n+1..t}) and PREVIOUS_N (C_{t-n..t-1}), ddof validated, two-pass centred variance per window
    (no E[x^2]-E[x]^2), dispersion floor max(tick/sqrt(12), 1e-5*|mean|) -> LOW_DISPERSION null (never a huge fake Z); hypotheses
    H_MR/H_BO/H_TP as separate event streams (thresholds = calibration start points, never trading).
"""
from __future__ import annotations

import hashlib
import json
import math

import numpy as np

from ..analysis import structure_v2 as S

REGIME_PROFILE = "MQ_REGIME_MULTI_V2"
REGIME_VERSION = "MQ-REGIME-2.0.0"
STRENGTH_FORMULA = "PMW-REGIME-STRENGTH-1 (trend: 100*(.4*clip(e/.35)+.4*clip(|d|/.5)+.2*agreement); range: 100*clip((.28-e)/.28)*clip(1-|d|/.4))"
MBA_PROFILE = "MARKET_BEHAVIOR_V1"
SMMA_PROFILE = "MQ_SMMA_HL3_V2"
Z_PROFILE = "MQ_ZSCORE_V2"
REGIME_CFG = {"horizons": [8, 20, 50], "atr_n": 14, "atr_floor_ticks": 1.0, "trend_e": 0.35, "trend_d": 0.50, "agree": 2 / 3, "agree_d": 0.20,
              "range_e": 0.18, "range_d": 0.25, "hold_e": 0.25, "hold_d": 0.25, "exit_range_e": 0.28, "exit_range_d": 0.40, "confirm": 2,
              "vol_window": 200, "vol_min": 100, "vol_lo": 0.2, "vol_hi": 0.8}


def cfg_hash(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:16]


def _clip(x: float, lo=0.0, hi=1.0) -> float:
    return min(hi, max(lo, x))


# ===================================================================== shared ATR / volatility axis (M11 + R22)
def atr_series(h, lo, c, n=14) -> list:
    return S.atr_series(list(h), list(lo), list(c), n)


def vol_axis(atr_rel: np.ndarray, i: int, window: int = 200, min_obs: int = 100, lo: float = 0.2, hi: float = 0.8) -> dict:
    """Percentile of ATR14/C at i vs the PREVIOUS `window` available observations (current value not in the reference); ties count half."""
    cur = atr_rel[i]
    if not np.isfinite(cur):
        return {"state": "WARMING_UP", "percentile": None, "n_ref": 0}
    ref = atr_rel[max(0, i - window):i]
    ref = ref[np.isfinite(ref)]
    if len(ref) < min_obs:
        return {"state": "WARMING_UP", "percentile": None, "n_ref": int(len(ref))}
    p = (float((ref < cur).sum()) + 0.5 * float((ref == cur).sum())) / len(ref)
    return {"state": "LOW" if p < lo else ("HIGH" if p > hi else "NORMAL"), "percentile": round(p, 4), "n_ref": int(len(ref)),
            "tie_rule": "ties count 0.5", "atr_rel": float(cur)}


# ===================================================================== R23 Market Behavior
def _ts(x) -> float:
    from datetime import datetime
    return x if isinstance(x, (int, float)) else datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp()


class MarketBehavior:
    """Incremental over closed bars. bars: dicts with open_utc,h,l,c (oldest first). All records carry known/sealed/available times."""

    def __init__(self, tf: str = "M1", tf_s: int = 60, left: int = 3, right: int = 3, tick: float = 0.01, point: float | None = None,
                 pip_size: float | None = None, min_dist_points: float = 0.0, min_leg_ticks: float = 0.0, layer: str = "internal",
                 context: str = "XAUUSD"):
        self.tf, self.tf_s, self.L, self.R = tf, tf_s, left, right
        self.tick, self.point, self.pip = tick, point or tick, pip_size
        self.min_dist, self.min_leg = min_dist_points, min_leg_ticks
        self.layer, self.context = layer, context
        self.profile = {"profile": MBA_PROFILE, "left": left, "right": right, "eq_tol": "max(tick, 0.05*ATR_at_pivot)", "min_dist_points": min_dist_points,
                        "min_leg_ticks": min_leg_ticks, "pip_size": pip_size, "layer": layer}
        self.profile_hash = cfg_hash(self.profile)
        self.reset()

    def reset(self):
        self.h, self.lo, self.c, self.t = [], [], [], []
        self.atr = []
        self.events: list[dict] = []          # append-only
        self.swings: dict[str, dict] = {}
        self.anchors: list[str] = []          # sealed anchor ids (alternating)
        self.tail: str | None = None          # developing anchor id
        self.legs: dict[str, dict] = {}
        self.last_accepted = {"H": None, "L": None}
        self.last_same_kind_anchor = {"H": None, "L": None}
        self.bias_hist: list[tuple[int, str]] = []
        self.anchors_leg_ids: list[str] = []

    def _sid(self, kind: str, idx: int) -> str:
        return "SW-" + hashlib.sha256(f"{self.context}|{self.tf}|{self.layer}|{kind}|{self.t[idx]}|{self.profile_hash}".encode()).hexdigest()[:16]

    def _close_ts(self, i: int) -> float:
        return _ts(self.t[i]) + self.tf_s

    def _ev(self, kind: str, i: int, **kw):
        e = {"event_id": hashlib.sha256(f"{kind}|{i}|{json.dumps(kw, sort_keys=True, default=str)}".encode()).hexdigest()[:16], "kind": kind,
             "bar_index": i, "available_at": self._close_ts(i), **kw}
        self.events.append(e)
        return e

    def bias_at(self, i: int) -> str:
        """Bias from the latest sealed/tail anchors known at bar i: UP for known HH+HL, DOWN for LH+LL, else UNKNOWN/MIXED."""
        b = "UNKNOWN"
        for k, v in self.bias_hist:
            if k <= i:
                b = v
        return b

    def _recompute_bias(self, i: int):
        ids = self.anchors + ([self.tail] if self.tail else [])
        lh = next((self.swings[s]["label"] for s in reversed(ids) if self.swings[s]["kind"] == "H"), None)
        ll = next((self.swings[s]["label"] for s in reversed(ids) if self.swings[s]["kind"] == "L"), None)
        if lh in ("HH",) and ll in ("HL",):
            b = "UP"
        elif lh in ("LH",) and ll in ("LL",):
            b = "DOWN"
        elif lh is None or ll is None or lh in ("H0",) or ll in ("L0",):
            b = "UNKNOWN"
        else:
            b = "MIXED"
        if not self.bias_hist or self.bias_hist[-1][1] != b:
            self.bias_hist.append((i, b))

    def update(self, bar: dict) -> list[dict]:
        """Append one CLOSED bar; returns new events."""
        n0 = len(self.events)
        self.t.append(bar["open_utc"])
        self.h.append(float(bar["h"]))
        self.lo.append(float(bar["l"]))
        self.c.append(float(bar["c"]))
        i = len(self.c) - 1
        a = S._atr(self.h, self.lo, self.c, i, 14)
        self.atr.append(a)
        p = i - self.R
        if p - self.L < 0:
            return []
        hs, ls = self.h, self.lo
        is_h = hs[p] > max(hs[p - self.L:p]) and hs[p] >= max(hs[p + 1:i + 1])
        is_l = ls[p] < min(ls[p - self.L:p]) and ls[p] <= min(ls[p + 1:i + 1])
        if is_h and is_l:
            for k in ("H", "L"):
                self._ev("PIVOT_CONFIRMED", i, swing_kind=k, origin_index=p, price=hs[p] if k == "H" else ls[p], flag="AMBIGUOUS_ORDER")
            self._ev("AMBIGUOUS_ORDER", i, origin_index=p, note="OHLC nie ujawnia kolejności H/L; pominięte w projekcji")
            return self.events[n0:]
        for k, ok in (("H", is_h), ("L", is_l)):
            if not ok:
                continue
            price = hs[p] if k == "H" else ls[p]
            self._ev("PIVOT_CONFIRMED", i, swing_kind=k, origin_index=p, price=price)
            prev = self.last_accepted[k]
            if prev is not None and self.min_dist > 0 and abs(price - self.swings[prev]["price"]) < self.min_dist * self.point:
                self._ev("PIVOT_FILTERED", i, swing_kind=k, origin_index=p, reason="MIN_DIST_POINTS")
                continue
            self._accept(k, p, price, i)
        return self.events[n0:]

    def _accept(self, k: str, p: int, price: float, i: int):
        atr_p = self.atr[p] if p < len(self.atr) and self.atr[p] else None
        tol = max(self.tick, 0.05 * atr_p) if atr_p else self.tick
        tail = self.swings.get(self.tail) if self.tail else None
        if tail is not None and tail["kind"] == k:
            better = price > tail["price"] if k == "H" else price < tail["price"]
            if not better:
                self._ev("PIVOT_NOT_EXTREME", i, swing_kind=k, origin_index=p)
                return
            sid = self._new_swing(k, p, price, i, tol)
            self.swings[self.tail]["status"] = "REPLACED"
            self.swings[self.tail]["replaced_by"] = sid
            self._ev("TAIL_REPLACED", i, old=self.tail, new=sid)
            self.tail = sid
        else:
            if tail is not None:
                if self.min_leg > 0 and abs(price - tail["price"]) < self.min_leg * self.tick:
                    self._ev("PIVOT_FILTERED", i, swing_kind=k, origin_index=p, reason="MIN_LEG_TICKS")
                    return
                tail["status"] = "SEALED"
                tail["sealed_at"] = self._close_ts(i)
                tail["sealed_index"] = i
                self.anchors.append(self.tail)
                self._ev("ANCHOR_SEALED", i, swing_id=self.tail)
                if len(self.anchors) >= 2:
                    self._final_leg(self.anchors[-2], self.anchors[-1], i)
            sid = self._new_swing(k, p, price, i, tol)
            self.tail = sid
        self.last_accepted[k] = self.tail
        self._recompute_bias(i)

    def _new_swing(self, k: str, p: int, price: float, i: int, tol: float) -> str:
        sid = self._sid(k, p)
        ids = self.anchors
        prev_id = next((s for s in reversed(ids) if self.swings[s]["kind"] == k), None)
        prev = self.swings.get(prev_id) if prev_id else None
        if prev is None:
            lab = "H0" if k == "H" else "L0"
        elif abs(price - prev["price"]) <= prev_tol(prev, tol):
            lab = "EQH" if k == "H" else "EQL"
        elif k == "H":
            lab = "HH" if price > prev["price"] else "LH"
        else:
            lab = "HL" if price > prev["price"] else "LL"
        rev = sum(1 for s in self.swings.values() if s["id"] == sid)
        self.swings[sid] = {"id": sid, "context": self.context, "tf": self.tf, "layer": self.layer, "kind": k, "origin_index": p,
                            "origin_time": self.t[p], "price": price, "known_at": self._close_ts(i), "known_index": i, "sealed_at": None,
                            "status": "TAIL", "label": lab, "previous_same_kind_id": prev_id, "tolerance": tol, "revision": rev,
                            "profile_hash": self.profile_hash, "label_reason": f"vs {prev_id or 'brak poprzednika'} (tol {tol:.5g})"}
        self._ev("SWING_TAIL", i, swing_id=sid, label=lab)
        return sid

    def _final_leg(self, a_id: str, b_id: str, i: int):
        a, b = self.swings[a_id], self.swings[b_id]
        move = b["price"] - a["price"]
        bias_before = self.bias_at(a["known_index"] - 1) if a["known_index"] > 0 else "UNKNOWN"
        d = "UP" if move > 0 else "DOWN"
        role0 = "UNCLASSIFIED" if bias_before not in ("UP", "DOWN") else ("IMPULSE_CANDIDATE" if bias_before == d else "PULLBACK_CANDIDATE")
        prev_leg = self.legs[self.anchors_leg_ids[-1]] if self.anchors_leg_ids else None
        rel = (abs(move) / abs(prev_leg["move"]) * 100) if prev_leg and prev_leg["move"] else None
        retr = None
        flags = []
        if prev_leg is not None and prev_leg["direction"] != d and prev_leg["move"]:
            retr = abs(move) / abs(prev_leg["move"]) * 100
            if retr > 100:
                flags.append("OVER_RETRACE")
        final_role = role0
        if role0 == "PULLBACK_CANDIDATE" and retr is not None and retr > 100:
            final_role = "STRUCTURE_CHANGE"
        elif role0 in ("IMPULSE_CANDIDATE", "PULLBACK_CANDIDATE"):
            final_role = role0.replace("_CANDIDATE", "")
        ta, tb = _ts(a["origin_time"]), _ts(b["origin_time"])
        lid = "LEG-" + hashlib.sha256(f"{a_id}|{b_id}".encode()).hexdigest()[:16]
        leg = {"id": lid, "from_id": a_id, "to_id": b_id, "from_rev": a["revision"], "to_rev": b["revision"], "direction": d, "move": move,
               "abs_move": abs(move), "points": move / self.point, "ticks": move / self.tick, "pips": move / self.pip if self.pip else None,
               "pip_status": None if self.pip else "NO_PIP_DEFINITION", "bar_count": b["origin_index"] - a["origin_index"],
               "wall_duration_seconds": tb - ta, "market_bar_duration": (b["origin_index"] - a["origin_index"]) * self.tf_s,
               "available_at": self._close_ts(i), "status": "FINAL", "role_initial": role0, "role_initial_basis": bias_before, "role": final_role,
               "relative_leg_size_pct": rel, "retracement_pct": retr, "retracement_of": prev_leg["id"] if retr is not None else None, "flags": flags}
        self.legs[lid] = leg
        self.anchors_leg_ids.append(lid)
        self._ev("LEG_FINAL", i, leg_id=lid, role=final_role)

    # ---------------------------------------------------------------- queries (as-of)
    def provisional_tail(self) -> dict | None:
        if not self.tail or not self.anchors:
            return None
        a, b = self.swings[self.anchors[-1]], self.swings[self.tail]
        mv = b["price"] - a["price"]
        return {"from_id": a["id"], "to_id": b["id"], "direction": "UP" if mv > 0 else "DOWN", "move": mv, "status": "PROVISIONAL",
                "available_at": b["known_at"], "bar_count": b["origin_index"] - a["origin_index"]}

    def swing_asof(self, sid: str, as_of: float | None = None) -> dict | None:
        s = self.swings.get(sid)
        if s is None:
            return None
        if as_of is not None and s["known_at"] > as_of:
            return None
        known = [x for x in self.swings.values() if (as_of is None or x["known_at"] <= as_of) and x["status"] != "REPLACED"]
        known.sort(key=lambda x: x["origin_index"])
        pos = next((k for k, x in enumerate(known) if x["id"] == sid), None)
        prev_ = known[pos - 1]["id"] if pos is not None and pos > 0 else None
        nxt = known[pos + 1]["id"] if pos is not None and pos + 1 < len(known) else None
        legs = [lg for lg in self.legs.values() if (as_of is None or lg["available_at"] <= as_of) and sid in (lg["from_id"], lg["to_id"])]
        out = dict(s)
        if as_of is not None and s["sealed_at"] and s["sealed_at"] > as_of:
            out.update(sealed_at=None, status="TAIL")
        out.update(previous_id=prev_, next_id=nxt, legs=legs, as_of=as_of)
        return out

    def story(self) -> dict:
        legs = [self.legs[x] for x in self.anchors_leg_ids]
        last = legs[-1] if legs else None
        bias = self.bias_hist[-1][1] if self.bias_hist else "UNKNOWN"
        anchors = [self.swings[s] for s in self.anchors[-4:]]
        cond = None
        if bias == "UP":
            hl = next((x for x in reversed(anchors) if x["kind"] == "L"), None)
            cond = f"zamknięcie poniżej ostatniego HL {hl['price']:.5g} zmieni interpretację" if hl else None
        elif bias == "DOWN":
            lh = next((x for x in reversed(anchors) if x["kind"] == "H"), None)
            cond = f"zamknięcie powyżej ostatniego LH {lh['price']:.5g} zmieni interpretację" if lh else None
        return {"tf": self.tf, "bias": bias, "bias_anchors": [a["id"] for a in anchors], "last_final_leg": last, "provisional_tail": self.provisional_tail(),
                "change_condition": cond, "profile": self.profile}

    def snapshot(self, max_swings: int = 200) -> dict:
        sw = sorted(self.swings.values(), key=lambda s: s["origin_index"])[-max_swings:]
        return {"profile": self.profile, "profile_hash": self.profile_hash, "swings": sw, "legs": list(self.legs.values())[-max_swings:],
                "story": self.story(), "events": self.events[-500:]}


def prev_tol(prev: dict, tol_now: float) -> float:
    """Equality tolerance frozen in the EARLIER swing (never widened later by the current ATR)."""
    return prev.get("tolerance") or tol_now


def market_behavior(bars: list[dict], tf: str, tick: float, point: float | None = None, pip_size: float | None = None, context: str = "XAUUSD",
                    tf_s: int = 60, **kw) -> MarketBehavior:
    mb = MarketBehavior(tf, tf_s, tick=tick, point=point, pip_size=pip_size, context=context, **kw)
    for b in bars:
        mb.update(b)
    return mb


# ===================================================================== R22 regime v2
def _er(c: np.ndarray, n: int) -> float | None:
    if len(c) <= n:
        return None
    path = float(np.abs(np.diff(c[-n - 1:])).sum())
    return abs(float(c[-1] - c[-n - 1])) / path if path > 0 else 0.0


def _slope(c: np.ndarray, n: int) -> float | None:
    if len(c) <= n:
        return None
    y = c[-n - 1:]
    x = np.arange(n + 1, dtype=float)
    xm = x - x.mean()
    return float((xm * (y - y.mean())).sum() / (xm * xm).sum())


class RegimeMachine:
    """Hysteresis over closed bars; checkpoint = dict state (restart never recounts the same bar)."""

    def __init__(self, cfg: dict | None = None, tick: float = 0.01):
        self.cfg = dict(REGIME_CFG, **(cfg or {}))
        self.tick = tick
        self.hash = cfg_hash(self.cfg)
        self.st = {"state": "WARMING_UP", "candidate": None, "count_cand": 0, "count_fail": 0, "entered_at": None, "reason": None,
                   "last_bar_id": None, "cfg_hash": self.hash, "history": []}

    def checkpoint(self) -> dict:
        return json.loads(json.dumps(self.st))

    def restore(self, ck: dict) -> None:
        if ck.get("cfg_hash") != self.hash:
            raise ValueError("REGIME_CONFIG_CHANGED: nowa historia (stare snapshoty nie są przemalowywane)")
        self.st = json.loads(json.dumps(ck))

    def components(self, c: np.ndarray, atr: float | None, struct_bias: str) -> dict:
        cf = self.cfg
        hs = cf["horizons"]
        if len(c) <= max(hs) or atr is None:
            return {"status": "WARMING_UP"}
        ers = [_er(c, n) for n in hs]
        path_total = float(np.abs(np.diff(c[-max(hs) - 1:])).sum())
        if path_total == 0:
            return {"status": "FLAT", "er": ers, "e": 0.0, "d": None, "d_n": [None] * 3, "agreement": None, "structure": struct_bias}
        floor = cf["atr_floor_ticks"] * self.tick
        if atr < floor:
            return {"status": "ATR_BELOW_FLOOR", "er": ers}
        d_n = [math.tanh(n * _slope(c, n) / (2 * atr)) for n in hs]
        e, d = float(np.mean(ers)), float(np.mean(d_n))
        sgn = 1 if d > 0 else (-1 if d < 0 else 0)
        agree = sum(1 for x in d_n if sgn != 0 and np.sign(x) == sgn and abs(x) >= cf["agree_d"]) / len(hs)
        sb = 1 if struct_bias == "UP" else (-1 if struct_bias == "DOWN" else 0)
        return {"status": "OK", "er": [round(x, 4) for x in ers], "d_n": [round(x, 4) for x in d_n], "e": round(e, 4), "d": round(d, 4),
                "agreement": round(agree, 4), "structure": struct_bias, "structure_sign": sb}

    def candidate(self, comp: dict) -> tuple[str | None, list[str]]:
        cf = self.cfg
        if comp["status"] == "FLAT":
            return "RANGE", ["FLAT"]
        if comp["status"] != "OK":
            return None, [comp["status"]]
        e, d, ag, sb = comp["e"], comp["d"], comp["agreement"], comp["structure_sign"]
        why = []
        if e >= cf["trend_e"] and abs(d) >= cf["trend_d"] and ag >= cf["agree"] - 1e-9:
            want = 1 if d > 0 else -1
            if sb == want:
                return ("TREND_UP" if want > 0 else "TREND_DOWN"), why
            why.append("STRUCTURE_NOT_CONFIRMED" if sb == 0 else "STRUCTURE_OPPOSITE")
        else:
            if e < cf["trend_e"]:
                why.append("ER_BELOW_TREND")
            if abs(d) < cf["trend_d"]:
                why.append("DIRECTION_WEAK")
            if ag < cf["agree"] - 1e-9:
                why.append("HORIZONS_DISAGREE")
        if e <= cf["range_e"] and abs(d) <= cf["range_d"]:
            return "RANGE", why
        return "TRANSITION", why

    def strength(self, state: str, comp: dict) -> float | None:
        if comp.get("status") != "OK":
            return None
        e, d, ag = comp["e"], abs(comp["d"]), comp["agreement"]
        if state.startswith("TREND"):
            return round(100 * (0.4 * _clip(e / 0.35) + 0.4 * _clip(d / 0.5) + 0.2 * ag), 1)
        if state == "RANGE":
            return round(100 * _clip((0.28 - e) / 0.28) * _clip(1 - d / 0.4), 1)
        return None

    def step(self, bar_id: str, c: np.ndarray, atr: float | None, struct_bias: str, opposite_break: bool = False, vol: dict | None = None) -> dict:
        st, cf = self.st, self.cfg
        if st["last_bar_id"] == bar_id:                      # repeated poll / restart: no recount
            return self.view(None)
        comp = self.components(c, atr, struct_bias)
        cand, why = self.candidate(comp)
        prev = st["state"]
        new = prev
        reason = None
        if cand is None:
            new, reason = "WARMING_UP" if comp["status"] == "WARMING_UP" else prev, comp["status"]
        elif prev.startswith("TREND"):
            want = 1 if prev == "TREND_UP" else -1
            if opposite_break:
                new, reason = "TRANSITION", "OPPOSITE_STRUCTURE_BREAK"
                st["count_fail"] = 0
            else:
                ok = comp["status"] == "OK" and comp["e"] >= cf["hold_e"] and comp["d"] * want >= cf["hold_d"] and comp["structure_sign"] != -want
                st["count_fail"] = 0 if ok else st["count_fail"] + 1
                if st["count_fail"] >= cf["confirm"]:
                    new, reason, st["count_fail"] = "TRANSITION", "HOLD_CONDITIONS_FAILED_2X", 0
        elif prev == "RANGE":
            leave = comp["status"] == "OK" and (comp["e"] >= cf["exit_range_e"] or abs(comp["d"]) >= cf["exit_range_d"])
            st["count_fail"] = st["count_fail"] + 1 if leave else 0
            if st["count_fail"] >= cf["confirm"]:
                new, reason, st["count_fail"] = "TRANSITION", "RANGE_EXIT_2X", 0
        else:                                                # WARMING_UP / TRANSITION
            if prev == "WARMING_UP":
                new = "TRANSITION"
            if cand in ("TREND_UP", "TREND_DOWN", "RANGE"):
                st["count_cand"] = st["count_cand"] + 1 if st["candidate"] == cand else 1
                if st["count_cand"] >= cf["confirm"]:
                    new, reason, st["count_cand"] = cand, f"ENTER_{cand}_2X", 0
            else:
                st["count_cand"] = 0
        st["candidate"] = cand
        if new != prev:
            st["entered_at"] = bar_id
            st["history"].append({"bar_id": bar_id, "from": prev, "to": new, "reason": reason})
            st["history"] = st["history"][-500:]
        st["state"], st["reason"], st["last_bar_id"] = new, reason or st["reason"], bar_id
        return self.view(comp, why, vol)

    def view(self, comp: dict | None, why: list | None = None, vol: dict | None = None) -> dict:
        st = self.st
        need = self.cfg["confirm"]
        return {"profile": REGIME_PROFILE, "version": REGIME_VERSION, "cfg_hash": self.hash, "state": st["state"], "candidate": st["candidate"],
                "hysteresis": {"candidate_count": st["count_cand"], "fail_count": st["count_fail"], "needed": need}, "entered_at": st["entered_at"],
                "reason": st["reason"], "rejections": why or [], "components": comp, "strength": self.strength(st["state"], comp or {}),
                "strength_formula": STRENGTH_FORMULA, "strength_is_probability": False, "volatility": vol, "last_bar_id": st["last_bar_id"],
                "source_parity": "UNVERIFIED (MQ5 Arixis nieodczytany)"}


def regime_series(bars: list[dict], tf: str, tick: float, tf_s: int = 60, cfg: dict | None = None, keep: int = 300) -> dict:
    """Replay over closed bars with the shared MBA structure (as known at each bar) and the shared vol axis."""
    rm = RegimeMachine(cfg, tick)
    mb = MarketBehavior(tf, tf_s, tick=tick)
    c = np.array([b["c"] for b in bars], dtype=float)
    atr = atr_series([b["h"] for b in bars], [b["l"] for b in bars], c)
    atr_rel = np.array([a / cc if a else np.nan for a, cc in zip(atr, c)])
    out = []
    last_bias = "UNKNOWN"
    for i, b in enumerate(bars):
        evs = mb.update(b)
        bias = mb.bias_at(i)
        opp = last_bias in ("UP", "DOWN") and bias in ("UP", "DOWN") and bias != last_bias
        last_bias = bias if bias in ("UP", "DOWN") else last_bias
        v = rm.step(str(b["open_utc"]), c[:i + 1], atr[i], bias, opp, vol_axis(atr_rel, i, rm.cfg["vol_window"], rm.cfg["vol_min"], rm.cfg["vol_lo"],
                                                                           rm.cfg["vol_hi"]))
        if i >= len(bars) - keep:
            out.append({"t": b["open_utc"], "state": v["state"], "candidate": v["candidate"], "strength": v["strength"],
                        "volatility": (v["volatility"] or {}).get("state"), "available_at": _ts(b["open_utc"]) + tf_s})
        _ = evs
    return {"current": rm.view(rm.components(c, atr[-1] if atr else None, mb.bias_at(len(bars) - 1)), None,
                               vol_axis(atr_rel, len(bars) - 1, rm.cfg["vol_window"], rm.cfg["vol_min"], rm.cfg["vol_lo"], rm.cfg["vol_hi"]) if len(bars) else None)
            if bars else None, "series": out, "history": rm.st["history"][-50:], "checkpoint": rm.checkpoint()}


# ===================================================================== R24 SMMA(3) channel
class SmmaChannel:
    def __init__(self, n: int = 3, boundary: str = "CURRENT_CLOSED", lag: int = 0, deadband: float = 0.01, max_gap_s: float = 300.0, tf_s: int = 60,
                 context: str = "XAUUSD|M1"):
        if n < 1 or lag < 0:
            raise ValueError("SMMA_CONFIG_INVALID: n>=1, analytical_lag>=0")
        if boundary not in ("CURRENT_CLOSED", "PREVIOUS_BOUNDARY"):
            raise ValueError("SMMA_BOUNDARY_INVALID")
        self.n, self.boundary, self.lag, self.db, self.max_gap, self.tf_s, self.ctx = n, boundary, lag, deadband, max_gap_s, tf_s, context
        self.profile = {"profile": SMMA_PROFILE, "n": n, "boundary": boundary, "analytical_lag": lag, "deadband": deadband, "seed": "SMA_first_n"}
        self.hash = cfg_hash(self.profile)
        self.reset()

    def reset(self):
        self.seed_h, self.seed_l = [], []
        self.U = self.L = None
        self.hist: list[dict] = []          # per bar: (t, close, U, L)
        self.buf: list[dict] = []           # lag buffer of raw bars
        self.last_t = None
        self.events: dict[str, dict] = {}

    def checkpoint(self) -> dict:
        return {"hash": self.hash, "seed_h": self.seed_h, "seed_l": self.seed_l, "U": self.U, "L": self.L, "hist": self.hist[-3:], "buf": self.buf,
                "last_t": self.last_t}

    def restore(self, ck: dict):
        if ck["hash"] != self.hash:
            raise ValueError("SMMA_PROFILE_CHANGED")
        self.seed_h, self.seed_l, self.U, self.L, self.hist, self.buf, self.last_t = (ck["seed_h"], ck["seed_l"], ck["U"], ck["L"], ck["hist"],
                                                                                   ck["buf"], ck["last_t"])

    def update(self, bar: dict) -> dict:
        t = _ts(bar["open_utc"])
        if self.last_t is not None and t == self.last_t:
            return dict(self.hist[-1], dedup=True) if self.hist else {"status": "WARMUP"}
        gap = self.last_t is not None and t - self.last_t > self.max_gap
        self.last_t = t
        if gap:
            self.seed_h, self.seed_l, self.U, self.L, self.buf = [], [], None, None, []
            self.hist.append({"t": bar["open_utc"], "status": "GAP_RESEED"})
        self.buf.append({"h": float(bar["h"]), "l": float(bar["l"])})
        if len(self.buf) <= self.lag:
            rec = {"t": bar["open_utc"], "status": "WARMUP"}
            self.hist.append(rec)
            return rec
        src = self.buf[-1 - self.lag]
        self.buf = self.buf[-(self.lag + 1):]
        if self.U is None:
            self.seed_h.append(src["h"])
            self.seed_l.append(src["l"])
            if len(self.seed_h) == self.n:
                self.U, self.L = sum(self.seed_h) / self.n, sum(self.seed_l) / self.n
        else:
            self.U = ((self.n - 1) * self.U + src["h"]) / self.n
            self.L = ((self.n - 1) * self.L + src["l"]) / self.n
        c = float(bar["c"])
        if self.U is None:
            rec = {"t": bar["open_utc"], "status": "WARMUP", "close": c}
            self.hist.append(rec)
            return rec
        if self.U < self.L - 1e-12:
            raise ValueError("NUMERIC_ERROR: U<L")
        prev = self.hist[-1] if self.hist and self.hist[-1].get("U") is not None else None
        if self.boundary == "PREVIOUS_BOUNDARY":
            if prev is None:
                rec = {"t": bar["open_utc"], "status": "NO_PREVIOUS_BOUNDARY", "close": c, "U": self.U, "L": self.L}
                self.hist.append(rec)
                return rec
            u, l_ = prev["U"], prev["L"]
        else:
            u, l_ = self.U, self.L
        loc = "ABOVE" if c > u + self.db else ("BELOW" if c < l_ - self.db else ("BAND_TOUCH" if (abs(c - u) <= self.db or abs(c - l_) <= self.db) else "INSIDE"))
        ev = "NONE"
        pb = prev.get("bu") if prev else None
        if prev is not None and pb is not None:
            up = c > u + self.db and prev["close"] <= pb + self.db
            dn = c < l_ - self.db and prev["close"] >= prev["bl"] - self.db
            ev = "INVALID_CHANNEL" if (up and dn) else ("UP" if up else ("DOWN" if dn else "NONE"))
        rec = {"t": bar["open_utc"], "status": "OK", "close": c, "U": self.U, "L": self.L, "bu": u, "bl": l_, "location": loc, "event": ev}
        if ev in ("UP", "DOWN"):
            eid = hashlib.sha256(f"{self.ctx}|{bar['open_utc']}|{self.hash}|{ev}".encode()).hexdigest()[:16]
            rec["event_id"] = eid
            rec["confirmed_at"] = t + self.tf_s
            self.events.setdefault(eid, {"event_id": eid, "t": bar["open_utc"], "event": ev, "confirmed_at": t + self.tf_s, "close": c, "U": u, "L": l_})
        self.hist.append(rec)
        self.hist = self.hist[-2000:]
        return rec


def smma_series(bars: list[dict], **kw) -> dict:
    ch = SmmaChannel(**kw)
    recs = [ch.update(b) for b in bars]
    return {"profile": ch.profile, "hash": ch.hash, "series": recs[-300:], "events": list(ch.events.values())[-100:], "checkpoint": ch.checkpoint()}


# ===================================================================== R25 Z-score
def zscore_at(c: np.ndarray, t: int, n: int = 20, mode: str = "INCLUSIVE_N", ddof: int = 0, tick: float = 0.01, min_rel_std: float = 1e-5) -> dict:
    if not 0 <= ddof < n:
        raise ValueError("ZSCORE_DDOF_INVALID: 0<=ddof<n")
    if mode not in ("INCLUSIVE_N", "PREVIOUS_N"):
        raise ValueError("ZSCORE_MODE_INVALID")
    lo, hi = (t - n + 1, t + 1) if mode == "INCLUSIVE_N" else (t - n, t)
    if lo < 0:
        return {"z": None, "status": "WARMUP", "window": [lo, hi - 1], "mode": mode}
    w = np.asarray(c[lo:hi], dtype=np.float64)
    if not np.isfinite(w).all() or not np.isfinite(c[t]):
        return {"z": None, "status": "GAP", "window": [lo, hi - 1], "mode": mode}
    mean = float(w.mean())
    dev = w - mean                                                  # centred two-pass (no E[x^2]-E[x]^2 cancellation)
    var = float((dev * dev).sum() / (n - ddof))
    if var < 0:
        if var < -1e-12 * max(1.0, mean * mean):
            return {"z": None, "status": "NUMERIC_ERROR"}
        var = 0.0
    std = math.sqrt(var)
    floor = max(tick / math.sqrt(12.0), min_rel_std * abs(mean))
    base = {"mean": mean, "std": std, "floor": floor, "window": [lo, hi - 1], "mode": mode, "n": n, "ddof": ddof, "price_basis": "close",
            "algorithm": "two_pass_centered"}
    if std < floor:
        return dict(base, z=None, status="LOW_DISPERSION")
    z = (float(c[t]) - mean) / std
    return dict(base, z=z, status="OK", bound=math.sqrt(n - 1) if (mode == "INCLUSIVE_N" and ddof == 0) else None)


Z_HYP = {"version": "ZH-2.0.0", "H_MR": {"extreme": 2.0}, "H_BO": {"entry": 2.5, "exit_inside": 1.0}, "H_TP": {"ema": 200, "band": 1.5},
         "note": "progi = start kalibracji na train/dev, nie potwierdzone parametry; Z nie jest p-value; żadna hipoteza nie włącza handlu"}


def zscore_series(bars: list[dict], n: int = 20, mode: str = "INCLUSIVE_N", ddof: int = 0, tick: float = 0.01, context: str = "XAUUSD|M1",
                  keep: int = 300) -> dict:
    c = np.array([b["c"] for b in bars], dtype=float)
    zs = [zscore_at(c, t, n, mode, ddof, tick) for t in range(len(c))]
    from .common import ema
    e200 = ema(c, Z_HYP["H_TP"]["ema"]) if len(c) else np.array([])
    events = []
    bo_state = None
    for t in range(1, len(c)):
        z0, z1 = zs[t - 1].get("z"), zs[t].get("z")
        if z0 is None or z1 is None:
            bo_state = None
            continue
        ex = Z_HYP["H_MR"]["extreme"]
        if z0 < -ex <= z1:
            events.append(("H_MR", "LONG_CANDIDATE", t))
        elif z0 > ex >= z1:
            events.append(("H_MR", "SHORT_CANDIDATE", t))
        en = Z_HYP["H_BO"]["entry"]
        st = "UP" if z1 > en else ("DOWN" if z1 < -en else ("EXIT" if abs(z1) < Z_HYP["H_BO"]["exit_inside"] else bo_state))
        if st in ("UP", "DOWN") and bo_state != st:
            events.append(("H_BO", "LONG_CANDIDATE" if st == "UP" else "SHORT_CANDIDATE", t))   # first cross only, not the held state
        bo_state = st
        if np.isfinite(e200[t]) and t >= Z_HYP["H_TP"]["ema"]:
            tol = tick
            trend = "NEUTRAL" if abs(c[t] - e200[t]) <= tol else ("UP" if c[t] > e200[t] else "DOWN")
            b = Z_HYP["H_TP"]["band"]
            if trend == "UP" and z0 < -b <= z1:
                events.append(("H_TP", "LONG_CANDIDATE", t))
            elif trend == "DOWN" and z0 > b >= z1:
                events.append(("H_TP", "SHORT_CANDIDATE", t))
    ev = [{"event_id": hashlib.sha256(f"{context}|{h}|{bars[t]['open_utc']}|{mode}|{n}".encode()).hexdigest()[:16], "hypothesis": h, "kind": k,
           "t": bars[t]["open_utc"], "z": zs[t]["z"], "policy_id": f"{Z_PROFILE}:{h}:{mode}:n{n}"} for h, k, t in events]
    return {"profile": {"profile": Z_PROFILE, "n": n, "window_mode": mode, "ddof": ddof, "price_basis": "close", "algorithm": "two_pass_centered",
                        "min_std": "max(tick/sqrt(12), 1e-5*|mean|)"}, "current": zs[-1] if zs else None,
            "series": [{"t": bars[t]["open_utc"], "z": zs[t].get("z"), "status": zs[t]["status"]} for t in range(max(0, len(c) - keep), len(c))],
            "events": ev[-100:], "hypotheses": Z_HYP}


def percent_b_from_z(z: float, k: float) -> float:
    """Algebraic dependence (same mean/std/k): %B = 0.5 + z/(2k) - not an independent confirmation."""
    return 0.5 + z / (2 * k)


# ===================================================================== calibration (dev only) - R14.7
def calibrate_profiles(bars: list[dict], tick: float, profiles: list[str], dev_frac: float = 0.8, tf_s: int = 60) -> dict:
    """Threshold/parameter choice on the DEVELOPMENT part only (first dev_frac of time; inner fit 60% / score rest). Criteria are
    stability/false-break statistics, never a 'true regime' label from future returns. Holdout is not read."""
    n = len(bars)
    dev = bars[: int(n * dev_frac)]
    k = int(len(dev) * 0.6)
    fit, ev = dev[:k], dev[k:]
    out = {"dev_bars": len(dev), "holdout_read": False, "profiles": {}}
    if len(ev) < 300:
        return dict(out, status="INSUFFICIENT_EVIDENCE")
    if REGIME_PROFILE in profiles:
        trials = []
        for confirm in (2, 3):
            for te in (0.30, 0.35, 0.40):
                r = regime_series(ev, "M1", tick, tf_s, {"confirm": confirm, "trend_e": te}, keep=len(ev))
                sts = [x["state"] for x in r["series"]]
                sw = sum(1 for a, b in zip(sts, sts[1:]) if a != b)
                trials.append({"confirm": confirm, "trend_e": te, "switches_per_1000": 1000 * sw / max(1, len(sts)),
                               "share": {s: sts.count(s) / max(1, len(sts)) for s in set(sts)}})
        best = min(trials, key=lambda x: (x["switches_per_1000"] if x["share"].get("TRANSITION", 0) < 0.8 else 1e9))
        out["profiles"][REGIME_PROFILE] = {"trials": trials, "chosen": {k2: best[k2] for k2 in ("confirm", "trend_e")},
                                           "criterion": "stabilność (zmiany/1000 świec) przy TRANSITION<80% – bez etykiety 'prawdziwego reżimu'"}
    if SMMA_PROFILE in profiles:
        trials = []
        c = np.array([b["c"] for b in ev])
        for boundary in ("CURRENT_CLOSED", "PREVIOUS_BOUNDARY"):
            for dbt in (1, 2, 4):
                s = smma_series(ev, boundary=boundary, deadband=dbt * tick)
                ch = SmmaChannel(boundary=boundary, deadband=dbt * tick)
                recs = [ch.update(b) for b in ev]
                fb, nev = 0, 0
                for i, r in enumerate(recs):
                    if r.get("event") in ("UP", "DOWN") and i + 5 < len(recs):
                        nev += 1
                        fwd = c[i + 5] - c[i]
                        if (fwd < 0) if r["event"] == "UP" else (fwd > 0):
                            fb += 1
                trials.append({"boundary": boundary, "deadband_ticks": dbt, "events": nev, "false_break_5": fb / max(1, nev)})
                _ = s
        best = min(trials, key=lambda x: (x["false_break_5"], -x["events"]))
        out["profiles"][SMMA_PROFILE] = {"trials": trials, "chosen": {k2: best[k2] for k2 in ("boundary", "deadband_ticks")},
                                         "criterion": "odsetek fałszywych wybić po 5 świecach (bez kosztów – kontekst, nie wejście)"}
    if Z_PROFILE in profiles:
        trials = []
        c = np.array([b["c"] for b in ev])
        for mode in ("INCLUSIVE_N", "PREVIOUS_N"):
            for thr in (1.5, 2.0, 2.5):
                zs = [zscore_at(c, t, 20, mode, 0, tick).get("z") for t in range(len(c))]
                hits, rev = 0, 0
                for t in range(1, len(c) - 5):
                    if zs[t] is not None and abs(zs[t]) > thr:
                        hits += 1
                        if np.sign(c[t + 5] - c[t]) == -np.sign(zs[t]):
                            rev += 1
                trials.append({"mode": mode, "threshold": thr, "extremes": hits, "reversion_share_5": rev / max(1, hits)})
        out["profiles"][Z_PROFILE] = {"trials": trials, "note": "raport warunkowy; brak wyboru 'skuteczności Z' bez kosztów i polityki"}
    if "STRUCTURE_CAUSAL_V2" in profiles:
        trials = []
        for lr in (2, 3, 4):
            mb = market_behavior(fit, "M1", tick, left=lr, right=lr)
            legs = list(mb.legs.values())
            trials.append({"left_right": lr, "final_legs": len(legs), "ambiguous": sum(1 for e in mb.events if e["kind"] == "AMBIGUOUS_ORDER"),
                           "median_leg_bars": float(np.median([lg["bar_count"] for lg in legs])) if legs else None})
        out["profiles"]["STRUCTURE_CAUSAL_V2"] = {"trials": trials, "note": "dobór głębokości jako hiperparametr dev; wpływ na zadanie ocenia trener"}
    return dict(out, status="OK")
