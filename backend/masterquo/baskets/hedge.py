"""The 20 hedge planners (FX_HEDGE / CP_HEDGE; OTC_HEDGE retired). A planner works only on EXISTING, identified exposure; without it the
result is NO_EXPOSURE (not an error). It may correctly return NO_HEDGE with the computed reason. It never opens a pair of opposite
positions to look "active", never uses martingale / grids / doubling, never moves the parent SL, never raises leverage.

planner(ctx) -> {"state": NO_EXPOSURE | NO_HEDGE | HEDGE_PLAN | WAITING_FOR_DATA | UNSUPPORTED_EXECUTION, "reason", "plan"?}
ctx: {"strategy": catalog entry, "p": parameters, "exposure": [...], "F": Feat of the signal TF (own instrument), "feats": {symbol: Feat},
      "bars": {symbol: {tf: bars}}, "account": {...}, "spec": {symbol: meta}, "events": [...] | None, "now": t}
"""
from __future__ import annotations

import math

import numpy as np

from . import detectors as D
from .rules import Unavailable


def _plan(parent, legs, *, ratio, risk_before, risk_after, cost, residual, exit_rule, timeout, action="HEDGE", extra=None):
    return {"plan_type": "HedgePlan", "action_type": action, "parent": parent, "legs": legs, "coverage_ratio": ratio, "risk_before": risk_before,
            "risk_after": risk_after, "protection_cost": cost, "residual_exposure": residual, "exit_rule": exit_rule, "timeout_bars": timeout,
            "on_leg_failure": "druga noga nie jest atomowa: brak wykonania = brak ochrony, rodzic z własnym SL pozostaje; bez ponawiania w ciemno",
            "parent_sl": "aktywny (niezmieniony)", **(extra or {})}


def _round_vol(v: float, step: float, vmin: float) -> float | None:
    if step <= 0:
        return None
    q = math.floor(v / step + 1e-9) * step
    return round(q, 8) if q >= vmin - 1e-12 else None


# ============================================================================ FX (MT5)
def _fx_parent(ctx, side_needed: str | None = None):
    exp = [e for e in ctx.get("exposure") or [] if e.get("leg") == "PRIMARY"]
    if not exp:
        return None
    sym = ctx.get("symbol")
    # 1.46 (I0762): only the context symbol's own positions - a position on another symbol was taken as the parent and judged on the
    # candles of the chart symbol (and the default volume step); without one the planner reports NO_EXPOSURE
    own = [e for e in exp if e.get("symbol") == sym]
    if not own:
        return None
    if side_needed:
        own = [e for e in own if e["side"] == side_needed] or own
    return own[0]


def _layers_used(ctx, parent) -> int:
    """1.46 (I0763): protection layers the parent already has - open HEDGE legs of the same plan id in the exposure (SH hedge legs carry
    the parent's plan id) + recent PROPOSED hedge plans for it: ctx['layers_used'] = {parent_id: n}, counted read-only by the basket
    service (an int from a direct caller = the count of this parent)."""
    pid = parent.get("id")
    legs = sum(1 for e in ctx.get("exposure") or [] if e.get("leg") == "HEDGE" and pid is not None and e.get("id") == pid)
    lu = ctx.get("layers_used")
    proposed = lu.get(pid, 0) if isinstance(lu, dict) else (lu or 0)
    return legs + int(proposed)


def _layers_full(ctx, parent, reason_trigger: str):
    """NO_HEDGE when the parent's protection layers reached p['max_layers'] (catalog default 1) - checked only where a HEDGE_PLAN would
    be returned (the triggers and the other NO_HEDGE answers are unchanged)."""
    mx = int(ctx["p"].get("max_layers", 1))
    n = _layers_used(ctx, parent)
    if n >= mx:
        return {"state": "NO_HEDGE", "reason": f"{reason_trigger}; limit warstw ochrony (max_layers={mx}) wyczerpany – rodzic ma już {n}"}
    return None


def _fx_same_symbol(ctx, parent, reason_trigger: str, extra=None):
    acc = ctx.get("account") or {}
    spec = (ctx.get("spec") or {}).get(parent["symbol"]) or {}
    ratio = float(ctx["p"].get("ratio", 0.5))
    step, vmin = float(spec.get("volume_step") or 0.01), float(spec.get("volume_min") or 0.01)
    vol = _round_vol(ratio * float(parent["volume"]), step, vmin)
    side = "SHORT" if parent["side"] == "LONG" else "LONG"
    F = ctx["F"]
    px = float(F.c[F.i])
    cs = float(spec.get("trade_contract_size") or 0) or None
    if vol is None:
        return {"state": "NO_HEDGE", "reason": f"{reason_trigger}; ilość {ratio:.0%} rodzica poniżej minimalnego wolumenu"}
    sens_parent = float(parent["volume"]) * (cs or 1.0)
    legs = [{"instrument": parent["symbol"], "side": side, "volume": vol, "unit": "lots", "price_ref": px}]
    # 1.46: no bid/ask (spread_price None) was shown as a 0.0 cost; spread x volume x contract size is in the QUOTE currency (JPY for
    # EURJPY), not "money" -> account currency via tick value / tick size, otherwise None with the reason and the quote-currency amount
    sp = spec.get("spread_price")
    tv, ts = float(spec.get("trade_tick_value") or 0), float(spec.get("trade_tick_size") or 0)
    if sp is None:
        cost = {"spread_money": None, "reason": "NO_QUOTE: brak bid/ask – koszt spreadu nieznany"}
    elif tv > 0 and ts > 0:
        cost = {"spread_money": float(sp) / ts * tv * vol, "currency": acc.get("currency")}
    else:
        cost = {"spread_money": None, "reason": "NO_TICK_VALUE: brak wartości ticka – koszt w walucie konta nieznany",
                "spread_quote_ccy": float(sp) * vol * cs if cs else None, "quote_currency": spec.get("currency_profit")}
    plan = _plan({"id": parent["id"], "engine": parent.get("engine"), "side": parent["side"], "volume": parent["volume"]}, legs, ratio=ratio,
                 risk_before={"net_units": sens_parent}, risk_after={"net_units": sens_parent - vol * (cs or 1.0), "gross_units": sens_parent + vol * (cs or 1.0)},
                 cost={**cost, "note": "koszt spreadu wejścia; margin drugiej nogi nie jest zakładany jako zero"},
                 residual=1 - vol / float(parent["volume"]), exit_rule=ctx["strategy"]["exit_policy_or_expiry_policy"], timeout=int(ctx["p"].get("timeout_bars", 6)),
                 extra=extra)
    if acc.get("margin_mode") != "HEDGING":
        plan["action_type"] = "REDUCE"
        return {"state": "NO_HEDGE", "reason": f"{reason_trigger}; rachunek {acc.get('margin_mode') or 'nieznany'} – przeciwna transakcja zmniejszy pozycję "
                "(alternatywa REDUCE, nie hedge)", "alternative": plan}
    full = _layers_full(ctx, parent, reason_trigger)              # 1.46 (I0763): max_layers was never checked by the FX planners
    if full:
        return full
    return {"state": "HEDGE_PLAN", "reason": reason_trigger, "plan": plan}


def structural_choch(ctx):
    par = _fx_parent(ctx)
    if not par:
        return {"state": "NO_EXPOSURE"}
    F, H = ctx["F"], ctx.get("htf")
    s = 1 if par["side"] == "LONG" else -1
    if H is None:
        raise Unavailable("brak H1")
    ch = F.last_break(F.i, -s, 2, kinds=("CHOCH",))
    if not ch or H.trend()[0] != s:
        return {"state": "NO_HEDGE", "reason": "brak przeciwnego CHoCH M5 przy zgodnym H1"}
    return _fx_same_symbol(ctx, par, f"przeciwny CHoCH M5 @ {ch['level']:.5g}, H1 nadal zgodny z rodzicem")


def range_profit(ctx):
    par = _fx_parent(ctx)
    if not par:
        return {"state": "NO_EXPOSURE"}
    F, H = ctx["F"], ctx.get("htf")
    s = 1 if par["side"] == "LONG" else -1
    px = float(F.c[F.i])
    if par.get("entry") is None or (px - float(par["entry"])) * s <= 0:
        return {"state": "NO_HEDGE", "reason": "rodzic bez bieżącego zysku"}
    if H is None:
        raise Unavailable("brak M15")
    res = H.swings(H.i, "H" if s > 0 else "L", 1)
    if not res:
        return {"state": "NO_HEDGE", "reason": "brak znanego oporu"}
    lvl = res[-1].price
    if not (F.sweep(F.i, lvl, -s) or F.sweep(F.i - 1, lvl, -s)):
        return {"state": "NO_HEDGE", "reason": "brak sweepu i odrzucenia przy oporze"}
    return _fx_same_symbol(ctx, par, f"sweep oporu {lvl:.5g} z odrzuceniem przy zysku rodzica", extra={"own_invalidation": float(F.h[F.i] if s > 0 else F.l[F.i])})


def _shock(F, i, pct, lookback):
    rng = F.h - F.l
    pr = F.pct_rank_before(rng, i, lookback)
    return pr is not None and pr >= pct


def vol_shock(ctx):
    par = _fx_parent(ctx)
    if not par:
        return {"state": "NO_EXPOSURE"}
    F = ctx["F"]
    s = 1 if par["side"] == "LONG" else -1
    p = ctx["p"]
    if not _shock(F, F.i, float(p.get("pct", 0.95)), int(p.get("lookback", 200))):
        return {"state": "NO_HEDGE", "reason": "zakres M1 poniżej 95. percentyla 200 poprzednich"}
    if not (F.bear(F.i) if s > 0 else F.bull(F.i)):
        return {"state": "NO_HEDGE", "reason": "zamknięcie nie jest przeciw rodzicowi"}
    if _layers_used(ctx, par) >= 1:                                # 1.46 (I0763): layers_used was never supplied - counted per parent now
        return {"state": "NO_HEDGE", "reason": "jednorazowy hedge już przygotowany – bez kolejnej warstwy (max_layers)"}
    return _fx_same_symbol(ctx, par, "szok zmienności przeciw rodzicowi")


def session_transition(ctx):
    par = _fx_parent(ctx)
    if not par:
        return {"state": "NO_EXPOSURE"}
    F = ctx["F"]
    from .rules import _session_anchor
    near = False
    for tz, hh in (("Europe/London", "08:00"), ("America/New_York", "08:00"), ("Asia/Tokyo", "09:00")):
        a = _session_anchor(F.t[F.i], tz, hh)
        if 0 <= F.t[F.i] - a <= 900:
            near = True
    if not near:
        return {"state": "NO_HEDGE", "reason": "poza oknem zmiany sesji"}
    spec = (ctx.get("spec") or {}).get(par["symbol"]) or {}
    sp, sp_med = spec.get("spread_price"), spec.get("spread_median_price")
    if sp is None or sp_med is None:
        raise Unavailable("brak bieżącego i referencyjnego spreadu")
    a = F.A()
    if sp < float(ctx["p"].get("spread_mult", 2.0)) * sp_med and not (a and F.h[F.i] - F.l[F.i] > 2 * a):
        return {"state": "NO_HEDGE", "reason": "spread i zmienność w normie"}
    return _fx_same_symbol(ctx, par, "zmiana sesji ze wzrostem spreadu / zmienności")


def mtf_countermove(ctx):
    par = _fx_parent(ctx)
    if not par:
        return {"state": "NO_EXPOSURE"}
    F, H = ctx["F"], ctx.get("htf")
    s = 1 if par["side"] == "LONG" else -1
    if H is None:
        raise Unavailable("brak H1")
    if H.trend()[0] != s:
        return {"state": "NO_HEDGE", "reason": "H1 nie utrzymuje kierunku rodzica"}
    hs, ls = F.swings(F.i, "H", 3), F.swings(F.i, "L", 3)
    if len(hs) < 3 or len(ls) < 3:
        return {"state": "NO_HEDGE", "reason": "za mało swingów M5"}
    against = (hs[2].price < hs[1].price < hs[0].price and ls[2].price < ls[1].price < ls[0].price) if s > 0 else \
              (hs[2].price > hs[1].price > hs[0].price and ls[2].price > ls[1].price > ls[0].price)
    if not against:
        return {"state": "NO_HEDGE", "reason": "brak dwóch przeciwnych sekwencji swingów M5"}
    lvl = ls[-1].price if s > 0 else hs[-1].price
    b = F.b()
    if not F.touched(F.i, lvl - b, lvl + b):
        return {"state": "NO_HEDGE", "reason": "brak retestu"}
    return _fx_same_symbol(ctx, par, "korekta M5 przeciw rodzicowi przy zgodnym H1")


def event_shield(ctx):
    par = _fx_parent(ctx)
    if not par:
        return {"state": "NO_EXPOSURE"}
    ev = ctx.get("events")
    if ev is None:
        raise Unavailable("brak kalendarza wydarzeń – reguła wyłączona (tylko ta)")
    now = ctx["now"]
    soon = [e for e in ev if 0 <= float(e["t"]) - now <= 60 * float(ctx["p"].get("before_min", 5)) and par["symbol"][:6].find(str(e.get("currency") or "?")) >= 0]
    if not soon:
        return {"state": "NO_HEDGE", "reason": "brak wydarzenia dla instrumentu w oknie 5 min"}
    return _fx_same_symbol(ctx, par, f"wydarzenie: {soon[0].get('title')}")


def _ccy_exposure(exp, spec):
    out = {}
    for e in exp:
        sym = e["symbol"].rstrip("-.").upper()[:6]
        if len(sym) < 6 or not sym.isalpha():
            continue
        cs = float(((spec or {}).get(e["symbol"]) or {}).get("trade_contract_size") or 100000)
        px = float(e.get("price") or e.get("entry") or 0) or None
        if px is None:
            continue
        sg = 1 if e["side"] == "LONG" else -1
        base, quote = sym[:3], sym[3:]
        out[base] = out.get(base, 0.0) + sg * float(e["volume"]) * cs
        out[quote] = out.get(quote, 0.0) - sg * float(e["volume"]) * cs * px
    return out


def currency_factor(ctx):
    exp = [e for e in ctx.get("exposure") or [] if e.get("leg") == "PRIMARY"]
    if not exp:
        return {"state": "NO_EXPOSURE"}
    lim = ctx["p"].get("limit_ccy_notional")
    ex = _ccy_exposure(exp, ctx.get("spec"))
    if lim is None:
        return {"state": "NO_HEDGE", "reason": "limit ekspozycji walutowej nieskonfigurowany", "currency_exposure": ex}
    over = {c: v for c, v in ex.items() if abs(v) > float(lim)}
    if not over:
        return {"state": "NO_HEDGE", "reason": "ekspozycje walutowe w limicie", "currency_exposure": ex}
    c, v = max(over.items(), key=lambda kv: abs(kv[1]))
    pairs = [p for p in ctx.get("fx_pairs") or [] if c in p[:6]]
    if not pairs:
        raise Unavailable(f"brak dostępnej pary FX z walutą {c} w Market Watch")
    pair = pairs[0]
    side = ("SHORT" if v > 0 else "LONG") if pair.startswith(c) else ("LONG" if v > 0 else "SHORT")
    excess = abs(v) - float(lim)
    return {"state": "HEDGE_PLAN", "reason": f"ekspozycja {c} {v:,.0f} > limit {lim}",
            "plan": _plan({"currency": c, "exposure": v}, [{"instrument": pair, "side": side, "notional_ccy": excess, "unit": c}], ratio=excess / abs(v),
                          risk_before={c: v}, risk_after={c: math.copysign(float(lim), v)}, cost=None, residual=None, exit_rule="powrót do limitu",
                          timeout=int(ctx["p"].get("timeout_bars", 6)), extra={"note": "neutralizacja czynnika waluty to nie pełny hedge pozostałych ryzyk"})}


def _beta_core(ctx, parent_bars, hedge_bars, p):
    rx, rh = D.sync_returns(parent_bars, hedge_bars, int(p.get("window", 120)))
    b1 = D.beta(rx, rh)
    rx2, rh2 = D.sync_returns(parent_bars, hedge_bars, int(p.get("window2", 60)))
    b2 = D.beta(rx2, rh2)
    ok = b1["beta"] is not None and b2["beta"] is not None and b1["beta"] > 0 and b2["beta"] > 0 and (b1["corr"] or 0) >= float(p.get("corr_min", 0.5))
    return ok, b1, b2


def _beta_hedge(ctx, partner: str | None):
    par = _fx_parent(ctx)
    if not par:
        return {"state": "NO_EXPOSURE"}
    if not partner:
        return {"state": "NO_HEDGE", "reason": "para porównawcza nieskonfigurowana"}
    bars = ctx.get("bars") or {}
    pb, hb = (bars.get(par["symbol"]) or {}).get("M15"), (bars.get(partner) or {}).get("M15")
    if not hb:
        raise Unavailable(f"{partner} niedostępny w terminalu")
    if not pb:
        raise Unavailable("brak M15 rodzica")
    ok, b1, b2 = _beta_core(ctx, pb, hb, ctx["p"])
    if not ok:
        return {"state": "NO_HEDGE", "reason": "relacja niestabilna (beta ≤ 0 w jednym z okien lub korelacja < 0.5)", "beta_120": b1, "beta_60": b2}
    spec = ctx.get("spec") or {}
    cs_p = float((spec.get(par["symbol"]) or {}).get("trade_contract_size") or 0)
    cs_h = float((spec.get(partner) or {}).get("trade_contract_size") or 0)
    if not cs_p or not cs_h:
        raise Unavailable("brak contract size do przeliczenia ilości")
    px_p, px_h = float(pb[-1]["c"]), float(hb[-1]["c"])
    sgn = 1 if par["side"] == "LONG" else -1
    parent_notional = sgn * float(par["volume"]) * cs_p * px_p
    ratio = float(ctx["p"].get("ratio", 0.5))
    hn = -ratio * b1["beta"] * parent_notional                                    # spec 9.1
    hs = (spec.get(partner) or {})
    vol = _round_vol(abs(hn) / (cs_h * px_h), float(hs.get("volume_step") or 0.01), float(hs.get("volume_min") or 0.01))
    if vol is None:
        return {"state": "NO_HEDGE", "reason": "ilość z bety poniżej minimalnego wolumenu partnera", "hedge_notional": hn}
    leg = {"instrument": partner, "side": "SHORT" if hn < 0 else "LONG", "volume": vol, "unit": "lots", "notional": vol * cs_h * px_h}
    # 1.46: the parent's factor exposure to the hedge instrument is beta x PN and the leg adds ±HN (was PN before and PN ± HN x beta after:
    # at beta > 1 the plan showed an over-hedge with a sign flip). The quote currencies of both legs are shown: the leg volume is computed
    # without an FX conversion (different quote currencies -> DIFFERENT_NOT_CONVERTED; the conversion itself is an owner decision)
    qc_p, qc_h = (spec.get(par["symbol"]) or {}).get("currency_profit"), hs.get("currency_profit")
    qc = {"parent": qc_p, "partner": qc_h, "status": ("SAME" if qc_p == qc_h else "DIFFERENT_NOT_CONVERTED") if qc_p and qc_h else "NOT_VERIFIED"}
    full = _layers_full(ctx, par, f"beta {b1['beta']:.3f} (120) / {b2['beta']:.3f} (60)")      # 1.46 (I0763)
    if full:
        return full
    return {"state": "HEDGE_PLAN", "reason": f"beta {b1['beta']:.3f} (120) / {b2['beta']:.3f} (60), korelacja {b1['corr']:.2f}",
            "plan": _plan({"id": par["id"], "symbol": par["symbol"], "side": par["side"], "volume": par["volume"]}, [leg], ratio=ratio,
                          risk_before={"factor_notional": b1["beta"] * parent_notional},
                          risk_after={"factor_notional": b1["beta"] * parent_notional + math.copysign(leg["notional"], hn)},
                          cost=None, residual={"basis_risk": "jawne – relacja może się rozpaść"}, exit_rule=ctx["strategy"]["exit_policy_or_expiry_policy"],
                          timeout=int(ctx["p"].get("timeout_bars", 6)), extra={"beta": {"w120": b1, "w60": b2}, "formula": "−coverage × beta × parent_notional",
                                                                               "quote_currency": qc})}


def beta_pair(ctx):
    return _beta_hedge(ctx, ctx["p"].get("partner"))


def pair_relative(ctx):
    return _beta_hedge(ctx, ctx["p"].get("partner") or (ctx.get("pair_map") or {}).get(ctx.get("symbol")))


def min_variance(ctx):
    exp = [e for e in ctx.get("exposure") or [] if e.get("leg") == "PRIMARY"]
    syms = sorted({e["symbol"] for e in exp})
    if len(syms) < 2:
        return {"state": "NO_EXPOSURE" if not exp else "NO_HEDGE", "reason": "wymagane ≥ 2 pozycje FX"}
    lim = ctx["p"].get("risk_limit")
    if lim is None:
        return {"state": "NO_HEDGE", "reason": "limit ryzyka koszyka nieskonfigurowany"}
    bars = ctx.get("bars") or {}
    cands = [c for c in (ctx.get("fx_pairs") or []) if c not in syms and (bars.get(c) or {}).get("M15")]
    if not cands:
        raise Unavailable("brak instrumentów ochronnych z historią M15")
    allsyms = syms + cands
    rets = []
    for s in allsyms:
        b = (bars.get(s) or {}).get("M15") or []
        c = np.array([float(x["c"]) for x in b[-121:]])
        if len(c) < 121:
            raise Unavailable(f"za mało historii {s}")
        rets.append(np.diff(np.log(c)))
    R = np.vstack(rets)
    C = np.cov(R)
    spec = ctx.get("spec") or {}
    w = np.zeros(len(allsyms))
    for e in exp:
        k = allsyms.index(e["symbol"])
        w[k] += (1 if e["side"] == "LONG" else -1) * float(e["volume"]) * float((spec.get(e["symbol"]) or {}).get("trade_contract_size") or 1) * float(e.get("price") or e.get("entry") or 1)
    var0 = float(w @ C @ w)
    if math.sqrt(max(var0, 0)) <= float(lim):
        return {"state": "NO_HEDGE", "reason": "ryzyko koszyka w limicie", "sigma": math.sqrt(max(var0, 0))}
    best = None
    import itertools
    np_ = len(syms)
    for k in (1, 2):
        for comb in itertools.combinations(range(np_, len(allsyms)), min(k, int(ctx["p"].get("max_instruments", 2)))):
            idx = list(comb)
            Chh = C[np.ix_(idx, idx)]
            if np.linalg.cond(Chh) > 1e8:
                continue
            h = -np.linalg.solve(Chh, C[idx][:, :np_] @ w[:np_])
            ww = w.copy()
            ww[idx] = h
            v = float(ww @ C @ ww)
            if best is None or v < best[0]:
                best = (v, idx, h)
    if best is None or best[0] >= var0:
        return {"state": "NO_HEDGE", "reason": "żaden zestaw nie zmniejsza wariancji"}
    legs = [{"instrument": allsyms[k], "side": "LONG" if h > 0 else "SHORT", "notional": abs(float(h)), "unit": "money"} for k, h in zip(best[1], best[2])]
    return {"state": "HEDGE_PLAN", "reason": f"σ koszyka {math.sqrt(var0):.2f} > limit {lim}",
            "plan": _plan({"positions": syms}, legs, ratio=None, risk_before={"sigma": math.sqrt(var0)}, risk_after={"sigma": math.sqrt(best[0])},
                          cost=None, residual=None, exit_rule="rebalans tylko po przekroczeniu pasma, cooldown", timeout=int(ctx["p"].get("timeout_bars", 6)))}


# ============================================================================ CRYPTO PERPS (declared exposure, MANUAL_ONLY)
def _cp_exposure(ctx):
    return [e for e in ctx.get("exposure") or [] if e.get("kind", "PERP") == "PERP"]


def _cp_bars(ctx, coin, tf="M15"):
    b = ((ctx.get("bars") or {}).get(coin) or {}).get(tf)
    if not b:
        raise Unavailable(f"brak świec {coin} {tf}")
    return b


def _cp_qty(ctx, coin, notional, px):
    meta = (ctx.get("spec") or {}).get(coin) or {}
    szd = meta.get("szDecimals")
    if szd is None:
        raise Unavailable(f"brak szDecimals {coin}")
    q = math.floor(abs(notional) / px * 10 ** int(szd)) / 10 ** int(szd)
    return q if q > 0 else None


def _factor_hedge(ctx, factor: str, trigger: str | None, tag: str | None = None):
    exp = [e for e in _cp_exposure(ctx) if e["instrument"] != factor and (tag is None or tag in (e.get("tags") or []))]
    if not exp:
        return {"state": "NO_EXPOSURE", "reason": f"brak zadeklarowanej ekspozycji{' z tagiem ' + tag if tag else ''} (poza {factor})"}
    par = exp[0]
    if trigger == "BENCH_CHOCH":
        Fb = (ctx.get("feats") or {}).get((factor, "M5"))
        if Fb is None:
            raise Unavailable(f"brak {factor} M5")
        s = 1 if par["side"] == "LONG" else -1
        if not Fb.last_break(Fb.i, -s, 2, kinds=("CHOCH",)):
            return {"state": "NO_HEDGE", "reason": f"brak przeciwnego CHoCH {factor} M5"}
    pb, fb = _cp_bars(ctx, par["instrument"]), _cp_bars(ctx, factor)
    ok, b1, b2 = _beta_core(ctx, pb, fb, ctx["p"])
    if not ok:
        return {"state": "NO_HEDGE", "reason": "relacja niestabilna (beta / korelacja)", "beta_120": b1, "beta_60": b2}
    px_p, px_f = float(pb[-1]["c"]), float(fb[-1]["c"])
    pn = (1 if par["side"] == "LONG" else -1) * float(par["size"]) * px_p
    ratio = float(ctx["p"].get("ratio", 0.5))
    hn = -ratio * b1["beta"] * pn
    q = _cp_qty(ctx, factor, hn, px_f)
    if q is None:
        return {"state": "NO_HEDGE", "reason": "ilość poniżej precyzji kontraktu"}
    fee = (ctx.get("fees") or {}).get("taker")
    leg = {"instrument": factor, "side": "SHORT" if hn < 0 else "LONG", "size": q, "unit": factor, "notional": q * px_f, "price_basis": "mark (trigger) / fill osobno"}
    return {"state": "HEDGE_PLAN", "reason": f"beta {b1['beta']:.2f}, korelacja {b1['corr']:.2f}",
            "plan": _plan({"instrument": par["instrument"], "side": par["side"], "size": par["size"], "source": par.get("source", "MANUAL_DECLARED")}, [leg],
                          ratio=ratio, risk_before={"factor_notional_usd": pn * b1["beta"]}, risk_after={"factor_notional_usd": pn * b1["beta"] + math.copysign(leg["notional"], hn)},
                          cost={"fees_both_sides": (2 * fee * leg["notional"]) if fee is not None else None, "funding": "wg bieżącej stawki – nie stała"},
                          residual={"idiosyncratic": "pozostaje"}, exit_rule=ctx["strategy"]["exit_policy_or_expiry_policy"],
                          timeout=int(ctx["p"].get("timeout_bars", 6)), extra={"execution": "MANUAL_TICKET (FOMO)", "beta": {"w120": b1, "w60": b2}})}


def crypto_beta(ctx):
    return _factor_hedge(ctx, ctx["p"].get("factor", "BTC"), ctx["p"].get("trigger"))


def eth_ecosystem(ctx):
    return _factor_hedge(ctx, "ETH", "BENCH_CHOCH", tag=ctx["p"].get("require_tag", "ETH"))


def basket_beta(ctx):
    exp = [e for e in _cp_exposure(ctx) if e["instrument"] not in ("BTC",)]
    if len(exp) < 2:
        return {"state": "NO_EXPOSURE" if not exp else "NO_HEDGE", "reason": "wymagane ≥ 2 alty"}
    fb = _cp_bars(ctx, "BTC")
    tot = 0.0
    for e in exp:
        ok, b1, _ = _beta_core(ctx, _cp_bars(ctx, e["instrument"]), fb, {"window": 120, "window2": 60, "corr_min": 0.0})
        if b1["beta"] is None:
            return {"state": "NO_HEDGE", "reason": f"brak bety {e['instrument']}"}
        tot += (1 if e["side"] == "LONG" else -1) * float(e["size"]) * float(_cp_bars(ctx, e["instrument"])[-1]["c"]) * b1["beta"]
    lim = ctx["p"].get("limit_usd")
    if lim is None:
        return {"state": "NO_HEDGE", "reason": "limit ekspozycji czynnikowej nieskonfigurowany", "beta_exposure_usd": tot}
    if abs(tot) <= float(lim) * (1 + float(ctx["p"].get("band", 0.25))):
        return {"state": "NO_HEDGE", "reason": "w paśmie", "beta_exposure_usd": tot}
    hn = -float(ctx["p"].get("ratio", 0.5)) * tot
    q = _cp_qty(ctx, "BTC", hn, float(fb[-1]["c"]))
    if q is None:                                                  # 1.46 (I0764): quantity rounded to 0 -> no HEDGE_PLAN with size None
        return {"state": "NO_HEDGE", "reason": "ilość poniżej precyzji kontraktu"}
    return {"state": "HEDGE_PLAN", "reason": f"suma beta-exposure {tot:,.0f} USD",
            "plan": _plan({"basket": [e["instrument"] for e in exp]}, [{"instrument": "BTC", "side": "SHORT" if hn < 0 else "LONG", "size": q, "unit": "BTC"}],
                          ratio=float(ctx["p"].get("ratio", 0.5)), risk_before={"beta_usd": tot}, risk_after={"beta_usd": tot + hn}, cost=None, residual=None,
                          exit_rule="rebalans po przekroczeniu pasma", timeout=int(ctx["p"].get("timeout_bars", 6)))}


def two_factor(ctx):
    exp = [e for e in _cp_exposure(ctx) if e["instrument"] not in ("BTC", "ETH")]
    if not exp:
        return {"state": "NO_EXPOSURE"}
    rb, re = _cp_bars(ctx, "BTC"), _cp_bars(ctx, "ETH")
    tot = np.zeros(2)
    for e in exp:
        pb = _cp_bars(ctx, e["instrument"])
        ra, rbt = D.sync_returns(pb, rb, 120)
        _, ret = D.sync_returns(pb, re, 120)
        n = min(len(ra), len(rbt), len(ret))
        if n < 60:
            raise Unavailable("za mało zsynchronizowanych zwrotów")
        X = np.column_stack([rbt[-n:], ret[-n:]])
        if np.linalg.cond(X.T @ X) > float(ctx["p"].get("max_cond", 30.0)) ** 2:
            return {"state": "NO_HEDGE", "reason": "współliniowość BTC/ETH – brak stabilnego rozwiązania dwuczynnikowego"}
        coef, *_ = np.linalg.lstsq(X, ra[-n:], rcond=None)
        pn = (1 if e["side"] == "LONG" else -1) * float(e["size"]) * float(pb[-1]["c"])
        tot += coef * pn
    ratio = float(ctx["p"].get("ratio", 0.5))
    legs = []
    for coin, expo, bars in (("BTC", tot[0], rb), ("ETH", tot[1], re)):
        q = _cp_qty(ctx, coin, ratio * expo, float(bars[-1]["c"]))
        if q:
            legs.append({"instrument": coin, "side": "SHORT" if expo > 0 else "LONG", "size": q, "unit": coin})
    if not legs:
        return {"state": "NO_HEDGE", "reason": "nogi poniżej precyzji"}
    return {"state": "HEDGE_PLAN", "reason": "model dwuczynnikowy (OLS na 120 zwrotach M15)",
            "plan": _plan({"positions": [e["instrument"] for e in exp]}, legs, ratio=ratio, risk_before={"btc_usd": tot[0], "eth_usd": tot[1]},
                          risk_after={"btc_usd": tot[0] * (1 - ratio), "eth_usd": tot[1] * (1 - ratio)}, cost=None, residual=None,
                          exit_rule="rebalans po zmianie składu", timeout=int(ctx["p"].get("timeout_bars", 6)))}


def residual_pair(ctx):
    exp = _cp_exposure(ctx)
    pm = ctx["p"].get("pairs") or (ctx.get("pair_map") or {})
    par = next((e for e in exp if e["instrument"] in pm), None)
    if not exp:
        return {"state": "NO_EXPOSURE"}
    if par is None:
        return {"state": "NO_HEDGE", "reason": "brak skonfigurowanej pary sektorowej dla ekspozycji"}
    other = pm[par["instrument"]]
    a, b = _cp_bars(ctx, par["instrument"]), _cp_bars(ctx, other)
    bm = {x["t"]: float(x["c"]) for x in b}
    pts = [(math.log(float(x["c"])), math.log(bm[x["t"]])) for x in a if x["t"] in bm][-(int(ctx["p"].get("window", 120)) + 1):]
    if len(pts) < 60:
        raise Unavailable("za mało wspólnych świec")
    hist, cur = np.array(pts[:-1]), pts[-1]
    A = np.column_stack([np.ones(len(hist)), hist[:, 1]])
    (alpha, beta_), *_ = np.linalg.lstsq(A, hist[:, 0], rcond=None)
    res = hist[:, 0] - (alpha + beta_ * hist[:, 1])
    sd = float(res.std(ddof=1))
    if beta_ <= 0 or sd <= 0:
        return {"state": "NO_HEDGE", "reason": "relacja log-cen niestabilna (beta ≤ 0 lub brak wariancji)"}
    z = (cur[0] - (alpha + beta_ * cur[1]) - float(res.mean())) / sd
    sgn = 1 if par["side"] == "LONG" else -1
    if sgn * z <= float(ctx["p"].get("z_in", 2.0)):
        return {"state": "NO_HEDGE", "reason": f"residual z = {z:.2f} poniżej progu", "z": z}
    pn = sgn * float(par["size"]) * float(a[-1]["c"])
    q = _cp_qty(ctx, other, beta_ * pn, float(b[-1]["c"]))
    if q is None:                                                  # 1.46 (I0764): quantity rounded to 0 -> no HEDGE_PLAN with size None
        return {"state": "NO_HEDGE", "reason": "ilość poniżej precyzji kontraktu"}
    return {"state": "HEDGE_PLAN", "reason": f"residual z = {z:.2f}",
            "plan": _plan({"instrument": par["instrument"]}, [{"instrument": other, "side": "SHORT" if pn > 0 else "LONG", "size": q, "unit": other}],
                          ratio=1.0, risk_before={"z": z}, risk_after=None, cost=None, residual=None, exit_rule=f"residual z ≤ {ctx['p'].get('z_out', 0.5)} / rozpad / timeout",
                          timeout=int(ctx["p"].get("timeout_bars", 6)), extra={"relation": {"alpha": alpha, "beta": beta_, "sd": sd}})}


def crypto_vol_shock(ctx):
    exp = _cp_exposure(ctx)
    if not exp:
        return {"state": "NO_EXPOSURE"}
    Fb = (ctx.get("feats") or {}).get(("BTC", "M1"))
    if Fb is None:
        raise Unavailable("brak BTC M1")
    if not _shock(Fb, Fb.i, float(ctx["p"].get("pct", 0.95)), int(ctx["p"].get("lookback", 200))):
        return {"state": "NO_HEDGE", "reason": "zakres BTC M1 w normie"}
    net = sum((1 if e["side"] == "LONG" else -1) for e in exp)
    if not ((Fb.bear(Fb.i) and net > 0) or (Fb.bull(Fb.i) and net < 0)):
        return {"state": "NO_HEDGE", "reason": "zamknięcie nie jest przeciw ekspozycji"}
    return _factor_hedge(ctx, "BTC", None)


def cross_market(ctx):
    exp = _cp_exposure(ctx)
    if not exp:
        return {"state": "NO_EXPOSURE"}
    alt = ctx.get("same_underlying") or {}
    par = next((e for e in exp if alt.get(e["instrument"])), None)
    if par is None:
        raise Unavailable("brak drugiego kontraktu tego samego underlying w innym namespace dostępnym w FOMO")
    other = alt[par["instrument"]]
    pa, pb = float(_cp_bars(ctx, par["instrument"])[-1]["c"]), float(_cp_bars(ctx, other)[-1]["c"])
    basis = (pb / pa - 1) * 1e4
    if abs(basis) > float(ctx["p"].get("basis_limit_bps", 50)):
        return {"state": "NO_HEDGE", "reason": f"basis {basis:.1f} bps ponad limit"}
    q = _cp_qty(ctx, other, float(par["size"]) * pa, pb)
    if q is None:                                                  # 1.46 (I0764): quantity rounded to 0 -> no HEDGE_PLAN with size None
        return {"state": "NO_HEDGE", "reason": "ilość poniżej precyzji kontraktu"}
    return {"state": "HEDGE_PLAN", "reason": f"basis {basis:.1f} bps",
            "plan": _plan({"instrument": par["instrument"]}, [{"instrument": other, "side": "SHORT" if par["side"] == "LONG" else "LONG", "size": q}], ratio=1.0,
                          risk_before=None, risk_after=None, cost=None, residual={"basis_oracle_collateral": "osobne ryzyka"}, exit_rule="limit basis / koszt / timeout",
                          timeout=int(ctx["p"].get("timeout_bars", 6)))}


def spot_inventory(ctx):
    inv = [e for e in ctx.get("exposure") or [] if e.get("kind") == "SPOT"]
    if not inv:
        return {"state": "NO_EXPOSURE", "reason": "brak zadeklarowanego salda spot"}
    e = inv[0]
    spec = (ctx.get("spec") or {}).get(e["instrument"])
    if not spec:
        raise Unavailable(f"brak perpa {e['instrument']}")
    px = float(_cp_bars(ctx, e["instrument"])[-1]["c"])
    q = _cp_qty(ctx, e["instrument"], float(ctx["p"].get("ratio", 0.5)) * float(e["size"]) * px, px)
    if q is None:                                                  # 1.46 (I0764): quantity rounded to 0 -> no HEDGE_PLAN with size None
        return {"state": "NO_HEDGE", "reason": "ilość poniżej precyzji kontraktu"}
    return {"state": "HEDGE_PLAN", "reason": "ochrona części salda spot",
            "plan": _plan({"spot": e["instrument"], "size": e["size"]}, [{"instrument": e["instrument"], "side": "SHORT", "size": q}], ratio=float(ctx["p"].get("ratio", 0.5)),
                          risk_before={"spot_units": e["size"]}, risk_after={"net_units": float(e["size"]) - (q or 0)}, cost=None,
                          residual={"platform_risk": "spot i perp – odrębne ryzyka platformy / likwidacji"}, exit_rule="zmniejszenie inventory / koniec okna",
                          timeout=int(ctx["p"].get("timeout_bars", 6)))}


def stress_loss(ctx):
    exp = _cp_exposure(ctx)
    if not exp:
        return {"state": "NO_EXPOSURE"}
    lim = ctx["p"].get("loss_limit")
    sc = [float(x) for x in ctx["p"].get("scenarios", [-0.05, -0.10, -0.20])]
    fb = _cp_bars(ctx, "BTC")
    betas, pns = [], []
    for e in exp:
        pb = _cp_bars(ctx, e["instrument"])
        b = 1.0 if e["instrument"] == "BTC" else D.beta(*D.sync_returns(pb, fb, 120))["beta"]
        if b is None:
            return {"state": "NO_HEDGE", "reason": f"brak bety {e['instrument']}"}
        betas.append(b)
        pns.append((1 if e["side"] == "LONG" else -1) * float(e["size"]) * float(pb[-1]["c"]))
    def worst(h):
        return min(sum(bt * pn * m for bt, pn in zip(betas, pns)) + h * m for m in sc + [-x for x in sc])
    w0 = worst(0.0)
    if lim is None:
        return {"state": "NO_HEDGE", "reason": "limit straty scenariuszowej nieskonfigurowany", "worst_loss_usd": w0}
    if w0 >= -float(lim):
        return {"state": "NO_HEDGE", "reason": "strata scenariuszowa w limicie", "worst_loss_usd": w0}
    expo = sum(bt * pn for bt, pn in zip(betas, pns))
    grid = np.linspace(0, -expo, 21)
    h = max(grid, key=worst)
    q = _cp_qty(ctx, "BTC", h, float(fb[-1]["c"]))
    if q is None:                                                  # 1.46 (I0764): quantity rounded to 0 -> no HEDGE_PLAN with size None
        return {"state": "NO_HEDGE", "reason": "ilość poniżej precyzji kontraktu"}
    return {"state": "HEDGE_PLAN", "reason": f"strata scenariuszowa {w0:,.0f} > limit {lim}",
            "plan": _plan({"positions": [e["instrument"] for e in exp]}, [{"instrument": "BTC", "side": "SHORT" if h < 0 else "LONG", "size": q}], ratio=None,
                          risk_before={"worst_scenario_usd": w0}, risk_after={"worst_scenario_usd": worst(h)}, cost=None,
                          residual={"note": "model scenariuszy (cena, beta), nie gwarantowana maksymalna strata; basis/korelacja mogą się zmienić"},
                          exit_rule="powrót do limitu / zmiana składu", timeout=int(ctx["p"].get("timeout_bars", 6)))}


def funding_aware(ctx):
    exp = _cp_exposure(ctx)
    if not exp:
        return {"state": "NO_EXPOSURE"}
    fund = ctx.get("funding") or {}
    fee = (ctx.get("fees") or {}).get("taker")
    # 1.46: {"BTC": None, "ETH": None} (contexts() failed) is truthy - every option was skipped and the result was a NO_HEDGE market verdict
    if not fund or all(v is None for v in fund.values()) or fee is None:
        raise Unavailable("brak bieżącego funding / stawki fee")
    opts = []
    for f in ("BTC", "ETH"):
        try:
            r = _factor_hedge(ctx, f, None)
        except Unavailable:
            continue
        if r["state"] != "HEDGE_PLAN":
            continue
        leg = r["plan"]["legs"][0]
        rate = fund.get(f)
        if rate is None:
            continue
        hold = float(ctx["p"].get("holding_h", 8))
        carry = (rate * hold) * leg["notional"] * (1 if leg["side"] == "LONG" else -1)       # hourly rate x hours (no 8h mix-up)
        opts.append((2 * fee * leg["notional"] + carry, f, r))
    if len(opts) < 2:
        return {"state": "NO_HEDGE", "reason": "mniej niż dwa instrumenty ochronne spełniają warunek redukcji ryzyka"}
    opts.sort(key=lambda x: x[0])
    best = opts[0]
    best[2]["plan"]["selection"] = {"candidates": [{"factor": f, "expected_cost": c} for c, f, _ in opts], "chosen": best[1]}
    best[2]["reason"] = f"tańszy zestaw: {best[1]} (fees + funding × {ctx['p'].get('holding_h', 8)} h)"
    return best[2]


# 1.46 (I0112): the 10 otc_* planners (+ _otc_parents / _otc_gate and baskets/payoff.py) were removed - OTC retired in TASK 020, no
# strategy of the active catalog points at them (OTC_HEDGE_* stay only as historical labels in catalog.HISTORICAL_STRATEGIES)
PLANNERS = {f.__name__: f for f in (structural_choch, range_profit, vol_shock, session_transition, mtf_countermove, event_shield, currency_factor, beta_pair,
                                    pair_relative, min_variance, crypto_beta, eth_ecosystem, basket_beta, two_factor, residual_pair, crypto_vol_shock,
                                    cross_market, spot_inventory, stress_loss, funding_aware)}
