"""Kronos runtime (.venv_kronos: torch, pandas, huggingface_hub) - skipped where torch is not installed (main .venv of the bot).

Run with the Kronos interpreter:  .venv_kronos\\Scripts\\python -m unittest test_kronos_runtime   (from tests/)
* vendored upstream code in its own namespace (no global "model" module), license kept, only the import line differs;
* manifest: tamper detection, test fixtures refused outside the tests;
* engine on a RANDOM-WEIGHT fixture (test only - kronos_fixture.py): offline load (network blocked), eval/no grad, compatibility of the
  pair, CPU fallback when CUDA is requested without a GPU, seeded determinism, equality with the original KronosPredictor call,
  independent paths + quantiles, input errors, worker protocol, timing at the published Kronos-small architecture size (random-weight fixture; the real Kronos-base is tested in test_foundation_real.py);
* installer download logic with a mocked Hugging Face API: checksum mismatch, wrong revision, missing safetensors, offline;
* the upstream regression comparison with the OFFICIAL weights runs only when MQ_KRONOS_WEIGHTS_DIR points to a real installation
  (on the user's computer after 33_KRONOS_INSTALUJ.bat) - here it is skipped, never faked.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(HERE))
try:
    import torch  # noqa: F401
    HAVE_TORCH = True
except Exception:  # noqa: BLE001
    HAVE_TORCH = False


@unittest.skipUnless(HAVE_TORCH, "PyTorch nie jest zainstalowany w tym interpreterze (to test .venv_kronos)")
class TestKronosRuntime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["MQ_KRONOS_ALLOW_FIXTURE"] = "1"
        import kronos_fixture
        cls.tmp = Path(tempfile.mkdtemp(prefix="kronos_rt_"))
        cls.small = cls.tmp / "small"
        kronos_fixture.build(cls.small, small=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)
        os.environ.pop("MQ_KRONOS_ALLOW_FIXTURE", None)

    def candles(self, n=200, vol=True):
        import math
        ts = [f"2026-10-{1 + (i * 5) // 1440:02d} {((i * 5) // 60) % 24:02d}:{(i * 5) % 60:02d}:00" for i in range(n + 32)]
        c = [2000 + 4 * math.sin(i / 7) + i * 0.02 for i in range(n)]
        return ts, {"t": ts[:n], "open": [x - 0.2 for x in c], "high": [x + 0.6 for x in c], "low": [x - 0.6 for x in c], "close": c,
                    "volume": [50 + i % 9 for i in range(n)] if vol else None}

    def test_01_vendored_namespace_and_license(self):
        import kronos_runtime.vendor.kronos as KV
        self.assertTrue(all(hasattr(KV, k) for k in ("Kronos", "KronosTokenizer", "KronosPredictor")))
        self.assertNotIn("model", sys.modules)                                  # no generic "model" package leaks into the process
        src = (ROOT / "backend/kronos_runtime/vendor/kronos/kronos.py").read_text(encoding="utf-8")
        self.assertIn("from .module import *", src)
        self.assertFalse([ln for ln in src.splitlines() if ln.strip().startswith(("sys.path.append", "from model", "import model"))])
        lic = (ROOT / "backend/kronos_runtime/vendor/kronos/LICENSE").read_text(encoding="utf-8")
        self.assertIn("MIT License", lic)
        self.assertIn("Copyright (c) 2025 ShiYu", lic)

    def test_02_manifest_tamper_and_fixture_guard(self):
        from kronos_runtime import lock
        from kronos_runtime import manifest as M
        d = self.tmp / "tamper"
        shutil.copytree(self.small, d)
        self.assertTrue(M.verify(d)["ok"])
        f = d / lock.component_dir_name(lock.MODEL) / "model.safetensors"
        b = bytearray(f.read_bytes())
        b[-1] ^= 0xFF
        f.write_bytes(bytes(b))
        with self.assertRaises(M.ManifestError) as cm:
            M.verify(d)
        self.assertEqual(cm.exception.code, "CHECKSUM")
        os.environ.pop("MQ_KRONOS_ALLOW_FIXTURE")
        try:
            s = M.summary(self.small)
            self.assertFalse(s["installed"])
            self.assertIn("testowy", s["reason"])
        finally:
            os.environ["MQ_KRONOS_ALLOW_FIXTURE"] = "1"

    def test_03_engine_offline_load_predict_paths_and_errors(self):
        from kronos_runtime import engine as E
        real_connect = socket.socket.connect

        def no_net(*a, **k):
            raise AssertionError("network access during offline load/predict")
        with mock.patch.object(socket.socket, "connect", no_net):
            eng = E.Engine()
            info = eng.load(str(self.small), device="CUDA" if not __import__("torch").cuda.is_available() else "CPU", max_context=512, threads=1)
            self.assertEqual(info["device"], "cpu")
            self.assertTrue(info["device_note"])                                # requested CUDA without GPU -> CPU with the reason
            self.assertEqual(info["compat"]["tokenizer_s1_bits"], info["compat"]["model_s1_bits"])
            self.assertFalse(any(p.requires_grad for p in eng.predictor.model.parameters()))
            self.assertFalse(eng.predictor.model.training)
            self.assertIs(eng.load(str(self.small), device=info["device_requested"], max_context=512, threads=1), info)   # once per process
            ts, cand = self.candles()
            req = {"candles": cand, "y_t": ts[200:212], "pred_len": 12, "seed": 11, "T": 1.0, "top_k": 0, "top_p": 0.9}
            a, b = eng.predict(req), eng.predict(req)
            self.assertEqual(a["pred"]["close"], b["pred"]["close"])            # seeded -> reproducible
            self.assertEqual(len(a["pred"]["close"]), 12)
            self.assertIsNotNone(a["pred"]["volume"])
            import numpy as np
            import pandas as pd
            torch = __import__("torch")
            torch.manual_seed(11)
            np.random.seed(11)
            df = pd.DataFrame({k: cand[k] for k in ("open", "high", "low", "close")} | {"volume": cand["volume"]})
            with torch.inference_mode():
                ref = eng.predictor.predict(df=df, x_timestamp=pd.Series(pd.to_datetime(cand["t"])), y_timestamp=pd.Series(pd.to_datetime(ts[200:212])),
                                            pred_len=12, T=1.0, top_k=0, top_p=0.9, sample_count=1, verbose=False)
            self.assertEqual([float(x) for x in ref["close"]], a["pred"]["close"])   # same as the original upstream call
            nv = eng.predict({**req, "candles": {**cand, "volume": None}})
            self.assertIsNone(nv["pred"]["volume"])
            p = eng.predict({**req, "paths": 4})
            q = p["paths"]["close_quantiles"]
            self.assertEqual(p["paths"]["n"], 4)
            self.assertTrue(all(q["q10"][i] <= q["q50"][i] <= q["q90"][i] for i in range(12)))
            self.assertIn("NIESKALIBROWANE", p["paths"]["note"])
            for bad in ({**req, "y_t": ts[200:205]}, {**req, "pred_len": 0, "y_t": []}):
                with self.assertRaises(E.EngineError) as cm:
                    eng.predict(bad)
                self.assertEqual(cm.exception.code, "CONFIG")
            st = eng.selftest(reference=True)
            self.assertTrue(st["smoke"]["ok"])
            # 1.37: the upstream regression files belong to Kronos-small; with Kronos-base pinned they are NOT_APPLICABLE
            self.assertIn(st["reference"]["status"], ("PASS", "DIFF_WITHIN_FLOAT_NOISE", "DIFF", "NOT_APPLICABLE"))
            self.assertEqual(st["parity"]["status"], "PASS")                 # bot path == direct official KronosPredictor call
        self.assertIs(socket.socket.connect, real_connect)

    def test_04_incompatible_pair_is_refused(self):
        import kronos_fixture
        from kronos_runtime import engine as E
        d = self.tmp / "incompat"
        kronos_fixture.build(d, small=True, model_override={"s1_bits": 5})
        with self.assertRaises(E.EngineError) as cm:
            E.Engine().load(str(d), device="CPU", threads=1)
        self.assertEqual(cm.exception.code, "INCOMPATIBLE")
        with self.assertRaises(E.EngineError) as cm:
            E.Engine().load(str(self.tmp / "nothing"), device="CPU")
        self.assertEqual(cm.exception.code, "NO_WEIGHTS")

    def test_05_worker_protocol(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT / "backend"), MQ_KRONOS_ALLOW_FIXTURE="1")
        p = subprocess.Popen([sys.executable, "-m", "kronos_runtime.worker"], cwd=str(ROOT / "backend"), env=env, text=True, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=1)

        def ask(obj):
            p.stdin.write((obj if isinstance(obj, str) else json.dumps(obj)) + "\n")
            p.stdin.flush()
            return json.loads(p.stdout.readline())
        try:
            h = ask({"cmd": "hello", "id": "1"})
            self.assertTrue(h["ok"])
            self.assertIn("torch", h["versions"])
            self.assertEqual(ask("{not json")["code"], "BAD_REQUEST")
            self.assertEqual(ask({"cmd": "x", "id": "2"})["code"], "UNKNOWN_COMMAND")
            self.assertEqual(ask({"cmd": "predict", "id": "3", "candles": {}, "y_t": [], "pred_len": 1})["code"], "NOT_LOADED")
            ld = ask({"cmd": "load", "id": "4", "weights_dir": str(self.small), "device": "AUTO", "threads": 1})
            self.assertTrue(ld["ok"], ld)
            ts, cand = self.candles()
            r = ask({"cmd": "predict", "id": "5", "candles": cand, "y_t": ts[200:206], "pred_len": 6, "seed": 1})
            self.assertTrue(r["ok"], r)
            self.assertEqual((r["id"], len(r["pred"]["close"]), r["device"]), ("5", 6, "cpu"))
            self.assertTrue(ask({"cmd": "quit", "id": "6"})["ok"])
            self.assertEqual(p.wait(10), 0)
        finally:
            if p.poll() is None:
                p.kill()

    def test_06_installer_download_checks_source_metadata(self):
        from kronos_runtime import install as I
        from kronos_runtime import lock
        from kronos_runtime import manifest as M

        class Sib:
            def __init__(self, name, path, lfs=True, sha=None):
                self.rfilename, self.size = name, path.stat().st_size
                self.lfs = {"sha256": sha or M.sha256_file(path)} if lfs else None
                self.blob_id = None if lfs else M.git_blob_sha1(path)

        def info_for(rev_ok=True, drop_safetensors=False, bad_sha=False):
            def model_info(repo, revision, files_metadata):
                c = next(x for x in lock.COMPONENTS if x["repo"] == repo)
                d = self.small / lock.component_dir_name(c)
                sib = [Sib("config.json", d / "config.json", lfs=False)]
                if not drop_safetensors:
                    sib.append(Sib("model.safetensors", d / "model.safetensors", sha=("0" * 64 if bad_sha else None)))
                else:
                    sib.append(Sib("pytorch_model.bin", d / "model.safetensors"))
                return type("I", (), {"sha": revision if rev_ok else "f" * 40, "siblings": sib})()
            return model_info

        def fake_download(url, part, size, label, rep, step, retries=4):
            # 1.40.4: direct download <SOURCE>/<repo>/resolve/<revision>/<name> into a short <dir>/.partial/<kind>/<name>.part
            repo_rev, name = url[len(lock.SOURCE) + 1:].rsplit("/", 1)
            repo = repo_rev.split("/resolve/")[0]
            c = next(x for x in lock.COMPONENTS if x["repo"] == repo)
            self.assertEqual(repo_rev.split("/resolve/")[1], c["revision"])
            self.assertEqual(Path(part).parent.name, c["kind"])
            shutil.copy(self.small / lock.component_dir_name(c) / name, part)

        os.environ.pop("HF_HUB_OFFLINE", None)          # the engine (test_03) sets it for its own process; the installer runs separately
        cases = [({}, True, None), ({"bad_sha": True}, False, "CHECKSUM_MISMATCH"), ({"rev_ok": False}, False, "REVISION_MISMATCH"),
                 ({"drop_safetensors": True}, False, "FILE_MISSING")]
        for kw, ok, code in cases:
            dest = self.tmp / f"dl_{code}"
            shutil.rmtree(dest, ignore_errors=True)
            with mock.patch("huggingface_hub.HfApi.model_info", side_effect=lambda *a, **k: info_for(**kw)(a[0] if a else k["repo_id"], k.get("revision"), True)), \
                    mock.patch.object(I, "_fetch", side_effect=fake_download), \
                    mock.patch("builtins.print"):
                rc = I.download(str(dest), None)
            self.assertEqual(rc == 0, ok, (kw, code))
            if ok:
                self.assertTrue(M.verify(dest)["ok"])
                # Windows MAX_PATH: nothing deeper than <dir>\<repo>__<name>@<40-char revision>\<file> is ever created (no .cache tree)
                longest = max(len(str(x.relative_to(dest))) for x in dest.rglob("*"))
                self.assertLess(longest, 120, longest)          # was ~200 with the huggingface_hub .cache tree
                self.assertFalse(list(dest.rglob(".cache")))
                comps = M.read(dest)["components"]
                self.assertEqual({c["revision"] for c in comps}, {lock.MODEL["revision"], lock.TOKENIZER["revision"]})
                self.assertEqual({f["source_check"] for c in comps for f in c["files"]}, {"lfs_sha256", "git_blob_sha1"})
            else:
                self.assertIsNone(M.read(dest))                                  # nothing half-installed is ever marked installed
                self.assertFalse((dest / lock.component_dir_name(lock.MODEL)).exists())
        with mock.patch.dict(os.environ, {"HF_HUB_OFFLINE": "1"}), mock.patch("builtins.print"):
            self.assertEqual(I.download(str(self.tmp / "offline"), None), 1)

    def test_07_timing_at_published_kronos_small_size(self):
        """Random weights at the published size (24.7 M parameters): CPU time of one forecast, lookback 400, horizon 12."""
        import kronos_fixture
        from kronos_runtime import engine as E
        d = self.tmp / "scale"
        out = kronos_fixture.build(d, small=False)
        self.assertEqual(out["params_model"], 24741376)
        eng = E.Engine()
        info = eng.load(str(d), device="CPU", threads=2)
        ts, cand = self.candles(400)
        t0 = time.perf_counter()
        r = eng.predict({"candles": cand, "y_t": ts[400:412], "pred_len": 12, "seed": 3})
        wall = time.perf_counter() - t0
        print(f"\n[timing] Kronos-small size, CPU {info['threads']} wątki: load {info['load_ms']} ms, prognoza H=12 z 400 świec {r['ms']} ms (wall {wall:.2f} s)")
        self.assertLess(wall, 120)


@unittest.skipUnless(HAVE_TORCH and os.environ.get("MQ_KRONOS_WEIGHTS_DIR"), "oficjalne wagi: ustaw MQ_KRONOS_WEIGHTS_DIR (po instalacji)")
class TestOfficialWeights(unittest.TestCase):
    def test_official_pair_loads_parity_and_identity(self):
        from kronos_runtime import engine as E
        from kronos_runtime import manifest as M
        wd = os.environ["MQ_KRONOS_WEIGHTS_DIR"]
        self.assertFalse((M.read(wd) or {}).get("fixture"), "to są wagi testowe, nie oficjalne")
        self.assertTrue(M.verify(wd)["ok"])
        eng = E.Engine()
        info = eng.load(wd, device="CPU", threads=2)
        self.assertEqual(info["params_model"], 102310592)                      # Kronos-base: 102.3 M (upstream model zoo) - 1.37
        self.assertEqual(info["model_name"], "Kronos-base")
        st = eng.selftest(reference=True)
        print("\n[official] " + json.dumps({k: st[k] for k in ("parity", "reference")}))
        self.assertTrue(st["smoke"]["ok"])
        self.assertEqual(st["parity"]["status"], "PASS")
        self.assertEqual(st["reference"]["status"], "NOT_APPLICABLE")       # authors' files are for Kronos-small


if __name__ == "__main__":
    unittest.main()
