"""1.40 Granite TTM in the Training Center - bot side (no torch): dataset export from the candle store with validation (too short, duplicate
times, bad OHLC refused), training refused by the Memory Governor (AUTO trading without confirmation, parallel heavy training), activation
only of a checkpoint with intact checksums, the same base fingerprint, the same horizon and the TEST verdict IMPROVED_VS_BASE, written to
the settings history; rollback to BASE. The real fine-tuning (torch) is covered by tests/test_foundation_real.py::TestGraniteFinetuneReal."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import unittest
from pathlib import Path

import _env  # noqa: F401
from _env import TempData

sys.path.insert(0, str(Path(__file__).resolve().parent))


class FakeStore:
    def __init__(self, n=5200, dup=False, bad=False):
        t = [1_700_000_000 + 300 * i for i in range(n)]
        if dup:
            t[10] = t[9]
        c = [4000.0 + (i % 50) * 0.1 for i in range(n)]
        self.cols = {"time": t, "open": c, "high": [x + 1 for x in c], "low": [x - 1 for x in c], "close": c}
        if bad:
            self.cols["high"][5] = self.cols["low"][5] - 5
        self.man = {"symbol": "XAUUSD-", "data_kind": "MT5_DEMO"}

    def read(self, inst, tf):
        return self.cols

    def manifest(self, inst):
        return self.man


class TestGraniteTrainBot(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_export_validation(self):
        from masterquo.tsfm import granite_train as G
        r = G.export("XAUUSD", "M5", store=FakeStore())
        self.assertTrue(r["ok"], r)
        ds = json.loads(Path(r["file"]).read_text(encoding="utf-8"))
        self.assertEqual((ds["bars"], ds["timeframe"], ds["data_kind"]), (5200, "M5", "MT5_DEMO"))
        for st, why in ((FakeStore(n=500), "za mało"), (FakeStore(dup=True), "nie rosną"), (FakeStore(bad=True), "geometrią")):
            r = G.export("XAUUSD", "M5", store=st)
            self.assertFalse(r["ok"])
            self.assertIn(why, r["reason"])

    def _svc(self):
        from masterquo.tsfm.settings import SettingsStore

        class W:
            killed = 0

            def kill(self):
                W.killed += 1

        class Log:
            def info(self, *a):
                pass

        class Svc:
            settings = SettingsStore(Path(self.td.dir) / "tsfm" / "settings.json")
            workers = {"granite_ttm": W()}
            applog = Log()
            _job_procs = {}
        return Svc()

    def _run(self, rid, verdict="IMPROVED_VS_BASE", horizon=12, tamper=False, base=None):
        from masterquo.tsfm import granite_train as G
        from tsfm_runtime import lock as L
        d = G.finetune_dir() / rid
        d.mkdir(parents=True, exist_ok=True)
        files = []
        for name in ("config.json", "model.safetensors"):
            (d / name).write_bytes(name.encode() * 10)
            files.append({"name": name, "sha256": hashlib.sha256(name.encode() * 10).hexdigest(), "size": 0})
        if tamper:
            (d / "model.safetensors").write_bytes(b"changed")
        (d / "granite_finetune.json").write_text(json.dumps({"run_id": rid, "base_fingerprint": base or L.fingerprint("granite_ttm"), "files": files,
                                                             "data": {"timeframe": "M5"}, "train": {"horizon": horizon},
                                                             "metrics": {"verdict": verdict}}), encoding="utf-8")

    def test_activation_rules_history_and_rollback(self):
        from masterquo.tsfm import granite_train as G
        svc = self._svc()
        self._run("GTR-WORSE01", verdict="NOT_BETTER_THAN_BASE")
        self._run("GTR-TAMPER1", tamper=True)
        self._run("GTR-OTHERB1", base="granite_ttm|other@x|granite-tsfm@0")
        self._run("GTR-HORIZ01", horizon=6)
        self._run("GTR-GOOD001")
        for rid, why in (("GTR-WORSE01", "nie jest lepszy"), ("GTR-TAMPER1", "SHA-256"), ("GTR-OTHERB1", "innego modelu bazowego"),
                         ("GTR-HORIZ01", "horyzontu"), ("GTR-MISSING", "brak checkpointu")):
            r = G.activate(svc, rid)
            self.assertFalse(r["ok"], rid)
            self.assertIn(why, r["reason"], rid)
        self.assertEqual(svc.settings.get().models["granite_ttm"].checkpoint, "BASE")
        r = G.activate(svc, "GTR-GOOD001")
        self.assertTrue(r["ok"], r)
        self.assertEqual(svc.settings.get().models["granite_ttm"].checkpoint, "GTR-GOOD001")
        self.assertEqual(svc.settings.history()[-1]["who"], "granite_activate")
        self.assertEqual({x["run_id"] for x in G.runs()}, {"GTR-WORSE01", "GTR-TAMPER1", "GTR-OTHERB1", "GTR-HORIZ01", "GTR-GOOD001"})
        G.rollback(svc)
        self.assertEqual(svc.settings.get().models["granite_ttm"].checkpoint, "BASE")
        self.assertEqual(svc.settings.history()[-1]["who"], "granite_rollback")

    def test_training_refused_by_governor(self):
        from masterquo.tsfm import granite_train as G
        from test_resources_governor import gov
        svc = self._svc()
        svc.governor, _ = gov(used=50.0)
        svc.weights_root = lambda: Path(self.td.dir)
        os.environ["MQ_GRANITE_TTM_PYTHON"] = sys.executable                     # an interpreter exists; the governor decides first
        try:
            r = G.start(svc, "XAUUSD", "M5", trading_active=True)
            self.assertFalse(r["ok"])
            self.assertIn("AUTO", r["reason"])
            svc.governor.training["kronos_train"] = "heavy"
            r = G.start(svc, "XAUUSD", "M5", trading_active=False)
            self.assertFalse(r["ok"])
            self.assertIn("równolegle", r["reason"])
        finally:
            os.environ.pop("MQ_GRANITE_TTM_PYTHON", None)

    def test_checkpoint_setting_is_validated(self):
        from masterquo.tsfm.settings import TsfmSettings
        with self.assertRaises(Exception):
            TsfmSettings.model_validate({"models": {"granite_ttm": {"checkpoint": "../../etc"}}})
        self.assertEqual(TsfmSettings().models["granite_ttm"].checkpoint, "BASE")


if __name__ == "__main__":
    unittest.main()
