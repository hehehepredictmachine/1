"""1.46 arch, Etap 4 - import cycle analysis <-> strategies and dead code.

Part 1 (cycle): the indicator functions live in masterquo.indicators.series (I0076, strategies.indicators = shim of the SAME objects);
Etap 4 moves the bar view TFView byte for byte to masterquo.indicators.view (strategies.base.TFView = alias of the SAME class) and points
the remaining lower-layer users (zones.hlze, zones.market, markets.analysis) at the indicators package - four upward pairs fewer in the
layer guard (tools/cycles.py, tests/data/layer_baseline.json). Equality old <-> new: the original class body (embedded below verbatim)
against the moved class on seeded random bars. Nothing here changes a number, a decision or a record.

Part 2 (dead code, ETAP1 martwy_kod_konfig #5 / #7): the waves already removed the retired OTC code (I0112) and the confirmed dead
functions (I0114). Etap 4 re-confirms both and adds the CI step the diagnosis asked for: an AST scan of every function / method / class
defined in backend/ and tools/ against the identifier tokens of backend, tests, tools, frontend, desktop, mql5, config and the launchers
(.bat / .cmd). A definition whose name occurs nowhere but in its own definition fails the test - unless the framework calls it (route
decorators, pydantic validators, ast.NodeVisitor visit_*), it is reached by the two getattr dispatchers (agent Toolbox t_*, mm jobs job_*)
or it is on the reasoned allowlist below. API endpoints are never removed (public contract) - the route decorators exempt them.
"""
from __future__ import annotations

import ast
import collections
import functools
import json
import random
import re
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

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


# ======================================================================================================== part 2: dead code (backend / tools)
CORPUS_DIRS = ("backend", "tests", "tools", "frontend/src", "desktop", "mql5", "config", "frog_wizard_bot")
CORPUS_EXTS = (".py", ".ts", ".tsx", ".js", ".mjs", ".bat", ".cmd", ".go", ".json", ".mq5", ".mqh", ".html", ".ps1")
SKIP_PARTS = {"vendor", "node_modules", "__pycache__", "dist", "tests_data"}
DEF_DIRS = ("backend", "tools")
# framework-called definitions: decorator call name (last attribute) -> registered by the framework, not by a call in the code
FRAMEWORK_DECORATORS = {"get", "post", "put", "delete", "patch", "websocket", "middleware", "on_event", "exception_handler", "route",
                        "api_route", "field_validator", "model_validator", "validator", "root_validator"}
# getattr dispatchers: (defining file, name prefix) - agent/tools.py: getattr(self, "t_" + name); mm/orchestrator.py and modelhub/smoke/mm.py:
# getattr(jobs, "job_" + jid)
DISPATCH = {("backend/masterquo/agent/tools.py", "t_"), ("backend/masterquo/mm/jobs.py", "job_")}
# kept on purpose (n = 1 in the corpus, reason given); key = "<file>::<qualified name>"
ALLOW = {
    "backend/kronos_runtime/install.py::_redirect_host._NoRedirect.redirect_request":
        "nadpisanie urllib.request.HTTPRedirectHandler.redirect_request - woła je biblioteka standardowa",
    "backend/masterquo/quant/units.py::InstrumentSpec.quantize_price":
        "I0053/I0115: quant/units = biblioteka badawcza (PRODUCTION_API = binary_ev), część nieprodukcyjna zostaje świadomie",
}
_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _skipped(p: Path) -> bool:
    return bool(SKIP_PARTS & set(p.parts))


@functools.lru_cache(maxsize=4)
def corpus_counts(root: Path = ROOT) -> collections.Counter:
    """Identifier tokens of the corpus. This file is left out: its allowlist / removed-name lists must not count as references."""
    files = [p for d in CORPUS_DIRS for p in (root / d).rglob("*") if p.suffix in CORPUS_EXTS and p.is_file() and not _skipped(p)
             and p.name != Path(__file__).name]
    files += [p for p in root.iterdir() if p.suffix in (".bat", ".cmd")]
    files += list((root / "frontend").glob("*.html"))
    counts: collections.Counter = collections.Counter()
    for p in files:
        try:
            s = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(s) <= 5_000_000:
            counts.update(_TOKEN.findall(s))
    return counts


@functools.lru_cache(maxsize=4)
def definitions(root: Path = ROOT) -> list[tuple[str, int, str, str, list]]:
    """(file, line, name, qualified name, decorator call names) of every function / method / class in backend/ and tools/."""
    out = []

    class V(ast.NodeVisitor):
        def __init__(self, rel):
            self.rel, self.stack = rel, []

        def _def(self, node):
            decs = []
            for d in getattr(node, "decorator_list", []):
                f = d.func if isinstance(d, ast.Call) else d
                decs.append(f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else ""))
            out.append((self.rel, node.lineno, node.name, ".".join([*self.stack, node.name]), decs))
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _def

    for d in DEF_DIRS:
        for p in sorted((root / d).rglob("*.py")):
            if _skipped(p):
                continue
            V(p.relative_to(root).as_posix()).visit(ast.parse(p.read_text(encoding="utf-8"), filename=str(p)))
    return out


def dead_definitions(root: Path = ROOT) -> list[str]:
    counts = corpus_counts(root)
    defs = definitions(root)
    n_defs = collections.Counter(d[2] for d in defs)
    out = []
    for rel, line, name, qual, decs in defs:
        if (name.startswith("__") and name.endswith("__")) or name.startswith("test") \
                or name in ("setUp", "tearDown", "setUpClass", "tearDownClass", "main"):
            continue
        if counts[name] > n_defs[name]:
            continue                                             # referenced somewhere besides its definition(s)
        if FRAMEWORK_DECORATORS & set(decs) or name.startswith("visit_") or name == "generic_visit":
            continue
        if any(rel == f and name.startswith(pre) for f, pre in DISPATCH):
            continue
        if f"{rel}::{qual}" in ALLOW:
            continue
        out.append(f"{rel}:{line} {qual}")
    return sorted(out)


class TestNoDeadDefinitions(unittest.TestCase):
    """martwy_kod_konfig#7 (I0114) - the CI step: no function / method / class without a static or dynamic reference."""

    def test_backend_and_tools_have_no_unreferenced_definitions(self):
        dead = dead_definitions()
        self.assertEqual(dead, [], "martwe definicje (nazwa występuje tylko w definicji): usuń je albo dopisz do ALLOW z powodem\n"
                         + "\n".join(dead))

    def test_scan_sees_a_planted_dead_function(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="mq_t_dead_"))
        try:
            (tmp / "backend").mkdir()
            (tmp / "backend" / "m.py").write_text(
                "def used():\n    return 1\n\n\ndef zz_orphan_helper():\n    return used()\n\n\n"
                "@app.get('/x')\ndef zz_route():\n    return 2\n", encoding="utf-8")
            self.assertEqual(dead_definitions(tmp), ["backend/m.py:5 zz_orphan_helper"])
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_allowlist_entries_still_exist(self):
        quals = {f"{d[0]}::{d[3]}" for d in definitions()}
        self.assertEqual(sorted(set(ALLOW) - quals), [])         # a stale allowlist entry hides nothing - drop it

    def test_etap4_removed_and_kept(self):
        from masterquo import procs
        from masterquo.modelhub.smoke import kronos_tsfm
        self.assertFalse(hasattr(procs.ProcessRegistry, "unregister"))     # Etap 4: no caller (register() drops finished children)
        self.assertFalse(hasattr(kronos_tsfm, "_exc"))                     # Etap 4: unused helper of the smoke
        reg = procs.ProcessRegistry()
        self.assertEqual(reg.running(), {})
        self.assertTrue(callable(reg.register) and callable(reg.stop_all) and callable(reg.stop))

    def test_i0114_list_reconfirmed(self):
        """The ETAP1 #7 list once more: the removed names are not referenced by any code (AST of backend / tools, tokens of frontend /
        desktop / mql5 / launchers); every kept name has a reference besides its definition."""
        removed = ("year_fraction", "register_context", "make_fake_module", "_kid", "simple_returns", "ewma_vol", "to_decimal",
                   "sqrt_time", "logsumexp")
        code_names: collections.Counter = collections.Counter()
        for d in DEF_DIRS:
            for p in (ROOT / d).rglob("*.py"):
                if _skipped(p):
                    continue
                for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                    if isinstance(n, ast.Name):
                        code_names[n.id] += 1
                    elif isinstance(n, ast.Attribute):
                        code_names[n.attr] += 1
                    elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        code_names[n.name] += 1
                    elif isinstance(n, ast.alias):
                        code_names[n.name.rsplit(".", 1)[-1]] += 1
        other = collections.Counter()
        for d in ("frontend/src", "desktop", "mql5"):
            for p in (ROOT / d).rglob("*"):
                if p.is_file() and p.suffix in CORPUS_EXTS and not _skipped(p):
                    other.update(_TOKEN.findall(p.read_text(encoding="utf-8", errors="replace")))
        for p in ROOT.iterdir():
            if p.suffix in (".bat", ".cmd"):
                other.update(_TOKEN.findall(p.read_text(encoding="utf-8", errors="replace")))
        self.assertEqual({n: (code_names[n], other[n]) for n in removed if code_names[n] or other[n]}, {})
        counts = corpus_counts()
        for kept in ("state_hash", "brute_force", "export_train", "history_orders_get", "stops_level_ok", "rollback_config"):
            self.assertGreater(counts[kept], 1, kept)


class TestRetiredOtcCodeReconfirmed(unittest.TestCase):
    """martwy_kod_konfig#5 (I0112): the retired OTC code is gone, the historical labels and the API contract stay."""

    def test_no_otc_planner_code(self):
        from masterquo.baskets import catalog as CAT
        from masterquo.baskets import hedge as HG
        self.assertEqual(sorted(p for p in HG.PLANNERS if p.startswith("otc_")), [])
        self.assertLessEqual(set(HG.PLANNERS), {s["family_id"] for s in CAT.CATALOG})
        names = {n.name for f in (MQ / "baskets").glob("*.py") for n in ast.walk(ast.parse(f.read_text(encoding="utf-8")))
                 if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        self.assertEqual(sorted(n for n in names if n.startswith(("otc_", "_otc")) or n in ("OTCFeed", "b_star")), [])
        self.assertFalse((MQ / "baskets" / "otc.py").exists() or (MQ / "baskets" / "payoff.py").exists())

    def test_historical_labels_and_endpoints_kept(self):
        from masterquo.baskets import catalog as CAT
        otc = {k: v for k, v in CAT.HISTORICAL_STRATEGIES.items() if k.startswith("OTC_HEDGE_")}
        self.assertEqual(len(otc), 10)
        self.assertIn("otc_basket", {v["family_id"] for v in otc.values()})
        self.assertTrue(all(CAT.retired_reason(k) for k in otc))
        self.assertTrue(all(v["runtime_status"] == "RETIRED" for v in otc.values()))
        inv = json.loads((ROOT / "docs" / "arch146" / "routes_inventory.json").read_text(encoding="utf-8"))
        paths = {(r["method"], r["path"]) for r in inv["routes"]}
        for k in (("GET", "/api/v1/baskets/otc"), ("PUT", "/api/v1/baskets/otc/meta"), ("POST", "/api/v1/baskets/otc/ticks"),
                  ("POST", "/api/v1/baskets/otc/payoff")):
            self.assertIn(k, paths)                              # public contract: answered 410 / RETIRED, never removed


if __name__ == "__main__":
    unittest.main()
