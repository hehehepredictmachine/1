"""1.33 U7 panels - real server process on the SYNTHETIC terminal (--demo) + Chromium.

1. API of the new panels: decision coordinator status, Studio status, SVP profile life cycle, model families catalog (15 + adapter).
2. Pages #/dxy, #/svp, #/decyzje and the Training Center families section render from the backend with no page errors; every chart has the
   four 1.33 layer buttons (Pepe Scalp Plan / Pepe Hedge Plan / AVWAP / SVP) and switching a layer never sends a non-GET request except the
   panel's own actions; the Studio button is in the top bar and in the CULT menu.
3. Studio launched FROM THE BOT (POST /api/v1/studio/launch) is a separate process answering its own health endpoint; stopped afterwards.
No order is sent; the execution mode is never changed by the panels."""
from __future__ import annotations

import json
import os
import signal
import sys
import unittest
import urllib.request

import _env
from _env import wait_for

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_ui_kronos import CHROMIUM, HAVE_PW, Server  # noqa: E402

PORT, STUDIO_PORT = 8821, 8822
SHOTS = _env.ROOT / "data" / "logs" / "ui_pmw133"


@unittest.skipUnless(HAVE_PW, "playwright not installed")
class TestUiPmw133(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = Server(PORT)
        cls.mode0 = cls.srv.call("/api/v1/state")[1]["mode"]["mode"]
        sdir = os.path.join(cls.srv.dir, "studio_data")
        os.makedirs(sdir, exist_ok=True)
        with open(os.path.join(sdir, "settings.json"), "w") as fh:
            json.dump({"port": STUDIO_PORT, "bot_port": PORT}, fh)
        SHOTS.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        try:
            st = cls.srv.call("/api/v1/studio/status")[1]
            if st.get("running") and getattr(cls, "studio_pid", None):
                os.kill(cls.studio_pid, signal.SIGTERM)
        except Exception:  # noqa: BLE001
            pass
        cls.srv.stop()

    # ------------------------------------------------------------ 1. API
    def test_01_api(self):
        c, d = self.srv.call("/api/v1/decision/status")
        self.assertEqual(c, 200)
        self.assertEqual(d["version"], "PMW-ARC-1")
        self.assertTrue(d["enabled"])
        c, s = self.srv.call("/api/v1/studio/status")
        self.assertEqual((c, s["port"], s["running"], s["launcher"]), (200, STUDIO_PORT, False, "PYTHON"))
        c, p = self.srv.call("/api/v1/svp/profiles", {"mode": "RANGE", "tf": "M5", "t0": "2026-11-02T08:00:00Z", "t1": "2026-11-02T12:00:00Z", "name": "t"})
        self.assertEqual(c, 200, p)
        c, comp = self.srv.call(f"/api/v1/svp/profiles/{p['profile_id']}/compute")
        self.assertEqual(c, 200)
        self.assertIn(comp["status"], ("READY", "PARTIAL", "NO_DATA"))        # never invented: NO_DATA without closed bars
        c, z = self.srv.call("/api/v1/svp/zones", {"lower": 2000.0, "upper": 2001.5, "name": "UI", "profile_id": p["profile_id"]})
        self.assertEqual(c, 200, z)
        self.assertEqual(self.srv.call("/api/v1/svp/zones")[1]["items"][0]["source"], "MANUAL")
        c, f = self.srv.call("/api/v1/families?instrument=XAUUSD")
        self.assertEqual(c, 200)
        self.assertEqual(len(f["items"]), 16)
        self.assertEqual(self.srv.call("/api/v1/indicators/chart?tf=H4")[0], 400)   # AVWAP only on configured TFs (panel never asks)

    # ------------------------------------------------------------ 2. pages
    def test_02_pages_render_and_layers(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch(executable_path=CHROMIUM)
            ctx = b.new_context(viewport={"width": 1500, "height": 950})
            p = ctx.new_page()
            errors, writes = [], []
            p.on("pageerror", lambda e: errors.append(str(e)))
            p.on("request", lambda r: writes.append(r.method + " " + r.url) if r.method != "GET" else None)
            for h, sel in (("dxy", "[data-testid=dxy-card]"), ("svp", "[data-testid=svp-profiles]"), ("decyzje", "[data-testid=dec-records]")):
                p.goto(f"{self.srv.base}/#/{h}")
                p.wait_for_selector(sel, timeout=30000)
                p.wait_for_timeout(800)
                p.screenshot(path=str(SHOTS / f"{h}.png"))
            p.goto(f"{self.srv.base}/#/dxy")
            p.wait_for_selector("[data-testid=dxy-card]", timeout=30000)
            self.assertIn("DXY", p.locator("[data-testid=dxy-card]").inner_text())
            p.goto(f"{self.srv.base}/#/trening")
            p.wait_for_selector("[data-testid=families-table] tbody tr", timeout=30000)
            self.assertGreaterEqual(p.locator("[data-testid=families-table] tbody tr").count(), 15)
            self.assertEqual(p.locator("[data-family=TS_ARIMA]").count(), 1)
            p.goto(f"{self.srv.base}/#/wykresy")
            p.wait_for_selector("[data-testid=pmw-layers]", timeout=30000)
            first = p.locator("[data-testid=pmw-layers]").first
            for k in ("scalp", "hedge", "avwap", "svp"):
                self.assertEqual(first.locator(f"[data-act=pmw-{k}]").count(), 1, k)
            before = len(writes)
            btn = first.locator("[data-act=pmw-svp]")
            btn.click()
            p.wait_for_timeout(500)
            self.assertEqual(btn.get_attribute("aria-pressed"), "true")
            first.locator("[data-act=pmw-scalp]").click()
            p.wait_for_timeout(1500)
            self.assertEqual(writes[before:], [])                              # a layer is presentation only
            p.screenshot(path=str(SHOTS / "wykresy_layers.png"))
            self.assertEqual(p.locator("[data-testid=topbar] [data-testid=studio-button]").count(), 1)
            p.goto(f"{self.srv.base}/#/menu")                                                  # 1.34: Neural City toolbar
            p.wait_for_selector("[data-testid=page-menu] [data-testid=studio-button]", timeout=30000)
            p.goto(f"{self.srv.base}/#/lightning")                                             # menu of the tower panels
            p.wait_for_selector("[data-testid=cu-left] [data-testid=studio-button]", timeout=30000)
            self.assertEqual(errors, [])
            self.assertFalse([w for w in writes if "/order" in w or "/execute" in w])
            b.close()
        self.assertEqual(self.srv.call("/api/v1/state")[1]["mode"]["mode"], self.mode0)          # panels never change the mode

    # ------------------------------------------------------------ 3. Studio from the bot
    def test_03_studio_launch_separate_process(self):
        c, r = self.srv.call("/api/v1/studio/launch", {})
        self.assertEqual(c, 200, r)
        self.assertTrue(r["started"])
        type(self).studio_pid = r["pid"]
        self.assertTrue(wait_for(lambda: self.srv.call("/api/v1/studio/status")[1]["running"], 90, 1.0))
        with urllib.request.urlopen(f"http://127.0.0.1:{STUDIO_PORT}/api/studio/health", timeout=5) as h:
            hj = json.loads(h.read())
        self.assertEqual(hj["app"], "PepeTrainingStudio")
        self.assertIn("studio_data", hj["data_dir"])
        c, r2 = self.srv.call("/api/v1/studio/launch", {})
        self.assertFalse(r2["started"])                                        # already running: never a second instance
        os.kill(r["pid"], signal.SIGTERM)
        self.assertTrue(wait_for(lambda: not self.srv.call("/api/v1/studio/status")[1]["running"], 30, 1.0))


if __name__ == "__main__":
    unittest.main()
