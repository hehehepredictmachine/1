"""PMW-UPD-05 Multi TimeFrame Scalping Dashboard - MTFContextSnapshot adapter, freshness heartbeat, chart cutoff, archive.
Generated bars only (code path); case ids follow the specification list (11.1-11.16)."""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import _env  # noqa: F401
from _env import TempData

UTC = timezone.utc


def gen(end: datetime, n_m1=3000, seed=3):
    import numpy as np
    rng = np.random.default_rng(seed)
    t0 = end - timedelta(minutes=n_m1)
    m1, c = [], 2000.0
    for k in range(n_m1):
        o = c
        c = o + rng.normal(0, 0.3)
        m1.append({"open_utc": (t0 + timedelta(minutes=k)).isoformat().replace("+00:00", "Z"), "o": o, "h": max(o, c) + 0.1, "l": min(o, c) - 0.1, "c": c,
                   "tv": 50.0, "spread": 12, "closed": True, "revision": 0, "source": "TEST", "basis": "OBSERVED"})

    def agg(mins):
        out = []
        for i in range(0, len(m1) - mins + 1, mins):
            g = m1[i:i + mins]
            out.append(dict(g[0], h=max(b["h"] for b in g), l=min(b["l"] for b in g), c=g[-1]["c"]))
        return out
    return {"M1": m1, "M5": agg(5), "M15": agg(15), "M30": agg(30), "H1": agg(60)}


class Bridge:
    def __init__(self, bars):
        self.b, self.state, self.session_epoch, self.synthetic = bars, "CONNECTED", 1, True
        self.cfg = type("C", (), {"symbol": "XAUUSD-"})()
        self.q = {"bid": 2000.0, "ask": 2000.12, "time_utc": None, "age_seconds": 0.2}

    def bars(self, tf, limit=None, include_forming=True):
        seq = self.b[tf]
        return list(seq[-limit:] if limit else seq)

    def quote_status(self):
        return dict(self.q)

    def connection_status(self):
        return {"clock": {"status": "VERIFIED"}}


class Bus:
    def __init__(self):
        self.ev = []

    def publish(self, k, v):
        self.ev.append((k, v))


def scalp_stub(bars):
    from masterquo.scalp import strategy as st
    prof = st.load_profile()
    mach = st.ScalpMachine(prof, 0.01)
    ev = []
    for tf, mins in (("H1", 60), ("M30", 30), ("M15", 15), ("M5", 5), ("M1", 1)):
        for b in bars[tf]:
            x = {k: b[k] for k in ("open_utc", "o", "h", "l", "c", "tv")}
            x["spread_price"] = 0.12
            ev.append((st.ts(b["open_utc"]) + mins * 60, {"H1": 0, "M30": 0, "M15": 1, "M5": 2, "M1": 3}[tf], tf, x))
    ev.sort(key=lambda e: (e[0], e[1]))
    for _, _, tf, x in ev:
        if tf in ("M15", "M30", "H1"):
            mach.add_context({"M15": 15, "M30": 30, "H1": 60}[tf], x)
        elif tf == "M5":
            mach.on_m5_close(x)
        else:
            mach.on_m1_close(x)
    return type("S", (), {"prof": prof, "inst": "XAUUSD", "machine": mach})()


def shadow_row(setup_id, side, plan_extra=None):
    plan = {"setup_id": setup_id, "direction": side, "decision_time": "2026-10-19T10:00:00Z", "sl": 1990.0, "tp1": 2005.0, "tp2": 2010.0, "range_id": "R-x",
            "fill_shadow": 2000.1, **(plan_extra or {})}
    return {"setup_id": setup_id, "direction": side, "status": "BLOCKED", "created_at": "2026-10-19T10:00:01Z", "plan": plan, "instrument": "XAUUSD",
            "gates": [{"name": "trend M30/M15/H1 i sesja", "ok": True, "detail": "ok"}, {"name": "spread", "ok": False, "detail": "0.5"},
                      {"name": "uprawnienie wykonania", "ok": False, "detail": "EXECUTION_AUTHORIZED=false (SHADOW)"}], "outcome_status": "NOT_APPLICABLE"}


class TestSnapshot(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.db.database import Database
        from masterquo.scalp.dashboard import MTFDashboard
        self.end = datetime.now(UTC).replace(second=0, microsecond=0)
        self.bars = gen(self.end)
        self.bridge = Bridge(self.bars)
        self.sc = scalp_stub(self.bars)
        self.db = Database()
        self.bus = Bus()
        self.dash = MTFDashboard(self.sc, self.bridge, self.bus, self.db)

    def tearDown(self):
        self.td.close()

    def build(self, recent=None, nss=None):
        return self.dash.build(self.bars, info={"name": "XAUUSD-", "digits": 2, "trade_tick_size": 0.01}, epoch=1, recent=recent or [], nss_last=nss)

    def test_one_instrument_epoch_asof_and_roles(self):                 # 11.1 / MTF-01 / MTF-02
        s = self.build()
        self.assertEqual((s["asset"], s["session_epoch"], s["schema_version"]), ("XAUUSD", "1", "PMW-MTF-SNAPSHOT-1"))
        self.assertEqual(s["as_of"], (datetime.fromisoformat(self.bars["M1"][-1]["open_utc"].replace("Z", "+00:00")) + timedelta(minutes=1)).isoformat().replace("+00:00", "Z"))
        self.assertEqual([r["tf"] for r in s["timeframes"]], ["H1", "M30", "M15", "M5", "M1"])
        self.assertEqual({r["tf"]: r["role"] for r in s["timeframes"]}["M1"], "TRIGGER")
        asof = datetime.fromisoformat(s["as_of"].replace("Z", "+00:00"))
        for r in s["timeframes"]:
            self.assertLessEqual(datetime.fromisoformat(r["last_closed_close"].replace("Z", "+00:00")), asof)       # 11.2 closed by as_of only
        self.assertTrue(all(ref["snapshot_id"] == s["snapshot_id"] and ref["cutoff"] == s["as_of"] for ref in s["chart_refs"]))
        self.assertEqual(self.bus.ev[-1][0], "scalp_dashboard")
        self.assertFalse(s["execution"]["permission"])                                                            # 11.16

    def test_context_conditions_follow_profile_mode(self):              # 11.5
        from masterquo.scalp import strategy as st
        s = self.build()
        m = self.sc.machine
        for side in ("BUY", "SELL"):
            blk, _ = st.fade_blocked({"M30": st.context(m.m30, self.sc.prof), "M15": st.context(m.m15, self.sc.prof), "H1": st.context(m.h1, self.sc.prof)}, side, self.sc.prof)
            self.assertEqual(s["context_filter"][side]["status"], "UNKNOWN" if blk is None else "CONFLICT" if blk else "MET")
        h1 = next(r for r in s["timeframes"] if r["tf"] == "H1")
        self.assertFalse(h1["required"])                                       # BOTH: H1 is information only, never a third vote
        self.assertIn("nie jest bramką", h1["regime_note"])

    def test_chart_cutoff_overlays_and_archive(self):                   # 11.3 / 11.7 / 11.8
        s = self.build(recent=[shadow_row("SET-A", "BUY"), shadow_row("SET-B", "SELL", {"sl": 2011.0, "tp1": 1995.0})])
        c = self.dash.chart("M1", s["snapshot_id"])
        self.assertEqual((c["status"], c["bars_source"], c["cutoff"]), ("OK", "LIVE_SNAPSHOT_CACHE", s["as_of"]))
        self.assertTrue(all(datetime.fromisoformat(b["open_utc"].replace("Z", "+00:00")) + timedelta(minutes=1) <= datetime.fromisoformat(s["as_of"].replace("Z", "+00:00"))
                            for b in c["bars"]))
        lv = [o for o in c["overlays"] if o.get("setup_id")]
        self.assertEqual({o["setup_id"] for o in lv}, {"SET-A", "SET-B"})
        self.assertTrue(all(o["overlay_id"].startswith(o["setup_id"]) for o in lv))                     # levels carry their own setup id
        sa = next(x for x in s["setups"] if x["setup_id"] == "SET-A")
        self.assertEqual(sa["completeness"], {"met": 1, "of": 2, "label": "Kompletność warunków (nie P(zysk))"})
        self.assertEqual([g["name"] for g in sa["hard_gates"]], ["spread", "uprawnienie wykonania"])
        self.assertEqual(self.dash.chart("M1", "MTF-unknown")["status"], "SNAPSHOT_EXPIRED")
        # archive: the stored analysis never changes with later data; live cache gone -> archive body by id
        body = json.loads(self.db.one("SELECT body FROM mtf_snapshots WHERE snapshot_id=?", (s["snapshot_id"],))["body"])
        self.dash.cache.clear()
        self.bars["M1"][-1]["c"] += 30.0
        self.bars["M1"][-1]["revision"] = 1
        got = self.dash.get(s["snapshot_id"])
        self.assertTrue(got["archived"])
        self.assertEqual(got["as_of"], body["as_of"])
        self.assertEqual(got["tf_revisions"], body["tf_revisions"])
        self.assertEqual(self.dash.chart("M1", s["snapshot_id"])["status"], "OK")              # buffer still holds the same last bar id
        self.bridge.b = {tf: v[:-30] for tf, v in self.bars.items()}
        self.assertEqual(self.dash.chart("M1", s["snapshot_id"])["status"], "ARCHIVE_BARS_UNAVAILABLE")   # never replaced by latest
        self.assertIsNone(self.dash.get("MTF-never"))

    def test_models_not_linked_to_other_setup(self):                   # 11.13
        nss = {"setup_id": "OTHER", "side": "BUY", "technical_status": "READY_INFERENCE", "candidate_output": {"calibrated_probabilities": [0.5, 0.3, 0.2]}}
        s = self.build(recent=[shadow_row("SET-A", "BUY")], nss=nss)
        m = {x["task_id"]: x for x in s["setups"][0]["models"]}
        self.assertEqual(m["SCALP_SETUP_MARKET_V1"]["status"], "NOT_LINKED")
        self.assertNotIn("calibrated_output", m["SCALP_SETUP_MARKET_V1"])
        self.assertEqual(m["SCALP_NET_PROFIT_MARKET_V1"]["status"], "NOT_INSTALLED")
        s2 = self.build(recent=[shadow_row("OTHER", "BUY")], nss=nss)
        self.assertEqual({x["task_id"]: x for x in s2["setups"][0]["models"]}["SCALP_SETUP_MARKET_V1"]["calibrated_output"], [0.5, 0.3, 0.2])

    def test_heartbeat_without_new_m1(self):                           # 11.4 / MTF-07
        s = self.build()
        h = self.dash.heartbeat()
        self.assertEqual((h["overall"], h["quote_status"]), ("OK", "OK"))
        self.assertTrue(h["analysis_valid"])
        self.bridge.state = "DISCONNECTED"
        h = self.dash.heartbeat()
        self.assertEqual(h["overall"], "DISCONNECTED")
        self.assertFalse(h["analysis_valid"])
        self.bridge.state = "CONNECTED"
        self.bridge.b = {tf: [dict(b, open_utc=(datetime.fromisoformat(b["open_utc"].replace("Z", "+00:00")) - timedelta(minutes=10)).isoformat()) for b in v]
                         for tf, v in self.bars.items()}                          # feed stopped 10 minutes ago, no new M1 arrived
        self.bridge.q["age_seconds"] = 30.0
        h = self.dash.heartbeat()
        st_ = {r["tf"]: r["data_status"] for r in h["timeframes"]}
        self.assertEqual((h["overall"], st_["M1"], st_["H1"], h["quote_status"]), ("STALE", "STALE", "OK", "STALE_OR_MISSING"))   # H1 40 min old is fine
        self.assertEqual(self.db.one("SELECT COUNT(*) AS n FROM mtf_snapshots")["n"], 1)                # heartbeat never rewrites the analysis
        self.assertEqual(self.dash.get(s["snapshot_id"])["overall_data_quality"], s["overall_data_quality"])
        sat = datetime(2026, 10, 17, 12, tzinfo=UTC).timestamp()
        self.assertTrue(self.dash._session(sat, False).startswith("WEEKEND"))
        self.assertTrue(self.dash._session(datetime(2026, 10, 14, 12, tzinfo=UTC).timestamp(), False).startswith("SESSION_UNKNOWN"))

    def test_cache_bounded(self):                                        # MTF-09
        from masterquo.scalp import dashboard as dmod
        for i in range(dmod.CACHE_N + 5):
            self.bars["M1"].append(dict(self.bars["M1"][-1], open_utc=(datetime.fromisoformat(self.bars["M1"][-1]["open_utc"].replace("Z", "+00:00"))
                                                                      + timedelta(minutes=1)).isoformat().replace("+00:00", "Z")))
            self.build()
        self.assertLessEqual(len(self.dash.cache), dmod.CACHE_N)
        self.assertIn(self.dash.last["snapshot_id"], self.dash.cache)

    def test_no_order_path(self):                                        # 11.16
        import masterquo.scalp.dashboard as m
        src = Path(m.__file__).read_text(encoding="utf-8")
        self.assertNotIn("order_send", src)
        self.assertNotIn("gateway", src)


if __name__ == "__main__":
    unittest.main()
