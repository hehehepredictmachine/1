"""PMW-UPD-04 Neural Scalp System (CAUSAL_MTF_TCN_V1 / SCALP_SETUP_MARKET_V1). Code tests on generated data only (FIXTURE) -
a passing test proves the code path, not a market edge. Case ids follow the specification list (J.1-J.22)."""
from __future__ import annotations

import json
import math
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import _env  # noqa: F401
from _env import TempData

UTC = timezone.utc
T0 = datetime(2026, 3, 2, 0, 0, tzinfo=UTC)


def gen_bars(n_m1=3000, seed=4, spread=True):
    import numpy as np
    rng = np.random.default_rng(seed)
    m1, c = [], 2000.0
    for k in range(n_m1):
        o = c
        c = o + rng.normal(0, 0.4)
        h, lo = max(o, c) + abs(rng.normal(0, 0.2)), min(o, c) - abs(rng.normal(0, 0.2))
        m1.append({"open_utc": (T0 + timedelta(minutes=k)).isoformat(), "o": o, "h": h, "l": lo, "c": c, "tv": float(rng.integers(20, 200)),
                   "spread_price": 0.12 if spread else None})

    def agg(mins):
        out = []
        for i in range(0, len(m1) - mins + 1, mins):
            g = m1[i:i + mins]
            out.append({"open_utc": g[0]["open_utc"], "o": g[0]["o"], "h": max(b["h"] for b in g), "l": min(b["l"] for b in g), "c": g[-1]["c"],
                        "tv": sum(b["tv"] for b in g), "spread_price": 0.12})
        return out
    return {"M1": m1, "M5": agg(5), "M15": agg(15), "H1": agg(60)}


def setup_feats(v=0.1):
    from masterquo.scalp.strategy import SETUP_FEATURES
    return {k: v for k in SETUP_FEATURES}


class TestNetwork(unittest.TestCase):
    def test_gradient_check(self):                                       # J.4
        import numpy as np
        from masterquo.lab.scalp_net import CausalMTFTCN
        rng = np.random.default_rng(0)
        net = CausalMTFTCN(3, 2, 4, {"width": 4, "m1_len": 20, "m5_len": 8, "m1_dil": [1, 2], "m5_dil": [1], "ctx_hidden": 6, "ctx_out": 3, "fusion": 5}, seed=1)
        a = (rng.normal(size=(6, 3, 20)), rng.normal(size=(6, 2, 8)), rng.normal(size=(6, 4)), np.array([0, 1, 0, 1, 1, 0]), rng.integers(0, 3, 6), rng.normal(size=6))
        _, G = net.loss_grad(*a)
        worst = 0.0
        for k, v in net.p.items():
            for _ in range(3):
                idx = tuple(rng.integers(0, s) for s in v.shape)
                old = v[idx]
                v[idx] = old + 1e-6
                lp = net.loss_grad(*a)[0]["loss"]
                v[idx] = old - 1e-6
                lm = net.loss_grad(*a)[0]["loss"]
                v[idx] = old
                num, an = (lp - lm) / 2e-6, G[k][idx]
                if abs(num - an) > 1e-7:
                    worst = max(worst, abs(num - an) / (abs(num) + abs(an)))
        self.assertLess(worst, 1e-4)

    def test_causality_and_receptive_field(self):                       # J.1 (operator)
        import numpy as np
        from masterquo.lab.scalp_net import CausalMTFTCN, receptive_field
        self.assertEqual((receptive_field(3, [1, 2, 4, 8, 16]), receptive_field(3, [1, 2, 4])), (125, 29))
        net = CausalMTFTCN(8, 8, 10, seed=17)
        rng = np.random.default_rng(1)
        x1, x5, c = rng.normal(size=(1, 8, 128)), rng.normal(size=(1, 8, 32)), rng.normal(size=(1, 10))
        base = net.predict(x1, x5, c, [0])["logits"]
        far = x1.copy()
        far[:, :, 2] += 5.0                                             # outside the 125-step field of the last step
        self.assertEqual(float(np.abs(net.predict(far, x5, c, [0])["logits"] - base).max()), 0.0)
        near = x1.copy()
        near[:, :, 3] += 5.0
        self.assertGreater(float(np.abs(net.predict(near, x5, c, [0])["logits"] - base).max()), 0.0)
        a = net.architecture()
        self.assertLess(a["params_total"], 100_000)
        ids = {n["layer_id"] for n in a["nodes"]}
        self.assertTrue(all(e["source_layer_id"] in ids and e["target_layer_id"] in ids for e in a["edges"]))

    def test_training_changes_weights_inference_does_not(self):         # J.5 / J.6
        import numpy as np
        from masterquo.lab import scalp_net as sn
        rng = np.random.default_rng(2)
        cfg = {"width": 6, "m1_len": 16, "m5_len": 6, "m1_dil": [1, 2], "m5_dil": [1]}
        net = sn.CausalMTFTCN(2, 2, 3, cfg, seed=17)
        n = 240
        m1 = rng.normal(size=(n, 2, 16))
        y = (m1[:, 0, -1] > 0).astype(int) * 1 + (m1[:, 0, -1] > 1).astype(int)       # learnable rule
        data = {"m1": m1, "m5": rng.normal(size=(n, 2, 6)), "ctx": rng.normal(size=(n, 3)), "side": rng.integers(0, 2, n), "y": y, "r": m1[:, 0, -1]}
        before = {k: v.copy() for k, v in net.p.items()}
        l0 = net.loss_grad(data["m1"], data["m5"], data["ctx"], data["side"], y, data["r"])[0]["loss"]
        sn.fit(net, data, np.arange(n), None, fixed_epochs=25, batch=32, lr=3e-3)
        l1 = net.loss_grad(data["m1"], data["m5"], data["ctx"], data["side"], y, data["r"])[0]["loss"]
        self.assertLess(l1, l0)
        self.assertTrue(any(not np.array_equal(before[k], net.p[k]) for k in net.p))
        snap = {k: v.copy() for k, v in net.p.items()}
        o1 = net.infer_with_telemetry(m1[:1], data["m5"][:1], data["ctx"][:1], [0])
        o2 = net.predict(m1[:1], data["m5"][:1], data["ctx"][:1], [0])
        self.assertTrue(all(np.array_equal(snap[k], net.p[k]) for k in net.p))
        np.testing.assert_allclose(o1["proba"], o2["proba"])
        self.assertTrue(all(l["finite_fraction"] == 1.0 for l in o1["layers"]))


class TestSnapshot(unittest.TestCase):
    def setUp(self):
        from masterquo.lab import nss
        self.nss = nss
        self.bars = gen_bars()

    def _T(self, minute):
        return (T0 + timedelta(minutes=minute)).timestamp()

    def test_prefix_invariance_and_htf_asof(self):                     # J.1 / J.2
        import numpy as np
        T = self._T(2000)
        full = self.nss.snapshot(self.nss.index_bars(self.bars), T, setup_feats())
        cut = {tf: [b for b in bb if datetime.fromisoformat(b["open_utc"]).timestamp() < T] for tf, bb in self.bars.items()}
        pre = self.nss.snapshot(self.nss.index_bars(cut), T, setup_feats())
        self.assertEqual(full["status"], "OK")
        np.testing.assert_array_equal(full["m1"], pre["m1"])
        np.testing.assert_array_equal(full["ctx"], pre["ctx"])
        h1 = self.nss.index_bars(self.bars)["H1"]
        last = h1.upto(T, 1)[-1]
        self.assertLessEqual(datetime.fromisoformat(last["open_utc"]).timestamp() + 3600, T)          # closed before T
        Tb = self._T(1980)                                                   # an H1 closes exactly at 33:00 -> included at the boundary
        self.assertEqual(datetime.fromisoformat(h1.upto(Tb, 1)[-1]["open_utc"]), T0 + timedelta(minutes=1920))
        changed = {tf: [dict(b) for b in bb] for tf, bb in self.bars.items()}
        for b in changed["M1"][2001:]:
            b["c"] += 50.0                                                   # future change
        again = self.nss.snapshot(self.nss.index_bars(changed), T, setup_feats())
        np.testing.assert_array_equal(full["m1"], again["m1"])

    def test_warmup_gap_duplicate_zero_atr_missing(self):              # J.3
        idx = lambda b: self.nss.index_bars(b)  # noqa: E731
        self.assertEqual(self.nss.snapshot(idx(self.bars), self._T(100), setup_feats())["status"].split(":")[0], "WARMING_UP")
        gap = {tf: list(bb) for tf, bb in self.bars.items()}
        gap["M1"] = [b for b in gap["M1"] if not (1900 <= (datetime.fromisoformat(b["open_utc"]) - T0).total_seconds() / 60 < 1995)]
        self.assertEqual(self.nss.snapshot(idx(gap), self._T(2000), setup_feats())["status"], "DATA_GAP")
        dup = {tf: list(bb) for tf, bb in self.bars.items()}
        dup["M1"] = dup["M1"][:1990] + [dup["M1"][1989]] + dup["M1"][1990:]
        self.assertTrue(self.nss.snapshot(idx(dup), self._T(2000), setup_feats())["status"].startswith("INVALID_FEATURES"))
        flat = {tf: [dict(b, o=1.0, h=1.0, l=1.0, c=1.0) for b in bb] for tf, bb in self.bars.items()}
        self.assertTrue(self.nss.snapshot(idx(flat), self._T(2000), setup_feats())["status"].startswith("INVALID_FEATURES"))
        nosp = gen_bars(spread=False)
        self.assertEqual(self.nss.snapshot(idx(nosp), self._T(2000), setup_feats())["status"], "DATA_GAP:SPREAD_UNKNOWN")
        bad = setup_feats()
        bad["er10"] = float("nan")
        self.assertEqual(self.nss.snapshot(idx(self.bars), self._T(2000), bad)["status"], "INVALID_FEATURES:SETUP")


def gen_table(n=600, seed=1):
    import numpy as np
    from masterquo.lab import nss
    rng = np.random.default_rng(seed)
    t0 = datetime(2026, 1, 5, tzinfo=UTC)
    rows, M1, M5, C = [], [], [], []
    for k in range(n):
        t = t0 + timedelta(minutes=97 * k)
        m1, m5, c = rng.normal(size=(8, 20)), rng.normal(size=(8, 8)), rng.normal(size=len(nss.ctx_names()))
        z = 1.5 * m1[0, -1]
        pr = np.array([math.exp(z), 1.0, 0.4])
        y = int(rng.choice(3, p=pr / pr.sum()))
        r = [0.9, -1.0, 0.05][y] + rng.normal(0, 0.2)
        rows.append({"setup_id": f"S{k}", "range_id": f"R{k // 3}", "side": "BUY" if k % 2 == 0 else "SELL", "signal_time": t.isoformat(),
                     "label_end": (t + timedelta(minutes=30)).isoformat(), "net_r": r, "net_price": r, "spread": 0.1, "risk": 1.0, "ambiguous": False, "event": y})
        M1.append(m1)
        M5.append(m5)
        C.append(c)
    arr = {"m1": np.array(M1), "m5": np.array(M5), "ctx": np.array(C), "side": np.array([k % 2 for k in range(n)]), "y": np.array([r["event"] for r in rows]),
           "r": np.array([r["net_r"] for r in rows])}
    return {"instrument": "XAUUSD", "symbol": "XAUUSD-", "dataset_id": "gen", "data_kind": "SYNTHETIC_TEST", "content_hash": "gen", "profile_id": "p", "profile_hash": "h1",
            "costs": {"commission_per_lot_side": 0.0, "commission_source": "TEST"}, "availability_basis": "GENERATED", "population": "generated", "skipped": {},
            "cfg": {"m1_len": 20, "m5_len": 8, "m1_dil": [1, 2], "m5_dil": [1], "width": 8}, "tick": 0.01, "rows": rows, "arr": arr,
            "prof": {"exits": {"max_hold_minutes": {"value": 30}}}}


class TestProtocolBundleRegistry(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_protocol_bundle_parity_scope_and_registry(self):          # J.7-J.12
        import numpy as np
        from masterquo.db.database import Database
        from masterquo.lab import nss
        db = Database()
        data = gen_table()
        rep = nss.run_protocol("XAUUSD", data, db=db, train_cfg={"members": [17, 29], "epochs": 6, "patience": 2}, log=lambda m: None)
        self.assertEqual((rep["status"], rep["role"]), ("EVALUATED", "FIXTURE_ONLY"))
        self.assertTrue(all(v["status"] == "FIXTURE_ONLY" for v in rep["sides"].values()))
        self.assertEqual(rep["ledger"]["status"], "FRESH")
        reg = json.loads((nss.root("XAUUSD") / "registry.json").read_text())
        e = reg["runs"][rep["run_id"]]
        self.assertIn("fixture_runs", e["run_dir"])
        self.assertIsNone(reg["selected"])                                       # never promoted automatically
        b = nss.load_bundle(Path(e["run_dir"]) / "bundle")
        self.assertEqual(b.man["model_hash"], rep["model_hash"])                 # evaluated == saved == loaded (J.12)
        self.assertEqual(b.man["class_order"], ["TP1_FIRST", "SL_FIRST", "TIMEOUT"])
        arr = data["arr"]
        raw = b.ens.raw(arr["m1"][:5], arr["m5"][:5], arr["ctx"][:5], arr["side"][:5])
        b2 = nss.load_bundle(Path(e["run_dir"]) / "bundle")
        np.testing.assert_allclose(raw["proba"], b2.ens.raw(arr["m1"][:5], arr["m5"][:5], arr["ctx"][:5], arr["side"][:5])["proba"])   # J.7
        snap = {"status": "OK", "m1": arr["m1"][0], "m5": arr["m5"][0], "ctx": arr["ctx"][0]}
        ok = b.predict(snap, instrument="XAUUSD", profile_hash="h1", side="BUY", telemetry=True)
        self.assertEqual(ok["technical_status"], "READY_INFERENCE")
        np.testing.assert_allclose(ok["candidate_output"]["raw_probabilities"], raw["proba"][0])
        self.assertAlmostEqual(sum(ok["candidate_output"]["raw_probabilities"]), 1.0, places=9)
        self.assertEqual(ok["telemetry_member"], "member_17")
        for kw, st in (({"instrument": "BTC", "profile_hash": "h1", "side": "BUY"}, "ERROR"), ({"instrument": "XAUUSD", "profile_hash": "zz", "side": "BUY"}, "ERROR"),
                       ({"instrument": "XAUUSD", "profile_hash": "h1", "side": "UP"}, "ERROR"),
                       ({"instrument": "XAUUSD", "profile_hash": "h1", "side": "BUY", "entry_mode": "LIMIT_EDGE"}, "UNSUPPORTED_ENTRY_POLICY")):
            self.assertEqual(b.predict(snap, **kw)["technical_status"], st)                                     # J.8 / J.14
        self.assertEqual(b.predict(dict(snap, status="DATA_GAP"), instrument="XAUUSD", profile_hash="h1", side="BUY")["technical_status"], "DATA_GAP")
        with self.assertRaisesRegex(ValueError, "FIXTURE_ONLY"):
            nss.select("XAUUSD", rep["run_id"], "OBSERVE")
        bd = Path(e["run_dir"]) / "bundle"
        (bd / "member_29.npz").write_bytes((bd / "member_29.npz").read_bytes()[:-3])
        with self.assertRaisesRegex(ValueError, "CHECKSUM"):
            nss.load_bundle(bd)
        rep2 = nss.run_protocol("XAUUSD", data, db=db, train_cfg={"members": [17], "epochs": 2, "patience": 1}, log=lambda m: None)
        self.assertEqual(rep2["ledger"]["status"], "REUSED_PERIOD_EXPLORATORY")                                # J.11

    def test_holdout_never_in_fit_blocks(self):                        # J.9
        import numpy as np
        from masterquo.lab import nss
        from masterquo.ml import scalp_task as stk
        data = gen_table(300)
        rows = data["rows"]
        t = np.array([nss._ts(r["signal_time"]) for r in rows])
        cut = t.min() + 0.8 * (t.max() - t.min())
        dev = stk._purged(np.where(t < cut)[0], rows, cut, 1800.0)
        blocks = stk.inner_blocks(dev, rows, 1800.0)
        used = set(np.concatenate(list(blocks.values())).tolist())
        self.assertFalse(used & set(np.where(t >= cut)[0].tolist()))
        self.assertTrue(all(nss._ts(rows[i]["label_end"]) < cut - 1800.0 for i in dev))

    def test_select_rollback_real_run(self):
        from masterquo.lab import nss
        rd = nss.root("XAUUSD") / "runs" / "R1"
        rd.mkdir(parents=True)
        reg = {"schema": "pmw-nss-registry-1", "selected": None, "history": [], "runs": {"R1": {"run_dir": str(rd), "status": "EVALUATED", "role": "RESEARCH",
                                                                                                   "model_hash": "x", "sides": {"BUY": "NO_VALIDATED_EDGE"}}}}
        (nss.root("XAUUSD") / "registry.json").write_text(json.dumps(reg))
        with self.assertRaisesRegex(ValueError, "SHADOW_GATE_REQUIRES_HOLDOUT_PASSED"):
            nss.select("XAUUSD", "R1", "SHADOW_GATE")
        with self.assertRaises(Exception):                                       # no bundle on disk -> never selected
            nss.select("XAUUSD", "R1", "OBSERVE")
        with self.assertRaisesRegex(ValueError, "NO_PREVIOUS"):
            nss.rollback("XAUUSD")


class _Bus:
    def __init__(self, db):
        self.ev, self.db = [], db

    def publish(self, k, v):
        row = self.db.one("SELECT inference_id FROM nss_inferences WHERE inference_id=?", (v.get("inference_id"),)) if v.get("inference_id") else None
        self.ev.append((k, v, row is not None))


class TestService(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def _wait(self, pred, t=10):
        end = time.time() + t
        while time.time() < end:
            if pred():
                return True
            time.sleep(0.05)
        return False

    def test_queue_context_stale_and_archive_before_publish(self):     # J.16-J.20
        from masterquo.db.database import Database
        from masterquo.lab.nss_service import QUEUE_MAX, NeuralScalpService
        db = Database()
        bus = _Bus(db)
        s = NeuralScalpService(db, bus, None, instrument="XAUUSD")
        bars = gen_bars()
        T = (T0 + timedelta(minutes=2000)).timestamp()
        tail = {tf: [b for b in bb if datetime.fromisoformat(b["open_utc"]).timestamp() < T] for tf, bb in bars.items()}
        for b in tail["M1"]:
            b["spread"] = 12
        plan = {"setup_id": "SET-1", "range_id": "R", "direction": "BUY", "decision_ts": T, "decision_time": datetime.fromtimestamp(T, UTC).isoformat(),
                "sl": 1.0, "tp1": 2.0, "tp2": 3.0, "entry_mode": "MARKET", "features": setup_feats()}
        for i in range(QUEUE_MAX + 3):                                           # bounded queue (worker not started yet)
            s.submit(dict(plan, setup_id=f"SET-{i}"), tail, instrument="XAUUSD", profile_hash="h", epoch=1, point=0.01)
        self.assertEqual((len(s.q), s.stats["dropped_full"]), (QUEUE_MAX, 3))
        s.reset("BTC", 1)                                                        # asset switch drops pending work
        self.assertEqual(len(s.q), 0)
        s.start()
        try:
            s.on_m1(tail, instrument="XAUUSD", epoch=1, point=0.01)
            self.assertTrue(self._wait(lambda: s.context is not None))
            self.assertEqual((s.context["telemetry_scope"], s.context["candidate_output"], s.context["technical_status"]), ("CONTEXT_ONLY", None, "NO_MODEL"))
            s.submit(plan, tail, instrument="XAUUSD", profile_hash="h", epoch=1, point=0.01)
            self.assertTrue(self._wait(lambda: s.last is not None))
            last = s.last
            self.assertEqual((last["technical_status"], last["candidate_output"]), ("NO_MODEL", None))                  # no fake probability
            row = db.one("SELECT * FROM nss_inferences WHERE inference_id=?", (last["inference_id"],))
            self.assertEqual((row["snapshot_hash"], row["label_status"]), (last["snapshot_hash"], "PENDING"))
            ev = [e for e in bus.ev if e[0] == "lab_neural"]
            self.assertTrue(ev and ev[-1][2])                                      # row existed when the event was published
            pub = s.public("XAUUSD")
            self.assertEqual(pub["snapshot"]["inference_id"], last["inference_id"])
            self.assertEqual(s.public("BTC")["status"], "ASSET_NOT_ACTIVE")
            n_before = len(bus.ev)
            s.epoch = 2                                                              # reconnect: an old-session request is discarded
            s.q.append({"request_id": "old", "plan": plan, "bars": tail, "instrument": "XAUUSD", "profile_hash": "h", "epoch": 1, "mode": "OBSERVE",
                        "enqueued": time.time()})
            with s._cv:
                s._cv.notify()
            self.assertTrue(self._wait(lambda: s.stats["stale_discarded"] >= 1))
            self.assertEqual(len(bus.ev), n_before)
            s.epoch = 1
            s._candidate({"request_id": "late", "plan": dict(plan, setup_id="SET-T"), "bars": tail, "instrument": "XAUUSD", "profile_hash": "h", "epoch": 1,
                          "mode": "OBSERVE", "enqueued": time.time() - 5})
            self.assertEqual(s.last["technical_status"], "TIMEOUT")
            s.label(last["inference_id"], "MISSED_LIMIT", None)
            self.assertEqual(db.one("SELECT label_status FROM nss_inferences WHERE inference_id=?", (last["inference_id"],))["label_status"], "NO_EXECUTABLE_ENTRY")
            s.label(s.last["inference_id"], "SETTLED", {"net_r": -0.4, "label_end": "x", "exits": [{"reason": "TIME"}]})
            r = db.one("SELECT label_status, label_event, label_net_r FROM nss_inferences WHERE inference_id=?", (s.last["inference_id"],))
            self.assertEqual((r["label_status"], r["label_event"], r["label_net_r"]), ("LABELED", "TIMEOUT", -0.4))
        finally:
            s.stop()

    def test_no_order_path(self):                                         # J.22
        import masterquo.lab.nss as m1
        import masterquo.lab.nss_service as m2
        for m in (m1, m2):
            src = Path(m.__file__).read_text(encoding="utf-8")
            self.assertNotIn("order_send", src)
            self.assertNotIn("gateway", src.replace("no path to the gateway", ""))


if __name__ == "__main__":
    unittest.main()
