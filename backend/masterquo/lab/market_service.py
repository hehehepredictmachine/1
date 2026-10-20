"""PMW-UPD-09 runtime adapter of the R22-R25 cores for the Structure Intelligence snapshot (one producer, many consumers: snapshot
cells -> MTF dashboard / agent, REST /regimes /swings /smma /zscore). State per (instrument, TF): Market Behavior, RegimeMachine and
SmmaChannel are updated ONLY with new closed bars (a poll without a new bar changes nothing); a history revision (non-contiguous or
rewritten bar) resets the state and replays the bounded window. Regime/SMMA checkpoints are persisted (restart never recounts a bar).
Profiles come from market_profiles.json (dev calibration) when present, else the documented defaults."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import numpy as np

from . import market_v2 as V

TF_S = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600}
MAX_BARS = 600


def _state_dir() -> Path:
    import mq_instruments
    d = mq_instruments.data_dir() / "si_market_state"
    d.mkdir(parents=True, exist_ok=True)
    return d


def calibrated(inst: str) -> dict:
    try:
        from .structure_task import root
        p = root(inst) / "market_profiles.json"
        rep = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:                                            # noqa: BLE001
        rep = {}
    prof = rep.get("profiles") or {}
    rg = (prof.get(V.REGIME_PROFILE) or {}).get("chosen") or {}
    sm = (prof.get(V.SMMA_PROFILE) or {}).get("chosen") or {}
    return {"regime": {k: rg[k] for k in ("confirm", "trend_e") if k in rg}, "smma": sm, "source": "CALIBRATED_ON_DEV" if prof else "DEFAULT"}


class _Key:
    def __init__(self, inst: str, tf: str, tick: float):
        self.inst, self.tf, self.tick = inst, tf, tick
        cal = calibrated(inst)
        self.cal_source = cal["source"]
        self.mb = V.MarketBehavior(tf, TF_S[tf], tick=tick, context=f"{inst}|{tf}")
        self.rm = V.RegimeMachine(cal["regime"], tick)
        sm = cal["smma"]
        self.sm = V.SmmaChannel(boundary=sm.get("boundary", "CURRENT_CLOSED"), deadband=sm.get("deadband_ticks", 1) * tick,
                                max_gap_s=5 * TF_S[tf], tf_s=TF_S[tf], context=f"{inst}|{tf}")
        self.bars: list[dict] = []
        self.atr_rel: list[float] = []
        self.bands: list[dict] = []
        self.last_bias = "UNKNOWN"
        self.resumed = False

    @property
    def path(self) -> Path:
        return _state_dir() / f"{self.inst}_{self.tf}.json"


class MarketSections:
    def __init__(self):
        self.keys: dict[tuple, _Key] = {}
        self._lock = threading.Lock()

    def _replay(self, k: _Key, bars: list[dict], ck: dict | None) -> None:
        resume_after = (ck or {}).get("last_bar") if ck and ck.get("regime", {}).get("cfg_hash") == k.rm.hash else None
        ids = [b["open_utc"] for b in bars]
        if resume_after in ids:
            k.rm.restore(ck["regime"])
            k.bands = ck.get("bands", [])
            k.resumed = True
        for b in bars:
            self._step(k, b, skip_regime=bool(k.resumed and b["open_utc"] <= resume_after))

    def _step(self, k: _Key, b: dict, skip_regime: bool = False) -> None:
        k.bars.append(b)
        k.bars = k.bars[-MAX_BARS:]
        k.mb.update(b)
        k.sm.update(b)
        c = np.array([x["c"] for x in k.bars], dtype=float)
        atr = V.S._atr([x["h"] for x in k.bars], [x["l"] for x in k.bars], list(c), len(c) - 1, 14)
        k.atr_rel = (k.atr_rel + [atr / c[-1] if atr else float("nan")])[-MAX_BARS:]
        i = len(k.mb.c) - 1
        bias = k.mb.bias_at(i)
        opp = k.last_bias in ("UP", "DOWN") and bias in ("UP", "DOWN") and bias != k.last_bias
        if bias in ("UP", "DOWN"):
            k.last_bias = bias
        if skip_regime:
            return
        vol = V.vol_axis(np.array(k.atr_rel), len(k.atr_rel) - 1, k.rm.cfg["vol_window"], k.rm.cfg["vol_min"], k.rm.cfg["vol_lo"], k.rm.cfg["vol_hi"])
        v = k.rm.step(str(b["open_utc"]), c, atr, bias, opp, vol)
        k.bands = (k.bands + [{"t": b["open_utc"], "state": v["state"], "candidate": v["candidate"], "strength": v["strength"],
                               "volatility": vol.get("state"), "available_at": V._ts(b["open_utc"]) + TF_S[k.tf]}])[-MAX_BARS:]
        k.last_view = v

    def update(self, inst: str, tf: str, bars: list[dict], tick: float) -> _Key | None:
        """Feed closed bars (oldest first). Only bars newer than the last processed one are applied."""
        bars = bars[-MAX_BARS:]
        if len(bars) < 20:
            return None
        with self._lock:
            k = self.keys.get((inst, tf))
            if k is not None and len(k.mb.c) > 5 * MAX_BARS:
                k = None                                           # bounded memory: periodic rebuild from the window (ids are bar-time based)
            if k is not None and k.bars:
                last = k.bars[-1]["open_utc"]
                pos = next((j for j in range(len(bars) - 1, -1, -1) if bars[j]["open_utc"] == last), None)
                if pos is None or bars[pos]["c"] != k.bars[-1]["c"]:
                    k = None                                       # revision / gap beyond window -> rebuild
                else:
                    for b in bars[pos + 1:]:
                        self._step(k, b)
            if k is None:
                k = _Key(inst, tf, tick)
                ck = None
                try:
                    ck = json.loads(k.path.read_text(encoding="utf-8")) if k.path.exists() else None
                except (OSError, ValueError):
                    ck = None
                self._replay(k, bars, ck)
                self.keys[(inst, tf)] = k
            try:
                tmp = k.path.with_suffix(".tmp")
                tmp.write_text(json.dumps({"last_bar": k.bars[-1]["open_utc"], "regime": k.rm.checkpoint(), "bands": k.bands[-MAX_BARS:],
                                           "smma": k.sm.checkpoint()}, default=str), encoding="utf-8")
                tmp.replace(k.path)
            except OSError:
                pass
            return k

    # ---------------------------------------------------------------- views
    def summary(self, k: _Key | None) -> dict:
        if k is None:
            return {"status": "WARMING_UP"}
        rv = getattr(k, "last_view", None) or k.rm.view(None)
        story = k.mb.story()
        sm = k.sm.hist[-1] if k.sm.hist else {}
        c = np.array([b["c"] for b in k.bars], dtype=float)
        zi = V.zscore_at(c, len(c) - 1, 20, "INCLUSIVE_N", 0, k.tick)
        zp = V.zscore_at(c, len(c) - 1, 20, "PREVIOUS_N", 0, k.tick)
        return {"status": "OK", "profiles_source": k.cal_source,
                "regime": {"state": rv["state"], "candidate": rv["candidate"], "strength": rv["strength"], "volatility": (rv.get("volatility") or {}).get("state"),
                           "hysteresis": rv["hysteresis"], "cfg_hash": rv["cfg_hash"], "strength_is_probability": False},
                "behavior": {"bias": story["bias"], "last_final_leg": story["last_final_leg"], "provisional_tail": story["provisional_tail"],
                             "change_condition": story["change_condition"]},
                "smma": {"location": sm.get("location"), "event": sm.get("event"), "event_id": sm.get("event_id"), "U": sm.get("U"), "L": sm.get("L"),
                         "status": sm.get("status"), "profile": k.sm.profile},
                "zscore": {"inclusive": {x: zi.get(x) for x in ("z", "status", "window", "mean", "std")},
                           "previous": {x: zp.get(x) for x in ("z", "status", "window", "mean", "std")}}}

    def regimes(self, k: _Key, limit: int = 300) -> dict:
        rv = getattr(k, "last_view", None) or k.rm.view(None)
        return {"instrument": k.inst, "tf": k.tf, "current": rv, "bands": k.bands[-limit:], "history": k.rm.st["history"][-50:],
                "resumed_from_checkpoint": k.resumed, "profiles_source": k.cal_source,
                "note": "pasy pokazują stan znany po zamknięciu danej świecy (available_at); strength ≠ prawdopodobieństwo"}

    def swings(self, k: _Key, as_of: float | None = None, limit: int = 120) -> dict:
        sw = [s for s in sorted(k.mb.swings.values(), key=lambda s: s["origin_index"]) if as_of is None or s["known_at"] <= as_of][-limit:]
        legs = [lg for lg in k.mb.legs.values() if as_of is None or lg["available_at"] <= as_of][-limit:]
        out = []
        for s in sw:
            x = dict(s)
            if as_of is not None and s["sealed_at"] and s["sealed_at"] > as_of:
                x.update(sealed_at=None, status="TAIL")
            out.append(x)
        return {"instrument": k.inst, "tf": k.tf, "as_of": as_of, "swings": out, "legs": legs, "story": k.mb.story(), "profile": k.mb.profile}

    def swing(self, inst: str, sid: str, as_of: float | None = None) -> dict | None:
        for (i, tf), k in self.keys.items():
            if i == inst and sid in k.mb.swings:
                return dict(k.mb.swing_asof(sid, as_of) or {"id": sid, "status": "NOT_KNOWN_AT_AS_OF"}, tf=tf)
        return None

    def smma(self, k: _Key, limit: int = 200) -> dict:
        return {"instrument": k.inst, "tf": k.tf, "profile": k.sm.profile, "series": k.sm.hist[-limit:], "events": list(k.sm.events.values())[-100:]}

    def zscore(self, k: _Key, mode: str = "INCLUSIVE_N", n: int = 20) -> dict:
        return dict(V.zscore_series(k.bars, n=n, mode=mode, tick=k.tick, context=f"{k.inst}|{k.tf}", keep=200), instrument=k.inst, tf=k.tf)
