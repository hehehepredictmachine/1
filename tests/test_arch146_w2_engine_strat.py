"""1.46 arch, wave 2 - group engine_strat: agent context freshness, MICROSTRUCTURE live book, volzones usage, DXY data time, frozen agent
view (neutral variant), indicators/series move, strategy ids leaf, dead code / lint, risk reporting and the tightening-only risk fixes,
symbol autodetection veto. Unit level only: fakes instead of the terminal / HTTP server, no order is ever sent."""
from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from _env import ROOT, TempData

MQ = ROOT / "backend" / "masterquo"


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, UTC).isoformat()


# ---------------------------------------------------------------------------------------------------------------- I0186
class _Ind:
    def __init__(self, snap, fresh=None, exc=None):
        self.snap, self.fresh, self.exc = snap, fresh, exc

    def current(self):
        return self.snap

    def freshness(self, s):
        if self.exc:
            raise self.exc
        return self.fresh


def _old_snapshot():
    as_of = _iso(time.time() - 2 * 86400)
    return {"version": "PMW-IND-SERVICE-1", "as_of": as_of, "snapshot_id": "INDS-x",
            "dxy": {"status": "READY", "reason": None, "values": {"corr_72": -0.4}, "data_time": as_of},
            "semivar": {"status": "READY", "values": {"rv_20": 0.1}}, "spread": {"status": "ERROR", "reason": "BOOM", "values": {}},
            "profile": {"status": "NO_DATA", "reason": "brak", "values": {}}, "microstructure": {"status": "READY", "values": {}},
            "avwap": {"M1": {"SESSION": {"status": "READY", "values": {"avwap": 1.0}}, "MANUAL": [{"status": "READY", "values": {}}]}}}


class TestI0186AgentSnapshotFreshness(unittest.TestCase):
    def _ctx(self, ind):
        from masterquo.engine.service import EngineService
        return EngineService._pmw_indicators(SimpleNamespace(indicators_provider=ind))

    def test_stale_snapshot_marked_for_agent(self):
        from masterquo.agent import tools as AT
        snap = _old_snapshot()
        frozen = json.dumps(snap, sort_keys=True)
        ctx_snap = self._ctx(_Ind(snap, ("STALE", "SNAPSHOT_AGE_172800S", 172800.0)))
        self.assertEqual(json.dumps(snap, sort_keys=True), frozen)                  # the stored snapshot is never mutated
        self.assertEqual((ctx_snap["snapshot_status"], ctx_snap["snapshot_status_reason"]), ("STALE", "SNAPSHOT_AGE_172800S"))
        tb = AT.Toolbox({"pmw_indicators": ctx_snap}, 5)
        d = json.loads(tb.run("get_dxy_relation", {})[0])
        self.assertEqual(d["status"], "STALE")                                       # 1.46: READY for data two days old
        self.assertEqual(d["values"], {"corr_72": -0.4})                             # values stay
        self.assertEqual(d["snapshot_status"], "STALE")
        p = json.loads(tb.run("get_pmw_indicators", {})[0])
        self.assertEqual(p["snapshot_status"], "STALE")
        self.assertEqual(p["semivar"]["status"], "STALE")
        self.assertEqual(p["spread"]["status"], "ERROR")                             # never softened
        self.assertEqual(p["profile"]["status"], "NO_DATA")
        self.assertEqual(p["avwap"]["M1"]["SESSION"]["status"], "STALE")
        self.assertEqual(p["avwap"]["M1"]["MANUAL"][0]["status"], "STALE")
        self.assertEqual(snap["semivar"]["status"], "READY")                         # frozen context untouched by the tools

    def test_ready_snapshot_unchanged_and_failures(self):
        from masterquo.agent import tools as AT
        snap = _old_snapshot()
        ok = self._ctx(_Ind(snap, ("READY", None, 5.0)))
        p = json.loads(AT.Toolbox({"pmw_indicators": ok}, 5).run("get_pmw_indicators", {})[0])
        self.assertEqual(p["semivar"]["status"], "READY")
        bad = self._ctx(_Ind(snap, exc=RuntimeError("x")))                           # freshness() failure: snapshot kept, STALE
        self.assertEqual((bad["snapshot_status"], bad["snapshot_status_reason"]), ("STALE", "FRESHNESS_ERROR"))
        self.assertIsNone(self._ctx(_Ind(None)))                                     # no snapshot -> None as before
        dis = self._ctx(_Ind(snap, ("DISABLED", "indicators.enabled=false", 1.0)))
        p = json.loads(AT.Toolbox({"pmw_indicators": dis}, 5).run("get_pmw_indicators", {})[0])
        self.assertEqual(p["spread"]["status"], "DISABLED")                         # DISABLED marks every component (compact rule)


# ---------------------------------------------------------------------------------------------------------------- I0191 / I0192
def _book(t, bid=2000.0, ask=2000.3, qb=5.0, qa=1.0):
    return {"t": t, "bids": [(bid, qb), (bid - 0.1, 3.0)], "asks": [(ask, qa), (ask + 0.1, 3.0)]}


def _measure(book, now=None):
    from masterquo.indicators import ofi as OF
    acc = OF.OFIAccumulator()
    acc.add(book)
    return OF.compute(book, acc, instrument="XAUUSD", broker_symbol="XAUUSD-", status="READY", now=now if now is not None else book["t"])


class _IndMicro:
    def __init__(self, snap_micro, now_micro=None, has_now=True):
        self.snap_micro, self.now_micro = snap_micro, now_micro
        if not has_now:
            self.microstructure_now = None

    def current(self):
        return {"microstructure": self.snap_micro}

    def microstructure_now(self):
        return self.now_micro


class TestI0191MicroLiveBook(unittest.TestCase):
    def setUp(self):
        self.data = TempData()                                                       # isolated config.json (ConfigStore.update persists)
        self.td = tempfile.mkdtemp(prefix="w2es_")
        from masterquo.modelhub.families import base as B
        self.store = B.Store(Path(self.td))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.td, ignore_errors=True)
        self.data.close()

    def svc(self, ind, upd=None):
        from masterquo.config import ConfigStore
        from masterquo.modelhub.families.service import FamilyService
        cs = ConfigStore()
        if upd:
            cs.update(upd)
        br = SimpleNamespace(quote={"bid": 2000.0, "ask": 2000.5}, bars=lambda *a, **k: [])
        return FamilyService(cs, br, indicators=ind, store=self.store)

    def test_live_uses_current_book_with_short_ttl(self):
        from masterquo.quant import checks as QC
        now = time.time()
        old = _measure(_book(now - 50, qb=1.0, qa=5.0))                            # snapshot of the last closed M1 (50 s old)
        fresh = _measure(_book(now - 1, qb=5.0, qa=1.0), now=now)
        p = self.svc(_IndMicro(old, fresh)).predict("MICROSTRUCTURE", "XAUUSD")
        self.assertEqual(p["state"], "READY", p.get("unavailable_reason"))
        self.assertAlmostEqual(p["result"]["best_imbalance"], fresh["values"]["best_imbalance"])   # 1.46: the 50 s old book
        self.assertEqual(QC.ts(p["data_time"]), QC.ts(fresh["data_time"]))
        self.assertLessEqual(p["ttl_s"], 25.0)
        self.assertTrue(QC.check(p, now=now)["eligible"])
        later = QC.check(p, now=QC.ts(p["data_time"]) + 60)                           # 1.46: eligible up to 900 s
        self.assertFalse(later["eligible"])
        self.assertTrue(later["reason"].startswith("STALE"))

    def test_stale_current_book_blocks(self):
        now = time.time()
        old = _measure(_book(now - 30))                                              # READY at its refresh
        fresh = _measure(_book(now - 30), now=now)                                   # the book stopped 30 s ago -> STALE now
        p = self.svc(_IndMicro(old, fresh)).predict("MICROSTRUCTURE", "XAUUSD")
        self.assertNotEqual(p["state"], "READY")

    def test_tightening_guard_keeps_todays_blocks(self):
        """A fresher book never lifts a block of the snapshot-based record (REQUIRED MICROSTRUCTURE): snapshot not READY or older than
        the REQUIRED age limit -> not READY, like the record of 1.46."""
        from masterquo.decision.coordinator import evaluate_models
        now = time.time()
        fresh = _measure(_book(now - 1), now=now)
        nod = {"status": "NO_DATA", "reason": "Brak danych arkusza", "values": {}}
        p = self.svc(_IndMicro(nod, fresh)).predict("MICROSTRUCTURE", "XAUUSD")
        self.assertEqual((p["state"], p["unavailable_reason"]), ("BLOCKED_DATA", "Brak danych arkusza"))   # as 1.46
        self.svc(_IndMicro(nod, fresh)).invalidate()
        old = _measure(_book(now - 50))
        s = self.svc(_IndMicro(old, fresh), {"decision": {"required_max_age_s": 30}})
        p = s.predict("MICROSTRUCTURE", "XAUUSD")
        self.assertEqual(p["state"], "STALE")
        # 1.46 record: READY with the snapshot data_time (50 s) -> REQUIRED blocks (age > 30); after: STALE -> blocks as well
        today = dict(p, state="READY", data_time=old["data_time"], result={"best_imbalance": 0.1})
        for rec in (today, p):
            _, reasons = evaluate_models([dict(rec, family="MICROSTRUCTURE")], "BUY", required={"MICROSTRUCTURE"}, assist_threshold=0.6,
                                         max_age_s=30, now=now)
            self.assertTrue(any(r.startswith("MODEL_REQUIRED_") for r in reasons), reasons)

    def test_without_microstructure_now_the_snapshot_is_used(self):
        now = time.time()
        snap = _measure(_book(now - 2))
        p = self.svc(_IndMicro(snap, has_now=False)).predict("MICROSTRUCTURE", "XAUUSD")
        self.assertEqual(p["state"], "READY")
        self.assertAlmostEqual(p["result"]["best_imbalance"], snap["values"]["best_imbalance"])

    def test_indicator_service_microstructure_now(self):
        from masterquo.config import ConfigStore
        from masterquo.indicators import ofi as OF
        from masterquo.indicators.service import IndicatorService
        now = time.time()
        s = IndicatorService.__new__(IndicatorService)
        s.cfg_store, s.bridge, s.clock, s._lock = ConfigStore(), SimpleNamespace(symbol_info={}), (lambda: now), threading.RLock()
        s.book = SimpleNamespace(last=_book(now - 1), status="READY", reason=None)
        s.ofi = OF.OFIAccumulator()
        r = s.microstructure_now()
        if not s._cfg().book_enabled:
            self.assertIsNone(r)
            return
        self.assertEqual(r["status"], "READY")
        self.assertAlmostEqual(r["values"]["book_spread"], 0.3)


class TestI0192BookSpread(unittest.TestCase):
    def test_ofi_compute_reports_book_spread(self):
        r = _measure(_book(1000.0, bid=1999.9, ask=2000.2))
        self.assertAlmostEqual(r["values"]["book_spread"], 0.3)
        self.assertEqual(r["units"]["book_spread"], "price")

    def test_microprice_normalised_by_book_spread(self):
        import numpy as np
        from masterquo.modelhub.families import micro as MI
        f = MI.Micro()
        art = {"coef": [[0.5, -0.2, 0.01, 3.0], [0.0, 0.0, 0.0, 0.0], [-0.5, 0.2, -0.01, -3.0]], "intercept": [0.0, 0.1, 0.0],
               "classes": [0, 1, 2], "ofi_window_s": MI.live_ofi_window_s()}
        vals = {"best_imbalance": 0.4, "depth_imbalance": 0.1, "ofi_window": 2.0, "microprice_dev": 0.06, "mid": 2000.0, "bid_levels": 5,
                "book_spread": 0.30}
        live = {"micro": {"status": "READY", "values": vals, "ofi_state": {"window_s": MI.live_ofi_window_s()}}, "spread": 0.50}
        m = f.predict(art, live)
        want = MI.Micro._proba(art, np.asarray([[0.4, 0.1, 2.0, 0.06 / 0.30]]))[0]
        self.assertAlmostEqual(m["p_up_10s"], float(want[2]), places=12)              # 1.46: dev / 0.50 (quote spread)
        old = MI.Micro._proba(art, np.asarray([[0.4, 0.1, 2.0, 0.06 / 0.50]]))[0]
        self.assertNotAlmostEqual(m["p_up_10s"], float(old[2]), places=6)
        B = MI.B
        with self.assertRaises(B.Unavailable):                                       # no book spread -> not served
            f.predict(art, dict(live, micro=dict(live["micro"], values={k: v for k, v in vals.items() if k != "book_spread"})))
        with self.assertRaises(B.Unavailable):                                       # no quote -> blocked as in 1.46 (tightening only)
            f.predict(art, {"micro": live["micro"]})


# ---------------------------------------------------------------------------------------------------------------- I0602
def _d1(n=40):
    import math
    out, c = [], 2000.0
    for i in range(n):
        o = c
        c = c * math.exp(0.01 * math.sin(i))
        out.append({"open_utc": f"2026-0{1 + i // 28}-{1 + i % 28:02d}T00:00:00Z", "o": o, "h": max(o, c) + 3, "l": min(o, c) - 3, "c": c,
                    "closed": i < n - 1})
    return out


class TestI0602VolzonesUsage(unittest.TestCase):
    def test_usage_in_every_branch_and_numbers_untouched(self):
        from masterquo.config import VolatilityConfig
        from masterquo.engine import volzones
        cfg = VolatilityConfig()
        ok = volzones.compute(_d1(), cfg, digits=2)
        self.assertEqual(ok["status"], "OK")
        self.assertEqual(ok["usage"], "PANEL_REFERENCE")                             # 1.46: no field
        self.assertIn("S12", ok["strategy_walls_note"])
        self.assertEqual(volzones.MODEL_VERSION, "MQ-VOLZONES-1.0.0")
        self.assertEqual(volzones.compute(_d1(5), cfg)["usage"], "PANEL_REFERENCE")  # INSUFFICIENT_HISTORY
        self.assertEqual(volzones.compute(_d1(), VolatilityConfig(enabled=False))["usage"], "PANEL_REFERENCE")
        # the agent tool keeps its fixed whitelist (no new keys in the agent context)
        from masterquo.agent import tools as AT
        v = AT.Toolbox({"volatility": ok}, 3).t_get_volatility_levels()
        self.assertNotIn("usage", v)


# ---------------------------------------------------------------------------------------------------------------- I0613 (neutral part)
class TestI0613DxyDataTimeInCompact(unittest.TestCase):
    def test_compact_dxy_carries_its_own_data_time(self):
        from masterquo.indicators.service import IndicatorService
        s = {"as_of": "2026-11-24T10:00:00+00:00", "dxy": {"status": "READY", "values": {"corr_72": -0.3},
                                                          "data_time": "2026-11-24T05:00:00+00:00", "available_at": "2026-11-24T06:00:00+00:00"}}
        c = IndicatorService._compact(s)
        self.assertEqual(c["dxy"]["data_time"], "2026-11-24T05:00:00+00:00")
        self.assertEqual(c["dxy"]["available_at"], "2026-11-24T06:00:00+00:00")
        self.assertEqual(c["dxy"]["corr_72"], -0.3)
        self.assertIsNone(IndicatorService._compact({"as_of": "x"})["dxy"])


# ---------------------------------------------------------------------------------------------------------------- I0756 (neutral variant)
def _st(as_of, walls_id):
    return {"status": "OK", "tf": "M5", "as_of": as_of, "walls": {"status": "OK", "snapshot_id": walls_id}, "sr": {"zones": [], "by_tf": {}},
            "range": {"status": "OK"}, "range_zones": {"status": "OK"}, "chart": {"patterns": []}, "candles": {"evidence": []}}


class TestI0756FrozenViewNothingWithheld(unittest.TestCase):
    def test_walls_frozen_view_plus_labelled_newer_scan(self):
        from masterquo.agent import tools as AT
        ctx = {"as_of": "2026-11-24T10:00:00+00:00", "structure_fn": lambda tf: _st("2026-11-24T10:02:00+00:00", "WS-NEW"),
               "structure_as_of_fn": lambda tf: _st("2026-11-24T10:00:00+00:00", "WS-OLD")}
        out = AT.Toolbox(ctx, 3).t_get_walls_and_patterns("M5")
        self.assertEqual((out["view"], out["view_as_of"]), ("AS_OF_EVALUATION", "2026-11-24T10:00:00+00:00"))
        self.assertEqual(out["walls"]["snapshot_id"], "WS-OLD")                     # 1.46: the latest scan only
        self.assertTrue(out["NEWER_DATA_AVAILABLE"])
        self.assertEqual(out["after_as_of"]["walls"]["snapshot_id"], "WS-NEW")       # the newest state is still shown
        same = AT.Toolbox(dict(ctx, structure_fn=ctx["structure_as_of_fn"]), 3).t_get_walls_and_patterns("M5")
        self.assertFalse(same["NEWER_DATA_AVAILABLE"])
        self.assertNotIn("after_as_of", same)
        legacy = AT.Toolbox({"structure_fn": ctx["structure_fn"]}, 3).t_get_walls_and_patterns("M5")   # an old context: as before
        self.assertEqual(legacy["walls"]["snapshot_id"], "WS-NEW")
        unsup = AT.Toolbox(dict(ctx, structure_fn=lambda tf: {"status": "UNSUPPORTED_ASSET"}), 3).t_get_walls_and_patterns("M5")
        self.assertEqual(unsup["after_as_of"]["status"], "UNSUPPORTED_ASSET")

    def test_structure_intelligence_latest_is_the_evaluation_one_plus_newer(self):
        from masterquo.agent import tools as AT
        snaps = {"SIS-A": {"snapshot_id": "SIS-A", "as_of": "2026-11-24T10:00:00+00:00", "cells": {}},
                 "SIS-B": {"snapshot_id": "SIS-B", "as_of": "2026-11-24T10:05:00+00:00", "cells": {}}}
        fn = lambda sid: snaps["SIS-B"] if sid == "latest" else snaps.get(sid)
        ctx = {"as_of": "2026-11-24T10:00:30+00:00", "structure_snapshot_fn": fn, "si_as_of_id": "SIS-A"}
        out = AT.Toolbox(ctx, 3).t_get_structure_intelligence("latest")
        self.assertEqual(out["view"], "AS_OF_EVALUATION")
        self.assertTrue(out["NEWER_DATA_AVAILABLE"])
        self.assertEqual(out["after_as_of"]["snapshot_id"], "SIS-B")
        old = AT.Toolbox({"structure_snapshot_fn": fn}, 3).t_get_structure_intelligence("latest")   # no frozen id: as before
        self.assertNotIn("after_as_of", old)
        exp = AT.Toolbox(ctx, 3).t_get_structure_intelligence("SIS-B")              # explicit id newer than the evaluation: labelled
        self.assertTrue(exp["snapshot_after_as_of"])

    def test_master_models_newer_bar_is_labelled_not_withheld(self):
        from masterquo.agent import tools as AT
        as_of = datetime(2026, 11, 24, 10, 0, tzinfo=UTC)
        lv = {"status": "OK", "last_closed_m5": as_of.timestamp(), "gpr": {}, "board": {"x": 1}}
        out = AT.Toolbox({"as_of": as_of.isoformat(), "master_models_fn": lambda: lv}, 3).t_get_master_models()
        self.assertEqual(out["status"], "OK")
        self.assertTrue(out["NEWER_DATA_AVAILABLE"])                                 # the bar closed 5 min after the evaluation
        self.assertEqual(out["board"], {"x": 1})
        lv2 = dict(lv, last_closed_m5=as_of.timestamp() - 600)
        self.assertFalse(AT.Toolbox({"as_of": as_of.isoformat(), "master_models_fn": lambda: lv2}, 3).t_get_master_models()["NEWER_DATA_AVAILABLE"])

    def test_store_context_keeps_the_view_of_the_evaluation(self):
        from masterquo.config import AppConfig
        from masterquo.engine.service import EngineService
        cfg = AppConfig()
        v1 = SimpleNamespace(symbol=cfg.mt5.symbol, as_of="2026-11-24T10:00:00+00:00", synthetic=True, context={"walls": {"id": 1}}, tfs={})
        v2 = SimpleNamespace(symbol=cfg.mt5.symbol, as_of="2026-11-24T10:01:00+00:00", synthetic=True, context={"walls": {"id": 2}}, tfs={})
        fake = SimpleNamespace(cfg_store=SimpleNamespace(get=lambda: cfg), bridge=SimpleNamespace(account_status=dict, bars=lambda tf: [], symbol_info={}),
                               news=None, lifecycle=SimpleNamespace(recent=lambda n: []), db=SimpleNamespace(query=lambda *a: []),
                               active=SimpleNamespace(view=v1, status=lambda compact=True: {}, tracker=SimpleNamespace(get=lambda k: None)),
                               volatility=dict, _indicator_context=lambda f: None, _liquidity_context=lambda f: None, _structure_snapshot=lambda s: None,
                               _pmw_indicators=lambda: None, _svp_view=lambda: None, _lock=threading.Lock(), contexts=OrderedDict(),
                               si=SimpleNamespace(last={"snapshot_id": "SIS-1"}), _structure_cache=None)
        fake.structure = lambda tf: EngineService.structure(fake, tf)
        full = {"snapshot_id": "S1", "as_of": "2026-11-24T10:00:05+00:00", "epoch": 1, "account_key": "A", "legacy": {}, "closed": {}}
        EngineService._store_context(fake, full, {}, None, {}, {}, {}, {})
        ctx = fake.contexts["S1"]
        fake.active.view = v2                                                        # a newer scan after the evaluation
        fake.si.last = {"snapshot_id": "SIS-2"}
        self.assertEqual(ctx["structure_as_of_fn"]("M5")["walls"], {"id": 1})
        self.assertEqual(ctx["structure_fn"]("M5")["walls"], {"id": 2})
        self.assertEqual(ctx["si_as_of_id"], "SIS-1")


# ---------------------------------------------------------------------------------------------------------------- I0076 / I0083
def _imports(path: Path) -> list[str]:
    out = []
    for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(n, ast.ImportFrom):
            mod = n.module or ""
            out.append("." * n.level + mod)
            out += ["." * n.level + (mod + "." if mod else "") + a.name for a in n.names]
        elif isinstance(n, ast.Import):
            out += [a.name for a in n.names]
    return out


class TestI0076AnalysisDoesNotImportStrategies(unittest.TestCase):
    def test_analysis_layer_has_no_strategies_import(self):
        bad = {p.name: [m for m in _imports(p) if "strategies" in m] for p in (MQ / "analysis").glob("*.py")}
        self.assertEqual({k: v for k, v in bad.items() if v}, {})                    # 1.46: chart_patterns, levels, mitp

    def test_shim_reexports_the_same_objects(self):
        from masterquo.indicators import series
        from masterquo.strategies import indicators as shim
        self.assertEqual(sorted(shim.__all__), sorted(series.__all__))
        for n in series.__all__:
            self.assertIs(getattr(shim, n), getattr(series, n), n)
        pub = sorted(n for n, v in vars(series).items() if callable(v) and not n.startswith("_") and getattr(v, "__module__", "") == series.__name__)
        self.assertEqual(pub, sorted(series.__all__))


class TestI0083StrategyIdsLeaf(unittest.TestCase):
    def test_config_does_not_import_the_registry(self):
        mods = _imports(MQ / "config.py")
        self.assertFalse([m for m in mods if "registry" in m and "strategies" in m], mods)
        self.assertEqual(_imports(MQ / "strategies" / "ids.py"), [])                 # leaf: no imports at all
        code = ("import sys, _env; from masterquo.config import AppConfig; AppConfig(); "
                "print(int('masterquo.strategies.registry' in sys.modules))")
        p = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT / "tests"), capture_output=True, text=True, timeout=120, check=False)
        self.assertEqual(p.stdout.strip(), "0", p.stderr[-800:])

    def test_values_identical(self):
        from masterquo.config import ActiveConfig, _default_toggles
        from masterquo.strategies import ids, registry
        self.assertIs(registry.DEFAULT_NO_TRADE, ids.DEFAULT_NO_TRADE)
        self.assertEqual(tuple(registry.STRATEGIES), ids.STRATEGY_IDS)
        snap = {sid: (t.scan, t.trade) for sid, t in _default_toggles().items()}
        self.assertEqual(snap, {f"S{i:02d}": (True, i not in (11, 12)) for i in range(1, 13)})
        for sid in registry.STRATEGIES:
            self.assertEqual(ActiveConfig(manual_strategy_id=sid).manual_strategy_id, sid)
        for bad in ("S13", "s01", "X"):
            with self.assertRaises(ValueError):
                ActiveConfig(manual_strategy_id=bad)
        self.assertIsNone(ActiveConfig(manual_strategy_id="").manual_strategy_id)


# ---------------------------------------------------------------------------------------------------------------- I0128 / I0114
class TestI0128LintAndConstants(unittest.TestCase):
    def test_pyflakes_subset_clean(self):
        if importlib.util.find_spec("ruff") is None:
            self.skipTest("ruff not installed")
        sys.path.insert(0, str(ROOT / "tools"))
        try:
            import run_tests as RT
        finally:
            sys.path.remove(str(ROOT / "tools"))
        p = subprocess.run(RT.lint_command(), cwd=str(ROOT), capture_output=True, text=True, timeout=600, check=False)
        self.assertEqual(p.returncode, 0, p.stdout[-3000:])

    def test_dead_constants_removed_and_vocabularies_validated(self):
        import importlib
        for mod, name in (("masterquo.analysis.walls", "SOURCE_PRIORITY"), ("masterquo.modelhub.families.service", "DIRECTIONAL"),
                          ("masterquo.sh.store", "SIGNAL_STATUSES"), ("masterquo.exports.registry", "MT5_TFS"),
                          ("masterquo.markets.universe", "HL_NATIVE_TF"), ("masterquo.strategies.registry", "REGISTRY_VERSION")):
            self.assertFalse(hasattr(importlib.import_module(mod), name), f"{mod}.{name}")
        from masterquo.mm import contracts as C
        from masterquo.mm import inventory as I
        self.assertLessEqual({m["category"] for m in I.MODULES}, set(C.CATEGORIES))
        rows = I.merge_run({"jobs": {m["id"]: {"status": "SUCCEEDED", "training_executed": True, "validation_passed": True} for m in I.MODULES}})
        self.assertLessEqual({s for r in rows for s in (r.get("status_chain") or [r["status"]])}, set(C.FEATURE_STATUS))
        lits = set()
        for f in ("orchestrator.py", "jobs.py"):
            for n in ast.walk(ast.parse((MQ / "mm" / f).read_text(encoding="utf-8"))):
                if isinstance(n, ast.Dict):
                    for k, v in zip(n.keys, n.values):
                        if isinstance(k, ast.Constant) and k.value == "status" and isinstance(v, ast.Constant) and str(v.value).isupper():
                            lits.add(v.value)
        self.assertLessEqual(lits - {"NO_DATA"}, set(C.JOB_STATUS))                  # NO_DATA = per-timeframe data state, not a job


class TestI0114DeadCode(unittest.TestCase):
    def test_removed_and_kept(self):
        from masterquo.analytics import black76
        from masterquo.mt5 import fake
        from masterquo.quant import numeric, tabicl
        from masterquo.research import service as RS
        self.assertFalse(hasattr(black76, "year_fraction"))
        self.assertFalse(hasattr(RS.ResearchModulesService, "register_context"))
        self.assertFalse(hasattr(fake, "make_fake_module"))
        for n in ("simple_returns", "ewma_vol", "to_decimal", "sqrt_time", "logsumexp"):
            self.assertFalse(hasattr(numeric, n), n)
        self.assertFalse(hasattr(tabicl, "_kid"))
        # kept on purpose: MetaTrader5 API of the simulator, owner decision, tested migration path, used by the smoke, format writer
        from masterquo.lab import minirocket_v2
        from masterquo.research import graph_ca
        from masterquo.sh import units
        from masterquo.upgrade import migrate
        self.assertTrue(hasattr(fake.FakeMT5, "history_orders_get"))
        self.assertTrue(hasattr(units.SymbolSpec, "stops_level_ok"))
        self.assertTrue(callable(migrate.rollback_config) and callable(graph_ca.state_hash) and callable(minirocket_v2.export_train))

    def test_pelt_matches_the_brute_force_reference(self):
        import random

        from masterquo.lab.change_points import pelt
        rnd = random.Random(3)
        r = [rnd.gauss(0, 0.001) for _ in range(60)] + [rnd.gauss(0, 0.004) for _ in range(60)] + [rnd.gauss(0, 0.0015) for _ in range(60)]
        a, b = pelt.solve(r, 10), pelt.brute_force(r, 10)
        self.assertEqual(a["status"], "OK")
        self.assertEqual(a["change_points"], b["change_points"])
        self.assertAlmostEqual(a["objective"], b["objective"], places=9)

    def test_export_train_is_not_implemented(self):
        import contextlib
        import io

        from masterquo.lab import structure_cli
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = structure_cli.main(["minirocket", "export-train"])
        self.assertEqual(rc, 2)
        self.assertIn("NOT_IMPLEMENTED", buf.getvalue())
        mq5 = (ROOT / "mql5" / "MiniRocketV2" / "Scripts" / "PMW_MR2_Fit.mq5").read_text(encoding="utf-8")
        self.assertIn("NOT_IMPLEMENTED", mq5)


# ---------------------------------------------------------------------------------------------------------------- engine _risk harness
class _Bridge(SimpleNamespace):
    """Contract-dependent calculator: XAUUSD-* contract 100, BTC* contract 1; None for UNKNOWN*."""

    @staticmethod
    def _c(sym):
        s = str(sym or "")
        return None if s.startswith("UNKNOWN") else (1.0 if s.startswith("BTC") else 100.0)

    def calc_profit_sym(self, sym, side, vol, po, pc):
        c = self._c(sym)
        return None if c is None else (pc - po) * vol * c * (1 if side == "BUY" else -1)

    def calc_margin_sym(self, sym, side, vol, px):
        c = self._c(sym)
        return None if c is None else px * vol * c / 100.0

    def calc_profit(self, side, vol, po, pc):
        return self.calc_profit_sym(self.cfgsym, side, vol, po, pc)

    def calc_margin(self, side, vol, px):
        return self.calc_margin_sym(self.cfgsym, side, vol, px)


def _risk_fake(positions=(), orders=(), deals=(), **risk):
    from masterquo.config import AppConfig
    from masterquo.db.database import Database
    from masterquo.engine.service import EngineService
    cfg = AppConfig()
    for k, v in {"risk_per_trade_pct": 1.0, "max_total_open_risk_pct": 5.0, "daily_loss_limit_pct": 5.0, "max_drawdown_pct": 20.0,
                 "max_open_positions": 10, "cooldown_minutes_after_loss": 0, **risk}.items():
        setattr(cfg.risk, k, v)
    b = _Bridge(_lock=threading.Lock(), positions=list(positions), deals=list(deals), orders=list(orders), server_day_start_utc=lambda: None,
                clock=SimpleNamespace(offset=0.0), account_key="ACC", cfgsym=cfg.mt5.symbol,
                symbol_info={"point": 0.01, "trade_tick_size": 0.01, "volume_min": 0.01, "volume_max": 50.0, "volume_step": 0.01, "trade_mode": 4,
                             "trade_stops_level": 0, "digits": 2},
                account={"margin_mode": "HEDGING"})
    b.account_status = lambda: {"equity": 10000.0, "balance": 10000.0, "free_margin": 9000.0, "currency": "USD"}
    fake = SimpleNamespace(cfg_store=SimpleNamespace(get=lambda: cfg), bridge=b, db=Database(), prefs=None, modes=None)
    fake.portfolio_snapshot = lambda p, o: EngineService.portfolio_snapshot(fake, p, o)
    fake.PENDING_BUY, fake.PENDING_SELL = EngineService.PENDING_BUY, EngineService.PENDING_SELL
    return fake, cfg


LEVELS = {"status": "AVAILABLE", "stop_loss": 1990.0, "targets": [{"price": 2030.0, "weight": 1.0}]}
QUOTE = {"bid": 1999.9, "ask": 2000.0, "spread": 0.1, "spread_points": 10}


class _RiskCase(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def risk(self, fake):
        from masterquo.engine.service import EngineService
        try:
            return EngineService._risk(fake, "LONG", LEVELS, QUOTE, True, None)
        finally:
            fake.db.close()


class TestI0709OpenRiskOwnSymbolTighteningOnly(_RiskCase):
    def _pos(self, sym, sl, vol=0.1, side="BUY", px=60000.0):
        return {"ticket": 7, "symbol": sym, "side": side, "volume": vol, "price_current": px, "price_open": px, "sl": sl, "profit": 0.0, "swap": 0.0}

    def test_risk_is_never_lower_than_today(self):
        # BTC position (contract 1) valued today with the XAUUSD contract (100): 0.1 x 100 x 2000 = 20000 > cap -> the BLOCK stays
        r = self.risk(_risk_fake([self._pos("BTCUSD", 58000.0)])[0])
        self.assertEqual(r["risk_gate"], "BLOCKED")
        self.assertIn("NO_RISK_BUDGET_AVAILABLE", r["reason_codes"])
        self.assertAlmostEqual(r["open_risk"]["open_risk"], 20000.0)                  # max(today 20000, own 200) - no new entry
        # the own-symbol calculator gives the LARGER risk -> it is used (1.46 understated it)
        pos = self._pos("BTCUSD", 58000.0)
        fake, _ = _risk_fake()
        fake.bridge.calc_profit = lambda s, v, o, c: (c - o) * v * 0.01 * (1 if s == "BUY" else -1)   # configured-symbol value: 2
        r = self.risk(_risk_with(fake, [pos]))
        self.assertAlmostEqual(r["open_risk"]["open_risk"], 200.0)                    # 1.46: 2

    def test_unknown_own_symbol_blocks_and_same_symbol_unchanged(self):
        r = self.risk(_risk_fake([self._pos("UNKNOWN1", 58000.0)])[0])
        self.assertEqual(r["risk_gate"], "BLOCKED")
        self.assertIn("OPEN_POSITION_WITHOUT_SL_RISK_UNBOUNDED", r["reason_codes"])  # unknown risk blocks (1.46: XAUUSD contract value)
        fake, cfg = _risk_fake()
        same = self._pos(cfg.mt5.symbol, 1999.0, vol=0.01, px=2000.0)
        r = self.risk(_risk_with(fake, [same]))
        self.assertAlmostEqual(r["open_risk"]["open_risk"], 1.0)                      # 0.01 x 100 x 1 - identical to 1.46


def _risk_with(fake, positions=(), orders=()):
    fake.bridge.positions, fake.bridge.orders = list(positions), list(orders)
    return fake


class TestI0723PendingCalcUnknown(_RiskCase):
    def test_unknown_pending_order_blocks(self):
        o = {"ticket": 9, "type": 2, "symbol": "UNKNOWN2", "volume_current": 0.1, "price_open": 100.0, "sl": 90.0}
        fake, _ = _risk_fake()
        snap = fake.portfolio_snapshot([], [o])
        self.assertEqual(snap["pending_unknown"], [9])
        self.assertIsNone(snap["pending_risk"])
        self.assertIsNone(snap["pending_margin"])
        r = self.risk(_risk_with(fake, orders=[o]))
        self.assertEqual(r["risk_gate"], "BLOCKED")                                   # 1.46: PASS with pending_risk 0
        self.assertIn("PENDING_ORDER_RISK_UNKNOWN", r["reason_codes"])
        self.assertIsNone(r["total_open_risk"])

    def test_known_pending_orders_identical(self):
        fake, cfg = _risk_fake()
        o = {"ticket": 3, "type": 2, "symbol": cfg.mt5.symbol, "volume_current": 0.01, "price_open": 1995.0, "sl": 1990.0}
        snap = fake.portfolio_snapshot([], [o])
        self.assertEqual(snap["pending_unknown"], [])
        self.assertAlmostEqual(snap["pending_risk"], 5.0)
        self.assertAlmostEqual(snap["pending_margin"], 19.95)
        r = self.risk(_risk_with(fake, orders=[o]))
        self.assertNotIn("PENDING_ORDER_RISK_UNKNOWN", r["reason_codes"])
        self.assertAlmostEqual(r["pending_risk"], 5.0)


class TestI0107DailyResetReported(_RiskCase):
    def test_utc_midnight_is_reported_not_applied(self):
        fake, cfg = _risk_fake()
        base = self.risk(_risk_fake()[0])
        cfg.risk.daily_reset = "UTC_MIDNIGHT"
        r = self.risk(fake)
        self.assertEqual(r["daily_reset_effective"], "BROKER_SERVER_MIDNIGHT")
        self.assertIn("DAILY_RESET_UTC_MIDNIGHT_NOT_APPLIED", r["warnings"])          # 1.46: silently ignored
        self.assertNotIn("DAILY_RESET_UTC_MIDNIGHT_NOT_APPLIED", r["reason_codes"])
        self.assertEqual((r["risk_gate"], r["reason_codes"], r.get("lots")), (base["risk_gate"], base["reason_codes"], base.get("lots")))
        self.assertNotIn("warnings", base)


class TestI0808DrawdownNote(_RiskCase):
    def test_withdrawal_after_peak_is_noted_block_unchanged(self):
        from masterquo.risk import engine as RE
        deals = [{"type": 2, "profit": -2000.0, "time": 2_000_000_000.0}]
        fake, _ = _risk_fake(deals=deals)
        fake.db.execute("INSERT INTO equity_snapshots(ts, mode, account_key, balance, equity, margin, free_margin, currency) VALUES (?,?,?,?,?,?,?,?)",
                        ("2026-01-01T00:00:00+00:00", "ACCOUNT", "ACC", 12500.0, 12500.0, 0, 12500.0, "USD"))
        r = self.risk(fake)
        self.assertEqual(r["risk_gate"], "BLOCKED")
        self.assertIn("DRAWDOWN_BREACH", r["reason_codes"])                           # the block stays (S0 otherwise)
        self.assertEqual(r["drawdown_note"], "PEAK_INCLUDES_CAPITAL_FLOWS")           # 1.46: nothing said
        self.assertNotIn("PEAK_INCLUDES_CAPITAL_FLOWS", r["reason_codes"])
        self.assertIsNone(RE.capital_flow_note([{"type": 2, "profit": -5.0, "time": 10.0}], 100.0))   # before the peak
        self.assertIsNone(RE.capital_flow_note([{"type": 2, "profit": 500.0, "time": 200.0}], 100.0))  # deposit


# ---------------------------------------------------------------------------------------------------------------- I0108 / I0124
class TestI0108JointExposureNotEnforced(unittest.TestCase):
    def test_status_says_not_enforced(self):
        from masterquo.assets.registry import AssetRegistry
        from masterquo.config import AppConfig, ConfigStore
        td = TempData()
        self.addCleanup(td.close)
        st = AssetRegistry(ConfigStore()).state()
        self.assertIs(st["max_joint_exposure_enforced"], False)
        self.assertIn("max_total_open_risk_pct", st["max_joint_exposure_note"])
        self.assertIn("NOT ENFORCED", AppConfig.model_fields["assets"].annotation.model_fields["max_joint_exposure_pct"].description)


class TestI0124LegacyAccountProfile(unittest.TestCase):
    def test_configured_profile_reported_vendor_constant_kept(self):
        from masterquo.config import AppConfig
        from masterquo.engine.legacy import build_snapshot
        cfg = AppConfig()
        s = build_snapshot(snapshot_id="S", analysis_id="A", as_of="2026-11-24T10:00:00Z", symbol="XAUUSD-", alias="XAUUSD", closed_bars={},
                           analysis_status="PASS", reason_codes=[], costs_account_profile=cfg.costs.account_profile)
        self.assertEqual(s["costs_account_profile"], cfg.costs.account_profile)
        self.assertEqual(s["account_profile"], "ZERO_SPREAD_DECLARED_UNVERIFIED")     # vendor contract (M02I bridge, M10A adapter)
        s0 = build_snapshot(snapshot_id="S", analysis_id="A", as_of="2026-11-24T10:00:00Z", symbol="XAUUSD-", alias="XAUUSD", closed_bars={},
                            analysis_status="PASS", reason_codes=[])
        self.assertNotIn("costs_account_profile", s0)


# ---------------------------------------------------------------------------------------------------------------- I0717 / I0760
class _SymBridge:
    def __init__(self, rows):
        self.rows = rows

    def _call(self, fn):
        return fn(SimpleNamespace(symbols_get=lambda: self.rows))


def _row(name, base, profit, visible=True, mode=None, trade_mode=4):
    d = {"name": name, "currency_base": base, "currency_profit": profit, "visible": visible, "trade_mode": trade_mode}
    if mode is not None:
        d["trade_calc_mode"] = mode
    return d


class TestI0717I0760AutodetectVeto(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.config import ConfigStore
        self.cfg = ConfigStore()

    def tearDown(self):
        self.td.close()

    def reg(self, rows):
        from masterquo.assets.registry import AssetRegistry
        return AssetRegistry(self.cfg, _SymBridge(rows))

    def test_conflicting_currencies_are_not_adopted(self):
        for rows in ([_row("ETHBTC", "ETH", "BTC")], [_row("BTCEUR", "BTC", "EUR")], [_row("BTCUSDT", "BTC", "USDT")]):
            r = self.reg(rows)
            self.assertIsNone(r.find_on_account("BTC"), rows)                        # 1.46: adopted by the name
            self.assertEqual(r.rejections[-1]["reason"], "CURRENCY_CONFLICT")
        self.assertEqual(self.reg([_row("BTCUSD.m", "BTC", "USD")]).find_on_account("BTC"), "BTCUSD.m")
        self.assertIsNone(self.reg([_row("XAUEUR", "XAU", "EUR")]).find_on_account("XAUUSD"))
        r = self.reg([_row("BTCUSDT", "BTC", "USDT", visible=True), _row("BITCOIN", "", "", visible=False)])
        self.assertIsNone(r.find_on_account("BTC"))                                  # the next name candidate is NOT promoted
        self.assertIsNone(r.autodetect("BTC"))
        self.assertIsNone(self.cfg.get().assets.mappings["BTC"].broker_symbol)

    def test_share_cfd_is_not_gold(self):
        from masterquo.assets.registry import classify
        gs = _row("#GOLDMANSACHS", "USD", "USD", mode=32)
        self.assertIsNone(classify(gs)["asset"])                                     # 1.46: XAUUSD
        self.assertIn("XAUUSD_NAME_AMBIGUOUS", classify(gs)["notes"])
        self.assertEqual(classify(gs, legacy=True)["asset"], "XAUUSD")
        self.assertIsNone(classify(_row("GOLD.NYSE", "USD", "USD", mode=2))["asset"])
        for name in ("GOLD", "GOLD.", "XAUUSD-"):
            self.assertEqual(classify(_row(name, "USD", "USD", mode=2))["asset"], "XAUUSD", name)
        r = self.reg([gs])
        self.assertIsNone(r.find_on_account("XAUUSD"))
        self.assertEqual(r.rejections[-1]["reason"], "XAUUSD_NAME_AMBIGUOUS")
        self.assertIsNone(self.reg([_row("#GOLDMANSACHS", "", "", mode=32)]).find_on_account("XAUUSD"))   # not back through the name

    def test_result_is_todays_winner_or_none(self):
        """Exhaustive small universe: the new result is always the 1.46 winner or None (never another candidate)."""
        import itertools

        from masterquo.assets import registry as R
        pool = [_row("XAUUSD-", "USD", "USD", mode=2), _row("GOLD.NYSE", "USD", "USD", mode=2), _row("#GOLDMANSACHS", "USD", "USD", True, 32),
                _row("XAUEUR", "XAU", "EUR"), _row("XAUUSD", "XAU", "USD", visible=False), _row("BTCUSDT", "BTC", "USDT"),
                _row("BITCOIN", "", "", visible=False), _row("BTCUSD", "BTC", "USD", visible=False), _row("ETHBTC", "ETH", "BTC")]
        orig = R.classify
        for k in (1, 2, 3):
            for rows in itertools.combinations(pool, k):
                for asset in ("XAUUSD", "BTC"):
                    new = self.reg(list(rows)).find_on_account(asset)
                    try:
                        R.classify = lambda m, legacy=True: orig(m, legacy=True)      # the 1.46 rule
                        reg = self.reg(list(rows))
                        reg._adoption_veto = lambda a, d: None
                        old = reg.find_on_account(asset)
                    finally:
                        R.classify = orig
                    self.assertIn(new, (old, None), (asset, [x["name"] for x in rows]))


if __name__ == "__main__":
    unittest.main()
