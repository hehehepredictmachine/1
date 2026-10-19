"""1.14 panel in a real browser (Chromium + demo backend on the SYNTHETIC terminal): seven-section menu, XAUUSD/BTC switch
(every lab page answers for the active asset; a response for the other asset is never shown), scenario card + checklist,
Neural Network Activity drawn from the SAME inference_id as the backend result (and 'sieć nieaktywna' without an artefact),
Execution Lock enforced by the backend (trade pad execute, unlock without phrase, config bypass), no symbol blocking (1.14.1),
390 px without horizontal scroll. Screenshots: data/logs/ui_lab/. Skipped without Playwright."""
from __future__ import annotations

import json
from pathlib import Path
import os
import subprocess
import sys
import time
import unittest
import urllib.request

import _env
from _env import TempData, wait_for

PORT = 8798
BASE = f"http://127.0.0.1:{PORT}"
CHROMIUM = os.environ.get("MQ_CHROMIUM", "/opt/pw-browsers/chromium")
SHOTS = _env.ROOT / "data" / "logs" / "ui_lab"
SECTIONS = ["pulpit", "wykresy", "setupy", "modele", "badania", "dane", "ustawienia"]
try:
    from playwright.sync_api import sync_playwright
    HAVE_PW = True
except ImportError:  # pragma: no cover
    HAVE_PW = False


def health():
    try:
        with urllib.request.urlopen(BASE + "/api/v1/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


@unittest.skipUnless(HAVE_PW, "playwright not installed")
class TestLabUI(unittest.TestCase):
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
        if not wait_for(health, 60, 0.5):
            cls.proc.kill()
            raise RuntimeError("server did not start")
        cls.pw = sync_playwright().start()
        kw = {"executable_path": CHROMIUM} if os.path.exists(CHROMIUM) else {}
        cls.browser = cls.pw.chromium.launch(**kw)
        cls.page = cls.browser.new_context(viewport={"width": 1366, "height": 900}).new_page()
        cls.errors = []
        cls.page.on("pageerror", lambda e: cls.errors.append(str(e)))
        cls.page.goto(BASE + "/#/pulpit")
        cls.page.wait_for_selector("[data-testid=lab-dashboard]", timeout=30000)

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

    def api(self, path):
        return self.page.request.get(BASE + path).json()

    def send(self, method, path, body=None):
        """Same-origin fetch with the session CSRF token (as the UI does). Returns (status, json)."""
        return self.page.evaluate("""async ([m, p, b]) => { const s = await (await fetch('/api/v1/session')).json();
            const r = await fetch(p, {method: m, headers: {'Content-Type': 'application/json', 'X-MQ-CSRF': s.csrf}, body: JSON.stringify(b || {})});
            let j = null; try { j = await r.json(); } catch (e) {} return [r.status, j]; }""", [method, path, body])

    def lab_ready(self, asset, need_model=False):
        def ok():
            r = self.api(f"/api/v1/lab?asset={asset}")
            return r.get("modules") and not r.get("stale") and (not need_model or (r.get("model") or {}).get("status") == "ready")
        return wait_for(ok, 180, 1.0)

    def no_hscroll(self):
        return self.page.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")

    def test_01_seven_sections_and_inactive_network(self):
        p = self.page
        self.assertEqual([g.get_attribute("data-group") for g in p.locator("[data-testid=sidenav] .nav-group").all()], SECTIONS)
        self.assertTrue(self.lab_ready("XAUUSD"))
        p.reload()
        p.wait_for_selector("[data-testid=scenario-card]")
        nn = p.locator("[data-testid=nn-activity]")
        wait_for(lambda: nn.get_attribute("data-state") != "waiting", 30, 0.5)
        self.assertEqual(nn.get_attribute("data-state"), "inactive")                       # no artefact -> no fake activity
        self.assertIn("Sieć nieaktywna", nn.inner_text())
        self.assertIn("Execution Lock", p.locator("[data-testid=chip-lock]").inner_text())
        for sec in SECTIONS:
            p.click(f"[data-testid=sidenav] [data-section={sec}]")
            p.wait_for_selector(f"main.page[data-page={sec}]", timeout=20000)
            p.wait_for_timeout(500)
            p.screenshot(path=str(SHOTS / f"{sec}_1366.png"))
            self.assertTrue(self.no_hscroll(), sec)
        self.assertEqual(self.errors, [])

    def test_02_backend_locks_and_allowlist(self):
        st, j = self.send("POST", "/api/v1/lab/tradepad/execute", {"side": "BUY"})
        self.assertEqual(st, 403)
        st, _ = self.send("POST", "/api/v1/execution/lock", {"lock": "UNLOCKED_BY_USER", "phrase": "zle"})
        self.assertEqual(st, 403)
        st, _ = self.send("PUT", "/api/v1/config", {"execution": {"lock": "UNLOCKED_BY_USER"}})
        self.assertEqual(st, 400)
        self.assertEqual(self.page.request.get(BASE + "/api/v1/lab?asset=DOGE").status, 403)   # asset id must be XAUUSD / BTC
        self.assertEqual(self.page.request.get(BASE + "/api/v1/markets/detail?symbol=EURUSD-").status, 200)   # no symbol blocking
        self.assertTrue(wait_for(lambda: self.api("/api/v1/assets")["assets"]["BTC"]["broker_symbol"] == "BTCUSD-", 30, 0.5))  # from the account
        st, j = self.send("POST", "/api/v1/lab/tradepad", {"side": "BUY", "entry": 100, "sl": 99, "tp": 102, "lots": 0.01})
        self.assertEqual(st, 200)
        self.assertEqual(j["execution"], "BLOCKED_BY_EXECUTION_LOCK")
        self.assertEqual(self.api("/api/v1/execution/lock")["lock"], "LOCKED")

    def test_03_model_telemetry_same_inference(self):
        p = self.page
        p.goto(BASE + "/#/modele")
        p.wait_for_selector("[data-testid=start-study]")
        p.select_option("[data-testid=artifact-family]", "SEW_SNN")
        p.click("[data-testid=start-study]")
        self.assertTrue(wait_for(lambda: (self.api("/api/v1/lab/jobs")["jobs"] or [{}])[0].get("status") in ("COMPLETED", "FAILED", "CANCELLED"), 600, 2))
        job = self.api("/api/v1/lab/jobs")["jobs"][0]
        self.assertEqual(job["status"], "COMPLETED", job.get("error"))
        self.assertTrue(self.lab_ready("XAUUSD", need_model=True))
        lab = self.api("/api/v1/lab?asset=XAUUSD")
        self.assertEqual(lab["model"]["role"], "fixture_only")
        p.goto(BASE + "/#/pulpit")
        p.wait_for_selector("[data-testid=nn-activity][data-inference]", timeout=30000)
        shown = p.locator("[data-testid=nn-activity]").get_attribute("data-inference")
        lab2 = self.api("/api/v1/lab?asset=XAUUSD")
        self.assertIn(shown, (lab["model"]["inference_id"], lab2["model"]["inference_id"]))   # drawn from a real inference
        self.assertEqual(p.locator("[data-testid=nn-raster] svg").count(), 2)
        self.assertIn("SYNTETYCZNYCH", p.locator("[data-testid=nn-activity]").inner_text())
        p.screenshot(path=str(SHOTS / "pulpit_nn.png"), full_page=True)
        p.goto(BASE + "/#/badania")
        p.wait_for_selector("[data-testid=traceability] tbody tr")
        self.assertEqual(p.locator("[data-testid=traceability] tbody tr").count(), 42)
        p.wait_for_selector("[data-testid=study] table", timeout=20000)

    def test_04_switch_to_btc_all_pages_follow(self):
        p = self.page
        p.goto(BASE + "/#/ustawienia")
        p.wait_for_selector("[data-testid=asset-mapping]")
        p.click("tr[data-asset=BTC] button")
        p.wait_for_selector("[data-testid=cands-BTC] button")
        p.click("[data-testid=cands-BTC] button:has-text('Użyj')")
        wait_for(lambda: self.api("/api/v1/assets")["assets"]["BTC"]["usable"], 20, 0.5)
        p.goto(BASE + "/#/pulpit")
        p.wait_for_selector("[data-testid=asset-switch] button[data-asset=BTC]:not([disabled])", timeout=20000)
        p.click("[data-testid=asset-switch] button[data-asset=BTC]")
        self.assertTrue(wait_for(lambda: self.api("/api/v1/assets")["active"] == "BTC", 20, 0.5))
        self.assertTrue(self.lab_ready("BTC"))
        lab = self.api("/api/v1/lab?asset=BTC")
        self.assertEqual(lab["symbol"], "BTCUSD-")
        self.assertEqual(lab["model"]["status"], "no_model")                                  # the XAUUSD artefact is never used
        self.assertTrue(self.api("/api/v1/lab?asset=XAUUSD")["stale"])
        for page, sel in (("pulpit", "[data-testid=asset-card]"), ("setupy", "[data-testid=page-setupy] h2"), ("modele", "[data-testid=page-modele] h2"),
                          ("badania", "[data-testid=page-badania] h2"), ("dane", "[data-testid=page-dane] h2")):
            p.goto(f"{BASE}/#/{page}")
            p.wait_for_selector(sel)
            wait_for(lambda: "BTC" in p.locator(sel).first.inner_text(), 20, 0.5)
            self.assertIn("BTC", p.locator(sel).first.inner_text(), page)
            self.assertNotIn("XAUUSD-", p.locator("main.page").inner_text().split("Pulpit")[0] if page == "pulpit" else "", page)
            p.screenshot(path=str(SHOTS / f"btc_{page}.png"))
        # 1.15: training card (same backend as the BAT installers) - start / progress / active models / rollback controls
        p.goto(BASE + "/#/modele")
        p.wait_for_selector("[data-testid=training-card] [data-testid=tr-start]")
        p.wait_for_selector("[data-testid=tr-active] li")
        self.assertIn("forecast:", p.locator("[data-testid=tr-active]").inner_text())
        self.assertIn("XAUUSD", p.locator("[data-testid=training-card]").inner_text())
        # fast switching: the page must end on the asset that is active, never on a stale answer
        p.goto(BASE + "/#/pulpit")
        p.click("[data-testid=asset-switch] button[data-asset=XAUUSD]")
        self.assertTrue(wait_for(lambda: self.api("/api/v1/assets")["active"] == "XAUUSD", 20, 0.5))
        self.assertTrue(wait_for(lambda: p.locator("[data-testid=asset-card] h3").inner_text().startswith("XAUUSD"), 30, 0.5))
        self.assertEqual(self.errors, [])

    def test_06_indicator_modules_end_to_end(self):
        """PMW-UPD-02 AUD-04: exporter file -> ingest -> archive -> API chart/status -> panel; PAL02M honestly blocked."""
        sys.path.insert(0, str(_env.ROOT / "backend"))
        from masterquo.extind import contract
        st, m = self.send("PUT", "/api/v1/indicator-context/mapping", {"adapter": "IQ_GOLD_GANN", "product_version": "1.0", "approved": True,
                                                                         "verified_examples": [{"name": "IQG_major_1", "chart": 2650.0}],
                                                                         "rules": [{"prefix": "IQG_major", "type": "HLINE", "kind": "LEVEL", "role": "MAJOR"}]})
        self.assertEqual(st, 200, m)
        body = {"schema_version": "pmw-extind-1", "producer_version": "test", "adapter_id": "IQ_GOLD_GANN", "product": {"version": "1.0"},
                "terminal_fingerprint": "Synthetic:001", "chart_id": "1", "symbol": "XAUUSD-", "tf": "PERIOD_M5", "time_basis": "UTC",
                "captured_at_server": 1_800_000_000, "generation": 1, "sequence": 1, "complete": True,
                "objects": [{"name": "IQG_major_1", "type": "HLINE", "prices": [2650.0], "times": []}]}
        inbox = Path(self.td.dir) / "extind" / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        (inbox / "IQ_GOLD_GANN__1.json").write_bytes(contract.wrap(body))
        self.assertTrue(wait_for(lambda: self.api("/api/v1/indicator-context/chart?tf=M5")["ext_levels"], 30, 0.5))
        ch = self.api("/api/v1/indicator-context/chart?tf=M5")
        stat = self.api("/api/v1/indicator-context")
        self.assertEqual(ch["ext_levels"][0]["price"], 2650.0)
        self.assertEqual(ch["ext_levels"][0]["snapshot_id"], stat["sources"]["adapters"]["IQ_GOLD_GANN"]["last_snapshot_id"])   # same snapshot id
        self.assertEqual(ch["sar"]["profile"], "MQ_SAR_WILDER_PROFILE_V1")
        self.assertEqual(stat["sources"]["adapters"]["PAL02M"]["identity_status"], "BLOCKED_IDENTITY_REQUIRED")
        p = self.page
        p.goto(BASE + "/#/modele")
        p.wait_for_selector("[data-testid=ind-modules] tr[data-adapter=PAL02M]")
        self.assertIn("wymagana identyfikacja", p.locator("[data-testid=ind-modules] tr[data-adapter=PAL02M]").inner_text())
        self.assertEqual(self.api("/api/v1/execution/lock")["lock"], "LOCKED")
        self.assertEqual(self.errors, [])

    def test_05_mobile(self):
        p = self.page
        p.set_viewport_size({"width": 390, "height": 844})
        for sec in ("pulpit", "setupy", "modele", "badania", "dane", "ustawienia"):
            p.goto(f"{BASE}/#/{sec}")
            p.wait_for_selector(f"main.page[data-page={sec}]")
            p.wait_for_timeout(400)
            self.assertTrue(self.no_hscroll(), sec)
            p.screenshot(path=str(SHOTS / f"{sec}_390.png"))
        p.set_viewport_size({"width": 1366, "height": 900})


if __name__ == "__main__":
    unittest.main()
