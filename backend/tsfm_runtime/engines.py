"""Inference engines of Chronos-2 and Granite TTM (run ONLY inside the model's own environment / process: .venv_chronos2, .venv_granite).
1.40: FinCast is retired (replaced by Granite TTM) - its engine and vendored code were removed; old FinCast forecasts stay in the history.

Both call the ORIGINAL upstream API and nothing else:
  Chronos-2    chronos.Chronos2Pipeline.from_pretrained(<local dir>) + predict_quantiles(inputs, prediction_length, quantile_levels)
  Granite TTM  tsfm_public.models.tinytimemixer.TinyTimeMixerForPrediction.from_pretrained(<local dir>) + forward(past_values)
What this file adds: loading from local, checksum-verified files (offline), the identity check of the loaded checkpoint (parameter
count == the pinned measurement), input validation (finite, length, horizon), the explicit target / input profile, the device choice
(CUDA only when available AND working, else CPU, the reason reported) and a self test with a PARITY check against a direct call of the
official API on the same data (independent code path - the expected values are never produced by this wrapper).

Output semantics (never re-labelled):
  quantiles    Chronos-2: the model's own quantile forecasts of the close at every step (21 trained levels); Granite TTM: none
  point        Chronos-2: the 0.5 quantile (the pipeline's "mean" output IS the median) -> point_kind "median";
               Granite TTM: the MSE head -> point_kind "point" (no median, no quantiles).
Close only: neither model produces OHLC candles here - no high / low is ever derived from the close forecast.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path

from . import lock
from . import manifest as M

PROFILES = {
    "CLOSE_V1": "target = close zamkniętych świec; bez zmiennych dodatkowych",
    "CLOSE_OHLCV_PAST_V1": "target = close; zmienne historyczne (past covariates, Chronos-2): open, high, low, wolumen – tylko przeszłość, "
                           "bez wartości przyszłych",
}


class EngineError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def versions() -> dict:
    out = {"python": sys.version.split()[0]}
    for mod in ("torch", "numpy", "pandas", "chronos", "tsfm_public", "transformers", "einops", "safetensors"):
        try:
            m = __import__(mod)
            out[mod] = getattr(m, "__version__", "?")
        except Exception as exc:  # noqa: BLE001
            out[mod] = f"BRAK ({type(exc).__name__})"
    return out


def cuda_info() -> dict:
    try:
        import torch
        ok = torch.cuda.is_available()
        return {"available": bool(ok), "device_name": torch.cuda.get_device_name(0) if ok else None, "torch_cuda": getattr(torch.version, "cuda", None)}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"[:200]}


def rss_mb() -> float | None:
    try:
        import resource
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    except Exception:  # noqa: BLE001 - Windows: psutil is not a dependency; reported as unknown
        return None


def input_hash(req: dict) -> str:
    keep = {k: req.get(k) for k in ("close", "covariates", "profile", "pred_len", "context_len", "quantiles", "freq_tf")}
    return hashlib.sha256(json.dumps(keep, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


def _pick_device(torch, pref: str) -> tuple[str, str | None]:
    if pref == "CPU":
        return "cpu", "wybrano CPU w ustawieniach"
    if not torch.cuda.is_available():
        return "cpu", "CUDA niedostępne – CPU" if pref == "CUDA" else "brak GPU z CUDA – CPU"
    try:
        t = torch.ones(4, device="cuda:0")
        float((t * 2).sum().item())
        return "cuda:0", None
    except Exception as exc:  # noqa: BLE001
        return "cpu", f"test CUDA nieudany ({type(exc).__name__}) – CPU"


def _validate(req: dict, max_context: int) -> tuple[list[float], int, int]:
    close = [float(x) for x in req.get("close") or []]
    if not close:
        raise EngineError("CONFIG", "brak danych wejściowych (close)")
    if not all(math.isfinite(x) for x in close):
        raise EngineError("NON_FINITE_INPUT", "dane wejściowe zawierają NaN/Inf – odrzucone (bez interpolacji)")
    H = int(req.get("pred_len") or 0)
    if not 1 <= H <= 256:
        raise EngineError("CONFIG", f"pred_len {H} poza zakresem 1..256")
    ctx = int(req.get("context_len") or len(close))
    if not 32 <= ctx <= max_context:
        raise EngineError("CONFIG", f"context_len {ctx} poza zakresem 32..{max_context}")
    if len(close) < 32:
        raise EngineError("WARMUP", f"za mało świec ({len(close)} < 32)")
    return close[-ctx:], H, ctx


def _quantile_block(levels: list[float], arr) -> dict:
    """{level: [values per step]} + monotonicity flag (reported, never repaired)."""
    out = {f"{q:g}": [float(v) for v in arr[:, i]] for i, q in enumerate(levels)}
    crossing = 0
    for i in range(1, len(levels)):
        crossing += int(sum(1 for a, b in zip(arr[:, i - 1], arr[:, i]) if b < a - 1e-9))
    return {"levels": levels, "values": out, "crossing_steps": crossing}


class BaseEngine:
    model_id = ""

    def __init__(self):
        self.info: dict = {}
        self.loaded = False

    def _verify(self, weights_root: str, verify_files: bool) -> Path:
        if verify_files:
            try:
                M.verify(weights_root, self.model_id)
            except M.ManifestError as exc:
                raise EngineError(exc.code, exc.detail) from None
        else:
            s = M.summary(weights_root, self.model_id)
            if not s["installed"]:
                raise EngineError("NO_WEIGHTS", s["reason"])
        return M.model_dir(weights_root, self.model_id)

    def _identity(self, n_params: int) -> dict:
        pin = lock.model(self.model_id)
        if os.environ.get("MQ_TSFM_ALLOW_FIXTURE") != "1" and n_params != pin["params_measured"]:
            raise EngineError("INCOMPATIBLE", f"załadowany checkpoint ma {n_params} parametrów, a przypięty {pin['variant']} "
                                              f"{pin['params_measured']} – inny wariant, nie zostanie użyty")
        return {"model_id": self.model_id, "name": pin["name"], "variant": pin["variant"], "repo": pin["repo"], "revision": pin["revision"],
                "params": n_params, "params_upstream": pin["params_upstream"], "code": pin["code"], "fingerprint": lock.fingerprint(self.model_id)}

    def predict(self, req: dict) -> dict:  # pragma: no cover - abstract
        raise NotImplementedError

    def selftest(self) -> dict:
        """Smoke forecast + parity: this wrapper vs a DIRECT call of the official API on identical data and settings."""
        import numpy as np
        rng = np.random.default_rng(20261108)
        close = list(np.round(2000 + np.cumsum(rng.normal(0, 1.2, 512)), 2))
        req = {"close": close, "pred_len": 12, "context_len": 512, "profile": "CLOSE_V1", "quantiles": [0.1, 0.5, 0.9], "freq_tf": "M5"}
        t0 = time.perf_counter()
        got = self.predict(req)
        smoke = {"ok": len(got["point"]) == 12 and all(math.isfinite(v) for v in got["point"]), "ms": round((time.perf_counter() - t0) * 1000, 1),
                 "device": got["device"], "first_point": got["point"][0]}
        ref = self._direct(close, 12, [0.1, 0.5, 0.9])
        a = np.asarray(got["point"], dtype=np.float64)
        e = np.asarray(ref["point"], dtype=np.float64)
        qa = np.asarray([got["quantiles"]["values"][k] for k in ("0.1", "0.5", "0.9")], dtype=np.float64)
        qe = np.asarray(ref["quantiles"], dtype=np.float64)
        d = float(max(np.abs(a - e).max(), np.abs(qa - qe).max()))
        return {"smoke": smoke, "parity": {"status": "PASS" if d <= 1e-6 else "DIFF", "max_abs_diff": d,
                                           "criterion": "|adapter − bezpośrednie wywołanie oficjalnego API| ≤ 1e-6 (te same dane, CPU, te same parametry)"},
                "rss_mb": rss_mb()}

    def _direct(self, close, H, qs) -> dict:  # pragma: no cover - abstract
        raise NotImplementedError


class Chronos2Engine(BaseEngine):
    model_id = "chronos2"

    def __init__(self):
        super().__init__()
        self.pipe = None

    def load(self, weights_root: str, device: str = "AUTO", threads: int | None = None, verify_files: bool = True) -> dict:
        if self.loaded:
            return self.info
        t0 = time.perf_counter()
        d = self._verify(weights_root, verify_files)
        os.environ["HF_HUB_OFFLINE"] = "1"
        try:
            import torch
            from chronos import Chronos2Pipeline
        except Exception as exc:  # noqa: BLE001
            raise EngineError("MISSING_DEPENDENCY", f"{type(exc).__name__}: {exc}"[:300]) from None
        if threads:
            torch.set_num_threads(int(threads))
        dev, note = _pick_device(torch, device)
        try:
            self.pipe = Chronos2Pipeline.from_pretrained(str(d), device_map=dev, dtype=torch.float32)
        except Exception as exc:  # noqa: BLE001
            raise EngineError("LOAD_ERROR", f"{type(exc).__name__}: {exc}"[:400]) from None
        self.pipe.model.eval()
        n = sum(p.numel() for p in self.pipe.model.parameters())
        self.info = {**self._identity(n), "device": dev, "device_note": note, "dtype": "float32", "threads": torch.get_num_threads(),
                     "load_ms": round((time.perf_counter() - t0) * 1000, 1), "trained_quantiles": list(self.pipe.quantiles),
                     "model_context_length": int(self.pipe.model_context_length), "rss_mb": rss_mb()}
        self.loaded = True
        return self.info

    def _inputs(self, req: dict, close: list[float]):
        import numpy as np
        import torch
        prof = req.get("profile") or "CLOSE_V1"
        if prof == "CLOSE_V1":
            return [torch.tensor(close, dtype=torch.float32)]
        if prof == "CLOSE_OHLCV_PAST_V1":
            cov = req.get("covariates") or {}
            n = len(close)
            past = {}
            for k in ("open", "high", "low", "volume"):
                v = [float(x) for x in (cov.get(k) or [])][-n:]
                if len(v) != n or not all(math.isfinite(x) for x in v):
                    raise EngineError("COVARIATES_MISSING", f"profil {prof} wymaga zmiennej {k} dla całego kontekstu – brak / niepełna "
                                                            "(profil nie jest zmieniany po cichu)")
                past[k] = np.asarray(v, dtype=np.float32)
            return [{"target": np.asarray(close, dtype=np.float32), "past_covariates": past}]
        raise EngineError("CONFIG", f"nieznany profil wejścia {prof}")

    def predict(self, req: dict) -> dict:
        if not self.loaded:
            raise EngineError("NOT_LOADED", "model nie jest załadowany")
        import numpy as np
        import torch
        close, H, ctx = _validate(req, lock.model("chronos2")["max_context"])
        qs = sorted({float(q) for q in (req.get("quantiles") or [0.1, 0.5, 0.9])} | {0.5})
        t0 = time.perf_counter()
        with torch.inference_mode():
            q, _mean_is_median = self.pipe.predict_quantiles(self._inputs(req, close), prediction_length=H, quantile_levels=qs)
        arr = q[0][0].cpu().numpy().astype(np.float64)                       # (H, len(qs)) of the single target variate
        if not np.isfinite(arr).all():
            raise EngineError("NON_FINITE", "model zwrócił NaN/Inf")
        med = arr[:, qs.index(0.5)]
        return {"point": [float(v) for v in med], "point_kind": "median", "median": [float(v) for v in med],
                "quantiles": _quantile_block(qs, arr), "ms": round((time.perf_counter() - t0) * 1000, 1), "device": str(self.pipe.model.device),
                "context_bars": ctx, "profile": req.get("profile") or "CLOSE_V1", "input_hash": input_hash(req),
                "note": "kwantyle modelu (nieskalibrowane na danych użytkownika); punkt = mediana (kwantyl 0,5)"}

    def _direct(self, close, H, qs) -> dict:
        import torch
        with torch.inference_mode():
            q, m = self.pipe.predict_quantiles([torch.tensor(close, dtype=torch.float32)], prediction_length=H, quantile_levels=qs)
        return {"point": m[0][0].tolist(), "quantiles": q[0][0].T.tolist()}


FINETUNE_MANIFEST = "granite_finetune.json"


def verify_finetune(finetune_dir: str | None, run_id: str) -> tuple[Path, dict]:
    """A fine-tuned Granite TTM checkpoint of the Training Center: <finetune_dir>/<run_id>/ with config.json + model.safetensors and the
    manifest written by the trainer (sha256 of both files, base fingerprint, data range, metrics). Any mismatch -> not loaded."""
    if not finetune_dir:
        raise EngineError("NO_WEIGHTS", "brak folderu checkpointów dotrenowanych")
    d = Path(finetune_dir) / run_id
    try:
        man = json.loads((d / FINETUNE_MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise EngineError("NO_WEIGHTS", f"checkpoint {run_id}: brak / nieczytelny {FINETUNE_MANIFEST}") from None
    if man.get("base_fingerprint") != lock.fingerprint("granite_ttm"):
        raise EngineError("INCOMPATIBLE", f"checkpoint {run_id} powstał z innego modelu bazowego ({man.get('base_fingerprint')})")
    for f in man.get("files") or []:
        p = d / f["name"]
        if not p.is_file() or M.sha256_file(p) != f["sha256"]:
            raise EngineError("CHECKSUM", f"checkpoint {run_id}: {f['name']} brak / suma niezgodna – nie zostanie użyty")
    return d, {k: man.get(k) for k in ("run_id", "created_at", "data", "metrics", "base_fingerprint", "train")}


def _ttm_class():
    """The official TinyTimeMixerForPrediction of granite-tsfm WITHOUT executing tsfm_public/__init__.py (which imports the whole toolkit:
    pandas, scikit-learn, datasets, pyarrow - measured +120 MB RSS that inference never uses). The package objects are registered with
    their real search paths, so the model module and its configuration load from the installed files unchanged."""
    import importlib.util
    import types
    for name in ("tsfm_public", "tsfm_public.models", "tsfm_public.models.tinytimemixer"):
        if name in sys.modules:
            continue
        spec = importlib.util.find_spec(name)
        if spec is None or not spec.submodule_search_locations:
            raise ImportError(f"brak pakietu {name} (granite-tsfm)")
        mod = types.ModuleType(name)
        mod.__path__ = list(spec.submodule_search_locations)
        mod.__spec__ = spec
        sys.modules[name] = mod
    from tsfm_public.models.tinytimemixer.modeling_tinytimemixer import TinyTimeMixerForPrediction
    return TinyTimeMixerForPrediction


class GraniteTTMEngine(BaseEngine):
    """IBM Granite TinyTimeMixer R2 (tsfm_public.models.tinytimemixer.TinyTimeMixerForPrediction, official granite-tsfm code).

    Input: the last 512 CLOSED closes (the model's fixed context; fewer bars -> WARMUP, never padded with invented values). Normalization:
    z-score with the mean / standard deviation of THAT context window only (no future value, no statistic of other windows), the output
    is mapped back with the same mean / std -> price units. The model was trained with MSE: the output is a POINT forecast of the close
    for every step (no quantiles, no OHLC candles - nothing of that kind is produced or derived)."""
    model_id = "granite_ttm"

    def __init__(self):
        super().__init__()
        self.model = None
        self.device = "cpu"

    def load(self, weights_root: str, device: str = "AUTO", threads: int | None = None, verify_files: bool = True,
             checkpoint: str | None = None, finetune_dir: str | None = None) -> dict:
        if self.loaded:
            return self.info
        t0 = time.perf_counter()
        d = self._verify(weights_root, verify_files)
        ft = None
        if checkpoint and checkpoint != "BASE":
            d, ft = verify_finetune(finetune_dir, checkpoint)
        os.environ["HF_HUB_OFFLINE"] = "1"
        try:
            import torch
            TinyTimeMixerForPrediction = _ttm_class()
        except Exception as exc:  # noqa: BLE001
            raise EngineError("MISSING_DEPENDENCY", f"{type(exc).__name__}: {exc}"[:300]) from None
        if threads:
            torch.set_num_threads(int(threads))
        self.device, note = _pick_device(torch, device)
        try:
            self.model = TinyTimeMixerForPrediction.from_pretrained(str(d), local_files_only=True).to(self.device).eval()
        except Exception as exc:  # noqa: BLE001
            raise EngineError("LOAD_ERROR", f"{type(exc).__name__}: {exc}"[:400]) from None
        cfg = self.model.config
        pin = lock.model(self.model_id)
        if int(cfg.context_length) != pin["max_context"] or int(cfg.prediction_length) != pin["native_horizon"] or getattr(cfg, "resolution_prefix_tuning", False):
            raise EngineError("INCOMPATIBLE", f"checkpoint {cfg.context_length}-{cfg.prediction_length} (prefix {getattr(cfg, 'resolution_prefix_tuning', None)}) "
                                              f"≠ przypięty {pin['max_context']}-{pin['native_horizon']} bez prefiksu częstotliwości")
        n = sum(p.numel() for p in self.model.parameters())
        self.info = {**self._identity(n), "device": self.device, "device_note": note, "dtype": "float32", "threads": torch.get_num_threads(),
                     "load_ms": round((time.perf_counter() - t0) * 1000, 1), "trained_quantiles": [], "context_length": int(cfg.context_length),
                     "native_horizon": int(cfg.prediction_length), "loss": getattr(cfg, "loss", None), "rss_mb": rss_mb(),
                     "normalization": pin["normalization"], "checkpoint": checkpoint or "BASE", "finetune": ft}
        self.loaded = True
        return self.info

    def _forward(self, z):
        import torch
        with torch.inference_mode():
            out = self.model(past_values=torch.tensor(z, dtype=torch.float32, device=self.device).reshape(1, -1, 1))
        return out.prediction_outputs[0, :, 0].detach().cpu().numpy().astype("float64")

    def predict(self, req: dict) -> dict:
        if not self.loaded:
            raise EngineError("NOT_LOADED", "model nie jest załadowany")
        import numpy as np
        if (req.get("profile") or "CLOSE_V1") != "CLOSE_V1":
            raise EngineError("PROFILE_UNSUPPORTED", "Granite TTM liczy jeden szereg (close) – profil ze zmiennymi dodatkowymi nie jest obsługiwany")
        ctx_need = lock.model(self.model_id)["max_context"]
        close, H, ctx = _validate(req, ctx_need)
        if ctx != ctx_need or len(close) != ctx_need:
            raise EngineError("WARMUP", f"Granite TTM wymaga dokładnie {ctx_need} zamkniętych świec kontekstu (jest {len(close)}) – bez dopełniania")
        if H > lock.model(self.model_id)["native_horizon"]:
            raise EngineError("CONFIG", f"horyzont {H} > {lock.model(self.model_id)['native_horizon']} świec modelu")
        x = np.asarray(close, dtype=np.float64)
        mu, sd = float(x.mean()), float(x.std())
        if not sd > 0:
            raise EngineError("CONSTANT_INPUT", "stała cena w całym kontekście – brak skali do normalizacji (bez prognozy)")
        t0 = time.perf_counter()
        y = self._forward((x - mu) / sd)[:H] * sd + mu
        if not np.isfinite(y).all():
            raise EngineError("NON_FINITE", "model zwrócił NaN/Inf")
        return {"point": [float(v) for v in y], "point_kind": "point", "median": None, "quantiles": None,
                "ms": round((time.perf_counter() - t0) * 1000, 2), "device": self.device, "context_bars": ctx, "profile": "CLOSE_V1",
                "input_hash": input_hash(req), "normalization": {"method": "zscore_context_window", "mean": mu, "std": sd},
                "note": "prognoza punktowa close (model trenowany MSE) – bez kwantyli i bez świec OHLC; normalizacja tylko z okna kontekstu"}

    def selftest(self) -> dict:
        """Smoke forecast + parity of this adapter (explicit z-score of the window + inverse) with a DIRECT official call on the raw prices
        (the model's own internal std scaler). Both use only the context window; the difference is the scaler epsilon."""
        import numpy as np
        rng = np.random.default_rng(20261109)
        close = list(np.round(4000 + np.cumsum(rng.normal(0, 1.5, 512)), 2))
        t0 = time.perf_counter()
        got = self.predict({"close": close, "pred_len": 12, "context_len": 512, "profile": "CLOSE_V1", "freq_tf": "M5"})
        smoke = {"ok": len(got["point"]) == 12 and all(math.isfinite(v) for v in got["point"]), "ms": round((time.perf_counter() - t0) * 1000, 1),
                 "device": got["device"], "first_point": got["point"][0]}
        ref = self._forward(np.asarray(close, dtype=np.float64))[:12]
        d = float(np.abs(np.asarray(got["point"]) - ref).max())
        tol = 1e-4 * float(np.mean(close))
        return {"smoke": smoke, "parity": {"status": "PASS" if d <= tol else "DIFF", "max_abs_diff": d,
                                           "criterion": f"|adapter (z-score okna) − oficjalne wywołanie na cenach (wewnętrzny skaler std)| ≤ 1e-4 × poziom ceny ({tol:.3f})"},
                "rss_mb": rss_mb()}


def make(mid: str) -> BaseEngine:
    if mid == "chronos2":
        return Chronos2Engine()
    if mid == "granite_ttm":
        return GraniteTTMEngine()
    if mid in lock.RETIRED:
        raise EngineError("RETIRED", f"model {mid} został wycofany (1.40: zastąpiony przez Granite TTM) – nie jest ładowany")
    raise EngineError("CONFIG", f"nieznany model {mid}")
