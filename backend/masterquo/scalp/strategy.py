"""M5 Range -> M1 Sweep/Reclaim -> Retest (profile MQ-SCALP-RANGE-SWEEP-1.0.0-RESEARCH) - causal state machine.

Driven by CLOSED bars in time order (`on_m5_close`, `on_m1_close`); the same object runs in replay and in the live
SHADOW service, so replay and live share one implementation. Every transition is journaled with timestamp, ids,
evidence and reason. The machine only proposes ENTRY_CANDIDATE plans; gates (quote, cost, risk, calendar, permission)
are applied by the caller, and READY_EXECUTION is impossible while EXECUTION_AUTHORIZED is false.

States: WARMUP, SEARCH_RANGE, RANGE_ARMED, WAIT_SWEEP, WAIT_RETEST, ENTRY_CANDIDATE, READY_SHADOW, READY_EXECUTION,
BASE_OPEN, BASE_HEDGED, EXITING, COOLDOWN, EXPIRED, INVALIDATED, MISSED, BLOCKED, ERROR_RECOVERY.

Time: every bar is identified by open time (epoch seconds UTC); it is known at open + tf. A decision at time T only uses
bars with close <= T. The M1 zone is frozen at arming (known_at); only M1 bars that CLOSE after known_at can sweep it.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from . import candles_sci, indicators as ind

STATES = ("WARMUP", "SEARCH_RANGE", "RANGE_ARMED", "WAIT_SWEEP", "WAIT_RETEST", "ENTRY_CANDIDATE", "READY_SHADOW", "READY_EXECUTION",
          "BASE_OPEN", "BASE_HEDGED", "EXITING", "COOLDOWN", "EXPIRED", "INVALIDATED", "MISSED", "BLOCKED", "ERROR_RECOVERY")
PROFILE_PATH = Path(__file__).resolve().parents[3] / "config" / "scalp_profile_v1.json"


def load_profile(path: Path | None = None, instrument: str | None = None) -> dict:
    """Profile of the instrument (config/instruments_v1.json -> scalp_profile); default XAUUSD (PROFILE_PATH)."""
    if path is None and instrument and instrument != "XAUUSD":
        import mq_instruments
        path = mq_instruments.ROOT / mq_instruments.profile(instrument)["scalp_profile"]
    raw = json.loads((path or PROFILE_PATH).read_text(encoding="utf-8"))
    return raw


def profile_hash(p: dict) -> str:
    return hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest()[:16]


def V(p: dict, *keys, default=None):
    x = p
    for k in keys:
        if not isinstance(x, dict) or k not in x:
            return default                              # older profile without this switch -> documented default (feature off)
        x = x[k]
    return x["value"] if isinstance(x, dict) and "value" in x else x


def with_overrides(p: dict, overrides: dict) -> dict:
    """Copy of a profile with dotted-path overrides ({"trigger.tick_volume_ratio_min": 1.5}) - variant comparison."""
    import copy
    q = copy.deepcopy(p)
    for path, val in overrides.items():
        node = q
        keys = path.split(".")
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        leaf = node.get(keys[-1])
        if isinstance(leaf, dict) and "value" in leaf:
            leaf["value"] = val
        else:
            node[keys[-1]] = {"value": val, "unit": "variant override"}
    q["profile_id"] = p["profile_id"] + "+" + ",".join(f"{k}={v}" for k, v in sorted(overrides.items())) if overrides else p["profile_id"]
    return q


def ts(s) -> int:
    if isinstance(s, (int, float)):
        return int(s)
    return int(datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp())


def iso_ts(t: int) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Series:
    """Closed bars of one TF as parallel lists + causal indicator caches (recomputed on append - small windows)."""

    def __init__(self, tf_min: int):
        self.tf = tf_min * 60
        self.t: list[int] = []
        self.o: list[float] = []
        self.h: list[float] = []
        self.l: list[float] = []
        self.c: list[float] = []
        self.tv: list[float | None] = []
        self.sp: list[float | None] = []
        self._atr: list = []

    def append(self, b: dict) -> bool:
        t = ts(b["open_utc"])
        if self.t and t <= self.t[-1]:
            return False                                       # duplicate / out of order: ignored (revision handled by caller)
        self.t.append(t)
        self.o.append(float(b["o"]))
        self.h.append(float(b["h"]))
        self.l.append(float(b["l"]))
        self.c.append(float(b["c"]))
        self.tv.append(None if b.get("tv") is None else float(b["tv"]))
        self.sp.append(None if b.get("spread_price") is None else float(b["spread_price"]))
        self._update_atr()
        return True

    def _update_atr(self, n: int = 14) -> None:
        i = len(self.c) - 1
        tr = self.h[i] - self.l[i] if i == 0 else max(self.h[i] - self.l[i], abs(self.h[i] - self.c[i - 1]), abs(self.l[i] - self.c[i - 1]))
        if i < n - 1:
            self._atr.append(None)
            self._tr = getattr(self, "_tr", []) + [tr]
        elif i == n - 1:
            self._tr = getattr(self, "_tr", []) + [tr]
            self._atr.append(sum(self._tr) / n)
        else:
            self._atr.append((self._atr[-1] * (n - 1) + tr) / n)

    def atr(self, i: int = -1):
        return self._atr[i] if self._atr else None

    def close_time(self, i: int = -1) -> int:
        return self.t[i] + self.tf

    def __len__(self):
        return len(self.t)


def context(series: Series, prof: dict) -> dict:
    """SAR trend, BB basis slope (ATR/bar over 3 closed bars) and BandWidth percentile of the last closed bar."""
    n = len(series)
    if n < 125:
        return {"status": "WARMUP", "bars": n}
    k = max(0, n - 260)
    c, h, lo = series.c[k:], series.h[k:], series.l[k:]
    a = series._atr[k:]
    bb = ind.bollinger(c, a, V(prof, "indicators", "bollinger", "period"), V(prof, "indicators", "bollinger", "deviation"))[-1]
    sr = ind.sar(h, lo, V(prof, "indicators", "sar", "step"), V(prof, "indicators", "sar", "maximum"))[-1]
    if not bb or bb["slope_atr_per_bar"] is None or bb["bandwidth_pct100"] is None or not sr:
        return {"status": "WARMUP", "bars": n}
    return {"status": "OK", "sar_trend": sr["trend"], "sar": sr["sar"], "slope": bb["slope_atr_per_bar"], "bw_pct": bb["bandwidth_pct100"],
            "pct_b": bb["pct_b"], "basis": bb["basis"], "upper": bb["upper"], "lower": bb["lower"], "as_of": iso_ts(series.close_time())}


def fade_blocked(ctx: dict[str, dict], direction: str, prof: dict) -> tuple[bool | None, str]:
    """Block a fade when the context TFs show a strong trend against it (SAR + slope + wide bands).
    mode BOTH (1.0.0 default): M30 AND M15; ANY: M30 OR M15; ANY_PLUS_H1: M30 OR M15 OR H1."""
    if not V(prof, "context_filter", "enabled"):
        return False, "filtr kontekstu wyłączony (ablation)"
    mode = V(prof, "context_filter", "mode", default="BOTH")
    use = {k: v for k, v in ctx.items() if k in (("M30", "M15", "H1") if mode == "ANY_PLUS_H1" else ("M30", "M15"))}
    if any(x.get("status") != "OK" for x in use.values()) or not use:
        return None, "WARMUP kontekstu " + "/".join(use or ctx)
    s_max, bw_p = V(prof, "context_filter", "slope_atr_per_bar"), V(prof, "context_filter", "bandwidth_percentile")
    against = "DOWN" if direction == "BUY" else "UP"
    hit = {k: x["sar_trend"] == against and abs(x["slope"]) > s_max and (x["slope"] < 0) == (against == "DOWN") and x["bw_pct"] > bw_p
           for k, x in use.items()}
    strong = all(hit.values()) if mode == "BOTH" else any(hit.values())
    tfs = "/".join(k for k, v in hit.items() if v)
    return strong, f"silny trend przeciwny ({tfs}, tryb {mode})" if strong else f"kontekst dopuszcza fade (tryb {mode})"


def session_blocked(t: int, prof: dict) -> tuple[bool, str]:
    """Session filter: allowed UTC hours and N minutes after the London / New York open (IANA DST)."""
    from . import sessions as _s
    hours = V(prof, "session_filter", "allowed_utc_hours")
    dt = datetime.fromtimestamp(t, timezone.utc)
    if hours is not None and dt.hour not in hours:
        return True, f"godzina {dt.hour} UTC poza dozwolonymi {hours}"
    n = V(prof, "session_filter", "block_after_open_min", default=0) or 0
    if n:
        for name, a, _b in _s.windows(dt):
            if name in ("LONDON", "NEW_YORK") and 0 <= (dt - a).total_seconds() < n * 60:
                return True, f"{n} min po otwarciu {name}"
    return False, "sesja dozwolona"


def entry_filters(mach: "ScalpMachine", plan: dict, prof: dict) -> tuple[bool | None, str]:
    """Shared by replay and the live SHADOW service: context trend filter + session filter. None = WARMUP (blocked)."""
    ctx = {"M30": context(mach.m30, prof), "M15": context(mach.m15, prof), "H1": context(mach.h1, prof)}
    blk, why = fade_blocked(ctx, plan["direction"], prof)
    if blk is None or blk:
        return blk, why
    sb, swhy = session_blocked(plan["decision_ts"], prof)
    if sb:
        return True, swhy
    return False, why + "; " + swhy


def detect_range(m5: Series, prof: dict) -> dict:
    """Range on the last `lookback` closed M5 (+ reasons when not)."""
    n = V(prof, "range", "lookback_m5_bars")
    if len(m5) < max(n, 25) or m5.atr() is None:
        return {"ok": False, "state": "WARMUP", "reason": "za mało zamkniętych M5 (ATR14 / ER10)"}
    i0 = len(m5) - n
    H, L = max(m5.h[i0:]), min(m5.l[i0:])
    W, a = H - L, m5.atr()
    er = ind.er(m5.c[-11:], 10)[-1]
    info = {"L": L, "H": H, "MID": (H + L) / 2, "W": W, "atr_m5": a, "w_atr": W / a, "er10": er}
    if not (V(prof, "range", "width_min_atr") <= W / a <= V(prof, "range", "width_max_atr")):
        return dict(info, ok=False, state="SEARCH_RANGE", reason=f"szerokość {W / a:.2f} ATR poza [{V(prof, 'range', 'width_min_atr')}, {V(prof, 'range', 'width_max_atr')}]")
    if er is None or er > V(prof, "range", "er10_max"):
        flat = sum(abs(m5.c[k] - m5.c[k - 1]) for k in range(len(m5) - 10, len(m5))) == 0
        return dict(info, ok=False, state="SEARCH_RANGE", reason="płaski rynek (ER mianownik 0)" if flat else f"ER10 {er:.2f} > {V(prof, 'range', 'er10_max')}")
    tol = V(prof, "range", "touch_tolerance_atr") * a
    sep = V(prof, "range", "touch_min_separation_bars") + 1
    need = V(prof, "range", "touch_min_per_edge")

    def touches(cond):
        sel: list[int] = []
        for k in range(i0, len(m5)):
            if cond(k) and (not sel or k - sel[-1] >= sep):
                sel.append(k)
        return sel
    lo_t, hi_t = touches(lambda k: m5.l[k] <= L + tol), touches(lambda k: m5.h[k] >= H - tol)
    info.update(tol=tol, touches_low=len(lo_t), touches_high=len(hi_t))
    if len(lo_t) < need or len(hi_t) < need:
        return dict(info, ok=False, state="SEARCH_RANGE", reason=f"dotknięcia L/H {len(lo_t)}/{len(hi_t)} < {need} (z separacją {sep - 1} M5)")
    return dict(info, ok=True, bars=[iso_ts(m5.t[k]) for k in (i0, len(m5) - 1)])


def find_zone(m1: Series, side: str, edge: float, tol: float, since: int, until: int, max_bars: int) -> dict | None:
    """Most recent run (<= max_bars consecutive closed M1, close <= until, open >= since) touching the edge tolerance."""
    touch = (lambda k: m1.l[k] <= edge + tol) if side == "LOW" else (lambda k: m1.h[k] >= edge - tol)
    k = len(m1) - 1
    while k >= 0 and m1.close_time(k) > until:
        k -= 1
    last = None
    while k >= 0 and m1.t[k] >= since:
        if touch(k):
            last = k
            break
        k -= 1
    if last is None:
        return None
    run = [last]
    while len(run) < max_bars and run[0] - 1 >= 0 and m1.t[run[0] - 1] >= since and touch(run[0] - 1) and m1.t[run[0]] - m1.t[run[0] - 1] == m1.tf:
        run.insert(0, run[0] - 1)
    return {"z_low": min(m1.l[k] for k in run), "z_high": max(m1.h[k] for k in run), "bars": [iso_ts(m1.t[k]) for k in run]}


class ScalpMachine:
    def __init__(self, prof: dict, tick: float = 0.01):
        self.p, self.tick = prof, tick
        self.m1, self.m5, self.m15, self.m30, self.h1 = Series(1), Series(5), Series(15), Series(30), Series(60)
        self.range: dict | None = None
        self.dirs: dict[str, dict] = {}
        self.state = "WARMUP"
        self.journal: list[dict] = []
        self.cycle_active = False
        self.cooldown_until = 0
        self.candidates: list[dict] = []          # ENTRY_CANDIDATE plans emitted (drained by the caller)
        self.last_reading: dict | None = None
        self._used_sweeps: set[str] = set()

    # ------------------------------------------------------------ journal
    def _j(self, t: int, state: str, reason: str, **ev) -> None:
        self.journal.append({"t": iso_ts(t), "state": state, "reason": reason, "range_id": (self.range or {}).get("range_id"), **ev})
        if len(self.journal) > 500:
            del self.journal[:100]

    # ------------------------------------------------------------ inputs
    def add_context(self, tf: int, b: dict) -> None:
        {15: self.m15, 30: self.m30, 60: self.h1}[tf].append(b)

    def on_m5_close(self, b: dict) -> None:
        if not self.m5.append(b):
            return
        T = self.m5.close_time()
        r = self.range
        if r and T >= r["ttl_end"]:
            self._j(T, "EXPIRED", f"TTL {V(self.p, 'range', 'ttl_m5_closes')} zamknięć M5 minął", range_id=r["range_id"])
            self.range, self.dirs = None, {}
        if self.range:
            return
        d = detect_range(self.m5, self.p)
        if not d["ok"]:
            if d["state"] != self.state:
                self._j(T, d["state"], d["reason"])
            self.state = d["state"]
            self.last_detect = d
            return
        rid = "RNG-" + hashlib.sha256(f"{T}|{d['L']}|{d['H']}".encode()).hexdigest()[:10]
        a = d["atr_m5"]
        self.range = dict(d, range_id=rid, armed_at=T, ttl_end=T + V(self.p, "range", "ttl_m5_closes") * 300,
                          inval_lo=d["L"] - V(self.p, "range", "invalidation_outside_atr") * a,
                          inval_hi=d["H"] + V(self.p, "range", "invalidation_outside_atr") * a, outside_run=0)
        self.last_detect = d
        self.state = "RANGE_ARMED"
        self._j(T, "RANGE_ARMED", "zakres zamrożony", L=d["L"], H=d["H"], MID=d["MID"], W=d["W"], atr_m5=a)
        since = self.m5.t[len(self.m5) - V(self.p, "range", "lookback_m5_bars")]
        zmax = min(V(self.p, "zone", "max_width_atr_m5") * a, V(self.p, "zone", "max_width_range_fraction") * d["W"])
        for direction, side, edge in (("BUY", "LOW", d["L"]), ("SELL", "HIGH", d["H"])):
            z = find_zone(self.m1, side, edge, d["tol"], since, T, V(self.p, "zone", "max_m1_bars"))
            if not z:
                self.dirs[direction] = {"state": "BLOCKED", "reason": "brak sekcji M1 przy granicy"}
            elif z["z_high"] - z["z_low"] > zmax:
                self.dirs[direction] = {"state": "BLOCKED", "reason": f"sekcja M1 za szeroka ({z['z_high'] - z['z_low']:.2f} > {zmax:.2f})", "zone": z}
            else:
                self.dirs[direction] = {"state": "WAIT_SWEEP", "zone": dict(z, known_at=iso_ts(T), known_at_ts=T), "reason": "czekam na sweep i reclaim"}
            self._j(T, self.dirs[direction]["state"], self.dirs[direction]["reason"], direction=direction)

    def on_m1_close(self, b: dict) -> list[dict]:
        if not self.m1.append(b):
            return []
        i = len(self.m1) - 1
        T = self.m1.close_time()
        out: list[dict] = []
        a1 = self.m1.atr()
        tv_r = candles_sci.tv_ratio(self.m1.tv, i)
        k = max(0, i - 24)                                            # window: 3-bar patterns + 20-bar tick-volume median
        m = self.m1
        self.last_reading = candles_sci.read_bar(m.o[k:], m.h[k:], m.l[k:], m.c[k:], [iso_ts(x) for x in m.t[k:]], i - k, a1, "M1", iso_ts(T),
                                                 m.tv[k:], (self.range["L"], self.range["H"]) if self.range else None)
        r = self.range
        if not r:
            return out
        c = self.m1.c[i]
        r["outside_run"] = r["outside_run"] + 1 if (c < r["inval_lo"] or c > r["inval_hi"]) else 0
        if r["outside_run"] >= V(self.p, "range", "invalidation_consecutive_m1_closes"):
            self._j(T, "INVALIDATED", "dwa kolejne zamknięcia M1 poza zakresem ± 0.25 ATR")
            self.range, self.dirs, self.state = None, {}, "INVALIDATED"
            return out
        if a1 is None:
            return out
        for direction, d in self.dirs.items():
            cand = self._step_dir(direction, d, i, T, a1, tv_r)
            if cand:
                out.append(cand)
        self.state = self._overall()
        self.candidates += out
        return out

    def _overall(self) -> str:
        st = [d["state"] for d in self.dirs.values()]
        for s in ("ENTRY_CANDIDATE", "WAIT_RETEST", "WAIT_SWEEP"):
            if s in st:
                return s
        return "RANGE_ARMED" if self.range else "SEARCH_RANGE"

    def _step_dir(self, direction: str, d: dict, i: int, T: int, a1: float, tv_r) -> dict | None:
        m1, p, tick = self.m1, self.p, self.tick
        sgn = 1 if direction == "BUY" else -1
        z = d.get("zone")
        if d["state"] == "WAIT_SWEEP":
            if m1.close_time(i) <= z["known_at_ts"]:
                return None                                           # bar known before the zone existed
            eps = max(2 * tick, V(p, "trigger", "epsilon_atr_m1") * a1)
            swept = m1.l[i] < z["z_low"] - eps if sgn > 0 else m1.h[i] > z["z_high"] + eps
            reclaimed = m1.c[i] > z["z_high"] + eps if sgn > 0 else m1.c[i] < z["z_low"] - eps
            if not (swept and reclaimed):
                return None
            key = f"{self.range['range_id']}|{direction}|{m1.t[i]}"
            fams = V(p, "trigger", "allowed_confirmation_families", default=list(candles_sci.CONFIRMATION_FAMILIES))
            conf = candles_sci.confirmation(self.last_reading, "LONG" if sgn > 0 else "SHORT", fams)
            depth = ((z["z_low"] - eps) - m1.l[i]) if sgn > 0 else (m1.h[i] - (z["z_high"] + eps))
            min_depth = (V(p, "trigger", "min_sweep_depth_atr_m5", default=0.0) or 0.0) * self.range["atr_m5"]
            tv_ok = tv_r is not None and tv_r >= V(p, "trigger", "tick_volume_ratio_min")
            ev = {"direction": direction, "bar": iso_ts(m1.t[i]), "eps": eps, "confirmation": conf, "tv_ratio": tv_r, "depth": depth}
            if depth < min_depth:
                self._j(T, "WAIT_SWEEP", f"sweep za płytki ({depth:.2f} < {min_depth:.2f})", **ev)
                return None
            if not conf:
                self._j(T, "WAIT_SWEEP", f"sweep+reclaim bez potwierdzenia z rodzin {'/'.join(fams)}", **ev)
                return None
            if not tv_ok:
                self._j(T, "WAIT_SWEEP", "tick volume UNKNOWN" if tv_r is None else f"tick volume {tv_r:.2f} < {V(p, 'trigger', 'tick_volume_ratio_min')}", **ev)
                return None
            if key in self._used_sweeps:
                return None
            self._used_sweeps.add(key)
            d.update(state="WAIT_RETEST", eps=eps, sweep_bar=i, sweep_extreme=m1.l[i] if sgn > 0 else m1.h[i], sweep_conf=conf, tv_ratio=tv_r, sweep_depth=depth,
                     reason="sweep + reclaim potwierdzony – czekam na retest", sweep_key=key)
            self._j(T, "WAIT_RETEST", d["reason"], **ev)
            if not V(p, "trigger", "retest_required"):
                return self._candidate(direction, d, i, T, a1)
            return None
        if d["state"] == "WAIT_RETEST":
            eps, edge = d["eps"], (z["z_high"] if sgn > 0 else z["z_low"])
            if (sgn > 0 and m1.l[i] < d["sweep_extreme"]) or (sgn < 0 and m1.h[i] > d["sweep_extreme"]):
                d.update(state="INVALIDATED", reason="retest zanegował ekstremum sweepu")
                self._j(T, "INVALIDATED", d["reason"], direction=direction)
                return None
            overlap = m1.l[i] <= edge + eps and m1.h[i] >= edge - eps
            back = m1.c[i] > edge + eps if sgn > 0 else m1.c[i] < edge - eps
            near_max = V(p, "trigger", "retest_close_max_atr_m1")
            if overlap and back and near_max is not None and sgn * (m1.c[i] - edge) > near_max * a1:
                self._j(T, "WAIT_RETEST", f"close retestu {sgn * (m1.c[i] - edge):.2f} za daleko od krawędzi (> {near_max} ATR M1)", direction=direction)
                back = False
            if overlap and back:
                return self._candidate(direction, d, i, T, a1)
            if i - d["sweep_bar"] >= V(p, "trigger", "retest_window_m1"):
                d.update(state="EXPIRED", reason=f"brak retestu w {V(p, 'trigger', 'retest_window_m1')} M1")
                self._j(T, "EXPIRED", d["reason"], direction=direction)
        return None

    def _candidate(self, direction: str, d: dict, i: int, T: int, a1: float) -> dict | None:
        m1, p, r, tick = self.m1, self.p, self.range, self.tick
        sgn = 1 if direction == "BUY" else -1
        spread = m1.sp[i] if m1.sp[i] is not None else None
        sp = spread if spread is not None else 0.0
        lo_seq = min(m1.l[d["sweep_bar"]: i + 1])
        hi_seq = max(m1.h[d["sweep_bar"]: i + 1])
        buf = max(2 * tick, sp, 0.10 * a1)
        exec_buf = max(2 * tick, sp)
        if sgn > 0:
            sl, tp1, tp2 = lo_seq - buf, r["MID"], r["H"] - exec_buf
        else:
            sl, tp1, tp2 = hi_seq + buf + sp, r["MID"], r["L"] + exec_buf       # short closes on Ask: SL level on the bid chart + spread
        ref = m1.c[i]
        plan = {"setup_id": "SET-" + hashlib.sha256(f"{d['sweep_key']}|{m1.t[i]}".encode()).hexdigest()[:10], "direction": direction,
                "range_id": r["range_id"], "range": {k: r[k] for k in ("L", "H", "MID", "W", "atr_m5")}, "zone": d["zone"],
                "sweep_bar": iso_ts(m1.t[d["sweep_bar"]]), "sweep_extreme": d["sweep_extreme"], "retest_bar": iso_ts(m1.t[i]),
                "decision_time": iso_ts(T), "decision_ts": T, "ref_close_bid": ref, "spread_at_signal": spread, "eps": d["eps"],
                "chase_limit": max(2 * tick, V(p, "trigger", "chase_limit_atr_m5") * r["atr_m5"]), "sl": _rt(sl, tick), "tp1": _rt(tp1, tick),
                "tp2": _rt(tp2, tick), "confirmation": d["sweep_conf"], "tv_ratio": d["tv_ratio"], "atr_m1": a1,
                "conditions": [{"name": "zakres zamrożony", "ok": True}, {"name": "sekcja M1 znana przed sweepem", "ok": True},
                               {"name": "sweep + reclaim", "ok": True}, {"name": f"potwierdzenie {d['sweep_conf']['family']}", "ok": True},
                               {"name": "tick volume ≥ próg", "ok": True}, {"name": "retest krawędzi sekcji", "ok": True}]}
        mode = V(p, "entry", "mode", default="MARKET")
        edge = d["zone"]["z_high"] if sgn > 0 else d["zone"]["z_low"]
        plan["entry_mode"] = mode
        plan["limit_price"] = _rt(edge + d["eps"] + sp, tick) if (mode == "LIMIT_EDGE" and sgn > 0) else \
            _rt(edge - d["eps"], tick) if mode == "LIMIT_EDGE" else None          # BUY limit = Ask level, SELL limit = Bid level
        plan["limit_wait_m1"] = V(p, "entry", "limit_wait_m1", default=3)
        plan["features"] = setup_features(self, plan, d, i, a1)
        plan["net_features"] = scalp_net_features(self, plan, d, i, a1)      # SCALP_NET_PROFIT_MARKET_V1 (ML) - same in replay / live
        d.update(state="ENTRY_CANDIDATE", plan=plan, reason="kandydat wejścia – czekam na świeże kwotowanie i bramki")
        self._j(T, "ENTRY_CANDIDATE", d["reason"], direction=direction, setup_id=plan["setup_id"])
        return plan

    def close_direction(self, direction: str, state: str, reason: str, t: int) -> None:
        d = self.dirs.get(direction)
        if d:
            d.update(state=state, reason=reason)
            self._j(t, state, reason, direction=direction)

    def public(self) -> dict:
        r = self.range
        return {"state": self.state, "range": None if not r else {k: r.get(k) for k in ("range_id", "L", "H", "MID", "W", "atr_m5", "w_atr", "er10",
                                                                                         "touches_low", "touches_high", "tol", "inval_lo", "inval_hi")}
                | {"armed_at": iso_ts(r["armed_at"]), "ttl_end": iso_ts(r["ttl_end"])},
                "last_detect": {k: v for k, v in (getattr(self, "last_detect", None) or {}).items() if k != "bars"},
                "directions": {k: {x: v.get(x) for x in ("state", "reason", "zone", "eps", "sweep_extreme", "tv_ratio", "plan")}
                               for k, v in self.dirs.items()},
                "journal": self.journal[-30:], "reading": self.last_reading}


SETUP_FEATURES = ("sweep_depth_atr5", "range_w_atr5", "zone_w_atr5", "er10", "touches_low", "touches_high", "conf_rejection", "conf_engulfing",
                  "conf_displacement", "conf_score", "tv_log_ratio", "retest_dist_atr1", "risk_atr1", "tp1_dist_atr1", "spread_atr1",
                  "m5_pct_b_dir", "m15_sar_with", "m30_sar_with", "h1_sar_with", "m30_slope_dir", "m15_bw_pct", "minutes_since_arm",
                  "dist_round5_atr5", "hour_sin", "hour_cos")


def setup_features(mach: "ScalpMachine", plan: dict, d: dict, i: int, a1: float) -> dict:
    """Features of ONE setup known at the decision time (task B / model filter). Same function in replay, training and live.
    Direction-normalised (sgn) so BUY and SELL share one model; missing context -> 0.0 (neutral), never future data."""
    m1, r = mach.m1, mach.range
    sgn = 1 if plan["direction"] == "BUY" else -1
    a5 = r["atr_m5"]
    edge = d["zone"]["z_high"] if sgn > 0 else d["zone"]["z_low"]
    conf = d["sweep_conf"] or {}
    sp = m1.sp[i] if m1.sp[i] is not None else 0.0
    ref = m1.c[i]

    def sar_with(series):
        c = context(series, mach.p)
        if c.get("status") != "OK":
            return 0.0, None
        return (1.0 if (c["sar_trend"] == "UP") == (sgn > 0) else -1.0), c
    m15w, c15 = sar_with(mach.m15)
    m30w, c30 = sar_with(mach.m30)
    h1w, _ = sar_with(mach.h1)
    bb5 = ind.bollinger(mach.m5.c[-40:], mach.m5._atr[-40:])[-1] if len(mach.m5) >= 40 else None
    pctb = (bb5["pct_b"] - 0.5) * sgn if bb5 and bb5["pct_b"] is not None else 0.0
    hr = (plan["decision_ts"] % 86400) / 3600.0
    r5 = ref - round(ref / 5.0) * 5.0
    f = {"sweep_depth_atr5": (d.get("sweep_depth") or 0.0) / a5, "range_w_atr5": r["W"] / a5, "zone_w_atr5": (d["zone"]["z_high"] - d["zone"]["z_low"]) / a5,
         "er10": r.get("er10") or 0.0, "touches_low": float(r.get("touches_low") or 0), "touches_high": float(r.get("touches_high") or 0),
         "conf_rejection": 1.0 if conf.get("family") == "REJECTION" else 0.0, "conf_engulfing": 1.0 if conf.get("family") == "ENGULFING" else 0.0,
         "conf_displacement": 1.0 if conf.get("family") == "DISPLACEMENT" else 0.0, "conf_score": float(conf.get("score") or 0.0),
         "tv_log_ratio": math.log(d["tv_ratio"]) if d.get("tv_ratio") else 0.0, "retest_dist_atr1": sgn * (ref - edge) / a1,
         "risk_atr1": sgn * (ref - plan["sl"]) / a1, "tp1_dist_atr1": sgn * (plan["tp1"] - ref) / a1, "spread_atr1": sp / a1,
         "m5_pct_b_dir": pctb, "m15_sar_with": m15w, "m30_sar_with": m30w, "h1_sar_with": h1w,
         "m30_slope_dir": sgn * c30["slope"] if c30 else 0.0, "m15_bw_pct": (c15["bw_pct"] / 100.0) if c15 else 0.5,
         "minutes_since_arm": (plan["decision_ts"] - r["armed_at"]) / 60.0, "dist_round5_atr5": sgn * r5 / a5,
         "hour_sin": math.sin(2 * math.pi * hr / 24), "hour_cos": math.cos(2 * math.pi * hr / 24)}
    return {k: round(float(f[k]), 6) for k in SETUP_FEATURES}


NET_FEATURE_SCHEMA = "SCALP-NET-FEAT-1.0.0"
NET_FEATURES = SETUP_FEATURES + ("m1_ret1_atr", "m1_ret3_atr", "m1_ret5_atr", "m1_ret10_atr", "m1_range_atr", "m1_body_ratio", "m1_wick_with",
                                 "m1_wick_against", "m1_pctb_dir", "m1_ema20_dist_atr", "atr1_atr5", "spread_over_risk", "ctx_m15_ok", "ctx_m30_ok",
                                 "ctx_h1_ok", "spread_known", "tv_known")


def scalp_net_features(mach: "ScalpMachine", plan: dict, d: dict, i: int, a1: float) -> dict:
    """SCALP-NET-FEAT-1.0.0 for SCALP_NET_PROFIT_MARKET_V1: the setup features WITHOUT the 0.0-for-missing convention (missing =
    NaN, with explicit *_ok / *_known flags) + an M1 block (direction-normalised, ATR(M1) units) + cost relative to the risk.
    Uses only closed bars <= the signal bar i. The legacy setup_features() is unchanged (old artefacts keep their meaning)."""
    nan = float("nan")
    m1 = mach.m1
    sgn = 1 if plan["direction"] == "BUY" else -1
    base = dict(plan.get("features") or setup_features(mach, plan, d, i, a1))
    oks = {}
    for tf, key, s_ in (("m15", "m15_sar_with", mach.m15), ("m30", "m30_sar_with", mach.m30), ("h1", "h1_sar_with", mach.h1)):
        ok = context(s_, mach.p).get("status") == "OK"
        oks[tf] = ok
        if not ok:
            base[key] = nan
    if not oks["m30"]:
        base["m30_slope_dir"] = nan
    if not oks["m15"]:
        base["m15_bw_pct"] = nan
    sp_known = m1.sp[i] is not None
    tv_known = bool(d.get("tv_ratio"))
    if not sp_known:
        base["spread_atr1"] = nan
    if not tv_known:
        base["tv_log_ratio"] = nan
    if len(mach.m5) < 40:
        base["m5_pct_b_dir"] = nan
    c, h, lo, o = m1.c, m1.h, m1.l, m1.o

    def ret(k):
        return sgn * (c[i] - c[i - k]) / a1 if i - k >= 0 else nan
    rng = h[i] - lo[i]
    up_w, dn_w = h[i] - max(o[i], c[i]), min(o[i], c[i]) - lo[i]
    win = c[max(0, i - 19):i + 1]
    m = sum(win) / len(win)
    sd = (sum((x - m) ** 2 for x in win) / len(win)) ** 0.5
    pctb = ((c[i] - (m - 2 * sd)) / (4 * sd) - 0.5) * sgn if len(win) == 20 and sd > 0 else nan
    k = 2 / 21
    ema = c[max(0, i - 59)]
    for x in c[max(0, i - 58):i + 1]:
        ema = x * k + ema * (1 - k)
    risk = sgn * (c[i] - plan["sl"])
    a5 = (mach.range or {}).get("atr_m5")
    base.update({"m1_ret1_atr": ret(1), "m1_ret3_atr": ret(3), "m1_ret5_atr": ret(5), "m1_ret10_atr": ret(10), "m1_range_atr": rng / a1,
                 "m1_body_ratio": abs(c[i] - o[i]) / rng if rng > 0 else nan,
                 "m1_wick_with": (dn_w if sgn > 0 else up_w) / a1, "m1_wick_against": (up_w if sgn > 0 else dn_w) / a1, "m1_pctb_dir": pctb,
                 "m1_ema20_dist_atr": sgn * (c[i] - ema) / a1 if i >= 20 else nan, "atr1_atr5": a1 / a5 if a5 else nan,
                 "spread_over_risk": (m1.sp[i] / risk) if (sp_known and risk > 0) else nan,
                 "ctx_m15_ok": 1.0 if oks["m15"] else 0.0, "ctx_m30_ok": 1.0 if oks["m30"] else 0.0, "ctx_h1_ok": 1.0 if oks["h1"] else 0.0,
                 "spread_known": 1.0 if sp_known else 0.0, "tv_known": 1.0 if tv_known else 0.0})
    return {kk: (round(float(base[kk]), 6) if math.isfinite(float(base[kk])) else nan) for kk in NET_FEATURES}


def _rt(x: float, tick: float) -> float:
    return round(round(x / tick) * tick, 10)


def economics(plan: dict, fill: float, spread: float, cost_extra: float, prof: dict) -> dict:
    """Geometry filter in price units per 1 unit of volume. fill = execution price (Ask for BUY, Bid for SELL);
    cost_extra = commission round trip + slippage expressed in price. Spread is already inside fill/exit sides."""
    sgn = 1 if plan["direction"] == "BUY" else -1
    tp1, tp2, sl = plan["tp1"], plan["tp2"], plan["sl"]
    # TP/SL are ORDER prices: BUY exits are compared with Bid, SELL exits with Ask, so the exit price is the level itself
    ex1, ex2, sl_exit = tp1, tp2, sl
    gross1 = sgn * (ex1 - fill)
    risk = sgn * (fill - sl_exit) + cost_extra
    f1 = V(prof, "exits", "tp1_fraction")
    net_w = f1 * (gross1 - cost_extra) + (1 - f1) * (sgn * (ex2 - fill) - cost_extra)
    cost_total = spread + cost_extra
    gross_tp1_mid = gross1 + spread                                   # gross move to TP1 before costs
    ok_side = gross1 > 0 and sgn * (ex2 - fill) > 0 and risk > 0
    out = {"gross_tp1": gross_tp1_mid, "cost_round_trip": cost_total, "risk_per_unit": risk, "weighted_net_rr": (net_w / risk) if risk > 0 else None,
           "cost_to_tp1": (cost_total / gross_tp1_mid) if gross_tp1_mid > 0 else None, "targets_on_right_side": ok_side}
    out["ok"] = bool(ok_side and out["cost_to_tp1"] is not None and out["cost_to_tp1"] <= V(prof, "economics", "max_cost_to_tp1_gross")
                     and out["weighted_net_rr"] is not None and out["weighted_net_rr"] >= V(prof, "economics", "min_weighted_net_rr"))
    out["reason"] = ("OK" if out["ok"] else "cele po złej stronie ceny wykonania" if not ok_side else
                     f"koszt/TP1 {out['cost_to_tp1']:.2f} > {V(prof, 'economics', 'max_cost_to_tp1_gross')}" if (out["cost_to_tp1"] or 9) > V(prof, "economics", "max_cost_to_tp1_gross")
                     else f"ważony RR netto {out['weighted_net_rr']:.2f} < {V(prof, 'economics', 'min_weighted_net_rr')}")
    return out


def size(risk_per_unit_price: float, contract_size: float, equity: float, prof: dict, vmin: float, vstep: float, vmax: float) -> dict:
    """Lots from the full cash risk per lot (price risk incl. costs x contract size); floored to the step, never rounded up.
    Split TP1/TP2 only if both parts are legal lots; otherwise the frozen single-TP1 variant."""
    budget = equity * V(prof, "risk", "cycle_risk_pct_equity") / 100.0
    per_lot = risk_per_unit_price * contract_size
    raw = budget / per_lot if per_lot > 0 else 0.0
    lots = math.floor(raw / vstep + 1e-9) * vstep
    lots = min(lots, vmax)
    if lots < vmin:
        return {"ok": False, "lots": 0.0, "raw": raw, "budget": budget, "reason": "minimalny lot przekracza budżet ryzyka – pominięcie"}
    half = math.floor(lots * V(prof, "exits", "tp1_fraction") / vstep + 1e-9) * vstep
    split = half >= vmin and (lots - half) >= vmin - 1e-12
    return {"ok": True, "lots": round(lots, 8), "tp1_lots": round(half if split else lots, 8), "tp2_lots": round(lots - half, 8) if split else 0.0,
            "split": split, "raw": raw, "budget": budget, "risk_cash": round(lots * per_lot, 2),
            "exit_variant": "TP1_TP2_SPLIT" if split else "SINGLE_TP1"}
