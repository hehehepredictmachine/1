"""Training installer 1.15 (masterquo/training) on the SYNTHETIC terminal, in a data folder whose path has spaces, Polish
letters and '!'. Windows + a real MT5 are not available here - those runs are reported as NOT EXECUTED in the test report.

Covers: plan -> export per instrument (exact symbol, USD vs USDT kept) -> quality -> gold_candles / scalp A-B-C / legacy ML /
lab for XAUUSD and BTC with separate datasets, registries and artefacts (no instrument mixing); three-axis statuses; synthetic
models never activated; lab artefact = the development-only fit (no refit inheriting the verdict) with loader parity;
bot config untouched (use_backfill_approx stays false, Execution Lock LOCKED); cancel + resume without repeating finished
tasks; 22_TRENUJ_WSZYSTKIE_MODELE (train-all) uses the same mechanism; report HTML/JSON with counts from the run."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

import _env
from _env import TempData, wait_for

PY = sys.executable
CANDLES = os.environ.get("MQ_CANDLES_PYTHON")


class _Base(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.data = Path(self.td.dir) / "dane treningu ąę !x"
        self.data.mkdir()
        with open(self.data / "config.json", "w", encoding="utf-8") as f:
            json.dump({"server": {"port": 8813, "open_browser": False}, "news": {"enabled": False}, "clock": {"reference_url": None},
                       "first_run_completed": True}, f)
        self.env = dict(os.environ, MASTERQUO_DATA_DIR=str(self.data), PYTHONPATH=str(_env.ROOT / "backend"), MQ_NO_BROWSER="1",
                        MQ_FAKE_MARKET_ALWAYS_OPEN="1")
        self.env.pop("ANTHROPIC_API_KEY", None)

    def tearDown(self):
        self.td.close()

    def cli(self, *args, timeout=3000):
        return subprocess.run([PY, "-m", "masterquo", *args], env=self.env, cwd=str(_env.ROOT / "backend"), capture_output=True, text=True,
                              timeout=timeout, encoding="utf-8", errors="replace")

    def state(self):
        p = sorted((self.data / "training" / "runs").glob("*/state.json"))[-1]
        return json.loads(p.read_text(encoding="utf-8"))


@unittest.skipUnless(CANDLES, "MQ_CANDLES_PYTHON (.venv_candles) wymagane do treningu prognoz/scalp")
class TestTrainingRun(_Base):
    def test_both_instruments_end_to_end(self):
        r = self.cli("training", "run", "--demo", "--profile", "TEST_INSTALACJI", "--months", "1", "--commission-btc", "2.0")
        self.assertIn(r.returncode, (0, 4), r.stdout[-3000:] + r.stderr[-2000:])
        self.assertIn("PODSUMOWANIE: XAUUSD:", r.stdout)
        st = self.state()
        tasks = {t["id"]: t for t in st["tasks"]}
        self.assertEqual(st["plan"]["instruments"], ["XAUUSD", "BTC"])                 # XAUUSD first, then BTC
        self.assertEqual(st["plan"]["symbols"], {"XAUUSD": "XAUUSD-", "BTC": "BTCUSDT-"})  # exact symbol, never BTCUSD substituted
        for inst, prefix, quote in (("XAUUSD", "XAUUSD", "USD"), ("BTC", "BTC", "USDT")):
            ex = tasks[f"{inst}:export"]
            self.assertEqual(ex["execution"], "UKONCZONE", ex)
            meta = json.loads((Path(ex["dataset_dir"]) / "source_metadata.json").read_text(encoding="utf-8"))
            self.assertEqual((meta["instrument"], meta["quote_currency"], meta["data_kind"]), (inst, quote, "SYNTHETIC_TEST"))
            self.assertTrue((Path(ex["dataset_dir"]) / f"{prefix}_M1.csv").exists() and (Path(ex["dataset_dir"]) / f"{prefix}_D1.csv").exists())
            self.assertIn(st["run_id"], ex["dataset_dir"])                                # explicit dataset of THIS run
            for k in ("forecast", "scalp_A", "lab"):
                t = tasks[f"{inst}:{k}"]
                self.assertEqual(t["execution"], "UKONCZONE", t)
                self.assertEqual(t["quality"], "TEST_TECHNICZNY", t)                       # synthetic -> technical test, never "validated"
                self.assertNotIn(t["integration"], ("AKTYWNY_W_REJESTRZE", "ZALADOWANY_DO_SHADOW"))
            self.assertIn("nie sieć", tasks[f"{inst}:scalp_C"]["detail"])                 # policy evaluation, not a network
            self.assertIn(tasks[f"{inst}:ml"]["execution"], ("UKONCZONE",))
            self.assertIn("bez aktywacji", tasks[f"{inst}:activate"]["detail"])
            self.assertEqual(tasks[f"{inst}:forecast"]["parity"]["status"], "OK")          # bot loader == batch training features
            self.assertTrue(tasks[f"{inst}:forecast"]["parity"]["foreign_contract"].startswith("REJECTED"))
        # separate spaces per instrument: XAUUSD keeps the historical paths, BTC has its own
        fx = json.loads((self.data / "forecast" / "registry.json").read_text(encoding="utf-8"))
        fb = json.loads((self.data / "instruments" / "BTC" / "forecast" / "registry.json").read_text(encoding="utf-8"))
        self.assertEqual({e["symbol"] for e in fx["runs"].values()}, {"XAUUSD-"})
        self.assertEqual({e["symbol"] for e in fb["runs"].values()}, {"BTCUSDT-"})
        self.assertEqual({e["grid_step"] for e in fb["runs"].values()}, {500.0})           # BTC profile, not the gold grid
        self.assertIsNone(fx["active"])
        self.assertIsNone(fb["active"])                                                    # synthetic never activated
        sb = json.loads((self.data / "instruments" / "BTC" / "scalp" / "registry.json").read_text(encoding="utf-8"))
        self.assertTrue(all(e["instrument"] == "BTC" and e["costs"]["commission_source"] == "USER_ARGUMENT" for e in sb["runs"].values()))
        self.assertTrue((self.data / "instruments" / "BTC" / "ml" / "ml.sqlite").exists())
        for inst in ("XAUUSD", "BTC"):
            mans = [json.loads(p.read_text(encoding="utf-8")) for p in (self.data / "lab" / "models" / inst).glob("*/manifest.json")]
            self.assertEqual({m["family"] for m in mans}, {"LOGREG", "SEW_SNN"})          # all requested families except the DUMMY baseline
            for m in mans:
                self.assertEqual((m["asset"], m["side"], m["role"]), (inst, "LONG", "fixture_only"))
                self.assertTrue(m["fit_scope"].startswith("DEVELOPMENT_ONLY"))
                self.assertEqual(m["loader_parity"]["status"], "OK")
                self.assertEqual(m["loader_parity"]["foreign_asset"], "REJECTED")
        # produced files carry every field required by the published schemas (docs/schemas)
        sch = lambda n: json.loads((_env.ROOT / "docs" / "schemas" / n).read_text(encoding="utf-8"))["required"]  # noqa: E731
        self.assertLessEqual(set(sch("training_run_state.schema.json")), set(st))
        self.assertLessEqual(set(sch("dataset_source_metadata.schema.json")), set(meta))
        self.assertLessEqual(set(sch("lab_artifact_manifest.schema.json")), set(mans[0]))
        self.assertLessEqual(set(sch("forecast_registry_entry.schema.json")), set(next(iter(fb["runs"].values()))))
        # bot config untouched by the installer
        cfg = json.loads((self.data / "config.json").read_text(encoding="utf-8"))
        self.assertFalse((cfg.get("ml") or {}).get("use_backfill_approx", False))
        self.assertNotEqual((cfg.get("execution") or {}).get("lock"), "UNLOCKED_BY_USER")             # Execution Lock never touched
        rep = json.loads((self.data / "training" / "runs" / st["run_id"] / "report.json").read_text(encoding="utf-8"))
        line = rep["summary"]["line"]
        self.assertRegex(line, r"XAUUSD: \d+/15 zadań ukończonych; BTC: \d+/15")
        self.assertTrue((self.data / "training" / "runs" / st["run_id"] / "report.html").exists())
        # rollback of a lab family uses the per-family pointer
        r = self.cli("training", "rollback", "--instrument", "BTC", "--family", "lab:LOGREG")
        self.assertEqual(r.returncode, 2)                                                   # nothing activated before -> honest refusal
        self.assertIn("NO_PREVIOUS_MODEL", r.stdout)


class TestCancelResume(_Base):
    def test_cancel_then_resume_does_not_repeat_finished_tasks(self):
        p = subprocess.Popen([PY, "-m", "masterquo", "training", "run", "--demo", "--profile", "TEST_INSTALACJI", "--months", "1",
                              "--instruments", "XAUUSD", "--tasks", "lab"], env=self.env, cwd=str(_env.ROOT / "backend"),
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        self.assertTrue(wait_for(lambda: (self.data / "training" / "runs").exists() and any(
            t["id"] == "XAUUSD:lab" and t["execution"] == "W_TOKU" for t in self.state()["tasks"]), 600, 0.5))
        self.assertEqual(self.cli("training", "cancel").returncode, 0)
        out = p.communicate(timeout=300)[0]
        self.assertEqual(p.returncode, 3, out[-2000:])
        st = self.state()
        self.assertEqual(st["status"], "CANCELLED")
        tasks = {t["id"]: t for t in st["tasks"]}
        self.assertEqual(tasks["XAUUSD:export"]["execution"], "UKONCZONE")
        self.assertEqual(tasks["XAUUSD:lab"]["execution"], "ANULOWANE")
        export_started = tasks["XAUUSD:export"]["started_at"]
        r = self.cli("training", "resume")
        self.assertIn(r.returncode, (0, 4), r.stdout[-2000:])
        st = self.state()
        tasks = {t["id"]: t for t in st["tasks"]}
        self.assertEqual(tasks["XAUUSD:export"]["started_at"], export_started)              # finished export not repeated
        self.assertEqual(tasks["XAUUSD:lab"]["execution"], "UKONCZONE")
        self.assertEqual(tasks["XAUUSD:forecast"]["execution"], "POMINIETE")                # not requested in the plan
        self.assertEqual(st["status"], "FINISHED")

    def test_second_run_is_refused_while_one_is_in_progress(self):
        sys.path.insert(0, str(_env.ROOT / "backend"))
        os.environ["MASTERQUO_DATA_DIR"] = str(self.data)
        from masterquo.training import core
        self.assertIsNone(core.acquire_lock("A"))
        try:
            self.assertEqual(core.acquire_lock("B"), "A")                                   # same live pid holds it
        finally:
            core.release_lock("A")
        self.assertIsNone(core.acquire_lock("B"))
        core.release_lock("B")


class TestTrainAllCompat(_Base):
    def test_22_launcher_uses_the_same_mechanism(self):
        r = self.cli("train-all", "--demo", "--quick", "--skip-candles", "--skip-ml", "--lab-bars", "4000", "--instruments", "BTC", "--months", "1")
        self.assertIn(r.returncode, (0, 4), r.stdout[-3000:] + r.stderr[-1500:])
        self.assertIn("masterquo training run", r.stdout)
        st = self.state()
        self.assertEqual(st["plan"]["origin"], "train-all")
        self.assertEqual(st["plan"]["instruments"], ["BTC"])
        t = {x["id"]: x for x in st["tasks"]}
        self.assertEqual(t["BTC:forecast"]["execution"], "POMINIETE")
        self.assertEqual(t["BTC:lab"]["execution"], "UKONCZONE", t["BTC:lab"])
        self.assertIsNone(st["plan"]["commissions"].get("BTC"))                             # no 0.50 copied onto BTC


class TestUnits(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_instrument_profiles_usd_usdt_and_lookalikes(self):
        import mq_instruments as mi
        self.assertEqual(mi.check_metadata("BTC", {"currency_base": "BTC", "currency_profit": "USDT"}), (True, []))
        self.assertTrue(mi.check_metadata("BTC", {"currency_base": "BTC", "currency_profit": "USD"})[0])      # allowed but recorded as USD
        self.assertFalse(mi.check_metadata("BTC", {"currency_base": "WBTC", "currency_profit": "USDT"})[0])
        self.assertFalse(mi.check_metadata("XAUUSD", {"currency_base": "PAXG", "currency_profit": "USD"})[0])
        self.assertFalse(mi.check_metadata("XAUUSD", {"currency_base": "XAU", "currency_profit": "EUR"})[0])
        c = mi.candidates("BTC", [{"name": "WBTCUSDT", "currency_base": "WBTC", "currency_profit": "USDT"},
                                  {"name": "BTSUSDT-", "currency_base": "BTS", "currency_profit": "USDT"},
                                  {"name": "BTCUSD-", "currency_base": "BTC", "currency_profit": "USD"},
                                  {"name": "BTCUSDT-", "currency_base": "BTC", "currency_profit": "USDT", "visible": True}])
        self.assertEqual([x["name"] for x in c], ["BTCUSDT-", "BTCUSD-"])                  # default first; look-alikes excluded
        self.assertEqual(mi.root("forecast", "XAUUSD"), Path(self.td.dir) / "forecast")    # historical XAUUSD paths kept
        self.assertEqual(mi.root("ml", "BTC"), Path(self.td.dir) / "instruments" / "BTC" / "ml")

    def test_export_process_cannot_send_orders(self):
        from masterquo.forecast.export import NoOrders
        from masterquo.mt5.fake import FakeMT5, is_fake
        m = NoOrders(FakeMT5())
        for fn in ("order_send", "order_check"):
            with self.assertRaises(RuntimeError):
                getattr(m, fn)
        self.assertTrue(is_fake(m))

    def test_registry_paths_survive_moving_the_project_folder(self):
        from gold_candles_runtime.common import relocated
        root = Path(self.td.dir) / "forecast"
        (root / "runs" / "R1").mkdir(parents=True)
        (root / "runs" / "R1" / "forecast_model.json").write_text("{}", encoding="utf-8")
        old = Path("/stary folder/PepeMarketWizard/data/forecast/runs/R1/forecast_model.json")
        self.assertEqual(relocated(old, root), root / "runs" / "R1" / "forecast_model.json")
        self.assertEqual(relocated("/x/runs/NOPE/m.json", root), Path("/x/runs/NOPE/m.json"))      # unknown -> unchanged (checksum fails)

    def test_lab_pointer_activation_and_rollback(self):
        from masterquo.lab import protocol as P
        root = Path(self.td.dir) / "lab"
        for mid in ("LM-A", "LM-B"):
            (root / "models" / "BTC" / mid).mkdir(parents=True)
            (root / "models" / "BTC" / mid / "manifest.json").write_text("{}", encoding="utf-8")
        P.set_active(root, "BTC", "SEW_SNN", "LM-A", "t")
        P.set_active(root, "BTC", "SEW_SNN", "LM-B", "t")
        self.assertEqual(P.read_pointer(root, "BTC")["active"]["SEW_SNN"], "LM-B")
        P.rollback_family(root, "BTC", "SEW_SNN")
        self.assertEqual(P.read_pointer(root, "BTC")["active"]["SEW_SNN"], "LM-A")
        with self.assertRaises(ValueError):
            P.set_active(root, "BTC", "SEW_SNN", "LM-NOPE", "t")
        self.assertEqual(P.read_pointer(root, "XAUUSD")["active"], {})                      # other instrument untouched

    def test_ml_router_separate_database_and_symbol_filter(self):
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        from masterquo.ml.router import MLRouter, ml_store
        cfg = ConfigStore()
        db = Database()

        class Bridge:
            synthetic, symbol_info, deals = True, {}, []
            _lock = __import__("threading").Lock()

            def account_status(self):
                return {}

        class Bus:
            def publish(self, *a):
                pass

        class Log:
            def info(self, *a, **k):
                pass
            warn = info
        r = MLRouter(cfg, db, Bridge(), Bus(), Log())
        self.assertEqual(r.inst, "XAUUSD")
        self.assertIs(r.db, db)
        bdb, broot = ml_store("BTC")
        self.assertNotEqual(Path(bdb.path), Path(db.path))
        cfg.update({"assets": {"mappings": {"BTC": {"broker_symbol": "BTCUSDT-", "status": "CONFIRMED"}}}})
        self.assertTrue(r.switch("BTC"))
        self.assertEqual((r.inst, Path(r.db.path)), ("BTC", Path(bdb.path)))
        res = r.start_training("TEST", force=True, include_approx=True)                  # per-job flag, never written to config
        self.assertFalse(res["started"])
        self.assertFalse(cfg.get().ml.use_backfill_approx)
        self.assertEqual(r.on_setup_events([("NEW_CONFIRMED", {"symbol": "XAUUSD-", "record": {"x": 1}, "setup_id": "S", "version": 1})], object(), None), 0)
        r.stop()


@unittest.skipUnless(CANDLES, "MQ_CANDLES_PYTHON wymagane")
class TestGoldCandlesInstrumentConfig(unittest.TestCase):
    def test_registered_btc_symbol_and_unregistered_rejected(self):
        code = ("import os; os.environ['MQ_INSTRUMENT']='BTC'\n"
                "from gold_candles_runtime.common import make_config\n"
                "from gold_candles.data import Config, DataError\n"
                "c = make_config('BTCUSDT-', 0.01)\n"
                "assert c.grid_step == 500.0 and c.contract_hash() != make_config('BTCUSDT-', 0.01, 'BTC', 250.0).contract_hash()\n"
                "x = make_config('XAUUSD-', 0.01, 'XAUUSD'); assert x == Config()\n"
                "try:\n    Config(symbol='ETHUSD-'); raise SystemExit(5)\nexcept DataError as e:\n    assert 'ONLY_XAUUSD' in str(e)\n"
                "print('OK')")
        r = subprocess.run([CANDLES, "-c", code], cwd=str(_env.ROOT / "backend"), capture_output=True, text=True,
                           env=dict(os.environ, PYTHONPATH=str(_env.ROOT / "backend")))
        self.assertEqual(r.stdout.strip(), "OK", r.stderr[-1500:])


if __name__ == "__main__":
    unittest.main()
