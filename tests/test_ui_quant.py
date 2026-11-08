"""1.35 PMW Quant Core - real server process on the SYNTHETIC terminal (--demo) + Chromium.

1. API: /api/v1/quant/status|predictions|assessment|jobs|mode|inventory - the cycle runs without any panel open (generation grows with no
   page loaded), reads never trigger a computation, ASSIST is refused without a validated model, training from an empty ledger is an
   honest INSUFFICIENT_EVIDENCE, a candidate assessment without a model says NOT_TRAINED (no 0 / 50 %).
2. Pages #/decyzje and #/trening show the Quant sections; no order / execution request is sent; the execution mode is unchanged."""
from __future__ import annotations

import os
import sys
import time
import unittest

import _env
from _env import wait_for

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_ui_kronos import CHROMIUM, HAVE_PW, Server  # noqa: E402

PORT = 8841
SHOTS = _env.ROOT / "data" / "logs" / "ui_quant"


class TestQuantApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = Server(PORT, extra_env={"MQ_FAKE_MARKET_ALWAYS_OPEN": "1"})
        cls.mode0 = cls.srv.call("/api/v1/state")[1]["mode"]["mode"]
        SHOTS.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()

    def gen(self):
        return self.srv.call("/api/v1/quant/status")[1].get("generation") or 0

    def test_01_cycle_without_panel_and_reads_only(self):
        self.assertTrue(wait_for(lambda: self.gen() >= 2, 90, 1.0))         # nothing opened in a browser
        c, st = self.srv.call("/api/v1/quant/status")
        self.assertEqual(c, 200)
        self.assertEqual(st["mode"], "SHADOW")                               # default after installation
        self.assertFalse(st["execution_allowed"])
        self.assertEqual(st["snapshot"]["data_kind"], "SYNTHETIC")
        self.assertTrue(all(t["status"] == "OK" for t in st["tasks"].values()), st["tasks"])
        g = st["generation"]
        t0 = time.time()
        for _ in range(15):
            self.srv.call("/api/v1/quant/status")
        self.assertLessEqual(self.gen() - g, int((time.time() - t0) / 5) + 1)  # reads do not add cycles beyond the 5 s loop
        c, pr = self.srv.call("/api/v1/quant/predictions")
        self.assertEqual(c, 200)
        for p in pr["excluded"]:
            self.assertIsNone(p["result"])                                   # an excluded / unavailable record carries no value
            self.assertTrue(p["eligibility"]["reason"])
        ids = [p["canonical_id"] for p in pr["eligible"]]
        self.assertFalse([i for i in ids if i.startswith("unresolved:") or i == "?"])

    def test_02_modes_jobs_assessment(self):
        c, r = self.srv.call("/api/v1/quant/mode", {"mode": "ASSIST", "confirm": True})
        self.assertEqual(c, 409)
        self.assertIn("VALIDATED_SHADOW", r.get("detail", ""))
        c, j = self.srv.call("/api/v1/quant/jobs", {"kind": "TRAIN_METAMODEL"})
        self.assertEqual(c, 200)
        self.assertTrue(wait_for(lambda: self.srv.call("/api/v1/quant/jobs")[1]["items"][-1]["state"] != "RUNNING", 60, 0.5))
        last = self.srv.call("/api/v1/quant/jobs")[1]["items"][-1]
        self.assertEqual(last["state"], "DONE")
        self.assertTrue(all(x["status"] == "INSUFFICIENT_EVIDENCE" for x in last["results"]))
        cand = {"setup_id": "UI-1", "engine": "SH_SCALPING", "strategy_id": "SCALPING", "symbol": "XAUUSD-", "instrument": "XAUUSD", "timeframe": "M1",
                "decision_ts": time.time(), "direction": "LONG", "entry_type": "MARKET", "entry_price": 2000.0, "stop_loss": 1998.0,
                "targets": [{"price": 2002.5, "weight": 0.5}, {"price": 2003.0, "weight": 0.5}], "horizon_s": 3600,
                "execution_context": {"cost_price": 0.1, "commission_known": True}}
        c, a = self.srv.call("/api/v1/quant/assessment", {"candidate": cand})
        self.assertEqual(c, 200, a)
        self.assertEqual(a["status"], "NOT_TRAINED")
        self.assertIsNone(a["probability"])
        self.assertEqual(self.srv.call("/api/v1/quant/assessment", {"candidate": {"setup_id": "x"}})[0], 400)
        self.assertEqual(self.srv.call("/api/v1/quant/mode", {"mode": "OFF"})[0], 200)
        self.assertEqual(self.srv.call("/api/v1/quant/mode", {"mode": "SHADOW"})[0], 200)
        c, inv = self.srv.call("/api/v1/quant/inventory")
        self.assertEqual(c, 200)
        self.assertEqual(inv["coverage"]["adapters"]["missing"], [])

    @unittest.skipUnless(HAVE_PW, "playwright not installed")
    def test_03_pages(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch(executable_path=CHROMIUM)
            p = b.new_context(viewport={"width": 1500, "height": 950}).new_page()
            errors, writes = [], []
            p.on("pageerror", lambda e: errors.append(str(e)))
            p.on("request", lambda r: writes.append(r.method + " " + r.url) if r.method != "GET" else None)
            p.goto(f"{self.srv.base}/#/decyzje")
            p.wait_for_selector("[data-testid=quant-decision] [data-testid=quant-models]", timeout=30000)
            self.assertIn("SHADOW", p.locator("[data-testid=quant-mode]").first.inner_text())
            self.assertGreaterEqual(p.locator("[data-testid=quant-tasks] tbody tr").count(), 4)
            p.screenshot(path=str(SHOTS / "decyzje_quant.png"), full_page=True)
            p.goto(f"{self.srv.base}/#/trening")
            p.wait_for_selector("[data-testid=quant-training] [data-testid=quant-ledger]", timeout=30000)
            self.assertTrue(p.locator("[data-testid=quant-assist]").is_disabled())   # ASSIST needs the explicit confirmation first
            p.locator("[data-testid=quant-training]").screenshot(path=str(SHOTS / "trening_quant.png"))
            self.assertEqual(errors, [])
            self.assertEqual(writes, [])                                    # viewing never sends anything
            b.close()
        self.assertEqual(self.srv.call("/api/v1/state")[1]["mode"]["mode"], self.mode0)


if __name__ == "__main__":
    unittest.main()
