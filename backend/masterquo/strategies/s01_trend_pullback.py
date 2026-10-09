"""S01 TREND_PULLBACK - continuation of an existing trend after a measured correction.

LONG rules (SHORT = mirrored prices), setup TF in p["tfs"] (M5, M15), context H1:
  necessary  trend: EMA20 > EMA50, EMA50 slope (10 bars) >= min_slope ATR/bar, ER(20) >= 0.6 x min_er
             (ER below min_er is reported as missing confirmation TREND_EFFICIENCY_WEAK and lowers the score)
             swing: the highest high of the last `swing_lookback` bars (impulse extreme) is >= 2 bars old
             correction: depth from that high to the lowest low since = min_depth..max_depth ATR,
                         no close below EMA50 - deep_close_atr x ATR (that would be a trend failure)
  WATCH      trend + correction >= 0.5 x min_depth in progress
  EARLY      a bar (closed in the last `zone_bars`, or the forming bar) traded into the value zone
             [EMA50 - 0.25 ATR, EMA20 + 0.25 ATR]
  TRIGGER    after the zone contact a CLOSED bar closes above the previous bar's high with a bullish body
  invalid.   close below the correction low - 0.2 ATR (CLOSE_BEYOND)
  SL         correction low - sl_buffer ATR (+spread for SHORT)
  targets    TP1 = impulse extreme (retest of the high), TP2 = measured move: entry + impulse length
  exit       time exit after `time_exit_bars`; SL to BE after TP1
"""
from __future__ import annotations

from .base import Draft, MarketView, Strategy, long_stop
from .common import body_ratio, plan, valid_targets
from .indicators import efficiency_ratio


class TrendPullback(Strategy):
    id = "S01"
    name = "TREND_PULLBACK"
    version = "1.0.0-EXPERIMENTAL"
    family = "TREND"
    setup_tfs = ("M5", "M15")
    context_tf = "H1"
    required_tfs = ("M5", "M15")
    min_bars = 80
    regime_fit = {"TREND_UP": 1.0, "TREND_DOWN": 1.0, "TRANSITION": 0.5, "EXPANSION": 0.4, "COMPRESSION": 0.2, "RANGE": 0.1,
                  "EXHAUSTION_OR_REVERSAL_CANDIDATE": 0.2}
    params = {"tfs": ["M5", "M15"], "min_slope": 0.02, "min_er": 0.25, "swing_lookback": 30, "min_depth_atr": 1.0, "max_depth_atr": 3.5,
              "deep_close_atr": 0.5, "zone_bars": 3, "sl_buffer_atr": 0.2, "time_exit_bars": 36, "expires_bars": 12}

    def detect_long(self, view: MarketView, p: dict) -> list[Draft]:
        out = []
        for tf in p["tfs"]:
            v = view.tfs.get(tf)
            if v is None or len(v) < self.min_bars:
                continue
            i = v.last
            a = v.atr()[i]
            e20, e50 = v.ema(20), v.ema(50)
            if not a or e20[i] is None or e50[i] is None or e50[i - 10] is None:
                continue
            er = efficiency_ratio(v.c, 20)[i] or 0.0
            slope50 = (e50[i] - e50[i - 10]) / (10 * a)
            if not (e20[i] > e50[i] and slope50 >= p["min_slope"] and er >= p["min_er"] * 0.6):
                continue
            lb = p["swing_lookback"]
            hi_idx = max(range(i - lb + 1, i + 1), key=lambda k: v.h[k])
            if i - hi_idx < 2:
                continue                                   # still making highs: no correction yet
            hi = v.h[hi_idx]
            lo_idx = min(range(hi_idx + 1, i + 1), key=lambda k: v.l[k])
            lo = v.l[lo_idx]
            if v.forming and v.forming["l"] < lo:
                lo = v.forming["l"]
            depth = (hi - lo) / a
            if depth < 0.5 * p["min_depth_atr"] or depth > p["max_depth_atr"]:
                continue
            if any(v.c[k] < e50[k] - p["deep_close_atr"] * a for k in range(hi_idx + 1, i + 1) if e50[k] is not None):
                continue
            impulse_start = min(v.l[max(0, hi_idx - lb):hi_idx + 1])
            zone = (e50[i] - 0.25 * a, e20[i] + 0.25 * a)
            touched = [k for k in range(max(hi_idx + 1, i - p["zone_bars"] + 1), i + 1) if v.l[k] <= zone[1]]
            forming_touch = bool(v.forming and v.forming["l"] <= zone[1])
            trig = bool(touched) and v.c[i] > v.h[i - 1] and v.c[i] > v.o[i]
            phase = "WATCH"
            if depth >= p["min_depth_atr"] and (touched or forming_touch):
                phase = "EARLY"
                if trig:
                    phase = "TRIGGER"
            inval = lo - 0.2 * a
            sl = long_stop(view, lo, p["sl_buffer_atr"] * a)
            entry = v.c[i] if phase == "TRIGGER" else max(zone[1], v.c[i])
            tg = valid_targets("LONG", entry, sl, [(hi, 0.5, "IMPULSE_EXTREME"), (entry + (hi - impulse_start), 0.5, "MEASURED_MOVE")])
            missing = []
            if depth < p["min_depth_atr"]:
                missing.append("CORRECTION_TOO_SHALLOW")
            if not (touched or forming_touch):
                missing.append("VALUE_ZONE_NOT_REACHED")
            elif phase == "EARLY":
                missing.append("REACTION_BAR_CLOSE_ABOVE_PRIOR_HIGH")
            if er < p["min_er"]:
                missing.append("TREND_EFFICIENCY_WEAK")
            out.append(Draft(
                strategy_id=self.id, direction="LONG", timeframe=tf, phase=phase,
                structure_key=f"{tf}:{v.t[hi_idx]}", event_key=f"TREND_CONT:LONG:{tf}:{v.t[hi_idx]}", anchor_time=v.t[hi_idx],
                entry_plan=plan("PULLBACK_REACTION", entry, zone, "zamknięcie powyżej high poprzedniej świecy po kontakcie ze strefą EMA20/EMA50",
                                v.h[i - 1] if phase != "TRIGGER" else v.c[i], 3, 1.0),
                invalidation_level=inval, stop_loss=sl, targets=tg,
                exit_rules={"time_exit_bars": p["time_exit_bars"], "be_after_tp1": True, "trailing": None},
                expires_bars=p["expires_bars"],
                components={"structure": min(1.0, er / 0.5) * (1.0 if slope50 >= 2 * p["min_slope"] else 0.7),
                            "formation": 1.0 if p["min_depth_atr"] <= depth <= 2.5 and touched else (0.6 if touched or forming_touch else 0.3),
                            "trigger": (1.0 if body_ratio(v, i) >= 0.5 else 0.6) if phase == "TRIGGER" else 0.0},
                momentum_mode="CONTINUATION", missing=missing, reason_codes=[f"TREND_ER_{er:.2f}", f"PULLBACK_{depth:.1f}ATR"],
                facts={"impulse_high_px": round(hi, 3), "correction_low_px": round(lo, 3), "depth_atr": round(depth, 2), "er": round(er, 3),
                       "ema50_slope_atr": round(slope50, 4), "zone_touch": bool(touched or forming_touch)},
                horizon="INTRADAY" if tf == "M15" else "SCALP"))
        return out
