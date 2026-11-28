"""1.46 arch, Etap 4 - import cycle analysis <-> strategies and dead code.

Part 1 (cycle): the indicator functions live in masterquo.indicators.series (I0076, strategies.indicators = shim of the SAME objects);
Etap 4 moves the bar view TFView byte for byte to masterquo.indicators.view (strategies.base.TFView = alias of the SAME class) and points
the remaining lower-layer users (zones.hlze, zones.market, markets.analysis) at the indicators package - four upward pairs fewer in the
layer guard (tools/cycles.py, tests/data/layer_baseline.json). Equality old <-> new: the original class body (embedded below verbatim)
against the moved class on seeded random bars. Nothing here changes a number, a decision or a record.
"""
from __future__ import annotations

import random
import sys
import unittest
from datetime import UTC, datetime, timedelta

from _env import ROOT

MQ = ROOT / "backend" / "masterquo"
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))


# ======================================================================================================== part 1: analysis <-> strategies
class _LegacyTFView:
    """strategies/base.py TFView as it was before the Etap 4 move (verbatim body; `ind` = the strategies.indicators shim)."""

    def __init__(self, tf: str, bars: list[dict]):
        self.tf = tf
        closed = [b for b in bars if b.get("closed") and b.get("open_utc")]
        self.t = [b["open_utc"] for b in closed]
        self.o = [float(b["o"]) for b in closed]
        self.h = [float(b["h"]) for b in closed]
        self.l = [float(b["l"]) for b in closed]
        self.c = [float(b["c"]) for b in closed]
        self.tv = [float(b.get("tv") or 0.0) for b in closed]     # broker tick count (CFD activity proxy, not exchange volume)
        fb = next((b for b in reversed(bars) if not b.get("closed")), None)
        self.forming = {"open_utc": fb["open_utc"], "o": float(fb["o"]), "h": float(fb["h"]), "l": float(fb["l"]), "c": float(fb["c"])} if fb else None
        self._cache: dict = {}

    def __len__(self) -> int:
        return len(self.c)

    @property
    def last(self) -> int:
        return len(self.c) - 1

    def get(self, key: str, fn):
        if key not in self._cache:
            self._cache[key] = fn()
        return self._cache[key]

    def atr(self, n: int = 14):
        from masterquo.strategies import indicators as ind
        return self.get(f"atr{n}", lambda: ind.atr(self.h, self.l, self.c, n))

    def ema(self, n: int):
        from masterquo.strategies import indicators as ind
        return self.get(f"ema{n}", lambda: ind.ema(self.c, n))

    def rsi(self, n: int = 14):
        from masterquo.strategies import indicators as ind
        return self.get(f"rsi{n}", lambda: ind.rsi(self.c, n))

    def macd_hist(self):
        from masterquo.strategies import indicators as ind
        return self.get("macdh", lambda: ind.macd_hist(self.c))

    def pivots(self, left: int = 3, right: int = 3):
        from masterquo.strategies import indicators as ind
        return self.get(f"piv{left}_{right}", lambda: ind.pivots(self.h, self.l, left, right))


def _bars(rnd: random.Random, n: int, forming: bool) -> list[dict]:
    t0 = datetime(2026, 1, 5, tzinfo=UTC)
    p = 2000 + rnd.random() * 500
    out = []
    for i in range(n):
        o = p
        c = o + rnd.gauss(0, 2.5)
        b = {"open_utc": (t0 + timedelta(minutes=5 * i)).isoformat(), "o": o, "h": max(o, c) + abs(rnd.gauss(0, 1.2)),
             "l": min(o, c) - abs(rnd.gauss(0, 1.2)), "c": c, "tv": rnd.randint(0, 300), "closed": True}
        if rnd.random() < 0.03:
            b.pop("tv")
        if rnd.random() < 0.01:
            b["open_utc"] = None                                  # skipped by the view (closed bar without a time)
        out.append(b)
        p = c
    if forming and out:
        out[-1]["closed"] = False
    return out


def _view_state(v) -> dict:
    def call(fn, *a):
        try:
            return fn(*a)
        except Exception as ex:  # noqa: BLE001 - the same exception type on both sides is part of the behaviour
            return ("EXC", type(ex).__name__)

    a, e = 7 + len(v) % 15, 9 + len(v) % 41
    out = {"tf": v.tf, "len": len(v), "last": v.last, "t": v.t, "o": v.o, "h": v.h, "l": v.l, "c": v.c, "tv": v.tv, "forming": v.forming,
           "atr": call(v.atr, a), "atr14": call(v.atr), "ema": call(v.ema, e), "rsi": call(v.rsi, 7), "rsi14": call(v.rsi),
           "macdh": call(v.macd_hist), "piv": call(v.pivots, 2, 5), "piv33": call(v.pivots)}
    out["cache"] = sorted(v._cache)
    out["cached_is_same"] = (v.atr(a) is v.atr(a)) if len(v) else None
    return out


class TestTFViewMovedToIndicators(unittest.TestCase):
    def test_alias_is_the_same_class(self):
        from masterquo.indicators import view
        from masterquo.strategies import adapter, base, common, regime
        self.assertIs(base.TFView, view.TFView)
        self.assertIs(common.TFView, view.TFView)
        self.assertIs(regime.TFView, view.TFView)
        self.assertIs(adapter.TFView, view.TFView)
        self.assertEqual(view.TFView.__module__, "masterquo.indicators.view")
        self.assertIs(view.ind, __import__("masterquo.indicators.series", fromlist=["x"]))

    def test_moved_class_equals_the_original_on_random_bars(self):
        from masterquo.indicators.view import TFView
        rnd = random.Random(20261128)
        n_cases = 0
        for _ in range(240):
            bars = _bars(rnd, rnd.choice((0, 1, 2, 5, 20, 35, 60, 150, 320)), forming=rnd.random() < 0.6)
            tf = rnd.choice(("M5", "M15", "H1", "D1"))
            self.assertEqual(_view_state(TFView(tf, bars)), _view_state(_LegacyTFView(tf, bars)))
            n_cases += 1
        self.assertGreaterEqual(n_cases, 200)

    def test_mirrored_and_adapter_views_unchanged(self):
        """MarketView paths that build TFView objects (adapter.build_view, base._mirror_tf) give the legacy values."""
        from masterquo.strategies import base
        rnd = random.Random(7)
        for _ in range(30):
            bars = _bars(rnd, rnd.choice((40, 120)), forming=True)
            v = base.TFView("M5", bars)
            m = base._mirror_tf(v, 2 * 2100.0)
            self.assertIs(type(m), base.TFView)
            legacy = _LegacyTFView("M5", [{"open_utc": t, "o": 4200.0 - o, "h": 4200.0 - lo, "l": 4200.0 - h, "c": 4200.0 - c, "tv": tv,
                                           "closed": True} for t, o, h, lo, c, tv in zip(v.t, v.o, v.h, v.l, v.c, v.tv)])
            self.assertEqual([m.c, m.h, m.l, m.atr(), m.ema(20), m.pivots()], [legacy.c, legacy.h, legacy.l, legacy.atr(), legacy.ema(20),
                                                                                legacy.pivots()])


class TestLowerLayersDoNotImportStrategies(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib

        import cycles
        cls.C = importlib.reload(cycles)
        cls.edges = cls.C.edges()

    def test_zones_and_markets_use_the_indicator_package(self):
        from masterquo.indicators import series
        from masterquo.markets import analysis as MA
        from masterquo.strategies import indicators as shim
        from masterquo.zones import hlze, market
        for m in (hlze, market, MA):
            self.assertIs(m.ind, series, m.__name__)
            for n in series.__all__:
                self.assertIs(getattr(m.ind, n), getattr(shim, n), (m.__name__, n))

    def test_no_l0_l2_module_imports_strategy_indicators_or_view(self):
        bad = [e for e in self.edges if self.C.LAYERS.get(self.C.component(e["src"]), 9) <= 2
               and e["dst"] in ("masterquo.strategies.indicators", "masterquo.strategies.base")]
        self.assertEqual(bad, [])

    def test_analysis_package_has_no_strategies_import_of_any_kind(self):
        bad = [e for e in self.edges if self.C.component(e["src"]) == "analysis" and self.C.component(e["dst"]) == "strategies"]
        self.assertEqual(bad, [])                                # module level, in functions and dynamic

    def test_no_module_level_package_cycle_analysis_strategies(self):
        import collections
        g = collections.defaultdict(set)
        for e in self.edges:
            a, b = self.C.component(e["src"]), self.C.component(e["dst"])
            if e["kind"] == "MODULE" and a != b:
                g[a].add(b)

        def reach(s):
            seen, st = {s}, [s]
            while st:
                for y in g[st.pop()]:
                    if y not in seen:
                        seen.add(y)
                        st.append(y)
            return seen
        self.assertFalse("strategies" in reach("analysis") and "analysis" in reach("strategies"))

    def test_upward_pairs_removed_from_the_guard(self):
        up = self.C.upward(self.edges)
        gone = ("masterquo.zones.hlze -> masterquo.strategies.indicators", "masterquo.zones.hlze -> masterquo.strategies.base",
                "masterquo.zones.market -> masterquo.strategies.indicators", "masterquo.markets.analysis -> masterquo.strategies.indicators")
        for k in gone:
            self.assertNotIn(k, up)
            self.assertNotIn(k, self.C.load_baseline())
        self.assertLessEqual(len(up), 60)                        # 63 before Etap 4 (cf5d941): -4 pairs, +1 L1 -> L2 (markets -> indicators)
        self.assertEqual(self.C.compare(up, self.C.load_baseline())[0], [])


if __name__ == "__main__":
    unittest.main()
