"""S04 VOLATILITY_COMPRESSION_BREAKOUT - expansion out of a previously recognised compression.

The distinguishing condition is the historical compression, not a channel touch (that is S03).
  compression bar  Bollinger width(20,2) percentile among the previous `pct_lookback` bars <= max_pct
  box              >= min_bars_in_box consecutive compression bars ending no more than `max_box_age`
                   bars before the evaluated bar (the evaluated bar never defines its own box);
                   box = their high/low; box height <= max_box_atr x ATR
  LONG (SHORT mirrored)
  WATCH      compression box active (the last closed bar is still a compression bar), price nearer the top
  EARLY      forming bar above the box, or close above the box by less than the buffer
  TRIGGER    CLOSED bar closes above box top + buffer_atr x ATR, entry distance from the top
             <= max_entry_atr x ATR (else TOO_FAR_FROM_BOX - no chasing)
  invalid.   close back below the box midpoint
  SL         box midpoint - 0.1 ATR (+spread for SHORT)
  targets    TP1 = top + 1 x box height, TP2 = top + 2 x box height
"""
from __future__ import annotations

from .base import Draft, MarketView, Strategy, long_stop
from .common import level_bucket, plan, valid_targets
from .indicators import bb_width, percentile_rank


class VolatilityCompressionBreakout(Strategy):
    id = "S04"
    name = "VOLATILITY_COMPRESSION_BREAKOUT"
    version = "1.0.0-EXPERIMENTAL"
    family = "BREAKOUT"
    setup_tfs = ("M5", "M15")
    context_tf = "H1"
    required_tfs = ("M5", "M15")
    min_bars = 150
    regime_fit = {"COMPRESSION": 1.0, "EXPANSION": 0.8, "TRANSITION": 0.5, "RANGE": 0.5, "TREND_UP": 0.3, "TREND_DOWN": 0.3,
                  "EXHAUSTION_OR_REVERSAL_CANDIDATE": 0.1}
    params = {"tfs": ["M5", "M15"], "pct_lookback": 120, "max_pct": 0.15, "min_bars_in_box": 5, "max_box_age": 6, "max_box_atr": 3.0,
              "buffer_atr": 0.15, "max_entry_atr": 1.0, "time_exit_bars": 24, "expires_bars": 3}

    def _box(self, v, p):
        bbw = v.get("bbw", lambda: bb_width(v.c, 20, 2.0))
        i = v.last
        # the box is known BEFORE the evaluated bar: compression flags on bars i-41 .. i-1 only
        comp = [percentile_rank(bbw, k, p["pct_lookback"]) for k in range(i - 41, i)]
        flags = [c is not None and c <= p["max_pct"] for c in comp]
        end = None
        for back in range(0, p["max_box_age"] + 1):
            if flags[-1 - back]:
                end = len(flags) - 1 - back
                break
        if end is None:
            return None
        start = end
        while start - 1 >= 0 and flags[start - 1]:
            start -= 1
        n = end - start + 1
        if n < p["min_bars_in_box"]:
            return None
        s, e = i - 41 + start, i - 41 + end
        return {"start": s, "end": e, "n": n, "top": max(v.h[s:e + 1]), "bottom": min(v.l[s:e + 1]), "active": end == len(flags) - 1}

    def detect_long(self, view: MarketView, p: dict) -> list[Draft]:
        out = []
        for tf in p["tfs"]:
            v = view.tfs.get(tf)
            if v is None or len(v) < self.min_bars:
                continue
            i = v.last
            a = v.atr()[i]
            if not a:
                continue
            box = self._box(v, p)
            if box is None:
                continue
            top, bot = box["top"], box["bottom"]
            height = top - bot
            if height <= 0 or height > p["max_box_atr"] * a:
                continue
            mid = (top + bot) / 2
            buf = p["buffer_atr"] * a
            phase, missing = None, []
            broke_now = v.c[i] > top + buf and box["end"] < i
            if broke_now:
                if v.c[i] - top <= p["max_entry_atr"] * a:
                    phase = "TRIGGER"
                else:
                    phase, missing = "EARLY", ["TOO_FAR_FROM_BOX"]
                if any(v.c[k] > top + buf for k in range(box["end"] + 1, i)):
                    continue                                    # breakout already happened earlier
            elif (v.forming and v.forming["h"] > top) or (v.c[i] > top and box["end"] < i):
                phase, missing = "EARLY", ["CLOSE_BEYOND_BOX_PLUS_BUFFER"]
            elif box["active"] and v.c[i] >= mid:
                phase, missing = "WATCH", ["COMPRESSION_NOT_RELEASED"]
            if phase is None:
                continue
            entry = v.c[i] if phase == "TRIGGER" else top + buf
            sl = long_stop(view, mid, 0.1 * a)
            tg = valid_targets("LONG", entry, sl, [(top + height, 0.5, "BOX_HEIGHT_1X"), (top + 2 * height, 0.5, "BOX_HEIGHT_2X")])
            out.append(Draft(
                strategy_id=self.id, direction="LONG", timeframe=tf, phase=phase,
                structure_key=f"{tf}:BOX:{v.t[box['start']]}", event_key=f"BREAKOUT:LONG:{level_bucket(view, top)}", anchor_time=v.t[box["start"]],
                entry_plan=plan("COMPRESSION_RELEASE", entry, (top, top + buf), "zamknięcie powyżej górnej krawędzi kompresji + bufor", top + buf, 2, p["max_entry_atr"]),
                invalidation_level=mid, stop_loss=sl, targets=tg,
                exit_rules={"time_exit_bars": p["time_exit_bars"], "be_after_tp1": True, "trailing": None}, expires_bars=p["expires_bars"] if phase != "WATCH" else 30,
                components={"structure": min(1.0, box["n"] / 10), "formation": 1.0 if height <= 2 * a else 0.6,
                            "trigger": 1.0 if phase == "TRIGGER" else 0.0},
                momentum_mode="CONTINUATION", missing=missing, reason_codes=[f"COMPRESSION_{box['n']}_BARS", f"BOX_{height / a:.1f}ATR"],
                facts={"box_top_px": round(top, 3), "box_bottom_px": round(bot, 3), "box_bars": box["n"], "box_height_atr": round(height / a, 2)},
                horizon="SCALP" if tf == "M5" else "INTRADAY"))
        return out
