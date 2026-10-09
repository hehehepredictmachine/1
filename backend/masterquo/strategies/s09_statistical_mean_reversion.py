"""S09 STATISTICAL_MEAN_REVERSION - return after a measurable deviation from a rolling mean.

Hypothesis (to be tested, not assumed): a large z-score deviation of the close from its rolling
mean tends to partially revert. Price stationarity is NOT assumed; the rule is disabled in an
efficient trend (ER filter) where deviations tend to persist.
  estimator  z = (close - SMA(n)) / stdev(n), n = 40 on the setup TF
  necessary  ER(20) < max_er (no strong trend on the setup TF)
  LONG (SHORT mirrored)
  WATCH      z <= watch_z (-1.5)
  EARLY      z <= entry_z (-2.0) at the last closed bar (or the forming bar's close)
  TRIGGER    CLOSED bar: min z over the last 3 bars <= entry_z, z rising vs previous bar and a bullish close
  invalid.   close below SMA - stop_z x stdev (deviation keeps expanding), frozen at detection
  SL         min(SMA - stop_z x stdev, lowest low of 3 bars - 0.3 ATR) (+spread for SHORT)
  targets    TP1 = SMA - 1 x stdev (partial reversion), TP2 = SMA (full reversion)
  exit       time exit after `time_exit_bars` bars without reversion
"""
from __future__ import annotations

from .base import Draft, MarketView, Strategy, long_stop
from .common import plan, valid_targets
from .indicators import efficiency_ratio, rolling_std, sma


class StatisticalMeanReversion(Strategy):
    id = "S09"
    name = "STATISTICAL_MEAN_REVERSION"
    version = "1.0.0-EXPERIMENTAL"
    family = "REVERSION"
    setup_tfs = ("M5", "M15")
    context_tf = "H1"
    required_tfs = ("M5", "M15")
    min_bars = 60
    regime_fit = {"RANGE": 1.0, "TRANSITION": 0.6, "EXHAUSTION_OR_REVERSAL_CANDIDATE": 0.7, "COMPRESSION": 0.3, "EXPANSION": 0.3,
                  "TREND_UP": 0.1, "TREND_DOWN": 0.1}
    params = {"tfs": ["M5", "M15"], "n": 40, "watch_z": -1.5, "entry_z": -2.0, "stop_z": -3.5, "max_er": 0.35, "time_exit_bars": 20, "expires_bars": 4}

    def detect_long(self, view: MarketView, p: dict) -> list[Draft]:
        out = []
        for tf in p["tfs"]:
            v = view.tfs.get(tf)
            if v is None or len(v) < self.min_bars:
                continue
            i = v.last
            a = v.atr()[i]
            m = v.get(f"sma{p['n']}", lambda: sma(v.c, p["n"]))
            sd = v.get(f"sd{p['n']}", lambda: rolling_std(v.c, p["n"]))
            er = v.get("er20", lambda: efficiency_ratio(v.c, 20))[i]
            if not a or m[i] is None or not sd[i] or er is None:
                continue
            z = [None if m[k] is None or not sd[k] else (v.c[k] - m[k]) / sd[k] for k in range(i - 3, i + 1)]
            if any(x is None for x in z):
                continue
            zf = (v.forming["c"] - m[i]) / sd[i] if v.forming else None
            if er >= p["max_er"]:
                continue
            phase, missing = None, []
            if min(z[-3:]) <= p["entry_z"] and z[-1] > z[-2] and v.c[i] > v.o[i]:
                phase = "TRIGGER"
            elif z[-1] <= p["entry_z"] or (zf is not None and zf <= p["entry_z"]):
                phase, missing = "EARLY", ["Z_TURNING_UP_WITH_BULLISH_CLOSE"]
            elif z[-1] <= p["watch_z"]:
                phase, missing = "WATCH", ["Z_EXTREME_NOT_REACHED"]
            if phase is None:
                continue
            inval = m[i] + p["stop_z"] * sd[i]
            entry = v.c[i]
            sl = long_stop(view, min(inval, min(v.l[i - 2:i + 1]) - 0.3 * a), 0.0)
            tg = valid_targets("LONG", entry, sl, [(m[i] - sd[i], 0.5, "MEAN_MINUS_1SD"), (m[i], 0.5, "MEAN")])
            if not tg:
                missing.append("NO_ROOM_TO_MEAN")
            # episode anchor: the bar where z last crossed below watch_z (stable while the episode lasts)
            start = i
            for k in range(i, max(i - 30, p["n"]) - 1, -1):
                zk = (v.c[k] - m[k]) / sd[k] if m[k] is not None and sd[k] else None
                if zk is None or zk > p["watch_z"]:
                    break
                start = k
            out.append(Draft(
                strategy_id=self.id, direction="LONG", timeframe=tf, phase=phase,
                structure_key=f"{tf}:Z:{v.t[start]}",
                event_key=f"MEANREV:LONG:{tf}", anchor_time=v.t[i],
                entry_plan=plan("MEAN_REVERSION", entry, None, "z-score zawraca z poziomu ≤ progu i świeca zamyka się wzrostowo", entry, 2, 1.5),
                invalidation_level=inval, stop_loss=sl, targets=tg,
                exit_rules={"time_exit_bars": p["time_exit_bars"], "be_after_tp1": True, "trailing": None}, expires_bars=p["expires_bars"],
                components={"structure": max(0.0, min(1.0, (p["max_er"] - er) / p["max_er"] + 0.3)),
                            "formation": min(1.0, abs(min(z)) / 3.0), "trigger": 1.0 if phase == "TRIGGER" else 0.0},
                momentum_mode="REVERSAL", missing=missing, reason_codes=[f"Z_DEVIATION_{abs(z[-1]):.2f}", f"ER_{er:.2f}"],
                facts={"z_sgn": round(z[-1], 2), "z_extreme3_sgn": round(min(z[-3:]), 2), "mean_px": round(m[i], 3), "stdev": round(sd[i], 4), "er": round(er, 3)},
                horizon="SCALP" if tf == "M5" else "INTRADAY"))
        return out
