# 1.41 browser part of tests/test_sh_api.py (old SCALPING/HEDGING and training pages) - archived in 1.42; not runnable alone.
    def test_panels_in_browser(self):
        """Acceptance 16 (UI): the strategy panel and the training panel render REAL backend data, no page errors, no horizontal
        scroll on a phone width, the trading mode is never changed by the panel."""
        if not (_env.ROOT / "frontend" / "dist" / "index.html").exists():
            self.skipTest("frontend not built")
        SHOTS.mkdir(parents=True, exist_ok=True)
        mode0 = call("/api/v1/sh")[1]["mode"]
        self.assertTrue(wait_for(lambda: bool(call("/api/v1/sh")[1].get("last_eval")), 120, 1.0))
        with sync_playwright() as pw:
            kw = {"executable_path": CHROMIUM} if os.path.exists(CHROMIUM) else {}
            br = pw.chromium.launch(**kw)
            errors = []
            for w, h in ((1366, 900), (390, 844)):
                ctx = br.new_context(viewport={"width": w, "height": h})
                p = ctx.new_page()
                p.on("pageerror", lambda e: errors.append(str(e)))
                p.goto(BASE + "/#/strategie")
                p.wait_for_selector("[data-testid=page-strategie]", timeout=30000)
                p.wait_for_selector("[data-testid=sh-checklist] li", timeout=30000)
                self.assertIn(p.locator("[data-testid=sh-mode]").inner_text(), ("SIGNALS", "PAPER"))
                self.assertTrue(p.locator("[data-testid=sh-models] tbody tr").count() >= 20)
                self.assertIn("heurystyka", p.locator("[data-testid=sh-setup]").inner_text())
                # 1.25: SCALPING TP3 chosen from 5 / 7.5 / 10 USD; commission editable, empty = unknown (never 0)
                p.wait_for_selector("[data-testid=sh-tp3]")
                self.assertEqual([o.get_attribute("value") for o in p.locator("[data-testid=sh-tp3] option").all()], ["5", "7.5", "10"])
                self.assertEqual(p.locator("[data-testid=sh-commission]").input_value(), "")
                if w == 1366:
                    comm = lambda: call("/api/v1/sh/config")[1]["instruments"]["XAUUSD"]["commission_per_lot_side"]
                    p.fill("[data-testid=sh-commission]", "3,5")
                    p.click("[data-testid=sh-config-save]")
                    self.assertTrue(wait_for(lambda: comm() == 3.5, 10, 0.3))
                    # the panel reloads the saved config and shows the stored value - edit again only after that, like a user
                    self.assertTrue(wait_for(lambda: p.locator("[data-testid=sh-commission]").input_value() == "3.5", 10, 0.2))
                    p.fill("[data-testid=sh-commission]", "")
                    p.click("[data-testid=sh-config-save]")
                    self.assertTrue(wait_for(lambda: comm() is None, 10, 0.3))
                p.wait_for_selector("[data-testid=sh-chart] canvas", timeout=20000)
                p.click("[data-testid=sh-sel-HEDGING]")
                p.wait_for_selector("[data-testid=sh-tp3]")
                self.assertIn("Setup HEDGING", p.locator("[data-testid=sh-setup]").inner_text())
                self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"), w + 1, f"horizontal scroll at {w}px")
                p.screenshot(path=str(SHOTS / f"strategie_{w}.png"), full_page=True)
                p.goto(BASE + "/#/modele")
                p.wait_for_selector("[data-testid=training-panel] [data-testid=tp-models] tbody tr", timeout=30000)
                self.assertIn("nie wymaga treningu", p.locator("[data-testid=tp-models]").inner_text())
                self.assertEqual(p.locator("[data-model=sh_tp_model]").count(), 1)
                p.click("[data-testid=tp-tab-start]")
                p.wait_for_selector("[data-check=no_running_training]", timeout=20000)
                p.click("[data-testid=tp-tab-pakiety]")
                p.select_option("[data-testid=tp-scope]", "sh_tp_model")
                p.click("[data-testid=tp-export]")
                p.wait_for_selector("[data-testid=tp-download]", timeout=30000)
                self.assertTrue(p.locator("[data-testid=tp-download]").get_attribute("href").startswith("/api/v1/training/exports/PMW_TRENING_"))
                p.click("[data-testid=tp-tab-historia]")
                p.wait_for_selector("[data-testid=tp-history]")
                self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"), w + 1, f"horizontal scroll at {w}px (trening)")
                p.screenshot(path=str(SHOTS / f"trening_{w}.png"), full_page=True)
                ctx.close()
            br.close()
        self.assertEqual(errors, [])
        self.assertEqual(call("/api/v1/sh")[1]["mode"], mode0)                         # the panels never change the trading mode


