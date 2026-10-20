"""PMW-UPD-14 pullback detector (T11-T20) and SMC automaton (T21-T38) - hand-built bar sequences and golden traces."""
import unittest

import _env  # noqa: F401

from _bars import bar
from masterquo.lab.context_ind import smc as SM


def run_pb(seq, mode="WICK"):
    p = SM.Pullback(mode, 0.01)
    out = []
    for i, (h, lo, c) in enumerate(seq):
        out += p.update(i, bar(i, h, lo, c), 60.0 * (i + 1))
    return p, out


class PullbackTests(unittest.TestCase):
    def test_t11_inside_bar_keeps_reference(self):
        p, out = run_pb([(10, 9, 9.5), (9.8, 9.2, 9.5)])
        self.assertEqual((p.ext, p.ref), (10, 9))
        p, out = run_pb([(10, 9, 9.5), (11, 9.5, 10.5)])
        self.assertEqual((p.ext, p.ext_bar, p.ref), (11, 1, 9.5))         # new high moves the reference to that candle's low

    def test_t12_break_confirms_old_high(self):
        p, out = run_pb([(10, 9, 9.5), (11, 9.5, 10.5), (10.5, 9.4, 9.6)])
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0]["side"], out[0]["price"], out[0]["origin_bar"], out[0]["confirming_bar"]), ("H", 11, 1, 2))
        self.assertEqual(out[0]["reason"], "NORMAL")
        self.assertEqual((p.side, p.ext, p.ref), ("LOW", 9.4, 10.5))

    def test_t13_outside_bar(self):
        p, out = run_pb([(10, 9, 9.5), (12, 8, 8.5)])
        self.assertEqual((out[0]["price"], out[0]["origin_bar"], out[0]["reason"]), (12, 1, "OUTSIDE"))
        self.assertEqual((p.side, p.ext, p.ref, p.ext_bar), ("LOW", 8, 12, 1))

    def test_t14_low_mirror(self):
        p, out = run_pb([(12, 8, 8.5), (11, 7, 7.5), (11.5, 7.2, 11)])      # bar1 lower low; bar2 breaks ref (H of bar1 = 11)
        lows = [s for s in out if s["side"] == "L"]
        self.assertEqual((lows[0]["price"], lows[0]["origin_bar"]), (7, 1))
        p2, out2 = run_pb([(10, 9, 9.5), (12, 8, 8.5), (13, 6, 7)])         # LOW outside: confirm L of the current bar
        self.assertEqual(out2[-1]["side"], "L")
        self.assertEqual((out2[-1]["price"], out2[-1]["reason"]), (6, "OUTSIDE"))

    def test_t15_wick_vs_close_and_equality(self):
        seq = [(10, 9, 9.5), (11, 9.5, 10.5), (10.6, 9.4, 9.6)]
        _, w = run_pb(seq, "WICK")
        _, c = run_pb(seq, "CLOSE")
        self.assertEqual(len(w), 1)
        self.assertEqual(len(c), 0)                                         # close 9.6 >= ref 9.5
        _, eq = run_pb([(10, 9, 9.5), (11, 9.5, 10.5), (10.5, 9.5, 9.6)])    # touch == ref is not a break
        self.assertEqual(eq, [])
        p, _ = run_pb([(10, 9, 9.5), (10, 9.2, 9.5)])                       # equal extreme keeps earlier origin
        self.assertEqual(p.ext_bar, 0)

    def test_t16_t17_t19_alternation_ids_immutable(self):
        seq = [(10, 9, 9.5), (12, 8, 8.5), (13, 6, 7), (14, 5, 6), (13, 7, 12)]
        p, out = run_pb(seq)
        sides = [s["side"] for s in p.ledger]
        self.assertTrue(all(a != b for a, b in zip(sides, sides[1:])))
        self.assertEqual(len({s["swing_id"] for s in p.ledger}), len(p.ledger))
        snap = [dict(s) for s in p.ledger]
        p.update(5, bar(5, 20, 1, 10), 360)
        self.assertEqual(snap, p.ledger[:len(snap)])
        self.assertEqual(p.update(3, bar(3, 1, 0, 0.5), 240), [])            # replayed bar does nothing


def S(seq, **kw):
    s = SM.SMC(**kw)
    res = []
    for i, (h, lo, c) in enumerate(seq):
        res.append(s.update(bar(i, h, lo, c), 60.0 * (i + 1)))
    return s, res


# hand trace: pullback H(11) confirmed on bar2, L(9.4) confirmed on bar3 -> SEED; then close above 11 -> BoS UP
SEED = [(10, 9, 9.5), (11, 9.5, 10.5), (10.5, 9.4, 9.6), (10.8, 9.7, 10.6)]


class SMCTests(unittest.TestCase):
    def test_t21_seed(self):
        s, res = S(SEED)
        self.assertEqual(s.slot["H"]["level"], 11)
        self.assertEqual(s.slot["L"]["level"], 9.4)
        self.assertEqual(s.trend, "NONE")
        self.assertIn("SEEDED", [e["kind"] for e in s.events])

    def test_t22_t23_t24_t25_break_pending(self):
        s, res = S(SEED + [(11.5, 10.6, 11.2)])
        kinds = [e["kind"] for e in res[-1]["events"]]
        self.assertIn("BOS_UP", kinds)
        self.assertEqual(s.trend, "UP")
        self.assertEqual(s.slot["H"]["status"], "PENDING")
        bos = next(e for e in s.events if e["kind"] == "BOS_UP")
        self.assertEqual((bos["level"], bos["point_version"]), (11, 1))
        self.assertEqual(s.pending["trail"], 11.5)
        s.update(bar(5, 12.0, 11.0, 11.8), 360)
        self.assertNotIn("BOS_UP", [e["kind"] for e in s.events if e["bar"] == 5])     # consumed high: no repeated BoS
        self.assertEqual(s.pending["trail"], 12.0)
        # table: UP + break DOWN = CHoCH
        s2, _ = S(SEED + [(11.5, 10.6, 11.2), (11.0, 9.0, 9.2)])
        self.assertIn("CHOCH_DOWN", [e["kind"] for e in s2.events])
        same = [e for e in s2.events if e["bar"] == 5]
        k = [e["kind"] for e in same]
        self.assertLess(k.index("IDM"), k.index("CHOCH_DOWN"))                         # fixed order: IDM/point first, then the break
        self.assertEqual([e["seq"] for e in same], sorted(e["seq"] for e in same))
        # pending without any IDM reference -> opposite break publishes the trail as FALLBACK (no fake IDM event)
        s3 = SM.SMC()
        for i, (h, lo, c) in enumerate(SEED + [(11.5, 10.6, 11.2)]):
            s3.update(bar(i, h, lo, c), 60.0 * (i + 1))
        s3.pending["idm"] = None
        s3.update(bar(5, 11.0, 9.0, 9.2), 360)
        self.assertIn("OPPOSITE_BREAK_FALLBACK", [e.get("reason") for e in s3.events])
        self.assertFalse([e for e in s3.events if e["kind"] == "IDM"])

    def test_t26_t28_t29_idm(self):
        # BoS UP at bar4, trail max 12 at bar5; IDM fallback = protective L 9.4 (no qualifying pullback L yet); wick to 9.3 takes it
        s, _ = S(SEED + [(11.5, 10.6, 11.2), (12.0, 11.0, 11.8), (11.9, 9.3, 9.8)])
        idm = [e for e in s.events if e["kind"] == "IDM"]
        self.assertTrue(idm)
        pub = [e for e in s.events if e["kind"] == "STRUCTURE_H" and e.get("reason") == "IDM_CONFIRMED"]
        self.assertEqual((pub[-1]["price"], pub[-1]["origin_bar"]), (12.0, 5))
        self.assertEqual(s.slot["H"]["status"], "ACTIVE")
        s_close, _ = S(SEED + [(11.5, 10.6, 11.2), (12.0, 11.0, 11.8), (11.9, 9.3, 9.8)], idm_mode="CLOSE")
        self.assertIn(s_close.pending is None or s_close.pending.get("side"), (True, "H", None))

    def test_t30_t25_not_on_breaking_bar(self):
        s, _ = S(SEED + [(11.5, 9.0, 11.2)])                                  # break bar itself dips below IDM ref
        self.assertFalse([e for e in s.events if e["kind"] == "IDM"])

    def test_t32_t33_t34_sweeps(self):
        base = SEED + [(11.5, 10.6, 11.2), (12.0, 11.0, 11.8), (11.9, 9.3, 9.8)]        # H 12 active again, L 9.4 active
        s, _ = S(base + [(12.4, 11.0, 11.9)])                                     # wick above 12, close back: candidate only
        self.assertIn("SWEEP_CANDIDATE_H", [e["kind"] for e in s.events])
        self.assertFalse([e for e in s.events if e["kind"] == "X_H"])
        s2, _ = S(base + [(12.4, 11.0, 11.9), (12.6, 11.5, 12.5)])               # same-side close break -> rejected, BoS
        self.assertIn("SWEEP_REJECTED", [e["kind"] for e in s2.events])
        s3, _ = S(base + [(12.4, 11.0, 11.9), (11.0, 9.0, 9.1)])                 # later opposite break -> x + relocation before CHoCH
        kinds = [e["kind"] for e in s3.events]
        self.assertIn("X_H", kinds)
        self.assertLess(kinds.index("STRUCTURE_POINT_RELOCATED"), max(i for i, k in enumerate(kinds) if k.startswith(("CHOCH", "BOS"))))
        x = next(e for e in s3.events if e["kind"] == "X_H")
        self.assertEqual(x["level"], 12.0)                                        # x keeps the old taken level price

    def test_t35_same_bar_wick_and_break_not_x(self):
        base = SEED + [(11.5, 10.6, 11.2), (12.0, 11.0, 11.8), (11.9, 9.3, 9.8)]
        s, _ = S(base + [(12.4, 9.0, 9.1)])
        self.assertFalse([e for e in s.events if e["kind"] == "X_H"])

    def test_t37_versions_and_asof(self):
        base = SEED + [(11.5, 10.6, 11.2), (12.0, 11.0, 11.8), (11.9, 9.3, 9.8), (12.4, 11.0, 11.9), (11.0, 9.0, 9.1)]
        s, _ = S(base)
        rel = next(e for e in s.events if e["kind"] == "STRUCTURE_POINT_RELOCATED")
        before = {v["point_id"]: v["price"] for v in s.points_asof(rel["available_at"] - 1)}
        after = {v["point_id"]: v["price"] for v in s.points_asof()}
        self.assertNotEqual(before[rel["point_id"]], after[rel["point_id"]])
        bos_events = [dict(e) for e in s.events if e["kind"].startswith(("BOS", "CHOCH"))]
        self.assertTrue(all("point_version" in e for e in bos_events))

    def test_t36_sweeps_off_and_t38_replay(self):
        base = SEED + [(11.5, 10.6, 11.2), (12.0, 11.0, 11.8), (11.9, 9.3, 9.8), (12.4, 11.0, 11.9), (11.0, 9.0, 9.1)]
        s, _ = S(base, detect_sweeps=False)
        self.assertFalse([e for e in s.events if e["kind"].startswith("X_")])
        a, _ = S(base)
        b, _ = S(base)
        self.assertEqual(a.state_hash(), b.state_hash())

    def test_t31_alternation_anchor(self):
        # seed (H 11, L 9.4), BoS DOWN pending L; IDM then publishes L -> chain ..., L; a new break DOWN would need an H anchor
        s, _ = S(SEED + [(10.0, 9.0, 9.2), (9.5, 8.5, 8.8), (10.3, 8.9, 10.2), (10.0, 8.0, 8.1)])
        sides = [s.points[p]["side"] for p in s.chain]
        self.assertTrue(all(a != b for a, b in zip(sides, sides[1:])), sides)


if __name__ == "__main__":
    unittest.main()
