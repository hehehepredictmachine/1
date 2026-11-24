"""1.46 audit, group B_ml_quant_2: quant/checks, events, metamodel, scheduler, service, snapshot, units, cli, inventory, features.

Stub bridges and isolated data dirs (TempData); no MT5, no server, no order path. All market data is SYNTHETIC."""
from __future__ import annotations

import contextlib
import io
import time
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest import mock

import _env  # noqa: F401
from _env import TempData
from test_quant_core import NOW, StubBridge, StubRt, bar, cand, pred


# =============================================================================================== checks: 1.45 gating kept (rule 1)
class TestChecksGatingAsIn145(unittest.TestCase):
    """chunk_26#5 (data_time basis of trainhub / Kronos / TSFM records) changes which records are eligible - it is on the owner's decision
    list; TTL and LATE_GENERATION stay measured from data_time exactly as in 1.45.0."""

    def test_close_producers_keep_145_ttl_and_late_generation(self):
        from masterquo.quant import checks as CK
        floor = {"M5": NOW - 300}                               # newest closed M5 bar opened 300 s ago
        self.assertTrue(CK.check(pred(age=300), now=NOW, generation_floor=floor)["eligible"])
        self.assertTrue(CK.check(pred(age=600), now=NOW, generation_floor=floor)["eligible"])
        self.assertEqual(CK.check(pred(age=700), now=NOW, generation_floor=floor)["reason"], "LATE_GENERATION:M5")
        for age in (650, 850):                                  # TTL = 3 bars from data_time
            self.assertTrue(CK.check(pred(age=age), now=NOW)["eligible"], age)
        self.assertEqual(CK.check(pred(age=950), now=NOW)["reason"].split(":")[0], "STALE")
        kr = pred(name="Kronos-small", task="KRONOS_CLOSE_PATH_H6_M5", age=850)
        self.assertTrue(CK.check(kr, now=NOW)["eligible"])


# =============================================================================================== events (chunk_26#8, #16)
class TestEventSpecFinite(unittest.TestCase):
    def _spec(self, **kw):
        from masterquo.quant import events as EV
        d = {"instrument": "XAUUSD", "strategy": "t", "direction": "LONG", "entry": 2000.0, "sl": 1998.0, "targets": ((2002.0, 0.5), (2004.0, 0.5)),
             "horizon_s": 600.0}
        d.update(kw)
        return EV.EventSpec(**d)

    def test_nan_and_inf_are_refused(self):
        from masterquo.quant import events as EV
        nan, inf = float("nan"), float("inf")
        for kw in ({"entry": nan}, {"sl": nan}, {"horizon_s": nan}, {"horizon_s": inf}, {"targets": ((nan, 1.0),)},
                   {"targets": ((2002.0, nan), (2004.0, 1.0))}, {"cost_price": nan}, {"entry": inf, "sl": 1998.0}):
            with self.assertRaises(EV.EventError, msg=str(kw)) as cm:
                self._spec(**kw)
            self.assertTrue(str(cm.exception).startswith("NOT_FINITE"), str(cm.exception))
        self.assertEqual(self._spec().R, 2.0)                  # a valid plan is unchanged

    def test_net_r_event_with_unknown_costs_is_no_label(self):
        from masterquo.quant import events as EV
        spec = self._spec(event_id="NET_R_POSITIVE", cost_price=None, targets=((2002.0, 1.0),), be_after=None)
        bars = [{"t": NOW + i * 60, "o": 2000.0, "h": 2003.0 if i == 2 else 2000.5, "l": 1999.5, "c": 2000.2} for i in range(12)]
        lab = EV.simulate(spec, bars, NOW, available_until=NOW + 12 * 60)
        self.assertTrue(lab["mature"])
        self.assertIsNone(lab["events"]["NET_R_POSITIVE"])
        self.assertIsNone(lab["y_event"])                      # unknown, never y = 0


# =============================================================================================== metamodel (chunk_26#2, #15)
class TestMetaModelPaths(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_traversal_in_instrument_task_or_version_is_refused(self):
        from pathlib import Path

        from masterquo.quant import metamodel as M
        outside = Path(self.td.dir) / "evil"
        for bad in ("../../evil", "..", "a/b", "", "/abs"):
            with self.assertRaises(M.MetaError):
                M.root(bad)
        with self.assertRaises(M.MetaError):
            M.load("XAUUSD", "../../evil", "v1")
        with self.assertRaises(M.MetaError):
            M.activate("XAUUSD", "t", "../../../evil")
        with self.assertRaises(M.MetaError):
            M.save("XAUUSD", {"model": {}, "status": "X", "report": {}}, spec={"task_hash": "../x"})
        self.assertEqual(M.pointer("../../evil")["active"], {})   # read side: empty pointer, nothing created
        self.assertFalse(outside.exists())
        self.assertFalse((Path(self.td.dir) / "quant" / "evil").exists())
        self.assertTrue(M.root("XAUUSD").is_dir())             # plain names still work

    def test_list_versions_newest_last(self):
        from masterquo.quant import metamodel as M
        from masterquo.quant.scheduler import write_json_atomic
        for th, ver, t in (("aaaa", "v-new", 2000.0), ("bbbb", "v-old", 1000.0), ("aaaa", "v-mid", 1500.0)):
            write_json_atomic(M.root("XAUUSD") / th / ver / "manifest.json",
                              {"task_hash": th, "version": ver, "status": "NOT_VALIDATED", "created_at": t, "report": {}})
        self.assertEqual([v["version"] for v in M.list_versions("XAUUSD")], ["v-old", "v-mid", "v-new"])
        self.assertEqual(M.list_versions("XAUUSD")[-1:][0]["version"], "v-new")


# =============================================================================================== scheduler (soft_deps capability)
class TestSchedulerSoftDeps(unittest.TestCase):
    def test_soft_dependency_keeps_the_successful_branch(self):
        from masterquo.quant.scheduler import Dag
        d = Dag()
        d.add("a", lambda c, _: 1, owner="x")
        d.add("good", lambda c, deps: [deps["a"]], deps=("a",), owner="x")
        d.add("bad", lambda c, deps: 1 / 0, deps=("a",), owner="x")
        d.add("join", lambda c, deps: (deps["good"], deps["bad"]), deps=("a",), soft_deps=("good", "bad"), owner="x")
        try:
            r = d.run({}, 1)
        finally:
            d.shutdown()
        self.assertEqual(r["tasks"]["join"]["status"], "OK")
        self.assertEqual(r["tasks"]["join"]["value"], ([1], None))
        self.assertFalse(r["complete"])


# =============================================================================================== service
class _Svc(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.quant.service import QuantService
        self.q = QuantService(StubRt())

    def tearDown(self):
        self.q.stop()
        self.td.close()


class TestConfidenceForSamePlan(_Svc):
    def test_other_sl_is_not_this_plan(self):
        now = self.q.clock()
        a = {"created_at": now, "strategy": "SCALPING", "direction": "LONG", "plan": {"entry": 2000.0, "sl": 1998.0, "targets": [[2003.0, 1.0]]},
             "event": {"event_id": "TP1_BEFORE_STOP"},
             "confidence": {"estimator_kind": "tabicl_v2", "state": "READY", "confidence_score": 0.7, "plan_hash": "h1", "event_id": "TP1_BEFORE_STOP"}}
        self.q.recent = [a]
        self.assertIsNone(self.q.confidence_for("SCALPING", "BUY", 2000.0, 1995.0))          # same entry, another SL
        self.assertIsNone(self.q.confidence_for("SCALPING", "BUY", 2000.0, None))            # SL unknown: not verifiable
        got = self.q.confidence_for("SCALPING", "BUY", 2000.005, 1998.0)                    # within one tick
        self.assertEqual(got["plan_hash"], "h1")


class TestMatureIsolationAndInstrument(_Svc):
    def _row(self, rid, inst, ts, spec):
        self.q.ledger.add_row({"row_id": rid, "instrument": inst, "engine": "SH_SCALPING", "strategy": "S", "direction": "LONG", "decision_ts": ts,
                               "task_hash": "th", "event_id": "TP1_BEFORE_STOP", "spec": spec, "features": {}, "data_kind": "SYNTHETIC",
                               "matures_at": ts + 1800})

    def _good_spec(self):
        from masterquo.quant import events as EV
        br = self.q.rt.bridge
        e = 2018.0
        return EV.EventSpec(instrument="XAUUSD", strategy="S", direction="LONG", entry=e, sl=e - 2.0, targets=((e + 2.5, 1.0),), horizon_s=1800.0,
                            event_id="TP1_BEFORE_STOP").to_dict(), datetime.fromisoformat(br.series["M1"][-120]["available_at"]).timestamp()

    def test_one_broken_row_does_not_stop_labelling(self):
        spec, ts = self._good_spec()
        self._row("broken", "XAUUSD", ts - 5, dict(spec, direction="UP"))
        self._row("good", "XAUUSD", ts, spec)
        n = self.q.mature(now=time.time())
        self.assertEqual(n, 2)
        by = self.q.ledger.counts("XAUUSD")["tasks"][0]["by_status"]
        self.assertEqual(by.get("INVALID_SPEC"), 1)            # kept, with its reason - never deleted
        self.assertEqual(by.get("LABELLED", 0) + by.get("NO_BARS", 0), 1)

    def test_rows_of_another_instrument_do_not_starve_this_one(self):
        spec, ts = self._good_spec()
        for i in range(3):
            self._row(f"btc{i}", "BTC", ts - 100 - i, dict(spec, instrument="BTC"))
        self._row("xau", "XAUUSD", ts, spec)
        orig = self.q.ledger.pending

        def pending(now, limit=2, instrument=None):            # the ledger with the instrument filter, small batch
            rows = [r for r in orig(now, 10_000) if instrument is None or r["instrument"] == instrument]
            return rows[:limit]
        self.q.ledger.pending = pending
        self.assertEqual(self.q.mature(now=time.time()), 1)
        self.assertNotIn("PENDING", self.q.ledger.counts("XAUUSD")["tasks"][0]["by_status"])


class TestDataKindUnknown(_Svc):
    def test_row_before_first_generation_takes_the_bridge_kind(self):
        a = self.q.assess(cand(ts=time.time()), log_row=True)
        self.assertEqual(a["status"], "NOT_TRAINED")
        with self.q.ledger._lock:
            kind = self.q.ledger.c.execute("SELECT data_kind FROM rows").fetchone()[0]
        self.assertEqual(kind, "SYNTHETIC")                    # the stub bridge declares synthetic=True

    def test_unknown_rows_are_not_training_evidence(self):
        from masterquo.quant import service as SV
        for i, kind in enumerate(("REAL", "UNKNOWN", "REAL", None)):
            self.q.ledger.add_row({"row_id": f"r{i}", "instrument": "XAUUSD", "engine": "E", "strategy": "S", "direction": "LONG", "decision_ts": 1e9 + i,
                                   "task_hash": "th", "event_id": "TP1_BEFORE_STOP", "spec": {"event_id": "TP1_BEFORE_STOP"}, "features": {},
                                   "data_kind": kind, "matures_at": 1e9 + i})
            self.q.ledger.label(f"r{i}", "LABELLED", {"y_event": True, "net_r": 1.0}, 1e9 + i + 60)
        seen = {}

        def fake_train(rows, **kw):
            seen["kinds"] = sorted({r["data_kind"] for r in rows})
            return {"status": "INSUFFICIENT_EVIDENCE", "report": {"reason": "test"}}
        with mock.patch.object(SV.M, "train", side_effect=fake_train):
            res = SV.train_from_ledger(self.q.ledger, "XAUUSD", log=lambda *_: None)
        self.assertEqual(seen["kinds"], ["REAL"])
        self.assertEqual(res[0]["n_rows"], 2)
        self.assertEqual(res[0]["excluded_unknown_data_kind"], 2)


class TestSettingsRobust(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_non_object_and_bad_cycle_never_raise(self):
        from pathlib import Path

        from masterquo.quant.service import Settings
        f = Path(self.td.dir) / "settings.json"
        st = Settings(f)
        f.write_text("[]", encoding="utf-8")
        s = st.get()
        self.assertEqual((s["mode"], s["cycle_s"]), ("SHADOW", 5.0))
        self.assertIsNotNone(st.error)
        for raw, want in (('{"cycle_s": "5s"}', 5.0), ('{"cycle_s": -1}', 5.0), ('{"cycle_s": 0.2}', 1.0), ('{"cycle_s": 9999}', 300.0),
                          ('{"cycle_s": 10}', 10.0), ('{"tabicl": [], "assist": 3}', 5.0)):
            f.write_text(raw, encoding="utf-8")
            s = Settings(f).get()
            self.assertEqual(s["cycle_s"], want, raw)
            self.assertIsInstance(s["tabicl"], dict)
            self.assertIsInstance(s["assist"], dict)

    def test_status_answers_with_a_damaged_settings_file(self):
        from masterquo.quant.service import QuantService
        q = QuantService(StubRt())
        try:
            q.settings.path.write_text("[]", encoding="utf-8")
            st = q.status()
            self.assertEqual(st["mode"], "SHADOW")
            self.assertTrue(st["settings_error"])
        finally:
            q.stop()


# =============================================================================================== snapshot QC (chunk_27#11, #12)
class TestSnapshotMissingAndSessions(unittest.TestCase):
    def test_tf_without_bars_is_missing_never_ok(self):
        from masterquo.quant import snapshot as S
        q = S.qc([], "M1")
        self.assertEqual((q["status"], q["issues"]), ("MISSING", ["NO_BARS"]))
        empty = SimpleNamespace(tfs={"M1": None, "M5": None}, bars=lambda tf, limit=None, include_forming=True: [],
                                quote_status=lambda: {"age_seconds": 0.5}, symbol_info={}, cfg=SimpleNamespace(symbol="XAUUSD-"), synthetic=True)
        snap = S.build(empty, instrument="XAUUSD", now=NOW, tfs=("M1", "M5"))
        self.assertEqual(snap["status"], "MISSING")
        self.assertIsNone(snap["as_of_utc"])
        br = StubBridge(now=NOW)
        br.series["M5"] = []
        snap2 = S.build(br, instrument="XAUUSD", now=NOW, tfs=("M1", "M5"))
        self.assertEqual(snap2["quality"]["M5"]["status"], "MISSING")
        self.assertEqual(snap2["status"], "DEGRADED")

    def test_weekend_breaks_are_not_missing_bars(self):
        from masterquo.quant import snapshot as S
        day = 86400
        monday = 1_704_067_200.0                               # 2024-01-01 00:00 UTC, a Monday
        rows, t = [], monday
        while len(rows) < 500:
            if datetime.fromtimestamp(t, UTC).weekday() < 5:
                rows.append(bar(t, 2000, 2001, 1999, 2000.5, day))
            t += day
        q = S.qc(S.normalise(rows, "D1"), "D1")
        self.assertEqual((q["status"], q["gap_count"]), ("OK", 0))
        self.assertGreaterEqual(q["session_breaks"], 99)
        # D1 aligned to a server midnight at 22:00 UTC (Sunday 22:00 opens Monday's bar) - still the weekend
        rows2 = [bar(monday - 2 * 3600 + i * day, 2000, 2001, 1999, 2000.5, day) for i in (0, 1, 2, 3, 4, 7, 8)]
        self.assertEqual(S.qc(S.normalise(rows2, "D1"), "D1")["gap_count"], 0)
        # a missing Wednesday is a real gap
        rows3 = [bar(monday + i * day, 2000, 2001, 1999, 2000.5, day) for i in (0, 1, 3, 4)]
        self.assertEqual(S.qc(S.normalise(rows3, "D1"), "D1")["gap_count"], 1)

    def test_degraded_by_gaps_names_the_reason(self):
        from masterquo.quant import snapshot as S
        monday = 1_704_067_200.0
        rows = [bar(monday + i * 120, 2000, 2001, 1999, 2000.5) for i in range(60)]   # every other M1 bar missing (weekday)
        q = S.qc(S.normalise(rows, "M1"), "M1")
        self.assertEqual(q["status"], "DEGRADED")
        self.assertIn("GAPS:59", q["issues"])


# =============================================================================================== NISKI
class TestLowFindings(unittest.TestCase):
    def test_cli_and_inventory_display_name(self):
        from masterquo.quant import cli
        from masterquo.quant import inventory as I
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            cli.main(["--help"])
        self.assertIn("Apollo23 Quant Core", out.getvalue())
        self.assertIn("masterquo quant", out.getvalue())                    # prog unchanged
        td = TempData()
        try:
            md = I.to_markdown(I.build(None, "XAUUSD"))
        finally:
            td.close()
        self.assertTrue(md.startswith("# Inwentaryzacja komponentów obliczeniowych – Apollo23 Quant Core"))

    def test_lab_unit_is_ratio(self):
        from masterquo.quant import inventory as I
        rows = [e for e in I._lab_rows() if e["id"].startswith("lab:") and e.get("task_type") == "SCORE"]
        self.assertTrue(rows)
        self.assertEqual({e["unit"] for e in rows}, {"ratio"})

    def test_price_forecast_columns_keep_the_canonical_name(self):
        from masterquo.quant import features as F
        p = {"state": "READY", "unit": "price", "task_type": "REGRESSION", "canonical_id": "tsfm:chronos2", "model_id": "tsfm:chronos2",
             "timeframe": "M5", "result": {"last_close": 2000.0, "pred_close": 2001.0}}
        f = F.price_forecast_features([p], {"direction": "LONG", "entry_price": 2000.0, "stop_loss": 1998.0, "features": {"atr_m5": 2.0}})
        self.assertEqual(f["fcp:tsfm:chronos2:M5:d_atr"], 0.5)

    def test_units_contract(self):
        from masterquo.quant import units as U
        r = U.ev_for_plan(p_event=0.6, event_id="TP1_BEFORE_STOP", targets=[{"price": 1, "weight": 1}], be_after=None, timeout=False, gain_r=2.0,
                          loss_r=1.0, cost_known=True)
        self.assertEqual(r["status"], "NET_VALIDATED_COSTS")
        self.assertAlmostEqual(r["ev_r"], 0.8)
        spec = U.InstrumentSpec.from_mt5("XAUUSD-", {"point": 0.01, "trade_tick_size": 0.01, "trade_tick_value": 1.0})
        self.assertIsNone(spec.tick_value_ccy)
        with self.assertRaises(U.UnitsError):
            spec.money(2.5, 1.0, account_ccy="PLN")            # currency of tick_value unknown -> no amount
        b = U.CostModel(commission_per_lot_side=0.0).basis()
        self.assertIn("swap", b["unknown"])                    # an unset swap is unknown, never a known 0
        self.assertEqual(b["status"], "PARTIAL")


if __name__ == "__main__":
    unittest.main()
