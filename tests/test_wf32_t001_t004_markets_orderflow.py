"""WF3.2 TASK 001-004: multi-market instrument master + FOMO 101 seed, three bridges on one contract, ten TFs (deterministic M10), capability
registry, canonical trade ledger (dedupe / correction / provider side semantics), trade-based Volume Profile, Footprint (A+B+U=V conservation,
imbalances), depth book with sequence-gap detection, CP_SCALP_09 blocked on unverified aggressor semantics."""
from __future__ import annotations

import json
import os
import unittest
import urllib.request

import _env  # noqa: F401

CORE = {"universe": [{"name": "BTC", "szDecimals": 5, "maxLeverage": 40}, {"name": "ETH", "szDecimals": 4, "maxLeverage": 25},
                     {"name": "OLD", "szDecimals": 0, "maxLeverage": 3, "isDelisted": True}]}
XYZ = {"universe": [{"name": "xyz:XYZ100", "szDecimals": 4, "maxLeverage": 30}, {"name": "xyz:NVDA", "szDecimals": 3, "maxLeverage": 20},
                    {"name": "xyz:GOLD", "szDecimals": 4, "maxLeverage": 20}, {"name": "xyz:AAPL", "szDecimals": 3, "maxLeverage": 10, "isDelisted": True},
                    {"name": "xyz:SP500", "szDecimals": 3, "maxLeverage": 20}]}


class FakeHL:
    errors, last_error = 0, None

    def __init__(self):
        self.calls = []

    def post(self, body):
        self.calls.append(body)
        t = body["type"]
        if t == "perpDexs":
            return [None, {"name": "xyz"}, {"name": "flx"}]
        if t == "meta":
            return XYZ if body.get("dex") == "xyz" else CORE
        if t == "candleSnapshot":
            iv = body["req"]["interval"]
            sec = {"5m": 300, "1h": 3600}[iv]
            end = body["req"]["endTime"]
            t0 = (end // 1000 // sec - 30) * sec
            return [{"t": (t0 + i * sec) * 1000, "T": (t0 + (i + 1) * sec) * 1000 - 1, "o": 1 + i, "h": 2 + i, "l": i, "c": 1.5 + i, "v": 10, "n": 3}
                    for i in range(30)]
        if t == "l2Book":
            return {"time": 1_700_000_000_000, "levels": [[{"px": "99", "sz": "5"}, {"px": "98", "sz": "7"}], [{"px": "101", "sz": "4"}]]}
        if t == "recentTrades":
            return [{"coin": body["coin"], "side": "B", "px": "100", "sz": "2", "time": 1_700_000_000_000, "tid": 1},
                    {"coin": body["coin"], "side": "A", "px": "100.4", "sz": "3", "time": 1_700_000_001_000, "tid": 2},
                    {"coin": body["coin"], "side": "A", "px": "100.4", "sz": "3", "time": 1_700_000_001_000, "tid": 2}]
        if t == "metaAndAssetCtxs":
            meta = XYZ if body.get("dex") == "xyz" else CORE
            return [meta, [{"markPx": "100.1", "oraclePx": "100.0", "funding": "0.0001", "openInterest": "5000", "dayNtlVlm": "1e6"}
                           for _ in meta["universe"]]]
        raise AssertionError(body)


class TestUniverse(unittest.TestCase):
    def setUp(self):
        from masterquo.markets import universe as MU
        self.MU = MU
        self.u = MU.Universe(FakeHL())

    def test_seed_exactly_101_unique_with_nvda(self):
        v = self.MU.validate_seed(self.MU.load_seed())
        self.assertEqual((v["count"], v["unique"], v["nvda_present"], v["ok"]), (101, 101, True, True))

    def test_identity_classification_and_hip3_asset_id(self):
        ins = {i.native_symbol: i for i in self.u.instruments()}
        self.assertEqual((ins["xyz:NVDA"].market, ins["xyz:NVDA"].product_type, ins["xyz:NVDA"].asset_id), ("FOMO_STOCK_PERPS", "STOCK_PERPETUAL", 110001))
        self.assertEqual(ins["xyz:XYZ100"].market, "INDICES")
        self.assertEqual(ins["xyz:GOLD"].market, "OTHER_XYZ")
        self.assertEqual((ins["BTC"].market, ins["BTC"].execution), ("CRYPTO", "MANUAL_ONLY"))
        self.assertEqual(ins["xyz:NVDA"].execution, "DISABLED")
        self.assertEqual(ins["OLD"].status, "DELISTED")
        self.assertNotEqual(ins["xyz:NVDA"].instrument_id, "NVDA")                    # ticker = display alias only

    def test_seed_resolution_reports_not_found_and_delisted(self):
        res = {r["symbol"]: r for r in self.MU.resolve_seed(self.MU.load_seed(), self.u.instruments())}
        self.assertEqual(len(res), 101)
        self.assertEqual(res["NVDA"]["status"], "ACTIVE")
        self.assertEqual(res["AAPL"]["status"], "DELISTED")
        self.assertEqual(res["TSLA"]["status"], "NOT_FOUND")                          # not in the fake catalogue -> never fabricated
        offline = self.MU.resolve_seed(self.MU.load_seed(), [])
        self.assertEqual({r["status"] for r in offline}, {"NOT_VERIFIED"})

    def test_bridges_share_contract_and_m10_is_resampled(self):
        fb = self.MU.FomoStockPerpsBridge(self.u.hl, self.u)
        c = fb.candles("xyz:NVDA", "10m", 5)
        self.assertTrue(c["resampled"])
        self.assertTrue(all(b["t"] % 600 == 0 and b["complete"] for b in c["bars"]))
        self.assertEqual(self.u.hl.calls[-1]["req"]["interval"], "5m")
        with self.assertRaises(self.MU.UniverseError):
            fb.candles("BTC", "1h")                                                    # crypto instrument is not on the stock perps bridge
        with self.assertRaises(self.MU.UniverseError):
            fb.candles("xyz:NVDA", "2h")
        ctx = fb.context("xyz:NVDA")
        self.assertEqual((ctx["mark"], ctx["oracle"], ctx["funding"]), (100.1, 100.0, 0.0001))
        self.assertTrue(ctx["warnings"])
        self.assertEqual([i["native_symbol"] for i in self.MU.IndicesMarketBridge(self.u.hl, self.u).instruments()], ["xyz:XYZ100", "xyz:SP500"])
        for br in (self.MU.CryptoMarketBridge, self.MU.IndicesMarketBridge, self.MU.FomoStockPerpsBridge):
            for m in ("instruments", "candles", "context", "book", "trades", "health"):
                self.assertTrue(callable(getattr(br, m)))
            self.assertFalse(any(hasattr(br, x) for x in ("order", "place_order", "send_order", "order_send")))

    def test_resample_skips_incomplete_groups(self):
        bars = [{"t": 600 + i * 300, "o": 1, "h": 2, "l": 0, "c": 1, "v": 1} for i in range(5)]      # 600..1800: groups 600,1200 complete, 1800 partial
        out = self.MU.resample(bars, 300, 600)
        self.assertEqual([b["t"] for b in out], [600, 1200])
        self.assertEqual(out[0]["v"], 2)

    def test_capabilities_and_templates(self):
        nv = next(i for i in self.u.instruments() if i.native_symbol == "xyz:NVDA")
        cap = self.MU.capabilities(nv)
        self.assertEqual((cap["trades_aggressor"], cap["orderbook"], cap["orders"], cap["historical_depth"]),
                         ("NOT_VERIFIED", "DEGRADED", "UNSUPPORTED", "UNSUPPORTED"))
        for k, v in cap.items():
            if k != "notes":
                self.assertIn(v, self.MU.CAP_STATES)
        t = self.MU.basket_templates()
        self.assertEqual(set(t), {"CRYPTO", "INDICES", "FOMO_STOCK_PERPS"})
        self.assertTrue(all(x["status"] == "PROPOSED" and len(x["timeframes"]) == 10 for x in t.values()))
        from masterquo.baskets import catalog as C
        self.assertEqual(C.validate()["total"], 60)                                    # templates never enter the active catalogue


class TestTradeLedger(unittest.TestCase):
    def ev(self, tid, ts, px, sz, ag="UNKNOWN", prov="BYBIT", rev=0):
        from masterquo.orderflow.trades import TradeEvent
        return TradeEvent(prov, "I", str(tid), ts, px, sz, ag, revision=rev)

    def test_side_semantics_per_provider(self):
        from masterquo.orderflow import trades as T
        self.assertEqual(T.aggressor_from_raw("BINANCE", True), "SELL")
        self.assertEqual(T.aggressor_from_raw("BINANCE", False), "BUY")
        self.assertEqual(T.aggressor_from_raw("BYBIT", "Buy"), "BUY")
        self.assertEqual(T.aggressor_from_raw("OKX", "sell"), "SELL")
        self.assertEqual(T.aggressor_from_raw("HYPERLIQUID", "B"), "UNKNOWN")           # not verified -> no direction
        self.assertEqual(T.aggressor_from_raw("MT5", "BUY"), "UNKNOWN")
        self.assertEqual((T.capability("HYPERLIQUID"), T.capability("OKX")), ("NOT_VERIFIED", "SUPPORTED"))

    def test_dedupe_correction_and_validation(self):
        from masterquo.orderflow.trades import TradeLedger, from_hyperliquid
        L = TradeLedger()
        self.assertEqual(L.extend(from_hyperliquid("HL|xyz:NVDA", FakeHL().post({"type": "recentTrades", "coin": "x"}))),
                         {"ADDED": 2, "CORRECTED": 0, "DUPLICATE": 1})
        self.assertEqual(L.total_volume(), 5.0)
        L.add(self.ev(9, 1, 10, 1))
        self.assertEqual(L.add(self.ev(9, 1, 10, 4, rev=1)), "CORRECTED")
        self.assertEqual(L.total_volume("I"), 4.0)
        with self.assertRaises(ValueError):
            self.ev(1, 1, float("nan"), 1)
        with self.assertRaises(ValueError):
            self.ev(1, 1, 10, 0)


class TestProfileFootprint(unittest.TestCase):
    def events(self, directional=True):
        from masterquo.orderflow.trades import TradeEvent
        rows = [(0, 100.00, 1, "BUY"), (1, 100.05, 2, "BUY"), (2, 100.10, 5, "SELL"), (3, 100.10, 1, "BUY"), (61, 100.20, 3, "BUY"),
                (62, 100.25, 4, "BUY"), (63, 100.30, 4, "BUY"), (64, 99.90, 2, "SELL"), (65, 100.10, 1, "SELL"),
                (66, 100.40, 2, "BUY")]
        return [TradeEvent("BYBIT", "I", str(i), ts, px, sz, ag if directional else "UNKNOWN") for i, (ts, px, sz, ag) in enumerate(rows)]

    def test_volume_profile_conservation_poc_va(self):
        from masterquo.orderflow import analytics as OA
        vp = OA.volume_profile(self.events(), 0.1)
        self.assertAlmostEqual(sum(r["total"] for r in vp["rows"]), 25.0)
        self.assertAlmostEqual(vp["total_volume"], 25.0)
        self.assertEqual(vp["poc"], 100.1)
        self.assertTrue(vp["val"] <= vp["poc"] < vp["vah"])
        self.assertGreaterEqual(vp["value_area_volume"], 0.7 * 25 - 1e-9)
        for r in vp["rows"]:
            self.assertAlmostEqual(r["buy"] + r["sell"] + r["unknown"], r["total"])
        self.assertAlmostEqual(vp["delta"], 17 - 8)                                # buys 1+2+1+3+4+4+2, sells 5+2+1

    def test_unknown_side_gives_neutral_profile_and_footprint(self):
        from masterquo.orderflow import analytics as OA
        vp = OA.volume_profile(self.events(False), 0.1)
        self.assertIsNone(vp["delta"])
        self.assertTrue(all(r["delta"] is None for r in vp["rows"]))
        fp = OA.footprint(self.events(False), 60, 0.1)
        self.assertEqual(fp["mode"], "NEUTRAL_TOTAL_ONLY (strona agresora niezweryfikowana)")
        self.assertTrue(all(r["A"] is None and r["imbalance"] is None for b in fp["bars"] for r in b["rows"]))
        self.assertEqual(OA.cvd(self.events(False)), [])

    def test_footprint_conservation_and_cross_consumer_consistency(self):
        from masterquo.orderflow import analytics as OA
        ev = self.events()
        fp = OA.footprint(ev, 60, 0.1)
        self.assertEqual([b["t"] for b in fp["bars"]], [0, 60])
        for b in fp["bars"]:
            for r in b["rows"]:
                self.assertAlmostEqual(r["A"] + r["B"] + r["U"], r["V"])
        fp_total = sum(r["V"] for b in fp["bars"] for r in b["rows"])
        self.assertAlmostEqual(fp_total, OA.volume_profile(ev, 0.1)["total_volume"])
        self.assertAlmostEqual(fp_total, sum(e.size for e in ev))
        self.assertAlmostEqual(sum(x["size"] for x in OA.bubbles(ev)), fp_total)

    def test_diagonal_and_stacked_imbalance(self):
        from masterquo.orderflow import analytics as OA
        fp = OA.footprint(self.events(), 60, 0.1, ratio=3.0, min_volume=1.0, stacked=3)
        b2 = fp["bars"][1]
        imb = {r["price"]: r["imbalance"] for r in b2["rows"]}
        self.assertEqual(imb[100.2], "BUY")
        self.assertEqual([s["rows"] for s in b2["stacked_imbalances"] if s["side"] == "BUY"], [3])
        self.assertEqual(b2["labels"], "HEURISTIC")


class TestDepth(unittest.TestCase):
    def test_book_gap_requires_resync_and_dom(self):
        from masterquo.orderflow import analytics as OA
        b = OA.OrderBook()
        self.assertEqual(b.delta("BID", 1, 1, 1), "IGNORED_NOT_SYNCED")
        b.snapshot([[99, 5], [98, 7]], [[101, 4]], seq=10)
        self.assertEqual(b.delta("BID", 99.5, 2, 11), "APPLIED")
        self.assertEqual(b.delta("ASK", 101, 0, 12), "APPLIED")
        self.assertEqual(b.dom()["bids"][0], (99.5, 2.0))
        self.assertEqual(b.dom()["asks"], [])
        self.assertEqual(b.delta("BID", 97, 1, 14), "GAP")
        self.assertEqual(b.state, "RESYNC_REQUIRED")
        h = OA.heatmap([{"t": 1, "bids": [[99, 5]], "asks": [[101, 4]]}], 1.0)
        self.assertIn("DEGRADED", h["quality"])


class TestCpScalp09Gate(unittest.TestCase):
    def test_unverified_aggressor_blocks_rule(self):
        from masterquo.baskets import rules as R
        from masterquo.baskets.rules import Unavailable

        class F:
            i, c = 0, [0]

            def b(self):
                return 1.0
        with self.assertRaises(Unavailable) as cm:
            R.l2_aggressor(F(), 1, {}, {"flow": [{"t": 1, "imbalance5": 0.5, "aggr_buy_share_30s": 0.9, "aggressor_semantics": "NOT_VERIFIED"}]})
        self.assertIn("NOT_VERIFIED", str(cm.exception))
        with self.assertRaises(Unavailable):
            R.l2_aggressor(F(), 1, {}, {"flow": [{"t": 1, "imbalance5": 0.5, "aggr_buy_share_30s": 0.9}]})      # legacy flow without the field


@unittest.skipUnless(os.environ.get("PMW_LIVE_TESTS") == "1", "live provider check: PMW_LIVE_TESTS=1")
class TestLiveHyperliquid(unittest.TestCase):
    def test_live_xyz_contains_nvda(self):
        req = urllib.request.Request("https://api.hyperliquid.xyz/info", data=json.dumps({"type": "meta", "dex": "xyz"}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            names = [u["name"] for u in json.load(r)["universe"]]
        self.assertIn("xyz:NVDA", names)


if __name__ == "__main__":
    unittest.main()
