"""Etap 4, faza 2, krok A (Apollo23 1.46, docs/arch146/ETAP2_PROJEKT.md §1, §3, §4 "Composition root", §5, §6 pkt 7): runtime.py jest
JEDYNYM composition rootem. Obiekty, które api/app.create_app i api/wf32_routes.register tworzyły same (LocalSecurity, rejestr procesów
treningu `train_procs` + blokada, rejestr zadań NSS `nss_jobs`, PresetStore, IndicatorEngine TASK 007 + blokada), buduje
runtime.compose_api_services (Runtime.compose_api, wołane jako pierwsze przez create_app); API czyta je z rt.api_services / rt.security
pod tymi samymi nazwami lokalnymi - treść handlerów bez zmian. Usługi wf32 (ledger, trials, journal, TLG, Hyperliquid / Universe,
AccountCenter) były już w Runtime (I0088: rt.wf32_services), Bootstrap (I0092: rt.bootstrap), rejestr procesów potomnych (I0100: rt.procs).

Dowody neutralności:
1. TestRuntimeSnapshotVsBase - sonda (ten plik z --probe, osobny proces) na Runtime(demo=True) offline: atrybuty Runtime (kolejność +
   typy) po __init__ / create_app / start(), nazwy i kolejność wątków startowanych z wątku głównego w każdej fazie, tryb, start_failures
   - porównane z migawką zamrożoną NA BAZIE 505f75a (tests/data/arch146_e4_runtime_base.json). Jedyna dozwolona różnica: nowy atrybut
   `api_services` (None po __init__, ApiServices po create_app). Polecenie migawki:
     git archive 505f75a backend config | tar -x -C <tmp>
     PMW_BOOTSTRAP=0 python tests/test_arch146_e4_composition_root.py --probe <tmp>/probe.json --root <tmp>
     PMW_BOOTSTRAP=0 python tests/test_arch146_e4_composition_root.py --hashes <tmp>/hashes.json --root <tmp>
   (plik danych = {"probe": ..., "hashes": ...}).
2. TestLiveUntouched - LIVE nietknięty: execution/gateway.py bajt w bajt (sha256 pliku), źródło ModeManager, ExecutionConfig
   (start_mode / live_autobind) i każdej funkcji ścieżki zleceń MT5 (PositionManager, ManualPad.execute, SHExecutor) identyczne z bazą;
   martwy warunek D1 (`if not demo and mt5_factory is None:`) w Runtime.__init__ identyczny (ast.dump); cała klasa Runtime (ast.dump, bez
   komentarzy) = baza po usunięciu WYŁĄCZNIE nowej metody compose_api i przypisania self.api_services.
3. TestApiReadsRuntimeServices - handlery API trzymają DOKŁADNIE obiekty z rt.api_services (domknięcia), nowy komplet na każde
   create_app (jak dotąd), runtime-atrapa (MagicMock, tools/routes_inventory) dostaje komplet z tej samej funkcji, wf32_routes.register
   bez create_app buduje własny silnik jak wcześniej; konstruktory bez wątków / plików.
Jednorazowe porównanie odpowiedzi API (każda trasa GET bez parametrów ścieżki, baza z git archive vs worktree) - raport w scratchpadzie
(wynik w opisie commita). Nic tu nie łączy się z MT5, nie wysyła zleceń ani nie zapisuje do data/ (katalog tymczasowy).
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

PORT = 18803
BASE_FILE = Path(__file__).resolve().parent / "data" / "arch146_e4_runtime_base.json"
NEW_ATTRS = {"api_services"}

# source pinned byte for byte (LIVE: start_mode, live_autobind, ModeManager, MT5 order paths)
PINNED_FILES = ("backend/masterquo/execution/gateway.py",)
PINNED_DEFS = {
    "backend/masterquo/execution/modes.py": ("ModeManager",),
    "backend/masterquo/config.py": ("ExecutionConfig",),
    "backend/masterquo/execution/manager.py": ("PositionManager._partial_close", "PositionManager._sync_broker_tp",
                                               "PositionManager._close_mt5", "PositionManager._move_be", "PositionManager.close_positions"),
    "backend/masterquo/execution/manual.py": ("ManualPad.execute",),
    "backend/masterquo/sh/executor.py": ("SHExecutor._mt5_open", "SHExecutor._mt5_action"),
    "backend/masterquo/runtime.py": ("real_mt5_factory",),
}


# ------------------------------------------------------------------------------------------------------------------ probe / hashes
def _norm_thread(name: str) -> str:
    return re.sub(r"\d+", "N", name)


def _tname(v) -> str:
    t = type(v)
    return f"{t.__module__}.{t.__qualname__}"


def probe(root: Path, out: Path) -> dict:
    """Runtime(demo=True) of the tree at `root` in a temporary data folder (offline: news off, no clock reference, baskets offline,
    bootstrap off): attributes after __init__ / create_app / start(), threads started FROM THE MAIN THREAD per phase (order of
    Thread.start - deterministic; threads started by service threads are not), mode, start failures; then stop()."""
    sys.path.insert(0, str(root / "backend"))
    td = tempfile.mkdtemp(prefix="e4a_rt_")
    os.environ.update(MASTERQUO_DATA_DIR=td, PMW_BOOTSTRAP="0", MQ_FAKE_MARKET_ALWAYS_OPEN="1", MQ_BASKETS_OFFLINE="1")
    Path(td, "config.json").write_text(json.dumps({"server": {"port": PORT, "open_browser": False}, "news": {"enabled": False},
                                                   "clock": {"reference_url": None}, "first_run_completed": True}), encoding="utf-8")
    import masterquo
    if not Path(masterquo.__file__).resolve().is_relative_to(root.resolve()):
        raise RuntimeError(f"masterquo from {masterquo.__file__}, not from {root}")
    started: list = []
    phase = {"p": "import"}
    orig = threading.Thread.start

    def _start(self):
        if threading.current_thread() is threading.main_thread():
            started.append([phase["p"], _norm_thread(self.name)])
        return orig(self)

    threading.Thread.start = _start
    res: dict = {}
    try:
        from masterquo.api.app import create_app
        from masterquo.runtime import Runtime
        phase["p"] = "init"
        rt = Runtime(demo=True)
        res["attrs_init"] = [[k, _tname(v)] for k, v in vars(rt).items()]
        res["mode"] = rt.modes.mode
        res["start_mode_applied"] = getattr(rt.modes, "start_mode_applied", None)
        phase["p"] = "app"
        app = create_app(rt, PORT)
        res["attrs_app"] = [[k, _tname(v)] for k, v in vars(rt).items()]
        res["security"] = _tname(rt.security)
        res["app_state"] = sorted(getattr(app.state, "_state", {}))
        res["app_state_wf32_is_rt_wf32"] = app.state.wf32 is rt.wf32
        res["routes"] = len(app.routes)
        phase["p"] = "start"
        rt.start()
        res["attrs_start"] = [[k, _tname(v)] for k, v in vars(rt).items()]
        res["start_failures"] = [f["part"] for f in rt.start_failures]
        res["mode_after_start"] = rt.modes.mode
        phase["p"] = "stop"
        before = {t.ident for t in threading.enumerate()}
        rt.stop()
        end = time.monotonic() + 30
        while time.monotonic() < end and [t for t in threading.enumerate() if t.ident not in before and not t.daemon and t.is_alive()]:
            time.sleep(0.2)
        res["threads_started_main"] = started
    finally:
        threading.Thread.start = orig
        import shutil
        shutil.rmtree(td, ignore_errors=True)
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    return res


def _defs(tree: ast.AST) -> dict:
    out: dict = {}

    def walk(node, pre=""):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out[pre + ch.name] = ch
                walk(ch, pre + ch.name + ".")
    walk(tree)
    return out


def _sha(s: str | bytes) -> str:
    return hashlib.sha256(s.encode("utf-8") if isinstance(s, str) else s).hexdigest()


def _runtime_class_without_composition_root_additions(tree: ast.AST) -> ast.ClassDef:
    """The Runtime class minus exactly what Etap 4 krok A added: the method compose_api and `self.api_services = ...` in __init__
    (comments are not in the AST). On the base tree nothing is removed."""
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Runtime")
    cls.body = [n for n in cls.body if not (isinstance(n, ast.FunctionDef) and n.name == "compose_api")]
    init = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "__init__")

    def added(st) -> bool:
        tgt = st.target if isinstance(st, ast.AnnAssign) else (st.targets[0] if isinstance(st, ast.Assign) and len(st.targets) == 1 else None)
        return isinstance(tgt, ast.Attribute) and tgt.attr == "api_services" and isinstance(tgt.value, ast.Name) and tgt.value.id == "self"
    init.body = [st for st in init.body if not added(st)]
    return cls


def _d1_node(tree: ast.AST) -> ast.If:
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Runtime")
    init = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    hits = [n for n in ast.walk(init) if isinstance(n, ast.If) and "apply_start_mode" in ast.dump(n)]
    if len(hits) != 1:
        raise AssertionError(f"D1: {len(hits)} warunków z apply_start_mode w Runtime.__init__")
    return hits[0]


def hashes(root: Path) -> dict:
    out: dict = {"files": {}, "defs": {}}
    for rel in PINNED_FILES:
        out["files"][rel] = _sha((root / rel).read_bytes())
    for rel, names in PINNED_DEFS.items():
        src = (root / rel).read_text(encoding="utf-8")
        d = _defs(ast.parse(src))
        for n in names:
            out["defs"][f"{rel}:{n}"] = _sha(ast.get_source_segment(src, d[n], padded=True))
    rsrc = (root / "backend/masterquo/runtime.py").read_text(encoding="utf-8")
    d1 = _d1_node(ast.parse(rsrc))
    out["d1_ast"] = ast.dump(d1)
    out["d1_source_line"] = rsrc.splitlines()[d1.lineno - 1].strip()
    out["runtime_class_ast_sha256"] = _sha(ast.dump(_runtime_class_without_composition_root_additions(ast.parse(rsrc))))
    out["runtime_methods"] = sorted(n.name for n in next(c for c in ast.parse(rsrc).body if isinstance(c, ast.ClassDef)
                                                         and c.name == "Runtime").body if isinstance(n, ast.FunctionDef))
    return out


if __name__ == "__main__" and ("--probe" in sys.argv or "--hashes" in sys.argv):
    _root = Path(sys.argv[sys.argv.index("--root") + 1]) if "--root" in sys.argv else Path(__file__).resolve().parents[1]
    if "--probe" in sys.argv:
        probe(_root, Path(sys.argv[sys.argv.index("--probe") + 1]))
    else:
        Path(sys.argv[sys.argv.index("--hashes") + 1]).write_text(json.dumps(hashes(_root), indent=1), encoding="utf-8")
    sys.stdout.flush()
    os._exit(0)                                # service threads of the probed runtime are daemons - never wait for them

import types
import unittest
from unittest import mock

import _env


def _base() -> dict:
    return json.loads(BASE_FILE.read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------------------------------------------------ 1. probe
class TestRuntimeSnapshotVsBase(unittest.TestCase):
    """Runtime(demo=True) start w osobnym procesie: atrybuty, typy, kolejność, wątki - jak na bazie (poza nowym api_services)."""

    @classmethod
    def setUpClass(cls):
        cls.base = _base()["probe"]
        with tempfile.TemporaryDirectory(prefix="e4a_probe_") as d:
            out = Path(d) / "probe.json"
            env = dict(os.environ, PMW_BOOTSTRAP="0", PYTHONPATH="")
            env.pop("MASTERQUO_DATA_DIR", None)
            r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--probe", str(out), "--root", str(_env.ROOT)],
                               env=env, cwd=d, capture_output=True, text=True, timeout=600, check=False)
            if not out.exists():
                raise AssertionError(f"sonda nie zapisała wyniku (kod {r.returncode}): {r.stderr[-2000:]}")
            cls.cur = json.loads(out.read_text(encoding="utf-8"))

    def _without_new(self, attrs):
        return [a for a in attrs if a[0] not in NEW_ATTRS]

    def test_attributes_order_and_types_after_init_are_the_base_ones_plus_api_services(self):
        self.assertEqual(self._without_new(self.cur["attrs_init"]), self.base["attrs_init"])
        names = [a[0] for a in self.cur["attrs_init"]]
        self.assertEqual(names[names.index("security") + 1], "api_services")           # declared next to rt.security
        self.assertIn(["api_services", "builtins.NoneType"], self.cur["attrs_init"])
        self.assertEqual({a[0] for a in self.cur["attrs_init"]} - {a[0] for a in self.base["attrs_init"]}, NEW_ATTRS)

    def test_attributes_after_create_app_and_start(self):
        for ph in ("attrs_app", "attrs_start"):
            self.assertEqual(self._without_new(self.cur[ph]), self.base[ph], ph)
            self.assertIn(["api_services", "masterquo.runtime.ApiServices"], self.cur[ph], ph)
        self.assertEqual(self.cur["security"], self.base["security"])                   # masterquo.api.security.LocalSecurity

    def test_threads_started_per_phase_names_and_order(self):
        self.assertEqual(self.cur["threads_started_main"], self.base["threads_started_main"])
        phases = {p for p, _ in self.cur["threads_started_main"]}
        self.assertNotIn("init", phases)                                                # no thread in __init__ (I0103)
        self.assertNotIn("app", phases)                                                 # no thread while the routes are registered (I0092)
        self.assertGreater(len(self.cur["threads_started_main"]), 30)

    def test_mode_start_failures_app_state(self):
        for k in ("mode", "start_mode_applied", "mode_after_start", "start_failures", "app_state", "app_state_wf32_is_rt_wf32", "routes"):
            self.assertEqual(self.cur[k], self.base[k], k)
        self.assertEqual(self.cur["mode"], "PAPER")
        self.assertIsNone(self.cur["start_mode_applied"])                              # D1: apply_start_mode never ran


# ------------------------------------------------------------------------------------------------------------------ 2. LIVE / D1
class TestLiveUntouched(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = _base()["hashes"]
        cls.cur = hashes(_env.ROOT)

    def test_gateway_byte_for_byte(self):
        self.assertEqual(self.cur["files"], self.base["files"])

    def test_mode_manager_start_mode_live_autobind_and_mt5_order_paths(self):
        self.assertEqual(set(self.cur["defs"]), set(self.base["defs"]))
        for k, v in self.base["defs"].items():
            self.assertEqual(self.cur["defs"][k], v, k)

    def test_d1_dead_condition_exactly_as_in_base(self):
        self.assertEqual(self.cur["d1_ast"], self.base["d1_ast"])
        self.assertEqual(self.cur["d1_source_line"], self.base["d1_source_line"])
        self.assertTrue(self.cur["d1_source_line"].startswith("if not demo and mt5_factory is None:"))

    def test_runtime_class_is_the_base_plus_compose_api_only(self):
        self.assertEqual(self.cur["runtime_class_ast_sha256"], self.base["runtime_class_ast_sha256"])
        self.assertEqual(sorted(set(self.cur["runtime_methods"]) - set(self.base["runtime_methods"])), ["compose_api"])
        self.assertEqual(set(self.base["runtime_methods"]) - set(self.cur["runtime_methods"]), set())


# ------------------------------------------------------------------------------------------------- 3. the API reads rt.api_services
def _endpoints(app) -> dict:
    return {(r.path, m): r.endpoint for r in app.routes if hasattr(r, "endpoint") for m in (getattr(r, "methods", None) or ())}


def _closure(fn, name):
    import inspect
    return inspect.getclosurevars(fn).nonlocals[name]


class TestApiReadsRuntimeServices(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = _env.TempData()
        cls._boot = os.environ.get("PMW_BOOTSTRAP")
        os.environ["PMW_BOOTSTRAP"] = "0"
        from masterquo.runtime import Runtime
        cls.rt = Runtime(demo=True)

    @classmethod
    def tearDownClass(cls):
        cls.rt._stop.set()
        if cls._boot is None:
            os.environ.pop("PMW_BOOTSTRAP", None)
        else:
            os.environ["PMW_BOOTSTRAP"] = cls._boot
        cls.td.close()

    def _check_app_uses(self, app, svc):
        ep = _endpoints(app)
        self.assertIs(_closure(ep[("/api/v1/session", "GET")], "sec"), svc.security)
        self.assertIs(_closure(ep[("/api/v1/presets/strategy", "GET")], "preset_store"), svc.presets)
        train_start = _closure(ep[("/api/v1/indicator-context/train", "POST")], "_train_start")
        self.assertIs(_closure(train_start, "train_procs"), svc.train_procs)
        self.assertIs(_closure(train_start, "train_procs_lock"), svc.train_procs_lock)
        nss_fns = [fn for (p, m), fn in ep.items() if p.startswith("/api/v1/lab/neural/") and m == "POST"
                   and "_nss_job" in __import__("inspect").getclosurevars(fn).nonlocals]
        self.assertTrue(nss_fns)
        for fn in nss_fns:
            self.assertIs(_closure(_closure(fn, "_nss_job"), "nss_jobs"), svc.nss_jobs)
        calc = ep[("/api/v1/indicators/calculate", "POST")]
        self.assertIs(_closure(calc, "_ind"), svc.indicator_engine)
        self.assertIs(_closure(calc, "_ind_lock"), svc.indicator_lock)
        self.assertIs(_closure(ep[("/api/v1/indicators/diagnostics", "GET")], "_ind"), svc.indicator_engine)

    def test_runtime_builds_the_api_services_and_the_handlers_use_them(self):
        from masterquo.api import app as A
        from masterquo.api.security import LocalSecurity
        from masterquo.indicators.smoothing import IndicatorEngine
        from masterquo.presets import PresetStore
        from masterquo.runtime import ApiServices
        app = A.create_app(self.rt, PORT)
        svc = self.rt.api_services
        self.assertIsInstance(svc, ApiServices)
        self.assertIs(self.rt.security, svc.security)                                    # __main__ writes rt.security.shutdown_token
        self.assertIsInstance(svc.security, LocalSecurity)
        self.assertEqual(svc.security.port, PORT)
        self.assertIsInstance(svc.presets, PresetStore)
        self.assertEqual(svc.presets.path, Path(self.td.dir).resolve() / "presets" / "strategy.json")
        self.assertIsInstance(svc.indicator_engine, IndicatorEngine)
        self.assertEqual((svc.train_procs, svc.nss_jobs), ({}, {}))
        self._check_app_uses(app, svc)

    def test_a_new_set_per_create_app_as_before(self):
        from masterquo.api import app as A
        a1 = A.create_app(self.rt, PORT)
        s1 = self.rt.api_services
        a2 = A.create_app(self.rt, PORT)
        s2 = self.rt.api_services
        for f in ("security", "train_procs", "train_procs_lock", "nss_jobs", "presets", "indicator_engine", "indicator_lock"):
            self.assertIsNot(getattr(s1, f), getattr(s2, f), f)
        self.assertNotEqual(s1.security.shutdown_token, s2.security.shutdown_token)
        self._check_app_uses(a1, s1)                                                     # the first app keeps its own objects
        self._check_app_uses(a2, s2)
        self.assertIs(self.rt.security, s2.security)

    def test_stub_runtime_gets_a_set_from_the_same_function(self):
        from masterquo import runtime as R
        from masterquo.api import app as A
        rt = mock.MagicMock()
        rt.license.locked = False
        rt.cfg.get.return_value.assets.active = "XAUUSD"
        with mock.patch.object(R, "compose_api_services", wraps=R.compose_api_services) as comp:
            app = A.create_app(rt, PORT)
        comp.assert_called_once_with(PORT)
        self.assertIsInstance(rt.api_services, R.ApiServices)
        self.assertIs(rt.security, rt.api_services.security)
        self._check_app_uses(app, rt.api_services)
        rt.compose_api.assert_not_called()                                               # a MagicMock is never asked to compose

    def test_wf32_register_without_create_app_builds_its_own_engine(self):
        from fastapi import FastAPI
        from masterquo.api import wf32_routes
        from masterquo.indicators.smoothing import IndicatorEngine
        app = FastAPI()
        wf32_routes.register(app, types.SimpleNamespace(bridge=None, baskets=None, cfg=None))
        calc = _endpoints(app)[("/api/v1/indicators/calculate", "POST")]
        self.assertIsInstance(_closure(calc, "_ind"), IndicatorEngine)
        self.assertIsInstance(_closure(calc, "_ind_lock"), type(threading.Lock()))
        m = mock.MagicMock()                                                             # attribute of a mock is not ApiServices
        app2 = FastAPI()
        wf32_routes.register(app2, m)
        self.assertIsInstance(_closure(_endpoints(app2)[("/api/v1/indicators/calculate", "POST")], "_ind"), IndicatorEngine)

    def test_construction_starts_no_thread_and_touches_no_file(self):
        from masterquo import runtime as R
        before = {t.ident for t in threading.enumerate()}
        files = sorted(p.relative_to(self.td.dir) for p in Path(self.td.dir).rglob("*"))
        with mock.patch("pathlib.Path.read_text", side_effect=AssertionError("odczyt pliku przy konstrukcji")), \
                mock.patch("pathlib.Path.write_text", side_effect=AssertionError("zapis pliku przy konstrukcji")):
            svc = R.compose_api_services(PORT)
        self.assertEqual([t.name for t in threading.enumerate() if t.ident not in before], [])
        self.assertEqual(sorted(p.relative_to(self.td.dir) for p in Path(self.td.dir).rglob("*")), files)
        self.assertEqual(svc.indicator_engine._st, {})
        self.assertEqual(svc.security.sessions, {})

    def test_existing_contracts_kept(self):
        from masterquo.api import app as A
        self.assertTrue(hasattr(A, "LocalSecurity"))                                     # old name importable from api.app
        src = (_env.ROOT / "backend" / "masterquo" / "api" / "app.py").read_text(encoding="utf-8")
        routes = _env.api_sources()                                                      # Etap 4 krok B: handlers in api/routes/*.py
        self.assertIn('REGISTRY.register(f"api:{kind}", train_procs[kind], "training")', routes)   # I0100 pin (training studio test)
        create = src[src.index("def create_app(rt, port: int) -> FastAPI:"):src.index("\ndef _api_services(")]
        create += routes[len(src):]                                                      # + api/schemas.py and every route block
        for old in ("LocalSecurity(port)", "PresetStore(", "IndicatorEngine(", "train_procs: dict = {}", "nss_jobs: dict = {}"):
            self.assertNotIn(old, create, old)                                           # create_app builds none of them itself
        wf = (_env.ROOT / "backend" / "masterquo" / "api" / "wf32_routes.py").read_text(encoding="utf-8")
        reg = wf[wf.index("def register(app, rt) -> None:"):wf.index("\ndef _indicator_engine(")]
        self.assertNotIn("IndicatorEngine(", reg)


if __name__ == "__main__":
    unittest.main()
