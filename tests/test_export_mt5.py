"""Export MT5 -> dataset -> training (1.25, prompt 4A) on the terminal SIMULATOR - every dataset here is SYNTHETIC_TEST.

Covered: folder with spaces and Polish letters, real_volume column, Bid/Ask ticks with equal time_msc kept across hourly chunks,
interrupted export (never read as complete) and resume after damaged checkpoints (identical files), date range and DST switch,
missing terminal / symbol / write permission, model readiness, and one real training pipeline reading exactly the exported files."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import _env
from _env import TempData


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.root = Path(tempfile.mkdtemp(prefix="mq exp ąę "))
        from masterquo.mt5.fake import BTCUSDT_SYN, SYN_MARKETS, FakeMT5
        self.fake = FakeMT5(markets=dict(SYN_MARKETS, **BTCUSDT_SYN))
        sys.modules["MetaTrader5"] = self.fake

    def tearDown(self):
        sys.modules.pop("MetaTrader5", None)
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)
        self.td.close()

    def export(self, out: Path, tfs=("M1", "M5", "M15"), **kw) -> int:
        from masterquo.forecast.export import export_candles
        return export_candles(kw.pop("months", 1), str(out), "AUTO", tfs, "training", "XAUUSD", "XAUUSD-", **kw)


class TestExport(Base):
    def test_complete_export_in_folder_with_spaces_real_volume_and_readiness(self):
        from masterquo.forecast.export import CSV_HEADER, dataset_state
        out = self.root / "zbiór danych 1"
        self.assertEqual(self.export(out), 0)
        st = json.loads((out / "EXPORT_STATUS.json").read_text(encoding="utf-8"))
        self.assertEqual(st["status"], "COMPLETE")
        self.assertTrue(dataset_state(out)["usable"])
        head = (out / "XAUUSD_M5.csv").read_text(encoding="utf-8").splitlines()
        self.assertEqual(head[0].split(","), CSV_HEADER)                         # real_volume appended at the end (old readers unaffected)
        meta = json.loads((out / "source_metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["data_kind"], "SYNTHETIC_TEST")
        for name, h in meta["files_sha256"].items():
            self.assertEqual(_sha(out / name), h)
        rd = json.loads((out / "MODEL_DATA_READINESS.json").read_text(encoding="utf-8"))
        by = {m["kind"]: m for m in rd["models"]}
        self.assertEqual(by["sh_models"]["status"], "GOTOWE")                    # M1 present
        self.assertEqual(by["forecast"]["status"], "BRAK_DANYCH")                # M30 not exported - reported, not faked
        self.assertIn("M30", by["forecast"]["reason"])
        self.assertEqual(by["ml"]["status"], "BRAK_DANYCH")
        dq = json.loads((out / "DATA_QUALITY_REPORT.json").read_text(encoding="utf-8"))
        self.assertIn("NIE jest wolumenem", dq["columns"]["tick_volume"])
        self.assertIn("NOT_EXPORTED", dq["ticks"])

    def test_ticks_keep_equal_times_and_order_across_hourly_chunks(self):
        import numpy as np
        out = self.root / "ticks"
        self.assertEqual(self.export(out, ("M1",), tick_days=0.25), 0)
        man = json.loads((out / "ticks" / "TICKS_MANIFEST.json").read_text(encoding="utf-8"))
        self.assertGreater(man["ticks"], 1000)
        self.assertGreater(man["same_time_msc_neighbours"], 0)                  # equal time_msc kept, not de-duplicated
        self.assertEqual(man["non_monotonic_steps"], 0)
        arrs = []
        for f in sorted((out / "ticks").glob("ticks_*.npz")):
            with np.load(f) as z:
                arrs.append((z["time_msc_utc"].copy(), z["bid"].copy(), z["ord"].copy()))
                self.assertTrue((np.diff(z["ord"]) == 1).all())
        t = np.concatenate([a[0] for a in arrs])
        self.assertEqual(len(t), man["ticks"])
        # the same range read in ONE request gives exactly the same ticks: hour borders neither lose nor double anything
        st = json.loads((out / "EXPORT_STATUS.json").read_text(encoding="utf-8"))
        a_ms = int(datetime.fromisoformat(man["requested_utc"][0].replace("Z", "+00:00")).timestamp() * 1000)
        b_ms = int(datetime.fromisoformat(man["requested_utc"][1].replace("Z", "+00:00")).timestamp() * 1000)
        off = int(st["frozen"]["offset_seconds"])
        self.fake.initialize()                                                  # the export closed its own connection
        r = self.fake.copy_ticks_range("XAUUSD-", datetime.fromtimestamp(a_ms / 1000 + off - 7200, timezone.utc),
                                       datetime.fromtimestamp(b_ms / 1000 + off + 7200, timezone.utc), -1)
        from masterquo.diagnostics import server_to_utc
        ref = [int(x["time_msc"]) - server_to_utc(int(x["time_msc"]) // 1000, st["frozen"]["dst_model"], off)[1] * 1000 for x in r]
        ref = [x for x in ref if a_ms <= x < b_ms]
        self.assertEqual(len(ref), len(t))
        self.assertEqual(sorted(ref), list(t))

    def test_interrupted_export_is_never_complete_and_resume_gives_identical_files(self):
        from masterquo.forecast import export as EX
        from masterquo.training import requirements as RQ
        ref = self.root / "ref"
        self.assertEqual(self.export(ref, tick_days=0.1), 0)
        out = self.root / "przerwany"
        orig = EX.export_ticks

        def crash(*a, **k):                                                     # power cut after the bars, before the ticks finished
            raise OSError("simulated crash")
        with mock.patch.object(EX, "export_ticks", crash):
            self.assertNotEqual(self.export(out, tick_days=0.1), 0)
        self.assertFalse((out / "source_metadata.json").exists())
        state = EX.dataset_state(out)
        self.assertFalse(state["usable"])
        self.assertIn(state["state"], ("FAILED", "INTERRUPTED"))
        self.assertTrue(all(m["status"] == "NIEKOMPLETNY_EKSPORT" for m in RQ.check_dataset(out)["models"]))
        # damaged checkpoint (write interrupted half way) - fetched again on resume
        ck = sorted((out / "chunks").glob("M5_*.json"))[0]
        ck.write_text(ck.read_text(encoding="utf-8")[:500], encoding="utf-8")
        self.assertIs(EX.export_ticks, orig)
        self.assertEqual(self.export(out, tick_days=0.1), 0)
        self.assertEqual(EX.read_status(out)["status"], "COMPLETE")
        for tf in ("M1", "M5", "M15"):                                           # same frozen range -> byte-identical CSV, nothing lost or doubled
            self.assertEqual(_sha(out / f"XAUUSD_{tf}.csv"), _sha(ref / f"XAUUSD_{tf}.csv"), tf)

    def test_date_range_and_dst_switch(self):
        out = self.root / "zakres"
        # US DST started 2026-03-08: broker NY+7 offset changes 2 -> 3 h; bars must stay continuous in UTC
        self.assertEqual(self.export(out, ("M5",), date_from="2026-03-02", date_to="2026-03-13T00:00Z"), 0)
        meta = json.loads((out / "source_metadata.json").read_text(encoding="utf-8"))
        dq = json.loads((out / "DATA_QUALITY_REPORT.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["requested_range_utc"], ["2026-03-02T00:00:00Z", "2026-03-13T00:00:00Z"])
        rows = (out / "XAUUSD_M5.csv").read_text(encoding="utf-8").splitlines()[1:]
        ts = [datetime.fromisoformat(r.split(",")[0].replace("Z", "+00:00")) for r in rows]
        self.assertEqual(len(ts), len(set(ts)))                                 # no doubled hour
        self.assertTrue(ts[0] >= datetime(2026, 3, 2, tzinfo=timezone.utc) and ts[-1] < datetime(2026, 3, 13, tzinfo=timezone.utc))
        self.assertEqual(dq["timeframes"]["M5"]["gaps"]["other"], 0, dq["timeframes"]["M5"]["gaps"])   # no unexplained hole at the switch
        self.assertEqual(dq["timeframes"]["M5"]["conflicting_revisions_count"], 0)

    def test_partial_history_is_reported_not_hidden(self):
        out = self.root / "krotka"
        orig = self.fake.copy_rates_range
        limit = datetime.now(timezone.utc) - timedelta(days=10)

        def short(sym, tf, a, b):                                               # terminal keeps only ~10 days ("Max bars in chart")
            r = orig(sym, tf, a, b)
            return r if r is None else r[r["time"] >= limit.timestamp()]
        self.fake.copy_rates_range = short
        self.assertEqual(self.export(out, ("M5",), months=2), 0)
        dq = json.loads((out / "DATA_QUALITY_REPORT.json").read_text(encoding="utf-8"))
        self.assertGreater(dq["timeframes"]["M5"]["history_shorter_than_requested_days"], 30)
        self.assertIn("Maks. barów", dq["requested_vs_received"]["note"])

    def test_missing_terminal_symbol_and_permission_say_what_to_do(self):
        import io
        from contextlib import redirect_stdout
        sys.modules["MetaTrader5"] = None                                       # package missing (not Windows / not installed)
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(self.export(self.root / "a"), 3)
        self.assertIn("BLOCKED_NO_MT5", buf.getvalue())
        sys.modules["MetaTrader5"] = self.fake
        from masterquo.forecast.export import export_candles
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(export_candles(1, str(self.root / "b"), "AUTO", ("M5",), "training", "XAUUSD", "XAUUSDX"), 4)
        self.assertIn("Market Watch", buf.getvalue())
        buf = io.StringIO()
        real_mkdir = Path.mkdir

        def deny(path, *a, **k):                                                # only the export folder is not writable
            if "bez prawa" in str(path):
                raise PermissionError(13, "denied", str(path))
            return real_mkdir(path, *a, **k)
        with redirect_stdout(buf), mock.patch.object(Path, "mkdir", autospec=True, side_effect=deny):
            self.assertEqual(self.export(self.root / "bez prawa"), 7)
        self.assertIn("Brak uprawnień", buf.getvalue())
        self.assertNotIn("Traceback", buf.getvalue())


class TestDstProbe(unittest.TestCase):
    """Broker time convention from the weekly market open (server time) in US winter vs summer - synthetic H1 rows."""

    def rates(self, fixed: bool):
        import numpy as np
        from masterquo.diagnostics import ny_close_offset
        dt = np.dtype([("time", "<i8")])
        out, t = [], datetime(2025, 9, 1, tzinfo=timezone.utc).timestamp()
        end = datetime(2026, 10, 20, tzinfo=timezone.utc).timestamp()
        from zoneinfo import ZoneInfo
        ny_tz = ZoneInfo("America/New_York")
        while t < end:
            off = 3 * 3600 if fixed else ny_close_offset(t)
            ny = datetime.fromtimestamp(t, timezone.utc).astimezone(ny_tz)    # market: Sunday 17:00 .. Friday 17:00 New York time
            closed = (ny.weekday() == 4 and ny.hour >= 17) or ny.weekday() == 5 or (ny.weekday() == 6 and ny.hour < 17)
            if not closed:
                out.append((int(t + off),))
            t += 3600
        return np.array(out, dtype=dt)

    def probe(self, fixed: bool) -> dict:
        from masterquo.forecast.export import dst_model_probe
        r = self.rates(fixed)
        fake = mock.Mock(TIMEFRAME_H1=16385)
        fake.copy_rates_range.return_value = r
        return dst_model_probe(fake, "XAUUSD-", datetime(2026, 10, 20, tzinfo=timezone.utc))

    def test_fixed_offset_broker_is_recognised(self):
        self.assertEqual(self.probe(True)["verdict"], "UNIFORM")

    def test_new_york_broker_is_recognised(self):
        self.assertEqual(self.probe(False)["verdict"], "NY_CLOSE")


class TestExportToTraining(Base):
    def test_exported_files_feed_a_real_training_pipeline(self):
        """export M1/M5/M15 -> quality -> SH replay + event model reading THIS export -> validation -> artefact (synthetic: never active)."""
        out = self.root / "eksport do treningu"
        self.assertEqual(self.export(out), 0)
        env = dict(os.environ, PYTHONPATH=str(_env.ROOT / "backend"), MASTERQUO_DATA_DIR=self.td.dir)
        r = subprocess.run([sys.executable, "-m", "masterquo", "training", "run", "--instruments", "XAUUSD", "--profile", "TEST_INSTALACJI",
                            "--tasks", "sh_models", "--dataset-xauusd", str(out), "--no-detect"], cwd=str(_env.ROOT / "backend"), env=env,
                           capture_output=True, text=True, timeout=900)
        from masterquo.training import core
        st = core.Run.load(core.Run.latest()).state
        t = {x["kind"]: x for x in st["tasks"]}
        self.assertEqual(st["plan"]["datasets"]["XAUUSD"], str(out.resolve()), r.stdout[-1500:])
        self.assertEqual(t["export"]["execution"], "UKONCZONE")
        self.assertEqual(Path(t["export"]["dataset_dir"]), out.resolve())
        self.assertEqual(t["quality"]["execution"], "UKONCZONE")
        self.assertTrue(any(x["kind"] == "forecast" and x["status"] == "BRAK_DANYCH" for x in t["quality"]["readiness"]))
        self.assertEqual(t["sh_models"]["execution"], "UKONCZONE", (t["sh_models"].get("detail"), r.stdout[-1500:], r.stderr[-1500:]))
        rep = json.loads(Path(t["sh_models"]["artifacts"][0]).read_text(encoding="utf-8"))
        self.assertEqual(rep["dataset"], str(out.resolve()))                       # read exactly the exported folder
        self.assertEqual(rep["data_kind"], "SYNTHETIC_TEST")
        self.assertEqual(t["sh_models"]["integration"], "ZAPISANY_DO_BADAN")       # synthetic: never promoted

    def test_refuses_incomplete_export_for_training(self):
        from masterquo.forecast import export as EX
        out = self.root / "niepelny"
        with mock.patch.object(EX, "_commission", side_effect=OSError("crash")):
            self.assertNotEqual(self.export(out), 0)
        env = dict(os.environ, PYTHONPATH=str(_env.ROOT / "backend"), MASTERQUO_DATA_DIR=self.td.dir)
        r = subprocess.run([sys.executable, "-m", "masterquo", "training", "run", "--instruments", "XAUUSD", "--profile", "TEST_INSTALACJI",
                            "--tasks", "sh_models", "--dataset-xauusd", str(out), "--no-detect"], cwd=str(_env.ROOT / "backend"), env=env,
                           capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 2)
        self.assertIn("nie nadaje się do treningu", r.stdout)


if __name__ == "__main__":
    unittest.main()
