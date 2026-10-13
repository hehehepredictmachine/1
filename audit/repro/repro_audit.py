"""Minimal, isolated reproductions of the audit findings (A-J) - no MT5 terminal, no real orders, temporary data dir.

Run from the project root:  python audit/repro/repro_audit.py --out audit/repro/wyniki_<label>.json
Every case records: inputs, observed result, expected (correct) result and a status:
  REPRODUCED      - the observed behaviour differs from the expected one (the defect exists in this code)
  NOT_REPRODUCED  - the code behaves as expected (defect absent / fixed)
  ERROR           - the case could not run (exception text recorded)
The same script is run on 1.9.0 (before the fixes) and on the fixed version - results are stored separately.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
import tempfile
import threading
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
UTC = timezone.utc


def iso(t: datetime) -> str:
    return t.astimezone(UTC).isoformat().replace("+00:00", "Z")


# ----------------------------------------------------------------------------- fakes (no terminal)
class FakeBridge:
    """Just enough of MarketBridge for PaperBroker / PositionManager. Linear XAU: 100 oz per lot."""

    def __init__(self, bid=2000.0, ask=2000.2, profit_ok=True):
        self._lock = threading.Lock()
        self.deals: list[dict] = []
        self.positions: list[dict] = []
        self.symbol_info = {"point": 0.01, "digits": 2, "volume_min": 0.01, "volume_step": 0.01, "volume_max": 100.0,
                            "trade_contract_size": 100.0, "filling_mode": 1, "trade_stops_level": 0, "trade_freeze_level": 0}
        self.account_key = "Fake:1"
        self.state = "CONNECTED"
        self.session_epoch = 1
        self.synthetic = True
        self.deals_loaded_at = None
        self.q = {"bid": bid, "ask": ask, "spread": round(ask - bid, 5), "age_seconds": 0.1, "time_msc": None}
        self.profit_ok = profit_ok
        self.sent: list[dict] = []
        self.send_retcode = 10009

        class _C:
            offset = 0
        self.clock = _C()

    def quote_status(self):
        return dict(self.q)

    def account_status(self):
        return {"currency": "USD", "balance": 10000.0, "equity": 10000.0, "server": "Fake"}

    def calc_profit(self, side, vol, o, c):
        if not self.profit_ok:
            return None
        return round((c - o if side == "BUY" else o - c) * 100 * vol, 2)

    def raw_call(self, fn, prio=None, timeout=None):
        class T:
            bid, ask = self.q["bid"], self.q["ask"]

        class M:
            TRADE_ACTION_DEAL, TRADE_ACTION_SLTP, ORDER_TYPE_BUY, ORDER_TYPE_SELL = 1, 6, 0, 1
            ORDER_TIME_GTC, ORDER_FILLING_FOK, ORDER_FILLING_IOC = 0, 0, 1

            @staticmethod
            def symbol_info_tick(s):
                return T

            @staticmethod
            def order_send(req, _b=self):
                _b.sent.append(dict(req))

                class R:
                    retcode = _b.send_retcode
                    volume = req.get("volume")
                    price = req.get("price")
                return R
        return fn(M)


class Env:
    """Temporary data dir + config + DB + bus + log (the real classes, isolated from the user's data)."""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="mq_audit_")
        os.environ["MASTERQUO_DATA_DIR"] = self.dir
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        from masterquo.events import AppLog, EventBus
        self.cfg = ConfigStore()
        self.db = Database()
        self.bus = EventBus()
        self.log = AppLog(self.db, self.bus)

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def paper_stack(env, bridge):
    from masterquo.execution.manager import PositionManager
    from masterquo.execution.paper import PaperBroker

    class Modes:
        mode = "PAPER"

        def gate(self, _k):
            return {"mode": "PAPER", "allowed": True}
    paper = PaperBroker(env.cfg, bridge, env.db, env.bus, env.log)
    mgr = PositionManager(env.cfg, bridge, env.db, env.bus, env.log, Modes(), paper)
    return paper, mgr


def open_paper(env, paper, *, targets, sl, side="BUY", lots=0.10, exit_rules=None, setup_id="MQS-A1"):
    now = iso(datetime.now(UTC))
    env.db.execute("""INSERT INTO order_attempts(attempt_id, entry_key, decision_id, setup_id, created_at, updated_at, mode, account_key, symbol, side,
                      volume, price_requested, sl, tp, client_tag, state, initiated_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                   ("ATT-" + setup_id, "PAPER:x:" + setup_id, "DEC-" + setup_id, setup_id, now, now, "PAPER", "Fake:1", "XAUUSD-", side, lots, 2000.2,
                    sl, targets[-1]["price"], "MQ:A", "PREPARED", "TEST"))
    dec = {"decision_id": "DEC-" + setup_id, "symbol": "XAUUSD-", "setup": {"setup_id": setup_id, "strategy_id": "S01"},
           "risk": {"modeled_loss": 100.0, "targets": targets, "exit_rules": exit_rules, "stop_loss": sl}}
    import inspect
    kw = {}
    if "exit_policy" in inspect.signature(paper.open).parameters:          # fixed versions store the policy at open
        from masterquo.execution import policy as pol
        kw["exit_policy"] = pol.from_plan(side="LONG" if side == "BUY" else "SHORT", stop_loss=sl, targets=targets, exit_rules=exit_rules or {},
                                          timeframe="M15", tp1_weight_default=env.cfg.get().strategy.tp1_weight,
                                          be_default=env.cfg.get().strategy.move_sl_to_breakeven_after_tp1)
    return paper.open(attempt_id="ATT-" + setup_id, decision=dec, side=side, lots=lots, sl=sl, targets=targets, **kw)


# ----------------------------------------------------------------------------- cases
def case_A():
    """ML label cost vs execution cost: commission known only from MT5 deal history, manual field empty."""
    env = Env()
    try:
        from masterquo.ml.service import MLService
        from masterquo.risk.costs import resolve_commission
        cfg = env.cfg.update({"costs": {"commission_mode": "FROM_DEAL_HISTORY", "commission_per_lot_per_side": None}})
        deals = [{"symbol": "XAUUSD-", "type": 0, "entry": 0, "volume": 0.1, "commission": -0.35} for _ in range(5)]
        b = FakeBridge()
        b.deals = deals
        exec_c = resolve_commission(cfg.costs, deals, "XAUUSD-")

        class Self:
            cfg_store = env.cfg
            bridge = b
        Self.bridge.symbol_info = dict(b.symbol_info)
        ml = MLService._cost(Self())
        expected_price_units = 3.5 / 100.0
        observed = {"execution_commission_per_lot_side": exec_c.get("per_lot_per_side"), "execution_source": exec_c.get("source"),
                    "ml_commission_price_units": ml["commission"], "ml_flags": ml["flags"]}
        bad = abs(ml["commission"] - expected_price_units) > 1e-9
        return {"id": "A", "title": "Prowizja w etykietach ML vs wykonanie (tylko historia deals)", "inputs": {"commission_mode": "FROM_DEAL_HISTORY",
                "manual_commission": None, "deals": "5 x 0.1 lota, prowizja 0.35 USD/deal (= 3.5 USD/lot/stronę)"},
                "observed": observed, "expected": {"ml_commission_price_units": expected_price_units, "note": "ten sam koszt co wykonanie (3.5 USD/lot/stronę)"},
                "status": "REPRODUCED" if bad else "NOT_REPRODUCED"}
    finally:
        env.close()


def case_B():
    """PAPER: TP1 partial exit while the rest of the position is still open, then the rest closes at a loss."""
    env = Env()
    try:
        from masterquo import stats
        b = FakeBridge(bid=2000.0, ask=2000.2)
        paper, mgr = paper_stack(env, b)
        tg = [{"price": 2005.0, "weight": 0.5}, {"price": 2010.0, "weight": 0.5}]
        open_paper(env, paper, targets=tg, sl=1995.0)
        b.q.update(bid=2005.1, ask=2005.3)                 # TP1
        mgr._manage_paper()
        after_tp1 = stats.bot_stats(env.db, "PAPER")["all"]
        pos = env.db.one("SELECT state, volume_open, sl FROM managed_positions")
        b.q.update(bid=1990.0, ask=1990.2)                 # the rest stopped (BE or SL)
        mgr._manage_paper()
        final = stats.bot_stats(env.db, "PAPER")["all"]
        rows = env.db.query("SELECT trade_id, closed_at, volume, net_pnl FROM trades")
        bad = after_tp1["trades"] > 0 and pos["state"] == "OPEN"
        return {"id": "B", "title": "PAPER: częściowe wyjście liczone jako zamknięta transakcja", "inputs": {"entry_ask": 2000.2, "sl": 1995.0,
                "targets": tg, "lots": 0.10, "path": "TP1 2005.1 -> 1990.0"},
                "observed": {"stats_after_tp1_trades": after_tp1["trades"], "stats_after_tp1_wins": after_tp1.get("wins"),
                             "position_after_tp1": pos, "trades_rows": rows, "final_stats": {k: final.get(k) for k in ("trades", "wins", "losses", "breakeven", "net")}},
                "expected": {"stats_after_tp1_trades": 0, "note": "pozycja otwarta nie trafia do statystyk zamkniętych transakcji; po zamknięciu jedna transakcja"},
                "status": "REPRODUCED" if bad else "NOT_REPRODUCED"}
    finally:
        env.close()


def case_C():
    """labels.step(): the M1 low BEFORE TP1 must not hit the break-even stop set after TP1."""
    from masterquo.ml import labels as lb
    t0 = datetime(2026, 10, 13, 10, 0, tzinfo=UTC)
    spec = {"direction": "LONG", "asof_utc": iso(t0), "stop_loss": 90.0, "targets": [{"price": 105.0, "weight": 0.5}, {"price": 110.0, "weight": 0.5}],
            "be_after_tp1": True, "horizon_minutes": 60, "entry_window_minutes": 5, "spread": 0.0, "slippage": 0.0, "commission": 0.0}
    st = lb.new_state(spec)
    entry_bar = {"open_utc": iso(t0), "o": 100.0, "h": 100.0, "l": 100.0, "c": 100.0}
    bar = {"open_utc": iso(t0 + timedelta(minutes=1)), "o": 100.0, "h": 106.0, "l": 99.0, "c": 106.0}
    tb = (t0 + timedelta(minutes=1)).timestamp()
    ticks = [(tb + 1, 100.0, 100.0), (tb + 10, 99.0, 99.0), (tb + 20, 105.0, 105.0), (tb + 40, 106.0, 106.0)]
    st, res = lb.step(spec, st, [entry_bar], ticks, t0 + timedelta(minutes=1))
    st, res = lb.step(spec, st, [bar], ticks, t0 + timedelta(minutes=2))
    observed = {"result": res, "remaining": st.get("remaining"), "stop": st.get("stop")}
    bad = bool(res) and res.get("exit_reason") == "BREAKEVEN_STOP"
    return {"id": "C", "title": "TP1 -> BE w jednej świecy M1 (minimum przed TP1)", "inputs": {"spec": spec, "bar": bar, "ticks": ticks},
            "observed": observed, "expected": {"result": None, "remaining": 0.5, "stop": 100.0,
                                               "note": "po TP1 cena nie wróciła do 100 -> pozycja (0.5) nadal otwarta, SL na BE"},
            "status": "REPRODUCED" if bad else "NOT_REPRODUCED"}


def case_D():
    """S11 exit_rules.time_exit_bars=None in labels.make_spec() and tools/replay_strategies.simulate()."""
    from masterquo.ml import labels as lb
    rec = {"direction": "LONG", "stop_loss": 1990.0, "targets": [{"price": 2025.0, "weight": 1.0}], "timeframe": "M15",
           "exit_rules": {"tp_rule": "RR_FROM_FILL", "rr": 2.5, "be_after_tp1": False, "trailing": None, "time_exit_bars": None}}
    out = {}
    try:
        spec = lb.make_spec(rec, "2026-10-13T10:00:00Z", spread=0.2, slippage=0.05, commission=0.035, cost_flags=[])
        out["make_spec"] = {"ok": True, "horizon_minutes": spec.get("horizon_minutes"), "tp_rule": spec.get("tp_rule")}
    except Exception as exc:
        out["make_spec"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import replay_strategies as rp
        t0 = datetime(2026, 10, 13, 10, 0, tzinfo=UTC)
        m5 = [{"open_utc": iso(t0 + timedelta(minutes=5 * i)), "o": 2000.0, "h": 2001.0, "l": 1999.0, "c": 2000.0} for i in range(10)]
        idx = {"times": [t0 + timedelta(minutes=5 * i) for i in range(10)]}
        r = rp.simulate(dict(rec, setup_id="X"), t0, m5, idx, {"spread": 0.2, "slip": 0.05, "commission": 0.035})
        out["replay_simulate"] = {"ok": True, "result": r}
    except Exception as exc:
        out["replay_simulate"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    bad = not out["make_spec"]["ok"] or not out["replay_simulate"]["ok"]
    return {"id": "D", "title": "S11: time_exit_bars=None w etykietach ML i replay", "inputs": {"exit_rules": rec["exit_rules"]},
            "observed": out, "expected": {"note": "brak time-exit reprezentowany jawnie (bez ukrytego 24), TP liczony od fillu (RR_FROM_FILL)"},
            "status": "REPRODUCED" if bad else "NOT_REPRODUCED"}


def case_E():
    """Exit policy: the manager uses GLOBAL config weights / BE instead of the setup's own exit_rules and targets."""
    env = Env()
    try:
        env.cfg.update({"strategy": {"tp1_weight": 0.5, "move_sl_to_breakeven_after_tp1": True}})
        b = FakeBridge(bid=2000.0, ask=2000.2)
        paper, mgr = paper_stack(env, b)
        tg = [{"price": 2004.0, "weight": 0.3}, {"price": 2008.0, "weight": 0.3}, {"price": 2012.0, "weight": 0.4}]
        open_paper(env, paper, targets=tg, sl=1995.0, exit_rules={"be_after_tp1": False, "time_exit_bars": 24})
        pos0 = env.db.one("SELECT tp1, tp2 FROM managed_positions")
        b.q.update(bid=2004.1, ask=2004.3)
        mgr._manage_paper()
        after = env.db.one("SELECT volume_open, sl, be_done FROM managed_positions")
        closed = round(0.10 - after["volume_open"], 4)
        bad = abs(closed - 0.03) > 1e-9 or after["sl"] != 1995.0 or (pos0["tp1"], pos0["tp2"]) == (2004.0, 2012.0)
        return {"id": "E", "title": "Polityka wyjścia: globalne wagi/BE zamiast reguł setupu (3 cele, be_after_tp1=False)",
                "inputs": {"targets": tg, "exit_rules": {"be_after_tp1": False, "time_exit_bars": 24}, "cfg_tp1_weight": 0.5, "cfg_be": True},
                "observed": {"stored_tp1_tp2": pos0, "closed_at_tp1": closed, "sl_after_tp1": after["sl"], "be_done": after["be_done"],
                             "middle_target_2008_stored": False},
                "expected": {"closed_at_tp1": 0.03, "sl_after_tp1": 1995.0, "note": "wagi i BE z planu setupu zapisane przy otwarciu; środkowy cel nie znika"},
                "status": "REPRODUCED" if bad else "NOT_REPRODUCED"}
    finally:
        env.close()


def case_F():
    """MT5 TP1 partial close rejected by the broker: tp1_done must not be set (and BE must not follow)."""
    env = Env()
    try:
        b = FakeBridge(bid=2005.1, ask=2005.3)
        b.send_retcode = 10006                             # REJECT
        _paper, mgr = paper_stack(env, b)
        now = iso(datetime.now(UTC))
        env.db.execute("""INSERT INTO managed_positions(position_key, mode, account_key, position_ticket, side, symbol, volume_initial, volume_open,
                          entry_price, sl, tp1, tp2, state, opened_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       ("AUTO_DEMO:Fake:1:77", "AUTO_DEMO", "Fake:1", 77, "BUY", "XAUUSD-", 0.10, 0.10, 2000.2, 1995.0, 2005.0, 2010.0, "OPEN", now))
        b.positions = [{"ticket": 77, "volume": 0.10, "sl": 1995.0, "tp": 2010.0, "symbol": "XAUUSD-"}]
        mgr._manage_mt5_positions()
        st1 = env.db.one("SELECT * FROM managed_positions")
        mgr._manage_mt5_positions()                         # next tick
        st2 = env.db.one("SELECT * FROM managed_positions")
        sl_moves = [r for r in b.sent if r.get("action") == 6]
        tp1_state = st1.get("tp1_state") if "tp1_state" in st1 else None
        bad = st1["tp1_done"] == 1 and (len(sl_moves) > 0 or tp1_state is None)
        return {"id": "F", "title": "TP1 oznaczony przed potwierdzeniem order_send (odrzucenie brokera)",
                "inputs": {"retcode": "10006 REJECT", "volume_open": 0.10},
                "observed": {"tp1_done_after_reject": st1["tp1_done"], "tp1_state": tp1_state, "volume_open": st2["volume_open"],
                             "sl_to_be_requests_after_reject": len(sl_moves), "requests": [{k: r.get(k) for k in ("action", "volume", "sl", "comment")} for r in b.sent]},
                "expected": {"tp1_done_after_reject": 0, "tp1_state": "REJECTED", "sl_to_be_requests_after_reject": 0,
                             "note": "stan TP1 z wykonania: REQUESTED/UNKNOWN/CONFIRMED/REJECTED; BE dopiero po potwierdzonym TP1"},
                "status": "REPRODUCED" if bad else "NOT_REPRODUCED"}
    finally:
        env.close()


def case_G():
    """ML: champion re-evaluated on a date window of the new test block instead of the same sample_ids."""
    from masterquo.ml import validation as V
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    rows = []
    for i in range(100):
        a = t0 + timedelta(hours=i)
        ev = f"E{i}" if i != 81 else "E79"                # sample 81 belongs to an event that started at sample 79 (calib)
        rows.append({"sample_id": f"S{i:03d}", "group_id": f"G{i}", "event_id": ev, "asof_utc": iso(a),
                     "label_end_utc": iso(a + timedelta(minutes=30)), "label": i % 2, "outcome_r": 1.0 if i % 2 else -1.0})
    info, why = V.split(rows, embargo_minutes=0, min_block=1, min_class=1)
    test_ids = {r["sample_id"] for r in info["blocks"]["test"]}
    w = info["windows"]["test"]
    window_ids = {r["sample_id"] for r in rows if w[0] <= r["asof_utc"] <= w[1]}
    bad = window_ids != test_ids
    return {"id": "G", "title": "Porównanie z championem: okno dat zamiast tych samych sample_id",
            "inputs": {"rows": 100, "event_grouping": "S081 należy do zdarzenia E79 (blok CALIB)"},
            "observed": {"test_block": len(test_ids), "window_selection": len(window_ids), "extra_in_window": sorted(window_ids - test_ids)},
            "expected": {"note": "champion i challenger oceniani na identycznym zbiorze sample_id"},
            "status": "REPRODUCED" if bad else "NOT_REPRODUCED"}


def case_J():
    """PAPER: profit calculator unavailable (None) -> the part is booked as 0 instead of 'unsettled'."""
    env = Env()
    try:
        b = FakeBridge(bid=2000.0, ask=2000.2)
        paper, mgr = paper_stack(env, b)
        open_paper(env, paper, targets=[{"price": 2010.0, "weight": 1.0}], sl=1995.0)
        b.profit_ok = False
        b.q.update(bid=1994.0, ask=1994.2)
        mgr._manage_paper()
        rows = env.db.query("SELECT gross_pnl, net_pnl, closed_at FROM trades")
        pos = env.db.one("SELECT state FROM managed_positions")
        bad = bool(rows) and rows[0]["gross_pnl"] == 0.0
        return {"id": "J", "title": "PAPER: brak kalkulacji P/L zapisany jako 0", "inputs": {"calc_profit": None, "exit": "SL 1994.0"},
                "observed": {"trades": rows, "position_state": pos["state"]},
                "expected": {"note": "transakcja nierozliczona (UNSETTLED) - nie zero, nie BE w statystykach"},
                "status": "REPRODUCED" if bad else "NOT_REPRODUCED"}
    finally:
        env.close()


CASES = [case_A, case_B, case_C, case_D, case_E, case_F, case_G, case_J]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default="")
    a = ap.parse_args()
    from masterquo.version import APP_VERSION
    res = []
    for c in CASES:
        try:
            res.append(c())
        except Exception as exc:
            res.append({"id": c.__name__[-1], "status": "ERROR", "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-1500:]})
    out = {"label": a.label, "app_version": APP_VERSION, "run_at_utc": iso(datetime.now(UTC)), "python": sys.version.split()[0],
           "platform": platform.platform(), "environment": "SYNTHETIC_FUNCTIONAL (bez terminala MT5, bez zleceń)", "cases": res}
    Path(a.out).write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    for r in res:
        print(f"{r['id']}: {r['status']}  {r.get('title', r.get('error', ''))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
