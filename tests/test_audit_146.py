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
        # chunk_12#4 (1.46): a naive anchor time was read in the local zone; with the strict anchor check it gave a 500 - now 400
        self.assertEqual(c("/api/v1/indicators/anchors", {"timeframe": "M5", "source_time": "2026-01-05T10:00:00"})[0], 400)
        self.assertEqual(c("/api/v1/indicators/anchors", {"timeframe": "M5", "source_time": 1e20})[0], 400)

    def test_wf32_routes_validate_input(self):
        """Chunk 04 (SREDNI): wrong types in v3.2 routes answered 500; loot scores > 100 granted LEGENDARY; non-ASCII CSRF was a 500."""
        c = self.S.call
        self.assertEqual(c("/api/v1/models/pt/evaluate", {"forecasts": ["a"] * 40, "outcomes": [1] * 40})[0], 400)
        self.assertEqual(c("/api/v1/models/dt-ranker/rank", {"candidates": ["x"]})[0], 400)
        self.assertEqual(c("/api/v1/models/dt-ranker/rank", {"candidates": "x"})[0], 400)
        bad_ir = {"side": "LONG", "conditions": ["close_above_sma"], "exit": {"tp_r": 2, "sl_atr": 1, "max_bars": 10}}
        self.assertIn(c("/api/v1/asge/run", {"seeds": [bad_ir]})[0], (200, 400))             # 200 only when INSUFFICIENT_DATA (demo)
        self.assertEqual(c("/api/v1/tlg/loot/evaluate", {"scores": {"evidence_quality": 500}})[0], 400)
        self.assertEqual(c("/api/v1/tlg/loot/evaluate", {"scores": "x"})[0], 400)
        self.assertEqual(c("/api/v1/tlg/sim/1/open", {"side": "BUY", "size": 1, "sl": "x"})[0], 400)
        import json as _j
        import urllib.error as _ue
        import urllib.request as _ur
        from _demo_server import BASE as _B
        put = _ur.Request(_B + "/api/v1/telegram/account/templates/nope", data=_j.dumps({"template": None}).encode(), method="PUT",
                          headers={"Content-Type": "application/json", "Origin": _B, "X-MQ-CSRF": self.S.csrf})
        try:
            pc = self.S.op.open(put, timeout=10).status
        except _ue.HTTPError as e:
            pc = e.code
        self.assertEqual(pc, 400)
        self.assertEqual(c("/api/v1/tlg/xp?limit=-5")[0], 200)
        self.assertEqual(c("/api/v1/orderflow/CRYPTO/workspace?instrument=BTC&row=nan")[0], 400)
        self.assertEqual(c("/api/v1/orderflow/CRYPTO/workspace?instrument=BTC&tf_seconds=0")[0], 400)
        self.assertEqual(c("/api/v1/indicators/calculate", {"method": "SMA", "period": 3, "bars": [{"o": 1, "h": 1, "l": 1, "c": "inf"}]})[0], 400)
        import urllib.error
        import urllib.request
        from _demo_server import BASE
        req = urllib.request.Request(BASE + "/api/v1/tlg/notes/PLAN", data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json", "Origin": BASE, "X-MQ-CSRF": "\u00e9t\u00e9"})
        try:
            code = self.S.op.open(req, timeout=10).status
        except urllib.error.HTTPError as e:
            code = e.code
        self.assertEqual(code, 403)

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


class TestExportIntegrity(unittest.TestCase):
    """1.45.0: (a) Studio committed the 'export' stage when EX.run RETURNED CANCELLED / FAILED (a pause = a 'done' partial export);
    (b) a simulator export was merged into the REAL candle store and relabelled it."""

    def test_studio_does_not_commit_interrupted_export(self):
        import tempfile
        from pathlib import Path
        from unittest import mock

        from masterquo.studio import pipeline as SP
        commits = []

        class Pkg:
            def tmp(self, name):
                return Path(tempfile.mkdtemp())

            def commit(self, *a, **k):
                commits.append(a)
        task = {"adapter": "TRAINHUB", "instrument": "XAUUSD", "sources": [{"kind": "BARS", "tf": "M5"}], "broker_symbol": "XAUUSD-"}
        for status, paused, want in (("CANCELLED", True, "PAUSED"), ("CANCELLED", False, "CANCELLED"), ("FAILED", False, "FAILED")):
            ctx = SP.Ctx(task, Pkg(), source={"mode": "SYNTHETIC", "days": 2, "cutoff": 1_795_000_000}, pause=lambda p=paused: p)
            with mock.patch("masterquo.marketdata.export.run", return_value={"status": status, "reason": "x", "timeframes": {}}), \
                    mock.patch.object(SP, "needed_tfs", return_value=["M5"]):
                with self.assertRaises(SP.Blocked) as cm:
                    SP.stage_export(ctx)
            self.assertEqual(cm.exception.state, want)
        self.assertEqual(commits, [])

    def test_synthetic_source_never_merges_into_real_store(self):
        import json
        import tempfile
        from pathlib import Path

        from masterquo.marketdata import export as EX
        from masterquo.marketdata.sources import DirectSource
        from masterquo.marketdata.store import Store
        from masterquo.mt5.fake import FakeMT5
        store = Store(Path(tempfile.mkdtemp()))
        d = store.inst_dir("XAUUSD")
        d.mkdir(parents=True)
        (d / "manifest.json").write_text(json.dumps({"instrument": "XAUUSD", "data_kind": "REAL_USER_DATA"}), encoding="utf-8")
        f = FakeMT5(history_days=3)
        f.initialize()
        src = DirectSource(f, offset=f.offset, offset_basis="SIMULATOR")
        with self.assertRaises(ValueError) as cm:
            EX.run(src, store, "XAUUSD", "XAUUSD-", timeframes=("M5",), lookback_days=1, sleep=lambda s: None)
        self.assertIn("DATA_KIND_MISMATCH", str(cm.exception))
        self.assertEqual(json.loads((d / "manifest.json").read_text())["data_kind"], "REAL_USER_DATA")


class TestWf32LazyNoDeadlock(unittest.TestCase):
    """1.45.0: lazy() ran factories under a non-reentrant Lock; with rt.baskets = None the 'universe' factory called lazy('hl') -> the thread
    blocked forever holding the lock and every lazy() route (TLG, bootstrap view, Telegram account, BAT) hung."""

    def test_universe_without_baskets_returns(self):
        import threading
        import types

        from fastapi import FastAPI

        from masterquo.api import wf32_routes
        app = FastAPI()
        wf32_routes.register(app, types.SimpleNamespace(bridge=None, baskets=None, cfg=None))
        out = {}
        t = threading.Thread(target=lambda: out.setdefault("u", app.state.wf32["universe"]()), daemon=True)
        t.start()
        t.join(5)
        self.assertFalse(t.is_alive(), "lazy('universe') deadlocked")
        self.assertIn("u", out)


class TestForexEngineStub(unittest.TestCase):
    """1.45.0: without WebGL the FOREX engine stub lacked setScreenData / nodeAt / setReduced ... -> TypeError in SIGNALS / MODELS / ROI."""

    def test_stub_has_full_api(self):
        import shutil
        import subprocess
        if not shutil.which("node"):
            self.skipTest("node not installed")
        r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", str(_env.ROOT / "tests" / "js" / "forex_engine_stub.test.mjs")],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)


class TestAssetAutodetectCurrency(unittest.TestCase):
    """1.45.0: find_on_account adopted a symbol by NAME although its currencies contradict the asset (BTCUSDT / BTCEUR / ETHBTC as BTC,
    XAUEUR as XAUUSD) - and autodetect() saved it as the mapping without confirmation."""

    def _reg(self, symbols):
        import types

        from masterquo.assets.registry import AssetRegistry
        br = types.SimpleNamespace(_call=lambda fn: fn(types.SimpleNamespace(symbols_get=lambda: symbols)))
        reg = AssetRegistry.__new__(AssetRegistry)
        reg.bridge = br
        return reg

    def test_conflicting_currencies_are_not_adopted(self):
        bad = [{"name": "BTCUSDT", "currency_base": "BTC", "currency_profit": "USDT", "visible": True},
               {"name": "BTCEUR", "currency_base": "BTC", "currency_profit": "EUR", "visible": True},
               {"name": "ETHBTC", "currency_base": "ETH", "currency_profit": "BTC", "visible": True},
               {"name": "XAUEUR", "currency_base": "XAU", "currency_profit": "EUR", "visible": True}]
        self.assertIsNone(self._reg(bad).find_on_account("BTC"))
        self.assertIsNone(self._reg(bad).find_on_account("XAUUSD"))
        good = bad + [{"name": "BTCUSD.m", "currency_base": "BTC", "currency_profit": "USD", "visible": True},
                      {"name": "GOLD", "currency_base": "USD", "currency_profit": "USD", "visible": True}]
        self.assertEqual(self._reg(good).find_on_account("BTC"), "BTCUSD.m")
        self.assertEqual(self._reg(good).find_on_account("XAUUSD"), "GOLD")


class TestMlRetryBackoff(unittest.TestCase):
    """1.45.0: _readiness ignored FAILED / INTERRUPTED / CANCELLED jobs -> the scheduler restarted training every 60 s with a new snapshot."""

    def test_failed_or_cancelled_job_blocks_automatic_restart(self):
        import test_ml as TM
        if not TM.HAVE_ML:
            self.skipTest("scikit-learn/xgboost not installed")
        t = TM.TestService("test_no_model_contract_and_fallback")
        t.setUp()
        try:
            from masterquo.timeutil import iso, utcnow
            ml = t.svc()
            ml.store.counts = lambda *a, **k: {"unique_setups": 10_000, "pos": 5_000, "neg": 5_000, "labeled": 10_000}
            self.assertTrue(ml._readiness()["ready"])
            for status, code in (("FAILED", "PO_BLEDZIE_FAILED"), ("INTERRUPTED", "PO_BLEDZIE_INTERRUPTED"), ("CANCELLED", "ANULOWANO_RECZNIE")):
                t.db.execute("DELETE FROM ml_jobs")
                t.db.execute("INSERT INTO ml_jobs(job_id, kind, status, created_at, finished_at, detail_json) VALUES (?,?,?,?,?,?)",
                             (f"J-{status}", "TRAIN", status, iso(utcnow()), iso(utcnow()), "{}"))
                r = ml._readiness()
                self.assertFalse(r["ready"], status)
                self.assertTrue(any(x.startswith(code) for x in r["reasons"]), r["reasons"])
        finally:
            t.tearDown()



class TestWf32Units(unittest.TestCase):
    """Chunk 04 (SREDNI): offset 0 in long-horizon, hour -1 in association rules, unbounded ledger, Telegram loop writes / ROI keys / SH magic."""

    def _app(self, rt):
        from fastapi import FastAPI

        from masterquo.api import wf32_routes
        app = FastAPI()
        wf32_routes.register(app, rt)
        ep = {r.path: r.endpoint for r in app.routes if hasattr(r, "endpoint")}
        return app, ep

    def test_unknown_offset_is_not_zero(self):
        import types
        bars = [{"t_raw": 1_790_000_000 + 3600 * i, "open_utc": None, "o": 1, "h": 1, "l": 1, "c": 1.0 + i * 1e-3, "tv": 1} for i in range(800)]
        br = types.SimpleNamespace(bars=lambda tf, n, include_forming=False: bars[-n:], clock=types.SimpleNamespace(offset=None), tfs={"H1": 1})
        app, ep = self._app(types.SimpleNamespace(bridge=None, baskets=None, cfg=None))
        import masterquo.api.wf32_routes as W  # noqa: F401
        rt2 = types.SimpleNamespace(bridge=br, baskets=None, cfg=None)
        app2, ep2 = self._app(rt2)
        r = ep2["/api/v1/forecast/long-horizon"](horizon="24h", timeframe="H1")
        self.assertEqual(r["status"], "UNAVAILABLE")
        self.assertIn("TIME_OFFSET_UNVERIFIED", r["reason"])
        a = ep2["/api/v1/models/association/snapshot"](timeframe="H1", horizon=24)
        self.assertEqual(a["status"], "UNAVAILABLE")

    def test_trade_ledger_is_bounded_oldest_first(self):
        from masterquo.orderflow.trades import TradeEvent, TradeLedger
        led = TradeLedger(max_per_instrument=100)
        for i in range(500):
            led.add(TradeEvent("BINANCE", "X", str(i), 1_700_000_000 + i, 100.0, 1.0, "BUY"))
        ev = led.events("X")
        self.assertLessEqual(len(ev), 110)
        self.assertEqual(ev[-1].trade_id, "499")
        self.assertGreater(int(ev[0].trade_id), 300)

    def test_account_center_no_idle_writes_and_queued_report_once(self):
        import tempfile
        import time
        from pathlib import Path

        from masterquo.notify.account_center import AccountCenter
        d = Path(tempfile.mkdtemp())
        c = AccountCenter(d, account_fn=lambda: {"server": "S", "login": 1}, clock=lambda: 1_795_000_000.0)
        st = d / "telegram_account_state.json"
        self.assertEqual((c.flush(), c.queue_reports()), (0, 0))
        self.assertFalse(st.exists())                                    # nothing to do -> nothing written
        c.cfg.update(bound_account_key="S:1", send_account_daily_report=True, report_time="00:00")
        n1 = c.queue_reports(now=time.time())
        n2 = c.queue_reports(now=time.time())
        self.assertEqual((n1, n2, len(c.state["outbox"])), (1, 0, 1))      # the waiting report is not queued again every 10 s

    def test_account_roi_keys_and_sh_magic(self):
        import types
        from unittest import mock
        rt = types.SimpleNamespace(bridge=None, baskets=None, cfg=types.SimpleNamespace(get=lambda: types.SimpleNamespace(mt5=types.SimpleNamespace(magic_number=4108_2026))),
                                   db=None, telegram=None)
        app, _ = self._app(rt)
        with mock.patch("masterquo.sh.config.load", return_value={"magic_number": 41082100}):
            self.assertIn(41082100, app.state.wf32["acct"]().pmw_magics)
        br = types.SimpleNamespace(_lock=__import__("threading").Lock(), deals=[{"type": 0, "time": 1_795_000_100 + 7200}, {"type": 2, "time": 1}],
                                   account_key="S:1", clock=types.SimpleNamespace(offset=7200), account_status=lambda: {"currency": "USD"})
        rt.bridge = br
        roi = {"status": "OK", "roi_pct": 1.5, "start_equity": 1000.0, "end_equity": 1100.0, "net_flows": 50.0,
               "period_from": "2026-11-18T00:00:00Z", "period_to": "2026-11-30T00:00:00Z"}
        with mock.patch("masterquo.stats.account_roi", return_value=roi):
            r = app.state.wf32["acct_roi"](30)
        self.assertEqual((r["net"], r["deals"], r["currency"]), (50.0, 1, "USD"))


class TestSfbAssistDisabled(unittest.TestCase):
    """1.45.0 (KRYTYCZNY, rule 2): SFB ASSIST set through PUT /api/v1/strategy-filter/config narrowed the strategies of the FOREX baskets that
    reach the SH execution path. The application now refuses ASSIST and runs a stored ASSIST as SHADOW (nothing filtered)."""

    def test_assist_refused_and_stored_assist_runs_as_shadow(self):
        import json
        import tempfile
        import types
        from pathlib import Path

        from masterquo.baskets import catalog as CAT
        from masterquo.baskets import service as BS
        from masterquo.baskets.sfb import ConfigError
        d = Path(tempfile.mkdtemp())
        rt = types.SimpleNamespace(demo=True, bridge=None, db=None, bus=None, quant=None, news=None)
        svc = BS.BasketService(rt, data_dir=d)
        with self.assertRaises(ConfigError):
            svc.set_sfb({"mode": "ASSIST"})
        (d / "sfb.json").write_text(json.dumps({"mode": "ASSIST"}), encoding="utf-8")          # stored by 1.45.0
        svc2 = BS.BasketService(rt, data_dir=d)
        st = svc2.sfb.status()
        self.assertEqual(st["mode"], "SHADOW")
        self.assertTrue(st["mode_requested"].startswith("ASSIST"))
        strats = [s for s in CAT.strategies() if s["profile_id"] == "FOREX_MT5"]
        kept, snap = svc2.sfb.filter(strats, {"profile": "FOREX_MT5", "venue": "MT5", "environment": "PAPER", "product": None, "instrument": "XAUUSD"})
        self.assertEqual(kept, strats)                                                     # nothing filtered
        self.assertEqual(json.loads((d / "sfb.json").read_text())["mode"], "ASSIST")          # the user's file is not rewritten
        (d / "sfb.json").write_text(json.dumps({"mode": "OFF", "apply_to_execution": True}), encoding="utf-8")
        self.assertEqual(BS.BasketService(rt, data_dir=d).sfb.status()["mode"], "OFF")        # damaged config -> OFF, service still starts


class TestTrackerEnteredNotResurrected(unittest.TestCase):
    """1.45.0: the scan thread saved rows read at its start; an ENTERED set meanwhile by the execution (API thread, POST /api/v1/execute) was
    overwritten back to ACTIVE (lost update) - the setup could be selected and executed again."""

    def test_stale_copy_cannot_overwrite_entered(self):
        import test_strategies as TS
        t = TS.TestTracker("test_dedupe_invalidation_expiry_restore")
        t.setUp()
        try:
            sid = TS.ALL[0]
            bars = TS.scenario(sid)
            v, cands = t._scan(bars, sid)
            now = t._now(bars)
            t.tr.update(cands, view=v, symbol="XAUUSD-", account_key="acc", data_ok=True, new_data=True, now=now, cfg=t.cfg, scanned={sid})
            row = t.tr.active("XAUUSD-", "acc")[0]                 # the scan's copy (status ACTIVE)
            t.tr.mark_entered(row["setup_id"], "AUTO_DEMO_FILLED", "2026-11-20T10:00:00Z")   # execution thread
            row["updated_at"] = "2026-11-20T10:00:01Z"
            t.tr._save(row)                                         # the scan finishes and writes its stale copy
            self.assertEqual(t.tr.get(row["setup_id"])["status"], "ENTERED")
            self.assertEqual(t.tr.active("XAUUSD-", "acc"), [])
        finally:
            t.tearDown()


class TestConfigIntegrity(unittest.TestCase):
    """1.45.0: (a) config_version was writable through ConfigStore.update / PUT /api/v1/config -> the next start re-ran the migrations over the
    user's settings; (b) scalp.commission_per_lot_side = null (UNKNOWN) was replaced with 0.50 on EVERY load."""

    def test_config_version_not_patchable_and_null_commission_kept(self):
        from _env import TempData

        from masterquo.config import ConfigStore
        td = TempData()
        try:
            st = ConfigStore()
            cur = st.get().config_version
            st.update({"config_version": 1})
            self.assertEqual(st.get().config_version, cur)
            self.assertEqual(ConfigStore().get().config_version, cur)          # after a "restart"
            st.update({"scalp": {"commission_per_lot_side": None}})
            self.assertIsNone(ConfigStore().get().scalp.commission_per_lot_side)
            self.assertIsNone(ConfigStore().get().scalp.commission_per_lot_side)
        finally:
            td.close()


class TestBootstrapNoParallelInstalls(unittest.TestCase):
    def test_timeout_keeps_installing_and_stops_the_queue(self):
        import pathlib
        import tempfile

        from masterquo.bootstrap import Bootstrap
        started = []
        inst = {c: ((lambda c=c: started.append(c) or {"ok": True}), (lambda: "RUNNING")) for c in ("tsfm_chronos2", "tsfm_granite_ttm")}
        b = Bootstrap(state_file=pathlib.Path(tempfile.mkdtemp()) / "b.json", installers=inst, poll_s=0.01)
        b.state["components"] = {c: {"state": "NOT_INSTALLED"} for c in inst}
        out = b.run_heavy(timeout_s=0.05)
        self.assertEqual(started, ["tsfm_chronos2"])                                # the second install never starts in parallel
        self.assertEqual(out[0]["state"], "INSTALLING")


class TestV32ModulesBatch2(unittest.TestCase):
    """Chunks 05 / 07 / 18 / 19 (SREDNI / NISKI) in workflow v3.2 modules."""

    def test_asge_ledger_durable_locked_and_ir_types(self):
        import tempfile
        import threading
        from pathlib import Path

        from masterquo.apollo import asge as A
        p = Path(tempfile.mkdtemp()) / "asge_trials.jsonl"
        led = A.TrialLedger(p)
        ts = [threading.Thread(target=lambda: [led.add({"x": 1}) for _ in range(50)]) for _ in range(4)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(len({r["trial_id"] for r in led.rows}), 200)           # no duplicated ids
        self.assertEqual(len(A.TrialLedger(p).rows), 200)                         # survives a restart
        for bad in ({"side": "LONG", "conditions": "x", "exit": {}}, {"side": "LONG", "conditions": [{"type": "close_above_sma", "n": 20.5}],
                                                                       "exit": {"tp_r": 2, "sl_atr": 1, "max_bars": 10}}, "x"):
            with self.assertRaises(A.IRError):
                A.validate_ir(bad)

    def test_sfb_nan_lookahead_and_config_types(self):
        from masterquo.baskets import catalog as CAT
        from masterquo.baskets import sfb as F
        s = CAT.strategies()[0]
        base = {"strategy_id": s["strategy_id"], "config_hash": s["config_hash"], "version": s["version"], "source": "PAPER"}
        rows = [dict(base, net_R=float("nan"), closed_ts=1_700_000_000 + i) for i in range(5)]
        self.assertEqual(F.evidence(s, rows, F.validate_config({}), now=1_800_000_000)["n_events"], 0)   # NaN never counts
        fut = [dict(base, net_R=1.0, closed_ts=1_900_000_000)]
        self.assertEqual(F.evidence(s, fut, F.validate_config({}), now=1_800_000_000)["n_events"], 0)    # closed after `now`
        for bad in ({"bootstrap_reps": 0}, {"bootstrap_block": 0}, {"bootstrap_confidence": "x"}, {"min_outer_folds": "5"}):
            with self.assertRaises(F.ConfigError):
                F.validate_config(bad)

    def test_association_contrary_is_not_supported(self):
        from masterquo.ml import association_rules as AR
        m = {"status": "READY", "rules": [{"mask": 1, "edge_up": 0.10, "edge_down": 0.30}]}
        a = AR.assess(m, 1, "LONG", mode="ASSIST")
        self.assertEqual((a["candidate_direction_supported"], a["reason"], a["action"]), (False, "CONTRARY_EDGE", "HOLD"))

    def test_smma_cci_unknown_spread_and_forming_bar(self):
        from masterquo.apollo import smma_cci as S
        bars = [{"t": 1_700_000_000 + 300 * i, "o": 100.0, "h": 100.0, "l": 100.0, "c": 100.0, "closed": True} for i in range(60)]
        r = S.evaluate(bars + [{"t": 1_700_018_000, "o": 1, "h": 999, "l": 1, "c": 999, "closed": False}])
        self.assertIsNone(r["spread_atr"])                                       # flat bars: ATR 0 -> unknown, not 0.0
        self.assertEqual(r["bar_index"], 59)                                     # the forming bar is excluded
        self.assertEqual(r["bar_t_basis"], "UTC_EPOCH")

    def test_provider_down_is_unavailable_and_backs_off(self):
        from masterquo.markets import universe as MU

        class Down:
            calls = 0

            def post(self, body):
                Down.calls += 1
                raise OSError("network down")
        hl = Down()
        u = MU.Universe(hl)
        br = MU.CryptoMarketBridge(hl, u)
        with self.assertRaises(MU.ProviderUnavailable):
            br.candles("BTC", "1h", 10)
        n = Down.calls
        for _ in range(5):
            with self.assertRaises(MU.ProviderUnavailable):
                br.candles("BTC", "1h", 10)
        self.assertEqual(Down.calls, n)                                          # no re-query on every request


class TestTickArchiveForTsvp(unittest.TestCase):
    """1.45.0: mm job_tsvp failed with KeyError 'time_msc' on a REAL tick archive (tick_store format); tick_store.load re-read every npz array
    per tick (quadratic)."""

    def test_archive_ticks_feed_tsvp_and_load_once(self):
        import types
        from unittest import mock

        from _env import TempData

        from masterquo.lab import tick_store
        from masterquo.mm import jobs as J
        td = TempData()
        try:
            base = 1_795_000_000_000
            ticks = [{"t_ms": base + 100 * i, "time_msc": base + 7_200_000 + 100 * i, "bid": 2000 + (i % 7) * 0.01, "ask": 2000.2 + (i % 7) * 0.01,
                      "flags": 6} for i in range(3000)]
            tick_store.save_chunk("XAUUSD", ticks, "TEST", "NONE", False)
            got = tick_store.load("XAUUSD")
            self.assertEqual((len(got), got[0]["time_msc"], got[0]["flags"]), (3000, base + 7_200_000, 6))
            ctx = types.SimpleNamespace(inst="XAUUSD", synthetic=False, snap=types.SimpleNamespace(tick_size=0.01))
            tk, src = J._ticks(ctx)
            self.assertEqual(src, "REAL_TICK_ARCHIVE")
            self.assertTrue(all("time_msc" in t and "last" in t for t in tk))
            res = J.job_tsvp(ctx)                                               # 1.45.0: KeyError 'time_msc'
            self.assertIsInstance(res, dict)
            import numpy as np
            real_load = np.load
            reads = {"n": 0}

            class Counting:
                def __init__(self, z):
                    self.z, self.files = z, z.files

                def __getitem__(self, k):
                    reads["n"] += 1
                    return self.z[k]

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    self.z.close()
            with mock.patch.object(tick_store.np, "load", side_effect=lambda *a, **k: Counting(real_load(*a, **k))):
                tick_store.load("XAUUSD")
            self.assertLessEqual(reads["n"], 6)                                 # each array once, not 4 x 3000 reads
        finally:
            td.close()


class TestTrainhubStudioRobustness(unittest.TestCase):
    """1.45.0: (a) the trainhub inference loop called AppLog.warning (no such method) -> AttributeError killed the thread on the first error;
    (b) Studio lock liveness used os.kill(pid, 0) (on Windows a console CTRL-C event, failing for other processes -> every owner 'dead');
    (c) a Studio TRAINHUB import wrote created_at as a float -> registry.summary() TypeError (500) next to native ISO versions."""

    def test_inference_loop_survives_an_error(self):
        import threading
        import types

        from masterquo.events import AppLog, EventBus
        from masterquo.trainhub import inference as INF
        calls = {"n": 0}

        class Db:
            def execute(self, *a, **k):
                return None
        svc = INF.TrainhubInference.__new__(INF.TrainhubInference)
        svc.log = AppLog(Db(), EventBus())
        svc.poll_s = 0.01
        svc._stop = threading.Event()

        def boom(inst, force=False):
            calls["n"] += 1
            if calls["n"] > 6:
                svc._stop.set()
            raise RuntimeError("x")
        svc.run_instrument = boom
        t = threading.Thread(target=svc._loop, daemon=True)
        t.start()
        t.join(5)
        self.assertGreater(calls["n"], 2)                           # 1.45.0: the thread died after the first error

    def test_studio_lock_uses_process_query(self):
        import os as _os
        from unittest import mock

        from masterquo.studio import lock as L
        self.assertTrue(L._alive(_os.getpid()))
        with mock.patch("masterquo.training.core._pid_alive", return_value=True) as m:
            self.assertTrue(L._alive(123456))
            m.assert_called_once_with(123456)

    def test_registry_summary_with_numeric_created_at(self):
        from _env import TempData

        from masterquo.trainhub import registry as R
        td = TempData()
        try:
            reg = R._reg("XAUUSD")
            reg.setdefault("versions", {})["k"] = [{"version": "a", "created_at": "2026-11-20T10:00:00Z"}, {"version": "b", "created_at": 1_795_000_000.0}]
            R._save_reg("XAUUSD", reg)
            out = R.summary("XAUUSD")
            self.assertEqual([v["version"] for v in out["versions"]], ["a", "b"])        # 2026-11-20 is newer than 1_795_000_000 (2026-11-17)
        finally:
            td.close()


class TestTrainingTestProfileAndLock(unittest.TestCase):
    """1.45.0 (KRYTYCZNY): profile TEST_INSTALACJI ("modele nie są aktywowane") on REAL data rewrote data/sh/validation/* and the pack variant
    status files that gate AUTO_LIVE SH entries (and could promote the SH model) from ~4 days of history. And the training lock was handed to a
    second process resuming the SAME run while the owner was alive."""

    def test_sh_train_no_live_write(self):
        import types
        from pathlib import Path
        from unittest import mock

        from _env import TempData

        from masterquo import paths
        from masterquo.sh import train_cli as TC
        td = TempData()
        try:
            out = Path(td.dir) / "run" / "x.json"
            out.parent.mkdir()
            calls = {}
            res = {"samples": [], "counts": {}}
            with mock.patch.object(TC.RP, "load_dataset", return_value=({"M1": [1]}, {"instrument": "XAUUSD", "data_kind": "REAL_USER_DATA"})), \
                    mock.patch.object(TC.C, "load", return_value={"_hash": "h", "instruments": {"XAUUSD": {"enabled": True}}}), \
                    mock.patch.object(TC.C, "profile", return_value={"horizon_minutes": 30}), \
                    mock.patch.object(TC.SymbolSpec, "from_mt5", return_value=types.SimpleNamespace(check_usd=lambda x: None)), \
                    mock.patch.object(TC.RP, "Market", return_value=types.SimpleNamespace(m1=[1])), \
                    mock.patch.object(TC.RP, "run", return_value={"SCALPING": res}), \
                    mock.patch.object(TC.TM, "train", side_effect=lambda *a, **k: calls.setdefault("promo", k["allow_promotion"]) and {} or {}), \
                    mock.patch.object(TC.RP, "report", return_value={"event_model": {}, "baseline": {}}):
                TC.train(Path("ds"), "XAUUSD", out, strategies=("SCALPING",), live_write=False)
            self.assertIs(calls["promo"], False)
            self.assertFalse((paths.data_dir() / "sh" / "validation" / "XAUUSD_SCALPING.json").exists())
        finally:
            td.close()

    def test_pack_write_live_false_keeps_catalog_status(self):
        from _env import TempData

        from masterquo import paths
        from masterquo.sh.pack import replay as PR
        td = TempData()
        try:
            rep = {"report_id": "R1", "data_kind": "REAL_USER_DATA", "created_at": "2026-11-20T00:00:00Z",
                   "variants": {"PMW_SC01|M5": {"verdict": "VALIDATED", "verdict_reason": "x"}}}
            self.assertEqual(PR.write(rep, live=False)["variant_files"], [])
            self.assertFalse((paths.data_dir() / "sh" / "pack_validation" / "PMW_SC01.json").exists())
            self.assertEqual(len(PR.write(dict(rep, report_id="R2"))["variant_files"]), 1)          # a real run still writes it
        finally:
            td.close()

    def test_runner_passes_no_live_write_for_test_profile(self):
        from pathlib import Path
        from unittest import mock

        from masterquo.training import runner as RN
        cmds = []

        class Run:
            dir = Path("/tmp")
            state = {"plan": {"profile": "TEST_INSTALACJI", "synthetic": False, "activate": False, "profile_params": {"task_timeout_minutes": 1},
                              "commissions": {}}}

            def set(self, *a, **k):
                return None
        with mock.patch.object(RN, "_ready", return_value=Path("/tmp/ds")), \
                mock.patch.object(RN.core, "run_child", side_effect=lambda run, tid, cmd, *a, **k: cmds.append(cmd) or (None, "")), \
                mock.patch.object(RN.core, "child_env", return_value={}):
            RN.t_sh_models(Run(), "XAUUSD")
            RN.t_sh_pack(Run(), "XAUUSD")
        self.assertEqual(len(cmds), 2)
        self.assertTrue(all("--no-live-write" in c for c in cmds), cmds)

    def test_lock_refused_for_same_run_in_another_live_process(self):
        import json
        import os

        from _env import TempData

        from masterquo.training import core
        td = TempData()
        try:
            p = core.lock_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"run_id": "RUN-1", "pid": os.getppid(), "at": "x"}), encoding="utf-8")   # a live other process
            self.assertEqual(core.acquire_lock("RUN-1"), "RUN-1")
            p.write_text(json.dumps({"run_id": "RUN-1", "pid": 999_999_9, "at": "x"}), encoding="utf-8")       # dead owner -> taken over
            self.assertIsNone(core.acquire_lock("RUN-1"))
        finally:
            td.close()


class TestGoldCandlesContractHashStable(unittest.TestCase):
    """1.46 regression found by the audit: the ruff F401 cleanup removed unused imports from gold_candles/data.py and model.py. contract_hash()
    hashes the RAW BYTES of data/patterns/features/model.py, so every forecast model trained in 1.45 became CONTRACT_MISMATCH. The bytes are
    restored; this pins the 1.45.0 contract of the default XAUUSD config (any byte change of those four files must be a deliberate new contract)."""

    def test_default_contract_hash_is_the_1_45_one(self):
        import sys

        from _env import ROOT
        sys.path.insert(0, str(ROOT / "backend"))
        from gold_candles.data import Config
        self.assertEqual(Config().contract_hash(), "403283d916e01f528ac74186b6724784e37c1f6c8ceb8d56171a2314b2f1e77c")


class TestFamiliesServiceSafety(unittest.TestCase):
    """1.45.0 (WYSOKI x5): model families - ASSIST kept on artifacts that never passed the gate (activate / rollback, SYNTHETIC_TEST data);
    `_alive` = os.kill(pid, 0) (TerminateProcess on Windows); cancel left the .venv_deep worker running; the prediction cache grew per bar;
    unknown family names created folders; a train_all queue interrupted by a restart waited forever; a second submit while QUEUED."""

    def setUp(self):
        import shutil
        import tempfile
        from pathlib import Path

        from masterquo.modelhub.families import base as B
        self.td = tempfile.mkdtemp(prefix="fam146_")
        self.addCleanup(shutil.rmtree, self.td, True)
        self.B, self.store = B, B.Store(Path(self.td))

    def run_(self, rid, status, kind, fid="TS_ARIMA"):
        d = self.store.run_dir(fid, "XAUUSD", rid)
        d.mkdir(parents=True)
        self.B._atomic_json(d / "manifest.json", {"run_id": rid, "validation": {"status": status}, "data_kind": kind, "created_at": 1})

    def svc(self):
        from masterquo.config import ConfigStore
        from masterquo.modelhub.families.service import FamilyService
        return FamilyService(ConfigStore(), None, store=self.store)

    def test_activate_and_rollback_drop_assist_from_unapproved_artifact(self):
        self.run_("R1", "APPROVED", "REAL_USER_DATA")
        self.run_("R2", "VALIDATION_FAILED", "REAL_USER_DATA")
        self.store.set_active("TS_ARIMA", "XAUUSD", "R1", "t")
        self.assertEqual(self.store.set_use("TS_ARIMA", "XAUUSD", "ASSIST")["use"], "ASSIST")      # REAL_USER_DATA + APPROVED passes
        self.assertEqual(self.store.set_active("TS_ARIMA", "XAUUSD", "R2", "t")["use"], "SHADOW")  # 1.45.0: stayed ASSIST
        self.store.set_active("TS_ARIMA", "XAUUSD", "R1", "t")
        self.store.set_use("TS_ARIMA", "XAUUSD", "ASSIST")
        self.store._save_state("TS_ARIMA", "XAUUSD", dict(self.store.state("TS_ARIMA", "XAUUSD"),
                                                          history=[{"action": "ACTIVATE", "run_id": "R1", "previous": "R2"}]))
        self.assertEqual(self.store.rollback("TS_ARIMA", "XAUUSD")["use"], "SHADOW")              # back to the unapproved R2

    def test_synthetic_test_and_unknown_data_never_get_assist(self):
        for kind in ("SYNTHETIC_TEST", "UNKNOWN", None):
            self.store._save_state("TS_ARIMA", "XAUUSD", {"active": None, "use": "OFF", "history": []})
            rid = f"S-{kind}"
            self.run_(rid, "APPROVED", kind)
            self.store.set_active("TS_ARIMA", "XAUUSD", rid, "t")
            with self.assertRaises(ValueError, msg=kind):
                self.store.set_use("TS_ARIMA", "XAUUSD", "ASSIST")
        self.assertEqual(self.B.kind_class("SYNTHETIC_TEST"), "SYNTHETIC")
        self.assertEqual(self.B.kind_class("REAL_USER_DATA"), "REAL")
        self.assertIsNone(self.B.kind_class("UNKNOWN_SOURCE"))

    def test_saved_assist_on_bad_artifact_predicts_as_shadow(self):
        from unittest import mock
        self.run_("R9", "APPROVED", "SYNTHETIC_TEST")
        self.store._save_state("TS_ARIMA", "XAUUSD", {"active": "R9", "use": "ASSIST", "history": []})    # written by 1.45
        s = self.svc()
        with mock.patch.object(s, "_live", return_value={"bars": [{"t": 60.0}]}):
            p = s.predict("TS_ARIMA", "XAUUSD")
        self.assertEqual(p.get("use"), "SHADOW", p)

    def test_prediction_cache_keeps_one_entry_per_family(self):
        from unittest import mock
        self.run_("R1", "APPROVED", "REAL")
        self.store._save_state("TS_ARIMA", "XAUUSD", {"active": "R1", "use": "SHADOW", "history": []})
        s = self.svc()
        for t in range(50):
            with mock.patch.object(s, "_live", return_value={"bars": [{"t": 60.0 * t}]}):
                s.predict("TS_ARIMA", "XAUUSD")
        self.assertEqual(len(s._cache), 1)

    def test_unknown_family_and_traversal_refused_without_disk_writes(self):
        from pathlib import Path
        s = self.svc()
        for call in (lambda: s.runs("NOPE", "XAUUSD"), lambda: s.rollback("NOPE", "XAUUSD"), lambda: s.set_use("NOPE", "XAUUSD", "SHADOW"),
                     lambda: s.cancel("NOPE", "XAUUSD"), lambda: s.runs("..", "XAUUSD")):
            with self.assertRaises(KeyError):
                call()
        with self.assertRaises(KeyError):
            self.store.fam_dir("..", "XAUUSD")
        self.assertFalse((Path(self.td) / "NOPE").exists())
        self.assertFalse((Path(self.td) / "XAUUSD").exists())

    def test_alive_never_signals_the_process(self):
        from unittest import mock

        from masterquo.modelhub.families import service as FS
        with mock.patch("os.kill", side_effect=AssertionError("os.kill(pid, 0) = TerminateProcess on Windows")), \
                mock.patch("masterquo.training.core._pid_alive", return_value=True) as pa:
            self.assertTrue(FS._alive(1234))
        pa.assert_called_once_with(1234)

    def test_restart_cancels_interrupted_queue(self):
        jobs = self.store.base / "_jobs"
        jobs.mkdir(parents=True)
        self.B._atomic_json(jobs / "BREAKOUT__XAUUSD.json", {"state": "QUEUED", "family": "BREAKOUT", "waiting": True})
        self.B._atomic_json(jobs / "KALMAN_LS__XAUUSD.json", {"state": "QUEUED", "family": "KALMAN_LS"})          # submit died before Popen
        s = self.svc()
        self.assertEqual(s.job("BREAKOUT", "XAUUSD")["state"], "CANCELLED")
        self.assertEqual(s.job("KALMAN_LS", "XAUUSD")["state"], "CANCELLED")

    def test_second_submit_while_queued_and_own_process_group(self):
        from unittest import mock
        s = self.svc()
        seen = []

        class P:
            pid = 4242

            def poll(self):
                return None
        with mock.patch("subprocess.Popen", side_effect=lambda *a, **k: seen.append(k) or P()):
            self.assertTrue(s.submit("KALMAN_LS", "XAUUSD")["ok"])
            self.assertEqual(s.job("KALMAN_LS", "XAUUSD")["state"], "QUEUED")         # the child has not written RUNNING yet
            self.assertEqual(s.submit("KALMAN_LS", "XAUUSD")["status"], "ALREADY_RUNNING")
        self.assertEqual(len(seen), 1)
        import os
        if os.name != "nt":
            self.assertTrue(seen[0].get("start_new_session"))

    @unittest.skipIf(__import__("os").name == "nt", "process groups: POSIX branch")
    def test_kill_tree_ends_the_grandchild(self):
        import os
        import subprocess
        import sys
        import time

        from masterquo.modelhub.families import service as FS
        code = "import subprocess,sys,time; c=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); print(c.pid, flush=True); time.sleep(60)"
        p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True, start_new_session=True)
        child = int(p.stdout.readline())
        p.stdout.close()
        FS._kill_tree(p.pid, p)
        p.wait(10)
        for _ in range(40):
            try:
                os.kill(child, 0)
                with open(f"/proc/{child}/stat") as fh:
                    if fh.read().split()[2] == "Z":
                        break
            except (OSError, FileNotFoundError):
                break
            time.sleep(0.1)
        else:
            self.fail("the grandchild survived cancel")
