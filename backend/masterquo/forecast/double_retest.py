"""MasterQUO Gold Double Retest 5/10/15 - Execution Lock v2: research state machine (DR-V2-1.0.0).

One strategy, BUY and SELL are mirror directions (SELL is evaluated on negated prices, so every rule is written once).
Input: the bot's closed M5/M30 bars (UTC) and the gold_candles pattern flags of the same M5 bars (one pattern definition
for forecasts and triggers). The whole buffer is replayed deterministically on every new closed M5, so a restart or a
model reload can neither duplicate nor resurrect a setup (setup_id = direction + L + ARMED time).

States: IDLE, WAIT_LOCATION, ARMED, FIRST_EPISODE_CONFIRMED, DOUBLE_EPISODE_CONFIRMED, RECLAIM_CONFIRMED, RETEST_STARTED,
CANDLE_TRIGGER_CONFIRMED -> RESEARCH_SETUP_COMPLETE; terminal INVALIDATED / EXPIRED. READY_BUY / READY_SELL are NOT
reachable here: the strategy has no strategy backtest (VALIDATION_STATE=NOT_VALIDATED), so EXECUTION_STATE stays BLOCKED.
Parameters: config_strategy_v2_research.json (starting hypotheses, not optimal values)."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

VERSION = "DR-V2-1.0.0"
G = 5.0
P = {"slope": 0.05, "eps_a5": 0.05, "bounce_a5": 0.20, "probe_a5": 0.25, "probe_g": 0.25, "ttl_min": 60, "retest_bars": 6, "confirm_bars": 2,
     "cooldown_bars": 3, "loc_a30": 0.10, "loc_max_g": 0.25, "pivot_fresh_m30": 6}
REJECTION = {1: "lower_wick_rejection", -1: "upper_wick_rejection"}
CONTINUATION = {1: ("bullish_engulfing", "bullish_outside_close", "bullish_displacement", "inside_break_bull"),
                -1: ("bearish_engulfing", "bearish_outside_close", "bearish_displacement", "inside_break_bear")}
SESSIONS = (("ASIA", "UTC", 0, 0, 8, 0), ("LONDON", "Europe/London", 8, 0, 16, 0), ("NEW_YORK", "America/New_York", 8, 0, 17, 0))
STATE_PL = {"IDLE": "brak kontekstu do wejścia", "WAIT_LOCATION": "czeka na lokalizację poziomu L", "ARMED": "uzbrojony – czeka na 1. epizod w strefie",
            "FIRST_EPISODE_CONFIRMED": "1. epizod potwierdzony – czeka na reset i 2. epizod",
            "DOUBLE_EPISODE_CONFIRMED": "2 epizody – czeka na odzyskanie L (reclaim)", "RECLAIM_CONFIRMED": "reclaim – czeka na retest L",
            "RETEST_STARTED": "retest L – czeka na świecę potwierdzenia", "RESEARCH_SETUP_COMPLETE": "setup kompletny (badawczy – bez zgody na zlecenie)",
            "INVALIDATED": "unieważniony", "EXPIRED": "wygasł (TTL 60 min)"}


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _bars(rows: list[dict], sign: int, minutes: int) -> list[dict]:
    out = []
    for r in rows:
        o, h, l, c = r["o"], r["h"], r["l"], r["c"]
        if sign < 0:
            o, h, l, c = -o, -l, -h, -c
        t = _t(r["open_utc"])
        out.append({"t": t, "close_t": t + timedelta(minutes=minutes), "o": o, "h": h, "l": l, "c": c, "raw": r})
    return out


def atr14(b: list[dict]) -> list[float | None]:
    out: list[float | None] = [None] * len(b)
    tr = []
    for i, x in enumerate(b):
        pc = b[i - 1]["c"] if i else None
        tr.append(x["h"] - x["l"] if pc is None else max(x["h"] - x["l"], abs(x["h"] - pc), abs(x["l"] - pc)))
        if i == 13:
            out[i] = sum(tr) / 14
        elif i > 13:
            out[i] = (out[i - 1] * 13 + tr[i]) / 14
    return out


def ema20(b: list[dict]) -> list[float | None]:
    out: list[float | None] = [None] * len(b)
    a = 2 / 21
    for i in range(len(b)):
        if i == 19:
            out[i] = sum(x["c"] for x in b[:20]) / 20         # SMA seed (recorded method)
        elif i > 19:
            out[i] = a * b[i]["c"] + (1 - a) * out[i - 1]
    return out


def pivots(b: list[dict]) -> list[dict]:
    """2-left/2-right pivots, usable only from confirmed_at (close of the 2nd bar on the right)."""
    out = []
    for i in range(2, len(b) - 2):
        if all(b[i]["l"] < b[j]["l"] for j in (i - 2, i - 1, i + 1, i + 2)):
            out.append({"kind": "LOW", "price": b[i]["l"], "bar_t": b[i]["t"], "confirmed_at": b[i + 2]["close_t"]})
        if all(b[i]["h"] > b[j]["h"] for j in (i - 2, i - 1, i + 1, i + 2)):
            out.append({"kind": "HIGH", "price": b[i]["h"], "bar_t": b[i]["t"], "confirmed_at": b[i + 2]["close_t"]})
    return out


def session_levels(m5: list[dict], at: datetime) -> list[dict]:
    """High/low of the last COMPLETED session of each kind, still valid at `at` (not swept / closed beyond, next session of
    the same kind not started)."""
    out = []
    for name, tz, sh, sm, eh, em in SESSIONS:
        z = ZoneInfo(tz)
        loc = at.astimezone(z)
        for back in range(0, 4):
            d = (loc - timedelta(days=back)).date()
            s = datetime(d.year, d.month, d.day, sh, sm, tzinfo=z).astimezone(timezone.utc)
            e = datetime(d.year, d.month, d.day, eh, em, tzinfo=z).astimezone(timezone.utc)
            if e <= at:
                break
        else:
            continue
        nxt = s + timedelta(days=1)
        if at >= nxt:
            continue
        inside = [x for x in m5 if s <= x["t"] and x["close_t"] <= e]
        if len(inside) < 12:
            continue
        hi, lo = max(x["h"] for x in inside), min(x["l"] for x in inside)
        after = [x for x in m5 if e <= x["t"] and x["close_t"] <= at]
        if not any(x["h"] > hi for x in after):
            out.append({"kind": f"{name}_HIGH", "price": hi, "confirmed_at": e})
        if not any(x["l"] < lo for x in after):
            out.append({"kind": f"{name}_LOW", "price": lo, "confirmed_at": e})
    return out


def context_at(m30: list[dict], a30: list, e30: list, piv: list[dict], at: datetime, tick: float) -> dict:
    idx = max((i for i, x in enumerate(m30) if x["close_t"] <= at), default=None)
    if idx is None or idx < 3 or e30[idx] is None or a30[idx] is None or e30[idx - 3] is None:
        return {"direction": "UNKNOWN", "reason": "WARMUP_M30"}
    x, atr, ema = m30[idx], a30[idx], e30[idx]
    slope = (ema - e30[idx - 3]) / atr if atr else 0.0
    eps30 = max(2 * tick, 0.05 * atr)
    fresh_from = m30[max(0, idx - P["pivot_fresh_m30"] + 1)]["t"]
    lows = [p for p in piv if p["kind"] == "LOW" and p["confirmed_at"] <= at]
    recent = [p for p in lows if p["bar_t"] >= fresh_from - timedelta(minutes=60)]
    base = {"m30_close_utc": x["close_t"], "close": x["c"], "ema20": ema, "atr14_m30": atr, "slope": slope, "eps30": eps30, "idx": idx}
    if not (x["c"] > ema and slope >= P["slope"]):
        return {**base, "direction": "TRANSITION", "reason": "close<=EMA20 lub nachylenie < 0.05"}
    if not recent:
        return {**base, "direction": "UNKNOWN", "reason": "brak potwierdzonego pivotu w ostatnich 6 M30"}
    last = max(recent, key=lambda p: p["confirmed_at"])
    if x["c"] < last["price"] - eps30:
        return {**base, "direction": "TRANSITION", "reason": "naruszenie struktury (zamknięcie pod pivot low)"}
    return {**base, "direction": "WITH", "last_pivot": last["price"]}


def locate(ctx: dict, piv: list[dict], sess: list[dict], at: datetime, tick: float) -> dict | None:
    L = math.floor(ctx["close"] / G) * G
    tol = min(max(2 * tick, P["loc_a30"] * ctx["atr14_m30"]), P["loc_max_g"] * G)
    cands = [p for p in piv if p["confirmed_at"] <= at] + sess
    near = [p for p in cands if abs(p["price"] - L) <= tol]
    if not near or not ctx["close"] > L + ctx["eps30"]:
        return None
    ref = min(near, key=lambda p: abs(p["price"] - L))
    return {"L": L, "tolerance": tol, "trace": ref["kind"], "trace_price": ref["price"], "trace_confirmed_at": ref["confirmed_at"]}


def run_direction(m5raw, m30raw, flags: dict, tick: float, sign: int) -> dict:
    m5, m30 = _bars(m5raw, sign, 5), _bars(m30raw, sign, 30)
    a5, a30, e30 = atr14(m5), atr14(m30), ema20(m30)
    piv = pivots(m30)
    done: list[dict] = []
    s: dict | None = None
    cooldown: dict = {}
    last_ctx: dict = {}
    for i, x in enumerate(m5):
        at = x["close_t"]
        gap = i > 0 and x["t"] - m5[i - 1]["t"] != timedelta(minutes=5)
        names = set(flags.get(x["raw"]["open_utc"].replace("Z", "+00:00"), flags.get(x["raw"]["open_utc"], [])) or [])
        if s:                                                  # ---- advance the active setup with this closed bar
            s = step(s, x, i, m5, a5, names, sign, gap, done, cooldown)
            if s:
                continue
        ctx = context_at(m30, a30, e30, piv, at, tick)
        last_ctx = ctx
        if ctx["direction"] != "WITH" or a5[i] is None:
            continue
        loc = locate(ctx, piv, session_levels(m5[max(0, i - 400): i + 1], at), at, tick)
        if not loc or cooldown.get(loc["L"], -99) > i:
            continue
        A5 = a5[i]
        L = loc["L"]
        s = {"setup_id": f"DRV2:{'BUY' if sign > 0 else 'SELL'}:{L * sign:g}:{at.strftime('%Y%m%dT%H%MZ')}", "state": "ARMED", "L": L, "A5": A5,
             "A30": ctx["atr14_m30"], "tick": tick, "armed_at": at, "expires_at": at + timedelta(minutes=P["ttl_min"]), "location": loc,
             "eps": max(2 * tick, P["eps_a5"] * A5), "bounce": max(4 * tick, P["bounce_a5"] * A5), "probe": min(P["probe_a5"] * A5, P["probe_g"] * G),
             "zone": [L - 1.5 * G, L - G], "episodes": [], "in_episode": None, "reset_count": 0, "reclaim": None, "retest": None, "trigger": None,
             "context": {k: ctx[k] for k in ("m30_close_utc", "ema20", "atr14_m30", "slope")}}
    return {"active": s, "done": done[-10:], "context": last_ctx, "m5_last": m5[-1]["close_t"] if m5 else None}


def _end(s, state, reason, at, done, cooldown, i):
    s.update(state=state, end_reason=reason, ended_at=at)
    done.append(s)
    cooldown[s["L"]] = i + 1 + P["cooldown_bars"]
    return None


def step(s, x, i, m5, a5, names, sign, gap, done, cooldown):
    at = x["close_t"]
    lo_z, hi_z = s["zone"]
    L, eps, probe = s["L"], s["eps"], s["probe"]
    if gap:
        return _end(s, "INVALIDATED", "DATA_GAP – luka w M5 podczas aktywnego setupu", at, done, cooldown, i)
    if at > s["expires_at"]:
        return _end(s, "EXPIRED", "TTL 60 min od ARMED", at, done, cooldown, i)
    if a5[i] is not None and not (0.5 * s["A5"] <= a5[i] <= 1.5 * s["A5"]):
        return _end(s, "INVALIDATED", "REGIME_CHANGE – ATR5 poza [0.5, 1.5]×A5", at, done, cooldown, i)
    if x["c"] < lo_z - eps or x["l"] < lo_z - probe:
        return _end(s, "INVALIDATED", "zamknięcie pod strefą albo zbyt głęboki probe", at, done, cooldown, i)
    st = s["state"]
    if st in ("ARMED", "FIRST_EPISODE_CONFIRMED"):
        if s["in_episode"] is None:
            ready = st == "ARMED" or s["reset_count"] >= 2
            if ready and x["l"] <= hi_z and x["h"] >= lo_z:
                s["in_episode"] = {"contact_at": at}
            elif st == "FIRST_EPISODE_CONFIRMED" and x["l"] > hi_z + eps:
                s["reset_count"] += 1
        if s["in_episode"] is not None and x["c"] > hi_z + s["bounce"]:
            s["episodes"].append({"contact_at": s["in_episode"]["contact_at"], "confirmed_at": at, "close": x["c"]})
            s["in_episode"], s["reset_count"] = None, 0
            s["state"] = "FIRST_EPISODE_CONFIRMED" if len(s["episodes"]) == 1 else "DOUBLE_EPISODE_CONFIRMED"
        st = s["state"]
    if st == "DOUBLE_EPISODE_CONFIRMED":
        if x["c"] > L + eps:
            s.update(state="RECLAIM_CONFIRMED", reclaim={"at": at, "close": x["c"], "bar": i})
        return s
    if st == "RECLAIM_CONFIRMED":
        if i - s["reclaim"]["bar"] > P["retest_bars"]:
            return _end(s, "INVALIDATED", "brak retestu L w 6 M5 po reclaimie", at, done, cooldown, i)
        if x["c"] < L - eps:
            return _end(s, "INVALIDATED", "zamknięcie po drugiej stronie L", at, done, cooldown, i)
        if x["l"] <= L + eps and x["h"] >= L - eps:
            s.update(state="RETEST_STARTED", retest={"contact_at": at, "bar": i, "low": x["l"]})
        else:
            return s
    if s["state"] == "RETEST_STARTED":
        s["retest"]["low"] = min(s["retest"]["low"], x["l"])
        if x["c"] < L - eps or x["l"] < L - probe:
            return _end(s, "INVALIDATED", "utrata L w oknie retestu", at, done, cooldown, i)
        fam = "REJECTION" if REJECTION[sign] in names else "CONTINUATION" if any(n in names for n in CONTINUATION[sign]) else None
        if x["c"] > L + eps and fam and x["h"] > x["l"]:
            s.update(state="RESEARCH_SETUP_COMPLETE", trigger={"at": at, "family": fam, "patterns": sorted(names), "close": x["c"],
                                                              "observed_retest_low": s["retest"]["low"]})
            return _end(s, "RESEARCH_SETUP_COMPLETE", "trigger świecowy potwierdzony (badawczo)", at, done, cooldown, i)
        if i - s["retest"]["bar"] + 1 >= P["confirm_bars"]:
            return _end(s, "INVALIDATED", "brak świecy potwierdzenia w oknie 2 M5", at, done, cooldown, i)
    return s


def _public(s: dict | None, sign: int, tick: float) -> dict | None:
    if s is None:
        return None
    f = (lambda v: None if v is None else round(v * sign, 6))
    zone = sorted([f(s["zone"][0]), f(s["zone"][1])])
    nxt = {"ARMED": f"zamknięta M5 w strefie {zone[0]:g}–{zone[1]:g} i odbicie o ≥ {s['bounce']:.2f}",
           "FIRST_EPISODE_CONFIRMED": f"2 zamknięte M5 poza strefą (reset {s['reset_count']}/2), potem nowy kontakt i odbicie",
           "DOUBLE_EPISODE_CONFIRMED": f"zamknięcie M5 {'powyżej' if sign > 0 else 'poniżej'} {f(s['L'] + s['eps'] * 1):g} (reclaim L)",
           "RECLAIM_CONFIRMED": f"retest pasma L ±{s['eps']:.2f} w ≤ 6 M5", "RETEST_STARTED": "świeca REJECTION albo CONTINUATION w ≤ 2 M5"}.get(s["state"])
    iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(d, datetime) else d   # noqa: E731
    return {"setup_id": s["setup_id"], "direction": "BUY" if sign > 0 else "SELL", "state": s["state"], "state_pl": STATE_PL.get(s["state"], s["state"]),
            "L": f(s["L"]), "deep_zone": zone, "epsilon": round(s["eps"], 4), "bounce_min": round(s["bounce"], 4), "probe_allowance": round(s["probe"], 4),
            "A5": round(s["A5"], 4), "A30": round(s["A30"], 4), "armed_at": iso(s["armed_at"]), "expires_at": iso(s["expires_at"]),
            "location": {**s["location"], "L": f(s["location"]["L"]), "trace_price": f(s["location"]["trace_price"]),
                         "trace_confirmed_at": iso(s["location"]["trace_confirmed_at"])},
            "episodes": [{"contact_at": iso(e["contact_at"]), "confirmed_at": iso(e["confirmed_at"]), "close": f(e["close"])} for e in s["episodes"]],
            "reclaim": s["reclaim"] and {"at": iso(s["reclaim"]["at"]), "close": f(s["reclaim"]["close"])},
            "retest": s["retest"] and {"contact_at": iso(s["retest"]["contact_at"]), "extreme": f(s["retest"]["low"])},
            "trigger": s["trigger"] and {**s["trigger"], "at": iso(s["trigger"]["at"]), "close": f(s["trigger"]["close"]),
                                        "observed_retest_extreme": f(s["trigger"]["observed_retest_low"])},
            "targets_hypothetical": [f(s["L"] + G), f(s["L"] + 2 * G)], "next_required_event": nxt,
            "invalidation": f"zamknięcie M5 {'poniżej' if sign > 0 else 'powyżej'} {f(s['zone'][0] - s['eps']):g} albo knot poza {f(s['zone'][0] - s['probe']):g}; "
                            f"TTL do {iso(s['expires_at'])}; luka danych; zmiana reżimu ATR5",
            "end_reason": s.get("end_reason"), "ended_at": iso(s.get("ended_at"))}


class DoubleRetest:
    def update(self, m5: list[dict], m30: list[dict], flags: dict, tick: float) -> dict:
        res = {"version": VERSION, "strategy": "MasterQUO Gold Double Retest 5/10/15 – Execution Lock v2", "states": {}}
        for sign in (1, -1):
            r = run_direction(m5, m30, flags, tick, sign)
            side = "BUY" if sign > 0 else "SELL"
            ctx = r["context"] or {}
            want = "BULLISH" if sign > 0 else "BEARISH"
            res["states"][side] = {"context": want if ctx.get("direction") == "WITH" else ctx.get("direction") or "UNKNOWN",
                                   "context_reason": ctx.get("reason"), "m30_slope_atr": None if ctx.get("slope") is None else round(ctx["slope"] * sign, 3),
                                   "active": _public(r["active"], sign, tick), "recent": [_public(d, sign, tick) for d in reversed(r["done"])],
                                   "state": r["active"]["state"] if r["active"] else ("WAIT_LOCATION" if ctx.get("direction") == "WITH" else "IDLE")}
            res["states"][side]["state_pl"] = STATE_PL.get(res["states"][side]["state"], res["states"][side]["state"])
        res.update(DATA_STATE="CLOSED_BARS_FROM_BOT_SESSION", VALIDATION_STATE="NOT_VALIDATED (STRATEGY_BACKTEST_NOT_AVAILABLE)",
                   EXECUTION_STATE="BLOCKED", can_submit_order=False,
                   block_reasons=["brak backtestu P&L tej wersji strategii (Bid/Ask, koszty)", "TRADING_ENABLED=false, ML_EXECUTION=false",
                                  "koszty / ryzyko / kalendarz / tick wykonania nie są oceniane przez tę maszynę stanów"],
                   note="Najwyższy osiągalny stan to RESEARCH_SETUP_COMPLETE – to nie jest sygnał „kup/sprzedaj teraz”.")
        return res
