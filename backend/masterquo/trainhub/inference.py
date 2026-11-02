"""Live inference of ACTIVE Training Center packages (PMW-TH-INF-1), in the bot process, on closed candles only.

* For every instrument and every ACTIVE package: after a new CLOSED base-TF candle, the bars are read through the bridge, the features
  are built by the SAME code as in training (features.last_row), the package is loaded only after its compatibility check and the
  output is published in the unified prediction contract (modelhub.contract).
* Any problem gives a non-READY state with the reason and NO value: INCOMPATIBLE (schema / library / checksum), ERROR (data missing,
  stale, warm-up incomplete, exception), DISABLED (no active version). The fallback is "no vote" - never a default probability.
* Predictions are information for the panel and the evidence board; they do not open positions and do not change any setting.
"""
from __future__ import annotations

import threading
import time

import numpy as np

from ..modelhub import contract as C
from . import features as F
from . import registry as R

INSTRUMENTS = ("XAUUSD", "BTC")
BARS = {"base": 600, "htf": 300}


def cols_from_bars(rows: list[dict]) -> dict:
    from ..zones.series import ts
    rows = [b for b in rows if b.get("closed") is not False and b.get("open_utc")]
    return {"time": [int(ts(b["open_utc"])) for b in rows], "open": [float(b["o"]) for b in rows], "high": [float(b["h"]) for b in rows],
            "low": [float(b["l"]) for b in rows], "close": [float(b["c"]) for b in rows], "tick_volume": [float(b.get("tv") or 0) for b in rows],
            "spread": [float(b.get("spread") or 0) for b in rows]}


class TrainhubInference:
    def __init__(self, cfg_store, bridge, *, bus=None, log=None, poll_s: float = 5.0, clock=time.time):
        self.cfg_store, self.bridge, self.bus, self.log, self.poll_s, self.clock = cfg_store, bridge, bus, log, poll_s, clock
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.cache: dict[tuple, tuple] = {}            # (inst, key, version) -> (obj, conf) | Exception
        self.latest: dict[tuple, dict] = {}            # (inst, key) -> prediction
        self.last_bar: dict[tuple, int] = {}

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="trainhub-infer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.poll_s):
            for inst in INSTRUMENTS:
                try:
                    self.run_instrument(inst)
                except Exception as exc:  # noqa: BLE001 - inference never stops the bot
                    if self.log:
                        self.log.warning("trainhub", f"inferencja {inst}: {type(exc).__name__}: {exc}"[:200])

    def symbol(self, inst: str) -> str | None:
        m = self.cfg_store.get().assets.mappings.get(inst)
        return m.broker_symbol if m and m.broker_symbol else None

    def run_instrument(self, inst: str, force: bool = False) -> list[dict]:
        reg = R.registry(inst)
        out = []
        for key, version in (reg.get("active") or {}).items():
            out.append(self.predict(inst, key, version, force=force))
        with self._lock:
            for (i, k) in list(self.latest):
                if i == inst and k not in (reg.get("active") or {}):
                    self.latest.pop((i, k), None)                      # deactivated / rolled back to nothing
        return out

    def _load(self, inst: str, key: str, version: str):
        ck = (inst, key, version)
        if ck not in self.cache:
            try:
                obj, conf, sch = R.load(inst, key, version)
                self.cache[ck] = (obj, conf, sch)
            except Exception as exc:  # noqa: BLE001 - cached: a broken package is not re-read every 5 s
                self.cache[ck] = exc
        return self.cache[ck]

    def _pred(self, inst, key, version, conf, state, reason=None, **kw) -> dict:
        p = C.make(instrument=inst, symbol=self.symbol(inst), timeframe=(conf or {}).get("base_tf") or key.split("_")[-2],
                   model_name=(conf or {}).get("model_id") or key, model_version=version, task_type="CLASS_PROBABILITIES",
                   task=f"DIRECTION_H{(conf or {}).get('horizon', '?')}_{(conf or {}).get('base_tf', '?')}",
                   horizon_bars=int((conf or {}).get("horizon") or 1), unit="probability", state=state, unavailable_reason=reason,
                   feature_schema=F.FEATURE_SCHEMA,
                   calibration={"method": "temperature (dev OOF)", "status": "CALIBRATED_DEV"} if conf else {"method": None, "status": "NOT_APPLICABLE"},
                   extra={"model_key": key}, **kw)
        with self._lock:
            self.latest[(inst, key)] = p
        return p

    def predict(self, inst: str, key: str, version: str, force: bool = False) -> dict:
        t0 = time.perf_counter()
        loaded = self._load(inst, key, version)
        if isinstance(loaded, Exception):
            st = "INCOMPATIBLE" if isinstance(loaded, R.IncompatiblePackage) else "ERROR"
            return self._pred(inst, key, version, None, st, f"{type(loaded).__name__}: {loaded}"[:300])
        obj, conf, sch = loaded
        sym = self.symbol(inst)
        if not sym:
            return self._pred(inst, key, version, conf, "DISABLED", f"brak symbolu brokera dla {inst}")
        tf = conf["base_tf"]
        try:
            cols = {tf: cols_from_bars(self.bridge.symbol_bars(sym, tf, BARS["base"]))}
            for h in F.HTF_OF[tf]:
                cols[h] = cols_from_bars(self.bridge.symbol_bars(sym, h, BARS["htf"]))
        except Exception as exc:  # noqa: BLE001
            return self._pred(inst, key, version, conf, "ERROR", f"dane z MT5 niedostępne: {type(exc).__name__}: {exc}"[:240],
                              data_quality="MISSING")
        if not cols[tf]["time"]:
            return self._pred(inst, key, version, conf, "ERROR", "brak zamkniętych świec (offset czasu serwera nieznany?)", data_quality="MISSING")
        last_t = cols[tf]["time"][-1]
        if not force and self.last_bar.get((inst, key)) == last_t and (inst, key) in self.latest:
            return self.latest[(inst, key)]
        self.last_bar[(inst, key)] = last_t
        point = float((self.bridge.symbol_meta(sym) or {}).get("point") or conf.get("point") or 0.01)
        t, x, names = F.last_row(cols, tf, point)
        if names != (sch or {}).get("names"):
            return self._pred(inst, key, version, conf, "INCOMPATIBLE", "kolejność / nazwy cech inne niż w paczce – inferencja zablokowana")
        close_t = last_t + F.TF_S[tf]
        age = self.clock() - close_t
        dq = "OK" if age <= 3 * F.TF_S[tf] + 30 else "STALE"
        if x is None or not np.all(np.isfinite(x)):
            return self._pred(inst, key, version, conf, "ERROR", "niepełne cechy (za krótka historia / brak świec wyższego interwału)",
                              data_quality="DEGRADED", data_time=_iso(close_t))
        if dq != "OK":
            return self._pred(inst, key, version, conf, "ERROR", f"dane nieaktualne: ostatnia zamknięta świeca {_iso(close_t)} "
                              f"({int(age // 60)} min) – rynek zamknięty albo brak notowań", data_quality="STALE", data_time=_iso(close_t),
                              freshness_s=round(age, 1))
        p = R.predict_loaded(obj, x.reshape(1, -1))[0]
        res = {"DOWN": round(float(p[0]), 6), "FLAT": round(float(p[1]), 6), "UP": round(1.0 - round(float(p[0]), 6) - round(float(p[1]), 6), 6)}
        return self._pred(inst, key, version, conf, "READY", result=res, data_time=_iso(close_t), freshness_s=round(age, 1),
                          compute_ms=round((time.perf_counter() - t0) * 1000, 1), data_quality=dq)

    def predictions(self, inst: str) -> list[dict]:
        with self._lock:
            return [v for (i, _), v in self.latest.items() if i == inst]

    def invalidate(self, inst: str) -> None:
        """After activation / rollback: drop cached packages and predictions of the instrument (recomputed at the next poll)."""
        with self._lock:
            for k in [k for k in self.cache if k[0] == inst]:
                self.cache.pop(k, None)
            for k in [k for k in self.latest if k[0] == inst]:
                self.latest.pop(k, None)
            for k in [k for k in self.last_bar if k[0] == inst]:
                self.last_bar.pop(k, None)


def _iso(t):
    from ..marketdata.store import iso
    return iso(t)
