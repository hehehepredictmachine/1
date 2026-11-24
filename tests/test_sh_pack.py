"""1.38 PMW-SH-PACK-2 - the 20 SH variants (PMW_SC01..SC10, PMW_HG01..HG10) on the existing SH runtime.

Catalog / units / two-target RR (the specification's examples) / every detector (BUY found on deterministic regime-switching data, the
mirrored series gives the explicit SELL with the mirrored stop, a flattened trigger bar is a near-miss, too little history is WARMING_UP,
future bars never change a past decision) / hedge policies (activation, unwind, timeout, one activation, no hedge at the stop, SELL mirror)
/ service flow (SIGNALS: no order, PAPER: planned absolute TP1/TP2 without BE, basket hedge with the ratio cap after TP1 and the unwind on
TP2, NETTING refuses the opposite leg) / plan contract PMW-PLAN-2 / replay on a synthetic export (always NOT_VALIDATED)."""
from __future__ import annotations

import json
import math
import random
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import _env  # noqa: F401
from _env import TempData
from test_sh_service import NOW, Base

from masterquo.sh.pack import catalog as CAT
from masterquo.sh.pack import detectors as D
from masterquo.sh.pack import features as F
from masterquo.sh.pack import policies as POL
from masterquo.sh.pack import replay as PR
from masterquo.sh.pack import solver as SV

T0 = 1762128000                       # Monday 2025-11-03 00:00 UTC


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")


def series(n=30000, seed=3, t0=T0):
    rnd = random.Random(seed)
    p, out, regime, drift, anchor = 3000.0, [], "range", 0.0, 3000.0
    for k in range(n):
        if k % 1500 == 0:
            regime = rnd.choice(["up", "down", "range", "up", "down"])
            drift, anchor = {"up": 0.06, "down": -0.06, "range": 0.0}[regime], p
        d = (-0.02 * (p - anchor) + rnd.gauss(0, 0.3)) if regime == "range" else drift + rnd.gauss(0, 0.3)
        o, c = p, p + d
        h, lo = max(o, c) + abs(rnd.gauss(0, 0.2)), min(o, c) - abs(rnd.gauss(0, 0.2))
        out.append({"open_utc": iso(t0 + 60 * k), "o": round(o, 2), "h": round(h, 2), "l": round(lo, 2), "c": round(c, 2), "tv": rnd.randint(20, 200),
                    "closed": True})
        p = c
    return out


def all_tfs(m1):
    b = {"M1": m1}
    for tf in ("M3", "M5", "M15", "H1"):
        b[tf] = PR.aggregate(m1, F.TF_S[tf])
    return b


def mirror(bars, k=6000.0):
    return {tf: [dict(x, o=round(k - x["o"], 2), h=round(k - x["l"], 2), l=round(k - x["h"], 2), c=round(k - x["c"], 2)) for x in rows]
            for tf, rows in bars.items()}


def ctx(bars, as_of, warm_mult=1):
    cfg = CAT.load()
    X = F.Context(bars, tick=0.01, common=dict(cfg["common"], warmup={"ema_mult": warm_mult}), as_of=as_of)
    X.advance(as_of)
    return X


class _Found:
    cache = None

    @classmethod
    def get(cls):
        """First BUY setup of every variant (its first signal TF) on the deterministic series - searched once for the module."""
        if cls.cache is None:
            m1 = series()
            bars = all_tfs(m1)
            cfg = CAT.load()
            X = ctx(bars, F.ts(m1[300]["open_utc"]))
            found = {}
            for j in range(300, len(m1) - 1):
                t = F.ts(m1[j]["open_utc"]) + 60
                X.advance(t)
                for vid in CAT.IDS:
                    v = cfg["variants"][vid]
                    tf = v["signal_tfs"][0]
                    if vid in found or int(t) % F.TF_S[tf]:
                        continue
                    d = D.detect(X, v, tf, "BUY")
                    if d.get("status") == "SETUP":
                        found[vid] = (t, tf, d)
                if len(found) == len(CAT.IDS):
                    break
            cls.cache = (bars, found, cfg)
        return cls.cache


class TestCatalog(unittest.TestCase):
    def test_exactly_ten_and_ten_unique_described(self):
        cfg = CAT.load()
        self.assertEqual(len(CAT.SC_IDS), 10)
        self.assertEqual(len(CAT.HG_IDS), 10)
        self.assertEqual(len(set(CAT.IDS)), 20)
        descs = {cfg["variants"][v]["description"] for v in CAT.IDS}
        self.assertEqual(len(descs), 20)
        self.assertTrue(all(cfg["variants"][v]["family"] == ("SCALPING" if v.startswith("PMW_SC") else "HEDGING") for v in CAT.IDS))
        self.assertEqual(cfg["errors"], [])
        # HG01 and HG10 deliberately share the detector and the setup group (not two independent votes)
        self.assertEqual(cfg["variants"]["PMW_HG01"]["detector"], cfg["variants"]["PMW_HG10"]["detector"])
        self.assertEqual(cfg["variants"]["PMW_HG01"]["setup_group_id"], cfg["variants"]["PMW_HG10"]["setup_group_id"])
        self.assertNotEqual(cfg["variants"]["PMW_HG01"]["management_policy_id"], cfg["variants"]["PMW_HG10"]["management_policy_id"])
        pub = CAT.public(cfg)
        self.assertEqual(pub["count"], 20)
        self.assertTrue(all(x["validation"]["status"] == "NOT_VALIDATED" for x in pub["items"]))

    def test_hash_changes_and_override_validation(self):
        td = TempData()
        self.addCleanup(td.close)
        if True:
            a = CAT.load()
            b = CAT.load({"variants": {"PMW_SC01": {"position_max_minutes": 25}}})
            self.assertNotEqual(a["variants"]["PMW_SC01"]["config_hash"], b["variants"]["PMW_SC01"]["config_hash"])
            self.assertEqual(a["variants"]["PMW_SC02"]["config_hash"], b["variants"]["PMW_SC02"]["config_hash"])
            with self.assertRaises(ValueError):
                CAT.save_override({"variants": {"PMW_HG01": {"hedge": {"ratio": 0.75}}}})          # never more than 0.50, no martingale
            with self.assertRaises(ValueError):
                CAT.save_override({"families": {"SCALPING": {"rr_min": 1.5}}})                    # below the specification
            with self.assertRaises(ValueError):
                CAT.save_override({"variants": {"PMW_SC01": {"signal_tfs": ["H1"]}}})              # TF not implemented for the variant
            with self.assertRaises(ValueError):
                CAT.save_override({"risk": {}})


class TestUnitsAndRR(unittest.TestCase):
    def test_pips_independent_of_digits(self):
        pip = CAT.load()["instruments"]["XAUUSD"]["pip_size"]
        self.assertAlmostEqual(25 * pip, 2.50)
        self.assertAlmostEqual(40 * pip, 4.00)

    def test_spec_examples(self):
        self.assertAlmostEqual(SV.rr_plan_net(2.5, 3.75, 1.25, 0.15, 0.15), (3.125 - 0.15) / (1.25 + 0.15))
        self.assertAlmostEqual(SV.rr_plan_net(2.5, 3.75, 1.25, 0.15, 0.15), 2.125)
        self.assertAlmostEqual(SV.rr_plan_net(4, 10, 2, 0.25, 0.25), 3.0)
        self.assertAlmostEqual(SV.rr_basket(4, 10, 2, 0.25, 0.30, 0.0), (7 - 0.25 - 0.30) / 2.25, places=6)
        self.assertLess(SV.rr_basket(4, 10, 2, 0.25, 0.30, 0.0), 3.0)
        self.assertAlmostEqual(SV.rr_basket(4, 10.6, 2, 0.25, 0.30, 0.0), 3.0, places=6)
        self.assertLess(SV.rr_plan_net(1.0, 2.0, 1.0, 0.0, 0.0), 2.0)       # TP1 1R + TP2 2R is not a weighted RR 2

    def _rules(self, fam):
        return CAT.load()["families"][fam]

    def test_solver_sc_and_hg_buy_and_sell_symmetry(self):
        r = self._rules("SCALPING")
        s = SV.solve(E=3000.0, S_raw=2998.753, tick=0.01, pip=0.10, rules=r, c=0.15)
        self.assertEqual(s["status"], "OK", s)
        self.assertAlmostEqual(s["sl"], 2998.75)                                # quantized OUTWARD (further), never shortened
        self.assertGreaterEqual(s["d1"], 2.5 - 1e-9)
        self.assertGreaterEqual(s["d2"], 3 * s["r"] - 1e-9)
        self.assertGreaterEqual(s["rr_plan_net"], 2.0)
        m = SV.solve(E=-3000.0, S_raw=-3001.247, tick=0.01, pip=0.10, rules=r, c=0.15)   # SELL (mirror view)
        self.assertAlmostEqual(-m["sl"], 3001.25)
        self.assertAlmostEqual(m["d2"], s["d2"])
        h = SV.solve(E=3000.0, S_raw=2998.0, tick=0.01, pip=0.10, rules=self._rules("HEDGING"), c=0.25, hedge_loss=0.3, hedging=True)
        self.assertEqual(h["status"], "OK")
        self.assertGreaterEqual(h["d1"], 4.0 - 1e-9)
        self.assertGreaterEqual(h["rr_basket_net_target"], 3.0)
        self.assertGreaterEqual(h["d2"], 5 * h["r"] - 1e-9)

    def test_refusals(self):
        r = self._rules("SCALPING")
        self.assertEqual(SV.solve(E=3000.0, S_raw=2998.0, tick=0.01, pip=0.1, rules=r, c=0.15, target_space=3002.0)["reason_code"], "TARGET_UNREACHABLE")
        self.assertEqual(SV.solve(E=3000.0, S_raw=2998.0, tick=0.01, pip=0.1, rules=r, c=0.15, reach=3.0)["reason_code"], "TARGET_UNREACHABLE")
        self.assertEqual(SV.solve(E=3000.0, S_raw=2999.0, tick=0.01, pip=0.1, rules=r, c=0.15, natural=[3001.0, 3004.0])["reason_code"],
                         "TARGET_UNREACHABLE")                                 # natural targets are never moved to fit
        self.assertEqual(SV.solve(E=3000.0, S_raw=2998.0, tick=0.01, pip=0.1, rules=self._rules("HEDGING"), c=0.2, hedge_loss=None,
                                  hedging=True)["reason_code"], "RR_NOT_ESTIMABLE")
        self.assertEqual(SV.solve(E=3000.0, S_raw=3000.5, tick=0.01, pip=0.1, rules=r, c=0.1)["reason_code"], "SL_INVALID")

    def test_tick_grids(self):
        r = self._rules("SCALPING")
        for tick in (0.01, 0.1):
            s = SV.solve(E=3000.0, S_raw=2998.77, tick=tick, pip=0.1, rules=r, c=0.1)
            for k in ("sl", "tp1", "tp2"):
                self.assertAlmostEqual(round(s[k] / tick) * tick, s[k], places=8)
            self.assertLessEqual(s["sl"], 2998.77)

    def test_costs_unknown_commission_is_a_scenario(self):
        c = SV.costs({"slippage_usd": 0.05, "commission_per_lot_side": None}, 100.0, CAT.load()["common"])
        self.assertEqual(c["cost_status"], "ESTIMATED_SCENARIO")
        self.assertGreater(c["commission_price_rt"], 0)
        k = SV.costs({"slippage_usd": 0.05, "commission_per_lot_side": 3.5}, 100.0, CAT.load()["common"])
        self.assertEqual((k["cost_status"], k["commission_price_rt"]), ("KNOWN", 0.07))
        self.assertIn("nie jest odejmowany drugi raz", k["spread_note"])


class TestDetectors(unittest.TestCase):
    def test_every_variant_buy_mirror_sell_nearmiss_warmup_causality(self):
        bars, found, cfg = _Found.get()
        missing = [v for v in CAT.IDS if v not in found]
        self.assertEqual(missing, [], f"brak setupu BUY dla {missing}")
        mbars = mirror(bars)
        for vid, (t, tf, d) in sorted(found.items()):
            with self.subTest(vid=vid):
                v = cfg["variants"][vid]
                # mirror: the explicit SELL version on the mirrored market, mirrored stop (view units: sl - 6000)
                ds = D.detect(ctx(mbars, t), v, tf, "SELL")
                self.assertEqual(ds["status"], "SETUP", (vid, ds.get("reason")))
                self.assertAlmostEqual(ds["sl"], d["sl"] - 6000.0, places=4)
                # causality: future bars present (Context advanced to t) == history cut at t
                cut = {k: [b for b in rows if F.ts(b["open_utc"]) + F.TF_S[k] <= t] for k, rows in bars.items()}
                dc = D.detect(ctx(cut, t), v, tf, "BUY")
                self.assertEqual((dc["status"], round(dc.get("sl") or 0, 6)), ("SETUP", round(d["sl"], 6)))
                # near-miss: the trigger bar flattened onto the previous close -> no setup
                nm = {k: [dict(b) for b in rows] for k, rows in cut.items()}
                last, prev = nm[tf][-1], nm[tf][-2]
                last.update(o=prev["c"], c=prev["c"], h=prev["c"], l=prev["c"])
                self.assertNotEqual(D.detect(ctx(nm, t), v, tf, "BUY")["status"], "SETUP", vid)
                # warm-up: a short history is WARMING_UP (never a signal)
                short = {k: rows[-30:] for k, rows in cut.items()}
                self.assertIn(D.detect(ctx(short, t), v, tf, "BUY")["status"], ("WARMING_UP", "NO_DATA"), vid)

    def test_full_warmup_rule_h1(self):
        bars, found, cfg = _Found.get()
        t, tf, _d = found["PMW_HG01"]
        d = D.detect(ctx(bars, t, warm_mult=5), cfg["variants"]["PMW_HG01"], tf, "BUY")
        self.assertEqual(d["status"], "WARMING_UP")                              # H1 EMA200 x 5 = 1000 closed H1 bars required
        self.assertIn("5 × najdłuższa EMA", json.dumps(d["checklist"], ensure_ascii=False))

    def test_engine_plan_contract_and_idempotent_id(self):
        from masterquo.sh.pack.engine import PackEngine
        from masterquo.sh.units import SymbolSpec
        bars, found, cfg = _Found.get()
        spec = SymbolSpec("XAUUSD-", 0.01, 1.0, 100, 0.01, 0.01, 50, 2, "USD", point=0.01)
        cm = dict(cfg["common"], warmup={"ema_mult": 1})
        cfg2 = dict(cfg, common=cm)
        got = 0
        for vid, (t, tf, d) in sorted(found.items()):
            X = ctx(bars, t)
            v = cfg["variants"][vid]
            last = X.tf(tf, False)
            c = last.c[last.n - 1]
            q = {"bid": c, "ask": c + 0.2, "spread": 0.2, "age_s": 0.3}
            e = PackEngine()
            su = e._plan(X, v, tf, "BUY", d, "XAUUSD", spec, {"slippage_usd": 0.05}, q, t, cfg["instruments"]["XAUUSD"], cfg2, 100.0, "USD")
            su2 = PackEngine()._plan(X, v, tf, "BUY", d, "XAUUSD", spec, {"slippage_usd": 0.05}, q, t + 30, cfg["instruments"]["XAUUSD"], cfg2, 100.0, "USD")
            self.assertEqual(su["signal_id"], su2["signal_id"])                 # a refresh never creates a new id
            p = su["pack"]
            self.assertEqual(p["contract"], "PMW-PLAN-2")
            self.assertIsNone(p["models"]["p_tp2_before_sl"])                  # no calibrated event model -> null, not 0 / 80 %
            if su["status"] == "READY":
                got += 1
                self.assertEqual([x["name"] for x in su["tps"]], ["TP1", "TP2"])
                ec = p["economics"]
                rr = ec["rr_basket_net_target"] if v["family"] == "HEDGING" else ec["rr_plan_net"]
                self.assertGreaterEqual(rr, v["rules"]["rr_min"] - 1e-6)
                self.assertGreaterEqual(su["tps"][0]["distance_pips"], v["rules"]["tp1_min_pips"] - 1e-6)
                self.assertFalse(p["ready_to_execute"])                         # commission unknown -> not READY_TO_EXECUTE
                from masterquo.plans import contract as PC
                view = PC.from_pack(su, now=t)
                self.assertEqual(view["contract"], "PMW-PLAN-2")
                self.assertEqual({x["name"] for x in view["levels"]} & {"TP3"}, set())
                self.assertEqual(view["arrow"]["kind"], "CONFIRMED")
                self.assertEqual(len({x["key"] for x in view["levels"]}), len(view["levels"]))
            else:
                self.assertIn(su["status"], ("NO_TRADE", "WAIT", "INVALIDATED"))
                self.assertTrue(su["status_reason"])
        self.assertGreater(got, 0)


def m5bars(closes, t0, base=3000.0):
    out = []
    for k, c in enumerate(closes):
        o = closes[k - 1] if k else base
        out.append({"open_utc": iso(t0 + 300 * k), "o": o, "h": max(o, c) + 0.1, "l": min(o, c) - 0.1, "c": c, "tv": 50, "closed": True})
    return out


class TestPolicies(unittest.TestCase):
    def _plan(self, vid="PMW_HG03"):
        cfg = CAT.load()
        v = cfg["variants"][vid]
        return {"pack": {"hedge": v["hedge"], "params": v["params"], "economics": {"c_round_trip": 0.2}}}

    def test_midchannel_activation_unwind_timeout_and_limits(self):
        t0 = T0
        base = [3000.0] * 30
        st = {"mid": 2997.0}
        prim = {"side": "BUY", "entry": 3000.0, "sl": 2990.0, "remaining": 1.0, "volume": 1.0, "opened_at": t0 + 300 * 30}
        cm = CAT.load()["common"]
        bars = m5bars(base + [2996.0, 2995.5], t0)
        dec = POL.decision("PMW_HG03", plan=self._plan(), st=st, pstate={}, m5_bars=bars, h1_bars=[], quote={"bid": 2995.5, "ask": 2995.7},
                           now=t0 + 300 * 32, primary=prim, hedged=False, hedge_opened_at=None, activations=0, tick=0.01, common=cm)
        self.assertEqual((dec["decision"], dec["ratio"]), ("HEDGE", 0.25))
        dec = POL.decision("PMW_HG03", plan=self._plan(), st=st, pstate={}, m5_bars=bars, h1_bars=[], quote={"bid": 2995.5, "ask": 2995.7},
                           now=t0 + 300 * 32, primary=prim, hedged=False, hedge_opened_at=None, activations=1, tick=0.01, common=cm)
        self.assertEqual(dec["decision"], "HOLD")                              # one activation in the life of the basket
        dec = POL.decision("PMW_HG03", plan=self._plan(), st=st, pstate={}, m5_bars=bars, h1_bars=[], quote={"bid": 2989.0, "ask": 2989.2},
                           now=t0 + 300 * 32, primary=prim, hedged=False, hedge_opened_at=None, activations=0, tick=0.01, common=cm)
        self.assertEqual(dec["decision"], "HOLD")                              # at / beyond the stop: never a hedge
        up = m5bars(base + [2996.0, 2995.5, 2998.5, 2999.0], t0)
        dec = POL.decision("PMW_HG03", plan=self._plan(), st=st, pstate={}, m5_bars=up, h1_bars=[], quote={"bid": 2999.0, "ask": 2999.2},
                           now=t0 + 300 * 34, primary=prim, hedged=True, hedge_opened_at=t0 + 300 * 32, activations=1, tick=0.01, common=cm)
        self.assertEqual(dec["decision"], "UNWIND")
        dec = POL.decision("PMW_HG03", plan=self._plan(), st=st, pstate={}, m5_bars=bars, h1_bars=[], quote={"bid": 2995.5, "ask": 2995.7},
                           now=t0 + 300 * 32 + 46 * 60, primary=prim, hedged=True, hedge_opened_at=t0 + 300 * 32, activations=1, tick=0.01, common=cm)
        self.assertEqual(dec["decision"], "EXIT")                              # hedge timeout without the return condition: whole basket

    def test_sell_base_is_mirrored(self):
        t0 = T0
        st = {"mid": -3003.0}                                                 # view units of a SELL base (mirrored): real mid 3003
        prim = {"side": "SELL", "entry": 3000.0, "sl": 3010.0, "remaining": 1.0, "volume": 1.0, "opened_at": t0 + 300 * 30}
        bars = m5bars([3000.0] * 30 + [3004.0, 3004.5], t0)
        dec = POL.decision("PMW_HG03", plan=self._plan(), st=st, pstate={}, m5_bars=bars, h1_bars=[], quote={"bid": 3004.3, "ask": 3004.5},
                           now=t0 + 300 * 32, primary=prim, hedged=False, hedge_opened_at=None, activations=0, tick=0.01, common=CAT.load()["common"])
        self.assertEqual(dec["decision"], "HEDGE")

    def test_every_policy_has_text_and_a_bound(self):
        fam = CAT.load()["families"]["HEDGING"]
        for vid in CAT.HG_IDS:
            self.assertTrue(POL.texts(vid)["activation_condition"] and POL.texts(vid)["unwind_condition"])
            st = {"L": 2999.0, "mid": 2998.0, "or_high": 3000.5, "or_mid": 2999.5, "break_level": 2999.5, "VAL": 2999.0}
            hl, how = POL.hedge_loss_bound(vid, st, r=2.0, b5=0.1, c=0.2, ratio=0.5, hcfg=CAT.load()["variants"][vid]["hedge"], fam=fam)
            self.assertIsNotNone(hl, vid)
            self.assertGreater(hl, 0)
        self.assertIsNone(POL.hedge_loss_bound("PMW_HG09", {}, r=2.0, b5=0.1, c=0.2, ratio=0.5, hcfg={}, fam=fam)[0])


def pack_su(spec, vid="PMW_SC01", side="BUY", ref=2000.2, sl=1999.0, now=NOW):
    cfg = CAT.load()
    v = cfg["variants"][vid]
    hg = v["family"] == "HEDGING"
    d1, d2 = (4.0, 8.0) if hg else (2.5, 4.0)
    sg = 1 if side == "BUY" else -1
    tps = [{"name": "TP1", "price": round(ref + sg * d1, 2), "share": 0.5, "distance_requested": d1, "distance_actual": d1, "distance_pips": d1 * 10},
           {"name": "TP2", "price": round(ref + sg * d2, 2), "share": 0.5, "distance_requested": d2, "distance_actual": d2, "distance_pips": d2 * 10}]
    return {"signal_id": f"SH-{abs(hash((vid, side, ref))) % 10 ** 14:014x}"[:17], "strategy": v["family"], "strategy_id": vid, "instrument": "XAUUSD",
            "symbol": spec.symbol, "side": side, "status": "READY", "status_reason": "test", "entry_ref": ref, "sl": sl, "invalidation": sl, "tps": tps,
            "shares": [0.5, 0.5], "be": None, "costs": {"round_trip_price": 0.2, "commission_known": False}, "net_rr": 3.2,
            "horizon_minutes": v["position_max_minutes"], "position_max_minutes": v["position_max_minutes"], "valid_until": now + 600,
            "model_mode": "OGRANICZONA", "probability": {"status": "BRAK_MODELU_ZDARZENIA"}, "score": {"value": 90}, "created_at": now,
            "config_hash": v["config_hash"], "setup_version": v["strategy_version"], "checklist": [],
            "pack": {"contract": "PMW-PLAN-2", "strategy_id": vid, "family": v["family"], "cluster": v["cluster"], "setup_group_id": v["setup_group_id"],
                     "signal_tf": v["signal_tfs"][0], "context_tfs": v["context_tfs"], "management_policy_id": v["management_policy_id"],
                     "strategy_version": v["strategy_version"], "config_hash": v["config_hash"], "structure_view": {"mid": 1999.5}, "params": v["params"],
                     "economics": {"c_round_trip": 0.2, "hedge_loss_bound_price": 0.15 if hg else None, "cost_status": "ESTIMATED_SCENARIO"},
                     "hedge": {"policy_id": v["management_policy_id"]} if hg else None, "analytical_state": "READY", "reason_code": "OK"}}


class TestPlanContractAll(unittest.TestCase):
    def test_every_id_draws_entry_sl_tp1_tp2_and_an_arrow(self):
        from masterquo.plans import contract as PC
        from masterquo.sh.units import SymbolSpec
        spec = SymbolSpec("XAUUSD-", 0.01, 1.0, 100, 0.01, 0.01, 50, 2, "USD", point=0.01)
        for vid in CAT.IDS:
            for side in ("BUY", "SELL"):
                su = pack_su(spec, vid, side, ref=3000.0, sl=2998.8 if side == "BUY" else 3001.2)
                su["pack"]["arrow"] = {"time": iso(T0 + 600), "side": side, "label": f"{vid} / M5", "position": "belowBar" if side == "BUY" else "aboveBar"}
                v = PC.from_pack(su, now=NOW)
                names = [x["name"] for x in v["levels"]]
                self.assertEqual(sorted(names), sorted(["ENTRY", "SL", "TP1", "TP2"]), (vid, side, names))
                self.assertEqual(v["arrow"]["kind"], "CONFIRMED")
                self.assertEqual(v["arrow"]["position"], "belowBar" if side == "BUY" else "aboveBar")
                self.assertEqual(v["strategy_id"], vid)
                wait = PC.from_pack(dict(su, status="WAIT", pack=dict(su["pack"], analytical_state="WAIT")), now=NOW)
                self.assertEqual(wait["arrow"]["kind"], "WATCH")                          # WAIT never looks like an entry signal


class TestServicePaper(Base):
    mode = "PAPER"

    def setUp(self):
        super().setUp()
        from masterquo.sh.pack.engine import PackEngine
        self.svc.pack = PackEngine()

    def open_pack(self, vid="PMW_SC01", volume=0.2, side="BUY"):
        q = self.q()
        ref = q["ask"] if side == "BUY" else q["bid"]
        su = pack_su(self.spec, vid, side, ref=ref, sl=round(ref - 1.2, 2) if side == "BUY" else round(ref + 1.2, 2), now=self.t)
        risk = {"volume": volume, "legs": self.spec.split(volume, [0.5, 0.5])["legs"], "shares_used": {"variant": "PRIMARY", "shares": [0.5, 0.5]},
                "risk_money": 30.0, "basket_loss_limit_money": 60.0}
        return self.svc.open_plan(self.ex, su, risk, self.spec, q, self.mode, self.t, self.shc, "XAUUSD", {"vol": {"atr_m5": 1.0}}), su

    def test_two_planned_targets_no_be(self):
        r, su = self.open_pack()
        self.assertEqual(r["status"], "OPEN", r)
        row = self.row()
        self.assertEqual((row["strategy"], row["strategy_id"], row["signal_tf"]), ("SCALPING", "PMW_SC01", "M1"))
        pos = row["fsm_obj"]
        self.assertEqual([lg.name for lg in pos.legs], ["TP1", "TP2"])
        self.assertEqual([lg.price for lg in pos.legs], [t["price"] for t in su["tps"]])     # planned absolute levels kept
        self.assertEqual([lg.volume for lg in pos.legs], [0.1, 0.1])
        ev = [e["kind"] for e in self.svc.store.events(row["plan_id"])]
        self.assertIn("FILL_DEVIATION", ev)
        row = self.step(su["tps"][0]["price"] + 0.01)
        self.assertEqual(row["fsm_obj"].legs[0].status, "DONE")
        self.assertEqual(row["fsm_obj"].be_status, "NOT_REQUESTED")
        row = self.step(su["tps"][1]["price"] + 0.01)
        self.assertEqual(row["state"], "CLOSED")
        self.assertEqual(row["fsm_obj"].be_status, "NOT_REQUESTED")                     # no BE in the new profiles (no runner left)
        self.assertIsNotNone(row["result"]["r_multiple"])

    def test_slippage_breaking_the_plan_aborts(self):
        q = self.q(2000.0)
        su = pack_su(self.spec, "PMW_SC01", "BUY", ref=1998.0, sl=1997.9, now=self.t)       # quote ran away: fill far from the plan
        risk = {"volume": 0.2, "legs": [0.1, 0.1], "shares_used": {"variant": "PRIMARY", "shares": [0.5, 0.5]}, "risk_money": 30.0}
        r = self.svc.open_plan(self.ex, su, risk, self.spec, q, self.mode, self.t, self.shc, "XAUUSD", {})
        self.assertEqual(r["status"], "ABORTED")

    def test_hedge_basket_cap_after_tp1_and_unwind_on_tp2(self):
        from unittest import mock
        r, su = self.open_pack("PMW_HG03", volume=0.4)
        self.assertEqual(r["status"], "OPEN", r)
        row = self.row()
        from masterquo.sh.hedge_fsm import Basket
        self.assertIsInstance(row["fsm_obj"], Basket)
        fill = row["fsm_obj"].primary.entry
        with mock.patch("masterquo.sh.pack.policies.decision", return_value={"decision": "HEDGE", "reason": "test", "ratio": 0.5}):
            row = self.step(fill - 0.5)
        b = row["fsm_obj"]
        self.assertEqual((b.state, b.hedge.volume, b.activations), ("HEDGED", 0.2, 1))
        with mock.patch("masterquo.sh.pack.policies.decision", return_value={"decision": "HOLD", "reason": "test"}):
            row = self.step(su["tps"][0]["price"] + 0.01)                                  # TP1: base 0.4 -> 0.2, hedge cap 0.5 x 0.2 = 0.1
            row = self.step(su["tps"][0]["price"] + 0.02)
        b = row["fsm_obj"]
        self.assertAlmostEqual(b.primary.remaining, 0.2)
        self.assertLessEqual(b.hedge.volume, 0.1 + 1e-9)
        with mock.patch("masterquo.sh.pack.policies.decision", return_value={"decision": "HOLD", "reason": "test"}):
            row = self.step(su["tps"][1]["price"] + 0.01)
            row = self.step(su["tps"][1]["price"] + 0.02)
        self.assertEqual(row["state"], "CLOSED")
        self.assertNotEqual(row["fsm_obj"].hedge.status, "OPEN")                           # no lone opposite leg after TP2
        self.assertEqual(row["fsm_obj"].activations, 1)


class TestServiceNetting(Base):
    mode = "PAPER"
    margin_mode = "NETTING"

    def test_no_opposite_leg_on_netting(self):
        from unittest import mock
        from masterquo.sh.pack.engine import PackEngine
        self.svc.pack = PackEngine()
        q = self.q()
        su = pack_su(self.spec, "PMW_HG03", "BUY", ref=q["ask"], sl=round(q["ask"] - 1.2, 2), now=self.t)
        risk = {"volume": 0.4, "legs": [0.2, 0.2], "shares_used": {"variant": "PRIMARY", "shares": [0.5, 0.5]}, "risk_money": 30.0,
                "basket_loss_limit_money": 60.0}
        self.svc.open_plan(self.ex, su, risk, self.spec, q, self.mode, self.t, self.shc, "XAUUSD", {})
        with mock.patch("masterquo.sh.pack.policies.decision", return_value={"decision": "HEDGE", "reason": "test", "ratio": 0.5}):
            row = self.step(q["bid"] - 0.4)
        b = row["fsm_obj"]
        self.assertIsNone(b.hedge)
        self.assertEqual(b.activations, 1)                                                 # consumed, never retried
        self.assertIn("HEDGE_REFUSED", [e["kind"] for e in self.svc.store.events(row["plan_id"])])


class TestServiceSignals(Base):
    mode = "SIGNALS"

    def test_signals_mode_never_opens_and_history_has_variant(self):
        from unittest import mock
        from masterquo.sh.pack.engine import PackEngine
        self.svc.pack = PackEngine()
        q = self.q()
        su = pack_su(self.spec, "PMW_SC02", "BUY", ref=q["ask"], sl=round(q["ask"] - 1.2, 2), now=self.t)
        with mock.patch.object(self.svc, "pack_cycle", return_value=[su]), mock.patch.object(self.svc, "open_plan") as op:
            self.svc.cycle("XAUUSD", {"M1": [], "M5": [], "M15": [], "H1": []}, q, self.spec, self.svc.account(), "SIGNALS", self.t, self.shc, self.ex,
                           entry_block=[])
            op.assert_not_called()
        rows = self.svc.store.recent_signals(strategy_id="PMW_SC02")
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["strategy"], rows[0]["strategy_id"], rows[0]["status"]), ("SCALPING", "PMW_SC02", "READY"))
        self.assertEqual(self.db.query("SELECT COUNT(*) AS n FROM sh_plans")[0]["n"], 0)
        legacy = self.svc.store.recent_signals(strategy_id="LEGACY_SCALPING")
        self.assertTrue(all(r["strategy_id"] == "LEGACY_SCALPING" for r in legacy))


class TestArbitration(unittest.TestCase):
    def test_one_entry_per_exposure_and_conflicting_sides_wait(self):
        from masterquo.sh.coordinator import arbitrate
        cfg = {"priority": ["HEDGING", "SCALPING"]}
        a = {"signal_id": "A", "strategy": "SCALPING", "strategy_id": "PMW_SC01", "side": "BUY", "net_rr": 2.4, "pack": {"cluster": "TREND_PULLBACK"}}
        b = {"signal_id": "B", "strategy": "SCALPING", "strategy_id": "PMW_SC08", "side": "BUY", "net_rr": 2.9, "pack": {"cluster": "TREND_PULLBACK"}}
        out = {d["signal_id"]: d for d in arbitrate([b, a], open_plans=[], foreign_positions=0, cfg=cfg, symbol="X")}
        self.assertEqual(sum(1 for d in out.values() if d["decision"] == "PROCEED"), 1)
        self.assertEqual(out["B"]["decision"], "PROCEED")                                   # same cluster: higher net RR, then the id
        c = dict(a, signal_id="C", side="SELL")
        out = arbitrate([a, c], open_plans=[], foreign_positions=0, cfg=cfg, symbol="X")
        self.assertTrue(all(d["decision"] == "WAIT" for d in out))


class TestReplay(unittest.TestCase):
    def test_synthetic_export_is_never_validated(self):
        td = TempData()
        self.addCleanup(td.close)
        if True:
            d = Path(tempfile.mkdtemp(prefix="pack_ds_"))
            m1 = series(6000, seed=5)
            (d / "source_metadata.json").write_text(json.dumps({"instrument": "XAUUSD", "file_prefix": "XAUUSD", "data_kind": "SYNTHETIC_TEST",
                                                                "spec": {"point": 0.01, "trade_tick_size": 0.01}}), encoding="utf-8")
            with (d / "XAUUSD_M1.csv").open("w", encoding="utf-8") as fh:
                fh.write("time_open_utc,open,high,low,close,tick_volume,spread_points\n")
                for b in m1:
                    fh.write(f"{b['open_utc']},{b['o']},{b['h']},{b['l']},{b['c']},{b['tv']},20\n")
            bars, meta = PR.load(d)
            self.assertEqual(meta["tf_sources"]["M3"], "RESAMPLED_FROM_M1")
            rep = PR.run(bars, meta, variants=["PMW_SC04", "PMW_SC05", "PMW_HG03"], warm_m1=600)
            self.assertTrue(all(v["verdict"] == "NOT_VALIDATED" for v in rep["variants"].values()))
            self.assertIn("PMW_HG03|M15", rep["variants"])
            self.assertIn("modes", rep["variants"]["PMW_HG03|M15"])
            w = PR.write(rep)
            self.assertEqual(w["variant_files"], [])                                       # synthetic -> no per-variant validation file
            self.assertEqual(CAT.validation_status("PMW_SC04")["status"], "NOT_VALIDATED")

    def test_m3_resampling_needs_complete_triples(self):
        m1 = series(9, seed=1)
        del m1[4]                                                                          # one missing minute
        m3 = PR.aggregate(m1, 180)
        self.assertEqual(len(m3), 2)                                                       # the incomplete triple is dropped, never padded

    def test_stop_first_on_ambiguous_bar(self):
        m1 = [{"open_utc": iso(T0 + 60 * k), "o": 3000.0, "h": 3000.1, "l": 2999.9, "c": 3000.0, "spread_price": 0.2} for k in range(3)]
        m1.append({"open_utc": iso(T0 + 180), "o": 3000.0, "h": 3010.0, "l": 2990.0, "c": 3000.0, "spread_price": 0.2})
        su = {"side": "BUY", "sl": 2998.0, "entry_ref": 3000.2, "tps": [{"price": 3003.0}, {"price": 3006.0}], "strategy_id": "PMW_SC01",
              "pack": {"economics": {}}}
        r = PR.simulate(m1, 1, su, spread_fb=0.2, slip=0.0, c_rt=0.1, max_minutes=30)
        self.assertTrue(r["ambiguous"])
        self.assertEqual(r["end"], "SL")


if __name__ == "__main__":
    unittest.main()


class TestGarchHG09(unittest.TestCase):
    """1.39: HG09 with volatility_method VOL_GARCH uses the ACTIVE trained GARCH(1,1) (family VOL_GARCH) - same filter, frozen params."""

    def test_filter_equals_family_forecast(self):
        import numpy as np
        from masterquo.modelhub.families import garch as G
        m1 = series(4000, seed=9)
        m5 = PR.aggregate(m1, 300)
        v = F.TF("M5", m5)
        om, al, be = 0.002, 0.08, 0.9
        g = v.garch_sigma(om, al, be)
        c = np.array([b["c"] for b in m5])
        r = np.diff(np.log(c)) * 100.0
        vf = G.garch_filter(r, om, al, be)
        nxt = om + al * r[-1] ** 2 + be * vf[-1]
        self.assertAlmostEqual(g[-1], math.sqrt(nxt) / 100.0, places=12)
        cut = F.TF("M5", m5[:500])                                       # causal: a longer history never changes an earlier value
        self.assertAlmostEqual(cut.garch_sigma(om, al, be)[499], g[499], places=12)
        self.assertEqual(F.TF("M5", m5, mirror=True).garch_sigma(om, al, be)[-1], g[-1])     # SELL view: same returns

    def test_no_silent_fallback_and_config_validation(self):
        bars, found, cfg = _Found.get()
        t, tf, d = found["PMW_HG09"]
        v = dict(cfg["variants"]["PMW_HG09"], params=dict(cfg["variants"]["PMW_HG09"]["params"], volatility_method="VOL_GARCH"))
        X = ctx(bars, t)
        dn = D.detect(X, v, tf, "BUY")
        self.assertEqual((dn["status"], dn["reason_code"]), ("NO_DATA", "GARCH_NOT_READY"))
        X.garch = {"status": "CANDIDATE"}
        self.assertEqual(D.detect(X, v, tf, "BUY")["reason_code"], "GARCH_NOT_READY")
        X.garch = {"status": "READY", "omega": 0.002, "alpha": 0.08, "beta": 0.9, "run_id": "R1"}
        dg = D.detect(X, v, tf, "BUY")
        self.assertIn(dg["status"], ("SETUP", "NO_SETUP"))
        if dg["status"] == "SETUP":
            self.assertEqual(dg["structure"]["sigma_method"], "VOL_GARCH")
            self.assertEqual(dg["structure"]["garch"]["run_id"], "R1")
        self.assertIn("volatility_method", " ".join(CAT.load({"variants": {"PMW_HG09": {"params": {"volatility_method": "EGARCH"}}}})["errors"]))

    def test_service_reads_only_an_approved_active_artifact(self):
        from masterquo.sh.service import SHService

        class Fam:
            def __init__(self, st):
                self.st = st

            def status(self, fid, inst):
                return self.st

            def _artifact(self, fid, inst, rid):
                return {"omega": 0.01, "alpha": 0.05, "beta": 0.9, "dist": "t"}
        s = SHService.__new__(SHService)
        s.families = Fam({"artifact": "CANDIDATE", "active_run": "R1"})
        self.assertEqual(s.garch_artifact("XAUUSD")["status"], "CANDIDATE")
        s.families = Fam({"artifact": "APPROVED", "active_run": "R2"})
        g = s.garch_artifact("XAUUSD")
        self.assertEqual((g["status"], g["run_id"], g["alpha"]), ("READY", "R2", 0.05))
