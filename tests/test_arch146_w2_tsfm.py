"""1.46 arch, fala 2 - grupa „tsfm” (Chronos-2 / Granite TTM / TiRex-2, TabICLv2 runtime): testy regresji pozycji

I0200 (+I0204)  błąd CUDA w predict: proces zostawał na zepsutym GPU, błąd przy każdej świecy - teraz restart na CPU (tylko po
                potwierdzonym trwałym błędzie kontekstu CUDA); prognoza awaryjna jest WYŁĄCZNIE do wstrzymań (REQUIRED nadal czeka,
                ASSIST może wstrzymać, wiersz kontraktu dla Quant/prezentacji nadal niedostępny jak dziś)
I0201           docstringi tsfm_runtime / service: TiRex-2 aktywny, FinCast tylko jako wycofany
I0205           Granite TTM: zła konfiguracja (context_len ≠ 512, profil, lookback < 512, horyzont > 96) odrzucana przy zapisie,
                istniejący plik -> stan CONFIG bez wywołania procesu (zamiast WARMUP co świecę)
I0207           TiRex2Engine: load / predict / _direct / selftest na podstawionych modułach tirex2 + torch (+ wariant z prawdziwym
                TiRex-2 pod MQ_TIREX2_PYTHON + MQ_TSFM_WEIGHTS_ROOT, bez środowiska SKIP)
I0213           TabICLv2 z prawdziwym tabicl i checkpointem (proces tabicl_runtime.worker; bez .venv_tabicl / wag SKIP)
I0540           tabicl_runtime.engine.Engine: walidacje fit / predict / selftest na podstawionych modułach tabicl + torch
I0834 / I0844   checkpoint Granite poza zakresem dotrenowania (instrument / TF / horyzont): prognoza nie może POTWIERDZIĆ roli
                REQUIRED (ASSIST i wejścia Quant bez zmian - wariant wyłącznie zaostrzający)
I0835           approval_ok: REQUIRED bez raportu dopuszczenia DLA TEGO instrumentu -> nieaktualne (ASSIST bez zmian)
I0836           ścieżka ACTIVE: REQUIRED przy wyłączonym modelu / instrumencie / TF / braku prognozy -> wiersz niedostępny (jak SH)
I0845           werdykt dotrenowania IMPROVED_VS_BASE tylko przy >= 100 oknach testowych (INSUFFICIENT_TEST), aktywacja też to sprawdza
P001            komunikat CHECKSUM rozmiaru podaje rozmiar przypięty (nie 'rozmiar 2 B ≠ 2 B z manifestu')
P002            offline verify() porównuje git blob sha1 plików przypiętych tak (config.json / LICENSE / NOTICE) z lock.py

Procesy modeli w testach usługi to TEST DOUBLE (tests/tsfm_stub_worker.py) - ich liczby nie są prognozami."""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

import _env
from _env import TempData

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kronos_testkit as K  # noqa: E402
from test_tsfm_bot import POSIX, WED_1200, fixture_weights, stub_python  # noqa: E402

BACKEND = _env.ROOT / "backend"


# ======================================================================================================== service fixture (stub workers)
class _Svc(unittest.TestCase):
    """Real TsfmService, stub model processes (tests/tsfm_stub_worker.py), fake MT5 bridge with M5 + M15 bars, isolated data dir."""

    def setUp(self):
        self.td = TempData()
        self.dir = Path(self.td.dir)
        os.environ["MQ_TSFM_ALLOW_FIXTURE"] = "1"
        self.bridge = K.FakeBridge({("XAUUSD-", "M5"): K.make_bars(300, WED_1200, 10), ("XAUUSD-", "M15"): K.make_bars(900, WED_1200, 20)})
        self.cfg = K.FakeCfgStore(K.FakeCfg({"XAUUSD": K.FakeMapping("XAUUSD-")}))
        self.svc = None

    def tearDown(self):
        os.environ.pop("MQ_TSFM_ALLOW_FIXTURE", None)
        if self.svc is not None:
            self.svc.stop()
        self.td.close()

    def make(self, mode="ok", tfs=("M5",), pre: dict | None = None, **models):
        from masterquo.db.database import Database
        from masterquo.tsfm.service import TsfmService
        from masterquo.tsfm.settings import SettingsStore
        p = self.dir / "tsfm" / "settings.json"
        if pre is not None:                                       # a settings file that already exists on disk (written by an older build)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(pre), encoding="utf-8")
        st = SettingsStore(p)
        root = self.dir / "w"
        for m in ("chronos2", "granite_ttm"):
            fixture_weights(root, m)
        py = stub_python(self.dir, mode)
        mc = {m: {"python_path": py, "timeframes": list(tfs), "instruments": ["XAUUSD"], "request_timeout_s": 5.0, **models.get(m, {})}
              for m in ("chronos2", "granite_ttm", "tirex2")}
        st.update({"weights_root": str(root), "models": mc})
        self.svc = TsfmService(self.cfg, self.bridge, Database(self.dir / "t.sqlite"), K.Bus(), K.Log(), clock=lambda: WED_1200, settings=st)
        return self.svc

    def run_queue(self):
        out = []
        while self.svc.queue:
            _k, job = self.svc.queue.popitem(last=False)
            out.append(self.svc.run_job(job))
        return out

    def approve(self, mid: str, path: str, tf: str, use: str = "REQUIRED", inst: str = "XAUUSD") -> str:
        """A positive walk-forward report bound to the CURRENT settings + the role written as set_use would (VALIDATION policy)."""
        from masterquo.tsfm import validation as V
        rep = V._save({"schema": V.SCHEMA, "instrument": inst, "timeframe": tf, "status": "DONE", "bindings": {mid: V.binding(self.svc, mid, inst, tf)},
                       "models": {mid: {"verdict": {"positive": True, "reason": "test"}}}})
        self.svc.settings.update({"models": {mid: {"use": {path: {"use": use, "timeframe": tf, "validation_report": rep["report_id"],
                                                                  "confirmed_at": "2026-11-24T00:00:00Z", "activation_policy": "VALIDATION"}}}}})
        return rep["report_id"]

    @staticmethod
    def ev(rows, side):
        from masterquo.decision.coordinator import evaluate_models
        return evaluate_models(rows, side, required=set(), assist_threshold=0.6, max_age_s=10 ** 9, now=WED_1200 + 60)


# ======================================================================================================== I0201 docstrings
class TestI0201Docstrings(unittest.TestCase):
    def test_active_models_and_fincast_retired(self):
        import importlib
        for name in ("tsfm_runtime", "tsfm_runtime.manifest", "tsfm_runtime.install", "tsfm_runtime.engines", "tsfm_runtime.worker",
                     "masterquo.tsfm.service"):
            doc = importlib.import_module(name).__doc__ or ""
            head = doc.split("\n\n")[0]
            for model in ("Chronos-2", "Granite TTM", "TiRex-2"):
                self.assertIn(model, head, name)
            self.assertNotIn(".venv_fincast", doc, name)
            if "FinCast" in doc:
                self.assertRegex(doc, r"FinCast[^.]{0,60}(wycofany|RETIRED|retired)", name)


# ======================================================================================================== I0205 Granite configuration
class TestI0205GraniteConfigOnSave(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.tsfm.settings import SettingsStore
        self.p = Path(self.td.dir) / "tsfm" / "settings.json"
        self.SS = SettingsStore

    def tearDown(self):
        self.td.close()

    def test_bad_granite_config_is_refused(self):
        st = self.SS(self.p)
        for patch, why in (({"models": {"granite_ttm": {"context_len": 256}}}, "512"),
                           ({"models": {"granite_ttm": {"profile": "CLOSE_OHLCV_PAST_V1"}}}, "CLOSE_V1"),
                           ({"lookback": 300}, "lookback"),
                           ({"horizon_bars": {"M5": 120}}, "96")):
            with self.assertRaises(ValueError) as cm:                       # before: accepted -> WARMUP / PROFILE_UNSUPPORTED at every bar
                st.update(patch)
            self.assertIn(why, str(cm.exception), patch)
            self.assertIn("GRANITE_CONFIG", str(cm.exception))
        s = st.get()
        self.assertEqual((s.models["granite_ttm"].context_len, s.lookback), (512, 560))           # nothing written
        st.update({"models": {"chronos2": {"context_len": 1024, "profile": "CLOSE_OHLCV_PAST_V1"}}})   # other models: no such limit
        st.update({"horizon_bars": {"H1": 120}})                                                     # TF Granite does not compute

    def test_disabled_granite_is_not_checked_until_enabled(self):
        st = self.SS(self.p)
        st.update({"models": {"granite_ttm": {"enabled": False}}})
        st.update({"models": {"granite_ttm": {"context_len": 256}}})
        with self.assertRaises(ValueError):
            st.update({"models": {"granite_ttm": {"enabled": True}}})

    def test_existing_bad_file_loads_and_unrelated_changes_pass(self):
        self.p.parent.mkdir(parents=True, exist_ok=True)
        self.p.write_text(json.dumps({"models": {"granite_ttm": {"context_len": 256}}}), encoding="utf-8")
        st = self.SS(self.p)
        self.assertIsNone(st.load_error)                                   # the file contract is unchanged on read
        self.assertEqual(st.get().models["granite_ttm"].context_len, 256)
        st.update({"models": {"chronos2": {"enabled": False}}})              # an unrelated change is not blocked by the old value
        with self.assertRaises(ValueError):
            st.update({"models": {"granite_ttm": {"context_len": 300}}})   # another wrong value: refused
        st.update({"models": {"granite_ttm": {"context_len": 512}}})       # repair: accepted


@unittest.skipUnless(POSIX, "stub worker uses a POSIX shell wrapper")
class TestI0205GraniteConfigState(_Svc):
    def test_config_state_and_no_worker_call(self):
        from masterquo.tsfm import predictions as TP
        svc = self.make(pre={"models": {"granite_ttm": {"context_len": 256}}})
        svc.tick()
        self.assertEqual(set(svc.queue), {("chronos2", "XAUUSD", "M5")})    # before: granite queued -> WARMUP from the model at every bar
        ms = svc.mstate[("granite_ttm", "XAUUSD", "M5")]
        self.assertEqual(ms["state"], "CONFIG")
        self.assertIn("512", ms["reason"])
        w = svc.workers["granite_ttm"]
        self.assertIsNone(w.proc)                                          # the model process is never asked
        self.assertEqual((w.state["status"], w.state["code"]), ("CONFIG", "CONFIG"))
        self.run_queue()
        row = next(r for r in TP.contract_predictions(svc, "XAUUSD") if r["model_id"] == "tsfm:granite_ttm")
        self.assertEqual((row["state"], row["result"]), ("ERROR", None))   # the same class as today's model error: decisions unchanged
        self.assertIn("512", row["unavailable_reason"])
        svc.settings.update({"models": {"granite_ttm": {"context_len": 512}}})
        self.assertTrue(svc.refresh("granite_ttm", "XAUUSD", "M5")["ok"])     # repaired: queued again (state back to IDLE)
        self.assertIn(("granite_ttm", "XAUUSD", "M5"), svc.queue)
        self.assertEqual(w.state["status"], "IDLE")


# ======================================================================================================== I0207 TiRex2Engine
class _FT:
    """Fake torch tensor (numpy inside)."""

    def __init__(self, arr):
        import numpy as np
        self.arr = np.asarray(arr)

    def unsqueeze(self, d):
        return _FT(self.arr[None] if d == 0 else self.arr[..., None])

    def reshape(self, *s):
        return _FT(self.arr.reshape(*s))

    def double(self):
        return _FT(self.arr.astype("float64"))

    def cpu(self):
        return self

    def numpy(self):
        return self.arr


def fake_torch(cuda: bool = False):
    import numpy as np
    t = types.ModuleType("torch")
    t._dynamo = types.SimpleNamespace(config=types.SimpleNamespace(disable=False))
    t.float32 = "float32"
    t._threads = [1]
    t.set_num_threads = lambda n: t._threads.__setitem__(0, int(n))
    t.get_num_threads = lambda: t._threads[0]
    t.cuda = types.SimpleNamespace(is_available=lambda: cuda)
    t.tensor = lambda data, dtype=None: _FT(np.asarray(data, dtype=np.float32 if dtype == "float32" else None))
    t.inference_mode = contextlib.nullcontext
    return t


LEVELS = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]


def fake_tirex2(nan: bool = False):
    import numpy as np
    m = types.ModuleType("tirex2")
    m.calls = []

    class Inner:
        def eval(self):
            return self

        def parameters(self):
            return [types.SimpleNamespace(numel=lambda: 7)]

    class Model:
        model = Inner()

        def _quantile_levels(self):
            return list(LEVELS)

        def forecast(self, series, prediction_length, output_type="numpy", batch_size=None):
            out = []
            for ts in series:
                last = float(np.asarray(ts.target.arr, dtype=np.float64).reshape(-1)[-1])
                a = np.asarray([[last + 0.1 * (h + 1) + (q - 0.5) * 2.0 for h in range(prediction_length)] for q in LEVELS])
                if nan:
                    a[0, 0] = float("nan")
                out.append(a if output_type == "numpy" else _FT(a))
            return out

    def load_model(path, device="cpu", compile=False, cuda_graphs=None):  # noqa: A002 - the official keyword
        m.calls.append({"path": path, "device": device, "compile": compile, "cuda_graphs": cuda_graphs})
        return Model()
    m.load_model = load_model
    m.TimeseriesType = lambda target, past_covariates=None, future_covariates=None: types.SimpleNamespace(target=target)
    return m


class TestI0207TiRex2Engine(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.root = Path(self.td.dir) / "w"
        fixture_weights(self.root, "tirex2")
        self.env = mock.patch.dict(os.environ, {"MQ_TSFM_ALLOW_FIXTURE": "1"})
        self.env.start()
        os.environ.pop("PMW_TIREX_COMPILE", None)
        os.environ.pop("TORCHDYNAMO_DISABLE", None)

    def tearDown(self):
        self.env.stop()
        self.td.close()

    def engine(self, nan=False):
        from tsfm_runtime import engines as E
        self.torch, self.tx = fake_torch(), fake_tirex2(nan)
        mods = mock.patch.dict(sys.modules, {"torch": self.torch, "tirex2": self.tx})
        mods.start()
        self.addCleanup(mods.stop)
        e = E.make("tirex2")
        self.info = e.load(str(self.root), device="AUTO", threads=3, verify_files=False)
        return e, E

    def req(self, n=600, **kw):
        return {"close": [2000.0 + 0.5 * i for i in range(n)], "pred_len": 12, "context_len": 512, "profile": "CLOSE_V1",
                "quantiles": [0.1, 0.5, 0.9], "freq_tf": "M5", **kw}

    def test_load_plain_inference_on_cpu(self):
        e, _E = self.engine()
        self.assertEqual(self.tx.calls, [{"path": str(_E.M.model_dir(self.root, "tirex2")), "device": "cpu", "compile": False, "cuda_graphs": None}])
        self.assertEqual(os.environ.get("TORCHDYNAMO_DISABLE"), "1")              # 1.42.1: no TorchInductor without PMW_TIREX_COMPILE
        self.assertTrue(self.torch._dynamo.config.disable)
        self.assertEqual((self.info["device"], self.info["threads"], self.info["trained_quantiles"]), ("cpu", 3, LEVELS))
        self.assertEqual(self.info["model_context_length"], 2048)

    def test_compile_override(self):
        os.environ["PMW_TIREX_COMPILE"] = "1"
        self.engine()
        self.assertNotIn("TORCHDYNAMO_DISABLE", os.environ)
        self.assertFalse(self.torch._dynamo.config.disable)

    def test_predict_median_and_quantile_blocks(self):
        e, _E = self.engine()
        r = e.predict(self.req())
        self.assertEqual((r["point_kind"], len(r["point"]), r["context_bars"]), ("median", 12, 512))
        self.assertEqual(r["point"], r["median"])
        self.assertEqual(r["point"], r["quantiles"]["values"]["0.5"])
        self.assertEqual(sorted(r["quantiles"]["values"]), ["0.1", "0.5", "0.9"])
        self.assertEqual(r["quantiles"]["crossing_steps"], 0)
        last = 2000.0 + 0.5 * 599                                                  # only the last 512 closes; the forecast follows the last one
        self.assertAlmostEqual(r["point"][0], last + 0.1, places=3)
        self.assertAlmostEqual(r["quantiles"]["values"]["0.9"][0] - r["point"][0], 0.8, places=6)

    def test_errors(self):
        e, E = self.engine()
        bad = self.req()
        bad["close"][10] = float("nan")
        for req, code in ((self.req(quantiles=[0.15]), "CONFIG"), (bad, "NON_FINITE_INPUT"), (self.req(n=20, context_len=20), "CONFIG"),
                          (self.req(pred_len=0), "CONFIG"), (self.req(context_len=4096), "CONFIG")):
            with self.assertRaises(E.EngineError) as cm:
                e.predict(req)
            self.assertEqual(cm.exception.code, code, req.get("quantiles"))
        e2, E = self.engine(nan=True)
        with self.assertRaises(E.EngineError) as cm:
            e2.predict(self.req())
        self.assertEqual(cm.exception.code, "NON_FINITE")
        with self.assertRaises(E.EngineError) as cm:
            E.make("tirex2").predict(self.req())
        self.assertEqual(cm.exception.code, "NOT_LOADED")

    def test_direct_parity_and_selftest(self):
        e, _E = self.engine()
        close = self.req()["close"][-512:]
        got = e.predict(self.req())
        ref = e._direct(close, 12, [0.1, 0.5, 0.9])
        self.assertEqual(got["point"], ref["point"])
        self.assertEqual([got["quantiles"]["values"][k] for k in ("0.1", "0.5", "0.9")], ref["quantiles"])
        st = e.selftest()
        self.assertTrue(st["smoke"]["ok"])
        self.assertEqual(st["parity"]["status"], "PASS")


def _real_python(env_key: str, venv: str) -> str | None:
    for x in (os.environ.get(env_key), str(_env.ROOT / venv / "bin" / "python"), str(_env.ROOT / venv / "Scripts" / "python.exe")):
        if x and Path(x).is_file():
            return x
    return None


def _run_worker(argv: list[str], reqs: list[dict], timeout: float) -> dict:
    """The real JSON-lines worker in its own environment: requests (with ids) -> {id: response}."""
    env = dict(os.environ, PYTHONPATH=str(BACKEND), PYTHONIOENCODING="utf-8", HF_HUB_OFFLINE="1", OMP_NUM_THREADS="2")
    env.pop("MQ_TSFM_ALLOW_FIXTURE", None)
    data = "".join(json.dumps({**r, "id": str(i)}) + "\n" for i, r in enumerate(reqs)) + json.dumps({"cmd": "quit", "id": "q"}) + "\n"
    p = subprocess.run(argv, input=data, capture_output=True, text=True, encoding="utf-8", cwd=str(BACKEND), env=env, timeout=timeout)
    out = {}
    for ln in p.stdout.splitlines():
        try:
            m = json.loads(ln)
        except ValueError:
            continue
        out[m.get("id")] = m
    return out


TIREX_PY = _real_python("MQ_TIREX2_PYTHON", ".venv_tirex2")
WROOT = os.environ.get("MQ_TSFM_WEIGHTS_ROOT")


def _tirex_installed() -> bool:
    if not (TIREX_PY and WROOT):
        return False
    from tsfm_runtime import manifest as M
    return bool(M.summary(WROOT, "tirex2")["installed"])


@unittest.skipUnless(_tirex_installed(), "TiRex-2: MQ_TIREX2_PYTHON (.venv_tirex2) + MQ_TSFM_WEIGHTS_ROOT z zainstalowanymi wagami")
class TestI0207TiRex2Real(unittest.TestCase):
    def test_real_worker_load_predict_selftest(self):
        close = [2650.0 + 3.0 * ((i % 40) - 20) / 20 + 0.01 * i for i in range(600)]
        r = _run_worker([TIREX_PY, "-m", "tsfm_runtime.worker", "--model", "tirex2"],
                        [{"cmd": "hello"}, {"cmd": "load", "weights_root": WROOT, "device": "CPU", "threads": 2, "verify_files": True},
                         {"cmd": "predict", "close": close, "pred_len": 12, "context_len": 512, "profile": "CLOSE_V1", "quantiles": [0.1, 0.5, 0.9],
                          "freq_tf": "M5"},
                         {"cmd": "predict", "close": close, "pred_len": 12, "context_len": 512, "quantiles": [0.25]},
                         {"cmd": "selftest"}], timeout=900)
        self.assertTrue(r["1"]["ok"], r["1"])
        from tsfm_runtime import lock as L
        self.assertEqual((r["1"]["info"]["params"], r["1"]["info"]["revision"]), (L.model("tirex2")["params_measured"], L.model("tirex2")["revision"]))
        p = r["2"]
        self.assertTrue(p["ok"], p)
        self.assertEqual((p["point_kind"], len(p["point"])), ("median", 12))
        self.assertEqual(p["point"], p["quantiles"]["values"]["0.5"])
        self.assertTrue(all(a <= b <= c for a, b, c in zip(*(p["quantiles"]["values"][k] for k in ("0.1", "0.5", "0.9")))))
        self.assertEqual((r["3"]["ok"], r["3"]["code"]), (False, "CONFIG"))             # 0.25 is not a TiRex-2 level - never interpolated
        self.assertTrue(r["4"]["ok"], r["4"])
        self.assertTrue(r["4"]["smoke"]["ok"])
        self.assertEqual(r["4"]["parity"]["status"], "PASS", r["4"]["parity"])


# ======================================================================================================== I0213 real TabICLv2
TABICL_PY = _real_python("MQ_TABICL_PYTHON", ".venv_tabicl")


def _tabicl_root() -> str | None:
    if not TABICL_PY:
        return None
    from tabicl_runtime import install as TI
    for root in (WROOT, str(_env.ROOT / "data" / "tsfm" / "models")):
        if root and TI.verify(root)["ok"]:
            return root
    return None


TABICL_ROOT = _tabicl_root()


@unittest.skipUnless(TABICL_ROOT, "TabICLv2: MQ_TABICL_PYTHON / .venv_tabicl + zweryfikowany checkpoint (MQ_TSFM_WEIGHTS_ROOT)")
class TestI0213TabiclReal(unittest.TestCase):
    def test_real_fit_predict_selftest(self):
        import numpy as np
        from tabicl_runtime import lock as TL
        rng = np.random.default_rng(7)
        X = rng.normal(size=(160, 5))
        y = (X[:, 0] - 0.5 * X[:, 2] + rng.normal(0, 0.5, 160) > 0).astype(int)
        r = _run_worker([TABICL_PY, "-m", "tabicl_runtime.worker"],
                        [{"cmd": "hello"}, {"cmd": "load", "weights_root": TABICL_ROOT, "threads": 2, "verify_files": True},
                         {"cmd": "fit", "context_id": "C1", "X": X[:128].tolist(), "y": y[:128].tolist(), "names": [f"f{i}" for i in range(5)]},
                         {"cmd": "predict", "context_id": "C1", "X": X[128:].tolist()},
                         {"cmd": "predict", "context_id": "C1", "X": X[128:, :4].tolist()},
                         {"cmd": "fit", "context_id": "C2", "X": X[:50].tolist(), "y": [0] * 50},
                         {"cmd": "selftest"}], timeout=900)
        self.assertTrue(r["1"]["ok"], r["1"])
        self.assertEqual(r["1"]["info"]["fingerprint"], TL.fingerprint())
        self.assertEqual((r["2"]["n"], r["2"]["dim"], r["2"]["classes"]), (128, 5, [0, 1]))
        p = r["3"]
        self.assertTrue(p["ok"], p)
        self.assertEqual(len(p["p_event_raw"]), 32)
        self.assertTrue(all(0.0 <= v <= 1.0 for v in p["p_event_raw"]))
        hits = sum(int((v > 0.5) == bool(t)) for v, t in zip(p["p_event_raw"], y[128:]))
        self.assertGreater(hits, 16)                                                # a real in-context classifier, not a constant
        self.assertEqual((r["4"]["ok"], r["4"]["code"]), (False, "SHAPE"))                 # another feature schema than the context
        self.assertEqual((r["5"]["ok"], r["5"]["code"]), (False, "SINGLE_CLASS"))
        self.assertTrue(r["6"]["ok"], r["6"])
        self.assertTrue(r["6"]["ok"] and r["6"]["single_class_refused"])
        self.assertEqual(r["6"]["parity"]["status"], "PASS", r["6"]["parity"])


# ======================================================================================================== I0540 tabicl_runtime.engine
def fake_tabicl(nan=False, positive=1):
    import numpy as np
    m = types.ModuleType("tabicl")
    m.made = []

    class TabICLClassifier:
        def __init__(self, **kw):
            m.made.append(kw)

        def fit(self, X, y):
            self.classes_ = np.unique(y)
            return self

        def predict_proba(self, X):
            p = 1.0 / (1.0 + np.exp(-np.asarray(X)[:, 0]))
            if nan:
                p = p * float("nan")
            cols = [p if c == positive else 1.0 - p for c in self.classes_]
            return np.stack(cols, axis=1)
    m.TabICLClassifier = TabICLClassifier
    return m


class TestI0540TabiclEngine(unittest.TestCase):
    def engine(self, **kw):
        from tabicl_runtime import engine as TE
        tb = fake_tabicl(**kw)
        mods = mock.patch.dict(sys.modules, {"torch": fake_torch(), "tabicl": tb})
        mods.start()
        self.addCleanup(mods.stop)
        e = TE.Engine()
        info = e.load("/nonexistent-weights", threads=3, verify_files=False)
        return e, TE, tb, info

    def test_load_and_official_settings(self):
        from tabicl_runtime import lock as TL
        e, TE, tb, info = self.engine()
        self.assertEqual((info["fingerprint"], info["threads"], info["device"]), (TL.fingerprint(), 3, "cpu"))
        self.assertTrue(str(e.ckpt).endswith(TL.PIN["checkpoint"]))
        e.fit("C", [[0.0, 1.0], [1.0, 0.0], [2.0, 1.0]], [0, 1, 1])
        kw = tb.made[-1]
        self.assertEqual((kw["allow_auto_download"], kw["device"], kw["n_jobs"], kw["checkpoint_version"]), (False, "cpu", 1, TL.PIN["checkpoint"]))
        self.assertEqual(kw["n_estimators"], TL.PIN["inference"]["n_estimators"])

    def test_fit_and_predict_validation(self):
        e, TE, _tb, _ = self.engine()
        X = [[float(i), float(i % 3)] for i in range(10)]
        y = [i % 2 for i in range(10)]
        for args, code in ((([1.0, 2.0], [0, 1]), "SHAPE"), ((X, y[:5]), "SHAPE"), (([[1.0, float("inf")], [2.0, 1.0]], [0, 1]), "NON_FINITE_INPUT"),
                           ((X, [1] * 10), "SINGLE_CLASS"), (([], []), "SHAPE")):
            with self.assertRaises(TE.EngineError) as cm:
                e.fit("C", *args)
            self.assertEqual(cm.exception.code, code, args)
        r = e.fit("C", X, y, names=["a", "b"])
        self.assertEqual((r["n"], r["dim"], r["classes"]), (10, 2, [0, 1]))
        p = e.predict("C", [[0.0, 0.0], [3.0, 1.0]])
        self.assertAlmostEqual(p["p_event_raw"][0], 0.5)
        self.assertGreater(p["p_event_raw"][1], 0.9)
        with self.assertRaises(TE.EngineError) as cm:
            e.predict("OTHER", [[0.0, 0.0]])
        self.assertEqual(cm.exception.code, "NO_CONTEXT")
        with self.assertRaises(TE.EngineError) as cm:
            e.predict("C", [[0.0, 0.0, 1.0]])
        self.assertEqual(cm.exception.code, "SHAPE")
        e.fit("D", X, [0, 2] * 5)                                                   # classes without the positive class 1
        with self.assertRaises(TE.EngineError) as cm:
            e.predict("D", [[0.0, 0.0]])
        self.assertEqual(cm.exception.code, "NO_POSITIVE_CLASS")
        self.assertNotIn("C", e.contexts)                                            # one context in RAM (the newest)
        e2 = TE.Engine()
        with self.assertRaises(TE.EngineError) as cm:
            e2.fit("C", X, y)
        self.assertEqual(cm.exception.code, "NOT_LOADED")

    def test_non_finite_output_and_positive_column(self):
        e, TE, _tb, _ = self.engine(nan=True)
        e.fit("C", [[0.0], [1.0]], [0, 1])
        with self.assertRaises(TE.EngineError) as cm:
            e.predict("C", [[0.5]])
        self.assertEqual(cm.exception.code, "NON_FINITE")
        e, TE, _tb, _ = self.engine(positive=0)                                      # proba columns follow classes_: column of class 1 is used
        e.fit("C", [[0.0], [1.0]], [0, 1])
        self.assertLess(e.predict("C", [[3.0]])["p_event_raw"][0], 0.1)

    def test_selftest_deterministic_stub(self):
        e, _TE, _tb, _ = self.engine()
        st = e.selftest()
        self.assertTrue(st["ok"], st)
        self.assertEqual((st["parity"]["status"], st["single_class_refused"]), ("PASS", True))
        self.assertNotIn("_selftest", e.contexts)


# ======================================================================================================== I0845 verdict minimum sample
class TestI0845VerdictMinSample(unittest.TestCase):
    def test_verdict(self):
        import inspect

        from tsfm_runtime import granite_finetune as GF
        self.assertEqual(GF.verdict(3, {"mae_h": 1.0}, {"mae_h": 1.1}, 26), "INSUFFICIENT_TEST")   # before: IMPROVED_VS_BASE on 26 windows
        self.assertEqual(GF.verdict(3, {"mae_h": 1.0}, {"mae_h": 1.1}, 150), "IMPROVED_VS_BASE")
        self.assertEqual(GF.verdict(0, {"mae_h": 1.0}, {"mae_h": 1.1}, 150), "NOT_BETTER_THAN_BASE")
        self.assertEqual(GF.verdict(2, {"mae_h": 1.2}, {"mae_h": 1.1}, 150), "NOT_BETTER_THAN_BASE")
        self.assertEqual(GF.verdict(2, {"mae_h": 1.2}, {"mae_h": 1.1}, 10), "NOT_BETTER_THAN_BASE")
        self.assertEqual(GF.MIN_TEST_WINDOWS, 100)
        self.assertIn("verdict(best_epoch", inspect.getsource(GF.main))

    def test_activation_refuses_a_small_test_sample(self):
        import hashlib

        from masterquo.tsfm import granite_train as G
        from masterquo.tsfm.settings import SettingsStore
        from tsfm_runtime import lock as L
        td = TempData()
        try:
            class W:
                def kill(self):
                    pass

            class Log:
                def info(self, *a):
                    pass
            svc = types.SimpleNamespace(settings=SettingsStore(Path(td.dir) / "tsfm" / "settings.json"), workers={"granite_ttm": W()}, applog=Log())
            for rid, metrics, train in (("GTR-SMALL01", {"verdict": "IMPROVED_VS_BASE", "test_windows": 26}, {"horizon": 12}),
                                        ("GTR-NOCNT01", {"verdict": "IMPROVED_VS_BASE"}, {"horizon": 12}),
                                        ("GTR-OLDWIN1", {"verdict": "IMPROVED_VS_BASE"}, {"horizon": 12, "windows": {"test": 140}}),
                                        ("GTR-BIG0001", {"verdict": "IMPROVED_VS_BASE", "test_windows": 150}, {"horizon": 12})):
                d = G.finetune_dir() / rid
                d.mkdir(parents=True, exist_ok=True)
                files = []
                for name in ("config.json", "model.safetensors"):
                    (d / name).write_bytes(name.encode())
                    files.append({"name": name, "sha256": hashlib.sha256(name.encode()).hexdigest()})
                (d / "granite_finetune.json").write_text(json.dumps({"run_id": rid, "base_fingerprint": L.fingerprint("granite_ttm"), "files": files,
                                                                     "data": {"timeframe": "M5"}, "train": train, "metrics": metrics}), encoding="utf-8")
            r = G.activate(svc, "GTR-SMALL01")
            self.assertFalse(r["ok"])                                            # before: activated on 26 test windows
            self.assertIn("26", r["reason"])
            self.assertFalse(G.activate(svc, "GTR-NOCNT01")["ok"])
            self.assertEqual(svc.settings.get().models["granite_ttm"].checkpoint, "BASE")
            self.assertTrue(G.activate(svc, "GTR-OLDWIN1")["ok"])               # count from train.windows (manifests of 1.40-1.45)
            self.assertTrue(G.activate(svc, "GTR-BIG0001")["ok"])
            self.assertEqual(svc.settings.get().models["granite_ttm"].checkpoint, "GTR-BIG0001")
        finally:
            td.close()


# ======================================================================================================== P001 / P002 manifest verify
class _Pin(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.root = Path(self.td.dir) / "w"
        self.src = Path(self.td.dir) / "src"
        self.src.mkdir()
        from tsfm_runtime import lock as L
        from tsfm_runtime import manifest as M
        self.L, self.M = L, M
        self._orig = json.loads(json.dumps(L.MODELS["chronos2"]))
        (self.src / "config.json").write_bytes(b'{"a": 1}')
        (self.src / "model.safetensors").write_bytes(b"\1" * 1000)
        L.MODELS["chronos2"]["files"] = [{"name": "config.json", "size": 8, "git_blob_sha1": M.git_blob_sha1(self.src / "config.json")},
                                         {"name": "model.safetensors", "size": 1000, "sha256": M.sha256_file(self.src / "model.safetensors")}]
        from tsfm_runtime import install as I
        self.assertTrue(I.download("chronos2", str(self.root), from_dir=str(self.src))["ok"])

    def tearDown(self):
        self.L.MODELS["chronos2"] = self._orig
        self.td.close()


class TestP001SizeMessage(_Pin):
    def test_message_names_the_pinned_size(self):
        self.L.MODELS["chronos2"]["files"][0]["size"] = 9                      # the pin differs, the manifest matches the file
        with self.assertRaises(self.M.ManifestError) as cm:
            self.M.verify(self.root, "chronos2")
        self.assertEqual(cm.exception.code, "CHECKSUM")
        self.assertNotIn("8 B ≠ 8 B", cm.exception.detail)                    # before: 'rozmiar 8 B ≠ 8 B z manifestu'
        self.assertIn("9 B", cm.exception.detail)
        self.assertIn("przypięt", cm.exception.detail)

    def test_manifest_size_message_unchanged(self):
        f = self.M.model_dir(self.root, "chronos2") / "config.json"
        f.write_bytes(b'{"a": 12}')
        with self.assertRaises(self.M.ManifestError) as cm:
            self.M.verify(self.root, "chronos2")
        self.assertIn("9 B ≠ 8 B z manifestu", cm.exception.detail)


class TestP002GitBlobPin(_Pin):
    def test_git_blob_pinned_file_checked_against_the_pin(self):
        self.assertTrue(self.M.verify(self.root, "chronos2")["ok"])
        f = self.M.model_dir(self.root, "chronos2") / "config.json"
        f.write_bytes(b'{"b": 2}')                                              # same size, other content
        man = self.M.read(self.root, "chronos2")
        for x in man["files"]:
            if x["name"] == "config.json":
                x["sha256"] = self.M.sha256_file(f)                             # manifest rewritten to match (hand edit / other copy)
        self.M.write(self.root, "chronos2", man)
        with self.assertRaises(self.M.ManifestError) as cm:                    # before: passed (sha256 compared with the manifest only)
            self.M.verify(self.root, "chronos2")
        self.assertEqual(cm.exception.code, "CHECKSUM")
        self.assertIn("git blob", cm.exception.detail)


if __name__ == "__main__":
    unittest.main()
