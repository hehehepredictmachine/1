"""S02 ADAPTIVE_TREND - trend following with Kaufman's adaptive moving average (KAMA) and ER.

Entry is a CHANGE of the trend state (not a pullback - that is S01). LONG (SHORT mirrored):
  KAMA(er_n=10, fast=2, slow=30) on the setup TF; band = KAMA + band_atr x ATR14 (hysteresis).
  state UP   = close > KAMA + band, KAMA rising over 3 bars; DOWN symmetric; otherwise NEUTRAL.
  necessary  ER(er_n) >= min_er at the trigger bar; previous closed bar NOT in state UP
  WATCH      ER >= 0.6 x min_er, close within 1 ATR below the upper band, KAMA flat or rising
  EARLY      close above KAMA but not above the band yet, or the forming bar above the band
  TRIGGER    CLOSED bar: state turns UP (previous bar not UP)
  invalid.   close below KAMA - band_atr x ATR (state flips back) - level frozen at detection
  SL         min(lowest low of last 5 bars, KAMA - 1 ATR) - 0.2 ATR (+spread for SHORT)
  exit       trailing: close back below KAMA - band (exit_rules.trailing=KAMA_STATE_FLIP);
             TP1 1.5R (partial), TP2 3R - fixed multiples because the hypothesis has no structural target
"""
from __future__ import annotations

from .base import Draft, MarketView, Strategy, long_stop, r_targets
from .common import plan
from .indicators import efficiency_ratio, kama


class AdaptiveTrend(Strategy):
    id = "S02"
    name = "ADAPTIVE_TREND"
    version = "1.0.0-EXPERIMENTAL"
    family = "TREND"
    setup_tfs = ("M15", "H1")
    context_tf = "H4"
    required_tfs = ("M15",)
    min_bars = 60
    regime_fit = {"TREND_UP": 0.9, "TREND_DOWN": 0.9, "TRANSITION": 0.7, "EXPANSION": 0.6, "COMPRESSION": 0.3, "RANGE": 0.1,
                  "EXHAUSTION_OR_REVERSAL_CANDIDATE": 0.1}
    params = {"tfs": ["M15", "H1"], "er_n": 10, "fast": 2, "slow": 30, "band_atr": 0.3, "min_er": 0.30, "time_exit_bars": 48, "expires_bars": 4}

    def detect_long(self, view: MarketView, p: dict) -> list[Draft]:
        out = []
        for tf in p["tfs"]:
            v = view.tfs.get(tf)
            if v is None or len(v) < self.min_bars:
                continue
            i = v.last
            a = v.atr()[i]
            k = v.get(f"kama{p['er_n']}_{p['fast']}_{p['slow']}", lambda: kama(v.c, p["er_n"], p["fast"], p["slow"]))
            er_s = v.get(f"er{p['er_n']}", lambda: efficiency_ratio(v.c, p["er_n"]))
            if not a or k[i] is None or k[i - 3] is None or er_s[i] is None:
                continue
            band = p["band_atr"] * a
            er = er_s[i]
            rising = k[i] > k[i - 3]
            up_now = v.c[i] > k[i] + band and rising
            prev_a = v.atr()[i - 1] or a
            up_prev = v.c[i - 1] > (k[i - 1] or k[i]) + p["band_atr"] * prev_a and (k[i - 1] or 0) > (k[i - 4] or 0)
            near = (k[i] + band) - v.c[i] <= a and v.c[i] <= k[i] + band
            forming_above = bool(v.forming and v.forming["c"] > k[i] + band)
            if up_prev and up_now:
                continue                                    # already trending: S02 enters on the state change only
            phase = None
            if up_now and not up_prev and er >= p["min_er"]:
                phase = "TRIGGER"
            elif (v.c[i] > k[i] or forming_above) and er >= 0.6 * p["min_er"] and k[i] >= k[i - 3]:
                phase = "EARLY"
            elif near and er >= 0.6 * p["min_er"] and k[i] >= k[i - 3] - 0.05 * a:
                phase = "WATCH"
            if phase is None:
                continue
            entry = v.c[i] if phase == "TRIGGER" else k[i] + band
            low5 = min(v.l[i - 4:i + 1])
            sl = long_stop(view, min(low5, k[i] - a), 0.2 * a)
            missing = []
            if phase != "TRIGGER":
                missing.append("CLOSE_ABOVE_KAMA_BAND")
            if er < p["min_er"]:
                missing.append("ER_INSUFFICIENT")
            if not rising:
                missing.append("KAMA_NOT_RISING")
            out.append(Draft(
                strategy_id=self.id, direction="LONG", timeframe=tf, phase=phase,
                structure_key=f"{tf}:KAMA_FLIP:{v.t[i] if phase == 'TRIGGER' else 'pending'}",
                event_key=f"TREND_CONT:LONG:{tf}:KAMA", anchor_time=v.t[i],
                entry_plan=plan("STATE_CHANGE", entry, None, "zamknięcie powyżej KAMA + pasmo histerezy przy ER ≥ progu", k[i] + band, 2, 1.0),
                invalidation_level=k[i] - band, stop_loss=sl, targets=r_targets("LONG", entry, sl, (1.5, 3.0), "R"),
                exit_rules={"time_exit_bars": p["time_exit_bars"], "be_after_tp1": True, "trailing": "KAMA_STATE_FLIP"},
                expires_bars=p["expires_bars"],
                components={"structure": min(1.0, er / 0.6), "formation": 1.0 if rising else 0.5,
                            "trigger": (1.0 if (v.c[i] - (k[i] + band)) <= a else 0.5) if phase == "TRIGGER" else 0.0},
                momentum_mode="CONTINUATION", missing=missing, reason_codes=[f"ER_{er:.2f}", "KAMA_RISING" if rising else "KAMA_FLAT"],
                facts={"kama_px": round(k[i], 3), "band_px": round(k[i] + band, 3), "er": round(er, 3)},
                horizon="INTRADAY"))
        return out
