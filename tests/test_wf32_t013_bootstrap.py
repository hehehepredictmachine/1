"""WF3.2 TASK 013 - bootstrap DAG (topological order, verify-first, heavy runtimes strictly sequential, CORE profile, disabled in demo)
and desktop display preferences (fullscreen / auto scale / auto enter ON by default, old prefs files keep working)."""
from __future__ import annotations

import json
import tempfile
import types
import unittest
from pathlib import Path

import _env  # noqa: F401


class TestBootstrap(unittest.TestCase):
    def test_topological_order_and_cycle_detection(self):
        from masterquo import bootstrap as B
        order = B.topo_order()
        for cid, _k, deps, _c, _h in B.COMPONENTS:
            for d in deps:
                self.assertLess(order.index(d), order.index(cid), (d, cid))
        with self.assertRaises(ValueError):
            B.topo_order([("a", "X", ["b"], False, False), ("b", "X", ["a"], False, False)])

    def test_verify_then_sequential_heavy_installs(self):
        from masterquo import bootstrap as B
        with tempfile.TemporaryDirectory() as d:
            heavy = [c[0] for c in B.COMPONENTS if c[4]]
            installed = set()
            running = []
            log = []

            def probe(cid):
                return lambda: (cid in installed, "fake")

            def installer(cid):
                st = {"s": None}

                def start():
                    self.assertEqual(running, [], "two heavy installs at once")
                    running.append(cid)
                    log.append(cid)
                    st["s"] = "RUNNING"
                    return {"ok": True}

                def poll():
                    installed.add(cid)
                    running.remove(cid)
                    st["s"] = "DONE"
                    return "DONE"
                return start, poll
            probes = {cid: probe(cid) for cid in heavy}
            b = B.Bootstrap(None, Path(d) / "s.json", "FULL", probes=probes, installers={cid: installer(cid) for cid in heavy}, poll_s=0)
            st = b.verify_all()
            states = {c["id"]: c["state"] for c in st["components"]}
            self.assertEqual(states["frontend_assets"], "VERIFIED")
            self.assertEqual(states["modular_indicator_engine"], "VERIFIED")
            self.assertTrue(all(states[h] == "NOT_INSTALLED" for h in heavy))
            res = b.run_heavy()
            self.assertEqual([r["id"] for r in res], heavy)
            self.assertEqual(log, heavy)
            self.assertTrue(all(r["state"] == "INSTALLED" for r in res))
            saved = json.loads((Path(d) / "s.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["components"]["kronos_model"]["state"], "INSTALLED")

    def test_core_profile_never_installs_and_demo_disabled(self):
        from masterquo import bootstrap as B
        with tempfile.TemporaryDirectory() as d:
            b = B.Bootstrap(None, Path(d) / "s.json", "CORE", probes={c[0]: (lambda: (False, "x")) for c in B.COMPONENTS if c[4]})
            b.verify_all()
            self.assertEqual(b.queue(), [])
            with self.assertRaises(ValueError):
                b.set_profile("TURBO")
            demo = B.Bootstrap(types.SimpleNamespace(demo=True), Path(d) / "t.json")
            self.assertFalse(demo.start())
            st = b.status()
            self.assertFalse(st["policy"]["heavy_parallel"])
            self.assertFalse(st["policy"]["windows_resolution_change"])

    def test_failed_dependency_blocks_dependents(self):
        from masterquo import bootstrap as B
        with tempfile.TemporaryDirectory() as d:
            b = B.Bootstrap(None, Path(d) / "s.json", probes={"backend_core": lambda: (False, "broken")})
            st = {c["id"]: c["state"] for c in b.verify_all()["components"]}
            self.assertEqual(st["backend_core"], "FAILED")
            self.assertEqual(st["trader_life_game"], "BLOCKED")


class TestDisplayPrefs(unittest.TestCase):
    def test_defaults_and_merge(self):
        import os
        from masterquo import desktop as DK
        with tempfile.TemporaryDirectory() as d:
            old = os.environ.get("MASTERQUO_DATA_DIR")
            os.environ["MASTERQUO_DATA_DIR"] = d
            try:
                p = DK.load_prefs()
                self.assertEqual((p["fullscreen"], p["auto_scale"], p["auto_enter"]), (True, True, True))
                (Path(d) / "desktop_prefs.json").write_text(json.dumps({"close_action": "exit"}), encoding="utf-8")
                self.assertTrue(DK.load_prefs()["fullscreen"])
                out = DK.save_display(False, True, False)
                self.assertEqual((out["fullscreen"], out["auto_enter"], out["close_action"]), (False, False, "exit"))
                DK.save_prefs("background", False, False, reg=None)
                self.assertFalse(DK.load_prefs()["fullscreen"])                        # display prefs survive a close-action save
            finally:
                if old is None:
                    os.environ.pop("MASTERQUO_DATA_DIR", None)
                else:
                    os.environ["MASTERQUO_DATA_DIR"] = old


if __name__ == "__main__":
    unittest.main()
