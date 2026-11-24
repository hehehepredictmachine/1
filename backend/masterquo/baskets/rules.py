"""Rule families of the 60 directional strategies (SMC + SCALP of the three profiles). One family = one detector sequence; the catalog
binds each canonical strategy id to a family + its parameters + the market's requirements (spec 6.1/6.2/7.1/7.2/8.1/8.2).

Interface: fn(F, side, p, x) -> Setup dict | None, raising Unavailable(reason) when a REQUIRED input is missing (real volume, OI, L2,
benchmark, calendar ...): the strategy shows the missing capability, never a fake confirmation.
  F     detectors.Feat of the signal TF (bar i = last closed bar)
  side  +1 LONG/CALL, -1 SHORT/PUT (spec: the LONG description holds symmetrically)
  p     strategy parameters (catalog)
  x     context: {"htf": Feat | None, "htf2": Feat | None, "bench": Feat | None, "oi": [(t, oi)], "flow": [...], "session": {...},
                  "now": t}
Setup: {entry, invalidation, sl, target?, event: {type, level, t}, conditions: {...}} - entry is the close of the confirming bar
(the plan takes the live price at execution; no historical fill after the close).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None


class Unavailable(Exception):
    """A required input / capability is missing for THIS strategy variant (state WAITING_FOR_DATA / UNSUPPORTED_*)."""


def _gt(a, b, s):
    return a > b if s > 0 else a < b


def _ext(F, k, s):
    """Protective extreme of bar k (low for LONG)."""
    return float(F.l[k] if s > 0 else F.h[k])


def _first_touch(F, lo, hi, a, b):
    """No bar in (a, b) touched [lo, hi]."""
    return not any(F.touched(k, lo, hi) for k in range(a + 1, b))


def _htf_ok(x, s, key="htf"):
    h = x.get(key)
    if h is None:
        raise Unavailable(f"brak zamkniętego kontekstu {key.upper()}")
    tr, how = h.trend()
    return tr == s, how


def _setup(F, s, sl, inval, ev_type, level, t_ev, cond, target=None, **kw):
    i = F.i
    entry = float(F.c[i])
    if sl is None or not _gt(entry, sl, s):
        return None
    out = {"entry": entry, "sl": float(sl), "invalidation": float(inval), "event": {"type": ev_type, "level": None if level is None else float(level),
           "t": float(F.t[t_ev])}, "conditions": cond}
    if target is not None:
        out["target"] = float(target)
    out.update(kw)
    return out


# ============================================================================ SMC families
def sweep_choch_retest(F, s, p, x):
    i, b = F.i, F.b()
    if b is None:
        return None
    sw = F.swept_swing(i - 1, s, int(p.get("sweep_within", 12)))
    if not sw:
        return None
    j, lvl = sw
    ch = None
    for k in range(j, min(i, j + 4)):
        sb = F.structure_break(k, s)
        if sb and sb["kind"] in tuple(p.get("break_kinds", ("CHOCH",))):
            ch = sb | {"at": k}
            break
    if not ch or ch["at"] >= i:
        return None
    L = ch["level"]
    ext = _ext(F, j, s)
    if (F.l[i] < ext if s > 0 else F.h[i] > ext):
        return None                                                            # sweep extreme violated again -> cancelled
    if not _first_touch(F, L - b, L + b, ch["at"], i) or not F.confirmed_retest(i, L - b, L + b, s, ext):
        return None
    return _setup(F, s, ext - s * b, ext, "SWEEP_CHOCH", lvl, j, {"sweep_bar": j, "sweep_level": lvl, "choch_bar": ch["at"], "broken_level": L,
                                                                  "first_retest": True})


def bos_ob_retest(F, s, p, x):
    i, b = F.i, F.b()
    if b is None:
        return None
    if p.get("htf_trend", True):
        ok, how = _htf_ok(x, s)
        if not ok:
            return None
    for k in range(i - 1, max(1, i - 7), -1):
        sb = F.structure_break(k, s)
        if not sb or not F.displacement(k, s):
            continue
        if p.get("rvol_min"):
            rv = F.rvol(k)
            if rv is None:
                raise Unavailable("brak rzeczywistego wolumenu – wariant z RVOL niedostępny")
            if rv < float(p["rvol_min"]):
                return None
        ob = F.order_block(k, s)
        if not ob:
            return None
        distal = ob["lo"] if s > 0 else ob["hi"]
        if not _first_touch(F, ob["lo"], ob["hi"], k, i):
            return None
        if any(_gt(distal, F.c[m], s) for m in range(k + 1, i + 1)):
            return None                                                        # close beyond the distal edge -> invalid
        if F.touched(i, ob["lo"], ob["hi"]) and _gt(F.c[i], ob["mid"], s) and (F.bull(i) if s > 0 else F.bear(i)):
            return _setup(F, s, distal - s * b, distal, "BOS_OB", ob["mid"], ob["k"], {"bos_bar": k, "ob": ob, "rvol": F.rvol(k)})
        return None
    return None


def fvg_continuation(F, s, p, x):
    i, b = F.i, F.b()
    if b is None:
        return None
    if p.get("htf_trend", True):
        ok, _ = _htf_ok(x, s)
        if not ok:
            return None
    for z in reversed(F.fvgs(i - 1, s, int(p.get("max_wait", 6)) + 1, need_disp=True)):
        if not _first_touch(F, z["lo"], z["hi"], z["t"], i):
            continue
        edge = z["hi"] if s > 0 else z["lo"]
        far = z["lo"] if s > 0 else z["hi"]
        if F.touched(i, z["lo"], z["hi"]) and _gt(F.c[i], edge, s):
            sl = (min(far, F.l[i]) - b) if s > 0 else (max(far, F.h[i]) + b)
            return _setup(F, s, sl, far, "FVG", (z["lo"] + z["hi"]) / 2, z["t"], {"fvg": z})
    return None


def ifvg_reversal(F, s, p, x):
    i, b = F.i, F.b()
    if b is None:
        return None
    for z in reversed(F.fvgs(i - 2, -s, 40)):
        far = z["hi"] if s > 0 else z["lo"]                                    # the farther edge of the OPPOSITE FVG
        k = next((m for m in range(z["t"] + 1, i) if _gt(F.c[m], far, s)), None)
        if k is None:
            continue
        ch = F.last_break(k, s, 6, kinds=("CHOCH",))
        if not ch:
            continue
        near = z["lo"] if s > 0 else z["hi"]
        if any(_gt(near, F.c[m], s) for m in range(k + 1, i + 1)):
            return None
        if _first_touch(F, z["lo"], z["hi"], k, i) and F.touched(i, z["lo"], z["hi"]) and _gt(F.c[i], far, s):
            return _setup(F, s, near - s * b, near, "IFVG", far, z["t"], {"fvg": z, "broken_at": k, "choch_bar": ch["at"]})
        return None
    return None


def breaker_retest(F, s, p, x):
    i, b = F.i, F.b()
    if b is None:
        return None
    for k0 in range(i - 3, max(6, i - 60), -1):
        if not F.displacement(k0, -s):
            continue
        if p.get("need_failed_break") and not F.structure_break(k0, -s):
            continue
        ob = F.order_block(k0, -s)                                             # opposite OB (bearish for LONG)
        if not ob:
            continue
        far = ob["hi"] if s > 0 else ob["lo"]
        k1 = next((m for m in range(k0 + 1, i) if _gt(F.c[m], far, s) and F.displacement(m, s) and F.structure_break(m, s)), None)
        if k1 is None:
            continue
        near = ob["lo"] if s > 0 else ob["hi"]
        if not _first_touch(F, ob["lo"], ob["hi"], k1, i):
            return None
        if F.confirmed_retest(i, ob["lo"], ob["hi"], s, near) and _gt(F.c[i], far, s):
            return _setup(F, s, near - s * b, near, "BREAKER", far, ob["k"], {"opposite_ob": ob, "break_bar": k1, "failed_break_event": k0})
        return None
    return None


def second_mitigation(F, s, p, x):
    i, b = F.i, F.b()
    if b is None:
        return None
    for k0 in range(i - 4, max(2, i - 60), -1):
        if not (F.structure_break(k0, s) and F.displacement(k0, s)):
            continue
        ob = F.order_block(k0, s)
        if not ob:
            continue
        distal = ob["lo"] if s > 0 else ob["hi"]
        touches = [m for m in range(k0 + 1, i) if F.touched(m, ob["lo"], ob["hi"])]
        if not touches or any(_gt(distal, F.c[m], s) for m in range(k0 + 1, i + 1)):
            return None
        r1 = touches[0]
        k1 = next((m for m in range(r1 + 1, i) if F.structure_break(m, s) and F.displacement(m, s)), None)
        if k1 is None or any(F.touched(m, ob["lo"], ob["hi"]) for m in range(k1 + 1, i)) or len([m for m in touches if m < k1]) > 1:
            return None
        if p.get("oi_delta"):
            d = oi_delta(x, _oi_ref_t(F, i, x, F.t[i]), 300)               # 1.46 (I0765): at the close of the signal candle
            if d is None:
                raise Unavailable("brak historii OI – wariant z udziałem OI niedostępny")
            if d <= 0:
                return None
        if F.confirmed_retest(i, ob["lo"], ob["hi"], s, distal):
            return _setup(F, s, distal - s * b, distal, "MITIGATION_2", ob["mid"], ob["k"], {"ob": ob, "first_retest": r1, "fresh_bos": k1,
                                                                                            "retest_no": 2})
        return None
    return None


def eq_raid(F, s, p, x):
    i, b = F.i, F.b()
    if b is None:
        return None
    for j in (i - 1, i - 2):
        if j < 3:
            continue
        lvl = F.equal_levels(j - 1, s)
        if lvl is None or not F.sweep(j, lvl, s):
            continue
        if _gt(F.c[i], (F.h[j] + b) if s > 0 else (F.l[j] - b), s) and all(not _gt(F.c[m], (F.h[j] + b) if s > 0 else (F.l[j] - b), s)
                                                                          for m in range(j + 1, i)):
            ext = _ext(F, j, s)
            return _setup(F, s, ext - s * b, ext, "EQ_RAID", lvl, j, {"equal_level": lvl, "sweep_bar": j, "bars_to_trigger": i - j})
    return None


def ote_continuation(F, s, p, x):
    i, b = F.i, F.b()
    if b is None:
        return None
    if p.get("htf_trend", True):
        ok, _ = _htf_ok(x, s)
        if not ok:
            return None
    lo_f, hi_f = p.get("ote", (0.62, 0.79))
    for k in range(i - 2, max(3, i - 30), -1):
        if not (F.structure_break(k, s) and F.displacement(k, s)):
            continue
        st = F.swings(k, "L" if s > 0 else "H", 1)
        if not st:
            return None
        start = st[-1].price
        ext = float(F.h[st[-1].k:k + 1].max() if s > 0 else F.l[st[-1].k:k + 1].min())
        rng = abs(ext - start)
        if rng <= 0:
            return None
        if any(_gt(F.h[m] if s > 0 else F.l[m], ext, s) for m in range(k + 1, i)):
            return None                                                        # range changed (new extreme) -> invalid
        zone_a, zone_b = ext - s * hi_f * rng, ext - s * lo_f * rng
        zlo, zhi = min(zone_a, zone_b), max(zone_a, zone_b)
        mid = (ext + start) / 2
        hit = next((m for m in range(k + 1, i + 1) if F.touched(m, zlo, zhi) and _gt(mid, F.c[m] if m < i else F.o[m], s)), None)
        if hit is None or any(_gt(start, F.l[m] if s > 0 else F.h[m], s) for m in range(k + 1, i + 1)):
            return None
        if F.displacement(i, s):
            return _setup(F, s, start - s * b, start, "OTE", (zlo + zhi) / 2, k, {"impulse_start": start, "impulse_end": ext, "ote_zone": [zlo, zhi],
                                                                               "discount": True}, target=ext)
        return None
    return None


def _session_anchor(t: float, tz: str, hhmm: str) -> float:
    if ZoneInfo is None:
        raise Unavailable("brak bazy stref czasowych (zoneinfo)")
    z = ZoneInfo(tz)
    d = datetime.fromtimestamp(t, z)
    hh, mm = (int(v) for v in hhmm.split(":"))
    a = d.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if a.timestamp() > t:
        a -= timedelta(days=1)
    return a.timestamp()


def range_sweep(F, s, p, x):
    """FX_SMC_09 session range (60 min before the London / NY anchor, sweep within 120 min after), CP_SMC_09 previous UTC day,
    OTC_SMC_09 rolling 20-bar range frozen at the sweep."""
    i, b = F.i, F.b()
    if b is None:
        return None
    mode = p.get("range", "SESSION")
    if mode == "SESSION":
        best = None
        for tz, hhmm in p.get("anchors", (("Europe/London", "08:00"), ("America/New_York", "08:00"))):
            a = _session_anchor(F.t[i], tz, hhmm)
            if F.t[i] - a <= 120 * 60:
                best = a if best is None or a > best else best
        if best is None:
            return None
        pre = [k for k in range(F.n) if best - 3600 <= F.t[k] < best]
        if len(pre) < 3:
            raise Unavailable("brak pełnych świec zakresu przed sesją")
        lo, hi = float(F.l[pre].min()), float(F.h[pre].max())
        after = [k for k in range(F.n) if F.t[k] >= best]
        rid = best
    elif mode == "PREV_UTC_DAY":
        d0 = datetime.fromtimestamp(F.t[i], timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        pre = [k for k in range(F.n) if d0 - 86400 <= F.t[k] < d0]
        if len(pre) < 0.9 * 86400 / max(60.0, F.t[1] - F.t[0]):
            raise Unavailable("niepełna poprzednia doba UTC")
        lo, hi = float(F.l[pre].min()), float(F.h[pre].max())
        after = [k for k in range(F.n) if F.t[k] >= d0]
        rid = d0
    else:
        after, lo, hi, rid = None, None, None, None
    level = lo if s > 0 else hi
    if mode == "ROLLING20":
        for j in range(i - 1, max(21, i - 8), -1):
            lv = F.LL(20, j) if s > 0 else F.HH(20, j)
            if lv is not None and F.sweep(j, lv, s):
                level, after, rid = lv, list(range(j, F.n)), F.t[j]
                break
        else:
            return None
    j = next((k for k in after if k < i and F.sweep(k, level, s)), None)
    if j is None:
        return None
    ms = F.last_break(i - 1, s, i - j, start=j)
    if not ms or not F.displacement(ms["at"], s):
        return None
    L = ms["level"]
    if not _first_touch(F, L - b, L + b, ms["at"], i) or not F.confirmed_retest(i, L - b, L + b, s, _ext(F, j, s)):
        return None
    ext = _ext(F, j, s)
    return _setup(F, s, ext - s * b, ext, f"RANGE_SWEEP_{mode}", level, j, {"range": [lo, hi] if lo is not None else None, "range_id": rid,
                                                                             "sweep_bar": j, "mss_bar": ms["at"]})


def internal_external(F, s, p, x):
    i, b = F.i, F.b()
    if b is None:
        return None
    h = x.get("htf")
    if h is None:
        raise Unavailable("brak zamkniętego kontekstu H1")
    dr = h.dealing_range(h.i)
    if not dr:
        return None
    if not _gt(dr["mid"], F.c[i], s):
        return None                                                            # not in discount (premium for SHORT)
    ext_t = dr["hi"] if s > 0 else dr["lo"]
    hs = [k for k in range(h.n) if h.t[k] > h.t[max(0, h.i - 50)]]
    if any(_gt(h.h[k] if s > 0 else h.l[k], ext_t, s) for k in hs[-3:]):
        return None
    sw = F.swept_swing(i - 1, s, 10)
    if not sw:
        return None
    j, _ = sw
    bos = F.last_break(i - 1, s, i - j, start=j)
    if not bos:
        return None
    L = bos["level"]
    if not F.confirmed_retest(i, L - b, L + b, s, _ext(F, j, s)):
        return None
    ext = _ext(F, j, s)
    risk = abs(F.c[i] - (ext - s * b))
    if risk <= 0 or abs(ext_t - F.c[i]) < float(p.get("min_rr", 1.0)) * risk:
        return None                                                            # too little room to the external target after costs
    return _setup(F, s, ext - s * b, ext, "INT_EXT", L, j, {"htf_range": dr, "external_target": ext_t, "internal_sweep_bar": j}, target=ext_t)


def cross_asset_divergence(F, s, p, x):
    i, b = F.i, F.b()
    B = x.get("bench")
    if B is None:
        raise Unavailable("brak zsynchronizowanego feedu benchmarku BTC")
    if b is None or B.n < 30:
        return None
    if abs(B.t[B.i] - F.t[i]) > 1:
        raise Unavailable("benchmark niezsynchronizowany z kontraktem (inny czas ostatniej świecy)")
    win = int(p.get("window", 8))
    bk = next((k for k in range(B.i, B.i - win, -1) if B.LL(20, k) is not None and (B.l[k] < B.LL(20, k) if s > 0 else B.h[k] > B.HH(20, k))), None)
    if bk is None:
        return None
    own = [k for k in range(i - win, i + 1)]
    if any((F.l[k] < F.LL(20, k) if s > 0 else F.h[k] > F.HH(20, k)) for k in own if F.LL(20, k) is not None):
        return None
    ch = F.last_break(i - 1, s, win, kinds=("CHOCH",))
    if not ch:
        return None
    L = ch["level"]
    sw = F.swings(ch["at"], "L" if s > 0 else "H", 1)
    inval = sw[-1].price if sw else float(F.l[i - win:i].min() if s > 0 else F.h[i - win:i].max())
    if not F.confirmed_retest(i, L - b, L + b, s, inval):
        return None
    return _setup(F, s, inval - s * b, inval, "XASSET_DIV", L, ch["at"], {"bench_break_bar_t": float(B.t[bk]), "choch_bar": ch["at"]})


def nested_structure(F, s, p, x):
    i, b = F.i, F.b()
    h, h2 = x.get("htf"), x.get("htf2")
    if h is None or h2 is None:
        raise Unavailable("brak kontekstu M1/M5 z własnego feedu")
    if b is None or h2.trend()[0] != s:
        return None
    ob = None
    for k in range(h.i, max(2, h.i - 40), -1):
        if h.structure_break(k, s) and h.displacement(k, s):
            ob = h.order_block(k, s)
            break
    if not ob or not any(F.touched(k, ob["lo"], ob["hi"]) for k in range(max(0, i - 6), i + 1)):
        return None
    bos = F.last_break(i - 1, s, 6)
    if not bos:
        return None
    L = bos["level"]
    distal = ob["lo"] if s > 0 else ob["hi"]
    if not F.confirmed_retest(i, L - b, L + b, s, distal):
        return None
    return _setup(F, s, distal - s * b, distal, "NESTED", ob["mid"], bos["at"], {"m1_ob": ob, "s15_bos": bos["at"]})


# ============================================================================ SCALP families
def ema_pullback(F, s, p, x):
    i, b = F.i, F.b()
    if b is None or i < 25:
        return None
    if not _gt(F.ema9[i], F.ema21[i], s):
        return None
    if p.get("ema21_rising") and not _gt(F.ema21[i], F.ema21[i - 1], s):
        return None
    if p.get("htf_trend", True):
        ok, _ = _htf_ok(x, s)
        if not ok:
            return None
    prev = range(i - 3, i)
    if not any(F.l[k] <= F.ema9[k] if s > 0 else F.h[k] >= F.ema9[k] for k in prev):
        return None
    if any(_gt(F.ema21[k], F.c[k], s) for k in prev):
        return None
    if not _gt(F.c[i], (F.h[i - 1] + b) if s > 0 else (F.l[i - 1] - b), s):
        return None
    ext = float(F.l[i - 3:i + 1].min() if s > 0 else F.h[i - 3:i + 1].max())
    return _setup(F, s, ext - s * b, ext, "EMA_PULLBACK", float(F.ema9[i]), i, {"ema9": float(F.ema9[i]), "ema21": float(F.ema21[i])})


def bb_reentry(F, s, p, x):
    i, b = F.i, F.b()
    bb = F.bb(i)
    adx = F.ADX(i)
    if b is None or bb is None or adx is None or adx >= float(p.get("adx_max", 20)):
        return None
    band = bb["lo"] if s > 0 else bb["up"]
    if not (_gt(band, F.l[i] if s > 0 else F.h[i], s) and _gt(F.c[i], band, s) and (F.bull(i) if s > 0 else F.bear(i))):
        return None
    if p.get("wick_ratio"):
        wick = (min(F.o[i], F.c[i]) - F.l[i]) if s > 0 else (F.h[i] - max(F.o[i], F.c[i]))
        if wick < float(p["wick_ratio"]) * max(F.body(i), F.quantum):
            return None
    ext = _ext(F, i, s)
    return _setup(F, s, ext - s * b, ext, "BB_REENTRY", band, i, {"bb": bb, "adx": adx}, target=bb["mid"], target2=(bb["up"] if s > 0 else bb["lo"]))


def vwap_reclaim(F, s, p, x):
    i, b = F.i, F.b()
    if b is None:
        return None
    if p.get("htf_trend", True):
        ok, _ = _htf_ok(x, s)
        if not ok:
            return None
    anchor = p.get("anchor", "SESSION")
    if anchor == "UTC_DAY":
        a = datetime.fromtimestamp(F.t[i], timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    else:
        a = _session_anchor(F.t[i], *p.get("session", ("Europe/London", "08:00")))
    vw = []
    for k in range(i - 6, i + 1):
        v, how = F.vwap(k, a, use_tick_proxy=bool(p.get("tick_proxy")))
        if v is None:
            if how == "NO_VOLUME":
                raise Unavailable("brak wolumenu do VWAP (FX: dozwolony tylko jawny proxy aktywności tickowej)")
            return None
        vw.append(v)
    vw = np.array(vw)
    cl = F.c[i - 6:i + 1]
    below = [(cl[k] < vw[k]) if s > 0 else (cl[k] > vw[k]) for k in range(7)]
    r = next((k for k in range(2, 6) if below[k - 2] and below[k - 1] and not below[k]), None)
    if r is None or (6 - r) > 3:
        return None
    if p.get("max_crosses") is not None:
        cr = int(np.sum(np.diff(np.sign(cl - vw)) != 0))
        # 1.46 (I0850): the catalog limit is "<= N crosses in 10 bars" - the 3 bars before the 7-bar reclaim window are added here; a bar
        # whose VWAP is unknown (before the anchor / no volume) is skipped, so the count never drops below the 7-bar one
        older = []
        for k in range(max(0, i - 9), i - 6):
            v_k, _ = F.vwap(k, a, use_tick_proxy=bool(p.get("tick_proxy")))
            older.append(None if v_k is None else float(np.sign(F.c[k] - v_k)))
        sg = older + [float(x) for x in np.sign(cl - vw)]
        cr += sum(1 for u, w in zip(sg[:len(older)], sg[1:len(older) + 1]) if u is not None and w is not None and u != w)
        if cr > int(p["max_crosses"]):
            return None
    v = vw[6]
    if not (F.touched(i, v - b, v + b) and _gt(F.c[i], v, s) and (F.bull(i) if s > 0 else F.bear(i))):
        return None
    ext = _ext(F, i, s)
    return _setup(F, s, ext - s * b, ext, "VWAP_RECLAIM", v, i - 6 + r, {"vwap": v, "vwap_kind": how, "anchor": a})


def level_breakout_retest(F, s, p, x):
    """FX_SCALP_04 opening range (first 15 min of the session), CP_SCALP_02 HH20 + RVOL, OTC_SCALP_04 HH20."""
    i, b = F.i, F.b()
    if b is None:
        return None
    wait = int(p.get("retest_within", 3))
    for k in range(i - 1, max(21, i - wait - 1), -1):
        if p.get("level") == "OPENING_RANGE":
            a = _session_anchor(F.t[k], *p.get("session", ("Europe/London", "08:00")))
            orb = [m for m in range(F.n) if a <= F.t[m] < a + 900]
            if len(orb) < 2 or F.t[k] < a + 900:
                continue
            lvl = float(F.h[orb].max() if s > 0 else F.l[orb].min())
        else:
            lvl = F.HH(20, k) if s > 0 else F.LL(20, k)
        if lvl is None or not _gt(F.c[k], lvl + s * b, s):
            continue
        if p.get("rvol_min"):
            rv = F.rvol(k)
            if rv is None:
                raise Unavailable("brak rzeczywistego wolumenu – strategia wymaga RVOL")
            if rv < float(p["rvol_min"]):
                return None
        if any(_gt(lvl - s * b, F.c[m], s) for m in range(k + 1, i + 1)):
            return None
        if F.touched(i, lvl - b, lvl + b) and _gt(F.c[i], lvl, s) and (F.bull(i) if s > 0 else F.bear(i)):
            ext = _ext(F, i, s)
            return _setup(F, s, ext - s * b, ext, "BREAKOUT_RETEST", lvl, k, {"level": lvl, "breakout_bar": k, "kind": p.get("level", "HH20"),
                                                                              "rvol": F.rvol(k)})
        return None
    return None


def donchian(F, s, p, x):
    i, b = F.i, F.b()
    adx = F.ADX(i)
    if b is None or adx is None or adx < float(p.get("adx_min", 25)) or i < 25:
        return None
    ok, _ = _htf_ok(x, s)
    if not ok:
        return None
    lvl = F.HH(20) if s > 0 else F.LL(20)
    if not _gt(F.c[i], lvl + s * b, s) or not (F.A(i) and F.A(i - 5) and F.A(i) > F.A(i - 5)):
        return None
    ext = float(F.l[i - 2:i + 1].min() if s > 0 else F.h[i - 2:i + 1].max())
    return _setup(F, s, ext - s * b, ext, "DONCHIAN", lvl, i, {"adx": adx, "donchian": lvl})


def compression_breakout(F, s, p, x):
    i, b, a = F.i, F.b(), F.A()
    if b is None or i < 8:
        return None
    rng = F.h[i - 5:i] - F.l[i - 5:i]
    if int(np.sum(rng <= float(p.get("k_range", 0.6)) * a)) < 3:
        return None
    lvl = float(F.h[i - 5:i].max() if s > 0 else F.l[i - 5:i].min())
    if not _gt(F.c[i], lvl, s) or F.body(i) < float(p.get("k_body", 1.0)) * a:
        return None
    if p.get("close_extreme") and not (F.close_pos(i) >= 0.8 if s > 0 else F.close_pos(i) <= 0.2):
        return None
    ext = float(F.l[i - 5:i].min() if s > 0 else F.h[i - 5:i].max())
    return _setup(F, s, ext - s * b, ext, "COMPRESSION", lvl, i - 1, {"compression_ranges": rng.tolist(), "atr": a})


def rsi2_snapback(F, s, p, x):
    i, b = F.i, F.b()
    if b is None or i < 55:
        return None
    if p.get("htf_trend"):
        ok, _ = _htf_ok(x, s)
    else:
        ok = F.trend()[0] == s and F.trend()[1] in ("EMA20_50", "SWINGS_HH_HL", "SWINGS_LH_LL")
    if not ok:
        return None
    r0, r1 = F.rsi2[i - 1], F.rsi2[i]
    if not ((r0 < 10 and r1 > 20) if s > 0 else (r0 > 90 and r1 < 80)):
        return None
    if not _gt(F.c[i], F.h[i - 1] if s > 0 else F.l[i - 1], s):
        return None
    ext = float(F.l[i - 3:i + 1].min() if s > 0 else F.h[i - 3:i + 1].max())
    tgt = F.HH(10) if s > 0 else F.LL(10)
    return _setup(F, s, ext - s * b, ext, "RSI2", None, i, {"rsi2_prev": float(r0), "rsi2": float(r1)},
                  target=tgt if tgt is not None and _gt(tgt, F.c[i], s) else None)


def engulfing_support(F, s, p, x):
    i, b = F.i, F.b()
    h = x.get("htf")
    if b is None or i < 3:
        return None
    if p.get("support") == "LOCAL20":
        if h is None:
            raise Unavailable("brak kontekstu M1 z własnego feedu")
        lv = h.LL(20, h.i) if s > 0 else h.HH(20, h.i)
        levels = [lv] if lv is not None else []
    else:
        if h is None:
            raise Unavailable("brak kontekstu M15")
        levels = [pv.price for pv in h.swings(h.i, "L" if s > 0 else "H", 4)]
    if not levels:
        return None
    a, c_ = i - 1, i
    if not ((F.bear(a) and F.bull(c_)) if s > 0 else (F.bull(a) and F.bear(c_))):
        return None
    if F.body(c_) <= F.body(a) or not (min(F.o[c_], F.c[c_]) <= min(F.o[a], F.c[a]) and max(F.o[c_], F.c[c_]) >= max(F.o[a], F.c[a])):
        return None
    ext = float(min(F.l[a], F.l[c_]) if s > 0 else max(F.h[a], F.h[c_]))
    lvl = next((L for L in levels if abs(ext - L) <= b), None)
    if lvl is None or not _gt(F.c[c_], F.h[a] if s > 0 else F.l[a], s):
        return None
    return _setup(F, s, ext - s * b, ext, "ENGULF_SUPPORT", lvl, a, {"support": lvl})


def double_bottom(F, s, p, x):
    i, b, a = F.i, F.b(), F.A()
    if b is None:
        return None
    ps = F.swings(i, "L" if s > 0 else "H", 4)
    for y in range(len(ps) - 1, 0, -1):
        p2, p1 = ps[y], ps[y - 1]
        if not 3 <= p2.k - p1.k <= 12 or abs(p2.price - p1.price) > float(p.get("tol_atr", 0.2)) * a:
            continue
        neck = float(F.h[p1.k:p2.k + 1].max() if s > 0 else F.l[p1.k:p2.k + 1].min())
        if _gt(F.c[i], neck + s * b, s) and not _gt(F.c[i - 1], neck + s * b, s) and p2.confirmed_at <= i:
            low = min(p1.price, p2.price) if s > 0 else max(p1.price, p2.price)
            return _setup(F, s, low - s * b, low, "DOUBLE_BOTTOM", neck, p1.k, {"pivots": [p1.k, p2.k], "neckline": neck},
                          target=neck + s * abs(neck - low))
        return None
    return None


def two_bar_momentum(F, s, p, x):
    i, b, a = F.i, F.b(), F.A()
    if b is None or i < 55:
        return None
    if p.get("htf_trend", True):
        ok, _ = _htf_ok(x, s)
        if not ok:
            return None
    for k in (i - 1, i):
        if not ((F.bull(k) and F.close_pos(k) >= 0.8) if s > 0 else (F.bear(k) and F.close_pos(k) <= 0.2)) or F.body(k) < 0.5 * a:
            return None
    if not _gt(F.c[i], F.h[i - 1] if s > 0 else F.l[i - 1], s):
        return None
    ext = float(min(F.l[i - 1], F.l[i]) if s > 0 else max(F.h[i - 1], F.h[i]))
    return _setup(F, s, ext - s * b, ext, "TWO_BAR", None, i - 1, {"bodies_atr": [F.body(i - 1) / a, F.body(i) / a]}, timeout_bars=4)


def squeeze_volume(F, s, p, x):
    i, b = F.i, F.b()
    if b is None or i < 230:
        return None
    bw = np.array([(F.bb(k) or {}).get("bw") or np.nan for k in range(F.n)], float)
    low = 0
    for k in range(i - 5, i):
        ref = bw[k - 200:k]
        ref = ref[np.isfinite(ref)]
        if len(ref) >= 180 and np.isfinite(bw[k]) and bw[k] < np.percentile(ref, 20):
            low += 1
    if low < 3:
        return None
    lvl = F.HH(10) if s > 0 else F.LL(10)
    rv = F.rvol(i)
    if rv is None:
        raise Unavailable("brak rzeczywistego wolumenu – squeeze wymaga RVOL")
    if not _gt(F.c[i], lvl, s) or rv < float(p.get("rvol_min", 1.5)):
        return None
    ext = float(F.l[i - 5:i].min() if s > 0 else F.h[i - 5:i].max())
    return _setup(F, s, ext - s * b, ext, "SQUEEZE", lvl, i - 1, {"squeeze_bars": low, "rvol": rv})


def relative_strength(F, s, p, x):
    i, b = F.i, F.b()
    B = x.get("bench")
    if B is None:
        raise Unavailable("brak zsynchronizowanego feedu BTC")
    if b is None or i < 25 or B.n < 20:
        return None
    if abs(B.t[B.i] - F.t[i]) > 1:
        raise Unavailable("benchmark niezsynchronizowany")
    def z(G):
        A = G.A(G.i)
        if A is None or G.c[G.i] <= 0 or G.c[G.i - 3] <= 0:
            return None, None
        r = G.c[G.i] / G.c[G.i - 3] - 1
        return r, r / (A / G.c[G.i])
    ra, za = z(F)
    rb, zb = z(B)
    if za is None or zb is None:
        return None
    if not (_gt(ra, 0, s) and _gt(rb, 0, s) and s * (za - zb) >= float(p.get("z_min", 0.5))):
        return None
    lvl = F.HH(20) if s > 0 else F.LL(20)
    if not _gt(F.c[i], lvl, s):
        return None
    ext = float(F.l[i - 2:i + 1].min() if s > 0 else F.h[i - 2:i + 1].max())
    return _setup(F, s, ext - s * b, ext, "REL_STRENGTH", lvl, i, {"z_asset": za, "z_btc": zb, "r15_asset": ra, "r15_btc": rb})


def l2_aggressor(F, s, p, x):
    i, b = F.i, F.b()
    flow = x.get("flow") or []
    if not flow:
        raise Unavailable("brak aktualnego L2 i strumienia transakcji z agresorem")
    if flow[-1].get("aggressor_semantics", "NOT_VERIFIED") != "VERIFIED":          # TASK 004: no unverified `trades_aggressor` capability
        raise Unavailable("trades_aggressor NOT_VERIFIED – znaczenie strony transakcji Hyperliquid nie jest potwierdzone (TASK 004)")
    if b is None:
        return None
    lvl = F.HH(10) if s > 0 else F.LL(10)
    if not _gt(F.c[i], lvl, s):
        return None
    ok = [f for f in flow[-6:] if f.get("connected", True) and f.get("imbalance5") is not None and f.get("aggr_buy_share_30s") is not None
          and s * f["imbalance5"] >= 0.20 and (f["aggr_buy_share_30s"] >= 0.60 if s > 0 else f["aggr_buy_share_30s"] <= 0.40)]
    if len(ok) < 2 or ok[-1]["t"] - ok[0]["t"] < 2.0:
        return None
    ext = float(F.l[i - 2:i + 1].min() if s > 0 else F.h[i - 2:i + 1].max())
    return _setup(F, s, ext - s * b, ext, "L2_AGGRESSOR", lvl, i, {"flow": ok[-2:]})


def _oi_ref_t(F, i, x, legacy: float) -> float:
    """1.46 (I0765): the 5-min OI change is read at the CLOSE of the signal candle (its open + the catalog TF length x['tf_s'], supplied
    by the basket service), never later than x['now'] (no look-ahead). It was read at the candle OPEN (second_mitigation: 15 min early
    on M15) or open + 60 s (oi_expansion: 4 min early on M5). Without x['tf_s'] (a direct caller) the 1.46.0 time `legacy` is kept."""
    tf_s = x.get("tf_s")
    if not tf_s:
        return legacy
    t = float(F.t[i]) + float(tf_s)
    now = x.get("now")
    return min(t, float(now)) if now is not None else t


def oi_delta(x, t, window_s):
    oi = x.get("oi") or []
    if len(oi) < 2:
        return None
    now = [v for tt, v in oi if tt <= t]
    past = [v for tt, v in oi if tt <= t - window_s]
    if not now or not past:
        return None
    return now[-1] - past[-1]


def oi_expansion(F, s, p, x):
    i, b = F.i, F.b()
    if b is None or i < 25:
        return None
    ok, _ = _htf_ok(x, s)
    if not ok:
        return None
    lvl = F.HH(20) if s > 0 else F.LL(20)
    if not _gt(F.c[i], lvl + s * b, s):
        return None
    rv = F.rvol(i)
    if rv is None:
        raise Unavailable("brak rzeczywistego wolumenu")
    d = oi_delta(x, _oi_ref_t(F, i, x, F.t[i] + 60), 300)                  # 1.46 (I0765): at the close of the signal candle
    if d is None:
        raise Unavailable("brak historii OI (zbierana od startu – WARMUP 5 min)")
    if rv < 1.5 or d <= 0:
        return None
    ext = float(F.l[i - 2:i + 1].min() if s > 0 else F.h[i - 2:i + 1].max())
    return _setup(F, s, ext - s * b, ext, "OI_EXPANSION", lvl, i, {"rvol": rv, "d_oi_5m_contracts": d})


def ema20_mean_reclaim(F, s, p, x):
    i, b, a = F.i, F.b(), F.A()
    adx = F.ADX(i)
    if b is None or adx is None or adx >= 20 or i < 25:
        return None
    d0, d1 = F.c[i - 1] - F.ema20[i - 1], F.c[i] - F.ema20[i]
    if not ((d0 <= -a and d1 - d0 >= 0.5 * a and F.bull(i)) if s > 0 else (d0 >= a and d0 - d1 >= 0.5 * a and F.bear(i))):
        return None
    ext = float(min(F.l[i - 1], F.l[i]) if s > 0 else max(F.h[i - 1], F.h[i]))
    return _setup(F, s, ext - s * b, ext, "EMA20_RECLAIM", float(F.ema20[i]), i - 1, {"dev_prev_atr": d0 / a, "dev_atr": d1 / a, "adx": adx},
                  target=float(F.ema20[i]))


def inside_bar(F, s, p, x):
    i, b = F.i, F.b()
    if b is None or i < 3:
        return None
    m, ib = i - 2, i - 1
    if not (F.h[ib] <= F.h[m] and F.l[ib] >= F.l[m]):
        return None
    ok, _ = _htf_ok(x, s)
    if not ok:
        return None
    if not _gt(F.c[i], (F.h[m] + b) if s > 0 else (F.l[m] - b), s):
        return None
    ext = _ext(F, m, s)
    return _setup(F, s, ext - s * b, ext, "INSIDE_BAR", float(F.h[m] if s > 0 else F.l[m]), m, {"mother": m})


def failed_breakdown(F, s, p, x):
    i, b = F.i, F.b()
    j = i - 1
    if b is None or j < 21:
        return None
    lv = F.LL(20, j) if s > 0 else F.HH(20, j)
    if not ((F.l[j] < lv - b and F.c[j] > lv) if s > 0 else (F.h[j] > lv + b and F.c[j] < lv)):
        return None
    if not _gt(F.c[i], F.h[j] if s > 0 else F.l[j], s):
        return None
    ext = _ext(F, j, s)
    return _setup(F, s, ext - s * b, ext, "FAILED_BREAKDOWN", lv, j, {"ll20": lv, "sweep_bar": j})


FAMILIES = {f.__name__: f for f in (sweep_choch_retest, bos_ob_retest, fvg_continuation, ifvg_reversal, breaker_retest, second_mitigation, eq_raid,
                                    ote_continuation, range_sweep, internal_external, cross_asset_divergence, nested_structure, ema_pullback,
                                    bb_reentry, vwap_reclaim, level_breakout_retest, donchian, compression_breakout, rsi2_snapback,
                                    engulfing_support, double_bottom, two_bar_momentum, squeeze_volume, relative_strength, l2_aggressor,
                                    oi_expansion, ema20_mean_reclaim, inside_bar, failed_breakdown)}
