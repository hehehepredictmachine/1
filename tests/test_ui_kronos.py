"""Kronos AI Forecast - real server process on the SYNTHETIC terminal (--demo) + Chromium.

1. Not installed: the panel says so (no forecast is invented), SHADOW / "zgoda na zlecenia: NIE" visible, the four buttons exist; API:
   strategy_use cannot be changed through settings, REQUIRED is refused without validation, PMW-PRED-1 has Kronos DISABLED with the
   reason, the model catalog lists Kronos.
2. With the STUB worker (test double, kronos_stub_worker.py) and a fixture manifest: forecasts appear only after the server clock offset is
   known and only for closed bars; the panel shows the forecast separated from real candles, the SYNTHETIC data badge, direction, timing,
   provenance; no page errors; the trading mode never changes and no order is sent. POSIX only (the stub is a shell script)."""
from __future__ import annotations

import http.cookiejar
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

import _env
from _env import wait_for

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kronos_testkit as K  # noqa: E402

try:
    from playwright.sync_api import sync_playwright  # noqa: F401
    HAVE_PW = True
except ImportError:  # pragma: no cover
    HAVE_PW = False
CHROMIUM = "/opt/pw-browsers/chromium"
SHOTS = _env.ROOT / "data" / "logs" / "ui_kronos"


class Server:
    def __init__(self, port: int, extra_env: dict | None = None, settings: dict | None = None):
        self.port, self.base = port, f"http://127.0.0.1:{port}"
        self.dir = tempfile.mkdtemp(prefix="mq_kronos_ui_")
        json.dump({"server": {"port": port, "open_browser": False}, "news": {"enabled": False}, "clock": {"reference_url": None},
                   "first_run_completed": True}, open(os.path.join(self.dir, "config.json"), "w"))
        if settings:
            os.makedirs(os.path.join(self.dir, "kronos"), exist_ok=True)
            json.dump(settings, open(os.path.join(self.dir, "kronos", "settings.json"), "w"))
        env = dict(os.environ, MASTERQUO_DATA_DIR=self.dir, PYTHONPATH=str(_env.ROOT / "backend"), **(extra_env or {}))
        env.pop("MQ_KRONOS_PYTHON", None) if not (extra_env or {}).get("MQ_KRONOS_PYTHON") else None
        self.proc = subprocess.Popen([sys.executable, "-m", "masterquo", "serve", "--demo", "--no-browser"], env=env, cwd=str(_env.ROOT / "backend"),
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.csrf = ""
        if not wait_for(self._up, 90, 0.5):
            self.stop()
            raise RuntimeError("server did not start")
        self.csrf = self.call("/api/v1/session")[1]["csrf"]

    def _up(self):
        try:
            self.op.open(self.base + "/", timeout=5).read()
            return True
        except Exception:  # noqa: BLE001
            return False

    def call(self, path, body=None, method=None):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json", "X-MQ-CSRF": self.csrf, "Origin": self.base},
                                     method=method or ("POST" if body is not None else "GET"))
        try:
            with self.op.open(req, timeout=60) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(20)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def _browse(test, srv, shot):
    from playwright.sync_api import sync_playwright
    SHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        br = pw.chromium.launch(**({"executable_path": CHROMIUM} if os.path.exists(CHROMIUM) else {}))
        p = br.new_page(viewport={"width": 1600, "height": 1100})
        errors = []
        p.on("pageerror", lambda e: errors.append(str(e)))
        p.goto(srv.base + "/#/wykresy")
        p.wait_for_selector("[data-testid=kronos-panel]", timeout=60000)
        p.wait_for_timeout(2500)
        out = {"status": p.locator("[data-testid=kronos-status]").inner_text(), "mode": p.locator("[data-testid=kronos-mode]").inner_text(),
               "buttons": [p.locator(f"[data-testid=kronos-{b}]").count() for b in ("install", "verify", "toggle", "refresh")],
               "forecast": p.locator("[data-testid=kronos-forecast]").count(), "no_forecast": p.locator("[data-testid=kronos-no-forecast]").count(),
               "synthetic": p.locator("[data-testid=kronos-synthetic]").count(), "chart_canvas": p.locator("[data-testid=kronos-chart] canvas").count(),
               "direction": p.locator("[data-testid=kronos-direction]").inner_text() if p.locator("[data-testid=kronos-direction]").count() else None,
               "timing": p.locator("[data-testid=kronos-timing]").inner_text() if p.locator("[data-testid=kronos-timing]").count() else None,
               "use": p.locator("[data-testid=kronos-strategy-use]").inner_text()}
        if out["forecast"]:
            p.click("[data-testid=kronos-refresh]")
            p.wait_for_selector("[data-testid=kronos-msg]", timeout=10000)
            out["msg"] = p.locator("[data-testid=kronos-msg]").inner_text()
        p.locator("[data-testid=sec-kronos]").screenshot(path=str(SHOTS / shot))
        br.close()
    test.assertEqual(errors, [])
    return out


@unittest.skipUnless(HAVE_PW, "playwright not installed")
class TestKronosUI(unittest.TestCase):
    def test_01_not_installed_honest_state_and_api_guards(self):
        empty = tempfile.mkdtemp(prefix="kronos_empty_")                    # no weights here (a real .venv_kronos may exist on the PC)
        srv = Server(8815, extra_env={"MQ_KRONOS_PYTHON": ""}, settings={"weights_dir": empty})
        try:
            c, st = srv.call("/api/v1/kronos")
            self.assertEqual((c, st["mode"], st["execution_permission"]), (200, "SHADOW", False))
            self.assertIn(st["status"], ("NOT_INSTALLED", "NO_WEIGHTS"))
            self.assertEqual(st["model"]["repo"], "NeoQuasar/Kronos-base")              # 1.37: largest public variant
            self.assertEqual(st["tokenizer"]["repo"], "NeoQuasar/Kronos-Tokenizer-base")
            c, r = srv.call("/api/v1/kronos/settings", {"strategy_use": {"SCALPING": {"use": "REQUIRED"}}}, method="PUT")
            self.assertEqual(c, 400)
            c, r = srv.call("/api/v1/kronos/settings", {"lookback": 9999}, method="PUT")
            self.assertEqual(c, 400)
            c, r = srv.call("/api/v1/kronos/strategy-use", {"strategy": "SCALPING", "use": "REQUIRED", "confirm": True})
            self.assertEqual(c, 409)
            self.assertIn("VALIDATION_REQUIRED", r.get("detail", ""))
            c, f = srv.call("/api/v1/kronos/forecast?instrument=XAUUSD&tf=M5")
            self.assertEqual((c, f["forecast"]), (200, None))
            self.assertEqual(srv.call("/api/v1/kronos/forecast?instrument=EURUSD&tf=M5")[0], 400)
            self.assertEqual(srv.call("/api/v1/kronos/forecast?instrument=XAUUSD&tf=H4")[0], 400)
            preds = [x for x in srv.call("/api/v1/models/predictions?instrument=XAUUSD")[1]["items"] if x["model_name"] == "Kronos-base"]
            self.assertTrue(preds and all(x["state"] == "DISABLED" and x["result"] is None and x["unavailable_reason"] for x in preds))
            cat = [x for x in srv.call("/api/v1/models/catalog?instrument=XAUUSD")[1]["items"] if x["id"] == "kronos"]
            self.assertEqual(len(cat), 1)
            ui = _browse(self, srv, "not_installed.png")
            self.assertTrue("nie zainstalowano" in ui["status"] or "brak zweryfikowanych wag" in ui["status"], ui["status"])
            self.assertIn("zgoda na zlecenia: NIE", ui["mode"])
            self.assertEqual(ui["buttons"], [1, 1, 1, 1])
            self.assertEqual((ui["forecast"], ui["no_forecast"]), (0, 1))
            self.assertIn("obserwacja (SHADOW)", ui["use"])
        finally:
            srv.stop()

    @unittest.skipUnless(os.name != "nt", "stub worker is a POSIX shell script")
    def test_02_stub_forecast_rendered_as_synthetic_shadow(self):
        tmp = tempfile.mkdtemp(prefix="kronos_stub_")
        wd = K.fixture_weights(os.path.join(tmp, "w"))
        srv = Server(8816, extra_env={"MQ_KRONOS_PYTHON": K.stub_python(tmp, "ok"), "MQ_KRONOS_ALLOW_FIXTURE": "1"},
                     settings={"weights_dir": str(wd), "instruments": ["XAUUSD"], "timeframes": ["M5", "M15"]})
        try:
            mode0 = srv.call("/api/v1/state")[1]["mode"]["mode"]
            ok = wait_for(lambda: all(t["state"] == "READY" for t in srv.call("/api/v1/kronos")[1]["targets"]) and srv.call("/api/v1/kronos")[1]["targets"],
                          150, 2.0)
            st = srv.call("/api/v1/kronos")[1]
            self.assertTrue(ok, st["targets"])
            self.assertEqual(st["status"], "READY")
            f = srv.call("/api/v1/kronos/forecast?instrument=XAUUSD&tf=M5")[1]
            fc = f["forecast"]
            self.assertTrue(f["is_current"])
            self.assertEqual((fc["data_kind"], fc["mode"], fc["execution_permission"]), ("SYNTHETIC", "SHADOW", False))
            self.assertEqual(len(fc["pred"]), 12)
            self.assertEqual(fc["quality"]["volume_source"], "TICK_VOLUME")
            bars = srv.call("/api/v1/candles?tf=M5&limit=5")[1]
            closed = [b for b in (bars.get("bars") or bars.get("items") or []) if b.get("closed")]
            if closed:
                self.assertLessEqual(fc["last_bar_open_utc"], closed[-1]["open_utc"])   # never the forming bar
            preds = {x["timeframe"]: x for x in srv.call("/api/v1/models/predictions?instrument=XAUUSD")[1]["items"] if x["model_name"] == "Kronos-base"}
            self.assertEqual(preds["M5"]["state"], "READY")
            self.assertEqual(preds["M5"]["unit"], "price")
            ui = _browse(self, srv, "stub_forecast.png")
            self.assertEqual(ui["forecast"], 1)
            self.assertEqual(ui["synthetic"], 1)
            self.assertGreaterEqual(ui["chart_canvas"], 1)
            self.assertIn(ui["direction"], ("wzrost", "spadek", "bocznie"))
            self.assertIn("ms", ui["timing"])
            self.assertIn("kolejce", ui.get("msg", ""))
            self.assertEqual(srv.call("/api/v1/state")[1]["mode"]["mode"], mode0)        # the panel never changes the trading mode
            plans = srv.call("/api/v1/sh/plans")[1].get("items", [])
            self.assertTrue(all(p.get("exec_mode") == "PAPER" for p in plans))
        finally:
            srv.stop()


if __name__ == "__main__":
    unittest.main()
