"""1.38 UI + API of the 20-variant pack on a real server process (SYNTHETIC terminal, --demo) + Chromium: the strategy page shows the
catalog panel with all 20 variants from the backend (no frontend list), selecting a variant x TF opens its detail (plan / reason, chart,
history) without page errors; the chart layer "Pakiet 20" shows its filters; API guards (unknown strategy_id / TF -> 400, M3 accepted, a
GET never creates a plan). No order is sent: the demo runs in SIGNALS."""
from __future__ import annotations

import os
import sys
import unittest

import _env  # noqa: F401

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_ui_kronos import CHROMIUM, HAVE_PW, SHOTS, Server  # noqa: E402


@unittest.skipUnless(HAVE_PW, "playwright not installed")
class TestPackUI(unittest.TestCase):
    def test_catalog_panel_layer_and_api_guards(self):
        srv = Server(8819, extra_env={"MQ_KRONOS_PYTHON": "", "MQ_CHRONOS2_PYTHON": "", "MQ_FINCAST_PYTHON": ""})
        try:
            c, cat = srv.call("/api/v1/sh/strategies")
            self.assertEqual((c, cat["count"], cat["families"]), (200, 20, {"SCALPING": 10, "HEDGING": 10}))
            self.assertTrue(all(x["validation"]["status"] == "NOT_VALIDATED" for x in cat["items"]))
            self.assertEqual(srv.call("/api/v1/sh/signals?strategy_id=PMW_XX99")[0], 400)
            self.assertEqual(srv.call("/api/v1/sh/signals?strategy_id=PMW_SC01&tf=W1")[0], 400)
            self.assertEqual(srv.call("/api/v1/sh/signals?strategy_id=LEGACY_SCALPING")[0], 200)
            self.assertEqual(srv.call("/api/v1/sh/chart?tf=M3&limit=50")[0], 200)
            c, pl = srv.call("/api/v1/plans/chart?layer=PACK&strategy_id=PMW_HG01")
            self.assertEqual((c, pl["contract"]), (200, "PMW-PLAN-2"))
            self.assertEqual(srv.call("/api/v1/plans/chart?layer=PACK&plan_id=../x")[0], 400)
            c, pl = srv.call("/api/v1/plans/chart?layer=PACK&symbol=BTCUSD-")
            self.assertEqual(pl["plans"], [])                                     # never another symbol's levels
            self.assertEqual(srv.call("/api/v1/sh/strategies/config", {"variants": {"PMW_HG01": {"hedge": {"ratio": 0.9}}}})[0], 400)
            c, stt = srv.call("/api/v1/sh/pack/stats")
            self.assertEqual((c, stt["items"]), (200, []))
            self.assertEqual(srv.call("/api/v1/sh/pack/stats?strategy_id=XX")[0], 400)
            n0 = srv.call("/api/v1/sh/plans")[1]["items"]
            ui = self._browse(srv)
            self.assertEqual(ui["errors"], [])
            self.assertEqual(ui["rows"], 20)
            self.assertTrue(ui["detail"])
            self.assertEqual(ui["pack_controls"], 1)
            self.assertEqual(srv.call("/api/v1/sh/plans")[1]["items"], n0)       # rendering / GET never opens a plan
        finally:
            srv.stop()

    def _browse(self, srv):
        from playwright.sync_api import sync_playwright
        SHOTS.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as pw:
            br = pw.chromium.launch(**({"executable_path": CHROMIUM} if os.path.exists(CHROMIUM) else {}))
            p = br.new_page(viewport={"width": 1600, "height": 1200})
            errors = []
            p.on("pageerror", lambda e: errors.append(str(e)))
            p.goto(srv.base + "/#/strategie")
            p.wait_for_selector("[data-testid=pack-table]", timeout=60000)
            rows = p.locator("[data-testid^=pack-row-]").count()
            p.click("[data-testid=pack-sel-PMW_SC01-M1]")
            p.wait_for_selector("[data-testid=pack-detail]", timeout=20000)
            p.wait_for_timeout(2500)
            detail = p.locator("[data-testid=pack-detail]").inner_text()
            p.locator("[data-testid=sh-pack]").screenshot(path=str(SHOTS / "sh_pack_panel.png"))
            p.click("[data-testid=pack-fam-HEDGING]")
            p.wait_for_timeout(500)
            hg_rows = p.locator("[data-testid^=pack-row-PMW_HG]").count()
            p.goto(srv.base + "/#/wykresy")
            p.wait_for_selector("[data-act=pmw-pack]", timeout=60000)
            p.locator("[data-act=pmw-pack]").first.click()
            p.wait_for_timeout(2500)
            ctrl = min(1, p.locator("[data-testid=pack-controls]").count())
            br.close()
        self.assertEqual(hg_rows, 10)
        return {"errors": errors, "rows": rows, "detail": "PMW_SC01" in detail, "pack_controls": ctrl}


if __name__ == "__main__":
    unittest.main()
