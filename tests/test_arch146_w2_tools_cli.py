"""Fala 2 / grupa tools_cli (Apollo23 1.46): narzędzia i CLI bez wpływu na decyzje handlowe.

I0480 (build terminala w statusie natywnym MiniRocket v2). Każdy test nie przechodzi na kodzie sprzed poprawki.
Bez serwera HTTP, bez MT5, bez zleceń.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import _env

ROOT = _env.ROOT
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))


# ============================================================================================== I0480 mr2_native_status: build
class TestNativeStatusBuild(unittest.TestCase):
    """I0480: native_status.json had no terminal_build, so MR.native_status(...)['build'] was always None although the self-test line
    carries `build=N` (PMW_MR2_SelfTest.mq5:82)."""

    def setUp(self):
        import mr2_native_status as ns
        self.ns = ns
        self.tmp = Path(tempfile.mkdtemp(prefix="mq_t_w2tc_native_"))
        self.mql = self.tmp / "MQL5"
        for d in ("Scripts/PMW", "Indicators/PMW", "Include/PMW", "Files/PMW"):
            (self.mql / d).mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, text: str, selftest_age: float) -> dict:
        ex5 = self.mql / "Scripts" / "PMW" / "PMW_MR2_SelfTest.ex5"
        ex5.write_bytes(b"ex5")
        (self.mql / "Scripts" / "PMW" / "PMW_MR2_SelfTest.mq5").write_text("src", encoding="utf-8")
        st = self.mql / "Files" / "PMW" / "mr2_selftest.txt"
        st.write_text(text, encoding="utf-8")
        now = time.time()
        os.utime(ex5, (now, now))
        os.utime(st, (now + selftest_age, now + selftest_age))
        with redirect_stdout(io.StringIO()):
            self.ns.main(str(self.tmp), "0", "log")
        return json.loads((self.mql / "Files" / "PMW" / "native_status.json").read_text(encoding="utf-8"))

    def test_fresh_selftest_build_is_written_and_reported(self):
        from masterquo.lab import minirocket_v2 as MR
        out = self._run("2026.11.24 PMW_MR2_SELFTEST RESULT=PASS failures=0 build=4620\n", +60)
        self.assertEqual(out["terminal_build"], 4620)
        ns = MR.native_status(self.mql / "Files" / "PMW" / "native_status.json")
        self.assertEqual(ns["build"], 4620)
        self.assertEqual(ns["NATIVE_EXECUTED"], "PASS")

    def test_stale_selftest_build_is_not_evidence(self):
        out = self._run("PMW_MR2_SELFTEST RESULT=PASS failures=0 build=4620\n", -3600)
        self.assertIsNone(out["terminal_build"])
        self.assertEqual(out["selftest_result"], "NATIVE_NOT_EXECUTED")

    def test_selftest_without_build_gives_none(self):
        out = self._run("RESULT=PASS\n", +60)
        self.assertIsNone(out["terminal_build"])
        self.assertEqual(out["selftest_result"], "PASS")


# ============================================================================================== I0137 `masterquo studio --port`
class TestStudioCliArgs(unittest.TestCase):
    """I0137: `studio --port` without a value / with a non-number ended in IndexError / ValueError; the branch skipped _load_dotenv()."""

    def _main(self, *args):
        from masterquo import __main__ as M
        calls = []

        class Gate:
            locked = False

            def __init__(self):
                calls.append("gate")

            def evaluate(self, refresh_net=False):
                return {"message": ""}

        def serve(port=None):
            calls.append(("serve", port))
            return 0

        err = io.StringIO()
        with mock.patch.object(M, "_load_dotenv", side_effect=lambda: calls.append("dotenv")), \
                mock.patch("masterquo.licensing.gate.LicenseGate", Gate), mock.patch("masterquo.studio.app.serve", serve), \
                redirect_stderr(err):
            rc = M.main(["studio", *args])
        return rc, calls, err.getvalue()

    def test_port_without_value_is_exit_2_not_a_traceback(self):
        rc, calls, err = self._main("--port")
        self.assertEqual(rc, 2)
        self.assertNotIn(("serve", None), calls)
        self.assertIn("--port", err)

    def test_non_numeric_and_out_of_range_port_is_exit_2(self):
        for bad in ("abc", "70000", "-5", "8780.5"):
            rc, calls, err = self._main("--port", bad)
            self.assertEqual(rc, 2, bad)
            self.assertFalse([c for c in calls if isinstance(c, tuple)], bad)
            self.assertIn("--port", err, bad)

    def test_valid_port_and_default_reach_serve_after_dotenv(self):
        rc, calls, _ = self._main("--port", "8790")
        self.assertEqual(rc, 0)
        self.assertEqual(calls, ["dotenv", "gate", ("serve", 8790)])
        rc, calls, _ = self._main("--port=8791")
        self.assertEqual(calls[-1], ("serve", 8791))
        rc, calls, _ = self._main()
        self.assertEqual(calls, ["dotenv", "gate", ("serve", None)])
        rc, calls, _ = self._main("--extra", "x", "--port", "8792")       # other arguments were ignored before - still ignored
        self.assertEqual((rc, calls[-1]), (0, ("serve", 8792)))


# ============================================================================================== I0132 `masterquo train-all`
TODAY_TASKS = ["forecast", "scalp_A", "ml", "lab", "indicator_context", "ml_scalp", "neural_scalp", "structure_intelligence", "flow_context",
               "context_indicators"]


class TestTrainAllHelp(unittest.TestCase):
    """I0132: help claimed `train-all` = 22_TRENUJ_WSZYSTKIE_MODELE.bat (`training run`, every task) while it trains an explicit subset of
    10 tasks; --scalp-months / --mt5-wait were parsed and silently ignored. The trained set must stay EXACTLY the same."""

    def _help(self, *args) -> str:
        from masterquo import __main__ as M
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit):
            M.main([*args, "--help"])
        return " ".join(out.getvalue().split())

    def _tasks(self, *args):
        from masterquo import __main__ as M
        seen = []
        out = io.StringIO()
        with mock.patch("masterquo.training.cli.main", side_effect=lambda argv: seen.append(list(argv)) or 0), \
                mock.patch.object(M, "_load_dotenv"), redirect_stdout(out):
            self.assertEqual(M.main(["train-all", *args]), 0)
        argv = seen[0]
        return argv[argv.index("--tasks") + 1], out.getvalue()

    def test_help_does_not_claim_the_22_mechanism_and_lists_the_tasks(self):
        top = self._help()
        self.assertNotIn("ten sam mechanizm co `training run`", top)
        sub = self._help("train-all")
        for t in TODAY_TASKS:
            self.assertIn(t, sub)
        self.assertIn("22_TRENUJ_WSZYSTKIE_MODELE.bat", sub)
        self.assertRegex(sub, r"--mt5-wait [A-Z0-9_]+ \(przestarzałe, ignorowane")
        self.assertRegex(sub, r"--scalp-months [A-Z0-9_]+ \(przestarzałe, ignorowane")

    def test_task_subset_identical_to_today(self):
        from masterquo import train_all as TA
        self.assertEqual([t for t, _ in TA.TRAIN_ALL_TASKS], TODAY_TASKS)
        tasks, _ = self._tasks()
        self.assertEqual(tasks, ",".join(TODAY_TASKS))
        tasks, _ = self._tasks("--skip-candles")
        self.assertEqual(tasks, "ml,lab,ml_scalp,neural_scalp,structure_intelligence,flow_context,context_indicators")
        tasks, _ = self._tasks("--skip-ml", "--skip-lab")
        self.assertEqual(tasks, "forecast,scalp_A,indicator_context")
        tasks, _ = self._tasks("--skip-candles", "--skip-ml", "--skip-lab")
        self.assertEqual(tasks, "none")

    def test_deprecated_flags_warn_and_change_nothing(self):
        tasks, out = self._tasks("--mt5-wait", "60", "--scalp-months", "3")
        self.assertEqual(tasks, ",".join(TODAY_TASKS))
        self.assertIn("--mt5-wait", out)
        self.assertIn("--scalp-months", out)
        self.assertIn("ignorowan", out)
        _, out = self._tasks()
        self.assertNotIn("ignorowan", out)


# ============================================================================================== I0658 / I0666 / I0012 model map + cards
class TestModelMapFromRegistry(unittest.TestCase):
    """I0666 (+I0673): the trainhub loop of tools/model_map.py was a hand list of 4 models (no TH_RF / TH_SVM). I0658: the trainer text said
    `trainhub train|full` for every model although without --models only pipeline.DEFAULTS['models'] are trained. I0012: the map was a hand
    list (29 rows, no Kronos/TSFM/MM/...), the family cards inherited TF/horizon of the family adapter (TH_XGB 'M5 / 6')."""

    @classmethod
    def setUpClass(cls):
        import importlib
        cls.td = _env.TempData()
        import model_map
        cls.MM = importlib.reload(model_map)
        from masterquo.quant import inventory as QI
        cls.inv = QI.build()

    @classmethod
    def tearDownClass(cls):
        cls.td.close()

    def test_i0666_every_trainhub_model_has_an_element(self):
        from masterquo.trainhub import learn
        ids = {e["id"] for e in self.MM.ELEMENTS}
        self.assertLessEqual(set(learn.MODELS), ids, set(learn.MODELS) - ids)

    def test_i0658_trainer_text_says_how_non_default_models_are_trained(self):
        from masterquo.trainhub import learn, pipeline
        th = {e["id"]: e for e in self.MM.ELEMENTS if e["id"] in learn.MODELS}
        self.assertEqual(set(th), set(learn.MODELS))
        for mid, e in th.items():
            if mid in pipeline.DEFAULTS["models"]:
                self.assertIn("domyślny zestaw bez --models", e["trainer"], mid)
            else:
                self.assertIn(f"--models {mid}", e["trainer"], mid)
                self.assertIn("--profile", e["trainer"], mid)
                self.assertIn("NIE w domyślnym zestawie", e["trainer"], mid)

    def test_i0012_every_registry_producer_is_in_the_map(self):
        m = self.MM.build(self.inv)
        self.assertEqual(m["schema"], "mq-model-map-2")
        ids = [e["id"] for e in m["elements"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), {e["id"] for e in self.inv["entries"] if e["category"] != "GROUP"})
        for cid in ("tsfm:tirex2", "trainhub:TH_RF", "trainhub:TH_SVM", "kronos:Kronos-small", "mm:event_engine_dir3", "quant:tabicl_v2"):
            self.assertIn(cid, ids)
        keys = {"id", "name", *self.MM.FIELDS}
        for e in m["elements"] + m["outside_registry"]:
            self.assertLessEqual(keys, set(e), e["id"])              # mq-model-map-1 element keys kept

    def test_i0012_overlay_folded_by_canonical_id_and_registry_tf(self):
        m = self.MM.build(self.inv)
        by = {e["id"]: e for e in m["elements"]}
        self.assertEqual(by["ml:legacy_s01_s12"]["legacy_ids"], ["LEGACY_ML_DT", "LEGACY_ML_XGB"])
        self.assertEqual(by["trainhub:TH_XGB"]["legacy_ids"], ["TH_XGB"])
        self.assertEqual(by["trainhub:TH_XGB"]["tf"], "M1, M5, M15, M30")          # registry, not the overlay text
        self.assertIn("--models TH_XGB", by["trainhub:TH_XGB"]["trainer"])
        self.assertEqual(by["lab:LOGREG"]["legacy_ids"], ["LAB_LOGREG"])
        outside = {e["id"] for e in m["outside_registry"]}
        self.assertEqual(outside, {"SCALP_PROFILE", "LAB_MARKOV", "LAB_ACD", "STRATEGIES_S01_S12"})
        md = self.MM.to_markdown(m)
        for e in m["elements"]:
            self.assertIn(f"## {e['id']} – ", md)
        self.assertIn("# Poza rejestrem kanonicznym", md)

    def test_i0012_alias_family_cards_take_tf_and_horizon_from_registry(self):
        import model_docs as MD
        reg = MD._registry()
        cat = {f["id"]: f for f in MD._catalog()}
        self.assertEqual(MD._tf_h(cat["TH_XGB"], reg), "M1, M5, M15, M30 / h świec (per paczka)")
        self.assertEqual(MD._tf_h(cat["SEQ_GRU_EVENT"], reg), "EVENT / 2 jednostki zdarzeń (16 zdarzeń/jednostka)")
        self.assertEqual(MD._tf_h(cat["TS_ARIMA"], reg), "M5 / 1, 3, 5")                    # own family: unchanged
        self.assertEqual(MD._tf_h(cat["MICROSTRUCTURE"], reg), "– / brak (pomiar stanu)")


# ============================================================================================== I0084 layer guard (lazy imports)
class TestLayerGuard(unittest.TestCase):
    """I0084: no layer map and no guard against lazy (function-level / dynamic) imports from a lower layer into a higher one - the cycle
    test only sees module-level imports. tools/cycles.py: layer map L0-L5 + every internal import with its line; today's upward pairs are
    the baseline (tests/data/layer_baseline.json); a NEW upward pair fails."""

    @classmethod
    def setUpClass(cls):
        import importlib

        import cycles
        cls.C = importlib.reload(cycles)

    def test_every_component_has_a_layer(self):
        self.assertEqual(self.C.unclassified(), [])

    def test_no_new_upward_edges(self):
        up = self.C.upward(self.C.edges())
        new, _gone = self.C.compare(up, self.C.load_baseline())
        self.assertEqual(new, [], "\n".join(f"{k}: {up[k]}" for k in new))

    def test_lazy_and_dynamic_upward_edges_are_detected(self):
        tmp = Path(tempfile.mkdtemp(prefix="mq_t_layers_"))
        try:
            pkg = tmp / "masterquo"
            for d in ("", "engine", "lab"):
                (pkg / d).mkdir(parents=True, exist_ok=True)
                (pkg / d / "__init__.py").write_text("", encoding="utf-8")
            (pkg / "paths.py").write_text("X = 1\n", encoding="utf-8")
            (pkg / "lab" / "y.py").write_text("from .. import paths\n", encoding="utf-8")
            (pkg / "engine" / "x.py").write_text(
                "from .. import paths\n\n\ndef f():\n    from ..lab import y\n    return y\n\n\ndef g():\n"
                "    return __import__('masterquo.lab.y')\n", encoding="utf-8")
            (pkg / "engine" / "z.py").write_text("import masterquo.lab.y\n", encoding="utf-8")
            up = self.C.upward(self.C.edges(pkg))
            self.assertEqual(up["masterquo.engine.x -> masterquo.lab.y"]["kinds"], ["DYNAMIC", "FUNCTION"])
            self.assertEqual(up["masterquo.engine.x -> masterquo.lab.y"]["lines"], [5, 10])
            self.assertEqual(up["masterquo.engine.z -> masterquo.lab.y"]["kinds"], ["MODULE"])
            self.assertNotIn("masterquo.engine.x -> masterquo.paths", up)                  # downward: allowed
            self.assertNotIn("masterquo.lab.y -> masterquo.paths", up)
            new, gone = self.C.compare(up, {"masterquo.engine.z -> masterquo.lab.y": {}, "masterquo.old -> masterquo.lab": {}})
            self.assertEqual(new, ["masterquo.engine.x -> masterquo.lab.y"])
            self.assertEqual(gone, ["masterquo.old -> masterquo.lab"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ============================================================================================== I0113 (+I0136) route inventory
ORDER_ROUTES = [("POST", "/api/v1/execute"), ("POST", "/api/v1/auto"), ("POST", "/api/v1/lab/tradepad/execute"),
                ("POST", "/api/v1/manual/intents/{iid}/execute"), ("POST", "/api/v1/manual/intents/{iid}/manage"),
                ("POST", "/api/v1/positions/close"), ("POST", "/api/v1/positions/{ticket}/adopt"), ("POST", "/api/v1/sh/plans/{pid}/close"),
                ("POST", "/api/v1/mode")]
ROUTE_PORT = 18797


def _mock_rt(edition: str = "OWNER"):
    rt = mock.MagicMock()
    rt.license.locked = False
    rt.license.edition = edition
    rt.cfg.get.return_value.assets.active = "XAUUSD"
    return rt


class TestRouteInventory(unittest.TestCase):
    """I0113 / I0136: no inventory of the ~520 routes; order routes without any client or test. The inventory is generated from
    create_app (tools/routes_inventory.py) and kept equal to it by this test; nothing is removed or blocked."""

    @classmethod
    def setUpClass(cls):
        import importlib

        import routes_inventory
        cls.td = _env.TempData()
        cls.RI = importlib.reload(routes_inventory)

    @classmethod
    def tearDownClass(cls):
        cls.td.close()

    def test_inventory_matches_app(self):
        self.assertTrue(self.RI.OUT.exists(), "brak docs/arch146/routes_inventory.json")
        self.assertEqual(self.RI.check(), [], "odśwież: python tools/routes_inventory.py")

    def test_order_routes_are_classified_execution(self):
        inv = json.loads(self.RI.OUT.read_text(encoding="utf-8"))
        cls = {(x["method"], x["path"]): x for x in inv["routes"]}
        for k in ORDER_ROUTES:
            self.assertEqual(cls[k]["class"], "EXECUTION", k)
        self.assertLessEqual(set(inv["by_class"]), {"EXECUTION", "PUBLIC", "INTERNAL", "LEGACY_UI141"})
        self.assertEqual(inv["total"], len(inv["routes"]))
        self.assertEqual(sum(inv["by_class"].values()), inv["total"])
        self.assertEqual(cls[("GET", "/api/v1/health")]["editions"], ["CLIENT", "OWNER"])
        self.assertTrue(any(x["editions"] == ["OWNER"] for x in inv["routes"]))           # owner-only routes are marked
        self.assertIn("POST /api/v1/execute", inv["execution_without_client"])

    def test_classification_rules(self):
        self.assertEqual(self.RI.classify(True, {"frontend": 3}), "EXECUTION")
        self.assertEqual(self.RI.classify(False, {"frontend": 1}), "PUBLIC")
        self.assertEqual(self.RI.classify(False, {"tests": 2, "archive_ui141": 1}), "LEGACY_UI141")
        self.assertEqual(self.RI.classify(False, {"tests": 2}), "INTERNAL")
        rx = self.RI._path_re("/api/v1/manual/intents/{iid}/execute")
        self.assertTrue(rx.search("post(`/api/v1/manual/intents/${id}/execute`)"))
        self.assertFalse(rx.search("'/api/v1/manual/intents/x/execute-more'"))


class TestExecutionRoutesGuarded(unittest.TestCase):
    """I0113 contract: every EXECUTION route needs the session cookie, the CSRF token and an allowed Origin - without them the handler
    (and the order path behind it) is never reached. Positive control: with all three the mocked service IS called."""

    def setUp(self):
        from fastapi.testclient import TestClient
        from masterquo.api import app as A
        self.td = _env.TempData()
        self.rt = _mock_rt()
        self.c = TestClient(A.create_app(self.rt, ROUTE_PORT), base_url=f"http://127.0.0.1:{ROUTE_PORT}")
        self.origin = {"Origin": f"http://127.0.0.1:{ROUTE_PORT}"}

    def tearDown(self):
        self.c.close()
        self.td.close()

    def _order_calls(self):
        rt = self.rt
        return [m.call_count for m in (rt.gateway.execute, rt.manual.execute, rt.manual.manage, rt.manager.close_positions, rt.manager.adopt,
                                       rt.sh.close_plan, rt.modes.set_auto, rt.modes.set_mode, rt.modes.set_primary_path)]

    def test_no_session_no_csrf_or_foreign_origin_never_reaches_the_order_path(self):
        for _m, path in ORDER_ROUTES:
            url = path.replace("{iid}", "I1").replace("{pid}", "P1").replace("{ticket}", "1")
            r = self.c.post(url, json={}, headers=self.origin)                              # no session cookie
            self.assertEqual((r.status_code, r.json().get("error")), (403, "CSRF_OR_SESSION_INVALID"), url)
        self.c.get("/")                                                                     # session cookie of the panel
        csrf = self.c.get("/api/v1/session").json()["csrf"]
        self.assertTrue(csrf)
        for _m, path in ORDER_ROUTES:
            url = path.replace("{iid}", "I1").replace("{pid}", "P1").replace("{ticket}", "1")
            r = self.c.post(url, json={}, headers=self.origin)                              # session, no CSRF header
            self.assertEqual(r.status_code, 403, url)
            r = self.c.post(url, json={}, headers={"Origin": "http://127.0.0.1:9", "X-MQ-CSRF": csrf})   # other local app
            self.assertEqual((r.status_code, r.json().get("error")), (403, "ORIGIN_NOT_ALLOWED"), url)
        self.assertEqual(self._order_calls(), [0] * 9)
        self.rt.gateway.execute.return_value = {"status": "BLOCKED"}
        r = self.c.post("/api/v1/execute", json={"decision_id": "MQD-X"}, headers={**self.origin, "X-MQ-CSRF": csrf})
        self.assertEqual(r.status_code, 200)
        self.rt.gateway.execute.assert_called_once_with("MQD-X", initiated_by="USER")


class TestExecuteRouteSignalsPaper(unittest.TestCase):
    """I0113 contract: POST /api/v1/execute through the route on the terminal simulator - SIGNALS blocks, PAPER fills on paper; in neither
    mode does the route reach order_send."""

    def setUp(self):
        from masterquo.engine.lifecycle import LifecycleStore
        from masterquo.execution.gateway import ExecutionGateway
        from masterquo.execution.manager import PositionManager
        from masterquo.execution.modes import ModeManager
        from masterquo.execution.paper import PaperBroker
        from test_risk_execution import LIMITS
        self.td = _env.TempData()
        cfg, db, bus, log, fake, worker, b = _env.core()
        self.db, self.fake, self.worker, self.b = db, fake, worker, b
        cfg.update({"execution": {"primary_path": {"XAUUSD": "ACTIVE"}}})
        cfg.update({"risk": LIMITS, "costs": {"slippage_stress_points": 5}})
        b.start()
        self.assertTrue(_env.wait_for(lambda: b.state == "CONNECTED" and b.quote_status() and b.symbol_info, 40))
        self.modes = ModeManager(cfg, db, bus, log, account_provider=lambda: (b.account_status(), b.account_key, b.synthetic))
        self.modes.set_mode("SIGNALS", account=None, account_key=None, synthetic=True)

        class Engine:
            decision = None

            def __init__(self, lc):
                self.lifecycle = lc

            def current_decision(self):
                return self.decision

            def mark_entered(self, setup_id, reason):
                self.lifecycle.terminate(setup_id, "ENTERED", reason)

        self.engine = Engine(LifecycleStore(db))
        paper = PaperBroker(cfg, b, db, bus, log)
        self.gw = ExecutionGateway(cfg, b, db, bus, log, self.modes, self.engine, paper)
        self.gw.manager = PositionManager(cfg, b, db, bus, log, self.modes, paper)
        self.gw.manager.reconciled_epoch = b.session_epoch
        from masterquo.api import app as A
        rt = _mock_rt()
        rt.gateway, rt.modes = self.gw, self.modes
        app = A.create_app(rt, ROUTE_PORT)
        self.route = next(r.endpoint for r in app.routes if getattr(r, "path", None) == "/api/v1/execute")
        self.ExecReq = A.ExecReq

    def tearDown(self):
        self.b.stop()
        self.worker.stop()
        self.td.close()

    def _decision(self, did):
        from datetime import UTC, datetime, timedelta
        e = self.b.quote_status()["bid"]
        return {"decision_id": did, "execution_permission": "ALLOWED", "expires_at_utc": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
                "account_key": self.b.account_key, "session_epoch": self.b.session_epoch, "symbol": "XAUUSD-", "analysis_direction": "SHORT",
                "reason_codes": [], "setup": {"setup_id": "MQS-" + did, "state": "CONFIRMED", "strategy_id": "XAU-S01"},
                "risk": {"risk_gate": "PASS", "lots": 0.05, "entry": e, "stop_loss": round(e + 8, 2),
                         "targets": [{"price": round(e - 6, 2), "weight": 0.5}, {"price": round(e - 12, 2), "weight": 0.5}], "modeled_loss": 41.0}}

    def test_signals_and_paper_never_call_order_send_through_the_route(self):
        calls = []
        self.fake.order_send = lambda r: calls.append(r)
        self.engine.decision = self._decision("MQD-S")
        r = self.route(self.ExecReq(decision_id="MQD-S"))
        self.assertEqual(r["status"], "BLOCKED")
        self.assertIn("EXECUTION_MODE_SIGNALS", r["reason"])
        self.modes.set_mode("PAPER", confirm="PAPER", account=self.b.account_status(), account_key=self.b.account_key, synthetic=True)
        self.engine.decision = self._decision("MQD-P")
        r = self.route(self.ExecReq(decision_id="MQD-P"))
        self.assertEqual((r["status"], r.get("paper")), ("FILLED", True))
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
