"""Fala 2b, grupa „platform_api” (config/paths, api/app.py, api/wf32_routes.py, runtime.py, punkty wejścia CLI, desktop/).

Testy bez sieci, bez MT5 (FakeMT5 albo atrapy), osobny folder danych na test. Każda klasa odpowiada pozycji (klucz w nazwie/docstringu)."""
from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
