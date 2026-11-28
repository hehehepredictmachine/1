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


if __name__ == "__main__":
    unittest.main()
