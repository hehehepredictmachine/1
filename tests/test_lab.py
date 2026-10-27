"""1.14 lab / two-asset tests (prompt B16). Synthetic data and the synthetic terminal ONLY test the code - no result here is
a market result. Covered: symbol lock, trade pad plan, causality (prefix invariance), multi-TF availability, model pipeline (fit
isolation, artifact reload, schema/asset rejection), streaming == replay (incl. SNN state), pattern/zone persistence, data edge
cases (gaps, duplicates, DST, missing ticks, short history) and one end-to-end run for XAUUSD and one for BTC."""
from __future__ import annotations

import json
import math
import unittest
from datetime import datetime, timedelta, timezone

import numpy as np

import _env
from _env import TempData, core, wait_for

UTC = timezone.utc


def synth_bars(n=1500, tf="M5", seed=1, start=datetime(2026, 3, 2, tzinfo=UTC), price=2400.0, scale=0.6):
    rng = np.random.default_rng(seed)
    sec = {"M5": 300, "M15": 900, "H1": 3600, "D1": 86400}[tf]
    c = price + np.cumsum(rng.normal(0, scale, n))
    out = []
    for i in range(n):
        o = c[i - 1] if i else c[0]
        h = max(o, c[i]) + abs(rng.normal(0, scale / 2))
        lo = min(o, c[i]) - abs(rng.normal(0, scale / 2))
        out.append({"open_utc": (start + timedelta(seconds=sec * i)).strftime("%Y-%m-%dT%H:%M:%SZ"), "o": float(o), "h": float(h), "l": float(lo),
                    "c": float(c[i]), "tv": int(rng.integers(50, 500)), "spread": 12, "closed": True})
    return out


def connected(symbol="XAUUSD-"):
    cfg, db, bus, log, fake, worker, b = core(symbol=symbol)
    from masterquo.assets.registry import AssetRegistry
    reg = AssetRegistry(cfg, b, log)
    b.assets = reg
    b.start()
    assert wait_for(lambda: b.state == "CONNECTED" and b.clock.verified and bool([x for x in b.bars("M5", 5) if x.get("open_utc")]), 60)
    return cfg, db, bus, log, fake, worker, b, reg


# ------------------------------------------------------------------------------------------------ symbol lock
class TestSymbolLock(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_classify_metadata_not_names(self):
        from masterquo.assets.registry import classify
        self.assertEqual(classify({"currency_base": "XAU", "currency_profit": "USD"})["asset"], "XAUUSD")
        self.assertIsNone(classify({"currency_base": "XAUT", "currency_profit": "USD"})["asset"])          # tether gold != XAU
        self.assertIsNone(classify({"currency_base": "WBTC", "currency_profit": "USD"})["asset"])          # wrapped BTC != BTC
        r = classify({"currency_base": "BTC", "currency_profit": "USDT"})
        self.assertIsNone(r["asset"])                                                                        # not assumed BTCUSD
        self.assertIn("BTC_QUOTED_IN_USDT_NOT_USD", r["conflicts"])
        self.assertEqual(classify({"currency_base": "BTC", "currency_profit": "USD"})["asset"], "BTC")
        self.assertIsNone(classify({"currency_base": "EUR", "currency_profit": "USD"})["asset"])

    def test_config_allowlist(self):
        from masterquo.config import AppConfig
        with self.assertRaises(Exception):
            AppConfig.model_validate({"mt5": {"symbol": "EURUSD-"}})                                       # free-text engine symbol
        with self.assertRaises(Exception):
            AppConfig.model_validate({"assets": {"mappings": {"EURUSD": {"broker_symbol": "EURUSD-"}}}})  # third asset
        with self.assertRaises(Exception):
            AppConfig.model_validate({"assets": {"mappings": {"BTC": {"broker_symbol": "XAUUSD-", "status": "CONFIRMED"}}}})

    def test_migration_keeps_user_symbol(self):
        from masterquo.config import AppConfig, migrate
        raw = {"config_version": 10, "mt5": {"symbol": "XAUUSD-"}, "execution": {"mode": "AUTO_DEMO"}}
        self.assertTrue(migrate(raw))
        c = AppConfig.model_validate(raw)
        self.assertEqual(c.assets.mappings["XAUUSD"].broker_symbol, "XAUUSD-")
        self.assertEqual(c.assets.mappings["XAUUSD"].status, "USER_SPECIFIED")
        self.assertEqual(c.assets.mappings["BTC"].status, "UNMAPPED")
        self.assertFalse(hasattr(c.execution, "lock"))                          # 1.24: Execution Lock withdrawn (config v12)
        self.assertEqual(c.execution.mode, "PAPER")                             # the AUTO mode the old lock held back is not started silently

    def test_no_symbol_blocking_and_account_symbols(self):
        """1.14.1: nothing is blocked by symbol - other enabled symbols work; BTC is taken from the account automatically."""
        cfg, db, bus, log, fake, worker, b, reg = connected()
        try:
            self.assertTrue(b.symbol_bars("EURUSD-", "H1", 10))                       # other enabled symbol: works
            self.assertIsNone(reg.check_symbol("EURUSD-", "DATA"))                    # labelled, not rejected
            self.assertEqual(reg.check_symbol("XAUUSD-", "DATA"), "XAUUSD")
            self.assertTrue(wait_for(lambda: cfg.get().assets.mappings["BTC"].broker_symbol == "BTCUSD-", 20))
            self.assertEqual(cfg.get().assets.mappings["BTC"].status, "AUTO_DETECTED")
            with self.assertRaises(SymbolNotAllowedT()):
                reg.check_asset("DOGE", "TRAINING")                                    # only the asset id must be XAUUSD / BTC
            from masterquo.markets.scanner import MarketScanner
            self.assertIn("EURUSD-", MarketScanner(cfg, b, bus, log).universe())    # scanner: Market Watch as before
            reg.switch("BTC")
            self.assertEqual((cfg.get().mt5.symbol, cfg.get().mt5.analytical_alias), ("BTCUSD-", "BTC"))
        finally:
            b.stop()
            worker.stop()

    def test_missing_configured_symbol_uses_account_symbol(self):
        """Configured symbol not offered by the broker -> the gold symbol enabled on the account is used (no blocking)."""
        cfg, db, bus, log, fake, worker, b = core(symbol="XAUUSD.pro")
        from masterquo.assets.registry import AssetRegistry
        b.assets = AssetRegistry(cfg, b, log)
        b.start()
        try:
            self.assertTrue(wait_for(lambda: b.state == "CONNECTED", 40))
            self.assertEqual(cfg.get().mt5.symbol, "XAUUSD-")
            self.assertEqual(cfg.get().assets.mappings["XAUUSD"].status, "AUTO_DETECTED")
        finally:
            b.stop()
            worker.stop()

    def test_metadata_mismatch_is_only_a_warning(self):
        cfg, db, bus, log, fake, worker, b = core()
        from masterquo.assets.registry import AssetRegistry
        reg = AssetRegistry(cfg, b, log)
        r = reg.verify("XAUUSD", {"currency_base": "USD", "currency_profit": "USD", "trade_contract_size": 100.0, "digits": 2, "point": 0.01})
        self.assertEqual(r["status"], "WARNING")
        self.assertIn("XAUUSD-", reg.allowed_symbols())                                  # still works
        worker.stop()


def SymbolNotAllowedT():
    from masterquo.assets.registry import SymbolNotAllowed
    return SymbolNotAllowed


# ------------------------------------------------------------------------------------------------ Trade Pad (M42)
class TestTradePadPlan(unittest.TestCase):
    def test_trade_pad_is_simulation_only(self):
        from masterquo.lab.edge import trade_pad_plan
        r = trade_pad_plan(side="BUY", entry=2400, sl=2395, tp=2410, lots=0.1, meta={"trade_contract_size": 100, "volume_min": 0.01, "volume_step": 0.01},
                           quote={"bid": 2399.9, "ask": 2400.1}, commission_per_lot_side=0.5)
        self.assertEqual(r["execution"], "VIA_MANUAL_PAD")        # the plan never sends; real orders: Manual Pad (1.24: no Execution Lock)
        self.assertAlmostEqual(r["pnl_at_tp"], 10 * 100 * 0.1 - 0.1, places=6)
        self.assertAlmostEqual(r["pnl_at_sl"], -5 * 100 * 0.1 - 0.1, places=6)
        with self.assertRaises(ValueError):
            trade_pad_plan(side="BUY", entry=2400, sl=2405, tp=2410, lots=0.1, meta={"trade_contract_size": 100}, quote=None, commission_per_lot_side=0)


# ------------------------------------------------------------------------------------------------ causality / structure
class TestStructure(unittest.TestCase):
    def test_prefix_invariance_features_and_modules(self):
        from masterquo.lab import features as FE
        from masterquo.lab import market
        bars = synth_bars(900)
        k = 700
        a = FE.feature_matrix(bars[:k], "M5")["X"]
        b = FE.feature_matrix(bars, "M5")["X"]
        np.testing.assert_allclose(a, b[:k], equal_nan=True)                              # future bars never change past features
        va, vb = market.vol_regime(bars[:k], series=k), market.vol_regime(bars, series=900)
        self.assertEqual([x["state"] for x in va["series"]], [x["state"] for x in vb["series"]][:len(va["series"])])
        pa = [p for p in market.pivots(bars[:k], "M5")]
        pb = [p for p in market.pivots(bars, "M5") if p["confirmed_i"] < k]
        self.assertEqual([(p["kind"], p["i"]) for p in pa], [(p["kind"], p["i"]) for p in pb])
        za, zb = market.zscore(bars[:k]), market.zscore(bars[:k] + [dict(bars[k], c=bars[k]["c"] * 1.5)])
        self.assertEqual(za["series"][1:], zb["series"][:-1])                              # appended bar changes only itself

    def test_pivot_confirmed_at(self):
        from masterquo.lab.market import pivots
        bars = synth_bars(300)
        for p in pivots(bars, "M5", 3, 3):
            self.assertEqual(p["confirmed_i"], p["i"] + 3)
            self.assertGreater(p["confirmed_at"], p["origin_time"])

    def test_markov_causal(self):
        from masterquo.lab.market import markov
        bars = synth_bars(800)
        m1 = markov(bars[:600])
        m2 = markov(bars[:600] + synth_bars(200, seed=9))
        self.assertEqual(markov(bars[:600]), m1)                                          # deterministic on the same prefix
        self.assertAlmostEqual(sum(m1["next_distribution"].values()), 1.0, places=2)
        self.assertNotEqual(m1["samples"], 0)
        self.assertIn(m2["current_state"], ("DOWN", "FLAT", "UP"))

    def test_zscore_guard(self):
        from masterquo.lab.market import zscore
        flat = [dict(b, o=2400.0, h=2400.0, l=2400.0, c=2400.0) for b in synth_bars(100)]
        self.assertEqual(zscore(flat)["status"], "low_dispersion")

    def test_ict_fvg_ids(self):
        from masterquo.lab.market import ict_sequence, fvgs
        bars = synth_bars(600, seed=4, scale=1.5)
        g = fvgs(bars, "M5")
        self.assertEqual(len({x["id"] for x in g}), len(g))
        r = ict_sequence(bars, "M5")
        self.assertIn("definitions", r)
        sel = [x for x in r.get("fvg_candidates", []) if x["selected"]]
        self.assertLessEqual(len(sel), 1)
        for x in r.get("fvg_candidates", []):
            self.assertTrue(x["selected"] or x["rejected_because"])              # every FVG: selected or a stated reason

    def test_liquidity_pdh_only_from_closed_day(self):
        from masterquo.lab.market import previous_day_levels
        d1 = synth_bars(5, tf="D1", start=datetime(2026, 3, 2, tzinfo=UTC))
        as_of = datetime(2026, 3, 4, 10, tzinfo=UTC).timestamp()                         # inside day 3 (open 2026-03-04)
        lv = previous_day_levels(d1, as_of)
        self.assertEqual(lv["day_open"], "2026-03-03T00:00:00Z")                          # the developing day is never 'previous'


# ------------------------------------------------------------------------------------------------ multi-TF / sessions
class TestMTF(unittest.TestCase):
    def test_h1_close_never_in_m5_decision(self):
        from masterquo.lab.sessions import as_of_join
        h1 = synth_bars(10, tf="H1")
        t = datetime(2026, 3, 2, 3, 15, tzinfo=UTC).timestamp()                           # 03:15 decision
        b = as_of_join(t, h1, "H1")
        self.assertEqual(b["open_utc"], "2026-03-02T02:00:00Z")                           # 02:00-03:00 bar, not 03:00-04:00

    def test_memory_sequence(self):
        from masterquo.lab.sessions import memory_sequence
        by = {"M5": synth_bars(60), "M15": synth_bars(20, tf="M15"), "H1": synth_bars(6, tf="H1")}
        r = memory_sequence(by, "M15", "2026-03-02T01:15:00Z")
        self.assertEqual(len(r["projections"]["M5"]["bars"]), 3)
        self.assertTrue(r["projections"]["H1"]["forming_at_host_close"])

    def test_sessions_dst(self):
        from masterquo.lab.sessions import session_windows
        jan = {w["session"]: w for w in session_windows("XAUUSD", datetime(2026, 1, 15, 12, tzinfo=UTC))}
        jul = {w["session"]: w for w in session_windows("XAUUSD", datetime(2026, 7, 15, 12, tzinfo=UTC))}
        self.assertEqual(jan["LONDON"]["start"].hour, 8)
        self.assertEqual(jul["LONDON"]["start"].hour, 7)                                  # BST
        self.assertNotEqual(session_windows("BTC", datetime(2026, 1, 15, tzinfo=UTC))[0]["tz"], jan["ASIA"]["tz"])

    def test_session_box_developing_has_no_final_levels(self):
        from masterquo.lab.sessions import session_boxes
        bars = synth_bars(40, tf="M15", start=datetime(2026, 3, 2, 8, tzinfo=UTC))       # London open, partial session
        boxes = session_boxes(bars, "M15", "XAUUSD", days=0)["boxes"]
        dev = [b for b in boxes if b["state"] == "DEVELOPING"]
        self.assertTrue(dev)
        self.assertIsNone(dev[0]["available_at"])


# ------------------------------------------------------------------------------------------------ ticks
class TestTicks(unittest.TestCase):
    def ticks(self, n=2000, gap_at=1000, seed=3):
        rng = np.random.default_rng(seed)
        t, out, px = 1_772_000_000.0, [], 2400.0
        for i in range(n):
            t += rng.exponential(2.0) + (3600 if i == gap_at else 0)
            px += rng.normal(0, 0.05)
            out.append({"t": t, "bid": round(px, 2), "ask": round(px + 0.12, 2), "flags": 6})
        return out

    def test_acd_gap_policy_and_fit(self):
        from masterquo.lab.ticks import acd_activity
        tk = self.ticks()
        r = acd_activity(tk, tk[-1]["t"] + 1)
        self.assertEqual(r["status"], "ready")
        self.assertEqual(r["gaps_removed"], 1)                                             # the 1 h break is not "quiet"
        f = r["fit"]
        self.assertTrue(f["omega"] > 0 and 0 <= f["alpha"] and 0 <= f["beta"] and f["alpha"] + f["beta"] < 1)
        self.assertGreater(r["expected_wait_s"], 0)
        self.assertEqual(acd_activity(tk, tk[-1]["t"] + 7200)["state"], "SESSION_BREAK_OR_OUTAGE")
        self.assertEqual(acd_activity(tk[:50], tk[49]["t"])["status"], "missing_data")

    def test_kinematics_and_verification(self):
        from masterquo.lab.ticks import kinematics, verify_forecasts
        tk = [{"t": 1000.0 + i * 0.5, "bid": 2400 + 0.01 * i * 0.5, "ask": 2400.1 + 0.01 * i * 0.5} for i in range(200)]
        k = kinematics(tk)
        self.assertAlmostEqual(k["velocity_per_s"], 0.01, places=6)
        self.assertEqual(kinematics(tk[:3])["status"], "missing_data")
        v = verify_forecasts([k["forecast"]], tk + [{"t": tk[-1]["t"] + 20, "bid": 2400 + 0.01 * 120, "ask": 2400.1 + 0.01 * 120}])
        self.assertEqual(v["verified"], 1)

    def test_bridge_ticks_dedup_and_invalid(self):
        td = TempData()
        cfg, db, bus, log, fake, worker, b, reg = connected()
        try:
            r = b.ticks("XAUUSD-", 600)
            self.assertIn(r["status"], ("ok", "missing_data"))
            keys = [(x["t"], x["bid"], x["ask"]) for x in r["ticks"]]
            self.assertEqual(len(keys), len(set(keys)))
            self.assertTrue(all(x["ask"] >= x["bid"] > 0 for x in r["ticks"]))
        finally:
            b.stop()
            worker.stop()
            td.close()


# ------------------------------------------------------------------------------------------------ Fourier archive
class TestFourier(unittest.TestCase):
    def test_sinusoid_and_archive(self):
        from masterquo.lab.fourier import archive_record, evaluate, extrapolate
        x = np.arange(400)
        c = 100 + 0.01 * x + np.sin(2 * np.pi * x / 32)
        r = extrapolate(c[:300], n_past=256, n_fut=20)
        self.assertEqual(r["status"], "ready")
        self.assertTrue(any(abs(h["period_bars"] - 32) < 1 for h in r["harmonics"]))
        np.testing.assert_allclose(r["path"], c[300:320], atol=0.15)
        opens = [f"t{i:04d}" for i in range(400)]
        rec = archive_record("XAUUSD", "H1", "t", opens[299], r)
        before = json.dumps(rec, sort_keys=True)
        ev = evaluate([rec], dict(zip(opens, c.tolist())), opens)
        self.assertEqual(ev["evaluated_points"], 20)
        self.assertEqual(json.dumps(rec, sort_keys=True), before)                          # the archived path is never rewritten
        self.assertEqual(extrapolate(c[:100], n_past=256)["status"], "warming_up")


# ------------------------------------------------------------------------------------------------ zones persistence
class TestZones(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_restore_corrupt_snapshot_no_duplicates(self):
        from masterquo.db.database import Database
        from masterquo.lab.zones import ZoneStore, detect
        db = Database()
        root = _env.Path(self.td.dir) / "zones"
        st = ZoneStore(db, root)
        z = detect(synth_bars(800, scale=1.2, seed=5), "M15", "XAUUSD", disp_atr=1.2)
        self.assertTrue(z)
        st.save("XAUUSD", z)
        st.save("XAUUSD", z)                                                               # same ids -> upsert, not duplicates
        n = len(st.load_db("XAUUSD"))
        self.assertEqual(n, len({x["zone_id"] for x in z}))
        (root / "zones_XAUUSD.json").write_text("{corrupt", encoding="utf-8")
        db.execute("DELETE FROM lab_zones WHERE zone_id=?", (z[0]["zone_id"],))
        st2 = ZoneStore(db, root)
        r = st2.restore("XAUUSD")
        self.assertEqual(r["snapshot_used"], "zones_XAUUSD.json.bak")
        self.assertEqual(r["restored"], 1)
        self.assertEqual(len(st2.load_db("XAUUSD")), n)
        self.assertTrue(any(e["event"] == "SNAPSHOT_CORRUPT" for e in st2.events))

    def test_manual_zone_never_auto_rated(self):
        from masterquo.db.database import Database
        from masterquo.lab.zones import ZoneStore
        st = ZoneStore(Database(), _env.Path(self.td.dir) / "zones")
        z = st.add_manual("BTC", "H1", "DEMAND", 65000, 64000, "2026-03-02T00:00:00Z")
        st.save("BTC", [{**z, "quality": "AUTO_RULE", "state": "TESTED"}])
        row = st.load_db("BTC")[0]
        self.assertEqual(row["quality"], "UNRATED")
        with self.assertRaises(ValueError):
            st.save("XAUUSD", [z])                                                           # asset mismatch refused


# ------------------------------------------------------------------------------------------------ edge / drift / repaint
class TestEdge(unittest.TestCase):
    def test_bootstrap(self):
        from masterquo.lab.edge import block_bootstrap_mean
        rng = np.random.default_rng(0)
        r = block_bootstrap_mean((rng.normal(0.3, 1, 400)).tolist())
        self.assertLess(r["ci95"][0], r["mean"])
        self.assertLess(r["mean"], r["ci95"][1])
        self.assertEqual(block_bootstrap_mean([1, 2])["status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(block_bootstrap_mean(rng.normal(0, 1, 300).tolist())["verdict"], "NO_VALIDATED_EDGE")

    def test_drift(self):
        from masterquo.lab.edge import edge_drift
        rng = np.random.default_rng(1)
        ok = edge_drift(rng.normal(0.2, 1, 200).tolist(), baseline_mean=0.2)
        bad = edge_drift((list(rng.normal(0.2, 1, 100)) + list(rng.normal(-0.8, 1, 100))), baseline_mean=0.2)
        self.assertEqual(ok["state"], "OK")
        self.assertEqual(bad["state"], "DEGRADED")
        self.assertEqual(edge_drift([1.0] * 30, baseline_mean=0.0, label_delay=25)["state"], "INSUFFICIENT_EVIDENCE")

    def test_repaint(self):
        from masterquo.lab.edge import RepaintInspector
        ri = RepaintInspector()
        self.assertEqual(ri.observe("XAUUSD", "M", "M5", {"a": 1, "b": 2}, "t1"), [])
        ch = ri.observe("XAUUSD", "M", "M5", {"a": 1, "b": 3, "c": 4}, "t2")
        self.assertEqual([c["change"] for c in ch], ["CHANGED"])
        ch = ri.observe("XAUUSD", "M", "M5", {"a": 1, "c": 4}, "t3")
        self.assertEqual([c["change"] for c in ch], ["VANISHED"])
        self.assertEqual(ri.report()[0]["observations"], 3)


# ------------------------------------------------------------------------------------------------ networks / MiniRocket
class TestNets(unittest.TestCase):
    def test_resnet_gradient_check(self):
        from masterquo.lab.nets import ResNet1D
        rng = np.random.default_rng(1)
        m = ResNet1D(3, width=4, blocks=2, seed=3)
        x, y = rng.normal(size=(5, 3, 7)), rng.integers(0, 2, 5)
        _, G = m.loss_grad(x, y, l2=1e-3)
        errs = []
        for k, P in m.p.items():
            for _ in range(5):
                i = tuple(rng.integers(0, s) for s in P.shape)
                o = P[i]
                P[i] = o + 1e-5
                lp, _ = m.loss_grad(x, y, l2=1e-3)
                P[i] = o - 1e-5
                lm, _ = m.loss_grad(x, y, l2=1e-3)
                P[i] = o
                num = (lp - lm) / 2e-5
                errs.append(abs(num - G[k][i]) / max(1e-8, abs(num) + abs(G[k][i])))
        self.assertLess(float(np.median(errs)), 1e-5)

    def test_sew_identity_and_streaming(self):
        from masterquo.lab.nets import SEWSNN
        rng = np.random.default_rng(2)
        x = rng.normal(size=(2, 20, 3))
        s = SEWSNN(3, hidden=8, seed=1)
        s.p["W2"][:] = 0
        s.p["b2"][:] = 0
        o = s.run(x)
        np.testing.assert_array_equal(o["S1"] + o["S2"], o["S1"])                        # identity path of SEW ADD
        s = SEWSNN(3, hidden=8, seed=4)
        full = s.run(x)
        st, steps = None, []
        for t in range(20):
            r = s.run(x[:, t:t + 1], st)
            st = r["state"]
            steps.append(r["S2"][:, 0])
        np.testing.assert_array_equal(np.stack(steps, 1), full["S2"])                    # streaming == replay (state continuity)
        before = {k: v.copy() for k, v in s.p.items()}
        s.predict_proba(x)
        self.assertTrue(all(np.array_equal(before[k], s.p[k]) for k in before))           # no update in inference
        a, b = SEWSNN(3, seed=4), SEWSNN(3, seed=4)                                         # separate instances = separate state
        ra = a.run(x[:, :10])
        rb = b.run(x[:, :10], ra["state"])
        self.assertFalse(np.array_equal(rb["V1"], a.run(x[:, :10])["V1"]))

    def test_minirocket_fit_on_train_only(self):
        from masterquo.lab.minirocket import MiniRocket
        rng = np.random.default_rng(0)
        tr, te = rng.normal(size=(40, 2, 32)), rng.normal(5, 3, size=(10, 2, 32))
        m = MiniRocket(num_features=336, seed=1).fit(tr)
        st = json.dumps(m.state())
        Z = m.transform(te)
        self.assertEqual(json.dumps(m.state()), st)                                        # transform never refits
        self.assertEqual(Z.shape[0], 10)
        self.assertTrue(((Z >= 0) & (Z <= 1)).all())
        np.testing.assert_array_equal(MiniRocket(num_features=336, seed=1).fit(tr).transform(te), Z)   # deterministic artefact
        with self.assertRaises(ValueError):
            m.transform(rng.normal(size=(3, 2, 40)))


# ------------------------------------------------------------------------------------------------ protocol / artifacts
class TestProtocol(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_splits_purged(self):
        from masterquo.lab.protocol import split_dev_holdout, walk_forward
        te = np.arange(1000) * 300.0
        tl = te + 12 * 300
        dev, hold, cut = split_dev_holdout(te, tl, 0.2, 3600)
        self.assertTrue((tl[dev] < cut).all())
        self.assertTrue((te[hold] >= cut + 3600).all())
        for tr, va in walk_forward(te, tl, dev, 4, 3600):
            self.assertTrue((tl[tr] < te[va].min() - 3600).all())

    def test_gmm_rows_only_in_training(self):
        from masterquo.lab.protocol import fit_family
        from masterquo.lab import features as FE
        rng = np.random.default_rng(0)
        X = rng.normal(size=(400, len(FE.FEATURES)))
        y = (X[:, 0] > 0).astype(int)
        f = fit_family("LOGREG_GMM_AUG", X[:300], None, y[:300], seed=1, budget=1)
        self.assertGreater(f.prep["gmm_synthetic_rows"], 0)
        self.assertEqual(len(f.predict(X[300:], None)), 100)                               # validation rows untouched

    def test_study_insufficient_and_holdout_once_and_artifact(self):
        from masterquo.db.database import Database
        from masterquo.lab import protocol as P
        db = Database()
        small = P.Study(db, P.default_protocol("XAUUSD", min_events=5000), synth_bars(800), point=0.01, data_source="SYNTHETIC", instrument_id=None)
        self.assertEqual(small.run()["verdict"], "INSUFFICIENT_EVIDENCE")
        bars = synth_bars(2600, seed=2)
        prot = P.default_protocol("XAUUSD", families=("DUMMY", "LOGREG"), experiments=(), min_events=600)
        st = P.Study(db, prot, bars, point=0.01, data_source="SYNTHETIC", instrument_id="XAUUSD:SYN:XAUUSD-")
        res = st.run()
        self.assertIn(res["verdict"], ("NO_VALIDATED_EDGE", "HOLDOUT_PASSED"))
        self.assertTrue(db.query("SELECT * FROM lab_trials WHERE asset='XAUUSD'"))          # every trial recorded
        prep = st.prepare()
        idx = prep["idx"]
        X = prep["fm"]["X"][idx]
        Xs = P.FE.sequences(prep["fm"]["X"], idx, prot["seq_len"])
        y = prep["lb"]["y"][idx].astype(int)
        dev, hold = np.arange(0, 1500), np.arange(1700, len(y))
        first = st.holdout_once("LOGREG", X, Xs, y, prep["lb"]["r"][idx], dev, hold, "HH1")
        self.assertIn("passed", first)
        self.assertEqual(st.holdout_once("LOGREG", X, Xs, y, prep["lb"]["r"][idx], dev, hold, "HH1")["refused"], "HOLDOUT_ALREADY_USED")
        f = P.fit_family("LOGREG", X[:1500], Xs[:1500], y[:1500], seed=11, budget=1)
        root = _env.Path(self.td.dir) / "models"
        man = {"model_id": "LM-T", "asset": "XAUUSD", "feature_set": P.FE.FEATURE_SET, "features": P.FE.FEATURES}
        p = P.save_artifact(root, f, man)
        g, _ = P.load_artifact(p, asset="XAUUSD", feature_set=P.FE.FEATURE_SET)
        np.testing.assert_allclose(g.predict(X[1500:], Xs[1500:]), f.predict(X[1500:], Xs[1500:]))   # reload == same outputs
        with self.assertRaises(P.ArtifactMismatch):
            P.load_artifact(p, asset="BTC", feature_set=P.FE.FEATURE_SET)                      # wrong asset blocks loading
        with self.assertRaises(P.ArtifactMismatch):
            P.load_artifact(p, asset="XAUUSD", feature_set="FS-9")
        (p / "model.pkl").write_bytes((p / "model.pkl").read_bytes() + b"x")
        with self.assertRaises(P.ArtifactMismatch):
            P.load_artifact(p, asset="XAUUSD", feature_set=P.FE.FEATURE_SET)

    def test_labels_conservative_and_mature(self):
        from masterquo.lab.features import triple_barrier
        bars = synth_bars(300, scale=2.0)
        lb = triple_barrier(bars, "M5", side="LONG", horizon=12, k_tp=1.0, k_sl=1.0, point=0.01)
        self.assertTrue((lb["y"][-12:] == -1).all())                                        # immature at the end -> no label
        cut = datetime(2026, 3, 2, 10, tzinfo=UTC).timestamp()
        lb2 = triple_barrier(bars, "M5", side="LONG", horizon=12, k_tp=1.0, k_sl=1.0, point=0.01, cutoff_t=cut)
        ok = lb2["y"] >= 0
        self.assertTrue((lb2["t_label_end"][ok] <= cut).all())
        amb = lb["ambiguous"] & (lb["y"] >= 0)
        self.assertTrue((lb["y"][amb] == 0).all())                                          # same-bar SL+TP -> SL first


# ------------------------------------------------------------------------------------------------ end-to-end XAUUSD and BTC
class TestEndToEnd(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_xauusd_then_btc(self):
        cfg, db, bus, log, fake, worker, b, reg = connected()
        try:
            from masterquo.lab.protocol import default_protocol
            from masterquo.lab.service import LabService
            lab = LabService(cfg, b, db, bus, log, reg)
            st = lab.tick(force=True)
            self.assertEqual((st["asset"], st["symbol"]), ("XAUUSD", "XAUUSD-"))
            self.assertEqual(st["model"]["status"], "no_model")                                 # explicit abstention: no artefact
            self.assertEqual(st["model"]["nn_status"], "INACTIVE")
            for s in st["scenarios"]:
                self.assertEqual(s["decision_role"], "shadow")
                self.assertNotIn("probability", s["checklist_completeness"])
            bars = [x for x in b.symbol_bars("XAUUSD-", "M5", 5000) if x["closed"] and x.get("open_utc")]
            r = lab.trainer.start("XAUUSD", bars, point=0.01, data_source="SYNTHETIC", instrument_id="XAUUSD:Synthetic:XAUUSD-",
                                  protocol=default_protocol("XAUUSD", families=("DUMMY", "LOGREG"), experiments=()), artifact_family="LOGREG")
            self.assertTrue(wait_for(lambda: lab.trainer.jobs[r["job_id"]]["status"] != "RUNNING", 300, 0.5))
            job = lab.trainer.jobs[r["job_id"]]
            self.assertEqual(job["status"], "COMPLETED", job.get("error"))
            st = lab.tick(force=True)
            m = st["model"]
            self.assertEqual(m["status"], "ready")
            self.assertEqual(m["role"], "fixture_only")                                         # synthetic data never a real model
            tel = m["telemetry"]
            self.assertEqual(tel["inference_id"], m["inference_id"])
            self.assertEqual(tel["trace_id"], st["trace_id"])
            self.assertTrue(any("SYNTETYCZNYCH" in w for w in tel["warnings"]))
            for s in st["scenarios"]:
                if s["model"] and s["model"].get("inference_id"):
                    self.assertEqual(s["model"]["inference_id"], tel["inference_id"])
            json.dumps(lab.public("XAUUSD"))
            # ---- BTC (symbol taken from the account automatically)
            reg.switch("BTC")
            b.state = "RECONNECTING"
            b.next_retry = 0
            self.assertTrue(wait_for(lambda: b.state == "CONNECTED" and b.buffer_symbol == "BTCUSD-" and bool(b.bars("M5", 5)), 60))
            st2 = lab.tick(force=True)
            self.assertEqual((st2["asset"], st2["symbol"]), ("BTC", "BTCUSD-"))
            self.assertIsNotNone(st2["modules"]["M5"].get("zscore"))
            self.assertNotEqual(st2["trace_id"], st["trace_id"])
            self.assertEqual(st2["model"]["status"], "no_model")                                 # XAUUSD model never used for BTC
            self.assertTrue(lab.public("XAUUSD")["stale"])                                     # other asset's state flagged
            self.assertTrue(all(z["asset"] == "BTC" for z in st2["zones"]))
            last_btc = [x for x in b.bars("M5", 3)][-1]["c"]
            self.assertGreater(last_btc, 10_000)                                               # BTC prices, not gold buffers
        finally:
            b.stop()
            worker.stop()


if __name__ == "__main__":
    unittest.main()
