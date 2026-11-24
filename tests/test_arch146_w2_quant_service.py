"""1.46 arch fix wave 2b, group "quant_service": QFENCE + producer / service / coordinator items of Quant Core.

QFENCE: a MetaModel trained before the producer fixes (manifest without producer_semantics) is served in SHADOW exactly as before, but in an
activated Quant ASSIST it holds EVERY new SH / ACTIVE entry (fail-closed) - assist_active() stays True (switching it off would lift every
Quant HOLD). With that fence the producer fixes below may change the values / masks of fc:* / st:* / ctx:dxy_* MetaModel inputs; what
stays S0 is lifting a block of decision.required_models (STALE / UNAVAILABLE) or an ASSIST role hold - each test of an adapter fix shows
the record only goes READY -> not READY (REQUIRED gets stricter), the coordinator reads exactly what it read before where a fix would have
handed it records it did not see (incomplete generations, the fresher Event GRU alias).
Isolated MASTERQUO_DATA_DIR, stub runtimes, SYNTHETIC data - no terminal, no orders, no HTTP server."""
from __future__ import annotations

import json
import time
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _env  # noqa: F401
import numpy as np
from _env import TempData


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, UTC).isoformat()


def synth_rows(n=900, seed=1):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        x = float(rng.normal())
        y = int(rng.random() < 1 / (1 + np.exp(-1.5 * x)))
        f = {"plan:gain_r": 1.5, "fc:trainhub:TH_LOGREG:DIRECTION_H6_M5:M5:edge": x, "ctx:hour_sin": float(rng.normal())}
        rows.append({"row_id": f"r{i}", "decision_ts": 1_794_000_000.0 + i * 600, "resolve_ts": 1_794_000_000.0 + i * 600 + 1800, "features": f,
                     "y": y, "net_r": (1.5 if y else -1.0) - 0.05, "data_kind": "REAL"})
    return rows


def su_ready(created=None):
    return {"strategy": "SCALPING", "signal_id": "SIG-QF", "symbol": "XAUUSD-", "instrument": "XAUUSD", "side": "BUY", "status": "READY",
            "entry_ref": 2000.0, "sl": 1998.0, "tps": [{"price": 2002.5, "share": 0.5, "name": "TP1"}, {"price": 2004.0, "share": 0.5, "name": "TP2"}],
            "horizon_minutes": 30, "created_at": created or 1_794_000_123.0, "costs": {"spread": 0.2, "round_trip_price": 0.3, "commission_known": True},
            "score": {"value": 64}, "status_reason": ""}


class StubBridge:
    synthetic = True

    def bars(self, tf, n=None, include_forming=False):
        return []


class StubRt:
    def __init__(self):
        self.bridge = StubBridge()


def coordinator(q):
    from masterquo.config import ConfigStore
    from masterquo.db.database import Database
    from masterquo.decision.coordinator import DecisionCoordinator
    db = Database()
    db.migrate()
    c = DecisionCoordinator(db, ConfigStore(), families=SimpleNamespace(predictions=lambda inst: []), instrument_fn=lambda: "XAUUSD")
    c.quant = q
    return c


# ================================================================================================ QFENCE
class QFenceFixture:
    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)

    def service(self):
        from masterquo.quant.service import QuantService
        q = QuantService(StubRt())
        q.tabicl.submit = lambda *a, **k: {"state": "DISABLED", "reason": "test"}
        q.instrument = lambda: "XAUUSD"
        return q

    def activate(self, task_hash: str, *, legacy: bool) -> str:
        """A validated, active MetaModel; legacy=True = its manifest as written before QFENCE (no producer_semantics)."""
        from masterquo.quant import metamodel as M
        res = M.train(synth_rows(), task={"task_hash": task_hash, "event_id": "TP1_BEFORE_STOP"})
        ver = M.save("XAUUSD", res, spec={"task_hash": task_hash})
        if legacy:
            p = M.root("XAUUSD") / task_hash / ver / "manifest.json"
            man = json.loads(p.read_text(encoding="utf-8"))
            man.pop("producer_semantics", None)
            p.write_text(json.dumps(man), encoding="utf-8")
        M.activate("XAUUSD", task_hash, ver)
        return ver

    def cand(self):
        from masterquo.evaluation import contract as EK
        return EK.sh_candidate(su_ready(), regime={"state": "TREND"}).to_dict()

    def task_of(self, cd):
        from masterquo.quant import events as QE
        return QE.spec_from_candidate(cd).task_hash()


class TestQFenceFailClosed(QFenceFixture, unittest.TestCase):
    def test_new_artifacts_record_the_producer_semantics(self):
        from masterquo.quant import metamodel as M
        ver = self.activate("t", legacy=False)
        man = json.loads((M.root("XAUUSD") / "t" / ver / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(man["producer_semantics"], M.PRODUCERS)
        self.assertEqual(M.producer_semantics({}), M.PRODUCERS_LEGACY)
        sem = M.feature_semantics("XAUUSD", "t", ver)
        self.assertFalse(sem["revalidation_required"])

    def test_assist_with_legacy_artifact_holds_every_sh_and_active_entry(self):
        from masterquo.quant import metamodel as M
        q = self.service()
        cd = self.cand()
        self.activate(self.task_of(cd), legacy=True)
        self.assertTrue(q.set_mode("ASSIST", confirm=True, by="TEST")["ok"])
        self.assertTrue(q.assist_active())                         # ASSIST is NOT switched off (that would lift every Quant HOLD)
        for e in (q.coordinator_entry("SH", cand=cd), q.coordinator_entry("ACTIVE", setup={"strategy_id": "S01", "direction": "LONG"})):
            self.assertEqual(e["state"], "READY", e)
            self.assertTrue(e["quant_hold"].startswith(M.REVALIDATION_REASON), e)
            self.assertEqual(e["revalidation_required"][0]["producer_semantics"], M.PRODUCERS_LEGACY)
        st = q.status()
        self.assertTrue(st["revalidation_required"])
        self.assertTrue(st["assist_fail_closed"])
        self.assertEqual(len(st["metamodel"]["revalidation_required"]), 1)
        self.assertEqual(len(M.revalidation_notices("XAUUSD")), 1)
        self.assertTrue(M.list_versions("XAUUSD")[-1]["producer_semantics"] == M.PRODUCERS_LEGACY)

    def test_coordinator_blocks_both_paths(self):
        q = self.service()
        cd = self.cand()
        self.activate(self.task_of(cd), legacy=True)
        q.set_mode("ASSIST", confirm=True, by="TEST")
        c = coordinator(q)
        gate = c.model_gate_active({"strategy_id": "S01", "direction": "LONG"})
        self.assertEqual(gate["status"], "FAIL")
        self.assertIn("MODEL_QUANT_HOLD:quant:metamodel", gate["codes"])
        rec = c.record_sh(su_ready(), None, "PAPER", "acc", None, regime={"state": "TREND"})
        self.assertIn("MODEL_QUANT_HOLD:quant:metamodel", rec["reason_codes"])
        self.assertEqual(rec["final_verdict"], "BLOCKED")
        with mock.patch("masterquo.evaluation.contract.sh_candidate", side_effect=ValueError("poza kontraktem")):
            rec = c.record_sh(dict(su_ready(), signal_id="SIG-QF2"), None, "PAPER", "acc", None)
        self.assertIn("MODEL_QUANT_HOLD:quant:metamodel", rec["reason_codes"])   # a candidate outside the contract is held too

    def test_current_artifact_gets_its_assessment_and_shadow_is_unchanged(self):
        q = self.service()
        cd = self.cand()
        self.activate(self.task_of(cd), legacy=False)
        a_shadow = q.assess(cd, mode="SHADOW")
        q.set_mode("ASSIST", confirm=True, by="TEST")
        e = q.coordinator_entry("SH", cand=cd)
        self.assertNotIn("revalidation_required", e)
        self.assertIsNotNone(e["result"]["p"])
        self.assertFalse(q.status()["revalidation_required"])
        # SHADOW: the legacy artifact is assessed exactly as before (no fence in the assessment, no entry in the coordinator)
        q2 = self.service()
        q2.set_mode("SHADOW")
        th = self.task_of(cd)
        from masterquo.quant import metamodel as M
        M.rollback("XAUUSD", th)
        self.activate(th, legacy=True)
        a_legacy = q2.assess(cd, mode="SHADOW")
        self.assertEqual(a_legacy["status"], "READY")
        self.assertEqual(a_legacy["influence"], "NONE")
        self.assertAlmostEqual(a_legacy["probability"]["p"], a_shadow["probability"]["p"], places=12)
        self.assertIsNone(q2.fence_entry())                          # SHADOW (default mode): no fence
        self.assertEqual(coordinator(q2)._quant_entry("SH", cand=cd), [])

    def test_assist_answer_and_activation_semantics_warn(self):
        from masterquo.quant import metamodel as M
        q = self.service()
        cd = self.cand()
        ver = self.activate(self.task_of(cd), legacy=True)
        r = q.set_mode("ASSIST", confirm=True, by="TEST")
        self.assertTrue(r["ok"])
        self.assertIn("QFENCE", r["warning"])
        sem = M.feature_semantics("XAUUSD", self.task_of(cd), ver)
        self.assertTrue(sem["revalidation_required"])
        self.assertIn("QFENCE", sem["revalidation_note"])


class TestQFenceRequiredRole(QFenceFixture, unittest.TestCase):
    """Review (S0): the fence entry is READY with result None - a REQUIRED quant:metamodel (decision.required_models) must not PASS it.
    Before the fence the same candidates got MODEL_REQUIRED_UNAVAILABLE (no ACTIVE assessment, SH outside the contract); they stay blocked."""

    def _assist_legacy(self):
        q = self.service()
        cd = self.cand()
        self.activate(self.task_of(cd), legacy=True)
        self.assertTrue(q.set_mode("ASSIST", confirm=True, by="TEST")["ok"])
        c = coordinator(q)
        c.cfg_store.update({"decision": {"required_models": ["quant:metamodel"]}})
        return q, c

    def test_required_role_never_passes_a_quant_hold(self):
        from masterquo.decision.coordinator import evaluate_models
        now = time.time()
        fence = {"family": "quant:metamodel", "use": "ASSIST", "task_type": "EVENT_PROBABILITY", "data_time": iso(now), "state": "READY",
                 "result": None, "quant_hold": "QUANT_REVALIDATION_REQUIRED: test"}
        hold = dict(fence, result={"p": 0.2, "e_net_r": -0.3}, quant_hold="P(TP1)=0.20 < 0.35")
        for p in (fence, hold):
            models, reasons = evaluate_models([p], "BUY", required={"quant:metamodel"}, assist_threshold=0.6, max_age_s=900.0, now=now)
            self.assertEqual(reasons, ["MODEL_REQUIRED_QUANT_HOLD:quant:metamodel"], p)
            self.assertEqual(models[0]["influence"], "BLOCK")
            # the ASSIST role (no REQUIRED) is unchanged: MODEL_QUANT_HOLD
            self.assertEqual(evaluate_models([p], "BUY", required=set(), assist_threshold=0.6, max_age_s=900.0, now=now)[1],
                             ["MODEL_QUANT_HOLD:quant:metamodel"])
        ok = dict(fence, result={"p": 0.6, "e_net_r": 0.4}, quant_hold=None)          # an assessment without a hold still PASSes REQUIRED
        models, reasons = evaluate_models([ok], "BUY", required={"quant:metamodel"}, assist_threshold=0.6, max_age_s=900.0, now=now)
        self.assertEqual((reasons, models[0]["influence"]), ([], "PASS"))

    def test_required_quant_with_fence_blocks_active_without_assessment(self):
        _, c = self._assist_legacy()
        self.assertEqual(c.cfg_store.get().decision.required_models, ["quant:metamodel"])
        g = c.model_gate_active({"strategy_id": "S07", "direction": "LONG"})        # no recent assessment (before QFENCE: UNAVAILABLE)
        self.assertEqual(g["status"], "FAIL")
        self.assertIn("MODEL_REQUIRED_QUANT_HOLD:quant:metamodel", g["codes"])

    def test_required_quant_with_fence_blocks_sh_in_and_outside_the_contract(self):
        _, c = self._assist_legacy()
        rec = c.record_sh(su_ready(), None, "PAPER", "acc", None, regime={"state": "TREND"})
        self.assertEqual(rec["final_verdict"], "BLOCKED")
        self.assertIn("MODEL_REQUIRED_QUANT_HOLD:quant:metamodel", rec["reason_codes"])
        with mock.patch("masterquo.evaluation.contract.sh_candidate", side_effect=ValueError("poza kontraktem")):
            rec = c.record_sh(dict(su_ready(), signal_id="SIG-RQ"), None, "PAPER", "acc", None)
        self.assertEqual(rec["final_verdict"], "BLOCKED")                             # before QFENCE: MODEL_REQUIRED_UNAVAILABLE
        self.assertIn("MODEL_REQUIRED_QUANT_HOLD:quant:metamodel", rec["reason_codes"])


# ================================================================================================ helpers: coordinator view
def required_codes(recs, side="BUY", required=(), now=None):
    """Coordinator evaluation (REQUIRED roles) of what quant.checks lets through - the Quant ASSIST view of the records."""
    from masterquo.decision.coordinator import evaluate_models
    from masterquo.quant import checks as CK
    now = time.time() if now is None else now
    el = CK.screen(recs, now=now, snapshot_kind="REAL")["eligible"]
    return evaluate_models(el, side, required=set(required), assist_threshold=0.6, max_age_s=900.0, now=now)[1]


class FakeIndicators:
    def __init__(self, cp):
        self.cp = cp

    def current(self):
        return {"as_of": self.cp.get("as_of")}

    def compact(self, s):
        return self.cp


def compact(now, *, dxy_status="READY", comp="READY", snap="READY"):
    return {"as_of": iso(now - 30), "snapshot_status": snap,
            "avwap": {"M1_SESSION": {"status": comp, "reason": None, "avwap": 2000.0}}, "semivar": {"status": "WARMUP", "reason": "rozgrzewka"},
            "spread": {"status": "NO_DATA", "reason": "brak"}, "profile": {"status": "NO_DATA"}, "microstructure": {"status": "DISABLED"},
            "dxy": {"status": dxy_status, "reason": "DXY_AGE_361223S>10800S" if dxy_status == "STALE" else None, "corr_72": -1.0,
                    "resid_z_72": -2.51, "beta_72": -2.0}}


# ================================================================================================ I0183 / I0612 / I0188 / I0189
class TestDxyAndIndicatorsRecords(unittest.TestCase):
    def recs(self, cp):
        from masterquo.quant import adapters as A
        return {r["canonical_id"]: r for r in A.analysis(SimpleNamespace(indicators=FakeIndicators(cp)), "XAUUSD")}

    def test_stale_dxy_is_not_a_ready_record_nor_a_feature(self):
        from masterquo.quant import checks as CK
        from masterquo.quant import features as F
        now = time.time()
        for st, want in (("STALE", "STALE"), ("WARMUP", "BLOCKED_DATA"), ("ERROR", "BLOCKED_DATA"), ("DISABLED", "DISABLED")):
            r = self.recs(compact(now, dxy_status=st))["analysis:dxy_correlation"]
            self.assertEqual(r["state"], want, st)
            self.assertIsNone(r["result"])
            el = CK.screen([r], now=now, snapshot_kind="REAL")["eligible"]
            self.assertEqual(el, [])
            for v in (F.VERSION, F.CURRENT):                              # FEAT-1 artifacts too (QFENCE holds them in ASSIST)
                self.assertFalse([k for k in F.build_for(v, {"direction": "LONG"}, el) if k.startswith("ctx:dxy_")], (st, v))
        r = self.recs(compact(now))["analysis:dxy_correlation"]
        self.assertEqual(r["state"], "READY")
        self.assertEqual(F.prediction_features([r], "LONG")["ctx:dxy_corr_72"], -1.0)

    def test_required_dxy_gets_stricter_never_looser(self):
        now = time.time()
        ready = self.recs(compact(now))["analysis:dxy_correlation"]
        stale = self.recs(compact(now, dxy_status="STALE"))["analysis:dxy_correlation"]
        self.assertEqual(required_codes([ready], required={"analysis:dxy_correlation"}, now=now), [])
        self.assertEqual(required_codes([stale], required={"analysis:dxy_correlation"}, now=now),
                         ["MODEL_REQUIRED_UNAVAILABLE:analysis:dxy_correlation"])

    def test_indicators_record_needs_a_ready_component_and_snapshot(self):
        now = time.time()
        bad = self.recs(compact(now, comp="STALE"))["analysis:indicators"]           # every component STALE / WARMUP / NO_DATA / DISABLED
        self.assertNotEqual(bad["state"], "READY")
        self.assertIn("avwap.M1_SESSION=STALE", bad["unavailable_reason"])
        old = self.recs(compact(now, snap="STALE"))["analysis:indicators"]
        self.assertEqual(old["state"], "STALE")
        ok = self.recs(compact(now))["analysis:indicators"]
        self.assertEqual(ok["state"], "READY")

    def test_indicators_role_is_context_state(self):
        from masterquo.quant import features as F
        from masterquo.quant import inventory as INV
        ok = self.recs(compact(time.time()))["analysis:indicators"]
        self.assertEqual(ok["analytic_role"], "CONTEXT_STATE")
        self.assertEqual(F.prediction_features([ok], "LONG"), {})                     # no feature is built from it
        self.assertIn("CONTEXT_STATE", INV.ROLE_PL)
        row = next(r for r in INV._analysis_rows() if r["id"] == "analysis:indicators")
        self.assertEqual(row["quant_role"], "CONTEXT_STATE")


# ================================================================================================ I0595
class TestZonesDataState(unittest.TestCase):
    def rec(self, state, *, restored=False):
        from masterquo.quant import adapters as A
        zm = {"summary": {"zones": 3, "nearest_support": {"zone_type": "S"}}, "data": {"state": state, "reasons": ["M5: 40 świec"]},
              "as_of": iso(time.time() - 60), "restored": restored}
        return next(r for r in A.analysis(SimpleNamespace(zones=SimpleNamespace(current=lambda: zm)), "XAUUSD") if r["canonical_id"] == "analysis:zones")

    def test_map_data_state_respected(self):
        self.assertEqual(self.rec("INSUFFICIENT_HISTORY")["state"], "BLOCKED_DATA")
        self.assertIn("INSUFFICIENT_HISTORY", self.rec("INSUFFICIENT_HISTORY")["unavailable_reason"])
        self.assertEqual(self.rec("STALE")["state"], "STALE")
        self.assertEqual(self.rec(None)["state"], "BLOCKED_DATA")
        self.assertEqual(self.rec("OK", restored=True)["state"], "BLOCKED_DATA")
        d = self.rec("DEGRADED")
        self.assertEqual((d["state"], d["data_quality"]), ("READY", "DEGRADED"))
        self.assertEqual((self.rec("OK")["state"], self.rec("OK")["data_quality"]), ("READY", "OK"))
        self.assertEqual(required_codes([self.rec("INSUFFICIENT_HISTORY")], required={"analysis:zones"}), ["MODEL_REQUIRED_UNAVAILABLE:analysis:zones"])


# ================================================================================================ I0795
class TestKalmanWarmupNotReady(unittest.TestCase):
    def rec(self, state):
        from masterquo.quant import adapters as A
        t = time.time() - 400
        v = {"status": "OK", "last_closed_m5": t, "kalman": {"state": state, "fast": 2000.0, "slow": 1999.0}}
        rt = SimpleNamespace(mm=SimpleNamespace(_cache={"XAUUSD": {"value": v}}))
        return next(r for r in A.mm(rt, "XAUUSD") if r["canonical_id"] == "mm:kalman_cross")

    def test_states_without_data_are_blocked(self):
        from masterquo.quant import features as F
        for st in ("INSUFFICIENT_HISTORY", "INITIALIZING", "INVALID_INPUT"):
            r = self.rec(st)
            self.assertEqual(r["state"], "BLOCKED_DATA", st)
            self.assertIn(st, r["unavailable_reason"])
            f = F.build_for(F.VERSION, {"direction": "LONG"}, [r])
            self.assertEqual(F.vectorise(f, ["st:mm:kalman_cross:aligned"]), ([0.0], [1.0]))   # a missing input (mask 1), not 0 with mask 0
        for st in ("NEUTRAL", "BULLISH_CONFIRMED", "BEARISH_CANDIDATE"):
            self.assertEqual(self.rec(st)["state"], "READY", st)


# ================================================================================================ Event GRU: I0476 / I0542 / I0796
def m1_bars(n=56, t0=1_794_000_000.0):
    return [{"open_utc": iso(t0 + 60 * i), "o": 2000.0, "h": 2000.5, "l": 1999.5, "c": 2000.0 + 0.1 * np.sin(i), "tv": 5, "spread": 20,
             "closed": True} for i in range(n)]


class TestEventGru(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)

    def predict(self, *, symbol_info=None, probs=(0.2, 0.3, 0.5), load=None):
        from masterquo.mm import artifacts as MA
        from masterquo.mm import event_engine as EE
        from masterquo.quant import adapters as A
        bars = m1_bars()
        rt = SimpleNamespace(bridge=SimpleNamespace(bars=lambda tf, include_forming=False: bars, symbol_info=symbol_info, synthetic=True))
        st = {"scaler_med": [0.0] * 8, "scaler_iqr": [1.0] * 8}
        patches = [mock.patch.object(MA, "read_pointer", return_value={"active": {"event_engine_dir3": load or "EG1"}}),
                   mock.patch.object(EE.EventModel, "from_state", return_value=object()),
                   mock.patch.object(EE, "predict", side_effect=lambda m, X, seg: np.tile(list(probs), (len(X), 1)))]
        if load is None:
            patches.append(mock.patch.object(MA, "load", return_value=(st, {"event_source": "BAR_CLOSE_EVENTS"})))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        g = A.EventGRU()
        return g, g.predict(rt, "XAUUSD")

    def test_unknown_point_is_blocked_data(self):
        _, r = self.predict(symbol_info=None)
        self.assertEqual(r["state"], "BLOCKED_DATA")
        self.assertIn("point", r["unavailable_reason"])
        _, r = self.predict(symbol_info={"point": 0.01})
        self.assertEqual(r["state"], "READY")

    def test_feature_schema_checked_at_load(self):
        from masterquo.mm import artifacts as MA
        from masterquo.quant import adapters as A
        st = {"scaler_med": np.zeros(8), "scaler_iqr": np.ones(8)}
        bad = MA.save("XAUUSD", "event_engine_dir3", st, {"feature_schema": "PMW-MM-EVENT-1:x", "event_source": "BAR_CLOSE_EVENTS"})
        _, r = self.predict(symbol_info={"point": 0.01}, load=bad)
        self.assertEqual(r["state"], "INCOMPATIBLE")
        self.assertIn("FEATURE_SCHEMA_MISMATCH", r["unavailable_reason"])
        good = MA.save("XAUUSD", "event_engine_dir3", st, {"feature_schema": A.event_feature_schema(), "event_source": "BAR_CLOSE_EVENTS"})
        _, r = self.predict(symbol_info={"point": 0.01}, load=good)
        self.assertEqual(r["state"], "READY")

    def test_nan_distribution_is_an_error_record(self):
        from masterquo.quant import adapters as A
        g, r = self.predict(symbol_info={"point": 0.01}, probs=(float("nan"), 0.5, 0.5))
        self.assertEqual(r["state"], "ERROR")
        self.assertEqual(r[A.INCOMPLETE_KEY], "EVENT_GRU_INVALID_DISTRIBUTION")
        # review (I0796): the old code raised before `latest` was written - the incomplete record is never stored there
        self.assertNotIn("XAUUSD", g.latest)

    def test_family_keeps_the_previous_ready_record_after_an_incomplete_cycle(self):
        """Review (I0796): families SEQ_GRU_EVENT (next cycle's base branch) reads event_gru.latest - after a NaN / out-of-[0, 1] cycle or an
        exception out of predict() it still sees the last READY record (bit for bit as when the old code raised), not the ERROR record."""
        from masterquo.modelhub.families.service import FamilyService
        from masterquo.quant import adapters as A
        probs = {"v": (0.1, 0.2, 0.7)}
        bars = m1_bars()
        rt = SimpleNamespace(bridge=SimpleNamespace(bars=lambda tf, include_forming=False: bars, symbol_info={"point": 0.01}, synthetic=False))
        g, r0 = self.predict(symbol_info={"point": 0.01})
        with mock.patch("masterquo.mm.event_engine.predict", side_effect=lambda m, X, seg: np.tile(list(probs["v"]), (len(X), 1))):
            r0 = g.predict(rt, "XAUUSD")
            self.assertEqual(r0["state"], "READY")
            fam = SimpleNamespace(event_gru_provider=lambda inst: g.latest.get(inst), fams={"SEQ_GRU_EVENT": None})
            for bad in ((float("nan"), 0.5, 0.5), (-0.1, 0.6, 0.5)):
                probs["v"] = bad
                out = A.extended(rt, "XAUUSD", g, with_scalp=False)
                e = next(p for p in out if p["canonical_id"] == "mm:event_engine_dir3")
                self.assertEqual(e[A.INCOMPLETE_KEY], "EVENT_GRU_INVALID_DISTRIBUTION")
                self.assertIs(g.latest["XAUUSD"], r0, bad)
                self.assertIs(FamilyService.predict(fam, "SEQ_GRU_EVENT", "XAUUSD"), r0, bad)
            with mock.patch.object(g, "predict", side_effect=RuntimeError("boom")):
                A.extended(rt, "XAUUSD", g, with_scalp=False)
            self.assertIs(g.latest["XAUUSD"], r0)
            probs["v"] = (0.2, 0.3, 0.6)                                            # wrong sum: the old ERROR record (stored as before)
            r2 = g.predict(rt, "XAUUSD")
            self.assertEqual((r2["state"], r2.get(A.INCOMPLETE_KEY)), ("ERROR", None))
            self.assertIs(g.latest["XAUUSD"], r2)

    def test_incomplete_marker_exactly_where_the_old_code_raised(self):
        from masterquo.quant import adapters as A
        _, r = self.predict(symbol_info={"point": 0.01}, probs=(-0.1, 0.6, 0.5))           # sum 1, class < 0: ContractError before
        self.assertEqual((r["state"], r.get(A.INCOMPLETE_KEY)), ("ERROR", "EVENT_GRU_INVALID_DISTRIBUTION"))
        _, r = self.predict(symbol_info={"point": 0.01}, probs=(0.2, 0.3, 0.6))            # sum 1.1: the old ERROR record, generation complete
        self.assertEqual((r["state"], r.get(A.INCOMPLETE_KEY)), ("ERROR", None))
        _, r = self.predict(symbol_info={"point": 0.01}, probs=(float("inf"), 0.3, 0.6))   # sum inf: also the old ERROR record
        self.assertEqual((r["state"], r.get(A.INCOMPLETE_KEY)), ("ERROR", None))

    def test_extended_keeps_the_other_records_when_the_gru_raises(self):
        from masterquo.quant import adapters as A
        g = A.EventGRU()
        rt = SimpleNamespace(mm=SimpleNamespace(_cache={"XAUUSD": {"value": {"status": "OK", "last_closed_m5": time.time() - 400,
                                                                               "kalman": {"state": "NEUTRAL"}}}}))
        with mock.patch.object(g, "predict", side_effect=RuntimeError("boom")):
            out = A.extended(rt, "XAUUSD", g, with_scalp=False)
        ids = [p["canonical_id"] for p in out]
        self.assertIn("mm:kalman_cross", ids)
        e = next(p for p in out if p["canonical_id"] == "mm:event_engine_dir3")
        self.assertEqual((e["state"], e[A.INCOMPLETE_KEY]), ("ERROR", "EVENT_GRU_EXCEPTION"))
        self.assertEqual(g.latest, {})                         # review (I0796): `latest` untouched, as when the exception left the branch


# ================================================================================================ service: I0796 / I0799 / I0366 / I0801 / I0800
def ready_pred(cid, *, tf="M5", age=60.0, version="v1", family=None, task="DIRECTION_H6_M5", ttl=None, up=0.4, down=0.3):
    from masterquo.modelhub import contract as C
    extra = {"canonical_id": cid, "model_key": cid}
    if family:
        extra.update(family=family, use="SHADOW")
    return C.make(instrument="XAUUSD", symbol="XAUUSD-", timeframe=tf, model_name=cid, model_version=version, task_type="CLASS_PROBABILITIES",
                  task=task, horizon_bars=2 if tf == "EVENT" else 6, unit="probability", state="READY",
                  result={"DOWN": down, "FLAT": round(1 - up - down, 10), "UP": up}, data_time=iso(time.time() - age), ttl_s=ttl, extra=extra)


class QuantCycleFixture:
    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)

    def service(self):
        from masterquo.quant.service import QuantService
        from test_quant_core import StubBridge as QBridge
        rt = SimpleNamespace(bridge=QBridge(now=time.time()), sh=SimpleNamespace(instrument=lambda: "XAUUSD", snapshot=None))
        q = QuantService(rt)
        q.tabicl.submit = lambda *a, **k: {"state": "DISABLED", "reason": "test"}
        return q


class TestIncompleteGenerationCoordinatorUnchanged(QuantCycleFixture, unittest.TestCase):
    def test_gru_failure_keeps_records_for_features_but_not_for_the_coordinator(self):
        from masterquo.modelhub import adapters as MA
        from masterquo.quant import adapters as A
        q = self.service()
        rec = ready_pred("trainhub:TH_LOGREG")
        bad = A.EventGRU()._none("XAUUSD", "ERROR", "rozkład NaN", "EG1", incomplete="EVENT_GRU_INVALID_DISTRIBUTION")
        with mock.patch.object(MA, "all_predictions", return_value=[]), mock.patch.object(A, "extended", return_value=[rec, bad]):
            p = q.cycle()
        self.assertFalse(p["complete"])
        self.assertEqual(p["incomplete_reasons"], ["EVENT_GRU_INVALID_DISTRIBUTION"])
        self.assertEqual([x["canonical_id"] for x in p["eligible"]], ["trainhub:TH_LOGREG"])
        self.assertEqual(q.coordinator_predictions("XAUUSD"), [])                       # as when the branch raised: nothing for REQUIRED / ASSIST
        self.assertEqual([x["canonical_id"] for x in q._eligible_at(time.time())[0]], ["trainhub:TH_LOGREG"])

    def test_failed_base_branch_keeps_extended_records_for_features_only(self):
        from masterquo.modelhub import adapters as MA
        from masterquo.quant import adapters as A
        q = self.service()
        rec = ready_pred("trainhub:TH_LOGREG")
        with mock.patch.object(MA, "all_predictions", side_effect=RuntimeError("base down")), mock.patch.object(A, "extended", return_value=[rec]):
            p = q.cycle()
        self.assertEqual(p["tasks"]["base_predictions"]["status"], "ERROR")
        self.assertEqual(p["tasks"]["contract_checks"]["status"], "OK")
        self.assertFalse(p["complete"])
        self.assertEqual(len(p["eligible"]), 1)
        self.assertEqual(q.coordinator_predictions("XAUUSD"), [])
        self.assertEqual(len(q._eligible_at(time.time())[0]), 1)
        with mock.patch.object(MA, "all_predictions", return_value=[]), mock.patch.object(A, "extended", return_value=[rec]):
            p = q.cycle()
        self.assertTrue(p["complete"])
        self.assertEqual([x["model_id"] for x in q.coordinator_predictions("XAUUSD")], ["trainhub:TH_LOGREG"])   # complete: as before


class TestFreshEventGruForFeatures(QuantCycleFixture, unittest.TestCase):
    def run_cycle(self, old_age, new_age):
        from masterquo.modelhub import adapters as MA
        from masterquo.quant import adapters as A
        q = self.service()
        old = ready_pred("mm:event_engine_dir3", tf="EVENT", age=old_age, version="EG1", family="SEQ_GRU_EVENT", task="EVENT_UNITS_DIR3", ttl=900.0,
                         up=0.2, down=0.7)
        time.sleep(0.01)
        new = ready_pred("mm:event_engine_dir3", tf="EVENT", age=new_age, version="EG1", family="SEQ_GRU_EVENT", task="EVENT_UNITS_DIR3", ttl=900.0,
                         up=0.6, down=0.2)
        with mock.patch.object(MA, "all_predictions", return_value=[old]), mock.patch.object(A, "extended", return_value=[new]):
            p = q.cycle()
        return q, p

    def test_dedup_keeps_fresh_event_gru_in_the_features(self):
        q, p = self.run_cycle(300, 30)
        coord = q.coordinator_predictions("XAUUSD")
        self.assertEqual([x["result"]["UP"] for x in coord], [0.2])                      # the coordinator list exactly as before (base first)
        feats = q._eligible_at(time.time())[0]
        self.assertEqual([x["result"]["UP"] for x in feats], [0.6])                      # the features: this cycle's answer
        self.assertEqual(len(p["aliases_dropped"]), 1)

    def test_stale_old_alias_is_not_lifted_for_the_coordinator(self):
        q, _ = self.run_cycle(950, 30)                                                   # older alias STALE (ttl 900 s)
        self.assertEqual(q.coordinator_predictions("XAUUSD"), [])                        # REQUIRED stays MISSING as before
        self.assertEqual([x["result"]["UP"] for x in q._eligible_at(time.time())[0]], [0.6])


class TestScalpInstrument(QuantCycleFixture, unittest.TestCase):
    def test_cache_never_carries_another_instruments_forecast(self):
        from masterquo.quant import adapters as A
        from masterquo.quant import snapshot as S
        q = self.service()
        q._last_m1 = 123.0
        q._last_scalp = [dict(ready_pred("scalp:A_direction", tf="M1"), instrument="XAUUSD")]
        with mock.patch.object(S, "last_closed", return_value={"t": 123.0}), mock.patch.object(A, "extended", return_value=[]):
            self.assertEqual(q._extended({"rt": q.rt, "inst": "BTC"}, {"snapshot": {}}), [])
            self.assertEqual(len(q._extended({"rt": q.rt, "inst": "XAUUSD"}, {"snapshot": {}})), 1)

    def test_scalp_a_of_another_instrument_is_disabled(self):
        from masterquo.quant import adapters as A
        sc = SimpleNamespace(inst="XAUUSD", registry=lambda: {"active": "R1"},
                             forecasts=lambda: {"status": "SHADOW", "horizons": {"1": {"p_down": 0.2, "p_flat": 0.3, "p_up": 0.5}},
                                                "feature_time_utc": iso(time.time() - 30), "run_id": "R1"})
        out = A.scalp_a(SimpleNamespace(scalp=sc), "BTC")
        self.assertEqual([(r["state"], r["instrument"]) for r in out], [("DISABLED", "BTC")])
        self.assertIsNone(out[0]["result"])
        self.assertEqual(A.scalp_a(SimpleNamespace(scalp=sc), "XAUUSD")[0]["state"], "READY")


# ================================================================================================ I0227
class TestLabFixtureOnlyNeverReal(unittest.TestCase):
    def recs(self, **model):
        from masterquo.quant import adapters as A
        m = {"status": "ready", "family": "SEW_SNN", "horizon": "M5x12", "raw_score": 0.6, "model_id": "LM-1", **model}
        lb = SimpleNamespace(state={"XAUUSD": {"as_of": iso(time.time() - 30), "data_mode": "live", "models": [m]}}, assets=None)
        return A.lab(SimpleNamespace(lab=lb), "XAUUSD")

    def test_fixture_only_model_never_enters_real_snapshot(self):
        from masterquo.quant import checks as CK
        now = time.time()
        r = CK.screen(self.recs(role="fixture_only", data_source="SYNTHETIC"), now=now, snapshot_kind="REAL")
        self.assertEqual(r["eligible"], [])
        self.assertEqual(r["excluded"][0]["eligibility"]["reason"], "SYNTHETIC_IN_REAL_SNAPSHOT")
        self.assertEqual(r["excluded"][0]["model_role"], "fixture_only")
        r = CK.screen(self.recs(role="research", data_source="MT5"), now=now, snapshot_kind="REAL")
        self.assertEqual([p["canonical_id"] for p in r["eligible"]], ["lab:SEW_SNN"])
        r = CK.screen(self.recs(), now=now, snapshot_kind="REAL")                       # an artifact without the fields: as before
        self.assertEqual(len(r["eligible"]), 1)


# ================================================================================================ I0558 / I0559
class TestRuleNews(unittest.TestCase):
    def news(self, *, risk="HIGH", events=({"name": "NFP"},)):
        from masterquo.news.service import NewsService
        cfg = SimpleNamespace(news=SimpleNamespace(enabled=True, poll_seconds=300))
        n = NewsService(SimpleNamespace(get=lambda: cfg), None, SimpleNamespace(publish=lambda *a: None), None)
        n.report = {"as_of": iso(time.time()), "status": "PARTIAL", "calendar": {"status": "PARTIAL", "risk": {"level": risk, "events": list(events)},
                                                                                "events": []}}
        return n

    def test_required_news_blocks_in_an_event_window(self):
        from masterquo.quant import adapters as A
        rec = A.news_record(self.news(), "XAUUSD")
        self.assertEqual((rec["state"], rec["result"]["blackout"]), ("READY", "TAK"))
        self.assertEqual(required_codes([rec], required={"rule:news"}), ["MODEL_REQUIRED_BLACKOUT:rule:news"])
        self.assertEqual(required_codes([rec]), [])                                          # not REQUIRED: no effect
        calm = A.news_record(self.news(risk="NONE_DETECTED_IN_PARTIAL_CALENDAR", events=()), "XAUUSD")
        self.assertEqual(required_codes([calm], required={"rule:news"}), [])
        from masterquo.decision.coordinator import evaluate_models
        raw = dict(calm, result=dict(calm["result"], blackout=True))                          # a bool True (not through clean()) blocks too
        self.assertEqual(evaluate_models([raw], "SELL", required={"rule:news"}, assist_threshold=0.6, max_age_s=900, now=time.time())[1],
                         ["MODEL_REQUIRED_BLACKOUT:rule:news"])

    def test_news_record_without_sh_snapshot_is_explicitly_blocked(self):
        from masterquo.quant import adapters as A
        out = A.rules(SimpleNamespace(sh=SimpleNamespace(snapshot=None), news=self.news(risk="NONE", events=())), "XAUUSD")
        n = [r for r in out if r["canonical_id"] == "rule:news"]
        self.assertEqual([r["state"] for r in n], ["BLOCKED_DATA"])
        self.assertIn("migawki kontekstu SH", n[0]["unavailable_reason"])
        # the decision is exactly the one of the missing record: REQUIRED rule:news -> MODEL_REQUIRED_UNAVAILABLE, never READY / PASS
        self.assertEqual(required_codes(out, required={"rule:news"}), ["MODEL_REQUIRED_UNAVAILABLE:rule:news"])
        self.assertEqual(required_codes([r for r in out if r["canonical_id"] != "rule:news"], required={"rule:news"}),
                         ["MODEL_REQUIRED_UNAVAILABLE:rule:news"])


# ================================================================================================ I0532 / I0537
class TestConfidenceLabels(QFenceFixture, unittest.TestCase):
    def test_estimator_kind_follows_the_settings(self):
        from masterquo.quant.service import QuantService
        cd = self.cand()
        self.assertEqual(QuantService(StubRt()).assess(cd)["confidence"]["estimator_kind"], "tabicl_v2")
        QuantService(StubRt()).set_estimator("legacy_logistic", by="TEST")
        a = QuantService(StubRt()).assess(cd)                       # a fresh service: TabICL results are cached per plan
        self.assertEqual(a["confidence"]["estimator_kind"], "legacy_logistic")
        self.assertIn("estimator = legacy_logistic", a["tabicl"]["reason"])
        q = QuantService(StubRt())
        s = q.settings.get()
        s.update(estimator="tabicl_v2", tabicl=dict(s["tabicl"], enabled=False))
        q.settings.put(s)
        a = QuantService(StubRt()).assess(cd)
        self.assertEqual(a["confidence"]["estimator_kind"], "tabicl_v2_disabled")
        self.assertIn("tabicl.enabled = false", a["tabicl"]["reason"])

    def test_confidence_influence_is_presentation(self):
        q = self.service()
        cd = self.cand()
        q.tabicl.submit = lambda *a, **k: {"state": "READY", "confidence_score": 61.0, "p_event_raw": 0.61, "context_id": "C1"}
        self.assertEqual(q.assess(cd)["confidence"]["influence"], "PRESENTATION")
        q.tabicl.submit = lambda *a, **k: {"state": "QUEUED"}
        self.assertEqual(q.assess(cd)["confidence"]["influence"], "NONE")


# ================================================================================================ I0528 / I0798
class TestTaskGroupTraining(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)

    def spec(self, sl, tp1=2002.5, horizon=1800.0):
        from masterquo.quant import events as EV
        return EV.EventSpec(instrument="XAUUSD", strategy="SH_SCALPING/PMW_SC01", direction="LONG", entry=2000.0, sl=sl,
                            targets=((tp1, 0.5), (2004.0, 0.5)), horizon_s=horizon, entry_rule="MARKET", event_id="TP2_BEFORE_STOP")

    def test_plan_geometry_is_not_part_of_the_training_key(self):
        a, b, c = self.spec(1998.0), self.spec(1998.1), self.spec(1998.0, tp1=2002.7, horizon=2400.0)
        self.assertNotEqual(a.task_hash(), b.task_hash())
        self.assertEqual(a.task_group(), b.task_group())
        self.assertEqual(a.task_group(), c.task_group())
        self.assertTrue(a.task_group().startswith("G"))
        from masterquo.quant import events as EV
        other = EV.EventSpec(instrument="XAUUSD", strategy="SH_SCALPING/PMW_SC01", direction="LONG", entry=2000.0, sl=1998.0,
                             targets=((2002.5, 1.0),), horizon_s=1800.0, entry_rule="MARKET", event_id="TP1_BEFORE_STOP")
        self.assertNotEqual(a.task_group(), other.task_group())                        # another event / number of targets: another group

    def ledger(self, n):
        from masterquo.quant.ledger import QuantLedger
        led = QuantLedger(Path(self.td.dir) / "l.sqlite")
        rng = np.random.default_rng(3)
        for i in range(n):
            sp = self.spec(round(1998.0 - 0.01 * (i % 97), 2))
            x = float(rng.normal())
            y = int(rng.random() < 1 / (1 + np.exp(-1.5 * x)))
            led.add_row({"row_id": f"r{i}", "instrument": "XAUUSD", "engine": "SH_SCALPING", "strategy": "PMW_SC01", "direction": "LONG",
                         "decision_ts": 1_794_000_000.0 + 600 * i, "task_hash": sp.task_hash(), "event_id": sp.event_id, "spec": sp.to_dict(),
                         "features": {"plan:gain_r": 1.5, "fc:trainhub:TH_LOGREG:DIRECTION_H6_M5:M5:edge": x}, "data_kind": "REAL",
                         "matures_at": 1_794_000_000.0 + 600 * i})
            led.label(f"r{i}", "LABELLED", {"y_event": bool(y), "net_r": 1.4 if y else -1.05}, 1_794_000_000.0 + 600 * i + 1800)
        return led

    def test_train_from_ledger_groups_tasks(self):
        from masterquo.quant import service as SV
        led = self.ledger(600)
        self.assertGreater(len(led.counts("XAUUSD")["tasks"]), 90)                       # ~97 different task_hash
        self.assertEqual(len(led.counts("XAUUSD")["groups"]), 1)
        seen = []

        def fake_train(rows, **kw):
            seen.append((len(rows), kw["task"]))
            return {"status": "INSUFFICIENT_EVIDENCE", "report": {"reason": "test"}}
        with mock.patch.object(SV.M, "train", side_effect=fake_train):
            res = SV.train_from_ledger(led, "XAUUSD", log=lambda *_: None)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["n_rows"], 600)
        self.assertEqual(res[0]["task_hash"], self.spec(1998.0).task_group())
        self.assertGreater(res[0]["member_tasks"], 90)
        self.assertEqual(seen[0][1]["train_key"], "TASK_GROUP")
        with mock.patch.object(SV.M, "train", side_effect=fake_train):                 # one task_hash -> its whole group
            res = SV.train_from_ledger(led, "XAUUSD", self.spec(1998.0).task_hash(), log=lambda *_: None)
        self.assertEqual(res[0]["n_rows"], 600)

    def test_group_model_serves_every_task_of_the_group(self):
        from masterquo.evaluation import contract as EK
        from masterquo.quant import events as QE
        from masterquo.quant import metamodel as M
        from masterquo.quant import service as SV
        from masterquo.quant.service import QuantService
        led = self.ledger(900)
        res = SV.train_from_ledger(led, "XAUUSD", log=lambda *_: None)
        self.assertEqual(res[0]["status"], "VALIDATED_SHADOW", res[0])
        g = res[0]["task_hash"]
        M.activate("XAUUSD", g, res[0]["version"])
        man = json.loads((M.root("XAUUSD") / g / res[0]["version"] / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual((man["train_key"], man["task_group"], man["producer_semantics"]), ("TASK_GROUP", g, M.PRODUCERS))
        q = QuantService(StubRt())
        q.tabicl.submit = lambda *a, **k: {"state": "DISABLED", "reason": "test"}
        su = dict(su_ready(), strategy="SCALPING")
        cd = EK.sh_candidate(su, regime={"state": "TREND"}).to_dict()
        cd.update(strategy_id="PMW_SC01", engine="SH_SCALPING", horizon_s=1800.0, stop_loss=1996.5,
                  targets=[{"price": 2002.5, "weight": 0.5}, {"price": 2004.0, "weight": 0.5}])
        sp = QE.spec_from_candidate(cd)
        self.assertEqual(sp.task_group(), g)
        self.assertNotIn(sp.task_hash(), {r["task_hash"] for r in led.counts("XAUUSD")["tasks"]})   # a task never seen in training
        a = q.assess(cd)
        self.assertEqual(a["status"], "READY", a.get("reason"))
        self.assertEqual(a["task_group"], g)

    def test_member_task_test_blocks_count_as_seen(self):
        """Review (I0528 a): a TEST block a member task_hash model already used is not fresh for the group (test once)."""
        from masterquo.quant import metamodel as M
        from masterquo.quant import service as SV
        led = self.ledger(900)
        rows = led.training_rows("XAUUSD")
        member = rows[-1]["task_hash"]
        M.record_test("XAUUSD", member, [r["row_id"] for r in rows if r["task_hash"] == member])
        r = SV.train_from_ledger(led, "XAUUSD", log=lambda *_: None)[0]
        self.assertNotEqual(r["status"], "VALIDATED_SHADOW", r)
        self.assertIn("test_block_fresh", r["failed_gates"])

    def test_counts_computes_the_group_once_per_task(self):
        """Review (I0528 b): counts() (every NOT_TRAINED assessment) hashes the group of a task once, not on every call."""
        from masterquo.quant import events as QE
        led = self.ledger(300)
        n_tasks = len(led.counts("XAUUSD")["tasks"])
        self.assertGreater(n_tasks, 90)
        with mock.patch.object(QE, "task_group_of", wraps=QE.task_group_of) as tg:
            c = led.counts("XAUUSD")
        self.assertEqual(tg.call_count, 0)
        self.assertEqual(len(c["groups"]), 1)
        self.assertEqual(c["groups"][0]["task_group"], self.spec(1998.0).task_group())
        self.assertTrue(all(t["task_group"] == self.spec(1998.0).task_group() for t in c["tasks"]))

    def test_qfence_exit_path_needs_the_old_keys_rolled_back(self):
        """Review (QFENCE/I0528): a new group model (key G…) does not replace a legacy artifact stored under its task_hash - the fence
        holds every entry until each old key is rolled back out of `active` (repeated while its history has versions), as the note says."""
        from masterquo.quant import metamodel as M
        from masterquo.quant import service as SV
        from masterquo.quant.service import QuantService
        q = QuantService(StubRt())
        q.tabicl.submit = lambda *a, **k: {"state": "DISABLED", "reason": "test"}
        q.instrument = lambda: "XAUUSD"
        th = self.spec(1998.0).task_hash()
        for _ in range(2):                                     # two legacy versions under the old key (history)
            res = M.train(synth_rows(), task={"task_hash": th, "event_id": "TP2_BEFORE_STOP"})
            ver = M.save("XAUUSD", res, spec={"task_hash": th})
            p = M.root("XAUUSD") / th / ver / "manifest.json"
            man = json.loads(p.read_text(encoding="utf-8"))
            man.pop("producer_semantics", None)
            p.write_text(json.dumps(man), encoding="utf-8")
            M.activate("XAUUSD", th, ver)
        self.assertTrue(q.set_mode("ASSIST", confirm=True, by="TEST")["ok"])
        self.assertIn("quant rollback", M.REVALIDATION_NOTE)
        r = SV.train_from_ledger(self.ledger(900), "XAUUSD", log=lambda *_: None)[0]
        self.assertEqual(r["status"], "VALIDATED_SHADOW", r)
        M.activate("XAUUSD", r["task_hash"], r["version"])
        self.assertIsNotNone(q.fence_entry())                  # train + activate alone: still fenced (old key stays in ACTIVE.json)
        self.assertEqual([x["task_hash"] for x in q.revalidation_required()], [th])
        M.rollback("XAUUSD", th)
        self.assertIsNotNone(q.fence_entry())                  # the previous legacy version is back from the history
        M.rollback("XAUUSD", th)
        self.assertNotIn(th, M.pointer("XAUUSD")["active"])
        self.assertIsNone(q.fence_entry())
        self.assertTrue(q.assist_active())                     # the group model keeps ASSIST active (its assessments, no fence)


if __name__ == "__main__":
    unittest.main()
