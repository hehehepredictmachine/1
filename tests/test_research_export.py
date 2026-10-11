"""History export (UTC) -> unchanged M06R loader accepts it with the exact broker symbol."""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import _env
from _env import TempData


class TestExport(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        sys.modules.pop("MetaTrader5", None)
        self.td.close()

    def test_export_loads_in_m06r(self):
        from masterquo.mt5.fake import FakeMT5
        fake = FakeMT5()
        sys.modules["MetaTrader5"] = fake  # the export uses the module API only
        from masterquo import diagnostics
        out = tempfile.mkdtemp(prefix="mq_export_")
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        rc = diagnostics.export_history((now - timedelta(days=60)).isoformat().replace("+00:00", "Z"),
                                        (now - timedelta(hours=2)).isoformat().replace("+00:00", "Z"), out)
        self.assertEqual(rc, 0)
        rp = str(_env.ROOT / "research" / "03_ANALIZA_HISTORYCZNA" / "M06R_REPLAY")
        sys.path.insert(0, rp)
        try:
            import M06R_HISTORICAL_REPLAY as m06r
            bank = m06r.load_bundle(out, "XAUUSD-")
        finally:
            sys.path.remove(rp)
        self.assertEqual(set(bank), {"D1", "H4", "H1", "M15", "M5", "M1"})
        last = bank["M1"][-1]["bar_open_utc"]
        self.assertLessEqual(datetime.fromisoformat(last.replace("Z", "+00:00")), now)  # UTC, not +3h server time
        with self.assertRaises(Exception):
            m06r.load_bundle(out, "XAUUSD")  # symbol mismatch is refused, never substituted
        import csv
        import json as _json
        man = _json.loads(open(os.path.join(out, "MT5_EXPORT_MANIFEST.json"), encoding="utf-8").read())
        self.assertEqual(man["timeframes"], ["D1", "H8", "H4", "H1", "M30", "M15", "M5", "M1"])
        self.assertEqual(man["dst_model"], "UNIFORM")
        self.assertGreater(man["context_files"]["M30"]["bars"], 0)
        self.assertGreater(man["context_files"]["H8"]["bars"], 0)
        with open(os.path.join(out, "H8.csv"), encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertTrue(all(int(r["time_server_raw"]) % 28800 == 0 for r in rows))          # 00/08/16 server time
        self.assertTrue(all(int(r["time_server_raw"]) - int(r["offset_seconds"]) ==
                            int(datetime.fromisoformat(r["time_utc"].replace("Z", "+00:00")).timestamp()) for r in rows))

    def test_dst_model_ny_close_per_bar_offset(self):
        from masterquo.diagnostics import ny_close_offset, server_to_utc
        winter = datetime(2026, 1, 15, 12, tzinfo=timezone.utc).timestamp()
        summer = datetime(2026, 7, 15, 12, tzinfo=timezone.utc).timestamp()
        self.assertEqual((ny_close_offset(winter), ny_close_offset(summer)), (7200, 10800))
        for u in (winter, summer):
            raw = int(u) + ny_close_offset(u)
            self.assertEqual(server_to_utc(raw, "NY_CLOSE", 0)[:2], (int(u), ny_close_offset(u)))
        # UNIFORM applies one offset everywhere (documented limitation)
        self.assertEqual(server_to_utc(int(summer) + 7200, "UNIFORM", 7200)[0], int(summer))
        # 2026-03-08: US switch to DST -> broker offset changes 2 h -> 3 h; bars on both sides convert correctly
        before = datetime(2026, 3, 6, 20, tzinfo=timezone.utc).timestamp()
        after = datetime(2026, 3, 9, 20, tzinfo=timezone.utc).timestamp()
        self.assertEqual(server_to_utc(int(before) + 7200, "NY_CLOSE", 0)[0], int(before))
        self.assertEqual(server_to_utc(int(after) + 10800, "NY_CLOSE", 0)[0], int(after))


if __name__ == "__main__":
    unittest.main()
