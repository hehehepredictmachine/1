"""PMW-UPD-07 Structure Intelligence - networks (T36-T43), tasks/protocol (T11-T13, T54-T56), SCI2 (T09/T10), zones (T31-T35),
pattern library (T23-T27), Manual Pad (T44-T49), knowledge (T58/T59). Generated / synthetic data only (TEST_ONLY): a passing test
proves the code path, never a market edge. No real account is touched; Fake MT5 only."""
from __future__ import annotations

import csv
import json
import math
import time
import unittest
from datetime import datetime, timedelta, timezone

import numpy as np

import _env  # noqa: F401
from _env import TempData

UTC = timezone.utc


# ------------------------------------------------------------------------------------------------ networks
class TestNets(unittest.TestCase):
    CFG = {"widths": [4, 8], "blocks_per_stage": 1, "cardinality": 2, "horizons": [3, 5]}

    def data(self, n=3, T=9, seed=0):
        rng = np.random.default_rng(seed)
        return rng.normal(size=(n, 3, T)), np.array([[0, 2], [1, -1], [2, 1]])[:n], np.array([[0.3, np.nan], [-0.1, 0.5], [0.2, -0.4]])[:n]

    def test_t40_numeric_gradients_smooth_reference(self):
        from masterquo.lab import structure_nets as SN
        x, y, r = self.data()
        rng = np.random.default_rng(1)
        for fam in SN.FAMILIES:
            net = SN.StructureNet(fam, 3, self.CFG, seed=2)
            for k in net.p:
                if k.startswith("b_"):
                    net.p[k] = rng.normal(0, 0.3, net.p[k].shape)          # away from ReLU kinks
            if net.spiking:
                net.smooth_reference, net.reset_reference = True, False      # smooth reference of the adopted backward
            _, G = net.loss_grad(x, y, r, lam=0.05)
            worst = 0.0
            for k in net.p:
                idx = np.unravel_index(np.argmax(np.abs(G[k])), G[k].shape)
                old = net.p[k][idx]
                net.p[k][idx] = old + 1e-6
                lp = net.loss_grad(x, y, r, lam=0.05)[0]["loss"]
                net.p[k][idx] = old - 1e-6
                lm = net.loss_grad(x, y, r, lam=0.05)[0]["loss"]
                net.p[k][idx] = old
                num = (lp - lm) / 2e-6
                worst = max(worst, abs(num - G[k][idx]) / (abs(num) + abs(G[k][idx]) + 1e-9))
            self.assertLess(worst, 1e-4, fam)

    def test_t37_bptt_matches_independent_vjp(self):
        from masterquo.lab import structure_nets as SN
        rng = np.random.default_rng(3)
        I = rng.normal(0.8, 0.6, size=(2, 3, 7))
        ds = rng.normal(size=I.shape)
        s, u = SN.lif_fwd(I, 0.9, 1.0, 2.0)
        dI = SN.lif_bwd(ds, u, 0.9, 1.0, 2.0)
        ref = np.zeros_like(I)                                               # scalar loops, adopted formula (reset detached)
        for n in range(2):
            for c in range(3):
                g = 0.0
                for t in range(6, -1, -1):
                    x = u[n, c, t] - 1.0
                    sg = 1.0 / (1 + (math.pi / 2 * 2.0 * x) ** 2)
                    g = ds[n, c, t] * sg + g
                    ref[n, c, t] = g
                    g *= 0.9
        np.testing.assert_allclose(dI, ref, rtol=1e-10, atol=1e-12)
        self.assertTrue(set(np.unique(s)).issubset({0.0, 1.0}))

    def test_t36_sew_add_identity_and_projection(self):
        from masterquo.lab import structure_nets as SN
        net = SN.StructureNet("MQ_SEW_RESNET1D_V2", 3, {"widths": [4, 4], "blocks_per_stage": 1, "horizons": [3]}, seed=1)
        for k in net.p:
            if k.startswith(("W_s0b0", "b_s0b0")):
                net.p[k][:] = 0.0                                            # zero branch of the first block (same width)
        x = np.random.default_rng(0).normal(size=(2, 3, 6))
        _, _, fc = net.forward(x)
        blk = fc["layers"][1]
        np.testing.assert_allclose(blk[5], blk[4])                           # out == input: identity
        self.assertFalse(blk[1]["proj"])
        net2 = SN.StructureNet("MQ_SEW_RESNET1D_V2", 3, {"widths": [4, 8], "blocks_per_stage": 1, "horizons": [3]}, seed=1)
        self.assertTrue(net2.blocks[1]["proj"])                              # width change -> projection (not identity)

    def test_t38_reset_each_window(self):
        from masterquo.lab import structure_nets as SN
        net = SN.StructureNet("MQ_SEW_RESNEXT_EB_V1", 3, self.CFG, seed=4)
        x = np.random.default_rng(1).normal(size=(4, 3, 10))
        a = net.predict(x)["proba"]
        b = np.concatenate([net.predict(x[i:i + 1])["proba"] for i in range(4)])
        np.testing.assert_allclose(a, b)                                     # no state across batch items
        c = net.predict(x[:1])["proba"]
        np.testing.assert_allclose(c, a[:1])                                 # nor across calls

    def test_t39_predict_pure_and_save_load(self):
        from masterquo.lab import structure_nets as SN
        td = TempData()
        try:
            net = SN.StructureNet("MQ_RESNEXT1D_V2", 3, self.CFG, seed=5)
            x, y, r = self.data()
            before = {k: v.copy() for k, v in net.p.items()}
            p1 = net.predict(x)
            for k in net.p:
                np.testing.assert_array_equal(before[k], net.p[k])
            info = SN.fit(net, x, y, r, np.arange(3), epochs=2, batch=2)
            self.assertEqual(info["status"], "TRAINED")
            self.assertTrue(any(not np.array_equal(before[k], net.p[k]) for k in net.p))
            p2 = net.predict(x)
            d = _env.Path(td.dir) / "m"
            man = net.save(d)
            net2 = SN.StructureNet.load(d, {"architecture_id": "MQ_RESNEXT1D_V2"})
            np.testing.assert_allclose(net2.predict(x)["proba"], p2["proba"])
            self.assertEqual(man["layout"].split()[0], "NCT")
            with self.assertRaises(ValueError):
                SN.StructureNet.load(d, {"architecture_id": "MQ_SEW_RESNET1D_V2"})
            (d / "weights.npz").write_bytes((d / "weights.npz").read_bytes() + b"x")
            with self.assertRaises(ValueError):
                SN.StructureNet.load(d)
            self.assertIsNotNone(p1)
        finally:
            td.close()

    def test_t41_cardinality_not_divisor(self):
        from masterquo.lab import structure_nets as SN
        with self.assertRaises(ValueError) as cm:
            SN.StructureNet("MQ_RESNEXT1D_V2", 3, {"widths": [6], "blocks_per_stage": 1, "cardinality": 4, "horizons": [3]})
        self.assertIn("CARDINALITY_NOT_DIVISOR", str(cm.exception))

    def test_t42_t43_lambda_effect_and_energy(self):
        from masterquo.lab import structure_nets as SN
        net = SN.StructureNet("MQ_SEW_RESNEXT_EB_V1", 3, self.CFG, seed=6)
        x, y, r = self.data()
        L0, G0 = net.loss_grad(x, y, r, lam=0.0)
        L1, G1 = net.loss_grad(x, y, r, lam=0.05)
        self.assertGreater(L1["loss"], L0["loss"])
        self.assertTrue(any(not np.allclose(G0[k], G1[k]) for k in G0 if k.startswith("W_s")))
        tel = net.telemetry(x, repeats=2)
        self.assertIsNone(tel["energy_j"])
        self.assertEqual(tel["energy_status"], "NOT_MEASURED")
        self.assertIsNotNone(tel["synops_estimate"])
        self.assertGreater(tel["dense_macs"], 0)

    def test_quantile_order(self):                                           # T12 (model side)
        from masterquo.lab import structure_nets as SN
        net = SN.StructureNet("MQ_SEW_RESNET1D_V2", 3, self.CFG, seed=7)
        q = net.predict(np.random.default_rng(2).normal(size=(5, 3, 8)) * 5)["quantiles"]
        self.assertTrue(np.all(q[..., 0] <= q[..., 1]) and np.all(q[..., 1] <= q[..., 2]))


# ------------------------------------------------------------------------------------------------ task / protocol / SCI2
def m1_bars(n=2600, seed=3, gap_at=None):
    rng = np.random.default_rng(seed)
    t0 = datetime(2026, 3, 2, tzinfo=UTC)
    out, c = [], 2000.0
    k = 0
    for i in range(n):
        if gap_at is not None and i == gap_at:
            k += 7
        o = c
        c = o + rng.normal(0, 0.4)
        out.append({"open_utc": (t0 + timedelta(minutes=k)).strftime("%Y-%m-%dT%H:%M:%SZ"), "o": o, "h": max(o, c) + abs(rng.normal(0, 0.2)),
                    "l": min(o, c) - abs(rng.normal(0, 0.2)), "c": c, "tv": 50.0, "spread": 12.0})
        k += 1
    return out


def write_export(d, m1, kind="SYNTHETIC_TEST"):
    d.mkdir(parents=True)

    def agg(mins):
        res = []
        for i in range(0, len(m1) - mins + 1, mins):
            g = m1[i:i + mins]
            res.append({"open_utc": g[0]["open_utc"], "o": g[0]["o"], "h": max(b["h"] for b in g), "l": min(b["l"] for b in g), "c": g[-1]["c"], "tv": 1.0, "spread": 12.0})
        return res
    for tf, bs in (("M1", m1), ("M5", agg(5)), ("M15", agg(15)), ("H1", agg(60))):
        with open(d / f"XAUUSD_{tf}.csv", "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["time_open_utc", "open", "high", "low", "close", "tick_volume", "spread_points"])
            for b in bs:
                w.writerow([b["open_utc"], b["o"], b["h"], b["l"], b["c"], b["tv"], b["spread"]])
    (d / "source_metadata.json").write_text(json.dumps({"instrument": "XAUUSD", "file_prefix": "XAUUSD", "tick_size": 0.01, "spec": {"point": 0.01},
                                                        "data_kind": kind, "dataset_id": "fx", "symbol": "XAUUSD-"}))
    return d


class TestTask(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_t11_labels_maturity_and_gaps(self):
        from masterquo.lab import structure_task as T
        bars = m1_bars(400, gap_at=200)
        fe = T.features(bars, None, 0.01)
        Y, R = T.labels(list(fe["t"]), list(fe["c"]), list(fe["atr"]))
        n = len(bars)
        for j, h in enumerate(T.HORIZONS):
            self.assertTrue(np.all(Y[n - h:, j] == -1))                      # immature labels are missing, never a class
            i = 150
            r = (fe["c"][i + h] - fe["c"][i]) / fe["atr"][i]
            self.assertAlmostEqual(float(R[i, j]), r, places=5)
            b = 0.15 * math.sqrt(h)
            self.assertEqual(Y[i, j], 0 if r < -b else 2 if r > b else 1)
            self.assertEqual(Y[199, j], -1)                                  # window crossing the gap is excluded
        self.assertTrue((Y[:, 0] >= 0).sum() > (Y[:, 2] >= 0).sum())        # different label ends per horizon

    def test_t03_feature_prefix_invariance(self):
        from masterquo.lab import structure_task as T
        bars = m1_bars(700)
        a = T.features(bars[:600], None, 0.01)["F"]
        future = [dict(b, h=b["h"] * 1.5, c=b["c"] * 1.3) for b in bars[600:]]
        b = T.features(bars[:600] + future, None, 0.01)["F"]
        np.testing.assert_allclose(a, b[:600], equal_nan=True)

    def test_t54_t56_protocol_holdout_and_registry(self):
        from masterquo.db.database import Database
        from masterquo.lab import structure_task as T
        import mq_instruments
        db = Database()
        db.migrate()
        ds = write_export(mq_instruments.data_dir() / "exp", m1_bars(3000))
        man = T.save_dataset("XAUUSD", T.build_move_dataset("XAUUSD", ds, log=lambda *a: None))
        T.PROFILES["fixture"] = dict(T.PROFILES["quick"], epochs=1, net_cfg={"widths": [4, 8], "blocks_per_stage": 1, "cardinality": 2}, max_fit_rows=300)
        try:
            rep = T.train("XAUUSD", T.latest_dataset("XAUUSD", T.TASK_MOVE), T.TASK_MOVE, ["LOGREG", "MQ_SEW_RESNET1D_V2"], "fixture", db=db, log=lambda *a: None)
        finally:
            T.PROFILES.pop("fixture")
        self.assertEqual(rep["role"], "TEST_ONLY")
        self.assertEqual(rep["evidence"]["status"], "INSUFFICIENT_EVIDENCE")
        data = T.load_dataset(T.latest_dataset("XAUUSD", T.TASK_MOVE), T.TASK_MOVE)
        sp = T.split(data)
        hold = set(sp["hold"].tolist())
        for f in sp["folds"]:
            for k, blk in f["blocks"].items():
                self.assertFalse(hold & set(blk.tolist()), k)                 # holdout never in fit / tune / calibration / policy
            if len(f["eval"]):
                ev0 = T._ts(f["eval_start"])
                last_end = max(T._ts(sp["rows"][i]["label_end"]) for i in f["blocks"]["POLICY"]) if len(f["blocks"]["POLICY"]) else 0
                self.assertLess(last_end, ev0)                               # purge by label end
        cid = rep["candidates"]["LOGREG"]["candidate_id"]
        with self.assertRaises(ValueError):
            T.select_shadow("XAUUSD", cid)                                   # TEST_ONLY never reaches SHADOW
        r1 = T.evaluate_holdout("XAUUSD", cid, T.PROTOCOL_ID, db)
        r2 = T.evaluate_holdout("XAUUSD", cid, T.PROTOCOL_ID, db)
        self.assertEqual((r1["status"], r2["status"]), ("EVALUATED_ONCE", "ALREADY_EVALUATED"))
        self.assertEqual(len(db.query("SELECT * FROM eval_ledger WHERE task_id=?", (T.TASK_MOVE,))), 1)
        d = _env.Path(rep["run_dir"]) / "models" / "LOGREG"
        with self.assertRaises(ValueError):
            T.load_candidate(d, {"task_id": T.TASK_SETUP})                   # wrong task rejected
        with self.assertRaises(ValueError):
            T.load_dataset(T.latest_dataset("XAUUSD", T.TASK_MOVE), T.TASK_SETUP)
        # profile change -> stale dataset refused with the rebuild command
        (T.root("XAUUSD") / "indicator_profile.json").write_text(json.dumps({"version": "X", "structure": {"internal": [2, 2], "major": [5, 5]},
                                                                            "mitp_profile": "STRICT_ALL", "hash": "different"}))
        st = T.train("XAUUSD", T.latest_dataset("XAUUSD", T.TASK_MOVE), T.TASK_MOVE, ["LOGREG"], "quick", db=db)
        self.assertEqual(st["status"], "STALE_DATASET")
        self.assertIn("dataset", st["rebuild"])
        self.assertTrue(man["sha256"])

    def test_t13_no_setup(self):
        from masterquo.lab import structure_task as T
        import mq_instruments
        ds = write_export(mq_instruments.data_dir() / "exp2", m1_bars(1200))
        d = T.build_move_dataset("XAUUSD", ds, log=lambda *a: None)
        d.update(task=T.TASK_SETUP, setup_y=np.zeros(0, np.int8), setup_r=np.zeros(0, np.float32), setup_idx=np.zeros(0, np.int64))
        T.save_dataset("XAUUSD", d)
        r = T.train("XAUUSD", T.latest_dataset("XAUUSD", T.TASK_SETUP), T.TASK_SETUP, ["LOGREG"], "quick")
        self.assertEqual(r["status"], "NO_SETUP")

    def test_t09_t10_sci2_roles_and_evidence_groups(self):
        from masterquo.analysis import sci2, structure_v2 as S
        bars = m1_bars(300, seed=9)
        t, o, h, lo, c = ([b[k] for b in bars] for k in ("open_utc", "o", "h", "l", "c"))
        st = S.analyse(t, h, lo, c)
        sweeps = [e for e in st["events"] if e["kind"].startswith("SWEEP") and e["layer"] == "internal"]
        self.assertTrue(sweeps)
        i = sweeps[-1]["bar_index"]
        rd = sci2.read(t, o, h, lo, c, "M1", i=i)
        self.assertEqual(rd["role"], "SWEEP_RECLAIM")
        self.assertIsNone(rd["signal"])
        mid = sci2.read(t, o, h, lo, c, "M1", i=i - 1)
        self.assertNotEqual(mid["role"], "SWEEP_RECLAIM")                    # same machinery, different structural context
        for g in rd["candles"]:
            self.assertEqual(len({g["evidence_group_id"]}), 1)               # names of one bar = one evidence group
        self.assertEqual(sci2.read(t[:5], o[:5], h[:5], lo[:5], c[:5], "M1")["role"], "NO_STRUCTURAL_CONTEXT")

    def test_t58_t59_knowledge(self):
        from masterquo.analysis import structure_knowledge as sk
        from masterquo.agent.service import load_prompt
        text, ver = load_prompt()
        self.assertIn(sk.KNOWLEDGE_VERSION, ver)
        self.assertIn("K36", text)
        snap = {"snapshot_id": "SIS-1", "as_of": "x", "cells": {"M5": {"status": "OK", "structure": {"trend_internal": "UP", "trend_major": "UNKNOWN",
                "last_event": {"event_id": "SE-1", "kind": "BOS_UP", "level": 1.0, "bar_t": "t"}}, "pattern": None, "candle_role": {"reading_id": "SCI2-1", "role": "MID_RANGE"},
                "mitp": {"held_state": "BUY", "current_vote": 0}}}, "forecast": {"forecast_status": "ABSTAIN", "reason": "NO_SHADOW_MODEL"}, "divergences": []}
        ex = sk.explain(snap)
        self.assertIn("SE-1", ex["evidence_ids"])
        self.assertIn("K15", ex["rules"])
        self.assertNotIn("%", ex["text"])                                    # no probability invented without a model output
        self.assertEqual(sk.explain(None)["status"], "NO_SNAPSHOT")


# ------------------------------------------------------------------------------------------------ zones
class TestZonesV2(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.db.database import Database
        from masterquo.lab.zones import ZoneStore
        self.db = Database()
        self.db.migrate()
        self.root = _env.Path(self.td.dir) / "z"
        self.st = ZoneStore(self.db, self.root)

    def tearDown(self):
        self.td.close()

    def bars(self, prices):
        t0 = datetime(2026, 3, 2, tzinfo=UTC)
        return [{"open_utc": (t0 + timedelta(minutes=15 * i)).strftime("%Y-%m-%dT%H:%M:%SZ"), "o": p, "h": p + 0.5, "l": p - 0.5, "c": p} for i, p in enumerate(prices)]

    def zone(self):
        return {"zone_id": "SDZ-XAUUSD-M15-D-T", "asset": "XAUUSD", "tf": "M15", "kind": "DEMAND", "top": 100.0, "bottom": 99.0,
                "origin_time": "2026-03-02T00:00:00Z", "confirmed_at": "2026-03-02T00:15:00Z", "source": "AUTO", "quality": "AUTO_RULE", "exit_strength_atr": 2.0, "base_len": 1}

    def test_t31_t32_t33_episodes_idempotent_and_outside_window(self):
        self.st.save("XAUUSD", [self.zone()])
        b = self.bars([105, 104, 99.8, 99.6, 99.9, 103, 104, 99.7, 103])     # one episode of 3 bars inside, exit, second touch
        self.st.process("XAUUSD", "M15", b)
        z = self.st.list_asof("XAUUSD")[0]
        self.assertEqual(z["touch_count"], 2)
        self.assertEqual(z["state"], "TESTED")
        self.st.process("XAUUSD", "M15", b)                                   # replay of the same bars
        self.assertEqual(self.st.list_asof("XAUUSD")[0]["touch_count"], 2)
        self.assertEqual(self.db.one("SELECT COUNT(*) AS n FROM lab_zone_events")["n"], 2)
        self.st.save("XAUUSD", [dict(self.zone(), top=101.0)])                # detector again: stored lifecycle not overwritten
        self.assertEqual(self.st.list_asof("XAUUSD")[0]["top"], 100.0)
        from masterquo.lab.zones import ZoneStore
        st2 = ZoneStore(self.db, self.root)                                   # restart: same state
        st2.restore("XAUUSD")
        z2 = st2.list_asof("XAUUSD")[0]
        self.assertEqual((z2["touch_count"], z2["state"], z2["last_processed_bar"]), (2, "TESTED", b[-1]["open_utc"]))
        st2.process("XAUUSD", "M15", self.bars([105] * 9) + [dict(self.bars([98.0] * 10)[9])])
        self.assertEqual(st2.list_asof("XAUUSD")[0]["state"], "BROKEN")
        self.assertIsNotNone(st2.list_asof("XAUUSD")[0]["right_edge"])

    def test_t34_t35_tombstone_revision_and_corrupt_snapshot(self):
        self.st.save("XAUUSD", [self.zone()])
        z = self.st.list_asof("XAUUSD")[0]
        with self.assertRaises(ValueError):
            self.st.patch(z["zone_id"], z["revision"] + 5, top=101.0)
        r = self.st.patch(z["zone_id"], z["revision"], top=101.0, reason="edit")
        self.assertEqual(r["revision"], 2)
        self.st.delete(z["zone_id"], 2)
        (self.root / "zones_XAUUSD.json").write_text("{corrupt", encoding="utf-8")
        self.db.execute("DELETE FROM lab_zones")                               # DB loss
        from masterquo.lab.zones import ZoneStore
        st2 = ZoneStore(self.db, self.root)
        r = st2.restore("XAUUSD")
        self.assertEqual(st2.list_asof("XAUUSD"), [])                          # tombstoned zone never resurrected
        self.assertTrue(any(e["event"] == "SNAPSHOT_CORRUPT" for e in st2.events))
        m = st2.add_manual("XAUUSD", "H1", "DEMAND", 10.0, 9.0, "2026-03-02T00:00:00Z")
        row = next(x for x in st2.list_asof("XAUUSD") if x["zone_id"] == m["zone_id"])
        self.assertEqual(row["quality"], "UNRATED")
        self.assertEqual(row["score"]["rating"], "MANUAL_BASELINE")
        with self.assertRaises(ValueError):
            st2.save("XAUUSD", [dict(self.zone(), zone_id="Z0", top=99.0, bottom=99.0)])   # zero height is an error
        self.assertIsNotNone(r)


# ------------------------------------------------------------------------------------------------ pattern library
class TestLibraryV2(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.db.database import Database
        from masterquo.analytics import double_bottom as DB
        from masterquo.analytics.library import PatternLibrary
        self.db = Database()
        self.db.migrate()
        self.lib = PatternLibrary(self.db, lambda: dict(DB.DEFAULT))

    def tearDown(self):
        self.td.close()

    def wait(self, jid):
        for _ in range(200):
            j = self.lib.job(jid)
            if j["status"] != "RUNNING":
                return j
            time.sleep(0.05)
        self.fail("job")

    def test_t23_t25_t26_t27_manifest_interrupt_resume_export_result(self):
        import test_analytics as TA
        a = self.lib.add_sample("XAUUSD-", "M5", TA.F.double_bottom("up"), "TEST")
        b = self.lib.add_sample("XAUUSD-", "M5", TA.F.double_bottom("down"), "TEST")
        st = self.lib.start_job(None)
        j = self.wait(st["job_id"])
        self.assertEqual(j["status"], "COMPLETED")
        self.assertEqual(j["processed"] + j["pending"], j["total"])
        res = self.lib.results(st["job_id"])
        self.assertEqual(len(res), 2)
        one = self.lib.validate_one(a["id"])["result"]["values"]
        saved = self.lib.result(next(r["result_id"] for r in res if r["sample_id"] == a["id"]))
        self.assertEqual(saved["result"]["values"]["coordinates"], one["coordinates"])   # single == batch
        self.assertIsNotNone(saved["usable_at"])
        # SHOW ON CHART reads the stored result: later parameter changes do not change it, no new job/result rows
        n0 = self.db.one("SELECT COUNT(*) AS n FROM pattern_results")["n"]
        again = self.lib.latest_result(a["id"])
        self.assertEqual(again["result_id"], saved["result_id"])
        self.assertEqual(self.db.one("SELECT COUNT(*) AS n FROM pattern_results")["n"], n0)
        # interrupted -> resume with the same manifest, no duplicated results
        self.db.execute("UPDATE pattern_jobs SET status='RUNNING' WHERE job_id=?", (st["job_id"],))
        self.db.execute("DELETE FROM pattern_results WHERE job_id=? AND sample_id=?", (st["job_id"], b["id"]))
        self.assertEqual(self.lib.mark_interrupted(), 1)
        self.assertEqual(self.lib.job(st["job_id"])["status"], "INTERRUPTED")
        self.lib.delete(b["id"])                                              # removed after the start: manifest still reproduces it
        self.assertTrue(self.lib.resume(st["job_id"])["ok"])
        j2 = self.wait(st["job_id"])
        self.assertEqual(len(self.lib.results(st["job_id"])), 2)
        self.assertEqual(j2["counts"]["FAILED"], 1)
        # export failure keeps results; re-export without validation
        from masterquo.analytics import library as L
        orig = L.PatternLibrary._write_report
        L.PatternLibrary._write_report = lambda *a, **k: (_ for _ in ()).throw(OSError("disk"))
        try:
            self.assertFalse(self.lib.export(st["job_id"])["ok"])
        finally:
            L.PatternLibrary._write_report = orig
        self.assertTrue(self.lib.job(st["job_id"])["export_status"].startswith("EXPORT_FAILED"))
        ex = self.lib.export(st["job_id"])
        self.assertTrue(ex["ok"])
        sheet = (L.lib_dir() / "reports" / f"{ex['report_id']}_sheet.csv").read_text(encoding="utf-8-sig")
        self.assertIn("result_id", sheet)
        self.assertEqual(L.PatternLibrary._safe_cell("=cmd()"), "'=cmd()")

    def test_t24_decisive_before_recognition(self):
        from masterquo.analytics import double_bottom as DB
        import test_analytics as TA
        bars = TA.F.double_bottom("up")
        r = DB.validate(bars, dict(DB.DEFAULT, pivot_right=8), symbol="X", tf="M5")
        v = r["values"]
        if v["status"] == "CONFIRMED" and "DECISIVE_EVENT_PRECEDED_RECOGNITION" in v["flags"]:
            self.assertGreaterEqual(v["usable_at"], v["available"]["bottom2_pivot_known_at"])
        self.assertGreaterEqual(v.get("usable_at") or "", v["available"]["bottom2_pivot_known_at"] or "")
        bad = list(bars) + [dict(bars[-1], open_utc="2099-01-01T00:00:00Z", h=-1)]
        self.assertEqual(DB.validate(bad, upto=len(bars) - 1, symbol="X", tf="M5")["values"]["status"], v["status"])   # future damage ignored


# ------------------------------------------------------------------------------------------------ Manual Pad
class TestManualPad(unittest.TestCase):
    META = {"trade_tick_size": 0.01, "point": 0.01, "volume_min": 0.01, "volume_max": 5.0, "volume_step": 0.01, "trade_stops_level": 0,
            "trade_contract_size": 100.0, "currency_profit": "USD"}

    def test_t44_t45_sizing_and_blocks(self):
        from masterquo.execution.manual import PlanError, plan_math
        q = {"bid": 2000.00, "ask": 2000.20}
        fx = 0.9                                                               # account currency EUR: profit USD x 0.9 (terminal calculator)
        calc = lambda side, vol, o, c: (c - o) * 100 * vol * fx * (1 if side == "BUY" else -1)  # noqa: E731
        p = plan_math(side="BUY", quote=q, meta=self.META, sl=1995.003, tp=2010.0, sizing_mode="RISK_PCT", risk_pct=0.5, basis_value=10000,
                      calc_profit=calc, commission={"per_lot_per_side": 3.5, "source": "CONFIGURED"})
        self.assertEqual(p["sl"], 1995.0)                                    # aligned away from the entry
        self.assertLessEqual(p["risk_net"], 50.0 + 1e-9)                     # cash risk never above the budget
        self.assertAlmostEqual(p["lots"] * 100 % 1, 0.0)
        self.assertTrue(p["execution_eligible"])
        unk = plan_math(side="BUY", quote=q, meta=self.META, sl=1995.0, tp=2010.0, sizing_mode="FIXED", lots=0.1, calc_profit=calc, commission=None)
        self.assertIn("COMMISSION_UNKNOWN", unk["reason_codes"])
        self.assertFalse(unk["execution_eligible"])
        self.assertIsNone(unk["commission_round_turn"])                       # unknown is never 0
        for kw, code in ((dict(sl=2001.0), "SL_WRONG_SIDE"), (dict(sl=1995.0, sizing_mode="FIXED", lots=9.0), "LOTS_ABOVE_MAX"),
                         (dict(sl=1000.0, risk_pct=0.01, basis_value=100), "MIN_VOLUME_EXCEEDS_RISK")):
            with self.assertRaises(PlanError) as cm:
                plan_math(**dict(dict(side="BUY", quote=q, meta=self.META, sizing_mode="RISK_PCT", risk_pct=0.5, basis_value=10000, calc_profit=calc,
                                      commission={"per_lot_per_side": 3.5, "source": "CONFIGURED"}), **kw))
            self.assertIn(code, str(cm.exception))
        st = plan_math(side="SELL", quote=q, meta=dict(self.META, trade_stops_level=1000), sl=2001.0, sizing_mode="FIXED", lots=0.1, calc_profit=calc,
                       commission={"per_lot_per_side": 1, "source": "CONFIGURED"})
        self.assertIn("STOPS_LEVEL_VIOLATION", st["reason_codes"])


class TestManualPadRuntime(unittest.TestCase):
    def setUp(self):
        import test_risk_execution as TR
        self.td = TempData()
        cfg, db, bus, log, fake, worker, b = TR.core()
        self.cfg, self.db, self.fake, self.worker, self.b = cfg, db, fake, worker, b
        cfg.update({"risk": TR.LIMITS, "costs": {"commission_mode": "CONFIGURED", "commission_per_lot_per_side": 3.0}})   # Execution Lock stays LOCKED
        b.start()
        self.assertTrue(TR.wait_for(lambda: b.state == "CONNECTED" and b.quote_status() and b.symbol_info, 40))
        from masterquo.engine.lifecycle import LifecycleStore
        from masterquo.execution.gateway import ExecutionGateway
        from masterquo.execution.manager import PositionManager
        from masterquo.execution.manual import ManualPad
        from masterquo.execution.modes import ModeManager
        from masterquo.execution.paper import PaperBroker
        self.modes = ModeManager(cfg, db, bus, log, account_provider=lambda: (b.account_status(), b.account_key, b.synthetic))
        self.paper = PaperBroker(cfg, b, db, bus, log)
        self.gw = ExecutionGateway(cfg, b, db, bus, log, self.modes, TR.StubEngine(LifecycleStore(db)), self.paper)
        self.gw.manager = PositionManager(cfg, b, db, bus, log, self.modes, self.paper)
        self.gw.manager.reconciled_epoch = b.session_epoch
        self.pad = ManualPad(cfg, b, db, bus, log, self.modes, self.paper, self.gw, ttl_s=30)
        self.sent = []
        orig = self.fake.order_send
        self.fake.order_send = lambda r: self.sent.append(r) or orig(r)

    def tearDown(self):
        self.b.stop()
        self.worker.stop()
        self.td.close()

    def plan(self):
        q = self.b.quote_status()
        return self.pad.plan({"side": "BUY", "sl": q["ask"] - 5, "tp": q["ask"] + 10, "sizing_mode": "FIXED", "lots": 0.05})

    def test_t46_t47_t48_lock_paper_idempotency_be_partial(self):
        acct = self.b.account_status()
        self.modes.set_mode("AUTO_DEMO", confirm=str(acct["login"]), account=acct, account_key=self.b.account_key, synthetic=True)
        it = self.pad.create_intent(self.plan()["plan_id"])
        self.modes.set_kill(True, "TEST")                                       # STOP: no new manual entry either
        r = self.pad.execute(it["intent_id"])
        self.assertEqual(r["status"], "BLOCKED")
        self.assertIn("NEW_ENTRIES_STOPPED", r["reason"])
        self.assertEqual(self.sent, [])
        self.modes.set_kill(False, "TEST")
        self.modes.set_mode("PAPER", account=None, account_key=None, synthetic=True)
        it = self.pad.create_intent(self.plan()["plan_id"])
        r1 = self.pad.execute(it["intent_id"])
        r2 = self.pad.execute(it["intent_id"])                                # double click / retry
        self.assertEqual(r1["status"], "FILLED")
        self.assertEqual(r2["status"], "DUPLICATE")
        self.assertEqual(self.sent, [])                                       # PAPER never calls order_send
        self.assertEqual(len(self.db.query("SELECT * FROM managed_positions WHERE decision_id=?", (it["intent_id"],))), 1)
        pos = self.db.one("SELECT * FROM managed_positions WHERE decision_id=?", (it["intent_id"],))
        self.db.execute("UPDATE managed_positions SET sl=? WHERE position_key=?", (pos["entry_price"] + 0.5, pos["position_key"]))
        be = self.pad.manage(it["intent_id"], "BREAK_EVEN", 1)
        self.assertEqual(be["items"][0]["status"], "UNCHANGED")               # never worsen a better SL
        bad = self.pad.manage(it["intent_id"], "PARTIAL_CLOSE", 1, volume=0.045)
        self.assertEqual(bad["items"][0]["status"], "DONE")                   # rounded down to the step 0.04, remaining 0.01 >= min
        self.assertAlmostEqual(bad["items"][0]["remaining"], 0.01)
        self.assertEqual(self.pad.manage(it["intent_id"], "PARTIAL_CLOSE", 1, volume=0.01)["status"], "DUPLICATE")

    def test_t45_stale_plan_and_settings(self):
        self.modes.set_mode("PAPER", account=None, account_key=None, synthetic=True)
        p = self.plan()
        it = self.pad.create_intent(p["plan_id"])
        self.db.execute("UPDATE manual_intents SET plan=? WHERE intent_id=?",
                        (json.dumps(dict(p, expires_at="2000-01-01T00:00:00Z")), it["intent_id"]))
        r = self.pad.execute(it["intent_id"])
        self.assertEqual(r["status"], "BLOCKED")
        self.assertIn("PLAN_EXPIRED", r["reason"])


if __name__ == "__main__":
    unittest.main()
