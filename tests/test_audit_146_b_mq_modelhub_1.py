"""1.46 audit, group B_mq_modelhub_1 - regression tests for modelhub/aggregate.py, modelhub/catalog.py and the model families
(base / run / micro / garch / rl / seq / breakout / cli / nlp / pairs). Synthetic data only, no MT5, no HTTP server, no .venv_deep."""
from __future__ import annotations

import io
import json
import math
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import _env  # noqa: F401
import numpy as np
from _env import TempData

T0 = 1_772_409_600  # 2026-03-02 00:00 UTC


def _bars(n, tf_s=300, seed=1, spread=20):
    rng = np.random.default_rng(seed)
    c, out = 2000.0, []
    for i in range(n):
        o = c
        c = c * math.exp(rng.normal(0, 1e-3))
        out.append({"t": T0 + i * tf_s, "o": o, "h": max(o, c) + 0.1, "l": min(o, c) - 0.1, "c": c, "tv": 50, "spread": spread})
    return out


def _books(n=6000, seed=3):
    rng = np.random.default_rng(seed)
    books, mid = [], 2000.0
    for i in range(n):
        qb, qa = float(rng.integers(1, 10)), float(rng.integers(1, 10))
        books.append({"t": float(i), "bids": [(mid - 0.05, qb), (mid - 0.15, 3.0)], "asks": [(mid + 0.05, qa), (mid + 0.15, 3.0)]})
        mid += 0.01 * np.sign(qb - qa) + rng.normal(0, 0.002)
    return books


# ---------------------------------------------------------------------------------------------------------------- aggregate (PMW-AGG-1)
class TestAggregate(unittest.TestCase):
    def _p(self, key, **kw):
        from masterquo.modelhub import contract as C
        d = {"instrument": "XAUUSD", "symbol": "XAUUSD-", "timeframe": "M5", "model_name": key.split("_M5")[0], "model_version": "v1",
             "task_type": "CLASS_PROBABILITIES", "task": "DIRECTION_H6_M5", "horizon_bars": 6, "unit": "probability", "state": "READY",
             "result": {"DOWN": 0.2, "FLAT": 0.3, "UP": 0.5}, "data_time": "2026-11-02T10:00:00Z",
             "calibration": {"method": "t", "status": "CALIBRATED_DEV"}, "extra": {"model_key": key}}
        d.update(kw)
        return C.make(**d)

    def test_zero_dev_skill_speaks_before_negative_skill(self):
        """chunk_23#19: `x[0] or -1` turned a valid skill 0.0 into -1 - the model with skill -0.5 became the group speaker.
        arch146 D12: a skill <= 0 is no better than the baseline - neither model speaks now; the ranking (0.0 before -0.5) still holds."""
        from masterquo.modelhub import aggregate as AG
        skills = {"TH_LOGREG_M5_H6": 0.0, "TH_HGB_M5_H6": -0.5}
        neg, zero = self._p("TH_HGB_M5_H6"), self._p("TH_LOGREG_M5_H6")
        with mock.patch.object(AG, "dev_skill", side_effect=lambda inst, key, ver: skills[key]):
            for order in ([neg, zero], [zero, neg]):
                g = AG.evidence(order, "SCALPING", "XAUUSD")["groups"][0]
                self.assertIsNone(g["speaker"])                                   # never the -0.5 model
                self.assertEqual([x["model"] for x in g["silenced_same_group"]], ["TH_LOGREG_M5_H6", "TH_HGB_M5_H6"])

    def test_none_skill_still_last(self):
        """An unmeasured skill ranks after any model that may speak; a model measured as worse than the baseline (arch146 D12) never
        speaks - the unmeasured one does (weight 0)."""
        from masterquo.modelhub import aggregate as AG
        for skills, speaker in (({"TH_LOGREG_M5_H6": None, "TH_HGB_M5_H6": 0.3}, "TH_HGB_M5_H6"),
                                ({"TH_LOGREG_M5_H6": None, "TH_HGB_M5_H6": -0.5}, "TH_LOGREG_M5_H6")):
            with mock.patch.object(AG, "dev_skill", side_effect=lambda inst, key, ver, s=skills: s[key]):
                g = AG.evidence([self._p("TH_LOGREG_M5_H6"), self._p("TH_HGB_M5_H6")], "SCALPING", "XAUUSD")["groups"][0]
            self.assertEqual(g["speaker"], speaker)

    def test_excluded_ready_without_model_key_has_a_name(self):
        """chunk_23#24: an unrouted READY family record (no model_key) was listed as {'model': None}."""
        from masterquo.modelhub import aggregate as AG
        from masterquo.modelhub import contract as C
        g = C.make(instrument="XAUUSD", symbol="XAUUSD-", timeframe="M5", model_name="VOL_GARCH", model_version="r1", task_type="VOLATILITY",
                   task="SIGMA_LOG_RETURN_H", horizon_bars=6, unit="sigma_return", state="READY",
                   result={"sigma": 0.003, "variance": 9e-6, "scale": "decimal"}, data_time="2026-11-02T10:00:00Z")
        ev = AG.evidence([g], "SCALPING", "XAUUSD")
        self.assertEqual(ev["excluded"], [{"model": "VOL_GARCH", "state": "READY", "reason": "brak jawnego mapowania zadania na rolę strategii"}])


# ---------------------------------------------------------------------------------------------------------------- catalog (PMW-CATALOG-1)
class TestCatalogTrainhub(unittest.TestCase):
    @staticmethod
    def _reg():
        return {"versions": {"TH_LOGREG_M5_H6": [{"version": "v1"}], "TH_HGB_M5_H6": [{"version": "v1"}, {"version": "v2"}]},
                "active": {"TH_LOGREG_M5_H6": "v1"}}

    def _row(self, rt, mid="th_logreg"):
        from masterquo.modelhub import catalog as CAT
        with mock.patch("masterquo.trainhub.registry.registry", return_value=self._reg()), \
                mock.patch("masterquo.trainhub.learn.available", return_value={k: True for k in
                                                                               ("TH_BASELINE", "TH_LOGREG", "TH_HGB", "TH_XGB", "TH_RF", "TH_SVM")}):
            rows = CAT._th_entries("XAUUSD", rt)
        return next(r for r in rows if r["id"] == mid)

    @staticmethod
    def _rt(inf):
        return type("RT", (), {"trainhub": None, "trainhub_inference": inf})()

    def test_active_version_without_prediction_is_not_ready(self):
        """chunk_23#20: an active package with no prediction was READY 'waiting for the first candle'."""
        inf = type("I", (), {"predictions": lambda self, inst: []})()
        r = self._row(self._rt(inf))
        self.assertEqual(r["state"], "BLOCKED_DATA")
        self.assertIn("czeka na pierwszą zamkniętą świecę", r["reason"])

    def test_no_inference_service_or_failure_is_not_ready(self):
        r = self._row(self._rt(None))
        self.assertEqual(r["state"], "DISABLED")
        self.assertIn("serwis inferencji", r["reason"])

        def boom(self, inst):
            raise RuntimeError("cache broken")
        r = self._row(self._rt(type("I", (), {"predictions": boom})()))
        self.assertEqual(r["state"], "ERROR")
        self.assertIn("RuntimeError: cache broken", r["reason"])

    def test_ready_prediction_still_ready(self):
        p = {"model_key": "TH_LOGREG_M5_H6", "state": "READY", "unavailable_reason": None}
        r = self._row(self._rt(type("I", (), {"predictions": lambda self, inst: [p]})()))
        self.assertEqual(r["state"], "READY")

    def test_versions_without_active_message(self):
        """chunk_23#25: the branch 'no version active' said 'żadna nieaktywna' (= all active)."""
        r = self._row(self._rt(None), "th_hgb")
        self.assertEqual(r["state"], "DISABLED")
        self.assertIn("2 wersji, żadna nie jest aktywna", r["reason"])
        self.assertNotIn("żadna nieaktywna", r["reason"])


# ---------------------------------------------------------------------------------------------------------------- artifact store
class TestTmpSweep(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="fam146_")
        from masterquo.modelhub.families import base as B
        self.B = B
        self.store = B.Store(Path(self.td))

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def _tmp(self, name, owner_pid=None, age_s=0.0):
        d = self.store.fam_dir("SEQ_LSTM", "XAUUSD") / name
        d.mkdir()
        (d / "seq_data.npz").write_bytes(b"x" * 1000)
        if owner_pid is not None:
            (d / self.B.Store.OWNER).write_text(json.dumps({"pid": owner_pid}), encoding="utf-8")
        if age_s:
            t = time.time() - age_s
            os.utime(d, (t, t))
        return d

    def test_orphaned_tmp_dirs_are_removed_running_ones_kept(self):
        """chunk_23#17: a cancelled / crashed training left .tmp-<run> (SEQ: the whole dataset) forever."""
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        p.wait()
        dead = self._tmp(".tmp-dead", owner_pid=p.pid)
        live = self._tmp(".tmp-live", owner_pid=os.getpid())
        legacy_new = self._tmp(".tmp-legacy-new")
        legacy_old = self._tmp(".tmp-legacy-old", age_s=2 * 86400)
        rid, tmp = self.store.new_run("SEQ_LSTM", "XAUUSD")
        self.assertFalse(dead.exists())
        self.assertFalse(legacy_old.exists())
        self.assertTrue(live.exists())                                   # a running training keeps its directory
        self.assertTrue(legacy_new.exists())
        self.assertEqual(json.loads((tmp / self.B.Store.OWNER).read_text(encoding="utf-8"))["pid"], os.getpid())
        (tmp / "model.json").write_text("{}", encoding="utf-8")
        final = self.store.commit("SEQ_LSTM", "XAUUSD", rid, tmp, {"validation": {"status": "CANDIDATE"}})
        self.assertFalse((final / self.B.Store.OWNER).exists())        # the marker is not part of the artifact
        man = json.loads((final / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(set(man["files"]), {"model.json"})
        self.assertEqual(self.store.verify("SEQ_LSTM", "XAUUSD", rid), (True, None))
        self.assertEqual([r["run_id"] for r in self.store.runs("SEQ_LSTM", "XAUUSD")], [rid])


# ---------------------------------------------------------------------------------------------------------------- VOL_GARCH horizon
class TestGarchHorizon(unittest.TestCase):
    def test_record_horizon_matches_sigma_horizon(self):
        """chunk_23#7: result = 6-bar sigma, but the PMW-PRED-2 record said horizon.bars = 1."""
        from masterquo.modelhub import contract as MC
        from masterquo.modelhub.families import garch as G
        f = G.GARCH()
        res = {"sigma": 0.0032, "variance": 0.0032 ** 2, "scale": "decimal", "sigma_bar": 0.0013, "horizon_bars": f.HORIZONS[1],
               "price_move_1sigma": 6.4, "horizons": {}, "note": "x"}
        p = f.pred(inst="XAUUSD", symbol="XAUUSD-", state="READY", result=res, run_id="r1", data_kind="REAL", data_time=float(T0))
        MC.validate(p)
        self.assertEqual(p["horizon"]["bars"], res["horizon_bars"])
        self.assertEqual(p["horizon"]["bars"], 6)
        e = f.pred(inst="XAUUSD", symbol="XAUUSD-", state="BLOCKED_DATA", reason="za mało świec", run_id="r1")
        self.assertEqual(e["horizon"]["bars"], 6)
        self.assertEqual(f.pred(inst="XAUUSD", symbol=None, state="READY", result=res, horizon_bars=12, data_time=float(T0))["horizon"]["bars"], 12)


# ---------------------------------------------------------------------------------------------------------------- MICROSTRUCTURE
class TestMicroWindow(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="fam146_")
        from masterquo.modelhub.families import base as B
        self.store = B.Store(Path(self.td))

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    @staticmethod
    def _live(window_s=None):
        """A live MICROSTRUCTURE measurement as IndicatorService.current() gives it (OF.compute); window_s set = the measurement
        declares its window (ofi_state.window_s), None = the IndicatorService accumulator (OFIAccumulator default, undeclared)."""
        from masterquo.indicators import ofi as OF
        acc = OF.OFIAccumulator(window_s=window_s) if window_s else OF.OFIAccumulator()
        books = _books(80, seed=9)
        for b in books:
            acc.add(b)
        last = books[-1]
        res = OF.compute(last, acc, instrument="XAUUSD", broker_symbol="XAUUSD-", status="READY", now=last["t"])
        if window_s:
            res["ofi_state"]["window_s"] = window_s
        return {"micro": res, "spread": last["asks"][0][0] - last["bids"][0][0]}

    def test_training_window_equals_live_window_and_mismatch_blocks_probabilities(self):
        """chunk_23#8: ofi_window was trained over 30 s, the live IndicatorService value sums 60 s (OFIAccumulator default)."""
        from masterquo.indicators import ofi as OF
        from masterquo.modelhub.families import micro as MI
        from masterquo.modelhub.families import run as RUN
        live_w = OF.OFIAccumulator().window_s
        r = RUN.train("MICROSTRUCTURE", "XAUUSD", "smoke", {}, data={"instrument": "XAUUSD", "books": _books(), "data_kind": "REAL"},
                      store=self.store)
        self.assertEqual(r["state"], "DONE", r)
        f = MI.Micro()
        art = f.load(self.store.run_dir("MICROSTRUCTURE", "XAUUSD", r["run_id"]))
        self.assertEqual(art["ofi_window_s"], live_w)
        for live in (self._live(), self._live(live_w)):                   # same window as IndicatorService -> probabilities
            ok = f.predict(art, live)
            self.assertIn("p_up_10s", ok)
            self.assertNotIn("classifier_state", ok)
        bad = f.predict(art, self._live(30.0))                           # another window -> measurements only, the reason
        self.assertNotIn("p_up_10s", bad)
        self.assertEqual(bad["classifier_state"], "INCOMPATIBLE")
        self.assertIsNotNone(bad["best_imbalance"])
        legacy = {k: v for k, v in art.items() if k != "ofi_window_s"}  # 1.33-1.45 artifact: trained on 30 s
        self.assertEqual(f.predict(legacy, self._live())["classifier_state"], "INCOMPATIBLE")
        self.assertIn("p_up_10s", f.predict(legacy, self._live(30.0)))

    def test_feature_window_default_is_live(self):
        from masterquo.indicators import ofi as OF
        from masterquo.modelhub.families import micro as MI
        books = _books(400, seed=5)
        X_def = MI.features_from_books(books)[0]
        X_live = MI.features_from_books(books, window_s=OF.OFIAccumulator().window_s)[0]
        X_30 = MI.features_from_books(books, window_s=30.0)[0]
        np.testing.assert_array_equal(X_def, X_live)
        self.assertFalse(np.array_equal(X_def[:, 2], X_30[:, 2]))


# ---------------------------------------------------------------------------------------------------------------- RL_PPO
class TestPPOPosition(unittest.TestCase):
    def test_unknown_position_is_blocked_not_flat(self):
        """chunk_23#22: live.get('position') or 0.0 - no receiver passes a position, every proposal assumed FLAT."""
        from masterquo.modelhub.families import base as B
        from masterquo.modelhub.families import deep as D
        from masterquo.modelhub.families import rl as RL
        f = RL.PPO()
        bars = _bars(60)
        with mock.patch.object(D, "call", return_value={"ok": True, "action": 1, "probs": [0.2, 0.6, 0.2]}) as call:
            with self.assertRaises(B.Unavailable) as cm:
                f.predict({"dir": "x"}, {"bars": bars})
            self.assertEqual(cm.exception.state, "BLOCKED_DATA")
            call.assert_not_called()
            res = f.predict({"dir": "x"}, {"bars": bars, "position": 0.0})   # an explicit flat position is a value
            self.assertEqual(res["action"], "FLAT")
            self.assertEqual(call.call_args[0][1]["position"], 0.0)


# ---------------------------------------------------------------------------------------------------------------- run.py data / manifest
class TestRunData(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def _book_db(self):
        db = Path(self.td.dir) / "indicators.sqlite"
        con = sqlite3.connect(str(db))
        con.execute("CREATE TABLE book_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, t REAL, bids TEXT, asks TEXT)")
        for sym, px in (("XAUUSD-", 2000.0), ("BTCUSD", 90000.0)):
            for i in range(100):
                bids = [[px - 0.1 * (k + 1), 1.0 + k] for k in range(20)]
                asks = [[px + 0.1 * (k + 1), 1.0 + k] for k in range(20)]
                con.execute("INSERT INTO book_snapshots(symbol, t, bids, asks) VALUES (?,?,?,?)", (sym, float(i), json.dumps(bids), json.dumps(asks)))
        con.commit()
        con.close()
        return db

    def test_books_one_symbol_newest_rows_limited(self):
        """chunk_23#9 + #10: the whole archive (every symbol, every level) was loaded into memory."""
        from masterquo.modelhub.families import run as RUN
        db = self._book_db()
        self.assertEqual(RUN.books_from_archive(db, None), [])          # no symbol -> nothing (1.45.0: every symbol)
        bk = RUN.books_from_archive(db, "XAUUSD-", limit=10, levels=5)
        self.assertEqual([b["t"] for b in bk], [float(i) for i in range(90, 100)])
        self.assertTrue(all(len(b["bids"]) == 5 and len(b["asks"]) == 5 and b["bids"][0][0] < 2001 for b in bk))
        self.assertEqual(len(RUN.books_from_archive(db, "XAUUSD-")), 100)

    def test_load_data_books_symbol_from_mapping_or_blocked(self):
        from masterquo.modelhub.families import registry
        from masterquo.modelhub.families import run as RUN
        db = str(self._book_db())
        fam = registry()["MICROSTRUCTURE"]
        d = RUN.load_data(fam, "XAUUSD", {"indicators_db": db})          # no store manifest: the mapping XAUUSD -> XAUUSD-
        self.assertEqual(d["symbol"], "XAUUSD-")
        self.assertEqual(len(d["books"]), 100)
        self.assertTrue(all(b["bids"][0][0] < 2001 for b in d["books"]))  # never BTC snapshots
        d = RUN.load_data(fam, "BTC", {"indicators_db": db})              # BTC has no broker symbol -> blocked with the reason
        self.assertEqual(d["books"], [])
        ok, why = fam.validate_data(d)
        self.assertFalse(ok)
        self.assertIn("brak symbolu brokera", why)

    def test_manifest_describes_the_training_slice(self):
        """chunk_23#11: rows / hash / range described the whole archive, fit used bars[-max_rows:]."""
        from masterquo.modelhub.families import base as B
        from masterquo.modelhub.families import run as RUN
        bars = _bars(4000)
        store = B.Store(Path(self.td.dir) / "fam")
        r = RUN.train("KALMAN_LS", "XAUUSD", "smoke", {}, data={"instrument": "XAUUSD", "point": 0.01, "data_kind": "REAL", "bars": bars},
                      store=store)
        self.assertEqual(r["state"], "DONE", r)
        man = store.runs("KALMAN_LS", "XAUUSD")[-1]["data"]
        used = bars[-RUN.BUDGETS["smoke"]["max_rows"]:]
        self.assertEqual(man["rows"], len(used))
        self.assertEqual(man["hash"], B.data_hash(used))
        self.assertEqual(man["range"], [used[0]["t"], used[-1]["t"]])
        self.assertEqual(man["rows_available"], 4000)

    def test_unknown_point_is_not_assumed(self):
        """chunk_23#12: without a symbol spec the point was 0.01 (10x the spread cost on a 3-digit XAUUSD broker)."""
        from masterquo.modelhub.families import registry
        from masterquo.modelhub.families import run as RUN
        fams = registry()
        bf = Path(self.td.dir) / "bars.json"
        bf.write_text(json.dumps({"source": "MT5_LIVE_BRIDGE", "symbol": "XAUUSD-", "tf": "M5", "bars": _bars(2000), "synthetic": False}),
                      encoding="utf-8")
        d = RUN.load_data(fams["BREAKOUT"], "XAUUSD", {}, str(bf))
        self.assertIsNone(d["point"])
        for fid in ("BREAKOUT", "SEQ_LSTM", "SEQ_GRU", "RL_PPO"):
            ok, why = fams[fid].validate_data(dict(d, bars=_bars(4000)))
            self.assertFalse(ok, fid)
            self.assertIn("rozmiar punktu", why)
        self.assertTrue(fams["TS_ARIMA"].validate_data(d)[0])            # families that do not convert the spread are unaffected
        r = RUN.train("BREAKOUT", "XAUUSD", "smoke", {}, data=d)
        self.assertEqual(r["state"], "BLOCKED")
        bf.write_text(json.dumps({"symbol": "XAUUSD-", "bars": _bars(2000), "synthetic": False, "point": 0.001}), encoding="utf-8")
        d = RUN.load_data(fams["BREAKOUT"], "XAUUSD", {}, str(bf))
        self.assertEqual(d["point"], 0.001)
        self.assertTrue(fams["BREAKOUT"].validate_data(d)[0])
        from masterquo.marketdata.store import Store
        Store().write_manifest("XAUUSD", {"symbol": "XAUUSD-", "symbol_spec": {"point": 0.01}})
        self.assertEqual(RUN.load_data(fams["TS_ARIMA"], "XAUUSD", {})["point"], 0.01)


# ---------------------------------------------------------------------------------------------------------------- CLI
class TestCliJobConfig(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_cli_train_passes_the_book_archive(self):
        """chunk_23#30: `families train` had no indicators_db - MICROSTRUCTURE always saw 0 snapshots."""
        from masterquo.modelhub.families import cli
        from masterquo.modelhub.families import run as RUN
        from masterquo.paths import data_dir
        seen = {}

        def fake_train(fid, inst, profile, cfg, *a, **k):
            seen.update(cfg)
            return {"state": "BLOCKED", "reason": "test", "family": fid}
        with mock.patch.object(RUN, "train", side_effect=fake_train), redirect_stdout(io.StringIO()):
            rc = cli.main(["train", "--instrument", "XAUUSD", "--family", "MICROSTRUCTURE"])
        self.assertEqual(rc, 3)
        self.assertEqual(seen.get("indicators_db"), str(data_dir() / "indicators" / "indicators.sqlite"))


# ---------------------------------------------------------------------------------------------------------------- NLP topics
class TestNlpTopics(unittest.TestCase):
    def test_whole_words_only(self):
        """chunk_23#28: 'rate' matched corporate / generate / separate, 'fed' matched FedEx / federation."""
        from masterquo.modelhub.families import nlp as NL
        self.assertEqual(NL.topics("Corporate earnings generate separate gains")["FED"], 0.0)
        self.assertEqual(NL.topics("FedEx joins the federation")["FED"], 0.0)
        self.assertEqual(NL.topics("Fed holds rates steady")["FED"], 1.0)
        self.assertEqual(NL.topics("Federal Reserve minutes")["FED"], 1.0)
        t = NL.topics("XAU/USD rallies as bullion demand jumps")
        self.assertEqual((t["GOLD"], t["USD"]), (1.0, 1.0))
        t = NL.topics("XAUUSD extends gains")
        self.assertEqual((t["GOLD"], t["USD"]), (1.0, 1.0))
        t = NL.topics("Gold rallies on Fed")
        self.assertEqual((t["GOLD"], t["FED"], t["BTC"]), (1.0, 1.0, 0.0))
        self.assertEqual(NL.topics("Bitcoins and cryptocurrency flows")["BTC"], 1.0)


# ---------------------------------------------------------------------------------------------------------------- STATARB matrix
class TestStatArbMatrix(unittest.TestCase):
    def test_matrix_linear_and_identical(self):
        """chunk_23#23: the per-series dict was rebuilt for every timestamp (O(n^2) - minutes on a full H1 history)."""
        from masterquo.modelhub.families import pairs as PR
        n = 5000
        rng = np.random.default_rng(7)
        series = [[{"t": T0 + i * 3600, "c": float(np.exp(5 + rng.normal(0, 0.01)))} for i in range(n) if (i + k) % 97] for k in range(3)]
        t0 = time.perf_counter()
        ts, R = PR.StatArb.matrix(series)
        dt = time.perf_counter() - t0
        common = sorted(set.intersection(*[{x["t"] for x in s} for s in series]))
        maps = [{x["t"]: x["c"] for x in s} for s in series]
        P = np.column_stack([[m[t] for t in common] for m in maps])
        np.testing.assert_array_equal(ts, np.asarray(common))
        np.testing.assert_allclose(R, np.diff(np.log(P), axis=0))
        self.assertLess(dt, 1.0)


if __name__ == "__main__":
    unittest.main()


class TestLiveBridgeDataKind(unittest.TestCase):
    """chunk_23#1 (live path): bars of the demo simulator (MarketBridge.synthetic = True) were labelled MT5_LIVE_BRIDGE (= REAL for the
    ASSIST gate). A real terminal (synthetic False) and an object without the flag keep MT5_LIVE_BRIDGE."""

    def test_simulator_bars_are_synthetic_test(self):
        import json
        import tempfile
        from pathlib import Path
        from unittest import mock

        from masterquo.modelhub.families import registry
        from masterquo.modelhub.families import run as R
        bars = [{"t": 1_700_000_000 + 300 * i, "o": 1.0, "h": 1.1, "l": 0.9, "c": 1.0 + 0.001 * (i % 7), "v": 1} for i in range(1200)]
        with tempfile.TemporaryDirectory() as td:
            for syn, want in ((True, "SYNTHETIC_TEST"), (False, "MT5_LIVE_BRIDGE"), (None, "MT5_LIVE_BRIDGE")):
                f = Path(td) / f"b{syn}.json"
                f.write_text(json.dumps({"source": "MT5_LIVE_BRIDGE", "symbol": "XAUUSD-", "tf": "M5", "bars": bars, "synthetic": syn}), encoding="utf-8")
                with mock.patch("masterquo.marketdata.store.Store.manifest", return_value={}), \
                        mock.patch("masterquo.modelhub.families.base.bars_from_store", return_value=[]):
                    d = R.load_data(registry()["TS_ARIMA"], "XAUUSD", {}, str(f))
                self.assertEqual(d["data_kind"], want, syn)
