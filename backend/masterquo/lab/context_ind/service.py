"""Runtime context sections (PMW-UPD-14 section 11.1): one producer per (instrument, TF, profile hash) fed with CLOSED bars by the Structure
Intelligence snapshot. VAMD / FD / Pullback+SMC process every closed bar in order (repeated polls change nothing; a history revision or a
profile change rebuilds from the bounded window under a new epoch). Forming previews never feed filters; SMC never evaluates bar0.
Structure events go to an append-only per-key ledger (unique event ids + epoch, idempotent on restart). The facts adapter exposes VAMD sign,
FD zone/quality and the latest published structure events to scenarios as OBSERVE/SHADOW with a separate `would_block`; FD TREND + VAMD>0
alone is never a BUY. External buffer sources come only through the verified-mapping bridge (AVAILABLE_UNVALIDATED, diagnostic)."""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime

from . import buffers as BF
from . import fractal as FD
from . import smc as SM
from . import task as CT
from . import vamd as VM

TF_S = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600}
WINDOW = 800
SERIES_KEEP = 600


def _ts(x) -> float:
    return x if isinstance(x, (int, float)) else datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp()


class _Key:
    def __init__(self, inst: str, tf: str, tick: float, epoch: int):
        self.inst, self.tf, self.tick, self.epoch = inst, tf, tick, epoch
        prof = CT.profile(inst)
        self.profile, self.profile_hash = prof, prof["hash"]
        self.vamd = VM.VAMD(prof.get("vamd"))
        self.fd = FD.FractalRegime(prof.get("fd"), tick)
        self.smc = SM.SMC(tick=tick, **(prof.get("smc") or {}))
        self.bars: list[dict] = []
        self.vrows: list[dict] = []
        self.frows: list[dict] = []
        self.ledgered = 0


class ContextSections:
    def __init__(self):
        self.keys: dict = {}
        self._lock = threading.Lock()
        self.bridge: BF.BridgeImporter | None = None
        self.epochs: dict = {}

    def _ledger(self, k: _Key) -> None:
        new = k.smc.events[k.ledgered:]
        if not new:
            return
        p = CT.root(k.inst) / "ledger" / f"{k.tf}_{k.profile_hash}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            for e in new:
                fh.write(json.dumps(dict(e, ledger_id=f"{k.inst}|{k.tf}|{k.profile_hash}|E{k.epoch}|{e['event_id']}", epoch=k.epoch)) + "\n")
        k.ledgered = len(k.smc.events)

    def update(self, inst: str, tf: str, bars: list[dict], tick: float, ledger: bool = True) -> _Key | None:
        bars = bars[-WINDOW:]
        if len(bars) < 30 or tf not in TF_S:
            return None
        with self._lock:
            k = self.keys.get((inst, tf))
            if k is not None and k.profile_hash != CT.profile(inst)["hash"]:
                k = None
            new = bars
            if k is not None and k.bars:
                last = k.bars[-1]["open_utc"]
                pos = next((j for j in range(len(bars) - 1, -1, -1) if bars[j]["open_utc"] == last), None)
                if pos is None or bars[pos]["c"] != k.bars[-1]["c"] or len(k.smc.bars) > 4 * WINDOW:
                    k = None                                       # revision / gap beyond window / bounded memory -> new epoch
                else:
                    new = bars[pos + 1:]
            if k is None:
                ep = self.epochs.get((inst, tf), 0) + 1
                self.epochs[(inst, tf)] = ep
                k = _Key(inst, tf, tick, ep)
                self.keys[(inst, tf)] = k
                new = bars
            for b in new:
                t_close = _ts(b["open_utc"]) + TF_S[tf]
                k.bars = (k.bars + [b])[-WINDOW:]
                k.vrows = (k.vrows + [dict(k.vamd.update(b), t=b["open_utc"])])[-SERIES_KEEP:]
                k.frows = (k.frows + [dict(k.fd.update(b), t=b["open_utc"])])[-SERIES_KEEP:]
                k.smc.update(b, t_close)
            if ledger:
                try:
                    self._ledger(k)
                except OSError:
                    pass
            return k

    # ------------------------------------------------------------------ facts adapter (scenarios / agent / cells)
    def summary(self, k: _Key | None) -> dict:
        if k is None:
            return {"status": "WARMING_UP"}
        v = k.vrows[-1] if k.vrows else {}
        f = k.frows[-1] if k.frows else {}
        sm = k.smc
        last = [e for e in sm.events if e["kind"].startswith(("BOS", "CHOCH", "IDM", "X_"))][-3:]
        out = {"status": "OK", "profile_hash": k.profile_hash, "epoch": k.epoch, "last_closed_open": k.bars[-1]["open_utc"],
               "vamd": {"status": v.get("status"), "y": v.get("y"), "m": v.get("m"), "alpha": v.get("alpha"), "profile": VM.PROFILE,
                        "note": "znak = momentum, nie p(win); brak targetu ≠ decay do 0"},
               "fd": {"status": f.get("status"), "fd_smooth": f.get("fd_smooth"), "zone": f.get("zone"), "saturated": f.get("saturated"),
                      "clipped": f.get("clipped"), "profile": FD.PROFILE, "note": "TREND bez strony"},
               "smc": {"trend": sm.trend, "active_high": sm.slot["H"].get("level") if sm.slot["H"].get("status") == "ACTIVE" else None,
                       "active_low": sm.slot["L"].get("level") if sm.slot["L"].get("status") == "ACTIVE" else None,
                       "pending": bool(sm.pending), "last_events": last, "state_hash": sm.state_hash(), "profile": sm.profile}}
        out["would_block"] = self.would_block(out)
        out["mode"] = "OBSERVE_SHADOW"
        return out

    @staticmethod
    def would_block(s: dict) -> dict:
        """Diagnostic only: which side a context filter WOULD block; never a trigger. Missing data -> UNKNOWN, not 'pass'."""
        res = {}
        y, zone, tr = (s.get("vamd") or {}).get("y"), (s.get("fd") or {}).get("zone"), (s.get("smc") or {}).get("trend")
        for side, sg in (("BUY", 1), ("SELL", -1)):
            reasons = []
            if y is None or zone is None:
                res[side] = {"status": "UNKNOWN", "reasons": ["VAMD/FD w rozgrzewce"]}
                continue
            if y * sg < 0:
                reasons.append("VAMD_AGAINST")
            if zone == "CHOP":
                reasons.append("FD_CHOP")
            if tr in ("UP", "DOWN") and (tr == "UP") != (sg > 0):
                reasons.append("SMC_TREND_AGAINST")
            res[side] = {"status": "WOULD_BLOCK" if reasons else "NO_BLOCK", "reasons": reasons,
                         "note": "SHADOW: filtr nie jest triggerem; brak blokady ≠ sygnał wejścia"}
        return res

    # ------------------------------------------------------------------ REST views
    def vamd(self, k: _Key, limit: int = 300, preview_bar: dict | None = None) -> dict:
        out = {"instrument": k.inst, "tf": k.tf, "profile": VM.PROFILE, "config": k.vamd.cfg, "profile_hash": k.profile_hash, "epoch": k.epoch,
               "series": k.vrows[-limit:], "current": k.vrows[-1] if k.vrows else None}
        if preview_bar is not None:
            out["preview"] = dict(k.vamd.preview(preview_bar), role="FORMING_PREVIEW – nie jest źródłem filtra")
        return out

    def fractal(self, k: _Key, limit: int = 300) -> dict:
        return {"instrument": k.inst, "tf": k.tf, "profile": FD.PROFILE, "config": k.fd.cfg, "profile_hash": k.profile_hash, "epoch": k.epoch,
                "series": k.frows[-limit:], "current": k.frows[-1] if k.frows else None}

    def smc(self, k: _Key, as_of: float | None = None, limit: int = 300) -> dict:
        sm = k.smc
        evs = [e for e in sm.events if as_of is None or e["available_at"] <= as_of]
        pb = [e for e in sm.pb.ledger if as_of is None or e["available_at"] <= as_of]
        n0 = max(0, len(sm.bars) - limit)
        return {"instrument": k.inst, "tf": k.tf, "profile": sm.profile, "profile_hash": k.profile_hash, "epoch": k.epoch,
                "as_of": as_of, "mode": "AS_OF_KNOWN" if as_of is not None else "CURRENT",
                "bars": [dict(b, i=n0 + j) for j, b in enumerate(sm.bars[n0:])], "first_bar": n0,
                "points": sm.points_asof(as_of), "versions": [v for v in sm.versions if as_of is None or v["available_at"] <= as_of],
                "events": evs[-400:], "pullback": pb[-400:], "trend": sm.trend if as_of is None else None,
                "provisional": sm.pb.provisional() if as_of is None else None, "event_bits": SM.EVENT_BITS, "state_hash": sm.state_hash()}

    def external(self, symbol: str, tf: str) -> dict:
        files = os.environ.get("MQ_MT5_FILES_DIR")
        if self.bridge is None or str(self.bridge.dir) != str(files):
            self.bridge = BF.BridgeImporter(files)
        st = self.bridge.poll(symbol, tf)
        st["mappings"] = [{"mapping_id": m["mapping_id"], "mapper_version": m["mapper_version"], "status": m["validation"]["status"],
                           "indicator_path": m.get("indicator_path"), "buffer": m.get("buffer")} for m in BF.mappings().values()]
        return st
