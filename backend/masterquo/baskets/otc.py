"""Gold OTC (Pocket Option) feed: ONLY the product's own quotes. No MT5 XAUUSD, GC, PAXG or a Hyperliquid gold perp is ever used
as the OTC price. Without a connected / imported feed the profile reports WAITING_FOR_OTC_FEED (everything else keeps working).

Sources (in this order):
  1. live push from a user-run, permitted connector: POST /api/v1/baskets/otc/ticks [{t, price}] (kept in memory + appended to disk)
  2. import of the user's own exported quotes / candles: data/otc/import/*.csv|*.jsonl  (t / time, price | o,h,l,c) - idempotent
Short candles are aggregated ONLY from sufficiently fine data: ticks -> S5/S15/S30/M1/M5; imported S15 candles -> S15/S30/M1/M5 ...
never M1 cut into fake S5. Payout / allowed expiries / stake rules are user-entered metadata (from the platform screen at that moment),
stored with a timestamp; a stale payout is refused by the payoff gate.
"""
from __future__ import annotations

import csv
import json
import threading
import time
from pathlib import Path

from .. import paths

TF_S = {"S5": 5, "S15": 15, "S30": 30, "M1": 60, "M3": 180, "M5": 300}
INSTRUMENT = "GOLD_OTC"
DEFAULT_META = {"instrument_id": None, "payout": {"CALL": None, "PUT": None}, "payout_at": None, "expiries_s": [], "stake_min": 1.0, "stake_step": 1.0,
                "stake_max_hedge": 0.0, "currency": None, "tie_rule": "REFUND", "source": None, "min_improvement_money": 1.0, "allow_negative_lock": True,
                "min_accept_s": 5}


def odir() -> Path:
    p = paths.data_dir() / "otc"
    (p / "import").mkdir(parents=True, exist_ok=True)
    return p


class OTCFeed:
    def __init__(self, base: Path | None = None):
        self.base = Path(base) if base else odir()
        (self.base / "import").mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.ticks: list[tuple[float, float]] = []
        self.candles: dict[int, dict[float, dict]] = {}                     # native resolution (s) -> {t: bar}
        self.imported: set[str] = set()
        self.last_tick_at: float | None = None
        self.source: str | None = None
        self.payout_history: list[dict] = []
        self._load_ticks()

    # ------------------------------------------------------------------ metadata
    def meta(self) -> dict:
        try:
            return {**DEFAULT_META, **json.loads((self.base / "meta.json").read_text(encoding="utf-8"))}
        except (OSError, ValueError):
            return dict(DEFAULT_META)

    def set_meta(self, patch: dict) -> dict:
        m = self.meta()
        allowed = set(DEFAULT_META)
        bad = [k for k in patch if k not in allowed]
        if bad:
            raise ValueError(f"OTC_META_KEYS:{bad}")
        if "payout" in patch:
            for d, v in (patch["payout"] or {}).items():
                if d not in ("CALL", "PUT") or (v is not None and not 0 < float(v) < 5):
                    raise ValueError("payout = zysk ponad stawkę jako ułamek, np. 0.8 dla 80%")
            patch = {**patch, "payout_at": time.time()}
            self.payout_history.append({"at": time.time(), **(patch["payout"] or {})})
            self.payout_history = self.payout_history[-50:]
        m.update(patch)
        (self.base / "meta.json").write_text(json.dumps(m, indent=1), encoding="utf-8")
        return m

    # ------------------------------------------------------------------ data in
    def _load_ticks(self) -> None:
        f = self.base / "ticks.jsonl"
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines()[-200000:]:
                try:
                    t, p = json.loads(line)
                    self.ticks.append((float(t), float(p)))
                except (ValueError, TypeError):
                    continue
            if self.ticks:
                self.source = "TICKS_FILE"

    def push_ticks(self, rows: list[dict], source: str) -> int:
        new = []
        with self._lock:
            last = self.ticks[-1][0] if self.ticks else 0.0
            for r in rows:
                t, p = float(r["t"]), float(r["price"])
                if p <= 0 or t <= last:
                    continue
                new.append((t, p))
                last = t
            self.ticks += new
            self.ticks = self.ticks[-200000:]
            if new:
                self.last_tick_at, self.source = time.time(), source
        if new:
            with open(self.base / "ticks.jsonl", "a", encoding="utf-8") as fh:
                for t, p in new:
                    fh.write(json.dumps([t, p]) + "\n")
        return len(new)

    def import_dir(self) -> dict:
        """Idempotent import of data/otc/import/*: rows {t|time, price} (ticks) or {t|time, o, h, l, c} with an explicit tf column / file
        suffix _S15 / _M1 ... (candles of that native resolution)."""
        done = {"files": 0, "ticks": 0, "candles": 0, "skipped": []}
        for f in sorted((self.base / "import").glob("*")):
            key = f"{f.name}:{f.stat().st_size}:{int(f.stat().st_mtime)}"
            if key in self.imported or f.suffix.lower() not in (".csv", ".jsonl"):
                continue
            rows = []
            if f.suffix.lower() == ".csv":
                with open(f, encoding="utf-8") as fh:
                    rows = list(csv.DictReader(fh))
            else:
                rows = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
            tf = next((k for k in TF_S if f.stem.upper().endswith("_" + k)), None)
            ticks, cnd = [], {}
            for r in rows:
                t = r.get("t") or r.get("time")
                try:
                    t = float(t)
                except (TypeError, ValueError):
                    from datetime import datetime
                    t = datetime.fromisoformat(str(t).replace("Z", "+00:00")).timestamp()
                if "price" in r:
                    ticks.append({"t": t, "price": float(r["price"])})
                elif tf and all(k in r for k in "ohlc"):
                    cnd[t] = {"t": t, **{k: float(r[k]) for k in "ohlc"}}
            if ticks:
                done["ticks"] += self.push_ticks(sorted(ticks, key=lambda x: x["t"]), f"IMPORT:{f.name}")
            elif cnd:
                with self._lock:
                    self.candles.setdefault(TF_S[tf], {}).update(cnd)
                    self.source = f"IMPORT:{f.name}"
                done["candles"] += len(cnd)
            else:
                done["skipped"].append(f.name)
                continue
            self.imported.add(key)
            done["files"] += 1
        return done

    # ------------------------------------------------------------------ data out
    def bars(self, tf: str, n: int = 500, now: float | None = None) -> list[dict]:
        """CLOSED candles of tf built from data at least as fine as tf; [] when no such data (WAITING_FOR_OTC_FEED / UNSUPPORTED_TF)."""
        sec = TF_S[tf]
        now = time.time() if now is None else now
        with self._lock:
            if self.ticks:
                out: dict[float, dict] = {}
                for t, p in self.ticks:
                    k = t // sec * sec
                    b = out.get(k)
                    if b is None:
                        out[k] = {"t": k, "o": p, "h": p, "l": p, "c": p, "ticks": 1}
                    else:
                        b["h"], b["l"], b["c"], b["ticks"] = max(b["h"], p), min(b["l"], p), p, b["ticks"] + 1
                bars = [b for k, b in sorted(out.items()) if k + sec <= now]
                return bars[-n:]
            src = max((r for r in self.candles if r <= sec and sec % r == 0), default=None)
            if src is None:
                return []
            out = {}
            for t, b in sorted(self.candles[src].items()):
                k = t // sec * sec
                o = out.get(k)
                if o is None:
                    out[k] = dict(b, t=k)
                else:
                    o["h"], o["l"], o["c"] = max(o["h"], b["h"]), min(o["l"], b["l"]), b["c"]
            return [b for k, b in sorted(out.items()) if k + sec <= now][-n:]

    def price_at(self, t: float) -> float | None:
        """The feed's last price at or before t (for SIGNAL_SIMULATION outcome only; the platform's own settlement wins)."""
        with self._lock:
            ps = [p for tt, p in self.ticks if tt <= t]
            return ps[-1] if ps else None

    def state(self) -> dict:
        has = bool(self.ticks) or bool(self.candles)
        live = self.last_tick_at is not None and time.time() - self.last_tick_at < 30
        m = self.meta()
        return {"instrument": INSTRUMENT, "state": "LIVE" if live else ("HISTORY_ONLY" if has else "WAITING_FOR_OTC_FEED"),
                "reason": None if has else "brak źródła kwotowań Gold OTC – podłącz dopuszczony konektor (POST /api/v1/baskets/otc/ticks) lub "
                                           "umieść własny eksport w data/otc/import (CSV/JSONL)",
                "source": self.source, "ticks": len(self.ticks), "candle_sets": {f"{k}s": len(v) for k, v in self.candles.items()},
                "payout": m["payout"], "payout_at": m["payout_at"], "expiries_s": m["expiries_s"], "execution_capability": "MANUAL_ONLY",
                "note": "żadna inna cena złota (MT5 XAUUSD, GC, PAXG, perp GOLD) nie zastępuje feedu OTC"}


def choose_expiry(D: float, supported: list[float]) -> float | None:
    """The supported duration nearest to D inside [0.8 D, 1.2 D]; None when no compatible contract exists."""
    c = [e for e in supported if 0.8 * D <= float(e) <= 1.2 * D]
    return min(c, key=lambda e: abs(float(e) - D)) if c else None
