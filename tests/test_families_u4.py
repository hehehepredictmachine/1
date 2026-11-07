"""1.33 U4 - model families (PMW-FAM-1): train -> save -> load -> predict for every family on controlled synthetic data, contract
validity, three state axes, roles (ASSIST needs APPROVED + REAL data), integrity, receivers (ASSIST hold changes the SH setup, SHADOW
does not), RL replay timing / costs, no look-ahead of the breakout channel, pair / basket blocking, NLP corpus, isolated deep worker."""
import json
import math
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

import _env  # noqa: F401

SP = Path("/tmp/claude-0/-home-user-1/8bce07ae-728e-58d9-ad38-3f74986983fd/scratchpad")
DEEP_PY = os.environ.get("MQ_DEEP_PYTHON") or str(SP / "venv_kronos" / "bin" / "python")
T0 = 1_772_409_600  # 2026-03-02 00:00 UTC


def synth(n=4000, tf_s=300, seed=1, phi=0.25, drift=0.0, garch=True, start=2000.0):
    rng = np.random.default_rng(seed)
    r, v, out, c = 0.0, 1e-6, [], start
    for i in range(n):
        if garch:
            v = 2e-8 + 0.08 * r * r + 0.9 * v
        else:
            v = 1e-6
        r = phi * r + math.sqrt(v) * rng.standard_normal() + drift
        o = c
        c = c * math.exp(r)
        h, l = max(o, c) * (1 + abs(rng.normal(0, 2e-4))), min(o, c) * (1 - abs(rng.normal(0, 2e-4)))
        out.append({"t": T0 + i * tf_s, "o": o, "h": h, "l": l, "c": c, "tv": int(50 + rng.integers(0, 50)), "spread": 20})
    return out


def data_for(bars, inst="XAUUSD", kind="REAL"):
    return {"instrument": inst, "point": 0.01, "data_kind": kind, "symbol": "XAUUSD-", "bars": bars}


class Base(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="fam_")
        from masterquo.modelhub.families import base as B
        self.B = B
        self.store = B.Store(Path(self.td))

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def train(self, fid, data, profile="smoke", cfg=None):
        from masterquo.modelhub.families import run as RUN
        return RUN.train(fid, data.get("instrument", "XAUUSD"), profile, cfg or {}, data=data, store=self.store)

    def svc(self, cfg_over=None):
        from masterquo.config import ConfigStore
        from masterquo.modelhub.families.service import FamilyService
        cs = ConfigStore()
        if cfg_over:
            cs.update(cfg_over)
        return FamilyService(cs, None, store=self.store)

    def roundtrip(self, fid, data, live, **kw):
        r = self.train(fid, data, **kw)
        self.assertEqual(r["state"], "DONE", r)
        s = self.svc()
        a = s.activate(fid, "XAUUSD", r["run_id"])
        self.assertTrue(a["ok"], a)
        f = s.fams[fid]
        art = f.load(self.store.run_dir(fid, "XAUUSD", r["run_id"]))
        res = f.predict(art, live)
        p = f.pred(inst="XAUUSD", symbol="XAUUSD-", state="READY", result=res, run_id=r["run_id"], data_kind="REAL",
                   data_time=float(live["bars"][-1]["t"]))
        from masterquo.modelhub import contract as MC
        MC.validate(p)
        json.dumps(p, allow_nan=False, default=str)
        return r, res, a


class TestStatisticalFamilies(Base):
    def test_arima_recovers_ar_structure_and_roundtrip(self):
        bars = synth(2500, phi=0.4, garch=False, seed=3)
        r, res, a = self.roundtrip("TS_ARIMA", data_for(bars), {"bars": bars})
        m = self.store.runs("TS_ARIMA", "XAUUSD")[-1]
        self.assertTrue(a["sample_check"]["checked"])
        self.assertLessEqual(a["sample_check"]["max_abs_diff"], 1e-8)
        ch = m["metrics"]["chosen"]
        self.assertGreaterEqual(ch["order"][0] + ch["order"][2], 1)               # an AR / MA term is found on AR(1) data
        self.assertEqual(m["validation"]["status"], "APPROVED")                    # beats zero return on development
        self.assertLess(res["lo"], res["mean"])
        self.assertLess(res["mean"], res["hi"])
        self.assertEqual(set(res["horizons"]), {"1", "3", "5"})

    def test_sarimax_calendar_exog_known_in_advance(self):
        bars = synth(900, tf_s=3600, phi=0.1, garch=False, seed=4)
        r, res, _ = self.roundtrip("TS_SARIMAX", data_for(bars), {"bars": bars})
        self.assertEqual(res["exog_scenario"], "CALENDAR_KNOWN")
        from masterquo.modelhub.families import arima
        X = arima.calendar_exog(np.asarray([T0 + 9 * 3600.0]), "LAB_XAU_REFERENCE_V1")
        self.assertEqual(X.shape, (1, 5))                                          # 3 sessions + sin/cos

    def test_garch_scale_and_persistence(self):
        bars = synth(3000, seed=5)
        r, res, a = self.roundtrip("VOL_GARCH", data_for(bars), {"bars": bars})
        m = self.store.runs("VOL_GARCH", "XAUUSD")[-1]
        pick = next(c for c in m["metrics"]["candidates"] if c["dist"] == m["metrics"]["chosen_dist"])
        self.assertLess(pick["persistence"], 1.0)
        self.assertEqual(res["scale"], "decimal")
        hz = res["horizons"]
        self.assertAlmostEqual(hz["12"]["sigma"], math.sqrt(hz["12"]["variance"]), places=12)
        self.assertGreater(hz["12"]["variance"], hz["1"]["variance"])
        self.assertAlmostEqual(res["price_move_1sigma"], bars[-1]["c"] * res["sigma"], places=6)
        self.assertLess(res["sigma_bar"], 0.05)                                    # decimal, not percent

    def test_kalman_level_slope_causal(self):
        bars = synth(1500, drift=2e-4, garch=False, phi=0.0, seed=6)
        r, res, _ = self.roundtrip("KALMAN_LS", data_for(bars), {"bars": bars})
        self.assertGreater(res["slope"], 0)
        self.assertIn(res["state"], ("UP", "FLAT", "DOWN"))
        from masterquo.modelhub.families import kalman_ls as K
        y = np.asarray([b["c"] for b in bars[:300]])
        a, _, _ = K.run(y, 1e-2, 1e-5, 1e-1)
        b2, _, _ = K.run(np.concatenate([y, y[-50:] * 1.1]), 1e-2, 1e-5, 1e-1)
        self.assertTrue(np.allclose(a, b2[:300]))                                 # future values never change past states

    def test_breakout_channel_excludes_current_bar_and_no_lookahead(self):
        from masterquo.modelhub.families import breakout as BO
        bars = synth(800, seed=7)
        ev = BO.scan(bars[:600], 20, 3.0)
        ev2 = BO.scan(bars[:600] + [dict(b, c=b["c"] * 1.2, h=b["h"] * 1.2) for b in bars[600:]], 20, 3.0)
        first = [(e["i"], e["dir"], e["edge"]) for e in ev]
        self.assertEqual(first, [(e["i"], e["dir"], e["edge"]) for e in ev2[:len(ev)]])
        for e in ev:
            hi = max(b["h"] for b in bars[e["i"] - 20:e["i"]])
            lo = min(b["l"] for b in bars[e["i"] - 20:e["i"]])
            self.assertAlmostEqual(e["edge"], hi if e["dir"] == "UP" else lo)
        r, res, _ = self.roundtrip("BREAKOUT", data_for(synth(3000, seed=8)), {"bars": synth(3000, seed=8)})
        self.assertIn("state", res)


class TestPairsMicroNLP(Base):
    def test_pair_cointegrated_vs_not_and_leg_conversion(self):
        from masterquo.modelhub.families import pairs as PR
        rng = np.random.default_rng(1)
        x = np.cumsum(rng.normal(0, 0.01, 1200)) + 7.0
        y = 0.5 + 0.8 * x + rng.normal(0, 0.003, 1200)
        A = [{"t": T0 + i * 3600, "c": float(np.exp(y[i]))} for i in range(1200)]
        Bb = [{"t": T0 + i * 3600, "c": float(np.exp(x[i]))} for i in range(1200)]
        r = self.train("PAIR_COINT", {"instrument": "XAUUSD", "pair": ["XAUUSD", "BTC"], "pair_bars": [A, Bb], "data_kind": "REAL"})
        self.assertEqual(r["state"], "DONE", r)
        m = self.store.runs("PAIR_COINT", "XAUUSD")[-1]
        self.assertEqual(m["validation"]["status"], "APPROVED")
        self.assertAlmostEqual(m["metrics"]["p_value_train"] < 0.05, True)
        rw = [{"t": T0 + i * 3600, "c": float(np.exp(7 + np.cumsum(rng.normal(0, 0.01, 1200))[i]))} for i in range(1200)]
        r2 = self.train("PAIR_COINT", {"instrument": "XAUUSD", "pair": ["XAUUSD", "BTC"], "pair_bars": [A, rw], "data_kind": "REAL"})
        m2 = self.store.runs("PAIR_COINT", "XAUUSD")[-1]
        self.assertEqual(m2["validation"]["status"], "VALIDATION_FAILED")
        nb = self.train("PAIR_COINT", {"instrument": "XAUUSD", "pair": None})
        self.assertEqual(nb["state"], "BLOCKED")
        self.assertIn("PAIR_NOT_CONFIGURED", nb["reason"])
        self.assertAlmostEqual(PR.legs_volume(0.8, 2000.0, 100000.0, 100.0, 1.0, 1.0, 0.01), 1.6)   # beta * notional ratio, step-rounded

    def test_statarb_needs_three_series(self):
        nb = self.train("STATARB", {"instrument": "XAUUSD", "basket": ["XAUUSD", "BTC"]})
        self.assertEqual(nb["state"], "BLOCKED")
        rng = np.random.default_rng(2)
        f = np.cumsum(rng.normal(0, 0.01, 900))
        ser = [[{"t": T0 + i * 3600, "c": float(np.exp(5 + k * 0.3 * f[i] + rng.normal(0, 0.002)))} for i in range(900)] for k in (1, 2, 3)]
        r = self.train("STATARB", {"instrument": "XAUUSD", "basket": ["A", "B", "C"], "basket_bars": ser, "data_kind": "REAL"})
        self.assertEqual(r["state"], "DONE", r)
        s = self.svc()
        f2 = s.fams["STATARB"]
        res = f2.predict(f2.load(self.store.run_dir("STATARB", "XAUUSD", r["run_id"])), {"basket_bars": ser})
        self.assertAlmostEqual(res["gross"], 1.0, places=6)
        self.assertEqual(len(res["weights"]), 3)

    def test_microstructure_measure_without_model_and_blocked_training(self):
        from masterquo.modelhub.families import micro as MI
        f = MI.Micro()
        with self.assertRaises(self.B.Unavailable):
            f.measure({"status": "NO_DATA", "reason": "Brak danych arkusza"})
        m = f.measure({"status": "READY", "values": {"best_imbalance": 0.2, "depth_imbalance": 0.1, "ofi_window": 3.0, "microprice_dev": 0.01,
                                                      "mid": 2000.0, "bid_levels": 5}, "ofi_state": {"mode": "SAMPLED(1s)"}})
        self.assertEqual(m["capability"], "L2_BOOK")
        r = self.train("MICROSTRUCTURE", {"instrument": "XAUUSD", "books": []})
        self.assertEqual(r["state"], "BLOCKED")
        self.assertIn(str(MI.MIN_SNAPSHOTS), r["reason"])

    def test_microstructure_classifier_learns_imbalance(self):
        from masterquo.modelhub.families import micro as MI
        rng = np.random.default_rng(3)
        books, mid = [], 2000.0
        for i in range(6000):
            qb, qa = float(rng.integers(1, 10)), float(rng.integers(1, 10))
            books.append({"t": float(i), "bids": [(mid - 0.05, qb), (mid - 0.15, 3.0)], "asks": [(mid + 0.05, qa), (mid + 0.15, 3.0)]})
            mid += 0.01 * np.sign(qb - qa) + rng.normal(0, 0.002)
        r = self.train("MICROSTRUCTURE", {"instrument": "XAUUSD", "books": books, "data_kind": "REAL"})
        self.assertEqual(r["state"], "DONE", r)
        self.assertEqual(self.store.runs("MICROSTRUCTURE", "XAUUSD")[-1]["validation"]["status"], "APPROVED")

    def test_nlp_corpus_dedup_train_predict(self):
        from masterquo.modelhub.families import nlp as NL
        os.environ["PMW_FAMILIES_DIR"] = self.td
        try:
            rng = np.random.default_rng(4)
            pos, neg, neu = ["gold rallies", "bullion surges", "strong demand lifts"], ["gold plunges", "prices slump", "sell-off deepens"], \
                ["market waits", "traders eye data", "session opens quietly"]
            rows = []
            for i in range(600):
                k = i % 3
                w = (pos, neu, neg)[k][i % 3] + f" item {i} " + " ".join(rng.choice(["today", "again", "now", "on fed"], 2))
                rows.append({"text": w, "label": ("POSITIVE", "NEUTRAL", "NEGATIVE")[k], "first_seen_at": f"2026-01-{1 + i % 28:02d}T00:{i % 60:02d}:00Z"})
            rows.append(dict(rows[0]))                                                   # duplicate
            p = Path(self.td) / "c.jsonl"
            p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
            imp = NL.import_file(p)
            self.assertEqual(imp["added"], 600)
            self.assertEqual(NL.import_file(p)["added"], 0)
            r = self.train("NLP_SENTIMENT", {"instrument": "XAUUSD", "corpus": NL.load_corpus(), "data_kind": "REAL"})
            self.assertEqual(r["state"], "DONE", r)
            self.assertGreater(self.store.runs("NLP_SENTIMENT", "XAUUSD")[-1]["metrics"]["holdout"]["macro_f1"], 0.8)
            f = NL.NLP()
            art = f.load(self.store.run_dir("NLP_SENTIMENT", "XAUUSD", r["run_id"]))
            out = f.predict(art, {"news": [{"headline": "Gold rallies on Fed", "first_seen_at": "2026-11-07T10:00:00Z"}]})
            self.assertGreater(out["sentiment"]["POSITIVE"], out["sentiment"]["NEGATIVE"])
            self.assertEqual(out["topic_share"]["GOLD"], 1.0)
            with self.assertRaises(self.B.Unavailable):
                f.predict(art, {"news": []})
        finally:
            os.environ.pop("PMW_FAMILIES_DIR", None)


class TestRolesIntegrityReceivers(Base):
    def test_roles_assist_requires_approved_and_real(self):
        bars = synth(1500, drift=2e-4, garch=False, phi=0.0, seed=9)
        r = self.train("KALMAN_LS", data_for(bars, kind="SYNTHETIC"))
        self.assertEqual(r["state"], "DONE", r)
        s = self.svc()
        self.assertTrue(s.activate("KALMAN_LS", "XAUUSD", r["run_id"])["ok"])
        self.assertEqual(self.store.state("KALMAN_LS", "XAUUSD")["use"], "SHADOW")      # activation never gives influence
        with self.assertRaises(ValueError):
            s.set_use("KALMAN_LS", "XAUUSD", "ASSIST")                                    # synthetic data -> no ASSIST
        st = s.status("KALMAN_LS", "XAUUSD")
        self.assertEqual(set(st) >= {"implementation", "artifact", "use"}, True)

    def test_tampered_artifact_is_incompatible_and_rollback(self):
        bars = synth(2500, phi=0.4, garch=False, seed=10)
        r1 = self.train("TS_ARIMA", data_for(bars))
        r2 = self.train("TS_ARIMA", data_for(bars))
        s = self.svc()
        self.assertTrue(s.activate("TS_ARIMA", "XAUUSD", r1["run_id"])["ok"])
        self.assertTrue(s.activate("TS_ARIMA", "XAUUSD", r2["run_id"])["ok"])
        self.assertEqual(s.rollback("TS_ARIMA", "XAUUSD")["state"]["active"], r1["run_id"])
        p = self.store.run_dir("TS_ARIMA", "XAUUSD", r2["run_id"]) / "arima.json"
        d = json.loads(p.read_text())
        d["params"][0] += 1.0
        p.write_text(json.dumps(d))
        bad = s.activate("TS_ARIMA", "XAUUSD", r2["run_id"])
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["status"], "INCOMPATIBLE")
        self.assertEqual(self.store.state("TS_ARIMA", "XAUUSD")["active"], r1["run_id"])  # the working artifact stays

    def test_assist_hold_changes_setup_shadow_does_not(self):
        from masterquo.modelhub.families import service as FS
        su = {"status": "READY", "side": "BUY", "checklist": []}

        class Fake(FS.FamilyService):
            def __init__(self, p):
                self.p = p

            def predictions(self, inst):
                return self.p

            def _cfg(self):
                class C:
                    assist_hold_threshold = 0.6
                return C()
        mk = lambda use, down: {"family": "SEQ_GRU", "state": "READY", "use": use, "task_type": "CLASS_PROBABILITIES",  # noqa: E731
                                "result": {"DOWN": down, "FLAT": 0.1, "UP": 0.9 - down}}
        sh = FS.apply_to_setup(su, Fake([mk("SHADOW", 0.8)]).setup_context(su, "XAUUSD"))
        self.assertEqual(sh["status"], "READY")
        self.assertIn("family_context", sh)
        low = FS.apply_to_setup(su, Fake([mk("ASSIST", 0.3)]).setup_context(su, "XAUUSD"))
        self.assertEqual(low["status"], "READY")
        hi = FS.apply_to_setup(su, Fake([mk("ASSIST", 0.8)]).setup_context(su, "XAUUSD"))
        self.assertEqual(hi["status"], "WAIT")
        self.assertIn("ASSIST", hi["status_reason"])
        wait = FS.apply_to_setup(dict(su, status="WAIT"), Fake([mk("ASSIST", 0.1)]).setup_context(su, "XAUUSD"))
        self.assertEqual(wait["status"], "WAIT")                                          # never creates a READY

    def test_catalog_lists_all_15_plus_adapter(self):
        from masterquo.modelhub import families as F
        s = self.svc()
        cat = {c["id"]: c for c in s.catalog("XAUUSD")}
        self.assertTrue(set(F.ids()) <= set(cat))
        self.assertEqual(len(F.ids()), 15)
        self.assertEqual(cat["KALMAN_LS"]["fit_label"], "estymacja Q/R")
        self.assertEqual(cat["BREAKOUT"]["kind"], "VALIDATED_RULES")
        self.assertEqual(cat["SEQ_GRU_EVENT"]["data"]["schema"], "EVENT_UNITS_V1")


class TestRLCore(unittest.TestCase):
    def test_execution_next_open_costs_once_and_liquidation(self):
        from masterquo.modelhub.families.rl_core import ReplayCore
        bars = [{"o": 100 + i, "h": 101 + i, "l": 99 + i, "c": 100.5 + i} for i in range(40)]
        core = ReplayCore(bars, k=4, spread=0.2, slippage=0.1, commission=0.0, max_steps=10)
        core.reset(10)
        _, r, d, tr, info = core.step(2)                                   # LONG decided at close of bar 10
        self.assertAlmostEqual(core.entry, bars[11]["o"] + 0.2)          # filled at the NEXT open + half spread + slippage
        self.assertAlmostEqual(info["cost"], 0.2)
        self.assertAlmostEqual(r, (bars[11]["c"] - (bars[11]["o"] + 0.2)) / 1.0)
        costs_before = core.costs
        for _ in range(20):
            _, r, d, tr, info = core.step(2)
            if d or tr:
                break
        self.assertTrue(tr)
        self.assertEqual(core.pos, 0.0)                                    # forced liquidation
        self.assertAlmostEqual(core.costs - costs_before, 0.2)             # exit cost charged exactly once
        o = core.obs()
        self.assertEqual(len(o), core.obs_dim)

    def test_exposure_limit(self):
        from masterquo.modelhub.families.rl_core import ReplayCore
        core = ReplayCore([{"o": 1, "h": 1, "l": 1, "c": 1}] * 30, k=4, max_units=1)
        core.reset(5)
        core.step(2)
        core.step(2)
        self.assertEqual(core.pos, 1.0)


@unittest.skipUnless(Path(DEEP_PY).is_file(), "brak interpretera .venv_deep (torch/gymnasium/SB3) – test BLOCKED w tym środowisku")
class TestDeepWorker(Base):
    def setUp(self):
        super().setUp()
        os.environ["MQ_DEEP_PYTHON"] = DEEP_PY
        from masterquo.modelhub.families import deep
        deep._HEALTH.clear()

    def test_health_and_lstm_gru_roundtrip(self):
        from masterquo.modelhub.families import deep
        h = deep.health(force=True)
        self.assertTrue(h.get("ok"), h)
        self.assertTrue(h.get("torch"))
        bars = synth(3500, seed=11, phi=0.3)
        for fid in ("SEQ_LSTM", "SEQ_GRU"):
            r, res, a = self.roundtrip(fid, data_for(bars), {"bars": bars})
            self.assertAlmostEqual(sum(res.values()), 1.0, places=5)
            self.assertTrue(a["sample_check"]["checked"])
            m = self.store.runs(fid, "XAUUSD")[-1]
            self.assertGreater(m["metrics"]["param_change_l1"], 0)            # parameters really updated

    def test_ppo_trains_and_proposes(self):
        bars = synth(3200, seed=12)
        r = self.train("RL_PPO", data_for(bars))
        self.assertEqual(r["state"], "DONE", r)
        s = self.svc()
        self.assertTrue(s.activate("RL_PPO", "XAUUSD", r["run_id"])["ok"])
        f = s.fams["RL_PPO"]
        res = f.predict(f.load(self.store.run_dir("RL_PPO", "XAUUSD", r["run_id"])), {"bars": bars})
        self.assertIn(res["action"], ("SHORT", "FLAT", "LONG"))
        self.assertAlmostEqual(sum(res["action_probabilities"].values()), 1.0, places=5)
        m = self.store.runs("RL_PPO", "XAUUSD")[-1]
        self.assertIn("flat", m["metrics"]["test"])


if __name__ == "__main__":
    unittest.main()
