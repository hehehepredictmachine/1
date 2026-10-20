"""Runtime flow-context sections (FF08): one producer per (instrument, TF) fed with CLOSED bars by the Structure Intelligence snapshot
(same parent snapshot), consumers: snapshot cells / MTF / agent / REST. Heikin Flow, StopDistance and the S/R channel archive commit once
per closed bar (repeated polls change nothing; a history revision rebuilds from the bounded window). Markov models come only from a fitted
artefact (`flow-context train-markov`); without it MODEL_MISSING - the deterministic indicators still work."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from . import heikin as HF
from . import markov as MK
from . import native as NV
from . import sr_channels as SR
from . import stop_distance as SD
from . import task as FT

TF_S = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600}
WINDOW = 800


class _Key:
    def __init__(self, inst: str, tf: str, point: float, tick: float):
        self.inst, self.tf, self.point, self.tick = inst, tf, point, tick
        prof = FT.profile(inst)
        self.profile_hash = prof["hash"]
        self.hf = HF.HeikinFlow(prof["heikin"], point)
        self.sd = SD.StopDistance(prof["stopdistance"], point, tick)
        self.srh = SR.ChannelHistory(prof["sr"], f"{inst}|{tf}", keep=WINDOW)
        self.bars: list[dict] = []
        self.ha: list[dict] = []
        self.sdr: list[dict] = []
        self.m3 = self.md = None
        self.m3_last = self.md_last = None
        self.model_dir = None
        self._load_models()

    def _load_models(self):
        p = FT.root(self.inst) / "markov" / "latest.txt"
        if not p.exists():
            return
        d = Path(p.read_text(encoding="utf-8").strip())
        try:
            m3 = MK.Markov3.from_dict(json.loads((d / "markov3.json").read_text(encoding="utf-8")))
            md = MK.MarkovDiff.load(d / "diff")
            if abs(m3.point - self.point) > 1e-12:
                return                                            # context mismatch (other point) -> model not used
            self.m3, self.md, self.model_dir = m3, md, str(d)
        except (OSError, ValueError):
            self.m3 = self.md = None


class FlowSections:
    def __init__(self):
        self.keys: dict = {}
        self._lock = threading.Lock()
        self.importer = None

    def update(self, inst: str, tf: str, bars: list[dict], point: float, tick: float) -> _Key | None:
        bars = bars[-WINDOW:]
        if len(bars) < 30:
            return None
        with self._lock:
            k = self.keys.get((inst, tf))
            if k is not None and (k.profile_hash != FT.profile(inst)["hash"]):
                k = None                                          # profile changed -> new state, reason in snapshot
            new = bars
            if k is not None and k.bars:
                last = k.bars[-1]["open_utc"]
                pos = next((j for j in range(len(bars) - 1, -1, -1) if bars[j]["open_utc"] == last), None)
                if pos is None or bars[pos]["c"] != k.bars[-1]["c"]:
                    k = None
                else:
                    new = bars[pos + 1:]
            if k is None:
                k = _Key(inst, tf, point, tick)
                self.keys[(inst, tf)] = k
                new = bars
            for b in new:
                k.bars = (k.bars + [b])[-WINDOW:]
                r = k.hf.update(b)
                if r:
                    k.ha = (k.ha + [r])[-WINDOW:]
                s = k.sd.update(b)
                if s:
                    k.sdr = (k.sdr + [s])[-WINDOW:]
                if len(k.bars) > 2 * 10 + 1:
                    k.srh.update(k.bars)
                if tf == "M1" and k.m3 is not None and len(k.bars) >= 3 and b is new[-1]:
                    k.m3_last = k.m3.step(k.bars[-3:])
                    k.md_last = k.md.step(k.bars[-2:], 15)
            return k

    def summary(self, k: _Key | None) -> dict:
        if k is None:
            return {"status": "WARMING_UP"}
        ha = k.ha[-1] if k.ha else {}
        sd = k.sdr[-1] if k.sdr else {}
        snap = k.srh.snaps[-1] if k.srh.snaps else None
        nn = SR.nearest(snap, k.bars[-1]["c"]) if snap else None
        out = {"status": "OK", "profile_hash": k.profile_hash,
               "heikin": {"color": ha.get("color"), "quality": ha.get("quality"), "o": ha.get("o"), "c": ha.get("c"), "units": "synthetic"},
               "stopdistance": {k2: sd.get(k2) for k2 in ("range_points", "average_points", "suggested_points", "suggested_price_distance", "status")},
               "sr": {"nearest": nn, "channels": len(snap["channels"]) if snap else 0, "flags": snap["flags"] if snap else None}}
        if k.tf == "M1":
            if k.m3_last:
                out["markov3"] = {"state": k.m3_last.get("state"), "next": k.m3_last.get("next"), "entropy": k.m3_last.get("entropy_next"),
                                  "support": k.m3_last.get("support")}
            else:
                out["markov3"] = {"status": "MODEL_MISSING" if k.m3 is None else "WARMUP"}
            if k.md_last and k.md_last.get("projection"):
                p = k.md_last["projection"]
                out["buckets"] = {h: {"price_mean": p[h]["price_mean"], "price_q": p[h]["price_q"]} for h in ("5", "15") if h in p}
                out["buckets"]["K_effective"] = k.md_last["K_effective"]
            else:
                out["buckets"] = {"status": "MODEL_MISSING" if k.md is None else ((k.md_last or {}).get("eligibility") or {}).get("reason", "WARMUP")}
        return out

    def series(self, k: _Key, limit: int = 300) -> dict:
        return {"instrument": k.inst, "tf": k.tf, "algorithm": HF.ALGO, "config": k.hf.cfg, "units": "synthetic price (nie cena wykonania)",
                "raw": k.bars[-limit:], "heikin": k.ha[-limit:], "stopdistance": k.sdr[-limit:], "source_parity": "UNVERIFIED_ORIGINAL"}

    def channels(self, k: _Key, as_of=None, mode: str = "CURRENT_MAP_FULL_WIDTH") -> dict:
        if mode == "HISTORY_AS_KNOWN":
            snaps = [s for s in k.srh.snaps if as_of is None or str(s["as_of"]) <= str(as_of)]
            return {"mode": mode, "snapshots": [{"as_of": s["as_of"], "channels": s["channels"]} for s in snaps[-120:]], "events": k.srh.events[-200:]}
        snap = k.srh.as_of(as_of) if as_of is not None else (k.srh.snaps[-1] if k.srh.snaps else None)
        return {"mode": mode, "snapshot": snap, "events": k.srh.events[-100:],
                "label": f"bieżąca mapa, znana od {snap['as_of']}" if snap else None}

    def markov(self, k: _Key) -> dict:
        if k.m3 is None:
            return {"status": "MODEL_MISSING", "hint": "python -m masterquo flow-context train-markov --latest"}
        return {"status": "OK", "model_dir": k.model_dir, "markov3": k.m3_last, "buckets": k.md_last,
                "fit": {"markov3": k.m3.fit_info, "buckets": k.md.fit_info}}

    def stopdistance(self, k: _Key, entry: float | None, side: str | None, strategy_sl_points: float | None = None) -> dict:
        row = k.sdr[-1] if k.sdr else None
        if row is None:
            return {"status": "WARMUP"}
        out = {"row": row, "diagnostics": SD.risk_diagnostics(row, strategy_sl_points)}
        if entry is not None and side in ("BUY", "SELL") and row.get("suggested_price_distance") is not None:
            out["sl_price_proposal"] = SD.sl_price(entry, side, row["suggested_price_distance"], k.tick)
            out["note"] = "propozycja ADVISORY – nie zmienia SL strategii ani TP1=MID M5; cena SL po zaokrągleniu na zewnątrz do tick size"
        return out

    def native(self, inst: str, symbol: str) -> dict:
        files = os.environ.get("MQ_MT5_FILES_DIR")
        if self.importer is None or self.importer.dir != (Path(files) if files else None):
            self.importer = NV.FlowImporter(files, symbol, "M15")
        st = NV.native_status(Path(files) / "PMW" / "flow_native_status.json" if files else None)
        return {"feed": self.importer.poll(), "compile": st, "original_parity": "UNVERIFIED_ORIGINAL", "role": "SHADOW_AUDIT"}
