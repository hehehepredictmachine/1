"""Demo backend server helper for API tests (moved in 1.42 out of the archived 1.41 UI test test_ui_export.py)."""
from __future__ import annotations

import http.cookiejar
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

import _env
from _env import TempData, wait_for

PORT = 8781
BASE = f"http://127.0.0.1:{PORT}"


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
