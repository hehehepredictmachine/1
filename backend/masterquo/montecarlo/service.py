"""Runtime Monte Carlo (PMW-MC-1): computed on request / per closed M1 bar in ONE background thread of its own - never in the API
event loop, never in the MT5 worker (it reads the bridge's closed-bar buffer, no terminal request). Results are cached per last
closed bar and plan. The variant is the one chosen by the user's validation when an ACTIVE calibrator exists; otherwise BLOCK, and the
result says that the variant was NOT chosen by validation and that the probability is a model probability only."""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout

from . import engine as E
from . import validate as V


class MonteCarloService:
    def __init__(self, cfg_store, bridge, *, synthetic: bool = False, n_paths: int = 2000):
        self.cfg_store, self.bridge, self.synthetic, self.n_paths = cfg_store, bridge, synthetic, n_paths
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="montecarlo")
        self._lock = threading.Lock()
        self._cache: dict = {}
        self.state = {"runs": 0, "last_ms": None, "last_error": None}

    def stop(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _ctx(self):
        cfg = self.cfg_store.get()
        info = getattr(self.bridge, "symbol_info", None) or {}
        point = float(info.get("point") or info.get("trade_tick_size") or 0.01)
        return cfg.assets.active, point

    def _variant(self, inst: str) -> tuple[str, dict | None]:
        cal = None if self.synthetic else V.active_calibrator(inst)
        return (cal["variant"], cal) if cal else ("BLOCK", None)

    def compute(self, plans: list[E.Plan] | None = None, *, horizon: int = 60, variant: str | None = None, n_paths: int | None = None,
                timeout: float = 20.0, levels: tuple | None = None) -> dict:
        inst, point = self._ctx()
        bars = [b for b in self.bridge.bars("M1", include_forming=False) if b.get("open_utc")]   # UTC time verified (clock) only
        if not bars:
            return {"status": "NO_DATA", "reason": "brak zamkniętych świec M1 z potwierdzonym czasem UTC (MT5 rozłączony albo zegar serwera "
                                                   "jeszcze nie zmierzony)", "instrument": inst}
        last = bars[-1].get("open_utc")
        chosen, cal = self._variant(inst)
        v = variant or chosen
        levels = tuple(float(x) for x in levels) if levels else (2.5, 3.0, 5.0, 7.5, 10.0)
        key = (inst, last, v, horizon, n_paths or self.n_paths, levels, tuple((p.side, round(p.entry, 5), round(p.sl, 5), tuple(round(x, 5) for x in p.tps), p.horizon)
                                                                   for p in plans or []))
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        as_of = E._ts(last) + 60
        fut = self._pool.submit(E.run, bars, as_of, plans, tf="M1", point=point, variant=v, n_paths=n_paths or self.n_paths, horizon=horizon,
                                synthetic=self.synthetic, calibrator=cal, levels=levels)
        try:
            res = fut.result(timeout=timeout)
        except FutTimeout:
            return {"status": "TIMEOUT", "reason": f"obliczenia > {timeout:.0f} s – zmniejsz liczbę ścieżek", "instrument": inst}
        except Exception as exc:  # noqa: BLE001
            self.state["last_error"] = f"{type(exc).__name__}: {exc}"[:300]
            return {"status": "ERROR", "reason": self.state["last_error"], "instrument": inst}
        res["instrument"] = inst
        res["variant_basis"] = ("wybrany walidacją na Twoich danych (" + cal["run_id"] + ")") if cal else \
            "domyślny BLOCK – wariant NIE był wybrany walidacją (brak aktywnej kalibracji); to prawdopodobieństwo w modelu, nie skalibrowane"
        self.state.update(runs=self.state["runs"] + 1, last_ms=res.get("compute_ms"), last_error=None)
        with self._lock:
            if len(self._cache) > 64:
                self._cache.clear()
            self._cache[key] = res
        return res

    def plan_for(self, side: str, sl_distance: float, tp_distances: list[float], *, entry: float | None = None, horizon: int = 60) -> E.Plan | None:
        """Plan from distances (price units) and the current quote: BUY at Ask, SELL at Bid."""
        q = self.bridge.quote_status() if hasattr(self.bridge, "quote_status") else None
        if entry is None:
            if not q or q.get("bid") is None:
                return None
            entry = float(q["ask"]) if side == "BUY" else float(q["bid"])
        sgn = 1 if side == "BUY" else -1
        return E.Plan(side, entry, entry - sgn * sl_distance, [entry + sgn * d for d in tp_distances], horizon)

    def status(self) -> dict:
        inst, _ = self._ctx()
        chosen, cal = self._variant(inst)
        reg = {}
        try:
            import json
            reg = json.loads((V.root(inst) / "registry.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        runs = sorted((reg.get("runs") or {}).items(), key=lambda kv: kv[1].get("created_at") or "", reverse=True)
        return {"version": E.VERSION, "instrument": inst, "variant": chosen, "calibrated": bool(cal), "active_calibration": cal and cal.get("run_id"),
                "validations": [dict(v, run_id=k) for k, v in runs[:10]], "synthetic": self.synthetic, **self.state,
                "note": "prawdopodobieństwo w modelu ≠ prawdopodobieństwo skalibrowane; błąd z liczby ścieżek to nie niepewność rynku"}
