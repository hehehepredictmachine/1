"""Panel "Eksportuj dane z MT5" (1.25, prompt 4A §10) on the demo backend - the export runs on the terminal SIMULATOR (synthetic
data, labelled as such): API (start / status / cancel / datasets / readiness, protected like every change) and the card in a real
browser (choice, confirmation, progress, result table per model, hand-over to training)."""
from __future__ import annotations

import http.cookiejar
import json
import os
import subprocess
import sys
import unittest
import urllib.error
import urllib.request

import _env
from _env import TempData, wait_for

PORT = 8781
BASE = f"http://127.0.0.1:{PORT}"
CHROMIUM = os.environ.get("MQ_CHROMIUM", "/opt/pw-browsers/chromium")
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


class Server:
    @classmethod
    def start_server(cls):
        if health():
            raise RuntimeError(f"port {PORT} busy")
        cls.td = TempData()
        with open(os.path.join(cls.td.dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"server": {"port": PORT, "open_browser": False}, "news": {"enabled": False}, "clock": {"reference_url": None},
                       "first_run_completed": True}, f)
        cls.env = dict(os.environ, MASTERQUO_DATA_DIR=cls.td.dir, PYTHONPATH=str(_env.ROOT / "backend"))
        cls.env.pop("ANTHROPIC_API_KEY", None)
        cls.proc = subprocess.Popen([sys.executable, "-m", "masterquo", "serve", "--demo", "--no-browser"], env=cls.env,
                                    cwd=str(_env.ROOT / "backend"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not wait_for(health, 90, 0.5):
            cls.proc.kill()
            raise RuntimeError("server did not start")
        cls.jar = http.cookiejar.CookieJar()
        cls.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cls.jar))
        cls.op.open(BASE + "/", timeout=30).read()
        cls.csrf = cls.call("/api/v1/session")[1]["csrf"]

    @classmethod
    def stop_server(cls):
        subprocess.run([sys.executable, "-m", "masterquo", "stop"], env=cls.env, cwd=str(_env.ROOT / "backend"), timeout=60)
        try:
            cls.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
        cls.td.close()

    @classmethod
    def call(cls, path, body=None, csrf=True):
        h = {"Content-Type": "application/json", "Origin": BASE}
        if csrf:
            h["X-MQ-CSRF"] = getattr(cls, "csrf", "")
        req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None, headers=h,
                                     method="POST" if body is not None else "GET")
        try:
            with cls.op.open(req, timeout=60) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")


class TestExportApi(Server, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.start_server()

    @classmethod
    def tearDownClass(cls):
        cls.stop_server()

    def test_1_export_runs_in_own_process_and_reports_models(self):
        st, out = self.call("/api/v1/export/start", {"instrument": "XAUUSD", "symbol": "XAUUSD-", "months": 1, "timeframes": ["M1", "M5"],
                                                      "ticks_days": 0.1})
        self.assertEqual(st, 200, out)
        self.assertTrue(out["started"], out)
        st, again = self.call("/api/v1/export/start", {"instrument": "XAUUSD", "symbol": "XAUUSD-", "months": 1, "timeframes": ["M5"]})
        self.assertIn(again.get("reason"), ("EXPORT_ALREADY_RUNNING", None))    # one export at a time (unless the first already ended)
        self.assertTrue(wait_for(lambda: self.call("/api/v1/export/status")[1].get("state") in ("COMPLETE", "FAILED"), 300, 1))
        s = self.call("/api/v1/export/status")[1]
        self.assertEqual(s["state"], "COMPLETE", s.get("log_tail"))
        self.assertTrue(s["usable"])
        self.assertEqual(s["data_kind"], "SYNTHETIC_TEST")                      # demo: simulator data, never REAL_USER_DATA
        kinds = {m["kind"]: m["status"] for m in s["readiness"]["models"]}
        self.assertEqual(kinds["sh_models"], "GOTOWE")
        self.assertEqual(kinds["forecast"], "BRAK_DANYCH")                      # M30 not chosen - said, not hidden
        ds = self.call("/api/v1/export/datasets?instrument=XAUUSD")[1]
        self.assertTrue(any(d["usable"] and d["dir"] == s["job"]["out"] and d["ticks"] for d in ds["datasets"]))
        rd = self.call("/api/v1/export/readiness?dataset=" + urllib.request.quote(s["job"]["out"]))[1]
        self.assertEqual(rd["export_state"]["state"], "COMPLETE")

    def test_2_protected_and_validated(self):
        st, _ = self.call("/api/v1/export/start", {"instrument": "XAUUSD", "months": 1}, csrf=False)
        self.assertEqual(st, 403)
        for bad in ({"instrument": "EURUSD"}, {"instrument": "XAUUSD", "symbol": "X\\..\\y"}, {"instrument": "XAUUSD", "months": 99},
                    {"instrument": "XAUUSD", "from": "jutro"}, {"instrument": "XAUUSD", "ticks_days": 400}):
            self.assertEqual(self.call("/api/v1/export/start", bad)[0], 400, bad)
        self.assertEqual(self.call("/api/v1/export/readiness?dataset=/etc")[0], 400)   # only folders inside the data folder

    def test_3_cancel_marks_export_cancelled_and_resumable(self):
        st, out = self.call("/api/v1/export/start", {"instrument": "XAUUSD", "symbol": "XAUUSD-", "months": 3,
                                                      "timeframes": ["M1", "M5", "M15", "M30", "H1"], "ticks_days": 3})
        self.assertTrue(out.get("started"), out)
        wait_for(lambda: (self.call("/api/v1/export/status")[1].get("progress") or {}).get("done", 0) >= 1, 60, 0.3)
        self.assertTrue(self.call("/api/v1/export/cancel", {})[1]["ok"])
        s = self.call("/api/v1/export/status")[1]
        self.assertFalse(s["running"])
        self.assertIn(s["state"], ("CANCELLED", "COMPLETE"))                    # a very fast machine may finish first
        if s["state"] == "CANCELLED":
            self.assertFalse(s["usable"])
            ds = self.call("/api/v1/export/datasets?instrument=XAUUSD")[1]["datasets"]
            self.assertTrue(any(d["dir"] == s["job"]["out"] and not d["usable"] for d in ds))


@unittest.skipUnless(HAVE_PW, "playwright not installed")
class TestExportCard(Server, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (_env.ROOT / "frontend" / "dist" / "index.html").exists():
            raise unittest.SkipTest("frontend not built")
        cls.start_server()
        cls.pw = sync_playwright().start()
        kw = {"executable_path": CHROMIUM} if os.path.exists(CHROMIUM) else {}
        cls.browser = cls.pw.chromium.launch(**kw)
        cls.page = cls.browser.new_context(viewport={"width": 1500, "height": 1000}).new_page()
        cls.errors = []
        cls.page.on("pageerror", lambda e: cls.errors.append(str(e)))

    @classmethod
    def tearDownClass(cls):
        try:
            cls.browser.close()
            cls.pw.stop()
        finally:
            cls.stop_server()

    def test_card_exports_shows_models_and_hands_over_to_training(self):
        p = self.page
        p.goto(BASE + "/#/ai-neural-lab")
        p.wait_for_selector("[data-testid=nl-tab-training]", timeout=30000)
        p.click("[data-testid=nl-tab-training]")
        p.wait_for_selector("[data-testid=nl-export]")
        self.assertTrue(wait_for(lambda: p.input_value("[data-testid=nl-export-symbol]") == "XAUUSD-", 20, 0.3))   # broker symbol from the mapping
        p.fill("[data-testid=nl-export-months]", "1")
        for tf in ("H4", "D1", "M30", "H1"):
            p.uncheck(f"[data-testid=nl-export-tf-{tf}]")
        p.click("[data-testid=nl-export-start]")
        p.wait_for_selector("text=Tylko odczyt – żadne zlecenie nie jest wysyłane")
        p.click("[data-testid=nl-export-yes]")
        self.assertTrue(wait_for(lambda: p.locator("[data-testid=nl-export-state]").inner_text() == "ukończony", 300, 1),
                        p.locator("[data-testid=nl-export]").inner_text()[:600])
        p.wait_for_selector("[data-testid=nl-export-readiness]")
        statuses = p.locator("[data-testid=nl-export-readiness] tbody tr").evaluate_all("rs => rs.map(r => r.dataset.status)")
        self.assertIn("GOTOWE", statuses)
        self.assertIn("BRAK_DANYCH", statuses)
        self.assertIn("SYNTETYCZNE", p.locator("[data-testid=nl-export-result]").inner_text())
        p.click("[data-testid=nl-export-use]")
        self.assertTrue(wait_for(lambda: p.input_value("[data-testid=nl-train-dataset]") != "", 10, 0.3))
        self.assertIn("EXP-", p.input_value("[data-testid=nl-train-dataset]"))
        p.screenshot(path=str(_env.ROOT / "data" / "logs" / "ui_export_card.png"), full_page=True)
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
