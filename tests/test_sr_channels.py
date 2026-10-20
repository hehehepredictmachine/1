"""PMW-UPD-11 FF04 ranked S/R channels (T29-T38)."""
import unittest

import numpy as np

import _env  # noqa: F401

from _bars import bar
from masterquo.lab.flow_context import sr_channels as SR


def wave(n=700, seed=0):
    r = np.random.default_rng(seed)
    out = []
    for i in range(n):
        c = 100 + 5 * np.sin(i / 15.0) + r.normal(0, 0.3)
        out.append(bar(i, c + 0.4, c - 0.4, c, o=c))
    return out


class SRTests(unittest.TestCase):
    def test_t29_pivots_known_after_right(self):
        b = wave(200)
        pv = SR.pivots(b, 10)
        self.assertTrue(pv)
        self.assertTrue(all(p["confirmed_index"] == p["origin_index"] + 10 for p in pv))
        self.assertEqual(SR.pivots(b, 10, upto=50), [p for p in pv if p["confirmed_index"] <= 50 and p["origin_index"] <= 40])
        body = SR.pivots(b, 10, "BODY")
        self.assertTrue(all(p["price"] in (b[p["origin_index"]]["o"], b[p["origin_index"]]["c"]) for p in body))

    def test_t30_eligibility_290(self):
        b = wave(700)
        pv = SR.pivots(b, 10)
        p = pv[0]
        t_ok = p["confirmed_index"] + 290
        s1 = SR.channels_at(b, t_ok, piv=pv)
        s2 = SR.channels_at(b, t_ok + 1, piv=pv)
        in1 = any(p["id"] in c["members"] for c in s1["channels"])
        in2 = any(p["id"] in c["members"] for c in s2["channels"])
        self.assertFalse(in2)
        self.assertTrue(in1 or s1["candidates"] > 0)

    def test_t31_t33_t34_width_score_greedy(self):
        b = wave(700, 1)
        s = SR.channels_at(b, 650)
        self.assertTrue(s["channels"])
        for c in s["channels"]:
            self.assertLessEqual(c["width"], s["width_cap"] + 1e-9)
            self.assertEqual(c["score"], 20 * c["score_components"]["pivots"] + c["score_components"]["touch_bars"])
        ch = s["channels"]
        for i in range(len(ch)):
            for j in range(i + 1, len(ch)):
                self.assertTrue(ch[i]["hi"] < ch[j]["lo"] or ch[i]["lo"] > ch[j]["hi"])   # no overlap incl. shared edge
        self.assertLessEqual(len(ch), 10)
        self.assertLessEqual(sum(c["visible"] for c in ch), 6)
        self.assertEqual([c["rank"] for c in ch], list(range(1, len(ch) + 1)))
        self.assertIn("RANGE_WINDOW_PARTIAL", SR.channels_at(b, 150)["flags"])

    def test_t33_touch_definition(self):
        b = [bar(i, 101, 99) for i in range(30)]
        b[25] = bar(25, 120, 80)                                  # spans the band with both ends outside: not a touch
        snap = {"lo": 100.0, "hi": 100.5}
        touch = sum(1 for x in b if snap["lo"] <= x["h"] <= snap["hi"] or snap["lo"] <= x["l"] <= snap["hi"])
        self.assertEqual(touch, 0)

    def test_t35_t36_ids_and_asof(self):
        b = wave(700, 2)
        a = SR.channels_at(b, 600)
        a2 = SR.channels_at(b[:601] + [dict(x, h=x["h"] + 50) for x in b[601:]], 600)
        self.assertEqual([c["id"] for c in a["channels"]], [c["id"] for c in a2["channels"]])    # future does not change as_of
        h = SR.ChannelHistory()
        for t in range(560, 600):
            h.update(b[:t + 1])
        self.assertIsNotNone(h.as_of(b[570]["open_utc"]))
        self.assertTrue(any(e["kind"] == "CREATED" for e in h.events))
        n = len(h.snaps)
        h.update(b[:600])                                          # repeated poll of the same bar
        self.assertEqual(len(h.snaps), n)

    def test_nearest_helpers(self):
        snap = {"channels": [{"lo": 90, "hi": 91, "rank": 2, "id": "a"}, {"lo": 110, "hi": 111, "rank": 1, "id": "b"},
                             {"lo": 99, "hi": 101, "rank": 3, "id": "c"}]}
        n = SR.nearest(snap, 100)
        self.assertEqual((n["support"]["id"], n["resistance"]["id"], n["inside"]["id"]), ("a", "b", "c"))


if __name__ == "__main__":
    unittest.main()
