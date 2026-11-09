"""Kronos inference engine (runs in .venv_kronos): one model + tokenizer per process, eval mode, no gradients.

Calls the ORIGINAL upstream API only (vendor/kronos: KronosPredictor.predict / predict_batch). What this file adds:
* loading from local, checksum-verified files (offline after installation; HF_HUB_OFFLINE=1),
* the compatibility check of the pair (tokenizer s1/s2 bits == model s1/s2 bits, 6 input channels, context <= 512),
* device choice: CUDA only when available AND a test operation works, otherwise CPU (the reason is reported); a CUDA error during a
  forecast moves the engine to CPU once and says so,
* a seeded main forecast (one sampled path, sample_count=1 - upstream averages samples when sample_count > 1, so it never returns
  separate paths) and OPTIONAL independent paths for an uncertainty band: N copies of the same input in predict_batch, each row is
  sampled independently; the band is the empirical quantile of those paths - NOT calibrated, NOT a probability.
"""
from __future__ import annotations

import math
import os
import time
from pathlib import Path

from . import lock
from . import manifest as M

DATA = Path(__file__).resolve().parent / "tests_data"


class EngineError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def versions() -> dict:
    out = {}
    import sys
    out["python"] = sys.version.split()[0]
    for mod in ("torch", "numpy", "pandas", "einops", "huggingface_hub", "safetensors"):
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
        return {"available": bool(ok), "device_name": torch.cuda.get_device_name(0) if ok else None,
                "torch_cuda": getattr(torch.version, "cuda", None)}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"[:200]}


class Engine:
    def __init__(self):
        self.predictor = None
        self.info: dict = {}
        self.key = None

    # ------------------------------------------------------------------ load
    def load(self, weights_dir: str, device: str = "AUTO", max_context: int = lock.MAX_CONTEXT, threads: int | None = None,
             verify_files: bool = True) -> dict:
        key = (str(weights_dir), device, int(max_context), threads)
        if self.predictor is not None and key == self.key:
            return self.info                                           # loaded once per process
        if int(max_context) > lock.MAX_CONTEXT or int(max_context) < 16:
            raise EngineError("CONFIG", f"max_context {max_context} poza zakresem 16..{lock.MAX_CONTEXT} ({lock.MODEL_NAME})")
        t0 = time.perf_counter()
        if verify_files:
            try:
                M.verify(weights_dir)
            except M.ManifestError as exc:
                raise EngineError(exc.code, exc.detail) from None
        else:
            s = M.summary(weights_dir)
            if not s["installed"]:
                raise EngineError("NO_WEIGHTS", s["reason"])
        try:
            import torch
            from .vendor.kronos import Kronos, KronosPredictor, KronosTokenizer
        except Exception as exc:  # noqa: BLE001
            raise EngineError("MISSING_DEPENDENCY", f"{type(exc).__name__}: {exc}"[:300]) from None
        os.environ["HF_HUB_OFFLINE"] = "1"                            # local files only from here on
        if threads:
            torch.set_num_threads(int(threads))
        dirs = M.component_dirs(weights_dir)
        try:
            tok = KronosTokenizer.from_pretrained(str(dirs["tokenizer"]))
            model = Kronos.from_pretrained(str(dirs["model"]))
        except Exception as exc:  # noqa: BLE001
            raise EngineError("LOAD_ERROR", f"{type(exc).__name__}: {exc}"[:400]) from None
        compat = {"tokenizer_s1_bits": tok.s1_bits, "tokenizer_s2_bits": tok.s2_bits, "model_s1_bits": model.s1_bits,
                  "model_s2_bits": model.s2_bits, "tokenizer_d_in": tok.d_in, "max_context": int(max_context)}
        if tok.s1_bits != model.s1_bits or tok.s2_bits != model.s2_bits or tok.d_in != 6:
            raise EngineError("INCOMPATIBLE", f"para model/tokenizer niezgodna: {compat}")
        n_model = sum(p.numel() for p in model.parameters())
        if os.environ.get("MQ_KRONOS_ALLOW_FIXTURE") != "1" and n_model != lock.MODEL["params_measured"]:
            raise EngineError("INCOMPATIBLE", f"załadowany model ma {n_model} parametrów, a przypięty {lock.MODEL_NAME} {lock.MODEL['params_measured']} "
                                              "– inny wariant, nie zostanie użyty (brak cichego modelu zastępczego)")
        tok.eval()
        model.eval()
        for p in list(tok.parameters()) + list(model.parameters()):
            p.requires_grad_(False)
        dev, note = self._pick_device(torch, device)
        self.predictor = KronosPredictor(model, tok, device=dev, max_context=int(max_context))
        self.key = key
        man = M.read(weights_dir) or {}
        self.info = {"model_name": lock.MODEL_NAME, "variant": lock.MODEL["repo"], "params_upstream": lock.MODEL["params_upstream"],
                     "fingerprint": lock.fingerprint(), "code": lock.CODE,
                     "device": dev, "device_requested": device, "device_note": note, "load_ms": round((time.perf_counter() - t0) * 1000, 1),
                     "params_model": sum(p.numel() for p in model.parameters()), "params_tokenizer": sum(p.numel() for p in tok.parameters()),
                     "compat": compat, "threads": torch.get_num_threads(),
                     "components": [{k: c.get(k) for k in ("kind", "repo", "revision")} for c in man.get("components") or []],
                     "installed_at": man.get("installed_at")}
        return self.info

    @staticmethod
    def _pick_device(torch, pref: str) -> tuple[str, str | None]:
        if pref == "CPU":
            return "cpu", "wybrano CPU w ustawieniach"
        if not torch.cuda.is_available():
            return "cpu", "CUDA niedostępne (brak GPU NVIDIA lub PyTorch bez CUDA) – CPU" if pref == "CUDA" else "brak GPU z CUDA – CPU"
        try:
            t = torch.ones(4, device="cuda:0")
            float((t * 2).sum().item())
            return "cuda:0", None
        except Exception as exc:  # noqa: BLE001
            return "cpu", f"test CUDA nieudany ({type(exc).__name__}: {exc}"[:160] + ") – CPU"

    def _to_cpu(self, why: str) -> None:
        p = self.predictor
        p.tokenizer = p.tokenizer.to("cpu")
        p.model = p.model.to("cpu")
        p.device = "cpu"
        self.info["device"] = "cpu"
        self.info["device_note"] = f"GPU_ERROR_FALLBACK_CPU: {why}"[:200]

    # ------------------------------------------------------------------ forecast
    def predict(self, req: dict) -> dict:
        if self.predictor is None:
            raise EngineError("NOT_LOADED", "model nie jest załadowany")
        import numpy as np
        import pandas as pd
        import torch
        c = req["candles"]
        n = len(c["close"])
        pred_len = int(req["pred_len"])
        if pred_len < 1 or pred_len > 256:
            raise EngineError("CONFIG", f"pred_len {pred_len} poza zakresem 1..256")
        if len(req["y_t"]) != pred_len:
            raise EngineError("CONFIG", f"liczba przyszłych znaczników {len(req['y_t'])} ≠ pred_len {pred_len}")
        df = pd.DataFrame({k: np.asarray(c[k], dtype=float) for k in ("open", "high", "low", "close")})
        vol = c.get("volume")
        if vol is not None:
            df["volume"] = np.asarray(vol, dtype=float)               # amount: upstream proxy volume x mean(OHLC) (marked by the bot)
        x_t = pd.Series(pd.to_datetime(c["t"]))
        y_t = pd.Series(pd.to_datetime(req["y_t"]))
        if len(x_t) != n:
            raise EngineError("CONFIG", "liczba znaczników czasu ≠ liczba świec")
        T, top_k, top_p = float(req.get("T", 1.0)), int(req.get("top_k", 0)), float(req.get("top_p", 0.9))
        seed = int(req.get("seed", 0)) & 0x7FFFFFFF

        def run_main():
            torch.manual_seed(seed)
            np.random.seed(seed % (2 ** 32))
            with torch.inference_mode():
                return self.predictor.predict(df=df, x_timestamp=x_t, y_timestamp=y_t, pred_len=pred_len, T=T, top_k=top_k, top_p=top_p,
                                              sample_count=1, verbose=False)
        t0 = time.perf_counter()
        try:
            out = run_main()
        except Exception as exc:  # noqa: BLE001
            if str(self.predictor.device).startswith("cuda"):
                self._to_cpu(f"{type(exc).__name__}: {exc}")
                t0 = time.perf_counter()
                out = run_main()
            else:
                raise
        ms = round((time.perf_counter() - t0) * 1000, 1)
        pred = {"t": [str(x) for x in req["y_t"]]}
        for k in ("open", "high", "low", "close"):
            pred[k] = [float(v) for v in out[k].to_numpy()]
        pred["volume"] = [float(v) for v in out["volume"].to_numpy()] if vol is not None else None
        if not all(math.isfinite(v) for k in ("open", "high", "low", "close") for v in pred[k]):
            raise EngineError("NON_FINITE", "model zwrócił wartości nieskończone / NaN")
        res = {"pred": pred, "ms": ms, "device": str(self.predictor.device), "device_note": self.info.get("device_note"), "seed": seed,
               "sampling": {"T": T, "top_k": top_k, "top_p": top_p, "sample_count": 1}, "context_bars": n, "paths": None}
        npaths = int(req.get("paths") or 0)
        if npaths >= 2:
            t1 = time.perf_counter()
            torch.manual_seed(seed + 1)
            with torch.inference_mode():
                outs = self.predictor.predict_batch([df] * npaths, [x_t] * npaths, [y_t] * npaths, pred_len=pred_len, T=T, top_k=top_k,
                                                    top_p=top_p, sample_count=1, verbose=False)
            closes = np.stack([o["close"].to_numpy() for o in outs])          # (N, pred_len)
            q = {f"q{int(p * 100)}": [float(v) for v in np.quantile(closes, p, axis=0)] for p in (0.1, 0.5, 0.9)}
            res["paths"] = {"n": npaths, "close_quantiles": q, "final_close": [float(v) for v in closes[:, -1]],
                            "ms": round((time.perf_counter() - t1) * 1000, 1),
                            "note": "empiryczne kwantyle niezależnych ścieżek – NIESKALIBROWANE, nie są prawdopodobieństwem"}
        return res

    # ------------------------------------------------------------------ self test
    def selftest(self, reference: bool = False) -> dict:
        """Short real forecast on the bundled upstream input; with reference=True:
        * PARITY: this engine's predict() (the path the bot uses) vs a DIRECT call of the official KronosPredictor.predict on the same
          data, timestamps, seed and sampling parameters - an independent code path, the expected values are not produced by the wrapper;
        * the authors' regression files (tests_data/) belong to Kronos-small + Tokenizer-base - they are compared only when that pair is
          loaded; for Kronos-base they are NOT_APPLICABLE (a different model must not reproduce Kronos-small's numbers)."""
        import numpy as np
        import pandas as pd
        df = pd.read_csv(DATA / "regression_input.csv", parse_dates=["timestamps"])
        feats = ["open", "high", "low", "close", "volume", "amount"]
        t0 = time.perf_counter()
        import torch
        torch.manual_seed(123)
        with torch.inference_mode():
            out = self.predictor.predict(df=df.iloc[:256][feats].reset_index(drop=True), x_timestamp=df["timestamps"].iloc[:256].reset_index(drop=True),
                                         y_timestamp=df["timestamps"].iloc[256:264].reset_index(drop=True), pred_len=8, T=1.0, top_k=1, top_p=1.0,
                                         sample_count=1, verbose=False)
        smoke_ok = bool(np.isfinite(out[feats].to_numpy()).all()) and out.shape == (8, 6)
        res = {"model": lock.MODEL_NAME, "smoke": {"ok": smoke_ok, "pred_len": 8, "context": 256, "ms": round((time.perf_counter() - t0) * 1000, 1),
                                                   "device": str(self.predictor.device), "first_close": float(out["close"].iloc[0])}}
        if not reference:
            return res
        dev0 = str(self.predictor.device)
        if dev0 != "cpu":
            self._to_cpu("porównanie referencyjne liczone na CPU (jak u autorów)")
        # ---- parity: adapter vs official call (sampled path, the production settings T=1, top_p=0.9)
        ctx, H, seed = 400, 12, 4242
        sub = df.iloc[:ctx]
        req = {"candles": {"t": [str(x) for x in sub["timestamps"]], **{k: [float(v) for v in sub[k]] for k in ("open", "high", "low", "close")},
                           "volume": [float(v) for v in sub["volume"]]},
               "y_t": [str(x) for x in df["timestamps"].iloc[ctx:ctx + H]], "pred_len": H, "T": 1.0, "top_k": 0, "top_p": 0.9, "seed": seed}
        got = self.predict(req)["pred"]
        torch.manual_seed(seed)
        np.random.seed(seed)
        with torch.inference_mode():
            ref = self.predictor.predict(df=sub[["open", "high", "low", "close", "volume"]].reset_index(drop=True),
                                         x_timestamp=pd.Series(pd.to_datetime(req["candles"]["t"])), y_timestamp=pd.Series(pd.to_datetime(req["y_t"])),
                                         pred_len=H, T=1.0, top_k=0, top_p=0.9, sample_count=1, verbose=False)
        d = max(float(np.abs(np.asarray(got[k]) - ref[k].to_numpy()).max()) for k in ("open", "high", "low", "close"))
        res["parity"] = {"status": "PASS" if d <= 1e-6 else "DIFF", "max_abs_diff": d, "context": ctx, "pred_len": H, "seed": seed,
                         "criterion": "|predict() bota − bezpośrednie KronosPredictor.predict| ≤ 1e-6 (te same dane, ziarno, T=1, top_p=0,9, CPU)"}
        # ---- the authors' regression files: only for the pair they were generated with
        if lock.MODEL["repo"] != lock.REFERENCE_DATA_MODEL:
            res["reference"] = {"status": "NOT_APPLICABLE", "rows": [], "criterion": f"dane referencyjne autorów dotyczą {lock.REFERENCE_DATA_MODEL} – "
                                f"{lock.MODEL_NAME} nie musi ich odtwarzać; tożsamość sprawdza parity + liczba parametrów"}
            return res
        rows = []
        for c in (512, 256):
            exp = pd.read_csv(DATA / f"regression_output_{c}.csv", parse_dates=["timestamps"])
            import random
            random.seed(123)
            np.random.seed(123)
            torch.manual_seed(123)
            with torch.inference_mode():
                g = self.predictor.predict(df=df.iloc[:c][feats].reset_index(drop=True), x_timestamp=df["timestamps"].iloc[:c].reset_index(drop=True),
                                           y_timestamp=df["timestamps"].iloc[c:c + len(exp)].reset_index(drop=True), pred_len=len(exp),
                                           T=1.0, top_k=1, top_p=1.0, sample_count=1, verbose=False)
            a, e = g[feats].to_numpy(dtype=np.float32), exp[feats].to_numpy(dtype=np.float32)
            absd = np.abs(a - e)
            reld = absd / (np.abs(e) + 1e-9)
            rows.append({"context": c, "max_abs_diff": float(absd.max()), "max_rel_diff": float(reld.max()), "pass_rtol_1e-5": bool(np.allclose(a, e, rtol=1e-5))})
        status = "PASS" if all(r["pass_rtol_1e-5"] for r in rows) else ("DIFF_WITHIN_FLOAT_NOISE" if max(r["max_rel_diff"] for r in rows) <= 1e-3 else "DIFF")
        res["reference"] = {"status": status, "rows": rows, "criterion": "upstream: np.testing.assert_allclose(rtol=1e-5), CPU, top_k=1"}
        return res
