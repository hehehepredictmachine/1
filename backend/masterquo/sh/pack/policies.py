"""Hedge management policies of PMW_HG01..HG10 on top of the existing basket state machine (sh/hedge_fsm.Basket).

Every policy is evaluated on the CLOSED M5 bars after the actual fill of the base position (plus the executable quote for adverse / MFE
excursions), in the base position's VIEW (SELL bases use the mirrored M5, exactly like the entry rules). Event priority (the service
applies it in this order): STOP / reconciliation / limits -> hard SL or structure invalidation (whole basket out, never a hedge after it)
-> confirmed fills -> hedge reduction / close (unwind, timeout, ratio cap after a partial) -> only then a new activation.
One hedge per basket, at most one activation in its life (a candle change never resets it; a rejected / UNKNOWN hedge consumes it), ratio
0.25 or 0.50 of the CURRENT base volume (rounded down), never more than 0.50, never increased after an adverse move. Hedge timeout without
the return condition = exit of the whole basket.

decision(...) -> {"decision": HOLD|HEDGE|UNWIND|EXIT, "reason", "ratio", "progress"}; the policy state (MFE, armed flags, counters) is a
plain dict persisted with the basket (Basket.policy) so a restart continues the same policy.
"""
from __future__ import annotations

from . import features as F

TEXT = {
    "PMW_HG01": ("niekorzystny ruch ≥ 0,5r od fillu i dwa zamknięcia M5 < EMA20−b przy ważnym trendzie H1 i swingu → SELL 0,50",
                 "zamknięcie M5 > EMA20+b i > high poprzedniej M5"),
    "PMW_HG02": ("zamknięcie M5 < L−b, a następne < L, przy cenie nad unieważnieniem → SELL 0,50 (gdy ostrzeżenie pokrywa się z SL: EXIT)",
                 "zamknięcie > L+b i kolejna świeca utrzymuje L"),
    "PMW_HG03": ("dwa zamknięcia M5 < środek kanału−b przy ważnym H1 i swingu → SELL 0,25 (gdy środek poniżej SL – aktywacja niedozwolona)",
                 "dwa zamknięcia M5 > środek+b"),
    "PMW_HG04": ("zamknięcie M5 < OR_high−b, potem zamknięcie < środek OR, nadal nad SL → SELL 0,50", "zamknięcie > OR_high+b"),
    "PMW_HG05": ("dwa zamknięcia M5 < AVWAP−b przy ważnym H1/swingu → SELL 0,50 (kotwica niezmienna w koszyku)", "dwa zamknięcia M5 > AVWAP+b"),
    "PMW_HG06": ("dwa zamknięcia M5 pod poziomem wybicia, korpus ostatniej przeciw bazie > 0,8 ATR14, minimum kompresji ważne → SELL 0,50",
                 "zamknięcie > poziom wybicia+b i > high poprzedniej świecy"),
    "PMW_HG07": ("zamknięcie < L−b i kolejne < L, nad ekstremum sweepu → SELL 0,25 (strefa L–SL zbyt wąska na koszty: EXIT)", "zamknięcie > L+b"),
    "PMW_HG08": ("dwa zamknięcia M5 < VAL−b przy ważnym SL → SELL 0,25 (ostrzeżenie o akceptacji, nie dowód zmiany wolumenu)", "zamknięcie > VAL+b"),
    "PMW_HG09": ("σ_teraz/σ_wejście ≥ 1,5 i przeciwna M5 > 0,5 ATR przy ważnej strukturze → jednorazowo ratio = clip(1−σ_wejście/σ_teraz; 0,25; 0,50)",
                 "3 kolejne M5 z σ-ratio ≤ 1,2 i zamknięciem po korzystnej stronie EMA20"),
    "PMW_HG10": ("MFE ≥ 1,5r, potem oddanie ≥ 0,5r od najlepszego poziomu i zamknięcie M5 < EMA9 → SELL 0,50 pozostałej bazy",
                 "zamknięcie > EMA9+b i ponad zamrożone lokalne maksimum sprzed korekty"),
}
SCALAR = {"PMW_HG02": "L", "PMW_HG03": "mid", "PMW_HG04": "or_mid", "PMW_HG06": "break_level", "PMW_HG07": "L", "PMW_HG08": "VAL"}


def texts(vid: str) -> dict:
    a, u = TEXT[vid]
    return {"activation_condition": a, "unwind_condition": u}


def activation_level_view(vid: str, st: dict, b5: float) -> float | None:
    """Scalar activation threshold (view units) when the condition IS a price line; dynamic conditions (EMA, AVWAP, σ, giveback) -> None,
    the chart then shows the condition and its progress instead of a misleading line."""
    k = SCALAR.get(vid)
    if not k or st.get(k) is None:
        return None
    return st[k] if vid in ("PMW_HG04", "PMW_HG06") else st[k] - b5


def hedge_loss_bound(vid: str, st: dict, *, r: float, b5: float, c: float, ratio: float, hcfg: dict, fam: dict) -> tuple[float | None, str]:
    """Bounded hedge loss per unit of base volume in the paths that still reach the targets (hedge entered at the activation side,
    closed at the unwind side) - a MODELLED scenario bound: ratio x (gap + C). None = not estimable (RR_NOT_ESTIMABLE)."""
    ov = float(fam.get("scenario_unwind_overshoot_r", 0.25)) * r
    if vid in ("PMW_HG02", "PMW_HG03", "PMW_HG07", "PMW_HG08", "PMW_HG01", "PMW_HG05", "PMW_HG06"):
        gap, how = 2 * b5 + ov, "aktywacja po stronie poziom−b, powrót po stronie poziom+b (+ zapas przestrzelenia)"
    elif vid == "PMW_HG04":
        if st.get("or_high") is None or st.get("or_mid") is None:
            return None, "brak zamrożonego OR"
        gap, how = (st["or_high"] + b5) - st["or_mid"] + ov, "aktywacja pod środkiem OR, powrót nad OR_high+b"
    elif vid in ("PMW_HG09", "PMW_HG10"):
        g = hcfg.get("scenario_unwind_gap_r")
        if g is None:
            return None, "polityka bez skalarnego poziomu i bez skonfigurowanego ograniczenia scenariusza"
        gap, how = float(g) * r, f"warunek dynamiczny – modelowe ograniczenie luki {g} r (parametr scenariusza)"
    else:
        return None, "nieznana polityka"
    return ratio * (gap + c), how


def _closes_after(v: F.TF, t_fill: float) -> list[int]:
    return [i for i in range(v.n) if v.t[i] >= t_fill - 1e-6]


def decision(vid: str, *, plan: dict, st: dict, pstate: dict, m5_bars: list[dict], h1_bars: list[dict], quote: dict, now: float,
             primary: dict, hedged: bool, hedge_opened_at: float | None, activations: int, tick: float, common: dict) -> dict:
    """primary: {side, entry (fill), sl, remaining, volume, opened_at}. Returns the policy decision; never sizes beyond ratio x remaining."""
    side = primary["side"]
    mir = side == "SELL"
    v = F.TF("M5", m5_bars, mirror=mir)
    hc = plan["pack"]["hedge"] or {}
    sg = -1.0 if mir else 1.0
    E, S = sg * primary["entry"], sg * primary["sl"]
    r = max(E - S, tick)
    px = sg * (quote["bid"] if side == "BUY" else quote["ask"])            # executable closing side of the base, in the view
    pstate["mfe"] = max(pstate.get("mfe", 0.0), (px - E) / r)
    pstate["best"] = max(pstate.get("best", px), px)
    pstate["max_adverse"] = max(pstate.get("max_adverse", 0.0), (E - px) / r)
    idx = _closes_after(v, primary["opened_at"])
    i = v.n - 1
    b5 = v.b(i, tick, common) if v.n else None
    if not idx or b5 is None:
        return {"decision": "HOLD", "reason": "czekam na zamknięte M5 po wejściu", "progress": None}
    # ---- hedge open: timeout first, then the return (unwind) condition
    if hedged:
        mx = float(hc.get("max_hedge_minutes", 30))
        if hedge_opened_at is not None and now - hedge_opened_at >= 60 * mx:
            return {"decision": "EXIT", "reason": f"limit czasu hedge {mx:.0f} min bez warunku powrotu – wyjście całego koszyka"}
        after = [k for k in idx if v.t[k] >= (hedge_opened_at or 0) - 1e-6]
        u = _unwind(vid, v, after, st, b5, pstate, plan)
        return {"decision": "UNWIND", "reason": u} if u else {"decision": "HOLD", "reason": "hedge aktywny – warunek powrotu niespełniony"}
    if activations >= 1:
        return {"decision": "HOLD", "reason": "wykorzystano jedyną aktywację hedge w życiu koszyka"}
    # ---- activation (never after a hard invalidation: the basket's own exit runs before this)
    if px <= S:
        return {"decision": "HOLD", "reason": "cena na/za SL – twarde wyjście, nie hedge"}
    h1 = F.TF("H1", h1_bars, mirror=mir)
    h1_ok = F.trend_up(h1, h1.n - 1, True) if h1.n > 200 else None
    act = _activate(vid, v, idx, st, b5, pstate, plan, E, S, r, px, h1_ok)
    if act is None:
        return {"decision": "HOLD", "reason": "warunek aktywacji niespełniony", "progress": pstate.get("progress")}
    if act.get("decision") == "EXIT":
        return act
    return {"decision": "HEDGE", "reason": act["reason"], "ratio": min(float(act["ratio"]), 0.5)}


def _two_below(v, idx, level_fn, n: int = 2) -> bool:
    if len(idx) < n:
        return False
    return all(v.c[k] < level_fn(k) for k in idx[-n:])


def _activate(vid, v: F.TF, idx, st, b5, ps, plan, E, S, r, px, h1_ok):
    hc = plan["pack"]["hedge"] or {}
    i = idx[-1]
    ratio = float(hc.get("ratio", 0.5))
    cost = float(plan["pack"]["economics"].get("c_round_trip") or 0.0)
    if vid in ("PMW_HG01",):
        e20 = v.ema(20)
        ps["progress"] = f"MAE {ps.get('max_adverse', 0):.2f}r / 0,5r"
        if ps.get("max_adverse", 0) >= float(hc.get("adverse_min_r", 0.5)) and h1_ok is not False and \
                _two_below(v, idx, lambda k: (e20[k] or 0) - b5, int(hc.get("confirm_closes", 2))):
            return {"reason": "korekta: dwa zamknięcia M5 pod EMA20−b po niekorzystnym ruchu ≥ 0,5r", "ratio": ratio}
    elif vid in ("PMW_HG02", "PMW_HG07"):
        L = st["L"]
        if vid == "PMW_HG02" and (L - b5) - S <= 2 * cost:
            if len(idx) >= 2 and v.c[idx[-2]] < L - b5 and v.c[i] < L:
                return {"decision": "EXIT", "reason": "ostrzeżenie (utrata L) pokrywa się z unieważnieniem – EXIT zamiast hedge"}
            return None
        if vid == "PMW_HG07" and ((L - b5) - S) < 2 * cost:
            if len(idx) >= 2 and v.c[idx[-2]] < L - b5 and v.c[i] < L:
                return {"decision": "EXIT", "reason": "strefa między L a SL zbyt wąska na koszty – EXIT zamiast hedge"}
            return None
        if vid == "PMW_HG07" and px <= st.get("sweep_extreme", S):
            return None
        if len(idx) >= 2 and v.c[idx[-2]] < L - b5 and v.c[i] < L:
            return {"reason": f"utrata poziomu L {('(odzyskanego)' if vid == 'PMW_HG07' else '')}: zamknięcie < L−b i potwierdzenie < L", "ratio": ratio}
    elif vid == "PMW_HG03":
        M = st["mid"]
        if M - b5 <= S or h1_ok is False:
            return None
        if _two_below(v, idx, lambda k: M - b5, int(hc.get("confirm_closes", 2))):
            return {"reason": "dwa zamknięcia M5 pod środkiem zamrożonego kanału − b", "ratio": ratio}
    elif vid == "PMW_HG04":
        if any(v.c[k] < st["or_high"] - b5 for k in idx):
            ps["armed"] = True
        if ps.get("armed") and v.c[i] < st["or_mid"] and px > S:
            return {"reason": "powrót pod OR_high−b, potem zamknięcie pod środkiem OR", "ratio": ratio}
    elif vid == "PMW_HG05":
        anc = F.ts(st["anchor"])
        vw = v.vwap(anc)
        if h1_ok is not False and vw[i] is not None and _two_below(v, idx, lambda k: (vw[k] if vw[k] is not None else -1e18) - b5,
                                                                    int(hc.get("confirm_closes", 2))):
            return {"reason": "dwa zamknięcia M5 pod AVWAP−b (kotwica niezmieniona)", "ratio": ratio}
    elif vid == "PMW_HG06":
        a = v.atr()
        BL, comp = st["break_level"], st.get("compression_low")
        if len(idx) >= 2 and all(v.c[k] < BL for k in idx[-2:]) and a[i] and (v.o[i] - v.c[i]) > float(hc.get("body_atr", 0.8)) * a[i] \
                and (comp is None or px > comp):
            return {"reason": "dwa zamknięcia pod poziomem wybicia z korpusem > 0,8 ATR (wygasanie impulsu)", "ratio": ratio}
    elif vid == "PMW_HG08":
        if _two_below(v, idx, lambda k: st["VAL"] - b5, int(hc.get("confirm_closes", 2))):
            return {"reason": "dwa zamknięcia M5 pod VAL−b (akceptacja poza obszarem wartości)", "ratio": ratio}
    elif vid == "PMW_HG09":
        sg = _hg09_sigma(v, st, plan)
        a = v.atr()
        se, sn = st.get("sigma_entry"), sg[i]
        if se and sn and a[i]:
            ps["progress"] = f"σ-ratio {sn / se:.2f} / {hc.get('sigma_ratio_on', 1.5)}"
            if sn / se >= float(hc.get("sigma_ratio_on", 1.5)) and v.c[i] < v.c[i - 1] and abs(v.c[i] - v.c[i - 1]) > float(hc.get("move_atr", 0.5)) * a[i]:
                rt = min(max(1 - se / sn, float(hc.get("ratio_min", 0.25))), float(hc.get("ratio_max", 0.5)))
                return {"reason": f"skok zmienności σ×{sn / se:.2f} i przeciwna świeca > 0,5 ATR", "ratio": rt}
    elif vid == "PMW_HG10":
        e9 = v.ema(9)
        ps["progress"] = f"MFE {ps.get('mfe', 0):.2f}r / {hc.get('mfe_min_r', 1.5)}r"
        if ps.get("mfe", 0) >= float(hc.get("mfe_min_r", 1.5)):
            give = (ps["best"] - px) / r
            ps["progress"] = f"oddanie {give:.2f}r / {hc.get('giveback_r', 0.5)}r"
            if give >= float(hc.get("giveback_r", 0.5)) and e9[i] is not None and v.c[i] < e9[i]:
                return {"reason": f"MFE ≥ 1,5r, oddanie {give:.2f}r i zamknięcie M5 pod EMA9", "ratio": ratio}
    return None


def _unwind(vid, v: F.TF, after, st, b5, ps, plan) -> str | None:
    if not after:
        return None
    i = after[-1]
    if vid == "PMW_HG01":
        e20 = v.ema(20)
        return "zamknięcie M5 > EMA20+b i > high poprzedniej" if e20[i] is not None and v.c[i] > e20[i] + b5 and v.c[i] > v.h[i - 1] else None
    if vid == "PMW_HG02":
        L = st["L"]
        return "reclaim L+b i utrzymanie L" if len(after) >= 2 and v.c[after[-2]] > L + b5 and v.c[i] > L else None
    if vid == "PMW_HG03":
        M = st["mid"]
        return "dwa zamknięcia M5 nad środkiem+b" if len(after) >= 2 and all(v.c[k] > M + b5 for k in after[-2:]) else None
    if vid == "PMW_HG04":
        return "reclaim OR_high+b" if v.c[i] > st["or_high"] + b5 else None
    if vid == "PMW_HG05":
        vw = v.vwap(F.ts(st["anchor"]))
        return "dwa zamknięcia M5 nad AVWAP+b" if len(after) >= 2 and all(vw[k] is not None and v.c[k] > vw[k] + b5 for k in after[-2:]) else None
    if vid == "PMW_HG06":
        return "zamknięcie nad poziomem wybicia+b i high poprzedniej" if v.c[i] > st["break_level"] + b5 and v.c[i] > v.h[i - 1] else None
    if vid == "PMW_HG07":
        return "zamknięcie > L+b" if v.c[i] > st["L"] + b5 else None
    if vid == "PMW_HG08":
        return "zamknięcie > VAL+b" if v.c[i] > st["VAL"] + b5 else None
    if vid == "PMW_HG09":
        hc = plan["pack"]["hedge"] or {}
        sg = _hg09_sigma(v, st, plan)
        e20 = v.ema(20)
        se = st.get("sigma_entry")
        n = int(hc.get("off_bars", 3))
        if se and len(after) >= n and all(sg[k] and sg[k] / se <= float(hc.get("sigma_ratio_off", 1.2)) and e20[k] is not None and v.c[k] > e20[k]
                                          for k in after[-n:]):
            return "3 kolejne M5 z σ-ratio ≤ 1,2 i zamknięciem nad EMA20"
        return None
    if vid == "PMW_HG10":
        e9 = v.ema(9)
        pre = st.get("pre_correction_high")
        return "zamknięcie > EMA9+b i ponad lokalne maksimum sprzed korekty" if e9[i] is not None and v.c[i] > e9[i] + b5 and pre is not None and v.c[i] > pre else None
    return None


def _hg09_sigma(v: F.TF, st: dict, plan: dict) -> list:
    """The SAME volatility method the entry used (frozen in the plan): GARCH with the frozen artifact parameters, else std of log returns."""
    g = st.get("garch") if st.get("sigma_method") == "VOL_GARCH" else None
    if g:
        return v.garch_sigma(float(g["omega"]), float(g["alpha"]), float(g["beta"]))
    return v.sigma(int((plan["pack"].get("params") or {}).get("sigma_window", 60)))
