"""1.46 audit, group B_mq_lab_1: Buffer Inspector / bridge (zero_is_valid, field types, report structure, corrupt files, locking),
context ledger (persisted epochs, no duplicate events after a restart), DEV/holdout boundary of the VAMD/FD/SMC and flow-context
calibrations (time-based like structure_task.split), S/R as-of comparison, StopDistance / Trade Pad non-finite inputs, Trade Pad currency,
flow SHADOW double rollback, flow native export size / header types, atomic profile writes. No MT5 connection, no orders."""
import contextlib
import hashlib
import io
import json
import math
import tempfile
import threading
import time
import types
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

import _env  # noqa: F401
import numpy as np
from _env import TempData
from masterquo.extind.contract import EnvelopeError, checksum
from masterquo.lab.context_ind import buffers as B
from test_structure_intelligence import write_export

GOOD = {"indicator_path": "Market/Foo", "input_hash": "abc", "buffer": 0, "units": "PRICE", "direction_semantics": "NONE_LEVEL_ONLY",
        "empty_sentinel": "EMPTY_VALUE", "zero_is_valid": True, "shift_policy": "SHIFT1_CLOSED", "plot_shift": 0, "confirmation_policy": "CLOSED_BAR",
        "symbol": "XAUUSD-", "tf": "M5"}


def gapped(segments, step_min: int, seed: int = 5) -> list[dict]:
    """Synthetic bars in contiguous segments; each segment starts after `gap` minutes of no data (weekend / history hole)."""
    rng = np.random.default_rng(seed)
    t, c, out = datetime(2026, 3, 2, tzinfo=UTC), 2000.0, []
    for n, gap in segments:
        t += timedelta(minutes=gap)
        for _ in range(n):
            o = c
            c = o + rng.normal(0, 0.4 * math.sqrt(step_min))
            out.append({"open_utc": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "o": o, "h": max(o, c) + abs(rng.normal(0, 0.2)),
                        "l": min(o, c) - abs(rng.normal(0, 0.2)), "c": c, "tv": 50.0, "spread": 12.0})
            t += timedelta(minutes=step_min)
    return out


def m5(n=1000, seed=4):
    from test_structure_intelligence import m1_bars
    bs = m1_bars(n * 5, seed)
    return [{"open_utc": bs[i]["open_utc"], "o": bs[i]["o"], "h": max(b["h"] for b in bs[i:i + 5]), "l": min(b["l"] for b in bs[i:i + 5]),
             "c": bs[i + 4]["c"]} for i in range(0, len(bs) - 4, 5)]


def holdout_start(t: np.ndarray, rows: np.ndarray) -> float:
    """Open time of the first holdout row according to the protocol itself (structure_task.split)."""
    from masterquo.lab import structure_task as T
    sp = T.split({"fe": {"t": t}, "rows_idx": rows, "manifest": {"task": T.TASK_MOVE}})
    return float(t[rows[sp["hold"][0]]])


def _ts(x) -> float:
    return datetime.fromisoformat(str(x)).timestamp()


class _Writes:
    """Records every Path.write_text target (to prove profile.json is never written in place)."""

    def __init__(self):
        self.paths = []
        self._orig = Path.write_text

    def __call__(self, p, *a, **kw):
        self.paths.append(Path(p))
        return self._orig(p, *a, **kw)


# ============================================================================ Buffer Inspector / bridge
class BufferBridgeTests(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.files = tempfile.mkdtemp()

    def tearDown(self):
        self.td.close()

    def _bridge(self, body: dict):
        p = Path(self.files) / "PMW" / B.BridgeImporter.NAME
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(B.wrap(B.BRIDGE_SCHEMA, body))

    def _body(self, m, **kw):
        return dict({"mapping_id": m["mapping_id"], "mapper_version": m["mapper_version"], "symbol": "XAUUSD-", "tf": "M5", "epoch": 1, "seq": 1,
                     "heartbeat_utc": time.time(), "rows": [{"source_bar": "a", "raw": 1.0}]}, **kw)

    def test_zero_not_valid_with_empty_value_sentinel(self):
        """chunk_17#4: zero_is_valid=False must mark a raw 0 as empty also when the sentinel is EMPTY_VALUE."""
        m = B.save_mapping(dict(GOOD, zero_is_valid=False))
        self.assertEqual(m["validation"]["status"], "VERIFIED_TECHNICAL")
        self._bridge(self._body(m, rows=[{"source_bar": "a", "raw": 0.0}, {"source_bar": "b", "raw": 5.0}]))
        r = B.BridgeImporter(self.files).poll("XAUUSD-", "M5")
        self.assertEqual(r["status"], "AVAILABLE_UNVALIDATED")
        self.assertEqual([(x["value"], x["empty"]) for x in r["rows"]], [(None, True), (5.0, False)])
        m2 = B.save_mapping(dict(GOOD, buffer=2, zero_is_valid=True))               # 0 declared valid stays a value
        self._bridge(self._body(m2, seq=2, rows=[{"source_bar": "a", "raw": 0.0}]))
        self.assertEqual(B.BridgeImporter(self.files).poll("XAUUSD-", "M5")["rows"], [{"source_bar": "a", "value": 0.0, "empty": False}])

    def test_mapping_field_types(self):
        """chunk_17#5: wrong field types are a problem (MAPPING_INCOMPLETE), never VERIFIED_TECHNICAL."""
        self.assertEqual(B.validate_mapping(GOOD)["status"], "VERIFIED_TECHNICAL")
        self.assertEqual(B.validate_mapping(dict(GOOD, empty_sentinel=0.0, zero_is_valid=False, plot_shift=1))["status"], "VERIFIED_TECHNICAL")
        for k, v in (("buffer", "abc"), ("buffer", 3.7), ("buffer", True), ("zero_is_valid", "false"), ("zero_is_valid", 1),
                     ("plot_shift", "x"), ("plot_shift", 1.5), ("empty_sentinel", "foo"), ("shift_policy", 5), ("direction_semantics", ["A"]),
                     ("confirmation_policy", {"a": 1})):
            v_ = B.validate_mapping(dict(GOOD, **{k: v}))
            self.assertEqual(v_["status"], "MAPPING_INCOMPLETE", (k, v))
            self.assertIn(f"FIELD_TYPE_INVALID:{k}", v_["problems"], (k, v))

    def test_import_report_bad_structure_is_envelope_error(self):
        """chunk_17#6: a valid envelope with a malformed body is a rejected report (422), not a TypeError / AttributeError (500)."""
        good = {"terminal_build": 1, "scan_range": {"from": 0, "to": 511},
                "instances": [{"short_name": "Foo", "buffers": [{"index": 0, "status": "READABLE", "sample": [1.0, None, 2.0]}]}]}
        self.assertEqual(B.import_report(B.wrap(B.REPORT_SCHEMA, good))["coverage"], "FULL_0_511")
        bad_bodies = [dict(good, instances=["abc"]), dict(good, instances="abc"),
                      dict(good, instances=[{"short_name": "Foo", "buffers": ["x"]}]),
                      dict(good, instances=[{"short_name": "Foo", "buffers": [{"index": 0, "status": "READABLE", "sample": [1.0, "2.0", None]}]}]),
                      dict(good, instances=[{"short_name": "Foo", "buffers": [{"index": 0, "status": "READABLE", "sample": "abc"}]}]),
                      dict(good, scan_range=[0, 511])]
        for body in bad_bodies:
            with self.assertRaises(EnvelopeError, msg=str(body)[:80]):
                B.import_report(B.wrap(B.REPORT_SCHEMA, body))
        raw = json.dumps({"envelope": B.REPORT_SCHEMA, "checksum": checksum("not json"), "body": "not json"}).encode()
        with self.assertRaises(EnvelopeError):
            B.import_report(raw)

    def test_list_reports_survives_corrupt_file(self):
        """chunk_17#7: one truncated BR-*.json must not break the list; the user's file stays untouched; reports are written atomically."""
        d = B.import_report(B.wrap(B.REPORT_SCHEMA, {"terminal_build": 1, "instances": []}))
        bad = B.reports_dir() / "BR-deadbeef.json"
        bad.write_text('{"report_id": "BR-dead', encoding="utf-8")
        lst = B.list_reports()
        self.assertIn(d["report_id"], [r["report_id"] for r in lst])
        self.assertIn({"report_id": "BR-deadbeef", "status": "CORRUPT", "instances": 0}, lst)
        self.assertEqual(B.get_report("BR-deadbeef")["status"], "CORRUPT")
        self.assertEqual(bad.read_text(encoding="utf-8"), '{"report_id": "BR-dead')
        self.assertEqual([p.name for p in B.reports_dir().iterdir() if p.name.endswith(".tmp")], [])

    def test_corrupt_mappings_not_overwritten_and_locked_saves(self):
        """chunk_17#11: a damaged buffer_mappings.json is read as 'no mappings' (no 500) and is never overwritten; concurrent saves
        keep every mapping (lock + unique tmp)."""
        p = B.mappings_path()
        p.write_text("{oops", encoding="utf-8")
        self.assertEqual(B.mappings(), {})
        with self.assertRaises(ValueError):
            B.save_mapping(GOOD)
        with self.assertRaises(ValueError):
            B.rollback_mapping("BM-x")
        self.assertEqual(p.read_text(encoding="utf-8"), "{oops")
        p.unlink()
        errs = []

        def worker(k):
            try:
                for _ in range(5):
                    B.save_mapping(dict(GOOD, indicator_path=f"Market/Foo{k}"))
            except Exception as exc:                                    # noqa: BLE001
                errs.append(exc)
        ths = [threading.Thread(target=worker, args=(k,)) for k in range(8)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        self.assertEqual(errs, [])
        ms = B.mappings()
        self.assertEqual(len(ms), 8)
        self.assertEqual({m["mapper_version"] for m in ms.values()}, {5})
        B.rollback_mapping(next(iter(ms)))
        self.assertEqual(len(json.loads(p.read_text(encoding="utf-8"))["mappings"]), 7)

    def test_bridge_bad_field_types_rejected(self):
        """chunk_17#12: non-numeric seq / heartbeat, rows of non-objects or a list mapping_id -> REJECTED, not a 500."""
        m = B.save_mapping(GOOD)
        for kw in ({"seq": "x"}, {"seq": None}, {"heartbeat_utc": None}, {"heartbeat_utc": "abc"}, {"rows": ["a"]}, {"rows": "abc"},
                   {"mapping_id": [1, 2]}, {"epoch": [1]}):
            self._bridge(self._body(m, **kw))
            r = B.BridgeImporter(self.files).poll("XAUUSD-", "M5")
            self.assertEqual((r["status"], r.get("reason")), ("REJECTED", "FIELD_TYPE"), kw)
        self._bridge(self._body(m))
        self.assertEqual(B.BridgeImporter(self.files).poll("XAUUSD-", "M5")["status"], "AVAILABLE_UNVALIDATED")


# ============================================================================ context runtime ledger / summary
class ContextLedgerTests(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def _rows(self):
        led = list((Path(self.td.dir) / "context_ind" / "XAUUSD" / "ledger").glob("M5_*.jsonl"))
        self.assertEqual(len(led), 1)
        return [json.loads(x) for x in led[0].read_text(encoding="utf-8").splitlines()]

    def test_restart_keeps_ids_unique_and_does_not_reappend(self):
        """chunk_17#2: after a restart the epoch continues (no E1 collision) and events already in the ledger are not appended again."""
        from masterquo.lab.context_ind.service import ContextSections
        bars = m5(1000)
        k1 = ContextSections().update("XAUUSD", "M5", bars[:800], 0.01)
        n1 = len(self._rows())
        self.assertEqual(n1, len(k1.smc.events))
        k2 = ContextSections().update("XAUUSD", "M5", bars[100:900], 0.01)             # restart: new process state, later window
        self.assertEqual(k2.epoch, k1.epoch + 1)
        rows = self._rows()
        ids = [r["ledger_id"] for r in rows]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertLess(len(rows), n1 + len(k2.smc.events))                         # overlapping window not copied again
        content = [json.dumps([r.get("kind"), r.get("available_at"), r.get("side"), r.get("price"), r.get("level")]) for r in rows]
        self.assertLess(len(content) - len(set(content)), len(k2.smc.events) // 2)
        k3 = ContextSections().update("XAUUSD", "M5", bars[100:900], 0.01)             # identical restart: nothing new to record
        self.assertEqual(k3.epoch, k2.epoch + 1)
        self.assertEqual(len(self._rows()), len(rows))

    def test_summary_unsupported_tf(self):
        """chunk_17#14: an unsupported TF is reported as such, not as a never-ending warm-up."""
        from masterquo.lab.context_ind.service import ContextSections
        cs = ContextSections()
        self.assertIsNone(cs.update("XAUUSD", "M30", m5(100), 0.01))
        self.assertEqual(cs.summary(None, tf="M30")["status"], "NOT_SUPPORTED_TF")
        self.assertEqual(cs.summary(None, tf="M5")["status"], "WARMING_UP")
        self.assertEqual(cs.summary(None)["status"], "WARMING_UP")


# ============================================================================ calibration DEV / holdout boundary + atomic profile
class CalibrationBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_context_calibration_never_reads_holdout(self):
        """chunk_17#0 (+#16): VAMD/FD/SMC calibration bars all lie before the holdout of the CONTEXT_MOVE_M5_V1 dataset (time-based
        split) even with a history gap; profile.json is replaced atomically."""
        from masterquo.lab.context_ind import fractal as FD
        from masterquo.lab.context_ind import smc as SM
        from masterquo.lab.context_ind import task as CT
        from masterquo.lab.context_ind import vamd as VM
        bars = gapped([(1500, 0), (1000, 60 * 24 * 10)], 5)
        fe = CT.features(bars, 0.01)
        rows = np.where((np.arange(len(bars)) >= 80) & np.isfinite(fe["atr"]) & np.isfinite(fe["F"]).all(axis=1))[0]   # as build_dataset
        t_hold = holdout_start(fe["t"], rows)
        seen = []

        def cap(ev, *a, **kw):
            seen.extend(ev)
            return []
        wr = _Writes()
        with mock.patch.object(VM, "series", side_effect=cap), mock.patch.object(FD, "series", side_effect=cap), \
                mock.patch.object(SM, "run", side_effect=lambda ev, *a, **kw: cap(ev) or types.SimpleNamespace(events=[])), \
                mock.patch.object(Path, "write_text", autospec=True, side_effect=wr):
            out = CT.calibrate("XAUUSD", bars, 0.01, {"data_kind": "SYNTHETIC_TEST"})
        self.assertFalse(out["holdout_read"])
        self.assertTrue(seen)
        self.assertLess(max(_ts(b["open_utc"]) for b in seen), t_hold)
        self.assertNotIn(CT.root("XAUUSD") / "profile.json", wr.paths)
        self.assertEqual(CT.profile("XAUUSD")["source"], "CALIBRATED_ON_DEV")

    def test_flow_dev_never_reaches_holdout(self):
        """chunk_17#1: the DEV part handed to flow calibration / Markov fits ends before the FLOW_CONTEXT_MOVE_M1_V1 holdout."""
        import mq_instruments
        from masterquo.lab.flow_context import cli as C
        from masterquo.lab.flow_context import task as FT
        m1 = gapped([(2000, 0), (1000, 60 * 24 * 10)], 1)
        fe = FT.features(m1, 0.01, 0.01)
        rows = np.where((np.arange(len(m1)) >= FT.WARM) & np.isfinite(fe["atr"]) & np.isfinite(fe["F"]).all(axis=1))[0]
        t_hold = holdout_start(fe["t"], rows)
        dev = FT.dev_bars(m1)
        self.assertGreater(len(dev), 1500)
        self.assertLess(_ts(dev[-1]["open_utc"]), t_hold)
        ds = write_export(mq_instruments.data_dir() / "exp", m1)
        got = {}

        def cap(name):
            def f(inst, dev_, *a, **kw):
                got[name] = dev_
                return {}
            return f
        with mock.patch.object(C, "calibrate", side_effect=cap("calibrate")), mock.patch.object(C, "train_markov", side_effect=cap("markov")), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(C.main(["calibrate", "--asset", "XAUUSD", "--dataset", str(ds), "--allow-synthetic-fixture"]), 0)
            self.assertEqual(C.main(["train-markov", "--asset", "XAUUSD", "--dataset", str(ds), "--allow-synthetic-fixture"]), 0)
        for name in ("calibrate", "markov"):
            self.assertLess(max(_ts(b["open_utc"]) for b in got[name]), t_hold, name)

    def test_flow_stopdistance_factor_for_profile_cfg_and_atomic_profile(self):
        """chunk_17#15 (+#16): the StopDistance factor is calibrated with the profile's own period/method; profile.json atomic."""
        from masterquo.lab.flow_context import cli as C
        from masterquo.lab.flow_context import stop_distance as SD
        from masterquo.lab.flow_context import task as FT
        (FT.root("XAUUSD") / "profile.json").write_text(json.dumps({"stopdistance": {"period": 14, "method": "EMA", "factor": 1.5}}), encoding="utf-8")
        cfgs = []

        def cal(bars, point, cfg=None, *a, **kw):
            cfgs.append(cfg)
            return {"status": "OK", "factor": 1.7}
        wr = _Writes()
        with mock.patch.object(SD, "calibrate_factor", side_effect=cal), mock.patch.object(Path, "write_text", autospec=True, side_effect=wr):
            C.calibrate("XAUUSD", gapped([(600, 0)], 1), 0.01, 0.01, ["stopdistance"], {"data_kind": "SYNTHETIC_TEST"})
        self.assertEqual(len(cfgs), 2)
        for c in cfgs:
            self.assertEqual((c or {}).get("period"), 14)
            self.assertEqual((c or {}).get("method"), "EMA")
        self.assertEqual(FT.profile("XAUUSD")["stopdistance"], {"period": 14, "method": "EMA", "factor": 1.7})
        self.assertNotIn(FT.root("XAUUSD") / "profile.json", wr.paths)


# ============================================================================ flow runtime: S/R as-of, StopDistance
class FlowRuntimeTests(unittest.TestCase):
    def _history(self):
        from masterquo.lab.flow_context import sr_channels as SR
        t0 = datetime(2025, 1, 6, tzinfo=UTC)
        rng = np.random.default_rng(2)
        bars, c = [], 2600.0
        for i in range(60):
            o = c
            c = o + rng.normal(0, 2)
            bars.append({"open_utc": (t0 + timedelta(minutes=15 * i)).strftime("%Y-%m-%dT%H:%M:%SZ"), "o": o, "h": max(o, c) + 1, "l": min(o, c) - 1,
                         "c": c})
        h = SR.ChannelHistory(None, "XAUUSD|M15")
        for i in range(25, 60):
            h.update(bars[:i + 1])
        return h

    def test_channels_as_of_numeric(self):
        """chunk_17#3: as-of with an offset / as epoch selects the snapshot known at that instant, never a later one."""
        from masterquo.lab.flow_context.service import FlowSections
        h = self._history()
        self.assertEqual(h.as_of("2025-01-06T10:00:00+01:00")["as_of"], "2025-01-06T09:00:00Z")
        self.assertEqual(h.as_of("1736154000")["as_of"], "2025-01-06T09:00:00Z")
        self.assertEqual(h.as_of(1736154000)["as_of"], "2025-01-06T09:00:00Z")
        self.assertEqual(h.as_of("2025-01-06T09:00:00Z")["as_of"], "2025-01-06T09:00:00Z")
        self.assertIsNone(h.as_of("2025-01-06T05:00:00Z"))
        fs, k = FlowSections(), types.SimpleNamespace(srh=h)
        hist = fs.channels(k, "2025-01-06T10:00:00+01:00", "HISTORY_AS_KNOWN")
        self.assertEqual(hist["snapshots"][-1]["as_of"], "2025-01-06T09:00:00Z")
        self.assertEqual(fs.channels(k, "2025-01-06T10:00:00+01:00")["snapshot"]["as_of"], "2025-01-06T09:00:00Z")
        self.assertEqual(fs.channels(k, "garbage")["status"], "AS_OF_INVALID")
        self.assertEqual(fs.channels(k, "nan", "HISTORY_AS_KNOWN")["status"], "AS_OF_INVALID")

    def test_stopdistance_non_finite_entry(self):
        """chunk_17#8: entry nan/inf/<=0 -> SL_INPUT_INVALID (ValueError) and a JSON-safe INVALID_ENTRY response, never a 500."""
        from masterquo.lab.flow_context import stop_distance as SD
        from masterquo.lab.flow_context.service import FlowSections
        for e in (float("nan"), float("inf"), float("-inf"), 0.0, -5.0, 1.0):
            with self.assertRaises(ValueError, msg=e):
                SD.sl_price(e, "BUY", 1.5, 0.01)
        with self.assertRaises(ValueError):
            SD.sl_price(2000.0, "SELL", float("inf"), 0.01)
        self.assertEqual(SD.sl_price(2000.0, "BUY", 1.505, 0.01), 1998.49)                 # unchanged legal path (rounded outward)
        row = {"range_points": 90.0, "average_points": 100.0, "suggested_points": 150.0, "suggested_price_distance": 1.5}
        fs, k = FlowSections(), types.SimpleNamespace(sdr=[row], tick=0.01)
        for e in (float("nan"), float("inf"), -1.0):
            out = fs.stopdistance(k, e, "BUY")
            self.assertEqual(out["sl_status"], "INVALID_ENTRY")
            self.assertIsNone(out["sl_price_proposal"])
            json.dumps(out, allow_nan=False)
        out = fs.stopdistance(k, 2000.0, "BUY", float("inf"))
        self.assertEqual(out["diagnostics"]["status"], "INVALID_INPUT")
        json.dumps(out, allow_nan=False)
        self.assertEqual(fs.stopdistance(k, 2000.0, "BUY", 50.0)["sl_price_proposal"], 1998.5)


# ============================================================================ flow SHADOW rollback
class FlowRollbackTests(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_double_rollback(self):
        """chunk_17#10: a second rollback restores the selection before the previous one instead of a TypeError."""
        from masterquo.lab.flow_context import task as FT
        A = {"candidate_id": "R1-LOGREG", "dir": "/x/a", "model_hash": "ha"}
        Bm = {"candidate_id": "R2-LOGREG", "dir": "/x/b", "model_hash": "hb"}
        FT._save_reg("XAUUSD", {"runs": {}, "shadow": {FT.TASK: Bm}, "holdout_access": {},
                                "history": [{"from": None, "to": "R1-LOGREG", "at": "t1"}, {"from": A, "to": "R2-LOGREG", "at": "t2"}]})
        self.assertEqual(FT.rollback("XAUUSD")["shadow"], A)
        self.assertIsNone(FT.rollback("XAUUSD")["shadow"])
        self.assertNotIn(FT.TASK, FT._reg("XAUUSD")["shadow"])
        with self.assertRaises(ValueError):
            FT.rollback("XAUUSD")                                                       # nothing left to undo
        reg = FT._reg("XAUUSD")
        C = {"candidate_id": "R3-LOGREG", "dir": "/x/c", "model_hash": "hc"}
        reg["shadow"][FT.TASK] = C
        reg["history"] += [{"from": None, "to": "R1-LOGREG", "to_record": A, "at": "t3"}, {"from": A, "to": "R3-LOGREG", "to_record": C, "at": "t4"}]
        FT._save_reg("XAUUSD", reg)
        self.assertEqual(FT.rollback("XAUUSD")["shadow"], A)
        self.assertTrue(all(isinstance(v, dict) for v in FT._reg("XAUUSD")["shadow"].values()))


# ============================================================================ flow native export
class FlowNativeTests(unittest.TestCase):
    def setUp(self):
        self.files = tempfile.mkdtemp()

    @staticmethod
    def _rows(n):
        r = np.random.default_rng(1)
        out = []
        for i in range(n):
            v = 2650.0 + float(r.normal(0, 5))
            out.append({"bar_time": 1_700_000_000 + 900 * i, **{k: v + j * 0.0123456789 for j, k in enumerate(
                ("o", "h", "l", "c", "ha_o", "ha_h", "ha_l", "ha_c", "sd_range", "sd_avg", "sd_sugg", "sup_lo", "sup_hi", "res_lo", "res_hi",
                 "in_lo", "in_hi"))}})
        return out

    def test_full_history_export_is_not_too_large(self):
        """chunk_17#9: a full-history collector export above 8 MB (InpBars=0) is accepted."""
        from masterquo.lab.flow_context import native as NV
        p = Path(self.files) / "x.txt"
        NV.write_export(p, {"seq": 1, "symbol": "XAUUSD-", "tf": "M15"}, self._rows(32000))
        raw = p.read_bytes()
        self.assertGreater(len(raw), 8 * 1024 * 1024)
        self.assertEqual(len(NV.parse_export(raw)["rows"]), 32000)
        self.assertGreaterEqual(NV.MAX_BYTES, 32 * 1024 * 1024)

    def test_bad_header_types_rejected(self):
        """chunk_17#13: header seq/written_at_utc of a wrong type or a non-object header -> REJECTED; parity() reports bad rows."""
        from masterquo.lab.flow_context import native as NV
        p = Path(self.files) / "PMW" / NV.FlowImporter.NAME
        p.parent.mkdir(parents=True, exist_ok=True)
        for h in ({"seq": None}, {"seq": "abc"}, {"seq": 1, "written_at_utc": None}, {"seq": 1, "written_at_utc": "x"},
                  {"seq": 1, "written_at_utc": float("nan")}):
            NV.write_export(p, dict({"symbol": "XAUUSD-", "tf": "M15", "written_at_utc": time.time()}, **h), self._rows(3))
            r = NV.FlowImporter(self.files, "XAUUSD-").poll()
            self.assertEqual((r["status"], r.get("reason")), ("REJECTED", "HEADER_FORMAT"), h)
        body = json.dumps([NV.SCHEMA]) + "\n"
        p.write_bytes((body + "#sha256=" + hashlib.sha256(body.encode()).hexdigest() + "\n").encode())
        self.assertEqual(NV.FlowImporter(self.files, "XAUUSD-").poll()["status"], "REJECTED")
        NV.write_export(p, {"seq": 3, "symbol": "XAUUSD-", "tf": "M15", "written_at_utc": time.time()}, self._rows(3))
        self.assertEqual(NV.FlowImporter(self.files, "XAUUSD-").poll()["status"], "IMPORTED")
        fx = Path(self.files) / "fx"
        fx.mkdir()
        body = json.dumps({"schema": NV.SCHEMA, "point": 0.01}) + "\n" + ",".join(["1700000000"] + ["abc"] * 17) + "\n"
        (fx / "native_export.txt").write_bytes((body + "#sha256=" + hashlib.sha256(body.encode()).hexdigest() + "\n").encode())
        self.assertEqual(NV.parity(fx)["OWN_IMPLEMENTATIONS"]["status"], "REJECTED")


# ============================================================================ Trade Pad (M42)
TP_META = {"trade_contract_size": 100, "volume_min": 0.01, "volume_step": 0.01}


class TradePadTests(unittest.TestCase):

    def test_non_finite_inputs_rejected(self):
        """chunk_13#4: NaN/inf in entry/sl/tp/lots/commission -> ValueError (400), never a NaN/inf JSON body (500)."""
        from masterquo.lab.edge import trade_pad_plan
        base = {"side": "BUY", "entry": 2400.0, "sl": 2395.0, "tp": 2410.0, "lots": 0.1}
        for k in ("entry", "sl", "tp", "lots"):
            for v in (float("nan"), float("inf")):
                with self.assertRaises(ValueError, msg=(k, v)):
                    trade_pad_plan(**dict(base, **{k: v}), meta=TP_META, quote=None, commission_per_lot_side=0.5)
        with self.assertRaises(ValueError):
            trade_pad_plan(**base, meta=TP_META, quote=None, commission_per_lot_side=float("nan"))
        json.dumps(trade_pad_plan(**base, meta=TP_META, quote=None, commission_per_lot_side=0.5), allow_nan=False)

    def test_currency_is_not_mixed(self):
        """chunk_13#5: P&L in the profit currency is not netted with an account-currency commission at an unknown rate."""
        from masterquo.lab.edge import trade_pad_plan
        meta = dict(TP_META, currency_profit="USD")
        kw = {"side": "BUY", "entry": 2400.0, "sl": 2395.0, "tp": 2410.0, "lots": 1.0, "quote": None, "commission_per_lot_side": 20.0}
        r = trade_pad_plan(**kw, meta=meta, account_currency="PLN")
        self.assertEqual(r["currency_status"], "CONVERSION_UNKNOWN")
        self.assertIsNone(r["pnl_at_tp"])
        self.assertIsNone(r["pnl_at_sl"])
        self.assertEqual((r["gross_at_tp_profit_ccy"], r["profit_currency"]), (1000.0, "USD"))
        r = trade_pad_plan(**kw, meta=meta, account_currency="PLN", account_ccy_per_profit_ccy=4.0)
        self.assertEqual((r["pnl_at_tp"], r["pnl_at_sl"], r["currency_status"]), (3960.0, -2040.0, "CONVERTED"))
        r = trade_pad_plan(**kw, meta=meta, account_currency="usd")
        self.assertEqual((r["pnl_at_tp"], r["pnl_currency"], r["currency_status"]), (960.0, "usd", "SAME_CURRENCY"))
        r = trade_pad_plan(**kw, meta=TP_META)                                          # legacy call: currencies not provided
        self.assertEqual((r["pnl_at_tp"], r["currency_status"]), (960.0, "NOT_VERIFIED"))


if __name__ == "__main__":
    unittest.main()
