"""Fala 2 (1.46.0, gałąź claude/architektura-modele-146) - grupa data_forecast_ui.

I0230  quant/adapters.lab(): testy jednostkowe ścieżki Lab -> Quant (wcześniej tylko smoke)
I0346  /api/v1/models/bat/shadow: losowe, niewytrenowane wagi -> NOT_TRAINED, bez actor/critic (surowe głowice tylko diagnostic=true)
I0607  /api/v1/market-trap: baza spreadu = mediana spreadu zamkniętych świec (EXECUTION_STRESS przestaje być zawsze UNAVAILABLE)
I0615  scalp A/B bez procesu analityki: dokładny powód (bez uruchamiania workera - S0: nowe wejście MetaModelu)
I0633  forecast shadow_summary: jeden run_id, pokrycie q10-q90 liczone na wierszach z kwantylami (+I0635, I0636)
I0638  Double Retest (siatka 5 USD złota) tylko dla XAUUSD - BTC: UNSUPPORTED_INSTRUMENT, bez sygnałów
I0640  long-horizon: zakres etykiety CALIBRATED (pasmo q05-q95) i nieskalibrowane p_up/p_down/p_flat
I0123  config/profiles: nieczytane pliki usunięte
I0078  analytics -> scalp / ml: cykl przez liquidity_eval usunięty (moduł w evaluation/, alias w analytics)
I0121  dwa pola „okno wejścia po potwierdzeniu” opisane ścieżką (ORIGINAL / M07 vs ACTIVE S01-S12)
I0033  eksport magazynów: ledgery instrumentu innego niż domyślny (mm@BTC, ml@BTC)
I0857  nazwy warstw planów po rebrandzie (Apollo23 Scalp / Hedge Plan)
I0103  cały graf Runtime w jednym procesie testów
I0047  wspólne funkcje kontroli jakości danych dla bramek ACTIVE i SH (bez zmiany decyzji - porównanie z poprzednim kodem)
I0051  jeden klasyfikator luk raportów offline (marketdata / eksport) z parametrami konsumentów (porównanie z poprzednim kodem)
I0126  martwy kod frontendu usunięty
I0328  szanse w karcie planu liczone per wybrany plan (tests/js/charts_adapters.test.mjs)
"""
from __future__ import annotations

import ast
import math
import random
import shutil
import sqlite3
import subprocess
import threading
import types
import unittest
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import _env
from _env import TempData

ROOT = _env.ROOT
BACKEND = ROOT / "backend" / "masterquo"
UTC = timezone.utc  # noqa: UP017 - the same constant as in the legacy oracles


def _endpoints(rt):
    from fastapi import FastAPI
    from masterquo.api import wf32_routes
    app = FastAPI()
    wf32_routes.register(app, rt)
    return {(r.path, m): r.endpoint for r in app.routes if hasattr(r, "methods") for m in r.methods}


def _bars(n, *, tf_s=300, spread=10, t0=1_795_000_000):
    out = []
    for i in range(n):
        px = 2400.0 + 2.0 * math.sin(i / 7.0)
        out.append({"t_raw": t0 + i * tf_s, "open_utc": datetime.fromtimestamp(t0 + i * tf_s, UTC).isoformat().replace("+00:00", "Z"),
                    "o": px, "h": px + 1.0, "l": px - 1.0, "c": px + 0.2, "tv": 100, "spread": spread, "closed": True})
    return out


# ============================================================================================ I0230 quant/adapters.lab
class TestLabQuantAdapter(unittest.TestCase):
    def rt(self, state):
        return types.SimpleNamespace(lab=types.SimpleNamespace(state=state, assets=None))

    def test_no_lab_service_gives_nothing(self):
        from masterquo.quant import adapters as A
        self.assertEqual(A.lab(types.SimpleNamespace(), "XAUUSD"), [])

    def test_instrument_not_computed_is_blocked_data(self):
        from masterquo.quant import adapters as A
        (p,) = A.lab(self.rt({}), "XAUUSD")
        self.assertEqual((p["canonical_id"], p["state"]), ("lab:models", "BLOCKED_DATA"))

    def test_ready_model_record(self):
        from masterquo.modelhub import contract as C
        from masterquo.quant import adapters as A
        st = {"XAUUSD": {"as_of": "2026-11-20T10:00:00Z", "data_mode": "mt5",
                         "models": [{"family": "LGBM", "horizon": "M5x12", "status": "ready", "raw_score": 0.61, "model_id": "m1", "side": "LONG",
                                     "event": "TB_LONG"}]}}
        (p,) = A.lab(self.rt(st), "XAUUSD")
        C.validate(p)
        self.assertEqual((p["canonical_id"], p["state"], p["unit"], p["task"], p["horizon"]["bars"]),
                         ("lab:LGBM", "READY", "ratio", "TRIPLE_BARRIER_LONG_SCORE_H12", 12))
        self.assertEqual(p["result"], {"raw_score": 0.61})
        self.assertEqual(p["data_kind"], "REAL")

    def test_error_and_warming_up_states(self):
        from masterquo.quant import adapters as A
        st = {"XAUUSD": {"as_of": "2026-11-20T10:00:00Z", "models": [{"family": "A", "horizon": "M5x3", "status": "error", "reason": "boom"},
                                                                       {"family": "B", "horizon": "M5x3", "status": "warming_up"}]}}
        out = {p["canonical_id"]: p for p in A.lab(self.rt(st), "XAUUSD")}
        self.assertEqual((out["lab:A"]["state"], out["lab:B"]["state"]), ("ERROR", "BLOCKED_DATA"))
        self.assertIn("boom", out["lab:A"]["unavailable_reason"])

    def test_no_model_is_not_trained(self):
        from masterquo.quant import adapters as A
        (p,) = A.lab(self.rt({"XAUUSD": {"models": [], "model": {"status": "no_model", "reason": "brak artefaktu"}}}), "XAUUSD")
        self.assertEqual((p["canonical_id"], p["state"]), ("lab:models", "NOT_TRAINED"))

    def test_fixture_data_is_synthetic_and_excluded_from_real_snapshot(self):
        import time as _t

        from masterquo.quant import adapters as A
        from masterquo.quant import checks as CK
        now = _t.time()
        st = {"XAUUSD": {"as_of": datetime.fromtimestamp(now - 30, UTC).isoformat().replace("+00:00", "Z"), "data_mode": "fixture",
                         "models": [{"family": "LGBM", "horizon": "M5x6", "status": "ready", "raw_score": 0.4, "model_id": "m"}]}}
        (p,) = A.lab(self.rt(st), "XAUUSD")
        self.assertEqual(p["data_kind"], "SYNTHETIC")
        self.assertEqual(CK.check(p, now=now, snapshot_kind="REAL")["reason"], "SYNTHETIC_IN_REAL_SNAPSHOT")


# ============================================================================================ I0346 BAT encoder endpoint
class TestBatShadowNotTrained(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        bars = _bars(80, tf_s=3600)
        self.rt = types.SimpleNamespace(bridge=types.SimpleNamespace(bars=lambda tf, n, include_forming=False: bars, quote_status=lambda: None))

    def tearDown(self):
        self.td.close()

    def test_untrained_heads_are_not_published(self):
        ep = _endpoints(self.rt)[("/api/v1/models/bat/shadow", "GET")]
        r = ep(timeframe="H1")
        self.assertEqual(r["status"], "NOT_TRAINED")
        self.assertIsNone(r["actor"])
        self.assertIsNone(r["critic_value"])
        self.assertTrue(r["context"])                           # the encoder context stays (descriptive)
        self.assertNotIn("untrained_heads_diagnostic", r)
        d = ep(timeframe="H1", diagnostic=True)
        self.assertEqual(set(d["untrained_heads_diagnostic"]["actor"]), {"LONG", "FLAT", "SHORT"})

    def test_encoder_itself_unchanged(self):
        from masterquo.mm.bat_encoder import BATEncoder
        self.assertEqual(BATEncoder().run(_bars(40, tf_s=3600))["status"], "SHADOW_UNTRAINED")   # causality tests / smoke call it directly


# ============================================================================================ I0607 market trap spread baseline
class TestMarketTrapSpreadBaseline(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def ep(self, bars, spread_points):
        rt = types.SimpleNamespace(bridge=types.SimpleNamespace(bars=lambda tf, n, include_forming=False: bars,
                                                                quote_status=lambda: {"spread_points": spread_points}))
        return _endpoints(rt)[("/api/v1/market-trap", "GET")]

    def test_baseline_from_closed_bars(self):
        r = self.ep(_bars(120, spread=10), 30)(timeframe="M5")
        self.assertEqual(r["components"]["EXECUTION_STRESS"]["status"], "OK")
        self.assertEqual(r["spread_baseline"], 10)
        self.assertAlmostEqual(r["components"]["EXECUTION_STRESS"]["spread_ratio"], 3.0)
        self.assertEqual(r["confidence"], 0.3)
        self.assertIn("MEDIAN", r["spread_baseline_source"])

    def test_too_few_bars_with_spread_stays_unavailable(self):
        bars = _bars(120, spread=0)
        for b in bars[:30]:
            b["spread"] = 12
        r = self.ep(bars, 30)(timeframe="M5")
        self.assertEqual(r["components"]["EXECUTION_STRESS"]["status"], "UNAVAILABLE")
        self.assertIsNone(r["spread_baseline"])
        self.assertEqual(r["confidence"], 0.2)


# ============================================================================================ I0615 scalp A/B without the analytics worker
class TestScalpWorkerReason(unittest.TestCase):
    def service(self, enabled, status="DISABLED", retry_in=0.0):
        import time as _t

        from masterquo.forecast.service import ForecastService
        cfg = types.SimpleNamespace(forecast=types.SimpleNamespace(enabled=enabled))
        fs = ForecastService(types.SimpleNamespace(get=lambda: cfg), None, None, None, None)
        fs.state["status"] = status
        fs.retry_at = _t.monotonic() + retry_in
        return fs

    def scalp(self, fs):
        from masterquo.scalp.service import ScalpService
        sc = ScalpService.__new__(ScalpService)
        sc.forecast = fs
        sc.registry = lambda: {"active": "run1", "runs": {"run1": {"setup_model": True}}}
        return sc

    def test_disabled_forecasts_give_exact_reason_and_stay_unavailable(self):
        fs = self.service(False)
        sc = self.scalp(fs)
        a, b = sc.forecasts(), sc.setup_quality({"features": {}})
        self.assertEqual((a["status"], a["reason_code"]), ("UNAVAILABLE", "FORECAST_DISABLED_NO_WORKER"))
        self.assertEqual((b["status"], b["reason_code"], b["pass"]), ("UNAVAILABLE", "FORECAST_DISABLED_NO_WORKER", False))
        self.assertIn("forecast.enabled=false", a["reason"])
        self.assertIsNone(fs.proc)                               # nothing was started (availability of scalp A/B unchanged - S0)

    def test_other_reasons(self):
        self.assertEqual(self.scalp(self.service(True, "NO_CANDLE_ENV")).forecasts()["reason_code"], "NO_CANDLE_ENV")
        self.assertEqual(self.scalp(self.service(True, "FORECAST_UNAVAILABLE", retry_in=30)).forecasts()["reason_code"], "WORKER_RESTART")
        self.assertEqual(self.scalp(self.service(True, "STARTING")).forecasts()["reason_code"], "STARTING")
        sc = self.scalp(None)
        self.assertEqual(sc.forecasts()["status"], "UNAVAILABLE")

    def test_running_worker_is_asked_as_before(self):
        fs = self.service(True, "SHADOW")
        fs.proc = types.SimpleNamespace(poll=lambda: None)
        fs._ask = lambda req, timeout: {"status": "SHADOW", "cmd": req["cmd"]}
        sc = self.scalp(fs)
        sc.bridge = types.SimpleNamespace(bars=lambda tf, n, include_forming=False: [], symbol_info={"point": 0.01})
        self.assertEqual(sc.forecasts(), {"status": "SHADOW", "cmd": "scalp_forecast"})
        self.assertEqual(sc.setup_quality({"features": {}})["cmd"], "setup_quality")


# ============================================================================================ I0633 / I0635 / I0636 forecast shadow summary
class TestForecastShadowSummary(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.db.database import Database
        from masterquo.forecast.service import ForecastService
        self.db = Database()
        self.fs = ForecastService(None, None, self.db, None, None)

    def tearDown(self):
        self.td.close()

    def row(self, run, k, p, q=None, cls="UP", close=2405.0):
        t = (datetime(2026, 11, 20, 10, tzinfo=UTC) + timedelta(minutes=5 * k)).isoformat().replace("+00:00", "Z")
        self.db.execute("""INSERT INTO forecast_shadow(created_at, run_id, feature_time_utc, horizon_minutes, target_time_utc, close_now, neutral_band,
                           p_down, p_flat, p_up, q10, q50, q90, horizon_status, outcome_close, outcome_class, outcome_status, instrument)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (t, run, t, 5, t, 2400.0, 1.0, p[0], p[1], p[2], q[0] if q else None, None, q[1] if q else None, "ACCEPTED", close, cls,
                         "SCORED", "XAUUSD"))

    def test_only_the_active_run_is_scored(self):
        for k in range(4):
            self.row("A", k, (0.0, 0.0, 1.0))                   # perfect model A
        self.row("B", 10, (1.0, 0.0, 0.0), q=(2400.0, 2410.0))    # bad model B: 2 rows with quantiles (1 covered), 2 without
        self.row("B", 11, (1.0, 0.0, 0.0), q=(2410.0, 2420.0))
        self.row("B", 12, (1.0, 0.0, 0.0))
        self.row("B", 13, (1.0, 0.0, 0.0))
        self.fs.state["model"] = {"run_id": "B"}
        s = self.fs.shadow_summary()["5"]
        self.assertEqual((s["run_id"], s["scored"], s["scored_other_runs"]), ("B", 4, 4))
        self.assertEqual(s["brier"], 2.0)                        # before: (4 x 0 + 4 x 2) / 8 = 1.0 - two models mixed
        self.assertEqual((s["q10_q90_coverage"], s["quantile_rows"]), (0.5, 2))   # before: 1 / 8
        self.assertEqual(self.fs.shadow_summary("A")["5"]["brier"], 0.0)

    def test_no_quantiles_is_none_not_zero(self):
        self.row("A", 0, (0.0, 0.0, 1.0))
        s = self.fs.shadow_summary("A")["5"]
        self.assertIsNone(s["q10_q90_coverage"])
        self.assertEqual(s["quantile_rows"], 0)

    def test_without_model_the_latest_stored_run_is_used(self):
        self.row("A", 0, (0.0, 0.0, 1.0))
        self.row("B", 1, (1.0, 0.0, 0.0))
        self.assertEqual(self.fs.shadow_summary()["5"]["run_id"], "B")


# ============================================================================================ I0638 Double Retest only for XAUUSD
class TestDoubleRetestInstrument(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def run_tick(self, inst):
        from masterquo.db.database import Database
        from masterquo.forecast import service as FSm
        m5, m30 = _bars(60, tf_s=300), _bars(20, tf_s=1800)
        cfg = types.SimpleNamespace(forecast=types.SimpleNamespace(enabled=True, m5_bars=500, m30_bars=200, request_timeout_seconds=5),
                                    assets=types.SimpleNamespace(active=inst), mt5=types.SimpleNamespace(symbol="SYM"))
        bridge = types.SimpleNamespace(bars=lambda tf, n, include_forming=False: m5 if tf == "M5" else m30, symbol_info={},
                                       quote_status=dict)
        bus = types.SimpleNamespace(publish=lambda *a, **k: None)
        fs = FSm.ForecastService(types.SimpleNamespace(get=lambda: cfg), bridge, Database(), bus, None)
        fs._spawn = lambda: setattr(fs, "proc", types.SimpleNamespace(poll=lambda: None, pid=1)) or True
        fs._ask = lambda req, timeout: {"status": "NO_MODEL", "flags_tail": [{"time_open_utc": b["open_utc"], "names": []} for b in m5]}
        seen = []
        fs.listeners.append(lambda setup, symbol: seen.append(setup))
        fs.tick()
        return fs.state["setup_v2"], seen

    def test_btc_is_unsupported_and_announces_nothing(self):
        setup, seen = self.run_tick("BTC")
        self.assertEqual(setup["status"], "UNSUPPORTED_INSTRUMENT")
        self.assertEqual((setup["states"], setup["can_submit_order"]), ({}, False))
        self.assertEqual(seen, [])

    def test_gold_runs_the_machine(self):
        setup, seen = self.run_tick("XAUUSD")
        self.assertNotIn("status", setup)
        self.assertEqual(len(seen), 1)

    def test_signal_listener_ignores_unsupported(self):
        from masterquo.markets.signals import BotSignalService
        calls = []
        fake = types.SimpleNamespace(cfg=types.SimpleNamespace(strategy_sources=types.SimpleNamespace(double_retest=True)),
                                     record_strategy=lambda **k: calls.append(k) or True)
        done = (datetime.now(UTC) - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
        s = {"state": "RESEARCH_SETUP_COMPLETE", "ended_at": done, "deep_zone": [100.0, 101.0], "epsilon": 0.1, "targets_hypothetical": [105.0]}
        base = {"states": {"BUY": {"recent": [s]}}}
        self.assertEqual(BotSignalService.on_double_retest(fake, base, symbol="X"), 1)
        self.assertEqual(BotSignalService.on_double_retest(fake, dict(base, status="UNSUPPORTED_INSTRUMENT"), symbol="X"), 0)
        self.assertEqual(len(calls), 1)


# ============================================================================================ I0640 long-horizon calibration scope
class TestLongHorizonCalibrationScope(unittest.TestCase):
    def test_scope_fields(self):
        from masterquo.forecast import long_horizon as LH
        rnd = random.Random(5)
        ts, px, p = [], [], 2000.0
        for i in range(24 * 200):
            p *= math.exp(rnd.gauss(0, 0.002))
            ts.append(1_700_000_000 + i * 3600)
            px.append(p)
        r = LH.forecast(ts, px, "24h")
        self.assertIn(r["status"], ("OK", "STALE"))
        self.assertIn(r["calibration"], ("CALIBRATED", "UNCALIBRATED"))      # key unchanged (API / export contract)
        self.assertEqual(r["calibration_scope"], "q05_q95_band")
        self.assertTrue(r["p_calibration"].startswith("UNCALIBRATED"))


# ============================================================================================ I0123 config/profiles
class TestProfilesDirReadOrAbsent(unittest.TestCase):
    def test_profiles_dir_is_read_or_absent(self):
        d = ROOT / "config" / "profiles"
        if not d.exists():
            return
        code = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in BACKEND.rglob("*.py"))
        for f in d.iterdir():
            self.assertIn(f.name, code, f"config/profiles/{f.name} jest pakowany, ale nic go nie czyta")

    def test_rollback_doc_does_not_point_to_removed_files(self):
        txt = (ROOT / "ROLLBACK.md").read_text(encoding="utf-8")
        if not (ROOT / "config" / "profiles").exists():
            self.assertNotIn("config/profiles/", txt)


# ============================================================================================ I0078 analytics layering
class TestAnalyticsLayering(unittest.TestCase):
    FORBIDDEN = ("masterquo.scalp", "masterquo.ml", "masterquo.evaluation")

    def _imports(self, path: Path):
        mod = "masterquo." + ".".join(path.relative_to(BACKEND).with_suffix("").parts)
        pkg = mod.rsplit(".", 1)[0] if path.name != "__init__.py" else mod
        out = []
        for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Import):
                out += [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                base = pkg.split(".")
                base = base[:len(base) - (n.level - 1)] if n.level else []
                full = ".".join(base + ([n.module] if n.module else []))
                out += [full] + [f"{full}.{a.name}" for a in n.names]
        return out

    def test_analytics_has_no_edge_to_scalp_ml_or_evaluation(self):
        bad = []
        for p in (BACKEND / "analytics").rglob("*.py"):
            bad += [(p.name, m) for m in self._imports(p) if any(m == f or m.startswith(f + ".") for f in self.FORBIDDEN)]
        self.assertEqual(bad, [])

    def test_alias_still_serves_the_old_import(self):
        from masterquo.analytics import liquidity_eval as alias
        from masterquo.evaluation import liquidity_eval as real
        self.assertIs(alias.evaluate, real.evaluate)
        self.assertEqual(alias.PARAMS, real.PARAMS)


# ============================================================================================ I0121 confirmed window labels
class TestConfirmedWindowLabels(unittest.TestCase):
    def test_each_field_names_its_path(self):
        import re
        src = (ROOT / "frontend" / "src" / "components" / "Dialogs.tsx").read_text(encoding="utf-8")

        def label(path):
            m = re.search(r'field\("([^"]+)",\s*"' + re.escape(path) + '"', src)
            self.assertIsNotNone(m, path)
            return m.group(1)
        self.assertIn("ORIGINAL", label("strategy.confirmed_window_bars"))
        self.assertIn("ACTIVE", label("active.confirmed_window_bars"))
        self.assertNotEqual(label("strategy.confirmed_window_bars"), label("active.confirmed_window_bars"))


# ============================================================================================ I0033 export of per-instrument ledgers
class TestExportStoresPerInstrument(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.data = Path(self.td.dir)

    def tearDown(self):
        self.td.close()

    def test_btc_mm_ledger_is_exportable(self):
        from masterquo.exports import registry as ER
        from masterquo.exports import sources as S
        self.assertIn("mm@BTC", S.STORES)
        self.assertIn("ml@BTC", S.STORES)
        self.assertEqual(S.STORES["ml@BTC"][1], S.STORES["main"][1])          # full copy of the main schema -> same exclusions
        for k in ("main", "mm", "quant", "evaluation"):                     # existing names / paths unchanged
            self.assertIn(k, S.STORES)
        self.assertEqual(S.STORES["mm"][0], "mm/ledger.sqlite")
        p = self.data / "instruments" / "BTC" / "mm" / "ledger.sqlite"
        p.parent.mkdir(parents=True)
        con = sqlite3.connect(p)
        con.execute("CREATE TABLE predictions(id INTEGER PRIMARY KEY, at TEXT, value REAL)")
        con.executemany("INSERT INTO predictions(at, value) VALUES (?, ?)", [("2026-11-20T10:00:00Z", 0.1 * i) for i in range(7)])
        con.commit()
        con.close()
        man = ER.run("store-tables", S.SourceContext(self.data), {"store": "mm@BTC"}, out_root=self.data / "exports")
        self.assertEqual(man["row_counts"]["predictions"], 7)


# ============================================================================================ I0857 plan layer names
class TestPlanLayerNamesRebranded(unittest.TestCase):
    def test_layers_and_legend(self):
        from masterquo.plans import contract as PC
        self.assertEqual(PC.LAYERS["SCALPING"], ("SCALP", "Apollo23 Scalp Plan"))
        self.assertEqual(PC.LAYERS["HEDGING"], ("HEDGE", "Apollo23 Hedge Plan"))
        self.assertEqual(PC.from_setup({"strategy": "UNKNOWN"})["layer"], "Apollo23 Scalp Plan")
        src = (BACKEND / "plans" / "contract.py").read_text(encoding="utf-8") + \
            (ROOT / "frontend" / "src" / "features" / "pmw133" / "overlays.tsx").read_text(encoding="utf-8")
        self.assertNotIn("Pepe Scalp Plan", src)
        self.assertNotIn("Pepe Hedge Plan", src)


# ============================================================================================ I0103 whole Runtime graph in one process
class TestRuntimeGraphInProcess(unittest.TestCase):
    def test_graph_singletons_mode_and_clean_stop(self):
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        from masterquo.runtime import Runtime
        from masterquo.secrets_store import SecretStore
        td = TempData()
        before = {t.ident for t in threading.enumerate()}
        rt = None
        try:
            rt = Runtime(demo=True)
            self.assertEqual([t.name for t in threading.enumerate() if t.ident not in before], [], "wątki uruchomione w __init__")
            cfgs, secs, dbs = set(), set(), {}
            for svc in [rt] + [v for v in vars(rt).values() if hasattr(v, "__dict__") and not isinstance(v, type)]:
                for v in list(vars(svc).values()):
                    if isinstance(v, ConfigStore):
                        cfgs.add(id(v))
                    elif isinstance(v, SecretStore):
                        secs.add(id(v))
                    elif isinstance(v, Database):
                        dbs.setdefault(str(v.path), set()).add(id(v))
            self.assertEqual(cfgs, {id(rt.cfg)})
            self.assertEqual(secs, {id(rt.secrets)})
            self.assertEqual({k: len(v) for k, v in dbs.items() if len(v) > 1}, {}, "więcej niż 1 Database na plik")
            self.assertIs(rt.bridge.cfg_store, rt.cfg)
            self.assertEqual(rt.modes.mode, rt.cfg.get().execution.mode)        # the start never lands in another mode (PAPER by default)
            self.assertNotEqual(rt.modes.mode, "AUTO_LIVE")
            rt.start()
            rt.stop()
            _env.wait_for(lambda: not [t for t in threading.enumerate() if t.ident not in before and not t.daemon and t.is_alive()], 20)
            self.assertEqual([t.name for t in threading.enumerate() if t.ident not in before and not t.daemon and t.is_alive()], [])
        finally:
            if rt is not None:
                try:
                    rt.stop()
                except Exception as exc:  # noqa: BLE001 - a second stop after a failed assertion: report only
                    print(f"stop: {exc}")
            td.close()


# ============================================================================================ I0047 shared data-quality checks (parity)
def _legacy_assess_tf(tf, bars, required, now, offset, session, market_open, symbol):
    """assess_tf of HEAD before I0047 (verbatim) - the oracle for the refactor."""
    from masterquo.data.quality import FIX_HISTORY, _finite
    from masterquo.timeutil import TF_SECONDS, from_epoch
    sec = TF_SECONDS[tf]
    reasons = []
    closed = [b for b in bars if b["closed"]]
    invalid = [b["t_raw"] for b in bars if not (_finite(b["o"], b["h"], b["l"], b["c"]) and b["l"] > 0
                                                and b["l"] <= min(b["o"], b["c"]) <= max(b["o"], b["c"]) <= b["h"])]
    neg_vol = [b["t_raw"] for b in bars if b["tv"] < 0]
    raws = [b["t_raw"] for b in bars]
    dups = len(raws) - len(set(raws))
    nonmono = sum(1 for a, b in zip(raws, raws[1:]) if b <= a)  # noqa: RUF007 - verbatim legacy code (oracle)
    gaps = []
    for a, b in zip(bars, bars[1:]):  # noqa: RUF007 - verbatim legacy code (oracle)
        if tf == "D1":
            continue
        step = b["t_raw"] - a["t_raw"]
        if step > sec:
            kind = session.classify_gap(a["t_raw"], b["t_raw"], sec)
            gaps.append({"from_raw": a["t_raw"] + sec, "to_raw": b["t_raw"], "missing_bars": step // sec - 1, "kind": kind})
    recent_cut = bars[-30]["t_raw"] if len(bars) >= 30 else (bars[0]["t_raw"] if bars else 0)
    recent_unexplained = [g for g in gaps if g["kind"] == "UNEXPLAINED" and g["to_raw"] >= recent_cut]
    future = []
    if offset is not None:
        future = [b["t_raw"] for b in bars if from_epoch(b["t_raw"] - offset) > now + timedelta(seconds=60)]
    status = "OK"
    if not bars:
        status = "NO_DATA"
        reasons.append("NO_BARS_FROM_TERMINAL")
    elif invalid or neg_vol or dups or nonmono:
        status = "INVALID"
        reasons += (["INVALID_OHLC"] if invalid else []) + (["NEGATIVE_TICK_VOLUME"] if neg_vol else []) + \
                   (["DUPLICATE_BARS"] if dups else []) + (["NON_MONOTONIC_BARS"] if nonmono else [])
    elif future:
        status = "TIME_ERROR"
        reasons.append("FUTURE_BAR_TIMESTAMP")
    elif len(closed) < required:
        status = "INSUFFICIENT_HISTORY"
        reasons.append(f"CLOSED_BARS_{len(closed)}_LT_REQUIRED_{required}")
    stale = False
    if bars and offset is not None and market_open:
        forming_open = from_epoch(bars[-1]["t_raw"] - offset)
        age = (now - forming_open).total_seconds()
        if age > sec + 180:
            stale = True
            reasons.append("BARS_NOT_UPDATING")
            if status == "OK":
                status = "STALE"
    if recent_unexplained:
        reasons.append("RECENT_UNEXPLAINED_GAP")
        if status == "OK":
            status = "DEGRADED"
    hint = FIX_HISTORY.format(sym=symbol, tf=tf) if status in ("INSUFFICIENT_HISTORY", "NO_DATA") else None
    return {"tf": tf, "status": status, "closed_bars": len(closed), "required": required, "bars_total": len(bars),
            "last_closed_raw": closed[-1]["t_raw"] if closed else None,
            "last_closed_available_at": closed[-1].get("available_at") if closed else None,
            "forming_open_raw": bars[-1]["t_raw"] if bars and not bars[-1]["closed"] else None,
            "invalid_bars": len(invalid), "duplicates": dups, "non_monotonic": nonmono, "future_bars": len(future),
            "gaps": gaps[-10:], "gap_counts": dict(Counter(g["kind"] for g in gaps)), "stale": stale,
            "reasons": reasons, "fix_hint": hint}


def _legacy_sh_data_quality(bars, quote, now, cfg):
    """sh/context.data_quality of HEAD before I0047 (verbatim)."""
    from masterquo.sh.context import TF_S, _ts
    issues, ages = [], {}
    for tf, bs in bars.items():
        if not bs:
            issues.append(f"{tf}: brak świec")
            continue
        ts = [_ts(b["open_utc"]) for b in bs[-60:]]
        if any(b2 <= b1 for b1, b2 in zip(ts, ts[1:])):  # noqa: RUF007 - verbatim legacy code (oracle)
            issues.append(f"{tf}: świece nieuporządkowane lub zdublowane")
        if any(not all(math.isfinite(float(b[k])) for k in ("o", "h", "l", "c")) or b["h"] < b["l"] for b in bs[-50:]):
            issues.append(f"{tf}: NaN/inf lub błędna geometria")
        close_t = ts[-1] + TF_S.get(tf, 60)
        ages[tf] = round(now - close_t, 1)
        if close_t > now + 1:
            issues.append(f"{tf}: ostatnia świeca nie jest zamknięta (forming) – odrzucona")
        elif now - close_t > cfg["max_bar_age_s"].get(tf, 3 * TF_S.get(tf, 60)):
            issues.append(f"{tf}: dane nieaktualne ({now - close_t:.0f} s od zamknięcia)")
    q_age = None
    spread = None
    if not quote:
        issues.append("brak notowania Bid/Ask")
    else:
        try:
            qt = float(quote.get("time") or 0.0)
        except (TypeError, ValueError):
            qt = 0.0
        spread = float(quote["ask"]) - float(quote["bid"])
        if not (math.isfinite(qt) and qt > 0):
            issues.append("brak znacznika czasu notowania")
        else:
            q_age = round(now - qt, 2)
            if q_age > cfg["max_quote_age_s"]:
                issues.append(f"notowanie nieaktualne ({q_age:.1f} s)")
        if spread < 0:
            issues.append("Ask < Bid")
        elif cfg.get("max_spread_usd") is not None and spread > cfg["max_spread_usd"]:
            issues.append(f"spread {spread:.3f} > limit {cfg['max_spread_usd']:.3f} USD")
    return {"status": "OK" if not issues else "BLOCK", "issues": issues, "bar_age_s": ages, "quote_age_s": q_age, "spread": spread}


def _outcome(fn, *a):
    try:
        return ("ok", fn(*a))
    except Exception as exc:  # noqa: BLE001 - the exception type and text are part of the parity
        return ("raise", type(exc).__name__, str(exc))


BAD_VALUES = (float("nan"), float("inf"), -1.0, 0.0, "2400.5", "abc", None, True)


def _series(rnd, n, step, t0, *, faults=True):
    out, t = [], t0
    for i in range(n):
        t += step * (1 if not faults or rnd.random() > 0.08 else rnd.choice((0, -1, 2, 3, 30, 90)))
        o = 2400 + rnd.uniform(-5, 5)
        c = o + rnd.uniform(-2, 2)
        h, lo = max(o, c) + rnd.uniform(0, 1), min(o, c) - rnd.uniform(0, 1)
        b = {"t_raw": t, "o": o, "h": h, "l": lo, "c": c, "tv": rnd.choice((0, 5, 100)), "closed": True, "available_at": None}
        if faults and rnd.random() < 0.05:
            b[rnd.choice(("o", "h", "l", "c"))] = rnd.choice(BAD_VALUES)
        if faults and rnd.random() < 0.04:
            b["c"], b["h"] = (b["h"] + 1, b["h"]) if isinstance(b["h"], float) else (b["c"], b["h"])     # close > high (dq_compare)
        if faults and rnd.random() < 0.02:
            b["tv"] = -1
        out.append(b)
    if out and rnd.random() < 0.5:
        out[-1]["closed"] = False
    return out


class TestDqCoreParity(unittest.TestCase):
    def test_shared_checks_exist(self):
        from masterquo.data import quality as Q
        for name in ("ohlc_finite", "geometry_ok", "order_violations", "duplicate_count", "find_gaps"):
            self.assertTrue(callable(getattr(Q, name, None)), name)

    def test_active_assess_tf_same_as_before(self):
        from masterquo.data import quality as Q
        rnd = random.Random(146)
        n_cases = 0
        for case in range(400):
            tf = rnd.choice(("M1", "M5", "M15", "H1", "H4", "D1"))
            sec = Q.TF_SECONDS[tf]
            t0 = 1_793_000_000 // sec * sec + rnd.choice((0, 86400 * 2, 86400 * 5))
            bars = _series(rnd, rnd.choice((0, 1, 5, 40, 120)), sec, t0, faults=case % 4 != 0)
            h1 = [t0 - 3600 * k for k in range(rnd.choice((0, 50, 400))) if (t0 - 3600 * k) % 86400 // 3600 != 22]
            session = Q.SessionModel(h1)
            now = datetime.fromtimestamp(t0 + len(bars) * sec + rnd.choice((0, 30, 600, 7200)), UTC)
            offset = rnd.choice((None, 0, 7200, 10800))
            args = (tf, bars, rnd.choice((0, 30, 300)), now, offset, session, rnd.random() < 0.7, "XAUUSD-")
            self.assertEqual(_outcome(Q.assess_tf, *args), _outcome(_legacy_assess_tf, *args), f"case {case}")
            n_cases += 1
        self.assertEqual(n_cases, 400)

    def test_dq_compare_scenarios(self):
        """The scenarios of the ETAP1 comparison (close > high 30 / 100 bars back, 20-min gap) - both gates exactly as before."""
        from masterquo.data import quality as Q
        from masterquo.sh import context as SC
        t0 = 1_795_000_000 // 60 * 60
        base = [{"t_raw": t0 + 60 * i, "o": 2400.0, "h": 2401.0, "l": 2399.0, "c": 2400.5, "tv": 10, "closed": True} for i in range(200)]
        sess = Q.SessionModel([])
        now = datetime.fromtimestamp(t0 + 200 * 60, UTC)
        for back in (30, 100):
            bars = [dict(b) for b in base]
            bars[-back]["c"] = bars[-back]["h"] + 1.0
            r = Q.assess_tf("M1", bars, 100, now, 0, sess, True, "X")
            self.assertEqual(r, _legacy_assess_tf("M1", bars, 100, now, 0, sess, True, "X"))
            self.assertEqual(r["status"], "INVALID")
            shb = {"M1": [dict(b, open_utc=b["t_raw"]) for b in bars]}
            cfg = {"max_bar_age_s": {"M1": 150}, "max_quote_age_s": 5.0, "max_spread_usd": None}
            q = {"bid": 2400.0, "ask": 2400.2, "time": t0 + 200 * 60}
            self.assertEqual(SC.data_quality(shb, q, t0 + 200 * 60, cfg), _legacy_sh_data_quality(shb, q, t0 + 200 * 60, cfg))
            self.assertEqual(SC.data_quality(shb, q, t0 + 200 * 60, cfg)["status"], "OK")     # SH policy: h >= l only (unchanged, O7)
        gap = base[:190] + [dict(b, t_raw=b["t_raw"] + 1200) for b in base[190:]]          # 20-min unexplained gap 10 bars back
        sess5 = Q.SessionModel([t0 - 3600 * k for k in range(24 * 10)])
        for s_ in (sess, sess5):
            r = Q.assess_tf("M1", gap, 100, now + timedelta(seconds=1200), 0, s_, True, "X")
            self.assertEqual(r, _legacy_assess_tf("M1", gap, 100, now + timedelta(seconds=1200), 0, s_, True, "X"))
        self.assertEqual(r["status"], "DEGRADED")
        self.assertIn("RECENT_UNEXPLAINED_GAP", r["reasons"])

    def test_sh_data_quality_same_as_before(self):
        from masterquo.sh import context as SC
        rnd = random.Random(7)
        for case in range(500):
            bars = {}
            for tf, sec in (("M1", 60), ("M5", 300), ("M15", 900), ("H1", 3600)):
                if rnd.random() < 0.15:
                    bars[tf] = []
                    continue
                t0 = 1_795_000_000 // sec * sec
                ser = _series(rnd, rnd.choice((1, 20, 70)), sec, t0, faults=case % 3 != 0)
                bars[tf] = [dict(b, open_utc=rnd.choice((b["t_raw"], datetime.fromtimestamp(b["t_raw"], UTC).isoformat().replace("+00:00", "Z"))))
                            for b in ser]
            now = 1_795_000_000 + rnd.choice((60 * 70, 3600 * 30, 300 * 75))
            quote = rnd.choice((None, {}, {"bid": 2400.0, "ask": 2400.3, "time": now - rnd.choice((0, 1, 9))}, {"bid": 2401.0, "ask": 2400.0, "time": "x"},
                                {"bid": 2400.0, "ask": 2400.5}))
            cfg = {"max_bar_age_s": {"M1": 150, "M5": 600}, "max_quote_age_s": 5.0, "max_spread_usd": rnd.choice((None, 0.25))}
            self.assertEqual(_outcome(SC.data_quality, bars, quote, now, cfg), _outcome(_legacy_sh_data_quality, bars, quote, now, cfg), f"case {case}")


# ============================================================================================ I0051 one offline gap classifier (parity)
def _legacy_md_classify_gaps(times, step):
    """marketdata/quality.classify_gaps of HEAD before I0051 (verbatim)."""
    from masterquo.marketdata.store import iso
    gaps = []
    for a, b in zip(times, times[1:]):  # noqa: RUF007 - verbatim legacy code (oracle)
        if b - a > step:
            gaps.append((a, b))
    days = {datetime.fromtimestamp(t, timezone.utc).date() for t in times}  # noqa: UP017 - verbatim legacy code (oracle)
    starts = Counter(((a + step) % 86400) // step * step for a, b in gaps if b - a <= 3 * 3600 + step and (b - a) // step - 1 > 3)
    recurring = {k for k, v in starts.items() if days and v >= max(3, 0.3 * len(days))}
    out = {"WEEKEND": 0, "SESSION_BREAK": 0, "NO_TICKS_SHORT": 0, "MISSING": 0, "missing_bars": 0, "missing_list": [],
           "session_break_times_utc": sorted(f"{k // 3600:02d}:{k % 3600 // 60:02d}" for k in recurring)}
    for a, b in gaps:
        miss = (b - a) // step - 1
        da, db = datetime.fromtimestamp(a, timezone.utc), datetime.fromtimestamp(b, timezone.utc)  # noqa: UP017 - verbatim legacy code (oracle)
        covers_sat = any((datetime.fromtimestamp(a + k * 3600, timezone.utc)).weekday() == 5 for k in range(0, int((b - a) // 3600) + 1))  # noqa: PIE808, UP017 - verbatim legacy code (oracle)
        if covers_sat and b - a >= 20 * 3600:
            out["WEEKEND"] += 1
        elif ((a + step) % 86400) // step * step in recurring and b - a <= 3 * 3600 + step:
            out["SESSION_BREAK"] += 1
        elif miss <= 3:
            out["NO_TICKS_SHORT"] += 1
        else:
            out["MISSING"] += 1
            out["missing_bars"] += int(miss)
            if len(out["missing_list"]) < 100:
                out["missing_list"].append({"after_utc": iso(a), "next_utc": iso(b), "missing_bars": int(miss), "weekday": da.strftime("%a"),
                                            "next_weekday": db.strftime("%a")})
    return out


def _legacy_export_gaps(times, step):
    """forecast/export._gaps of HEAD before I0051 (verbatim)."""
    from masterquo.timeutil import iso
    out = {"weekend": 0, "daily_break_le_2h": 0, "other": 0, "other_list": []}
    for a, b in zip(times, times[1:]):  # noqa: RUF007 - verbatim legacy code (oracle)
        if b - a == step:
            continue
        da, db = datetime.fromtimestamp(a, timezone.utc), datetime.fromtimestamp(b, timezone.utc)  # noqa: UP017 - verbatim legacy code (oracle)
        if db - da >= timedelta(hours=40) and any((da + timedelta(days=k)).weekday() == 5 for k in range((db - da).days + 1)):
            out["weekend"] += 1
        elif b - a <= 2 * 3600 + step:
            out["daily_break_le_2h"] += 1
        else:
            out["other"] += 1
            if len(out["other_list"]) < 60:
                out["other_list"].append({"after_utc": iso(da), "next_utc": iso(db), "missing_bars": (b - a) // step - 1})
    return out


def _gap_fixture(rnd, step, days=21, break_h=None, break_len_h=1, holes=3):
    t0 = 1_793_000_000 // 86400 * 86400 - rnd.randrange(7) * 86400
    out = []
    for d in range(days):
        day0 = t0 + d * 86400
        wd = datetime.fromtimestamp(day0, UTC).weekday()
        if wd == 5 or (wd == 6 and rnd.random() < 0.8) or (wd == 4 and rnd.random() < 0.2):
            continue
        for k in range(86400 // step):
            t = day0 + k * step
            if break_h is not None and break_h * 3600 <= t - day0 < (break_h + break_len_h) * 3600:
                continue
            out.append(t)
    for _ in range(holes):
        if len(out) > 10:
            i = rnd.randrange(len(out) - 10)
            del out[i:i + rnd.choice((1, 2, 4, 8, 30, 70))]
    return out


class TestGapClassifierParity(unittest.TestCase):
    def test_shared_classifier_exists(self):
        from masterquo.data import quality as Q
        self.assertTrue(callable(getattr(Q, "classify_gap_series", None)))

    def test_both_reports_same_as_before(self):
        from masterquo.forecast import export as EX
        from masterquo.marketdata import quality as MQ
        rnd = random.Random(51)
        n = 0
        for step in (60, 300, 900, 1800, 3600):
            for _ in range(12):
                times = _gap_fixture(rnd, step, break_h=rnd.choice((None, 21, 22, 23, 0)), break_len_h=rnd.choice((1, 2, 3)),
                                     holes=rnd.choice((0, 3, 10)))
                self.assertEqual(MQ.classify_gaps(times, step), _legacy_md_classify_gaps(times, step))
                self.assertEqual(EX._gaps(times, step), _legacy_export_gaps(times, step))
                n += 1
        self.assertEqual(n, 60)

    def test_irregular_inputs_same_as_before(self):
        """Unsorted / duplicated / misaligned times: the export rule counts every distance != step (also 0 and negative)."""
        from masterquo.forecast import export as EX
        from masterquo.marketdata import quality as MQ
        rnd = random.Random(3)
        for _ in range(200):
            step = rnd.choice((60, 300, 3600))
            t = 1_793_000_000
            times = []
            for _k in range(rnd.choice((0, 1, 2, 50, 300))):
                t += rnd.choice((step, step, step, 0, -step, step * 2, step * 5, 7 * 3600, 50 * 3600, step + 7))
                times.append(t)
            self.assertEqual(EX._gaps(times, step), _legacy_export_gaps(times, step))
            self.assertEqual(MQ.classify_gaps(times, step), _legacy_md_classify_gaps(times, step))


# ============================================================================================ I0126 dead frontend code
class TestFrontendDeadExports(unittest.TestCase):
    NAMES = ("useChartOpts", "ChartToolbar", "migrateLegacyViews", "stopZones", "exportTheme", "fmtMoney", "reasonPl", "REASON_PL")

    def test_removed(self):
        import re
        src = ROOT / "frontend" / "src"
        self.assertFalse((src / "components" / "ChartToolbar.tsx").exists())
        found = []
        for p in list(src.rglob("*.ts")) + list(src.rglob("*.tsx")):
            t = p.read_text(encoding="utf-8")
            found += [(p.name, n) for n in self.NAMES if re.search(r"export\s+(?:default\s+)?(?:function|const|let|class)\s+" + n + r"\b", t)]
        self.assertEqual(found, [])
        self.assertIn("export function parseThemeFile", (src / "theme.tsx").read_text(encoding="utf-8"))   # used by tests/js


# ============================================================================================ I0328 chart card probabilities per plan (JS)
class TestChartCardProbabilitiesPerPlan(unittest.TestCase):
    def test_charts_adapters_js(self):
        if not shutil.which("node"):
            self.skipTest("node not installed")
        r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", str(ROOT / "tests" / "js" / "charts_adapters.test.mjs")],
                           capture_output=True, text=True, timeout=120, check=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_card_never_asks_the_instrument_list(self):
        src = (ROOT / "frontend" / "src" / "features" / "forex" / "screens" / "charts" / "chartsData.ts").read_text(encoding="utf-8")
        calls = r"(?:\bg|apiGet<any>|get)\(\s*[`\"]"
        self.assertNotRegex(src, calls + r"/api/v1/models/predictions")
        self.assertNotRegex(src, calls + r"/api/v1/ml/predict")      # it writes a prediction into the ML drift sample - never from the panel
        self.assertRegex(src, calls + r"/api/v1/sh/signals/\$\{")


if __name__ == "__main__":
    unittest.main()
