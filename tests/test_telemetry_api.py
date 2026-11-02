"""1.26 read-only telemetry for the main menu's model-flow maps and the Profits view:
- EventBus.activity(): real publishing count / last time / last sequence per topic (nothing invented, copies not views);
- account_stats: deposits and withdrawals reported separately (never profit), credit / bonus apart;
- GET /api/v1/telemetry on a running demo backend: topics with real counts, model registry rows with roles, SCALPING / HEDGING state,
  decision nodes; requires the monitor session like every other route; no secret-looking fields; not writable (POST -> 405)."""
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

from masterquo import stats  # noqa: E402
from masterquo.events import EventBus  # noqa: E402

PORT = 8788
BASE = f"http://127.0.0.1:{PORT}"
JAR = http.cookiejar.CookieJar()
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(JAR))


def call(path, method="GET", opener=OPENER):
    req = urllib.request.Request(BASE + path, method=method, headers={"Origin": BASE}, data=b"{}" if method == "POST" else None)
    try:
        with opener.open(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}


def health():
    try:
        return call("/api/v1/health")[0] == 200
    except Exception:
        return False


class TestBusActivity(unittest.TestCase):
    def test_counts_only_real_publications(self):
        bus = EventBus()
        self.assertEqual(bus.activity(), {})
        bus.publish("bar", {"tf": "M5"})
        bus.publish("bar", {"tf": "M1"})
        bus.publish("decision", {})
        a = bus.activity()
        self.assertEqual(a["bar"]["count"], 2)
        self.assertEqual(a["decision"]["count"], 1)
        self.assertEqual(a["decision"]["last_seq"], 3)
        self.assertTrue(a["bar"]["last_ts"])
        a["bar"]["count"] = 999                                         # a copy - callers cannot change the bus
        self.assertEqual(bus.activity()["bar"]["count"], 2)


class TestDepositsAreNotProfit(unittest.TestCase):
    def test_deposits_withdrawals_separate(self):
        deals = [{"type": 0, "symbol": "XAUUSD-", "profit": 12.0, "commission": -1.0, "swap": 0.0, "time": 10},
                 {"type": 2, "profit": 1000.0, "time": 5}, {"type": 2, "profit": -300.0, "time": 20},
                 {"type": 3, "profit": 50.0, "time": 30}]                # credit / bonus - a flow, not a deposit and not profit
        s = stats.account_stats(deals, "XAUUSD-", None)
        self.assertEqual(s["trading_net_all_symbols"], 11.0)
        self.assertEqual((s["deposits"], s["withdrawals"]), (1000.0, -300.0))
        self.assertEqual(s["balance_operations"], 700.0)
        self.assertEqual(s["credit_bonus_other_flows"], 50.0)
        self.assertEqual(s["deals"], 1)


class TestTelemetryEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = TempData()
        with open(os.path.join(cls.td.dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"server": {"port": PORT, "open_browser": False}, "news": {"enabled": False}, "clock": {"reference_url": None},
                       "first_run_completed": True}, f)
        cls.env = dict(os.environ, MASTERQUO_DATA_DIR=cls.td.dir, PYTHONPATH=str(_env.ROOT / "backend"), MQ_FAKE_MARKET_ALWAYS_OPEN="1")
        cls.env.pop("ANTHROPIC_API_KEY", None)
        cls.proc = subprocess.Popen([sys.executable, "-m", "masterquo", "serve", "--demo", "--no-browser"], env=cls.env, cwd=str(_env.ROOT / "backend"),
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not wait_for(health, 60, 0.5):
            cls.proc.kill()
            raise RuntimeError("server did not start")
        OPENER.open(BASE + "/", timeout=30).read()                       # the monitor page sets the session cookie

    @classmethod
    def tearDownClass(cls):
        subprocess.run([sys.executable, "-m", "masterquo", "stop"], env=cls.env, cwd=str(_env.ROOT / "backend"), timeout=60)
        try:
            cls.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
        cls.td.close()

    def test_shape_and_real_activity(self):
        self.assertTrue(wait_for(lambda: (call("/api/v1/telemetry")[1].get("topics") or {}).get("quote", {}).get("count", 0) > 0, 60, 0.5))
        code, d = call("/api/v1/telemetry")
        self.assertEqual(code, 200)
        for k in ("server_time", "boot_id", "seq", "instrument", "topics", "models", "sh", "engine"):
            self.assertIn(k, d)
        self.assertGreater(d["seq"], 0)
        for t in d["topics"].values():
            self.assertGreater(t["count"], 0)
            self.assertLessEqual(t["last_seq"], d["seq"])
        rows = d["models"]["rows"]
        self.assertGreater(len(rows), 5)
        for r in rows:
            self.assertTrue({"id", "name", "kind", "status", "roles"} <= set(r))
            self.assertEqual(set(r["roles"]), {"SCALPING", "HEDGING"})
        self.assertIn("status", d["sh"])
        blob = json.dumps(d).lower()
        for secret in ("api_key", "password", "token\":", "secret"):
            self.assertNotIn(secret, blob)

    def test_session_required_and_read_only(self):
        fresh = urllib.request.build_opener()                              # no session cookie
        self.assertEqual(call("/api/v1/telemetry", opener=fresh)[0], 401)
        self.assertEqual(call("/api/v1/telemetry", method="POST")[0] in (403, 405), True)


if __name__ == "__main__":
    unittest.main()
