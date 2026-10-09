"""Whole application process in synthetic mode: launcher, local security, secrets, WebSocket resync."""
import asyncio
import http.cookiejar
import json
import os
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request

import _env
from _env import TempData, wait_for

PORT = 8799
BASE = f"http://127.0.0.1:{PORT}"


def req(path, method="GET", data=None, headers=None, opener=None):
    r = urllib.request.Request(BASE + path, method=method, data=json.dumps(data).encode() if data is not None else None,
                               headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with (opener or urllib.request.build_opener()).open(r, timeout=10) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except (urllib.error.URLError, OSError):
        return 0, ""



class TestAppProcess(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if req("/api/v1/health")[0] == 200:
            raise RuntimeError(f"port {PORT} already serves another MasterQUO instance - stop it first")
        cls.td = TempData()
        os.makedirs(cls.td.dir, exist_ok=True)
        with open(os.path.join(cls.td.dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"server": {"port": PORT, "open_browser": False}, "news": {"enabled": False}, "clock": {"reference_url": None}}, f)
        env = dict(os.environ, MASTERQUO_DATA_DIR=cls.td.dir, PYTHONPATH=str(_env.ROOT / "backend"))
        env.pop("ANTHROPIC_API_KEY", None)
        cls.env = env
        cls.proc = subprocess.Popen([sys.executable, "-m", "masterquo", "serve", "--demo", "--no-browser"], env=env, cwd=str(_env.ROOT / "backend"),
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        ok = wait_for(lambda: req("/api/v1/health")[0] == 200, 60, 0.5)
        if not ok:
            cls.proc.kill()
            cls.td.close()
            raise RuntimeError("server did not start: " + (cls.proc.stdout.read() if cls.proc.stdout else ""))
        cls.jar = http.cookiejar.CookieJar()
        cls.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cls.jar))
        req("/", opener=cls.op)
        cls.csrf = json.loads(req("/api/v1/session", opener=cls.op)[1])["csrf"]

    @classmethod
    def tearDownClass(cls):
        subprocess.run([sys.executable, "-m", "masterquo", "stop"], env=cls.env, cwd=str(_env.ROOT / "backend"), timeout=60)
        try:
            cls.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
        cls.td.close()

    def H(self, **extra):
        return {"Origin": BASE, "X-MQ-CSRF": self.csrf, **extra}

    def test_01_health_and_single_instance(self):
        st, body = req("/api/v1/health")
        self.assertEqual(st, 200)
        self.assertTrue(json.loads(body)["synthetic"])
        out = subprocess.run([sys.executable, "-m", "masterquo", "serve", "--demo", "--no-browser"], env=self.env, cwd=str(_env.ROOT / "backend"),
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0)
        self.assertIn("już działa", out.stdout)

    def test_02_security(self):
        self.assertEqual(req("/api/v1/state")[0], 401)                                  # no session
        self.assertEqual(req("/api/v1/health", headers={"Host": "evil.example:8799"})[0], 421)  # DNS rebinding
        self.assertEqual(req("/api/v1/mode", "POST", {"mode": "PAPER"}, opener=self.op)[0], 403)  # no origin/csrf
        self.assertEqual(req("/api/v1/mode", "POST", {"mode": "PAPER"}, {"Origin": "http://evil.example", "X-MQ-CSRF": self.csrf}, self.op)[0], 403)
        self.assertEqual(req("/api/v1/mode", "POST", {"mode": "PAPER"}, {"Origin": BASE, "X-MQ-CSRF": "bad"}, self.op)[0], 403)
        st, body = req("/api/v1/mode", "POST", {"mode": "PAPER", "confirm": "PAPER"}, self.H(), self.op)
        self.assertEqual(st, 400)                                                          # authorised, but limits missing
        self.assertIn("RISK_LIMITS_NOT_CONFIGURED", body)

    def test_03_state_and_charts(self):
        self.assertTrue(wait_for(lambda: json.loads(req("/api/v1/state", opener=self.op)[1]).get("decision") is not None, 90, 1))
        s = json.loads(req("/api/v1/state", opener=self.op)[1])
        self.assertEqual(s["mode"]["mode"], "READ_ONLY")
        self.assertFalse(s["mode"]["auto_trading"])
        self.assertEqual(s["symbol"]["symbol"], "XAUUSD-")
        self.assertEqual(s["agent"]["state"], "AI_UNAVAILABLE_NO_KEY")
        self.assertEqual(s["decision"]["execution_permission"], "BLOCKED")
        for tf in ("M1", "M5", "M15", "H1", "H4", "D1"):
            c = json.loads(req(f"/api/v1/candles?tf={tf}", opener=self.op)[1])
            self.assertGreater(len(c["bars"]), 100, tf)
            self.assertIn("overlays", c)

    def test_04_secret_never_returned(self):
        key = "sk-ant-api03-SECRETVALUE-1234567890"
        self.assertEqual(req("/api/v1/secrets/anthropic", "POST", {"api_key": key}, self.H(), self.op)[0], 200)
        _, body = req("/api/v1/config", opener=self.op)
        self.assertNotIn("SECRETVALUE", body)
        _, body = req("/api/v1/state", opener=self.op)
        self.assertNotIn("SECRETVALUE", body)
        _, body = req("/api/v1/diagnostics", opener=self.op)
        self.assertNotIn("SECRETVALUE", body)
        logs = open(os.path.join(self.td.dir, "logs", "masterquo.log"), encoding="utf-8").read()
        self.assertNotIn("SECRETVALUE", logs)
        req("/api/v1/secrets", "POST", {"name": "ANTHROPIC_API_KEY", "value": None}, self.H(), self.op)

    def test_05_websocket_auth_and_resync(self):
        import websockets
        sid = next(c.value for c in self.jar if c.name == "mq_sid")

        async def run():
            hdr = {"Origin": BASE, "Cookie": f"mq_sid={sid}"}
            async with websockets.connect(f"ws://127.0.0.1:{PORT}/api/v1/ws", additional_headers=hdr) as ws:
                await ws.send(json.dumps({"csrf": self.csrf, "last_seq": None}))
                first = json.loads(await asyncio.wait_for(ws.recv(), 10))
                self.assertEqual(first["type"], "resync")
                seq, boot = first["seq"], first["boot_id"]
                ev = json.loads(await asyncio.wait_for(ws.recv(), 15))
                self.assertGreater(ev["seq"], seq)
            # reconnect asking for events since `seq` -> incremental replay (no full resync)
            async with websockets.connect(f"ws://127.0.0.1:{PORT}/api/v1/ws", additional_headers=hdr) as ws:
                await ws.send(json.dumps({"csrf": self.csrf, "last_seq": seq, "boot_id": boot}))
                m = json.loads(await asyncio.wait_for(ws.recv(), 10))
                self.assertNotEqual(m["type"], "resync")
                self.assertEqual(m["seq"], seq + 1)
            async with websockets.connect(f"ws://127.0.0.1:{PORT}/api/v1/ws", additional_headers=hdr) as ws:
                await ws.send(json.dumps({"csrf": "wrong"}))
                with self.assertRaises(websockets.ConnectionClosed) as cm:
                    await asyncio.wait_for(ws.recv(), 10)
                self.assertEqual(cm.exception.rcvd.code, 4403)
        asyncio.run(run())

    def test_06_auto_strategy_api_separate_from_execution(self):
        self.assertTrue(wait_for(lambda: json.loads(req("/api/v1/strategy/auto", opener=self.op)[1]).get("scans", 0) >= 1, 90, 1))
        a = json.loads(req("/api/v1/strategy/auto", opener=self.op)[1])
        for k in ("contract", "strategy_mode", "system_state", "regime", "selected_strategy_id", "selection_reason_codes", "candidate_ranking",
                  "last_evaluated_at", "data_status", "strategies", "setups", "why_no_setup"):
            self.assertIn(k, a)
        self.assertEqual(len(a["strategies"]), 10)
        self.assertEqual(req("/api/v1/strategy/mode", "POST", {"strategy_mode": "MANUAL", "manual_strategy_id": "S03"}, opener=self.op)[0], 403)
        st, body = req("/api/v1/strategy/mode", "POST", {"strategy_mode": "MANUAL", "manual_strategy_id": "S03"}, self.H(), self.op)
        self.assertEqual(st, 200, body)
        self.assertEqual(json.loads(body)["strategy_mode"], "MANUAL")
        self.assertEqual(req("/api/v1/strategy/mode", "POST", {"strategy_mode": "MANUAL", "manual_strategy_id": "S99"}, self.H(), self.op)[0], 400)
        st, body = req("/api/v1/strategy/toggle", "POST", {"strategy_id": "S07", "trade": False}, self.H(), self.op)
        self.assertEqual(st, 200, body)
        cfg = json.loads(req("/api/v1/config", opener=self.op)[1])["config"]["active"]
        self.assertEqual((cfg["strategy_mode"], cfg["manual_strategy_id"], cfg["strategies"]["S07"]["trade"], cfg["strategies"]["S07"]["scan"]),
                         ("MANUAL", "S03", False, True))
        s = json.loads(req("/api/v1/state", opener=self.op)[1])
        self.assertEqual((s["mode"]["mode"], s["mode"]["auto_trading"]), ("READ_ONLY", False))   # AUTO strategy selection != order execution
        self.assertEqual(req("/api/v1/strategy/mode", "POST", {"strategy_mode": "AUTO"}, self.H(), self.op)[0], 200)
        self.assertEqual(json.loads(req("/api/v1/playbook", opener=self.op)[1]).keys() >= {"cards", "note"}, True)

    def test_07_backend_keeps_working_without_browser(self):
        n1 = json.loads(req("/api/v1/strategy/auto", opener=self.op)[1])["scans"]
        time.sleep(6)                                         # no WebSocket client connected during this time
        n2 = json.loads(req("/api/v1/strategy/auto", opener=self.op)[1])["scans"]
        self.assertGreater(n2, n1)

    def test_08_gif_assets_and_upload(self):
        a = json.loads(req("/api/v1/appearance/assets", opener=self.op)[1])
        self.assertEqual(a["frog"]["source"], "BUILT_IN")
        self.assertEqual((a["frog"]["gif"]["width"], a["frog"]["gif"]["height"], a["frog"]["gif"]["frames"], a["frog"]["gif"]["transparency"]),
                         (336, 468, 22, True))
        self.assertFalse(a["background"]["animated_available"])          # the animated original was not delivered - static frame only
        gif = (_env.ROOT / "frontend" / "public" / "assets" / "masterquo" / "frog-dance.gif").read_bytes()

        def upload(data, headers):
            r = urllib.request.Request(BASE + "/api/v1/appearance/upload?slot=background", method="POST", data=data,
                                       headers={"Content-Type": "image/gif", **headers})
            try:
                with self.op.open(r, timeout=10) as resp:
                    return resp.status, resp.read().decode()
            except urllib.error.HTTPError as e:
                return e.code, e.read().decode()
        self.assertEqual(upload(gif, {})[0], 403)                          # CSRF/Origin required
        self.assertEqual(upload(b"not a gif", self.H())[0], 400)
        st, body = upload(gif, self.H())
        self.assertEqual(st, 200, body)
        a = json.loads(req("/api/v1/appearance/assets", opener=self.op)[1])
        self.assertEqual((a["background"]["source"], a["background"]["gif"]["frames"]), ("USER_UPLOAD", 22))
        with self.op.open(BASE + "/media/masterquo/background", timeout=10) as r:
            self.assertEqual(r.read(), gif)
        os.remove(os.path.join(self.td.dir, "assets", "masterquo", "background-matrix.gif"))

    def test_99_stop_only_this_server(self):
        out = subprocess.run([sys.executable, "-m", "masterquo", "stop"], env=self.env, cwd=str(_env.ROOT / "backend"),
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertTrue(wait_for(lambda: req("/api/v1/health")[0] != 200, 30, 0.5))
        self.proc.wait(timeout=30)
        self.assertEqual(self.proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
