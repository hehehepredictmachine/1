"""Fala 2 / grupa tools_cli (Apollo23 1.46): narzędzia, CLI i warstwy tylko-do-odczytu bez wpływu na decyzje handlowe.

I0480 (build terminala w statusie natywnym MiniRocket v2), I0137 (`studio --port`), I0132 (pomoc train-all, martwe flagi),
I0658 / I0666 / I0012 (mapa modeli z rejestru kanonicznego, karty rodzin-aliasów), I0084 (strażnik warstw / importów leniwych),
I0113 / I0136 (inwentarz tras API + testy kontraktowe tras wykonawczych), I0028 / I0037 (widok ledgerów PMW-LEDGER-VIEW-1),
I0021 (słownik cech PMW-FEAT-DICT-1). Testy poprawek nie przechodzą na kodzie sprzed poprawki; testy kontraktowe tras wykonawczych
(brakujące testy) potwierdzają dzisiejsze zachowanie. Bez serwera HTTP (TestClient w procesie), bez MT5 (FakeMT5), bez zleceń;
dane rynkowe SYNTETYCZNE.
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

    def test_help_and_docstring_match_the_runner_scalp_bc_come_with_scalp_a(self):
        # uwaga recenzenta: pomoc i docstring twierdziły, że scalp_B/C trenuje tylko `training run` bez --tasks - nieprawda:
        # runner.build_plan dokłada scalp_B/C do zadań, gdy jest scalp_A (jeden proces scalp_train), --skip-candles pomija wszystkie trzy
        from masterquo import train_all as TA
        from masterquo.training import runner as R
        plan, _ = R.build_plan(instruments=["XAUUSD"], profile="TEST_INSTALACJI", symbols={}, commissions={}, months=None, synthetic=True,
                               tasks=[t for t, _ in TA.TRAIN_ALL_TASKS])
        always = ("export", "quality", "activate", "bot")
        self.assertIn("scalp_B", plan["requested_tasks"])
        self.assertIn("scalp_C", plan["requested_tasks"])
        outside = [k for k, _ in R.TASKS if k not in plan["requested_tasks"] and k not in always]
        self.assertEqual(outside, ["sh_models", "sh_pack", "monte_carlo", "master_models"])
        self.assertEqual(list(TA.NOT_IN_TRAIN_ALL), outside)
        sub = self._help("train-all")
        rest = sub.split("trenuje też:", 1)[1].split(".", 1)[0]            # zadania tylko `training run` bez --tasks
        self.assertEqual([x.strip() for x in rest.split(",")], outside)
        self.assertNotIn("scalp_B", rest)
        self.assertIn("scalp_A (+ scalp_B/C", sub)
        self.assertRegex(sub, r"--skip-candles\s+pomiń forecast, scalp_A/B/C, indicator_context")
        doc = " ".join((TA.__doc__ or "").split())
        self.assertNotIn("scalp_B / scalp_C, sh_models", doc)
        self.assertIn("scalp_B / scalp_C are produced together with scalp_A", doc)
        self.assertIn("only sh_models, sh_pack, monte_carlo and master_models", doc)
        self.assertIn("--skip-candles (forecast + scalp_A/B/C + indicator_context)", doc)

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
        self.assertEqual(self.C.unclassified(), [], "dopisz komponent do tools/cycles.LAYERS (i do tabeli ETAP2_PROJEKT §3a)")

    def test_merged_wave2b_components_are_classified(self):
        # I0084 (integracja): komponenty dodane przez scalone grupy fali 2b - liście L0 i usługi Runtime w L5
        for name, layer in (("contracts", 0), ("settings_store", 0), ("localapi", 0), ("runtimes", 0), ("wf32_services", 5)):
            self.assertEqual(self.C.LAYERS.get(name), layer, name)

    def test_no_new_upward_edges(self):
        up = self.C.upward(self.C.edges())
        new, _gone = self.C.compare(up, self.C.load_baseline())
        self.assertEqual(new, [], "\n".join(f"{k}: {up[k]}" for k in new)
                         + "\nprzejrzyj nowe pary; zamierzone -> python tools/cycles.py --write-baseline")

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


# ============================================================================================== I0028 / I0037 ledger view
MAIN_TABLES = {"ml_predictions", "ml_scalp_predictions", "forecast_shadow", "scalp_shadow", "lab_forecasts", "nss_inferences", "si_forecasts",
               "quote_forecasts", "kronos_forecasts", "tsfm_forecasts", "ai_signals", "si_outcomes", "quote_outcomes", "ml_samples",
               "ml_scalp_samples"}
T0 = 1_790_000_000.0                                                    # 2026-09-21 UTC (fixed)


def _iso(t: float) -> str:
    from datetime import UTC, datetime
    return datetime.fromtimestamp(t, UTC).isoformat().replace("+00:00", "Z")


def _insert(db, table: str, **vals) -> None:
    """One fixture row: NOT NULL columns without a default get a placeholder of their type, the rest is given explicitly."""
    for c in db.query(f'PRAGMA table_info("{table}")'):
        if c["name"] in vals or not c["notnull"] or c["dflt_value"] is not None or (c["pk"] and "INT" in (c["type"] or "").upper()):
            continue
        vals[c["name"]] = 0 if (c["type"] or "").upper() in ("INTEGER", "REAL", "INT", "FLOAT") else "x"
    cols = ", ".join(vals)
    db.execute(f'INSERT INTO "{table}"({cols}) VALUES ({", ".join("?" * len(vals))})', tuple(vals.values()))


class TestLedgerView(unittest.TestCase):
    """I0028: no common format for 15 tables + 3 files (keys, times, statuses, instrument ids). I0037: status vocabularies
    (SCORED / SETTLED / MATURED / LABELED / LABELLED, 6 'no data' names) and time columns with different meanings (decision_time = plan,
    dequeue or processing time). masterquo/ledgers/view.py: read-only PMW-LEDGER-VIEW-1, writers and data unchanged."""

    def setUp(self):
        self.td = _env.TempData()
        self.data = Path(self.td.dir)

    def tearDown(self):
        self.td.close()

    def test_registry_covers_15_tables_and_3_files(self):
        from masterquo.ledgers import view as LV
        self.assertEqual({a.table for a in LV.ADAPTERS.values() if set(a.stores) & {"main", "ml"}}, MAIN_TABLES)
        self.assertEqual({k for a in LV.ADAPTERS.values() for k in a.stores} - {"main", "ml"}, {"mm", "evaluation", "quant"})
        self.assertEqual({a.table for a in LV.ADAPTERS.values() if "quant" in a.stores}, {"rows", "assessments"})
        self.assertEqual(set(LV.OUTCOME_STATUSES), {"PENDING", "SCORED", "NO_DATA", "OUT_OF_BUFFER", "EXCLUDED", "NOT_APPLICABLE", "INVALID"})

    def test_store_paths_are_the_writers_paths_and_the_view_creates_nothing(self):
        import mq_instruments as mi
        from masterquo.db.database import Database
        from masterquo.evaluation import service as ES
        from masterquo.ledgers import view as LV
        from masterquo.mm import artifacts
        from masterquo.quant import service as QS
        st = {s.id: s for s in LV.stores()}
        self.assertEqual(list(self.data.rglob("*")), [])                    # registry only: no file, no folder
        self.assertEqual(list(LV.records("nss_inferences")), [])
        self.assertEqual(list(self.data.rglob("*")), [])
        self.assertEqual(st["main"].path, Database().path)
        for inst in mi.profiles():
            self.assertEqual(st[f"mm:{inst}"].path, artifacts.root(inst) / "ledger.sqlite")
            if inst != mi.DEFAULT:
                self.assertEqual(st[f"ml:{inst}"].path, mi.root("ml", inst) / "ml.sqlite")
        self.assertEqual(st["evaluation"].path, ES._default_dir() / "ledger.sqlite")
        self.assertEqual(st["quant"].path, QS.qdir() / "ledger.sqlite")

    def test_read_only_connection_refuses_writes(self):
        import sqlite3

        from masterquo.db.database import Database
        from masterquo.ledgers import view as LV
        db = Database()
        db.query("SELECT 1")
        c = LV.connect_ro(db.path)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                c.execute("INSERT INTO lab_forecasts(forecast_id, asset, module, tf, issued_as_of, payload) VALUES ('a','b','c','d','e','f')")
        finally:
            c.close()
        with self.assertRaises(FileNotFoundError):
            LV.connect_ro(self.data / "nope.sqlite")
        self.assertFalse((self.data / "nope.sqlite").exists())

    def _fill(self):
        from masterquo.db.database import Database
        from masterquo.evaluation import service as ES
        from masterquo.ml.router import ml_store
        from masterquo.mm import artifacts
        from masterquo.mm.ledger import Ledger
        from masterquo.quant import service as QS
        from masterquo.quant.ledger import QuantLedger
        db = Database()
        i = _iso
        _insert(db, "ml_predictions", at=i(T0), setup_id="S1", setup_version=1, model_id="DT-1", role="OBSERVE", raw_score=0.4,
                calibrated_probability=0.55, readiness="READY", contract_json="{}")
        _insert(db, "ml_scalp_predictions", prediction_id="P1", sample_id="SS1", model_hash="h", role="OBSERVE", instrument="XAUUSD", side="BUY",
                as_of=i(T0), computed_at=i(T0 + 2), expires_at=i(T0 + 60), status="OK", p=0.6)
        _insert(db, "forecast_shadow", created_at=i(T0 + 1), run_id="R1", feature_time_utc=i(T0), horizon_minutes=15, target_time_utc=i(T0 + 900),
                p_down=0.2, p_flat=0.5, p_up=0.3, outcome_status="SCORED", outcome_close=2650.0, outcome_class="UP", scored_at=i(T0 + 1000),
                instrument="XAUUSD")
        _insert(db, "scalp_shadow", created_at=i(T0 + 1), setup_id="SC1", profile_id="P", direction="BUY", decision_time_utc=i(T0),
                status="READY_SHADOW", plan="{}", outcome_status="SETTLED", outcome='{"exits": []}', net_r=0.8, settled_at=i(T0 + 600),
                instrument="XAUUSD")
        _insert(db, "scalp_shadow", created_at=i(T0 + 2), setup_id="SC2", profile_id="P", direction="SELL", decision_time_utc=i(T0),
                status="READY_SHADOW", plan="{}", outcome_status="NO_DATA", settled_at=i(T0 + 9000), instrument="XAUUSD")
        _insert(db, "lab_forecasts", forecast_id="L1", asset="XAUUSD", module="M29", tf="M5", issued_as_of=i(T0), payload='{"p": 0.5}')
        _insert(db, "nss_inferences", inference_id="N1", request_id="Q1", task_id="T", instrument="XAUUSD", setup_id="SC1", side="BUY",
                signal_time=i(T0), decision_time=i(T0 + 5), computed_at=i(T0 + 6), label_status="LABELED", label_event="TP1_FIRST",
                label_net_r=1.1, label_end=i(T0 + 300), label_available_at=i(T0 + 360))
        _insert(db, "si_forecasts", instrument="XAUUSD", task_id="M1_MOVE", model_id="SI-A", as_of=i(T0), horizon=5, emitted_at=i(T0 + 1),
                payload="{}")
        _insert(db, "si_outcomes", forecast_id=1, data_revision=0, matured_at=i(T0 + 400), r_h=0.3, label="UP", status="MATURED")
        _insert(db, "quote_forecasts", forecast_id="QF1", context="c", side="BUY", scale="s", issued_at=i(T0), target_at=i(T0 + 60), payload="{}")
        _insert(db, "quote_outcomes", forecast_id="QF1", status="SCORED", scored_at=i(T0 + 70), outcome="{}")
        for t in ("kronos_forecasts", "tsfm_forecasts"):
            _insert(db, t, forecast_id=f"{t}-1", created_at=i(T0), instrument="XAUUSD", symbol="XAUUSD-", timeframe="M5", horizon_bars=6,
                    outcome_status="OUT_OF_BUFFER", settled_at=i(T0 + 7200), data_kind="REAL")
        _insert(db, "ai_signals", signal_id="A1", created_at=i(T0), updated_at=i(T0), symbol="XAUUSD-", status="WIN", action="BUY",
                outcome_r=1.2, closed_at=i(T0 + 900), synthetic=1)
        _insert(db, "ml_samples", sample_id="MS1", setup_id="S1", setup_version=1, symbol="XAUUSD-", strategy_id="XAU-S01", direction="LONG",
                timeframe="M5", asof_utc=i(T0), status="LABELED", outcome_r=0.5, label_end_utc=i(T0 + 600), label_known_utc=i(T0 + 660),
                source="LIVE", synthetic=0, created_at=i(T0), updated_at=i(T0))
        _insert(db, "ml_scalp_samples", sample_id="SS1", instrument="XAUUSD", side="BUY", signal_time=i(T0), decision_time=i(T0 + 4),
                status="NO_EXECUTABLE_ENTRY", created_at=i(T0 + 4))
        btc_db, _ = ml_store("BTC")                                             # the writers' own BTC ML space
        _insert(btc_db, "ml_samples", sample_id="MS-BTC", setup_id="S9", setup_version=1, symbol="BTCUSDT-", strategy_id="BTC-S01",
                direction="SHORT", timeframe="M5", asof_utc=i(T0), status="PENDING", source="BACKFILL_X", synthetic=0, created_at=i(T0),
                updated_at=i(T0))
        btc_db.close()
        mm = Ledger(artifacts.root("XAUUSD") / "ledger.sqlite")
        mm.log(pred_id="MM1", model_id="mm:gpr", artifact_id="a", feature_schema="F", symbol="XAUUSD-", timeframe="M5", source_ts=T0,
               available_at=T0 + 1, matures_at=T0 + 900, horizon="3", kind="REG", payload={"mu": 0.1}, quality="OK")
        mm.mature(T0 + 1000, lambda r: {"err": 0.01})
        mm.c.close()
        ev = Ledger(ES._default_dir() / "ledger.sqlite")
        ev.log(pred_id="E1", model_id="PMW-EVAL/SH", artifact_id=None, feature_schema=None, symbol="XAUUSD-", timeframe="M1", source_ts=T0,
               available_at=T0, matures_at=T0 + 60, horizon="H", kind="P", payload={}, quality="OK")
        ev.mature(T0 + 100, lambda r: {"status": "NO_BARS", "reason": "x"})
        ev.c.close()
        q = QuantLedger(QS.qdir() / "ledger.sqlite")
        q.add_row({"row_id": "QR1", "instrument": "XAUUSD", "engine": "SH", "strategy": "s", "direction": "BUY", "decision_ts": T0, "task_hash": "th",
                   "event_id": "ev", "spec": {}, "features": {}, "matures_at": T0 + 600})
        q.label("QR1", "LABELLED", {"y_event": 1, "net_r": 0.7}, T0 + 500)
        q.add_assessment({"assessment_id": "QA1", "row_id": "QR1", "created_at": time.time(), "mode": "SHADOW", "direction": "BUY"})
        q.c.close()
        db.close()

    def test_every_adapter_maps_a_fixture_row_to_the_canonical_record(self):
        from masterquo.ledgers import view as LV
        self._fill()
        seen = {}
        for name in LV.ADAPTERS:
            recs = list(LV.records(name))
            self.assertTrue(recs, name)
            for r in recs:
                self.assertLessEqual(set(LV.REQUIRED), set(r), name)
                self.assertIn(r["outcome_status"], LV.OUTCOME_STATUSES, name)
                self.assertEqual(r["pred_id"], f"{name}:{r['source_key']}")
                self.assertEqual(r["view"], "PMW-LEDGER-VIEW-1")
                self.assertIsInstance(r["raw"], dict)
            seen[name] = recs
        by = {n: {r["source_key"]: r for r in rs} for n, rs in seen.items()}
        self.assertEqual(by["ml_samples"]["MS-BTC"]["instrument"], "BTC")
        self.assertEqual(by["ml_samples"]["MS-BTC"]["run_mode"], "REPLAY")
        self.assertEqual(by["ml_samples"]["MS1"]["instrument"], "XAUUSD")
        self.assertEqual([r["source_key"] for r in LV.records("ml_samples", instrument="BTC")], ["MS-BTC"])
        self.assertEqual(by["ai_signals"]["A1"]["data_kind"], "SYNTHETIC")
        self.assertEqual(by["kronos_forecasts"]["1"]["outcome_status"], "OUT_OF_BUFFER")
        self.assertEqual(by["mm_predictions"]["MM1"]["instrument"], "XAUUSD")
        self.assertEqual(by["mm_predictions"]["MM1"]["outcome_status"], "SCORED")
        self.assertEqual((by["evaluation"]["E1"]["outcome_status"], by["evaluation"]["E1"]["status_raw"]), ("NO_DATA", "NO_BARS"))
        self.assertEqual(by["forecast_shadow"]["1"]["horizon"], {"seconds": 900})
        self.assertEqual(by["quant_assessments"]["QA1"]["outcome_status"], "NOT_APPLICABLE")
        self.assertEqual(by["si_outcomes"]["1:0"]["link_ids"], {"forecast_id": 1})

    def test_i0037_one_status_vocabulary_and_plan_time_as_decision_ts(self):
        from masterquo.ledgers import view as LV
        self._fill()
        one = {n: {r["source_key"]: r for r in LV.records(n)} for n in ("quant_rows", "nss_inferences", "scalp_shadow", "si_outcomes",
                                                                          "ml_scalp_samples", "ml_scalp_predictions")}
        for n, k, raw in (("quant_rows", "QR1", "LABELLED"), ("nss_inferences", "N1", "LABELED"), ("scalp_shadow", "1", "SETTLED"),
                          ("si_outcomes", "1:0", "MATURED")):
            self.assertEqual((one[n][k]["outcome_status"], one[n][k]["status_raw"]), ("SCORED", raw), n)
        n1 = one["nss_inferences"]["N1"]
        self.assertEqual((n1["decision_ts"], n1["processed_at"]), (T0, T0 + 5))           # plan time, not the dequeue time
        self.assertEqual((n1["outcome_event_ts"], n1["matured_at"]), (T0 + 300, T0 + 360))
        ss = one["ml_scalp_samples"]["SS1"]
        self.assertEqual((ss["decision_ts"], ss["processed_at"], ss["outcome_status"]), (T0, T0 + 4, "EXCLUDED"))
        self.assertEqual(one["ml_scalp_predictions"]["P1"]["decision_ts"], T0)
        settled, nodata = one["scalp_shadow"]["1"], one["scalp_shadow"]["2"]
        self.assertEqual((settled["outcome_event_ts"], settled["matured_at"]), (T0 + 600, None))   # SETTLED: settled_at = label_end
        self.assertEqual((nodata["outcome_event_ts"], nodata["matured_at"], nodata["outcome_status"]), (None, T0 + 9000, "NO_DATA"))
        for raw, want in (("DATA_GAP", "NO_DATA"), ("NO_CONTINUOUS_DATA", "NO_DATA"), ("EXCLUDED_GAP", "NO_DATA"), ("UNSCORED_GAP", "NO_DATA"),
                          ("MISSED_LIMIT", "EXCLUDED"), ("OUT_OF_BUFFER", "OUT_OF_BUFFER"), ("PENDING", "PENDING"), ("ERROR", "INVALID")):
            self.assertEqual(LV.canonical_status(raw)[0], want, raw)
        self.assertEqual(LV.canonical_status("WHATEVER"), ("INVALID", "UNKNOWN_STATUS:WHATEVER"))
        self.assertEqual(LV._t("2026-09-21T00:00:00Z"), LV._t("2026-09-21T00:00:00+00:00"))


# ============================================================================================== I0021 feature dictionary
def _synthetic_bars(n: int = 320, seed: int = 11):
    """SYNTHETIC M5 random walk (checks formulas, not market behaviour)."""
    import numpy as np
    rng = np.random.default_rng(seed)
    c = 2650.0 + np.cumsum(rng.normal(0, 1.2, n))
    o = np.r_[c[0], c[:-1]] + rng.normal(0, 0.2, n)
    h = np.maximum(o, c) + np.abs(rng.normal(0, 0.8, n))
    lo = np.minimum(o, c) - np.abs(rng.normal(0, 0.8, n))
    tv = rng.integers(50, 400, n).astype(float)
    t = 1_790_000_000 - (1_790_000_000 % 300) + 300 * np.arange(n)
    return t, o, h, lo, c, tv


class TestFeatureDictionary(unittest.TestCase):
    """I0021: the same feature names mean different formulas / units across the lab, mm, ml, trainhub and scalp registries.
    masterquo/features/catalog.py maps every registry name to a canonical entry (unit, window, seed, impl, aliases) - metadata only."""

    def test_every_registry_name_has_an_entry_and_no_alias_is_stale(self):
        from masterquo.features import catalog as FC
        names = FC.registry_names()
        self.assertEqual(set(names), set(FC.REGISTRIES))
        for reg, ns in names.items():
            self.assertTrue(ns, reg)
            for n in ns:
                r = FC.resolve(reg, n)
                self.assertTrue(r["canonical"], (reg, n))
        self.assertEqual(FC.resolve("ml", "M15_ret1")["tf"], "M15")
        self.assertEqual(FC.resolve("trainhub", "M30_rsi14")["canonical"], "rsi14_wilder_centered_th_seed")
        for e in FC.CANONICAL:
            for reg, al in e.aliases.items():
                live = {FC._split_tf(reg, n)[1] for n in names[reg]}
                self.assertLessEqual(set(al), live, (e.name, reg))                    # every declared alias exists in its registry
        d = FC.dictionary()
        self.assertEqual(d["version"], "PMW-FEAT-DICT-1")
        self.assertEqual(sorted(d["entries"]["range_over_atr14_wilder"]["aliases"]), ["lab", "ml", "scalp", "trainhub"])

    def test_same_name_different_formula_gets_different_canonical_names(self):
        from masterquo.features import catalog as FC
        c = lambda reg, n: FC.resolve(reg, n)["canonical"]
        self.assertEqual((c("lab", "range_rel"), c("mm", "range_rel")), ("range_over_atr14_wilder", "range_over_close"))
        self.assertEqual(len({c("lab", "ret_1"), c("mm", "ret_1"), c("ml", "M5_ret1"), c("scalp", "ret1")}), 4)
        self.assertEqual((c("lab", "ret_1"), c("mm", "ret_1")), ("ret_simple_1", "ret_log_1"))
        self.assertEqual(c("mm", "ret_1"), c("trainhub", "M5_r1"))                        # both ln(C/C[-1])
        self.assertEqual(len({c("mm", "rsi_14"), c("trainhub", "M5_rsi14"), c("ml", "M5_rsi")}), 3)
        self.assertEqual(len({c("lab", "tv_pct"), c("mm", "tv_rel_48"), c("trainhub", "M5_tick_ratio"), c("ml", "M5_tick_activity"),
                              c("scalp", "tv_log_ratio")}), 5)
        self.assertEqual(len({c("mm", "body_rel"), c("ml", "M5_body"), c("trainhub", "M5_body_atr")}), 3)
        self.assertEqual(c("ml", "M5_body"), c("scalp", "body_ratio"))
        self.assertEqual(len({c("lab", "hour_sin"), c("ml", "hour_sin"), c("scalp", "hour_sin")}), 3)
        self.assertEqual(c("lab", "hour_sin"), c("trainhub", "M5_tod_sin"))
        # a base name present in several registries shares a canonical name ONLY through an explicit (declared) entry
        names = FC.registry_names()
        by_base: dict[str, list[tuple[str, str]]] = {}
        for reg, ns in names.items():
            for n in ns:
                by_base.setdefault(FC._split_tf(reg, n)[1], []).append((reg, n))
        for base, occ in by_base.items():
            regs = {r for r, _ in occ}
            if len(regs) < 2:
                continue
            canon = {(r, c(r, n)) for r, n in occ}
            shared = {k for k in {x for _, x in canon} if len({r for r, x in canon if x == k}) > 1}
            for k in shared:
                self.assertFalse(k.split(":")[0] in FC.REGISTRIES, (base, k))             # never a registry-scoped name

    def test_impl_points_to_an_existing_function(self):
        import importlib

        from masterquo.features import catalog as FC
        for name, e in FC.dictionary()["entries"].items():
            mod, fn = e["impl"].split(":")
            self.assertTrue(callable(getattr(importlib.import_module(mod), fn)), name)

    def test_shared_canonical_entries_are_numerically_equal_and_split_ones_differ(self):
        import types

        import numpy as np
        from gold_candles_runtime import scalp_features as SF
        from masterquo.lab import features as LF
        from masterquo.mm import features as MMF
        from masterquo.trainhub import features as TF
        t, o, h, lo, c, tv = _synthetic_bars()
        lab = LF.feature_matrix([{"open_utc": _iso(float(t[i])), "o": o[i], "h": h[i], "l": lo[i], "c": c[i], "tv": tv[i]} for i in range(len(c))],
                                "M5")
        L = {n: lab["X"][:, j] for j, n in enumerate(lab["features"])}
        mmx = MMF.features(types.SimpleNamespace(c=c, o=o, h=h, l=lo, tv=tv), ["ret_1", "range_rel", "atr_rel_14", "rsi_14"])
        M = {"ret_1": mmx[:, 0], "range_rel": mmx[:, 1], "atr_rel_14": mmx[:, 2], "rsi_14": mmx[:, 3]}
        thx = TF._base({"time": list(t), "open": list(o), "high": list(h), "low": list(lo), "close": list(c), "tick_volume": list(tv),
                        "spread": [20.0] * len(c)}, "M5", 0.01)
        T = {n: thx[:, j] for j, n in enumerate(TF.BASE_NAMES)}
        sx, _atr = SF.build(list(t), list(o), list(h), list(lo), list(c), list(tv), [0.2] * len(c))
        S = {n: sx[:, j] for j, n in enumerate(SF.FEATURES)}

        def same(a, b):
            ok = np.isfinite(a) & np.isfinite(b)
            self.assertGreater(ok.sum(), 200)
            np.testing.assert_allclose(a[ok], b[ok], rtol=1e-9, atol=1e-12)

        same(M["ret_1"], T["r1"])                                                       # ret_log_1
        same(L["range_rel"], T["rng_atr"])                                              # range_over_atr14_wilder
        same(L["range_rel"], S["r_atr"])
        same(L["atr_rel"], M["atr_rel_14"])                                             # atr14_over_close
        same(L["atr_rel"], T["atr_rel"])
        same(L["hour_sin"], T["tod_sin"])                                               # hour_of_close_sin
        same(L["bb_pctb"], S["bb_pctb"])                                                # bb_pctb_sma20_2sd
        same(L["bb_pctb"], L["z20"] / 4 + 0.5)                                          # I0026 note
        ok = np.isfinite(L["range_rel"]) & np.isfinite(M["range_rel"])
        self.assertFalse(np.allclose(L["range_rel"][ok], M["range_rel"][ok]))           # same name, different feature
        self.assertGreater(abs(M["rsi_14"][14] - T["rsi14"][14]), 1e-4)                 # RSI seeds differ -> two canonical entries
        self.assertLess(abs(M["rsi_14"][-1] - T["rsi14"][-1]), 1e-6)


if __name__ == "__main__":
    unittest.main()
