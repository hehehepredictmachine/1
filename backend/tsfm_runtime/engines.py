"""Inference engines of Chronos-2 and FinCast (run ONLY inside the model's own environment / process: .venv_chronos2, .venv_fincast).

Both call the ORIGINAL upstream API and nothing else:
  Chronos-2  chronos.Chronos2Pipeline.from_pretrained(<local dir>) + predict_quantiles(inputs, prediction_length, quantile_levels)
  FinCast    ffm.FFM(FFmHparams(...), checkpoint=<v1.pth>) [torch.load(weights_only=True) + load_state_dict(strict=True) in upstream code]
             + FFM.forecast(inputs, freq)
What this file adds: loading from local, checksum-verified files (offline), the identity check of the loaded checkpoint (parameter
count == the pinned measurement), input validation (finite, length, horizon), the explicit target / input profile, the device choice
(CUDA only when available AND working, else CPU, the reason reported) and a self test with a PARITY check against a direct call of the
official API on the same data (independent code path - the expected values are never produced by this wrapper).

Output semantics (never re-labelled):
  quantiles    the model's own quantile forecasts of the close at every step (Chronos-2: 21 trained levels, FinCast: 0.1..0.9)
  point        Chronos-2: the 0.5 quantile (the pipeline's "mean" output IS the median) -> point_kind "median";
               FinCast: the mean head (point_forecast_mode="mean") -> point_kind "mean"; its 0.5 quantile is reported as `median`.
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
VENDOR_FINCAST = Path(__file__).resolve().parent / "vendor" / "fincast"


class EngineError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def versions() -> dict:
    out = {"python": sys.version.split()[0]}
    for mod in ("torch", "numpy", "pandas", "chronos", "transformers", "einops", "safetensors"):
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


class FinCastEngine(BaseEngine):
    model_id = "fincast"

    def __init__(self):
        super().__init__()
        self.base = None          # FFM instance that loaded the checkpoint (official loading path)
        self.apis: dict = {}      # (context_len, horizon_len) -> FFM sharing the loaded module (no second load)
        self.device = "cpu"

    def _import(self):
        if str(VENDOR_FINCAST) not in sys.path:
            sys.path.insert(0, str(VENDOR_FINCAST))             # only in this process: the upstream package names are generic
        from ffm import FFM, FFmHparams                          # noqa: E402 - official code (vendor/fincast/UPSTREAM.md)
        return FFM, FFmHparams

    def _hparams(self, ctx: int, H: int, batch: int = 1):
        _, FFmHparams = self._import()
        h = lock.model("fincast")["hparams"]
        return FFmHparams(backend="gpu" if self.device.startswith("cuda") else "cpu", per_core_batch_size=batch, horizon_len=H, context_len=ctx,
                          use_positional_embedding=h["use_positional_embedding"], num_experts=h["num_experts"], gating_top_n=h["gating_top_n"],
                          load_from_compile=h["load_from_compile"], point_forecast_mode="mean")

    def load(self, weights_root: str, device: str = "AUTO", threads: int | None = None, verify_files: bool = True) -> dict:
        if self.loaded:
            return self.info
        t0 = time.perf_counter()
        d = self._verify(weights_root, verify_files)
        try:
            import torch
            FFM, _ = self._import()
        except Exception as exc:  # noqa: BLE001
            raise EngineError("MISSING_DEPENDENCY", f"{type(exc).__name__}: {exc}"[:300]) from None
        if threads:
            torch.set_num_threads(int(threads))
        self.device, note = _pick_device(torch, device)
        try:
            self.base = FFM(hparams=self._hparams(512, 12), checkpoint=str(d / "v1.pth"), loading_mode=0)   # strict + weights_only upstream
        except RuntimeError as exc:
            if "out of memory" in str(exc).lower() or "DefaultCPUAllocator" in str(exc):
                raise EngineError("RESOURCE_LIMIT", f"za mało pamięci na FinCast 1B: {exc}"[:300]) from None
            raise EngineError("LOAD_ERROR", f"{type(exc).__name__}: {exc}"[:400]) from None
        except Exception as exc:  # noqa: BLE001
            raise EngineError("LOAD_ERROR", f"{type(exc).__name__}: {exc}"[:400]) from None
        self.base.model_eval_mode()
        n = sum(p.numel() for p in self.base._model.parameters())
        self.apis[(512, 12)] = self.base
        self.info = {**self._identity(n), "device": str(self.base._device), "device_note": note, "dtype": "float32", "threads": torch.get_num_threads(),
                     "load_ms": round((time.perf_counter() - t0) * 1000, 1), "trained_quantiles": list(self.base.quantiles),
                     "max_context": lock.model("fincast")["max_context"], "rss_mb": rss_mb(),
                     "hparams": lock.model("fincast")["hparams"]}
        self.loaded = True
        return self.info

    def _api(self, ctx: int, H: int):
        """FFM object for this context / horizon sharing the already loaded module (loading_mode=1: upstream skips the checkpoint load)."""
        k = (ctx, H)
        if k not in self.apis:
            FFM, _ = self._import()
            a = FFM(hparams=self._hparams(ctx, H), checkpoint=None, loading_mode=1)
            a._model = self.base._model
            self.apis[k] = a
        return self.apis[k]

    def predict(self, req: dict) -> dict:
        if not self.loaded:
            raise EngineError("NOT_LOADED", "model nie jest załadowany")
        import numpy as np
        import torch
        if (req.get("profile") or "CLOSE_V1") != "CLOSE_V1":
            raise EngineError("PROFILE_UNSUPPORTED", "FinCast liczy jeden szereg (close) – profil ze zmiennymi dodatkowymi nie jest obsługiwany")
        close, H, ctx = _validate(req, lock.model("fincast")["max_context"])
        tf = req.get("freq_tf") or "M5"
        fmap = lock.model("fincast")["freq_class"]
        if tf not in fmap:
            raise EngineError("FREQ_UNSUPPORTED", f"FinCast: brak mapowania częstotliwości dla {tf}")
        api = self._api(ctx, H)
        t0 = time.perf_counter()
        with torch.inference_mode():
            mean, full = api.forecast([np.asarray(close, dtype=np.float32)], freq=[fmap[tf]])
        mean = np.asarray(mean[0], dtype=np.float64)[:H]
        full = np.asarray(full[0], dtype=np.float64)[:H]                     # (H, 1 + 9): mean head + quantiles 0.1..0.9
        if not (np.isfinite(mean).all() and np.isfinite(full).all()):
            raise EngineError("NON_FINITE", "model zwrócił NaN/Inf")
        levels = [float(q) for q in api.quantiles]
        want = sorted({float(q) for q in (req.get("quantiles") or [0.1, 0.5, 0.9])} | {0.5})
        missing = [q for q in want if q not in levels]
        if missing:
            raise EngineError("QUANTILE_UNSUPPORTED", f"FinCast zwraca kwantyle {levels}; brak {missing}")
        qarr = np.stack([full[:, 1 + levels.index(q)] for q in want], axis=1)
        med = full[:, 1 + levels.index(0.5)]
        return {"point": [float(v) for v in mean], "point_kind": "mean", "median": [float(v) for v in med],
                "quantiles": _quantile_block(want, qarr), "ms": round((time.perf_counter() - t0) * 1000, 1), "device": str(api._device),
                "context_bars": ctx, "profile": "CLOSE_V1", "freq_class": fmap[tf], "input_hash": input_hash(req),
                "note": "kwantyle modelu (nieskalibrowane na danych użytkownika); punkt = średnia (głowica mean), mediana osobno"}

    def _direct(self, close, H, qs) -> dict:
        """Official notebook path: a NEW FFM with the notebook's batch size, sharing nothing but the loaded weights module."""
        import numpy as np
        import torch
        FFM, FFmHparams = self._import()
        h = lock.model("fincast")["hparams"]
        hp = FFmHparams(backend="cpu", per_core_batch_size=32, horizon_len=H, context_len=len(close), use_positional_embedding=False,
                        num_experts=h["num_experts"], gating_top_n=h["gating_top_n"], load_from_compile=True, point_forecast_mode="mean")
        a = FFM(hparams=hp, checkpoint=None, loading_mode=1)
        a._model = self.base._model
        with torch.inference_mode():
            mean, full = a.forecast([np.asarray(close, dtype=np.float32)], freq=[0])
        idx = [1 + [float(x) for x in a.quantiles].index(q) for q in qs]
        return {"point": list(mean[0][:H]), "quantiles": [list(full[0][:H, i]) for i in idx]}


def make(mid: str) -> BaseEngine:
    if mid == "chronos2":
        return Chronos2Engine()
    if mid == "fincast":
        return FinCastEngine()
    raise EngineError("CONFIG", f"nieznany model {mid}")
