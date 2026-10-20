"""PMW-UPD-14 VS06/VS08: Buffer Inspector report import + heuristics, mapping validation/rollback, bridge importer (whitelist, context,
mapping version, seq, TTL, finite, sentinel), FS_VS_CONTEXT_v1 calibration ledger/dataset/training on a TEST_ONLY synthetic export.
No MT5 connection, no orders."""
import json
import tempfile
import time
import unittest
from pathlib import Path

import _env  # noqa: F401
from _env import TempData

from masterquo.extind.contract import EnvelopeError
from masterquo.lab.context_ind import buffers as B
from test_structure_intelligence import m1_bars, write_export


def _report(n_inst=2, same_name=True, rng=(0, 511)):
    line = [2000 + 0.1 * i for i in range(300)]
    sparse = [B.EMPTY_VALUE] * 300
    sparse[17] = sparse[200] = 1999.5
    state = [float(i % 3) for i in range(300)]
    inst = []
    for k in range(n_inst):
        inst.append({"chart_id": 1, "window": 0, "short_name": "Foo" if same_name else f"Foo{k}", "buffers": [
            {"index": 0, "status": "READABLE", "sample": line}, {"index": 1, "status": "READABLE", "sample": sparse},
            {"index": 2, "status": "READABLE", "sample": state}, {"index": 3, "status": "PENDING"}]})
    return {"terminal_build": 5000, "symbol": "XAUUSD-", "tf": "M5", "scan_range": {"from": rng[0], "to": rng[1]},
            "capability": {"DATA": "READABLE", "COLOR_INDEX": "READABLE", "CALCULATIONS": "UNREADABLE"}, "instances": inst}


GOOD = {"indicator_path": "Market/Foo", "input_hash": "abc", "buffer": 0, "units": "PRICE", "direction_semantics": "NONE_LEVEL_ONLY",
        "empty_sentinel": "EMPTY_VALUE", "zero_is_valid": True, "shift_policy": "SHIFT1_CLOSED", "plot_shift": 0, "confirmation_policy": "CLOSED_BAR",
        "symbol": "XAUUSD-", "tf": "M5"}


class HeuristicTests(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(B.classify([])["type"], "UNKNOWN")
        self.assertEqual(B.classify([B.EMPTY_VALUE] * 10)["type"], "EMPTY_OBSERVED")
        self.assertLess(B.classify([B.EMPTY_VALUE] * 10)["confidence"], 0.5)
        self.assertEqual(B.classify([1.0 + 0.01 * i for i in range(100)])["type"], "LINE_LIKE")
        r = B.classify([float(i % 2) for i in range(100)])
        self.assertEqual(r["type"], "INTEGER_STATE_LIKE")
        self.assertIn("LINE_LIKE", r["alternatives"])                    # hypothesis, never a declared COLOR/BUY role
        self.assertEqual(B.classify([None] * 95 + [1.0] * 5)["type"], "SPARSE_EVENT_LIKE")
        self.assertEqual(B.classify([0.0] * 50, empty_sentinel=0.0)["type"], "EMPTY_OBSERVED")


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_import_and_tamper(self):
        raw = B.wrap(B.REPORT_SCHEMA, _report())
        d = B.import_report(raw)
        self.assertEqual(d["coverage"], "FULL_0_511")
        self.assertTrue(all(i["ambiguous"] for i in d["instances"]))
        bt = [b.get("hypothesis", {}).get("type") for b in d["instances"][0]["buffers"]]
        self.assertEqual(bt, ["LINE_LIKE", "SPARSE_EVENT_LIKE", "INTEGER_STATE_LIKE", "UNKNOWN"])
        self.assertEqual(B.list_reports()[0]["report_id"], d["report_id"])
        self.assertIsNotNone(B.get_report(d["report_id"]))
        self.assertIsNone(B.get_report("../etc/passwd"))
        d2 = B.import_report(B.wrap(B.REPORT_SCHEMA, _report(same_name=False, rng=(0, 63))))
        self.assertEqual(d2["coverage"], "PARTIAL_INDEX_RANGE")
        self.assertFalse(any(i["ambiguous"] for i in d2["instances"]))
        bad = json.loads(raw)
        bad["body"] = bad["body"].replace("5000", "5001")
        with self.assertRaises(EnvelopeError):
            B.import_report(json.dumps(bad).encode())
        with self.assertRaises(EnvelopeError):
            B.import_report(B.wrap(B.BRIDGE_SCHEMA, _report()))


class MappingBridgeTests(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.files = tempfile.mkdtemp()

    def tearDown(self):
        self.td.close()

    def _bridge(self, m, seq=1, hb=None, rows=None, symbol="XAUUSD-", epoch=1):
        p = Path(self.files) / "PMW" / B.BridgeImporter.NAME
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(B.wrap(B.BRIDGE_SCHEMA, {"mapping_id": m["mapping_id"], "mapper_version": m["mapper_version"], "symbol": symbol, "tf": "M5",
                                              "epoch": epoch, "seq": seq, "heartbeat_utc": time.time() if hb is None else hb,
                                              "rows": rows if rows is not None else [{"source_bar": "2026-03-02T00:00:00Z", "raw": 2001.5},
                                                                                     {"source_bar": "2026-03-02T00:05:00Z", "raw": B.EMPTY_VALUE}]}))

    def test_mapping_validation_and_rollback(self):
        self.assertEqual(B.validate_mapping(GOOD)["status"], "VERIFIED_TECHNICAL")
        v = B.validate_mapping(dict(GOOD, units=None, plot_shift="UNKNOWN"))
        self.assertEqual(v["status"], "MAPPING_INCOMPLETE")
        self.assertIn("units", v["missing"])
        self.assertTrue(any("PLOT_SHIFT_UNKNOWN" in p for p in v["problems"]))
        self.assertIn("DIRECTION_FROM_COLOR_NOT_ALLOWED", B.validate_mapping(dict(GOOD, direction_semantics="COLOR_GUESS"))["problems"])
        self.assertIn("BUFFER_OUT_OF_RANGE", B.validate_mapping(dict(GOOD, buffer=600))["problems"])
        m1 = B.save_mapping(GOOD)
        m2 = B.save_mapping(GOOD)
        self.assertEqual(m1["mapping_id"], m2["mapping_id"])
        self.assertEqual(m2["mapper_version"], 2)
        B.rollback_mapping(m1["mapping_id"])
        self.assertEqual(B.mappings(), {})
        with self.assertRaises(ValueError):
            B.rollback_mapping("BM-x")

    def test_bridge(self):
        self.assertEqual(B.BridgeImporter(None).poll("XAUUSD-", "M5")["status"], "UNAVAILABLE")
        imp = B.BridgeImporter(self.files)
        self.assertEqual(imp.poll("XAUUSD-", "M5")["status"], "UNAVAILABLE")
        bad = B.save_mapping(dict(GOOD, indicator_path="Bar", units=None))
        self._bridge(bad)
        self.assertEqual(imp.poll("XAUUSD-", "M5")["status"], "MAPPING_INCOMPLETE")
        m = B.save_mapping(GOOD)
        self._bridge(dict(m, mapper_version=99))
        self.assertEqual(imp.poll("XAUUSD-", "M5")["status"], "MISSING_MAPPING")
        self._bridge(m, symbol="BTCUSD")
        self.assertEqual(imp.poll("XAUUSD-", "M5")["reason"], "CONTEXT_MISMATCH")
        self._bridge(m, hb=time.time() - 3600)
        self.assertEqual(imp.poll("XAUUSD-", "M5")["status"], "STALE")
        self._bridge(m, seq=5)
        r = imp.poll("XAUUSD-", "M5")
        self.assertEqual(r["status"], "AVAILABLE_UNVALIDATED")
        self.assertEqual([x["empty"] for x in r["rows"]], [False, True])
        self.assertIn("SHADOW", r["role"])
        self.assertEqual(imp.poll("XAUUSD-", "M5")["status"], "STALE_SEQUENCE")       # duplicate delivery idempotent
        self._bridge(m, seq=1, epoch=2)                                                # new epoch restarts seq
        self.assertEqual(imp.poll("XAUUSD-", "M5")["status"], "AVAILABLE_UNVALIDATED")
        p = Path(self.files) / "PMW" / B.BridgeImporter.NAME
        p.write_bytes(p.read_bytes().replace(b'"checksum": "', b'"checksum": "0'))
        self.assertEqual(B.BridgeImporter(self.files).poll("XAUUSD-", "M5")["status"], "REJECTED")
        z = B.save_mapping(dict(GOOD, buffer=1, empty_sentinel=0.0, zero_is_valid=False))
        self._bridge(z, seq=9, rows=[{"source_bar": "a", "raw": 0.0}, {"source_bar": "b", "raw": 1.0}])
        self.assertEqual([x["empty"] for x in B.BridgeImporter(self.files).poll("XAUUSD-", "M5")["rows"]], [True, False])


class ContextTaskTests(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_calibrate_dataset_train(self):
        from masterquo.lab.context_ind import task as CT
        ds = Path(self.td.dir) / "raw" / "ds1"
        write_export(ds, m1_bars(n=9000, seed=5))
        from masterquo.extind.trainer import _bars
        m5 = _bars(ds, "XAUUSD", "M5")
        cal = CT.calibrate("XAUUSD", m5, 0.01, {"data_kind": "SYNTHETIC_TEST"})
        self.assertEqual(cal["grid_size"], 24)
        self.assertEqual(len(cal["trials"]), 24)
        self.assertFalse(cal["holdout_read"])
        self.assertEqual(cal["profile"]["source"], "CALIBRATED_ON_DEV")
        man = CT.build_dataset("XAUUSD", ds, log=lambda *_: None)
        self.assertEqual(man["features"], CT.FEATS)
        rep = CT.train("XAUUSD", CT.latest("XAUUSD"), families=("LOGREG",), profile_name="quick", log=lambda *_: None)
        self.assertEqual(rep["role"], "TEST_ONLY")
        self.assertEqual(rep["edge_status"], "NO_VALIDATED_EDGE")
        self.assertIn("_FIXTURE", rep["run_id"])
        self.assertEqual(set(rep["ablations"]) if rep["ablations"] else set(CT.ABLATION), set(CT.ABLATION))
        for c in rep["candidates"].values():
            meta, m = CT.load_candidate(Path(rep["run_dir"]) / "models" / "LOGREG")
            self.assertEqual(meta["role"], "TEST_ONLY")
        # profile change makes the dataset stale (no silent mixing of calibrations)
        p = CT.root("XAUUSD") / "profile.json"
        d = json.loads(p.read_text())
        d["fd"] = {"N": 20, "S": 3}
        p.write_text(json.dumps(d))
        if CT.profile("XAUUSD")["hash"] != man["profile"]["hash"]:
            self.assertEqual(CT.train("XAUUSD", CT.latest("XAUUSD"), families=("LOGREG",), log=lambda *_: None)["status"], "STALE_DATASET")


if __name__ == "__main__":
    unittest.main()
