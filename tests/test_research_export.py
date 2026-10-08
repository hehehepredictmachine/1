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


if __name__ == "__main__":
    unittest.main()
