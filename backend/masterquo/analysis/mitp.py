"""MITP - multi-indicator trend potwierdzany dwustopniowo (PMW-UPD-07 R06), profile MQ_MITP_32_V1.

OWN complete profile (not a claim of parity with the MT4 original R38 - that one is SOURCE_COMPAT_R38 = UNVERIFIED_SOURCE_PARITY until
its source, parameters and reference vectors exist). 16 base series, each with two nodes:
  BIAS  = sign(x - neutral)    (for moving averages x = close - MA)      SLOPE = sign(x_t - x_{t-1})  (for MAs: change of the MA)
Bases: EMA9, EMA21, ALMA9, HMA16, KAMA10, AO, MACD_LINE, MACD_HIST, PPO_LINE, PPO_HIST, RSI_MA, CCI_MA, FISHER10, TRUE_STRENGTH,
RCI26, TREND_STRENGTH14 (definitions in the code below, shared EMA/SMA/RSI/KAMA operators of strategies.indicators).
Missing history -> UNKNOWN (never NEUTRAL, never a vote). sign has a scale-dependent tolerance (TOL_REL x price scale).

Two levels of confirmation per node (and for the general trigger):
  1. raw condition turns bullish -> pending BUY at this bar's HIGH (bearish -> pending SELL at the LOW);
  2. a LATER bar's close beyond the trigger, while the raw condition still agrees, confirms the node state.
  An opposite raw condition cancels the unconfirmed pending; NEUTRAL keeps the confirmed state and the pending (it can still be
  confirmed later, only with an agreeing raw condition); UNKNOWN suspends evaluation and sets a quality flag.
General trigger (STRICT_ALL): all enabled, ready nodes BUY -> general buy trigger = high of that bar, confirmed by a LATER close
above it with unanimity still present (SELL mirrored). GROUP_BALANCED: groups trend / momentum / oscillators, base = mean of its
two node votes in [-1,1], group = mean of its bases, UP/DOWN beyond +-0.6, consensus = >= 2 ready groups of one side and no ready
opposite group. 32 nodes derived from one price are NOT 32 independent pieces of evidence.
"""
from __future__ import annotations

import math

from ..strategies import indicators as ind

VERSION = "MQ_MITP_32_V1"
TOL_REL = 1e-9
BASES = ("EMA9", "EMA21", "ALMA9", "HMA16", "KAMA10", "AO", "MACD_LINE", "MACD_HIST", "PPO_LINE", "PPO_HIST", "RSI_MA", "CCI_MA",
         "FISHER10", "TRUE_STRENGTH", "RCI26", "TREND_STRENGTH14")
MA_BASES = {"EMA9", "EMA21", "ALMA9", "HMA16", "KAMA10"}
NEUTRAL = {"RSI_MA": 50.0}
GROUPS = {"trend": ("EMA9", "EMA21", "ALMA9", "HMA16", "KAMA10", "TREND_STRENGTH14"),
          "momentum": ("AO", "MACD_LINE", "MACD_HIST", "PPO_LINE", "PPO_HIST", "TRUE_STRENGTH"),
          "oscillators": ("RSI_MA", "CCI_MA", "FISHER10", "RCI26")}


def _wma(x: list, n: int) -> list:
    out = [None] * len(x)
    w = list(range(1, n + 1))
    for i in range(n - 1, len(x)):
        seg = x[i - n + 1:i + 1]
        if any(v is None for v in seg):
            continue
        out[i] = sum(a * b for a, b in zip(seg, w)) / sum(w)
    return out


def _ema_tail(x: list, n: int) -> list:
    """EMA of a series with leading None: starts from the first full values (no inserted zeros)."""
    first = next((i for i, v in enumerate(x) if v is not None), None)
    out = [None] * len(x)
    if first is None:
        return out
    e = ind.ema([v for v in x[first:]], n)
    out[first:] = e
    return out


def _sma_tail(x: list, n: int) -> list:
    first = next((i for i, v in enumerate(x) if v is not None), None)
    out = [None] * len(x)
    if first is None:
        return out
    out[first:] = ind.sma(x[first:], n)
    return out


def _rank(v: list) -> list:
    order = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1                     # average ties
        i = j + 1
    return r


def _corr(a: list, b: list) -> float:
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    sa = math.sqrt(sum((x - ma) ** 2 for x in a))
    sb = math.sqrt(sum((y - mb) ** 2 for y in b))
    if sa == 0 or sb == 0:
        return 0.0                                            # flat window -> 0 (documented)
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sa * sb)


def series(h: list[float], lo: list[float], c: list[float]) -> dict[str, list]:
    n = len(c)
    hl2 = [(a + b) / 2 for a, b in zip(h, lo)]
    s = {}
    for name, length in (("EMA9", 9), ("EMA21", 21)):
        s[name] = ind.ema(c, length)
    w = [math.exp(-((i - 0.85 * 8) ** 2) / (2 * (9 / 6) ** 2)) for i in range(9)]
    s["ALMA9"] = [None] * n
    for i in range(8, n):
        s["ALMA9"][i] = sum(c[i - 8 + k] * w[k] for k in range(9)) / sum(w)
    w8, w16 = _wma(c, 8), _wma(c, 16)
    s["HMA16"] = _wma([None if a is None or b is None else 2 * a - b for a, b in zip(w8, w16)], 4)
    s["KAMA10"] = [None] * n
    if n > 10:
        k = sum(c[:10]) / 10
        s["KAMA10"][9] = k
        for i in range(10, n):
            noise = sum(abs(c[j] - c[j - 1]) for j in range(i - 9, i + 1))
            er = abs(c[i] - c[i - 10]) / noise if noise else 0.0
            sc = (er * (2 / 3 - 2 / 31) + 2 / 31) ** 2
            k = k + sc * (c[i] - k)
            s["KAMA10"][i] = k
    s5, s34 = ind.sma(hl2, 5), ind.sma(hl2, 34)
    s["AO"] = [None if a is None or b is None else a - b for a, b in zip(s5, s34)]
    e12, e26 = ind.ema(c, 12), ind.ema(c, 26)
    macd = [None if a is None or b is None else a - b for a, b in zip(e12, e26)]
    s["MACD_LINE"] = macd
    sig = _ema_tail(macd, 9)
    s["MACD_HIST"] = [None if a is None or b is None else a - b for a, b in zip(macd, sig)]
    ppo = [None if a is None or b is None or b == 0 else 100 * (a - b) / b for a, b in zip(e12, e26)]
    s["PPO_LINE"] = ppo
    ps = _ema_tail(ppo, 9)
    s["PPO_HIST"] = [None if a is None or b is None else a - b for a, b in zip(ppo, ps)]
    r = ind.rsi(c, 14)
    s["RSI_MA"] = _sma_tail([50.0 if (v is not None and i >= 14 and max(c[i - 14:i + 1]) == min(c[i - 14:i + 1])) else v
                             for i, v in enumerate(r)], 5)
    tp = [(a + b + d) / 3 for a, b, d in zip(h, lo, c)]
    cci = [None] * n
    for i in range(19, n):
        win = tp[i - 19:i + 1]
        m = sum(win) / 20
        mad = sum(abs(x - m) for x in win) / 20
        cci[i] = 0.0 if mad == 0 else (tp[i] - m) / (0.015 * mad)
    s["CCI_MA"] = _sma_tail(cci, 5)
    fis, z, f = [None] * n, 0.0, 0.0
    for i in range(9, n):
        win = hl2[i - 9:i + 1]
        mx, mn = max(win), min(win)
        pos = 0.5 if mx == mn else (hl2[i] - mn) / (mx - mn)
        z = max(-0.999, min(0.999, 0.66 * (pos - 0.5) + 0.67 * z))
        f = 0.5 * math.log((1 + z) / (1 - z)) + 0.5 * f
        fis[i] = f
    s["FISHER10"] = fis
    d = [None] + [c[i] - c[i - 1] for i in range(1, n)]
    ad = [None] + [abs(v) for v in d[1:]]
    num = _ema_tail(_ema_tail(d, 25), 13)
    den = _ema_tail(_ema_tail(ad, 25), 13)
    s["TRUE_STRENGTH"] = [None if a is None or b is None else (0.0 if b == 0 else 100 * a / b) for a, b in zip(num, den)]
    s["RCI26"] = [None] * n
    for i in range(25, n):
        s["RCI26"][i] = 100 * _corr(list(range(1, 27)), _rank(c[i - 25:i + 1]))
    s["TREND_STRENGTH14"] = [None] * n
    for i in range(13, n):
        s["TREND_STRENGTH14"][i] = _corr(list(range(14)), c[i - 13:i + 1])
    return s


def _sign(x: float | None, scale: float) -> int | None:
    if x is None or not math.isfinite(x):
        return None
    tol = TOL_REL * max(1.0, abs(scale))
    return 0 if abs(x) <= tol else (1 if x > 0 else -1)


def node_conditions(s: dict, c: list[float]) -> dict[str, list]:
    """32 raw node conditions per bar: +1 bullish, -1 bearish, 0 neutral, None unknown."""
    out = {}
    for b in BASES:
        x = s[b]
        bias, slope = [None] * len(c), [None] * len(c)
        for i in range(len(c)):
            if x[i] is None:
                continue
            if b in MA_BASES:
                bias[i] = _sign(c[i] - x[i], c[i])
                slope[i] = _sign(x[i] - x[i - 1], c[i]) if i and x[i - 1] is not None else None
            else:
                bias[i] = _sign(x[i] - NEUTRAL.get(b, 0.0), max(1.0, abs(x[i])))
                slope[i] = _sign(x[i] - x[i - 1], max(1.0, abs(x[i]))) if i and x[i - 1] is not None else None
        out[f"{b}.BIAS"], out[f"{b}.SLOPE"] = bias, slope
    return out


class TwoStage:
    """Pending trigger on the high/low of the bar where the condition turns; confirmation by a LATER close beyond it."""

    def __init__(self):
        self.state, self.pending, self.trigger, self.trigger_bar, self.confirmed_at, self.flag = None, None, None, None, None, None

    def step(self, i: int, raw: int | None, h: float, lo: float, c: float, prev_raw: int | None):
        self.flag = "UNKNOWN_SUSPENDED" if raw is None else None
        if raw is None:
            return
        if self.pending is not None and i > self.trigger_bar and raw == self.pending:
            if (raw > 0 and c > self.trigger) or (raw < 0 and c < self.trigger):
                self.state, self.confirmed_at, self.pending, self.trigger = ("BUY" if raw > 0 else "SELL"), i, None, None
                return
        if self.pending is not None and raw == -self.pending:
            self.pending, self.trigger = None, None                       # opposite condition cancels the unconfirmed trigger
        if raw != 0 and raw != prev_raw and (self.state != ("BUY" if raw > 0 else "SELL")):
            self.pending, self.trigger, self.trigger_bar = raw, (h if raw > 0 else lo), i


def _dump(ts: TwoStage) -> dict:
    return dict(ts.__dict__)


def _load(d: dict) -> TwoStage:
    ts = TwoStage()
    ts.__dict__.update(d)
    return ts


def run(h: list[float], lo: list[float], c: list[float], enabled: list[str] | None = None, profile: str = "STRICT_ALL",
        checkpoint: dict | None = None) -> dict:
    """Batch evaluation; with `checkpoint` (from an earlier result over a PREFIX of the same bars) only the new bars are stepped -
    the result is identical to the full batch (test T22). Returns per-node state + the general state + a new checkpoint."""
    if profile not in ("STRICT_ALL", "GROUP_BALANCED"):
        raise ValueError("PROFILE_INVALID")
    s = series(h, lo, c)
    raw = node_conditions(s, c)
    nodes = list(raw) if enabled is None else [n for n in raw if n in enabled]
    if not nodes:
        return {"version": VERSION, "profile": profile, "status": "NO_ENABLED_SIGNALS", "nodes": {}, "general": None}
    st = {n: TwoStage() for n in nodes}
    gen = TwoStage()
    prev_g, start = None, 0
    if checkpoint and checkpoint.get("version") == VERSION and checkpoint.get("profile") == profile and checkpoint.get("nodes_list") == nodes \
            and checkpoint.get("last_index", 10 ** 9) < len(c):
        st = {n: _load(checkpoint["nodes"][n]) for n in nodes}
        gen, prev_g, start = _load(checkpoint["general"]), checkpoint["prev_g"], checkpoint["last_index"] + 1
    for i in range(start, len(c)):
        for n in nodes:
            st[n].step(i, raw[n][i], h[i], lo[i], c[i], raw[n][i - 1] if i else None)
        g = _general(st, nodes, profile)
        gen.step(i, g["vote"], h[i], lo[i], c[i], prev_g)
        prev_g = g["vote"]
    i = len(c) - 1
    cur = {n: raw[n][i] for n in nodes}
    g = _general(st, nodes, profile)
    unknown = sum(1 for v in cur.values() if v is None)
    return {"version": VERSION, "profile": profile, "source_parity": "SOURCE_COMPAT_R38: UNVERIFIED_SOURCE_PARITY",
            "status": "WARMING_UP" if unknown == len(nodes) else "OK" if unknown == 0 else "PARTIAL_UNKNOWN",
            "nodes": {n: {"raw": cur[n], "state": st[n].state, "pending": st[n].pending, "trigger": st[n].trigger, "confirmed_at": st[n].confirmed_at,
                          "flag": st[n].flag} for n in nodes},
            "votes": {"buy": sum(1 for n in nodes if st[n].state == "BUY"), "sell": sum(1 for n in nodes if st[n].state == "SELL"),
                      "unknown": unknown, "enabled": len(nodes)},
            "groups": g.get("groups"), "general": {"held_state": gen.state, "current_vote": g["vote"], "pending": gen.pending, "trigger": gen.trigger,
                                                   "confirmed_at": gen.confirmed_at,
                                                   "note": "utrzymany stan ≠ aktualna jednomyślność; 32 węzły z jednej ceny to nie 32 niezależne dowody"},
            "checkpoint": {"version": VERSION, "profile": profile, "nodes_list": nodes, "last_index": i, "prev_g": prev_g,
                           "nodes": {n: _dump(st[n]) for n in nodes}, "general": _dump(gen)}}


def _general(st: dict, nodes: list[str], profile: str) -> dict:
    if profile == "STRICT_ALL":
        states = [st[n].state for n in nodes]
        if any(x is None for x in states):
            return {"vote": None}
        return {"vote": 1 if all(x == "BUY" for x in states) else -1 if all(x == "SELL" for x in states) else 0}
    groups = {}
    for gname, bases in GROUPS.items():
        bv = []
        ready = True
        for b in bases:
            vs = [st[f"{b}.{k}"].state for k in ("BIAS", "SLOPE") if f"{b}.{k}" in st]
            if not vs:
                continue
            if any(v is None for v in vs):
                ready = False
                continue
            bv.append(max(-1.0, min(1.0, sum(1 if v == "BUY" else -1 for v in vs) / len(vs))))
        m = sum(bv) / len(bv) if bv else None
        groups[gname] = {"ready": ready and bool(bv), "score": m, "side": None if m is None or not ready else ("UP" if m > 0.6 else "DOWN" if m < -0.6 else "MIXED")}
    up = sum(1 for g in groups.values() if g["ready"] and g["side"] == "UP")
    dn = sum(1 for g in groups.values() if g["ready"] and g["side"] == "DOWN")
    vote = 1 if up >= 2 and dn == 0 else -1 if dn >= 2 and up == 0 else 0
    return {"vote": vote, "groups": groups}


def trace(h: list[float], lo: list[float], c: list[float], profile: str = "GROUP_BALANCED") -> list[dict]:
    """Per-bar causal states (feature use): value at bar i depends only on bars <= i (same automata as `run`)."""
    s = series(h, lo, c)
    raw = node_conditions(s, c)
    nodes = list(raw)
    st = {n: TwoStage() for n in nodes}
    gen, prev_g, out = TwoStage(), None, []
    for i in range(len(c)):
        for n in nodes:
            st[n].step(i, raw[n][i], h[i], lo[i], c[i], raw[n][i - 1] if i else None)
        g = _general(st, nodes, profile)
        gen.step(i, g["vote"], h[i], lo[i], c[i], prev_g)
        prev_g = g["vote"]
        out.append({"buy": sum(1 for n in nodes if st[n].state == "BUY"), "sell": sum(1 for n in nodes if st[n].state == "SELL"),
                    "unknown": sum(1 for n in nodes if raw[n][i] is None), "vote": g["vote"],
                    "held": {"BUY": 1, "SELL": -1}.get(gen.state, 0)})
    return out
