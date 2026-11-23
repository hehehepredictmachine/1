"""1.46 audit, group C1 (zones service, basket catalog): regression tests.

* chunk_39#10 - after an asset switch the ZoneService kept serving the zone map of the PREVIOUS instrument: the recomputation was
  triggered only by a new open_utc of the last closed M5 bar, and the new symbol's buffer ends in the same time slot, so the old
  map (data.state OK) reached the evaluation layer and /api/v1/zones/map for up to 5 minutes.
* chunk_39#11 - context_for() ignored zones.enabled and the age of the map: with zones disabled (no more recomputation) or a dead
  feed, the last map kept data.state OK forever and its flags still counted in the assessment.
* chunk_06#19 / focus_X2#21 - preservation_view() declared execution_route SIGNALS_ONLY for all 60 strategies, although the
  FOREX_MT5 PositionPlans go to the SH execution path (AUTO_SH, 1.42).
All market data here is SYNTHETIC (tests/test_zones.py generators); nothing here touches an order path."""
import unittest
from pathlib import Path
from types import SimpleNamespace

import _env  # noqa: F401
import test_zones as TZ
from _env import TempData

BTC = {"assets": {"active": "BTC", "mappings": {"BTC": {"broker_symbol": "BTCUSD", "status": "CONFIRMED"}}},
       "mt5": {"symbol": "BTCUSD", "analytical_alias": "BTC"}}           # what AssetRegistry.switch("BTC") writes (+ the mapping)


class _ZoneServiceCase(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.config import ConfigStore
        from masterquo.zones.service import ZoneService
        self.store = ConfigStore()
        bars = TZ.market()
        self.reads = []
        reads = self.reads

        class Bridge:                                   # the buffers of the new symbol end in the SAME M5 slot (same time grid)
            def __init__(self):
                self.symbol_info = {"trade_tick_size": 0.01}

            def symbol_bars(self, symbol, tf, n):
                reads.append(symbol)
                return bars[tf][-n:]

            def bars(self, tf, include_forming=False, limit=None):
                return bars[tf][-500:]
        self.now = TZ.T0 + 2016 * 300
        self.svc = ZoneService(self.store, Bridge(), data_dir=Path(self.td.dir) / "zones", clock=lambda: self.now)

    def tearDown(self):
        self.svc.db.close()
        self.td.close()

    def poll_once(self):
        """One iteration of the service thread's loop (_loop), without a thread and without waiting poll_s."""
        waits = iter([False, True])
        self.svc._stop = SimpleNamespace(wait=lambda _s: next(waits), set=lambda: None)
        self.svc._loop()
        self.assertIsNone(self.svc.state["last_error"])


class ZoneMapFollowsTheActiveInstrument(_ZoneServiceCase):
    def test_asset_switch_recomputes_although_the_last_m5_slot_is_the_same(self):
        self.poll_once()
        zm = self.svc.current()
        self.assertEqual((zm["instrument"], zm["symbol"]), ("XAUUSD", "XAUUSD-"))
        self.assertEqual(self.svc.state["runs"], 1)
        self.poll_once()
        self.assertEqual(self.svc.state["runs"], 1)                    # same bar, same instrument: no recomputation (once per bar)
        self.store.update(BTC)                                         # assets.switch: only the configuration changes
        self.poll_once()                                               # the last closed M5 slot is unchanged
        zm = self.svc.current()
        self.assertEqual((zm["instrument"], zm["symbol"]), ("BTC", "BTCUSD"))
        self.assertEqual(self.svc.state["runs"], 2)
        self.assertEqual(self.reads[-1], "BTCUSD")

    def test_map_of_the_previous_instrument_is_never_served(self):
        zm = self.svc.refresh()
        price = zm["price"]
        self.assertEqual(self.svc.context_for(direction="LONG", entry=price, stop=price - 3)["map_id"], zm["map_id"])
        self.store.update(BTC)                                         # switched, not recomputed yet
        self.assertIsNone(self.svc.current())                          # XAUUSD map is not the map of BTC
        self.assertIsNone(self.svc.context_for(direction="LONG", entry=price, stop=price - 3))
        self.assertIsNone(self.svc.status()["instrument"])
        zm2 = self.svc.current_or_refresh()                            # the API recomputes on demand for the active instrument
        self.assertEqual(zm2["instrument"], "BTC")


class ZoneContextHonoursEnabledAndAge(_ZoneServiceCase):
    def test_disabled_zones_give_no_context(self):
        zm = self.svc.refresh()
        price = zm["price"]
        self.assertIsNotNone(self.svc.context_for(direction="LONG", entry=price, stop=price - 3))
        self.store.update({"zones": {"enabled": False}})              # the loop stops recomputing -> the last map must not keep counting
        self.assertIsNone(self.svc.context_for(direction="LONG", entry=price, stop=price - 3))

    def test_old_map_is_marked_stale_in_the_context(self):
        zm = self.svc.refresh()
        price = zm["price"]
        ctx = self.svc.context_for(direction="LONG", entry=price, stop=price - 3)
        self.assertEqual((ctx["data_state"], ctx["features"]["zone_data_ok"]), ("OK", 1.0))
        self.now += 2 * 300                                            # normal cadence (one map per closed M5): still current
        self.assertEqual(self.svc.context_for(direction="LONG", entry=price, stop=price - 3)["data_state"], "OK")
        self.now += 3600                                               # feed dead / no recomputation for an hour
        ctx = self.svc.context_for(direction="LONG", entry=price, stop=price - 3)
        self.assertEqual(ctx["data_state"], "STALE")
        self.assertEqual(ctx["features"]["zone_data_ok"], 0.0)
        self.assertEqual(ctx["map_id"], zm["map_id"])
        self.assertEqual(ctx["map_as_of"], zm["as_of"])                # the map's own time is never shifted (look-ahead check)
        self.assertEqual(self.svc.current()["data"]["state"], "OK")    # the stored map itself is not rewritten

    def test_stale_context_does_not_reduce_the_assessment(self):
        from masterquo.evaluation import engine as E
        from test_evaluation import cand
        self.svc.refresh()
        self.now += 3600
        z = dict(self.svc.context_for(direction="LONG", entry=self.svc.current()["price"], stop=None), flags=["ZONE_ROOM_INSUFFICIENT"])
        p = {"value": 0.60, "calibrated": True, "n_calibration": 2000,
             "interval": {"lo": 0.55, "hi": 0.65, "method": "test", "validated": True}}
        self.assertEqual(E.assess(cand(), prob=p, extra_cost=0.1, zones=z).decision, "ACCEPT")


class PreservationViewExecutionRoute(unittest.TestCase):
    def test_route_follows_profile_and_plan_type(self):
        from masterquo.baskets import catalog as C
        from masterquo.baskets import service as BS
        self.assertEqual(BS.DEFAULT_SETTINGS["profiles"]["FOREX_MT5"]["execution"], "AUTO_SH")
        view = C.preservation_view()
        self.assertEqual(len(view), 60)
        routes = {v["strategy_id"]: v["execution_route"] for v in view}
        for s in C.CATALOG:
            if s["profile_id"] == "FOREX_MT5" and s["plan_type"] == "PositionPlan":
                want = "SH_PATH (AUTO_SH)"                              # 1.42: FX_SMC / FX_SCALP plans -> the existing SH path
            elif s["plan_type"] == "HedgePlan":
                want = "PLAN_ONLY"
            else:
                want = "MANUAL_TICKET"                                  # CRYPTO: ticket for manual execution in FOMO
            self.assertEqual(routes[s["strategy_id"]], want, s["strategy_id"])
        self.assertEqual(sum(r == "SH_PATH (AUTO_SH)" for r in routes.values()), 20)
        signals = {v["strategy_id"]: v["execution_route"] for v in C.preservation_view(fx_execution="SIGNALS_ONLY")}
        self.assertEqual(signals["FX_SMC_01"], "SIGNALS_ONLY")         # 1.41 behaviour when the user chose SIGNALS_ONLY
        self.assertEqual(signals["CP_SMC_01"], "MANUAL_TICKET")
        self.assertTrue(all(v["legacy_aliases"] == [] for v in view))  # still no alias of a gold strategy -> no duplicate route

    def test_preservation_report_still_has_no_duplicate_route(self):
        from masterquo.baskets import catalog as C
        from masterquo.upgrade import preservation as P
        rep = P.compare([{"strategy_id": "S01", "source": "ACTIVE"}], [{"strategy_id": "S01", "source": "ACTIVE"}], new_catalog=C.preservation_view())
        self.assertEqual(rep["duplicate_execution_routes"], [])
        self.assertEqual(rep["result"], "PASS")


if __name__ == "__main__":
    unittest.main()
