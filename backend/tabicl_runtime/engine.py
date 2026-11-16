"""TabICLv2 engine (runs ONLY inside .venv_tabicl): the official tabicl.TabICLClassifier with the pinned local checkpoint.

fit(context_id, X, y) = TabICL's in-context "fit" (stores the reference rows and preprocessing - no gradient step, the pretrained weights
are not changed); predict(context_id, X) = the real predict_proba, positive class located through classes_ (never assumed column 1).
Refused (an error code, never a fake value): fewer than 2 classes in the context, non-finite output, wrong shapes."""
from __future__ import annotations

import math
import os
import time
from pathlib import Path

from . import lock


class EngineError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def rss_mb() -> float | None:
    try:
        import resource
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    except Exception:  # noqa: BLE001
        return None


class Engine:
    def __init__(self):
        self.ckpt: Path | None = None
        self.loaded = False
        self.contexts: dict[str, dict] = {}
        self.info: dict = {}
        self.threads = 2

    def load(self, weights_root: str, threads: int | None = 2, verify_files: bool = True) -> dict:
        if self.loaded:
            return self.info
        from .install import model_dir, verify
        t0 = time.perf_counter()
        if verify_files:
            v = verify(weights_root)
            if not v["ok"]:
                raise EngineError("NO_WEIGHTS", "; ".join(v["problems"])[:300])
        self.ckpt = model_dir(weights_root) / lock.PIN["checkpoint"]
        os.environ["HF_HUB_OFFLINE"] = "1"
        try:
            import torch
            import tabicl  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            raise EngineError("MISSING_DEPENDENCY", f"{type(exc).__name__}: {exc}"[:300]) from None
        self.threads = int(threads or 2)
        torch.set_num_threads(self.threads)
        self.loaded = True
        self.info = {"model_id": "tabicl_v2", "checkpoint": lock.PIN["checkpoint"], "revision": lock.PIN["revision"], "fingerprint": lock.fingerprint(),
                     "device": "cpu", "threads": self.threads, "inference": lock.PIN["inference"], "load_ms": round((time.perf_counter() - t0) * 1000, 1),
                     "rss_mb": rss_mb()}
        return self.info

    def _clf(self):
        from tabicl import TabICLClassifier
        inf = lock.PIN["inference"]
        return TabICLClassifier(n_estimators=inf["n_estimators"], batch_size=inf["batch_size"], kv_cache=inf["kv_cache"], model_path=str(self.ckpt),
                                allow_auto_download=False, checkpoint_version=lock.PIN["checkpoint"], device="cpu", random_state=inf["random_state"],
                                n_jobs=1, verbose=False)

    def fit(self, context_id: str, X, y, names: list[str] | None = None) -> dict:
        if not self.loaded:
            raise EngineError("NOT_LOADED", "model nie jest załadowany")
        import numpy as np
        X = np.asarray(X, dtype=np.float64)
        y = np.asarray(y, dtype=np.int64)
        if X.ndim != 2 or len(X) != len(y) or len(y) == 0:
            raise EngineError("SHAPE", f"kontekst {X.shape} / etykiety {y.shape}")
        if np.isinf(X).any():
            raise EngineError("NON_FINITE_INPUT", "kontekst zawiera Inf")
        classes = sorted(set(int(v) for v in y))
        if len(classes) < 2:
            raise EngineError("SINGLE_CLASS", f"kontekst ma tylko klasę {classes} – TabICL nie da uczciwej oceny (bez 0 % / 100 %)")
        t0 = time.perf_counter()
        clf = self._clf()
        clf.fit(X, y)
        self.contexts = {context_id: {"clf": clf, "n": len(y), "names": names, "dim": X.shape[1], "pos_rate": float(y.mean())}}   # one context in RAM
        return {"context_id": context_id, "n": len(y), "dim": X.shape[1], "classes": [int(c) for c in clf.classes_], "fit_ms": round((time.perf_counter() - t0) * 1000, 1),
                "rss_mb": rss_mb()}

    def predict(self, context_id: str, X) -> dict:
        import numpy as np
        ctx = self.contexts.get(context_id)
        if ctx is None:
            raise EngineError("NO_CONTEXT", f"kontekst {context_id} nie jest przygotowany w procesie")
        X = np.asarray(X, dtype=np.float64)
        if X.ndim != 2 or X.shape[1] != ctx["dim"]:
            raise EngineError("SHAPE", f"wiersz {X.shape} ≠ kontekst {ctx['dim']} kolumn")
        t0 = time.perf_counter()
        p = ctx["clf"].predict_proba(X)
        cls = [int(c) for c in ctx["clf"].classes_]
        if 1 not in cls:
            raise EngineError("NO_POSITIVE_CLASS", f"klasy {cls}")
        col = p[:, cls.index(1)]
        if not all(math.isfinite(float(v)) and 0.0 <= float(v) <= 1.0 for v in col):
            raise EngineError("NON_FINITE", "predict_proba poza [0, 1] / NaN")
        return {"p_event_raw": [float(v) for v in col], "classes": cls, "ms": round((time.perf_counter() - t0) * 1000, 1), "rss_mb": rss_mb()}

    def selftest(self) -> dict:
        """Smoke + parity: this wrapper vs a direct TabICLClassifier call on the same deterministic data; single-class refusal."""
        import numpy as np
        rng = np.random.default_rng(20261116)
        X = rng.normal(size=(256, 8))
        y = (X[:, 0] + 0.5 * X[:, 1] + rng.normal(0, 1, 256) > 0).astype(int)
        r = self.fit("_selftest", X[:200], y[:200])
        got = np.asarray(self.predict("_selftest", X[200:])["p_event_raw"])
        direct = self._clf().fit(X[:200], y[:200]).predict_proba(X[200:])[:, 1]
        d = float(np.abs(got - direct).max())
        single = None
        try:
            self.fit("_single", X[:50], np.zeros(50, int))
        except EngineError as exc:
            single = exc.code
        self.contexts.pop("_selftest", None)
        return {"ok": d <= 1e-6 and single == "SINGLE_CLASS", "fit_ms": r["fit_ms"], "parity": {"max_abs_diff": d, "status": "PASS" if d <= 1e-6 else "DIFF"},
                "single_class_refused": single == "SINGLE_CLASS", "rss_mb": rss_mb()}
