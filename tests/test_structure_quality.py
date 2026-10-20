"""PMW-UPD-09 R26 cross-cutting quality (T145-T148): automaton invalidation order, metric domains, artefact continuity and a
technical E2E of the two new families through the SHARED trainer (TEST_ONLY synthetic export; no edge claim, no orders)."""
import json
import math
import unittest

import numpy as np

import _env  # noqa: F401
from _env import TempData

from test_structure_intelligence import m1_bars, write_export


class QualityTests(unittest.TestCase):
    def test_t145_invalidation_before_breakout_and_dynamic_boundary(self):
        from masterquo.analysis import structure_v2 as S
        c = [100, 90, 101, 110]
        self.assertEqual(S.evaluate_instance("A", 1, 105, 95, -1, c, c, c, c)["state"], "INVALIDATED")
        m = [100, 110, 99, 90]
        self.assertEqual(S.evaluate_instance("B", -1, 95, 105, -1, m, m, m, m)["state"], "INVALIDATED")
        # sloped boundary: confirm level rises with the bar index; a close that would beat a flat level does not confirm
        r = S.evaluate_instance("C", 1, lambda i: 105 + 2 * i, lambda i: 95.0, -1, [100, 104, 106, 108], [100, 104, 106, 108],
                                [100, 104, 106, 108], [100, 104, 106, 108])
        self.assertEqual(r["state"], "FORMING")

    def test_t146_metric_domains(self):
        from masterquo.lab import structure_task as T
        P = np.full((4, 1, 3), 1 / 3)
        Q = np.zeros((4, 1, 3))
        empty = T.metrics(P, Q, np.full((4, 1), -1), np.full((4, 1), np.nan))[0]
        self.assertEqual((empty["n"], empty["status"], empty["log_loss"]), (0, "NO_SAMPLES", None))
        one = T.metrics(P, Q, np.zeros((4, 1), int), np.zeros((4, 1)))[0]
        self.assertEqual(one["status"], "ONE_CLASS")
        bad = P.copy()
        bad[0, 0, 0] = np.nan
        self.assertEqual(T.metrics(bad, Q, np.zeros((4, 1), int), np.zeros((4, 1)))[0]["status"], "INVALID_PREDICTION")
        json.dumps(empty, allow_nan=False)

    def test_t147_incomplete_artifact_never_trained(self):
        import tempfile
        from pathlib import Path
        from masterquo.lab import spike_brain as SB
        from masterquo.lab import structure_task as T
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cand"
            p.mkdir()
            (p / "net").mkdir()
            with self.assertRaises((OSError, ValueError)):
                T.load_candidate(p)                                       # no candidate.json -> not loadable / not TRAINED
            net = SB.SpikeBrain(8, {"blocks": 1}, 1)
            net.save(p / "m")
            with self.assertRaises(FileExistsError):
                net.save(p / "m")                                         # never overwrites an existing artefact in place


class KnowledgeTests(unittest.TestCase):
    def test_k25_k35_loaded_and_bounded(self):
        from masterquo.agent.service import load_prompt
        from masterquo.analysis import structure_knowledge as sk
        text, ver = load_prompt()
        for k in ("K25", "K28", "K31", "K34", "K35"):
            self.assertIn(k, text)
        self.assertTrue(ver.startswith("MQAI-AGENT-PROMPT-1.8.0"))
        snap = {"snapshot_id": "S1", "cells": {"M1": {"status": "OK", "structure": {"trend_internal": "UP", "trend_major": "UP"},
                "market": {"status": "OK", "regime": {"state": "TREND_UP", "strength": 72.0, "volatility": "HIGH"}, "behavior": {"bias": "UP"},
                           "smma": {"location": "ABOVE", "event": "UP"}, "zscore": {"inclusive": {"z": 2.4, "status": "OK"}, "previous": {"z": None, "status": "LOW_DISPERSION"}}}}},
                "forecast": {"forecast_status": "ABSTAIN", "reason": "NO_SHADOW_MODEL"}, "native": {"compile": {"NATIVE_COMPILED": "NOT_COMPILED_NO_METAEDITOR"}}}
        ex = sk.explain(snap)
        for k in ("K28", "K32", "K33", "K34", "K35", "K26"):
            self.assertIn(k, ex["rules"])
        self.assertNotIn("%", ex["text"])                                     # no invented percentages without a model output
        self.assertIn("nie prawdopodobieństwo", ex["text"])
        self.assertIn("LOW_DISPERSION", ex["text"])


class E2ETests(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_t148_new_families_through_shared_trainer(self):
        from masterquo.db.database import Database
        from masterquo.lab import structure_task as T
        import mq_instruments
        db = Database()
        db.migrate()
        ds = write_export(mq_instruments.data_dir() / "exp", m1_bars(2200))
        T.save_dataset("XAUUSD", T.build_move_dataset("XAUUSD", ds, log=lambda *a: None))
        T.PROFILES["fixture9"] = dict(T.PROFILES["quick"], epochs=1, max_fit_rows=200, mr_requested=168, mr_max_fit_rows=150, spike_max_fit_rows=24,
                                      batch=12, max_eval_rows=40, seeds=[11])
        try:
            rep = T.train("XAUUSD", T.latest_dataset("XAUUSD", T.TASK_MOVE), T.TASK_MOVE, list(T.SF.FAMILIES), "fixture9", db=db, log=lambda *a: None,
                          spike_cfg={"encoder": "BAR_EVENT_V1", "attention": "HYBRID"}, transform=T.SF.MR.TRANSFORM_ID)
            rq = T.train("XAUUSD", T.latest_dataset("XAUUSD", T.TASK_MOVE), T.TASK_MOVE, [T.SF.SB_FAMILY], "fixture9", db=db, log=lambda *a: None,
                         spike_cfg={"encoder": "QUOTE_EVENT_V1"})
            bad = T.train("XAUUSD", T.latest_dataset("XAUUSD", T.TASK_MOVE), T.TASK_MOVE, [T.SF.MR_FAMILY], "fixture9", transform="X")
        finally:
            T.PROFILES.pop("fixture9")
        self.assertEqual(rep["role"], "TEST_ONLY")
        self.assertEqual(bad["status"], "INCOMPATIBLE")
        fold = next(f for f in rep["folds"] if f.get("status") == "OK")
        for fam in T.SF.FAMILIES:
            r0 = fold["families"][fam][0]
            self.assertEqual(r0["status"], "TRAINED", fam)
            self.assertIn("diagnostics", r0)
            for m in r0["metrics"]:
                if m.get("log_loss") is not None:
                    self.assertTrue(math.isfinite(m["log_loss"]))
        sb_diag = fold["families"][T.SF.SB_FAMILY][0]["diagnostics"]
        self.assertEqual(sb_diag["attention"], "HYBRID")
        self.assertIn("experts_block0", sb_diag["telemetry"])
        self.assertIsNone(sb_diag["energy_j"])
        self.assertEqual(fold["families"][T.SF.MR_FAMILY][0]["diagnostics"]["transform"]["layout"]["F"], 168)
        # quote profile without a real tick archive is BLOCKED (only this profile)
        qf = next(f for f in rq["folds"] if f.get("status") == "OK")
        self.assertEqual(qf["families"][T.SF.SB_FAMILY][0]["status"], "BLOCKED_NO_QUOTE_HISTORY")
        # saved candidates reload and reproduce predictions (same ids/hash)
        data = T.load_dataset(T.latest_dataset("XAUUSD", T.TASK_MOVE), T.TASK_MOVE)
        pos = np.arange(len(data["rows_idx"]))[-5:]
        for fam in T.SF.FAMILIES:
            c = rep["candidates"][fam]
            d = _env.Path(rep["run_dir"]) / "models" / fam
            meta, model = T.load_candidate(d)
            self.assertEqual(meta["model_hash"], c["model_hash"])
            P1, Q1 = T._predict(model, fam, data, T.TASK_MOVE, pos)
            meta2, model2 = T.load_candidate(d)
            P2, _ = T._predict(model2, fam, data, T.TASK_MOVE, pos)
            np.testing.assert_allclose(P1, P2)
            np.testing.assert_allclose(P1.sum(-1), 1.0, atol=1e-9)
            self.assertTrue((np.diff(Q1, axis=-1) >= -1e-12).all())
            with self.assertRaises(ValueError):
                T.select_shadow("XAUUSD", c["candidate_id"])                # TEST_ONLY never becomes SHADOW


if __name__ == "__main__":
    unittest.main()
