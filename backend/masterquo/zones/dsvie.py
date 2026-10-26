"""Daily Session Volume Intelligence Engine - DSVIE (PMW-ZONES-DSVIE-1).

Volume source - always reported, never switched silently (volume_source()):
  TICK_VOLUME      MT5 bar tick_volume: number of price updates in the bar = ACTIVITY PROXY. For OTC XAUUSD it is the broker's
                   quote activity, not global gold volume and not buyer/seller aggressor volume.
  EXCHANGE_VOLUME  MT5 bar real_volume > 0 (exchange-traded instruments): traded quantity of that feed.
  NONE             no usable volume -> profiles are INVALID.
  order flow / footprint / order book: UNAVAILABLE in this bot (bars carry no bid/ask classification; COPY_TICKS_INFO ticks carry
  quotes only). No zone is ever labelled as verified buyer- or seller-initiated volume.

Session windows: analytics.session_engine (named profile, IANA time zones, DST via zoneinfo) - one session definition for the whole bot.
Profile per session window, from CLOSED bars of `profile_tf` whose close is <= min(window end, as_of) (no future bar):
  allocation UNIFORM_RANGE: each bar's volume spread over the price bins its [low, high] covers, in proportion to the overlap
  (a candle-based ESTIMATE of where volume traded - not a trade-level profile).
  POC = bin with the largest volume (tie -> lower price). Value area = expand from the POC one bin at a time to the side with the
  larger volume (tie -> lower side) until >= value_area_pct of the total; VAH / VAL = outer edges of that range.
  HVN = local maxima of the smoothed histogram >= hvn_min_share_of_poc x max (POC excluded); LVN = local minima <=
  lvn_max_share_of_peaks x the smaller of the highest bins on each side.
States: DEVELOPING (window open), COMPLETED (window over, coverage >= min_profile_coverage - reproducible: later sessions never change
it), INVALID (coverage too low / no volume), STALE (developing but the newest bar is older than 3 bars).
Relative volume compares a profile with the SAME session of previous days over the SAME elapsed time (never one universal threshold).

Demand / supply candidates (evidence-based): a confirmed swing low (high) with (1) rejection on the pivot candle, (2) displacement
>= displacement_atr x ATR within displacement_bars, and (3) at least one context element: a completed profile level (VAL / VAH / POC /
LVN edge / HVN) within tolerance, a previous day / session extreme, or tick activity of the pivot candle >= 1.5 x the median of the 20
bars before it. Evidence is typed: PRICE_ACTION_INFERENCE, VOLUME_OBSERVATION (with the volume source) - never ORDER_FLOW.
"""
from __future__ import annotations

import hashlib
import statistics
from datetime import datetime, timezone

from ..analytics import session_engine as SE
from . import hlze as HZ
from .series import Series, iso

VERSION = "PMW-ZONES-DSVIE-1"
METHOD = "UNIFORM_RANGE_ALLOCATION_FROM_CANDLES"


def volume_source(s: Series) -> dict:
    n = len(s)
    rv = sum(1 for x in s.rv if x > 0)
    tv = sum(1 for x in s.v if x > 0)
    if n and rv >= 0.5 * n:
        src, note = "EXCHANGE_VOLUME", "real_volume z MT5 (wolumen transakcyjny tego źródła)"
    elif n and tv >= 0.5 * n:
        src, note = "TICK_VOLUME", "tick_volume z MT5 = liczba zmian ceny (aktywność); nie jest wolumenem transakcyjnym ani wolumenem agresorów"
    else:
        src, note = "NONE", "brak użytecznego wolumenu – profile nieważne"
    return {"source": src, "note": note, "bars": n, "bars_with_tick_volume": tv, "bars_with_real_volume": rv,
            "order_flow": "UNAVAILABLE", "footprint": "UNAVAILABLE", "order_book": "UNAVAILABLE"}


def _vol(s: Series, i: int, src: str) -> float:
    return s.rv[i] if src == "EXCHANGE_VOLUME" else s.v[i]


def histogram(s: Series, idx: list[int], bin_size: float, src: str) -> dict[int, float]:
    hist: dict[int, float] = {}
    for i in idx:
        v = _vol(s, i, src)
        if v <= 0:
            continue
        lo, hi = s.l[i], s.h[i]
        b0, b1 = int(lo // bin_size), int(hi // bin_size)
        if b1 == b0 or hi <= lo:
            hist[b0] = hist.get(b0, 0.0) + v
            continue
        span = hi - lo
        for b in range(b0, b1 + 1):
            ov = min(hi, (b + 1) * bin_size) - max(lo, b * bin_size)
            if ov > 0:
                hist[b] = hist.get(b, 0.0) + v * ov / span
    return hist


def value_area(hist: dict[int, float], pct: float) -> tuple[int, int, int]:
    """(poc_bin, val_bin, vah_bin) on a dense bin range."""
    keys = sorted(hist)
    lo_k, hi_k = keys[0], keys[-1]
    vals = [hist.get(k, 0.0) for k in range(lo_k, hi_k + 1)]
    total = sum(vals)
    p = max(range(len(vals)), key=lambda i: (vals[i], -i))              # tie -> lower price
    a = b = p
    acc = vals[p]
    while acc < pct * total and (a > 0 or b < len(vals) - 1):
        up = vals[b + 1] if b < len(vals) - 1 else -1.0
        dn = vals[a - 1] if a > 0 else -1.0
        if up > dn:
            b += 1
            acc += up
        else:
            a -= 1
            acc += dn
    return lo_k + p, lo_k + a, lo_k + b


def nodes(hist: dict[int, float], poc: int, cfg) -> tuple[list[int], list[int]]:
    keys = sorted(hist)
    lo_k, hi_k = keys[0], keys[-1]
    raw = [hist.get(k, 0.0) for k in range(lo_k, hi_k + 1)]
    w = max(1, cfg.node_smoothing_bins)
    sm = [sum(raw[max(0, i - w // 2):i + w // 2 + 1]) / len(raw[max(0, i - w // 2):i + w // 2 + 1]) for i in range(len(raw))]
    mx = max(sm) if sm else 0.0
    hvn, lvn = [], []
    for i in range(1, len(sm) - 1):
        if sm[i] > sm[i - 1] and sm[i] >= sm[i + 1] and sm[i] >= cfg.hvn_min_share_of_poc * mx and lo_k + i != poc:
            hvn.append(lo_k + i)
        if sm[i] < sm[i - 1] and sm[i] <= sm[i + 1]:
            left, right = max(sm[:i]), max(sm[i + 1:])
            if sm[i] <= cfg.lvn_max_share_of_peaks * min(left, right):
                lvn.append(lo_k + i)
    return hvn, lvn


def _slots(start: float, end: float, tf_s: int) -> int:
    return max(0, int((end - start) // tf_s))


def session_profiles(s: Series, profile_id: str, instrument: str, cfg, as_of: float, src: str) -> list[dict]:
    """Every session window of the profile covered by the series, as known at as_of (oldest first)."""
    if len(s) == 0:
        return []
    bin_size = cfg.bin_size.get(instrument) or 1.0
    days = int((as_of - s.t[0]) // 86400) + 2
    out = []
    for w in SE.windows(profile_id, as_of, days, 0):
        s0, s1 = w["start"].timestamp(), w["end"].timestamp()
        if s0 > as_of or s1 < s.t[0]:
            continue
        upto = min(s1, as_of)
        idx = [i for i in range(len(s)) if s.t[i] >= s0 and s.close_time(i) <= upto]
        if not idx:
            continue                                                     # market closed / no data: no profile is invented
        state = "DEVELOPING" if as_of < s1 else "COMPLETED"
        expected = _slots(s0, upto, s.tf_s)
        coverage = len(idx) / expected if expected else 0.0
        pid = "VP-" + hashlib.sha256(f"{instrument}|{profile_id}|{w['session']}|{w['local_date']}|{bin_size}|{s.tf}".encode()).hexdigest()[:12]
        prof = {"profile_id": pid, "session": w["session"], "local_date": w["local_date"], "start": iso(s0), "end": iso(s1),
                "tz": w["tz"], "state": state, "volume_source": src, "method": METHOD, "tf": s.tf, "bin_size": bin_size, "bars": len(idx),
                "expected_bars": expected, "coverage": round(coverage, 3), "known_at": iso(s.close_time(idx[-1])) if state == "DEVELOPING" else iso(max(s1, s.close_time(idx[-1])))}
        hist = histogram(s, idx, bin_size, src) if src != "NONE" else {}
        total = sum(hist.values())
        if not hist or total <= 0:
            prof.update(state="INVALID", reason="brak wolumenu w oknie")
            out.append(prof)
            continue
        if state == "COMPLETED" and coverage < cfg.min_profile_coverage:
            prof.update(state="INVALID", reason=f"pokrycie {coverage:.0%} < {cfg.min_profile_coverage:.0%} – profil niepełny")
        if state == "DEVELOPING" and as_of - s.close_time(idx[-1]) > 3 * s.tf_s:
            prof["state"] = "STALE"
        poc, val_b, vah_b = value_area(hist, cfg.value_area_pct)
        hvn, lvn = nodes(hist, poc, cfg)
        hi, lo = max(s.h[i] for i in idx), min(s.l[i] for i in idx)
        path, run = [], {}
        for i in idx:                                                    # developing POC as it was known bar by bar (incremental)
            for b, v in histogram(s, [i], bin_size, src).items():
                run[b] = run.get(b, 0.0) + v
            if run:
                path.append((s.close_time(i), max(run, key=lambda b: (run[b], -b))))
        prof.update(total_volume=round(total, 3), poc=round((poc + 0.5) * bin_size, 10), vah=round((vah_b + 1) * bin_size, 10),
                    val=round(val_b * bin_size, 10), hvn=[round((b + 0.5) * bin_size, 10) for b in hvn], lvn=[round((b + 0.5) * bin_size, 10) for b in lvn],
                    high=hi, low=lo, range=round(hi - lo, 10), poc_share=round(hist[poc] / total, 4),
                    poc_path=[{"at": iso(t), "poc": round((b + 0.5) * bin_size, 10)} for t, b in path[-24:]],
                    poc_migration_bins=(path[-1][1] - path[len(path) // 2][1]) if len(path) >= 4 else 0,
                    histogram=[{"price": round((b + 0.5) * bin_size, 10), "volume": round(v, 3)} for b, v in sorted(hist.items())])
        out.append(prof)
    _relative_volume(out, s, src)
    return out


def _relative_volume(profiles: list[dict], s: Series, src: str) -> None:
    """Relative volume vs the same session of previous days over the same elapsed time (COMPLETED baselines only)."""
    for i, p in enumerate(profiles):
        if p["state"] == "INVALID" or "total_volume" not in p:
            continue
        s0 = datetime.fromisoformat(p["start"].replace("Z", "+00:00")).timestamp()
        elapsed = datetime.fromisoformat(p["known_at"].replace("Z", "+00:00")).timestamp() - s0
        base = []
        for q in profiles[:i][::-1]:
            if q["session"] != p["session"] or q["state"] != "COMPLETED":
                continue
            q0 = datetime.fromisoformat(q["start"].replace("Z", "+00:00")).timestamp()
            vol = sum(_vol(s, j, src) for j in range(len(s)) if s.t[j] >= q0 and s.close_time(j) <= q0 + elapsed)
            base.append(vol)
            if len(base) >= 5:
                break
        so_far = sum(_vol(s, j, src) for j in range(len(s)) if s.t[j] >= s0 and s.close_time(j) <= s0 + elapsed)
        p["relative_volume"] = round(so_far / statistics.mean(base), 3) if base and statistics.mean(base) > 0 else None
        p["relative_volume_baseline_sessions"] = len(base)


def context(profiles: list[dict], price: float, s: Series) -> dict:
    """Where the current price stands relative to the developing and the last completed profiles."""
    dev = next((p for p in reversed(profiles) if p["state"] in ("DEVELOPING", "STALE") and "poc" in p), None)
    done = [p for p in profiles if p["state"] == "COMPLETED" and "poc" in p]
    prev = done[-1] if done else None

    def pos(p):
        if p is None:
            return None
        return "ABOVE_VA" if price > p["vah"] else "BELOW_VA" if price < p["val"] else "INSIDE_VA"
    out = {"current_session": dev["session"] if dev else None, "position_developing": pos(dev), "position_previous": pos(prev),
           "previous_profile_id": prev["profile_id"] if prev else None, "developing_profile_id": dev["profile_id"] if dev else None,
           "relative_volume": dev.get("relative_volume") if dev else None, "poc_migration_bins": dev.get("poc_migration_bins") if dev else None}
    if prev is not None and len(s):
        closes = s.c[-6:]
        out["acceptance_outside_previous_va"] = ("ABOVE" if all(c > prev["vah"] for c in closes) else
                                                 "BELOW" if all(c < prev["val"] for c in closes) else None)
        if dev is not None:
            d0 = datetime.fromisoformat(dev["start"].replace("Z", "+00:00")).timestamp()
            out["returned_to_previous_poc"] = any(s.l[i] <= prev["poc"] <= s.h[i] for i in range(len(s)) if s.t[i] >= d0)
    if dev is not None and dev.get("poc_path"):
        last = [x["poc"] for x in dev["poc_path"][-6:]]
        out["developing_poc_stable"] = (max(last) - min(last)) <= 2 * dev["bin_size"]
    return out


# --------------------------------------------------------------------------------------------- demand / supply
def demand_supply(s: Series, piv: list[dict], profiles: list[dict], refs: list[dict], cfg, tick: float, src: str) -> list[dict]:
    a = HZ.atr_series(s)
    n = len(s)
    out = []
    for pv in piv:
        if pv["provisional"]:
            continue
        i = pv["index"]
        at = pv["atr"]
        rng = s.h[i] - s.l[i]
        if rng <= 0 or not at:
            continue
        if pv["kind"] == "L":
            rejection = (min(s.o[i], s.c[i]) - s.l[i]) / rng >= 0.4 or (s.c[i] - s.l[i]) / rng >= 0.6
            disp_j = next((j for j in range(i + 1, min(n, i + 1 + cfg.displacement_bars)) if s.h[j] - s.l[i] >= cfg.displacement_atr * at), None)
        else:
            rejection = (s.h[i] - max(s.o[i], s.c[i])) / rng >= 0.4 or (s.h[i] - s.c[i]) / rng >= 0.6
            disp_j = next((j for j in range(i + 1, min(n, i + 1 + cfg.displacement_bars)) if s.h[i] - s.l[j] >= cfg.displacement_atr * at), None)
        if not rejection or disp_j is None:
            continue
        lo, up = HZ.pivot_zone(s, pv, cfg, tick)
        known = max(pv["confirmed_at"], s.close_time(disp_j))
        tol = max(cfg.cluster_tol_atr * at, cfg.min_width_ticks * tick)
        ctx = []
        for p in profiles:                                               # only profiles COMPLETED before the pivot became known
            if p.get("state") != "COMPLETED" or "poc" not in p:
                continue
            if datetime.fromisoformat(p["known_at"].replace("Z", "+00:00")).timestamp() > pv["confirmed_at"]:
                continue
            levels = [("POC", p["poc"])] + ([("VAL", p["val"])] if pv["kind"] == "L" else [("VAH", p["vah"])]) + \
                     [("LVN", x) for x in p.get("lvn", [])] + [("HVN", x) for x in p.get("hvn", [])]
            for name, lv in levels:
                if lo - tol <= lv <= up + tol:
                    ctx.append({"group": "volume", "kind": f"PROFILE_{name}", "root": f"{p['profile_id']}:{name}",
                                "detail": f"{name} {p['session']} {p['local_date']} ({src})", "evidence_type": "VOLUME_OBSERVATION"})
        for r in refs:
            if r["zone_type"].startswith(("PREVIOUS_DAY", "PREVIOUS_SESSION")) and r["lower"] - tol <= pv["price"] <= r["upper"] + tol \
                    and ((pv["kind"] == "L") == r["zone_type"].endswith("LOW")):
                ctx.append({"group": "structure", "kind": r["zone_type"], "root": r["evidence"][0]["root"] if r["evidence"] else r["zone_id"],
                            "detail": "zbieżność z ekstremum dnia/sesji", "evidence_type": "PRICE_ACTION_INFERENCE"})
        prior = [s.v[k] for k in range(max(0, i - 20), i) if s.v[k] > 0]
        if src == "TICK_VOLUME" and len(prior) >= 10 and s.v[i] >= 1.5 * statistics.median(prior):
            ctx.append({"group": "volume", "kind": "TICK_ACTIVITY_SPIKE", "root": f"{pv['pivot_id']}:tick",
                        "detail": f"aktywność tickowa {s.v[i]:.0f} ≥ 1,5 × mediana 20 świec (proxy, nie wolumen agresorów)",
                        "evidence_type": "VOLUME_OBSERVATION"})
        if not ctx:
            continue                                                     # price action alone does not make a demand / supply zone
        ztype = "DEMAND" if pv["kind"] == "L" else "SUPPLY"
        ev = [{"group": "structure", "kind": f"{s.tf}_SWING_{'LOW' if pv['kind'] == 'L' else 'HIGH'}", "root": pv["pivot_id"],
               "detail": "potwierdzony swing", "evidence_type": "PRICE_ACTION_INFERENCE"},
              {"group": "reaction", "kind": "REJECTION", "root": pv["pivot_id"] + ":rej", "detail": "odrzucenie na świecy pivotu",
               "evidence_type": "PRICE_ACTION_INFERENCE"},
              {"group": "reaction", "kind": "DISPLACEMENT", "root": pv["pivot_id"] + ":disp",
               "detail": f"ruch ≥ {cfg.displacement_atr} ATR w {disp_j - i} świecach", "evidence_type": "PRICE_ACTION_INFERENCE"}] + ctx
        z = HZ._zone(HZ._id("DZ", s.tf, ztype, s.t[i]), ztype, s, lo, up, pv["created_at"], known, at, evidence=ev,
                     sources=[pv["pivot_id"]], extra={"pivot_id": pv["pivot_id"], "attribution": "INFERRED_FROM_PRICE_ACTION_AND_VOLUME_CONTEXT",
                                                      "order_flow_verified": False, "volume_source": src})
        lc = HZ.lifecycle(s, a, side="LOW" if pv["kind"] == "L" else "HIGH", lower=lo, upper=up, start=disp_j, cfg=cfg,
                          max_age=cfg.max_age_bars.get(s.tf, 500), birth_index=i)
        out.append(HZ._apply(z, lc, n, i))
    return out


def build(s: Series, *, profile_id: str, instrument: str, cfg, as_of: float, tick: float, piv_by_tf: dict, series_by_tf: dict,
          refs: list[dict]) -> dict:
    src = volume_source(s)
    profiles = session_profiles(s, profile_id, instrument, cfg, as_of, src["source"]) if src["source"] != "NONE" else []
    ds = []
    for tf, piv in piv_by_tf.items():
        st = series_by_tf.get(tf)
        if st is not None and len(st):
            ds.extend(demand_supply(st, piv, profiles, refs, cfg, tick, volume_source(st)["source"]))
    price = s.c[-1] if len(s) else None
    return {"version": VERSION, "volume_source": src, "profile_id": profile_id, "profiles": profiles, "demand_supply": ds,
            "context": context(profiles, price, s) if price is not None else {}}


def now_utc() -> float:
    return datetime.now(timezone.utc).timestamp()
