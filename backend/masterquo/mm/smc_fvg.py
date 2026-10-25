"""SMC BoS / IDM / FVG continuation engine (PMW-MM-SMCFVG-1). RULE_STRATEGY - observation events, execution_allowed = False.

Structure: REUSES the verified closed-bar structure engine lab/context_ind/smc.py (PWM_SMC_PULLBACK_BAR_ATOMIC_v1: pullback swings,
BoS/CHoCH table, IDM ratchet, append-only events with available_at). This module never re-derives structure.

Ordering (causal, per closed bar i, after the structure engine processed bar i):
 1. CHOCH_x       -> every active setup is INVALIDATED (CHOCH); the engine stands down. A new setup is created only by a BOS whose
                     old_trend == new_trend (a continuation BoS) - the first such BoS after a CHOCH re-arms the engine.
 2. BOS_d (cont.) -> setup created once per BoS event id. A = the protected opposite structure point ACTIVE at the break (long: the
                     structure low), with its origin bar. ONE FVG scan over bars [A.origin_bar .. breaking bar] (bullish 3-candle gap:
                     low[k] > high[k-2], gap = [high[k-2], low[k]]; the engineering baseline - no other source rule available). The gap
                     list is frozen; later gaps are never added. No gap -> SETUP_INVALIDATED (NO_ELIGIBLE_FVG). Else IDM_PENDING.
 3. STRUCTURE_H published with reason IDM_CONFIRMED (long) -> B = that point (frozen; never moved later), LEG_CONFIRMED ->
                     WAITING_FOR_VALID_RETRACEMENT. Requires A < B.
 4. From the bar AFTER B's confirmation: depth(p) = (B - p) / (B - A). For each frozen gap the qualifying price is
                     p* = min(gap_top, B - d_min (B - A)); the gap can qualify only if p* >= gap_bottom. A bar qualifies when low <= p*
                     (bar-only fill: entry = p*, or the open if the bar opened inside the gap below p*). Touches of a gap above p* are
                     recorded as insufficient depth and never promoted later. Default d_min = 0.73 (prose rule); the 0.50 diagram label is
                     an unresolved ambiguity, available only as an explicitly selected profile.
 5. Entry -> stop = A - buffer, R = entry - stop (> 0 required), target = entry + 2R. Tick-rounded executable prices are reported
                     separately with R recomputed.
 Invalidation: opposite BoS/CHoCH, close beyond A (broken origin), invalid bar, wait > max_wait_bars (SETUP_EXPIRED).
Short = exact mirror: the same code runs in transformed coordinates x = -price (high' = -low, low' = -high).
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from ..lab.context_ind import smc as SM

VERSION = "PMW-MM-SMCFVG-1"
PROFILES = {"PROSE_73": 0.73, "DIAGRAM_50_UNRESOLVED": 0.50}
STATES = ("WAITING_FOR_TREND", "WAITING_FOR_BOS", "BOS_CONFIRMED", "GAPS_SCANNED", "IDM_PENDING", "LEG_CONFIRMED", "WAITING_FOR_VALID_RETRACEMENT",
          "ENTRY_TOUCH_CONFIRMED", "SETUP_INVALIDATED", "SETUP_EXPIRED", "OBSERVATION_ONLY")


@dataclass
class SMCFVGConfig:
    depth_min: float = 0.73
    profile: str = "PROSE_73"
    stop_buffer_points: float = 0.0
    target_r: float = 2.0
    max_wait_bars: int = 288
    idm_mode: str = "WICK"
    pb_mode: str = "WICK"
    tick: float = 0.01

    def validate(self):
        if self.profile not in PROFILES or abs(PROFILES[self.profile] - self.depth_min) > 1e-12:
            raise ValueError("SMCFVG_PROFILE_DEPTH_MISMATCH")         # 0.50 only when the 50% profile is explicitly selected
        if not (0 < self.depth_min < 1) or self.target_r <= 0 or self.max_wait_bars < 1 or self.stop_buffer_points < 0 or self.tick <= 0:
            raise ValueError("SMCFVG_PARAM_INVALID")


class ContinuationEngine:
    def __init__(self, cfg: SMCFVGConfig | None = None, tf_s: int = 300, symbol: str = "XAUUSD", tf: str = "M5"):
        self.cfg = cfg or SMCFVGConfig()
        self.cfg.validate()
        self.tf_s, self.symbol, self.tf = tf_s, symbol, tf
        self.smc = SM.SMC(idm_mode=self.cfg.idm_mode, pb_mode=self.cfg.pb_mode, tick=self.cfg.tick)
        self.bars: list[dict] = []
        self.setups: dict[str, dict] = {}
        self.events: list[dict] = []
        self.last_bos = None
        self.last_choch = None

    # transformed coordinates for the exact mirror
    @staticmethod
    def _tb(b: dict, s: int) -> tuple[float, float, float, float]:
        return (b["o"], b["h"], b["l"], b["c"]) if s > 0 else (-b["o"], -b["l"], -b["h"], -b["c"])

    def _emit(self, st: dict, kind: str, i: int, **kw):
        e = {"event_id": f"{st['setup_id']}:{kind}", "kind": kind, "setup_id": st["setup_id"], "bar": i, "bar_ts": self.bars[i]["t"],
             "available_at": self.bars[i]["t"] + self.tf_s, "direction": st["direction"], "state": st["state"], **kw}
        if all(x["event_id"] != e["event_id"] for x in self.events[-50:]):
            self.events.append(e)
        return e

    def _set(self, st, state, i, why):
        st["history"].append({"bar": i, "ts": self.bars[i]["t"] + self.tf_s, "from": st["state"], "to": state, "why": why})
        st["state"] = state

    def _new_setup(self, ev: dict, i: int, res: dict):
        d = "LONG" if ev["kind"] == "BOS_UP" else "SHORT"
        s = 1 if d == "LONG" else -1
        sid = f"SMCC-{d}-{ev['event_id']}-{i}"
        if sid in self.setups:
            return
        opp = "L" if s > 0 else "H"
        slot = res["slots"][opp]
        st = {"setup_id": sid, "direction": d, "s": s, "state": "BOS_CONFIRMED", "history": [], "bos": {"event_id": ev["event_id"], "bar": i,
              "ts": self.bars[i]["t"], "price": self.bars[i]["c"], "level": ev.get("level")}, "choch": self.last_choch,
              "structure_tf": self.tf, "version": VERSION, "config": asdict(self.cfg), "execution_allowed": False}
        self.setups[sid] = st
        if slot.get("status") != "ACTIVE" or slot.get("point_id") not in self.smc.points:
            self._set(st, "SETUP_INVALIDATED", i, "NO_PROTECTED_ORIGIN")
            return self._emit(st, "INVALIDATED", i, reason="NO_PROTECTED_ORIGIN")
        pt = self.smc.points[slot["point_id"]]
        st["A"] = {"price": pt["price"], "bar": pt["origin_bar"], "ts": self.bars[pt["origin_bar"]]["t"], "point_id": pt["point_id"],
                   "available_at": pt["available_at"]}
        gaps = []
        for k in range(max(pt["origin_bar"], 0) + 2, i + 1):                     # one scan, origin .. breaking bar
            _, h2, _, _ = self._tb(self.bars[k - 2], s)
            _, _, lk, _ = self._tb(self.bars[k], s)
            if lk > h2:
                lo_t, hi_t = h2, lk
                lo, hi = (lo_t, hi_t) if s > 0 else (-hi_t, -lo_t)
                g = {"gap_id": f"FVG-{k}", "bar": k, "ts": self.bars[k]["t"], "low": lo, "high": hi, "t_low": lo_t, "t_high": hi_t}
                if all(not (abs(x["t_low"] - lo_t) < 1e-12 and abs(x["t_high"] - hi_t) < 1e-12) for x in gaps):
                    gaps.append(g)
        st["gaps"] = gaps
        self._set(st, "GAPS_SCANNED", i, f"{len(gaps)} gaps in [{pt['origin_bar']}, {i}]")
        if not gaps:
            self._set(st, "SETUP_INVALIDATED", i, "NO_ELIGIBLE_FVG")
            return self._emit(st, "INVALIDATED", i, reason="NO_ELIGIBLE_FVG")
        self._set(st, "IDM_PENDING", i, "waiting for IDM-confirmed structural extreme")
        self._emit(st, "BOS_SETUP", i, A=st["A"], gaps=[{k: g[k] for k in ("gap_id", "bar", "ts", "low", "high")} for g in gaps])

    def _live(self):
        return [st for st in self.setups.values() if st["state"] in ("IDM_PENDING", "LEG_CONFIRMED", "WAITING_FOR_VALID_RETRACEMENT")]

    def update(self, bar: dict, t_close: float) -> dict:
        """bar: {open_utc|t, o, h, l, c} - a CLOSED bar. Returns the structure result + events emitted on this bar."""
        t = float(bar["t"]) if "t" in bar else _iso_ts(bar["open_utc"])
        if self.bars and t <= self.bars[-1]["t"]:
            return {"processed": False, "events": []}
        b = {"t": t, "o": float(bar["o"]), "h": float(bar["h"]), "l": float(bar["l"]), "c": float(bar["c"])}
        n0 = len(self.events)
        i = len(self.bars)
        self.bars.append(b)
        valid = all(math.isfinite(b[k]) and b[k] > 0 for k in ("o", "h", "l", "c")) and b["h"] >= max(b["o"], b["c"]) and b["l"] <= min(b["o"], b["c"])
        if not valid:
            for st in self._live():
                self._set(st, "SETUP_INVALIDATED", i, "INVALID_BAR")
                self._emit(st, "INVALIDATED", i, reason="INVALID_BAR")
            return {"processed": True, "events": self.events[n0:], "quality": "INVALID"}
        res = self.smc.update({"open_utc": bar.get("open_utc", t), "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"]}, t_close)
        # 4. retracement / entry for setups confirmed on EARLIER bars (uses this bar's range)
        for st in self._live():
            if st["state"] == "WAITING_FOR_VALID_RETRACEMENT" and i > st["B"]["confirm_bar"]:
                self._retrace(st, i)
        for st in self._live():
            if st["state"] in ("IDM_PENDING", "WAITING_FOR_VALID_RETRACEMENT"):
                s = st["s"]
                _, _, _, ct = self._tb(b, s)
                if ct < s * st["A"]["price"]:
                    self._set(st, "SETUP_INVALIDATED", i, "CLOSE_BEYOND_ORIGIN_A")
                    self._emit(st, "INVALIDATED", i, reason="CLOSE_BEYOND_ORIGIN_A")
                elif i - st["bos"]["bar"] > self.cfg.max_wait_bars:
                    self._set(st, "SETUP_EXPIRED", i, "MAX_WAIT")
                    self._emit(st, "EXPIRED", i, reason="MAX_WAIT")
        # structure events of this bar (append-only, in engine order)
        for ev in res["events"]:
            k = ev["kind"]
            if k.startswith("CHOCH_"):
                self.last_choch = {"event_id": ev["event_id"], "kind": k, "bar": i, "ts": t}
                for st in self._live():
                    self._set(st, "SETUP_INVALIDATED", i, f"{k}_STAND_DOWN")
                    self._emit(st, "INVALIDATED", i, reason=f"{k}_STAND_DOWN")
            elif k in ("BOS_UP", "BOS_DOWN"):
                self.last_bos = {"event_id": ev["event_id"], "kind": k, "bar": i, "ts": t}
                d = "LONG" if k == "BOS_UP" else "SHORT"
                for st in self._live():
                    if st["direction"] != d:
                        self._set(st, "SETUP_INVALIDATED", i, f"OPPOSITE_{k}")
                        self._emit(st, "INVALIDATED", i, reason=f"OPPOSITE_{k}")
                if ev.get("old_trend") == ev.get("new_trend"):          # continuation BoS only (not NONE->d, not a CHoCH)
                    self._new_setup(ev, i, res)
            elif k in ("STRUCTURE_H", "STRUCTURE_L") and ev.get("reason") == "IDM_CONFIRMED":
                d = "LONG" if k == "STRUCTURE_H" else "SHORT"
                idm = next((x for x in res["events"] if x["kind"] == "IDM" and x["event_id"] == ev.get("idm_event")), None)
                for st in self._live():
                    if st["direction"] == d and st["state"] == "IDM_PENDING":
                        s = st["s"]
                        B = ev["price"]
                        if not (s * B > s * st["A"]["price"]):
                            self._set(st, "SETUP_INVALIDATED", i, "LEG_GEOMETRY_INVALID")
                            self._emit(st, "INVALIDATED", i, reason="LEG_GEOMETRY_INVALID")
                            continue
                        st["B"] = {"price": B, "bar": ev["origin_bar"], "ts": self.bars[ev["origin_bar"]]["t"], "confirm_bar": i, "confirm_ts": t_close}
                        st["idm"] = {"level": idm.get("ref") if idm else None, "kind": idm.get("ref_kind") if idm else None, "confirmed_ts": t_close,
                                     "status": "TAKEN"}
                        self._set(st, "LEG_CONFIRMED", i, "IDM taken; B frozen")
                        self._set(st, "WAITING_FOR_VALID_RETRACEMENT", i, "retracement from the next bar")
                        self._emit(st, "LEG_CONFIRMED", i, B=st["B"], idm=st["idm"])
        return {"processed": True, "trend": res["trend"], "events": self.events[n0:], "quality": "OK"}

    def _retrace(self, st: dict, i: int):
        s, cfg = st["s"], self.cfg
        A, B = s * st["A"]["price"], s * st["B"]["price"]
        o, h, lo, c = self._tb(self.bars[i], s)
        best = None
        for g in st["gaps"]:
            p_star = min(g["t_high"], B - cfg.depth_min * (B - A))
            if p_star < g["t_low"] - 1e-12:
                continue                                                  # this gap can never satisfy the depth rule
            if lo <= p_star:
                entry_t = o if (g["t_low"] <= o < p_star) else p_star     # opened inside the gap below p*: filled at the open
                if best is None or entry_t > best[0]:
                    best = (entry_t, g)
            elif lo <= g["t_high"]:
                st.setdefault("shallow_touches", []).append({"bar": i, "gap_id": g["gap_id"], "depth": (B - lo) / (B - A)})
        if best is None:
            return
        entry_t, g = best
        depth = (B - entry_t) / (B - A)
        entry = s * entry_t
        stop = st["A"]["price"] - s * cfg.stop_buffer_points * cfg.tick           # buffer in ticks beyond A
        R = s * (entry - stop)
        if not (R > 0) or not math.isfinite(R):
            self._set(st, "SETUP_INVALIDATED", i, "INVALID_RISK_GEOMETRY")
            return self._emit(st, "INVALIDATED", i, reason="INVALID_RISK_GEOMETRY")
        target = entry + s * cfg.target_r * R
        tk = cfg.tick
        ex_entry, ex_stop = round(entry / tk) * tk, round(stop / tk) * tk
        ex_R = s * (ex_entry - ex_stop)
        st["entry"] = {"bar": i, "ts": self.bars[i]["t"], "gap_id": g["gap_id"], "gap": [g["low"], g["high"]], "depth": depth, "depth_min": cfg.depth_min,
                       "entry": entry, "stop": stop, "R": R, "target": target, "fill_convention": "BAR_OHLC_CONSERVATIVE (p* or open inside gap)",
                       "executable": {"entry": ex_entry, "stop": ex_stop, "R": ex_R, "target": round((ex_entry + s * cfg.target_r * ex_R) / tk) * tk}}
        self._set(st, "ENTRY_TOUCH_CONFIRMED", i, f"gap {g['gap_id']} depth {depth:.3f} >= {cfg.depth_min}")
        self._emit(st, "ENTRY_TOUCH", i, **st["entry"], A=st["A"], B=st["B"], idm=st.get("idm"), bos=st["bos"], choch=st.get("choch"),
                   execution_allowed=False)


def _iso_ts(s) -> float:
    from datetime import datetime, timezone
    if isinstance(s, (int, float)):
        return float(s)
    return datetime.fromisoformat(str(s).replace("Z", "+00:00")).replace(tzinfo=timezone.utc).timestamp()


def run(bars, cfg: SMCFVGConfig | None = None, tf_s: int = 300, symbol: str = "XAUUSD", tf: str = "M5") -> ContinuationEngine:
    e = ContinuationEngine(cfg, tf_s, symbol, tf)
    for k in range(len(bars.t)):
        e.update({"t": float(bars.t[k]), "o": bars.o[k], "h": bars.h[k], "l": bars.l[k], "c": bars.c[k]}, float(bars.t[k]) + tf_s)
    return e


def evaluate(bars, cfg: SMCFVGConfig, tf_s: int, horizon: int = 96, spread: float = 0.0) -> dict:
    """Setup statistics + hypothetical stop/target outcome after each entry (bar OHLC; same bar touching both = STOP, conservative;
    entry bar itself is excluded; spread added against the entry). Not an order backtest."""
    e = run(bars, cfg, tf_s)
    st = list(e.setups.values())
    outs = []
    for x in st:
        if x["state"] != "ENTRY_TOUCH_CONFIRMED":
            continue
        en, s = x["entry"], x["s"]
        res, r_mult = "TIMEOUT", None
        for k in range(en["bar"] + 1, min(len(bars.t), en["bar"] + 1 + horizon)):
            hit_stop = (bars.l[k] <= en["stop"]) if s > 0 else (bars.h[k] >= en["stop"])
            hit_tgt = (bars.h[k] >= en["target"]) if s > 0 else (bars.l[k] <= en["target"])
            if hit_stop:
                res, r_mult = "STOP", -1.0 - spread / en["R"]
                break
            if hit_tgt:
                res, r_mult = "TARGET", cfg.target_r - spread / en["R"]
                break
        outs.append({"setup_id": x["setup_id"], "direction": x["direction"], "outcome": res, "r": r_mult})
    by = {}
    for x in st:
        by[x["state"]] = by.get(x["state"], 0) + 1
    rs = [o["r"] for o in outs if o["r"] is not None]
    return {"setups": len(st), "by_final_state": by, "entries": len(outs), "long": sum(o["direction"] == "LONG" for o in outs),
            "short": sum(o["direction"] == "SHORT" for o in outs), "target": sum(o["outcome"] == "TARGET" for o in outs),
            "stop": sum(o["outcome"] == "STOP" for o in outs), "timeout": sum(o["outcome"] == "TIMEOUT" for o in outs),
            "mean_r_resolved": (sum(rs) / len(rs)) if rs else None, "spread_assumption": spread, "horizon_bars": horizon,
            "invalidation_reasons": _reasons(st), "config": asdict(cfg)}


def _reasons(st) -> dict:
    out = {}
    for x in st:
        if x["state"] in ("SETUP_INVALIDATED", "SETUP_EXPIRED") and x["history"]:
            r = x["history"][-1]["why"]
            out[r] = out.get(r, 0) + 1
    return out
