"""1.14 panel in a real browser (Chromium + demo backend on the SYNTHETIC terminal): seven-section menu, XAUUSD/BTC switch
(every lab page answers for the active asset; a response for the other asset is never shown), scenario card + checklist,
Neural Network Activity drawn from the SAME inference_id as the backend result (and 'sieć nieaktywna' without an artefact),
execution guarded by the backend (trade pad execute needs an intent, Execution Lock withdrawn - 410, mode only via POST /mode), no symbol blocking (1.14.1),
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
        self.assertIn("Tryb", p.locator("[data-testid=chip-exec]").inner_text())                  # real mode from the backend
        for sec in SECTIONS:
            p.click(f"[data-testid=sidenav] [data-section={sec}]")
            p.wait_for_selector(f"main.page[data-page={sec}]", timeout=20000)
            p.wait_for_timeout(500)
            p.screenshot(path=str(SHOTS / f"{sec}_1366.png"))
            self.assertTrue(self.no_hscroll(), sec)
        self.assertEqual(self.errors, [])

    def test_02_backend_locks_and_allowlist(self):
        st, j = self.send("POST", "/api/v1/lab/tradepad/execute", {"side": "BUY"})
        self.assertEqual(st, 400)                                   # PMW-UPD-07: explicit routing - an intent is required (no blind order)
        st, _ = self.send("POST", "/api/v1/execution/lock", {"lock": "UNLOCKED_BY_USER", "phrase": "zle"})
        self.assertEqual(st, 410)                                   # 1.24: Execution Lock withdrawn - nothing to unlock
        st, _ = self.send("PUT", "/api/v1/config", {"execution": {"lock": "UNLOCKED_BY_USER"}})
        self.assertEqual(st, 400)                                   # unknown field
        st, j = self.send("PUT", "/api/v1/config", {"execution": {"mode": "AUTO_LIVE"}})
        self.assertEqual(st, 400)                                   # the mode changes only through POST /mode (account confirmation)
        self.assertEqual(self.page.request.get(BASE + "/api/v1/lab?asset=DOGE").status, 403)   # asset id must be XAUUSD / BTC
        self.assertEqual(self.page.request.get(BASE + "/api/v1/markets/detail?symbol=EURUSD-").status, 200)   # no symbol blocking
        self.assertTrue(wait_for(lambda: self.api("/api/v1/assets")["assets"]["BTC"]["broker_symbol"] == "BTCUSD-", 30, 0.5))  # from the account
        st, j = self.send("POST", "/api/v1/lab/tradepad", {"side": "BUY", "entry": 100, "sl": 99, "tp": 102, "lots": 0.01})
        self.assertEqual(st, 200)
        self.assertEqual(j["execution"], "VIA_MANUAL_PAD")
        self.assertEqual(self.api("/api/v1/execution/lock")["lock"], "WITHDRAWN")

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
        self.assertNotIn(self.api("/api/v1/state")["mode"]["mode"], ("AUTO_DEMO", "AUTO_LIVE"))   # no automatic orders switched on
        self.assertEqual(self.errors, [])

    def test_07_neural_system(self):
        """PMW-UPD-04: card on Pulpit + #/neural built from the server architecture (layer_id), honest no-model state, no fake activations."""
        st = self.api("/api/v1/lab/neural?asset=XAUUSD")
        self.assertEqual(self.api("/api/v1/lab/neural?asset=BTC")["status"], "ASSET_NOT_ACTIVE")
        ids = sorted(n["layer_id"] for n in st["architecture"]["nodes"])
        p = self.page
        p.goto(BASE + "/#/pulpit")
        p.wait_for_selector("[data-testid=nss-card] [data-testid=nss-graph]")
        card = p.locator("[data-testid=nss-card]").inner_text()
        self.assertIn("Neural System", card)
        if not st["trained"]:
            self.assertIn("brak wytrenowanego modelu", card)
            self.assertIsNone(st["snapshot"] and st["snapshot"].get("candidate_output"))
        p.goto(BASE + "/#/neural")
        p.wait_for_selector("[data-testid=page-neural] [data-testid=nss-graph]")
        shown = sorted(p.eval_on_selector_all("[data-testid=page-neural] [data-layer]", "els => els.map(e => e.dataset.layer)"))
        self.assertEqual(shown, ids)
        p.click("[data-testid=page-neural] [data-layer=m1_block5_d16]")
        self.assertIn("dylatacja 16", p.locator("[data-testid=nss-layer]").inner_text())
        p.set_viewport_size({"width": 390, "height": 844})
        p.wait_for_timeout(300)
        self.assertTrue(self.no_hscroll())
        p.set_viewport_size({"width": 1366, "height": 900})
        self.assertNotIn(self.api("/api/v1/state")["mode"]["mode"], ("AUTO_DEMO", "AUTO_LIVE"))   # no automatic orders switched on
        self.assertEqual(self.errors, [])

    def test_08_scalp_mtf_dashboard(self):
        """PMW-UPD-05: one snapshot drives the bar, the matrix and all five charts (same snapshot_id); expired id -> 410; mobile 390."""
        self.assertTrue(wait_for(lambda: (self.api("/api/v1/scalp/dashboard").get("snapshot") or {}).get("snapshot_id"), 60, 1.0))
        d = self.api("/api/v1/scalp/dashboard")
        self.assertEqual([r["tf"] for r in d["snapshot"]["timeframes"]], ["H1", "M30", "M15", "M5", "M1"])
        self.assertEqual(d["snapshot"]["data_mode"], "DANE SYNTETYCZNE")
        self.assertEqual(self.page.request.get(BASE + "/api/v1/scalp/dashboard/chart?tf=M1&snapshot_id=MTF-expired").status, 410)
        p = self.page
        p.goto(BASE + "/#/scalp-mtf")
        p.wait_for_selector("[data-testid=mtf-matrix] tr[data-tf=M1]")
        self.assertTrue(wait_for(lambda: len(set(p.eval_on_selector_all(".mtf-chart", "els => els.map(e => e.dataset.snapshot)")) - {""}) == 1
                                 and len(p.eval_on_selector_all(".mtf-chart", "els => els.map(e => e.dataset.snapshot).filter(Boolean)")) == 5, 20, 0.5))
        sid = p.inner_text("[data-testid=mtf-snapshot-id]")
        self.assertEqual(set(p.eval_on_selector_all(".mtf-chart", "els => els.map(e => e.dataset.snapshot)")), {sid})
        self.assertIn("DANE SYNTETYCZNE", p.inner_text("[data-testid=mtf-bar]"))
        p.click("text=Wejście")
        p.wait_for_timeout(300)
        self.assertEqual(sorted(p.eval_on_selector_all(".mtf-chart", "els => els.map(e => e.dataset.testid)")), ["mtf-chart-M1", "mtf-chart-M5"])
        p.click("text=Pełne MTF")
        p.set_viewport_size({"width": 390, "height": 844})
        p.wait_for_timeout(500)
        self.assertTrue(self.no_hscroll())
        self.assertEqual(p.eval_on_selector_all(".mtf-chart", "els => els.length"), 1)       # one chart + matrix on mobile
        p.set_viewport_size({"width": 1366, "height": 900})
        self.assertNotIn(self.api("/api/v1/state")["mode"]["mode"], ("AUTO_DEMO", "AUTO_LIVE"))   # no automatic orders switched on
        self.assertEqual(self.errors, [])

    def test_09_liquidity_layers(self):
        """PMW-UPD-06: file fixture (SYNTHETIC_TEST, XAUT source) -> validator -> archive -> API -> heatmap panel on the SOURCE axis;
        session boxes + OBSERVE context card; XAUT never presented as XAUUSD- prices; execution mode untouched."""
        st, m = self.send("PUT", "/api/v1/liquidity/source", {"asset": "XAUUSD", "source_symbol": "XAUT", "variant": "AGGREGATED", "range": "24h"})
        self.assertEqual(st, 200, m)
        st, _ = self.send("PUT", "/api/v1/liquidity/source", {"asset": "XAUUSD", "mapping": "VALIDATED_BASIS"})
        self.assertEqual(st, 400)                                                         # no mapping without a validated basis adapter
        times = [1_760_000_000 + 300 * i for i in range(6)]
        data = {"y_axis": [3990.0, 4000.0, 4010.0, 4020.0], "liquidation_leverage_data": [[i, j, float(1 + i + 7 * j)] for i in range(6) for j in range(4)],
                "price_candlesticks": [[t, 1, 1, 1, 1, 1] for t in times]}
        inbox = Path(self.td.dir) / "liquidity" / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        (inbox / "xaut_fixture.json").write_text(json.dumps({"schema": "pmw-liq-export-1", "target_asset": "XAUUSD", "variant": "AGGREGATED", "source_symbol": "XAUT",
                                                             "range": "24h", "data": data, "note": "SYNTHETIC_TEST"}))
        self.assertEqual(self.send("POST", "/api/v1/liquidity/poll", {})[0], 200)
        hm = self.api("/api/v1/liquidity/heatmap?asset=XAUUSD")
        self.assertEqual((hm["status"], hm["mapping_status"], hm["availability_trust"]), ("OK", "MAPPING_UNVALIDATED", "IMPORT_TIME_ONLY"))
        self.assertTrue(hm["axis"].startswith("SOURCE_PRICE"))
        p = self.page
        p.goto(BASE + "/#/wykresy")
        p.evaluate("""() => { const k = 'mq.chartopts.bot'; const o = JSON.parse(localStorage.getItem(k) || '{}');
                              localStorage.setItem(k, JSON.stringify({...o, tz: o.tz || 'LOCAL', showSessions: true, showHeatmap: true})); }""")
        p.reload()
        p.wait_for_selector("[data-testid=liq-heatmap][data-status=OK] canvas")
        txt = p.inner_text("[data-testid=liq-heatmap]")
        self.assertIn("SOURCE_PRICE", txt)
        self.assertIn("XAUT", txt)
        p.wait_for_selector("[data-testid=liq-context] [data-testid=liq-codes]")
        self.assertIn("OBSERVE", p.inner_text("[data-testid=liq-context]"))
        self.assertNotIn(self.api("/api/v1/state")["mode"]["mode"], ("AUTO_DEMO", "AUTO_LIVE"))   # no automatic orders switched on
        self.assertEqual(self.errors, [])

    def test_10_structure_intelligence(self):
        """PMW-UPD-07: structure cells attached to the SAME parent MTF snapshot; Structure page; Manual Pad PAPER plan->intent->execute
        (synthetic feed, no order_send), duplicate click; execution mode untouched."""
        self.assertTrue(wait_for(lambda: ((self.api("/api/v1/scalp/dashboard").get("snapshot") or {}).get("structure_intelligence") or {}).get("snapshot_id"), 90, 1.0))
        snap = self.api("/api/v1/scalp/dashboard")["snapshot"]
        si = snap["structure_intelligence"]
        self.assertEqual(si["parent_snapshot_id"], snap["snapshot_id"])
        self.assertEqual({r["structure"]["parent_snapshot_id"] for r in snap["timeframes"]}, {snap["snapshot_id"]})
        self.assertEqual(si["forecast"]["forecast_status"], "ABSTAIN")                    # no SHADOW model -> no invented numbers
        self.assertEqual(self.api("/api/v1/structure-intelligence/snapshots/" + si["snapshot_id"])["snapshot_id"], si["snapshot_id"])
        p = self.page
        p.goto(BASE + "/#/scalp-mtf")
        p.wait_for_selector("[data-testid=mtf-structure] tr[data-tf=M5]")
        self.assertIn("brak", p.inner_text("[data-testid=mtf-forecast]"))
        p.goto(BASE + "/#/struktura")
        p.wait_for_selector("[data-testid=si-models]")
        p.wait_for_selector("[data-testid=zones-manager]")
        p.screenshot(path=str(SHOTS / "struktura_1366.png"))
        q = self.api("/api/v1/scalp/dashboard")["snapshot"].get("quote") or {}
        st, plan = self.send("POST", "/api/v1/manual/plan", {"side": "BUY", "sl": (q.get("ask") or 0) - 5, "tp": (q.get("ask") or 0) + 10, "sizing_mode": "FIXED", "lots": 0.01})
        if st == 200 and plan["execution_eligible"]:
            st, it = self.send("POST", "/api/v1/manual/intents", {"plan_id": plan["plan_id"]})
            self.assertEqual(st, 200, it)
            st, r1 = self.send("POST", f"/api/v1/manual/intents/{it['intent_id']}/execute", {})
            st, r2 = self.send("POST", f"/api/v1/manual/intents/{it['intent_id']}/execute", {})
            self.assertEqual(r2["status"], "DUPLICATE")
            self.assertIn(r1["status"], ("FILLED", "BLOCKED"))
        else:
            self.assertIn(st, (200, 400))                                                   # e.g. COMMISSION_UNKNOWN / QUOTE_STALE explained
        p.goto(BASE + "/#/pozycje")
        p.click("text=Manual Trade Pad (jawne akcje użytkownika)")
        p.wait_for_selector("[data-testid=manual-pad]")
        self.assertNotIn(self.api("/api/v1/state")["mode"]["mode"], ("AUTO_DEMO", "AUTO_LIVE"))   # no automatic orders switched on
        self.assertEqual(self.errors, [])

    def test_11_neutral_sew_quotes(self):
        """PMW-UPD-08: quote kinematics from the SAME bridge (synthetic feed), neutralization section, Structure page cards; Lock untouched."""
        self.assertTrue(wait_for(lambda: self.api("/api/v1/structure-intelligence/quotes").get("phase"), 90, 1.0))
        q = self.api("/api/v1/structure-intelligence/quotes")
        self.assertIn(q["phase"], ("WARMING", "STRESSED", "RETRACEMENT", "EXPANSION", "CONSOLIDATION", "UNDETERMINED"))
        self.assertEqual(set(q["sides"]), {"BID", "ASK"})
        self.assertIn("scoreboard", self.api("/api/v1/structure-intelligence/quote-quality"))
        self.assertTrue(wait_for(lambda: self.api("/api/v1/structure-intelligence/neutralization").get("last"), 90, 1.0))
        n = self.api("/api/v1/structure-intelligence/neutralization")
        self.assertEqual(n["profile"], "SIGNAL_NEUTRALIZATION_ROLLING_V1")
        p = self.page
        p.goto(BASE + "/#/struktura")
        p.wait_for_selector("[data-testid=quotes-card] table")
        p.wait_for_selector("[data-testid=neutral-card]")
        p.screenshot(path=str(SHOTS / "struktura_quotes_1366.png"))
        self.assertNotIn(self.api("/api/v1/state")["mode"]["mode"], ("AUTO_DEMO", "AUTO_LIVE"))   # no automatic orders switched on
        self.assertEqual(self.errors, [])

    def test_12_market_story_regime_smma_z_native(self):
        """PMW-UPD-09: regime/swings/SMMA/Z sections from the SAME SI producer (snapshot cells == REST), Swing Inspector by ID,
        native MiniRocket status explicit (no terminal -> NOT_COMPILED / feed unavailable), Lock untouched."""
        self.assertTrue(wait_for(lambda: ((self.api("/api/v1/scalp/dashboard").get("snapshot") or {}).get("timeframes") or [{}])[0]
                                 .get("structure", {}).get("market", {}).get("status") == "OK", 120, 1.0))
        row = self.api("/api/v1/scalp/dashboard")["snapshot"]["timeframes"][0]
        tf = row["tf"]
        rg = self.api(f"/api/v1/structure-intelligence/regimes?tf={tf}")
        self.assertIn(rg["current"]["state"], ("TREND_UP", "TREND_DOWN", "RANGE", "TRANSITION", "WARMING_UP"))
        self.assertFalse(rg["current"]["strength_is_probability"])
        sw = self.api(f"/api/v1/structure-intelligence/swings?tf={tf}")
        self.assertIn(sw["story"]["bias"], ("UP", "DOWN", "MIXED", "UNKNOWN"))
        if sw["swings"]:
            one = self.api(f"/api/v1/structure-intelligence/swings/{sw['swings'][0]['id']}")
            self.assertEqual(one["id"], sw["swings"][0]["id"])
        st = self.page.evaluate("async (p) => (await fetch(p)).status", "/api/v1/structure-intelligence/swings/SW-doesnotexist")
        self.assertEqual(st, 404)
        z = self.api(f"/api/v1/structure-intelligence/zscore?tf={tf}&mode=PREVIOUS_N")
        self.assertEqual(z["profile"]["window_mode"], "PREVIOUS_N")
        self.assertIn("events", self.api(f"/api/v1/structure-intelligence/smma?tf={tf}"))
        nat = self.api("/api/v1/structure-intelligence/native-status")
        self.assertEqual(nat["compile"]["NATIVE_COMPILED"], "NOT_COMPILED_NO_METAEDITOR")
        self.assertEqual(nat["feed"]["status"], "NATIVE_FEED_UNAVAILABLE")
        p = self.page
        p.goto(BASE + "/#/struktura")
        p.wait_for_selector("[data-testid=regime-card] [data-testid=regime-bands]")
        p.wait_for_selector("[data-testid=smma-z-card]")
        p.wait_for_selector("[data-testid=model-lab-card] [data-testid=native-status]")
        if sw["swings"]:
            p.wait_for_selector("[data-testid=market-story] [data-swing-row]")
            sid = p.get_attribute("[data-testid=market-story] [data-swing-row]", "data-swing-row")
            p.click(f"[data-swing-row='{sid}']")
            p.wait_for_selector("[data-testid=swing-inspector]")
            # the inspector renders "…" first and fills in after its own request: wait for the content, not just the box
            p.wait_for_function("([sel, id]) => (document.querySelector(sel)?.innerText || '').includes(id)",
                                arg=["[data-testid=swing-inspector]", sid], timeout=20000)
            self.assertIn(sid, p.inner_text("[data-testid=swing-inspector]"))
            p.uncheck("[data-testid=market-story] input[type=checkbox] >> nth=1")       # labels off: display only
            p.wait_for_selector("[data-testid=swing-inspector]")
        p.screenshot(path=str(SHOTS / "struktura_market_1366.png"), full_page=True)
        p.goto(BASE + "/#/scalp-mtf")
        p.wait_for_selector("[data-testid=mtf-structure] tr[data-tf=M5]")
        self.assertNotIn(self.api("/api/v1/state")["mode"]["mode"], ("AUTO_DEMO", "AUTO_LIVE"))   # no automatic orders switched on
        self.assertEqual(self.errors, [])

    def test_13_flow_context(self):
        """PMW-UPD-11: flow sections from the SAME SI producer; series/channels/stopdistance endpoints; Markov MODEL_MISSING without a fit;
        native explicit NOT_COMPILED; panel card; Lock untouched."""
        self.assertTrue(wait_for(lambda: ((self.api("/api/v1/scalp/dashboard").get("snapshot") or {}).get("timeframes") or [{}])[0]
                                 .get("structure", {}).get("flow", {}).get("status") == "OK", 120, 1.0))
        s = self.api("/api/v1/flow-context/series?tf=M15&limit=50")
        self.assertIn("synthetic", s["units"])
        self.assertTrue(s["heikin"])
        ch = self.api("/api/v1/flow-context/channels?tf=M15&mode=HISTORY_AS_KNOWN")
        self.assertEqual(ch["mode"], "HISTORY_AS_KNOWN")
        sd = self.api("/api/v1/flow-context/stopdistance?tf=M15&entry=2000&side=BUY")
        self.assertIn("row", sd)
        self.assertEqual(self.api("/api/v1/flow-context/markov")["status"], "MODEL_MISSING")
        self.assertEqual(self.api("/api/v1/flow-context/native")["compile"]["NATIVE_COMPILED"], "NOT_COMPILED_NO_METAEDITOR")
        p = self.page
        p.goto(BASE + "/#/struktura")
        p.wait_for_selector("[data-testid=flow-context-card] [data-testid=flow-candles]")
        p.wait_for_selector("[data-testid=flow-markov]")
        self.assertIn("MODEL_MISSING", p.inner_text("[data-testid=flow-markov]"))
        p.locator("[data-testid=flow-context-card]").screenshot(path=str(SHOTS / "flow_context_1366.png"))
        self.assertNotIn(self.api("/api/v1/state")["mode"]["mode"], ("AUTO_DEMO", "AUTO_LIVE"))   # no automatic orders switched on
        self.assertEqual(self.errors, [])

    def test_14_context_indicators(self):
        """PMW-UPD-14: context sections from the SAME SI producer; VAMD/FD/SMC endpoints; as-of view; buffer inspector without a bridge
        (UNAVAILABLE, not a fake scan); mapping validation; panel card with chart + would_block checklist; no horizontal scroll at 390px;
        Lock untouched."""
        self.assertTrue(wait_for(lambda: ((self.api("/api/v1/scalp/dashboard").get("snapshot") or {}).get("timeframes") or [{}])[0]
                                 .get("structure", {}).get("context", {}).get("status") == "OK", 120, 1.0))
        v = self.api("/api/v1/lab/vamd?tf=M5&limit=50")
        self.assertEqual(v["profile"], "PWM_VAMD_ATR_WILDER_SMA_v1")
        f = self.api("/api/v1/lab/fractal-regime?tf=M5&limit=50")
        self.assertEqual(f["profile"], "PWM_KATZ_BOUNDED_v1")
        sm = self.api("/api/v1/lab/smc?tf=M5&limit=200")
        self.assertEqual(sm["mode"], "CURRENT")
        if sm["events"]:
            cut = sm["events"][0]["available_at"]
            sa = self.api(f"/api/v1/lab/smc?tf=M5&as_of={cut}")
            self.assertTrue(all(e["available_at"] <= cut for e in sa["events"]))
        self.assertEqual(self.api("/api/v1/lab/buffers/source?tf=M5")["status"], "UNAVAILABLE")
        st, j = self.send("POST", "/api/v1/lab/buffers/mappings/validate", {"units": "PRICE"})
        self.assertEqual((st, j["status"]), (200, "MAPPING_INCOMPLETE"))
        p = self.page
        p.goto(BASE + "/#/struktura")
        p.wait_for_selector("[data-testid=ctx-ind-card] [data-testid=ctx-chart] canvas")
        p.wait_for_selector("[data-testid=ctx-wouldblock] table")
        self.assertIn("nie jest triggerem", p.inner_text("[data-testid=ctx-wouldblock]"))
        p.uncheck("[data-testid=ctx-ind-card] input[type=checkbox] >> nth=0")          # render toggle only
        p.wait_for_selector("[data-testid=ctx-chart] canvas")
        p.click("[data-testid=ctx-buffers] button:has-text('Waliduj')")
        p.wait_for_selector("[data-testid=ctx-mapping-status]")
        self.assertIn("MAPPING_INCOMPLETE", p.inner_text("[data-testid=ctx-mapping-status]"))
        self.assertIn("UNAVAILABLE", p.inner_text("[data-testid=ctx-source]"))
        p.locator("[data-testid=ctx-ind-card]").screenshot(path=str(SHOTS / "context_indicators_1366.png"))
        p.set_viewport_size({"width": 390, "height": 844})
        p.wait_for_timeout(500)
        self.assertTrue(self.no_hscroll(), "struktura 390")
        p.locator("[data-testid=ctx-ind-card]").screenshot(path=str(SHOTS / "context_indicators_390.png"))
        p.set_viewport_size({"width": 1366, "height": 900})
        self.assertNotIn(self.api("/api/v1/state")["mode"]["mode"], ("AUTO_DEMO", "AUTO_LIVE"))   # no automatic orders switched on
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
