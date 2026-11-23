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


class BridgeReconnectDuringConnect(unittest.TestCase):
    """chunk_24#0: the API wrote bridge.state = RECONNECTING without synchronisation; a request landing inside connect() was overwritten by
    its final CONNECTED, and _load_all_history read cfg.symbol per TF (buffers of two symbols, buffer_symbol of the new one)."""

    def _bridge(self):
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        from masterquo.events import AppLog, EventBus
        from masterquo.mt5.bridge import MarketBridge
        self.td = __import__("_env").TempData()
        self.addCleanup(self.td.close)
        db, bus = Database(), EventBus()
        self.cs = ConfigStore()
        return MarketBridge(self.cs, None, db, bus, AppLog(db, bus))

    def test_request_inside_connect_is_not_lost(self):
        from unittest import mock
        b = self._bridge()

        def ask_reconnect(*a, **k):                                  # what the API does while connect() is loading history
            if hasattr(b, "request_reconnect"):
                b.request_reconnect("ACTIVE_ASSET_CHANGED")
            else:
                b.state = "RECONNECTING"
        term = {"name": "t", "company": "c", "path": "p", "build": 1, "connected": True, "trade_allowed": True}
        acct = {"login": 1, "server": "S", "currency": "USD", "balance": 1.0, "equity": 1.0, "margin": 0.0, "margin_free": 1.0, "leverage": 100,
                "trade_mode": 0, "name": "n", "company": "c"}
        calls = iter([False, term, acct])
        with mock.patch.object(b, "_initialize"), mock.patch.object(b, "_call", side_effect=lambda fn: next(calls)), \
                mock.patch("masterquo.mt5.bridge._row", side_effect=lambda r: r), mock.patch.object(b, "_record_account"), \
                mock.patch.object(b, "_load_stored_offset"), mock.patch.object(b, "_check_symbol"), \
                mock.patch.object(b, "_load_all_history", side_effect=ask_reconnect), mock.patch.object(b, "_load_dxy"), \
                mock.patch.object(b, "_notify"), mock.patch.object(b, "connection_status", return_value={}):
            b.connect()
        self.assertNotEqual(b.state, "CONNECTED")                    # 1.45.0: CONNECTED - the request was lost

    def test_history_of_one_symbol(self):
        from unittest import mock
        b = self._bridge()
        asked = []
        first = b.cfg.symbol

        import types
        real = self.cs.get()
        state = {"sym": first}

        def fetch(sym, tf, n):
            asked.append(sym)
            state["sym"] = "OTHER-"                                    # the user switches the asset meanwhile
            return []
        fake = types.SimpleNamespace(get=lambda: types.SimpleNamespace(**{**vars(real), "mt5": types.SimpleNamespace(**{**vars(real.mt5), "symbol": state["sym"]})}))
        with mock.patch.object(b, "_fetch", side_effect=fetch), mock.patch.object(b, "cfg_store", fake):
            if "symbol" in b._load_all_history.__code__.co_varnames:
                b._load_all_history(first)                             # what connect() passes (the symbol read at its start)
            else:
                b._load_all_history()
        self.assertTrue(asked)
        self.assertEqual(set(asked), {first})
        self.assertEqual(b.buffer_symbol, first)


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
