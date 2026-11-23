"""WF3.2 TASK 008 + 009 - session context clock (IANA DST, half-open windows, candle countdown, spread / ADR14 truth labels) and
broker-server-hour range boxes with HUD (overnight wrap, closed bars only, units, TIME_MAPPING_UNVERIFIED)."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import _env  # noqa: F401

UTC = timezone.utc


def at(s):
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


class TestSessions(unittest.TestCase):
    def S(self, when, mode="AUTO_DST"):
        from masterquo.analytics import session_context as SC
        return {s["id"]: s for s in SC.sessions(at(when), mode)}

    def test_winter_defaults_match_listing_gmt_hours(self):
        s = self.S("2025-01-15T12:00:00")
        self.assertEqual(s["LONDON"]["open_utc"], "2025-01-15T08:00:00Z")
        self.assertEqual(s["NEW_YORK"]["open_utc"], "2025-01-15T13:00:00Z")
        self.assertFalse(s["TOKYO"]["is_active"])                                   # Tokyo 00-09 GMT, closed at 12:00 -> next window
        self.assertEqual((s["TOKYO"]["open_utc"], s["TOKYO"]["next_transition"]), ("2025-01-16T00:00:00Z", "OPEN"))
        self.assertEqual(s["SYDNEY"]["open_utc"], "2025-01-15T21:00:00Z")          # next Sydney open 21:00 GMT (AEDT, southern summer)
        self.assertTrue(s["LONDON"]["is_active"] and s["NEW_YORK"]["is_active"] is False)

    def test_summer_dst_shifts_each_zone_by_its_own_rule(self):
        s = self.S("2025-07-15T12:00:00")
        self.assertEqual(s["LONDON"]["open_utc"], "2025-07-15T07:00:00Z")          # BST
        self.assertEqual(s["NEW_YORK"]["open_utc"], "2025-07-15T12:00:00Z")        # EDT
        self.assertEqual(s["SYDNEY"]["open_utc"], "2025-07-15T22:00:00Z")          # AEST (no DST in July)
        self.assertEqual(self.S("2025-07-15T01:00:00")["TOKYO"]["open_utc"], "2025-07-15T00:00:00Z")   # Tokyo never changes

    def test_out_of_sync_week_us_vs_eu(self):
        s = self.S("2025-03-12T12:00:00")                                           # US already on EDT, UK still GMT
        self.assertEqual(s["NEW_YORK"]["open_utc"], "2025-03-12T12:00:00Z")
        self.assertEqual(s["LONDON"]["open_utc"], "2025-03-12T08:00:00Z")

    def test_half_open_boundaries_and_fixed_mode(self):
        s = self.S("2025-01-15T08:00:00")
        self.assertTrue(s["LONDON"]["is_active"])
        s = self.S("2025-01-15T17:00:00")
        self.assertFalse(s["LONDON"]["is_active"])
        self.assertEqual(s["LONDON"]["next_transition"], "OPEN")
        f = self.S("2025-07-15T07:30:00", "FIXED_GMT")
        self.assertFalse(f["LONDON"]["is_active"])                                  # fixed mode = entered GMT hours literally
        self.assertTrue(self.S("2025-07-15T07:30:00")["LONDON"]["is_active"])

    def test_dst_transition_days_nine_hours_each(self):
        from masterquo.analytics import session_context as SC
        for day in ("2025-03-30", "2025-10-26", "2025-03-09", "2025-11-02", "2025-04-06", "2025-10-05", "2028-02-29"):
            for h in range(24):
                for s in SC.sessions(at(f"{day}T{h:02d}:00:00")):
                    o = datetime.fromisoformat(s["open_utc"].replace("Z", "+00:00"))
                    c = datetime.fromisoformat(s["close_utc"].replace("Z", "+00:00"))
                    self.assertEqual(c - o, timedelta(hours=9), (day, h, s["id"]))
                    self.assertEqual(s["quality"], "CONFIGURED_UNVERIFIED")


class TestCandleSpreadAdr(unittest.TestCase):
    def test_candle_countdown_progress_and_stale(self):
        from masterquo.analytics import session_context as SC
        c = SC.candle("M15", at("2025-01-15T10:07:30"))
        self.assertEqual((c["open_utc"], c["close_utc"], c["seconds_remaining"], c["progress"]), ("2025-01-15T10:00:00Z", "2025-01-15T10:15:00Z", 450, 0.5))
        s = SC.candle("M5", at("2025-01-15T10:07:30"), last_bar_open_utc=at("2025-01-15T09:00:00"))
        self.assertEqual((s["quality"], s["seconds_remaining"]), ("STALE", None))
        self.assertEqual(SC.candle("X7", at("2025-01-15T10:07:30"))["quality"], "UNKNOWN")
        for tf in SC.TF_SECONDS:
            self.assertGreaterEqual(SC.candle(tf, at("2025-01-15T10:07:30"))["seconds_remaining"], 0)

    def test_spread_truth_labels(self):
        from masterquo.analytics import session_context as SC
        self.assertEqual(SC.spread(None)["quality"], "UNKNOWN")
        fresh = SC.spread({"spread_points": 23.0, "age_seconds": 1.0, "received_at": "x"})
        self.assertEqual((fresh["current_points"], fresh["quality"], fresh["average_points"], fresh["average_reason"]),
                         (23.0, "VERIFIED", None, "AVERAGE_NOT_CONFIGURED"))
        stale = SC.spread({"spread_points": 23.0, "age_seconds": 120})
        self.assertEqual((stale["current_points"], stale["quality"]), (None, "STALE"))
        self.assertEqual(SC.spread({"spread_points": None, "age_seconds": 1})["quality"], "UNKNOWN")

    def test_adr14_complete_partial_and_zero_day(self):
        from masterquo.analytics import session_context as SC
        days = [{"h": 10.0 + i, "l": 8.0 + i, "closed": True} for i in range(20)] + [{"h": 33.0, "l": 30.0, "closed": False}]
        r = SC.daily_range(days)
        self.assertEqual((r["adr14"], r["today_range"], r["percent_of_adr14"], r["quality"]), (2.0, 3.0, 150.0, "VERIFIED"))
        self.assertEqual(SC.daily_range(days[-10:])["quality"], "INCOMPLETE")
        bad = list(days)
        bad[-3] = {"h": 5.0, "l": 5.0, "closed": True}
        self.assertEqual(SC.daily_range(bad)["quality"], "INCOMPLETE")
        self.assertEqual(SC.daily_range([])["quality"], "UNKNOWN")

    def test_server_clock_status_never_upgraded(self):
        from masterquo.analytics import session_context as SC
        for st in ("UNKNOWN", "MEASURING", "STORED_UNVERIFIED", "INCONSISTENT"):
            c = SC.server_clock({"status": st, "offset_seconds": 7200})
            self.assertEqual((c["status"], c["value"]), (st, None))
        self.assertIsNotNone(SC.server_clock({"status": "VERIFIED", "offset_seconds": 7200})["value"])


class TestServerBoxes(unittest.TestCase):
    def bars(self, days=3, tf=300):
        out = []
        base = 1_735_689_600                       # 2025-01-01 00:00 (server time epoch)
        for i in range(days * 86400 // tf):
            t = base + i * tf
            minute = (t % 86400) // 60
            p = 100 + minute / 100
            out.append({"t_raw": t, "o": p, "h": p + 0.5, "l": p - 0.5, "c": p, "closed": True})
        return out

    def test_three_default_boxes_high_low_closed_only(self):
        from masterquo.analytics import session_context as SC
        bs = self.bars(2)
        bs.append({"t_raw": bs[-1]["t_raw"] + 300, "o": 1e9, "h": 1e9, "l": -1e9, "c": 1e9, "closed": False})     # forming bar ignored
        boxes = SC.range_boxes(bs, history_days=2)
        asia = [b for b in boxes if b["box"] == "ASIA"]
        self.assertEqual(len(asia), 2)
        self.assertEqual(asia[0]["bars"], 96)                                       # 8 h of M5 bars
        self.assertAlmostEqual(asia[0]["low"], 99.5)
        self.assertAlmostEqual(asia[0]["high"], 100 + 475 / 100 + 0.5)             # last bar 07:55
        lon = [b for b in boxes if b["box"] == "LONDON"][0]
        self.assertEqual((lon["bars"], lon["state"]), (72, "COMPLETE"))
        self.assertTrue(all(b["high"] < 1e9 for b in boxes))

    def test_overnight_wrap_belongs_to_start_day(self):
        from masterquo.analytics import session_context as SC
        boxes = SC.range_boxes(self.bars(3), boxes=({"id": "NIGHT", "start": "22:00", "end": "02:00"},), history_days=5)
        self.assertEqual([b["bars"] for b in boxes if b["state"] == "COMPLETE"], [48, 48])
        self.assertEqual(boxes[0]["end_raw"] - boxes[0]["start_raw"], 4 * 3600)

    def test_hud_units_and_time_mapping(self):
        from masterquo.analytics import session_context as SC
        bs = self.bars(1)
        h = SC.hud({"spread_points": 20.0, "age_seconds": 0.5}, {"point": 0.01, "trade_stops_level": 30}, bs, {"status": "MEASURING"})
        self.assertEqual((h["spread_points"], h["stops_level_points"], h["time_mapping"]), (20.0, 30, "TIME_MAPPING_UNVERIFIED"))
        self.assertAlmostEqual(h["atr14_points"], h["atr14"] / 0.01, places=3)
        self.assertEqual(SC.hud(None, None, [], None)["stops_level_quality"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
