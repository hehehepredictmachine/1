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
