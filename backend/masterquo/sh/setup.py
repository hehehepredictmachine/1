"""Setup engine for SCALPING and HEDGING (PMW-SH-1). Deterministic, programmable, auditable.

Pipeline (each step is a checklist item with PASS / FAIL / WAIT and its reason):
 1. data quality and freshness              (gate)
 2. regime + higher-timeframe context       (gate; selects CONTINUATION or REVERSAL - never both)
 3. zone of interest + invalidation level
 4. confirmation (momentum / structure / candle by mode)
 5. trigger on the last CLOSED M1 bar
 6. reachability of TP1/TP2 within the horizon (volatility, obstacles, calibrated model if READY)
 7. result after costs and risk (SL from invalidation and volatility, net RR, SL cap)
 8. management plan (partials, BE after confirmed TP2, TTL, invalidation, position time limit)

Status: READY (all pass, trigger fired) / WAIT (a waiting condition) / NO_TRADE (a blocking reason) / INVALIDATED / EXPIRED.
A waiting setup is never presented as an active signal. Score = heuristic 0-100 (NOT a probability); a probability is shown
only from a READY model trained on exactly this strategy's event.
"""
from __future__ import annotations

import hashlib
import json
import math

from .context import obstacles
from .units import SymbolSpec, UnitError

SETUP_VERSION = "PMW-SH-SETUP-1.0.0"


def _sid(*parts) -> str:
    return "SH-" + hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:14]


class _CL:
    def __init__(self):
        self.items = []

    def add(self, cid, label, status, detail=""):
        self.items.append({"id": cid, "label": label, "status": status, "detail": detail})
        return status


def _dir_of(trend: str | None) -> int:
    return 1 if trend == "UP" else -1 if trend == "DOWN" else 0


def evaluate(strategy: str, inst: str, snap: dict, spec: SymbolSpec, prof: dict, *, now: float, tp_prob: dict | None = None,
             models: list[dict] | None = None, config_hash: str = "", m1: list[dict] | None = None) -> dict:
    cl, pro, con = _CL(), [], []
    out = {"strategy": strategy, "symbol": spec.symbol, "instrument": inst, "setup_version": SETUP_VERSION, "config_hash": config_hash,
           "created_at": now, "tp_unit": "USD_PRICE_MOVE (bezwzględny ruch ceny instrumentu w USD; nie %, nie punkty, nie zysk rachunku)",
           "score": {"value": None, "definition": "heurystyka 0–100 z checklisty – NIE jest prawdopodobieństwem"},
           "probability": {"value": None, "event": f"TP2 przed SL w {prof['horizon_minutes']} min", "status": "BRAK_MODELU_ZDARZENIA"}}

    def finish(status, reason):
        passed = sum(1 for x in cl.items if x["status"] == "PASS")
        total = max(1, sum(1 for x in cl.items if x["status"] in ("PASS", "FAIL", "WAIT")))
        out.update(status=status, status_reason=reason, checklist=cl.items, args_for=pro, args_against=con,
                   models=[{k: r.get(k) for k in ("id", "status", "group")} | {"use": (r.get(strategy) or {}).get("use"),
                                                                                    "role": (r.get(strategy) or {}).get("role")} for r in (models or [])])
        out["score"]["value"] = round(100.0 * passed / total, 1)
        out.setdefault("signal_id", _sid(strategy, inst, out.get("side"), out.get("mode"), round(now / 60)))
        return out

    ic = prof.get("_instrument") or {}
    # 0. instrument & units
    if ic.get("enabled") is False:
        cl.add("instrument", "Instrument dopuszczony", "FAIL", ic.get("status", "wyłączony"))
        return finish("NO_TRADE", f"instrument {inst} zablokowany: {ic.get('status')}")
    try:
        spec.check_usd(ic.get("unit_conversion"))
    except UnitError as exc:
        cl.add("units", "Jednostki TP (USD)", "FAIL", str(exc))
        return finish("NO_TRADE", str(exc))
    cl.add("units", "Jednostki TP (USD)", "PASS", f"kwotowanie {spec.currency_profit}, tick {spec.tick_size}")

    # 1. data
    d = snap.get("data") or {}
    if d.get("status") != "OK":
        cl.add("data", "Jakość i świeżość danych", "FAIL", "; ".join(d.get("issues") or ["brak"]))
        return finish("NO_TRADE", "dane: " + "; ".join(d.get("issues") or []))
    cl.add("data", "Jakość i świeżość danych", "PASS", f"notowanie {d.get('quote_age_s')} s, spread {d.get('spread'):.3f}")
    vol = snap.get("vol") or {}
    atr1, atr5 = vol.get("atr_m1"), vol.get("atr_m5")
    if not atr1 or not atr5:
        cl.add("vol", "Zmienność ATR", "WAIT", "rozgrzewka ATR")
        return finish("WAIT", "rozgrzewka wskaźników zmienności")
    cl.add("vol", "Zmienność ATR", "PASS", f"ATR M1 {atr1:.2f}, M5 {atr5:.2f} USD")

    # 2. regime + HTF -> mode and side
    reg = (snap.get("regime") or {}).get("state")
    s5, s15, s60 = (snap.get(f"structure_{tf}") or {} for tf in ("M5", "M15", "H1"))
    d5, d15, d60 = _dir_of(s5.get("internal")), _dir_of(s15.get("internal")), _dir_of(s60.get("major") if s60.get("major") in ("UP", "DOWN") else s60.get("internal"))
    allow = set(prof.get("allow_regimes") or [])
    reg_group = "TREND" if (reg or "").startswith("TREND") else reg
    if reg is None:
        cl.add("regime", "Reżim rynku", "WAIT", "reżim w rozgrzewce")
        return finish("WAIT", "reżim nieustalony")
    if reg_group not in allow:
        cl.add("regime", "Reżim rynku", "FAIL", f"{reg} nie jest dopuszczony dla {strategy} ({', '.join(sorted(allow))})")
        return finish("NO_TRADE", f"reżim {reg} niedopuszczony")
    mode, side = None, None
    if reg_group == "TREND":
        want = 1 if reg == "TREND_UP" else -1
        if d60 == -want or d15 == -want:
            cl.add("htf", "Kontekst wyższych interwałów", "FAIL", f"H1 {s60.get('major')}/M15 {s15.get('internal')} przeciw trendowi M5 – konflikt interwałów")
            return finish("WAIT", "sprzeczne interwały (H1/M15 przeciw trendowi M5)")
        mode, side = "CONTINUATION", "BUY" if want > 0 else "SELL"
    elif reg_group == "TRANSITION":
        if d5 and d5 == d15 and d60 != -d5:
            mode, side = "CONTINUATION", "BUY" if d5 > 0 else "SELL"
        else:
            cl.add("htf", "Kontekst wyższych interwałów", "WAIT", f"przejście: M5 {s5.get('internal')}, M15 {s15.get('internal')}, H1 {s60.get('major')}")
            return finish("WAIT", "reżim przejściowy bez zgodnych interwałów")
    elif reg_group == "RANGE":
        mode = "REVERSAL"
    cl.add("regime", "Reżim rynku", "PASS", f"{reg} → tryb {mode}")

    px = snap.get("price") or {}
    ctx = snap.get("ctx") or {}
    buf = prof["sl_atr_m1_buffer"] * atr1
    # 3. zone + invalidation
    if mode == "CONTINUATION":
        anchor = (ctx.get("pb_last_low_m5") or s5.get("last_low")) if side == "BUY" else (ctx.get("pb_last_high_m5") or s5.get("last_high"))
        if anchor is None:
            cl.add("zone", "Strefa i unieważnienie", "WAIT", "brak potwierdzonego pullbacku M5")
            return finish("WAIT", "brak strefy pullbacku")
        zone = (anchor, anchor + prof["zone_atr_m5"] * atr5) if side == "BUY" else (anchor - prof["zone_atr_m5"] * atr5, anchor)
        inval = anchor - buf if side == "BUY" else anchor + buf
        cl.add("htf", "Kontekst wyższych interwałów", "PASS", f"H1 {s60.get('major')}, M15 {s15.get('internal')}, M5 {s5.get('internal')}")
    else:
        lo = min(x for x in (s5.get("last_low"), ctx.get("smc_low_m5")) if x is not None) if (s5.get("last_low") or ctx.get("smc_low_m5")) else None
        hi = max(x for x in (s5.get("last_high"), ctx.get("smc_high_m5")) if x is not None) if (s5.get("last_high") or ctx.get("smc_high_m5")) else None
        mid = (px.get("bid", 0) + px.get("ask", 0)) / 2
        if lo is None or hi is None or hi <= lo:
            cl.add("zone", "Strefa i unieważnienie", "WAIT", "brak zakresu M5")
            return finish("WAIT", "brak zakresu")
        width = hi - lo
        if mid <= lo + 0.25 * width:
            side, anchor = "BUY", lo
            zone, inval = (lo - 0.2 * atr5, lo + prof["zone_atr_m5"] * atr5), lo - buf
        elif mid >= hi - 0.25 * width:
            side, anchor = "SELL", hi
            zone, inval = (hi - prof["zone_atr_m5"] * atr5, hi + 0.2 * atr5), hi + buf
        else:
            cl.add("zone", "Strefa i unieważnienie", "WAIT", f"cena w środku zakresu {lo:.2f}–{hi:.2f}")
            return finish("WAIT", "cena w środku zakresu – brak przewagi lokalizacji")
        if d60 and d60 == (-1 if side == "BUY" else 1):
            con.append(f"odwrócenie przeciw trendowi H1 ({s60.get('major')})")
    out.update(mode=mode, side=side)
    ref = px["ask"] if side == "BUY" else px["bid"]
    if (side == "BUY" and px["bid"] <= inval) or (side == "SELL" and px["ask"] >= inval):
        cl.add("zone", "Strefa i unieważnienie", "FAIL", f"cena przekroczyła unieważnienie {inval:.2f}")
        out.update(entry_zone=[round(zone[0], 5), round(zone[1], 5)], invalidation=inval)
        return finish("INVALIDATED", "unieważnienie przed wejściem")
    recent = (m1 or [])[-10:]
    touched = any((b["l"] <= zone[1]) if side == "BUY" else (b["h"] >= zone[0]) for b in recent) or (zone[0] <= ref <= zone[1])
    runaway = (ref - zone[1]) if side == "BUY" else (zone[0] - ref)
    out.update(entry_zone=[round(zone[0], 5), round(zone[1], 5)], invalidation=round(inval, 5))
    if not touched:
        cl.add("zone", "Strefa i unieważnienie", "WAIT", f"czekam na strefę {zone[0]:.2f}–{zone[1]:.2f}")
        return finish("WAIT", "cena poza strefą")
    if runaway > 0.5 * atr5:
        cl.add("zone", "Strefa i unieważnienie", "WAIT", f"cena uciekła ze strefy o {runaway:.2f}")
        return finish("WAIT", "cena za daleko od strefy (ryzyko pogoni)")
    cl.add("zone", "Strefa i unieważnienie", "PASS", f"strefa {zone[0]:.2f}–{zone[1]:.2f}, unieważnienie {inval:.2f}")

    # 4. confirmation
    sg = 1 if side == "BUY" else -1
    if mode == "CONTINUATION":
        vm = ctx.get("vamd_m5")
        fdz = ctx.get("fd_zone_m5")
        ok_v = vm is not None and vm * sg > 0
        ok_f = fdz not in (None, "CHOP")
        if ok_v:
            pro.append(f"VAMD M5 {vm:+.2f} zgodny z kierunkiem")
        else:
            con.append(f"VAMD M5 {vm if vm is None else round(vm, 2)} niezgodny/brak")
        if not ok_f:
            con.append(f"FD M5 {fdz} (chaos)")
        if not (ok_v and ok_f):
            cl.add("confirm", "Potwierdzenie (momentum + reżim FD)", "WAIT", "momentum lub FD nie potwierdza")
            return finish("WAIT", "brak potwierdzenia momentum")
        cl.add("confirm", "Potwierdzenie (momentum + reżim FD)", "PASS", f"VAMD M5 {vm:+.2f}, FD {fdz}")
    else:
        last = ctx.get("smc_last_m1") or {}
        ch_ok = last.get("kind") == ("CHOCH_UP" if side == "BUY" else "CHOCH_DOWN") and last.get("bars_ago", 99) <= 10
        cdl = (snap.get("candle_m1") or {}).get("direction")
        c_ok = cdl == ("LONG" if side == "BUY" else "SHORT")         # sci2 role direction LONG / SHORT / NEUTRAL
        if not (ch_ok or c_ok):
            cl.add("confirm", "Potwierdzenie odwrócenia (CHoCH M1 / świeca)", "WAIT", "brak CHoCH M1 ani świecy odwrócenia")
            return finish("WAIT", "brak potwierdzenia odwrócenia")
        cl.add("confirm", "Potwierdzenie odwrócenia (CHoCH M1 / świeca)", "PASS", ("CHoCH M1" if ch_ok else "") + (" świeca M1" if c_ok else ""))
        pro.append("potwierdzenie odwrócenia na M1")

    # 5. trigger on the last closed M1 bar (micro break of the previous 2 bars)
    if len(recent) < 3:
        cl.add("trigger", "Trigger M1", "WAIT", "za mało świec M1")
        return finish("WAIT", "trigger niedostępny")
    b0, b1, b2 = recent[-1], recent[-2], recent[-3]
    trig = b0["c"] > max(b1["h"], b2["h"]) if side == "BUY" else b0["c"] < min(b1["l"], b2["l"])
    if not trig:
        cl.add("trigger", "Trigger M1 (zamknięcie poza 2 poprzednie świece)", "WAIT", "brak wybicia mikrostruktury M1")
        return finish("WAIT", "czekam na trigger")
    cl.add("trigger", "Trigger M1 (zamknięcie poza 2 poprzednie świece)", "PASS", f"zamknięcie {b0['c']:.2f}")

    # 7 (geometry first). SL from invalidation and volatility; never widened later
    sl_dist = max(abs(ref - inval), prof["sl_min_usd"])
    if sl_dist > prof["sl_max_usd"]:
        cl.add("risk_geom", "SL z unieważnienia i zmienności", "FAIL", f"SL {sl_dist:.2f} > limit {prof['sl_max_usd']:.2f} USD")
        return finish("NO_TRADE", "ryzyko setupu za duże dla wymaganych TP")
    sl = spec.stop(ref, side, sl_dist)
    tps = []
    shares = prof["shares"]
    for name, dist, share in zip(("TP1", "TP2", "TP3"), prof["tp_usd"], shares):
        t = spec.target(ref, side, dist)
        tps.append({"name": name, "distance_requested": dist, "price": t["price"], "distance_actual": t["actual_distance"],
                    "rounding_diff": t["rounding_diff"], "share": share})
    cl.add("risk_geom", "SL z unieważnienia i zmienności", "PASS", f"SL {sl} ({abs(ref - sl):.2f} USD)")

    # 6. reachability
    horizon = prof["horizon_minutes"]
    expected = atr5 * math.sqrt(horizon / 5.0)
    obs = obstacles(snap, side, ref)
    first = obs[0] if obs else None
    if first and abs(first["price"] - ref) < prof["tp_usd"][0]:
        cl.add("reach", "Osiągalność TP1/TP2", "FAIL", f"przeszkoda {first['source']} {first['price']:.2f} przed TP1")
        return finish("NO_TRADE", f"przeszkoda przed TP1 ({first['source']})")
    if first and abs(first["price"] - ref) < prof["tp_usd"][1]:
        con.append(f"przeszkoda {first['source']} {first['price']:.2f} między TP1 a TP2")
    if expected < prof["tp_usd"][1] * prof.get("reach_factor", 1.0):
        cl.add("reach", "Osiągalność TP1/TP2", "FAIL", f"oczekiwany zasięg {expected:.2f} < TP2 {prof['tp_usd'][1]:.2f} w {horizon} min")
        return finish("NO_TRADE", "TP2 mało osiągalne w horyzoncie przy obecnej zmienności")
    pro.append(f"zasięg zmienności {expected:.2f} USD / {horizon} min ≥ TP2")
    if tp_prob and tp_prob.get("status") == "READY":
        p = tp_prob.get("p")
        out["probability"] = {"value": p, "event": f"TP2 przed SL w {horizon} min", "status": "SKALIBROWANE",
                              "model_version": tp_prob.get("version")}
        if p is None or p < prof.get("tp_model_min_prob", 0.55):
            cl.add("reach", "Osiągalność TP1/TP2", "FAIL", f"P(TP2 przed SL) = {p} < {prof.get('tp_model_min_prob')}")
            return finish("NO_TRADE", "model zdarzenia: za niskie prawdopodobieństwo TP2 przed SL")
    cl.add("reach", "Osiągalność TP1/TP2", "PASS", f"zasięg {expected:.2f}, najbliższa przeszkoda {first['price'] if first else '—'}")

    # 7. costs and net RR (whole cycle: weighted targets, one trade)
    cost = (d.get("spread") or 0.0) + 2 * (ic.get("slippage_usd") or 0.0)
    comm = ic.get("commission_per_lot_side")
    if comm is not None and spec.tick_value > 0:
        cost += 2 * comm / spec.money_per_price(1.0)
    else:
        con.append("prowizja nieznana – koszt bez prowizji (AUTO wymaga znanej prowizji)")
    w_tp = sum(t["distance_actual"] * t["share"] for t in tps)
    sl_real = abs(ref - sl)
    net_rr = (w_tp - cost) / (sl_real + cost)
    out.update(costs={"round_trip_price": round(cost, 4), "commission_known": comm is not None, "spread": d.get("spread")},
               net_rr=round(net_rr, 3))
    if net_rr < prof["min_net_rr"]:
        cl.add("costs", "Wynik po kosztach (RR netto całego cyklu)", "FAIL", f"RR netto {net_rr:.2f} < {prof['min_net_rr']}")
        return finish("NO_TRADE", "wynik po kosztach niewystarczający")
    cl.add("costs", "Wynik po kosztach (RR netto całego cyklu)", "PASS", f"RR netto {net_rr:.2f}, koszt {cost:.3f} USD")

    # 8. plan
    be_off = cost if prof.get("be_rule") == "ENTRY_PLUS_COSTS" else 0.0
    out.update(entry_ref=ref, sl=sl, tps=tps, shares=shares, horizon_minutes=horizon,
               be={"after": prof.get("be_after", "TP2"), "rule": prof.get("be_rule"), "offset_price": round(be_off, 4),
                   "definition": "BE po kosztach (cena wejścia ± koszt round-trip)" if be_off else "BE ceny wejścia",
                   "note": "stop nie gwarantuje braku straty przy luce lub poślizgu"},
               valid_until=now + 60 * prof["setup_ttl_minutes"], position_max_minutes=prof["position_max_minutes"],
               model_mode="PEŁNA" if out["probability"]["status"] == "SKALIBROWANE" else "OGRANICZONA")
    cl.add("plan", "Plan zarządzania", "PASS", f"udziały {shares}, BE po potwierdzonym {prof.get('be_after', 'TP2')}")
    out["signal_id"] = _sid(strategy, inst, side, mode, round(zone[0], 2), round(now / 60))
    return finish("READY", "wszystkie warunki spełnione")
