"""S12 WALLS_RANGE_FAMILY (1.0.0-CANDIDATE) - one family, three explicit variants, one arbiter, shared risk/exit policy.

Status: CANDIDATE / FUNCTIONAL_ONLY - deterministic rules that run end to end (scan, checklist, risk, PAPER/replay); there
is NO evidence of a positive expectancy. Default: scan ON, trade OFF (an explicit user switch).  The parameters below are
working engineering hypotheses fixed before any study, not "optimal settings".

Flow: higher-TF context -> S/R zones and walls -> regime -> structure (M5 range / chart pattern) -> CLOSED trigger candle
-> costs and risk (shared engine) -> ONE decision.  A recognised pattern never means an entry.

Variants (LONG rules; SHORT = the same code on the price-mirrored view, walls mirrored with it):
A. RANGE_RECLAIM (setup TF M1) - consolidation M5, entry on M1 back into the range
   range: analysis/range_m5 (closed M5, frozen at recognition, accepted breakout = no edge-to-edge trade);
   lower local zone: analysis/range_m5.local_zones (M1 reaction cluster, wick-to-body, frozen with the range);
   1 contact: an M1 bar AFTER the freeze reaches the lower zone (low <= zone_high);
   2 reaction: sweep below zone_low, OR a bullish candle evidence event on M1 (engulfing / pin bar / hammer / morning star /
     tweezer / outside-bar rejection / inside-bar break up), OR a higher low on M1 after the contact;
   3 trigger: the last CLOSED M1 bar closes above zone_high + buffer, the previous close did not (first reclaim close),
     within `trigger_window_m1` bars of the contact - a reclaim of the LOCAL zone, NOT a breakout of the whole range;
   4 activity: tick volume of the trigger >= activity_ratio x median of the previous 30 closed M1 bars (trigger excluded),
     body/range >= body_ratio, close location >= clv_long. No tick volume -> ACTIVITY_NO_DATA (never "met"); with
     activity_filter = OFF the filter is skipped as an explicit, separately studied variant;
   5 entry (Ask) not above the range midpoint (PRICE_IN_MIDDLE) and <= max_entry_atr x ATR(M5) above zone_high
     (ENTRY_TOO_LATE); SL below min(sweep low, zone_low) - sl_buffer_atr x ATR(M5); TP1 = range midpoint (50%),
     TP2 = range top - 10% height (50%); weighted gross RR >= rr_min_gross (the shared risk engine then checks RR net);
   6 walls variant (use_walls = True): a CURRENT lower wall (snapshot available before the trigger, not expired) whose zone
     lies within wall_proximity_atr x ATR(M5) of the reaction zone; else NO_WALL_ALIGNMENT / WALL_STALE.
     use_walls = False -> variant RANGE_RECLAIM_BASE: the same method WITHOUT walls (baseline for comparison, never called IV).
B. WALL_REJECTION (setup TF M5) - rejection of a volatility wall
   a current lower wall (k = 1 first, then 2); a closed M5 bar pierced the wall LEVEL within `rejection_lookback_m5` bars;
   two consecutive closes below the wall zone = ACCEPTED_BEYOND_WALL (no trade); a bar >= max_expansion_atr x ATR since the
   touch = EXPANSION_NO_TRADE; trigger = first CLOSED M5 bar back above the wall zone; activity + candle evidence as in A;
   context for mean reversion: H1 and H4 both DOWN with regime TREND_DOWN -> HTF_CONFLICT.
   SL = lowest low since the touch - buffer; targets: Daily Open (the walls' anchor) and the M5 range midpoint if above,
   else 1R / 2R marked R_MULTIPLE_NO_STRUCTURE.  A touch of +-1/2 sigma alone is never a signal.
C. BREAKOUT_RETEST (setup TF M1) - accepted breakout of the frozen M5 range, retest, continuation
   breakout = the range's accepted breakout (analysis/range_m5) with body >= 0.5 range on the breakout M5 bar; walls
   variant: the breakout close is also beyond the nearest upper wall within 1 ATR above the range top;
   retest: an M5 low back to top + retest_tol_atr x ATR within retest_window_m5 bars (else RETEST_MISSING); a close below
   top - fail_atr x ATR = FAILED_BREAKOUT (no trade here - S07 / RANGE_RECLAIM describe the reclaim);
   trigger: first CLOSED M1 bar after the retest closing above the highest M1 high since the retest started;
   SL = retest low - buffer; TP1 = top + height, TP2 = top + 2 x height (measured move - a proposal, not a promise).
Arbiter: per direction ONE draft - the variant that fits the regime (RANGE/COMPRESSION: A, B, C; EXPANSION/TREND: C, B, A;
otherwise B, A, C), the most advanced phase first. If both directions are at EARLY/TRIGGER at once (rejection vs breakout)
both are reduced to WATCH with CONFLICT_REJECTION_VS_BREAKOUT (WAIT) - never two opposite positions from one event.
The walls snapshot id is part of the scenario identity: new IV / a recalculated snapshot creates a NEW scenario version and
never moves an earlier trigger / SL.  Exit policy (shared, stored at open): BE after TP1, time exit per variant.
"""
from __future__ import annotations

from datetime import timedelta

from ..analysis import candles as CN
from ..analysis import chart_patterns as CH
from ..analysis import range_m5 as RG
from ..analysis import walls as W
from ..timeutil import iso, parse_iso
from .base import Draft, MarketView, Strategy, mirror_view, unmirror_draft
from .common import plan, valid_targets

VARIANTS = ("RANGE_RECLAIM", "WALL_REJECTION", "BREAKOUT_RETEST")
REJECT_PL = {
    "NO_RANGE": "brak konsolidacji M5 spełniającej definicję", "RANGE_ACCEPTED_BREAKOUT": "zakres M5 wybity i zaakceptowany – handel od krawędzi do krawędzi nieaktualny",
    "NO_M1_REACTION_ZONE": "brak lokalnej strefy reakcji M1 przy krawędzi zakresu", "M1_HISTORY_DOES_NOT_COVER_RANGE": "historia M1 nie obejmuje okresu zakresu",
    "PRICE_IN_MIDDLE": "cena w środku zakresu – wejście tylko po powrocie do strefy", "NO_CONTACT": "cena nie dotknęła strefy reakcji",
    "NO_WALL_ALIGNMENT": "brak właściwej strefy zmienności (wall) przy strefie reakcji", "WALL_STALE": "brak aktualnego snapshotu walls",
    "NO_CLOSED_TRIGGER": "brak zamkniętej świecy wyzwalającej", "NO_REACTION": "brak reakcji (sweep / formacja świecowa / wyższy dołek)",
    "VOLUME_NOT_CONFIRMED": "aktywność (tick volume) poniżej progu", "ACTIVITY_NO_DATA": "brak danych o aktywności (tick volume)",
    "TRIGGER_CANDLE_WEAK": "świeca wyzwalająca za słaba (korpus / miejsce zamknięcia)", "RETEST_MISSING": "brak retestu w oknie czasu",
    "FAILED_BREAKOUT": "wybicie nieudane – powrót do zakresu", "BREAKOUT_WEAK": "świeca wybicia za słaba", "RR_NET_TOO_LOW": "za mały stosunek zysku do ryzyka",
    "ENTRY_TOO_LATE": "cena odjechała za daleko od strefy (gonienie ceny)", "HTF_CONFLICT": "konflikt z kierunkiem wyższych interwałów",
    "DATA_MISSING": "brak wymaganych danych", "ACCEPTED_BEYOND_WALL": "akceptacja ceny poza wall – brak odbicia",
    "EXPANSION_NO_TRADE": "silna ekspansja – odrzucenie wall niewiarygodne", "TRIGGER_WINDOW_EXPIRED": "wyzwalacz poza oknem czasu od kontaktu",
    "CONFLICT_REJECTION_VS_BREAKOUT": "sprzeczne hipotezy (odrzucenie vs wybicie) – CZEKAJ", "NO_WALL_TOUCH": "brak dotknięcia wall",
    "RANGE_NOT_BROKEN": "brak zaakceptowanego wybicia zakresu", "NO_WALLS": "brak walls (źródło niedostępne)"}
REACTION_TYPES = {"ENGULFING_BULL", "PIN_BAR_BULL", "HAMMER", "MORNING_STAR", "TWEEZER_BOTTOM", "OUTSIDE_BAR_REJECTION", "INSIDE_BAR_BREAK_UP",
                  "OUTSIDE_BAR_EXPANSION", "MARUBOZU_DISPLACEMENT"}
PAIRS = (("zone_low_px", "zone_high_px"), ("range_bottom_px", "range_top_px"), ("wall_low_px", "wall_high_px"))


def _close_t(t: str, minutes: int) -> str:
    return iso(parse_iso(t) + timedelta(minutes=minutes))


def _median(xs):
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def activity(v, i: int, p: dict) -> dict:
    """Tick-volume activity of bar i vs the median of the previous N closed bars of the SAME TF (bar i excluded) + candle
    strength. Tick volume of a CFD = activity of the broker feed, not exchange volume and not 'institutional flow'."""
    n = int(p["activity_median_n"])
    rng = v.h[i] - v.l[i]
    body = abs(v.c[i] - v.o[i])
    clv = (v.c[i] - v.l[i]) / rng if rng > 0 else None
    prev = [x for x in v.tv[max(0, i - n):i]]
    med = _median(prev) if len(prev) >= max(5, n // 2) else None
    ratio = None if (med is None or med <= 0 or v.tv[i] <= 0) else v.tv[i] / med
    candle_ok = rng > 0 and body / rng >= p["body_ratio"] and clv is not None and clv >= p["clv_long"]
    if p.get("activity_filter", "REQUIRED") == "OFF":
        st = "NOT_APPLIED"
    elif ratio is None:
        st = "NO_DATA"
    else:
        st = "OK" if ratio >= p["activity_ratio"] else "LOW"
    return {"status": st, "ratio": None if ratio is None else round(ratio, 2), "median": med, "tv": v.tv[i],
            "body_ratio": round(body / rng, 2) if rng > 0 else None, "clv": None if clv is None else round(clv, 2), "candle_ok": candle_ok}


def _walls_state(view: MarketView, at: str | None) -> dict:
    snap = (view.context or {}).get("walls")
    if not snap or snap.get("status") != "OK":
        return {"status": "NO_WALLS" if not snap else snap.get("status", "UNAVAILABLE"), "snap": snap}
    if at is not None and (snap.get("available_at") or "") > at:
        return {"status": "WALL_STALE", "snap": snap, "why": "snapshot dostępny dopiero po świecy wyzwalającej"}
    if view.as_of and snap.get("valid_until") and snap["valid_until"] < view.as_of:
        return {"status": "WALL_STALE", "snap": snap, "why": "snapshot wygasł"}
    return {"status": "OK", "snap": snap}


def _lower_walls(snap: dict) -> list[dict]:
    return sorted([w for w in snap.get("walls") or [] if w["side"] == "LOWER"], key=lambda w: w["k"])


def _upper_walls(snap: dict) -> list[dict]:
    return sorted([w for w in snap.get("walls") or [] if w["side"] == "UPPER"], key=lambda w: w["k"])


class WallsRangeFamily(Strategy):
    id = "S12"
    name = "WALLS_RANGE_FAMILY"
    version = "1.0.0-CANDIDATE"
    family = "RANGE_WALLS"
    horizon = "INTRADAY"
    setup_tfs = ("M1", "M5")
    context_tf = "H1"
    required_tfs = ("M1", "M5")
    min_bars = 80
    regime_fit = {"RANGE": 1.0, "COMPRESSION": 0.8, "TRANSITION": 0.7, "EXHAUSTION_OR_REVERSAL_CANDIDATE": 0.6, "EXPANSION": 0.6,
                  "TREND_UP": 0.5, "TREND_DOWN": 0.5}
    params = {"variants": list(VARIANTS), "use_walls": True, "range_lookbacks": [18, 12, 24], "range_min_h_atr": 1.0, "range_max_h_atr": 6.0,
              "range_max_er": 0.35, "range_edge_frac": 0.2, "range_min_touches": 2, "range_max_age": 48, "zone_max_atr": 0.6,
              "buffer_atr": 0.05, "trigger_window_m1": 20, "max_entry_atr": 0.5, "sl_buffer_atr": 0.15, "activity_filter": "REQUIRED",
              "activity_ratio": 1.2, "activity_median_n": 30, "body_ratio": 0.45, "clv_long": 0.65, "wall_proximity_atr": 0.5,
              "rr_min_gross": 1.2, "retest_window_m5": 12, "retest_tol_atr": 0.25, "fail_atr": 0.25, "rejection_lookback_m5": 6,
              "max_expansion_atr": 2.5, "time_exit_m1": 90, "time_exit_breakout_m1": 120, "time_exit_m5": 36, "expires_bars": 3}
    validation_status = "CANDIDATE_FUNCTIONAL_ONLY_OOS_NOT_RUN"

    def __init__(self):
        self.last_rejections: dict = {}

    # ------------------------------------------------------------ family entry point (arbiter over both directions)
    def detect(self, view: MarketView, p: dict) -> list[Draft]:
        longs, rej_l = self._side(view, p)
        mv = mirror_view(view)
        mv.context = {"walls": W.mirror((view.context or {}).get("walls"), 2 * mv.center)}
        shorts_m, rej_s = self._side(mv, p)
        shorts = []
        for c in shorts_m:
            c["draft"] = unmirror_draft(c["draft"], mv.center)
            _swap_pairs(c["draft"].facts)
            shorts.append(c)
        out = self._arbiter(view, longs, shorts)
        for d in out:
            d.strategy_id = self.id
            d.facts["checklist"] = checklist_rows(d, p)
        self.last_rejections = {"LONG": rej_l, "SHORT": rej_s}
        return out

    def detect_long(self, view: MarketView, p: dict) -> list[Draft]:
        return [c["draft"] for c in self._side(view, p)[0]]

    def _arbiter(self, view, longs, shorts):
        state = (view.regime or {}).get("state")
        if state in ("RANGE", "COMPRESSION"):
            pri = ["RANGE_RECLAIM", "WALL_REJECTION", "BREAKOUT_RETEST"]
        elif state in ("EXPANSION", "TREND_UP", "TREND_DOWN"):
            pri = ["BREAKOUT_RETEST", "WALL_REJECTION", "RANGE_RECLAIM"]
        else:
            pri = ["WALL_REJECTION", "RANGE_RECLAIM", "BREAKOUT_RETEST"]
        rank = {"WATCH": 0, "EARLY": 1, "TRIGGER": 2}
        best = {}
        for side, cands in (("LONG", longs), ("SHORT", shorts)):
            if not cands:
                continue
            # most advanced first: TRIGGER > EARLY with a closed trigger candle (blocked by a gate) > EARLY > WATCH; then regime priority
            cands.sort(key=lambda c: (-(2 * rank[c["draft"].phase] + (1 if c["draft"].phase == "EARLY" and "NO_CLOSED_TRIGGER" not in c["draft"].missing else 0)),
                                      pri.index(c["variant"])))
            b = cands[0]
            b["draft"].facts["alternatives"] = [{"variant": c["draft"].facts.get("variant"), "phase": c["draft"].phase,
                                                 "missing": c["draft"].missing[:6]} for c in cands[1:]]
            b["draft"].facts["arbiter"] = "SELECTED_BY_REGIME_" + str(state)
            best[side] = b["draft"]
        if len(best) == 2 and all(d.phase in ("EARLY", "TRIGGER") for d in best.values()):
            for d in best.values():
                d.phase = "WATCH"
                d.missing.append("CONFLICT_REJECTION_VS_BREAKOUT")
                d.facts["arbiter"] = "WAIT_CONFLICT"
                d.components["trigger"] = 0.0
        return list(best.values())

    # ------------------------------------------------------------ one direction (LONG rules)
    def _side(self, view: MarketView, p: dict) -> tuple[list[dict], dict]:
        m5, m1 = view.tfs.get("M5"), view.tfs.get("M1")
        rej: dict[str, list[str]] = {}
        if m5 is None or m1 is None or len(m5) < 60 or len(m1) < 40:
            return [], {v: ["DATA_MISSING"] for v in VARIANTS}
        rp = {"lookbacks": p["range_lookbacks"], "min_h_atr": p["range_min_h_atr"], "max_h_atr": p["range_max_h_atr"], "max_er": p["range_max_er"],
              "edge_frac": p["range_edge_frac"], "min_touches": p["range_min_touches"], "max_age": p["range_max_age"], "zone_max_atr": p["zone_max_atr"]}
        rng = RG.detect(m5, rp)
        out = []
        variants = [v for v in p.get("variants", VARIANTS) if v in VARIANTS]
        for var in variants:
            fn = {"RANGE_RECLAIM": self._range_reclaim, "WALL_REJECTION": self._wall_rejection, "BREAKOUT_RETEST": self._breakout_retest}[var]
            c, why = fn(view, p, rng, rp)
            if c is not None:
                out.append(c)
            else:
                rej[var] = why
        return out, rej

    def _common_facts(self, view, p, var, rng):
        use_w = bool(p.get("use_walls", True))
        name = var if (use_w or var == "WALL_REJECTION") else var + "_BASE"
        f = {"variant": name, "uses_walls": use_w or var == "WALL_REJECTION", "activity_filter": p.get("activity_filter", "REQUIRED"),
             "regime": (view.regime or {}).get("state")}
        if rng.get("status") == "OK":
            f.update(range_id=rng["range_id"], range_top_px=rng["top"], range_bottom_px=rng["bottom"], range_mid_px=rng["mid"],
                     range_height_atr=rng["height_atr"], range_state=rng["state"], range_available_at=rng["available_at"], er=rng["er"],
                     range_lookback=rng["lookback"])
        return f

    def _reaction(self, m1, k0, i, zone_low, a1):
        lo = min(m1.l[k0:i + 1])
        sweep = lo < zone_low
        pats = []
        for k in range(max(1, k0 - 1), i + 1):
            pats += [x for x in CN.detect_at(m1.o, m1.h, m1.l, m1.c, m1.t, k, a1[k], "M1", _close_t(m1.t[k], 1))
                     if x["direction"] == "LONG" and x["type"] in REACTION_TYPES]
        ev = CN.evidence_events(pats)
        k_lo = k0 + m1.l[k0:i + 1].index(lo)
        higher_low = i - k_lo >= 2 and min(m1.l[k_lo + 1:i + 1]) > lo
        return {"sweep": sweep, "episode_low": lo, "candle_events": len(ev), "candle_types": sorted({x["type"] for x in pats}),
                "higher_low": higher_low, "ok": sweep or bool(ev) or higher_low}

    def _range_reclaim(self, view, p, rng, rp):
        if rng.get("status") != "OK":
            return None, [rng.get("reason") or "NO_RANGE"]
        if rng["state"] != "INSIDE":
            return None, ["RANGE_ACCEPTED_BREAKOUT"]
        m5, m1 = view.tfs["M5"], view.tfs["M1"]
        zones = RG.local_zones(m1, rng, rp)
        if zones["status"] != "OK" or not zones.get("lower"):
            return None, [zones.get("reason") or "NO_M1_REACTION_ZONE"]
        z = zones["lower"]
        a5 = rng["atr"]
        a1 = m1.atr()
        n1 = len(m1)
        i = n1 - 1
        after = [k for k in range(n1) if m1.t[k] >= rng["available_at"]]
        touches = [k for k in after if m1.l[k] <= z["high"]]
        facts = self._common_facts(view, p, "RANGE_RECLAIM", rng)
        facts.update(zone_low_px=z["low"], zone_high_px=z["high"], zones_frozen_at=zones["frozen_at"])
        last_c = m1.c[i]
        if not touches:
            if last_c <= rng["bottom"] + 0.35 * (rng["top"] - rng["bottom"]):
                d = self._draft(view, "RANGE_RECLAIM", "WATCH", "M1", f"RR:{rng['range_id']}:WAIT", rng, z, None, None, [], facts,
                                ["NO_CONTACT"], p, a5, components={"structure": _rng_quality(rng), "formation": 0.3, "trigger": 0.0})
                return {"variant": "RANGE_RECLAIM", "draft": d}, []
            return None, ["PRICE_IN_MIDDLE" if last_c < rng["mid"] + 0.25 * (rng["top"] - rng["bottom"]) else "NO_CONTACT"]
        kc = touches[-1]
        tset = set(touches)
        k0 = kc
        while (k0 - 1) in tset or (k0 - 2) in tset:          # one contact episode: touches at most 1 bar apart
            k0 = k0 - 1 if (k0 - 1) in tset else k0 - 2
        facts.update(contact_bar=m1.t[k0], contact_last_bar=m1.t[kc])
        reac = self._reaction(m1, k0, i, z["low"], a1)
        facts.update(sweep=reac["sweep"], episode_low_px=round(reac["episode_low"], 5), candle_evidence=reac["candle_types"], candle_events=reac["candle_events"],
                     higher_low=reac["higher_low"])
        buf = p["buffer_atr"] * a5
        lvl = z["high"] + buf
        trig = m1.c[i] > lvl and m1.c[i - 1] <= lvl
        within = i - kc <= p["trigger_window_m1"]
        if not trig and not within:
            return None, ["TRIGGER_WINDOW_EXPIRED"]          # an old contact is not a current scenario
        if not trig and (view.ask if view.ask is not None else m1.c[i]) > rng["mid"]:
            return None, ["PRICE_IN_MIDDLE"]                 # price left the zone without a reclaim close
        missing = []
        if not reac["ok"]:
            missing.append("NO_REACTION")
        if not trig:
            missing.append("NO_CLOSED_TRIGGER")
        elif not within:
            missing.append("TRIGGER_WINDOW_EXPIRED")
        act = activity(m1, i, p)
        facts.update(activity_status=act["status"], activity_ratio=act["ratio"], trigger_body_ratio=act["body_ratio"], trigger_clv=act["clv"],
                     trigger_close_px=round(m1.c[i], 5), trigger_bar=m1.t[i] if trig else None)
        if trig:
            if act["status"] == "LOW":
                missing.append("VOLUME_NOT_CONFIRMED")
            elif act["status"] == "NO_DATA":
                missing.append("ACTIVITY_NO_DATA")
            if not act["candle_ok"]:
                missing.append("TRIGGER_CANDLE_WEAK")
        entry = view.ask if view.ask is not None else m1.c[i] + view.spread
        sl = min(reac["episode_low"], z["low"]) - p["sl_buffer_atr"] * a5
        if view.mirrored:
            sl -= view.spread
        h = rng["top"] - rng["bottom"]
        tg = valid_targets("LONG", entry, sl, [(rng["mid"], 0.5, "RANGE_MID"), (rng["top"] - 0.1 * h, 0.5, "RANGE_TOP_MINUS_10PCT")], min_r=0.3)
        if entry > rng["mid"]:
            missing.append("PRICE_IN_MIDDLE")
        if entry - z["high"] > p["max_entry_atr"] * a5:
            missing.append("ENTRY_TOO_LATE")
        rr = _rr(entry, sl, tg)
        facts.update(rr_gross_weighted=rr)
        if rr is None or rr < p["rr_min_gross"]:
            missing.append("RR_NET_TOO_LOW")
        if p.get("use_walls", True):
            ws = _walls_state(view, _close_t(m1.t[i], 1))
            facts.update(walls_status=ws["status"], walls_source=(ws.get("snap") or {}).get("source_type"))
            if ws["status"] != "OK":
                missing.append("WALL_STALE" if ws["status"] in ("WALL_STALE", "STALE") else "NO_WALL_ALIGNMENT")
            else:
                prox = p["wall_proximity_atr"] * a5
                al = [w for w in _lower_walls(ws["snap"]) if w["low"] - prox <= z["high"] and w["high"] + prox >= z["low"]]
                facts.update(walls_snapshot_id=ws["snap"].get("snapshot_id"), walls_snapshot_version=ws["snap"].get("snapshot_version"))
                if al:
                    w = al[0]
                    facts.update(wall_id=w["wall_id"], wall_k=w["k"], wall_level_px=w["level"], wall_low_px=w["low"], wall_high_px=w["high"])
                else:
                    missing.append("NO_WALL_ALIGNMENT")
        cp = _chart_support(m5, "LONG", ("DOUBLE_BOTTOM", "TRIPLE_BOTTOM", "INVERSE_HEAD_SHOULDERS", "FAILED_BREAKOUT_RECLAIM"))
        if cp:
            facts["chart_pattern"] = cp
        blocking = [m for m in missing if m != "NO_CLOSED_TRIGGER"]
        phase = "TRIGGER" if (trig and within and not blocking) else ("EARLY" if reac["ok"] or trig else "WATCH")
        comps = {"structure": _rng_quality(rng), "formation": 1.0 if reac["ok"] else 0.4, "trigger": 1.0 if phase == "TRIGGER" else 0.0}
        key = f"RR:{rng['range_id']}:{m1.t[k0]}:{facts.get('walls_snapshot_id') or 'NOWALLS'}"
        d = self._draft(view, "RANGE_RECLAIM", phase, "M1", key, rng, z, sl, entry, tg, facts, missing, p, a5, components=comps,
                        trigger_level=lvl, time_exit=p["time_exit_m1"], inv=sl)
        return {"variant": "RANGE_RECLAIM", "draft": d}, []

    def _wall_rejection(self, view, p, rng, rp):
        m5 = view.tfs["M5"]
        n5 = len(m5)
        i = n5 - 1
        ws = _walls_state(view, _close_t(m5.t[i], 5))
        if ws["status"] != "OK":
            return None, ["WALL_STALE" if ws["status"] in ("WALL_STALE", "STALE") else "NO_WALLS"]
        a = m5.atr()[i]
        if not a:
            return None, ["DATA_MISSING"]
        snap = ws["snap"]
        why = []
        for w in _lower_walls(snap):
            lb = int(p["rejection_lookback_m5"])
            touch = [k for k in range(max(0, i - lb), i + 1) if m5.l[k] <= w["level"] and m5.t[k] >= snap["anchor_time"]]
            facts = self._common_facts(view, p, "WALL_REJECTION", rng)
            facts.update(wall_id=w["wall_id"], wall_k=w["k"], wall_level_px=w["level"], wall_low_px=w["low"], wall_high_px=w["high"],
                         walls_source=snap["source_type"], walls_snapshot_id=snap.get("snapshot_id"), walls_snapshot_version=snap.get("snapshot_version"),
                         walls_status="OK", anchor_px=snap["anchor_price"])
            if not touch:
                if 0 <= m5.c[i] - w["high"] <= 0.5 * a:
                    d = self._draft(view, "WALL_REJECTION", "WATCH", "M5", f"WR:{w['wall_id']}:WAIT", rng, None, None, None, [], facts, ["NO_WALL_TOUCH"],
                                    p, a, components={"structure": 0.5, "formation": 0.3, "trigger": 0.0})
                    return {"variant": "WALL_REJECTION", "draft": d}, []
                why.append("NO_WALL_TOUCH")
                continue
            k0 = touch[0]
            closes = m5.c[k0:i + 1]
            run = best = 0
            for c in closes:
                run = run + 1 if c < w["low"] else 0
                best = max(best, run)
            if best >= 2:
                why.append("ACCEPTED_BEYOND_WALL")
                continue
            if max(m5.h[k] - m5.l[k] for k in range(k0, i + 1)) >= p["max_expansion_atr"] * a:
                why.append("EXPANSION_NO_TRADE")
                continue
            missing = []
            trig = m5.c[i] > w["high"] and all(c <= w["high"] for c in m5.c[k0:i])
            if not trig:
                missing.append("NO_CLOSED_TRIGGER")
            lo = min(m5.l[k0:i + 1])
            pats = []
            for k in range(k0, i + 1):
                pats += [x for x in CN.detect_at(m5.o, m5.h, m5.l, m5.c, m5.t, k, m5.atr()[k], "M5", _close_t(m5.t[k], 5))
                         if x["direction"] == "LONG" and x["type"] in REACTION_TYPES]
            facts.update(touch_bar=m5.t[k0], episode_low_px=round(lo, 5), candle_evidence=sorted({x["type"] for x in pats}),
                         candle_events=len(CN.evidence_events(pats)), trigger_close_px=round(m5.c[i], 5), trigger_bar=m5.t[i] if trig else None)
            act = activity(m5, i, p)
            facts.update(activity_status=act["status"], activity_ratio=act["ratio"], trigger_body_ratio=act["body_ratio"], trigger_clv=act["clv"])
            if trig:
                if act["status"] == "LOW":
                    missing.append("VOLUME_NOT_CONFIRMED")
                elif act["status"] == "NO_DATA":
                    missing.append("ACTIVITY_NO_DATA")
                if not act["candle_ok"]:
                    missing.append("TRIGGER_CANDLE_WEAK")
            per = (view.regime or {}).get("per_tf") or {}
            htf_down = all((per.get(tf) or {}).get("direction") == "DOWN" for tf in ("H1", "H4"))
            facts["htf"] = {tf: (per.get(tf) or {}).get("direction") for tf in ("H1", "H4")}
            if htf_down and (view.regime or {}).get("state") == "TREND_DOWN":
                missing.append("HTF_CONFLICT")
            entry = view.ask if view.ask is not None else m5.c[i] + view.spread
            sl = lo - p["sl_buffer_atr"] * a - (view.spread if view.mirrored else 0.0)
            cands = [(snap["anchor_price"], 0.6, "DAILY_OPEN")]
            if rng.get("status") == "OK":
                cands.append((rng["mid"], 0.4, "RANGE_MID"))
            tg = valid_targets("LONG", entry, sl, cands, min_r=0.5)
            if not tg:
                risk = entry - sl
                tg = [{"price": round(entry + risk, 5), "weight": 0.5, "basis": "R_MULTIPLE_NO_STRUCTURE_1R"},
                      {"price": round(entry + 2 * risk, 5), "weight": 0.5, "basis": "R_MULTIPLE_NO_STRUCTURE_2R"}]
            if entry - w["high"] > p["max_entry_atr"] * a:
                missing.append("ENTRY_TOO_LATE")
            rr = _rr(entry, sl, tg)
            facts.update(rr_gross_weighted=rr)
            if rr is None or rr < p["rr_min_gross"]:
                missing.append("RR_NET_TOO_LOW")
            blocking = [m for m in missing if m != "NO_CLOSED_TRIGGER"]
            phase = "TRIGGER" if (trig and not blocking) else "EARLY"
            comps = {"structure": 0.8 if w["k"] >= 2 else 0.6, "formation": 1.0 if pats else 0.5, "trigger": 1.0 if phase == "TRIGGER" else 0.0}
            d = self._draft(view, "WALL_REJECTION", phase, "M5", f"WR:{w['wall_id']}:{m5.t[k0]}", rng, None, sl, entry, tg, facts, missing, p, a,
                            components=comps, trigger_level=w["high"], time_exit=p["time_exit_m5"], inv=sl, zone=(w["low"], w["high"]))
            return {"variant": "WALL_REJECTION", "draft": d}, []
        return None, why or ["NO_WALLS"]

    def _breakout_retest(self, view, p, rng, rp):
        if rng.get("status") != "OK":
            return None, [rng.get("reason") or "NO_RANGE"]
        if rng["state"] != "BROKEN_UP":
            return None, ["RANGE_NOT_BROKEN"]
        m5, m1 = view.tfs["M5"], view.tfs["M1"]
        a = rng["atr"]
        top, bot = rng["top"], rng["bottom"]
        h = top - bot
        j = rng["break_index"]
        n5 = len(m5)
        facts = self._common_facts(view, p, "BREAKOUT_RETEST", rng)
        missing = []
        br = m5.h[j] - m5.l[j]
        if br <= 0 or abs(m5.c[j] - m5.o[j]) / br < 0.5:
            missing.append("BREAKOUT_WEAK")
        act_b = activity(m5, j, p)
        facts.update(break_bar=m5.t[j], break_close_px=round(m5.c[j], 5), break_activity=act_b["status"], break_activity_ratio=act_b["ratio"])
        if act_b["status"] == "LOW":
            missing.append("VOLUME_NOT_CONFIRMED")
        if p.get("use_walls", True):
            ws = _walls_state(view, _close_t(m5.t[j], 5))
            facts.update(walls_status=ws["status"], walls_source=(ws.get("snap") or {}).get("source_type"))
            if ws["status"] != "OK":
                missing.append("WALL_STALE" if ws["status"] in ("WALL_STALE", "STALE") else "NO_WALL_ALIGNMENT")
            else:
                near = [w for w in _upper_walls(ws["snap"]) if top - a <= w["level"] <= top + a]
                facts.update(walls_snapshot_id=ws["snap"].get("snapshot_id"), walls_snapshot_version=ws["snap"].get("snapshot_version"))
                if near and m5.c[j] > near[0]["high"]:
                    w = near[0]
                    facts.update(wall_id=w["wall_id"], wall_k=w["k"], wall_level_px=w["level"], wall_low_px=w["low"], wall_high_px=w["high"])
                else:
                    missing.append("NO_WALL_ALIGNMENT")
        after = range(j + 1, n5)
        if any(m5.c[k] < top - p["fail_atr"] * a for k in after):
            return None, ["FAILED_BREAKOUT"]
        ret = next((k for k in after if m5.l[k] <= top + p["retest_tol_atr"] * a), None)
        if ret is None:
            if n5 - 1 - j > p["retest_window_m5"]:
                return None, ["RETEST_MISSING"]
            d = self._draft(view, "BREAKOUT_RETEST", "WATCH", "M1", f"BR:{rng['range_id']}:{m5.t[j]}", rng, None, None, None, [], facts,
                            ["RETEST_MISSING"] + missing, p, a, components={"structure": _rng_quality(rng), "formation": 0.5, "trigger": 0.0})
            return {"variant": "BREAKOUT_RETEST", "draft": d}, []
        if ret - j > p["retest_window_m5"]:
            return None, ["RETEST_MISSING"]
        rs = m5.t[ret]
        k1 = [k for k in range(len(m1)) if m1.t[k] >= rs]
        if not k1:
            return None, ["DATA_MISSING"]
        n1 = len(m1)
        i = n1 - 1
        r_low = min(m1.l[k1[0]:i + 1])
        prior_hi = max(m1.h[k1[0]:i]) if i > k1[0] else None
        trig = prior_hi is not None and m1.c[i] > prior_hi and m1.c[i] > top and (i - 1 < k1[0] or m1.c[i - 1] <= max(m1.h[k1[0]:i - 1] or [prior_hi]))
        if not trig:
            missing.append("NO_CLOSED_TRIGGER")
        act = activity(m1, i, p)
        facts.update(retest_bar=rs, retest_low_px=round(r_low, 5), trigger_close_px=round(m1.c[i], 5), trigger_bar=m1.t[i] if trig else None,
                     activity_status=act["status"], activity_ratio=act["ratio"], trigger_body_ratio=act["body_ratio"], trigger_clv=act["clv"])
        if trig:
            if act["status"] == "LOW":
                missing.append("VOLUME_NOT_CONFIRMED")
            elif act["status"] == "NO_DATA":
                missing.append("ACTIVITY_NO_DATA")
        entry = view.ask if view.ask is not None else m1.c[i] + view.spread
        sl = min(r_low, top) - p["sl_buffer_atr"] * a - (view.spread if view.mirrored else 0.0)
        tg = valid_targets("LONG", entry, sl, [(top + h, 0.5, "MEASURED_MOVE_1X"), (top + 2 * h, 0.5, "MEASURED_MOVE_2X")], min_r=0.3)
        if entry - top > p["max_entry_atr"] * a + 0.1 * a:
            missing.append("ENTRY_TOO_LATE")
        rr = _rr(entry, sl, tg)
        facts.update(rr_gross_weighted=rr)
        if rr is None or rr < p["rr_min_gross"]:
            missing.append("RR_NET_TOO_LOW")
        cp = _chart_support(m5, "LONG", ("RECTANGLE", "BREAKOUT_RETEST", "TRIANGLE_ASCENDING", "TRIANGLE_SYMMETRICAL", "FLAG_BREAK_BULL"))
        if cp:
            facts["chart_pattern"] = cp
        blocking = [m for m in missing if m != "NO_CLOSED_TRIGGER"]
        phase = "TRIGGER" if (trig and not blocking) else "EARLY"
        comps = {"structure": _rng_quality(rng), "formation": 1.0, "trigger": 1.0 if phase == "TRIGGER" else 0.0}
        d = self._draft(view, "BREAKOUT_RETEST", phase, "M1", f"BR:{rng['range_id']}:{m5.t[j]}:{facts.get('walls_snapshot_id') or 'NOWALLS'}", rng,
                        None, sl, entry, tg, facts, missing, p, a, components=comps, trigger_level=prior_hi, time_exit=p["time_exit_breakout_m1"],
                        inv=sl, zone=(top, top + p["retest_tol_atr"] * a), momentum="CONTINUATION")
        return {"variant": "BREAKOUT_RETEST", "draft": d}, []

    # ------------------------------------------------------------ draft helper
    def _draft(self, view, var, phase, tf, key, rng, zone_obj, sl, entry, tg, facts, missing, p, a, *, components, trigger_level=None, time_exit=None,
               inv=None, zone=None, momentum="REVERSAL"):
        name = facts["variant"]
        z = zone if zone is not None else ((zone_obj["low"], zone_obj["high"]) if isinstance(zone_obj, dict) else None)
        if z is None and facts.get("zone_low_px") is not None:
            z = (facts["zone_low_px"], facts["zone_high_px"])
        trig_txt = {"RANGE_RECLAIM": "zamknięcie świecy M1 powyżej górnej granicy lokalnej strefy reakcji (+ bufor) po kontakcie i reakcji",
                    "WALL_REJECTION": "zamknięcie świecy M5 z powrotem powyżej strefy wall po jej przebiciu",
                    "BREAKOUT_RETEST": "po retestcie górnej granicy zakresu: zamknięcie M1 powyżej najwyższego high od początku retestu"}[var]
        ref = entry if entry is not None else (trigger_level if trigger_level is not None else (view.ask or view.mid or 0.0))
        anchor = facts.get("contact_bar") or facts.get("touch_bar") or facts.get("break_bar") or (rng or {}).get("recognised_bar")
        er = {"time_exit_bars": time_exit, "be_after_tp1": True, "trailing": None} if time_exit is not None else {"be_after_tp1": True, "trailing": None,
                                                                                                                   "time_exit_bars": None}
        return Draft(strategy_id=self.id, direction="LONG", timeframe=tf, phase=phase, structure_key=f"{name}:{key}", event_key=f"S12:{var}:LONG:{key.split(':')[1]}",
                     anchor_time=anchor, entry_plan=plan(f"S12_{name}", ref, z, trig_txt, trigger_level, 3, p["max_entry_atr"]),
                     invalidation_level=inv, invalidation_rule="CLOSE_BEYOND", stop_loss=sl, targets=tg or [], exit_rules=er,
                     expires_bars=int(p["expires_bars"]) if phase == "TRIGGER" else 20, components=components, momentum_mode=momentum,
                     missing=list(dict.fromkeys(missing)), reason_codes=[f"S12_{name}", f"RANGE_{(rng or {}).get('state')}"], facts=facts,
                     horizon="SCALP" if tf == "M1" else "INTRADAY")


def _rng_quality(rng) -> float:
    if rng.get("status") != "OK":
        return 0.3
    t = min(rng["touches_top"], rng["touches_bottom"])
    return round(max(0.3, min(1.0, 0.4 + 0.2 * t) * (1 - 0.5 * rng["er"])), 3)


def _rr(entry, sl, tg) -> float | None:
    risk = entry - sl
    if risk <= 0 or not tg:
        return None
    return round(sum(t["weight"] * (t["price"] - entry) for t in tg) / risk, 2)


def _chart_support(m5, direction, kinds) -> dict | None:
    try:
        res = CH.scan(m5, "M5")
    except Exception:
        return None
    for x in res.get("patterns") or []:
        if x["type"] in kinds and x["state"] in ("FORMING", "CONFIRMED") and x["direction_if_confirmed"] in (direction, None):
            return {"pattern_id": x["pattern_id"], "type": x["type"], "state": x["state"], "geometric_score": x["geometric_score"]}
    return None


def _swap_pairs(f: dict) -> None:
    for a, b in PAIRS:
        if a in f or b in f:
            f[a], f[b] = f.get(b), f.get(a)


# ----------------------------------------------------------------------------- checklist (real coordinates, after the arbiter)
def checklist_rows(d: Draft, p: dict) -> list[dict]:
    """Every condition: name, requirement, reading, TF, status, time, Polish reason. Missing data is never a failed geometry."""
    f = d.facts
    var = f.get("variant", "")
    base_var = var.replace("_BASE", "")
    long_ = d.direction == "LONG"
    miss = set(d.missing)
    rows = []

    def row(name, req, val, tf, status, reason=None, at=None):
        rows.append({"name": name, "threshold": req, "value": val, "tf": tf, "status": status, "reason": reason, "at": at})

    def st(code, ok_val=True):
        return "NIESPEŁNIONY" if code in miss else "SPEŁNIONY"
    row("Reżim rynku", "zgodny z wariantem (arbiter)", f"{f.get('regime') or 'BRAK DANYCH'} → {var}", "M15", "ODCZYT" if f.get("regime") else "BRAK DANYCH",
        f.get("arbiter"))
    if f.get("uses_walls"):
        if f.get("walls_status") == "OK" or base_var == "WALL_REJECTION":
            src = f.get("walls_source") or "—"
            row("Wall – źródło i aktualność", "aktualny snapshot (HV_PROXY = przybliżenie, nie IV)", f"{src}, snapshot v{f.get('walls_snapshot_version')}",
                "D1", "SPEŁNIONY", None)
        else:
            row("Wall – źródło i aktualność", "aktualny snapshot", f.get("walls_status") or "BRAK DANYCH", "D1",
                "BRAK DANYCH" if f.get("walls_status") in (None, "NO_WALLS", "UNAVAILABLE") else "NIESPEŁNIONY",
                REJECT_PL.get("WALL_STALE"))
        if base_var != "WALL_REJECTION":
            w = f.get("wall_level_px")
            row("Wall przy strefie reakcji" if base_var == "RANGE_RECLAIM" else "Wybicie poza wall",
                f"strefa wall w odległości ≤ {p['wall_proximity_atr']} ATR(M5)" if base_var == "RANGE_RECLAIM" else "zamknięcie wybicia powyżej najbliższej wall",
                "BRAK DANYCH" if w is None else f"wall {f.get('wall_k')}σ: {f.get('wall_low_px')} – {f.get('wall_high_px')}", "M5",
                st("NO_WALL_ALIGNMENT") if w is not None or "NO_WALL_ALIGNMENT" in miss else "BRAK DANYCH",
                REJECT_PL["NO_WALL_ALIGNMENT"] if "NO_WALL_ALIGNMENT" in miss else None)
    else:
        row("Wall", "nie dotyczy (wariant bazowy bez walls)", "—", "—", "NIE DOTYCZY", "wariant porównawczy – walls nie biorą udziału w decyzji")
    if f.get("range_id"):
        row("Zakres M5 (konsolidacja)", f"{p['range_min_h_atr']}–{p['range_max_h_atr']} ATR, ER ≤ {p['range_max_er']}, ≥ {p['range_min_touches']} kontakty z każdą krawędzią",
            f"{f.get('range_bottom_px')} – {f.get('range_top_px')} ({f.get('range_height_atr')} ATR, ER {f.get('er')}, stan {f.get('range_state')})", "M5",
            "SPEŁNIONY", None, f.get("range_available_at"))
    elif base_var != "WALL_REJECTION":
        row("Zakres M5 (konsolidacja)", "rozpoznany zakres", "brak", "M5", "NIESPEŁNIONY", REJECT_PL["NO_RANGE"])
    if base_var == "RANGE_RECLAIM":
        row("Kontakt ze strefą " + ("dolną" if long_ else "górną"), "świeca M1 po zamrożeniu strefy dochodzi do strefy reakcji",
            f"strefa {f.get('zone_low_px')} – {f.get('zone_high_px')}" + (f", kontakt {f.get('contact_bar')}" if f.get("contact_bar") else ""), "M1",
            "OCZEKIWANIE" if "NO_CONTACT" in miss else "SPEŁNIONY", None if "NO_CONTACT" not in miss else REJECT_PL["NO_CONTACT"], f.get("zones_frozen_at"))
        row("Cena nie w środku zakresu", "wejście po stronie strefy, nie powyżej/poniżej środka", f"środek {f.get('range_mid_px')}", "M5",
            st("PRICE_IN_MIDDLE"), REJECT_PL["PRICE_IN_MIDDLE"] if "PRICE_IN_MIDDLE" in miss else None)
    if base_var == "WALL_REJECTION":
        row("Dotknięcie / przebicie wall", "świeca M5 przebija poziom wall, bez akceptacji poza strefą", f"wall {f.get('wall_k')}σ {f.get('wall_level_px')}"
            + (f", dotknięcie {f.get('touch_bar')}" if f.get("touch_bar") else ""), "M5", "OCZEKIWANIE" if "NO_WALL_TOUCH" in miss else "SPEŁNIONY")
    if base_var in ("RANGE_RECLAIM", "WALL_REJECTION"):
        ev = f.get("candle_evidence") or []
        ok = bool(f.get("sweep") or ev or f.get("higher_low"))
        row("Reakcja (sweep / formacja świecowa / " + ("wyższy dołek" if long_ else "niższy szczyt") + ")", "co najmniej jedna z trzech",
            ", ".join(([("sweep strefy")] if f.get("sweep") else []) + ev + (["wyższy dołek" if long_ else "niższy szczyt"] if f.get("higher_low") else [])) or "brak",
            "M1" if base_var == "RANGE_RECLAIM" else "M5", "SPEŁNIONY" if ok else ("OCZEKIWANIE" if "NO_CONTACT" in miss or "NO_WALL_TOUCH" in miss else "NIESPEŁNIONY"),
            None if ok else REJECT_PL["NO_REACTION"])
    if base_var == "BREAKOUT_RETEST":
        row("Zaakceptowane wybicie zakresu", "zamknięcie M5 poza granicą + bufor, korpus ≥ 50%", f"{f.get('break_bar')} zamknięcie {f.get('break_close_px')}", "M5",
            st("BREAKOUT_WEAK"), REJECT_PL["BREAKOUT_WEAK"] if "BREAKOUT_WEAK" in miss else None)
        row("Retest granicy", f"powrót do granicy (± {p['retest_tol_atr']} ATR) w ≤ {p['retest_window_m5']} świecach M5", f.get("retest_bar") or "brak", "M5",
            "OCZEKIWANIE" if "RETEST_MISSING" in miss else "SPEŁNIONY", REJECT_PL["RETEST_MISSING"] if "RETEST_MISSING" in miss else None)
    cp = f.get("chart_pattern")
    row("Formacja wykresowa (opcjonalna – struktura)", "nie jest wymagana", f"{cp['type']} ({cp['state']})" if cp else "brak", "M5", "ODCZYT" if cp else "NIE DOTYCZY")
    tf_t = "M5" if base_var == "WALL_REJECTION" else "M1"
    row(f"Zamknięcie świecy wyzwalającej {tf_t}", (d.entry_plan or {}).get("trigger") or "wyzwalacz", f"zamknięcie {f.get('trigger_close_px')}"
        + (f" ({f.get('trigger_bar')})" if f.get("trigger_bar") else ""), tf_t,
        "OCZEKIWANIE" if "NO_CLOSED_TRIGGER" in miss else ("NIESPEŁNIONY" if "TRIGGER_WINDOW_EXPIRED" in miss or "TRIGGER_CANDLE_WEAK" in miss else "SPEŁNIONY"),
        REJECT_PL.get("TRIGGER_WINDOW_EXPIRED") if "TRIGGER_WINDOW_EXPIRED" in miss else (REJECT_PL["TRIGGER_CANDLE_WEAK"] if "TRIGGER_CANDLE_WEAK" in miss else None),
        f.get("trigger_bar"))
    ast = f.get("activity_status")
    row("Aktywność (tick volume brokera)", f"≥ {p['activity_ratio']} × mediana {p['activity_median_n']} świec, korpus ≥ {p['body_ratio']}, zamknięcie ≥ {p['clv_long']}"
        if f.get("activity_filter") != "OFF" else "filtr wyłączony (wariant badawczy)",
        "BRAK DANYCH" if ast == "NO_DATA" else f"{f.get('activity_ratio')}× mediana, korpus {f.get('trigger_body_ratio')}, CLV {f.get('trigger_clv')}", tf_t,
        {"OK": "SPEŁNIONY", "LOW": "NIESPEŁNIONY", "NO_DATA": "BRAK DANYCH", "NOT_APPLIED": "NIE DOTYCZY"}.get(ast, "OCZEKIWANIE"),
        "tick volume CFD = aktywność feedu brokera, nie wolumen giełdowy" if ast in ("OK", "LOW") else (REJECT_PL["ACTIVITY_NO_DATA"] if ast == "NO_DATA" else None))
    row("Czas i oddalenie ceny", f"wejście ≤ {p['max_entry_atr']} ATR od strefy/poziomu", "za daleko" if "ENTRY_TOO_LATE" in miss else "w limicie", tf_t,
        st("ENTRY_TOO_LATE"), REJECT_PL["ENTRY_TOO_LATE"] if "ENTRY_TOO_LATE" in miss else None)
    rr = f.get("rr_gross_weighted")
    row("RR (brutto, wstępnie)", f"≥ {p['rr_min_gross']} (RR netto liczy silnik ryzyka)", "BRAK DANYCH" if rr is None else str(rr), tf_t,
        "BRAK DANYCH" if rr is None and "RR_NET_TOO_LOW" not in miss else st("RR_NET_TOO_LOW"), REJECT_PL["RR_NET_TOO_LOW"] if "RR_NET_TOO_LOW" in miss else None)
    if "HTF_CONFLICT" in miss or f.get("htf"):
        row("Wyższe interwały (H1/H4)", "brak silnego trendu przeciwnego dla odbicia", str(f.get("htf") or "—"), "H1/H4", st("HTF_CONFLICT"),
            REJECT_PL["HTF_CONFLICT"] if "HTF_CONFLICT" in miss else None)
    if "CONFLICT_REJECTION_VS_BREAKOUT" in miss:
        row("Arbiter rodziny S12", "jedna hipoteza na zdarzenie", "konflikt kierunków", "M5", "NIESPEŁNIONY", REJECT_PL["CONFLICT_REJECTION_VS_BREAKOUT"])
    row("Unieważnienie", "zamknięcie świecy za poziomem SL / unieważnienia", "BRAK DANYCH" if d.invalidation_level is None else f"{round(d.invalidation_level, 5)}",
        d.timeframe, "ODCZYT" if d.invalidation_level is not None else "BRAK DANYCH")
    return rows
