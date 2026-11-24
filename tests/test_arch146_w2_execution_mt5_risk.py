"""Arch 1.46, fala 2b, grupa execution_mt5_risk: wykonanie (menedżer pozycji, gateway, panel ręczny), most MT5, ryzyko, SH executor.

Poziom jednostkowy (stub mostu + prawdziwa Database / ConfigStore w izolowanym katalogu danych) albo syntetyczny terminal (FakeMT5).
Żadnego order_send do prawdziwego terminala, bez serwera demo.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

import _env  # noqa: F401


# ------------------------------------------------------------------------------------------------ I0807 (dzienna strata, Close By)
class TestDailyLossCloseBy(unittest.TestCase):
    def test_daily_loss_counts_close_by_losses(self):
        from masterquo.risk.engine import daily_loss_used
        d = daily_loss_used([{"type": 1, "entry": 3, "time": 100, "profit": -500.0}], 0, floating=0.0)
        self.assertEqual(d["used"], 500.0)                                     # przed: 0.0 (OUT_BY pomijany)
        self.assertEqual(d["realized_today"], -500.0)

    def test_close_by_profit_never_reduces_used(self):
        from masterquo.risk.engine import daily_loss_used
        deals = [{"type": 1, "entry": 1, "time": 100, "profit": -200.0},
                 {"type": 0, "entry": 3, "time": 110, "profit": 300.0}, {"type": 1, "entry": 3, "time": 110, "profit": -50.0}]
        d = daily_loss_used(deals, 0, floating=0.0)
        self.assertEqual(d["used"], 200.0)                                     # zysk netto z Close By nie zmniejsza zużycia
        old_day = daily_loss_used([{"type": 1, "entry": 3, "time": 10, "profit": -500.0}], 50, floating=0.0)
        self.assertEqual(old_day["used"], 0.0)                                 # deal sprzed początku dnia - bez zmian

    def test_close_by_loss_tightens_the_risk_gate(self):
        import test_risk_execution as TR
        t = TR.TestRisk("test_spread_not_double_counted_and_rr_net")
        t.setUp()
        try:
            base = t.ev(deals=[])
            hit = t.ev(deals=[{"type": 1, "entry": 3, "time": 10, "profit": -600.0}])
        finally:
            t.tearDown()
        self.assertNotIn("DAILY_STOP", base["reason_codes"])
        self.assertIn("DAILY_STOP", hit["reason_codes"])                       # przed: strata Close By niewidoczna dla DAILY_STOP


# ------------------------------------------------------------------------------------------------ I0735 (prowizja z historii)
def _deal(entry, comm, vol=1.0, fee=0.0, sym="XAUUSD-"):
    return {"symbol": sym, "type": 0, "entry": entry, "volume": vol, "commission": comm, "fee": fee}


class TestCommissionFromHistoryPartial(unittest.TestCase):
    def test_close_only_tariff_with_few_closings_is_not_zero(self):
        from masterquo.risk.costs import commission_from_history
        r = commission_from_history([_deal(0, 0.0)] * 4 + [_deal(1, -7.0)] * 2, "XAUUSD-")
        self.assertEqual(r["per_lot_per_side"], 7.0)                           # przed: 0.0 (mediana wszystkich deali)
        self.assertEqual(r["source"], "DEAL_HISTORY_PARTIAL_CONSERVATIVE")
        self.assertEqual(r["tariff"], "UNRESOLVED")

    def test_only_free_openings_is_unresolved_not_zero(self):
        from masterquo.risk.costs import commission_from_history
        r = commission_from_history([_deal(0, 0.0)] * 3, "XAUUSD-")
        self.assertIsNone(r["per_lot_per_side"])                               # przed: 0.0 jako znana prowizja
        self.assertEqual(r["source"], "DEAL_HISTORY_UNRESOLVED_ZERO")

    def test_fee_is_part_of_the_cost(self):
        from masterquo.risk.costs import commission_from_history
        r = commission_from_history([_deal(0, -3.0, fee=-1.0)] * 3 + [_deal(1, -3.0, fee=-1.0)] * 3, "XAUUSD-")
        self.assertEqual(r["per_lot_per_side"], 4.0)                           # przed: 3.0 (fee pominięte)
        r = commission_from_history([_deal(0, -3.0, fee=-1.0)] * 3, "XAUUSD-")
        self.assertEqual(r["per_lot_per_side"], 4.0)

    def test_never_below_the_former_median_and_resolved_branch_unchanged(self):
        from masterquo.risk.costs import commission_from_history
        r = commission_from_history([_deal(0, -3.5)] * 3 + [_deal(1, -3.5)] * 3, "XAUUSD-")
        self.assertEqual((r["per_lot_per_side"], r["source"], r["tariff"]), (3.5, "DEAL_HISTORY_IN_OUT_MEDIAN", "PER_SIDE"))
        r = commission_from_history([_deal(0, -2.0)] * 2 + [_deal(1, -5.0)] * 3, "XAUUSD-")
        self.assertGreaterEqual(r["per_lot_per_side"], 5.0)                    # mediana wszystkich = 5.0
        self.assertIsNone(commission_from_history([_deal(0, -3.0)] * 2, "XAUUSD-")["per_lot_per_side"])   # < min_samples - bez zmian

    def test_unresolved_zero_falls_back_without_loosening_the_manual_pad(self):
        from masterquo.execution.manual import COMMISSION_SOURCE
        from masterquo.risk.costs import resolve_commission
        cfg = SimpleNamespace(commission_mode="FROM_DEAL_HISTORY", commission_per_lot_per_side=3.0)
        r = resolve_commission(cfg, [_deal(0, 0.0)] * 3, "XAUUSD-")
        self.assertEqual(r["per_lot_per_side"], 3.0)                           # przed: 0.0 (DEAL_HISTORY_MEDIAN)
        self.assertNotIn(r["source"], COMMISSION_SOURCE)                       # panel ręczny: UNKNOWN jak przy DEAL_HISTORY_MEDIAN
        self.assertNotIn("DEAL_HISTORY_MEDIAN", COMMISSION_SOURCE)
        cfg0 = SimpleNamespace(commission_mode="FROM_DEAL_HISTORY", commission_per_lot_per_side=None)
        self.assertIsNone(resolve_commission(cfg0, [_deal(0, 0.0)] * 3, "XAUUSD-")["per_lot_per_side"])   # blokada w silniku
        r = resolve_commission(cfg, [_deal(0, -3.0)] * 2, "XAUUSD-")
        self.assertEqual(r["source"], "CONFIGURED_FALLBACK")                   # zwykła za krótka historia - bez zmian


if __name__ == "__main__":
    unittest.main()
