"""PMW-SH-1 acceptance 16 (backend part): the SCALPING / HEDGING endpoints on a REAL server process with the SYNTHETIC
terminal (--demo, clearly marked): state, last evaluation per strategy, signals, plans, model matrix, single config source
(validated change, hash, rollback), chart data. The demo mode is SIGNALS/PAPER: no terminal order is ever created."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
import urllib.error
import urllib.request

import _env
from _env import TempData, wait_for

PORT = 8798
BASE = f"http://127.0.0.1:{PORT}"


import http.cookiejar

JAR = http.cookiejar.CookieJar()
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(JAR))
CSRF = {"v": ""}


def open_session():
    """Same as the monitor page: GET / sets the session cookie, /api/v1/session returns the CSRF token."""
    OPENER.open(BASE + "/", timeout=30).read()
    CSRF["v"] = call("/api/v1/session")[1]["csrf"]


def call(path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", "X-MQ-CSRF": CSRF["v"], "Origin": BASE},
                                 method="POST" if body is not None else "GET")
    try:
        with OPENER.open(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def health():
    try:
        return call("/api/v1/health")[0] == 200
    except Exception:
        return False


class TestSHApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = TempData()
        with open(os.path.join(cls.td.dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"server": {"port": PORT, "open_browser": False}, "news": {"enabled": False}, "clock": {"reference_url": None},
                       "first_run_completed": True}, f)
        env = dict(os.environ, MASTERQUO_DATA_DIR=cls.td.dir, PYTHONPATH=str(_env.ROOT / "backend"))
        env.pop("ANTHROPIC_API_KEY", None)
        cls.proc = subprocess.Popen([sys.executable, "-m", "masterquo", "serve", "--demo", "--no-browser"], env=env, cwd=str(_env.ROOT / "backend"),
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not wait_for(health, 90, 0.5):
            cls.proc.kill()
            raise RuntimeError("server did not start")
        open_session()

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(20)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
        cls.td.close()

    def test_endpoints(self):
        self.assertTrue(wait_for(lambda: call("/api/v1/sh")[1].get("status") == "RUNNING" and call("/api/v1/sh")[1].get("last_eval"), 120, 1.0))
        c, st = call("/api/v1/sh")
        self.assertEqual(c, 200)
        self.assertIn(st["mode"], ("SIGNALS", "PAPER"))                                   # demo default; never AUTO
        self.assertEqual(set(st["last_eval"]), {"SCALPING", "HEDGING"})
        for ev in st["last_eval"].values():
            self.assertIn(ev["status"], ("READY", "WAIT", "NO_TRADE", "INVALIDATED"))
            self.assertTrue(ev["checklist"])
            self.assertIn("USD_PRICE_MOVE", ev["tp_unit"])
        self.assertEqual(st["config_errors"], [])
        self.assertEqual(st["models"]["mode"], "OGRANICZONA")
        self.assertEqual(st["tp_model"]["status"], "NOT_TRAINED")
        self.assertIn("data", st["snapshot"])
        c, sig = call("/api/v1/sh/signals?limit=10")
        self.assertEqual(c, 200)
        self.assertTrue(sig["items"])
        c, one = call("/api/v1/sh/signals/" + sig["items"][0]["signal_id"])
        self.assertEqual((c, one["signal_id"]), (200, sig["items"][0]["signal_id"]))
        self.assertTrue(all(p["exec_mode"] in ("PAPER",) for p in call("/api/v1/sh/plans")[1]["items"]))     # no terminal order
        self.assertEqual(call("/api/v1/sh/plans/NOPE")[0], 404)
        c, ch = call("/api/v1/sh/chart?tf=M1&limit=100")
        self.assertEqual(c, 200)
        self.assertGreater(len(ch["bars"]), 50)
        self.assertEqual(call("/api/v1/sh/chart?tf=H4")[0], 400)

    def test_config_change_and_rollback(self):
        h0 = call("/api/v1/sh/config")[1]["_hash"]
        c, e = call("/api/v1/sh/config", {"instruments": {"XAUUSD": {"SCALPING": {"shares": [0.5, 0.5, 0.5]}}}})
        self.assertEqual(c, 400)
        self.assertEqual(call("/api/v1/sh/config", {"magic_number": 1})[0], 400)
        c, cfg = call("/api/v1/sh/config", {"instruments": {"XAUUSD": {"HEDGING": {"tp_usd": [3.5, 5.0, 10.0]}}}})
        self.assertEqual(c, 200)
        self.assertEqual(cfg["instruments"]["XAUUSD"]["HEDGING"]["tp_usd"][2], 10.0)
        self.assertNotEqual(cfg["_hash"], h0)
        c, back = call("/api/v1/sh/config/rollback", {})
        self.assertEqual((c, back["_hash"]), (200, h0))


if __name__ == "__main__":
    unittest.main()
