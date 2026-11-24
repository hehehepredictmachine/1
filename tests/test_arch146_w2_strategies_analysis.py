"""1.46 arch, fala 2 - grupa strategies_analysis (strategie S01-S12, selektor, tracker, analiza S/R i walls).

Każda klasa odpowiada pozycji triażu (klucz w docstringu); test nie przechodził na kodzie sprzed poprawki.
"""
from __future__ import annotations

import importlib
import unittest

import _env


class TestPackagesRegular(unittest.TestCase):
    """I0090: strategies/ i lab/ były niejawnymi pakietami przestrzeni nazw (brak __init__.py, __file__ None) - jako jedyne z podpakietów
    backend/masterquo; narzędzia wykrywania pakietów i pakowanie mogły je pomijać."""

    def test_strategies_and_lab_are_regular_packages(self):
        for name in ("masterquo.strategies", "masterquo.lab"):
            mod = importlib.import_module(name)
            self.assertIsNotNone(getattr(mod, "__file__", None), name)
            self.assertTrue(str(mod.__file__).endswith("__init__.py"), name)

    def test_every_backend_directory_with_modules_has_init(self):
        pkg = _env.ROOT / "backend" / "masterquo"
        missing = sorted(str(d.relative_to(pkg)) for d in [pkg, *[p for p in pkg.rglob("*") if p.is_dir()]]
                         if "__pycache__" not in d.parts and any(d.glob("*.py")) and not (d / "__init__.py").exists())
        self.assertEqual(missing, [])


class TestStrategyParamsIsolation(unittest.TestCase):
    """I0098: STRATEGIES to singletony współdzielone przez skan live, backfill ML i API; params_for robił płytką kopię (lista 'tfs'
    wspólna z atrybutem klasy), a describe() oddawał żywy słownik params - mutacja u konsumenta zmieniała parametry skanu live."""

    def test_describe_returns_copies(self):
        from masterquo.strategies import registry
        before = list(registry.STRATEGIES["S01"].params["tfs"])
        d = next(x for x in registry.describe() if x["strategy_id"] == "S01")
        d["params"]["tfs"].append("X")
        d["params"]["new_key"] = 1
        d["regime_fit"]["TREND_UP"] = -1.0
        self.assertEqual(registry.STRATEGIES["S01"].params["tfs"], before)
        self.assertNotIn("new_key", registry.STRATEGIES["S01"].params)
        self.assertNotEqual(registry.STRATEGIES["S01"].regime_fit.get("TREND_UP"), -1.0)

    def test_params_for_is_a_deep_copy(self):
        from masterquo.strategies import registry
        before = list(registry.STRATEGIES["S01"].params["tfs"])
        p = registry.params_for("S01", None)
        p["tfs"].append("X")
        self.assertEqual(registry.STRATEGIES["S01"].params["tfs"], before)
        override = {"tfs": ["M15"]}
        q = registry.params_for("S01", override)
        q["tfs"].append("H1")
        self.assertEqual(override["tfs"], ["M15"])                    # the user's config value is not mutated either
        self.assertEqual(registry.params_for("S01", {"tfs": ["M5"]})["tfs"], ["M5"])   # overrides still apply

    def test_strategies_keep_no_instance_state_outside_thread_local(self):
        from masterquo.strategies import registry
        for sid, s in registry.STRATEGIES.items():
            self.assertLessEqual(set(vars(s)), {"_tls"}, sid)


if __name__ == "__main__":
    unittest.main()
