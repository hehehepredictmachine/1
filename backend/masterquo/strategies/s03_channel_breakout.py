"""S03 CHANNEL_BREAKOUT - Donchian channel breakout.

LONG (SHORT mirrored). Channel = highest high / lowest low of the N bars BEFORE the evaluated bar
(the breakout bar never sets its own threshold).
  necessary  channel width >= min_width_atr x ATR (a 1-bar-wide "channel" is noise)
  WATCH      close within watch_dist_atr x ATR below the upper channel
  EARLY      forming bar trades above the channel, or the closed bar broke it intrabar
             (high > upper) without closing beyond the buffer
  TRIGGER    CLOSED bar closes above upper + buffer_atr x ATR and its range <= max_bar_atr x ATR
             (a larger bar = chasing -> stays EARLY with BREAKOUT_BAR_TOO_LARGE)
  invalid.   close back below the channel midpoint
  SL         upper - sl_atr x ATR (back well inside the channel) (+spread for SHORT)
  targets    measured move: TP1 = upper + 0.5 x width, TP2 = upper + 1.0 x width
  exit       time exit; BE after TP1
"""
from __future__ import annotations

from .base import Draft, MarketView, Strategy, long_stop
from .common import level_bucket, plan, valid_targets
from .indicators import donchian_prior


class ChannelBreakout(Strategy):
    id = "S03"
    name = "CHANNEL_BREAKOUT"
    version = "1.0.0-EXPERIMENTAL"
    family = "BREAKOUT"
    setup_tfs = ("M5", "M15")
    context_tf = "H1"
    required_tfs = ("M5", "M15")
    min_bars = 60
    regime_fit = {"EXPANSION": 1.0, "COMPRESSION": 0.6, "TREND_UP": 0.6, "TREND_DOWN": 0.6, "TRANSITION": 0.5, "RANGE": 0.3,
                  "EXHAUSTION_OR_REVERSAL_CANDIDATE": 0.1}
    params = {"tfs": ["M5", "M15"], "n": 20, "min_width_atr": 2.0, "watch_dist_atr": 0.5, "buffer_atr": 0.1, "max_bar_atr": 2.5,
              "sl_atr": 1.0, "time_exit_bars": 30, "expires_bars": 4}

    def detect_long(self, view: MarketView, p: dict) -> list[Draft]:
        out = []
        for tf in p["tfs"]:
            v = view.tfs.get(tf)
            if v is None or len(v) < self.min_bars:
                continue
            i = v.last
            a = v.atr()[i]
            up, dn = v.get(f"don{p['n']}", lambda: donchian_prior(v.h, v.l, p["n"]))
            if not a or up[i] is None:
                continue
            upper, lower = up[i], dn[i]
            width = upper - lower
            if width < p["min_width_atr"] * a:
                continue
            mid = (upper + lower) / 2
            buf = p["buffer_atr"] * a
            bar_rng = v.h[i] - v.l[i]
            phase, missing = None, []
            if v.c[i] > upper + buf:
                if bar_rng <= p["max_bar_atr"] * a:
                    phase = "TRIGGER"
                else:
                    phase, missing = "EARLY", ["BREAKOUT_BAR_TOO_LARGE"]
            elif v.h[i] > upper or (v.forming and v.forming["h"] > upper):
                phase, missing = "EARLY", ["CLOSE_BEYOND_CHANNEL_PLUS_BUFFER"]
            elif upper - v.c[i] <= p["watch_dist_atr"] * a:
                phase, missing = "WATCH", ["CHANNEL_NOT_BROKEN"]
            if phase is None:
                continue
            # the breakout must be fresh: the previous close was inside the channel of its own time
            if phase == "TRIGGER" and up[i - 1] is not None and v.c[i - 1] > up[i - 1] + buf:
                continue
            entry = v.c[i] if phase == "TRIGGER" else upper + buf
            sl = long_stop(view, upper, p["sl_atr"] * a)
            tg = valid_targets("LONG", entry, sl, [(upper + 0.5 * width, 0.5, "HALF_CHANNEL_WIDTH"), (upper + width, 0.5, "CHANNEL_WIDTH")])
            out.append(Draft(
                strategy_id=self.id, direction="LONG", timeframe=tf, phase=phase,
                structure_key=f"{tf}:DON{p['n']}:{v.t[max(range(i - p['n'], i), key=lambda k: v.h[k])]}", event_key=f"BREAKOUT:LONG:{level_bucket(view, upper)}",
                anchor_time=v.t[i], entry_plan=plan("CHANNEL_BREAK", entry, (upper, upper + buf), f"zamknięcie powyżej kanału {p['n']} świec + bufor", upper + buf, 1, 1.0),
                invalidation_level=mid, stop_loss=sl, targets=tg,
                exit_rules={"time_exit_bars": p["time_exit_bars"], "be_after_tp1": True, "trailing": None}, expires_bars=p["expires_bars"],
                components={"structure": min(1.0, width / (4 * a)), "formation": 1.0 if phase != "WATCH" else 0.5,
                            "trigger": (1.0 if bar_rng <= 1.5 * a else 0.6) if phase == "TRIGGER" else 0.0},
                momentum_mode="CONTINUATION", missing=missing, reason_codes=[f"DONCHIAN_{p['n']}", f"WIDTH_{width / a:.1f}ATR"],
                facts={"upper_px": round(upper, 3), "lower_px": round(lower, 3), "width_atr": round(width / a, 2), "bar_range_atr": round(bar_rng / a, 2)},
                horizon="SCALP" if tf == "M5" else "INTRADAY"))
        return out
