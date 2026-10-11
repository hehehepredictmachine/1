"""M30 / H8 context for the monitor and the decision record (from the bridge's bars, closed bars only for indicators).

For each context timeframe: data source (native MT5 series or controlled resampling), last closed bar and the forming
bar (open/closed), direction (EMA20 vs EMA50, Pine-style EMA like S11), regime (MarketRegimeEngine), key levels and the
impact on decisions. A missing timeframe is shown as BRAK_DANYCH - never hidden. Closed H8 bars are used as-of: the
forming H8 bar is a preview and never feeds a confirmed decision.
"""
from __future__ import annotations

from ..strategies import ema_pullback_core as epc
from ..strategies import regime as regime_mod
from ..strategies.base import TFView
from ..timeutil import CONTEXT_TIMEFRAMES, TF_REGISTRY

ROLE_PL = {"SETUP_CONTEXT": "kontekst setupu (S11 liczy setupy także na M30)", "TREND_REGIME_CONTEXT": "trend / reżim / poziomy (filtr H8 dla S11 – opcja)"}


def summarize(bars_by_tf: dict[str, list[dict]], dq_tf: dict, s11_params: dict | None = None) -> dict:
    out = {}
    for tf in CONTEXT_TIMEFRAMES:
        bars = bars_by_tf.get(tf) or []
        q = (dq_tf or {}).get(tf) or {}
        closed = [b for b in bars if b.get("closed") and b.get("open_utc")]
        forming = bars[-1] if bars and not bars[-1].get("closed") else None
        if len(closed) < 60:
            out[tf] = {"status": "BRAK_DANYCH", "quality": q.get("status"), "closed_bars": len(closed), "role": TF_REGISTRY[tf]["role"],
                       "role_pl": ROLE_PL.get(TF_REGISTRY[tf]["role"]), "impact": "Strategie wymagające tego interwału: BRAK_DANYCH, blokada potwierdzenia."}
            continue
        c = [b["c"] for b in closed]
        e20, e50 = epc.pine_ema(c, 20), epc.pine_ema(c, 50)
        direction = "UP" if e20[-1] > e50[-1] else ("DOWN" if e20[-1] < e50[-1] else "FLAT")
        reg = regime_mod.tf_regime(TFView(tf, closed), regime_mod.DEFAULTS)
        hi20 = max(b["h"] for b in closed[-20:])
        lo20 = min(b["l"] for b in closed[-20:])
        last = closed[-1]
        h8f = bool((s11_params or {}).get("h8_trend_filter"))
        if tf == "H8":
            impact = ("Filtr trendu H8 dla S11 WŁĄCZONY: potwierdzenia tylko zgodne z kierunkiem " + direction) if h8f else \
                     "Kontekst informacyjny (filtr H8 dla S11 wyłączony – hipoteza w testach, nie promowana)."
        else:
            impact = "S11 wykrywa setupy także na M30; regime/kontekst pomocniczy."
        out[tf] = {"status": "OK" if q.get("status") in (None, "OK") else q.get("status"), "quality": q.get("status"),
                   "source": last.get("source", "native"), "parts": last.get("parts"),
                   "last_closed_open_utc": last["open_utc"], "last_closed_confirmed_utc": last.get("close_confirmed_utc"),
                   "forming": {"open_utc": forming["open_utc"], "o": forming["o"], "h": forming["h"], "l": forming["l"], "c": forming["c"],
                               "note": "świeca otwarta – tylko podgląd"} if forming else None,
                   "direction": direction, "ema20": round(e20[-1], 5), "ema50": round(e50[-1], 5),
                   "regime": reg.get("state"), "regime_reason": reg.get("reason"),
                   "levels": {"last_high": last["h"], "last_low": last["l"], "high_20": hi20, "low_20": lo20},
                   "closed_bars": len(closed), "role": TF_REGISTRY[tf]["role"], "role_pl": ROLE_PL.get(TF_REGISTRY[tf]["role"]), "impact": impact}
    return out
