"""1.46 audit, group B_mq_lab_2: lab/market.py, market_service.py, market_v2.py, minirocket_v2.py, nss.py, nss_cli.py, protocol.py,
quotes.py, scenarios.py, sessions.py.

Module-level tests only (no demo server, no socket). All market data is SYNTHETIC; a passing test proves a code path, not an edge."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import threading
import time
import types
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

import _env  # noqa: F401
import numpy as np
from _env import TempData


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ============================================================================= lab/market.py
class TestLiquidityPools(unittest.TestCase):
    def test_pivot_belongs_to_one_pool_only(self):
        """chunk_13#6: highs 100.00 / 100.30 / 100.15 with tol 0.216 - 100.15 was counted in two EQUAL_HIGHS pools (4 'touches' from 3 pivots)."""
        from masterquo.lab import market
        T0 = 1_767_225_600
        bars = [{"open_utc": _iso(T0 + 300 * i), "o": 99.0, "h": 100.08, "l": 97.92, "c": 99.0, "tv": 100} for i in range(60)]   # range 2.16 -> tol 0.216

        def pv(i, price):
            return {"kind": "H", "i": i, "price": price, "confirmed_i": i + 2, "origin_time": bars[i]["open_utc"], "confirmed_at": bars[i + 2]["open_utc"]}
        piv = [pv(10, 100.00), pv(20, 100.30), pv(30, 100.15)]
        with mock.patch.object(market, "pivots", return_value=piv):
            r = market.liquidity(bars, "M5")
        self.assertAlmostEqual(r["tolerance"], 0.216, places=3)
        above = [p for p in r["pools"] if p["side"] == "ABOVE" and p["kind"] in ("EQUAL_HIGHS", "SWING_HIGH")]
        self.assertEqual(sum(p["touches"] for p in above), 3, above)          # every pivot is in exactly one pool


# ============================================================================= lab/market_service.py
def _trend_bars(n=300, seed=3):
    from _bars import from_closes
    rng = np.random.default_rng(seed)
    return from_closes(list(100 + np.cumsum(rng.normal(0.15, 0.3, n))), spread=0.3)


def _band(k):
    return {x: k.bands[-1][x] for x in ("t", "state", "candidate", "strength")}


class TestMarketSections(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_revision_rebuild_does_not_resume_stale_checkpoint(self):
        """chunk_13#1: after a revision of the last bar the regime was restored from the checkpoint computed on the OLD close."""
        from masterquo.lab.market_service import MarketSections
        bars = _trend_bars()
        ms = MarketSections()
        ms.update("XAUUSD", "M1", bars, 0.01)
        rev = [dict(b) for b in bars]
        rev[-1] = dict(rev[-1], c=rev[-1]["c"] - 40, l=rev[-1]["c"] - 40.3)
        k = ms.update("XAUUSD", "M1", rev, 0.01)
        self.assertFalse(k.resumed)
        td2 = TempData()                                                         # clean replay of the revised window (no checkpoint)
        try:
            clean = MarketSections().update("XAUUSD", "M1", rev, 0.01)
            self.assertEqual(_band(k), _band(clean))
        finally:
            td2.close()                                                          # restores this test's data dir

    def test_restart_still_resumes_unrevised_checkpoint(self):
        """Regression guard of the fix above: a restart on the SAME bars resumes from the checkpoint (old files without the close too)."""
        from masterquo.lab.market_service import MarketSections, _Key
        bars = _trend_bars()
        k1 = MarketSections().update("XAUUSD", "M1", bars, 0.01)
        k2 = MarketSections().update("XAUUSD", "M1", bars, 0.01)
        self.assertTrue(k2.resumed)
        self.assertEqual(_band(k1), _band(k2))
        p = _Key("XAUUSD", "M1", 0.01).path
        ck = json.loads(p.read_text(encoding="utf-8"))
        ck.pop("last_c", None)                                                   # 1.45 checkpoint format
        p.write_text(json.dumps(ck), encoding="utf-8")
        self.assertTrue(MarketSections().update("XAUUSD", "M1", bars, 0.01).resumed)

    def test_views_take_the_state_lock(self):
        """chunk_13#2: swings()/swing() iterated MarketBehavior dicts without the lock the heartbeat's update() holds."""
        from masterquo.lab.market_service import MarketSections
        ms = MarketSections()
        k = ms.update("XAUUSD", "M1", _trend_bars(), 0.01)
        sid = next(iter(k.mb.swings))
        for name, call in (("swings", lambda: ms.swings(k)), ("swing", lambda: ms.swing("XAUUSD", sid)), ("regimes", lambda: ms.regimes(k)),
                           ("smma", lambda: ms.smma(k)), ("summary", lambda: ms.summary(k)), ("zscore", lambda: ms.zscore(k))):
            done = threading.Event()
            th = threading.Thread(target=lambda c=call, d=done: (c(), d.set()), daemon=True)
            with ms._lock:                                                       # update() in progress on another thread
                th.start()
                self.assertFalse(done.wait(0.3), f"{name}() did not wait for the state lock")
            self.assertTrue(done.wait(10), name)

    def test_calibrated_source_without_chosen_profile(self):
        """chunk_13#3 (consumer side): a calibration report without a chosen profile is not 'CALIBRATED_ON_DEV'."""
        from masterquo.lab import market_v2 as V
        from masterquo.lab.market_service import calibrated
        from masterquo.lab.structure_task import root
        (root("XAUUSD") / "market_profiles.json").write_text(json.dumps({"profiles": {
            V.REGIME_PROFILE: {"chosen": None, "status": "INSUFFICIENT_EVIDENCE"}, V.SMMA_PROFILE: {"chosen": None, "status": "INSUFFICIENT_EVIDENCE"}}}))
        c = calibrated("XAUUSD")
        self.assertEqual((c["source"], c["regime"], c["smma"]), ("DEFAULT", {}, {}))


# ============================================================================= lab/market_v2.py
class TestCalibrateProfiles(unittest.TestCase):
    def test_trial_without_events_is_not_chosen(self):
        """chunk_13#3: fb / max(1, nev) gave 0.0 for a trial with NO events, so min() picked it as the calibrated SMMA profile;
        with no REGIME trial meeting TRANSITION<80 % the first trial was 'chosen' anyway. chunk_13#12: smma_series was computed and discarded."""
        from _bars import from_closes
        from masterquo.lab import market_v2 as V
        rng = np.random.default_rng(7)
        bars = from_closes(list(100 + np.cumsum(rng.normal(0, 0.3, 1000))))

        class FakeChannel:
            def __init__(self, boundary="CURRENT_CLOSED", deadband=0.01, **kw):
                self.silent = boundary == "CURRENT_CLOSED" and abs(deadband - 0.04) < 1e-9
                self.i = -1

            def update(self, b):
                self.i += 1
                return {"event": None if self.silent or self.i % 5 else "UP"}

        def all_transition(ev, *a, **k):
            return {"series": [{"state": "TRANSITION"} for _ in ev]}
        with mock.patch.object(V, "SmmaChannel", FakeChannel), mock.patch.object(V, "regime_series", all_transition), \
                mock.patch.object(V, "smma_series", side_effect=AssertionError("smma_series result is never used")):
            rep = V.calibrate_profiles(bars, 0.01, [V.REGIME_PROFILE, V.SMMA_PROFILE])
        sm = rep["profiles"][V.SMMA_PROFILE]
        silent = next(t for t in sm["trials"] if t["boundary"] == "CURRENT_CLOSED" and t["deadband_ticks"] == 4)
        self.assertEqual(silent["events"], 0)
        self.assertIsNone(silent["false_break_5"])                              # no events = no measurement, not 0 %
        self.assertIsNotNone(sm["chosen"])
        self.assertNotEqual((sm["chosen"]["boundary"], sm["chosen"]["deadband_ticks"]), ("CURRENT_CLOSED", 4))
        rg = rep["profiles"][V.REGIME_PROFILE]
        self.assertIsNone(rg["chosen"])                                         # no trial qualifies -> defaults stay
        self.assertEqual(rg["status"], "INSUFFICIENT_EVIDENCE")


# ============================================================================= lab/minirocket_v2.py
class TestRidgeCG(unittest.TestCase):
    def test_zero_rhs_does_not_divide_by_zero(self):
        """chunk_13#0: a class absent from the FIT rows -> centred target column of zeros -> 0.0/0.0 ZeroDivisionError in cg_solve."""
        from masterquo.lab import minirocket_v2 as M
        x, info = M.cg_solve(lambda v: 2.0 * v, np.zeros(5), np.ones(5))
        self.assertTrue(np.array_equal(x, np.zeros(5)))
        self.assertTrue(info["converged"])
        rng = np.random.default_rng(0)
        Xs = rng.normal(size=(120, 10))
        Y = np.column_stack([rng.normal(size=120), np.zeros(120)])
        W, info = M.ridge_solve(Xs, Y, 1.0, method="CG")
        self.assertTrue(np.all(W[:, 1] == 0.0))
        self.assertTrue(info["converged"])

    def test_parity_cleans_temp_dir_and_closes_npz(self):
        """chunk_13#15: the --reference-python temp dir was never removed and np.load() handles were left open."""
        from masterquo.lab import minirocket_v2 as M
        fix = Path(__file__).resolve().parent / "fixtures" / "minirocket"
        if not (fix / "sktime_fixture.npz").exists():
            self.skipTest("SKIP: brak fixture sktime")
        opened = []
        real_load = np.load

        def spy_load(*a, **k):
            z = real_load(*a, **k)
            opened.append(z)
            return z
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(tempfile, "tempdir", td), mock.patch("subprocess.run", return_value=types.SimpleNamespace(returncode=1, stderr="no sktime")), \
                    mock.patch.object(np, "load", spy_load):
                r = M.parity(fix, reference_python=sys.executable)
            self.assertEqual(r["details"]["reference_run"]["status"], "BLOCKED")
            self.assertEqual(r["results"]["FROZEN_STATE_PARITY"], "PASS")
            self.assertEqual(list(Path(td).iterdir()), [])                       # mr2_ref_* removed
        self.assertTrue(opened)
        self.assertTrue(all(getattr(z, "zip", None) is None for z in opened))   # NpzFile closed


# ============================================================================= lab/nss.py
def _gen_bars(n_m1=6000, seed=4):
    from test_nss import gen_bars
    return gen_bars(n_m1, seed)


def _setup_feats():
    from test_nss import setup_feats
    return setup_feats()


T0_NSS = datetime(2026, 3, 2, 0, 0, tzinfo=UTC)


class TestNssSnapshot(unittest.TestCase):
    def test_stale_context_tf_is_data_gap(self):
        """chunk_14#7: M5/M15/H1 ending hours before T still gave snapshot OK (only gaps INSIDE the window were checked)."""
        from masterquo.lab import nss
        bars = _gen_bars()
        T = (T0_NSS + timedelta(minutes=5500)).timestamp()
        self.assertEqual(nss.snapshot(nss.index_bars(bars), T, _setup_feats())["status"], "OK")
        for tf, hours in (("H1", 10), ("M15", 6), ("M5", 3)):
            cut = dict(bars)
            cut[tf] = [b for b in bars[tf] if datetime.fromisoformat(b["open_utc"]).timestamp() < T - hours * 3600]
            s = nss.snapshot(nss.index_bars(cut), T, _setup_feats())
            self.assertEqual(s["status"], f"DATA_GAP:STALE_{tf}", tf)
            q = {i["tf"]: i["quality"] for i in s["inputs"]}
            self.assertEqual(q[tf], f"DATA_GAP:STALE_{tf}")

    def test_inputs_report_close_time_and_real_rows(self):
        """chunk_14#10: last_bar_close carried the OPEN time; M1/M5 rows were the configured length, not the bars available."""
        from masterquo.lab import nss
        bars = _gen_bars()
        T = (T0_NSS + timedelta(minutes=5530)).timestamp()
        s = nss.snapshot(nss.index_bars(bars), T, _setup_feats())
        inp = {i["tf"]: i for i in s["inputs"]}
        for tf in ("M1", "M5", "M15", "H1"):
            last = nss.index_bars(bars)[tf].upto(T, 1)[-1]
            self.assertEqual(nss._ts(inp[tf]["last_bar_close"]), nss._ts(last["open_utc"]) + nss.TF_S[tf], tf)
        short = {tf: bb[:40] if tf == "M1" else bb for tf, bb in bars.items()}
        s2 = nss.snapshot(nss.index_bars(short), (T0_NSS + timedelta(minutes=40)).timestamp(), _setup_feats())
        m1 = next(i for i in s2["inputs"] if i["tf"] == "M1")
        self.assertEqual((m1["quality"], m1["rows"]), ("WARMING_UP", 40))


def _bundle_fixture(inst="XAUUSD"):
    from masterquo.lab import nss
    from test_nss import gen_table
    data = gen_table(60)
    arr = data["arr"]
    net = nss.sn.CausalMTFTCN(len(nss.SEQ_CH), len(nss.SEQ_CH), arr["ctx"].shape[1], data["cfg"], seed=17)
    ens = nss.Ensemble([net], nss.fit_scaler(arr, np.arange(len(arr["y"]))))
    rep = {"instrument": inst, "symbol": "XAUUSD-", "profile_id": "p", "profile_hash": "h1", "role": "RESEARCH", "data_kind": "REAL_USER_DATA",
           "dataset_id": "d", "content_hash": "c", "costs": {}}
    rd = nss.root(inst) / "runs" / "R1"
    mh = nss.save_bundle(rd / "bundle", ens, rep, data)
    reg = {"schema": "pmw-nss-registry-1", "history": [],
           "selected": {"run_id": "R1", "role": "SHADOW_GATE", "model_hash": mh, "gated_sides": ["BUY"]},
           "runs": {"R1": {"run_dir": "C:/Users/old/AppData/Local/PepeMarketWizard/nss/XAUUSD/runs/R1", "status": "EVALUATED", "role": "RESEARCH",
                           "model_hash": mh, "sides": {"BUY": "HOLDOUT_PASSED"}}}}
    (nss.root(inst) / "registry.json").write_text(json.dumps(reg), encoding="utf-8")
    return rd, mh


class TestNssSelectedBundle(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.lab import nss
        nss._cache.clear()

    def tearDown(self):
        from masterquo.lab import nss
        nss._cache.clear()
        self.td.close()

    def test_moved_data_folder_and_missing_bundle(self):
        """chunk_14#2: run_dir is an ABSOLUTE path from another machine/profile -> load_bundle raised outside the try -> 500 on
        GET /api/v1/lab/neural and no nss_inferences row for the candidate."""
        import shutil

        from masterquo.db.database import Database
        from masterquo.lab import nss
        from masterquo.lab.nss_service import NeuralScalpService
        rd, mh = _bundle_fixture()
        b, sel = nss.selected_bundle("XAUUSD")                                   # same run under THIS data folder -> read-only fallback
        self.assertIsNotNone(b)
        self.assertEqual(b.man["model_hash"], mh)
        nss._cache.clear()
        shutil.rmtree(rd)
        b, sel = nss.selected_bundle("XAUUSD")
        self.assertIsNone(b)
        self.assertEqual(sel["status"], "ARTIFACT_UNAVAILABLE")
        self.assertEqual((sel["run_id"], sel["model_hash"]), ("R1", mh))
        self.assertEqual(sel["gated_sides"], [])                                 # no artefact -> no active shadow gate
        db = Database()
        s = NeuralScalpService(db, types.SimpleNamespace(publish=lambda *a: None), None, instrument="XAUUSD")
        pub = s.public("XAUUSD")                                                 # was FileNotFoundError -> HTTP 500
        self.assertFalse(pub["trained"])
        self.assertEqual(pub["selected"]["status"], "ARTIFACT_UNAVAILABLE")
        from test_nss import gen_bars
        bars = gen_bars()
        T = (T0_NSS + timedelta(minutes=2000)).timestamp()
        tail = {tf: [x for x in bb if datetime.fromisoformat(x["open_utc"]).timestamp() < T] for tf, bb in bars.items()}
        plan = {"setup_id": "SET-1", "range_id": "R", "direction": "BUY", "decision_ts": T, "decision_time": _iso(T), "sl": 1.0, "tp1": 2.0, "tp2": 3.0,
                "entry_mode": "MARKET", "features": _setup_feats()}
        s._candidate({"request_id": "r1", "plan": plan, "bars": tail, "instrument": "XAUUSD", "profile_hash": "h1", "epoch": s.epoch, "mode": "OBSERVE",
                      "enqueued": time.time()})
        self.assertTrue(s.last["archived"])
        self.assertFalse(s.last["shadow_gate_active"])
        self.assertIsNotNone(db.one("SELECT inference_id FROM nss_inferences WHERE inference_id=?", (s.last["inference_id"],)))

    def test_corrupted_bundle_is_unavailable_not_an_exception(self):
        from masterquo.lab import nss
        rd, _ = _bundle_fixture()
        f = rd / "bundle" / "member_17.npz"
        f.write_bytes(f.read_bytes()[:-3])
        b, sel = nss.selected_bundle("XAUUSD")
        self.assertIsNone(b)
        self.assertEqual(sel["status"], "ARTIFACT_UNAVAILABLE")
        self.assertIn("CHECKSUM", sel["reason"])


class _FakeTime:
    """Module `time` stand-in: time() jumps past every deadline once the final ensemble starts."""

    def __init__(self):
        import time as real
        self.real, self.jump = real, 0.0

    def __getattr__(self, k):
        return getattr(self.real, k)

    def time(self):
        return self.real.time() + self.jump


class TestNssBudget(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_final_ensemble_cut_by_budget_is_not_saved(self):
        """chunk_14#3: the deadline passing during the FINAL ensemble left members with 0 epochs (random weights) that were saved,
        evaluated on the holdout and reported EVALUATED."""
        from masterquo.lab import nss
        from test_nss import gen_table
        ft = _FakeTime()

        def log(m):
            if isinstance(m, str) and m.startswith("finalny"):
                ft.jump = 10.0 ** 6
        with mock.patch.object(nss, "time", ft):
            rep = nss.run_protocol("XAUUSD", gen_table(), db=None, train_cfg={"members": [17, 29], "epochs": 2, "patience": 1}, log=log)
        self.assertEqual(rep["status"], "BUDGET_EXCEEDED")
        self.assertIsNone(rep.get("model_hash"))
        rd = nss.root("XAUUSD") / "fixture_runs" / rep["run_id"]
        self.assertFalse((rd / "bundle").exists())
        reg = json.loads((nss.root("XAUUSD") / "registry.json").read_text(encoding="utf-8"))
        self.assertEqual(reg["runs"][rep["run_id"]]["status"], "BUDGET_EXCEEDED")


class TestNssPolicyReplay(unittest.TestCase):
    def test_baseline_same_population_and_not_ready_counted_apart(self):
        """chunk_14#8: the NSS replay (all exits) was compared with the FILTERED training rows (no EARLY_EXIT, no incomplete snapshots),
        and candidates without a READY inference were counted as policy rejections."""
        from masterquo.lab import nss
        cut = datetime(2026, 3, 10, tzinfo=UTC).timestamp()
        plans = [{"setup_id": f"S{i}", "direction": "BUY" if i % 2 == 0 else "SELL", "decision_time": _iso(cut + (i - 4) * 600),
                  "decision_ts": cut + (i - 4) * 600, "net_r": 0.5 if i % 3 else -1.0, "first_exit": "EARLY" if i % 4 == 0 else "TP1"} for i in range(16)]
        all_rows = [{"side": p["direction"], "signal_time": p["decision_time"], "net_r": p["net_r"], "first_exit": p["first_exit"]} for p in plans]
        keep = [r for r in all_rows if r["first_exit"] != "EARLY"]

        def fake_run(m1, prof, tick, costs, accept=None):
            cycles, blocked = [], []
            for p in plans:
                if accept is not None and not accept(dict(p, features={})):
                    blocked.append({"setup_id": p["setup_id"], "direction": p["direction"], "decision_time": p["decision_time"], "reason": "ML_POLICY_REJECTED"})
                    continue
                cycles.append(p)
            return {"cycles": cycles, "blocked": blocked}
        bl = types.SimpleNamespace(cfg={}, predict=lambda snap, **kw: {"technical_status": snap["status"].split(":")[0], "reason": snap["status"]})
        base_data = {"bars": {}, "m1": [{"open_utc": "x"}], "prof": {}, "tick": 0.01, "replay_costs": {}, "instrument": "XAUUSD", "profile_hash": "h1",
                     "rows": keep}
        exp_base = [r for r in all_rows if r["side"] == "BUY" and nss._ts(r["signal_time"]) >= cut]
        exp_nr = sum(1 for p in plans if p["direction"] == "BUY" and p["decision_ts"] >= cut)
        for data in (dict(base_data, all_rows=all_rows), base_data):            # dataset with the full population / older dict -> replay
            with mock.patch("masterquo.scalp.replay.run", fake_run):
                r = nss.policy_replay(data, 0, cut, bl)
            self.assertEqual(r["baseline_cycles"], len(exp_base))
            self.assertAlmostEqual(r["baseline_net_r_total"], sum(x["net_r"] for x in exp_base))
            self.assertEqual(r["rejected_by_policy"], 0)                          # WARMING_UP is not a policy decision
            self.assertEqual(r["rejected_nss_not_ready"], exp_nr)


class TestNssCli(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_report_unknown_run_is_blocked_not_traceback(self):
        """chunk_14#11: report --run <unknown> raised KeyError with a traceback instead of [BLAD] + exit 2."""
        from masterquo.lab import nss, nss_cli
        (nss.root("XAUUSD") / "registry.json").write_text(json.dumps({"runs": {"R1": {"run_dir": "/nonexistent"}}, "selected": None, "history": []}))
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = nss_cli.main(["report", "--asset", "XAUUSD", "--run", "NOPE"])
        self.assertEqual(rc, 2)
        self.assertIn("[BLAD]", buf.getvalue())
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = nss_cli.main(["report", "--asset", "XAUUSD", "--run", "R1"])        # registered, report file missing
        self.assertEqual(rc, 2)
        self.assertIn("[BLAD]", buf.getvalue())


# ============================================================================= lab/protocol.py
class TestXgbBestIteration(unittest.TestCase):
    def test_best_iteration_zero_is_one_tree_not_two_hundred(self):
        """chunk_14#4: `m.best_iteration or 200` turned a valid best_iteration 0 into 200 -> refit with 201 trees."""
        from masterquo.lab import protocol as P
        made = []

        class FakeXGB:
            def __init__(self, **kw):
                self.kw = kw
                made.append(self)

            def fit(self, X, y, **kw):
                if "early_stopping_rounds" in self.kw:
                    self.best_iteration = 0
                return self

            def predict_proba(self, X):
                return np.tile([0.5, 0.5], (len(X), 1))
        fake = types.ModuleType("xgboost")
        fake.XGBClassifier = FakeXGB
        rng = np.random.default_rng(0)
        with mock.patch.dict(sys.modules, {"xgboost": fake}):
            f = P.fit_family("XGB", rng.normal(size=(200, 4)), None, rng.integers(0, 2, 200), seed=1, budget=1)
        final = made[-1]
        self.assertNotIn("early_stopping_rounds", final.kw)
        self.assertEqual(final.kw["n_estimators"], 10)                           # max(10, 0 + 1), not 201
        self.assertEqual(f.cfg["trees"], 10)


# ============================================================================= lab/quotes.py
def _ticks(n=4000, seed=5):
    rng = np.random.default_rng(seed)
    mid = 2000 + np.cumsum(rng.normal(0, 0.02, n))
    return [{"t_ms": 1_700_000_000_000 + 250 * i + 7, "bid": round(m - 0.1, 2), "ask": round(m + 0.1, 2)} for i, m in enumerate(mid)]


class TestQuoteStress(unittest.TestCase):
    def _phases(self, ticks, cross_at=None):
        from masterquo.lab import quotes as Q
        eng = Q.QuoteEngine("X", 0.01, 0.01)
        out = []
        for s in range(0, len(ticks), 200):
            ch = ticks[s:s + 200]
            if cross_at == s:
                ch = ch[:5] + [dict(ch[5], bid=ch[5]["ask"] + 0.5)] + ch[5:]
            eng.ingest(ch)
            out.append(eng.snapshot(ch[-1]["t_ms"])["phase_raw"])
        return out, eng

    def test_one_crossed_quote_does_not_stress_the_session_forever(self):
        """chunk_14#5: one ask<bid tick added CROSSED_QUOTE to a never-cleared set -> STRESSED at every later snapshot."""
        tk = _ticks()
        clean, _ = self._phases(tk)
        crossed, eng = self._phases(tk, cross_at=1000)
        self.assertIn("CROSSED_QUOTE", eng.flags)                                # diagnostic flag kept
        self.assertEqual(crossed[6:], clean[6:])                                 # ~50 s later the quality event has expired
        self.assertTrue(any(p != "STRESSED" for p in clean[6:]))

    def test_fresh_quality_event_is_still_stressed(self):
        from masterquo.lab import quotes as Q
        tk = _ticks(1600)
        eng = Q.QuoteEngine("X", 0.01, 0.01)
        eng.ingest(tk[:1200])
        self.assertNotEqual(eng.snapshot(tk[1199]["t_ms"])["phase_raw"], "STRESSED")
        eng.ingest([dict(tk[1200], bid=tk[1200]["ask"] + 0.5)] + tk[1201:1205])
        self.assertEqual(eng.snapshot(tk[1204]["t_ms"])["phase_raw"], "STRESSED")
        eng2 = Q.QuoteEngine("X", 0.01, 0.01)
        eng2.ingest(tk[:1200])
        s2 = eng2.sides["BID"]                                                   # Side-level OUT_OF_ORDER now counts as well
        s2.push(s2.pending[0] - 5000, 1.0, eng2.origin_ms, eng2.cfg)
        self.assertIn("OUT_OF_ORDER", s2.flags)
        self.assertEqual(eng2.snapshot(tk[1199]["t_ms"])["phase_raw"], "STRESSED")
        self.assertNotEqual(eng2.snapshot(tk[1199]["t_ms"] + 60_000)["phase_raw"], "STRESSED")


# ============================================================================= lab/scenarios.py
class TestScenarioAnchor(unittest.TestCase):
    def test_held_breakout_state_keeps_setup_id(self):
        """chunk_14#9: ZSCORE scenarios were anchored on the CURRENT bar -> new setup_id / created_at / TTL every bar of the same state."""
        from masterquo.lab import market, scenarios
        T0 = 1_767_225_600
        rng = np.random.default_rng(1)
        cs = list(2000 + rng.normal(0, 0.3, 80)) + [2000 + 0.6 * 1.25 ** k for k in range(1, 15)]
        bars = [{"open_utc": _iso(T0 + 300 * i), "o": c, "h": c + 0.2, "l": c - 0.2, "c": c, "tv": 100} for i, c in enumerate(cs)]
        ids, created = set(), set()
        for n in range(85, len(bars) + 1):
            b = bars[:n]
            z = market.zscore(b)
            self.assertEqual(z["hypotheses_state"]["H_BO"], "LONG_CANDIDATE")
            ctx = {"asset": "XAUUSD", "symbol": "XAUUSD", "as_of": _iso(T0 + 300 * n), "last_close": b[-1]["c"], "fresh": True, "cost": {"spread_atr": 0.01},
                   "regime": None, "last_bar_open": {"M5": b[-1]["open_utc"], "M15": b[-1]["open_utc"]}}
            sc = [s for s in scenarios.build(ctx, {"M5": {"zscore": z}}, None) if s["kind"] == "ZSCORE_H_BO"]
            self.assertEqual(len(sc), 1)
            ids.add(sc[0]["setup_id"])
            created.add(sc[0]["created_at"])
        self.assertEqual(len(ids), 1)
        self.assertEqual(len(created), 1)
        start = datetime.fromisoformat(created.pop()).timestamp()
        self.assertLess(start, T0 + 300 * 84)
        ctx_late = dict(ctx, as_of=_iso(start + 25 * 300))
        late = next(s for s in scenarios.build(ctx_late, {"M5": {"zscore": z}}, None) if s["kind"] == "ZSCORE_H_BO")
        self.assertEqual(late["status"], "EXPIRED")                              # TTL reachable


# ============================================================================= lab/sessions.py
class TestMemorySequence(unittest.TestCase):
    def test_m3_host_and_naive_time(self):
        """chunk_14#6: tf=M3 passed the endpoint check but TF_SEC had no M3 -> KeyError 500; a naive t was read in local time."""
        from masterquo.lab.sessions import memory_sequence
        t0 = datetime(2026, 1, 15, 12, 0, tzinfo=UTC).timestamp()
        by = {"M1": [{"open_utc": _iso(t0 - 600 + 60 * i), "o": 1, "h": 2, "l": 0.5, "c": 1.5} for i in range(30)],
              "H1": [{"open_utc": _iso(t0), "o": 1, "h": 2, "l": 0.5, "c": 1.5}]}
        r = memory_sequence(by, "M3", "2026-01-15T12:00:00Z")
        self.assertEqual(r["host_close_utc"], "2026-01-15T12:03:00Z")
        self.assertEqual(len(r["projections"]["M1"]["bars"]), 3)
        self.assertEqual(r["projections"]["H1"]["relation"], "CONTAINING")
        with self.assertRaises(ValueError):
            memory_sequence(by, "M5", "2026-01-15T12:00:00")                    # naive -> rejected, never local time
        with self.assertRaises(ValueError):
            memory_sequence(by, "M7", "2026-01-15T12:00:00Z")


if __name__ == "__main__":
    unittest.main()
