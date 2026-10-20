"""PMW-UPD-09 R23 Market Behavior (T129-T135)."""
import unittest

import _env  # noqa: F401

from _bars import T0, bar, from_closes, zigzag
from masterquo.lab import market_v2 as V


class MarketBehaviorTests(unittest.TestCase):
    def test_t129_labels_golden(self):
        bars = zigzag([100, 110, 104, 116, 108, 122, 115, 121, 112], per_leg=6)
        mb = V.market_behavior(bars, "M1", 0.01)
        labs = [s["label"] for s in sorted(mb.swings.values(), key=lambda s: s["origin_index"]) if s["status"] != "REPLACED"]
        self.assertEqual(labs[:7], ["H0", "L0", "HH", "HL", "HH", "HL", "LH"])
        eq = V.market_behavior(zigzag([100, 110, 104, 110.001, 103], 6), "M1", 0.01)
        self.assertIn("EQH", [s["label"] for s in eq.swings.values()])
        self.assertTrue(all(s["tolerance"] >= 0.01 for s in eq.swings.values()))

    def test_t130_tail_and_sealing(self):
        # two highs in a row (second higher) -> TAIL_REPLACED, then a low seals the tail
        cs = [100, 98, 101, 106, 99, 102, 103, 104, 108, 104, 103, 102, 98, 99, 100, 101, 102, 103, 104, 105, 106, 103, 100, 99, 98, 97]
        mb = V.MarketBehavior("M1", 60, tick=0.01)
        known_before = None
        for i, b in enumerate(from_closes(cs, 0.1)):
            ev = mb.update(b)
            kinds = [e["kind"] for e in ev]
            if "TAIL_REPLACED" in kinds:
                known_before = i
        self.assertIsNotNone(known_before)
        self.assertTrue(any(e["kind"] == "ANCHOR_SEALED" for e in mb.events))
        for lg in mb.legs.values():
            a = mb.swings[lg["to_id"]]
            self.assertGreaterEqual(lg["available_at"], a["known_at"])          # finalisation never moved back to the pivot
            self.assertGreater(lg["available_at"], V._ts(a["origin_time"]))
        sid = next(iter(mb.swings))
        s = mb.swings[sid]
        self.assertIsNone(mb.swing_asof(sid, s["known_at"] - 1))               # not known before known_at

    def test_t131_outside_bar_and_filters(self):
        bars = [bar(i, 10 + (i % 2) * 0.1, 9 - (i % 2) * 0.1) for i in range(4)] + [bar(4, 20, 1)] + [bar(5 + i, 10, 9) for i in range(4)]
        mb = V.market_behavior(bars, "M1", 0.01)
        self.assertTrue(any(e["kind"] == "AMBIGUOUS_ORDER" for e in mb.events))
        self.assertFalse(mb.swings)                                             # not projected
        zz = zigzag([100, 110, 109.5, 120, 100], 6)
        a = V.market_behavior(zz, "M1", 0.01, min_leg_ticks=100)                # 1.0 price unit min leg
        self.assertTrue(any(e.get("reason") == "MIN_LEG_TICKS" for e in a.events))
        b = V.market_behavior(zigzag([100, 110, 104, 110.5, 103], 6), "M1", 0.01, min_dist_points=100)
        self.assertTrue(any(e.get("reason") == "MIN_DIST_POINTS" for e in b.events))
        plateau = [bar(0, 9, 8), bar(1, 9, 8), bar(2, 9, 8), bar(3, 12, 8), bar(4, 12, 8), bar(5, 10, 8), bar(6, 10, 8), bar(7, 10, 8), bar(8, 10, 8)]
        p = V.market_behavior(plateau, "M1", 0.01)
        hs = [e for e in p.events if e["kind"] == "PIVOT_CONFIRMED" and e["swing_kind"] == "H"]
        self.assertEqual([e["origin_index"] for e in hs], [3])                 # first bar of the plateau wins

    def test_t132_units(self):
        bars = zigzag([100, 110, 104, 116, 108], 6)
        mb = V.market_behavior(bars, "M1", 0.01, point=0.01)
        lg = next(iter(mb.legs.values()))
        self.assertAlmostEqual(lg["points"], lg["move"] / 0.01)
        self.assertIsNone(lg["pips"])
        self.assertEqual(lg["pip_status"], "NO_PIP_DEFINITION")
        mb2 = V.market_behavior(bars, "M1", 0.01, pip_size=0.1)
        self.assertAlmostEqual(next(iter(mb2.legs.values()))["pips"], lg["move"] / 0.1)
        more = zigzag([100, 110, 104, 116, 108, 120, 110, 118], 6)
        gap = [dict(b, open_utc=b["open_utc"] + (172800 if i >= 15 else 0)) for i, b in enumerate(more)]
        g = V.market_behavior(gap, "M1", 0.01)
        lgg = [x for x in g.legs.values() if x["wall_duration_seconds"] > x["market_bar_duration"]]
        self.assertTrue(lgg)

    def test_t133_roles_and_retracement(self):
        mb = V.market_behavior(zigzag([100, 110, 104, 116, 108, 122, 98, 105, 90], 6), "M1", 0.01)
        legs = list(mb.legs.values())
        self.assertEqual(legs[0]["role"], "UNCLASSIFIED")
        self.assertTrue(any(lg["flags"] == ["OVER_RETRACE"] and lg["retracement_pct"] > 100 for lg in legs))
        self.assertTrue(any(lg["role"] == "STRUCTURE_CHANGE" for lg in legs))
        self.assertTrue(all(lg["retracement_of"] for lg in legs if lg["retracement_pct"] is not None))

    def test_t134_stable_ids_and_asof(self):
        bars = zigzag([100, 110, 104, 116, 108, 122, 115], 6)
        a = V.market_behavior(bars, "M1", 0.01)
        b = V.market_behavior(bars[:-3], "M1", 0.01)
        common = set(a.swings) & set(b.swings)
        self.assertTrue(common)
        s0 = sorted(b.swings.values(), key=lambda s: s["origin_index"])[0]
        early = a.swing_asof(s0["id"], s0["known_at"])
        self.assertIsNone(early["next_id"])                                      # future swing unknown at that as-of
        self.assertIsNotNone(a.swing_asof(s0["id"])["next_id"])
        raw = [e for e in a.events if e["kind"] == "PIVOT_CONFIRMED"]
        self.assertTrue(all(e["available_at"] == T0 + 60 * (e["bar_index"] + 1) for e in raw))


if __name__ == "__main__":
    unittest.main()
