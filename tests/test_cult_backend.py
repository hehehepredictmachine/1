"""1.32 CULT interface - the backend pieces the approved panels need (no mock-ups):
* Infrastructure Monitor: GET /api/v1/system/resources - CPU / RAM of the computer, memory and uptime of the bot process (None when
  the platform does not report a value, never a guess);
* Telegram Message Studio: signal template with a fixed list of variables (no attribute access, no format specs), the simulator tag
  and the "analysis only - not an order" line are always added, preview with the last real signal or a marked example, test send
  validates the template first, the template is saved in its own file data/telegram/signal_template.json (not config.json - the
  config models are strict, so 1.31 must still read config.json after a rollback);
* Strategy Control Center presets: Save Preset / Load / Reset change only the strategy-control fields, through the same validated
  paths as the settings (strategy selection through its own endpoint), never the execution mode or risk limits."""
from __future__ import annotations

import http.cookiejar
import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import _env
from _env import TempData, wait_for

from masterquo import presets, sysres
from masterquo.config import AppConfig, TelegramConfig, telegram_template_errors
from masterquo.notify.telegram import EXAMPLE_SIGNAL, SignalTemplateStore, fmt_signal, render_signal

PORT = 8797
BASE = f"http://127.0.0.1:{PORT}"


class TestUnits(unittest.TestCase):
    def test_resources_snapshot(self):
        r = sysres.snapshot()
        self.assertEqual(set(r) >= {"cpu_pct", "memory", "started_at", "uptime_s", "pid"}, True)
        self.assertTrue(r["cpu_pct"] is None or 0 <= r["cpu_pct"] <= 100)
        m = r["memory"]
        self.assertTrue(m["used_pct"] is None or 0 < m["used_pct"] <= 100)
        self.assertTrue(m["process_mb"] is None or m["process_mb"] > 1)
        self.assertGreaterEqual(r["uptime_s"], 0)

    def test_template_validation(self):
        self.assertEqual(telegram_template_errors("{symbol} {direction} @ {entry}"), [])
        self.assertTrue(telegram_template_errors("{symbol.__class__}"))          # attribute access refused
        self.assertTrue(telegram_template_errors("{entry:>10}"))                   # format spec refused
        self.assertTrue(telegram_template_errors("{entry!r}"))
        self.assertTrue(telegram_template_errors("{confidence}"))                 # no such variable (not invented)
        self.assertTrue(telegram_template_errors("{symbol"))
        self.assertEqual(telegram_template_errors("literal {{braces}} {sl}"), [])
        self.assertNotIn("signal_template", TelegramConfig.model_fields)            # not in config.json (1.31 rollback, strict models)

    def test_template_store_file_validation_and_damage(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "telegram" / "signal_template.json"
            st = SignalTemplateStore(path)
            self.assertIsNone(st.get())
            with self.assertRaises(ValueError):
                st.set("{nope}")
            with self.assertRaises(ValueError):
                st.set("x" * 1501)
            self.assertFalse(path.exists())                                           # nothing written for a refused template
            self.assertEqual(st.set("PEPE {symbol}"), "PEPE {symbol}")
            self.assertEqual(SignalTemplateStore(path).get(), "PEPE {symbol}")       # survives a restart
            self.assertIsNone(st.set("   "))                                          # blank -> built-in format
            self.assertIsNone(SignalTemplateStore(path).get())
            path.write_text("{broken", encoding="utf-8")                              # damaged file: ignored, reported, no crash
            bad = SignalTemplateStore(path)
            self.assertIsNone(bad.get())
            self.assertTrue(bad.info()["load_error"])
            path.write_text(json.dumps({"template": "{symbol.__class__}"}), encoding="utf-8")
            self.assertIsNone(SignalTemplateStore(path).get())

    def test_render_always_marks_simulator_and_not_an_order(self):
        d = dict(EXAMPLE_SIGNAL, synthetic=True)
        t = render_signal("PEPE {symbol} {direction} E {entry} SL {sl} TP {tp}", d, "EN")
        self.assertTrue(t.startswith("[SYNTHETIC DATA]"))
        self.assertIn("PEPE XAUUSD- BUY E 2,682.00 SL 2,678.50 TP 2,688.50 / 2,692.00", t)
        self.assertTrue(t.rstrip().endswith("Analysis only – not an order."))
        self.assertIn("Signal", fmt_signal(d, "EN"))                                 # no template -> built-in format
        self.assertIn("PEPE", fmt_signal(d, "EN", "PEPE {symbol}"))
        self.assertIn("Signal", fmt_signal(d, "EN", "{broken"))                     # broken template never blocks a message

    def test_preset_store(self):
        with tempfile.TemporaryDirectory() as d:
            st = presets.PresetStore(d)
            cfg = AppConfig().model_dump(mode="json")
            cfg["active"]["thresholds"]["confirmed"] = 75.0
            item = st.save("Gold Alpha", cfg)
            self.assertEqual(item["values"]["active.thresholds"]["confirmed"], 75.0)
            self.assertEqual([x["name"] for x in st.list()], ["Gold Alpha"])
            with self.assertRaises(ValueError):
                st.save("../x", cfg)
            patch = presets.patch_of(item["values"])
            self.assertEqual(set(patch), {"active", "risk", "strategy"})
            self.assertNotIn("execution", patch)                                      # never the execution mode
            self.assertNotIn("risk_per_trade_pct", patch["risk"])                    # nor the risk limits
            self.assertEqual(presets.defaults()["active.thresholds"], AppConfig().active.thresholds.model_dump()
                             if hasattr(AppConfig().active.thresholds, "model_dump") else AppConfig().active.thresholds)


JAR = http.cookiejar.CookieJar()
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(JAR))
CSRF = {"v": ""}


def call(path, body=None, method=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", "X-MQ-CSRF": CSRF["v"], "Origin": BASE},
                                 method=method or ("POST" if body is not None else "GET"))
    try:
        with OPENER.open(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def health():
    try:
        with urllib.request.urlopen(BASE + "/api/v1/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


class TestApi(unittest.TestCase):
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
        OPENER.open(BASE + "/", timeout=30).read()
        CSRF["v"] = call("/api/v1/session")[1]["csrf"]

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(20)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
        cls.td.close()

    def test_01_resources(self):
        c, r = call("/api/v1/system/resources")
        self.assertEqual(c, 200)
        self.assertIn("cpu_pct", r)
        self.assertGreater(r["uptime_s"], 0)

    def test_02_telegram_template_preview_save_test(self):
        c, p = call("/api/v1/telegram/preview", {"template": None})
        self.assertEqual(c, 200)
        self.assertIn(p["source"], ("LAST_SIGNAL", "EXAMPLE"))
        if p["source"] == "EXAMPLE":
            self.assertTrue(p["text"].startswith("[EXAMPLE"))                          # an example is never shown as a signal
        self.assertIn("symbol", p["variables"])
        c, p = call("/api/v1/telegram/preview", {"template": "PEPE {symbol} {direction}"})
        self.assertEqual(c, 200)
        self.assertIn("PEPE", p["text"])
        self.assertIn("not an order", p["text"])
        self.assertEqual(call("/api/v1/telegram/preview", {"template": "{symbol.__class__}"})[0], 400)
        self.assertEqual(call("/api/v1/telegram/test", {"template": "{nope}"})[0], 400)    # validated before anything is sent
        c, r = call("/api/v1/telegram/test", {"template": "PEPE {symbol}"})                 # not configured: reported, not faked
        self.assertEqual(c, 200)
        self.assertFalse(r["ok"])
        self.assertIn("NOT_CONFIGURED", r["error"])
        c, info = call("/api/v1/telegram/template", {"template": "PEPE {symbol} {direction}"}, method="PUT")
        self.assertEqual(c, 200)
        self.assertEqual(info["template"], "PEPE {symbol} {direction}")
        self.assertEqual(call("/api/v1/telegram/template")[1]["template"], "PEPE {symbol} {direction}")
        self.assertEqual(call("/api/v1/telegram/template", {"template": "{x}"}, method="PUT")[0], 400)
        self.assertEqual(call("/api/v1/telegram/template")[1]["template"], "PEPE {symbol} {direction}")   # refused -> unchanged
        self.assertIn("PEPE", call("/api/v1/telegram/preview", {})[1]["text"])               # saved template is used
        self.assertTrue((Path(type(self).td.dir) / "telegram" / "signal_template.json").exists())
        self.assertEqual(call("/api/v1/config", {"telegram": {"signal_template": "PEPE"}}, method="PUT")[0], 400)  # not a config key
        raw = json.loads((Path(type(self).td.dir) / "config.json").read_text(encoding="utf-8"))
        self.assertNotIn("signal_template", raw["telegram"])                                 # config.json stays readable by 1.31

    def test_03_presets_roundtrip_touch_only_strategy_fields(self):
        before = call("/api/v1/config")[1]["config"]
        c, cfg = call("/api/v1/config", {"active": {"thresholds": {"watch": 41.0, "early": 56.0, "confirmed": 72.0}},
                                         "risk": {"max_spread_points": 35}}, method="PUT")
        self.assertEqual(c, 200)
        c, item = call("/api/v1/presets/strategy", {"name": "Gold Alpha"})
        self.assertEqual(c, 200)
        self.assertEqual(item["values"]["active.thresholds"]["confirmed"], 72.0)
        call("/api/v1/config", {"active": {"thresholds": {"watch": 40.0, "early": 55.0, "confirmed": 70.0}}}, method="PUT")
        c, cfg = call("/api/v1/presets/strategy/load", {"name": "Gold Alpha"})
        self.assertEqual(c, 200)
        self.assertEqual(cfg["config"]["active"]["thresholds"]["confirmed"], 72.0)
        self.assertEqual(cfg["config"]["risk"]["max_spread_points"], 35)
        self.assertEqual(cfg["config"]["execution"]["mode"], before["execution"]["mode"])      # execution mode untouched
        self.assertEqual(cfg["config"]["risk"]["risk_per_trade_pct"], before["risk"]["risk_per_trade_pct"])
        c, cfg = call("/api/v1/presets/strategy/reset", {})
        self.assertEqual(c, 200)
        self.assertEqual(cfg["config"]["active"]["thresholds"]["confirmed"], 70.0)
        self.assertIsNone(cfg["config"]["risk"]["max_spread_points"])
        lst = call("/api/v1/presets/strategy")[1]
        self.assertEqual([x["name"] for x in lst["items"]], ["Gold Alpha"])
        self.assertEqual(call("/api/v1/presets/strategy/load", {"name": "nope"})[0], 404)
        self.assertEqual(call("/api/v1/presets/strategy", {"name": "../../etc"})[0], 400)
        logs = call("/api/v1/logs")[1]
        self.assertTrue(any(l.get("code") == "PRESET_LOADED" for l in logs))


if __name__ == "__main__":
    unittest.main()
