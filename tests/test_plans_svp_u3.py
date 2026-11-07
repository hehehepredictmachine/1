"""1.33 U3 - PMW-PLAN-1 (Pepe Scalp Plan / Pepe Hedge Plan) and PMW-SVP-1 (interactive Session Volume Profile, zones MANUAL /
ALGORITHM / AI, AI proposal validation, LIVE generation guard). Analytical only - no order path is touched."""
import asyncio
import math
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

import _env  # noqa: F401
from _env import TempData

T0 = datetime(2026, 3, 2, 0, 0, tzinfo=timezone.utc).timestamp()


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")


def su(side="BUY", status="READY", entry=2000.0, sl=1996.0, tps=(2002.5, 2003.0, 2005.0), strategy="SCALPING", valid=None, now=None):
    now = now or time.time()
    sgn = 1 if side == "BUY" else -1
    return {"strategy": strategy, "symbol": "XAUUSD-", "instrument": "XAUUSD", "setup_version": "SH-1", "config_hash": "h", "status": status,
            "status_reason": "ok", "side": side, "signal_id": "SG-1", "created_at": now - 60, "valid_until": valid if valid is not None else now + 600,
            "entry_ref": entry, "sl": entry - sgn * (entry - sl) if side == "BUY" else entry + abs(entry - sl),
            "tps": [{"name": n, "price": entry + sgn * abs(p - entry), "share": 0.3} for n, p in zip(("TP1", "TP2", "TP3"), tps)],
            "be": {"after": "TP2"}}


class TestPlanContract(unittest.TestCase):
    def setUp(self):
        from masterquo.plans import contract as PC
        self.PC = PC

    def test_long_short_levels_and_order(self):
        for side in ("BUY", "SELL"):
            p = self.PC.from_setup(su(side=side))
            self.assertEqual(p["state"], "READY")
            names = [x["name"] for x in p["levels"]]
            self.assertEqual(names[:4], ["ENTRY", "SL", "TP1", "TP2"])
            lv = {x["name"]: x["price"] for x in p["levels"]}
            if side == "BUY":
                self.assertTrue(lv["SL"] < lv["ENTRY"] < lv["TP1"] < lv["TP2"])
            else:
                self.assertTrue(lv["SL"] > lv["ENTRY"] > lv["TP1"] > lv["TP2"])
            self.assertTrue(next(x for x in p["levels"] if x["name"] == "TP3")["optional"])
            self.assertEqual(p["layer"], "Pepe Scalp Plan")
            self.assertEqual(p["levels"][0]["kind"], "PLAN")

    def test_wait_without_levels_shows_reason_and_expired(self):
        w = self.PC.from_setup({"strategy": "SCALPING", "symbol": "XAUUSD-", "status": "WAIT", "status_reason": "czekam na trigger"})
        self.assertEqual(w["state"], "WAIT")
        self.assertEqual(w["levels"], [])
        self.assertEqual(w["state_reason"], "czekam na trigger")
        e = self.PC.from_setup(su(valid=time.time() - 1))
        self.assertEqual(e["state"], "EXPIRED")
        self.assertIn("TTL", e["state_reason"])

    def test_inconsistent_levels_invalidated(self):
        s = su()
        s["tps"][0]["price"] = 1990.0                                        # TP1 below entry for BUY
        p = self.PC.from_setup(s)
        self.assertEqual(p["state"], "INVALIDATED")
        self.assertIn("niespójne", p["state_reason"])

    def test_active_with_real_fill_and_managed_sl(self):
        pos = {"entry": 2000.12, "volume": 0.1, "remaining": 0.05, "sl": 2000.12, "be_status": "SET", "be_price": 2000.12, "state": "OPEN",
               "legs": [{"name": "TP1", "price": 2002.5, "status": "DONE", "fill_price": 2002.48, "fill_volume": 0.03},
                        {"name": "TP2", "price": 2003.0, "status": "PENDING"}]}
        p = self.PC.from_setup(su(), plan_row={"plan_id": "PL-1", "primary_ticket": 77, "state": "PRIMARY_OPEN", "exec_mode": "PAPER"}, position=pos)
        self.assertEqual(p["state"], "ACTIVE")
        ex = p["execution"]
        self.assertEqual(ex["entry_fill"], 2000.12)
        self.assertEqual(next(x for x in p["levels"] if x["name"] == "ENTRY")["price"], 2000.0)     # plan kept next to the fill
        self.assertEqual(next(x for x in p["levels"] if x["name"] == "ENTRY_FILL")["price"], 2000.12)
        self.assertEqual(ex["sl_version"], 2)
        self.assertIn("BE", ex["sl_change_reason"])
        self.assertEqual([t["reached"] for t in ex["targets"]], [True, False])                 # only from execution data
        self.assertIn("PAPER", ex["source"])

    def test_hedge_layer_netting_and_leg(self):
        s = su(strategy="HEDGING")
        net = self.PC.from_setup(s, account_margin_mode="RETAIL_NETTING")
        self.assertEqual(net["layer"], "Pepe Hedge Plan")
        self.assertFalse(net["hedge"]["available"])
        self.assertIn("NETTING", net["hedge"]["reason"])
        row = {"plan_id": "PL-2", "primary_ticket": 5, "state": "HEDGED", "plan": {"profile": {"hedge": {"trigger_fraction_of_sl": 0.5},
                                                                                              "position_max_minutes": 240},
                                                                                  "risk": {"basket_loss_limit_money": 50.0}}}
        basket = {"hedge": {"side": "SELL", "volume": 0.05, "entry": 1998.0, "status": "OPEN", "activations": 1},
                  "basket": {"net_after_costs": -3.2}}
        pos = {"entry": 2000.0, "sl": 1996.0, "volume": 0.1, "remaining": 0.1, "legs": [], "state": "OPEN"}
        h = self.PC.from_setup(s, account_margin_mode="RETAIL_HEDGING", plan_row=row, position=pos, basket=basket)
        self.assertTrue(h["hedge"]["available"])
        self.assertAlmostEqual(h["hedge"]["activation_level"], 1998.0)
        names = [x["name"] for x in h["levels"]]
        self.assertIn("HEDGE_ACTIVATION", names)
        self.assertIn("HEDGE_ENTRY", names)
        self.assertTrue(all(x["label"].startswith("HEDGE") for x in h["levels"] if x["name"].startswith("HEDGE")))
        self.assertEqual(h["hedge"]["leg_levels"], [])                                        # no invented hedge TP/SL
        self.assertIn("nie jest rysowany", h["hedge"]["basket_condition"])
        self.assertEqual(h["basket"]["net_after_costs"], -3.2)

    def test_chart_payload_filters_symbol_and_picks_primary(self):
        a = self.PC.from_setup(su())
        b = dict(self.PC.from_setup(su()), symbol="BTCUSD")
        out = self.PC.chart_payload([a, b], symbol="XAUUSD-", account_key="srv:1")
        self.assertEqual(len(out["plans"]), 1)
        self.assertEqual(out["primary"], a["plan_key"])


class TestSVPEngine(unittest.TestCase):
    def bars(self, n, f, tf_s=300, t0=T0, tv=lambda i: 10):
        out = []
        for i in range(n):
            c = f(i)
            out.append({"open_utc": iso(t0 + i * tf_s), "o": c, "h": c + 0.6, "l": c - 0.6, "c": c, "tv": tv(i), "rv": 0, "closed": True})
        return out

    def test_weight_conservation_deterministic_poc_va(self):
        from masterquo.svp import engine as EN
        b = self.bars(100, lambda i: 2000 + 3 * math.sin(i / 7), tv=lambda i: 5 + i % 7)
        p = EN.compute(b, "M5", T0, T0 + 100 * 300, as_of=T0 + 100 * 300, tick=0.01, bin_ticks=50, instrument="XAUUSD", symbol="X")
        self.assertEqual(p["status"], "READY")
        self.assertTrue(p["weight_conserved"])
        self.assertAlmostEqual(sum(x["weight"] for x in p["histogram"]), p["input_weight"], places=3)
        self.assertGreaterEqual(p["va_share"], 0.70)
        self.assertLess(p["val"], p["poc"])
        self.assertGreater(p["vah"], p["poc"])
        q = EN.compute(b, "M5", T0, T0 + 100 * 300, as_of=T0 + 100 * 300, tick=0.01, bin_ticks=50, instrument="XAUUSD", symbol="X")
        self.assertEqual((p["poc"], p["vah"], p["val"], p["snapshot_id"]), (q["poc"], q["vah"], q["val"], q["snapshot_id"]))
        for h in p["histogram"]:                                                  # bins = whole number of ticks
            self.assertAlmostEqual(round((h["hi"] - h["lo"]) / 0.01), 50)

    def test_tie_goes_to_lower_price(self):
        from masterquo.zones import dsvie as DS
        poc, a, b = DS.value_area({10: 5.0, 11: 5.0, 12: 1.0}, 0.5)
        self.assertEqual(poc, 10)

    def test_stable_grid_and_no_future(self):
        from masterquo.svp import engine as EN
        b = self.bars(60, lambda i: 2000 + i * 0.1)
        early = EN.compute(b, "M5", T0, T0 + 60 * 300, as_of=T0 + 30 * 300, tick=0.01, bin_ticks=25, instrument="XAUUSD", mode="LIVE")
        late = EN.compute(b, "M5", T0, T0 + 60 * 300, as_of=T0 + 60 * 300, tick=0.01, bin_ticks=25, instrument="XAUUSD", mode="LIVE")
        self.assertEqual(early["state"], "DEVELOPING")
        self.assertEqual(early["bars"], 30)                                       # nothing after as_of
        e = {x["lo"]: x["hi"] for x in early["histogram"]}
        l = {x["lo"]: x["hi"] for x in late["histogram"]}
        for lo, hi in e.items():                                                  # same bin boundaries as the profile grows
            self.assertEqual(l[lo], hi)

    def test_partial_history_and_empty(self):
        from masterquo.svp import engine as EN
        b = self.bars(20, lambda i: 2000.0)
        p = EN.compute(b, "M5", T0, T0 + 100 * 300, as_of=T0 + 200 * 300, tick=0.01, bin_ticks=50, instrument="XAUUSD")
        self.assertEqual(p["status"], "PARTIAL")
        self.assertIn("częściowa", p["reason"])
        n = EN.compute(b, "M5", T0 + 500 * 300, T0 + 600 * 300, as_of=T0 + 700 * 300, tick=0.01, bin_ticks=50, instrument="XAUUSD")
        self.assertEqual(n["status"], "NO_DATA")
        with self.assertRaises(ValueError):
            EN.compute(b, "M5", T0, T0, as_of=T0, tick=0.01, bin_ticks=50, instrument="XAUUSD")

    def test_midnight_and_dst_windows(self):
        from masterquo.svp import engine as EN
        a, b = EN.custom_window("Asia/Tokyo", "22:00", "02:00", "2026-03-02")
        self.assertEqual(b - a, 4 * 3600)                                         # crosses midnight
        a1, b1 = EN.custom_window("Europe/London", "08:00", "16:30", "2026-03-27")
        a2, b2 = EN.custom_window("Europe/London", "08:00", "16:30", "2026-03-30")  # after the UK DST switch
        self.assertEqual(datetime.fromtimestamp(a1, timezone.utc).hour, 8)
        self.assertEqual(datetime.fromtimestamp(a2, timezone.utc).hour, 7)


class TestSVPZones(unittest.TestCase):
    def snap(self):
        from masterquo.svp import engine as EN
        b = [{"open_utc": iso(T0 + i * 300), "o": 2000 + math.sin(i / 5), "h": 2000.8 + math.sin(i / 5), "l": 1999.2 + math.sin(i / 5),
              "c": 2000 + math.sin(i / 5), "tv": 10, "rv": 0, "closed": True} for i in range(80)]
        p = EN.compute(b, "M5", T0, T0 + 80 * 300, as_of=T0 + 80 * 300, tick=0.01, bin_ticks=20, instrument="XAUUSD", symbol="XAUUSD-")
        return dict(p, profile_id="UP-1"), b

    def test_algorithmic_zones_and_states(self):
        from masterquo.svp import zones as ZN
        p, b = self.snap()
        zs = ZN.algorithmic(p)
        kinds = {z["kind"] for z in zs}
        self.assertTrue({"POC", "VA_EDGE_HIGH", "VA_EDGE_LOW"} <= kinds)
        self.assertTrue(all("nie dowód zleceń" in z["justification"] for z in zs))
        z = {"zone_id": "Z", "lower": 2001.0, "upper": 2001.5, "available_at": iso(T0)}
        later = [{"open_utc": iso(T0 + i * 300), "o": c, "h": c + 0.2, "l": c - 0.2, "c": c, "closed": True}
                 for i, c in enumerate([2002.0, 2001.8, 2001.6, 2001.9, 2002.2, 2001.4, 2000.5, 2000.3, 2000.1, 2000.0, 1999.9])]
        st = ZN.evolve(z, later, tf_s=300, as_of=T0 + 20 * 300)
        self.assertEqual(st["origin_side"], "ABOVE")
        self.assertIn(st["state"], ("BROKEN", "INVALIDATED"))
        self.assertTrue(any(h["state"] == "CONFIRMED" for h in st["state_history"]))

    def test_ai_validation(self):
        from masterquo.svp import zones as ZN
        p, _ = self.snap()
        now = T0 + 81 * 300
        good = {"profile_id": "UP-1", "snapshot_id": p["snapshot_id"], "lower": p["val"], "upper": p["poc"], "type": "VALUE_AREA",
                "justification": "dolna część VA", "confirmation": "zamknięcie M5 powyżej POC", "invalidation": "2 zamknięcia poniżej VAL",
                "valid_until": iso(now + 3600)}
        ok, why, z = ZN.validate_ai(good, p, symbol="XAUUSD-", now=now)
        self.assertTrue(ok, why)
        self.assertEqual(z["source"], "AI")
        for patch, frag in (({"lower": p["low"] - 50, "upper": p["low"] - 49}, "zakres"), ({"upper": p["poc"] + 0.137 + p["bin_size"] * 1.5}, "podstawy"),
                            ({"snapshot_id": "SVS-x"}, "snapshot"), ({"valid_until": iso(now - 5)}, "ważności"), ({"type": "MAGIC"}, "typ"),
                            ({"justification": ""}, "brak pól")):
            ok, why, _ = ZN.validate_ai(dict(good, **patch), p, symbol="XAUUSD-", now=now)
            self.assertFalse(ok, patch)
            self.assertIn(frag, why)
        ok, why, _ = ZN.validate_ai(good, p, symbol="BTCUSD", now=now)
        self.assertIn("symbol", why)
        ok, why, _ = ZN.validate_ai(good, p, symbol="XAUUSD-", now=now + 10 * 86400)
        self.assertIn("nieaktualny", why)


class _Bridge:
    def __init__(self, bars):
        self._bars = bars
        self.symbol_info = {"trade_tick_size": 0.01, "digits": 2}
        self.account_key = "srv:1"
        self.sent = []

    def symbol_bars(self, symbol, tf, n):
        return self._bars[-n:]

    def bars(self, tf, include_forming=False, limit=None):
        return self._bars

    def order_send(self, *a, **k):          # never called by SVP
        self.sent.append(a)


class _Agent:
    def __init__(self, props=None, ok=True):
        self.props, self.ok, self.loop = props, ok, None

    def status(self):
        return {"state": "IDLE", "model": "m"}

    async def propose_zones(self, payload):
        self.payload = payload
        return {"ok": self.ok, "proposals": self.props(payload) if callable(self.props) else (self.props or []), "cost_usd_estimate": 0.001}


class TestSVPService(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.config import ConfigStore
        self.cfg = ConfigStore()
        self.now = T0 + 100 * 300
        self.bars = [{"open_utc": iso(T0 + i * 300), "o": 2000 + math.sin(i / 6), "h": 2000.7 + math.sin(i / 6), "l": 1999.3 + math.sin(i / 6),
                      "c": 2000 + math.sin(i / 6), "tv": 10 + i % 5, "rv": 0, "closed": True} for i in range(100)]
        self.bridge = _Bridge(self.bars)

    def tearDown(self):
        self.td.close()

    def svc(self, agent=None):
        from masterquo.svp.service import SVPService
        return SVPService(self.cfg, self.bridge, agent=agent, data_dir=Path(self.td.dir) / "svp", clock=lambda: self.now)

    def test_profile_crud_versions_freeze_restart(self):
        s = self.svc()
        p = s.create_profile({"mode": "RANGE", "t0": iso(T0), "t1": iso(T0 + 90 * 300), "name": "A", "bin_ticks": 20})
        r = s.compute(p["profile_id"])
        self.assertEqual(r["status"], "READY")
        p2 = s.update_profile(p["profile_id"], {"t1": iso(T0 + 95 * 300)})
        self.assertEqual(p2["version"], 2)                                      # moved bound = new version
        self.assertEqual(s.update_profile(p["profile_id"], {"color": "#ff0000"})["version"], 2)
        fr = s.freeze(p["profile_id"])
        self.bars.append({"open_utc": iso(T0 + 100 * 300), "o": 2050, "h": 2051, "l": 2049, "c": 2050, "tv": 1000, "rv": 0, "closed": True})
        self.now += 600
        again = s.compute(p["profile_id"])
        self.assertTrue(again["frozen"])
        self.assertEqual(again["snapshot_id"], fr["snapshot_id"])              # frozen snapshot never recomputed
        with self.assertRaises(ValueError):
            s.update_profile(p["profile_id"], {"t0": iso(T0 + 300)})
        s2 = self.svc()                                                         # restart: profiles and snapshots persist
        self.assertEqual(s2.compute(p["profile_id"])["snapshot_id"], fr["snapshot_id"])

    def test_manual_zone_never_overwritten_and_versioned(self):
        s = self.svc(agent=_Agent())
        p = s.create_profile({"mode": "RANGE", "t0": iso(T0), "t1": iso(T0 + 99 * 300), "bin_ticks": 20})
        m = s.create_manual({"lower": 2000.0, "upper": 2000.5, "name": "moja", "profile_id": p["profile_id"]})
        t_create = self.now
        s.algo_now(p["profile_id"])
        s.clear_auto(p["profile_id"])
        man = s.zones(source="MANUAL")
        self.assertEqual([z["zone_id"] for z in man], [m["zone_id"]])
        self.now += 60
        e = s.edit_zone(m["zone_id"], {"upper": 2000.8})
        self.assertEqual(e["version"], 2)
        self.assertEqual([h["version"] for h in s.zone_history(m["zone_id"])], [1, 2])
        old = s.zones(source="MANUAL", as_of=t_create)                          # reproduction at an earlier time
        self.assertEqual(old[0]["upper"], 2000.5)
        s.edit_zone(m["zone_id"], {"locked": True})
        with self.assertRaises(ValueError):
            s.edit_zone(m["zone_id"], {"upper": 2001.0})
        self.assertEqual(self.bridge.sent, [])

    def test_algo_zones_pinned_survive_refresh(self):
        s = self.svc()
        p = s.create_profile({"mode": "RANGE", "t0": iso(T0), "t1": iso(T0 + 99 * 300), "bin_ticks": 20})
        r = s.algo_now(p["profile_id"])
        self.assertTrue(r["zones"])
        zs = s.zones(source="ALGORITHM")
        pin = zs[0]["zone_id"]
        s.edit_zone(pin, {"pinned": True})
        self.assertEqual(s.clear_auto(p["profile_id"]), len(zs) - 1)
        self.assertEqual([z["zone_id"] for z in s.zones(source="ALGORITHM")], [pin])

    def test_ai_on_demand_validated_and_without_agent(self):
        none = self.svc(agent=None)
        p = none.create_profile({"mode": "RANGE", "t0": iso(T0), "t1": iso(T0 + 99 * 300), "bin_ticks": 20})
        r = asyncio.run(none.ai_propose(p["profile_id"]))
        self.assertEqual(r["status"], "AGENT_NOT_CONFIGURED")
        self.assertTrue(none.algo_now(p["profile_id"])["zones"])                # algorithm still works without the agent

        def props(pl):
            return [{"profile_id": pl["profile_id"], "snapshot_id": pl["snapshot_id"], "lower": pl["val"], "upper": pl["poc"], "type": "VALUE_AREA",
                     "justification": "VA", "confirmation": "c", "invalidation": "i", "valid_until": iso(self.now + 3600)},
                    {"profile_id": pl["profile_id"], "snapshot_id": pl["snapshot_id"], "lower": 1234.5, "upper": 1235.0, "type": "HVN",
                     "justification": "wymyślone", "confirmation": "c", "invalidation": "i", "valid_until": iso(self.now + 3600)}]
        s = self.svc(agent=_Agent(props))
        p = s.create_profile({"mode": "RANGE", "t0": iso(T0), "t1": iso(T0 + 99 * 300), "bin_ticks": 20})
        s.compute(p["profile_id"])
        r = asyncio.run(s.ai_propose(p["profile_id"]))
        self.assertEqual(r["status"], "OK")
        self.assertEqual(len(r["accepted"]), 1)
        self.assertEqual(len(r["rejected"]), 1)
        self.assertEqual({z["source"] for z in s.zones(source="AI")}, {"AI"})
        self.assertEqual(s.ai_jobs()[0]["accepted"], 1)

    def test_old_ai_result_never_replaces_newer_profile(self):
        s = self.svc(agent=_Agent())
        p = s.create_profile({"mode": "RANGE", "t0": iso(T0), "t1": iso(T0 + 99 * 300), "bin_ticks": 20})
        old = s.compute(p["profile_id"])
        s.update_profile(p["profile_id"], {"t0": iso(T0 + 3000)})
        self.now += 1
        s.compute(p["profile_id"])                                               # newer snapshot exists now
        prop = {"profile_id": p["profile_id"], "snapshot_id": old["snapshot_id"], "lower": old["val"], "upper": old["poc"], "type": "VALUE_AREA",
                "justification": "x", "confirmation": "c", "invalidation": "i", "valid_until": iso(self.now + 3600)}
        r = s.apply_ai(p["profile_id"], old, {"ok": True, "proposals": [prop]})
        self.assertEqual(r["status"], "STALE_RESULT_DROPPED")
        self.assertEqual(s.zones(source="AI"), [])

    def test_visible_rate_limit_and_significant_change(self):
        s = self.svc()
        a = s.visible("M5", iso(T0), iso(T0 + 50 * 300))
        self.assertIn(a["status"], ("READY", "PARTIAL"))
        self.assertEqual(s.visible("M5", iso(T0), iso(T0 + 50 * 300))["status"], "RATE_LIMITED")
        from masterquo.svp.service import SVPService
        self.assertFalse(SVPService.significant_change({"poc": 10.0, "vah": 11, "val": 9}, {"poc": 10.1, "vah": 11, "val": 9, "bin_size": 0.2}))
        self.assertTrue(SVPService.significant_change({"poc": 10.0, "vah": 11, "val": 9}, {"poc": 10.5, "vah": 11, "val": 9, "bin_size": 0.2}))

    def test_live_tick_recomputes_only_live_profiles(self):
        s = self.svc()
        s.create_profile({"mode": "RANGE", "t0": iso(T0), "t1": iso(T0 + 99 * 300), "bin_ticks": 20})
        lp = s.create_profile({"mode": "RANGE", "t0": iso(T0), "t1": iso(T0 + 99 * 300), "bin_ticks": 20})
        s.set_live(lp["profile_id"], True)
        self.assertEqual(s.live_tick(), 1)
        self.assertEqual(s.live_tick(), 0)                                       # same closed bar -> nothing to do


class TestAgentSVPTool(unittest.TestCase):
    def test_tool(self):
        import json as _j
        from masterquo.agent import tools as AT
        self.assertIn("get_svp_profiles", {t["name"] for t in AT.TOOL_DEFS})
        self.assertEqual(_j.loads(AT.Toolbox({}, 2).run("get_svp_profiles", {})[0])["status"], "UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
