"""1.46 audit fixes - regression tests. Each test fails on 1.45.0 (evidence in docs/AUDYT_1_45.md) and passes after the fix."""
from __future__ import annotations

import os
import unittest

import _env  # noqa: F401


class TestBodyNum(unittest.TestCase):
    def test_wrong_types_are_400_not_500(self):
        from fastapi import HTTPException

        from masterquo.api.app import body_num
        self.assertEqual(body_num({"n": "7"}, "n", 1, int), 7)
        self.assertEqual(body_num({}, "n", 1, int), 1)
        self.assertIsNone(body_num({"v": None}, "v", None, float))
        for bad in ("abc", [1], {"a": 1}, True, "nan", "inf"):
            with self.assertRaises(HTTPException) as cm:
                body_num({"n": bad}, "n", 1, float if bad in ("nan", "inf") else int, 0, 10)
            self.assertEqual(cm.exception.status_code, 400, bad)
        with self.assertRaises(HTTPException):
            body_num({"n": 11}, "n", 1, int, 0, 10)


class TestMarketZonesEmptySeries(unittest.TestCase):
    def test_as_of_before_data_is_no_data_not_index_error(self):
        from masterquo.zones import market as MZ
        from masterquo.zones.series import Series
        s = Series.from_bars([], "M5", 1_700_000_000.0)
        r = MZ.compute_tf(s, "XAUUSD", 0.01, None)                     # 1.45: IndexError in strategies.indicators.true_range
        self.assertEqual((r["state"], r["bars"], r["atr"]), ("NO_DATA", 0, None))
        out = MZ.compute({"M5": s}, instrument="XAUUSD", symbol="XAUUSD-", tick=0.01, as_of=1_700_000_000.0)
        self.assertIn("M5", str(out))


class TestBootstrapProbe(unittest.TestCase):
    """1.45.0: Bootstrap.verify_all raised KeyError 'tabicl' (tsfm_runtime.lock has no such model) -> the bootstrap thread died on every start,
    the components after it were never verified and no heavy runtime was ever queued."""

    def test_verify_all_survives_and_tabicl_uses_its_own_env(self):
        import pathlib
        import tempfile
        import types

        from masterquo.bootstrap import COMPONENTS, Bootstrap
        from masterquo.tsfm.service import TsfmService
        from masterquo.tsfm.settings import SettingsStore
        td = pathlib.Path(tempfile.mkdtemp())
        st = SettingsStore(td / "s.json")

        class Svc:
            settings = st
            jobs: dict = {}

            def env_status(self, mid):
                return TsfmService.env_status(self, mid)

            def weights_root(self):
                return td / "w"
        b = Bootstrap(types.SimpleNamespace(tsfm=Svc(), kronos=None, demo=False), state_file=td / "b.json")
        out = b.verify_all()
        states = {c["id"]: c["state"] for c in out["components"]}
        self.assertEqual(len(states), len(COMPONENTS))
        self.assertEqual(states["tsfm_tabicl"], "NOT_INSTALLED")          # not a crash, not FAILED: the env / weights are simply absent
        self.assertEqual(states["kronos_model"], "NOT_INSTALLED")        # the component AFTER tabicl is verified too
        self.assertTrue(all(v != "PENDING" for v in states.values()))

    def test_a_raising_probe_is_recorded_not_fatal(self):
        import pathlib
        import tempfile

        from masterquo.bootstrap import Bootstrap

        def boom():
            raise KeyError("x")
        td = pathlib.Path(tempfile.mkdtemp())
        b = Bootstrap(state_file=td / "b.json", probes={"tsfm_chronos2": boom})
        states = {c["id"]: c for c in b.verify_all()["components"]}
        self.assertEqual(states["tsfm_chronos2"]["state"], "FAILED")
        self.assertIn("PROBE_ERROR", states["tsfm_chronos2"]["detail"])


class TestWallsStoreRestart(unittest.TestCase):
    """1.45.0: the fingerprint held a tuple; after the JSON round trip (first freeze after a restart) it was a list -> never equal -> every restart
    created version N+1 with a new snapshot_id for the same input (and S12 got a new setup identity for the same market event)."""

    def test_same_input_after_restart_keeps_snapshot_id(self):
        from _env import TempData

        from masterquo.analysis.walls import WallsStore
        from masterquo.db.database import Database
        td = TempData()
        try:
            db = Database()
            snap = {"status": "OK", "symbol": "XAUUSD-", "anchor_time": "2026-11-20T00:00:00Z", "source_type": "HV_PROXY", "sigma_annual": 0.18,
                    "obs_id": None, "band_sigma": 0.15, "available_at": "2026-11-20T00:05:00Z",
                    "walls": [{"k": 1.0, "side": "UPPER", "level": 2410.0}, {"k": 2.0, "side": "UPPER", "level": 2430.0},
                              {"k": 1.0, "side": "LOWER", "level": 2390.0}]}
            a = WallsStore(db).freeze(dict(snap, walls=[dict(w) for w in snap["walls"]]))
            b = WallsStore(db).freeze(dict(snap, walls=[dict(w) for w in snap["walls"]]))     # new store = application restart
            self.assertEqual((b["snapshot_id"], b["snapshot_version"]), (a["snapshot_id"], 1))
            self.assertEqual(db.one("SELECT COUNT(*) n FROM walls_snapshots")["n"], 1)
            c = WallsStore(db).freeze(dict(snap, sigma_annual=0.25, walls=[dict(w) for w in snap["walls"]]))   # a real change -> next version
            self.assertEqual(c["snapshot_version"], 2)
        finally:
            td.close()


class TestApiInputValidation(unittest.TestCase):
    """Smoke test 1.45.0: these requests answered 500 (Internal Server Error) - now 400 with a reason."""

    @classmethod
    def setUpClass(cls):
        os.environ["PMW_BOOTSTRAP"] = "0"
        from _demo_server import Server
        cls.S = Server
        Server.start_server()

    @classmethod
    def tearDownClass(cls):
        cls.S.stop_server()

    def test_bad_values_answer_400(self):
        c = self.S.call
        self.assertEqual(c("/api/v1/lab/memory?tf=M5&t=garbage")[0], 400)
        code, _ = c("/api/v1/tlg/profile", {"username": "Walidacja", "class_id": "THE_ROOKIE", "difficulty": "EASY"})
        self.assertIn(code, (200, 409))
        self.assertEqual(c("/api/v1/tlg/sim", {"symbol": "XAUUSD", "count": "abc"})[0], 400)
        self.assertEqual(c("/api/v1/tlg/sim/1/step", {"n": "x"})[0], 400)
        self.assertEqual(c("/api/v1/asge/run", {"timeframe": "H1", "children": "x"})[0], 400)
        self.assertEqual(c("/api/v1/asge/run", {"timeframe": "H1", "children": 10_000})[0], 400)
        self.assertEqual(c("/api/v1/indicators/calculate", {"method": "SMA", "period": 5, "count": "x"})[0], 400)
        self.assertEqual(c("/api/v1/indicators/calculate", {"method": "SMA", "period": 5, "bars": [1, 2]})[0], 400)
        self.assertEqual(c("/api/v1/kronos/validate", {"max_origins": "x"})[0], 400)
        self.assertEqual(c("/api/v1/models/foundation/validate", {"max_origins": "x"})[0], 400)
        self.assertEqual(c("/api/v1/quant/tabicl/reconstruct", {"days": "x"})[0], 400)
        code, body = c("/api/v1/market-zones/as-of?as_of=2020-01-01T00:00:00Z")
        self.assertEqual(code, 200, body)                              # was 503 "IndexError: list index out of range"

    def test_foreign_page_cannot_log_the_panel_out(self):
        """1.45.0: every GET / created a session and at >200 ALL sessions were cleared - any web page could log the panel out (no STOP)."""
        import urllib.request
        from _demo_server import BASE
        code, before = self.S.call("/api/v1/session")
        self.assertTrue(before.get("csrf"))
        for _ in range(250):                                   # no cookies, as an <img src> / no-cors fetch from another site
            urllib.request.urlopen(urllib.request.Request(BASE + "/", headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "no-cors"}),
                                   timeout=10).read(0)
        code, after = self.S.call("/api/v1/session")
        self.assertEqual(after.get("csrf"), before["csrf"])


if __name__ == "__main__":
    unittest.main()


class TestAgentGateAndBudget(unittest.TestCase):
    """1.45.0: (a) a USER_QUESTION run with the setup id replaced the AI gate assessment of a CONFIRMED setup (WAIT answer -> DISAGREE veto) and
    marked a running SETUP_CONFIRMED assessment as superseded; (b) a model id without an exact price (e.g. a dated id returned by the API)
    stored est_cost_usd = NULL and the daily budget counted it as 0."""

    def setUp(self):
        import test_agent as TA
        self.TA = TA
        self.t = TA.TestAgent("test_veto_policy")
        self.t.setUp()
        self.agent = self.t.agent

    def tearDown(self):
        self.t.tearDown()

    def _handle(self, trigger, ans, question=None):
        import asyncio
        import json
        TA = self.TA
        client = TA.ScriptedClient([TA.msg([TA.text(json.dumps(ans))], "end_turn")])
        self.agent._client_get = lambda: client
        self.agent.last_auto_run = self.agent.last_user_run = 0
        self.agent.loop = None
        req = {"trigger": trigger, "snapshot_id": "SNP-1", "setup_id": "MQS-1", "setup_state": "CONFIRMED", "question": question, "key": trigger}
        asyncio.run(self.agent._handle(req))

    def test_user_question_does_not_replace_gate_assessment(self):
        TA = self.TA
        self._handle("SETUP_CONFIRMED", TA.answer())                                   # SELL for a SHORT setup -> PASS
        self.assertEqual(self.agent.by_setup["MQS-1"]["record"]["proposed_action"], "SELL")
        self._handle("USER_QUESTION", TA.answer(proposed_action="WAIT", answer_pl="Ryzyka newsów: ..."), question="Jakie są ryzyka?")
        self.assertEqual(self.agent.by_setup["MQS-1"]["record"]["proposed_action"], "SELL")   # the question's WAIT is not a veto
        self.assertEqual(self.agent.last_result["status_note"], "ANSWER_ONLY_NOT_A_GATE_ASSESSMENT")

    def test_unknown_or_dated_model_price_is_not_zero(self):
        usage = {"input_tokens": 1_000_000, "output_tokens": 0}
        self.assertEqual(self.agent._cost("claude-opus-5-5-20261101", usage), 4.0)             # dated id -> base model price
        self.assertEqual(self.agent._cost("some-unknown-model", usage, requested="claude-opus-5-5"), 4.0)
        self.assertEqual(self.agent._cost("some-unknown-model", usage), 10.0)                  # no price at all -> upper bound, never 0 / None


class TestQuoteBandUnscored(unittest.TestCase):
    """1.45.0: an UNSCORED_GAP row (no 'error') in QuoteEngine.matured made every later _band() raise KeyError -> quote forecasts frozen."""

    def test_band_ignores_unscored_rows(self):
        from masterquo.lab import quotes as Q
        eng = Q.QuoteEngine("X", 0.01, 0.01, {"calib_min": 2})
        eng.matured = [{"side": "BID", "scale": 20, "se_model": 0.5, "status": "UNSCORED_GAP"},
                       {"side": "BID", "scale": 20, "se_model": 0.5, "status": "SCORED", "error": 0.25},
                       {"side": "BID", "scale": 20, "se_model": 0.5, "status": "SCORED", "error": -0.5}]
        b = eng._band("BID", 20, 0.5)
        self.assertEqual((b["status"], b["n"]), ("EMPIRICAL", 2))
        eng.matured = eng.matured[:1]
        self.assertEqual(eng._band("BID", 20, 0.5)["status"], "MODEL_BAND_UNCALIBRATED")


class TestSetupDatasetNoLookahead(unittest.TestCase):
    """1.45.0: build_setup_dataset mapped a setup to the M1 that OPENS at the decision time (decision = CLOSE of the trigger bar) - features
    and windows contained the first minute after the decision (the entry bar)."""

    def test_setup_maps_to_trigger_bar(self):
        from masterquo.lab import structure_task as ST
        t0 = 1_795_000_020
        t0 -= t0 % 60
        tpos = {t0 + 60 * k: k for k in range(5)}
        trigger = 2                                                     # bar opening at t0+120 closes at t0+180 = decision time
        sig = __import__("datetime").datetime.fromtimestamp(t0 + 60 * trigger + 60, __import__("datetime").timezone.utc).isoformat().replace("+00:00", "Z")
        self.assertEqual(ST.setup_bar_index(tpos, sig), trigger)


class TestNoPickleCheckpointLoads(unittest.TestCase):
    """1.45.0: sdformer_runtime infer.py / train.py loaded last.pt (also from an imported ZIP) with torch.load(weights_only=False) - a crafted
    pickle executes code in the process that holds the MT5 session and the secrets. Every torch.load in the runtimes must be weights_only=True."""

    def test_every_torch_load_is_weights_only(self):
        import ast
        from pathlib import Path
        root = Path(_env.ROOT) / "backend"
        bad = []
        for p in [x for x in root.rglob("*.py") if "vendor" not in x.parts and "__pycache__" not in x.parts]:
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for n in ast.walk(tree):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "load" and \
                        isinstance(n.func.value, ast.Name) and n.func.value.id == "torch":
                    kw = {k.arg: k.value for k in n.keywords}
                    v = kw.get("weights_only")
                    if not (isinstance(v, ast.Constant) and v.value is True):
                        bad.append(f"{p.relative_to(root)}:{n.lineno}")
        self.assertEqual(bad, [])


class TestResearchContexts(unittest.TestCase):
    """1.45.0: (a) after an asset switch the old main research context kept learning from the NEW symbol's candles; (b) the automatic SDformerFlow
    bootstrap restarted every H1 bar after the user CANCELLED it (and after a DONE run that left no active checkpoint)."""

    def _svc(self, d):
        import types
        from pathlib import Path

        from masterquo.research import service as RS
        bars = [{"open_utc": f"2026-11-20T{h:02d}:{m:02d}:00Z", "o": 1.0, "h": 1.0, "l": 1.0, "c": 1.0, "tv": 1} for h in range(10) for m in range(0, 60, 5)]

        class Br:
            cfg = types.SimpleNamespace(symbol="EURUSD-")

            def bars(self, tf, include_forming=False):
                return bars
        rt = types.SimpleNamespace(demo=True, bridge=Br(), sh=types.SimpleNamespace(instrument=lambda: "XAUUSD"))
        return RS.ResearchModulesService(rt, data_dir=Path(d)), rt

    def test_old_context_gets_no_bars_of_the_new_symbol(self):
        import tempfile
        svc, rt = self._svc(tempfile.mkdtemp())
        old = svc.ensure_main_context()
        self.assertGreater(len(old.bars_fn("M5", 1500)), 0)
        rt.bridge.cfg.symbol = "XAUUSD-"                                     # asset switch
        new = svc.ensure_main_context()
        self.assertNotEqual(old.key, new.key)
        self.assertEqual(old.bars_fn("M5", 1500), [])                        # the EURUSD context waits instead of reading XAUUSD
        self.assertGreater(len(new.bars_fn("M5", 1500)), 0)

    def test_cancelled_bootstrap_is_not_restarted(self):
        import tempfile
        import time
        from unittest import mock
        svc, _ = self._svc(tempfile.mkdtemp())
        c = svc.ensure_main_context()
        h1 = [{"t": 1_700_000_000 + 3600 * i, "o": 1, "h": 1, "l": 1, "c": 1, "tv": 1} for i in range(700)]
        started = []
        with mock.patch("masterquo.research.service.torch_python", return_value="/x/python"), \
                mock.patch.object(svc, "start_training", side_effect=lambda *a, **k: started.append(1) or {"ok": True}):
            svc.jobs["sdformer_bootstrap"] = {"state": "CANCELLED", "finished_at": time.time()}
            svc._sdformer(c, h1)
            self.assertEqual((started, c.sdf["state"]), ([], "MISSING"))
            svc.jobs["sdformer_bootstrap"] = {"state": "DONE", "finished_at": time.time()}     # done, but no active checkpoint
            svc._sdformer(c, h1)
            self.assertEqual((started, c.sdf["state"]), ([], "ERROR"))


class TestStudioHostGuard(unittest.TestCase):
    """1.45.0: the Studio API (127.0.0.1:8780) had no Host / Origin check - a DNS-rebinding page could change settings (bot_data_dir), start
    jobs and transfer packages. Now: Host must be 127.0.0.1 / localhost; a browser write needs a loopback Origin."""

    def _call(self, app, method, path, headers):
        import asyncio
        import json
        sent = []
        body = json.dumps({}).encode() if method == "POST" else b""

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(msg):
            sent.append(msg)
        hdrs = [(k.lower().encode(), v.encode()) for k, v in headers.items()] + ([(b"content-type", b"application/json")] if body else [])
        scope = {"type": "http", "method": method, "path": path, "raw_path": path.encode(), "query_string": b"", "headers": hdrs,
                 "scheme": "http", "server": ("127.0.0.1", 8780), "client": ("127.0.0.1", 5555), "http_version": "1.1", "root_path": ""}
        asyncio.run(app(scope, receive, send))
        return next(m["status"] for m in sent if m["type"] == "http.response.start")

    def test_rebinding_host_and_foreign_origin_rejected(self):
        from _env import TempData
        td = TempData()
        os.environ["MQ_STUDIO_DATA_DIR"] = td.dir
        try:
            from masterquo.studio.app import create_app
            app = create_app(start_worker=False)
            self.assertEqual(self._call(app, "GET", "/api/studio/health", {"host": "127.0.0.1:8780"}), 200)
            self.assertEqual(self._call(app, "GET", "/api/studio/health", {"host": "localhost:8780"}), 200)
            self.assertEqual(self._call(app, "GET", "/api/studio/health", {"host": "attacker.example:8780"}), 421)
            self.assertEqual(self._call(app, "POST", "/api/studio/settings", {"host": "attacker.example"}), 421)
            self.assertEqual(self._call(app, "POST", "/api/studio/settings", {"host": "127.0.0.1:8780", "origin": "http://evil.example"}), 403)
        finally:
            os.environ.pop("MQ_STUDIO_DATA_DIR", None)
            td.close()


class TestSettingsNumberField(unittest.TestCase):
    """1.45.0: Settings number fields (risk %, costs, sigma ...) swallowed the decimal separator: typing 0.5 stored 5 (frontend Dialogs.tsx)."""

    def test_fraction_typed_key_by_key(self):
        import shutil
        import subprocess
        if not shutil.which("node"):
            self.skipTest("node not installed")
        r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", str(_env.ROOT / "tests" / "js" / "num_text.test.mjs")],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertIn("num_text OK", r.stdout)


class TestSessionEviction(unittest.TestCase):
    def test_least_recently_used_is_evicted_never_all(self):
        from masterquo.api.security import MAX_SESSIONS, LocalSecurity
        sec = LocalSecurity(8765)
        mine, _ = sec.new_session()
        for i in range(3 * MAX_SESSIONS):
            sec.new_session()
            if i % 50 == 0:
                self.assertIsNotNone(sec.csrf_for(mine))            # the panel polls -> stays most recently used
        self.assertIsNotNone(sec.csrf_for(mine))
        self.assertEqual(len(sec.sessions), MAX_SESSIONS)


class TestTrainingImportTraversal(unittest.TestCase):
    """1.45.0: POST /api/v1/training/import -> sh/tpmodel.import_run used run_id / instrument from the package as path parts ('../' wrote files
    outside <data>/sh/models)."""

    def _zip(self, inst, run_id):
        import hashlib
        import io
        import json
        import zipfile
        npz = b"not-really-npz"
        run = {"run_id": run_id, "sha256": hashlib.sha256(npz).hexdigest()}
        files = {f"models/sh_tp_model/{inst}/SCALPING/registry.json": json.dumps({"runs": [run]}).encode(),
                 f"models/sh_tp_model/{inst}/SCALPING/{run_id}.npz": npz}
        man = {"instrument": inst, "files": [{"path": k, "sha256": hashlib.sha256(v).hexdigest()} for k, v in files.items()]}
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("MANIFEST.json", json.dumps(man))
            for k, v in files.items():
                z.writestr(k, v)
        return buf.getvalue()

    def test_package_paths_are_validated(self):
        from pathlib import Path

        from _env import TempData

        from masterquo.training import panel
        td = TempData()
        try:
            rep = panel.import_package(self._zip("XAUUSD", "../../../../evil_run"))
            self.assertEqual(rep["imported"], [])
            self.assertTrue(any("NIEDOZWOLONY_RUN_ID" in x for x in rep["skipped"]))
            self.assertEqual([p for p in Path(td.dir).rglob("evil_run*")], [])
            with self.assertRaises(ValueError):
                panel.import_package(self._zip("../../../tmp/x", "run1"))
        finally:
            td.close()


class TestShRMultipleInitialRisk(unittest.TestCase):
    """1.45.0: sh/service.cycle_result divided the result by |entry - CURRENT sl|; after BE (TP2) the SL sits at entry(+costs) -> R ~7x too big
    or None. R must use the plan's initial (frozen) stop."""

    def test_r_from_initial_stop_after_be(self):
        import types

        from masterquo.sh.lifecycle import Leg, Position
        from masterquo.sh.service import SHService
        pos = Position("P1", "BUY", 2000.0, 1.0, 2000.3, [Leg("TP1", 2004.0, 1.0, status="DONE", fill_price=2004.0, fill_volume=1.0)])
        pos.realized = [{"volume": 1.0, "move": 4.0}]
        pos.remaining = 0.0
        row = {"plan": {"setup": {"sl": 1998.0}, "instrument_profile": {"commission_per_lot_side": 0.0}}, "plan_id": "P1"}
        spec = types.SimpleNamespace(money_per_price=lambda v: 100.0)
        res = SHService.cycle_result(types.SimpleNamespace(store=None), row, pos, spec)
        self.assertEqual(res["r_multiple"], 2.0)                    # +4.00 move / 2.00 initial risk (not / 0.30 after BE)
