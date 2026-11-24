"""1.46 audit, group B_runtimes_2: tsfm_runtime (install, engines, granite_finetune) and tabicl_runtime/install.py.

chunk_42#0 / chunk_41#4  a COMPLETE <file>.part (interrupted between the last byte and the rename) is verified, never requested with
                         `Range: bytes=<size>-` (HTTP 416 on every attempt and every later run = installer stuck until the user deleted
                         the file); a 416 for a partial file restarts the download from zero (as kronos_runtime.install._fetch).
chunk_42#5               no 'ponowienie 5/4' and no back-off sleep after the LAST attempt; 401 / 403 / 404 are not retried.
chunk_42#6               the MB/s after a resume counts only the bytes of THIS connection.
chunk_42#4               verify_finetune: schema PMW-GRANITE-FT-1 and checksums of config.json + model.safetensors are mandatory.
chunk_42#9               engines.PROFILES (dead constant) removed.
chunk_42#1               granite_finetune: when no epoch improves the validation MSE the saved model is the one early stopping selected
                         (the base), val_mse_saved / selected_epoch are reported, the verdict is never IMPROVED_VS_BASE.
chunk_42#3 (display)     the report states the number of test windows and warns about a small test sample (the gate is a DECISION).
No network: a local HTTP server on an ephemeral 127.0.0.1 port (RFC 7233 ranges) or a mocked urlopen; granite_finetune runs with a
numpy stand-in of torch and of TinyTimeMixerForPrediction (synthetic random walk - nothing here is a forecast)."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import signal
import sys
import tempfile
import threading
import types
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import _env  # noqa: F401 - backend on sys.path
import numpy as np


# ===================================================================================================== local HTTP server (RFC 7233)
class _Srv:
    """Serves {basename: bytes}; a Range starting at / beyond the end -> 416 (as the Hugging Face CDN); `always_416` answers 416 to any
    Range request (a resource that changed since the partial download)."""

    def __init__(self, files: dict[str, bytes], always_416: bool = False):
        self.files, self.always_416, self.ranges = files, always_416, []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # quiet
                pass

            def do_GET(self):
                data = outer.files.get(self.path.rsplit("/", 1)[-1])
                if data is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                rng = self.headers.get("Range")
                outer.ranges.append(rng)
                if rng:
                    start = int(rng.split("=")[1].split("-")[0])
                    if outer.always_416 or start >= len(data):
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{len(data)}")
                        self.end_headers()
                        return
                    body = data[start:]
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
                else:
                    body = data
                    self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.th = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.th.start()
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()
        self.httpd.server_close()


CFG = b'{"a": 1}'
WEIGHTS = bytes(range(256)) * 4                                                    # 1024 B


class _TsfmPin(unittest.TestCase):
    """chronos2 pin replaced by two small files (restored in tearDown, as tests/test_tsfm_bot.py does)."""

    def setUp(self):
        from tsfm_runtime import lock as L
        from tsfm_runtime import manifest as M
        self.L, self.M = L, M
        self._orig = json.loads(json.dumps(L.MODELS["chronos2"]))
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "w"
        src = Path(self.tmp.name) / "src"
        src.mkdir()
        (src / "config.json").write_bytes(CFG)
        (src / "model.safetensors").write_bytes(WEIGHTS)
        L.MODELS["chronos2"]["files"] = [{"name": "config.json", "size": len(CFG), "git_blob_sha1": M.git_blob_sha1(src / "config.json")},
                                         {"name": "model.safetensors", "size": len(WEIGHTS), "sha256": hashlib.sha256(WEIGHTS).hexdigest()}]
        self.d = M.model_dir(self.root, "chronos2")
        self.d.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.L.MODELS["chronos2"] = self._orig
        self.tmp.cleanup()

    def run_download(self, srv, retries=4):
        from tsfm_runtime import install as I
        out = io.StringIO()
        with mock.patch.object(self.L, "SOURCE", srv.url), mock.patch("time.sleep") as sl, contextlib.redirect_stdout(out):
            r = I.download("chronos2", str(self.root), retries=retries)
        return r, sl, out.getvalue()


# ===================================================================================================== chunk_42#0 tsfm complete .part
class TestTsfmCompletePart(_TsfmPin):
    def test_complete_part_is_verified_not_requested_with_a_range(self):
        (self.d / "model.safetensors.part").write_bytes(WEIGHTS)                    # interrupted after the last byte, before the rename
        with _Srv({"config.json": CFG, "model.safetensors": WEIGHTS}) as srv:
            r, sl, out = self.run_download(srv)
        self.assertTrue(r["ok"], r)                                                  # was NETWORK: 5 x HTTP 416 on every run
        self.assertIn("plik częściowy kompletny", out)
        self.assertNotIn(f"bytes={len(WEIGHTS)}-", srv.ranges)
        self.assertEqual(sl.call_count, 0)
        self.assertTrue(self.M.verify(self.root, "chronos2")["ok"])
        self.assertFalse((self.d / "model.safetensors.part").exists())

    def test_complete_but_wrong_part_is_rejected_and_the_next_run_installs(self):
        (self.d / "model.safetensors.part").write_bytes(b"\0" * len(WEIGHTS))       # full size, wrong content
        with _Srv({"config.json": CFG, "model.safetensors": WEIGHTS}) as srv:
            r, _, _ = self.run_download(srv)
            self.assertEqual((r["ok"], r["code"]), (False, "CHECKSUM"))
            self.assertFalse((self.d / "model.safetensors.part").exists())
            r, _, _ = self.run_download(srv)
        self.assertTrue(r["ok"], r)

    def test_416_for_a_partial_file_restarts_from_zero(self):
        (self.d / "model.safetensors.part").write_bytes(WEIGHTS[:300])
        with _Srv({"config.json": CFG, "model.safetensors": WEIGHTS}, always_416=True) as srv:
            r, _, _ = self.run_download(srv)
        self.assertTrue(r["ok"], r)
        self.assertIn("bytes=300-", srv.ranges)
        self.assertIn(None, srv.ranges)                                              # the restart is a plain GET (no Range)


# ===================================================================================================== chunk_41#4 tabicl complete .part
class TestTabiclCompletePart(unittest.TestCase):
    def setUp(self):
        from tabicl_runtime import lock as TL
        self.TL = TL
        self._orig = json.loads(json.dumps(TL.PIN))
        TL.PIN["files"] = [{"name": "tabicl.ckpt", "size": len(WEIGHTS), "sha256": hashlib.sha256(WEIGHTS).hexdigest()}]
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.TL.PIN.clear()
        self.TL.PIN.update(self._orig)
        self.tmp.cleanup()

    def test_complete_part_installs(self):
        from tabicl_runtime import install as TI
        d = TI.model_dir(self.tmp.name)
        d.mkdir(parents=True)
        (d / "tabicl.ckpt.part").write_bytes(WEIGHTS)
        with _Srv({"tabicl.ckpt": WEIGHTS}) as srv, mock.patch.object(self.TL, "SOURCE", srv.url), mock.patch("time.sleep") as sl, \
                contextlib.redirect_stdout(io.StringIO()):
            r = TI.download(self.tmp.name)
        self.assertTrue(r["ok"], r)                                                  # was NETWORK (HTTP 416) on every run
        self.assertEqual(sl.call_count, 0)
        self.assertTrue(TI.verify(self.tmp.name)["ok"])


# ===================================================================================================== chunk_42#5 retries
class TestRetryLoops(_TsfmPin):
    def _fail(self, exc):
        return mock.patch("urllib.request.urlopen", side_effect=exc)

    def test_tsfm_no_retry_message_or_sleep_after_the_last_attempt(self):
        from tsfm_runtime import install as I
        out = io.StringIO()
        with self._fail(OSError("connection reset")), mock.patch("time.sleep") as sl, contextlib.redirect_stdout(out):
            r = I.download("chronos2", str(self.root), retries=4)
        self.assertEqual(r["code"], "NETWORK")
        self.assertEqual(sl.call_count, 4)
        self.assertNotIn("5/4", out.getvalue())
        self.assertEqual(out.getvalue().count("ponowienie"), 4)

    def test_tsfm_404_is_not_retried(self):
        from tsfm_runtime import install as I
        e404 = urllib.error.HTTPError("http://x", 404, "Not Found", {}, None)
        with self._fail(e404), mock.patch("time.sleep") as sl, contextlib.redirect_stdout(io.StringIO()):
            r = I.download("chronos2", str(self.root), retries=4)
        self.assertEqual(r["code"], "NETWORK")
        self.assertIn("404", r["error"])
        self.assertEqual(sl.call_count, 0)

    def test_tabicl_no_retry_message_or_sleep_after_the_last_attempt(self):
        from tabicl_runtime import install as TI
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as w, self._fail(OSError("connection reset")), mock.patch("time.sleep") as sl, \
                contextlib.redirect_stdout(out):
            r = TI.download(w, retries=4)
        self.assertEqual(r["code"], "NETWORK")
        self.assertEqual(sl.call_count, 4)
        self.assertNotIn("5/4", out.getvalue())


# ===================================================================================================== chunk_42#6 speed after resume
class TestResumeSpeed(unittest.TestCase):
    def test_speed_counts_only_this_connection(self):
        from tsfm_runtime import install as I

        class R:
            status = 206

            def __init__(self):
                self.chunks = [b"\1" * 400_000, b""]

            def read(self, n):
                return self.chunks.pop(0)

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        ticks = iter([100.0] + [100.1] * 10)                                       # t0, then 0.1 s later
        fake_time = types.SimpleNamespace(time=lambda: next(ticks), sleep=lambda s: None)
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as d:
            part = Path(d) / "x.part"
            part.write_bytes(b"\0" * 600_000)                                       # 600 kB from an earlier run
            with mock.patch("urllib.request.urlopen", return_value=R()), mock.patch.object(I, "time", fake_time), \
                    contextlib.redirect_stdout(out):
                I._download("http://x/x", part, 1_000_000, None, "x")
            self.assertEqual(part.stat().st_size, 1_000_000)
        self.assertIn("(4.0 MB/s)", out.getvalue())                                 # 400 kB / 0.1 s - was 10.0 (1 MB / 0.1 s)


# ===================================================================================================== chunk_42#4 verify_finetune
class TestVerifyFinetune(unittest.TestCase):
    def _ckpt(self, root: Path, rid: str, **over):
        from tsfm_runtime import lock as L
        d = root / rid
        d.mkdir(parents=True)
        files = []
        for name in ("config.json", "model.safetensors"):
            (d / name).write_bytes(name.encode() * 10)
            files.append({"name": name, "sha256": hashlib.sha256(name.encode() * 10).hexdigest(), "size": len(name) * 10})
        man = {"schema": "PMW-GRANITE-FT-1", "run_id": rid, "base_fingerprint": L.fingerprint("granite_ttm"), "files": files}
        man.update(over)
        (d / "granite_finetune.json").write_text(json.dumps(man), encoding="utf-8")
        return files

    def test_files_and_schema_are_mandatory(self):
        from tsfm_runtime import engines as E
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            files = self._ckpt(root, "GTR-GOOD")
            d, info = E.verify_finetune(str(root), "GTR-GOOD")
            self.assertEqual((d, info["run_id"]), (root / "GTR-GOOD", "GTR-GOOD"))
            for rid, over in (("GTR-NOFILES", {"files": None}), ("GTR-EMPTY", {"files": []}),
                              ("GTR-NOWEIGHTS", {"files": [files[0]]}), ("GTR-SCHEMA", {"schema": "OTHER"}),
                              ("GTR-NOSCHEMA", {"schema": None})):
                self._ckpt(root, rid, **over)
                with self.assertRaises(E.EngineError, msg=rid) as cm:
                    E.verify_finetune(str(root), rid)
                self.assertIn(cm.exception.code, ("CHECKSUM", "INCOMPATIBLE"), rid)


# ===================================================================================================== chunk_42#9 dead constant
class TestDeadProfiles(unittest.TestCase):
    def test_engines_profiles_removed(self):
        from tsfm_runtime import engines as E
        self.assertFalse(hasattr(E, "PROFILES"))


# ===================================================================================================== granite_finetune (numpy stand-ins)
class _T(np.ndarray):
    """numpy stand-in for the torch.Tensor methods granite_finetune calls."""

    def numpy(self):
        return np.asarray(self)

    def detach(self):
        return self

    def clone(self):
        return np.array(self).view(_T)


class _Scalar:
    def __init__(self, v):
        self.v = float(v)

    def __float__(self):
        return self.v

    def backward(self):
        pass


class _P:
    def __init__(self, v):
        self.data = np.asarray([float(v)]).view(_T)
        self.requires_grad = True

    def numel(self):
        return 1


class _Opt:
    """Every step moves the trainable 'head' by STEP (normalized units): the bias of the forecast changes by STEP per step."""
    STEP = 0.5

    def __init__(self, params, lr=None, weight_decay=None):
        self.params = list(params)

    def zero_grad(self):
        pass

    def step(self):
        for p in self.params:
            p.data = (np.asarray(p.data) + self.STEP).view(_T)


def _fake_torch():
    t = types.ModuleType("torch")
    t.float32 = np.float32
    t.manual_seed = lambda s: None
    t.set_num_threads = lambda n: None
    t.get_num_threads = lambda: 1
    t.tensor = lambda x, dtype=None, device=None: np.asarray(x, dtype=dtype or np.float32).view(_T)
    t.inference_mode = contextlib.nullcontext
    t.mean = lambda x: _Scalar(np.mean(np.asarray(x, dtype=np.float64)))
    t.optim = types.SimpleNamespace(AdamW=_Opt)
    return t


class _FakeTTM:
    """Forecast = last context value (z-score units) + head bias, for all 96 steps. Weights file: {"head": bias}."""

    def __init__(self, head=0.0):
        self.p = {"backbone.mixer": _P(0.0), "head.bias": _P(head)}

    @classmethod
    def from_pretrained(cls, path, local_files_only=True):
        f = Path(path) / "model.safetensors"
        return cls(json.loads(f.read_text())["head"] if f.is_file() else 0.0)

    def eval(self):
        return self

    def train(self):
        return self

    def named_parameters(self):
        return list(self.p.items())

    def parameters(self):
        return list(self.p.values())

    def state_dict(self):
        return {k: v.data for k, v in self.p.items()}

    def load_state_dict(self, sd):
        for k, v in sd.items():
            self.p[k].data = np.array(v).view(_T)

    def __call__(self, past_values):
        x = np.asarray(past_values)
        y = np.repeat(x[:, -1:, :], 96, axis=1) + float(np.asarray(self.p["head.bias"].data)[0])
        return types.SimpleNamespace(prediction_outputs=y.view(_T))

    def save_pretrained(self, path, safe_serialization=True):
        Path(path, "config.json").write_text("{}")
        Path(path, "model.safetensors").write_text(json.dumps({"head": float(np.asarray(self.p["head.bias"].data)[0])}))


class TestGraniteFinetuneSelection(unittest.TestCase):
    def _run(self, base_head: float, epochs: int = 2):
        from tsfm_runtime import engines as E
        from tsfm_runtime import granite_finetune as GF
        from tsfm_runtime import manifest as M
        rng = np.random.default_rng(5)
        c = list(np.round(2000 + np.cumsum(rng.normal(0, 1.0, 5000)), 2))
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        t = Path(tmp.name)
        base = t / "base"
        base.mkdir()
        (base / "model.safetensors").write_text(json.dumps({"head": base_head}))
        (t / "ds.json").write_text(json.dumps({"instrument": "XAUUSD", "timeframe": "M5", "data_kind": "TEST_SERIES", "close": c, "open": c,
                                               "high": [x + 0.5 for x in c], "low": [x - 0.5 for x in c], "bars": len(c)}), encoding="utf-8")
        prev_term, prev_env = signal.getsignal(signal.SIGTERM), os.environ.get("HF_HUB_OFFLINE")
        out = io.StringIO()
        try:
            with mock.patch.dict(sys.modules, {"torch": _fake_torch()}), mock.patch.object(E, "_ttm_class", lambda: _FakeTTM), \
                    mock.patch.object(M, "verify", lambda *a, **k: {"ok": True}), mock.patch.object(M, "model_dir", lambda *a, **k: base), \
                    contextlib.redirect_stdout(out):
                rc = GF.main(["--data", str(t / "ds.json"), "--weights-root", str(t), "--out", str(t / "out"), "--horizon", "12",
                              "--epochs", str(epochs), "--run-id", "GTR-T"])
        finally:
            signal.signal(signal.SIGTERM, prev_term)
            if prev_env is None:
                os.environ.pop("HF_HUB_OFFLINE", None)
            else:
                os.environ["HF_HUB_OFFLINE"] = prev_env
        self.assertEqual(rc, 0, out.getvalue()[-2000:])
        man = json.loads((t / "out" / "GTR-T" / "granite_finetune.json").read_text(encoding="utf-8"))
        saved = json.loads((t / "out" / "GTR-T" / "model.safetensors").read_text())["head"]
        return man, saved

    def test_no_improving_epoch_saves_the_selected_base_model(self):
        man, saved = self._run(base_head=0.0)                                      # every step makes the bias worse
        m = man["metrics"]
        self.assertTrue(all(h["val_mse"] > m["val_mse_base"] for h in man["train"]["history"]))
        self.assertEqual(saved, 0.0)                                                 # was the (worse) last epoch
        self.assertEqual(m["selected_epoch"], 0)
        self.assertEqual(m["val_mse_saved"], m["val_mse_base"])
        self.assertEqual(m["val_mse_best"], m["val_mse_saved"])
        self.assertEqual(m["test_finetuned"], m["test_base"])
        self.assertEqual(m["verdict"], "NOT_BETTER_THAN_BASE")
        self.assertIn("żadna epoka", m["note"])

    def test_improving_epoch_is_selected_and_reported(self):
        man, saved = self._run(base_head=-40.0)                                    # ~13 steps / epoch x 0.5 towards 0
        m = man["metrics"]
        best = min(man["train"]["history"], key=lambda h: h["val_mse"])
        self.assertEqual(m["selected_epoch"], best["epoch"])
        self.assertEqual(m["val_mse_saved"], best["val_mse"])
        self.assertLess(m["val_mse_saved"], m["val_mse_base"])
        self.assertNotEqual(saved, -40.0)
        self.assertEqual(m["verdict"], "IMPROVED_VS_BASE")

    def test_small_test_sample_is_stated(self):
        man, _ = self._run(base_head=-40.0)
        m = man["metrics"]
        self.assertEqual(m["test_windows"], man["train"]["windows"]["test"])
        self.assertLess(m["test_windows"], 100)
        self.assertIn("mała próba testowa", m["note"])


if __name__ == "__main__":
    unittest.main()
