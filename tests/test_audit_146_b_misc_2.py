"""1.46 audit, group B_misc_2 - regression tests (bootstrap, data quality, MT5 history export, SHADOW evaluation, strategy ROI, Kronos
service). Each test failed on the 1.45 / pre-fix code and passes after the fix."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import types
import unittest
from collections import OrderedDict
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path

import _env  # noqa: F401
from _env import TempData

HEAVY = ("tsfm_chronos2", "tsfm_granite_ttm", "tsfm_tirex2", "tsfm_tabicl", "kronos_model")


# ============================================================================================== bootstrap
class TestBootstrapNeverTwoHeavyInstalls(unittest.TestCase):
    """chunk_00#2: an install of ANOTHER component already running (panel / upgrade auto_install) was ignored - run_heavy started its
    own heavy installer in parallel."""

    def make(self, rt, installed: set, installers: dict, queued=("tsfm_chronos2",)):
        from masterquo.bootstrap import Bootstrap
        b = Bootstrap(rt, state_file=Path(tempfile.mkdtemp()) / "b.json", probes={c: (lambda c=c: (c in installed, "fake")) for c in HEAVY},
                      installers=installers, poll_s=0.01)
        b.state["components"] = {c: {"state": "NOT_INSTALLED"} for c in queued}
        return b

    def test_waits_for_another_running_install(self):
        jobs = {"install_tirex2": {"state": "RUNNING"}}
        rt = types.SimpleNamespace(tsfm=types.SimpleNamespace(jobs=jobs), kronos=None, demo=False)
        installed, started = set(), []

        def start():
            started.append(jobs["install_tirex2"]["state"])
            return {"ok": True}

        def poll():
            installed.add("tsfm_chronos2")
            return "DONE"
        b = self.make(rt, installed, {"tsfm_chronos2": (start, poll)})
        threading.Timer(0.2, lambda: jobs["install_tirex2"].update(state="DONE")).start()
        out = b.run_heavy(timeout_s=10)
        self.assertEqual(started, ["DONE"])                                  # started only after the other install finished
        self.assertEqual(out, [{"id": "tsfm_chronos2", "state": "INSTALLED"}])

    def test_other_install_outlasting_the_timeout_pauses_the_queue(self):
        rt = types.SimpleNamespace(tsfm=types.SimpleNamespace(jobs={"install_tirex2": {"state": "RUNNING"}}), kronos=None, demo=False)
        started = []
        inst = {c: ((lambda c=c: started.append(c) or {"ok": True}), (lambda: "DONE")) for c in ("tsfm_chronos2", "tsfm_granite_ttm")}
        b = self.make(rt, set(), inst, queued=("tsfm_chronos2", "tsfm_granite_ttm"))
        out = b.run_heavy(timeout_s=0.05)
        self.assertEqual(started, [])
        self.assertEqual(out, [{"id": "tsfm_chronos2", "state": "QUEUED"}])
        st = b.state["components"]["tsfm_chronos2"]
        self.assertEqual(st["state"], "NOT_INSTALLED")
        self.assertIn("kolejka wstrzymana", st["detail"])

    def test_own_running_job_is_followed_not_waited_for(self):
        rt = types.SimpleNamespace(tsfm=types.SimpleNamespace(jobs={"install_chronos2": {"state": "RUNNING"}}), kronos=None, demo=False)
        installed = set()

        def poll():
            installed.add("tsfm_chronos2")
            return "DONE"
        b = self.make(rt, installed, {"tsfm_chronos2": ((lambda: {"ok": False, "reason": "install_chronos2 już trwa"}), poll)})
        self.assertEqual(b.run_heavy(timeout_s=0.5), [{"id": "tsfm_chronos2", "state": "INSTALLED"}])

    def test_component_installed_by_the_awaited_job_is_not_reinstalled(self):
        jobs = {"install": None, "migrate": {"state": "RUNNING"}}                # Kronos-base -> Kronos-small weight download
        rt = types.SimpleNamespace(tsfm=None, kronos=types.SimpleNamespace(jobs=jobs), demo=False)
        installed, started = set(), []

        def finish():
            installed.add("kronos_model")
            jobs["migrate"]["state"] = "DONE"
        b = self.make(rt, installed, {"kronos_model": ((lambda: started.append(1) or {"ok": True}), (lambda: "DONE"))}, queued=("kronos_model",))
        threading.Timer(0.1, finish).start()
        out = b.run_heavy(timeout_s=10)
        self.assertEqual(started, [])
        self.assertEqual(out, [{"id": "kronos_model", "state": "VERIFIED"}])


class TestBootstrapProfileLock(unittest.TestCase):
    """chunk_00#9: set_profile wrote the state file without the lock the bootstrap thread holds in _set."""

    def test_set_profile_waits_for_the_state_lock(self):
        from masterquo.bootstrap import Bootstrap
        b = Bootstrap(state_file=Path(tempfile.mkdtemp()) / "b.json")
        b._lock.acquire()
        th = threading.Thread(target=b.set_profile, args=("CORE",), daemon=True)
        try:
            th.start()
            th.join(0.3)
            self.assertTrue(th.is_alive(), "set_profile ran while the bootstrap thread held the state lock")
        finally:
            b._lock.release()
        th.join(5)
        self.assertFalse(th.is_alive())
        self.assertEqual(json.loads(b.file.read_text(encoding="utf-8"))["profile"], "CORE")


# ============================================================================================== data quality / clock
class TestServerNowIsNotUtc(unittest.TestCase):
    """chunk_08#11: server_now (broker wall clock = UTC + offset) carried a 'Z' suffix and read as a UTC instant."""

    def test_server_now_without_zone_and_with_offset(self):
        from masterquo.data.quality import assess
        now = datetime(2026, 11, 20, 1, 16, 30, tzinfo=UTC)
        r = assess(symbol="XAUUSD-", bars_by_tf={}, required={}, quote={"bid": 1, "ask": 1.1, "age_seconds": 0.5, "source_age_seconds": 0.5},
                   clock={"status": "VERIFIED", "offset_seconds": 7200}, connection_state="CONNECTED", now=now, max_quote_age=10,
                   symbol_status="OK")
        self.assertEqual(r["server_now"], "2026-11-20T03:16:30")
        self.assertEqual(r["server_tz_offset_s"], 7200)
        self.assertEqual(r["assessed_at"], "2026-11-20T01:16:30Z")                # real UTC timestamps keep their 'Z'

    def test_unused_imports_not_reexported(self):
        """chunk_08#14 / chunk_08#15: unused imports were hidden from the linter through __all__."""
        from masterquo.data import pcclock as PC
        from masterquo.data import quality as Q
        self.assertNotIn("parse_iso", Q.__all__)
        self.assertNotIn("datetime", PC.__all__)
        self.assertFalse(hasattr(PC, "datetime"))


# ============================================================================================== MT5 history export
class TestExportHistoryLastClosedBar(unittest.TestCase):
    """chunk_00#8: the last closed D1 bar of the range was dropped - its next bar (the closure proof) lay beyond the end + 4 h fetch."""

    def setUp(self):
        self.td = TempData()
        self.out = tempfile.mkdtemp(prefix="mq_exp_")
        from masterquo.mt5.fake import FakeMT5
        sys.modules["MetaTrader5"] = FakeMT5()

    def tearDown(self):
        sys.modules.pop("MetaTrader5", None)
        shutil.rmtree(self.out, ignore_errors=True)
        self.td.close()

    def test_last_closed_d1_bar_is_exported(self):
        import csv

        from masterquo import diagnostics as D
        now = datetime.now(UTC)
        d1_open = (now - timedelta(days=3)).replace(hour=21, minute=0, second=0, microsecond=0)   # server midnight (offset +3 h)
        end = d1_open + timedelta(hours=12)
        z = lambda d: d.isoformat().replace("+00:00", "Z")
        with redirect_stdout(StringIO()):
            self.assertEqual(D.export_history(z(end - timedelta(days=6)), z(end), self.out), 0)
        with open(os.path.join(self.out, "D1.csv"), encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(rows[-1]["time_utc"], z(d1_open))                     # closed long ago, its successor exists
        self.assertTrue(all(r["time_utc"] < z(end) for r in rows))              # bars after the range only confirm, never exported


# ============================================================================================== SHADOW evaluation
def _cand(**kw):
    from masterquo.evaluation import contract as K
    base = {"setup_id": "S-1", "engine": "SH_SCALPING", "strategy_id": "SCALPING", "symbol": "XAUUSD-", "instrument": "XAUUSD",
            "timeframe": "M1", "decision_ts": 1_760_000_000.0, "direction": "LONG", "entry_type": "MARKET", "entry_price": 100.0,
            "stop_loss": 99.0, "targets": [{"price": 102.0, "weight": 1.0}], "horizon_s": 1800.0}
    base.update(kw)
    return K.SetupCandidate(**base)


def _m1(t0, rows):
    return [{"open_utc": datetime.fromtimestamp(t0 + 60 * i, UTC).isoformat().replace("+00:00", "Z"), "o": c, "h": h, "l": l, "c": c,
             "closed": True} for i, (h, l, c) in enumerate(rows)]


class TestContractRejectsMalformedInput(unittest.TestCase):
    """chunk_10#16: malformed targets / data_quality raised AttributeError (HTTP 500 in POST /api/v1/quant/assessment); bool weight passed."""

    def test_contract_errors_not_attribute_errors(self):
        from masterquo.evaluation import contract as K
        for kw in ({"targets": ["x"]}, {"targets": {"a": 1}}, {"data_quality": ["x"]}, {"targets": [{"price": 102.0, "weight": True}]},
                   {"execution_context": ["spread"]}, {"features_as_of": "yesterday"}, {"data_quality": {"data_as_of": "x"}}):
            with self.assertRaises(K.ContractError, msg=str(kw)):
                _cand(**kw).validate()
        _cand().validate()                                                    # a well-formed candidate still passes


class TestUnknownCostIsNotZero(unittest.TestCase):
    """chunk_10#14: an unknown extra cost was stored as cost_r = 0.0 and then used as a known zero cost in plan_r_net."""

    def test_engine_and_outcome(self):
        from masterquo.evaluation import engine as E
        from masterquo.evaluation import outcome as O
        c = _cand()
        self.assertIsNone(E.economics(c, None)["cost_r"])
        a = E.assess(c, prob=None, extra_cost=None)
        self.assertIsNone(a.cost_r)
        self.assertEqual(E.assess(c, prob=None, extra_cost=0.1).cost_r, 0.1)   # a known cost is unchanged
        out = O.label(c.to_dict(), _m1(c.decision_ts, [(102.5, 99.9, 102.2)]), cost_r=None)
        self.assertEqual((out["status"], out["plan_r_gross"], out["plan_r_net"]), ("MATURED", 2.0, None))
        self.assertIsNone(O.event_hit("ACTIVE_S01_S12", out))                 # net R > 0 is unknown without the cost


class TestNoBarsOutcomeIsUnknown(unittest.TestCase):
    """chunk_10#15: an empty window returned NO_BARS next to exit TIMEOUT and plan_r / MFE / MAE = 0."""

    def test_no_bars_has_no_numbers(self):
        from masterquo.evaluation import outcome as O
        out = O.label(_cand().to_dict(), [], cost_r=0.1)
        self.assertEqual(out["status"], "NO_BARS")
        for k in ("exit", "first_event", "plan_r_gross", "plan_r_net", "mfe_r", "mae_r", "hold_s", "targets_hit"):
            self.assertIsNone(out[k], k)
        self.assertIsNone(O.event_hit("ACTIVE_S01_S12", out))


class TestEvaluationService(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        from masterquo.evaluation.service import EvaluationService
        from test_sh_service import NOW, Bridge
        self.now = NOW
        self.db = Database()
        self.bridge = Bridge(None, "HEDGING")
        self.bridge.buffer_symbol = self.bridge.symbol_info["name"]
        self.bars: list = []
        self.bridge.bars = lambda tf, limit=None, include_forming=True: list(self.bars)
        self.svc = EvaluationService(ConfigStore(), self.bridge, self.db, data_dir=Path(self.td.dir) / "evaluation", clock=lambda: NOW)

    def tearDown(self):
        self.svc.ledger.c.close()
        self.db.close()
        self.td.close()

    def test_unknown_cost_stays_unknown_through_maturity_and_report(self):
        """chunk_10#14 (service path): cost_r None -> plan_r_net None -> the report does not average it as a number."""
        plan = {"setup_id": "SC-1", "direction": "BUY", "decision_ts": self.now, "sl": 1999.0, "tp1": 2001.0, "tp2": 2002.0,
                "fill_shadow": 2000.2, "spread_fill": 0.2, "entry_mode": "MARKET", "model_b": {"status": "UNAVAILABLE", "pass": False}}
        self.svc.on_scalp_setup(plan, status="BLOCKED", reasons=[], instrument="XAUUSD", symbol="XAUUSD-", f1=0.5, horizon_s=1800,
                                extra_cost=None, commission_known=None)
        self.assertIsNone(self.svc.assessments()[0]["cost_r"])
        self.bars = _m1(self.now, [(2000.4, 2000.0, 2000.2), (2001.1, 2000.1, 2000.9)] + [(2000.9, 2000.4, 2000.6)] * 30)
        self.svc.mature(self.now + 3600)
        out = self.svc.assessments()[0]["outcome"]
        self.assertEqual(out["status"], "MATURED")
        self.assertIsNone(out["plan_r_net"])
        self.assertIsNotNone(out["plan_r_gross"])
        g = self.svc.report()["groups"][0]
        self.assertEqual((g["n"], g["mean_plan_r_net"], g["net_r_unknown"]), (1, None, 1))

    def test_active_path_checks_quote_age(self):
        """chunk_10#20: the S01-S12 quote carried no age, so QUOTE_AGE was never checked on the ACTIVE path."""
        class View:
            symbol, bid, ask, regime = "XAUUSD-", 2000.0, 2000.2, {"state": "TREND_UP"}
        self.bridge.quote_status = lambda: {"bid": 2000.0, "ask": 2000.2, "age_seconds": 30.0}
        row = {"setup_id": "ST-1", "stage": "CONFIRMED", "status": "ACTIVE", "version": 2, "expires_at": None, "stale": 0,
               "record": {"strategy_id": "S01", "direction": "LONG", "timeframe": "M15", "stop_loss": 1997.0, "setup_score": 71,
                          "targets": [{"price": 2003.0, "weight": 0.5}, {"price": 2006.0, "weight": 0.5}],
                          "entry_plan": {"order_type": "MARKET_ON_CONFIRMATION"}}}
        self.svc.on_active_events([("STAGE_CONFIRMED", row)], View())
        it = self.svc.assessments("ACTIVE_S01_S12")[0]
        self.assertEqual(it["execution"], "POOR")
        self.assertTrue(any(r.startswith("EXECUTION_QUOTE_AGE_30.0s") for r in it["reasons"]), it["reasons"])
        self.bridge.quote_status = lambda: {"bid": 2000.5, "ask": 2000.7, "age_seconds": 0.1}   # a NEWER tick: its age is not this quote's
        self.svc.on_active_events([("PLAN_REVISED", {**row, "version": 3})], View())
        self.assertNotEqual(self.svc.assessments("ACTIVE_S01_S12")[0]["execution"], "POOR")


# ============================================================================================== strategy ROI (TASK 014)
class TestStrategyRoi(unittest.TestCase):
    def test_closed_sh_plans_are_reported(self):
        """focus_X2#11: only `trades` was read - closed SH plans (pack variants, FX baskets via AUTO_SH) were silently missing."""
        from masterquo.db.database import Database
        from masterquo.evaluation import strategy_roi as SR
        td = TempData()
        try:
            db = Database()

            def plan(pid, mode, state, sid, result, strategy="SCALPING"):
                db.execute("INSERT INTO sh_plans(plan_id, signal_id, strategy, instrument, symbol, side, exec_mode, account_key, state, "
                           "config_hash, plan, created_at, updated_at, closed_at, result, strategy_id, signal_tf) VALUES "
                           "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (pid, "sig-" + pid, strategy, "XAUUSD", "XAUUSD-", "BUY", mode, "Srv:1", state, "cfg1", "{}", 1.0, 2.0,
                            1_763_000_000.0, json.dumps(result) if result is not None else None, sid, "M1" if sid else None))
            plan("p1", "PAPER", "CLOSED", "PMW_SC01", {"net_money": 12.5, "r_multiple": 0.5, "commission_money": 1.0, "commission_known": True})
            plan("p2", "PAPER", "CLOSED", None, {"net_money": -5.0, "r_multiple": -0.25, "commission_known": False}, strategy="HEDGING")
            plan("p3", "PAPER", "ERROR_CLOSED", "PMW_SC01", {"net_money": None})
            plan("p4", "AUTO_DEMO", "CLOSED", "PMW_SC01", {"net_money": 3.0, "r_multiple": 0.1, "commission_known": True})
            rep = SR.report(SR.outcomes_from_db(db, "PAPER"))
            by = {it["scope"]["strategy_id"]: it for it in rep["items"]}
            self.assertEqual(set(by), {"PMW_SC01", "LEGACY_HEDGING"})
            self.assertEqual(by["PMW_SC01"]["scope"]["source"], "SH_PLANS")
            self.assertEqual((by["PMW_SC01"]["trades"], by["PMW_SC01"]["net"], by["PMW_SC01"]["scope"]["environment"]), (1, 12.5, "PAPER"))
            self.assertEqual(by["LEGACY_HEDGING"]["cost_coverage_pct"], 0.0)          # commission unknown is reported, not assumed
            self.assertEqual(rep["excluded"]["UNSETTLED"], 1)                          # ERROR_CLOSED plan: never a settled result
            db.close()
        finally:
            td.close()

    def test_zero_expectancy_is_not_missing_data(self):
        """chunk_10#19: `-(expectancy_r or -1e9)` ranked an expectancy of exactly 0.0 behind losing strategies."""
        from masterquo.evaluation import strategy_roi as SR
        base = {"version": "1", "config_hash": "h", "market": "FOREX", "instrument": "XAUUSD", "venue": "MT5", "timeframe": "M5",
                "environment": "PAPER", "account": "a", "currency": "USD", "source": "X", "status": "CLOSED", "commission": 0.0, "swap": 0.0}
        rows = [{**base, "strategy_id": sid, "net_pnl": pnl, "r_multiple": r, "closed_at": "2026-01-01"}
                for sid, pnl, r in (("S_POS", 50.0, 0.5), ("S_NEG", -30.0, -0.3), ("S_ZERO", 0.0, 0.0), ("S_NONE", 10.0, None))]
        order = [it["scope"]["strategy_id"] for it in SR.report(rows)["items"]]
        self.assertEqual(order, ["S_POS", "S_ZERO", "S_NEG", "S_NONE"])


# ============================================================================================== Kronos service
class TestKronosService(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import kronos_testkit as K
        from masterquo.db.database import Database
        from masterquo.kronos.service import KronosService
        from masterquo.kronos.settings import SettingsStore

        class WarnLog:                                           # the real AppLog API: info / warn / error (no warning())
            def __init__(self):
                self.lines = []

            def info(self, *a):
                self.lines.append(("INFO",) + a)

            def warn(self, *a):
                self.lines.append(("WARN",) + a)
        self.log = WarnLog()
        self.svc = KronosService(K.FakeCfgStore(K.FakeCfg({"XAUUSD": K.FakeMapping("XAUUSD-")})), K.FakeBridge({}),
                                 Database(Path(self.td.dir) / "t.sqlite"), K.Bus(), self.log,
                                 settings=SettingsStore(Path(self.td.dir) / "kronos" / "settings.json"))

    def tearDown(self):
        self.svc.stop()
        self.svc.db.close()
        self.td.close()

    def test_failure_reaches_the_event_log(self):
        """chunk_12#16: _fail() called applog.warning only if it existed - AppLog has warn(), so no failure was ever logged."""
        self.assertFalse(self.svc._fail("LOAD_ERROR", "plik wag uszkodzony"))
        self.assertEqual(self.svc.state["code"], "LOAD_ERROR")
        self.assertEqual([x[:3] for x in self.log.lines], [("WARN", "KRONOS", "LOAD_ERROR")])

    def test_public_reads_the_queue_under_its_lock(self):
        """chunk_12#19: public() iterated the queue without _qlock while the exec / scheduler threads mutate it (RuntimeError -> 500)."""
        held = [False]

        class Lock:
            def __init__(self):
                self.c = threading.Condition()

            def __enter__(self):
                self.c.__enter__()
                held[0] = True
                return self

            def __exit__(self, *a):
                held[0] = False
                return self.c.__exit__(*a)

            def notify_all(self):
                self.c.notify_all()

        class GuardedQueue(OrderedDict):
            def __iter__(self):
                if not held[0]:
                    raise RuntimeError("OrderedDict iterated without _qlock")
                return super().__iter__()
        self.svc._qlock = Lock()
        q = GuardedQueue()
        q[("XAUUSD", "M5")] = {"job": 1}
        self.svc.queue = q
        self.svc.jobs["migrate"] = {"state": "RUNNING", "message": "x"}
        pub = self.svc.public()
        self.assertEqual(pub["queue"], [["XAUUSD", "M5"]])
        self.assertEqual(pub["jobs"]["migrate"]["state"], "RUNNING")


if __name__ == "__main__":
    unittest.main()
