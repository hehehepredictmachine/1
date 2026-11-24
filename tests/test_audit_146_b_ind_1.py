"""1.46 audit, group B_ind_1 - regression tests for extind/ (IQ Gold Gann / IQ Star Lines / PAL02M / SAR context) and indicators/
(PMW-IND-1 service, AVWAP, spread, OFI book adapter, smoothing engine). Synthetic data only, no MT5, no HTTP server."""
from __future__ import annotations

import json
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import _env  # noqa: F401
from _env import TempData

UTC = timezone.utc  # noqa: UP017
T0 = datetime(2026, 3, 2, 0, 0, tzinfo=UTC).timestamp()      # Monday 00:00 UTC


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, UTC).isoformat().replace("+00:00", "Z")


def _env_body(adapter="IQ_GOLD_GANN", seq=1, gen=1, objects=None, symbol="XAUUSD-", basis="UTC", ver="1.0", **kw):
    d = {"schema_version": "pmw-extind-1", "producer_version": "test", "adapter_id": adapter, "product": {"version": ver},
         "terminal_fingerprint": "Srv:001", "chart_id": "77", "symbol": symbol, "tf": "PERIOD_M5", "time_basis": basis,
         "captured_at_server": 1_800_000_000, "generation": gen, "sequence": seq, "complete": True,
         "objects": objects if objects is not None else [{"name": "IQG_major_1", "type": "HLINE", "prices": [2650.0], "times": []}]}
    d.update(kw)
    return d


def _gann_mapping(mp, ver="1.0"):
    return mp.save_mapping("IQ_GOLD_GANN", {"product_version": ver, "approved": True, "verified_examples": [{"name": "IQG_major_1", "chart": 2650.0}],
                                            "rules": [{"prefix": "IQG_major", "type": "HLINE", "kind": "LEVEL", "role": "MAJOR"}]})


class _ExtBase(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        from masterquo.extind import contract, mapping, service
        self.c, self.mp, self.s = contract, mapping, service
        self.db = Database()
        self.svc = service.ExtIndService(ConfigStore(), self.db)

    def tearDown(self):
        self.td.close()


# ---------------------------------------------------------------------------------------------------------------- extind/cli.py
class TestLatestReal(unittest.TestCase):
    """chunk_11#8: the newest REAL export is chosen by its data (cutoff), not by the directory name (TR-... > EXP-... as text)."""

    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def _ds(self, name, cutoff, kind="REAL_USER_DATA", status=None):
        d = Path(self.td.dir) / "training" / "datasets" / "XAUUSD" / name
        d.mkdir(parents=True)
        (d / "source_metadata.json").write_text(json.dumps({"data_kind": kind, "cutoff_utc": cutoff, "exported_at_utc": cutoff}), encoding="utf-8")
        if status:
            (d / "status.json").write_text(json.dumps({"status": status}), encoding="utf-8")
        return d

    def test_newest_by_cutoff_not_by_prefix(self):
        from masterquo.extind import cli
        self._ds("TR-20260105T100000Z-ab12", "2026-01-05T10:00:00Z")
        new = self._ds("EXP-20261120T080000Z", "2026-11-20T08:00:00Z")
        self._ds("ZZ-SYNTH", "2026-12-01T00:00:00Z", kind="SYNTHETIC_TEST")
        self.assertEqual(cli._latest_real("XAUUSD"), new)

    def test_unusable_export_is_skipped(self):
        from masterquo.extind import cli
        from masterquo.forecast.export import STATUS_FILE
        old = self._ds("EXP-20260105T100000Z", "2026-01-05T10:00:00Z")
        bad = self._ds("EXP-20261120T080000Z", "2026-11-20T08:00:00Z")
        (bad / STATUS_FILE).write_text(json.dumps({"status": "FAILED"}), encoding="utf-8")
        self.assertEqual(cli._latest_real("XAUUSD"), old)


class TestCliRollback(unittest.TestCase):
    """chunk_11#19: 'rollback' without a registry is an error code, not a traceback."""

    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_rollback_without_registry(self):
        import contextlib
        import io

        from masterquo.extind import cli
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main(["rollback", "--asset", "XAUUSD"])
        self.assertEqual(rc, 2)
        self.assertIn("[BLAD]", buf.getvalue())

    def test_groups_option_limits_the_variants(self):
        """chunk_11#19: --groups was parsed and ignored (the full VARIANTS set was trained)."""
        from unittest import mock

        from masterquo.extind import trainer
        seen = []
        data = {"rows": [], "data_kind": "SYNTHETIC_TEST", "dataset_id": "x", "costs": {}, "profile_id": "p", "symbol": "X", "bars": {}}
        with mock.patch.object(trainer, "build_dataset", return_value=data), \
                mock.patch.object(trainer, "calibrate_sar", return_value={"status": "INSUFFICIENT_DATA", "trials": []}), \
                mock.patch.object(trainer, "run_variant", side_effect=lambda d, v, sp, sar: seen.append(v) or {"groups": list(v), "status": "INSUFFICIENT_DATA"}):
            rep = trainer.train("XAUUSD", Path(self.td.dir), groups=["SAR"], out_dir=Path(self.td.dir) / "run", log=lambda m: None)
            self.assertEqual(seen, [("BASE",), ("BASE", "SAR")])
            self.assertEqual(rep["plan"]["variants"], [["BASE"], ["BASE", "SAR"]])
            with self.assertRaises(ValueError):
                trainer.train("XAUUSD", Path(self.td.dir), groups=["NOPE"], out_dir=Path(self.td.dir) / "run2", log=lambda m: None)


# ---------------------------------------------------------------------------------------------------------------- extind/mapping.py
class TestMappingValidation(_ExtBase):
    def test_kind_must_fit_object_type(self):
        """chunk_11#6: kind/type mismatches and malformed rules are a ValueError (HTTP 400), never a crash later in decode / a 500."""
        bad = [
            {"rules": [{"prefix": "S", "type": "VLINE", "kind": "TIME_WINDOW"}]},
            {"rules": [{"prefix": "S", "type": "HLINE", "kind": "TRENDLINE"}]},
            {"rules": [{"prefix": "S", "type": "HLINE", "kind": "TIME_EVENT"}]},
            {"rules": ["abc"]},
            {"rules": [{"prefix": "S", "type": "HLINE", "kind": "LEVEL"}], "version": [1]},
            {"rules": [{"prefix": "S", "type": "HLINE", "kind": "LEVEL"}], "approved": True, "product_version": "1.0", "verified_examples": [1]},
        ]
        for m in bad:
            with self.assertRaises(ValueError, msg=str(m)):
                self.mp.save_mapping("IQ_STAR_LINES", m)
        ok = self.mp.save_mapping("IQ_STAR_LINES", {"rules": [{"prefix": "S", "type": "TREND", "kind": "TRENDLINE"},
                                                             {"prefix": "W", "type": "RECTANGLE", "kind": "TIME_WINDOW"},
                                                             {"prefix": "V", "type": "VLINE", "kind": "TIME_EVENT"}]})
        self.assertEqual(len(ok["rules"]), 3)

    def test_decode_skips_insufficient_geometry_of_an_old_mapping_file(self):
        """chunk_11#6: a mapping file written by an older version (no kind/type check) must not break every later ingest."""
        p = self.mp.ext_root() / "mappings" / "IQ_STAR_LINES.json"
        p.write_text(json.dumps({"adapter_id": "IQ_STAR_LINES", "approved": True, "product_version": "1.0", "verified_examples": [{"x": 1}],
                                 "rules": ["abc", {"prefix": "S", "type": "HLINE", "kind": "TRENDLINE"},
                                           {"prefix": "S", "type": "HLINE", "kind": "TIME_EVENT"},
                                           {"prefix": "V", "type": "VLINE", "kind": "TIME_WINDOW"},
                                           {"prefix": "L", "type": "HLINE", "kind": "LEVEL"}]}), encoding="utf-8")
        objs = [{"name": "S1", "type": "HLINE", "prices": [1.0], "times": []}, {"name": "V1", "type": "VLINE", "prices": [], "times": [1_800_000_000]},
                {"name": "L1", "type": "HLINE", "prices": [2.0], "times": []}]
        self.assertEqual(self.svc.ingest_bytes(self.c.wrap(_env_body("IQ_STAR_LINES", objects=objs))), 1)
        r = self.db.one("SELECT levels, windows, events FROM extind_snapshots WHERE adapter='IQ_STAR_LINES'")
        self.assertEqual([x["price"] for x in json.loads(r["levels"])], [2.0])          # only the geometry that fits its kind
        self.assertEqual((json.loads(r["windows"]), json.loads(r["events"])), ([], []))

    def test_approval_is_bound_to_a_product_version(self):
        """chunk_11#15: an approval without product_version is never MAPPING_APPROVED (a new product version could not invalidate it)."""
        self.mp.save_mapping("IQ_STAR_LINES", {"approved": True, "verified_examples": [{"x": 1}],
                                               "rules": [{"prefix": "STAR_win", "type": "RECTANGLE", "kind": "TIME_WINDOW"}]})
        self.assertNotEqual(self.mp.mapping_status("IQ_STAR_LINES", {"product": {"version": "9.9"}})[0], "MAPPING_APPROVED")
        self.assertNotEqual(self.mp.mapping_status("IQ_STAR_LINES", None)[0], "MAPPING_APPROVED")
        self.mp.save_mapping("IQ_STAR_LINES", {"approved": True, "product_version": "1.0", "verified_examples": [{"x": 1}],
                                               "rules": [{"prefix": "STAR_win", "type": "RECTANGLE", "kind": "TIME_WINDOW"}]})
        self.assertEqual(self.mp.mapping_status("IQ_STAR_LINES", {"product": {"version": "1.0"}})[0], "MAPPING_APPROVED")
        self.assertEqual(self.mp.mapping_status("IQ_STAR_LINES", {"product": {"version": "2.0"}})[0], "MAPPING_VERSION_CHANGED")

    def test_user_manifest_must_be_an_object_and_allow_export(self):
        """chunk_11#14: a JSON list as manifest -> MANIFEST_UNREADABLE (no 500 from status()); license_allows_export=false blocks."""
        man = self.mp.ext_root() / "manifests" / "PAL02M.json"
        man.write_text("[1, 2]", encoding="utf-8")
        self.assertEqual(self.mp.manifest("PAL02M")["identity_status"], "MANIFEST_UNREADABLE")
        self.assertIn("PAL02M", self.svc.status()["adapters"])                               # no AttributeError
        full = {k: "x" for k in self.mp.MANIFEST_REQUIRED}
        full.update(platform="MT5", kinds=["LEVEL"], outputs=["objects"], license_allows_export=False)
        man.write_text(json.dumps(full), encoding="utf-8")
        m = self.mp.manifest("PAL02M")
        self.assertEqual(m["identity_status"], "LICENSE_FORBIDS_EXPORT")
        self.assertFalse(m.get("identity_confirmed"))
        man.write_text(json.dumps(dict(full, license_allows_export=True)), encoding="utf-8")
        self.assertEqual(self.mp.manifest("PAL02M")["identity_status"], "DECODER_NOT_IMPLEMENTED")   # identified, decoder still missing


# ---------------------------------------------------------------------------------------------------------------- extind/contract.py
class TestEnvelopeErrors(_ExtBase):
    def test_malformed_values_are_envelope_errors(self):
        """chunk_11#16: every malformed envelope ends as EnvelopeError (per-file rejection), never TypeError / OverflowError / IntegrityError."""
        cases = [_env_body(objects=[{"name": "x", "type": "OTHER", "prices": 5, "times": []}]),
                 _env_body(objects=[{"name": "x", "type": "OTHER", "prices": [], "times": 5}]),
                 _env_body(objects=[{"name": "x", "type": "OTHER", "prices": [10 ** 400], "times": []}]),
                 _env_body(product="1.0"),
                 _env_body(symbol=None)]
        for b in cases:
            with self.assertRaises(self.c.EnvelopeError, msg=str(b)[:120]):
                self.c.validate(self.c.wrap(b))
            self.assertEqual(self.svc.ingest_bytes(self.c.wrap(b), "bad.json"), 0)
        self.assertEqual(self.c.validate(self.c.wrap(_env_body(product=None)))["product"], None)    # absent product stays valid

    def test_one_bad_file_does_not_stop_the_scan(self):
        inbox = self.mp.ext_root() / "inbox"
        (inbox / "a_bad.json").write_bytes(self.c.wrap(_env_body(seq=1)))
        (inbox / "b_good.json").write_bytes(self.c.wrap(_env_body(seq=2)))
        orig = self.svc.ingest_bytes

        def boom(raw, name="<bytes>", now=None):
            if name == "a_bad.json":
                raise RuntimeError("unexpected")
            return orig(raw, name, now)
        self.svc.ingest_bytes = boom
        self.assertEqual(self.svc.scan(), 1)
        self.assertTrue(any(e["file"] == "a_bad.json" for e in self.svc.errors))


# ---------------------------------------------------------------------------------------------------------------- extind/service.py
class TestAsOfPointInTime(_ExtBase):
    def test_snapshot_received_after_decision_in_the_same_second_is_not_used(self):
        """chunk_11#2: '...:00.400000Z' < '...:00Z' as text; a snapshot received 0.4 s AFTER the decision was used (look-ahead)."""
        _gann_mapping(self.mp)
        d = datetime(2026, 10, 20, 12, 5, 0, tzinfo=UTC)
        objs_old = [{"name": "IQG_major_1", "type": "HLINE", "prices": [2650.0], "times": []}]
        objs_new = [{"name": "IQG_major_1", "type": "HLINE", "prices": [9999.0], "times": []}]
        self.svc.ingest_bytes(self.c.wrap(_env_body(seq=1, objects=objs_old)), now=d - timedelta(seconds=1.6))
        self.svc.ingest_bytes(self.c.wrap(_env_body(seq=2, objects=objs_new)), now=d + timedelta(seconds=0.4))
        s = self.svc.as_of("IQ_GOLD_GANN", "XAUUSD", d)
        self.assertEqual([x["price"] for x in s["levels"]], [2650.0])
        self.assertGreaterEqual(s["age_s"], 0.0)
        s2 = self.svc.as_of("IQ_GOLD_GANN", "XAUUSD", d + timedelta(seconds=1))
        self.assertEqual([x["price"] for x in s2["levels"]], [9999.0])

    def test_latest_within_one_second_wins(self):
        """chunk_11#2: ORDER BY available_at DESC inside one second is reversed when one stamp has no fraction ('Z' > '.')."""
        _gann_mapping(self.mp)
        d = datetime(2026, 10, 20, 12, 5, 0, tzinfo=UTC)
        self.svc.ingest_bytes(self.c.wrap(_env_body(seq=1, objects=[{"name": "IQG_major_1", "type": "HLINE", "prices": [1.0], "times": []}])), now=d)
        self.svc.ingest_bytes(self.c.wrap(_env_body(seq=2, objects=[{"name": "IQG_major_1", "type": "HLINE", "prices": [2.0], "times": []}])),
                              now=d + timedelta(seconds=0.5))
        s = self.svc.as_of("IQ_GOLD_GANN", "XAUUSD", d + timedelta(seconds=3))
        self.assertEqual([x["price"] for x in s["levels"]], [2.0])
        self.assertIsNone(self.svc.as_of("IQ_GOLD_GANN", "XAUUSD", d - timedelta(seconds=1)))


class TestStatusPerInstrument(_ExtBase):
    def test_status_of_another_instrument_is_not_receiving(self):
        """chunk_11#4: status('BTC') must not report the XAUUSD chart's heartbeat / archive."""
        _gann_mapping(self.mp)
        now = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
        for k in range(3):
            self.svc.ingest_bytes(self.c.wrap(_env_body(seq=k + 1)), now=now + timedelta(seconds=2 * k))
        t = now + timedelta(seconds=5)
        btc = self.svc.status("BTC", t)["adapters"]["IQ_GOLD_GANN"]
        self.assertEqual((btc["source_status"], btc["runtime_status"], btc["archived_approved"]), ("SOURCE_MISSING", "NOT_READY", 0))
        xau = self.svc.status("XAUUSD", t)["adapters"]["IQ_GOLD_GANN"]
        self.assertEqual((xau["source_status"], xau["runtime_status"], xau["archived_approved"]), ("RECEIVING", "READY_RUNTIME", 3))
        self.assertEqual(self.svc.status(None, t)["adapters"]["IQ_GOLD_GANN"]["source_status"], "RECEIVING")   # CLI view: all charts

    def test_product_version_change_is_not_ready_runtime(self):
        """chunk_11#5: after the indicator updated to a new version every new read is MAPPING_VERSION_CHANGED -> not READY_RUNTIME."""
        _gann_mapping(self.mp, "1.0")
        now = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
        self.svc.ingest_bytes(self.c.wrap(_env_body(seq=1, ver="1.0")), now=now)
        self.assertEqual(self.svc.status("XAUUSD", now + timedelta(seconds=1))["adapters"]["IQ_GOLD_GANN"]["runtime_status"], "READY_RUNTIME")
        self.svc.ingest_bytes(self.c.wrap(_env_body(seq=2, ver="2.0")), now=now + timedelta(seconds=2))
        st = self.svc.status("XAUUSD", now + timedelta(seconds=3))["adapters"]["IQ_GOLD_GANN"]
        self.assertEqual(st["runtime_status"], "NOT_READY")
        self.assertEqual(st["live_mapping_status"], "MAPPING_VERSION_CHANGED")
        self.assertTrue(any("wersj" in n for n in st["needs"]))


# ---------------------------------------------------------------------------------------------------------------- extind/trainer.py
class TestTrainerRoot(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_asset_is_a_known_instrument(self):
        """chunk_11#7: '../forecast' rewrote the gold_candles registry; any asset created directories outside the data folder."""
        from masterquo.extind import trainer
        fc = Path(self.td.dir) / "forecast"
        fc.mkdir()
        (fc / "registry.json").write_text(json.dumps({"active": "RUN_NEW", "history": ["RUN_OLD"]}), encoding="utf-8")
        for bad in ("../forecast", "../../evil_dir_created_by_asset", "", "XAUUSD/../../x"):
            with self.assertRaises(ValueError, msg=bad):
                trainer.root(bad)
        with self.assertRaises(ValueError):
            trainer.rollback("../forecast")
        self.assertEqual(json.loads((fc / "registry.json").read_text())["active"], "RUN_NEW")
        self.assertFalse((Path(self.td.dir).parent / "evil_dir_created_by_asset").exists())
        self.assertTrue(trainer.root("XAUUSD").is_dir())
        self.assertTrue(trainer.root("BTC").is_dir())

    def test_registry_write_does_not_share_a_fixed_tmp_name(self):
        """chunk_11#17: registry.tmp was shared by every writer (a concurrent writer / leftover broke the replace)."""
        from masterquo.extind import trainer
        r = trainer.root("XAUUSD")
        (r / "registry.json").write_text(json.dumps({"active": {"run_id": "A", "variant": "BASE"}, "history": [None], "runs": {}}), encoding="utf-8")
        (r / "registry.tmp").mkdir()                                     # a foreign writer's file in the way
        self.assertIsNone(trainer.rollback("XAUUSD"))
        self.assertIsNone(json.loads((r / "registry.json").read_text())["active"])
        self.assertEqual(sorted(p.name for p in r.iterdir()), ["registry.json", "registry.tmp"])     # no tmp left behind


# ---------------------------------------------------------------------------------------------------------------- indicators
def _bars(n, tf_s=60, t0=T0, start=100.0):
    out = []
    for i in range(n):
        c = start + (i % 17) * 0.1
        o = c - 0.05
        out.append({"open_utc": _iso(t0 + i * tf_s), "o": o, "h": max(o, c) + 0.1, "l": min(o, c) - 0.1, "c": c, "tv": 10 + i % 5, "rv": 0,
                    "closed": True, "available_at": _iso(t0 + (i + 1) * tf_s)})
    return out


class TestAVWAPHistory(unittest.TestCase):
    def test_anchor_older_than_history_is_not_ready(self):
        """chunk_12#2: a buffer cut after the anchor gave another AVWAP (from the first buffered bar) with status READY."""
        from masterquo.indicators import avwap as AV
        b = _bars(800)
        as_of = T0 + 800 * 60
        a = AV.manual_anchor(_iso(T0), _iso(T0), "m")
        full = AV.compute(b, "M1", a, as_of=as_of, instrument="XAUUSD")
        self.assertEqual(full["status"], "READY")
        cut = AV.compute(b[-600:], "M1", a, as_of=as_of, instrument="XAUUSD")
        self.assertNotEqual(cut["status"], "READY")
        self.assertEqual(cut["reason"], "ANCHOR_OLDER_THAN_HISTORY")
        self.assertIsNone(AV.compute(b[-600:], "M1", a, as_of=as_of, instrument="XAUUSD")["values"].get("avwap"))
        inside = AV.manual_anchor(b[-300]["open_utc"], _iso(T0), "m2")
        self.assertEqual(AV.compute(b[-600:], "M1", inside, as_of=as_of, instrument="XAUUSD")["status"], "READY")


class TestContractTs(unittest.TestCase):
    def test_numbers_out_of_range_and_naive_strings(self):
        """chunk_12#4: 1e20 / NaN passed the route check and crashed later (OverflowError / ValueError -> 500); a naive string was
        silently read in the computer's local zone."""
        from masterquo.indicators import avwap as AV
        from masterquo.indicators import contract as C
        for bad in (1e20, float("nan"), float("inf"), -1e20):
            with self.assertRaises(ValueError):
                C.ts(bad)
        with self.assertRaises(ValueError):
            C.ts("2026-11-20T10:00:00", strict=True)
        self.assertEqual(C.ts("2026-11-20T10:00:00Z", strict=True), datetime(2026, 11, 20, 10, tzinfo=UTC).timestamp())
        for bad in (1e20, "2026-11-20T10:00:00"):
            with self.assertRaises(ValueError):
                AV.manual_anchor(bad, _iso(T0))
        self.assertEqual(C.ts(5), 5.0)


class TestSpreadCompute(unittest.TestCase):
    pid = "LAB_XAU_REFERENCE_V1"

    def _samples(self, days, spread_of):
        from masterquo.indicators import spread as SP
        out = []
        for d in range(days):
            t = T0 + d * 86400 + 9 * 3600 + 60
            for k in range(5):
                out.append({"t": t + k * 10, "spread": spread_of(d), **SP.session_slot(self.pid, t + k * 10, 30)})
        return out

    def test_unusual_threshold_from_config(self):
        """chunk_12#13: spread_unusual_pct was ignored (fixed 90)."""
        from masterquo.indicators import spread as SP
        smp = self._samples(8, lambda d: 0.10 + 0.01 * d)
        now = T0 + 7 * 86400 + 9 * 3600 + 200
        q = {"bid": 2000.0, "ask": 2000.135, "time_utc": _iso(now - 1), "received_at": _iso(now - 0.5)}
        r = SP.compute(q, smp, now=now, instrument="XAUUSD", broker_symbol="XAUUSD-", profile_id=self.pid, tick=0.01, unusual_pct=50.0)
        self.assertGreaterEqual(r["values"]["percentile"], 50.0)
        self.assertLess(r["values"]["percentile"], 90.0)
        self.assertTrue(r["values"]["unusual"])
        r90 = SP.compute(q, smp, now=now, instrument="XAUUSD", broker_symbol="XAUUSD-", profile_id=self.pid, tick=0.01)
        self.assertFalse(r90["values"]["unusual"])

    def test_unknown_quote_time_is_not_ready(self):
        """chunk_12#14: time_utc=None (server offset unknown) gave READY for a quote of unknown age."""
        from masterquo.indicators import spread as SP
        smp = self._samples(8, lambda d: 0.10 + 0.01 * d)
        now = T0 + 7 * 86400 + 9 * 3600 + 200
        q = {"bid": 2000.0, "ask": 2000.2, "time_utc": None, "received_at": _iso(now - 0.5)}
        r = SP.compute(q, smp, now=now, instrument="XAUUSD", broker_symbol="XAUUSD-", profile_id=self.pid, tick=0.01)
        self.assertEqual(r["status"], "STALE")
        self.assertEqual(r["reason"], "QUOTE_TIME_UNKNOWN")

    def test_intensity_window_and_sampling_label(self):
        """chunk_12#8: closed window [now-60, now] counted 61 updates per minute; the 1 s loop clock was presented as the quote sequence."""
        from masterquo.indicators import spread as SP
        it = SP.Intensity()
        for k in range(61):
            it.observe({"time_msc": 1_000_000 + k * 1000 + (k % 3) * 7}, 1000.0 + k * 1.0 + (0.3 if k % 2 else 0.0))
        v = it.view()
        self.assertLessEqual(v["updates_per_min"], 60.0)
        self.assertTrue(str(v.get("sampling", "")).startswith("SAMPLED"))
        msc = [1_000_000 + k * 1000 + (k % 3) * 7 for k in range(61)]
        kept = msc[-int(v["updates_per_min"]):]
        self.assertAlmostEqual(v["mean_interval_s"], (kept[-1] - kept[0]) / 1000.0 / (len(kept) - 1), places=9)   # quote clock, not loop clock


# ---------------------------------------------------------------------------------------------------------------- indicators/service.py
class _FakeBridge:
    def __init__(self):
        self.quote = None
        self.symbol_info = {"trade_tick_size": 0.01, "point": 0.01, "digits": 2}
        self.session_epoch = 1
        self.dxy_status = None
        self.m1: list[dict] = []
        self.book_calls: list[str] = []

    def bars(self, tf, limit=None, include_forming=True):
        return list(self.m1) if tf == "M1" else []

    def _call(self, fn):
        bridge = self

        class M:
            def market_book_add(self, sym):
                bridge.book_calls.append("add:" + sym)
                return True

            def market_book_release(self, sym):
                bridge.book_calls.append("release:" + sym)
                return True

            def market_book_get(self, sym):
                return []
        return fn(M())


class _SvcBase(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.config import ConfigStore
        from masterquo.indicators.service import IndicatorService
        self.cfg = ConfigStore()
        self.br = _FakeBridge()
        self.now = T0 + 9 * 3600
        self.svc = IndicatorService(self.cfg, self.br, data_dir=Path(self.td.dir) / "ind", clock=lambda: self.now)

    def tearDown(self):
        self.svc.db.close()
        self.td.close()


class TestServiceSampling(_SvcBase):
    def test_frozen_quote_is_not_sampled(self):
        """chunk_12#1: a quote frozen since Friday (weekend) was sampled into the spread reference as a normal session."""
        self.cfg.update({"indicators": {"book_enabled": False}})
        frozen = datetime.fromtimestamp(self.now - 3600, UTC)
        self.br.quote = {"symbol": "XAUUSD-", "bid": 2000.0, "ask": 2000.6, "time_msc": 1, "time_utc": _iso(self.now - 3600),
                         "received_at": _iso(self.now), "_last_new_received": frozen}
        self.svc.tick(self.now)
        self.assertEqual(self.svc.state["spread_samples"], 0)
        self.br.quote = dict(self.br.quote, time_msc=2, time_utc=_iso(self.now + 10), _last_new_received=datetime.fromtimestamp(self.now + 10, UTC))
        self.svc.tick(self.now + 11)
        self.assertEqual(self.svc.state["spread_samples"], 1)
        n = self.svc.db.execute("SELECT COUNT(*) FROM spread_samples").fetchone()[0]
        self.assertEqual(n, 1)

    def test_book_closed_when_disabled_and_old_book_dropped_on_symbol_change(self):
        """chunk_12#12: book_enabled=false kept market_book_add active; a symbol change kept the previous symbol's book."""
        from masterquo.indicators import ofi as OF
        ad = OF.BookAdapter(self.br)
        ad.ensure("A")
        ad.last = {"t": 1.0, "bids": [(1.0, 1.0)], "asks": [(1.1, 1.0)]}
        ad.ensure("B")
        self.assertIsNone(ad.last)
        self.svc.tick(self.now)                                         # book enabled -> subscribed
        self.assertEqual(self.svc.book.symbol, "XAUUSD-")
        self.cfg.update({"indicators": {"book_enabled": False}})
        self.svc.tick(self.now + 1)
        self.assertIsNone(self.svc.book.symbol)
        self.assertIn("release:XAUUSD-", self.br.book_calls)


class TestServiceSnapshotAge(_SvcBase):
    def _snap(self, as_of):
        ready = {"status": "READY", "reason": None, "values": {"downside_share_20": 0.5, "spread_price": 0.2}}
        return {"version": "V", "as_of": _iso(as_of), "snapshot_id": "INDS-x", "avwap": {"M1": {"SESSION": dict(ready), "EVENT": None}},
                "semivar": dict(ready), "spread": dict(ready), "dxy": {"status": "READY", "values": {}}, "profile": None, "microstructure": dict(ready)}

    def test_old_snapshot_is_stale_and_disabled_is_disabled(self):
        """chunk_12#3: a snapshot from Friday was served as READY all weekend (and after indicators.enabled=false)."""
        self.svc.snap = self._snap(self.now)
        self.assertEqual(self.svc.context(None, {})["indicators"]["semivar"]["status"], "READY")
        self.now += 48 * 3600
        ind = self.svc.context(None, {})["indicators"]
        self.assertEqual(ind["semivar"]["status"], "STALE")
        self.assertTrue(ind["semivar"]["reason"].startswith("SNAPSHOT_AGE_"))
        self.assertEqual(ind["avwap"]["M1_SESSION"]["status"], "STALE")
        self.assertEqual(ind["snapshot_status"], "STALE")
        self.assertEqual(self.svc.status()["summary"]["semivar"], "STALE")
        self.assertEqual(self.svc.compact(self.svc.snap)["spread"]["status"], "STALE")
        self.cfg.update({"indicators": {"enabled": False}})
        ind = self.svc.context(None, {})["indicators"]
        self.assertEqual(ind["semivar"]["status"], "DISABLED")
        self.assertEqual(ind["snapshot_status"], "DISABLED")
        self.assertEqual(self.svc.snap["semivar"]["status"], "READY")                     # the frozen snapshot itself is not rewritten

    def test_snapshot_id_covers_as_of_and_avwap(self):
        """chunk_12#15: snapshot_id ignored as_of and the AVWAP results."""
        self.cfg.update({"indicators": {"book_enabled": False}})
        self.br.m1 = _bars(300, t0=self.now - 300 * 60)
        a = self.svc.compute(self.now, persist_versions=False)
        b = self.svc.compute(self.now + 3600 * 24 * 30, persist_versions=False)
        self.assertNotEqual(a["snapshot_id"], b["snapshot_id"])
        self.svc.add_manual_anchor("M1", self.br.m1[-200]["open_utc"], "x")
        c = self.svc.compute(self.now, persist_versions=False)
        self.assertNotEqual(a["snapshot_id"], c["snapshot_id"])


class TestServiceDbLock(_SvcBase):
    def test_shared_connection_reads_hold_the_lock(self):
        """focus_X3#2: reads on the shared sqlite connection ran without the lock while the loop thread wrote."""
        held = []
        inner = threading.RLock()
        svc = self.svc

        class Spy:
            def __enter__(self):
                inner.acquire()
                held.append(True)
                return self

            def __exit__(self, *a):
                inner.release()
                return False

        orig = svc.db

        class DB:
            def execute(self, *a, **k):
                if not held or not inner._is_owned():
                    raise AssertionError("sqlite read outside the service lock: " + str(a[0])[:60])
                return orig.execute(*a, **k)

            def executemany(self, *a, **k):
                return orig.executemany(*a, **k)

        svc._lock = Spy()
        svc.db = DB()
        try:
            svc._spread_samples("XAUUSD", "XAUUSD-", "LONDON", 0)
            svc.manual_anchors("M1")
            svc.manifest()
        finally:
            svc.db = orig


# ---------------------------------------------------------------------------------------------------------------- indicators/smoothing.py
class TestSmoothingEngine(unittest.TestCase):
    def _bars(self, n):
        return [{"t": i * 60, "o": 1.0 + i, "h": 1.5 + i, "l": 0.5 + i, "c": 1.0 + i} for i in range(n)]

    def test_state_cache_is_bounded(self):
        """chunk_12#9: one state per arbitrary timeframe from the request body, never evicted."""
        from masterquo.indicators import smoothing as SM
        eng = SM.IndicatorEngine()
        bars = self._bars(30)
        ref = eng.calculate(SM.IndicatorSpec.make("EMA", 5, timeframe="X0"), bars)["values"]
        for k in range(300):
            r = eng.calculate(SM.IndicatorSpec.make("EMA", 5, timeframe=f"X{k}"), bars)
            self.assertEqual(r["values"], ref)
        self.assertLessEqual(len(eng._st), SM.IndicatorEngine.MAX_STATES)
        spec = SM.IndicatorSpec.make("SMA", 3, timeframe="H1")
        eng.calculate(spec, bars[:20])
        self.assertEqual(eng.calculate(spec, bars[:21])["calc_mode"], "INCREMENTAL")      # the recent key is still incremental

    def test_closed_false_bar_excluded_and_available_at_not_guessed(self):
        """chunk_12#10: the project marks a forming bar closed=False (not 'forming'); available_at fell back to the OPEN time."""
        from masterquo.indicators import smoothing as SM
        eng = SM.IndicatorEngine()
        spec = SM.IndicatorSpec.make("SMA", 2)
        bars = self._bars(4) + [{"t": 240, "o": 100, "h": 100, "l": 100, "c": 100, "closed": False}]
        r = eng.calculate(spec, bars)
        self.assertEqual(len(r["values"]), 4)
        self.assertEqual(r["values"][-1], (3.0 + 4.0) / 2)
        self.assertIsNone(r["available_at"])                                               # no explicit availability -> unknown
        bars2 = self._bars(4)
        bars2[-1]["available_at"] = 240
        self.assertEqual(eng.calculate(spec, bars2)["available_at"], 240)


if __name__ == "__main__":
    unittest.main()
