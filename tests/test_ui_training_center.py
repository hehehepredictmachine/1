"""Centrum treningu in the panel (Chromium on the demo bot = terminal simulator, SYNTHETIC data - mechanics only, no market claims):
export through the bot's bridge, training in a SEPARATE process while the panel keeps answering, cancel, controlled activation
(compatibility + prediction test), the live prediction in the unified contract, rollback, the model catalog and the dataset / package
downloads. Screenshots: data/logs/ui_training_center/. Skipped (never "passed") without Playwright/Chromium."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest
import urllib.request

import _env
from _env import TempData, wait_for

CHROMIUM = os.environ.get("MQ_CHROMIUM", "/opt/pw-browsers/chromium")
SHOTS = _env.ROOT / "data" / "logs" / "ui_training_center"
PORT = 8792
try:
    from playwright.sync_api import sync_playwright
    HAVE_PW = True
except ImportError:  # pragma: no cover
    HAVE_PW = False


def up(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


@unittest.skipUnless(HAVE_PW, "playwright not installed")
class TestTrainingCenterUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (_env.ROOT / "frontend" / "dist" / "index.html").exists():
            raise unittest.SkipTest("frontend not built")
        SHOTS.mkdir(parents=True, exist_ok=True)
        cls.td = TempData()
        with open(os.path.join(cls.td.dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"server": {"port": PORT, "open_browser": False}, "news": {"enabled": False}, "clock": {"reference_url": None},
                       "first_run_completed": True}, f)
        cls.env = dict(os.environ, MASTERQUO_DATA_DIR=cls.td.dir, PYTHONPATH=str(_env.ROOT / "backend"))
        cls.env.pop("ANTHROPIC_API_KEY", None)
        cls.proc = subprocess.Popen([sys.executable, "-m", "masterquo", "serve", "--demo", "--no-browser"], env=cls.env, cwd=str(_env.ROOT / "backend"),
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not wait_for(lambda: up(PORT), 90, 0.5):
            cls.proc.kill()
            raise RuntimeError("bot did not start")
        cls.pw = sync_playwright().start()
        kw = {"executable_path": CHROMIUM} if os.path.exists(CHROMIUM) else {}
        cls.browser = cls.pw.chromium.launch(**kw)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.browser.close()
            cls.pw.stop()
        finally:
            subprocess.run([sys.executable, "-m", "masterquo", "stop"], env=cls.env, cwd=str(_env.ROOT / "backend"), timeout=60)
            try:
                cls.proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                cls.proc.kill()
            cls.td.close()

    def api(self, p, path, body=None):
        if body is None:
            return p.evaluate("async (u) => (await fetch(u, {credentials: 'same-origin'})).json()", path)
        return p.evaluate("""async ([u, b]) => { const s = await (await fetch('/api/v1/session', {credentials: 'same-origin'})).json();
            const r = await fetch(u, {method: 'POST', credentials: 'same-origin', headers: {'content-type': 'application/json', 'x-mq-csrf': s.csrf},
            body: JSON.stringify(b)}); return r.json(); }""", [path, body])

    def job_done(self, p, kind, n_before=0, timeout=240):
        def ok():
            jobs = [j for j in self.api(p, "/api/v1/trainhub/jobs?limit=50")["items"] if j["kind"] == kind]
            return len(jobs) > n_before and jobs[0]["status"] not in ("QUEUED", "RUNNING")
        self.assertTrue(wait_for(ok, timeout, 0.5), kind)
        return [j for j in self.api(p, "/api/v1/trainhub/jobs?limit=50")["items"] if j["kind"] == kind][0]

    def test_export_train_cancel_activate_predict_rollback(self):
        ctx = self.browser.new_context(viewport={"width": 1600, "height": 1100}, accept_downloads=True)
        p = ctx.new_page()
        errors = []
        p.on("pageerror", lambda e: errors.append(str(e)))
        try:
            p.goto(f"http://127.0.0.1:{PORT}/#/trening")
            p.wait_for_selector("[data-testid=page-trening]", timeout=60000)
            self.assertTrue(wait_for(lambda: self.api(p, "/api/v1/market-zones/bars?instrument=XAUUSD&tf=M5&count=30")["bars"], 60, 0.5))
            before = self.api(p, "/api/v1/config")
            # 1. export through the bridge (short range for the test)
            p.select_option("[data-testid=tc-exp-mode]", "incremental")
            p.fill("input[type=number] >> nth=0", "25")
            p.locator("[data-testid=tc-data]").get_by_role("checkbox", name="M1", exact=True).uncheck()
            p.click("[data-testid=tc-export]")
            j = self.job_done(p, "EXPORT")
            self.assertEqual(j["status"], "SUCCEEDED", j)
            data = self.api(p, "/api/v1/trainhub/data?instrument=XAUUSD")
            self.assertTrue(data["verify"]["ok"])
            self.assertEqual(data["manifest"]["data_kind"], "SYNTHETIC_TEST")
            self.assertGreater(data["manifest"]["timeframes"]["M5"]["rows"], 5000)
            p.screenshot(path=str(SHOTS / "01_exported.png"), full_page=True)
            # 2. train in a separate process - the panel keeps answering meanwhile
            for m in ("TH_HGB",):
                p.uncheck(f"[data-testid=tc-model-{m}]")
            p.click("[data-testid=tc-train-btn]")
            self.assertTrue(wait_for(lambda: any(x["kind"] == "TRAIN" and x["status"] == "RUNNING" and x.get("pid")
                                                 for x in self.api(p, "/api/v1/trainhub/jobs")["items"]), 60, 0.2))
            jt = [x for x in self.api(p, "/api/v1/trainhub/jobs")["items"] if x["kind"] == "TRAIN"][0]
            self.assertNotEqual(jt["pid"], self.proc.pid)                              # training is NOT in the bot process
            t0 = time.perf_counter()
            self.assertTrue(up(PORT))
            self.assertLess(time.perf_counter() - t0, 2.0)
            p.goto(f"http://127.0.0.1:{PORT}/#/strefy")                                  # the panel stays usable during training
            p.wait_for_selector("[data-testid=page-strefy]", timeout=20000)
            p.goto(f"http://127.0.0.1:{PORT}/#/trening")
            p.wait_for_selector("[data-testid=page-trening]", timeout=20000)
            j = self.job_done(p, "TRAIN")
            self.assertEqual(j["status"], "SUCCEEDED", j.get("error"))
            reg = self.api(p, "/api/v1/trainhub/registry?instrument=XAUUSD")
            self.assertEqual(reg["active"], {})                                          # training never activates
            self.assertTrue(any(v["model_key"].startswith("TH_LOGREG") for v in reg["versions"]))
            # 3. cancel: a second training is cancelled while running
            p.click("[data-testid=tc-full]")
            self.assertTrue(wait_for(lambda: any(x["kind"] == "FULL" and x["status"] == "RUNNING" for x in self.api(p, "/api/v1/trainhub/jobs")["items"]),
                                     60, 0.2))
            p.wait_for_selector("[data-testid=tc-cancel]", timeout=20000)
            p.click("[data-testid=tc-cancel]")
            j = self.job_done(p, "FULL", timeout=60)
            self.assertEqual(j["status"], "CANCELLED", j)
            # 4. controlled activation of LOGREG (compatibility + prediction test)
            p.reload()
            p.wait_for_selector("[data-testid=tc-version]", timeout=30000)
            row = p.locator("[data-testid=tc-version]").filter(has_text="").first
            key = next(v for v in reg["versions"] if v["model_key"].startswith("TH_LOGREG"))
            p.locator(f".tc-model:has-text('{key['model_key']}') [data-testid=tc-activate]").first.click()
            p.wait_for_selector("[data-testid=tc-msg]", timeout=20000)
            self.assertIn("ACTIVE", p.locator("[data-testid=tc-msg]").inner_text())
            reg = self.api(p, "/api/v1/trainhub/registry?instrument=XAUUSD")
            self.assertIn(key["model_key"], reg["active"])
            # 5. live prediction in the unified contract (READY or a state WITH a reason - never a silent value)
            self.assertTrue(wait_for(lambda: self.api(p, "/api/v1/models/predictions?instrument=XAUUSD")["items"], 60, 0.5))
            pr = self.api(p, "/api/v1/models/predictions?instrument=XAUUSD")["items"][0]
            self.assertEqual(pr["contract"], "PMW-PRED-2")                     # 1.33: PMW-PRED-2 (compatible superset of PMW-PRED-1)
            if pr["state"] == "READY":
                self.assertAlmostEqual(sum(pr["result"].values()), 1.0, places=5)
                self.assertEqual(pr["unit"], "probability")
                self.assertEqual(pr["calibration"]["status"], "CALIBRATED_DEV")
            else:
                self.assertIsNone(pr["result"])
                self.assertTrue(pr["unavailable_reason"])
            cat = self.api(p, "/api/v1/models/catalog?instrument=XAUUSD")
            self.assertGreater(len(cat["items"]), 40)
            self.assertTrue({"TRAINABLE", "INDICATOR", "RULE", "SIMULATION"} <= set(cat["counts_by_category"]))
            ev = self.api(p, "/api/v1/models/evidence?instrument=XAUUSD&strategy=SCALPING")
            for g in ev["groups"]:
                self.assertEqual(g["use"], "OBSERVATION")
            p.reload()
            p.wait_for_selector("[data-testid=tc-catalog] [data-testid=tc-cat-row]", timeout=30000)
            p.screenshot(path=str(SHOTS / "02_active_predictions_catalog.png"), full_page=True)
            # downloads: model package and dataset
            with p.expect_download() as dl:
                p.locator(f".tc-model:has-text('{key['model_key']}') a:has-text('Paczka')").first.click()
            self.assertTrue(dl.value.suggested_filename.endswith(".zip"))
            # 6. rollback -> nothing active (no previous version)
            p.locator(f".tc-model:has-text('{key['model_key']}') [data-testid=tc-rollback]").first.click()
            self.assertTrue(wait_for(lambda: key["model_key"] not in self.api(p, "/api/v1/trainhub/registry?instrument=XAUUSD")["active"], 20, 0.3))
            # nothing here changed trading settings
            self.assertEqual(self.api(p, "/api/v1/config"), before)
            self.assertEqual(errors, [])
            _ = row
        finally:
            ctx.close()


if __name__ == "__main__":
    unittest.main()
