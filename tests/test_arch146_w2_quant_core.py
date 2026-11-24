"""1.46 arch fix wave 2b, group "quant_core": quant/checks (data_time basis), features (FEAT-4 regime vocabulary), metamodel (missing
features never missing in training), TabICL (strategy encoding, persisted confidences, weights folder), Event GRU READY path, NO_SPEC rows,
quant/units production API, shared calibration metrics.

Isolated MASTERQUO_DATA_DIR, stub runtimes, SYNTHETIC data - no terminal, no orders, no HTTP server."""
from __future__ import annotations

import unittest

import _env  # noqa: F401
from test_quant_core import NOW, pred


# ================================================================================================ I0797 checks: data_time basis
class TestChecksDataTimeBasis(unittest.TestCase):
    """trainhub / Kronos / TSFM records report the bar CLOSE as data_time, checks.py measured TTL and LATE_GENERATION as if it were the
    bar OPEN - such a record lived one bar longer and a record two bars older than the newest closed bar was not LATE_GENERATION.
    Ported from the withdrawn patch 9f1958f (chunk_26#5); only tightens: a record is never eligible where it was excluded before."""

    def test_close_basis_record_two_bars_old_is_late(self):
        from masterquo.quant import checks as CK
        floor = {"M5": NOW - 300}                               # newest closed M5 bar opened 300 s ago
        p1 = pred(age=300)                                     # trainhub: data_time = CLOSE of the bar one before the newest
        self.assertTrue(CK.check(p1, now=NOW, generation_floor=floor)["eligible"])
        p2 = pred(age=600)                                     # close of the bar two before the newest -> late worker answer
        self.assertEqual(CK.check(p2, now=NOW, generation_floor=floor)["reason"], "LATE_GENERATION:M5")
        # the same time on a bar-OPEN record is one bar newer -> not late (unchanged rule for open-basis producers)
        p3 = dict(pred(age=600), data_time_basis="BAR_OPEN")
        self.assertTrue(CK.check(p3, now=NOW, generation_floor=floor)["eligible"])

    def test_close_basis_ttl_is_two_bars_after_close(self):
        from masterquo.quant import checks as CK
        self.assertTrue(CK.check(pred(age=590), now=NOW)["eligible"])                       # close + < 2 bars
        self.assertEqual(CK.check(pred(age=700), now=NOW)["reason"].split(":")[0], "STALE")  # close + 2 bars + 100 s
        p = dict(pred(age=700), data_time_basis="BAR_OPEN")                                  # open + 700 s < open + 3 bars
        self.assertTrue(CK.check(p, now=NOW)["eligible"])
        kr = pred(name="Kronos-small", task="KRONOS_CLOSE_PATH_H6_M5", age=850)
        self.assertEqual(CK.data_time_basis(kr), "BAR_CLOSE")
        self.assertEqual(CK.check(kr, now=NOW)["reason"].split(":")[0], "STALE")

    def test_explicit_ttl_and_open_basis_producers_unchanged(self):
        from masterquo.quant import checks as CK
        p = dict(pred(name="mm:gpr_logret", age=850))           # not a close-basis producer: TTL = 3 bars from data_time as before
        p["canonical_id"] = "mm:gpr_logret"
        self.assertEqual(CK.data_time_basis(p), "BAR_OPEN")
        self.assertTrue(CK.check(p, now=NOW)["eligible"])
        q = dict(pred(age=850), ttl_s=900.0)                    # an explicit ttl_s is measured from data_time (unchanged)
        self.assertTrue(CK.check(q, now=NOW)["eligible"])

    def test_tightening_only_on_a_grid(self):
        """Every record eligible after the change was eligible before (old rule re-implemented here): no new eligible record."""
        from masterquo.quant import checks as CK
        from masterquo.timeutil import TF_SECONDS

        def old_check(p, now, floor):
            dt = CK.ts(p.get("data_time"))
            age = now - dt
            if age > CK.ttl_for(p):
                return False
            tf = p.get("timeframe")
            return not (floor and tf in floor and dt < floor[tf] - TF_SECONDS.get(tf, 60))
        for name in ("TH_LOGREG_M5_H6", "Kronos-small", "mm:gpr_logret"):
            for age in range(0, 1300, 25):
                for floor in (None, {"M5": NOW - 300}, {"M5": NOW - 900}):
                    p = pred(name=name, age=float(age))
                    new = CK.check(p, now=NOW, generation_floor=floor)["eligible"]
                    if new:
                        self.assertTrue(old_check(p, NOW, floor), (name, age, floor))


if __name__ == "__main__":
    unittest.main()
