"""S10 EXHAUSTION_STRUCTURE_REVERSAL - reversal after a weakening impulse AND a confirmed change of
local structure. An overbought/oversold RSI alone is never the trigger, and a prior failed breakout
(S07) is not required.
LONG = reversal after a down impulse (SHORT mirrored):
  impulse    lowest low of the last `lookback` bars at bar x (x not older than `max_extreme_age`),
             impulse = highest high of the `lookback` bars before x minus low[x] >= min_impulse_atr x ATR
  exhaustion at least one, measured at x:
             (a) divergence: an earlier confirmed swing low q (3..lookback bars before x) with
                 low[x] < low[q] and RSI14[x] > RSI14[q] + 2   (momentum lower low not confirmed)
             (b) stretch: (EMA20[x] - low[x]) / ATR >= stretch_atr
  structure  last confirmed swing high (pivot 3/3) before x = the last lower high (CHoCH level)
  WATCH      impulse + exhaustion, price below the CHoCH level
  EARLY      close within 0.5 ATR of the CHoCH level, or the forming bar above it
  TRIGGER    first CLOSED bar after x closing above CHoCH + buffer_atr x ATR
  invalid.   close below the extreme low
  SL         extreme low - 0.2 ATR (+spread for SHORT)
  targets    TP1 = 50% retracement of the impulse, TP2 = 78.6% retracement
"""
from __future__ import annotations

from .base import Draft, MarketView, Strategy, long_stop
from .common import level_bucket, plan, valid_targets


class ExhaustionStructureReversal(Strategy):
    id = "S10"
    name = "EXHAUSTION_STRUCTURE_REVERSAL"
    version = "1.0.0-EXPERIMENTAL"
    family = "REVERSAL"
    setup_tfs = ("M5", "M15")
    context_tf = "H1"
    required_tfs = ("M5", "M15")
    min_bars = 80
    regime_fit = {"EXHAUSTION_OR_REVERSAL_CANDIDATE": 1.0, "TRANSITION": 0.6, "EXPANSION": 0.4, "RANGE": 0.4, "TREND_UP": 0.3,
                  "TREND_DOWN": 0.3, "COMPRESSION": 0.1}
    params = {"tfs": ["M5", "M15"], "lookback": 30, "max_extreme_age": 12, "min_impulse_atr": 3.0, "stretch_atr": 2.5,
              "buffer_atr": 0.1, "time_exit_bars": 30, "expires_bars": 8}

    def detect_long(self, view: MarketView, p: dict) -> list[Draft]:
        out = []
        for tf in p["tfs"]:
            v = view.tfs.get(tf)
            if v is None or len(v) < self.min_bars:
                continue
            i = v.last
            a = v.atr()[i]
            r, e20 = v.rsi(), v.ema(20)
            if not a:
                continue
            lb = p["lookback"]
            x = min(range(i - lb + 1, i + 1), key=lambda k: v.l[k])
            if i - x > p["max_extreme_age"] or x < lb + 5:
                continue
            ext_low = v.l[x]
            imp_hi = max(v.h[x - lb:x + 1])
            impulse = imp_hi - ext_low
            if impulse < p["min_impulse_atr"] * a:
                continue
            piv = [q for q in v.pivots() if q["confirmed_index"] <= x]
            lows = [q for q in piv if q["kind"] == "L" and 3 <= x - q["index"] <= lb and ext_low < q["price"]]
            div = next((q for q in sorted(lows, key=lambda q: -q["index"]) if r[x] is not None and r[q["index"]] is not None and r[x] > r[q["index"]] + 2), None)
            stretch = (e20[x] - ext_low) / a if e20[x] is not None else 0.0
            if not div and stretch < p["stretch_atr"]:
                continue
            highs = [q for q in v.pivots() if q["kind"] == "H" and q["index"] < x and q["confirmed_index"] <= i and x - q["index"] <= lb]
            if not highs:
                continue
            choch = max(highs, key=lambda q: q["index"])
            level = choch["price"]
            buf = p["buffer_atr"] * a
            if any(v.c[k] < ext_low for k in range(x + 1, i + 1)):
                continue
            if any(v.c[k] > level + buf for k in range(x + 1, i)):
                continue                                         # structure already changed earlier
            phase, missing = None, []
            if v.c[i] > level + buf and i > x:
                phase = "TRIGGER"
            elif level - v.c[i] <= 0.5 * a or (v.forming and v.forming["c"] > level):
                phase, missing = "EARLY", ["CLOSE_ABOVE_LAST_LOWER_HIGH"]
            else:
                phase, missing = "WATCH", ["STRUCTURE_CHANGE_NOT_CONFIRMED"]
            entry = v.c[i] if phase == "TRIGGER" else level + buf
            sl = long_stop(view, ext_low, 0.2 * a)
            tg = valid_targets("LONG", entry, sl, [(ext_low + 0.5 * impulse, 0.5, "RETRACE_50"), (ext_low + 0.786 * impulse, 0.5, "RETRACE_78.6")])
            out.append(Draft(
                strategy_id=self.id, direction="LONG", timeframe=tf, phase=phase,
                structure_key=f"{tf}:EXT:{v.t[x]}", event_key=f"REVERSAL:LONG:{level_bucket(view, ext_low)}", anchor_time=v.t[x],
                entry_plan=plan("STRUCTURE_CHANGE", entry, (level, level + buf), "zamknięcie powyżej ostatniego niższego szczytu (CHoCH) po ekstremum", level + buf, 3, 1.5),
                invalidation_level=ext_low, stop_loss=sl, targets=tg,
                exit_rules={"time_exit_bars": p["time_exit_bars"], "be_after_tp1": True, "trailing": None}, expires_bars=p["expires_bars"],
                components={"structure": min(1.0, impulse / (6 * a)), "formation": 1.0 if (div and stretch >= p["stretch_atr"]) else 0.7,
                            "trigger": 1.0 if phase == "TRIGGER" else 0.0},
                momentum_mode="REVERSAL", missing=missing,
                reason_codes=[f"IMPULSE_{impulse / a:.1f}ATR"] + (["RSI_DIVERGENCE"] if div else []) + ([f"STRETCH_{stretch:.1f}ATR"] if stretch >= p["stretch_atr"] else []),
                facts={"extreme_px": round(ext_low, 3), "choch_level_px": round(level, 3), "impulse_atr": round(impulse / a, 2),
                       "divergence": bool(div), "stretch_atr": round(stretch, 2), "extreme_bar": v.t[x]},
                horizon="SCALP" if tf == "M5" else "INTRADAY"))
        return out
