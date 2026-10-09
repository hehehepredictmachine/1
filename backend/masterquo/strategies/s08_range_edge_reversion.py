"""S08 RANGE_EDGE_REVERSION - rejection of the edge of a previously recognised consolidation.

The range must be known BEFORE the signal bar (computed on the `lookback` bars ending at i-1).
A prior excursion outside the range is NOT required (that is S07).
  range      top/bottom = max high / min low of the window; ER(lookback) <= max_er;
             height between min_h_atr and max_h_atr ATR; >= min_touches touches of each edge zone
             (bar high >= top - edge_frac x height, resp. low <= bottom + edge_frac x height),
             touches separated by >= 3 bars
  LONG (SHORT mirrored)
  WATCH      range recognised, close in the lower `watch_frac` of the range
  EARLY      the last closed (or the forming) bar trades into the lower edge zone
  TRIGGER    CLOSED rejection bar: low in the edge zone, close in the upper half of the bar and above
             bottom + edge_frac x height, no close below bottom - 0.25 ATR
  invalid.   close below bottom - 0.3 ATR
  SL         min(signal low, bottom) - 0.3 ATR (+spread for SHORT)
  targets    TP1 = range midpoint, TP2 = top - edge_frac x height
"""
from __future__ import annotations

from .base import Draft, MarketView, Strategy, long_stop
from .common import close_pos, level_bucket, plan, valid_targets


def _touches(idx: list[int], min_gap: int = 3) -> int:
    n, last = 0, -10 ** 9
    for k in idx:
        if k - last >= min_gap:
            n += 1
            last = k
    return n


class RangeEdgeReversion(Strategy):
    id = "S08"
    name = "RANGE_EDGE_REVERSION"
    version = "1.0.0-EXPERIMENTAL"
    family = "REVERSION"
    setup_tfs = ("M5", "M15")
    context_tf = "H1"
    required_tfs = ("M5", "M15")
    min_bars = 70
    regime_fit = {"RANGE": 1.0, "COMPRESSION": 0.4, "TRANSITION": 0.5, "EXHAUSTION_OR_REVERSAL_CANDIDATE": 0.4, "EXPANSION": 0.1,
                  "TREND_UP": 0.1, "TREND_DOWN": 0.1}
    params = {"tfs": ["M5", "M15"], "lookback": 40, "max_er": 0.25, "min_h_atr": 2.0, "max_h_atr": 8.0, "edge_frac": 0.15,
              "min_touches": 2, "watch_frac": 0.3, "time_exit_bars": 24, "expires_bars": 6}

    def range_at(self, v, end: int, a: float, p: dict) -> dict | None:
        lb = p["lookback"]
        s = end - lb + 1
        if s < 1:
            return None
        top, bot = max(v.h[s:end + 1]), min(v.l[s:end + 1])
        height = top - bot
        if not (p["min_h_atr"] * a <= height <= p["max_h_atr"] * a):
            return None
        noise = sum(abs(v.c[k] - v.c[k - 1]) for k in range(s, end + 1))
        er = 0.0 if noise == 0 else abs(v.c[end] - v.c[s - 1]) / noise
        if er > p["max_er"]:
            return None
        ef = p["edge_frac"] * height
        tt = _touches([k for k in range(s, end + 1) if v.h[k] >= top - ef])
        tb = _touches([k for k in range(s, end + 1) if v.l[k] <= bot + ef])
        if tt < p["min_touches"] or tb < p["min_touches"]:
            return None
        return {"top": top, "bottom": bot, "height": height, "er": er, "touch_top": tt, "touch_bottom": tb, "start": s}

    def detect_long(self, view: MarketView, p: dict) -> list[Draft]:
        out = []
        for tf in p["tfs"]:
            v = view.tfs.get(tf)
            if v is None or len(v) < self.min_bars:
                continue
            i = v.last
            a = v.atr()[i - 1]
            if not a:
                continue
            r = self.range_at(v, i - 1, a, p)
            if r is None:
                continue
            top, bot, h = r["top"], r["bottom"], r["height"]
            ef = p["edge_frac"] * h
            if v.c[i] < bot - 0.25 * a:
                continue                                       # broke down: not a range edge any more
            in_zone = v.l[i] <= bot + ef
            forming_zone = bool(v.forming and v.forming["l"] <= bot + ef)
            phase, missing = None, []
            if in_zone and close_pos(v, i) >= 0.5 and v.c[i] > bot + ef:
                phase = "TRIGGER"
            elif in_zone or forming_zone:
                phase, missing = "EARLY", ["REJECTION_CLOSE_UPPER_HALF"]
            elif v.c[i] <= bot + p["watch_frac"] * h:
                phase, missing = "WATCH", ["EDGE_ZONE_NOT_REACHED"]
            if phase is None:
                continue
            sig_low = min(v.l[i], v.forming["l"]) if (v.forming and phase == "EARLY") else v.l[i]
            entry = v.c[i] if phase == "TRIGGER" else bot + ef
            sl = long_stop(view, min(sig_low, bot), 0.3 * a)
            tg = valid_targets("LONG", entry, sl, [(bot + h / 2, 0.5, "RANGE_MID"), (top - ef, 0.5, "OPPOSITE_EDGE")])
            out.append(Draft(
                strategy_id=self.id, direction="LONG", timeframe=tf, phase=phase,
                structure_key=f"{tf}:RANGE:{v.t[min(range(r['start'], i), key=lambda k: v.l[k])]}", event_key=f"RANGE_EDGE:LONG:{level_bucket(view, bot)}",
                anchor_time=v.t[r["start"]],
                entry_plan=plan("EDGE_REJECTION", entry, (bot, bot + ef), "zamknięcie świecy odrzucenia w górnej połowie, powyżej strefy krawędzi", bot + ef, 2, 1.0),
                invalidation_level=bot - 0.3 * a, stop_loss=sl, targets=tg,
                exit_rules={"time_exit_bars": p["time_exit_bars"], "be_after_tp1": True, "trailing": None}, expires_bars=p["expires_bars"],
                components={"structure": min(1.0, (r["touch_top"] + r["touch_bottom"]) / 6), "formation": 1.0 if r["er"] <= 0.15 else 0.6,
                            "trigger": close_pos(v, i) if phase == "TRIGGER" else 0.0},
                momentum_mode="REVERSAL", missing=missing, reason_codes=[f"RANGE_ER_{r['er']:.2f}", f"TOUCHES_{r['touch_top']}/{r['touch_bottom']}"],
                facts={"range_top_px": round(top, 3), "range_bottom_px": round(bot, 3), "range_height_atr": round(h / a, 2), "er": round(r["er"], 3)},
                horizon="SCALP" if tf == "M5" else "INTRADAY"))
        return out
