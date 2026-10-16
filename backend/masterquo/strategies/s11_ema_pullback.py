"""S11 EMA20_PULLBACK_2_5R - the attached Pine strategy "EMA20 Pullback + 2.5R" after the audit (FIXED state machine).

LONG rules (SHORT = mirrored prices), on CLOSED bars of the setup timeframe (M15, M30; H8 = optional trend filter):
  trend      EMA20 > EMA50 (Pine ta.ema definition, ema_pullback_core)
  touch      bar low reaches EMA20 x (1 + tolerance%) while in trend; the FIRST touch opens the setup (setup id = its bar)
  wait       confirmation allowed on bars touch+1 .. touch+max_pullback_bars; trend change -> INVALIDATED, timeout -> EXPIRED
  TRIGGER    a LATER closed bar closes above EMA20 with the trend still up and ADX >= threshold (+ optional filters)
  SL         lowest low of `swing_lookback` bars ending at the confirmation bar - atr_buffer x ATR (+ spread for SHORT)
  TP         entry + rr x (entry - SL); the plan is MARKET_ON_CONFIRMATION and the TP is recomputed from the real entry
             (exit_rules.tp_rule = RR_FROM_FILL) - no TP1/TP2 split, no partial exits
A confirmed setup that is blocked (position, cooldown, risk) is consumed: it is never executed later.
The forming bar is shown as a preview only (phase EARLY at most); a confirmation needs a closed bar.
Validation status: FUNCTIONAL_ONLY_OOS_NOT_RUN - the claimed 42.86% winrate / PF 1.52 of the original file are NOT verified.
"""
from __future__ import annotations

from . import ema_pullback_core as core
from .base import Draft, MarketView, Strategy, long_stop
from .common import plan

KEYS = ("len_ema20", "len_ema50", "touch_tolerance_pct", "max_pullback_bars", "require_green_red", "use_adx", "adx_len",
        "adx_smoothing", "adx_threshold", "swing_lookback", "atr_len", "atr_buffer_mult", "rr", "touch_mode", "touch_tol_atr",
        "require_approach", "max_depth_atr", "confirm_mode", "min_ema_sep_atr", "h8_trend_filter")


def core_params(p: dict) -> core.Params:
    return core.Params(**{k: p[k] for k in KEYS if k in p})


class EmaPullback(Strategy):
    id = "S11"
    name = "EMA20_PULLBACK_2_5R"
    version = "1.1.0-FIXED-EXPERIMENTAL"
    family = "TREND"
    horizon = "INTRADAY"
    setup_tfs = ("M15", "M30")
    context_tf = "H8"
    required_tfs = ("M15", "M30")
    min_bars = 160          # core.warmup_bars(default params) = 150 + margin
    regime_fit = {"TREND_UP": 1.0, "TREND_DOWN": 1.0, "TRANSITION": 0.6, "EXPANSION": 0.5, "COMPRESSION": 0.3, "RANGE": 0.1,
                  "EXHAUSTION_OR_REVERSAL_CANDIDATE": 0.2}
    params = {"tfs": ["M15", "M30"], **{k: getattr(core.Params(), k) for k in KEYS}, "expires_bars": 2, "window": 400}
    validation_status = "FUNCTIONAL_ONLY_OOS_NOT_RUN"

    def check_data(self, view: MarketView):
        st, why = super().check_data(view)
        if st == "OK" and self.params.get("h8_trend_filter") and not view.tfs.get("H8"):
            return "DATA_MISSING", ["BRAK_DANYCH_H8"]
        return st, why

    def detect_long(self, view: MarketView, p: dict) -> list[Draft]:
        cp = core_params(p)
        out = []
        for tf in p["tfs"]:
            v = view.tfs.get(tf)
            if v is None or len(v) < self.min_bars:
                continue
            n0 = max(0, len(v) - int(p.get("window", 400)))
            o, h, lo, c, t = v.o[n0:], v.h[n0:], v.l[n0:], v.c[n0:], v.t[n0:]
            h8 = None
            missing = []
            if cp.h8_trend_filter:
                hv = view.tfs.get("H8")
                if hv is None or len(hv) == 0:
                    missing.append("BRAK_DANYCH_H8")
                else:
                    from datetime import datetime
                    ts = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()  # noqa: E731
                    from ..timeutil import TF_SECONDS
                    sec = TF_SECONDS[tf]
                    h8 = core.asof_h8_trend([ts(x) + sec for x in t], [{"close_ts": ts(x) + 28800, "c": y} for x, y in zip(hv.t, hv.c)], cp)
            ind = core.indicators(o, h, lo, c, cp)
            res = core.run_fixed(o, h, lo, c, cp, ind, h8)
            i = len(c) - 1
            e20, e50, atr, adx = ind["ema20"], ind["ema50"], ind["atr"], ind["adx"]
            if atr[i] is None or adx[i] is None:
                continue
            trend_up = e20[i] > e50[i]
            last = [e for e in res.events if e.i == i and e.direction == "LONG"]
            conf = next((e for e in last if e.kind == "CONFIRM"), None)
            blocked = next((e for e in last if e.kind == "BLOCKED_FILTER"), None)
            waiting = res.waiting.get("LONG")
            if conf is None and waiting is None and not trend_up:
                continue
            near = abs(c[i] - e20[i]) <= 1.0 * atr[i]
            if conf is None and waiting is None and blocked is None and not near:
                continue
            if conf:
                phase, ref, stop, sid = "TRIGGER", conf.ref_price, conf.stop, conf.setup_id
            else:
                sw = core.lowest(lo, i, cp.swing_lookback)
                phase = "EARLY" if waiting else "WATCH"
                ref, stop = max(c[i], e20[i]), sw - atr[i] * cp.atr_buffer_mult
                sid = waiting["setup_id"] if waiting else i
                if blocked:
                    missing.append(blocked.reason)
            if view.mirrored:
                stop = long_stop(view, stop, 0.0)                         # SHORT stop includes the spread (stopped on Ask)
            # a forming-bar touch is a preview: it can only raise WATCH to EARLY, never confirm
            if phase == "WATCH" and v.forming and trend_up and v.forming["l"] <= e20[i] * (1 + cp.touch_tolerance_pct / 100):
                phase = "EARLY"
                missing.append("TOUCH_ON_FORMING_BAR_PREVIEW")
            if phase != "TRIGGER":
                missing.append("CONFIRMATION_CLOSE_ABOVE_EMA20_ON_LATER_BAR")
            if cp.use_adx and adx[i] < cp.adx_threshold:
                missing.append(f"ADX_BELOW_{cp.adx_threshold:g}")
            risk = ref - stop
            if risk <= 0:
                continue
            tp = ref + cp.rr * risk
            setup_bar = t[sid] if 0 <= sid < len(t) else t[i]
            wait_left = None if not waiting or cp.max_pullback_bars == 0 else cp.max_pullback_bars - (i - waiting["touch_i"])
            out.append(Draft(
                strategy_id=self.id, direction="LONG", timeframe=tf, phase=phase,
                structure_key=f"{tf}:{setup_bar}", event_key=f"EMA20_PULLBACK:LONG:{tf}:{setup_bar}", anchor_time=setup_bar,
                entry_plan=plan("EMA20_PULLBACK_CONFIRM", ref, (e20[i] * (1 - cp.touch_tolerance_pct / 100), e20[i] * (1 + cp.touch_tolerance_pct / 100)),
                                "zamknięcie świecy powyżej EMA20 na świecy PÓŹNIEJSZEJ niż dotknięcie, trend EMA20>EMA50 nadal ważny",
                                e20[i], 1, 0.5),
                invalidation_level=stop, invalidation_rule="CLOSE_BEYOND", stop_loss=stop,
                targets=[{"price": tp, "weight": 1.0, "basis": f"RR_{cp.rr:g}_FROM_ENTRY"}],
                exit_rules={"tp_rule": "RR_FROM_FILL", "rr": cp.rr, "be_after_tp1": False, "trailing": None, "time_exit_bars": None},
                expires_bars=int(p.get("expires_bars", 2)),
                components={"structure": min(1.0, (adx[i] or 0) / 35.0), "formation": 1.0 if (conf or waiting) else 0.4,
                            "trigger": 1.0 if conf else 0.0},
                momentum_mode="CONTINUATION", missing=missing,
                reason_codes=["EMA20>EMA50", f"ADX_{adx[i]:.0f}", f"SETUP_{setup_bar}"] + ([f"WAIT_LEFT_{wait_left}"] if wait_left is not None else []),
                facts={"ema20_px": round(e20[i], 5), "ema50_px": round(e50[i], 5), "atr": round(atr[i], 5), "adx": round(adx[i], 2),
                       "touch_bar": setup_bar, "confirm_bar": t[i] if conf else None, "rr": cp.rr, "core": core.CORE_VERSION},
                horizon="INTRADAY" if tf in ("M15", "M30") else "SCALP"))
        return out
