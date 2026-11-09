"""Entry detectors of the 20 SH variants. Every rule is written ONCE for BUY and evaluated on the mirrored view for SELL
(features.TF(mirror=True)): all inequalities, highs/lows and indicator sides flip together, so the SELL version is exact and explicit.

A detector reads only closed bars (index i = last closed bar of the signal TF; context TFs: their last closed bar, which closed at or
before it) and returns a Detection in VIEW units (the engine maps levels back to prices):
  status: SETUP | NO_SETUP | WARMING_UP | NO_DATA ; reason, reason_code, checklist
  trigger_i, sl (view level, already includes the buffer b), invalidation_pre_fill (view level a close must not cross before the fill),
  structure (frozen levels used by the hedge policy and the chart), structure_key (idempotency), natural_targets (TP1, TP2 view levels
  when the rule defines them - POC/VAH, BB middle/opposite band), one_per_structure (one setup per direction and session / level).
Thresholds are the PMW research starting parameters from config/sh_strategy_pack_v2.json.
"""
from __future__ import annotations

from . import features as F


class Det(dict):
    pass


def _cl(cl: list, cid: str, label: str, status: str, detail: str = "") -> str:
    cl.append({"id": cid, "label": label, "status": status, "detail": detail})
    return status


def _none(*xs) -> bool:
    return any(x is None for x in xs)


def _done(status, code, reason, cl, **kw) -> Det:
    return Det(status=status, reason_code=code, reason=reason, checklist=cl, **kw)


def _need(v: F.TF, n: int, cl: list, label: str) -> Det | None:
    if v.n < n:
        _cl(cl, f"warm_{v.name}", f"Historia {v.name}", "WAIT", f"{v.n} zamkniętych świec < {n} (rozgrzewka)")
        return _done("WARMING_UP", "WARMING_UP", f"{label}: za mało zamkniętych świec {v.name} ({v.n} < {n})", cl)
    return None


def _ctx_trend(X: F.Context, side_mirror: bool, tf: str, htf: bool, cl: list, *, allow_neutral: bool = False,
               reject_strong_against: bool = False) -> Det | None:
    """Context requirement on TF `tf`: TrendUp (in the view) or, with allow_neutral, also neutral. reject_strong_against: only a strong
    opposite trend (opposite TrendUp + ADX14 >= 25) fails."""
    v = X.tf(tf, side_mirror)
    w = X.tf(tf, not side_mirror)
    need = (200 if htf else 50) * int((X.cm.get("warmup") or {}).get("ema_mult", 5))
    if v.n < need:
        _cl(cl, f"ctx_{tf}", f"Kontekst {tf}", "WAIT", f"historia {tf}: {v.n} < {need} zamkniętych świec (5 × najdłuższa EMA)")
        return _done("WARMING_UP", "WARMING_UP", f"kontekst {tf}: za mało zamkniętych świec", cl)
    i = v.n - 1
    up, dn = F.trend_up(v, i, htf), F.trend_up(w, i, htf)
    if up is None or dn is None:
        _cl(cl, f"ctx_{tf}", f"Kontekst {tf}", "WAIT", "rozgrzewka EMA")
        return _done("WARMING_UP", "WARMING_UP", f"kontekst {tf}: rozgrzewka EMA", cl)
    if reject_strong_against:
        ad = v.adx()[i]
        if ad is None:
            return _done("WARMING_UP", "WARMING_UP", f"kontekst {tf}: rozgrzewka ADX", cl)
        if dn and ad >= 25:
            _cl(cl, f"ctx_{tf}", f"Kontekst {tf}", "FAIL", f"silny przeciwny trend (ADX {ad:.1f})")
            return _done("NO_SETUP", "CONTEXT_AGAINST", f"{tf}: silny przeciwny trend", cl)
        _cl(cl, f"ctx_{tf}", f"Kontekst {tf}", "PASS", f"brak silnego przeciwnego trendu (ADX {ad:.1f})")
        return None
    if up or (allow_neutral and not dn):
        _cl(cl, f"ctx_{tf}", f"Kontekst {tf}", "PASS", "trend zgodny" if up else "neutralny")
        return None
    _cl(cl, f"ctx_{tf}", f"Kontekst {tf}", "FAIL", "trend niezgodny" if dn else "brak trendu zgodnego")
    return _done("NO_SETUP", "CONTEXT_NOT_ALIGNED", f"{tf}: kontekst niezgodny z kierunkiem", cl)


def _ctx_range(X: F.Context, mir: bool, tf: str, cl: list) -> Det | None:
    v = X.tf(tf, mir)
    if v.n < 60:
        return _done("WARMING_UP", "WARMING_UP", f"Range({tf}): za mało świec", cl)
    r = F.regime_range(v, v.n - 1)
    if r is None:
        return _done("WARMING_UP", "WARMING_UP", f"Range({tf}): rozgrzewka", cl)
    _cl(cl, f"range_{tf}", f"Reżim zakresu {tf}", "PASS" if r else "FAIL", "ADX14<20 i płaska EMA20" if r else "brak zakresu")
    return None if r else _done("NO_SETUP", "REGIME_NOT_RANGE", f"{tf} nie jest w zakresie", cl)


def _break_retest(v: F.TF, i: int, level_at, b: float, maxb: int) -> tuple[int, float] | None:
    """Breakout bar j in [i-maxb, i-1] with prev close <= L+b < close[j] (L = level_at(j), known before j) and retest at bar i:
    low <= L+b, close > L+b, close > open; no close below L-b between j and i (hard failure)."""
    for j in range(i - 1, max(0, i - maxb) - 1, -1):
        L = level_at(j)
        if L is None or j < 1:
            continue
        if not (v.c[j - 1] <= L + b < v.c[j]):
            continue
        if any(v.c[k] < L - b for k in range(j + 1, i)):
            return None
        if v.l[i] <= L + b and v.h[i] >= L - b and v.c[i] > L + b and v.c[i] > v.o[i]:
            return j, L
        return None
    return None


# ================================================================================================== shared trend pullback (SC01, HG01, HG10)
def trend_pullback_ema(X, vid, tf, mir, cfg) -> Det:
    cl: list = []
    v = X.tf(tf, mir)
    w = _need(v, 260, cl, vid)
    if w:
        return w
    for ctx_tf, htf in ((("M5", False), ("M15", False)) if tf in ("M1", "M3") else (("M15", False), ("H1", True))):
        if ctx_tf == tf:
            continue
        r = _ctx_trend(X, mir, ctx_tf, htf, cl)
        if r:
            return r
    i = v.n - 1
    e20, b = v.ema(20), v.b(i, X.tick, X.cm)
    if _none(e20[i], e20[i - 5], b):
        return _done("WARMING_UP", "WARMING_UP", "rozgrzewka EMA20/ATR", cl)
    sw = v.swings("L", i - 1)
    prot = sw[-1]["price"] if sw else None
    win = range(i - 4, i + 1)
    touched = any(v.l[k] <= e20[k] + b and v.h[k] >= e20[k] - b for k in win if e20[k] is not None)
    if not touched:
        _cl(cl, "zone", "Korekta do EMA20±b (5 świec)", "WAIT", "brak dotknięcia strefy")
        return _done("NO_SETUP", "NO_PULLBACK", "brak korekty do EMA20", cl)
    if prot is not None and any(v.c[k] < prot for k in win):
        _cl(cl, "swing", "Chroniony swing", "FAIL", "zamknięcie pod chronionym swingiem")
        return _done("NO_SETUP", "SWING_BROKEN", "korekta złamała chroniony swing", cl)
    _cl(cl, "zone", "Korekta do EMA20±b (5 świec)", "PASS", "")
    if not (v.c[i] > e20[i] + b and v.c[i] > v.h[i - 1]):
        _cl(cl, "trigger", "Zamknięcie > EMA20+b i > high[t-1]", "WAIT", "")
        return _done("NO_SETUP", "NO_TRIGGER", "brak triggera", cl)
    _cl(cl, "trigger", "Zamknięcie > EMA20+b i > high[t-1]", "PASS", "")
    low = min(v.l[k] for k in win)
    sl = (min(low, prot) if (prot is not None and vid != "PMW_SC01") else low) - b
    pre_high = max(v.h[k] for k in range(i - 10, i - 4))
    return _done("SETUP", "OK", "warunki spełnione", cl, trigger_i=i, sl=sl, invalidation_pre_fill=sl,
                 structure={"ema20": e20[i], "protected_swing": prot, "correction_low": low, "pre_correction_high": pre_high, "b": b},
                 structure_key=f"EMA20PB:{round(low, 2)}")


# ================================================================================================== HG02 breakout-retest
def breakout_retest(X, vid, tf, mir, cfg) -> Det:
    cl: list = []
    v = X.tf(tf, mir)
    w = _need(v, 120, cl, vid) or _ctx_trend(X, mir, "H1", True, cl)
    if w:
        return w
    i = v.n - 1
    b = v.b(i, X.tick, X.cm)
    if b is None:
        return _done("WARMING_UP", "WARMING_UP", "rozgrzewka ATR", cl)

    def level_at(j):
        hs = [p for p in v.swings("H", j - 1) if p["i"] >= j - 60]
        above = [p["price"] for p in hs if p["price"] >= v.c[j - 1] - b]
        return min(above) if above else None
    r = _break_retest(v, i, level_at, b, X.cm.get("retest_max_bars", 3))
    if not r:
        _cl(cl, "break", "Wybicie potwierdzonego oporu + retest (3 świece)", "WAIT", "")
        return _done("NO_SETUP", "NO_BREAK_RETEST", "brak wybicia z retestem", cl)
    j, L = r
    _cl(cl, "break", "Wybicie potwierdzonego oporu + retest (3 świece)", "PASS", f"L={v.out(L):.2f}")
    sw = v.swings("L", j - 1)
    prot = sw[-1]["price"] if sw else None
    rl = min(v.l[k] for k in range(j, i + 1))
    sl = min(rl, prot if prot is not None else rl) - b
    return _done("SETUP", "OK", "warunki spełnione", cl, trigger_i=i, sl=sl, invalidation_pre_fill=sl,
                 structure={"L": L, "breakout_i": j, "retest_low": rl, "protected_swing": prot, "b": b}, structure_key=f"BRK:{round(L, 2)}")


# ================================================================================================== Donchian retest (HG03, SC04)
def donchian_retest(X, vid, tf, mir, cfg) -> Det:
    cl: list = []
    v = X.tf(tf, mir)
    p = cfg.get("params") or {}
    n = int(p.get("channel", 20))
    w = _need(v, 120, cl, vid)
    if w:
        return w
    w = _ctx_trend(X, mir, "H1", True, cl) if vid == "PMW_HG03" else _ctx_trend(X, mir, "M15", False, cl)
    if w:
        return w
    i = v.n - 1
    ad, b, a = v.adx()[i], v.b(i, X.tick, X.cm), v.atr()
    if _none(ad, b, a[i - 1]):
        return _done("WARMING_UP", "WARMING_UP", "rozgrzewka ADX/ATR", cl)
    if ad < float(p.get("adx_min", 25)):
        _cl(cl, "adx", f"ADX14 {tf} ≥ {p.get('adx_min', 25)}", "FAIL", f"{ad:.1f}")
        return _done("NO_SETUP", "ADX_LOW", f"ADX {ad:.1f} za niski", cl)
    _cl(cl, "adx", f"ADX14 {tf} ≥ {p.get('adx_min', 25)}", "PASS", f"{ad:.1f}")
    up, dn = v.donchian(n)
    bb = 0.0 if vid == "PMW_HG03" else b                                # HG03: close > max of 20 prior bars; SC04: + b

    def level_at(j):
        if up[j] is None or a[j] is None or a[j - 1] is None:
            return None
        if vid == "PMW_SC04" and a[j] < a[j - 1]:
            return None
        return up[j] + bb - b                                              # _break_retest tests close > L + b
    r = _break_retest(v, i, level_at, b, X.cm.get("retest_max_bars", 3))
    if not r:
        _cl(cl, "break", f"Wybicie kanału {n} + retest", "WAIT", "")
        return _done("NO_SETUP", "NO_BREAK_RETEST", "brak wybicia kanału z retestem", cl)
    j, _L = r
    U, D = up[j], dn[j]
    _cl(cl, "break", f"Wybicie kanału {n} + retest", "PASS", f"górna {v.out(U):.2f}")
    rl = min(v.l[k] for k in range(j, i + 1))
    if vid == "PMW_HG03":
        sw = v.swings("L", i)
        swl = sw[-1]["price"] if sw else rl
        sl = min(swl, rl) - b
    else:
        sl = rl - b
    return _done("SETUP", "OK", "warunki spełnione", cl, trigger_i=i, sl=sl, invalidation_pre_fill=rl - b,
                 structure={"upper": U, "lower": D, "mid": (U + D) / 2, "breakout_i": j, "retest_low": rl, "b": b},
                 structure_key=f"DC{n}:{round(U, 2)}")


# ================================================================================================== opening range (HG04, SC03)
def opening_range(X, vid, tf, mir, cfg) -> Det:
    cl: list = []
    v = X.tf(tf, mir)
    m1 = X.tf("M1", mir)
    w = _need(v, 60, cl, vid)
    if w:
        return w
    w = _ctx_trend(X, mir, "M15", False, cl, reject_strong_against=True) if vid == "PMW_SC03" else _ctx_trend(X, mir, "H1", True, cl, allow_neutral=True)
    if w:
        return w
    i = v.n - 1
    b = v.b(i, X.tick, X.cm)
    if b is None:
        return _done("WARMING_UP", "WARMING_UP", "rozgrzewka ATR", cl)
    p = cfg.get("params") or {}
    win_m = float(p.get("entry_window_minutes", 60 if vid == "PMW_SC03" else 90))
    best = None
    for wdef in X.cm.get("or_windows") or []:
        ww = F.or_window(wdef, X.as_of)
        if not ww or ww[1] > v.close_t(i) or v.close_t(i) > ww[1] + 60 * win_m:
            continue
        a0, a1 = m1.since(ww[0]), m1.since(ww[1])
        idx = list(range(a0, a1))
        exp = int(round((ww[1] - ww[0]) / 60))
        if len(idx) < exp:
            _cl(cl, f"or_{wdef['id']}", f"OR {wdef['id']}", "FAIL", f"niepełne M1 w oknie ({len(idx)}/{exp}) – brak OR")
            continue
        best = (wdef, ww, max(m1.h[k] for k in idx), min(m1.l[k] for k in idx))
    if not best:
        _cl(cl, "or", "Zamrożony Opening Range", "WAIT", "brak zakończonego OR w oknie wejść")
        return _done("NO_SETUP", "NO_OPENING_RANGE", "brak aktywnego okna OR", cl)
    wdef, ww, H, Lo = best
    _cl(cl, "or", f"OR {wdef['id']} zamrożony", "PASS", f"{v.out(H):.2f}/{v.out(Lo):.2f}")
    r = _break_retest(v, i, lambda j: H if v.t[j] >= ww[1] - 1e-6 else None, b, X.cm.get("retest_max_bars", 3))
    if not r:
        return _done("NO_SETUP", "NO_BREAK_RETEST", "brak wybicia OR z retestem", cl)
    j, _ = r
    mid = (H + Lo) / 2
    rl = min(v.l[k] for k in range(j, i + 1))
    sl = (min(rl, Lo) if vid == "PMW_HG04" else rl) - b
    day = F.iso(ww[0])[:10]
    return _done("SETUP", "OK", "warunki spełnione", cl, trigger_i=i, sl=sl, invalidation_pre_fill=mid,
                 structure={"or_high": H, "or_low": Lo, "or_mid": mid, "or_window": wdef["id"], "or_start": F.iso(ww[0]), "or_end": F.iso(ww[1]),
                            "retest_low": rl, "b": b}, structure_key=f"OR:{wdef['id']}:{day}", one_per_structure=True)


# ================================================================================================== AVWAP pullback (HG05), session VWAP reclaim (SC02)
def _anchor(X) -> float:
    td = X.cm.get("trading_day") or {}
    return F.trading_day_start(X.as_of, td.get("tz", "America/New_York"), td.get("start", "17:00"))


def avwap_pullback(X, vid, tf, mir, cfg) -> Det:
    cl: list = []
    v = X.tf(tf, mir)
    w = _need(v, 60, cl, vid) or _ctx_trend(X, mir, "H1", True, cl)
    if w:
        return w
    i = v.n - 1
    anc = _anchor(X)
    vw = v.vwap(anc)
    if not any(v.tv[k] > 0 for k in range(v.since(anc), v.n)):
        return _done("NO_DATA", "NO_VOLUME", "brak wiarygodnego wolumenu (tick volume = 0) – AVWAP niedostępny", cl)
    b = v.b(i, X.tick, X.cm)
    if _none(b, vw[i], vw[i - 5] if i >= 5 else None):
        return _done("WARMING_UP", "WARMING_UP", "za mało świec od kotwicy AVWAP", cl)
    above_before = any(vw[k] is not None and v.c[k] > vw[k] + b for k in range(i - 12, i - 4))
    touch = any(vw[k] is not None and v.l[k] <= vw[k] + b and v.h[k] >= vw[k] - b for k in range(i - 4, i + 1))
    if not (above_before and touch):
        _cl(cl, "zone", "Wcześniej nad AVWAP i korekta do AVWAP±b", "WAIT", "")
        return _done("NO_SETUP", "NO_PULLBACK", "brak korekty do AVWAP", cl)
    if not (v.c[i] > vw[i] + b and v.c[i] > v.h[i - 1]):
        return _done("NO_SETUP", "NO_TRIGGER", "brak zamknięcia > AVWAP+b i > high[t-1]", cl)
    _cl(cl, "trigger", "Zamknięcie > AVWAP+b i > high[t-1]", "PASS", "")
    low = min(v.l[k] for k in range(i - 4, i + 1))
    sw = v.swings("L", i - 1)
    return _done("SETUP", "OK", "warunki spełnione", cl, trigger_i=i, sl=low - b, invalidation_pre_fill=low - b,
                 structure={"avwap": vw[i], "anchor": F.iso(anc), "anchor_kind": "TRADING_DAY_17NY", "protected_swing": sw[-1]["price"] if sw else None,
                            "b": b, "volume_source": "TICK_ACTIVITY"}, structure_key=f"AVWAP:{F.iso(anc)}:{round(low, 2)}")


def vwap_reclaim(X, vid, tf, mir, cfg) -> Det:
    cl: list = []
    v = X.tf(tf, mir)
    w = _need(v, 40, cl, vid) or _ctx_trend(X, mir, "M15", False, cl, allow_neutral=True)
    if w:
        return w
    i = v.n - 1
    anc = _anchor(X)
    vw = v.vwap(anc)
    if not any(v.tv[k] > 0 for k in range(v.since(anc), v.n)):
        return _done("NO_DATA", "NO_VOLUME", "brak tick volume – VWAP sesji niedostępny", cl)
    b = v.b(i, X.tick, X.cm)
    if b is None or any(vw[k] is None for k in range(i - 12, i + 1)):
        return _done("WARMING_UP", "WARMING_UP", "za mało świec sesji dla VWAP", cl)
    crosses = sum(1 for k in range(i - 9, i + 1) if (v.c[k] - vw[k]) * (v.c[k - 1] - vw[k - 1]) < 0)
    if crosses > int((cfg.get("params") or {}).get("max_crosses_10", 4)):
        _cl(cl, "chop", "Przecięcia VWAP w 10 świecach ≤ 4", "FAIL", str(crosses))
        return _done("NO_SETUP", "VWAP_CHOP", f"{crosses} przecięć VWAP w 10 świecach", cl)
    for j in range(i - 1, i - 4, -1):
        if not (v.c[j - 1] <= vw[j - 1] + b < v.c[j] and v.c[j] > vw[j] + b):
            continue
        below = sum(1 for k in range(j - 5, j) if v.c[k] < vw[k])
        if below < 2:
            continue
        if v.l[i] <= vw[i] + b and v.h[i] >= vw[i] - b and v.c[i] > vw[i] + b and v.c[i] > v.o[i]:
            low = min(v.l[k] for k in range(j - 1, i + 1))
            _cl(cl, "seq", "≥2 zamknięcia pod VWAP, przebicie VWAP+b, retest i wzrostowe zamknięcie", "PASS", "")
            return _done("SETUP", "OK", "warunki spełnione", cl, trigger_i=i, sl=low - b, invalidation_pre_fill=low - b,
                         structure={"vwap": vw[i], "anchor": F.iso(anc), "reclaim_i": j, "b": b, "volume_source": "TICK_ACTIVITY"},
                         structure_key=f"VWAPR:{F.iso(anc)}:{j}")
        break
    return _done("NO_SETUP", "NO_RECLAIM_RETEST", "brak sekwencji reclaim–retest VWAP", cl)


# ================================================================================================== squeeze (HG06 retest, SC05 break)
def _squeeze(v: F.TF, j: int, p: dict, cnt_min: int) -> tuple[bool, int]:
    _m, up, _lo, bw = v.bb(int(p.get("bb_n", 20)), float(p.get("bb_k", 2.0)))
    lb, q = int(p.get("bw_lookback", 120)), float(p.get("bw_pct", 0.20))
    from ...strategies.indicators import percentile_rank
    ranks = [percentile_rank(bw, k, lb) for k in range(j - 5, j)]
    hits = sum(1 for r in ranks if r is not None and r < q)
    return hits >= cnt_min, hits


def squeeze_break(X, vid, tf, mir, cfg) -> Det:
    cl: list = []
    v = X.tf(tf, mir)
    p = cfg.get("params") or {}
    w = _need(v, 160, cl, vid)
    if w:
        return w
    for ctx in ("M5", "M15"):
        if ctx != tf:
            r = _ctx_trend(X, mir, ctx, False, cl, allow_neutral=True)
            if r:
                return r
    i = v.n - 1
    _m, up, _lo, _bw = v.bb(int(p.get("bb_n", 20)), float(p.get("bb_k", 2.0)))
    a, b = v.atr(), v.b(i, X.tick, X.cm)
    if _none(up[i - 1], a[i], a[i - 1], b):
        return _done("WARMING_UP", "WARMING_UP", "rozgrzewka BB/ATR", cl)
    ok, hits = _squeeze(v, i, p, int(p.get("squeeze_min_of_5", 3)))
    _cl(cl, "squeeze", "BandWidth < 20. percentyl (≥3 z 5)", "PASS" if ok else "WAIT", f"{hits}/5")
    if not ok:
        return _done("NO_SETUP", "NO_SQUEEZE", "brak kompresji", cl)
    n = int(p.get("break_lookback", 10))
    BL = max(v.h[i - n:i])
    if not (v.c[i] > up[i - 1] and v.c[i] > BL + b and a[i] > a[i - 1]):
        return _done("NO_SETUP", "NO_TRIGGER", "brak wybicia nad pasmo i maksimum 10 świec+b przy rosnącym ATR", cl)
    _cl(cl, "trigger", "Zamknięcie > górne pasmo t-1 i > max(10)+b, ATR rośnie", "PASS", "")
    low3 = min(v.l[i - 2:i + 1])
    return _done("SETUP", "OK", "warunki spełnione", cl, trigger_i=i, sl=low3 - b, invalidation_pre_fill=BL,
                 structure={"break_level": BL, "compression_high": BL, "b": b}, structure_key=f"SQZ:{round(BL, 2)}:{i}")


def squeeze_retest(X, vid, tf, mir, cfg) -> Det:
    cl: list = []
    v = X.tf(tf, mir)
    p = cfg.get("params") or {}
    w = _need(v, 160, cl, vid) or _ctx_trend(X, mir, "M15", False, cl, allow_neutral=True) or _ctx_trend(X, mir, "H1", True, cl, allow_neutral=True)
    if w:
        return w
    i = v.n - 1
    _m, up, _lo, _bw = v.bb(int(p.get("bb_n", 20)), float(p.get("bb_k", 2.0)))
    a, b = v.atr(), v.b(i, X.tick, X.cm)
    if b is None:
        return _done("WARMING_UP", "WARMING_UP", "rozgrzewka ATR", cl)
    n = int(p.get("break_lookback", 10))

    def level_at(j):
        if up[j - 1] is None or a[j] is None or a[j - 1] is None or j < n + 6:
            return None
        if not _squeeze(v, j, p, 1)[0] or not (v.c[j] > up[j - 1] and a[j] > a[j - 1]):
            return None
        return max(v.h[j - n:j])
    r = _break_retest(v, i, level_at, b, X.cm.get("retest_max_bars", 3))
    if not r:
        return _done("NO_SETUP", "NO_BREAK_RETEST", "brak wybicia z kompresji z retestem", cl)
    j, BL = r
    comp_low = min(v.l[j - 5:j])
    rl = min(v.l[k] for k in range(j, i + 1))
    sl = (rl if p.get("sl_anchor", "RETEST") == "RETEST" else comp_low) - b
    _cl(cl, "break", "Kompresja, wybicie i retest poziomu", "PASS", f"poziom {v.out(BL):.2f}")
    return _done("SETUP", "OK", "warunki spełnione", cl, trigger_i=i, sl=sl, invalidation_pre_fill=sl,
                 structure={"break_level": BL, "compression_low": comp_low, "retest_low": rl, "b": b}, structure_key=f"SQZR:{round(BL, 2)}")


# ================================================================================================== sweep / failed breakout reclaim
def _support_levels(X, mir, v: F.TF, i: int) -> list[float]:
    m5 = X.tf("M5", mir)
    lv = [p["price"] for p in m5.swings("L", m5.n - 1)[-6:]]
    _hi, lo = X.prev_day_range(mir)
    if lo is not None:
        lv.append(lo)
    return lv


def _sweep(v: F.TF, i: int, levels: list[float], b: float, confirm_close: bool):
    for r in (i - 1,):
        for s in (r - 1, r):
            if s < 1:
                continue
            for L in sorted(levels, reverse=True):
                if not (v.l[s] < L - b and v.c[r] > L + b):
                    continue
                if any(v.l[k] < L - b for k in range(max(0, s - 10), s)):
                    continue                                    # L was already lost before: not a fresh sweep of a known level
                conf = v.c[i] > v.h[r] if confirm_close else (v.h[i] > v.h[r] and v.c[i] > L + b)
                if conf:
                    return s, r, L
    return None


def sweep_reclaim_sc(X, vid, tf, mir, cfg) -> Det:
    cl: list = []
    v = X.tf(tf, mir)
    w = _need(v, 60, cl, vid)
    if w:
        return w
    m15 = X.tf("M15", mir)
    rng = F.regime_range(m15, m15.n - 1) if m15.n > 60 else None
    if rng is None:
        return _done("WARMING_UP", "WARMING_UP", "kontekst M15: rozgrzewka", cl)
    if not rng:
        r = _ctx_trend(X, mir, "M15", False, cl)
        if r:
            return r
    i = v.n - 1
    b = v.b(i, X.tick, X.cm)
    if b is None:
        return _done("WARMING_UP", "WARMING_UP", "rozgrzewka ATR", cl)
    hit = _sweep(v, i, _support_levels(X, mir, v, i), b, True)
    if not hit:
        return _done("NO_SETUP", "NO_SWEEP_RECLAIM", "brak zejścia pod L i odzyskania z potwierdzeniem", cl)
    s, r, L = hit
    ext = min(v.l[k] for k in range(s, i + 1))
    _cl(cl, "sweep", "Low < L−b, zamknięcie > L+b, potwierdzenie nad high reclaim", "PASS", f"L={v.out(L):.2f}")
    return _done("SETUP", "OK", "warunki spełnione", cl, trigger_i=i, sl=ext - b, invalidation_pre_fill=ext,
                 structure={"L": L, "sweep_extreme": ext, "reclaim_i": r, "b": b}, structure_key=f"SWP:{round(L, 2)}:{s}")


def sweep_reclaim_hg(X, vid, tf, mir, cfg) -> Det:
    cl: list = []
    v = X.tf(tf, mir)
    w = _need(v, 60, cl, vid) or _ctx_trend(X, mir, "H1", True, cl, reject_strong_against=True)
    if w:
        return w
    i = v.n - 1
    b = v.b(i, X.tick, X.cm)
    if b is None:
        return _done("WARMING_UP", "WARMING_UP", "rozgrzewka ATR", cl)
    lv = [p["price"] for p in v.swings("L", i - 2)[-6:]] + _support_levels(X, mir, v, i)[-1:]
    hit = _sweep(v, i, lv, b, False)
    if not hit:
        return _done("NO_SETUP", "NO_SWEEP_RECLAIM", "brak sweep–reclaim z przebiciem high świecy reclaim", cl)
    s, r, L = hit
    ext = min(v.l[k] for k in range(s, i + 1))
    _cl(cl, "sweep", "Low < L−b, zamknięcie > L+b, kolejna świeca przebija high reclaim", "PASS", f"L={v.out(L):.2f}")
    return _done("SETUP", "OK", "warunki spełnione", cl, trigger_i=i, sl=ext - b, invalidation_pre_fill=ext,
                 structure={"L": L, "sweep_extreme": ext, "reclaim_i": r, "b": b}, structure_key=f"FBR:{round(L, 2)}")


# ================================================================================================== value area (HG08, SC10)
def value_area_rejection(X, vid, tf, mir, cfg) -> Det:
    cl: list = []
    v = X.tf(tf, mir)
    p = cfg.get("params") or {}
    w = _need(v, 30, cl, vid) or _ctx_range(X, mir, "M15", cl)
    if w:
        return w
    if vid == "PMW_HG08":
        r = _ctx_trend(X, mir, "H1", True, cl, reject_strong_against=True)
        if r:
            return r
    prof = X.prev_session_profile(float(p.get("value_area_pct", 0.70)), int(p.get("bin_ticks", 10)))
    if prof.get("status") not in ("READY",) or prof.get("val") is None:
        _cl(cl, "profile", "Profil poprzedniej sesji", "FAIL", prof.get("reason") or str(prof.get("status")))
        return _done("NO_DATA", "NO_PROFILE", f"profil poprzedniej sesji niedostępny: {prof.get('reason') or prof.get('status')}", cl)
    VAL, POC, VAH = (prof["val"], prof["poc"], prof["vah"]) if not mir else (-prof["vah"], -prof["poc"], -prof["val"])
    _cl(cl, "profile", "Profil poprzedniej sesji (zamrożony)", "PASS", f"VAL {prof['val']} POC {prof['poc']} VAH {prof['vah']} ({prof.get('volume_source')})")
    i = v.n - 1
    b = v.b(i, X.tick, X.cm)
    if b is None:
        return _done("WARMING_UP", "WARMING_UP", "rozgrzewka ATR", cl)
    r = i - 1
    if not (v.l[r] < VAL - b and v.c[r] > VAL + b and v.c[i] > v.h[r]):
        return _done("NO_SETUP", "NO_REJECTION", "brak odrzucenia VAL z potwierdzeniem", cl)
    if sum(1 for k in range(r - 3, r) if v.c[k] < VAL) >= 2:
        return _done("NO_SETUP", "ACCEPTED_BELOW", "dwa zamknięcia pod VAL przed wejściem – akceptacja poza obszarem", cl)
    _cl(cl, "reject", "Low < VAL−b, zamknięcie > VAL+b, następna świeca nad high", "PASS", "")
    return _done("SETUP", "OK", "warunki spełnione", cl, trigger_i=i, sl=v.l[r] - b, invalidation_pre_fill=v.l[r],
                 natural_targets=[POC, VAH], structure={"VAL": VAL, "POC": POC, "VAH": VAH, "profile_snapshot": prof.get("snapshot_id"),
                                                       "session": prof.get("session_start"), "volume_source": prof.get("volume_source"), "b": b},
                 structure_key=f"VA:{prof.get('session_start')}")


# ================================================================================================== SC07 BB + RSI reversion
def bb_rsi_reversion(X, vid, tf, mir, cfg) -> Det:
    cl: list = []
    v = X.tf(tf, mir)
    p = cfg.get("params") or {}
    w = _need(v, 60, cl, vid) or _ctx_range(X, mir, "M15", cl)
    if w:
        return w
    m5 = X.tf("M5", mir)
    ad5 = m5.adx()[m5.n - 1] if m5.n > 40 else None
    if ad5 is None:
        return _done("WARMING_UP", "WARMING_UP", "ADX M5: rozgrzewka", cl)
    if ad5 >= float(p.get("adx_m5_max", 20)):
        return _done("NO_SETUP", "ADX_HIGH", f"ADX M5 {ad5:.1f} ≥ 20", cl)
    i = v.n - 1
    mid, up, lo, _bw = v.bb()
    rs, b = v.rsi(), v.b(i, X.tick, X.cm)
    if _none(mid[i], lo[i - 1], rs[i], rs[i - 1], b):
        return _done("WARMING_UP", "WARMING_UP", "rozgrzewka BB/RSI", cl)
    lvl = float(p.get("rsi_level", 30))
    ok = v.l[i - 1] < lo[i - 1] and lo[i] < v.c[i] < up[i] and v.c[i] > v.h[i - 1] and min(x for x in rs[i - 2:i] if x is not None) <= lvl < rs[i]
    if not ok:
        return _done("NO_SETUP", "NO_TRIGGER", "brak powrotu do pasm z RSI z ≤30 na >30", cl)
    _cl(cl, "trigger", "Low t-1 < dolne pasmo, t wewnątrz pasm > high[t-1], RSI ≤30 → >30", "PASS", "")
    return _done("SETUP", "OK", "warunki spełnione", cl, trigger_i=i, sl=min(v.l[i - 1], v.l[i]) - b, invalidation_pre_fill=min(v.l[i - 1], v.l[i]),
                 natural_targets=[mid[i], up[i]], structure={"bb_mid": mid[i], "bb_up": up[i], "bb_lo": lo[i], "b": b}, structure_key=f"BBR:{i}")


# ================================================================================================== SC08 stochastic pullback
def stoch_pullback(X, vid, tf, mir, cfg) -> Det:
    cl: list = []
    v = X.tf(tf, mir)
    p = cfg.get("params") or {}
    w = _need(v, 120, cl, vid)
    if w:
        return w
    for ctx in ("M5", "M15"):
        r = _ctx_trend(X, mir, ctx, False, cl)
        if r:
            return r
    i = v.n - 1
    k, d = v.stoch()
    e50, b = v.ema(50), v.b(i, X.tick, X.cm)
    lb = int(p.get("lookback", 6))
    if _none(k[i], d[i], k[i - 1], d[i - 1], e50[i], b) or any(x is None for x in k[i - lb:i]):
        return _done("WARMING_UP", "WARMING_UP", "rozgrzewka stochastic/EMA50", cl)
    ok = min(k[i - lb:i]) < float(p.get("stoch_low", 20)) and k[i - 1] <= d[i - 1] and k[i] > d[i] and v.c[i] > v.h[i - 1] and v.c[i] > e50[i]
    if not ok:
        return _done("NO_SETUP", "NO_TRIGGER", "brak %K<20 i przecięcia %K/%D z potwierdzeniem ceny nad EMA50", cl)
    _cl(cl, "trigger", "%K<20 w korekcie, %K przecina %D w górę, close > high[t-1] i > EMA50", "PASS", "")
    low = min(v.l[i - lb:i + 1])
    return _done("SETUP", "OK", "warunki spełnione", cl, trigger_i=i, sl=low - b, invalidation_pre_fill=low - b,
                 structure={"ema50": e50[i], "correction_low": low, "b": b}, structure_key=f"STO:{round(low, 2)}")


# ================================================================================================== SC09 MACD momentum reset
def macd_reset(X, vid, tf, mir, cfg) -> Det:
    cl: list = []
    v = X.tf(tf, mir)
    w = _need(v, 120, cl, vid) or _ctx_trend(X, mir, "M15", False, cl)
    if w:
        return w
    i = v.n - 1
    line, hist = v.macd()
    e20, b = v.ema(20), v.b(i, X.tick, X.cm)
    if _none(e20[i], b) or any(x is None for x in line[i - 6:i + 1]) or any(x is None for x in hist[i - 6:i + 1]):
        return _done("WARMING_UP", "WARMING_UP", "rozgrzewka MACD", cl)
    ok = all(x > 0 for x in line[i - 2:i + 1]) and min(hist[i - 6:i]) <= 0 and hist[i - 1] <= 0 < hist[i] and v.c[i] > v.h[i - 1] and v.c[i] > e20[i]
    if not ok:
        return _done("NO_SETUP", "NO_TRIGGER", "brak resetu histogramu MACD przy linii > 0 z potwierdzeniem ceny", cl)
    _cl(cl, "trigger", "MACD > 0 (3 świece), histogram ≤0 → >0, close > high[t-1] i EMA20", "PASS", "")
    sw = [s for s in v.swings("L", i) if s["i"] >= i - 8]
    low = sw[-1]["price"] if sw else min(v.l[i - 6:i + 1])
    return _done("SETUP", "OK", "warunki spełnione", cl, trigger_i=i, sl=low - b, invalidation_pre_fill=low - b,
                 structure={"ema20": e20[i], "correction_low": low, "b": b}, structure_key=f"MACD:{round(low, 2)}")


# ================================================================================================== HG09 adaptive trend
def adaptive_trend(X, vid, tf, mir, cfg) -> Det:
    cl: list = []
    v = X.tf(tf, mir)
    p = cfg.get("params") or {}
    w = _need(v, 200, cl, vid) or _ctx_trend(X, mir, "H1", True, cl)
    if w:
        return w
    i = v.n - 1
    e20, e50, b = v.ema(20), v.ema(50), v.b(i, X.tick, X.cm)
    if _none(e20[i], e50[i], b):
        return _done("WARMING_UP", "WARMING_UP", "rozgrzewka EMA", cl)
    if not e20[i] > e50[i]:
        return _done("NO_SETUP", "NO_TREND", "EMA20 ≤ EMA50", cl)
    hi_k = max(range(i - 6, i), key=lambda k: v.h[k])
    age = i - hi_k
    sw = v.swings("L", i - 1)
    prot = sw[-1]["price"] if sw else None
    if not 2 <= age <= 5 or (prot is not None and any(v.c[k] < prot for k in range(hi_k, i + 1))):
        return _done("NO_SETUP", "NO_PULLBACK", "brak korekty 2–5 świec bez złamania swingu", cl)
    if not v.c[i] > max(v.h[i - 1], v.h[i - 2]) + b:
        return _done("NO_SETUP", "NO_TRIGGER", "brak zamknięcia nad maksimum dwóch świec + b", cl)
    m5 = X.tf("M5", mir)
    win = int(p.get("sigma_window", 60))
    method = p.get("volatility_method", "STD_LOGRET_60_M5")
    sg, how = F.vol_series(m5, method, window=win, garch=X.garch)
    if sg is None:
        _cl(cl, "vol", "Model zmienności", "FAIL", how)
        return _done("NO_DATA", "GARCH_NOT_READY", how, cl)
    j = m5.n - 1
    if j < win + 100 or sg[j] is None:
        return _done("WARMING_UP", "WARMING_UP", "σ M5: za mało historii", cl)
    hist = [x for x in sg[max(win, j - 2000):j] if x is not None]               # history available at t (bounded window)
    rank = sum(1 for x in hist if x < sg[j]) / len(hist)
    if rank >= float(p.get("sigma_extreme_pct", 0.95)):
        _cl(cl, "vol", "Reżim zmienności nie jest ekstremalny", "FAIL", f"percentyl {rank:.2f}")
        return _done("NO_SETUP", "VOL_EXTREME", f"zmienność ekstremalna (percentyl {rank:.2f})", cl)
    _cl(cl, "vol", "Reżim zmienności nie jest ekstremalny", "PASS", f"percentyl {rank:.2f}")
    low = min(v.l[k] for k in range(hi_k, i + 1))
    return _done("SETUP", "OK", "warunki spełnione", cl, trigger_i=i, sl=low - b, invalidation_pre_fill=low - b,
                 structure={"sigma_entry": sg[j], "sigma_method": method, "sigma_source": how, "sigma_rank": rank,
                            "garch": ({k: X.garch.get(k) for k in ("omega", "alpha", "beta", "run_id")} if method == "VOL_GARCH" else None),
                            "correction_low": low, "protected_swing": prot, "b": b}, structure_key=f"ADT:{round(low, 2)}")


DETECTORS = {
    "trend_pullback_ema": trend_pullback_ema, "breakout_retest": breakout_retest, "donchian_retest": donchian_retest,
    "opening_range": opening_range, "avwap_pullback": avwap_pullback, "vwap_reclaim": vwap_reclaim, "squeeze_break": squeeze_break,
    "squeeze_retest": squeeze_retest, "sweep_reclaim_sc": sweep_reclaim_sc, "sweep_reclaim_hg": sweep_reclaim_hg,
    "value_area_rejection": value_area_rejection, "bb_rsi_reversion": bb_rsi_reversion, "stoch_pullback": stoch_pullback,
    "macd_reset": macd_reset, "adaptive_trend": adaptive_trend,
}


def detect(X: F.Context, v: dict, tf: str, side: str) -> Det:
    """Run variant `v` on TF `tf` for `side` (SELL = mirrored view). Any exception = NO_DATA with the reason (never a signal)."""
    try:
        return DETECTORS[v["detector"]](X, v["strategy_id"], tf, side == "SELL", v)
    except (IndexError, ValueError, ZeroDivisionError) as exc:
        return Det(status="NO_DATA", reason_code="DETECTOR_DATA", reason=f"{type(exc).__name__}: {exc}"[:160], checklist=[])
