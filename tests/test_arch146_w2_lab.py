"""Fala 2 / grupa lab (Apollo23 1.46): I0226 (sonda SH 'lab' = ta sama reguła co LabService), I0229 (rozjazd wersji bibliotek artefaktu
lab), I0323 (M40 edge_drift NOT_INTEGRATED), I0347 (PELT: wynik identyczny, wrażliwość tylko do 2000 zwrotów), I0524 (świeżość
self-testu kontekstu), I0525 (export-fixture nie nadpisuje golden.json), I0481 (minirocket export-train), I0487 (zakres parytetu MR2),
I0099 (cache NSS pod blokadą), I0787 (polaryzacja impulsów enkodera SpikeBrain + wersja enkodera), I0855 (okna sekwencji lab bez
rozgrzewki - nowa polityka protokołu, stare protokoły bez zmian), I0019 (wersja etykiet zadania SETUP SML-1.0.1 + legacy), I0811
(MarketBehavior.trim: ograniczona pamięć IncRegime, wynik identyczny na każdym barze).
Każdy test nie przechodzi na kodzie sprzed poprawki. Dane SYNTETYCZNE - sprawdzają reguły, nie wartość predykcyjną."""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import tempfile
import time
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

import _env
import numpy as np
from _env import TempData

ROOT = _env.ROOT


def synth_m5(n=600, seed=1, start=datetime(2026, 3, 2, tzinfo=UTC), price=2400.0, scale=0.6):
    rng = np.random.default_rng(seed)
    c = price + np.cumsum(rng.normal(0, scale, n))
    out = []
    for i in range(n):
        o = c[i - 1] if i else c[0]
        h = max(o, c[i]) + abs(rng.normal(0, scale / 2))
        lo = min(o, c[i]) - abs(rng.normal(0, scale / 2))
        out.append({"open_utc": (start + timedelta(seconds=300 * i)).strftime("%Y-%m-%dT%H:%M:%SZ"), "o": float(o), "h": float(h), "l": float(lo),
                    "c": float(c[i]), "tv": int(rng.integers(50, 500)), "spread": 12, "closed": True})
    return out


def _lab_artifact(root: Path, asset: str, family: str, trained_at: str, role: str = "research") -> str:
    from masterquo.lab import protocol as P
    f = P.fit_family("DUMMY", np.zeros((10, len(P.FE.FEATURES))), None, np.array([0, 1] * 5), seed=1, budget=1)
    f.family = family                                   # DUMMY body, family label of the test (the rule is per family label)
    mid = f"LM-{asset}-M5x12-{family}-{trained_at[-8:].replace(':', '')}"
    man = {"model_id": mid, "asset": asset, "family": family, "role": role, "trained_at": trained_at, "horizon": "M5x12", "seq_len": 32,
           "feature_set": P.FE.FEATURE_SET, "features": P.FE.FEATURES, "label_spec": {"side": "LONG", "k_tp_atr": 1.5, "k_sl_atr": 1.0}}
    P.save_artifact(root / "models" / asset, f, man)
    return mid


# ================================================================================================ I0226 (+I0232/I0237/I0242/I0248/I0253/I0258/I0264)
class TestLabEffectiveModelsSHProbe(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo import paths
        self.root = paths.data_dir() / "lab"

    def tearDown(self):
        self.td.close()

    def _probe(self):
        from masterquo.sh import models as SM
        item = next(it for it in SM.REGISTRY if it["id"] == "lab")
        return SM.probe(item, None, "XAUUSD")

    def test_sh_probe_sees_unpinned_latest(self):
        """API /api/v1/lab/train never pins (no ACTIVE.json) - LabService runs the latest artefact, the SH row said NOT_TRAINED."""
        _lab_artifact(self.root, "XAUUSD", "LOGREG", "2026-11-01T10:00:00Z")
        st = self._probe()
        self.assertEqual(st["status"], "SHADOW_ONLY", st)            # 1.46.0: NOT_TRAINED (ACTIVE.json only)
        self.assertIn("LOGREG", st["reason"])
        self.assertIn("nieprzypięty", st["reason"])

    def test_probe_and_lab_service_use_one_rule(self):
        from masterquo.lab import protocol as P
        from masterquo.lab.service import LabService
        old = _lab_artifact(self.root, "XAUUSD", "LOGREG", "2026-11-01T10:00:00Z")
        _lab_artifact(self.root, "XAUUSD", "LOGREG", "2026-11-02T10:00:00Z")
        tree = _lab_artifact(self.root, "XAUUSD", "TREE", "2026-11-03T10:00:00Z")
        P.set_active(self.root, "XAUUSD", "LOGREG", old, "test")              # pinned older LOGREG, TREE unpinned (latest)
        eff = {m["family"]: (m["model_id"], m["pinned"]) for m in P.effective_models(self.root, "XAUUSD")}
        self.assertEqual(eff, {"LOGREG": (old, True), "TREE": (tree, False)})
        svc = LabService.__new__(LabService)                                    # only the model-selection part of the service
        svc.trainer, svc._models = P.LabTrainer(None, self.root), {}
        ran = {got[2]["model_id"] for got in LabService._active_models(svc, "XAUUSD")}
        self.assertEqual(ran, {old, tree})
        st = self._probe()
        self.assertEqual(st["status"], "SHADOW_ONLY")
        self.assertEqual({d["family"]: d["model_id"] for d in st["detail"]["models"]}, {"LOGREG": old, "TREE": tree})
        self.assertIn("przypięty", st["reason"])

    def test_no_artifact_is_not_trained(self):
        self.assertEqual(self._probe()["status"], "NOT_TRAINED")


# ================================================================================================ I0229 (+I0235/I0240/I0245/I0251/I0256/I0261/I0267)
class TestLabArtifactDependencyDrift(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.root = Path(self.td.dir) / "lab"

    def tearDown(self):
        self.td.close()

    def test_manifest_pins_xgboost_and_drift_is_reported(self):
        import importlib.util

        from masterquo.lab import protocol as P
        mid = _lab_artifact(self.root, "XAUUSD", "DUMMY", "2026-11-01T10:00:00Z")
        d = self.root / "models" / "XAUUSD" / mid
        man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        if importlib.util.find_spec("xgboost") is not None:
            self.assertIn("xgboost", man["dependencies"])                       # 1.46.0: python / numpy / scikit-learn only
        _, got = P.load_artifact(d, asset="XAUUSD", feature_set=P.FE.FEATURE_SET)
        self.assertEqual(got.get("dependency_drift"), [])                       # same environment -> no drift
        man["dependencies"]["scikit-learn"] = "0.0.1"
        (d / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
        fitted, got = P.load_artifact(d, asset="XAUUSD", feature_set=P.FE.FEATURE_SET)   # never refused for drift (no change of the model set)
        self.assertTrue(any(x.startswith("scikit-learn 0.0.1->") for x in got["dependency_drift"]), got.get("dependency_drift"))
        # the inference telemetry carries the warning (visible in the panel / models check)
        from masterquo.lab.service import LabService
        svc = LabService.__new__(LabService)
        res = LabService._infer(svc, "XAUUSD", synth_m5(400), "LTR-test", (str(d), fitted, got))
        self.assertEqual(res["status"], "ready")
        self.assertTrue(any(w.startswith("ZALEZNOSCI_INNE_NIZ_PRZY_TRENINGU") for w in res["telemetry"]["warnings"]))
        self.assertEqual(res["dependency_drift"], got["dependency_drift"])

    def test_old_manifest_without_xgboost_loads_as_before(self):
        from masterquo.lab import protocol as P
        mid = _lab_artifact(self.root, "XAUUSD", "DUMMY", "2026-11-01T10:00:00Z")
        d = self.root / "models" / "XAUUSD" / mid
        man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        man["dependencies"].pop("xgboost", None)
        (d / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
        _, got = P.load_artifact(d, asset="XAUUSD", feature_set=P.FE.FEATURE_SET)
        self.assertEqual(got["dependency_drift"], [])


# ================================================================================================ I0323
class TestTraceabilityM40NotIntegrated(unittest.TestCase):
    def test_edge_drift_marked_not_integrated_while_uncalled(self):
        from masterquo.lab import traceability as TR
        calls = []
        for p in (ROOT / "backend" / "masterquo").rglob("*.py"):
            rel = p.relative_to(ROOT / "backend" / "masterquo").as_posix()
            if rel in ("lab/edge.py", "lab/traceability.py") or rel.startswith("modelhub/smoke/"):
                continue
            if "edge_drift(" in p.read_text(encoding="utf-8", errors="replace"):
                calls.append(rel)
        row = next(r for r in TR.ROWS if r["id"] == "M40")
        if not calls:
            self.assertTrue(row["integration"].startswith("NOT_INTEGRATED"), row["integration"])     # 1.46.0: 'Badania i walidacja'
        md = (ROOT / "REQUIREMENTS_TRACEABILITY.md").read_text(encoding="utf-8")
        line = next(x for x in md.splitlines() if x.startswith("| M40 |"))
        self.assertIn("NOT_INTEGRATED", line)


# ================================================================================================ I0347
def _legacy_solve(r, m, beta=None):
    """Copy of the 1.46.0 DP (sorted(set(active)) every step, cost through the lambda) - reference for 'identical result'."""
    n = len(r)
    mu = sum(r) / n
    var_all = sum((x - mu) ** 2 for x in r) / n
    eps = 1e-8 * var_all
    if beta is None or beta <= 0:
        beta = 2 * math.log(n)
    from masterquo.lab.change_points import pelt as P
    C, M = P.segment_cost_table(r, eps)
    prune = P.guard(M, m, eps)
    F = [P.INF] * (n + 1)
    cp = [-1] * (n + 1)
    F[0] = -beta
    active, prune_at, evals = [0], {}, 0
    for t in range(m, n + 1):
        best, arg = P.INF, -1
        for tau in active:
            if t - tau < m or F[tau] == P.INF:
                continue
            v = F[tau] + C(tau, t) + beta
            evals += 1
            if v < best:
                best, arg = v, tau
        F[t], cp[t] = best, arg
        if prune and best < P.INF:
            for tau in active:
                if t - tau >= m and F[tau] < P.INF and F[tau] + C(tau, t) > F[t] and tau not in prune_at:
                    prune_at[tau] = t + m
            active = [tau for tau in active if not (tau in prune_at and prune_at[tau] <= t)]
        if t - m + 1 >= m:
            active.append(t - m + 1)
        active = sorted(set(active))
    return F[n], cp, evals


class TestPeltPerformanceSameResult(unittest.TestCase):
    def test_solve_identical_to_previous_dp(self):
        from masterquo.lab.change_points import pelt as P
        for seed in range(5):
            rnd = random.Random(seed)
            r = [rnd.gauss(0, s) for s in [0.01] * 150 + [0.03] * 120 + [0.006] * 130]
            if seed == 4:
                r = [0.0] * 30 + r + [0.0] * 30                                 # guard fails -> unpruned DP
            for m in (5, 10):
                got = P.solve(r, m)
                obj, _cp, evals = _legacy_solve(r, m)
                self.assertEqual(got["objective"], obj, (seed, m))              # bit-identical objective
                self.assertEqual(got["cost_evaluations"], evals)
                self.assertEqual(got["change_points"], P.brute_force(r, m)["change_points"])

    def test_sensitivity_skipped_for_large_lookback(self):
        from masterquo.lab.change_points import pelt as P
        calls = []

        def stub(r, m=10, beta=None, *a, **k):
            calls.append(len(r))
            return {"status": "OK", "change_points": [], "segments": [], "beta": 2 * math.log(max(len(r), 2)), "n": len(r)}
        rnd = random.Random(3)
        closes = [100.0]
        for _ in range(5000):
            closes.append(closes[-1] * math.exp(rnd.gauss(0, 0.002)))
        with mock.patch.object(P, "solve", side_effect=stub):
            d = P.detect(closes, lookback_returns=5000, m=10, sensitivity=True)
            self.assertEqual(len(calls), 1, calls)                              # 1.46.0: 11 solves (~40-50 s CPU in the API process)
            self.assertEqual(d["sensitivity_skipped"], "LOOKBACK_GT_2000")
            calls.clear()
            d2 = P.detect(closes, lookback_returns=1500, m=10, sensitivity=True)
            self.assertEqual(len(calls), 11)                                    # small lookback: unchanged analysis
            self.assertNotIn("sensitivity_skipped", d2)


# ================================================================================================ I0524
class TestCtxNativeStatusStale(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ctx_nat_"))
        self.files = self.tmp / "MQL5" / "Files" / "PMW"
        self.files.mkdir(parents=True)
        (self.tmp / "MQL5" / "Scripts" / "PMW").mkdir(parents=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _status(self, errors, sha, ex5=()):
        st = {"compile_errors": errors, "ex5_files": list(ex5), "ex5_sha256": sha, "selftest_result": "NATIVE_NOT_EXECUTED",
              "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        p = self.files / "ctx_native_status.json"
        p.write_text(json.dumps(st), encoding="utf-8")
        return p

    def _selftest(self, age_s):
        p = self.files / "ctx_selftest.txt"
        p.write_text("PWM_CONTEXT_SELFTEST RESULT=PASS failures=0", encoding="utf-8")
        t = time.time() - age_s
        os.utime(p, (t, t))

    def test_old_selftest_is_not_evidence_after_failed_compile(self):
        from masterquo.lab.context_ind import native as NV
        self._selftest(3600)
        st = NV.native_status(self._status(2, None))
        self.assertEqual(st["NATIVE_COMPILED"], "FAIL")
        self.assertNotEqual(st["NATIVE_EXECUTED"], "PASS", st)                 # 1.46.0: PASS from the previous build

    def test_selftest_older_than_new_ex5_is_stale(self):
        from masterquo.lab.context_ind import native as NV
        self._selftest(3600)
        ex5 = self.tmp / "MQL5" / "Scripts" / "PMW" / "PWM_ContextSelfTest.ex5"
        ex5.write_bytes(b"x")
        st = NV.native_status(self._status(0, "abc", [ex5.name]))
        self.assertEqual(st["NATIVE_COMPILED"], "PASS")
        self.assertNotEqual(st["NATIVE_EXECUTED"], "PASS")
        self.assertTrue(st.get("selftest_stale"))

    def test_fresh_selftest_after_compile_is_pass(self):
        from masterquo.lab.context_ind import native as NV
        ex5 = self.tmp / "MQL5" / "Scripts" / "PMW" / "PWM_ContextSelfTest.ex5"
        ex5.write_bytes(b"x")
        t = time.time() - 120
        os.utime(ex5, (t, t))
        p = self._status(0, "abc", [ex5.name])
        os.utime(p, (t, t))
        self._selftest(0)
        st = NV.native_status(p)
        self.assertEqual((st["NATIVE_COMPILED"], st["NATIVE_EXECUTED"]), ("PASS", "PASS"))


# ================================================================================================ I0525
class TestCtxExportFixtureKeepsGolden(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ctx_fix_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_existing_golden_is_not_regenerated(self):
        import contextlib
        import io

        from masterquo.lab.context_ind import cli
        from masterquo.lab.context_ind import native as NV
        out, files = self.tmp / "fx", self.tmp / "files"
        out.mkdir()
        gold = {"katz": [], "bars": NV.frozen_inputs(30), "tick": 0.01, "tf_s": 300, "reference_rows": [{"marker": "FROZEN_BY_REVIEW"}]}
        (out / "golden.json").write_text(json.dumps(gold), encoding="utf-8")
        before = (out / "golden.json").read_bytes()
        with contextlib.redirect_stdout(io.StringIO()):
            rc = cli.main(["export-fixture", "--out", str(out), "--files-dir", str(files)])
        self.assertEqual(rc, 0)
        self.assertEqual((out / "golden.json").read_bytes(), before)           # 1.46.0: overwritten with the current code's rows
        csv = (files / "PMW" / "ctx_fixture_bars.csv").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(csv), 1 + 30)
        self.assertEqual(csv[1].split(",")[0], str(int(gold["bars"][0]["open_utc"])))
        with contextlib.redirect_stdout(io.StringIO()):                        # explicit regeneration only on request
            self.assertEqual(cli.main(["export-fixture", "--out", str(out), "--regenerate-golden"]), 0)
        self.assertNotEqual((out / "golden.json").read_bytes(), before)

    def test_missing_golden_is_created(self):
        import contextlib
        import io

        from masterquo.lab.context_ind import cli
        out = self.tmp / "new"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["export-fixture", "--out", str(out)]), 0)
        self.assertIn("reference_rows", json.loads((out / "golden.json").read_text(encoding="utf-8")))


# ================================================================================================ I0481
class TestMiniRocketExportTrain(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def _dataset(self, n=2600):
        from masterquo.lab import structure_task as T
        rng = np.random.default_rng(5)
        t = 1_772_409_600.0 + 60.0 * np.arange(n)
        c = 2000 + np.cumsum(rng.normal(0, 0.4, n))
        atr = np.full(n, 0.6)
        F = rng.normal(size=(n, len(T.TAB)))
        Y = rng.integers(0, 3, size=(n, 3))
        R = rng.normal(size=(n, 3))
        rows = np.arange(T.WARMUP, n - 16)
        data = {"fe": {"F": F, "t": t, "c": c, "atr": atr}, "Y": Y, "R": R, "rows_idx": rows, "symbol": "XAUUSD-", "raw": "synthetic",
                "dataset_id": "RAW-SYN", "data_kind": "SYNTHETIC_TEST", "profile": T.indicator_profile("XAUUSD"), "tick": 0.01,
                "content_hash": "x", "task": T.TASK_MOVE}
        return T.save_dataset("XAUUSD", data)

    def test_cli_accepts_export_train_and_writes_fit_rows(self):
        import contextlib
        import io

        from masterquo.lab import minirocket_v2 as MR
        from masterquo.lab import si_families as SF
        from masterquo.lab import structure_cli as SC
        from masterquo.lab import structure_task as T
        out = Path(self.td.dir) / "exp"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = SC.main(["minirocket", "export-train", "--asset", "XAUUSD", "--output", str(out)])   # 1.46.0: argparse SystemExit(2)
        self.assertEqual(rc, 2)
        self.assertIn("BLOCKED_NO_DATASET", buf.getvalue())
        self._dataset()
        with contextlib.redirect_stdout(io.StringIO()):
            rc = SC.main(["minirocket", "export-train", "--asset", "XAUUSD", "--output", str(out), "--profile", "quick"])
        self.assertEqual(rc, 0)
        arr = MR.read_model_bin(out / "PMW_MR2_TRAIN.bin")
        data = T.load_dataset(T.latest_dataset("XAUUSD", T.TASK_MOVE), T.TASK_MOVE)
        sp = T.split(data)
        from masterquo.ml import scalp_task as stk
        fb = stk.inner_blocks(sp["dev"], sp["rows"], sp["embargo_s"])
        fit, _ = SF.mr_fit_rows(fb["FIT"], T.PROFILES["quick"])
        meta = arr["META"]
        self.assertEqual((int(meta[0]), int(meta[2]), int(meta[3])), (128, len(fit), 3))
        _, Y, _ = T._task_arrays(data, T.TASK_MOVE)
        np.testing.assert_array_equal(np.asarray(arr["YCLS"]).reshape(len(fit), 3), Y[fit])

    def test_fit_rows_cap_is_the_training_rule(self):
        from masterquo.lab import si_families as SF
        fit = np.arange(100, 4100)
        rows, note = SF.mr_fit_rows(fit, {"mr_max_fit_rows": 1500})
        np.testing.assert_array_equal(rows, fit[-1500:])
        self.assertIn("1500", note)
        rows2, note2 = SF.mr_fit_rows(fit, {"mr_max_fit_rows": None})
        np.testing.assert_array_equal(rows2, fit)
        self.assertIsNone(note2)


# ================================================================================================ I0487
class TestMR2ParityScope(unittest.TestCase):
    def test_parity_reports_scope_per_result(self):
        from masterquo.lab import minirocket_v2 as MR
        r = MR.parity(ROOT / "tests" / "fixtures" / "minirocket")
        sc = r["scope"]                                                          # 1.46.0: KeyError
        self.assertEqual(set(sc), set(MR.PARITY_STATES))
        self.assertTrue(sc["FROZEN_STATE_PARITY"].startswith("PYTHON_VS_SKTIME"))
        self.assertTrue(sc["FIT_LAYOUT_PARITY"].startswith("PYTHON_VS_SKTIME"))
        self.assertEqual(sc["NATIVE_EXECUTED"], "MQL5_TERMINAL")
        src = (ROOT / "mql5" / "MiniRocketV2" / "Scripts" / "PMW_MR2_SelfTest.mq5").read_text(encoding="utf-8")
        self.assertIn('"NATIVE_FROZEN_STATE_PARITY hit counts', src)


# ================================================================================================ I0099
class TestNssSelectedBundleCacheRace(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_concurrent_clear_between_store_and_read(self):
        from masterquo.lab import nss as N

        class Racing(dict):
            def __getitem__(self, k):            # another thread (other instrument / version) cleared the cache after our store
                self.clear()
                return dict.__getitem__(self, k)
        run_dir = Path(self.td.dir) / "run1"
        (run_dir / "bundle").mkdir(parents=True)
        (run_dir / "bundle" / "manifest.json").write_text("{}", encoding="utf-8")
        reg = {"selected": {"run_id": "R1", "model_hash": "H1"}, "runs": {"R1": {"run_dir": str(run_dir)}}}
        (N.root("XAUUSD") / "registry.json").write_text(json.dumps(reg), encoding="utf-8")
        bundle = type("B", (), {"man": {"model_hash": "H1"}})()
        with mock.patch.object(N, "_cache", Racing()), mock.patch.object(N, "load_bundle", return_value=bundle):
            b, sel = N.selected_bundle("XAUUSD")                                 # 1.46.0: KeyError
        self.assertIs(b, bundle)
        self.assertEqual(sel["run_id"], "R1")
        self.assertTrue(hasattr(N, "_cache_lock"))


# ================================================================================================ I0787
class TestSpikeEncoderPolarity(unittest.TestCase):
    def test_impulse_polarity_follows_the_accumulator(self):
        from masterquo.lab import spike_brain as SB
        e = SB.EventEncoder(1, warmup=3)
        e.n[0], e.mu[0], e.var[0], e.acc[0] = 50, 0.0, 1.0, 2.5               # residual +2.5, theta = 1
        out = e.step(np.array([-0.3]), 1.0)                                      # a = 2.2 -> two impulses of the POSITIVE accumulator
        self.assertEqual(out["tokens"].tolist(), [2.0, 0.0])                      # 1.46.0: [0, 2] (OFF by the sign of z)
        self.assertAlmostEqual(e.acc[0], 0.2)
        e2 = SB.EventEncoder(1, warmup=3)
        e2.n[0], e2.mu[0], e2.var[0], e2.acc[0] = 50, 0.0, 1.0, -2.5
        self.assertEqual(e2.step(np.array([0.3]), 1.0)["tokens"].tolist(), [0.0, 2.0])

    def test_old_spike_artifacts_are_incompatible(self):
        from masterquo.lab import si_families as SF
        from masterquo.lab import spike_brain as SB
        with self.assertRaises(ValueError) as cm:                                  # SHADOW-only model: ABSTAIN / refused selection
            SF.load_spike(Path(tempfile.gettempdir()) / "no_such_sb", {"sb": {"encoder": "BAR_EVENT_V1", "encoder_cfg": {}}})
        self.assertIn("INCOMPATIBLE_ARTIFACT", str(cm.exception))
        self.assertIn(SB.ENCODER_VERSION, str(cm.exception))


# ================================================================================================ I0855
class TestLabSequencesWarmupWindow(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_training_samples_have_no_warmup_in_the_window(self):
        from masterquo.lab import protocol as P
        bars = synth_m5(700, seed=4)
        prot = P.default_protocol("XAUUSD", families=("DUMMY",), experiments=())
        st = P.Study(None, prot, bars, point=0.01, data_source="SYNTHETIC", instrument_id=None)
        prep = st.prepare()
        warm, L = prep["fm"]["warmup"], prot["seq_len"]
        bad = [int(i) for i in prep["idx"] if warm[i - L + 1:i + 1].any()]
        self.assertEqual(bad, [])                                                  # 1.46.0: first ~31 samples had zero-filled tv_pct
        Xs = P.FE.sequences(prep["fm"]["X"], prep["idx"], L)
        self.assertFalse(np.isnan(P.FE.sequences(prep["fm"]["X"], prep["idx"], L, fill=None)).any())
        self.assertEqual(Xs.shape[0], len(prep["idx"]))

    def test_legacy_protocol_keeps_its_samples(self):
        from masterquo.lab import protocol as P
        bars = synth_m5(700, seed=4)
        prot = P.default_protocol("XAUUSD", families=("DUMMY",), experiments=())
        legacy = {k: v for k, v in prot.items() if k != "seq_window"}
        st = P.Study(None, legacy, bars, point=0.01, data_source="SYNTHETIC", instrument_id=None)
        prep = st.prepare()
        fm, lb = prep["fm"], prep["lb"]
        old = np.where((~fm["warmup"]) & (lb["y"] >= 0) & (np.arange(len(bars)) >= legacy["seq_len"]))[0]
        np.testing.assert_array_equal(prep["idx"], old)
        self.assertNotEqual(prot["protocol_id"], P.default_protocol("XAUUSD", families=("DUMMY",), experiments=(), seq_window=None)["protocol_id"])


# ================================================================================================ I0019
class TestStructureSetupLabelsVersion(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def _candidate(self, d: Path, task: str, labels_version: str) -> None:
        d.mkdir(parents=True)
        np.savez(d / "tabular.npz", mu=np.zeros(3), sd=np.ones(3), W_0=np.zeros((4, 3)), beta_0=np.zeros(3), resq_0=np.zeros((3, 3)))
        h = hashlib.sha256((d / "tabular.npz").read_bytes()).hexdigest()
        meta = {"task_id": task, "family": "LOGREG", "n_heads": 1, "labels_version": labels_version, "model_hash": h, "role": "RESEARCH"}
        (d / "candidate.json").write_text(json.dumps(meta), encoding="utf-8")

    def test_setup_labels_version_and_legacy_flag(self):
        from masterquo.lab import structure_task as T
        self.assertEqual(T.labels_version_for(T.TASK_MOVE), "SML-1.0.0")          # MOVE dataset did not change
        self.assertEqual(T.labels_version_for(T.TASK_SETUP), "SML-1.0.1")         # 1.46: trigger bar instead of the entry bar
        old = Path(self.td.dir) / "c_old"
        self._candidate(old, T.TASK_SETUP, "SML-1.0.0")
        meta, _ = T.load_candidate(old)
        self.assertTrue(meta["labels_legacy"])                                      # 1.46.0: no flag
        self.assertIn("SML-1.0.1", meta["labels_warning"])
        new = Path(self.td.dir) / "c_new"
        self._candidate(new, T.TASK_SETUP, "SML-1.0.1")
        self.assertFalse(T.load_candidate(new)[0]["labels_legacy"])
        mv = Path(self.td.dir) / "c_move"
        self._candidate(mv, T.TASK_MOVE, "SML-1.0.0")
        self.assertFalse(T.load_candidate(mv)[0]["labels_legacy"])

    def test_setup_dataset_version_and_legacy_dataset_refused(self):
        from masterquo.lab import structure_task as T
        n = 400
        data = {"fe": {"F": np.zeros((n, len(T.TAB))), "t": 1_772_409_600.0 + 60.0 * np.arange(n), "c": np.full(n, 2000.0), "atr": np.ones(n)},
                "Y": np.zeros((n, 3)), "R": np.zeros((n, 3)), "rows_idx": np.arange(200, 380), "symbol": "XAUUSD-", "raw": "s", "dataset_id": "RAW",
                "data_kind": "SYNTHETIC_TEST", "profile": T.indicator_profile("XAUUSD"), "tick": 0.01, "content_hash": "x", "task": T.TASK_SETUP,
                "setup_y": np.zeros(3), "setup_r": np.zeros(3), "setup_idx": np.array([250, 300, 350])}
        man = T.save_dataset("XAUUSD", data)
        self.assertEqual(man["labels_version"], "SML-1.0.1")                       # 1.46.0: SML-1.0.0
        d = T.root("XAUUSD") / "datasets" / man["dataset_id"]
        m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        m["labels_version"] = "SML-1.0.0"                                           # dataset built by 1.45 (entry-bar look-ahead)
        (d / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
        rep = T.train("XAUUSD", d, T.TASK_SETUP, ["LOGREG"], "quick", log=lambda *_: None)
        self.assertEqual(rep["status"], "STALE_DATASET")
        self.assertIn("SML-1.0.1", rep["reason"])


# ================================================================================================ I0811
def _regime_bars(n=6000, seed=11):
    rng = np.random.default_rng(seed)
    t0 = datetime(2026, 1, 5, tzinfo=UTC).timestamp()
    out, c = [], 2000.0
    drift = 0.0
    for i in range(n):
        if i % 250 == 0:
            drift = float(rng.choice([-0.35, -0.1, 0.0, 0.0, 0.1, 0.35]))
        o = c
        c = round(o + drift + rng.normal(0, 0.8), 2)
        out.append({"open_utc": datetime.fromtimestamp(t0 + 300 * i, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "o": o,
                    "h": round(max(o, c) + abs(rng.normal(0, 0.4)), 2), "l": round(min(o, c) - abs(rng.normal(0, 0.4)), 2), "c": c})
    return out


def _retained(mb) -> int:
    c = mb.c
    return c.retained() if hasattr(c, "retained") else len(c)


class TestIncRegimeBounded(unittest.TestCase):
    def test_market_behavior_is_bounded_with_identical_regime(self):
        from masterquo.sh.context import IncRegime
        bars = _regime_bars()
        ref = IncRegime(0.01)
        ref.MB_MAX_BARS = 10 ** 9                                                    # never trimmed = 1.46.0 behaviour
        hot = IncRegime(0.01)
        hot.MB_MAX_BARS, hot.MB_KEEP_BARS = 400, 120                                 # trimmed every ~280 bars
        dflt = IncRegime(0.01)
        states = set()
        for k, b in enumerate(bars):
            for x in (ref, hot, dflt):
                x.feed(b)
            self.assertEqual(hot.view, ref.view, k)
            self.assertEqual(dflt.view, ref.view, k)
            self.assertEqual(hot.public(), ref.public(), k)
            self.assertEqual(hot.mb.bias_at(k), ref.mb.bias_at(k), k)
            states.add((ref.view or {}).get("state"))
        self.assertEqual(hot.mb.story(), ref.mb.story())
        self.assertGreaterEqual(len(states - {None, "WARMING_UP"}), 2, states)        # the series exercises the hysteresis
        self.assertEqual(_retained(ref.mb), 6000)
        self.assertLessEqual(_retained(dflt.mb), 3000)                                  # 1.46.0: 6000 (unbounded)
        self.assertLessEqual(_retained(hot.mb), 400)
        self.assertLess(len(dflt.mb.bias_hist), len(ref.mb.bias_hist))
        self.assertLess(len(dflt.mb.swings), len(ref.mb.swings))
        self.assertLess(len(dflt.mb.events), len(ref.mb.events))                         # last 500 kept at a trim (+ events since)
        with self.assertRaises(IndexError):                                              # a dropped bar is never read silently
            hot.mb.c[0]


if __name__ == "__main__":
    unittest.main()
