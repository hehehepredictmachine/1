"""S07 FAILED_BREAKOUT_RECLAIM - an observed move outside a level that fails and returns inside.

Describes price behaviour only (no claim about who "took liquidity" - there is no order data).
LONG = failed breakdown below support (SHORT mirrored = failed breakout above resistance):
  level      lower edge of the prior range = min low of the N bars before the excursion (Donchian, prior bars)
  excursion  a bar k in the last `max_bars_out`+1 bars trades below level - out_atr x ATR
  WATCH      price is currently outside (last close or forming bar below the level)
  EARLY      close back above the level but by less than the buffer, or the forming bar back above it
  TRIGGER    CLOSED bar within `max_bars_out` bars after the excursion low closes above level + buffer_atr x ATR
  invalid.   close below the excursion low (CLOSE_BEYOND)
  SL         excursion low - 0.2 ATR (+spread for SHORT)
  targets    TP1 = range midpoint, TP2 = opposite range edge
"""
from __future__ import annotations

from .base import Draft, MarketView, Strategy, long_stop
from .common import level_bucket, plan, valid_targets
from .indicators import donchian_prior


class FailedBreakoutReclaim(Strategy):
    id = "S07"
    name = "FAILED_BREAKOUT_RECLAIM"
    version = "1.0.0-EXPERIMENTAL"
    family = "REVERSION"
    setup_tfs = ("M5", "M15")
    context_tf = "H1"
    required_tfs = ("M5", "M15")
    min_bars = 60
    regime_fit = {"RANGE": 0.9, "EXHAUSTION_OR_REVERSAL_CANDIDATE": 0.8, "TRANSITION": 0.6, "COMPRESSION": 0.5, "EXPANSION": 0.4,
                  "TREND_UP": 0.3, "TREND_DOWN": 0.3}
    params = {"tfs": ["M5", "M15"], "n": 20, "min_width_atr": 1.5, "out_atr": 0.1, "max_bars_out": 3, "buffer_atr": 0.1,
              "time_exit_bars": 24, "expires_bars": 4}

    def detect_long(self, view: MarketView, p: dict) -> list[Draft]:
        out = []
        for tf in p["tfs"]:
            v = view.tfs.get(tf)
            if v is None or len(v) < self.min_bars:
                continue
            i = v.last
            a = v.atr()[i]
            up, dn = v.get(f"don{p['n']}", lambda: donchian_prior(v.h, v.l, p["n"]))
            if not a:
                continue
            exc = None
            for k in range(i, i - p["max_bars_out"] - 1, -1):
                if dn[k] is None or up[k] is None:
                    continue
                if v.l[k] < dn[k] - p["out_atr"] * a and (up[k] - dn[k]) >= p["min_width_atr"] * a:
                    exc = k
            if exc is None:
                continue
            level, top = dn[exc], up[exc]
            ex_low = min(v.l[exc:i + 1])
            if v.forming and v.forming["l"] < ex_low:
                ex_low = v.forming["l"]
            buf = p["buffer_atr"] * a
            # bars after the excursion must not have already triggered (fresh reclaim only)
            if any(v.c[j] > level + buf for j in range(exc, i)):
                continue
            phase, missing = None, []
            if v.c[i] > level + buf:
                phase = "TRIGGER"
            elif v.c[i] > level or (v.forming and v.forming["c"] > level):
                phase, missing = "EARLY", ["CLOSE_ABOVE_LEVEL_PLUS_BUFFER"]
            else:
                phase, missing = "WATCH", ["RETURN_INSIDE_RANGE"]
            mid = (level + top) / 2
            entry = v.c[i] if phase == "TRIGGER" else level + buf
            sl = long_stop(view, ex_low, 0.2 * a)
            tg = valid_targets("LONG", entry, sl, [(mid, 0.5, "RANGE_MID"), (top, 0.5, "RANGE_OPPOSITE_EDGE")])
            depth = (level - ex_low) / a
            out.append(Draft(
                strategy_id=self.id, direction="LONG", timeframe=tf, phase=phase,
                structure_key=f"{tf}:FAIL:{v.t[exc]}", event_key=f"RANGE_EDGE:LONG:{level_bucket(view, level)}", anchor_time=v.t[exc],
                entry_plan=plan("RECLAIM", entry, (level, level + buf), "zamknięcie z powrotem powyżej poziomu + bufor (≤ 3 świece od wyjścia)", level + buf,
                                p["max_bars_out"], 1.0),
                invalidation_level=ex_low, stop_loss=sl, targets=tg,
                exit_rules={"time_exit_bars": p["time_exit_bars"], "be_after_tp1": True, "trailing": None}, expires_bars=p["expires_bars"],
                components={"structure": min(1.0, (top - level) / (4 * a)), "formation": 1.0 if 0.2 <= depth <= 1.5 else 0.5,
                            "trigger": (1.0 if v.c[i] > v.o[i] else 0.6) if phase == "TRIGGER" else 0.0},
                momentum_mode="REVERSAL", missing=missing, reason_codes=["EXCURSION_BELOW_RANGE", f"DEPTH_{depth:.2f}ATR"],
                facts={"level_px": round(level, 3), "excursion_low_px": round(ex_low, 3), "range_top_px": round(top, 3), "excursion_bar": v.t[exc]},
                horizon="SCALP" if tf == "M5" else "INTRADAY"))
        return out
