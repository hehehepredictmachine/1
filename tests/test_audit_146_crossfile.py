"""1.46: cross-file parts of fixes prepared by the file-group agents (the target file belonged to no group at that moment)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import _env  # noqa: F401


class TrainingReportLabels(unittest.TestCase):
    """chunk_37#16: values written by the runner (DO_OCENY_NA_DEV, RAPORT_WALIDACJI) had no Polish label in the report."""

    def test_labels(self):
        from masterquo.training import report
        self.assertIn("DO_OCENY_NA_DEV", report.PL)
        self.assertIn("RAPORT_WALIDACJI", report.PL)


class SignalCardModelsGate(unittest.TestCase):
    """chunk_09#2: the MODELS gate was skipped on the signal card (GATE_DESC), so a signal held only by model roles said 'brakuje: nic'."""

    def test_models_gate_has_a_description(self):
        from masterquo.engine import signal_view
        self.assertIn("MODELS", signal_view.GATE_DESC)


class QuantLedgerPendingPerInstrument(unittest.TestCase):
    """chunk_26#1: pending() returned the oldest rows of ALL instruments - rows of the other instrument filled the LIMIT."""

    def test_pending_filters_by_instrument(self):
        from masterquo.quant.ledger import QuantLedger as Ledger
        with tempfile.TemporaryDirectory() as td:
            led = Ledger(Path(td) / "l.sqlite")
            for i in range(3):
                for inst in ("BTC", "XAUUSD"):
                    led.c.execute("INSERT INTO rows(row_id, instrument, status, matures_at) VALUES(?,?,?,?)", (f"{inst}{i}", inst, "PENDING", float(i)))
            got = led.pending(10.0, limit=2, instrument="XAUUSD")
            self.assertEqual([r["instrument"] for r in got], ["XAUUSD", "XAUUSD"])
            self.assertEqual(len(led.pending(10.0, limit=10)), 6)         # without an instrument: unchanged
            led.c.close()


if __name__ == "__main__":
    unittest.main()


class TickExportUsesRawTruncation(unittest.TestCase):
    """chunk_24#12: tick_store guessed truncation from the FILTERED list (len >= max_count); a full raw terminal answer that ended before t1
    with one invalid quote dropped was saved as OK. The bridge reports `truncated` from the raw answer."""

    def test_raw_truncated_flag_is_used(self):
        import types
        from unittest import mock

        from masterquo.lab import tick_store as TS
        td = __import__("_env").TempData()
        self.addCleanup(td.close)
        ticks = [{"t_ms": 1_700_000_000_000 + i, "bid": 1.0, "ask": 1.1, "ord": i, "time_msc": 1_700_000_000_000 + i, "flags": 2} for i in range(9)]
        br = types.SimpleNamespace(ticks_range=lambda sym, a, b, n: {"status": "ok", "ticks": ticks, "truncated": True, "source": "MT5",
                                                                       "clock_transform": "x"})
        with mock.patch.object(TS.time, "time", return_value=1_700_000_000.0 + 3600):
            r = TS.export_via_bridge(br, "XAUUSD-", "XAUUSD", days=1 / 24, chunk_hours=1.0, max_count=10)
        self.assertEqual([c["status"] for c in r["chunks"]], ["TRUNCATED"])
        self.assertFalse(r["complete"])


class TrainhubClosesJobHandle(unittest.TestCase):
    """chunk_37#18 (trainhub part): the Windows Job Object handle of every TrainHub child stayed open for the bot's lifetime."""

    def test_close_job_called_after_child_ends(self):
        import types
        from unittest import mock

        from masterquo.trainhub import jobs as J
        td = __import__("_env").TempData()
        self.addCleanup(td.close)
        tc = J.TrainingCenter.__new__(J.TrainingCenter)          # only what _child uses
        log = Path(td.dir) / "job.log"
        tc.python, tc.poll_s, tc.proc = "python", 0.01, None
        tc._stop = __import__("threading").Event()
        tc.db = None
        proc = types.SimpleNamespace(pid=1, returncode=0, poll=lambda: 0)
        with mock.patch.object(J.TrainingCenter, "get", return_value={"log": str(log), "status": "DONE"}), \
                mock.patch.object(J, "update"), mock.patch.object(J, "db_path", return_value=Path(td.dir) / "x.sqlite"), \
                mock.patch.object(J.subprocess, "Popen", return_value=proc), \
                mock.patch("masterquo.training.core._job_limit"), \
                mock.patch("masterquo.training.core.close_job") as cj:
            tc._child("J1")
        cj.assert_called_once_with(proc)
