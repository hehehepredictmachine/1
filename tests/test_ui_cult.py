"""1.32 CULT tower panels in a real browser (Chromium + demo backend on the SYNTHETIC terminal - clearly marked data). 1.34: the launcher,
the intro and the main menu (Neural City V7.0) are tested in test_ui_neural_city.py; here:
- left navigation of the tower panels, DEMO strip, data-kind tags (never REAL on the simulator);
- Lightning / Wind / Control / Strategy Lab render on the bot's endpoints without page errors;
- Control Tower writes the real bot config (thresholds, filters, risk limits, Telegram template and flags, presets) and the screen
  shows the backend state after a reload; invalid values are refused by the backend and said on screen;
- STOP (new entries) needs a confirmation; Strategy Lab TEST/DEPLOY need a confirmation and change only the strategy toggles;
- navigation never sends an order and never changes the execution mode; ONE WebSocket after many switches;
- no horizontal scroll at 1920x1080 / 1366x768 / 390 px.
Screenshots: data/logs/ui_cult/. Skipped (never "passed") without Playwright/Chromium."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import unittest
import urllib.request

import _env
from _env import TempData, wait_for

PORT = 8806
BASE = f"http://127.0.0.1:{PORT}"
CHROMIUM = os.environ.get("MQ_CHROMIUM", "/opt/pw-browsers/chromium")
SHOTS = _env.ROOT / "data" / "logs" / "ui_cult"
# tower key -> (route, selector of the opened screen)
TOWERS = {"lightning": ("lightning", "[data-testid=page-lightning]"), "ice": ("precision", "[data-testid=page-precision]"),
          "wind": ("wind", "[data-testid=page-wind]"), "control": ("control", "[data-testid=page-control]"),
          "strategy": ("strategy-lab", "[data-testid=page-strategy-lab]"), "fire": ("trading-intelligence", "[data-testid=terminal-shell]")}
PANELS = {"lightning": ("lt-ai-status", "lt-chart", "lt-consensus", "lt-signals", "lt-lifecycle", "lt-alerts", "lt-plan", "lt-bar"),
          "wind": ("wp-card-xgb", "wp-card-rf", "wp-card-nn", "wp-card-mc", "wp-core", "wp-flow", "wp-matrix", "wp-trace", "wp-mc", "wp-anomaly",
                   "wp-mtf", "wp-cognition", "wp-bar"),
          "control": ("ct-performance", "ct-strategy", "ct-risk", "ct-telegram", "ct-data", "ct-autopilot", "ct-infra", "ct-audit", "ct-bar"),
          "strategy-lab": ("sl-engine", "sl-performance", "sl-settings", "sl-builder", "sl-library", "sl-entry", "sl-compare", "sl-evolution", "sl-bar")}
ORDER_URL = re.compile(r"/api/v1/(order|orders|trade|execution|close|positions?|plan/.*/(execute|confirm))", re.I)
MODE_URL = re.compile(r"/api/v1/mode\b", re.I)
SYSTEM_PANELS = ("lt-ai-status", "ct-infra")            # measurements of the bot itself (module states, CPU/RAM) may say REAL
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
class TestCultUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (_env.ROOT / "frontend" / "dist" / "index.html").exists():
            raise unittest.SkipTest("frontend not built")
        SHOTS.mkdir(parents=True, exist_ok=True)
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
        cls.pw = sync_playwright().start()
        kw = {"executable_path": CHROMIUM} if os.path.exists(CHROMIUM) else {}
        cls.browser = cls.pw.chromium.launch(**kw)
        cls.api_ctx = cls.browser.new_context()                 # the API needs the panel's session cookie: one page opens it once
        cls.api_page = cls.api_ctx.new_page()
        cls.api_page.goto(BASE + "/#/pulpit")
        cls.api_page.wait_for_selector("main.page, [data-testid=topbar]", timeout=60000)

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

    # ------------------------------------------------------------ helpers
    def ctx(self, **kw):
        """New browser context (= new session: the launcher gate starts from scratch). Records page errors, non-GET requests
        (with bodies) and the page's WebSocket connections."""
        c = self.browser.new_context(viewport=kw.pop("viewport", {"width": 1920, "height": 1080}), **kw)
        p = c.new_page()
        p.errors, p.sent, p.sockets = [], [], []
        p.on("pageerror", lambda e: p.errors.append(str(e)))
        p.on("console", lambda m: p.errors.append(m.text) if m.type == "error" else None)
        p.on("request", lambda r: p.sent.append((r.method, r.url, r.post_data)) if r.method != "GET" else None)

        def on_ws(ws):
            p.sockets.append(ws.url)
            server = ws.connect_to_server()
            server.on_message(lambda msg: ws.send(msg))
        p.route_web_socket(re.compile(r".*/api/v1/ws$"), on_ws)
        return c, p

    def api(self, path):
        r = self.api_page.request.get(BASE + path)
        self.assertEqual(r.status, 200, (path, r.text()[:200]))
        return r.json()

    def cfg(self):
        return self.api("/api/v1/config")["config"]

    def toggle(self, sid):
        """Per-strategy flags of the config; no entry = scan and trade on (as the endpoint and the panel treat it)."""
        return self.cfg()["active"]["strategies"].get(sid) or {"scan": True, "trade": True}

    def state(self):
        return self.api("/api/v1/state")

    def menu(self, p):
        """Main menu (Neural City) without the intro (a direct link skips the launcher)."""
        p.goto(BASE + "/#/menu")
        p.wait_for_selector("[data-testid=page-menu][data-phase=IDLE]", timeout=30000)

    def no_hscroll(self, p):
        return p.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")

    def real_errors(self, p):
        return [e for e in p.errors if "WebSocket" not in e and "favicon" not in e and "Failed to load resource" not in e]

    def shot(self, p, name, full=False):
        p.screenshot(path=str(SHOTS / f"{name}.png"), full_page=full)

    def msg(self, p, monitor):
        loc = p.locator(f"[data-testid={monitor}] .cu-msg")
        self.assertTrue(wait_for(lambda: loc.count() > 0, 15, 0.2), f"{monitor}: no result message")
        return loc.first.inner_text(), loc.first.get_attribute("class")

    # ------------------------------------------------------------ 4. left navigation, status, DEMO marking
    def test_04_navigation_status_and_demo_marking(self):
        c, p = self.ctx()
        try:
            p.goto(BASE + "/#/lightning")                                                       # 1.34: the left navigation lives in the tower panels
            p.wait_for_selector("[data-testid=cu-left]", timeout=30000)
            hrefs = {a.get_attribute("data-testid"): a.get_attribute("href") for a in p.locator("[data-testid=cu-left] a[data-testid^=cu-nav-]").all()}
            for page in ("menu", "lightning", "precision", "wind", "trading-intelligence", "strategy-lab", "profits", "kontekst", "ustawienia"):
                self.assertEqual(hrefs.get(f"cu-nav-{page}"), f"#/{page}", hrefs)
            self.assertTrue(p.locator("[data-testid=cu-demo]").is_visible())                    # SYNTHETIC terminal -> DEMO strip
            self.assertTrue(wait_for(lambda: "ms" in p.locator("[data-testid=cu-latency]").inner_text(), 20, 0.3))
            for page in PANELS:
                p.goto(BASE + f"/#/{page}")
                p.wait_for_selector(f"[data-testid=page-{page}]", timeout=30000)
                p.wait_for_timeout(2500)
                bad = p.evaluate("(sys) => [...document.querySelectorAll('[data-kind=REAL]')].filter(e => !sys.some(t => e.closest(`[data-testid=${t}]`)))"
                                 ".map(e => e.closest('[data-testid]')?.dataset.testid || '?')", list(SYSTEM_PANELS))
                self.assertEqual(bad, [], f"{page}: market data marked REAL on the simulator")
                self.assertTrue(p.locator("[data-testid=cu-demo]").is_visible(), page)
            p.click("[data-testid=cu-bell]")
            p.wait_for_selector("[data-testid=cu-notifications]", timeout=5000)
            p.click("[data-testid=cu-profile]")
            p.wait_for_selector("[data-testid=cu-profile-pop]", timeout=5000)
            self.assertIn("symulator", p.locator("[data-testid=cu-profile-pop]").inner_text())
            self.assertEqual(self.real_errors(p), [])
        finally:
            c.close()

    # ------------------------------------------------------------ 5. panels render on the bot's data at three widths
    def test_05_panels_render_and_layouts(self):
        for vp in ({"width": 1920, "height": 1080}, {"width": 1366, "height": 768}, {"width": 390, "height": 844}):
            c, p = self.ctx(viewport=vp)
            try:
                for page, parts in PANELS.items():
                    p.goto(BASE + f"/#/{page}")
                    p.wait_for_selector(f"[data-testid=page-{page}]", timeout=30000)
                    for part in parts:
                        self.assertTrue(wait_for(lambda: p.locator(f"[data-testid={part}]").count() == 1, 20, 0.2), (page, part, vp))
                    p.wait_for_timeout(2000)
                    self.assertTrue(self.no_hscroll(p), f"{page} {vp}")
                    self.shot(p, f"05_{page}_{vp['width']}", full=True)
                self.assertEqual(self.real_errors(p), [], vp)
            finally:
                c.close()
        c, p = self.ctx()
        try:
            p.goto(BASE + "/#/wind")
            p.wait_for_selector("[data-testid=page-wind]", timeout=30000)
            self.assertIn("BRAK W BOCIE", p.locator("[data-testid=wp-card-rf]").inner_text())    # Random Forest does not exist in the bot
            self.assertTrue(p.locator("[data-testid=wp-core-value]").is_visible())
            p.goto(BASE + "/#/strategy-lab")
            p.wait_for_selector("[data-testid=page-strategy-lab]", timeout=30000)
            self.assertTrue(p.locator("[data-testid=sl-evolution] button[disabled]").count() >= 1)  # not built -> disabled, not faked
            p.goto(BASE + "/#/lightning")
            p.wait_for_selector("[data-testid=page-lightning]", timeout=30000)
            p.click("[data-testid=lt-tf-M15]")
            self.assertEqual(p.locator("[data-testid=lt-tf-M15]").get_attribute("aria-pressed"), "true")
            self.assertTrue(wait_for(lambda: p.locator("[data-testid=lt-chart] canvas").count() > 0, 30, 0.3))
        finally:
            c.close()

    # ------------------------------------------------------------ 6. Control Tower writes the real config and shows it back
    def test_06_control_tower_settings_are_saved_to_the_bot(self):
        c, p = self.ctx()
        try:
            p.goto(BASE + "/#/control")
            p.wait_for_selector("[data-testid=ct-th-confirmed]", timeout=30000)
            cfg0 = self.cfg()
            th = cfg0["active"]["thresholds"]
            self.assertEqual(float(p.locator("[data-testid=ct-th-confirmed]").input_value()), th["confirmed"])   # screen = backend
            new_c, new_e = (th["confirmed"] - 2, th["early"] - 2)
            p.fill("[data-testid=ct-th-confirmed]", str(int(new_c)))
            p.fill("[data-testid=ct-th-early]", str(int(new_e)))
            p.fill("[data-testid=ct-f-spread]", "45")
            p.click("[data-testid=ct-strategy-save]")
            text, klass = self.msg(p, "ct-strategy")
            self.assertIn("ok", klass, text)
            cfg1 = self.cfg()
            self.assertEqual((cfg1["active"]["thresholds"]["confirmed"], cfg1["active"]["thresholds"]["early"]), (new_c, new_e))
            self.assertEqual(cfg1["risk"]["max_spread_points"], 45)
            # risk limits: valid value saved; invalid value refused by the backend and said on screen
            p.fill("[data-testid=ct-risk-max_open_positions]", "3")
            p.click("[data-testid=ct-risk-save]")
            text, klass = self.msg(p, "ct-risk")
            self.assertIn("ok", klass, text)
            self.assertEqual(self.cfg()["risk"]["max_open_positions"], 3)
            p.fill("[data-testid=ct-risk-risk_per_trade_pct]", "99")
            p.click("[data-testid=ct-risk-save]")
            self.assertTrue(wait_for(lambda: "bad" in (p.locator("[data-testid=ct-risk] .cu-msg").first.get_attribute("class") or ""), 15, 0.2))
            self.assertNotEqual(self.cfg()["risk"]["risk_per_trade_pct"], 99)
            # reload: the screen shows what the backend holds
            p.reload()
            p.wait_for_selector("[data-testid=ct-th-confirmed]", timeout=30000)
            self.assertTrue(wait_for(lambda: float(p.locator("[data-testid=ct-th-confirmed]").input_value() or 0) == new_c, 15, 0.2))
            self.assertEqual(p.locator("[data-testid=ct-risk-max_open_positions]").input_value(), "3")
            # Telegram: live preview (always marked as analysis), invalid template refused, saved template in the config
            p.click("[data-testid=ct-tg-tab-Editor]")
            p.fill("[data-testid=ct-tg-editor]", "PMW {symbol} {direction} @ {entry} SL {sl} TP {tp}")
            prev = p.locator("[data-testid=ct-tg-preview]")
            self.assertTrue(wait_for(lambda: prev.inner_text().count("PMW ") == 1 and "Analysis only" in prev.inner_text(), 15, 0.2),
                            prev.inner_text())                                                # the edited template, always "analysis only"
            # the last signal of this session (simulator -> tagged SYNTHETIC) or, before the first one, an example marked as such
            self.assertTrue("[EXAMPLE" in prev.inner_text() or "[SYNTHETIC DATA]" in prev.inner_text(), prev.inner_text())
            p.click("[data-testid=ct-tg-save]")
            text, klass = self.msg(p, "ct-telegram")
            self.assertIn("ok", klass, text)
            self.assertEqual(self.api("/api/v1/telegram/template")["template"], "PMW {symbol} {direction} @ {entry} SL {sl} TP {tp}")
            self.assertNotIn("signal_template", self.cfg()["telegram"])                          # own file, config.json unchanged
            p.reload()                                                                          # the saved template comes back
            p.wait_for_selector("[data-testid=ct-tg-editor]", timeout=30000)
            self.assertTrue(wait_for(lambda: p.locator("[data-testid=ct-tg-editor]").input_value().startswith("PMW {symbol}"), 15, 0.2))
            p.fill("[data-testid=ct-tg-editor]", "PMW {password}")
            self.assertTrue(wait_for(lambda: "bad" in (p.locator("[data-testid=ct-tg-preview]").get_attribute("class") or ""), 15, 0.2))
            p.click("[data-testid=ct-tg-test]")                                                   # not configured / invalid -> refused
            self.assertTrue(wait_for(lambda: re.search(r"Błąd|Odmowa", p.locator("[data-testid=ct-telegram] .cu-msg").first.inner_text() or "") is not None, 20, 0.3))
            p.click("[data-testid=ct-tg-save]")
            self.assertTrue(wait_for(lambda: "bad" in (p.locator("[data-testid=ct-telegram] .cu-msg").first.get_attribute("class") or ""), 15, 0.2))
            self.assertEqual(self.api("/api/v1/telegram/template")["template"], "PMW {symbol} {direction} @ {entry} SL {sl} TP {tp}")
            # presets: save, change, load back, reset (with confirmation)
            p.fill("[data-testid=ct-preset-name]", "cult-test")
            p.click("[data-testid=ct-preset-save]")
            self.assertIn("ok", self.msg(p, "ct-strategy")[1])
            self.assertIn("cult-test", [x["name"] for x in self.api("/api/v1/presets/strategy")["items"]])
            p.fill("[data-testid=ct-th-confirmed]", str(int(new_c - 5)))
            p.click("[data-testid=ct-strategy-save]")
            self.assertTrue(wait_for(lambda: self.cfg()["active"]["thresholds"]["confirmed"] == new_c - 5, 10, 0.2))
            self.assertTrue(wait_for(lambda: p.locator("[data-testid=ct-preset-pick] option[value='cult-test']").count() == 1, 10, 0.2))
            p.select_option("[data-testid=ct-preset-pick]", "cult-test")
            p.click("[data-testid=ct-preset-load]")
            self.assertTrue(wait_for(lambda: self.cfg()["active"]["thresholds"]["confirmed"] == new_c, 10, 0.2))
            self.assertTrue(wait_for(lambda: float(p.locator("[data-testid=ct-th-confirmed]").input_value() or 0) == new_c, 10, 0.2))
            p.once("dialog", lambda d: d.dismiss())                                               # Reset: cancel keeps the values
            p.click("[data-testid=ct-preset-reset]")
            p.wait_for_timeout(800)
            self.assertEqual(self.cfg()["active"]["thresholds"]["confirmed"], new_c)
            p.once("dialog", lambda d: d.accept())
            p.click("[data-testid=ct-preset-reset]")
            self.assertTrue(wait_for(lambda: self.cfg()["active"]["thresholds"]["confirmed"] == 70, 10, 0.2))
            self.assertEqual(self.cfg()["risk"]["max_open_positions"], 3)                         # presets touch strategy fields only
            self.shot(p, "06_control_saved", full=True)
            self.assertEqual([s for s in p.sent if ORDER_URL.search(s[1]) or MODE_URL.search(s[1])], [])
            self.assertEqual(self.real_errors(p), [])
        finally:
            c.close()

    # ------------------------------------------------------------ 7. STOP and Strategy Lab TEST/DEPLOY need a confirmation
    def test_07_confirmations_stop_and_strategy_toggles(self):
        c, p = self.ctx()
        try:
            p.goto(BASE + "/#/control")
            p.wait_for_selector("[data-testid=ct-kill]", timeout=30000)
            self.assertFalse(self.state()["mode"].get("kill_switch"))
            p.once("dialog", lambda d: d.dismiss())
            p.click("[data-testid=ct-kill]")
            p.wait_for_timeout(800)
            self.assertFalse(self.state()["mode"].get("kill_switch"))                               # cancelled -> nothing sent
            self.assertEqual([s for s in p.sent if "/api/v1/kill" in s[1]], [])
            p.once("dialog", lambda d: d.accept())
            p.click("[data-testid=ct-kill]")
            self.assertTrue(wait_for(lambda: self.state()["mode"].get("kill_switch") is True, 10, 0.2))
            self.assertTrue(wait_for(lambda: p.locator("[data-testid=ct-kill]").get_attribute("aria-checked") == "true", 10, 0.2))
            p.click("[data-testid=ct-kill]")                                                      # resume: no confirmation needed
            self.assertTrue(wait_for(lambda: not self.state()["mode"].get("kill_switch"), 10, 0.2))
            mode0 = self.state()["mode"]["mode"]
            p.click("[data-testid=ct-ap-FULL]")                                                   # autopilot tile opens the mode dialog
            p.wait_for_selector(".modal", timeout=5000)
            p.click(".modal .modal-head button.icon")                                             # close (✕) without choosing a mode
            p.wait_for_selector(".modal", state="detached", timeout=5000)
            self.assertEqual(self.state()["mode"]["mode"], mode0)                                  # nothing changes without confirming
            # Strategy Lab: TEST STRATEGY -> scan ON / trade OFF, DEPLOY TO BOT -> trade ON, both after a confirmation
            p.goto(BASE + "/#/strategy-lab")
            p.wait_for_selector("[data-testid=sl-test]:not([disabled])", timeout=30000)
            n0 = len([s for s in p.sent if "/strategy/toggle" in s[1]])
            p.once("dialog", lambda d: d.dismiss())
            p.click("[data-testid=sl-test]")
            p.wait_for_timeout(600)
            self.assertEqual(len([s for s in p.sent if "/strategy/toggle" in s[1]]), n0)
            p.once("dialog", lambda d: d.accept())
            p.click("[data-testid=sl-test]")
            self.assertTrue(wait_for(lambda: len([s for s in p.sent if "/strategy/toggle" in s[1]]) == n0 + 1, 10, 0.2))
            body = json.loads([s for s in p.sent if "/strategy/toggle" in s[1]][-1][2])
            sid = body["strategy_id"]
            self.assertEqual((body["scan"], body["trade"]), (True, False))
            self.assertTrue(wait_for(lambda: self.toggle(sid)["trade"] is False and self.toggle(sid)["scan"] is True, 10, 0.2))
            p.once("dialog", lambda d: d.accept())
            p.click("[data-testid=sl-deploy]")
            self.assertTrue(wait_for(lambda: self.toggle(sid)["trade"] is True, 10, 0.2))
            self.assertEqual(self.state()["mode"]["mode"], mode0)                                  # the execution mode is untouched
            self.assertEqual([s for s in p.sent if ORDER_URL.search(s[1]) or MODE_URL.search(s[1])], [])
            self.assertEqual(self.real_errors(p), [])
        finally:
            c.close()

    # ------------------------------------------------------------ 9. one WebSocket after many switches
    def test_09_single_socket_after_switches(self):
        c, p = self.ctx()
        # sockets counted in the page: opened in total, open now, most open at the same time
        p.add_init_script("""(() => { const W = window.WebSocket, s = window.__ws = { opened: 0, open: 0, maxOpen: 0 };
            window.WebSocket = class extends W { constructor(...a) { super(...a); s.opened++; s.open++; s.maxOpen = Math.max(s.maxOpen, s.open);
              this.addEventListener('close', () => { s.open--; }); } }; })();""")
        try:
            self.menu(p)
            p.wait_for_timeout(1000)
            self.assertEqual(len(p.sockets), 1)
            for _ in range(2):
                for key, (route, sel) in TOWERS.items():
                    if key == "fire":
                        continue
                    p.evaluate("(h) => { location.hash = h; }", f"#/{route}")
                    p.wait_for_selector(sel, timeout=30000)
                    p.wait_for_timeout(250)
                p.click("[data-testid=cu-logo]")
                p.wait_for_selector("[data-testid=page-menu]", timeout=20000)
            # one live socket for the whole panel: screens never open their own. A reconnect of that one socket (the client closes it
            # by itself when it sees a gap in the event sequence and asks for the missing events / a resync) is allowed - it is never
            # a second socket at the same time, and it always follows a close of the previous one.
            ws = p.evaluate("() => window.__ws")
            self.assertEqual(ws["maxOpen"], 1, ws)                                              # never two at the same time
            self.assertEqual(ws["open"], 1, ws)
            self.assertLessEqual(ws["opened"], 3, ws)                                           # not one socket per screen (10 switches)
            self.assertEqual(self.real_errors(p), [])
        finally:
            c.close()


if __name__ == "__main__":
    unittest.main()
