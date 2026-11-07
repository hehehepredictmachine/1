"""SEQ_LSTM / SEQ_GRU (bar sequences, PyTorch in .venv_deep) and SEQ_GRU_EVENT (adapter of the existing mm/event_engine).

Both bar models use the same dataset (seqdata.build), split (purged by H), scaler (train only) and evaluation, so the LSTM vs GRU
comparison is fair. The event GRU of mm/event_engine.py has DIFFERENT input units (event units, not bars), horizon and schema; its
weights are never loaded into the bar models and vice versa (schema ids EVENT_UNITS_V1 vs BAR_SEQ_V1)."""
from __future__ import annotations

import json

import numpy as np

from . import base as B
from . import deep as D
from . import seqdata as SD


class SeqBase(B.Family):
    ARCH = "LSTM"
    KIND = "TRAINED"
    TASK_TYPE = "CLASS_PROBABILITIES"
    UNIT = "probability"
    TASK = "DIRECTION_H6_AFTER_COST"
    DEPS = ("torch",)
    RUNTIME = "DEEP"
    TF = "M5"
    HORIZONS = (6,)
    RECEIVERS = ("SH_CONTEXT:direction_distribution", "MODELHUB:direction_group M5", "PANEL:model_status")
    DATA = {"kind": "BARS", "tf": "M5", "min_bars": 3000, "schema": "BAR_SEQ_V1"}

    def fit(self, data, cfg, tmp, budget):
        L, H = int(cfg.get("lookback", 64)), self.HORIZONS[0]
        bars = data["bars"][-int(budget.get("max_rows", 20000)):]
        cost_rel = float(np.median([b.get("spread") or 0 for b in bars])) * float(data.get("point") or 0.01) / float(bars[-1]["c"])
        X, y, idx = SD.build(bars, L=L, H=H, cost_rel=cost_rel)
        sp = SD.split(len(y), H)
        (a0, a1), (v0, v1), (h0, h1) = sp["train"], sp["val"], sp["holdout"]
        sc = SD.fit_scaler(X[a0:a1])
        Xs = SD.apply_scaler(X, sc)
        np.savez(tmp / "seq_data.npz", Xtr=Xs[a0:a1], ytr=y[a0:a1], Xva=Xs[v0:v1], yva=y[v0:v1], Xho=Xs[h0:h1], yho=y[h0:h1])
        prof = budget.get("profile") or "research"
        tc = {"epochs": 3 if prof == "smoke" else 25, "hidden": 16 if prof == "smoke" else 32, "patience": 2 if prof == "smoke" else 5, "seed": 7}
        res = D.call("train_seq", {"dir": str(tmp), "arch": self.ARCH, "cfg": tc}, timeout=float(budget.get("timeout_s", 1800)))
        (tmp / "seq_data.npz").unlink(missing_ok=True)               # the dataset is reproducible from the manifest; not shipped twice
        if not res.get("ok"):
            raise B.Unavailable("ERROR", f"trening {self.ARCH}: {res.get('error')}")
        (tmp / "scaler.json").write_text(json.dumps({"scaler": sc, "lookback": L, "horizon": H, "cost_rel": cost_rel, "schema": "BAR_SEQ_V1"}),
                                         encoding="utf-8")
        vm = {"val_skill": 1 - res["val_log_loss"] / res["val_baseline_log_loss"] if res["val_baseline_log_loss"] else None,
              "param_change_l1": res["param_change_l1"]}
        return {"metrics": {k: v for k, v in res.items() if k not in ("sample_p",)}, "validation": self.promotion(vm, {"val_skill": (">", 0.0),
                                                                                                                       "param_change_l1": (">", 0.0)}),
                "sample": {"x_file": "seq_sample_X.npy", "expected": res["sample_p"], "tolerance": 1e-5}, "class_counts": np.bincount(y, minlength=3).tolist()}

    def load(self, d):
        conf = json.loads((d / "scaler.json").read_text(encoding="utf-8"))
        return {"dir": str(d), **conf}

    def predict(self, art, live):
        x = SD.live_window(live["bars"], art["lookback"])
        if x is None:
            raise B.Unavailable("BLOCKED_DATA", f"za mało świec dla okna {art['lookback']}")
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.npy"
            np.save(p, SD.apply_scaler(x, art["scaler"]))
            r = D.call("predict_seq", {"dir": art["dir"], "x_path": str(p)}, timeout=120)
        if not r.get("ok"):
            raise B.Unavailable("ERROR", f"inferencja {self.ARCH}: {r.get('error')}")
        p = r["p"][0]
        return {"DOWN": float(p[0]), "FLAT": float(p[1]), "UP": float(p[2])}


class LSTM(SeqBase):
    ID = "SEQ_LSTM"
    NAME = "LSTM (PyTorch, .venv_deep) – rozkład kierunku po kosztach"
    ARCH = "LSTM"


class GRU(SeqBase):
    ID = "SEQ_GRU"
    NAME = "GRU świecowy (PyTorch, .venv_deep) – rozkład kierunku po kosztach"
    ARCH = "GRU"


class EventGRU(B.Family):
    ID = "SEQ_GRU_EVENT"
    NAME = "Event GRU (istniejący mm/event_engine) – adapter"
    KIND = "PRETRAINED_ADAPTER"
    FIT_LABEL = "trening w Centrum MM (mm/event_engine)"
    TASK_TYPE = "CLASS_PROBABILITIES"
    UNIT = "probability"
    TASK = "EVENT_UNITS_DIR3"
    TF = "EVENT"
    HORIZONS = (1,)
    RECEIVERS = ("PANEL:model_status", "MM_BOARD:evidence")
    DATA = {"kind": "EVENTS", "schema": "EVENT_UNITS_V1", "note": "jednostki zdarzeń (inne niż świece) – wagi niezamienne z SEQ_GRU"}

    def status_from_mm(self, inst: str) -> dict:
        try:
            from ...mm import artifacts
            ptr = artifacts.read_pointer(inst)
            v = (ptr.get("active") or {}).get("event_engine_dir3")
            return {"artifact": "CANDIDATE" if v else "NOT_TRAINED", "version": v, "schema": "EVENT_UNITS_V1"}
        except Exception as exc:  # noqa: BLE001
            return {"artifact": "NOT_TRAINED", "error": str(exc)[:120]}
