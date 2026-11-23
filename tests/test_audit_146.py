"""1.46 audit fixes - regression tests. Each test fails on 1.45.0 (evidence in docs/AUDYT_1_45.md) and passes after the fix."""
from __future__ import annotations

import os
import unittest

import _env  # noqa: F401


class TestBodyNum(unittest.TestCase):
    def test_wrong_types_are_400_not_500(self):
        from fastapi import HTTPException

        from masterquo.api.app import body_num
        self.assertEqual(body_num({"n": "7"}, "n", 1, int), 7)
        self.assertEqual(body_num({}, "n", 1, int), 1)
        self.assertIsNone(body_num({"v": None}, "v", None, float))
        for bad in ("abc", [1], {"a": 1}, True, "nan", "inf"):
            with self.assertRaises(HTTPException) as cm:
                body_num({"n": bad}, "n", 1, float if bad in ("nan", "inf") else int, 0, 10)
            self.assertEqual(cm.exception.status_code, 400, bad)
        with self.assertRaises(HTTPException):
            body_num({"n": 11}, "n", 1, int, 0, 10)


class TestMarketZonesEmptySeries(unittest.TestCase):
    def test_as_of_before_data_is_no_data_not_index_error(self):
        from masterquo.zones import market as MZ
        from masterquo.zones.series import Series
        s = Series.from_bars([], "M5", 1_700_000_000.0)
        r = MZ.compute_tf(s, "XAUUSD", 0.01, None)                     # 1.45: IndexError in strategies.indicators.true_range
        self.assertEqual((r["state"], r["bars"], r["atr"]), ("NO_DATA", 0, None))
        out = MZ.compute({"M5": s}, instrument="XAUUSD", symbol="XAUUSD-", tick=0.01, as_of=1_700_000_000.0)
        self.assertIn("M5", str(out))


class TestApiInputValidation(unittest.TestCase):
    """Smoke test 1.45.0: these requests answered 500 (Internal Server Error) - now 400 with a reason."""

    @classmethod
    def setUpClass(cls):
        os.environ["PMW_BOOTSTRAP"] = "0"
        from _demo_server import Server
        cls.S = Server
        Server.start_server()

    @classmethod
    def tearDownClass(cls):
        cls.S.stop_server()

    def test_bad_values_answer_400(self):
        c = self.S.call
        self.assertEqual(c("/api/v1/lab/memory?tf=M5&t=garbage")[0], 400)
        code, _ = c("/api/v1/tlg/profile", {"username": "Walidacja", "class_id": "THE_ROOKIE", "difficulty": "EASY"})
        self.assertIn(code, (200, 409))
        self.assertEqual(c("/api/v1/tlg/sim", {"symbol": "XAUUSD", "count": "abc"})[0], 400)
        self.assertEqual(c("/api/v1/tlg/sim/1/step", {"n": "x"})[0], 400)
        self.assertEqual(c("/api/v1/asge/run", {"timeframe": "H1", "children": "x"})[0], 400)
        self.assertEqual(c("/api/v1/asge/run", {"timeframe": "H1", "children": 10_000})[0], 400)
        self.assertEqual(c("/api/v1/indicators/calculate", {"method": "SMA", "period": 5, "count": "x"})[0], 400)
        self.assertEqual(c("/api/v1/indicators/calculate", {"method": "SMA", "period": 5, "bars": [1, 2]})[0], 400)
        self.assertEqual(c("/api/v1/kronos/validate", {"max_origins": "x"})[0], 400)
        self.assertEqual(c("/api/v1/models/foundation/validate", {"max_origins": "x"})[0], 400)
        self.assertEqual(c("/api/v1/quant/tabicl/reconstruct", {"days": "x"})[0], 400)
        code, body = c("/api/v1/market-zones/as-of?as_of=2020-01-01T00:00:00Z")
        self.assertEqual(code, 200, body)                              # was 503 "IndexError: list index out of range"


if __name__ == "__main__":
    unittest.main()
