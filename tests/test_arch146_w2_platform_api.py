"""Fala 2b, grupa „platform_api” (config/paths, api/app.py, api/wf32_routes.py, runtime.py, punkty wejścia CLI, desktop/).

Testy bez sieci, bez MT5 (FakeMT5 albo atrapy), osobny folder danych na test. Każda klasa odpowiada pozycji (klucz w nazwie/docstringu)."""
from __future__ import annotations

import ast
import json
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


if __name__ == "__main__":
    unittest.main()
