"""Etap 4 pkt 4 (PMW-COSTS-1): one cost resolver costs/ with TODAY's policy declared per track - neutrality proofs.

For every track the cost code from before Etap 4 is the reference:
  * `_old_*` below - the old cost expression of the track copied verbatim (runs everywhere, also in a release package without git);
  * where git has the base commit (cf5d941 = the branch after all repair waves), the WHOLE old function of the track loaded from it
    (risk.engine.evaluate, sh.setup.evaluate, sh.risk.evaluate, scalp economics_gate, evaluation _active_cost, quant spec_from_candidate).
Both are compared with the resolver / the new call site on >= 200 random inputs with a fixed seed, bit for bit (float.hex), including
None / 0 / unknown-commission and unconvertible cases. The declarations themselves are checked against the design (no flag, no setter,
an undeclared policy value is refused)."""
from __future__ import annotations

import math
import random
import subprocess
import sys
import types
import unittest
from types import SimpleNamespace

import _env
from _env import TempData

if str(_env.ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(_env.ROOT / "tools"))

BASE = "cf5d941"
N = 300
SEED = 1464


def _bits(x):
    """Nested structure with every float as float.hex - equality = bit-for-bit equality (also -0.0 vs 0.0, NaN)."""
    if isinstance(x, bool) or x is None or isinstance(x, (int, str)):
        return x
    if isinstance(x, float):
        return "nan" if math.isnan(x) else x.hex()
    if isinstance(x, dict):
        return {k: _bits(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return type(x)(_bits(v) for v in x)
    return repr(x)


def _old_module(rel: str, modname: str):
    """The module `rel` as it was at BASE, executed inside its real package (relative imports resolve to today's siblings)."""
    try:
        r = subprocess.run(["git", "-C", str(_env.ROOT), "show", f"{BASE}:{rel}"], capture_output=True, text=True, check=False)
    except OSError:
        raise unittest.SkipTest("brak git - porównanie z całą starą funkcją pominięte (wzory _old_* nadal sprawdzone)") from None
    if r.returncode != 0:
        raise unittest.SkipTest(f"brak commitu bazowego {BASE} (paczka wydania)")
    m = types.ModuleType(modname)
    m.__package__ = modname.rsplit(".", 1)[0]
    m.__file__ = str(_env.ROOT / rel)
    sys.modules[modname] = m
    try:
        exec(compile(r.stdout, f"<{BASE}:{rel}>", "exec"), m.__dict__)  # noqa: S102 - the repository's own code at the base commit
    finally:
        sys.modules.pop(modname, None)
    return m


def _maybe(rng: random.Random, value, p_none: float = 0.2):
    return None if rng.random() < p_none else value


# ====================================================================================================================== declarations
class TestDeclarations(unittest.TestCase):
    def test_every_track_declares_todays_policy(self):
        from masterquo import costs as C
        from masterquo.costs import policy as P
        self.assertEqual(set(C.TRACKS), {"ACTIVE", "EVALUATION_ACTIVE", "SH", "EVALUATION_SH", "SCALP", "QUANT_LABEL"})
        self.assertEqual(C.profile("SH", "XAUUSD").spread_policy, P.SPREAD_AS_COST)              # O7 unchanged
        self.assertEqual(C.profile("SH").sizing_commission, P.SIZING_TWICE)                      # D2 unchanged (S0)
        for t in ("ACTIVE", "EVALUATION_ACTIVE", "SCALP"):
            self.assertEqual(C.profile(t).spread_policy, P.SPREAD_IN_FILL, t)
        self.assertEqual(C.profile("EVALUATION_SH").spread_policy, P.SPREAD_REMOVED)
        self.assertEqual(C.profile("QUANT_LABEL").unknown_commission_policy, P.UNKNOWN_NO_LABEL)
        pols = {C.profile(t).unknown_commission_policy for t in C.TRACKS}
        self.assertGreaterEqual(len(pols - {P.UNKNOWN_INHERITED}), 4)                             # ETAP2 §4: 4 policies, declared
        self.assertEqual({C.profile(t).slippage_unit for t in ("EVALUATION_ACTIVE", "SH", "SCALP")},
                         {P.SLIP_POINTS, P.SLIP_PRICE, P.SLIP_TICKS})                                 # 3 slippage units
        self.assertEqual({C.profile(t).commission_source for t in ("ACTIVE", "SH", "SCALP")},
                         {P.SOURCE_COSTS_CONFIG, P.SOURCE_SH_PROFILE, P.SOURCE_SCALP_CONFIG})         # 3 commission sources
        p = C.profile("ACTIVE", "XAUUSD-")
        self.assertEqual((p.track, p.instrument, p.schema), ("ACTIVE", "XAUUSD-", "PMW-COSTS-1"))
        self.assertEqual(len(C.policies()), len(C.TRACKS))

    def test_no_flag_no_setter_and_undeclared_policies_refused(self):
        import dataclasses

        from masterquo import costs as C
        with self.assertRaises(KeyError):
            C.profile("SOMETHING_ELSE")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            C.profile("SH").spread_policy = "IN_FILL"                     # type: ignore[misc]
        with self.assertRaises(TypeError):
            C.POLICIES["SH"] = C.POLICIES["ACTIVE"]                       # type: ignore[index]
        src = "\n".join((_env.ROOT / "backend" / "masterquo" / "costs" / f).read_text(encoding="utf-8")
                        for f in ("__init__.py", "policy.py", "resolver.py", "commission.py"))
        for word in ("unified_v2", "environ", "cfg_store", "ConfigStore", "def set_", "global "):
            self.assertNotIn(word, src, word)                            # no flag, no settings read, no policy switch
        bad = dataclasses.replace(C.profile("SH"), spread_policy="SOMETHING")
        with self.assertRaises(ValueError):
            C.resolve(bad, spread=0.2, commission_per_lot_side=0.5, slippage=0.05, money_per_price=100.0)
        with self.assertRaises(ValueError):
            C.sizing_loss_per_lot(C.profile("ACTIVE"), stop_distance=1.0, round_trip_price=0.1, money_per_price=100.0,
                                  commission_per_lot_side=None)
        with self.assertRaises(ValueError):
            C.resolve(C.profile("ACTIVE"), commission_per_lot_side=1.0, slippage=5, point=0.01, move_value=lambda d: d, gate_check=True)

    def test_costs_is_a_stdlib_leaf(self):
        import cycles
        self.assertEqual(cycles.LAYERS.get("costs"), 0)
        es = [e for e in cycles.edges() if e["src"].startswith("masterquo.costs")]
        self.assertEqual([e for e in es if not e["dst"].startswith("masterquo.costs")], [])


# ====================================================================================================================== ACTIVE
def _old_active(comm, slip_pts, point, profit_fn, order_side, entry):
    """risk/engine.evaluate at cf5d941, lines 136-148 (verbatim)."""
    reasons = []
    comm_rt_1 = 2 * comm if comm is not None else None
    if comm is None:
        reasons.append("COST_MODEL_UNKNOWN_COMMISSION")
    slip_1 = None
    if slip_pts is not None and point:
        delta = slip_pts * point
        v = profit_fn(order_side, 1.0, entry, entry - delta if order_side == "BUY" else entry + delta)
        slip_1 = 2 * abs(v) if v is not None else None
    if slip_1 is None:
        reasons.append("SLIPPAGE_STRESS_NOT_CONFIGURED")
    cost_1 = (comm_rt_1 or 0.0) + (slip_1 or 0.0)
    return comm_rt_1, slip_1, cost_1, reasons


def _profit_fn(rng: random.Random):
    cs = rng.choice([1.0, 10.0, 100.0, 1000.0, 100000.0])
    nd = rng.choice([None, 2, 5])
    fails = rng.random() < 0.15

    def f(side, vol, o, c):
        if fails and abs(c - o) < 1.0:                     # broker calculator failure on the small slippage move
            return None
        v = (c - o if side == "BUY" else o - c) * cs * vol
        return round(v, nd) if nd is not None else v
    return f


class TestActive(unittest.TestCase):
    def test_resolver_equals_old_formula(self):
        from masterquo.risk.costs import active_cost_per_lot
        rng = random.Random(SEED)
        for i in range(N):
            comm = _maybe(rng, rng.choice([0.0, -0.0, rng.uniform(0, 12), round(rng.uniform(0, 5), 2)]))
            slip = _maybe(rng, rng.choice([0, 0.0, rng.uniform(0, 50), float(rng.randint(1, 40))]))
            point = rng.choice([None, 0.0, 0.01, 0.001, 0.00001, 1.0])
            pf, side, entry = _profit_fn(rng), rng.choice(["BUY", "SELL"]), rng.uniform(1, 3000)
            old = _old_active(comm, slip, point, pf, side, entry)
            cb = active_cost_per_lot(comm, slip, point,
                                     lambda d, pf=pf, side=side, entry=entry: pf(side, 1.0, entry, entry - d if side == "BUY" else entry + d))
            self.assertEqual(_bits((cb.commission, cb.slippage, cb.total, list(cb.reason_codes))), _bits(old), i)
            self.assertEqual(cb.commission_known and cb.slippage_known, comm is not None and old[1] is not None)

    def test_whole_risk_evaluate_old_vs_new(self):
        old = _old_module("backend/masterquo/risk/engine.py", "masterquo.risk._e4_old_engine")
        from datetime import UTC, datetime

        from masterquo.config import ConfigStore
        from masterquo.risk import engine as new
        td = TempData()
        try:
            base = ConfigStore().get().risk
        finally:
            td.close()
        rng = random.Random(SEED + 1)
        now = datetime(2026, 3, 4, 8, tzinfo=UTC)
        for i in range(N):
            side = rng.choice(["LONG", "SHORT"])
            bid = round(rng.uniform(100, 3000), 2)
            ask = round(bid + rng.choice([0.0, 0.01, 0.2, 1.5]), 2)
            e = ask if side == "LONG" else bid
            sgn = 1 if side == "LONG" else -1
            sl_d, t1, t2 = rng.uniform(0.5, 30), rng.uniform(0.5, 60), rng.uniform(0.5, 90)
            levels = {"status": "AVAILABLE", "stop_loss": e - sgn * sl_d,
                      "targets": [{"price": e + sgn * t1, "weight": 0.5}, {"price": e + sgn * max(t1, t2), "weight": 0.5}]}
            sym = {"point": rng.choice([0.01, 0.001, 0.0]), "trade_stops_level": rng.choice([0, 10]), "trade_mode": 4,
                   "volume_min": 0.01, "volume_max": rng.choice([1.0, 100.0]), "volume_step": 0.01}
            eq = rng.choice([300.0, 5000.0, 10000.0, 250000.0])
            lim = base.model_copy(update={"risk_per_trade_pct": rng.choice([0.5, 1.0, 2.0]), "max_total_open_risk_pct": 3.0,
                                          "daily_loss_limit_pct": 5.0, "max_drawdown_pct": 10.0, "max_open_positions": 3})
            kw = {"side": side, "levels": levels, "quote": {"bid": bid, "ask": ask, "spread_points": round((ask - bid) * 100)},
                  "symbol_info": sym, "account": {"equity": eq, "free_margin": eq, "currency": "USD"}, "limits": lim,
                  "costs_cfg": SimpleNamespace(slippage_stress_points=_maybe(rng, rng.choice([0.0, 5.0, rng.uniform(0, 40)]))),
                  "commission": {"per_lot_per_side": _maybe(rng, rng.choice([0.0, 3.5, rng.uniform(0, 10)]), 0.25), "source": "TEST"},
                  "profit_fn": _profit_fn(rng), "margin_fn": lambda s, v, p: v * p / 100, "positions": [], "deals": [], "day_start_raw": 0,
                  "equity_peak": eq, "open_risk_info": {"open_risk": 0.0, "positions_without_sl": []}, "margin_mode": "HEDGING",
                  "last_bot_loss_at": None, "now": now, "max_spread_points": None, "symbol": "XAUUSD-"}
            self.assertEqual(_bits(new.evaluate(**kw)), _bits(old.evaluate(**kw)), i)


class TestCommissionSourceMoved(unittest.TestCase):
    """commission_from_history / resolve_commission moved verbatim to costs.commission; risk.costs keeps aliases."""

    def _deals(self, rng):
        out = []
        for _ in range(rng.randint(0, 12)):
            out.append({"symbol": rng.choice(["XAUUSD-", "XAUUSD-", "EURUSD"]), "type": rng.choice([0, 1, 2]),
                        "volume": rng.choice([0, 0.01, 0.1, 1.0, rng.uniform(0, 3)]), "entry": rng.choice([0, 1, 2, 3]),
                        "commission": rng.choice([0.0, -3.5, -0.35, rng.uniform(-10, 0), None]), "fee": rng.choice([0.0, None, -0.1])})
        return out

    def test_aliases_are_the_moved_functions(self):
        from masterquo import costs as C
        from masterquo.risk import costs as RC
        self.assertIs(RC.commission_from_history, C.commission_from_history)
        self.assertIs(RC.resolve_commission, C.resolve_commission)
        self.assertEqual((RC.DEAL_ENTRY_IN, RC.DEAL_ENTRY_OUT, RC.DEAL_ENTRY_INOUT, RC.DEAL_ENTRY_OUT_BY, RC.DEAL_TYPE_BUY, RC.DEAL_TYPE_SELL),
                         (0, 1, 2, 3, 0, 1))

    def test_moved_functions_equal_the_old_ones(self):
        old = _old_module("backend/masterquo/risk/costs.py", "masterquo.risk._e4_old_costs")
        from masterquo.costs import commission as new
        rng = random.Random(SEED + 2)
        for i in range(N):
            deals = self._deals(rng)
            ms = rng.choice([1, 3, 5])
            self.assertEqual(_bits(new.commission_from_history(deals, "XAUUSD-", ms)), _bits(old.commission_from_history(deals, "XAUUSD-", ms)), i)
            cfg = SimpleNamespace(commission_mode=rng.choice(["CONFIGURED", "FROM_DEAL_HISTORY", "UNKNOWN"]),
                                  commission_per_lot_per_side=_maybe(rng, rng.choice([0.0, 3.5, rng.uniform(0, 9)]), 0.4))
            self.assertEqual(_bits(new.resolve_commission(cfg, deals, "XAUUSD-")), _bits(old.resolve_commission(cfg, deals, "XAUUSD-")), i)


def _outcome(fn, *a, **kw):
    """Result or the exception type (an old crash must stay the same crash)."""
    try:
        return _bits(fn(*a, **kw))
    except Exception as exc:  # noqa: BLE001
        return ("EXC", type(exc).__name__)


# ====================================================================================================================== SH
def _old_sh_cost(d, ic, spec):
    """sh/setup.evaluate step 7 at cf5d941 (verbatim): cost and the warnings appended to `con`."""
    con = []
    cost = (d.get("spread") or 0.0) + 2 * (ic.get("slippage_usd") or 0.0)
    comm = ic.get("commission_per_lot_side")
    if comm is not None and spec.tick_value > 0:
        cost += 2 * comm / spec.money_per_price(1.0)
    else:
        con.append("prowizja nieznana – koszt bez prowizji (AUTO wymaga znanej prowizji)")
    return cost, comm is not None, con


def _old_sh_loss_per_lot(setup, ic, mpp, sl_dist):
    """sh/risk.evaluate sizing at cf5d941 (verbatim)."""
    cost_price = float((setup.get("costs") or {}).get("round_trip_price") or 0.0)
    comm = ic.get("commission_per_lot_side")
    return (sl_dist + cost_price) * mpp + (2 * comm if comm is not None else 0.0)


def _sh_spec(rng):
    from masterquo.sh.units import SymbolSpec
    tick = rng.choice([0.01, 0.001, 0.1])
    return SymbolSpec("XAUUSD-", tick, rng.choice([0.0, 1.0, 0.1, 0.65, rng.uniform(0.01, 5)]), rng.choice([100, 10, 1]),
                      0.01, 0.01, rng.choice([100, 5]), 2, "USD", source="TEST")


class TestSH(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.sh import config as SC
        self.cfg = SC.load()
        self.SC = SC

    def tearDown(self):
        self.td.close()

    def _ic(self, rng):
        return {"slippage_usd": _maybe(rng, rng.choice([0.0, 0.05, rng.uniform(0, 0.5)])),
                "commission_per_lot_side": _maybe(rng, rng.choice([0.0, 0.5, 3.5, rng.uniform(0, 8)]), 0.3)}

    def test_round_trip_resolver_equals_old_formula(self):
        from masterquo import costs as C
        rng = random.Random(SEED + 10)
        for i in range(N):
            spec, ic = _sh_spec(rng), self._ic(rng)
            d = {"spread": _maybe(rng, rng.choice([0.0, 0.2, rng.uniform(0, 1.5)]))}
            comm = ic.get("commission_per_lot_side")
            cb = C.resolve(C.profile(C.SH, "XAUUSD"), spread=d.get("spread"), slippage=ic.get("slippage_usd"), commission_per_lot_side=comm,
                           money_per_price=spec.money_per_price(1.0) if comm is not None and spec.tick_value > 0 else None)
            self.assertEqual(_bits((cb.total, cb.commission_known, list(cb.warnings))), _bits(_old_sh_cost(d, ic, spec)), i)
            self.assertEqual(cb.spread, d.get("spread") or 0.0)                       # O7: the spread IS a cost line of SH

    def test_sizing_resolver_equals_old_formula(self):
        from masterquo import costs as C
        rng = random.Random(SEED + 11)
        for i in range(N):
            ic = self._ic(rng)
            setup = {"costs": _maybe(rng, {"round_trip_price": _maybe(rng, rng.choice([0.0, 0.3, rng.uniform(0, 2)]))}, 0.1)}
            mpp, sl_dist = rng.choice([100.0, 10.0, rng.uniform(0.5, 500)]), rng.uniform(0.1, 30)
            cost_price = float((setup.get("costs") or {}).get("round_trip_price") or 0.0)
            new = C.sizing_loss_per_lot(C.profile(C.SH), stop_distance=sl_dist, round_trip_price=cost_price, money_per_price=mpp,
                                        commission_per_lot_side=ic.get("commission_per_lot_side"))
            self.assertEqual(_bits(new), _bits(_old_sh_loss_per_lot(setup, ic, mpp, sl_dist)), i)

    def test_whole_setup_evaluate_old_vs_new(self):
        import copy

        import test_sh_setup as TS
        old = _old_module("backend/masterquo/sh/setup.py", "masterquo.sh._e4_old_setup")
        from masterquo.sh import setup as new
        rng = random.Random(SEED + 12)
        seen = set()
        for i in range(N):
            side, strat = rng.choice(["BUY", "SELL"]), rng.choice(["SCALPING", "HEDGING"])
            prof = copy.deepcopy(self.SC.profile(self.cfg, "XAUUSD", strat))
            prof["_instrument"] = dict(prof.get("_instrument") or {}, **self._ic(rng))
            prof["min_net_rr"] = rng.choice([prof["min_net_rr"], 0.5, 0.8, 0.9, 1.2])
            if rng.random() < 0.3:
                prof["be_rule"] = rng.choice(["ENTRY_PLUS_COSTS", "ENTRY"])
            snap = TS._snap(side)
            snap["data"] = dict(snap["data"], spread=rng.choice([0.0, 0.05, 0.2, 0.6, rng.uniform(0, 1.2)]))
            spec = _sh_spec(rng)
            kw = {"now": TS.NOW, "m1": TS._m1(side)}
            a = _outcome(old.evaluate, strat, "XAUUSD", copy.deepcopy(snap), spec, copy.deepcopy(prof), **kw)
            b = _outcome(new.evaluate, strat, "XAUUSD", copy.deepcopy(snap), spec, copy.deepcopy(prof), **kw)
            self.assertEqual(b, a, i)
            seen.add(a[0] if isinstance(a, tuple) else (a.get("status"), "costs" in a))
        self.assertIn(("READY", True), seen)                    # the cost step is reached and passed ...
        self.assertTrue({s for s in seen if s[0] == "NO_TRADE" and s[1]}, seen)   # ... and fails on net RR in some cases

    def test_whole_risk_evaluate_old_vs_new(self):
        import copy

        import test_sh_risk_state as TR
        old = _old_module("backend/masterquo/sh/risk.py", "masterquo.sh._e4_old_risk")
        from masterquo.sh import risk as new
        rng = random.Random(SEED + 13)
        statuses = set()
        for i in range(N):
            strat, side = rng.choice(["SCALPING", "HEDGING"]), rng.choice(["BUY", "SELL"])
            prof = copy.deepcopy(self.SC.profile(self.cfg, "XAUUSD", strat))
            prof["_instrument"] = dict(prof.get("_instrument") or {}, **self._ic(rng))
            sl = 2000.2 - rng.uniform(0.3, 8) if side == "BUY" else 2000.2 + rng.uniform(0.3, 8)
            setup = TR._setup(strat, side, sl=sl, costs=_maybe(rng, {"round_trip_price": _maybe(rng, rng.choice([0.0, 0.3, rng.uniform(0, 2)]))}, 0.1))
            spec = _sh_spec(rng)
            acc = dict(TR.ACC, equity=rng.choice([300.0, 2000.0, 10000.0, 80000.0]), margin_mode=rng.choice(["HEDGING", "NETTING"]))
            kw = {"setup": setup, "spec": spec, "prof": prof, "cfg": self.cfg, "inst": "XAUUSD", "account": acc, "state": {},
                  "exec_mode": rng.choice(["PAPER", "AUTO_DEMO", "SIGNALS"]), "now": TR.NOW, "quote": TR.Q}
            a = _outcome(old.evaluate, **copy.deepcopy(kw))
            b = _outcome(new.evaluate, **copy.deepcopy(kw))
            self.assertEqual(b, a, i)
            statuses.add(a.get("status") if isinstance(a, dict) else a[0])
        self.assertIn("PASS", statuses)


# ====================================================================================================================== SCALP
def _old_commission_price(com, contract_size, mpp):
    """scalp/service.commission_price at cf5d941 (verbatim)."""
    old = com / contract_size if contract_size > 0 else 0.0
    return max(old, com / mpp) if mpp else old


def _old_scalp_extras(com, contract_size, mpp, slippage_ticks, tick):
    """scalp/service.economics_gate at cf5d941: extra (account-currency conversion) and extra0 (the cost before 1.46 arch)."""
    extra = 2 * _old_commission_price(com, contract_size, mpp) + 2 * slippage_ticks * tick
    extra0 = 2 * com / contract_size + 2 * slippage_ticks * tick
    return extra, extra0


class TestScalp(unittest.TestCase):
    def _inputs(self, rng):
        com = rng.choice([0.0, -0.0, 3.5, 7.0, rng.uniform(0, 12)])
        cs = rng.choice([100.0, 1.0, 10.0, 100000.0, rng.uniform(0.5, 500)])
        mpp = rng.choice([None, 0.0, 50.0, 92.0, 100.0, 400.0, rng.uniform(0.1, 1000)])
        return com, cs, mpp, rng.choice([0, 0.0, 1, 2.0, rng.uniform(0, 10)]), rng.choice([0.01, 0.001, 0.1, 0.00001])

    def test_resolver_equals_old_formula(self):
        from masterquo import costs as C
        from masterquo.scalp import service as svc
        from masterquo.scalp import strategy as st
        rng = random.Random(SEED + 20)
        for i in range(N):
            com, cs, mpp, slip, tick = self._inputs(rng)
            self.assertEqual(_bits(svc.commission_price(com, cs, mpp)), _bits(_old_commission_price(com, cs, mpp)), i)
            self.assertEqual(_bits(C.commission_price_side(com, cs, mpp)), _bits(_old_commission_price(com, cs, mpp)), i)
            new = (st.cost_extra(com, cs, mpp, slip, tick), st.cost_extra(com, cs, mpp, slip, tick, pre_146=True))
            self.assertEqual(_bits(new), _bits(_old_scalp_extras(com, cs, mpp, slip, tick)), i)
        cb = C.resolve(C.profile(C.SCALP), commission_per_lot_side=None, contract_size=100.0, money_per_price=None, slippage=2, tick=0.01)
        self.assertEqual((cb.total, cb.commission_known), (2 * 2 * 0.01, False))       # unknown -> 0 in the cost, the gate blocks it

    def test_whole_economics_gate_old_vs_new(self):
        old = _old_module("backend/masterquo/scalp/service.py", "masterquo.scalp._e4_old_service")
        from masterquo.scalp import service as new
        from masterquo.scalp import strategy as st
        p = st.load_profile()
        rng = random.Random(SEED + 21)
        oks = set()
        for i in range(N):
            com, cs, mpp, slip, tick = self._inputs(rng)
            cs = cs or 100.0                                                        # the service calls the gate only with cs > 0
            side = rng.choice(["BUY", "SELL"])
            sgn = 1 if side == "BUY" else -1
            sl_d, t1 = rng.uniform(0.2, 6), rng.uniform(0.2, 8)
            plan = {"direction": side, "sl": round(2000 - sgn * sl_d, 2), "tp1": round(2000 + sgn * t1, 2),
                    "tp2": round(2000 + sgn * (t1 + rng.uniform(0, 6)), 2)}
            fill = round(2000 + sgn * rng.uniform(-sl_d - 0.5, t1 + 0.5), 2)
            sp = rng.choice([0.0, 0.05, 0.3, rng.uniform(0, 1)])
            a = _outcome(old.economics_gate, plan, fill, sp, com, cs, mpp, slip, tick, p)
            b = _outcome(new.economics_gate, plan, fill, sp, com, cs, mpp, slip, tick, p)
            self.assertEqual(b, a, i)
            oks.add(a[2] if isinstance(a, tuple) and len(a) == 4 else a)
        self.assertEqual(oks, {True, False})


# ====================================================================================================================== EVALUATION
def _old_eval_active_formula(comm, info, slippage_stress_points):
    """evaluation/service._active_cost at cf5d941 after the commission source (verbatim)."""
    tv, ts = float(info.get("trade_tick_value") or 0), float(info.get("trade_tick_size") or info.get("point") or 0)
    mpp = tv / ts if tv > 0 and ts > 0 else None
    slip = (slippage_stress_points or 0.0) * float(info.get("point") or 0.0) * 2
    c = slip + (2 * comm / mpp if comm is not None and mpp else 0.0)
    return c, comm is not None and mpp is not None


def _old_eval_sh_extra(costs):
    """evaluation/service._sh at cf5d941 (verbatim)."""
    extra = None
    if costs.get("round_trip_price") is not None:
        extra = max(0.0, float(costs["round_trip_price"]) - float(costs.get("spread") or 0.0))
    return extra


def _info(rng):
    out = {}
    for k, vals in (("trade_tick_value", [0, 0.0, 1.0, 0.1, rng.uniform(0.01, 10), "1.5", "n/a"]),
                    ("trade_tick_size", [0, 0.01, 0.001, rng.uniform(0.0001, 1)]), ("point", [0, 0.01, 0.001, 0.00001, "0.01"])):
        if rng.random() > 0.15:
            out[k] = rng.choice(vals)
    return out


class TestEvaluation(unittest.TestCase):
    def test_active_resolver_equals_old_formula(self):
        from masterquo import costs as C
        rng = random.Random(SEED + 30)
        for i in range(N):
            info = _info(rng)
            comm = _maybe(rng, rng.choice([0.0, 3.5, rng.uniform(0, 9)]), 0.3)
            pts = _maybe(rng, rng.choice([0.0, 20.0, rng.uniform(0, 50)]))
            a = _outcome(_old_eval_active_formula, comm, info, pts)

            def new(comm=comm, info=info, pts=pts):
                tv, ts = float(info.get("trade_tick_value") or 0), float(info.get("trade_tick_size") or info.get("point") or 0)
                mpp = tv / ts if tv > 0 and ts > 0 else None
                cb = C.resolve(C.profile(C.EVALUATION_ACTIVE), commission_per_lot_side=comm, money_per_price=mpp, slippage=pts,
                               point=float(info.get("point") or 0.0))
                return cb.total, cb.commission_known
            self.assertEqual(_outcome(new), a, i)

    def _fake(self, rng, cls):
        import threading
        deals = [{"symbol": "XAUUSD-", "type": rng.choice([0, 1]), "volume": 1.0, "entry": rng.choice([0, 1]),
                  "commission": -rng.choice([0.0, 3.5, 7.0]), "fee": 0.0} for _ in range(rng.randint(0, 8))]
        cfg = SimpleNamespace(costs=SimpleNamespace(commission_mode=rng.choice(["CONFIGURED", "FROM_DEAL_HISTORY", "UNKNOWN"]),
                                                    commission_per_lot_per_side=_maybe(rng, rng.choice([0.0, 3.5, rng.uniform(0, 9)]), 0.3),
                                                    slippage_stress_points=_maybe(rng, rng.choice([0.0, 20.0, rng.uniform(0, 50)]))),
                              mt5=SimpleNamespace(symbol="XAUUSD-"))
        fake = SimpleNamespace(cfg_store=SimpleNamespace(get=lambda: cfg), bridge=SimpleNamespace(_lock=threading.Lock(), deals=deals))
        return fake

    def test_whole_active_cost_old_vs_new(self):
        old = _old_module("backend/masterquo/evaluation/service.py", "masterquo.evaluation._e4_old_service")
        from masterquo.evaluation import service as new
        rng = random.Random(SEED + 31)
        known = set()
        for i in range(N):
            fake, info = self._fake(rng, None), _info(rng)
            a = _outcome(old.EvaluationService._active_cost, fake, info)
            self.assertEqual(_outcome(new.EvaluationService._active_cost, fake, info), a, i)
            known.add(a[1])
        self.assertEqual(known, {True, False, None})                 # known, unknown / unconvertible, and the failure branch

    def test_sh_extra_resolver_equals_old_formula(self):
        from masterquo import costs as C
        rng = random.Random(SEED + 32)
        for i in range(N):
            costs = {}
            if rng.random() > 0.2:
                costs["round_trip_price"] = rng.choice([None, 0.0, 0.3, rng.uniform(0, 2), 0.1])
            if rng.random() > 0.2:
                costs["spread"] = rng.choice([None, 0.0, 0.2, rng.uniform(0, 1.5)])
            a = _outcome(_old_eval_sh_extra, costs)
            b = _outcome(C.extra_from_round_trip, C.profile(C.EVALUATION_SH), costs.get("round_trip_price"), costs.get("spread"))
            self.assertEqual(b, a, i)

    def test_whole_sh_old_vs_new(self):
        import copy

        import test_sh_setup as TS
        old = _old_module("backend/masterquo/evaluation/service.py", "masterquo.evaluation._e4_old_service2")
        from masterquo.evaluation import service as new
        from masterquo.sh import config as SC
        from masterquo.sh import setup as SU
        td = TempData()
        try:
            cfg = SC.load()
            rng = random.Random(SEED + 33)
            ready = []
            for side in ("BUY", "SELL"):
                for strat in ("SCALPING", "HEDGING"):
                    r = SU.evaluate(strat, "XAUUSD", TS._snap(side), _sh_spec(random.Random(1)), SC.profile(cfg, "XAUUSD", strat), now=TS.NOW,
                                    m1=TS._m1(side))
                    if r["status"] == "READY":
                        ready.append(r)
            self.assertTrue(ready)
            extras = set()
            for i in range(N):
                su = copy.deepcopy(rng.choice(ready))
                su["costs"] = {k: v for k, v in (("round_trip_price", _maybe(rng, rng.uniform(0, 2))), ("spread", _maybe(rng, rng.uniform(0, 1.5))),
                                                  ("commission_known", rng.choice([True, False]))) if rng.random() > 0.1}
                got = []
                for mod in (old, new):
                    cap = []
                    fake = SimpleNamespace(_log=lambda c, prob, extra, cap=cap: cap.append((c.to_dict(), prob, extra)),
                                           _sh_n_cal=lambda inst, strat: None)
                    got.append((_outcome(mod.EvaluationService._sh, fake, copy.deepcopy(su), "XAUUSD", None, TS.NOW), _bits(cap)))
                self.assertEqual(got[1], got[0], i)
                self.assertEqual(len(got[0][1]), 1, got[0])                      # the candidate was logged with its extra cost
                extras.add(got[0][1][0][2] is None)
            self.assertEqual(extras, {True, False})
        finally:
            td.close()


# ====================================================================================================================== QUANT LABELS
def _old_label(cost, known, be):
    """quant/events.spec_from_candidate at cf5d941 (verbatim): be_offset_price and cost_price of the EventSpec."""
    return (float(cost or 0.0) if be else 0.0), (float(cost) if cost is not None and known is not False else None)


def _candidate(rng):
    eng = rng.choice(["ACTIVE", "SH_SCALPING", "SH_HEDGING", "SCALP_SHADOW"])
    side = rng.choice(["LONG", "SHORT"])
    sgn = 1 if side == "LONG" else -1
    e = round(rng.uniform(100, 3000), 2)
    tg = [{"price": e + sgn * rng.uniform(0.5, 9), "weight": 0.5}, {"price": e + sgn * rng.uniform(9, 20), "weight": 0.5}][:rng.choice([1, 2, 2])]
    if len(tg) == 1 and rng.random() < 0.8:
        tg[0]["weight"] = 1.0
    ec = {}
    if rng.random() > 0.1:
        ec["cost_price"] = rng.choice([None, 0, 0.0, 0.3, rng.uniform(0, 3), "0.25"])
    if rng.random() > 0.1:
        ec["commission_known"] = rng.choice([None, True, False])
    return {"engine": eng, "strategy_id": "S01", "instrument": rng.choice(["XAUUSD", None]), "symbol": "XAUUSD-", "direction": side,
            "entry_price": e, "stop_loss": e - sgn * rng.uniform(0.5, 10), "targets": tg, "horizon_s": 3600.0,
            "entry_type": rng.choice([None, "MARKET", "LIMIT_EDGE"]), "execution_context": ec}


class TestQuantLabels(unittest.TestCase):
    def test_resolver_equals_old_formula(self):
        from masterquo import costs as C
        rng = random.Random(SEED + 40)
        p = C.profile(C.QUANT_LABEL, "XAUUSD")
        for i in range(N):
            cost = rng.choice([None, 0, 0.0, -0.0, 0.3, rng.uniform(0, 3), "0.25"])
            known, be = rng.choice([None, True, False]), rng.choice([None, "TP2"])
            new = (C.be_offset(p, cost) if be else 0.0), C.label_cost(p, cost, known)
            self.assertEqual(_bits(new), _bits(_old_label(cost, known, be)), i)

    def test_whole_spec_from_candidate_old_vs_new(self):
        from dataclasses import asdict
        old = _old_module("backend/masterquo/quant/events.py", "masterquo.quant._e4_old_events")
        from masterquo.quant import events as new
        rng = random.Random(SEED + 41)
        labels = set()
        for i in range(N):
            c = _candidate(rng)
            kw = {"be_after": rng.choice([None, None, "TP1", "TP2"]), "ambiguity": rng.choice(["SL_FIRST", "BOUNDS"])}
            a = _outcome(lambda m=old, c=c, kw=kw: asdict(m.spec_from_candidate(c, **kw)))
            b = _outcome(lambda m=new, c=c, kw=kw: asdict(m.spec_from_candidate(c, **kw)))
            self.assertEqual(b, a, i)
            labels.add("EXC" if isinstance(a, tuple) else a["cost_price"] is None)
        self.assertLessEqual({True, False}, labels)                   # net labels with and without a known cost (EXC = same refusal)


if __name__ == "__main__":
    unittest.main()
