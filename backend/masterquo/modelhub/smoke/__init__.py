"""Smoke checks of the model producers (`python -m masterquo models check --smoke`).

Every area module (``modelhub/smoke/<area>.py``) exposes:

* ``SMOKES: dict[str, Callable[[Ctx], dict]]`` - canonical id (quant/ids.py, docs/quant/INVENTORY.json) -> smoke function;
* ``NOT_CHECKABLE: dict[str, str]`` (optional) - canonical id -> why it cannot be exercised in this environment (native MQL5 without a
  terminal, weights that cannot be downloaded) - reported as NIEZWERYFIKOWANY, never as a pass. NO_SPEC / NOT_IMPLEMENTED rows of the
  registry need no entry (models check reports them from the registry).

A smoke function goes through the REAL project path (the same functions the bot and the trainers call), on SYNTHETIC_TEST data
(FakeMT5 / generated bars) in an isolated data folder, and returns the steps it exercised::

    {"train": ok("..."), "artifact": ok("roundtrip diff 0.0"), "predict": ok("READY ..."), "contract": ok()}

Allowed steps: ``env``, ``import``, ``train``, ``artifact``, ``predict``, ``contract``, ``live``. A step that does not apply is left out
(a rule has no ``train``). Statuses: OK / FAIL / SKIP / NIEZWERYFIKOWANY. An exception inside the function is a FAIL of the step named
in ``ctx.step`` at that moment. A smoke result is a TECHNICAL check of the path - never a quality result and never shown as a result
on real data (rule 6 of the 1.46 architecture task).
"""
from __future__ import annotations

import importlib
import os
from collections.abc import Callable
from pathlib import Path

AREAS = ("rules", "families", "trainhub", "mm", "lab", "quant", "ml", "extind", "scalp_gold", "kronos_tsfm")
STEPS = ("env", "import", "train", "artifact", "predict", "contract", "live")
OK, FAIL, SKIP, UNVERIFIED = "OK", "FAIL", "SKIP", "NIEZWERYFIKOWANY"


def ok(detail: str = "") -> dict:
    return {"status": OK, "detail": str(detail)[:400]}


def fail(detail: str) -> dict:
    return {"status": FAIL, "detail": str(detail)[:400]}


def skip(reason: str) -> dict:
    return {"status": SKIP, "detail": str(reason)[:400]}


def unverified(reason: str) -> dict:
    return {"status": UNVERIFIED, "detail": str(reason)[:400]}


def check(cond: bool, detail_ok: str, detail_fail: str) -> dict:
    return ok(detail_ok) if cond else fail(detail_fail)


class Ctx:
    """Shared helpers for smoke functions. One instance per area worker process (MASTERQUO_DATA_DIR is already a temporary folder)."""

    def __init__(self, inst: str = "XAUUSD"):
        from ... import paths
        self.inst = inst
        self.data_dir: Path = paths.data_dir()
        self.root: Path = paths.ROOT_DIR
        self.step = "import"
        self._fakes: dict = {}
        self._stores: dict = {}

    # ------------------------------------------------------------------ synthetic market (FakeMT5 = the DEMO terminal of the bot)
    def fake(self, history_days: int = 40, seed: int = 3, symbol: str = "XAUUSD-"):
        key = (history_days, seed, symbol)
        if key not in self._fakes:
            os.environ.setdefault("MQ_FAKE_MARKET_ALWAYS_OPEN", "1")
            from ...mt5.fake import FakeMT5
            f = FakeMT5(symbol=symbol, seed=seed, history_days=history_days)
            f.initialize()
            self._fakes[key] = f
        return self._fakes[key]

    def rates(self, tf: str, n: int, *, history_days: int = 40, seed: int = 3):
        """Closed bars (numpy structured array, broker-server epochs) exactly as MetaTrader5.copy_rates_from_pos returns them."""
        f = self.fake(history_days, seed)
        return f.copy_rates_from_pos(f.symbol, getattr(f, "TIMEFRAME_" + tf), 1, n)

    def bars(self, tf: str, n: int, *, history_days: int = 40, seed: int = 3) -> list[dict]:
        """Closed bars in the bridge row format (open_utc / t / o / h / l / c / tv / spread / closed), UTC from the FakeMT5 offset."""
        from datetime import UTC, datetime
        f = self.fake(history_days, seed)
        out = []
        for x in self.rates(tf, n, history_days=history_days, seed=seed):
            t = int(x["time"]) - f.offset
            out.append({"open_utc": datetime.fromtimestamp(t, UTC).isoformat().replace("+00:00", "Z"), "t": t, "o": float(x["open"]),
                        "h": float(x["high"]), "l": float(x["low"]), "c": float(x["close"]), "tv": int(x["tick_volume"]),
                        "spread": int(x["spread"]), "closed": True})
        return out

    def store(self, timeframes=("M1", "M5", "M15", "M30", "H1"), lookback_days: int = 30, history_days: int = 40):
        """marketdata Store with a synthetic export of the instrument (the same exporter the Training Center uses)."""
        key = (tuple(timeframes), lookback_days, history_days)
        if key not in self._stores:
            from ...marketdata import export as EX
            from ...marketdata.sources import DirectSource
            from ...marketdata.store import Store
            f = self.fake(history_days)
            st = Store()
            EX.run(DirectSource(f, offset=f.offset, offset_basis="TEST"), st, self.inst, f.symbol, timeframes=tuple(timeframes),
                   lookback_days=lookback_days, sleep=lambda s: None)
            self._stores[key] = st
        return self._stores[key]

    # ------------------------------------------------------------------ environments and contract
    def env_python(self, venv: str) -> str | None:
        """Python of a separate model environment (.venv_deep, .venv_kronos, .venv_candles, ...) - the env variable the bot reads first
        (MQ_DEEP_PYTHON, MQ_KRONOS_PYTHON, MQ_CANDLES_PYTHON, MQ_TABICL_PYTHON ...), then <program>/<venv>. None = not installed."""
        # the same variables the bot reads first (tsfm/settings.python_candidates: MQ_<MODEL ID>_PYTHON; kronos/settings; quant/tabicl ...)
        var = {".venv_deep": "MQ_DEEP_PYTHON", ".venv_kronos": "MQ_KRONOS_PYTHON", ".venv_candles": "MQ_CANDLES_PYTHON",
               ".venv_tabicl": "MQ_TABICL_PYTHON", ".venv_chronos2": "MQ_CHRONOS2_PYTHON", ".venv_granite": "MQ_GRANITE_TTM_PYTHON",
               ".venv_tirex2": "MQ_TIREX2_PYTHON"}.get(venv)
        cands = [os.environ.get(var)] if var else []
        cands += [str(self.root / venv / "Scripts" / "python.exe"), str(self.root / venv / "bin" / "python")]
        for c in cands:
            if c and Path(c).is_file():
                return c
        return None

    def contract_errors(self, rec: dict) -> list[str]:
        """PMW-PRED-2 validation of one prediction record (modelhub/contract.py) -> list of errors (empty = valid)."""
        from .. import contract as C
        try:
            C.validate(rec)
            return []
        except Exception as exc:  # noqa: BLE001 - ContractError / ValueError / TypeError are all contract violations
            return [f"{type(exc).__name__}: {exc}"[:300]]

    def contract_step(self, recs: list[dict]) -> dict:
        errs = [e for r in recs for e in self.contract_errors(r)]
        if not recs:
            return fail("brak rekordu predykcji")
        return check(not errs, f"PMW-PRED-2: {len(recs)} rekord(y) poprawne", "; ".join(errs)[:400])


def load_area(area: str) -> tuple[dict[str, Callable], dict[str, str]]:
    mod = importlib.import_module(f"{__name__}.{area}")
    return dict(getattr(mod, "SMOKES", {}) or {}), dict(getattr(mod, "NOT_CHECKABLE", {}) or {})


def run_area(area: str, inst: str = "XAUUSD", only: Callable[[str], bool] | None = None) -> list[dict]:
    """Run every smoke function of one area in THIS process (the caller isolates the data folder). Never raises."""
    import time
    import traceback
    out = []
    try:
        smokes, nc = load_area(area)
    except Exception as exc:  # noqa: BLE001
        return [{"id": f"area:{area}", "area": area, "steps": {"import": fail(f"{type(exc).__name__}: {exc}")}, "ms": 0}]
    ctx = Ctx(inst)
    for cid, reason in nc.items():
        if only is None or only(cid):
            out.append({"id": cid, "area": area, "steps": {}, "not_checkable": reason, "ms": 0})
    for cid, fn in smokes.items():
        if only is not None and not only(cid):
            continue
        t0 = time.monotonic()
        ctx.step = "import"
        try:
            steps = dict(fn(ctx) or {})
        except Exception as exc:  # noqa: BLE001 - a crash is a FAIL of the step being executed
            tb = traceback.format_exc(limit=3).strip().splitlines()[-1]
            steps = {ctx.step: fail(f"{type(exc).__name__}: {exc} | {tb}")}
        bad = [k for k in steps if k not in STEPS]
        for k in bad:
            steps.setdefault("contract", fail(f"nieznany krok smoke: {k}"))
            steps.pop(k)
        out.append({"id": cid, "area": area, "steps": steps, "ms": int((time.monotonic() - t0) * 1000)})
    return out
