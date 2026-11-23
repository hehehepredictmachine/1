"""WF3.2 TASK 020 - OTC strategy retirement: 60 active strategies / 6 baskets / 2 profiles, retired OTC kept read-only for history,
retained FOREX/CRYPTO definitions identical to the v1.44.1 baseline, idempotent settings migration without data loss, server-side rejection."""
from __future__ import annotations

import json
import tempfile
import types
import unittest
from pathlib import Path

import _env  # noqa: F401  (sys.path)

FIX = Path(__file__).parent / "fixtures" / "catalog_baseline_1_44_1.json"


class TestActiveCatalog(unittest.TestCase):
    def test_exact_counts_60_6_2(self):                                              # T020-001/006/049
        from masterquo.baskets import catalog as C
        v = C.validate()
        self.assertTrue(v["ok"], v)
        self.assertEqual((v["total"], v["unique"], v["baskets"], v["profiles"]), (60, 60, 6, 2))
        self.assertEqual(set(C.PROFILES), {"FOREX_MT5", "CRYPTO_FOMO_PERPS"})
        self.assertEqual(set(C.BASKETS), {"FX_SMC", "FX_SCALP", "FX_HEDGE", "CP_SMC", "CP_SCALP", "CP_HEDGE"})

    def test_no_otc_in_active_maps(self):                                            # T020-002/003/004
        from masterquo.baskets import catalog as C
        self.assertNotIn("OTC_GOLD_POCKETOPTION", C.PROFILES)
        self.assertFalse(set(C.BASKETS) & {"OTC_SMC", "OTC_SCALP", "OTC_HEDGE"})
        self.assertFalse([s for s in C.BY_ID if s.startswith("OTC_")])
        self.assertFalse([b for b in C.baskets() if b["profile_id"].startswith("OTC")])

    def test_retained_60_match_baseline(self):                                       # T020-005/039/040
        from masterquo.baskets import catalog as C
        base = json.loads(FIX.read_text(encoding="utf-8"))
        now = [{"strategy_id": s["strategy_id"], "basket_id": s["basket_id"], "config_hash": s["config_hash"], "signal_timeframe": s["signal_timeframe"]}
               for s in C.CATALOG]
        self.assertEqual(now, base["active"])

    def test_retired_registry_keeps_original_ids(self):                              # T020-015/018 (history labels, no remap)
        from masterquo.baskets import catalog as C
        base = json.loads(FIX.read_text(encoding="utf-8"))
        self.assertEqual(sorted(C.HISTORICAL_STRATEGIES), sorted(base["retired_otc"]))
        for sid, s in C.HISTORICAL_STRATEGIES.items():
            self.assertEqual((s["runtime_status"], s["profile_id"]), ("RETIRED", "OTC_GOLD_POCKETOPTION"))
            self.assertEqual(C.retired_reason(sid), "RETIRED_STRATEGY_ID")
        self.assertEqual(C.retired_reason(profile_id="OTC_GOLD_POCKETOPTION"), "RETIRED_PROFILE")
        self.assertIsNone(C.retired_reason("FX_SMC_01"))

    def test_active_only_allowlist(self):                                            # T020-011/012/013/014
        from masterquo.baskets import catalog as C
        self.assertEqual(C.active_only(["OTC_SMC_01", "FX_SMC_01", "CP_SCALP_09", "OTC_HEDGE_10", "XYZ"]), ["FX_SMC_01", "CP_SCALP_09"])


class TestSettingsMigration(unittest.TestCase):
    def _svc(self, d):
        from masterquo.baskets import service as BS
        rt = types.SimpleNamespace(demo=True, bridge=None, db=None, bus=None, quant=None, news=None)
        return BS.BasketService(rt, data_dir=Path(d))

    def test_old_settings_with_otc_are_retired_not_deleted_and_idempotent(self):    # T020-009/031/032/037
        with tempfile.TemporaryDirectory() as d:
            old = {"active_profile": "OTC_GOLD_POCKETOPTION",
                   "profiles": {"OTC_GOLD_POCKETOPTION": {"enabled": True, "selection": "AUTO", "instruments": ["GOLD_OTC"]}},
                   "baskets": {"OTC_SMC": {"enabled": True}, "FX_SMC": {"enabled": True}},
                   "strategies": {"OTC_SCALP_03": {"enabled": True}, "FX_SCALP_01": {"enabled": False}},
                   "manual_select": {"OTC_GOLD_POCKETOPTION": ["OTC_SMC_01"], "FOREX_MT5": ["FX_SMC_01", "OTC_SMC_02"]}}
            (Path(d) / "settings.json").write_text(json.dumps(old), encoding="utf-8")
            svc = self._svc(d)
            st = svc.settings()
            self.assertEqual(set(st["profiles"]), {"FOREX_MT5", "CRYPTO_FOMO_PERPS"})
            self.assertNotIn("OTC_SMC", st["baskets"])
            self.assertNotIn("OTC_SCALP_03", st["strategies"])
            self.assertEqual(st["strategies"]["FX_SCALP_01"], {"enabled": False})
            self.assertEqual(st["manual_select"], {"FOREX_MT5": ["FX_SMC_01"]})
            self.assertEqual(st["active_profile"], "FOREX_MT5")
            r = st["retired"]
            self.assertEqual(r["profiles"]["OTC_GOLD_POCKETOPTION"]["reason"], "RETIRED_PROFILE")
            self.assertEqual(r["baskets"]["OTC_SMC"]["reason"], "RETIRED_STRATEGY_ID")
            self.assertEqual(r["strategies"]["OTC_SCALP_03"]["reason"], "RETIRED_STRATEGY_ID")
            self.assertIn("wycofany", r["notice"])
            self.assertEqual(json.loads((Path(d) / "settings.json").read_text(encoding="utf-8")), old)      # file untouched (rollback)
            self.assertEqual(svc.settings(), st)                                                            # idempotent
            svc.update_settings({"strategies": {"FX_SMC_02": {"enabled": False}}})
            self.assertEqual(json.loads((Path(d) / "settings.json").read_text(encoding="utf-8"))["strategies"]["OTC_SCALP_03"], {"enabled": True})

    def test_server_side_rejects_retired_ids(self):                                 # T020-007/008/010/030/045
        with tempfile.TemporaryDirectory() as d:
            svc = self._svc(d)
            for patch, code in (({"profiles": {"OTC_GOLD_POCKETOPTION": {"enabled": True}}}, "RETIRED_PROFILE"),
                                ({"baskets": {"OTC_HEDGE": {"enabled": True}}}, "RETIRED_STRATEGY_ID"),
                                ({"strategies": {"OTC_SMC_05": {"enabled": True}}}, "RETIRED_STRATEGY_ID"),
                                ({"manual_select": {"FOREX_MT5": ["OTC_SMC_01"]}}, "RETIRED_STRATEGY_ID"),
                                ({"active_profile": "OTC_GOLD_POCKETOPTION"}, "RETIRED_PROFILE")):
                with self.assertRaises(ValueError) as cm:
                    svc.update_settings(patch)
                self.assertTrue(str(cm.exception).startswith(code), cm.exception)

    def test_cycle_never_touches_otc_feed(self):                                     # T020-021
        with tempfile.TemporaryDirectory() as d:
            svc = self._svc(d)
            called = []
            svc.otc.import_dir = lambda *a, **k: called.append("import")
            svc.otc.state = lambda *a, **k: called.append("state") or {"state": "LIVE"}
            svc.update_settings({"profiles": {"CRYPTO_FOMO_PERPS": {"enabled": False}, "FOREX_MT5": {"enabled": False}}})
            out = svc.cycle()
            self.assertEqual(out, {})
            self.assertEqual(called, [])
            self.assertEqual(svc.status()["otc_feed"]["state"], "RETIRED")


if __name__ == "__main__":
    unittest.main()
