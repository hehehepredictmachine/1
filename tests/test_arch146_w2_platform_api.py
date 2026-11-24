"""Fala 2b, grupa „platform_api” (config/paths, api/app.py, api/wf32_routes.py, runtime.py, punkty wejścia CLI, desktop/).

Testy bez sieci, bez MT5 (FakeMT5 albo atrapy), osobny folder danych na test. Każda klasa odpowiada pozycji (klucz w nazwie/docstringu)."""
from __future__ import annotations

import ast
import json
import types
import unittest
from pathlib import Path
from unittest import mock

import _env  # noqa: F401
from _env import TempData

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "backend" / "masterquo"
PORT = 18791


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


# ------------------------------------------------------------------------------------------------------------------------- I0420
class TestBookRecordDescription(unittest.TestCase):
    """I0420: opis pola indicators.book_record wskazuje rzeczywisty plik (indicators.sqlite, tabela book_snapshots)."""

    def test_description_points_to_indicators_sqlite(self):
        from masterquo.config import IndicatorsConfig
        f = IndicatorsConfig.model_fields["book_record"]
        self.assertIn("indicators.sqlite", f.description)
        self.assertIn("book_snapshots", f.description)
        self.assertNotIn("book.sqlite", f.description.replace("indicators.sqlite", ""))
        self.assertIs(f.default, True)                          # klucz i wartość domyślna bez zmian

    def test_indicators_service_really_writes_there(self):
        src = (PKG / "indicators" / "service.py").read_text(encoding="utf-8")
        self.assertIn("indicators.sqlite", src)
        self.assertIn("book_snapshots", src)


# ------------------------------------------------------------------------------------------------------------------------- I0122
class TestConfigDefaultsSingleSource(_Base):
    """I0122: wartości domyślne = modele pydantic (AppConfig); martwa gałąź config/masterquo.defaults.json usunięta."""

    def test_no_defaults_file_reference(self):
        from masterquo import config, paths
        self.assertNotIn("masterquo.defaults.json", config.__doc__ or "")
        self.assertFalse(hasattr(paths, "DEFAULTS_FILE"))
        self.assertNotIn("DEFAULTS_FILE", (PKG / "config.py").read_text(encoding="utf-8"))

    def test_first_start_writes_appconfig_defaults(self):
        from masterquo.config import AppConfig, ConfigStore
        p = Path(self.td.dir) / "sub" / "config.json"
        st = ConfigStore(path=p)
        self.assertTrue(p.exists())
        self.assertEqual(json.loads(p.read_text(encoding="utf-8")), AppConfig().model_dump(mode="json"))
        self.assertEqual(st.get().model_dump(mode="json"), AppConfig().model_dump(mode="json"))


# ------------------------------------------------------------------------------------------------------------------------- I0852
class TestStrategyToggleDefaultTrade(_Base):
    """I0852: POST /api/v1/strategy/toggle bez zapisanego przełącznika – domyślne trade jak trade_allowed (S11/S12 tylko sygnały)."""

    def _call(self, strategies: dict, body: dict):
        from masterquo.api import app as A
        from masterquo.config import ConfigStore
        from masterquo.engine.active import trade_allowed
        p = Path(self.td.dir) / "config.json"
        store = ConfigStore(path=p)
        raw = store.get().model_dump(mode="json")
        raw["active"]["strategies"] = strategies
        p.write_text(json.dumps(raw), encoding="utf-8")
        store = ConfigStore(path=p)
        rt = make_rt(cfg=store)
        rt.engine.active.status.return_value = {"ok": True}
        fn = ep(A.create_app(rt, PORT), "POST", "/api/v1/strategy/toggle")
        fn(A.StrategyToggleReq(**body))
        act = store.get().active
        return act.strategies[body["strategy_id"]], trade_allowed(act, body["strategy_id"])

    def test_scan_only_toggle_keeps_s11_signal_only(self):
        for sid in ("S11", "S12"):
            tg, allowed = self._call({}, {"strategy_id": sid, "scan": True})
            self.assertEqual((tg.scan, tg.trade, allowed), (True, False, False), sid)     # HEAD: trade=True -> S11/S12 zaczynają handlować

    def test_other_strategies_and_explicit_trade_unchanged(self):
        tg, allowed = self._call({}, {"strategy_id": "S03", "scan": False})
        self.assertEqual((tg.scan, tg.trade, allowed), (False, True, True))                # S01-S10: jak dziś (True)
        tg, allowed = self._call({}, {"strategy_id": "S11", "trade": True})
        self.assertEqual((tg.scan, tg.trade, allowed), (True, True, True))                 # jawne trade=True honorowane
        tg, _ = self._call({"S12": {"scan": False, "trade": True}}, {"strategy_id": "S12", "scan": True})
        self.assertEqual((tg.scan, tg.trade), (True, True))                                # zapisany przełącznik bez zmian


# ------------------------------------------------------------------------------------------------------------------- I0080 / I0075
def _imports(path: Path) -> list[tuple[str, tuple[str, ...]]]:
    """(resolved module, imported names) of every import in a backend module (relative imports resolved to masterquo.*)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    pkg_parts = list(path.relative_to(PKG.parent).with_suffix("").parts[:-1])
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            if n.level:
                base = pkg_parts[: len(pkg_parts) - (n.level - 1)]
                mod = ".".join(base + ([n.module] if n.module else []))
            else:
                mod = n.module or ""
            out.append((mod, tuple(a.name for a in n.names)))
        elif isinstance(n, ast.Import):
            out.extend((a.name, ()) for a in n.names)
    return out


class TestLocalApiLeaf(unittest.TestCase):
    """I0080: pomocniki lokalnego API w jednym liściu masterquo/localapi.py; punkty wejścia nie importują się nawzajem.
    I0075: runner/diagnostyka nie importują klienta HTTP z modułu zgodności train_all; poprawione docstringi."""

    def test_no_entry_point_imports_entry_points(self):
        bad = []
        for f in PKG.rglob("*.py"):
            if f.name == "__main__.py" and f.parent == PKG:
                continue
            for mod, names in _imports(f):
                if mod == "masterquo.__main__":
                    bad.append(f"{f.relative_to(PKG)}: {mod} {names}")
                if mod == "masterquo.train_all" and set(names) & {"Bot", "_health"}:
                    bad.append(f"{f.relative_to(PKG)}: {mod} {names}")
        self.assertEqual(bad, [])

    def test_leaf_has_only_stdlib_at_module_level(self):
        tree = ast.parse((PKG / "localapi.py").read_text(encoding="utf-8"))
        for n in tree.body:
            if isinstance(n, ast.ImportFrom):
                self.assertTrue(n.level == 0 and not (n.module or "").startswith("masterquo"), n.module)
            elif isinstance(n, ast.Import):
                self.assertFalse(any(a.name.startswith("masterquo") for a in n.names))

    def test_old_names_are_aliases(self):
        from masterquo import __main__ as M
        from masterquo import localapi, train_all
        self.assertIs(M._port, localapi.port)
        self.assertIs(train_all.Bot, localapi.Bot)

    def test_callers_keep_their_timeouts(self):
        from masterquo import __main__ as M
        from masterquo import localapi, train_all
        from masterquo.studio import app as studio_app
        seen = []

        def fake_urlopen(req, timeout=None):
            seen.append(timeout)
            raise OSError("refused")
        with mock.patch("urllib.request.urlopen", fake_urlopen):
            self.assertIsNone(M._health(1))
            self.assertIsNone(M._health(1, 0.8))
            self.assertIsNone(train_all._health(1))
            self.assertIsNone(studio_app._bot_health(1))
            self.assertIsNone(localapi.health(1))
        self.assertEqual(seen, [1.5, 0.8, 3, 2, 1.5])

    def test_health_none_on_any_failure_and_dict_on_success(self):
        import http.client
        import io

        from masterquo import localapi

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        for exc in (OSError("x"), ValueError("x"), http.client.IncompleteRead(b"")):
            with mock.patch("urllib.request.urlopen", side_effect=exc):
                self.assertIsNone(localapi.health(1))
        with mock.patch("urllib.request.urlopen", return_value=Resp(b"<html>")):
            self.assertIsNone(localapi.health(1))
        with mock.patch("urllib.request.urlopen", return_value=Resp(b'{"app": "x"}')) as m:
            self.assertEqual(localapi.health(5, 0.5), {"app": "x"})
        req = m.call_args[0][0]
        self.assertEqual((req.full_url, req.get_header("Host")), ("http://127.0.0.1:5/api/v1/health", "127.0.0.1:5"))

    def test_docstrings_fixed(self):
        from masterquo import train_all
        from masterquo.training import cli
        self.assertNotIn("DYAGNOSTYKA", cli.__doc__)
        self.assertIn("DIAGNOSTYKA_TRENINGU.bat", cli.__doc__)
        self.assertIn("indicator_context", train_all.__doc__)
        self.assertNotIn("(22_TRENUJ_WSZYSTKIE_MODELE.bat) - compatibility", train_all.__doc__)


# ------------------------------------------------------------------------------------------------------------------------- I0081
class _TrackLock:
    """RLock that records whether it is held (to prove the deals copy is taken under it and the ROI is counted outside it)."""

    def __init__(self):
        import threading
        self._l = threading.RLock()
        self.depth = 0
        self.max_depth = 0

    def __enter__(self):
        self._l.acquire()
        self.depth += 1
        self.max_depth = max(self.max_depth, self.depth)
        return self

    def __exit__(self, *a):
        self.depth -= 1
        self._l.release()
        return False


class _SnapDB:
    def __init__(self, snaps=()):
        self.snaps = list(snaps)

    def query(self, sql, args=()):
        if "FROM equity_snapshots" in sql:
            return [r for r in self.snaps if r["account_key"] == args[0] and r["ts"] >= args[-1]]
        return []


class TestAccountRoiOneFunction(_Base):
    """I0081: wf32_routes nie importuje api.app (cykl); body_num w api/common.py, deals_coverage_from_utc w stats.py; ROI konta liczone
    jedną funkcją stats.account_roi_for_bridge w GET /api/v1/stats i w raporcie Telegram (wynik identyczny z dotychczasowym inline)."""

    def _bridge(self, days=7, loaded=True, deals=None):
        from datetime import timedelta

        from masterquo.timeutil import utcnow
        now = utcnow()
        lock = _TrackLock()

        class B:
            def __init__(self):
                self._lock = lock
                self._deals = list(deals or [])
                self.deals_loaded_at = now if loaded else None
                self.account_key = "Broker:1"
                self.cfg = types.SimpleNamespace(deals_history_days=days, symbol="XAUUSD-")
                self.clock = types.SimpleNamespace(offset=0.0)
                self.reads_outside = 0

            @property
            def deals(self):
                if lock.depth == 0:
                    self.reads_outside += 1
                return self._deals

            def server_day_start_utc(self):
                return None

            def account_status(self):
                return {"currency": "USD"}
        b = B()
        b._now = now
        b._td = timedelta
        return b

    def _db(self, b):
        from masterquo.timeutil import iso
        now, td = b._now, b._td
        return _SnapDB([{"account_key": "Broker:1", "ts": iso(now - td(days=25)), "equity": 1000.0},
                        {"account_key": "Broker:1", "ts": iso(now - td(days=5)), "equity": 2000.0},
                        {"account_key": "Broker:1", "ts": iso(now - td(minutes=1)), "equity": 2000.0}])

    def test_wf32_routes_does_not_import_api_app(self):
        mods = [m for m, _ in _imports(PKG / "api" / "wf32_routes.py")]
        self.assertNotIn("masterquo.api.app", mods)

    def test_helpers_moved_and_reexported(self):
        from masterquo import stats
        from masterquo.api import app as A
        from masterquo.api import common
        self.assertIs(A.body_num, common.body_num)
        self.assertIs(A.deals_coverage_from_utc, stats.deals_coverage_from_utc)

    def test_one_function_matches_previous_inline_result(self):
        from masterquo import stats
        for days, loaded in ((7, True), (60, True), (7, False)):
            b = self._bridge(days=days, loaded=loaded)
            db = self._db(b)
            with b._lock:
                deals, cover = list(b.deals), stats.deals_coverage_from_utc(b)
            want30 = stats.account_roi(db, b.account_key, deals, b.clock.offset, deals_from_utc=cover)
            want10 = stats.account_roi(db, b.account_key, deals, b.clock.offset, days=10, deals_from_utc=cover)
            self.assertEqual(stats.account_roi_for_bridge(db, b), want30)
            self.assertEqual(stats.account_roi_for_bridge(db, b, days=None), want30)       # None -> 30 (jak dziś), nigdy timedelta(None)
            self.assertEqual(stats.account_roi_for_bridge(db, b, days=10), want10)

    def test_copy_under_one_lock_roi_outside_it(self):
        from masterquo import stats
        b = self._bridge()
        db = self._db(b)
        real = stats.account_roi
        depth_at_roi = []

        def spy(*a, **k):
            depth_at_roi.append(b._lock.depth)
            return real(*a, **k)
        with mock.patch.object(stats, "account_roi", spy):
            stats.account_roi_for_bridge(db, b)
        self.assertEqual(depth_at_roi, [0])                       # liczone poza blokadą
        self.assertEqual((b.reads_outside, b._lock.max_depth), (0, 1))   # deals czytane pod jedną blokadą, bez zagnieżdżeń

    def test_routes_use_it_and_answers_are_unchanged(self):
        from fastapi import FastAPI
        from masterquo import stats
        from masterquo.api import app as A
        from masterquo.api import wf32_routes
        b = self._bridge()
        db = self._db(b)
        rt = make_rt(bridge=b, db=db)
        app = A.create_app(rt, PORT)
        with mock.patch.multiple("masterquo.stats", bot_stats=mock.DEFAULT, engine_stats=mock.DEFAULT, equity_curve=mock.DEFAULT,
                                 account_stats=mock.DEFAULT) as m:
            for v in m.values():
                v.return_value = {}
            with mock.patch.object(stats, "account_roi_for_bridge", wraps=stats.account_roi_for_bridge) as w:
                r = ep(app, "GET", "/api/v1/stats")(mode="PAPER")["account_roi"]
        self.assertEqual(w.call_count, 1)
        self.assertEqual((r["status"], r["roi_pct"], r["deals_coverage"], r["period_clipped_to_deal_history"]), ("OK", 0.0, "VERIFIED", True))
        rt2 = types.SimpleNamespace(bridge=None, baskets=None, cfg=None, db=db, telegram=None)
        app2 = FastAPI()
        wf32_routes.register(app2, rt2)
        rt2.bridge = b
        with mock.patch.object(stats, "account_roi_for_bridge", wraps=stats.account_roi_for_bridge) as w:
            t = app2.state.wf32["acct_roi"](30)
        self.assertEqual(w.call_count, 1)
        self.assertEqual(t, {"roi_pct": 0.0, "status": "OK", "deals": 0, "net": 0.0, "currency": "USD"})
        self.assertEqual(b.reads_outside, 0)


# ------------------------------------------------------------------------------------------------------------------- I0089 / I0102
class TestApiUsesPublicServiceInterface(_Base):
    """I0089 (+I0102): API nie sięga do prywatnych pól usług ani do bridge._lock; runtime._wire_governor nie zna wnętrz Kronos/TSFM/TabICL
    (usługi rejestrują się same: register_with). Publiczne metody to cienkie opakowania dokładnie tych samych operacji."""

    def _api_files(self):
        return sorted((PKG / "api").glob("*.py"))

    def test_api_has_no_private_service_access(self):
        bad = []
        for f in self._api_files():
            for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if not isinstance(n, ast.Attribute):
                    continue
                v = n.value
                if n.attr.startswith("_") and not n.attr.startswith("__") and isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name) \
                        and v.value.id == "rt":
                    bad.append(f"{f.name}:{n.lineno} rt.{v.attr}.{n.attr}")
                if n.attr == "_lock" and not (isinstance(v, ast.Name) and v.id == "self"):    # own lock of an API class is fine
                    bad.append(f"{f.name}:{n.lineno} ._lock")
                if n.attr == "next_retry" and isinstance(n.ctx, ast.Store):
                    bad.append(f"{f.name}:{n.lineno} next_retry=")
        self.assertEqual(bad, [])

    def test_wire_governor_knows_no_internals(self):
        tree = ast.parse((PKG / "runtime.py").read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_wire_governor")
        priv = sorted({n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute) and n.attr.startswith("_")})
        self.assertEqual(priv, [])
        attrs = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
        self.assertFalse(attrs & {"proc", "running", "last_used", "worker", "jobs", "workers"}, attrs)

    def _gov(self):
        regs = {}
        gov = types.SimpleNamespace(register=lambda name, kind, pid, release=None, idle=None: regs.__setitem__(name, (kind, pid, release, idle)))
        return gov, regs

    def test_kronos_register_with_keeps_guards(self):
        from masterquo.kronos.service import KronosService
        gov, regs = self._gov()
        killed = []
        proc = types.SimpleNamespace(pid=11, poll=lambda: None)
        k = types.SimpleNamespace(proc=proc, running=("K", "XAUUSD", "M5"), last_used=0.0, _kill=lambda: killed.append(1))
        KronosService.register_with(k, gov)
        kind, pid, release, idle = regs["kronos"]
        self.assertEqual((kind, pid()), ("light", 11))
        self.assertFalse(release())                            # pracuje -> nie zwalniaj
        self.assertEqual(killed, [])
        self.assertEqual(idle(), 0.0)
        k.running = None
        release()
        self.assertEqual(killed, [1])                           # bezczynny -> zwolniony (leniwa ewaluacja stanu)
        k.proc = None
        self.assertIsNone(pid())

    def test_tabicl_register_with_keeps_guards(self):
        import queue

        from masterquo.quant.tabicl import TabICLService
        gov, regs = self._gov()
        killed = []
        w = types.SimpleNamespace(proc=types.SimpleNamespace(pid=7, poll=lambda: None), last_used=0.0, kill=lambda: killed.append(1) or True)
        tb = types.SimpleNamespace(worker=w, jobs=queue.Queue())
        tb.jobs.put("job")
        TabICLService.register_with(tb, gov)
        kind, pid, release, idle = regs["tabicl"]
        self.assertEqual((kind, pid()), ("heavy", 7))
        self.assertGreater(idle(), 0.0)
        self.assertFalse(release())                            # zadanie w kolejce -> nie zwalniaj
        tb.jobs.get()
        self.assertTrue(release())
        self.assertEqual(killed, [1])

    def test_tsfm_register_with_keeps_guards(self):
        from masterquo.tsfm.service import TsfmService
        gov, regs = self._gov()
        killed = []
        def mk(mid):
            return types.SimpleNamespace(proc=types.SimpleNamespace(pid=7, poll=lambda: None), last_used=0.0,
                                         kill=lambda: killed.append(mid) or True)
        svc = types.SimpleNamespace(workers={"chronos2": mk("chronos2"), "granite_ttm": mk("granite_ttm")}, running=("chronos2", "XAUUSD", "M5"))
        TsfmService.register_with(svc, gov)
        self.assertEqual((regs["chronos2"][0], regs["granite_ttm"][0]), ("heavy", "light"))
        self.assertFalse(regs["chronos2"][2]())                # ten model liczy -> nie zwalniaj
        self.assertEqual(regs["chronos2"][3](), 0.0)
        self.assertTrue(regs["granite_ttm"][2]())              # inny model -> wolno zwolnić
        svc.running = None
        self.assertTrue(regs["chronos2"][2]())
        self.assertEqual(killed, ["granite_ttm", "chronos2"])

    def test_public_wrappers_do_the_same(self):
        from masterquo.mt5.bridge import MarketBridge
        from masterquo.resources.governor import Governor
        b = MarketBridge.__new__(MarketBridge)
        b.next_retry = 99.0
        b.connect = mock.Mock(side_effect=AssertionError("connect() z wątku API"))
        MarketBridge.retry_now(b)
        self.assertEqual(b.next_retry, 0)
        b.connect.assert_not_called()
        lock = _TrackLock()
        from masterquo.timeutil import utcnow
        b = types.SimpleNamespace(_lock=lock, deals=[{"ticket": 1}], deals_loaded_at=utcnow(), cfg=types.SimpleNamespace(deals_history_days=7),
                                  account_key="A:1")
        deals, cover = MarketBridge.deals_snapshot(b)
        self.assertEqual((deals, lock.max_depth), ([{"ticket": 1}], 1))
        self.assertAlmostEqual(cover, b.deals_loaded_at.timestamp() - 7 * 86400)
        self.assertIsNot(deals, b.deals)
        self.assertEqual(MarketBridge.loaded_deals_copy(b, "A:1", check_account=True), [{"ticket": 1}])
        self.assertIsNone(MarketBridge.loaded_deals_copy(b, "B:2", check_account=True))
        b.deals_loaded_at = None
        self.assertIsNone(MarketBridge.loaded_deals_copy(b))
        g = Governor.__new__(Governor)
        g.events, g.applog = [], None
        Governor.record_event(g, "PROFILE", "x")
        self.assertEqual([(e["kind"], e["message"]) for e in g.events], [("PROFILE", "x")])

    def test_ml_reload_and_secret_use_public_methods(self):
        from masterquo.api import app as A
        rt = make_rt()
        app = A.create_app(rt, PORT)
        ep(app, "POST", "/api/v1/ml/reload")()
        rt.ml.clear_prediction_cache.assert_called_once_with()
        rt.bridge.state = "DISCONNECTED"
        ep(app, "POST", "/api/v1/secrets")(A.SecretReq(name="MT5_PASSWORD", value="x"))
        rt.bridge.retry_now.assert_called_once_with()

    def test_ml_service_clear_prediction_cache(self):
        from masterquo.ml.service import MLService
        s = types.SimpleNamespace(_pred_cache={("a",): 1})
        MLService.clear_prediction_cache(s)
        self.assertEqual(s._pred_cache, {})


# ------------------------------------------------------------------------------------------------------------------------- I0087
def _asset_tuple_literals(path: Path) -> list[int]:
    """Lines with a tuple/list/set literal of exactly the canonical instruments ('XAUUSD', 'BTC') in any order."""
    out = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    literal_args = {id(n.slice) for n in ast.walk(tree) if isinstance(n, ast.Subscript) and getattr(n.value, "id", None) == "Literal"}
    for n in ast.walk(tree):
        if id(n) in literal_args:                       # the definition CanonicalAsset = Literal["XAUUSD", "BTC"] is the source itself
            continue
        if isinstance(n, (ast.Tuple, ast.List, ast.Set)) and len(n.elts) == 2 and all(isinstance(e, ast.Constant) for e in n.elts) \
                and {e.value for e in n.elts} == {"XAUUSD", "BTC"}:
            out.append(n.lineno)
    return out


class TestInstrumentSingleSource(_Base):
    """I0087: jedna lista instrumentów handlowych w KODZIE (config.ALLOWED_ASSETS = get_args(CanonicalAsset)), zgodna z
    config/instruments_v1.json (test, nie wyliczenie w runtime); jeden walidator API zachowujący kody błędów per domena."""

    def test_allowed_assets_from_code_and_equal_to_profiles(self):
        import typing

        import mq_instruments
        from masterquo import config
        self.assertEqual(config.ALLOWED_ASSETS, typing.get_args(config.CanonicalAsset))
        self.assertEqual(config.ALLOWED_ASSETS, tuple(mq_instruments.profiles()))
        self.assertNotIn("mq_instruments", (PKG / "config.py").read_text(encoding="utf-8"))   # nie z pliku danych (fail-closed)

    def test_no_literal_lists_in_group_files(self):
        files = {"config.py": [], "api/app.py": [], "api/deps.py": [], "execution/modes.py": []}
        got = {f: _asset_tuple_literals(PKG / f) for f in files}
        self.assertEqual(got, files)

    def test_one_helper_keeps_codes_per_domain(self):
        from fastapi import HTTPException
        from masterquo.api import deps
        self.assertEqual(deps.instrument("BTC", error_code="UNKNOWN_INSTRUMENT"), "BTC")
        for bad, code, kw in (("xauusd", "UNKNOWN_INSTRUMENT", {}), ("ETH", "INSTRUMENT_NOT_ALLOWED", {"normalize": True}),
                              (5, "INSTRUMENT_NOT_ALLOWED", {"normalize": True}), (None, "UNKNOWN_INSTRUMENT", {})):
            with self.assertRaises(HTTPException) as cm:
                deps.instrument(bad, error_code=code, **kw)
            self.assertEqual((cm.exception.status_code, cm.exception.detail), (400, code))
        self.assertEqual(deps.instrument("btc", normalize=True, error_code="X"), "BTC")
        self.assertEqual(deps.instrument("", normalize=True, default=lambda: "xauusd", error_code="X"), "XAUUSD")

    def test_routes_keep_todays_behaviour(self):
        from fastapi import HTTPException
        from masterquo.api import app as A
        rt = make_rt()
        app = A.create_app(rt, PORT)
        with self.assertRaises(HTTPException) as cm:
            ep(app, "GET", "/api/v1/mm/status")(instrument="xauusd")
        self.assertEqual((cm.exception.status_code, cm.exception.detail), (400, "UNKNOWN_INSTRUMENT"))      # /mm: bez upper, jak dziś
        ep(app, "GET", "/api/v1/mm/status")(instrument="XAUUSD")
        self.assertEqual(ep(app, "GET", "/api/v1/families")(instrument="xauusd")["instrument"], "XAUUSD")   # /families: upper, jak dziś
        self.assertEqual(ep(app, "GET", "/api/v1/families")(instrument=None)["instrument"], "XAUUSD")       # domyślnie aktywny
        with self.assertRaises(HTTPException) as cm:
            ep(app, "GET", "/api/v1/families")(instrument="ETH")
        self.assertEqual(cm.exception.detail, "INSTRUMENT_INVALID")


# ------------------------------------------------------------------------------------------------------------------------- I0007
class TestProducerHorizonsAndTimeframes(_Base):
    """I0007: horyzonty i interwały tego samego producenta zgodne między rejestrami (opisy; bez wpływu na rekordy predykcji)."""

    def test_kronos_api_timeframes_match_settings(self):
        import typing

        from fastapi import HTTPException
        from masterquo.api import app as A
        from masterquo.kronos import settings as KS
        rt = make_rt()
        rt.kronos.forecast.return_value = {"ok": True}
        app = A.create_app(rt, PORT)
        for tf in typing.get_args(KS.TF):
            ep(app, "GET", "/api/v1/kronos/forecast")(instrument="XAUUSD", tf=tf)               # HEAD: M3 -> 400 TIMEFRAME_NOT_ALLOWED
        self.assertEqual([c.args for c in rt.kronos.forecast.call_args_list], [("XAUUSD", tf) for tf in typing.get_args(KS.TF)])
        with self.assertRaises(HTTPException) as cm:
            ep(app, "GET", "/api/v1/kronos/forecast")(instrument="XAUUSD", tf="H4")
        self.assertEqual(cm.exception.detail, "TIMEFRAME_NOT_ALLOWED")
        rt.kronos.history.return_value = []
        ep(app, "GET", "/api/v1/kronos/history")(instrument="BTC", tf="m3", limit=5)
        rt.kronos.history.assert_called_once_with("BTC", "M3", 5)

    def test_event_gru_horizon_is_the_label_horizon(self):
        from masterquo.modelhub.families import seq
        self.assertEqual(seq.EventGRU.HORIZONS, (2,))                                            # etykieta unit_targets(u, 2); adapter horizon_bars=2
        self.assertEqual(seq.EventGRU().capabilities()["horizons"], [2])
        src = (PKG / "quant" / "adapters.py").read_text(encoding="utf-8")
        self.assertIn('task="EVENT_UNITS_DIR3", horizon_bars=2', src)

    def test_tabular_keeps_class_attrs_and_describes_allowed_set(self):
        from masterquo.modelhub.families import tabular
        from masterquo.trainhub import features as TF
        for cls in (tabular.RF, tabular.XGB, tabular.SVM):
            self.assertEqual((cls.TF, cls.HORIZONS, cls.DATA["tf"]), ("M5", (6,), "M5"))         # atrybuty klasowe bez zmian
            cap = cls().capabilities()
            self.assertEqual((cap["tf"], cap["horizons"]), ("M5", [6]))
            self.assertEqual(cap["tf_allowed"], list(TF.HTF_OF))
            self.assertIn("paczk", cap["horizon_source"])
        summary = {"versions": [{"model_key": "TH_RF_M15_H8"}], "active": {"TH_RF_M15_H8": "v3", "TH_XGB_M1_H12": "v1"}}
        with mock.patch("masterquo.trainhub.registry.summary", return_value=summary):
            st = tabular.RF().trainhub_state("XAUUSD")
        self.assertEqual(st["active_config"], [{"model_key": "TH_RF_M15_H8", "version": "v3", "base_tf": "M15", "horizon": 8}])
        self.assertEqual((st["artifact"], st["use"]), ("CANDIDATE", "SHADOW"))                   # dotychczasowe pola bez zmian

    def test_inventory_lists_settings_timeframes(self):
        from masterquo.kronos import settings as KS
        from masterquo.quant import inventory as QI
        from masterquo.tsfm import settings as TS
        self.assertEqual(QI._OVR["kronos:Kronos-small"]["tfs"], list(KS.TF_ALL))
        for k in ("tsfm:chronos2", "tsfm:granite_ttm"):
            self.assertEqual(QI._OVR[k]["tfs"], list(TS.TF_ALL), k)


# ------------------------------------------------------------------------------------------------------------------------- I0096
class TestDbLifecycle(_Base):
    """I0096: bazy tworzone ad hoc są zamykane – GET /api/v1/training/active dla nieaktywnego instrumentu i MLRouter.switch (stara baza
    ML po old.stop() i dołączeniu wątków); baza główna i baza aktywnej usługi ML nigdy nie są zamykane; zbędne drugie migrate()."""

    def _active(self, instrument: str, ml_inst: str, store_db):
        from masterquo.api import app as A
        rt = make_rt()
        rt.ml.inst = ml_inst
        rt.lab.trainer.models.return_value = []
        app = A.create_app(rt, PORT)
        with mock.patch("masterquo.ml.router.ml_store", return_value=(store_db(rt), Path(self.td.dir))):
            r = ep(app, "GET", "/api/v1/training/active")(instrument=instrument)
        return rt, r

    def test_adhoc_db_of_inactive_instrument_is_closed(self):
        adhoc = mock.MagicMock()
        adhoc.one.return_value = {"model_id": "M-1"}
        _, r = self._active("BTC", "XAUUSD", lambda rt: adhoc)
        self.assertEqual(r["families"]["ml"], {"active": "M-1"})
        adhoc.close.assert_called_once_with()                       # HEAD: nigdy nie zamykana

    def test_main_db_is_never_closed(self):
        rt, _ = self._active("XAUUSD", "BTC", lambda rt: rt.db)      # XAUUSD = baza główna (ml_store zwraca rt.db)
        rt.db.close.assert_not_called()
        rt2, _ = self._active("BTC", "XAUUSD", lambda rt: rt.ml.cur.db)
        rt2.ml.cur.db.close.assert_not_called()

    def _router(self, old_db, main_db):
        import threading

        from masterquo.ml.router import MLRouter
        r = MLRouter.__new__(MLRouter)
        order = mock.MagicMock()
        old = types.SimpleNamespace(inst="BTC", db=old_db, _threads=[], stop=order.stop)
        old_db.close = order.close
        new = types.SimpleNamespace(inst="XAUUSD", root=Path(self.td.dir), start=mock.Mock())
        log = mock.MagicMock()
        object.__setattr__(r, "_a", (None, main_db, None, None, log))
        object.__setattr__(r, "_lock", threading.Lock())
        object.__setattr__(r, "_started", False)
        object.__setattr__(r, "cur", old)
        object.__setattr__(r, "_make", lambda inst: new)
        return r, order, new

    def test_router_switch_closes_old_db_after_stop(self):
        r, order, new = self._router(types.SimpleNamespace(), main_db=object())
        self.assertTrue(r.switch("XAUUSD"))
        self.assertIs(r.cur, new)
        self.assertEqual([c[0] for c in order.mock_calls], ["stop", "close"])   # HEAD: tylko stop

    def test_router_switch_never_closes_main_db(self):
        main = types.SimpleNamespace()
        r, order, _ = self._router(main, main_db=main)
        r.switch("XAUUSD")
        self.assertEqual([c[0] for c in order.mock_calls], ["stop"])

    def test_router_switch_skips_close_while_old_threads_live(self):
        import threading
        ev = threading.Event()
        t = threading.Thread(target=ev.wait, daemon=True)
        t.start()
        r, order, _ = self._router(types.SimpleNamespace(), main_db=object())
        r.cur._threads = [t]
        with mock.patch("masterquo.ml.router.JOIN_TIMEOUT_S", 0.2):
            r.switch("XAUUSD")
        self.assertEqual([c[0] for c in order.mock_calls], ["stop"])           # wątek nie zakończył się -> bez close
        ev.set()

    def test_cmd_import_iv_has_no_second_migrate(self):
        tree = ast.parse((PKG / "__main__.py").read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "cmd_import_iv")
        self.assertFalse([n for n in ast.walk(fn) if isinstance(n, ast.Attribute) and n.attr == "migrate"])
        from masterquo.db.database import Database
        db = Database(Path(self.td.dir) / "x.sqlite")                           # __init__ migruje bezwarunkowo
        self.assertTrue(db.one("SELECT COUNT(*) AS n FROM schema_migrations")["n"] > 0)
        self.assertEqual(db.migrate(), [])
        db.close()


# ------------------------------------------------------------------------------------------------------------------------- I0117
def _env_names_read_by_backend() -> set[str]:
    """MQ_* / PMW_* names on lines that touch os.environ / getenv in the backend (bot, runtimes of the model environments)."""
    import re
    names = set()
    for d in (PKG, PKG.parent / "kronos_runtime", PKG.parent / "tsfm_runtime"):
        for f in d.rglob("*.py"):
            for line in f.read_text(encoding="utf-8").splitlines():
                if "environ" in line or "getenv" in line:
                    names |= set(re.findall(r"\b((?:MQ|PMW)_[A-Z0-9_]+)\b", line))
    for f in (PKG.parent / "mq_instruments.py",):
        for line in f.read_text(encoding="utf-8").splitlines():
            if "environ" in line:
                names |= set(re.findall(r"\b((?:MQ|PMW)_[A-Z0-9_]+)\b", line))
    return names


class TestRuntimesRegistry(_Base):
    """I0117: jedno wyszukiwanie interpretera modeli (runtimes.py, kolejność kandydatów jak dziś), jeden domyślny budżet RAM, każda
    zmienna MQ_*/PMW_* czytana przez backend opisana w .env.example (blok generowany z rejestru)."""

    def _fake_root(self):
        root = Path(self.td.dir) / "root"
        root.mkdir()
        return root

    def test_candidates_order_unchanged_per_module(self):
        from masterquo import paths, runtimes
        from masterquo.kronos import settings as KS
        from masterquo.tsfm import settings as TS
        root = self._fake_root()
        def win(v):
            return str(root / v / "Scripts" / "python.exe")

        def nix(v):
            return str(root / v / "bin" / "python")
        with mock.patch.object(paths, "ROOT_DIR", root), mock.patch.dict("os.environ", {"MQ_KRONOS_PYTHON": "/k", "MQ_CHRONOS2_PYTHON": "/c"}):
            s = types.SimpleNamespace(python_path="/typed")
            self.assertEqual(KS.python_candidates(s), ["/k", "/typed", win(".venv_kronos"), nix(".venv_kronos")])
            self.assertEqual(TS.python_candidates("chronos2", types.SimpleNamespace(python_path=None)), ["/c", win(".venv_chronos2"), nix(".venv_chronos2")])
            self.assertEqual(TS.python_candidates("granite_ttm", types.SimpleNamespace(python_path="/g")), ["/g", win(".venv_granite"), nix(".venv_granite")])
            self.assertEqual(runtimes.python_candidates("tabicl"), [win(".venv_tabicl"), nix(".venv_tabicl")])

    def test_find_python_per_module(self):
        from masterquo import paths
        from masterquo.forecast import service as FS
        from masterquo.modelhub.families import deep
        from masterquo.quant import tabicl
        from masterquo.training import core
        root = self._fake_root()
        for v in (".venv_tabicl", ".venv_deep", ".venv_candles"):
            (root / v / "bin").mkdir(parents=True)
            (root / v / "bin" / "python").write_text("", encoding="utf-8")
        cfg = types.SimpleNamespace(forecast=types.SimpleNamespace(python_path=None))
        with mock.patch.object(paths, "ROOT_DIR", root), mock.patch.dict("os.environ", {}, clear=False) as env:
            for k in ("MQ_TABICL_PYTHON", "MQ_DEEP_PYTHON", "MQ_CANDLES_PYTHON"):
                env.pop(k, None)
            self.assertEqual(tabicl.find_python(), str(root / ".venv_tabicl" / "bin" / "python"))
            self.assertEqual(deep.python(), str(root / ".venv_deep" / "bin" / "python"))
            self.assertEqual(FS.candle_python(cfg), str(root / ".venv_candles" / "bin" / "python"))
            self.assertEqual(core.candles_python(), str(root / ".venv_candles" / "bin" / "python"))
            env["MQ_CANDLES_PYTHON"] = str(root)                     # katalog: candles sprawdzały exists() (jak dziś), tabicl/deep is_file()
            self.assertEqual(core.candles_python(), str(root))
            self.assertEqual(FS.candle_python(cfg), str(root))
            env["MQ_TABICL_PYTHON"] = str(root)
            self.assertEqual(tabicl.find_python(), str(root / ".venv_tabicl" / "bin" / "python"))

    def test_one_ram_budget_default(self):
        from masterquo import runtimes
        from masterquo.training import core
        src = (PKG / "trainhub" / "jobs.py").read_text(encoding="utf-8")
        self.assertFalse("or 6144" in src)
        self.assertIn("DEFAULT_RAM_BUDGET_MB", src)
        with mock.patch.dict("os.environ", {}, clear=False) as env:
            env.pop("MQ_RAM_BUDGET_MB", None)
            self.assertEqual(core.ram_budget_mb({"profile_params": {}}), runtimes.DEFAULT_RAM_BUDGET_MB)
        self.assertEqual(runtimes.DEFAULT_RAM_BUDGET_MB, 8192)
        self.assertFalse("8192" in (PKG / "training" / "core.py").read_text(encoding="utf-8"))

    def test_every_backend_variable_is_documented(self):
        from masterquo import runtimes
        names = _env_names_read_by_backend()
        self.assertTrue({"MQ_KRONOS_PYTHON", "MQ_RAM_BUDGET_MB", "PMW_BOOTSTRAP"} <= names)
        self.assertEqual(sorted(names - set(runtimes.ENV_VARS)), [])
        example = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn(runtimes.env_example_section(), example)
        dotenv_keys = [ln.split("=", 1)[0] for ln in example.splitlines() if ln and not ln.startswith("#") and "=" in ln]
        self.assertFalse([k for k in dotenv_keys if k.startswith(("MQ_", "PMW_"))])    # procesowe zmienne tylko jako komentarz


# ------------------------------------------------------------------------------------------------------------------- I0088 / I0092
def _acct_threads():
    import threading
    return [t for t in threading.enumerate() if t.name == "telegram-account" and t.is_alive()]


class TestWf32ServicesInRuntime(unittest.TestCase):
    """I0088: usługi wf32 (ledger, trials, journal, TLG, Hyperliquid/Universe, AccountCenter) należą do Runtime – API i eksportery je
    tylko czytają (app.state.wf32 is rt.wf32); GET /bootstrap nie buduje drugiej instancji Bootstrap.
    I0092: wątek 'telegram-account' nie startuje przy rejestracji tras (przed rt.start() i niezależnie od licencji) – startuje
    w Runtime.start (tylko prawdziwe MT5, raz) i kończy się na rt._stop; Bootstrap powstaje w Runtime.__init__ (bez wątku)."""

    @classmethod
    def setUpClass(cls):
        import os
        cls.td = TempData()
        cls._boot = os.environ.get("PMW_BOOTSTRAP")
        os.environ["PMW_BOOTSTRAP"] = "0"
        from masterquo.runtime import Runtime
        cls.rt = Runtime(demo=True)

    @classmethod
    def tearDownClass(cls):
        import os
        cls.rt._stop.set()
        if cls._boot is None:
            os.environ.pop("PMW_BOOTSTRAP", None)
        else:
            os.environ["PMW_BOOTSTRAP"] = cls._boot
        cls.td.close()

    def test_runtime_owns_services_and_exporters_read_them_without_http(self):
        from masterquo.exports import sources as S
        rt = self.rt
        self.assertTrue({"ledger", "trials", "shadow_journal", "hl", "universe", "tlg", "acct", "acct_roi"} <= set(rt.wf32))
        ctx = S.SourceContext(Path(self.td.dir), rt=rt)                       # bez aplikacji HTTP
        self.assertIs(ctx.wf32["ledger"], rt.wf32["ledger"])
        col = S.shadow_journal(ctx, "pt")
        self.assertNotIn("APP_NOT_RUNNING", json.dumps(col.__dict__, default=str))            # HEAD: APP_NOT_RUNNING bez create_app

    def test_app_state_is_the_runtime_dict_and_no_thread_at_registration(self):
        from masterquo.api import app as A
        before = len(_acct_threads())
        app = A.create_app(self.rt, PORT)
        self.assertIs(app.state.wf32, self.rt.wf32)
        self.assertIs(app.state.wf32["ledger"], self.rt.wf32["ledger"])
        self.assertEqual(len(_acct_threads()), before)                                         # HEAD: wątek startował przy rejestracji
        self.assertIsNone(getattr(self.rt.wf32_services, "acct_thread", None))

    def test_bootstrap_built_in_init_without_thread(self):
        from masterquo.bootstrap import Bootstrap
        b = self.rt.bootstrap
        self.assertIsInstance(b, Bootstrap)                                                    # przed rt.start()
        self.assertIsNone(b._thread)

    def test_demo_runtime_never_starts_the_account_loop(self):
        self.rt._start_account_loop()
        self.assertIsNone(self.rt.wf32_services.acct_thread)


class TestAccountLoopLifecycle(unittest.TestCase):
    """I0092: rejestracja tras nie startuje pętli; Runtime._start_account_loop startuje ją raz (prawdziwe MT5) i kończy na rt._stop."""

    def test_register_starts_no_thread(self):
        import threading

        from fastapi import FastAPI
        from masterquo.api import wf32_routes
        before = len(_acct_threads())
        rt = types.SimpleNamespace(_stop=threading.Event(), bridge=types.SimpleNamespace(), cfg=None, baskets=None, db=None, telegram=None)
        wf32_routes.register(FastAPI(), rt)
        self.assertEqual(len(_acct_threads()), before)
        self.assertIsNone(getattr(rt, "_acct_thread", None))

    def test_runtime_start_part_starts_once_and_stops(self):
        import threading

        from masterquo.runtime import Runtime
        from masterquo.wf32_services import Wf32Services
        td = TempData()
        try:
            rt = Runtime.__new__(Runtime)
            rt.demo, rt._stop, rt.start_failures = False, threading.Event(), []
            rt.bridge, rt.cfg, rt.telegram, rt.db, rt.baskets = types.SimpleNamespace(), None, None, None, None
            rt.wf32_services = Wf32Services(rt)
            with mock.patch.object(Wf32Services, "acct", return_value=mock.MagicMock()):
                rt._start_account_loop()
                th = rt.wf32_services.acct_thread
                self.assertIsNotNone(th)
                rt._start_account_loop()                                                       # drugi raz: ten sam wątek
                self.assertIs(rt.wf32_services.acct_thread, th)
                rt._stop.set()
                th.join(15)
                self.assertFalse(th.is_alive())
        finally:
            td.close()

    def test_get_bootstrap_without_runtime_bootstrap_is_not_started(self):
        from fastapi import FastAPI
        from masterquo import bootstrap as BS
        from masterquo.api import wf32_routes
        app = FastAPI()
        wf32_routes.register(app, types.SimpleNamespace(bridge=None, baskets=None, cfg=None, bootstrap=None))
        fn = ep(app, "GET", "/api/v1/bootstrap")
        with mock.patch.object(BS, "Bootstrap", side_effect=AssertionError("druga instancja Bootstrap")):
            r = fn()
        self.assertEqual(r["status"], "NOT_STARTED")

    def test_services_construct_without_network(self):
        from masterquo.wf32_services import Wf32Services
        td = TempData()
        try:
            with mock.patch("masterquo.baskets.hyperliquid.Hyperliquid", side_effect=AssertionError("sieć przy starcie")):
                s = Wf32Services(types.SimpleNamespace(bridge=None, baskets=None))
                self.assertEqual(s._svc, {})
        finally:
            td.close()


# ------------------------------------------------------------------------------------------------------------------------- I0109
class TestChartWallsSource(_Base):
    """I0109: wykres dostaje ściany z TEGO SAMEGO snapshotu co S12 (rt.walls.last, jak GET /api/v1/walls – nigdy snapshot()/freeze z API),
    z podpisanym snapshot_id; parametry walls.* w Ustawieniach tylko do odczytu; sekcja volatility = wycena modelowa / tylko wykres."""

    def _candles(self, last):
        from masterquo.api import app as A
        rt = make_rt()
        rt.engine.chart.return_value = {"tf": "M5", "bars": [], "volatility": {"status": "OK"}}
        rt.walls.last = last
        rt.walls.snapshot.side_effect = AssertionError("snapshot() z wątku API")
        rt.walls.context.side_effect = AssertionError("context() z wątku API")
        return ep(A.create_app(rt, PORT), "GET", "/api/v1/candles")(tf="M5"), rt

    def test_chart_data_carries_the_s12_snapshot(self):
        last = {"status": "OK", "snapshot_id": "WS-abc", "snapshot_version": 2, "walls": [{"k": 1.0, "side": "UPPER", "low": 1, "high": 2}],
                "_fp": ["x"]}
        d, rt = self._candles(last)
        self.assertEqual(d["walls_snapshot"]["snapshot_id"], rt.walls.last["snapshot_id"])          # HEAD: brak walls_snapshot
        self.assertNotIn("_fp", d["walls_snapshot"])
        self.assertEqual(d["volatility"], {"status": "OK"})                                           # wycena panelu bez zmian

    def test_no_snapshot_yet(self):
        d, _ = self._candles(None)
        self.assertEqual(d["walls_snapshot"]["status"], "NO_SNAPSHOT_YET")

    def test_frontend_draws_the_snapshot_and_walls_settings_are_read_only(self):
        chart = (ROOT / "frontend" / "src" / "components" / "ChartPanel.tsx").read_text(encoding="utf-8")
        self.assertTrue("walls_snapshot" in chart and "snapshot_id" in chart)
        dlg = (ROOT / "frontend" / "src" / "components" / "Dialogs.tsx").read_text(encoding="utf-8")
        self.assertTrue("cfg.walls" in dlg)
        self.assertFalse('set("walls.' in dlg)                                                         # tylko do odczytu
        self.assertFalse("walls: cfg.walls" in dlg)                                                   # zapis Ustawień nie wysyła walls.*
        self.assertTrue("tylko wykres" in dlg)


if __name__ == "__main__":
    unittest.main()
