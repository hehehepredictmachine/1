"""Signal card in the REAL monitor (Chromium + the real demo backend). Every display state is produced by the real engine
code (signal_contract.build + signal_view.present) and delivered through the monitor's WebSocket (Playwright routes the
socket: the server stream passes through, the decision payload is replaced). Checks: BUY, SELL, waiting with the plan
direction, no signal, block, no data, AI unavailable, late AI answer, expiry, reconnect, copy = card values, the live
engine decision = card, readable layout at 1920/1366/900 px. Screenshots: data/logs/ui_signal_card/.
Skipped (never "passed") without Playwright/Chromium or the license server package."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone

import _env
from _env import TempData, wait_for
from _license import LicenseServerFixture  # noqa: E402

PORT = 8796
BASE = f"http://127.0.0.1:{PORT}"
CHROMIUM = os.environ.get("MQ_CHROMIUM", "/opt/pw-browsers/chromium")
SHOTS = _env.ROOT / "data" / "logs" / "ui_signal_card"
try:
    from playwright.sync_api import sync_playwright
    HAVE_PW = True
except ImportError:  # pragma: no cover
    HAVE_PW = False


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def make_decision(kind: str, *, valid_s: int = 3600) -> dict:
    """A decision record as the engine publishes it, built with the engine's own contract + presentation code."""
    from masterquo.engine import signal_contract as sc
    from masterquo.engine import signal_view as sv
    from test_signal_contract import build, decision
    now = datetime.now(timezone.utc)
    stage, dec, nodes, side, perm = "CONFIRMED", "BUY", {}, "LONG", "ALLOWED"
    agent_status, agent_result = {"state": "IDLE"}, None
    if kind == "SELL":
        dec, side = "SELL", "SHORT"
    elif kind == "WAIT":
        stage, dec = "EARLY_SETUP", "WAIT"
    elif kind == "BLOCK":
        dec, nodes = "NO_TRADE", {"RISK": "FAIL"}
    elif kind == "NODATA":
        nodes = {"DATA": "FAIL"}
    elif kind == "NOAI":
        agent_status = {"state": "AI_UNAVAILABLE_NO_KEY"}
    d = decision(stage=stage, decision=dec, nodes=nodes, permission=perm)
    d["as_of_utc"] = iso(now)
    d["decision_id"] = f"MQD-UI-{kind}"
    if side == "SHORT":
        d["setup"] = {**d["setup"], "direction": "SHORT"}
        d["levels"] = {"stop_loss": 2410.0, "targets": [{"price": 2380.0, "weight": 1.0}]}
    if kind == "LATEAI":
        agent_result = {"status": "OK", "record": {"setup_id": "S11-X", "proposed_action": "BUY", "explanation_pl": "stara ocena"},
                        "setup_state_changed_at": "2026-10-11T08:00:00Z"}
    row = {"status": "ACTIVE", "expires_at": iso(now + timedelta(seconds=valid_s))}
    sig = None if kind == "NONE" else build(d, row=row, agent_status=agent_status, agent_result=agent_result)
    if kind == "NONE":
        d["setup"] = None
    d["checklist"] = {"status": "NO_SCENARIO", "why": ["S01: brak impulsu", "S11: brak dotknięcia EMA20"], "gates": [{"id": "DATA", "status": "MET"}]} \
        if kind == "NONE" else {
        "status": "SCENARIO", "met": [{"id": "STRATEGY_RULE", "label": "x", "reading": "EMA20>EMA50, ADX_27"}],
        "missing": [] if stage == "CONFIRMED" else [{"id": "CONFIRMATION_CLOSE_ABOVE_EMA20_ON_LATER_BAR", "label": "Zamknięcie powyżej EMA20",
                                                       "required": "na świecy późniejszej niż dotknięcie", "status": "MISSING"}],
        "trigger": {"description": "zamknięcie świecy M30 powyżej EMA20", "met": stage == "CONFIRMED"},
        "gates": [{"id": "DATA", "status": "MISSING" if kind == "NODATA" else "MET"}, {"id": "MARKET", "status": "MET"},
                  {"id": "RISK", "status": "MISSING" if kind == "BLOCK" else "MET", "reasons": ["RISK_X"] if kind == "BLOCK" else []}]}
    d["signal"] = sc.ttl_status(sig, iso(now)) if sig else None
    d["signal_view"] = sv.present(d, d["signal"], symbol="XAUUSD-", digits=2, execution_mode="PAPER")
    d["tf_overview"] = [{"tf": tf, "role": "interwał wejścia" if tf == "M30" else "kontekst", "direction": "UP" if i % 3 else "DOWN", "data": "OK",
                         "last_closed_utc": iso(now - timedelta(minutes=30)), "forming": True, "source": "native",
                         "conflict": tf == "H8", "conflict_impact": "informacyjnie – nie zmienia kwalifikacji" if tf == "H8" else None}
                        for i, tf in enumerate(["M1", "M5", "M15", "M30", "H1", "H4", "H8", "D1"])]
    return d


@unittest.skipUnless(HAVE_PW, "playwright not installed")
class TestSignalCardUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (_env.ROOT / "frontend" / "dist" / "index.html").exists():
            raise unittest.SkipTest("frontend not built")
        SHOTS.mkdir(parents=True, exist_ok=True)
        cls.td = TempData()
        cls.lic = LicenseServerFixture()
        info = cls.lic.issue(note="ui signal card")
        with open(os.path.join(cls.td.dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"server": {"port": PORT, "open_browser": False}, "news": {"enabled": False}, "clock": {"reference_url": None},
                       **cls.lic.client_config(), "first_run_completed": True}, f)
        cls.env = dict(os.environ, MASTERQUO_DATA_DIR=cls.td.dir, PYTHONPATH=str(_env.ROOT / "backend"))
        cls.env.pop("ANTHROPIC_API_KEY", None)
        cls.proc = subprocess.Popen([sys.executable, "-m", "masterquo", "serve", "--demo", "--no-browser"], env=cls.env, cwd=str(_env.ROOT / "backend"),
                                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.proc.stdin.write((info["key"] + "\n").encode())
        cls.proc.stdin.close()
        import urllib.request

        def health():
            try:
                with urllib.request.urlopen(BASE + "/api/v1/health", timeout=3) as r:
                    return r.status == 200
            except Exception:
                return False
        if not wait_for(health, 60, 0.5):
            cls.proc.kill()
            raise RuntimeError("server did not start")
        cls.pw = sync_playwright().start()
        kw = {"executable_path": CHROMIUM} if os.path.exists(CHROMIUM) else {}
        cls.browser = cls.pw.chromium.launch(**kw)
        cls.override = None
        cls.routes = []
        cls.ctx = cls.browser.new_context(viewport={"width": 1920, "height": 1080}, permissions=["clipboard-read", "clipboard-write"])
        cls.page = cls.ctx.new_page()
        cls.errors = []
        cls.page.on("console", lambda m: cls.errors.append(m.text) if m.type == "error" else None)

        def on_ws(ws):
            server = ws.connect_to_server()
            cls.routes.append(ws)

            def from_server(msg):
                if cls.override is not None and isinstance(msg, str):
                    m = json.loads(msg)
                    if m.get("type") == "decision":
                        m["data"] = cls.override
                    elif m.get("type") == "resync":
                        m["state"]["decision"] = cls.override
                    msg = json.dumps(m)
                ws.send(msg)
            server.on_message(from_server)
        cls.page.route_web_socket(re.compile(r".*/api/v1/ws$"), on_ws)
        cls.page.goto(BASE + "/")
        cls.page.wait_for_selector("[data-testid=signal-hero]", timeout=30000)
        wait_for(lambda: cls.page.evaluate("() => document.querySelector('[data-testid=signal-hero]').dataset.state") not in (None, ""), 20, 0.5)

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
            cls.lic.close()

    # ------------------------------------------------------------ helpers
    def show(self, kind: str, **kw) -> dict:
        d = make_decision(kind, **kw)
        type(self).override = d
        self.routes[-1].send(json.dumps({"type": "decision", "data": d}))
        self.page.wait_for_function(f"() => document.querySelector('[data-testid=signal-hero]')?.dataset.state === {json.dumps(self.expected(d))}",
                                    timeout=10000)
        return d

    @staticmethod
    def expected(d):
        return d["signal_view"]["state"]

    def state(self):
        return self.page.get_attribute("[data-testid=signal-hero]", "data-state")

    def text(self, sel):
        return self.page.inner_text(sel).replace(" ", " ").replace(" ", " ")

    def shot(self, name):
        self.page.locator("[data-testid=signal-top]").screenshot(path=str(SHOTS / f"{name}.png"))

    # ------------------------------------------------------------ scenarios
    def test_01_live_engine_decision_matches_card(self):
        type(self).override = None
        r = self.page.request.get(BASE + "/api/v1/state")
        v = (r.json().get("decision") or {}).get("signal_view")
        self.assertIsNotNone(v, "engine did not publish signal_view")
        wait_for(lambda: self.state() == self.page.request.get(BASE + "/api/v1/state").json()["decision"]["signal_view"]["state"], 20, 0.5)
        cur = self.page.request.get(BASE + "/api/v1/state").json()["decision"]["signal_view"]
        self.assertEqual(self.state(), cur["state"])
        self.assertEqual(len(self.page.locator("[data-testid=tf-overview] .tfo").all()), 8)
        self.shot("00_live_engine")

    def test_02_buy(self):
        self.show("BUY")
        self.assertEqual(self.text("[data-testid=hero-state]"), "BUY")
        self.assertIn("2400,30", self.text("[data-testid=lv-wejście]"))
        self.assertIn("2390,00", self.text("[data-testid=lv-sl]"))
        self.assertIn("2425,00", self.text("[data-testid=lv-tp]"))
        self.assertIn("2,31", self.text("[data-testid=lv-rr]"))
        self.assertIn("nie wysłano", self.text("[data-testid=hero-fill]"))          # no "executed" before a fill
        self.assertIn("Do potwierdzenia brakuje: nic", self.text("[data-testid=missing-summary]"))
        self.assertEqual(self.page.locator("[data-testid=hero-plan]").count(), 0)
        self.shot("01_buy")
        self.page.click("[data-testid=hero-copy]")
        clip = self.page.evaluate("() => navigator.clipboard.readText()").replace(" ", " ")
        for part in ("BUY XAUUSD-", "wejście 2400,30", "SL 2390,00", "TP 2425,00", "RR 2,31", "ważny do"):
            self.assertIn(part, clip)
        self.assertFalse(clip.startswith("PLAN"))

    def test_03_sell(self):
        self.show("SELL")
        self.assertEqual(self.text("[data-testid=hero-state]"), "SELL")
        self.assertIn("2400,00", self.text("[data-testid=lv-wejście]"))             # SELL plans on Bid
        self.assertIn("otwarcie pozycji SHORT", self.text("[data-testid=signal-hero]"))
        self.shot("02_sell")

    def test_04_waiting_with_plan(self):
        self.show("WAIT")
        self.assertEqual(self.text("[data-testid=hero-state]"), "OCZEKIWANIE")
        self.assertEqual(self.text("[data-testid=hero-plan]"), "Plan: BUY")
        self.assertIn("Zamknięcie powyżej EMA20", self.text("[data-testid=missing-summary]"))
        self.assertIn("✗", self.text("[data-testid=simple-checklist]"))
        self.shot("03_waiting")
        self.page.click("[data-testid=hero-copy]")
        self.assertTrue(self.page.evaluate("() => navigator.clipboard.readText()").startswith("PLAN BUY"))

    def test_05_no_signal_block_no_data(self):
        self.show("NONE")
        self.assertEqual(self.text("[data-testid=hero-state]"), "BRAK SYGNAŁU")
        self.assertIn("S11: brak dotknięcia EMA20", self.text("[data-testid=signal-hero]"))
        self.assertEqual(self.page.locator("[data-testid=hero-copy]").count(), 0)
        self.shot("04_no_signal")
        self.show("BLOCK")
        self.assertEqual(self.text("[data-testid=hero-state]"), "BLOKADA")
        self.assertIn("Powód blokady", self.text("[data-testid=hero-block]"))
        self.shot("05_block")
        self.show("NODATA")
        self.assertEqual(self.text("[data-testid=hero-state]"), "BRAK DANYCH")
        self.shot("06_no_data")

    def test_06_ai_unavailable_and_late_ai(self):
        self.show("NOAI")
        self.assertEqual(self.text("[data-testid=hero-ai]"), "AI NIEDOSTĘPNE")
        self.assertEqual(self.text("[data-testid=hero-state]"), "BUY")              # AI absence is visible, strategy signal stays
        self.shot("07_ai_unavailable")
        d = self.show("LATEAI")
        self.assertIn("nieaktualna", self.text("[data-testid=hero-ai]"))
        self.assertEqual(d["signal_view"]["source"], "STRATEGIA")
        self.assertIn("STRATEGIA", self.text("[data-testid=signal-hero]"))

    def test_07_expiry_downgrades_immediately(self):
        self.show("BUY", valid_s=3)
        self.page.wait_for_function("() => document.querySelector('[data-testid=signal-hero]').dataset.state === 'NIEAKTUALNY'", timeout=8000)
        self.assertEqual(self.text("[data-testid=hero-state]"), "NIEAKTUALNY")
        self.shot("08_expired")

    def test_08_reconnect_never_restores_old_buy(self):
        self.show("BUY")
        type(self).override = None                       # the backend's real state from now on
        self.routes[-1].close()
        self.page.wait_for_function("() => document.querySelector('[data-testid=signal-hero]').dataset.state === 'BRAK_DANYCH'", timeout=8000)
        self.shot("09_disconnected")
        wait_for(lambda: self.page.evaluate("() => document.querySelector('[data-testid=signal-hero]').dataset.state") != "BRAK_DANYCH", 20, 0.5)
        real = self.page.request.get(BASE + "/api/v1/state").json()["decision"]["signal_view"]
        wait_for(lambda: self.state() == self.page.request.get(BASE + "/api/v1/state").json()["decision"]["signal_view"]["state"], 20, 0.5)
        self.assertNotEqual(self.page.get_attribute("[data-testid=signal-hero]", "data-state") + real.get("decision_id", ""), "BUYMQD-UI-BUY")
        self.assertNotIn("MQD-UI-BUY", self.page.inner_text("[data-testid=signal-hero]"))

    def test_09_layout_sizes_and_console(self):
        self.show("BUY")
        for w, h in ((1366, 768), (900, 1000)):
            self.page.set_viewport_size({"width": w, "height": h})
            time.sleep(0.4)
            box = self.page.locator("[data-testid=signal-hero]").bounding_box()
            self.assertLessEqual(box["x"] + box["width"], w + 1)                  # no horizontal overflow of the card
            self.assertGreaterEqual(self.page.evaluate("() => parseFloat(getComputedStyle(document.querySelector('[data-testid=hero-state]')).fontSize)"), 30)
            self.shot(f"10_buy_{w}")
        self.page.set_viewport_size({"width": 1920, "height": 1080})
        h1 = self.page.locator("[data-testid=signal-hero]").bounding_box()["height"]
        self.show("NONE")
        h2 = self.page.locator("[data-testid=signal-hero]").bounding_box()["height"]
        self.assertGreaterEqual(min(h1, h2), 300)                                   # stable minimum height - no jumping
        self.assertEqual([e for e in self.errors if "WebSocket" not in e and "favicon" not in e], [])


if __name__ == "__main__":
    unittest.main()
