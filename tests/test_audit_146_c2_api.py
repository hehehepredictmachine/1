"""1.46 audit, cross-file group C2_api: api/app.py, api/wf32_routes.py, exports/sources.py.

The library parts of these findings were fixed earlier (lab/edge.py, stats.py, forecast/long_horizon.py, desktop/proc_windows.go);
these tests check that the CALLERS now pass what those fixes need. Route functions are called directly (create_app / wf32 register on a
mock runtime) - no demo server, no socket, no real process. All market data is SYNTHETIC.

chunk_13#5   Trade Pad: the account currency is passed to trade_pad_plan (P&L in the profit currency was netted with the commission
             in the account currency at a silent rate 1.0)
chunk_00#5   account ROI (/api/v1/stats and the Telegram report): the deal-history coverage is passed to stats.account_roi (a deposit
             older than mt5.deals_history_days but newer than the first equity snapshot counted as profit)
chunk_11#10  long-horizon forecast (API + export): bar OPEN times -> CLOSE times and the wall clock for the data age (STALE was
             unreachable, as_of / target_utc one TF early)
chunk_49#10  Studio launch: CREATE_BREAKAWAY_FROM_JOB, so Studio outlives the engine's Job Object; retried without it where the job
             refuses breakaway
"""
import json
import math
import random
import threading
import time
import types
import unittest
from datetime import UTC, timedelta
from pathlib import Path
from unittest import mock

import _env  # noqa: F401
from _env import TempData

PORT = 18783


def make_rt(**kw):
    rt = mock.MagicMock()
    rt.license.locked = False
    rt.cfg.get.return_value.assets.active = "XAUUSD"
    for k, v in kw.items():
        setattr(rt, k, v)
    return rt


def endpoints(app) -> dict:
    return {(r.path, tuple(sorted(getattr(r, "methods", None) or ()))): r.endpoint for r in app.routes if hasattr(r, "endpoint")}


def ep(app, method: str, path: str):
    for (p, methods), fn in endpoints(app).items():
        if p == path and method in methods:
            return fn
    raise KeyError(path)


class _Base(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def create_app(self, rt):
        from masterquo.api import app as A
        return A.create_app(rt, PORT)


# ------------------------------------------------------------------------------------------------------------- chunk_13#5
class TradePadAccountCurrency(_Base):
    PLAN = (("side", "BUY"), ("entry", 2400), ("sl", 2395), ("tp", 2410), ("lots", 0.1))

    def _plan(self, account, meta_ccy="USD", comm=0.5):
        rt = make_rt()
        rt.cfg.get.return_value.scalp.commission_per_lot_side = comm
        rt.assets.check_asset.return_value = "XAUUSD-"
        rt.bridge.symbol_meta.return_value = {"trade_contract_size": 100.0, "currency_profit": meta_ccy}
        rt.bridge.symbol_info = {"volume_min": 0.01, "volume_step": 0.01}
        rt.bridge.quote_status.return_value = {"bid": 2400.0, "ask": 2400.2}
        if account is not mock.DEFAULT:
            rt.bridge.account_status.return_value = account
        r = ep(self.create_app(rt), "POST", "/api/v1/lab/tradepad")(body=dict(self.PLAN))
        json.dumps(r, allow_nan=False)                                        # the response stays JSON (no mock / NaN leaks into it)
        return r

    def test_pln_account_on_usd_profit_symbol_is_not_netted_at_rate_one(self):
        r = self._plan({"currency": "PLN"})
        self.assertEqual(r["currency_status"], "CONVERSION_UNKNOWN")         # HEAD: NOT_VERIFIED and 100 USD - 0.1 PLN = 99.9
        self.assertIsNone(r["pnl_at_tp"])
        self.assertIsNone(r["pnl_at_sl"])
        self.assertEqual((r["gross_at_tp_profit_ccy"], r["gross_at_sl_profit_ccy"], r["profit_currency"]), (100.0, -50.0, "USD"))
        self.assertIsNone(r["pnl_currency"])

    def test_same_currency_is_labelled(self):
        r = self._plan({"currency": "USD"})
        self.assertEqual((r["currency_status"], r["pnl_currency"]), ("SAME_CURRENCY", "USD"))
        self.assertEqual((r["pnl_at_tp"], r["pnl_at_sl"]), (99.9, -50.1))

    def test_account_unknown_keeps_legacy_numbers_not_verified(self):
        for acct in (None, {"currency": None}, {"currency": ""}, mock.DEFAULT):    # DEFAULT: a MagicMock account (no real currency)
            r = self._plan(acct)
            self.assertEqual((r["currency_status"], r["pnl_currency"], r["pnl_at_tp"]), ("NOT_VERIFIED", None, 99.9), acct)

    def test_unknown_commission_still_unavailable(self):
        r = self._plan({"currency": "USD"}, comm=None)
        self.assertEqual((r["pnl_at_tp"], r["cost_status"]), (None, "UNAVAILABLE"))


# ------------------------------------------------------------------------------------------------------------- chunk_00#5
class _SnapDB:
    def __init__(self, snaps=()):
        self.snaps = list(snaps)

    def query(self, sql, args=()):
        if "FROM equity_snapshots" in sql:
            return [r for r in self.snaps if r["account_key"] == args[0] and r["ts"] >= args[-1]]
        return []


class AccountRoiDealCoverage(_Base):
    """Equity 1000 (25 days ago) -> deposit 1000 (20 days ago) -> 2000 (5 days ago, 1 min ago). mt5.deals_history_days = 7, so the
    deposit is NOT in bridge.deals: the ROI window must be clipped to the deal history (ROI 0 %), not count the deposit as +100 %."""

    def _bridge(self, days=7, loaded=True):
        from masterquo.timeutil import utcnow
        now = utcnow()
        return types.SimpleNamespace(_lock=threading.RLock(), deals=[], deals_loaded_at=now if loaded else None, account_key="Broker:1",
                                     cfg=types.SimpleNamespace(deals_history_days=days, symbol="XAUUSD-"), clock=types.SimpleNamespace(offset=0.0),
                                     server_day_start_utc=lambda: None, account_status=lambda: {"currency": "USD"})

    def _db(self):
        from masterquo.timeutil import iso, utcnow
        now = utcnow()
        return _SnapDB([{"account_key": "Broker:1", "ts": iso(now - timedelta(days=25)), "equity": 1000.0},
                        {"account_key": "Broker:1", "ts": iso(now - timedelta(days=5)), "equity": 2000.0},
                        {"account_key": "Broker:1", "ts": iso(now - timedelta(minutes=1)), "equity": 2000.0}])

    def _stats_route(self, b):
        rt = make_rt(bridge=b, db=self._db())
        app = self.create_app(rt)
        with mock.patch.multiple("masterquo.stats", bot_stats=mock.DEFAULT, engine_stats=mock.DEFAULT, equity_curve=mock.DEFAULT,
                                 account_stats=mock.DEFAULT) as m:
            for v in m.values():
                v.return_value = {}
            return ep(app, "GET", "/api/v1/stats")(mode="PAPER")["account_roi"]

    def test_stats_route_clips_roi_to_deal_history(self):
        r = self._stats_route(self._bridge())
        self.assertEqual(r["status"], "OK")
        self.assertEqual(r["roi_pct"], 0.0)                                   # HEAD: 100.0 (the deposit counted as profit)
        self.assertEqual((r["deals_coverage"], r["period_clipped_to_deal_history"]), ("VERIFIED", True))

    def test_stats_route_long_history_not_clipped(self):
        r = self._stats_route(self._bridge(days=60))
        self.assertEqual((r["deals_coverage"], r["period_clipped_to_deal_history"]), ("VERIFIED", False))

    def test_stats_route_history_not_loaded_is_not_verified(self):
        r = self._stats_route(self._bridge(loaded=False))
        self.assertEqual(r["deals_coverage"], "NOT_VERIFIED")

    def test_telegram_report_roi_clips_too(self):
        from fastapi import FastAPI
        from masterquo.api import wf32_routes
        rt = types.SimpleNamespace(bridge=None, baskets=None, cfg=None, db=self._db(), telegram=None)
        app = FastAPI()
        wf32_routes.register(app, rt)
        rt.bridge = self._bridge()                                            # after register: no Telegram poll thread
        r = app.state.wf32["acct_roi"](30)
        self.assertEqual((r["status"], r["roi_pct"], r["net"], r["currency"]), ("OK", 0.0, 0.0, "USD"))   # HEAD: 100.0 / net 1000.0

    def test_coverage_helper_tolerates_old_or_fake_bridges(self):
        from masterquo.api.app import deals_coverage_from_utc
        b = self._bridge()
        self.assertAlmostEqual(deals_coverage_from_utc(b), b.deals_loaded_at.timestamp() - 7 * 86400)
        self.assertIsNone(deals_coverage_from_utc(types.SimpleNamespace()))
        self.assertIsNone(deals_coverage_from_utc(mock.MagicMock()))
        self.assertIsNone(deals_coverage_from_utc(self._bridge(loaded=False)))


# ------------------------------------------------------------------------------------------------------------- chunk_11#10
def _h1_bars(last_open: float, n: int = 3000, seed: int = 7) -> list[dict]:
    """Closed H1 bars (bridge format: open_utc ISO + close), the newest opening at `last_open`."""
    from datetime import datetime

    from masterquo.timeutil import iso
    rng, p, out = random.Random(seed), 2400.0, []
    for i in range(n):
        p *= math.exp(rng.gauss(0, 0.002))
        t = last_open - (n - 1 - i) * 3600
        out.append({"open_utc": iso(datetime.fromtimestamp(t, UTC)), "t_raw": int(t), "o": p, "h": p, "l": p, "c": p, "tv": 1})
    return out


def _bridge_with(bars):
    return types.SimpleNamespace(bars=lambda tf, n, include_forming=False: [dict(b) for b in bars[-n:]], tfs={"H1": object()},
                                 clock=types.SimpleNamespace(offset=0.0))


class LongHorizonObservationTimes(_Base):
    def _route(self, bars):
        from fastapi import FastAPI
        from masterquo.api import wf32_routes
        rt = types.SimpleNamespace(bridge=None, baskets=None, cfg=None)
        app = FastAPI()
        wf32_routes.register(app, rt)
        rt.bridge = _bridge_with(bars)
        return ep(app, "GET", "/api/v1/forecast/long-horizon")(horizon="24h", timeframe="H1")

    def _export(self, bars):
        from masterquo.exports import sources as S
        ctx = S.SourceContext(Path(self.td.dir), rt=types.SimpleNamespace(bridge=_bridge_with(bars)))
        return S.long_horizon(ctx, "H1", ["24h"]).datasets[0].rows[0]

    def test_api_old_data_is_stale(self):
        last_open = (time.time() // 3600) * 3600 - 73 * 3600                  # terminal disconnected / weekend: last bar 73 h ago
        r = self._route(_h1_bars(last_open))
        self.assertEqual(r["status"], "STALE")                                # HEAD: OK (age = as_of - ts[-1] = 0)
        self.assertEqual(r["as_of"], last_open + 3600)                        # the close of the last bar, not its open
        self.assertGreater(r["data_age_seconds"], 70 * 3600)

    def test_api_fresh_data_ok_and_as_of_is_close(self):
        last_open = (time.time() // 3600) * 3600 - 3600                       # newest CLOSED H1 bar
        r = self._route(_h1_bars(last_open))
        self.assertEqual(r["status"], "OK")
        self.assertEqual(r["as_of"], last_open + 3600)                        # HEAD: last_open (one TF early)

    def test_export_old_data_is_stale_and_target_from_close(self):
        from masterquo.exports.core import utc_iso
        last_open = (time.time() // 3600) * 3600 - 73 * 3600
        row = self._export(_h1_bars(last_open))
        self.assertEqual(row["status"], "STALE")                              # HEAD: OK
        self.assertEqual(row["as_of_utc"], utc_iso(last_open + 3600))
        self.assertEqual(row["target_utc"], utc_iso(last_open + 3600 + 86400))
        self.assertGreater(row["data_age_seconds"], 70 * 3600)

    def test_export_fresh_data_ok(self):
        last_open = (time.time() // 3600) * 3600 - 3600
        self.assertEqual(self._export(_h1_bars(last_open))["status"], "OK")


# ------------------------------------------------------------------------------------------------------------- chunk_49#10
class _OsNT:
    """app.py's `os` seen as Windows (only os.name; pathlib / the rest of the process stay POSIX)."""
    name = "nt"

    def __getattr__(self, k):
        import os
        return getattr(os, k)


BREAKAWAY = 0x01000000


class StudioLaunchBreakaway(_Base):
    def _launch(self, popen):
        from masterquo.api import app as A
        rt = make_rt()
        app = A.create_app(rt, PORT)
        fn = ep(app, "POST", "/api/v1/studio/launch")
        with mock.patch.object(A, "os", _OsNT()), mock.patch("subprocess.Popen", popen), \
                mock.patch("urllib.request.urlopen", side_effect=OSError("not running")):
            return fn()

    def test_windows_launch_breaks_away_from_the_engine_job(self):
        popen = mock.MagicMock(return_value=types.SimpleNamespace(pid=4242))
        r = self._launch(popen)
        self.assertTrue(r["started"])
        self.assertEqual(popen.call_count, 1)
        flags = popen.call_args.kwargs["creationflags"]
        self.assertTrue(flags & BREAKAWAY, hex(flags))                        # HEAD: no CREATE_BREAKAWAY_FROM_JOB
        self.assertTrue(flags & 0x00000008 and flags & 0x00000200, hex(flags))   # still DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        self.assertIs(r["job_breakaway"], True)

    def test_job_without_breakaway_ok_falls_back(self):
        def popen(*a, **k):
            if k["creationflags"] & BREAKAWAY:
                raise PermissionError(13, "Access is denied")                 # a job without JOB_OBJECT_LIMIT_BREAKAWAY_OK
            return types.SimpleNamespace(pid=77)
        m = mock.MagicMock(side_effect=popen)
        r = self._launch(m)
        self.assertEqual((r["started"], r["pid"], r["job_breakaway"]), (True, 77, False))   # HEAD: one call only, no fallback
        self.assertEqual(m.call_count, 2)
        self.assertFalse(m.call_args.kwargs["creationflags"] & BREAKAWAY)

    def test_other_start_failure_still_500(self):
        from fastapi import HTTPException
        m = mock.MagicMock(side_effect=FileNotFoundError(2, "missing"))
        with self.assertRaises(HTTPException) as cm:
            self._launch(m)
        self.assertEqual(cm.exception.status_code, 500)
        self.assertIn("STUDIO_START_FAILED", cm.exception.detail)

    def test_posix_launch_unchanged(self):
        from masterquo.api import app as A
        rt = make_rt()
        fn = ep(A.create_app(rt, PORT), "POST", "/api/v1/studio/launch")
        popen = mock.MagicMock(return_value=types.SimpleNamespace(pid=5))
        with mock.patch("subprocess.Popen", popen), mock.patch("urllib.request.urlopen", side_effect=OSError("not running")):
            r = fn()
        self.assertEqual(popen.call_count, 1)
        self.assertEqual(popen.call_args.kwargs["creationflags"], 0)
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertTrue(r["started"])


if __name__ == "__main__":
    unittest.main()
