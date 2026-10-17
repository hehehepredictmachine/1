"""22_TRENUJ_WSZYSTKIE_MODELE.bat -> `masterquo train-all` on the SYNTHETIC terminal (--demo --quick --skip-ml): starts the bot by
itself, trains the lab models of XAUUSD and BTC with artifact_family=ALL, restores the active asset, writes the report, and the
running bot then executes EVERY saved model (lab state lists all of them). Forecast/scalp training needs a real MT5 export and is
reported as skipped in demo; ML DT/XGB is covered by tests/test_ml.py."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

import _env
from _env import TempData, wait_for

PORT = 8812


class TestTrainAll(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        with open(os.path.join(self.td.dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"server": {"port": PORT, "open_browser": False}, "news": {"enabled": False}, "clock": {"reference_url": None},
                       "first_run_completed": True}, f)
        os.makedirs(os.path.join(self.td.dir, "logs"), exist_ok=True)
        self.env = dict(os.environ, MASTERQUO_DATA_DIR=self.td.dir, PYTHONPATH=str(_env.ROOT / "backend"))
        self.env.pop("ANTHROPIC_API_KEY", None)

    def tearDown(self):
        subprocess.run([sys.executable, "-m", "masterquo", "stop"], env=self.env, cwd=str(_env.ROOT / "backend"), timeout=60,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.td.close()

    def test_one_command_trains_and_bot_runs_all_models(self):
        r = subprocess.run([sys.executable, "-m", "masterquo", "train-all", "--demo", "--quick", "--skip-ml", "--lab-bars", "5000"],
                           env=self.env, cwd=str(_env.ROOT / "backend"), capture_output=True, text=True, timeout=2400)
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-2000:])
        self.assertIn("PODSUMOWANIE", r.stdout)
        reps = sorted((_env.Path(self.td.dir) / "logs").glob("trening_wszystkiego_*.json"))
        self.assertTrue(reps)
        rep = json.loads(reps[-1].read_text(encoding="utf-8"))
        steps = {s["step"]: s for s in rep["steps"]}
        self.assertEqual(steps["prognozy gold_candles + scalp"]["status"], "POMINIĘTE")      # demo: honest skip, not "OK"
        for asset in ("XAUUSD", "BTC"):
            st = steps[f"modele lab {asset} (wszystkie rodziny)"]
            self.assertEqual(st["status"], "OK", st)
            self.assertGreaterEqual(len(st["models"]), 2)                                       # every family saved (not only a winner)
            names = {p.name for p in (_env.Path(self.td.dir) / "lab" / "models" / asset).iterdir()}
            self.assertTrue(any("SEW_SNN" in n for n in names) and any("LOGREG" in n for n in names), names)
        sys.path.insert(0, str(_env.ROOT / "backend"))
        from masterquo.train_all import Bot
        bot = Bot(PORT)
        bot.login()
        self.assertEqual(bot.get("/api/v1/assets")[1]["active"], "XAUUSD")                       # active asset restored
        self.assertEqual(bot.get("/api/v1/execution/lock")[1]["lock"], "LOCKED")                 # training never unlocks orders

        def lab_runs_all():
            lab = bot.get("/api/v1/lab?asset=XAUUSD")[1]
            fams = {m.get("family") for m in lab.get("models") or [] if m.get("status") == "ready"}
            return {"LOGREG", "SEW_SNN"} <= fams
        self.assertTrue(wait_for(lab_runs_all, 120, 2), bot.get("/api/v1/lab?asset=XAUUSD")[1].get("models"))
        lab = bot.get("/api/v1/lab?asset=XAUUSD")[1]
        self.assertEqual(lab["model"]["family"], "SEW_SNN")                                       # the network is shown as primary
        self.assertTrue(all(m["role"] == "fixture_only" for m in lab["models"]))                   # synthetic data -> never a real model


if __name__ == "__main__":
    unittest.main()
