"""BREAKOUT - one shared breakout logic module (channel + volatility compression + confirmation), extending mm_breakout.

Definitions (rules v1, all causal on CLOSED bars):
  channel_t  = max(high) / min(low) of the N bars BEFORE bar t (the bar being tested never widens its own threshold);
  compression = channel width / ATR14 <= k_comp (narrow range);
  breakout   = close_t > channel_high_t (UP) or < channel_low_t (DOWN); an intrabar cross without the close is only PRE_BREAK;
  confirmed  = the next closed bar stays beyond the broken edge;
  retest     = a later bar touches the broken edge (within 0.1 ATR) and closes on the breakout side;
  false      = a close back inside the channel within `fail_bars` before confirmation;
  invalidated= a close beyond the opposite edge; timeout = no confirmation within `timeout_bars`.
The rules work without ML. Parameters (N, k_comp) are VALIDATED on development data by the after-cost expectancy of a fixed exit
(H bars) - not by the count of correct directions. The state is a rule output, its score is heuristic (not a probability).
"""
from __future__ import annotations

import json

import numpy as np

from . import base as B


def atr(h, l, c, n=14):
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    out = np.full(len(c), np.nan)
    for i in range(n, len(c)):
        out[i] = tr[i - n:i].mean()
    return out


def scan(bars: list[dict], N: int = 20, k_comp: float = 3.0, fail_bars: int = 3, timeout_bars: int = 6) -> list[dict]:
    h = np.asarray([b["h"] for b in bars]); l = np.asarray([b["l"] for b in bars]); c = np.asarray([b["c"] for b in bars])
    a = atr(h, l, c)
    events, active = [], None
    for i in range(N + 15, len(c)):
        hi, lo = h[i - N:i].max(), l[i - N:i].min()
        comp = (hi - lo) / a[i - 1] if a[i - 1] and a[i - 1] > 0 else np.nan
        if active is not None:
            ev = active
            age = i - ev["i"]
            if ev["state"] == "BREAKOUT":
                inside = c[i] < ev["edge"] if ev["dir"] == "UP" else c[i] > ev["edge"]          # close back inside the channel
                if inside and age <= fail_bars:
                    ev.update(state="FALSE_BREAKOUT", end=i)
                    active = None
                elif not inside and age == 1:
                    ev.update(state="CONFIRMED", confirmed_at=i)
                elif age > timeout_bars:
                    ev.update(state="TIMEOUT", end=i)
                    active = None
            elif ev["state"] in ("CONFIRMED", "RETEST"):
                opp = c[i] < ev["opp"] if ev["dir"] == "UP" else c[i] > ev["opp"]
                if opp:
                    ev.update(state="INVALIDATED", end=i)
                    active = None
                elif ev["state"] == "CONFIRMED" and (l[i] <= ev["edge"] + 0.1 * a[i] if ev["dir"] == "UP" else h[i] >= ev["edge"] - 0.1 * a[i]) and \
                        (c[i] > ev["edge"] if ev["dir"] == "UP" else c[i] < ev["edge"]):
                    ev.update(state="RETEST", retest_at=i)
                elif age > 4 * timeout_bars:
                    ev.update(end=i)
                    active = None
            continue
        if not np.isfinite(comp):
            continue
        if c[i] > hi or c[i] < lo:
            d = "UP" if c[i] > hi else "DOWN"
            active = {"i": i, "t": bars[i]["t"], "dir": d, "edge": float(hi if d == "UP" else lo), "opp": float(lo if d == "UP" else hi),
                      "compressed": bool(comp <= k_comp), "compression": float(comp), "state": "BREAKOUT", "close": float(c[i])}
            events.append(active)
    return events


def expectancy(bars, events, H=6, cost=0.0, only_compressed=True) -> dict:
    c = np.asarray([b["c"] for b in bars])
    pnl = []
    for e in events:
        if only_compressed and not e["compressed"]:
            continue
        j = e["i"] + 1                                            # enter at the NEXT bar close after the signal bar (no same-bar fill)
        if j + H >= len(c):
            continue
        s = 1 if e["dir"] == "UP" else -1
        pnl.append(s * (c[j + H] - c[j]) - cost)
    p = np.asarray(pnl)
    return {"trades": int(len(p)), "expectancy": float(p.mean()) if len(p) else None, "win_rate": float((p > 0).mean()) if len(p) else None,
            "profit_factor": float(p[p > 0].sum() / -p[p < 0].sum()) if len(p) and (p < 0).any() else None}


class Breakout(B.Family):
    ID = "BREAKOUT"
    NAME = "Breakout – wspólny moduł logiki wybicia (kanał, kompresja, potwierdzenie, retest)"
    KIND = "VALIDATED_RULES"
    FIT_LABEL = "walidacja parametrów"
    TASK_TYPE = "FILTER_STATE"
    UNIT = "mixed"
    TASK = "BREAKOUT_STATE"
    TF = "M5"
    RECEIVERS = ("SH_CONTEXT:breakout_state", "STRATEGY:S05/S12 BREAKOUT_RETEST context", "PANEL:model_status")
    DATA = {"kind": "BARS", "tf": "M5", "min_bars": 1500}

    def fit(self, data, cfg, tmp, budget):
        bars = data["bars"][-int(budget.get("max_rows", 8000)):]
        n = len(bars)
        dev = bars[: int(n * 0.8)]
        hold = bars[int(n * 0.8):]
        spread_pts = float(np.median([b.get("spread") or 0 for b in bars])) * float(data.get("point") or 0.01)
        grid = [(N, k) for N in (12, 20, 36) for k in (2.0, 3.0, 4.5)]
        res = []
        for N, k in grid:
            ex = expectancy(dev, scan(dev, N, k), cost=spread_pts)
            res.append({"N": N, "k_comp": k, **ex})
        ok = [r for r in res if r["trades"] >= 20 and r["expectancy"] is not None]
        pick = max(ok, key=lambda r: r["expectancy"]) if ok else {"N": 20, "k_comp": 3.0, "expectancy": None, "trades": 0}
        hold_ex = expectancy(hold, scan(hold, pick["N"], pick["k_comp"]), cost=spread_pts)
        art = {"N": pick["N"], "k_comp": pick["k_comp"], "fail_bars": 3, "timeout_bars": 6, "cost_used": spread_pts, "lookback": 400}
        (tmp / "breakout.json").write_text(json.dumps(art), encoding="utf-8")
        tail = bars[-art["lookback"]:]
        vm = {"dev_expectancy_after_cost": pick.get("expectancy"), "dev_trades": float(pick.get("trades") or 0)}
        return {"metrics": {"grid": res, "chosen": {"N": pick["N"], "k_comp": pick["k_comp"]}, "holdout": hold_ex,
                            "note": "wynik po koszcie spreadu, wyjście po H świecach; wejście na kolejnej świecy"},
                "validation": self.promotion(vm, {"dev_expectancy_after_cost": (">", 0.0), "dev_trades": (">", 19.0)}),
                "sample": {"bars_tail": tail, "expected": self._state(art, tail), "tolerance": 0.0}}

    def load(self, d):
        return json.loads((d / "breakout.json").read_text(encoding="utf-8"))

    def _state(self, art, bars):
        ev = scan(bars, art["N"], art["k_comp"], art["fail_bars"], art["timeout_bars"])
        last = ev[-1] if ev else None
        if last is None:
            return {"state": "NO_BREAKOUT", "bars_since": None, "edge": None, "compression": None}
        return {"state": last["state"], "direction": last["dir"], "edge": last["edge"], "opposite_edge": last["opp"],
                "compression": last["compression"], "bars_since": int(len(bars) - 1 - last["i"]), "event_time": int(last["t"])}

    def predict(self, art, live):
        bars = live["bars"][-art["lookback"]:]
        if len(bars) < art["N"] + 30:
            raise B.Unavailable("BLOCKED_DATA", "za mało świec dla kanału")
        return self._state(art, bars)
