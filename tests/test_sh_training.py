"""PMW-SH-1 acceptance 13-15: training pipeline and panel backend.
* runner task sh_models end to end on the SYNTHETIC demo export (technical test: never promoted, quality TEST_TECHNICZNY);
* real progress (tasks + trainer counter), run history, statuses incl. a LOST worker, logs, run comparison;
* export of a training package (data, configs, run, models, manifest with checksums, reproduction command, NO secrets) and
  import (checksums verified, run added as a candidate, active model untouched), explicit promotion and rollback;
* replay mechanics on a synthetic dataset (one plan at a time, conservative ambiguous bars, whole-cycle accounting).
Synthetic data exist only inside the isolated test data directory."""
import io
import json
import os
import subprocess
import sys
import unittest
import zipfile
from pathlib import Path

import _env
from _env import TempData

PY = sys.executable
NOW = 1_760_000_000.0


class Base(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def cli(self, *args, timeout=1500):
        env = dict(os.environ, MASTERQUO_DATA_DIR=self.td.dir, PYTHONPATH=str(_env.ROOT / "backend"), MQ_NO_BROWSER="1")
        env.pop("ANTHROPIC_API_KEY", None)
        return subprocess.run([PY, "-m", "masterquo", *args], cwd=str(_env.ROOT / "backend"), env=env, capture_output=True, text=True, timeout=timeout)


class RunnerSHModels(Base):
    def test_runner_task_and_panel_views(self):
        r = self.cli("training", "run", "--demo", "--profile", "TEST_INSTALACJI", "--months", "1", "--instruments", "XAUUSD", "--tasks", "sh_models")
        from masterquo.training import core, panel
        rid = core.Run.latest()
        st = core.Run.load(rid).state
        t = next(x for x in st["tasks"] if x["kind"] == "sh_models")
        self.assertEqual(t["execution"], "UKONCZONE", (t.get("detail"), r.stdout[-2000:], r.stderr[-2000:]))
        self.assertEqual(t["quality"], "TEST_TECHNICZNY")                               # synthetic: technical test only
        self.assertEqual(t["integration"], "ZAPISANY_DO_BADAN")                         # never promoted on synthetic data
        self.assertTrue(all(Path(a).exists() for a in t["artifacts"]))
        out = json.loads(Path(t["artifacts"][0]).read_text())
        self.assertEqual(out["data_kind"], "SYNTHETIC_TEST")
        self.assertEqual(set(out["strategies"]), {"SCALPING", "HEDGING"})
        log = panel.task_log(rid, t["id"])
        self.assertIn("[POSTEP] replay", log["text"])                                   # real counter written by the trainer
        d = panel.run_detail(rid)
        self.assertEqual(d["status_effective"], "FINISHED")
        self.assertEqual(d["progress"]["fraction"], 1.0)
        self.assertIsNone(d["progress"]["current_task"])
        self.assertEqual(panel.runs()[0]["run_id"], rid)
        from masterquo.sh import tpmodel as TM
        self.assertIsNone(TM.status("XAUUSD", "SCALPING").get("version"))              # no active model from synthetic data
        self.assertFalse((Path(self.td.dir) / "sh" / "validation" / "XAUUSD_SCALPING.json").exists())   # synthetic report not used live
        # comparison with itself: no changes
        self.assertTrue(all(not row["changed"] for row in panel.compare(rid, rid)["tasks"]))


class PanelStatuses(Base):
    def test_lost_worker_and_progress_counter(self):
        from masterquo.training import core, panel, runner
        plan, tasks = runner.build_plan(instruments=["XAUUSD"], profile="TEST_INSTALACJI", symbols={"XAUUSD": "XAUUSD-"}, commissions={},
                                        months=1, synthetic=True, tasks=["sh_models"])
        run = core.Run.create(plan, tasks)
        run.state["status"] = "RUNNING"
        lp = run.dir / "logs" / "x.log"
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.write_text("start\n[POSTEP] replay 500/6000\n[POSTEP] replay 1500/6000\n")
        run.set("XAUUSD:sh_models", execution="W_TOKU", log=str(lp))
        core.write_json_atomic(core.lock_path(), {"run_id": run.run_id, "pid": 999999, "at": core.now()})   # dead process
        d = panel.run_detail(run.run_id)
        self.assertEqual(d["status_effective"], "UTRACONY_PROCES")
        self.assertEqual(d["progress"]["current_task"], "XAUUSD:sh_models")
        self.assertEqual(d["progress"]["current_counter"]["done"], 1500)
        self.assertEqual(d["progress"]["current_counter"]["total"], 6000)
        core.write_json_atomic(core.lock_path(), {"run_id": run.run_id, "pid": os.getpid(), "at": core.now()})   # live holder
        self.assertEqual(panel.run_detail(run.run_id)["status_effective"], "RUNNING")
        run.state["status"] = "CANCELLED"
        run.save()
        self.assertEqual(panel.run_detail(run.run_id)["status_effective"], "CANCELLED")


class ExportImportPromote(Base):
    def samples(self, n, seed):
        import numpy as np
        from masterquo.sh.tpmodel import FEATURES
        rng = np.random.default_rng(seed)
        X = rng.normal(size=(n, len(FEATURES)))
        y = (rng.random(n) < 1 / (1 + np.exp(-2.5 * X[:, 0]))).astype(int)
        return [{"t": NOW + 600 * i, "x": X[i].tolist(), "y": int(y[i])} for i in range(n)]

    def test_package_roundtrip_no_secrets(self):
        from masterquo.sh import tpmodel as TM
        from masterquo.training import panel
        d = Path(self.td.dir)
        (d / "secrets.local.json").write_text('{"ANTHROPIC_API_KEY": "sk-should-never-leak"}')
        rec = TM.train("XAUUSD", "SCALPING", self.samples(1500, 3), embargo_s=1800, log=lambda *_: None, allow_promotion=False,
                       provenance={"data_kind": "TEST_FIXTURE"})
        self.assertEqual((rec["verdict"], rec["promoted"]), ("HOLDOUT_PASSED", False))
        pkg = panel.export_package("XAUUSD", "sh_tp_model")
        z = zipfile.ZipFile(pkg["path"])
        names = z.namelist()
        self.assertIn("MANIFEST.json", names)
        self.assertIn(f"models/sh_tp_model/XAUUSD/SCALPING/{rec['run_id']}.npz", names)
        self.assertIn("config/sh_strategies_v1.json", names)
        blob = b"".join(z.read(n) for n in names)
        self.assertNotIn(b"sk-should-never-leak", blob)
        man = json.loads(z.read("MANIFEST.json"))
        self.assertTrue(any("dane treningowe" in m for m in man["missing"]))            # missing history reported, not invented
        self.assertIn("sh train", man["reproduce"]["sh_models_from_this_package"])
        self.assertEqual(man["feature_schemas"]["sh_tp_model"]["features"], TM.FEATURES)
        for f in man["files"]:
            import hashlib
            self.assertEqual(hashlib.sha256(z.read(f["path"])).hexdigest(), f["sha256"])
        raw = Path(pkg["path"]).read_bytes()
        # import into a fresh data directory: candidate only, active unchanged
        self.td.close()
        self.td = TempData()
        res = panel.import_package(raw)
        self.assertEqual([x["run_id"] for x in res["imported"]], [rec["run_id"]])
        self.assertTrue(res["imported"][0]["compatible"])
        self.assertIsNone(TM.status("XAUUSD", "SCALPING").get("version"))
        with self.assertRaises(ValueError):                                              # test data are never promoted
            TM.promote("XAUUSD", "SCALPING", rec["run_id"])
        # tampered package is rejected file by file
        buf = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(raw)) as src, zipfile.ZipFile(buf, "w") as dst:
            for n in src.namelist():
                b = src.read(n)
                dst.writestr(n, b + b"x" if n.endswith(".npz") else b)
        bad = panel.import_package(buf.getvalue())
        self.assertEqual(bad["reason"], "SUMY_KONTROLNE_NIEZGODNE")

    def test_promote_and_rollback_explicit(self):
        from masterquo.sh import tpmodel as TM
        a = TM.train("XAUUSD", "HEDGING", self.samples(1500, 4), embargo_s=1800, log=lambda *_: None, allow_promotion=False)
        self.assertIsNone(TM.status("XAUUSD", "HEDGING").get("version"))
        self.assertEqual(TM.promote("XAUUSD", "HEDGING", a["run_id"]), {"active": a["run_id"], "changed": True})
        self.assertEqual(TM.status("XAUUSD", "HEDGING")["status"], "READY")
        b = TM.train("XAUUSD", "HEDGING", self.samples(1500, 5), embargo_s=1800, log=lambda *_: None)
        self.assertEqual(TM.status("XAUUSD", "HEDGING")["version"], b["run_id"])        # previous file kept, never overwritten
        self.assertTrue((TM.root("XAUUSD", "HEDGING") / f"{a['run_id']}.npz").exists())
        self.assertEqual(TM.rollback("XAUUSD", "HEDGING")["active"], a["run_id"])
        with self.assertRaises(ValueError):
            TM.promote("XAUUSD", "HEDGING", "NOPE")


class ReplayMechanics(Base):
    def test_conservative_bar_and_whole_cycle(self):
        from masterquo.sh import config as C
        from masterquo.sh import replay as RP
        from masterquo.sh.units import SymbolSpec
        spec = SymbolSpec("XAUUSD-", 0.01, 1.0, 100, 0.01, 0.01, 100, 2, "USD", source="TEST")
        prof = C.profile(C.load(), "XAUUSD", "SCALPING")
        t0 = 1_700_000_000

        def bar(k, o, h, lo, c):
            from datetime import datetime, timezone
            return {"open_utc": datetime.fromtimestamp(t0 + 60 * k, tz=timezone.utc).isoformat().replace("+00:00", "Z"), "o": o, "h": h, "l": lo,
                    "c": c, "spread_price": 0.2}
        m1 = [bar(0, 2000, 2000.1, 1999.9, 2000), bar(1, 2000, 2000.1, 1999.9, 2000.0),
              bar(2, 2000.0, 2003.0, 1997.0, 2000.0),                                   # touches TP1 AND the SL: ambiguous -> SL
              bar(3, 2000, 2000, 2000, 2000)]
        mk = RP.Market({"M1": m1, "M5": [], "M15": [], "H1": []}, 0.2)
        su = {"side": "BUY", "entry_ref": 2000.2, "sl": 1998.0, "shares": [0.5, 0.3, 0.2], "mode": "T",
              "tps": [{"name": n, "distance_requested": d} for n, d in zip(("TP1", "TP2", "TP3"), (2.5, 3.0, 5.0))], "be": {"offset_price": 0.3}}
        tr = RP.simulate_scalp(mk, 0, su, spec, prof, slip=0.05, commission_side=None)
        self.assertTrue(tr["ambiguous"])
        self.assertEqual(tr["exit"], "SL")
        self.assertLess(tr["net_r"], -1.0)                                              # stop + slippage + spread: worse than -1R
        self.assertEqual(RP.label_event(mk, 0, su, spec, 0.05, 30), 0)
        m1[2] = bar(2, 2000.0, 2006.0, 1999.5, 2005.5)                                  # clean run to TP3
        tr = RP.simulate_scalp(mk, 0, su, spec, prof, slip=0.05, commission_side=None)
        self.assertEqual((tr["exit"], tr["legs_done"]), ("TP3", ["TP1", "TP2", "TP3"]))
        self.assertAlmostEqual(tr["net_price"], 0.5 * 2.45 + 0.3 * 2.95 + 0.2 * 4.95, places=6)   # one cycle, slippage inside
        self.assertEqual(RP.label_event(mk, 0, su, spec, 0.05, 30), 1)
        m = RP.metrics([tr, dict(tr, net_r=-1.0)])
        self.assertEqual(m["n"], 2)


if __name__ == "__main__":
    unittest.main()
