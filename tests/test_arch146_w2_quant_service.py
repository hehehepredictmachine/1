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
import math
import time
import unittest
from datetime import UTC, datetime
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


if __name__ == "__main__":
    unittest.main()
