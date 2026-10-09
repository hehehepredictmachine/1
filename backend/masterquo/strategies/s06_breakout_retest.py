"""S06 BREAKOUT_RETEST - break of a confirmed level, return to it, reaction.

The sequence break -> retest -> reaction is mandatory; before the retest only WATCH/EARLY exist.
LONG (SHORT mirrored):
  level      most recent confirmed swing high (pivot 3/3) known before the break, max age `level_age`
  break      a CLOSED bar k (within the last `max_since_break` bars) closes above level + buffer
  WATCH      break done, no retest yet, price <= level + watch_dist_atr x ATR above the level
  EARLY      retest: a bar after k (closed or forming) with low <= level + retest_tol_atr x ATR and no close
             below level - fail_atr x ATR
  TRIGGER    CLOSED bar after the retest bar (<= 3 bars later) closes above the retest bar high
  invalid.   close below level - fail_atr x ATR
  SL         min(retest low, level) - 0.2 ATR (+spread for SHORT)
  targets    TP1 = highest high since the break, TP2 = 2R
"""
from __future__ import annotations

from .base import Draft, MarketView, Strategy, long_stop
from .common import level_bucket, plan, valid_targets


class BreakoutRetest(Strategy):
    id = "S06"
    name = "BREAKOUT_RETEST"
    version = "1.0.0-EXPERIMENTAL"
    family = "BREAKOUT"
    setup_tfs = ("M5", "M15")
    context_tf = "H1"
    required_tfs = ("M5", "M15")
    min_bars = 80
    regime_fit = {"EXPANSION": 0.8, "TREND_UP": 0.8, "TREND_DOWN": 0.8, "TRANSITION": 0.6, "COMPRESSION": 0.4, "RANGE": 0.3,
                  "EXHAUSTION_OR_REVERSAL_CANDIDATE": 0.1}
    params = {"tfs": ["M5", "M15"], "level_age": 60, "max_since_break": 20, "buffer_atr": 0.1, "watch_dist_atr": 2.0,
              "retest_tol_atr": 0.3, "fail_atr": 0.5, "time_exit_bars": 30, "expires_bars": 6}

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
            buf = p["buffer_atr"] * a
            found = None
            for k in range(i, max(i - p["max_since_break"], 1) - 1, -1):
                piv = [q for q in v.pivots() if q["kind"] == "H" and q["confirmed_index"] < k and k - q["index"] <= p["level_age"]]
                if not piv:
                    continue
                lvl = max(piv, key=lambda q: q["index"])
                if v.c[k] > lvl["price"] + buf and v.c[k - 1] <= lvl["price"] + buf:
                    found = (k, lvl)
                    break
            if not found:
                continue
            k, lvl = found
            level = lvl["price"]
            fail = level - p["fail_atr"] * a
            if any(v.c[j] < fail for j in range(k + 1, i + 1)):
                continue                                       # retest failed: invalid, nothing to publish
            retest = next((j for j in range(k + 1, i + 1) if v.l[j] <= level + p["retest_tol_atr"] * a), None)
            forming_retest = bool(v.forming and v.forming["l"] <= level + p["retest_tol_atr"] * a and v.forming["c"] >= fail)
            post_high = max(v.h[k:i + 1])
            phase, missing = None, []
            if retest is not None and i > retest and i - retest <= 3 and v.c[i] > v.h[retest]:
                phase = "TRIGGER"
            elif retest is not None and i - retest <= 3:
                phase, missing = "EARLY", ["REACTION_CLOSE_ABOVE_RETEST_HIGH"]
            elif retest is None and forming_retest:
                phase, missing = "EARLY", ["RETEST_BAR_NOT_CLOSED", "REACTION_CLOSE_ABOVE_RETEST_HIGH"]
            elif retest is None and v.c[i] - level <= p["watch_dist_atr"] * a:
                phase, missing = "WATCH", ["RETEST_OF_BROKEN_LEVEL"]
            if phase is None:
                continue
            rlow = v.l[retest] if retest is not None else (v.forming["l"] if forming_retest else level)
            entry = v.c[i] if phase == "TRIGGER" else (v.h[retest] if retest is not None else level + p["retest_tol_atr"] * a)
            sl = long_stop(view, min(rlow, level), 0.2 * a)
            risk = abs(entry - sl)
            tg = valid_targets("LONG", entry, sl, [(post_high, 0.5, "POST_BREAK_HIGH"), (entry + 2 * risk, 0.5, "2R")])
            out.append(Draft(
                strategy_id=self.id, direction="LONG", timeframe=tf, phase=phase,
                structure_key=f"{tf}:LVL:{v.t[lvl['index']]}", event_key=f"BREAKOUT:LONG:{level_bucket(view, level)}", anchor_time=v.t[lvl["index"]],
                entry_plan=plan("RETEST_REACTION", entry, (level - p["retest_tol_atr"] * a, level + p["retest_tol_atr"] * a),
                                "zamknięcie powyżej high świecy retestu (≤ 3 świece)", entry, 3, 1.0),
                invalidation_level=fail, stop_loss=sl, targets=tg,
                exit_rules={"time_exit_bars": p["time_exit_bars"], "be_after_tp1": True, "trailing": None}, expires_bars=p["expires_bars"],
                components={"structure": 1.0 if i - k <= 10 else 0.6, "formation": 1.0 if retest is not None else (0.5 if forming_retest else 0.3),
                            "trigger": 1.0 if phase == "TRIGGER" else 0.0},
                momentum_mode="CONTINUATION", missing=missing, reason_codes=["LEVEL_BROKEN", "RETEST" if retest is not None else "NO_RETEST_YET"],
                facts={"level_px": round(level, 3), "break_bar": v.t[k], "retest_bar": v.t[retest] if retest is not None else None,
                       "post_break_high_px": round(post_high, 3)},
                horizon="SCALP" if tf == "M5" else "INTRADAY"))
        return out
