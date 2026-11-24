"""arch146 fala 1, grupa agent_config: D1 wariant opisowy (S1).

(D13 – claude-fable-5-2 w cenniku i fallbacku – wycofany przy scaleniu: sceptyk bezpieczeństwa uznał plan za S0 (fallback przy REQUIRED
i liczenie budżetu przy VETO mogą dopuścić wejście, którego dziś nie ma); wariant bezpieczny wdraża fala 2b, grupa platform_misc.)

D1 (obszar chroniony): execution.start_mode NIE jest stosowany przy starcie (martwy warunek runtime.py:87 zostaje). Tu tylko opis pola
i jawny stan w statusie trybu. Testy dowodzą, że tryb startowy Runtime na FakeMT5 jest taki sam jak przed zmianą (apply_start_mode nie
jest wołane, tryb = zapisany execution.mode, brak powiązanego rachunku), a status pokazuje NOT_APPLIED z powodem."""
from __future__ import annotations

import json
import unittest
from unittest import mock

import _env  # noqa: F401
from _env import TempData

# klucze statusu trybu sprzed D1 - D1 tylko DOPISUJE pola, żadne istniejące nie znika ani nie zmienia znaczenia
OLD_STATUS_KEYS = {"mode", "mode_label", "auto_trading", "bound_account", "kill_switch", "kill_reason", "changed_at", "strategy_mode",
                   "ml_mode", "instrument", "primary_path", "primary_path_label", "primary_paths", "mode_note"}


class _Log:
    def __getattr__(self, name):
        return lambda *a, **k: None


class _Bus:
    def publish(self, *a, **k):
        pass


def _write_config(td: TempData, raw: dict) -> None:
    from pathlib import Path
    (Path(td.dir) / "config.json").write_text(json.dumps(raw), encoding="utf-8")


class TestStartModeNotApplied(unittest.TestCase):
    """D1 wariant opisowy (S1): start_mode opisany jako niestosowany + jawny stan w statusie; zachowanie startu bez zmian."""

    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def _runtime(self, **kw):
        import mq_venv
        from masterquo import runtime as R
        from masterquo.execution.modes import ModeManager
        from masterquo.upgrade import migrate as UM
        with mock.patch.object(mq_venv, "repair_all", return_value={}), mock.patch.object(UM, "before", return_value=None), \
                mock.patch.object(ModeManager, "apply_start_mode", autospec=True, side_effect=ModeManager.apply_start_mode) as spy:
            rt = R.Runtime(demo=False, **kw)
        return rt, spy

    def _fake_factory(self):
        from masterquo.mt5.fake import FakeMT5
        return lambda: FakeMT5(symbol="XAUUSD-", seed=3)

    def test_config_field_unchanged_and_described(self):
        from masterquo.config import ExecutionConfig
        ex = ExecutionConfig()
        self.assertEqual((ex.start_mode, ex.live_autobind), ("AUTO_LIVE", True))   # wartości domyślne bez zmian
        desc = ExecutionConfig.model_fields["start_mode"].description or ""
        self.assertIn("NIE jest stosowany", desc)
        self.assertIn("execution.mode", desc)

    def test_runtime_on_fakemt5_start_mode_identical(self):
        rt, spy = self._runtime(mt5_factory=self._fake_factory())
        self.assertEqual(spy.call_count, 0)                                     # apply_start_mode nie jest wołane
        self.assertEqual(rt.cfg.get().execution.start_mode, "AUTO_LIVE")
        self.assertEqual((rt.modes.mode, rt.cfg.get().execution.mode), ("PAPER", "PAPER"))   # tryb = zapisany (domyślny PAPER)
        self.assertIsNone(rt.modes.bound_account)
        self.assertIsNone(rt.cfg.get().execution.bound_account)
        st = rt.modes.status()
        self.assertTrue(OLD_STATUS_KEYS <= set(st))
        self.assertEqual((st["mode"], st["bound_account"], st["mode_note"]), ("PAPER", None, None))
        self.assertEqual(st["start_mode_configured"], "AUTO_LIVE")
        self.assertEqual(st["start_mode_effective"], "NOT_APPLIED")
        self.assertIn("execution.start_mode", st["start_mode_reason"])
        self.assertIn("execution.mode", st["start_mode_reason"])

    def test_runtime_production_factory_start_mode_identical(self):
        # ścieżka produkcyjna (fabryka MetaTrader5 podstawiana w runtime) - konstruktor nie łączy się z terminalem
        rt, spy = self._runtime()
        self.assertEqual(spy.call_count, 0)
        self.assertEqual(rt.modes.mode, "PAPER")
        self.assertEqual(rt.modes.status()["start_mode_effective"], "NOT_APPLIED")

    def test_runtime_keeps_stored_mode(self):
        _write_config(self.td, {"execution": {"mode": "SIGNALS"}})
        rt, spy = self._runtime(mt5_factory=self._fake_factory())
        self.assertEqual(spy.call_count, 0)
        self.assertEqual((rt.modes.mode, rt.cfg.get().execution.mode, rt.cfg.get().execution.start_mode), ("SIGNALS", "SIGNALS", "AUTO_LIVE"))
        st = rt.modes.status()
        self.assertEqual((st["mode"], st["start_mode_effective"]), ("SIGNALS", "NOT_APPLIED"))

    def test_status_reason_without_configured_start_mode(self):
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        from masterquo.execution.modes import ModeManager
        cfg = ConfigStore()
        cfg.update({"execution": {"start_mode": None}})
        mm = ModeManager(cfg, Database(), _Bus(), _Log(), account_provider=lambda: (None, None, False))
        st = mm.status()
        self.assertEqual((st["start_mode_configured"], st["start_mode_effective"], st["mode"]), (None, "NOT_APPLIED", "PAPER"))
        self.assertIn("execution.mode", st["start_mode_reason"])

    def test_status_is_honest_if_start_mode_is_ever_applied(self):
        # wywołanie jawne (jak w test_live_start) - status nie może wtedy dalej twierdzić NOT_APPLIED
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        from masterquo.execution.modes import ModeManager
        cfg = ConfigStore()
        cfg.update({"execution": {"start_mode": "SIGNALS"}})
        mm = ModeManager(cfg, Database(), _Bus(), _Log(), account_provider=lambda: (None, None, False))
        self.assertEqual(mm.status()["start_mode_effective"], "NOT_APPLIED")
        self.assertEqual(mm.apply_start_mode(), "SIGNALS")
        st = mm.status()
        self.assertEqual((st["mode"], st["start_mode_effective"], st["start_mode_reason"]), ("SIGNALS", "APPLIED", None))



D1_OLD_DOC_RECIPES = {   # dawne zdania, które obiecywały działający start_mode jako wyłącznik LIVE
    "START_TUTAJ_PL.md": ("**Bot startuje w AUTO LIVE**", "Wyłączenie: STOP albo"),
    "ROLLBACK.md": ("przycisk STOP, potem w `data/config.json`",),
    "docs/AKTUALIZACJA_1_39_PL.md": ('Wyłączenie: STOP / `start_mode: "SIGNALS"`',),
}


class TestStartModeDocsD1(unittest.TestCase):
    """D1, dokumentacja (S1): instrukcje użytkownika nie podają już start_mode / live_autobind jako wyłącznika LIVE. Strażnicy
    (przechodzą też przed zmianą) dowodzą na prawdziwym Runtime, że to, co dokumentacja teraz mówi, jest prawdą."""

    DOCS = tuple(D1_OLD_DOC_RECIPES)

    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    @staticmethod
    def _text(rel: str) -> tuple[str, str]:
        import re

        from _env import ROOT
        raw = (ROOT / rel).read_text(encoding="utf-8")
        return raw, re.sub(r"\s+", " ", re.sub(r"[*>]", "", raw))

    def test_docs_say_start_mode_is_not_applied(self):
        for rel in self.DOCS:
            with self.subTest(doc=rel):
                import re
                raw, flat = self._text(rel)
                self.assertTrue(re.search(r"start_mode`? (\(domyślnie `AUTO_LIVE`\) )?(NIE|nie) (jest )?stosowan", flat),
                                f"{rel}: brak zdania, że start_mode nie jest stosowany")
                for want in ("arch146 D1", "execution.mode",
                             "POST /api/v1/mode",                 # wyłącznik: zapisana zmiana trybu
                             "STOP nie przetrwa restartu",
                             "nie wyłącza"):                       # start_mode / live_autobind nie wyłączają zapisanego AUTO_LIVE
                    self.assertTrue(want in flat, f"{rel}: brak {want!r}")
                for old in D1_OLD_DOC_RECIPES[rel]:
                    self.assertFalse(old in raw, f"{rel}: nadal jest dawny przepis {old!r}")

    def _runtime(self):
        import mq_venv
        from masterquo import runtime as R
        from masterquo.mt5.fake import FakeMT5
        from masterquo.upgrade import migrate as UM
        with mock.patch.object(mq_venv, "repair_all", return_value={}), mock.patch.object(UM, "before", return_value=None):
            return R.Runtime(demo=False, mt5_factory=lambda: FakeMT5(symbol="XAUUSD-", seed=3))

    def test_old_recipe_does_not_switch_off_saved_auto_live(self):
        # stan po wyborze AUTO_LIVE w panelu + dawny przepis z dokumentacji (STOP, start_mode SIGNALS, live_autobind false, restart)
        _write_config(self.td, {"config_version": 15, "execution": {"mode": "AUTO_LIVE", "bound_account": "Broker-Live:1001",
                                                                     "start_mode": "SIGNALS", "live_autobind": False}})
        rt = self._runtime()
        self.assertEqual((rt.modes.mode, rt.modes.bound_account, rt.modes.kill_switch), ("AUTO_LIVE", "Broker-Live:1001", False))
        self.assertEqual(rt.modes.status()["start_mode_effective"], "NOT_APPLIED")

    def test_stop_does_not_survive_restart(self):
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        from masterquo.execution.modes import ModeManager
        mm = ModeManager(ConfigStore(), Database(), _Bus(), _Log(), account_provider=lambda: (None, None, False))
        self.assertTrue(mm.set_kill(True, "USER")["kill_switch"])
        mm2 = ModeManager(ConfigStore(), Database(), _Bus(), _Log(), account_provider=lambda: (None, None, False))
        self.assertFalse(mm2.kill_switch)

    def test_documented_off_switch_survives_restart(self):
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        from masterquo.execution.modes import ModeManager
        _write_config(self.td, {"config_version": 15, "execution": {"mode": "AUTO_LIVE", "bound_account": "Broker-Live:1001"}})
        mm = ModeManager(ConfigStore(), Database(), _Bus(), _Log(), account_provider=lambda: (None, None, False))
        self.assertEqual(mm.mode, "AUTO_LIVE")
        mm.set_mode("SIGNALS", account=None, account_key=None, synthetic=False)      # panel: POST /api/v1/mode
        rt = self._runtime()
        self.assertEqual((rt.modes.mode, rt.modes.bound_account), ("SIGNALS", None))
        self.assertFalse(rt.modes.gate("Broker-Live:1001", {"trade_mode": "REAL", "login": 1001}, False)["allowed"])

    def test_documented_offline_edit_survives_restart(self):
        _write_config(self.td, {"config_version": 15, "execution": {"mode": "SIGNALS", "bound_account": None}})
        rt = self._runtime()
        self.assertEqual((rt.modes.mode, rt.modes.bound_account), ("SIGNALS", None))


if __name__ == "__main__":
    unittest.main()
