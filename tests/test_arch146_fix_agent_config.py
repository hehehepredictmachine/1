"""arch146 fala 2a, grupa agent_config: D13 (claude-fable-5-2 w cenniku i fallbacku agenta) i D1 wariant opisowy (S1).

D13: claude-fable-5-2 ($8 / $40 za MTok, następca claude-fable-5-1) - w domyślnej tabeli cen, w koszcie wywołania także przy starej
zapisanej tabeli użytkownika (config.json trzyma cały cennik, _deep_merge go nie scala) i na liście modeli z server-side fallback.

D1 (obszar chroniony): execution.start_mode NIE jest stosowany przy starcie (martwy warunek runtime.py:87 zostaje). Tu tylko opis pola
i jawny stan w statusie trybu. Testy dowodzą, że tryb startowy Runtime na FakeMT5 jest taki sam jak przed zmianą (apply_start_mode nie
jest wołane, tryb = zapisany execution.mode, brak powiązanego rachunku), a status pokazuje NOT_APPLIED z powodem."""
from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest import mock

import _env  # noqa: F401
from _env import TempData

OLD_SAVED_PRICES = {   # cennik zapisany w config.json przez 1.45/1.46 (przed D13) - bez claude-fable-5-2
    "claude-fable-5-1": [10.0, 50.0], "claude-opus-5-5": [4.0, 20.0], "claude-opus-5": [5.0, 25.0],
    "claude-sonnet-5-5": [2.0, 10.0], "claude-sonnet-5": [2.0, 10.0], "claude-haiku-5-5": [0.10, 0.50],
}
# klucze statusu trybu sprzed D1 - D1 tylko DOPISUJE pola, żadne istniejące nie znika ani nie zmienia znaczenia
OLD_STATUS_KEYS = {"mode", "mode_label", "auto_trading", "bound_account", "kill_switch", "kill_reason", "changed_at", "strategy_mode",
                   "ml_mode", "instrument", "primary_path", "primary_path_label", "primary_paths", "mode_note"}


class _NoKey:
    def get(self, name):
        return None

    def source(self, name):
        return "MISSING"

    def mask(self, name):
        return None


class _Log:
    def __getattr__(self, name):
        return lambda *a, **k: None


class _Bus:
    def publish(self, *a, **k):
        pass


class _Recorder:
    """AsyncAnthropic zastępczy: zapisuje argumenty messages.create / beta.messages.create (bez sieci)."""

    def __init__(self):
        self.calls: list = []
        self.messages = SimpleNamespace(create=self._plain)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._beta))

    async def _plain(self, **kw):
        self.calls.append(("messages", kw))
        return {"stub": True}

    async def _beta(self, **kw):
        self.calls.append(("beta", kw))
        return {"stub": True}


def _write_config(td: TempData, raw: dict) -> None:
    from pathlib import Path
    (Path(td.dir) / "config.json").write_text(json.dumps(raw), encoding="utf-8")


class TestAgentFable52Pricing(unittest.TestCase):
    """D13."""

    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def _agent(self):
        from masterquo.agent.service import ClaudeAgent
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        return ClaudeAgent(ConfigStore(), _NoKey(), Database(), _Bus(), _Log(), lambda sid: None)

    def test_default_price_table_has_fable_5_2(self):
        from masterquo.config import AgentConfig
        prices = AgentConfig().price_per_mtok
        self.assertEqual(tuple(prices["claude-fable-5-2"]), (8.0, 40.0))
        self.assertEqual(tuple(prices["claude-fable-5-1"]), (10.0, 50.0))       # poprzednik bez zmian
        self.assertIsNone(AgentConfig().model)                                   # domyślny model dalej wybiera użytkownik

    def test_cost_fable_5_2_fresh_config(self):
        ag = self._agent()
        usage = {"input_tokens": 1_000_000, "output_tokens": 100_000}
        self.assertAlmostEqual(ag._cost("claude-fable-5-2", usage), 8.0 + 4.0)

    def test_cost_fable_5_2_with_old_saved_price_table(self):
        _write_config(self.td, {"agent": {"price_per_mtok": OLD_SAVED_PRICES}})
        ag = self._agent()
        self.assertNotIn("claude-fable-5-2", ag.cfg.price_per_mtok)             # zapisany cennik zastępuje domyślny (bez scalania)
        usage = {"input_tokens": 500_000, "output_tokens": 50_000, "cache_read_input_tokens": 1_000_000,
                 "cache_creation_input_tokens": 100_000}
        want = (500_000 * 8 + 100_000 * 8 * 1.25 + 1_000_000 * 8 * 0.025 + 50_000 * 40) / 1_000_000   # odczyt z cache $0.20/MTok
        self.assertAlmostEqual(ag._cost("claude-fable-5-2", usage), round(want, 6))
        self.assertAlmostEqual(ag._cost("claude-fable-5-1", {"input_tokens": 1_000_000}), 10.0)   # zapisane ceny działają jak dotąd
        self.assertIsNone(ag._cost("claude-unknown-model", {"input_tokens": 1_000_000}))        # nieznany model: nadal brak szacunku

    def test_cache_read_fable_5_2_billed_at_0_025(self):
        # przegląd D13: odczyt z cache claude-fable-5-2 kosztuje $0.20/MTok (0.025 x $8), nie 0.1 x $8 = $0.80
        ag = self._agent()
        self.assertAlmostEqual(ag._cost("claude-fable-5-2", {"cache_read_input_tokens": 1_000_000}), 0.20)
        self.assertAlmostEqual(ag._cost("claude-fable-5-2", {"cache_creation_input_tokens": 1_000_000}), 10.0)   # zapis 1.25x bez zmian

    def test_cache_read_other_models_unchanged(self):
        # strażnik: pozostałe modele zostają przy szacunku 0.1 (obniżenie wydłuża budżet - przy REQUIRED luzuje, decyzja właściciela)
        ag = self._agent()
        for model, pin in (("claude-fable-5-1", 10.0), ("claude-opus-5-5", 4.0), ("claude-sonnet-5-5", 2.0), ("claude-opus-5", 5.0)):
            with self.subTest(model=model):
                self.assertAlmostEqual(ag._cost(model, {"cache_read_input_tokens": 1_000_000}), round(pin * 0.1, 6))

    def test_user_price_override_wins(self):
        prices = dict(OLD_SAVED_PRICES, **{"claude-fable-5-2": [9.0, 45.0]})
        _write_config(self.td, {"agent": {"price_per_mtok": prices}})
        ag = self._agent()
        self.assertAlmostEqual(ag._cost("claude-fable-5-2", {"input_tokens": 1_000_000}), 9.0)

    def test_fable_5_2_uses_server_side_fallback(self):
        from masterquo.agent import service as AS
        self.assertIn("claude-fable-5-2", AS.FALLBACK_MODELS)
        ag = self._agent()
        rec = _Recorder()
        asyncio.run(ag._create(rec, "claude-fable-5-2", "system", [{"role": "user", "content": "x"}], True))
        kind, kw = rec.calls[-1]
        self.assertEqual(kind, "beta")
        self.assertEqual((kw["betas"], kw["fallbacks"], kw["model"]), ([AS.FALLBACK_BETA], "default", "claude-fable-5-2"))

    def test_fallback_switch_off_still_respected(self):
        self.td.close()
        self.td = TempData()
        _write_config(self.td, {"agent": {"use_refusal_fallback": False}})
        ag = self._agent()
        rec = _Recorder()
        asyncio.run(ag._create(rec, "claude-fable-5-2", "system", [{"role": "user", "content": "x"}], True))
        self.assertEqual(rec.calls[-1][0], "messages")
        self.assertNotIn("fallbacks", rec.calls[-1][1])

    def test_status_cost_note_names_default_price_table(self):
        # przegląd D13: cena może pochodzić z domyślnej tabeli programu (stan 2026-11), nie tylko z konfiguracji (stan 2026-10-06)
        note = self._agent().status()["cost_note"]
        self.assertIn("domyślnego cennika", note)
        self.assertIn("2026-11", note)
        self.assertNotIn("2026-10-06", note)

    def test_every_fallback_model_is_priced(self):
        from masterquo.agent import service as AS
        from masterquo.config import AgentConfig
        self.assertFalse(AS.FALLBACK_MODELS - set(AgentConfig().price_per_mtok))


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



class TestAgentUnpricedModelVisible(unittest.TestCase):
    """Przegląd D13 (S1): przebieg modelu spoza cennika (np. odpowiedź modelu zapasowego server-side fallback) nadal liczy się w budżecie
    jako 0 (bez zmian), ale nie po cichu: ostrzeżenie w dzienniku (raz na model) i pole last_run.price_missing_for."""

    def setUp(self):
        import os
        self.td = TempData()
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-not-a-real-key"
        import test_agent as TA
        from masterquo.agent.service import ClaudeAgent
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        from masterquo.events import AppLog, EventBus
        from masterquo.secrets_store import SecretStore
        self.TA = TA
        cfg = ConfigStore()
        cfg.update({"agent": {"model": "claude-opus-5-5"}})
        self.db = Database()
        bus = EventBus()
        self.agent = ClaudeAgent(cfg, SecretStore(), self.db, bus, AppLog(self.db, bus), lambda sid: TA.CTX)

    def tearDown(self):
        import os
        os.environ.pop("ANTHROPIC_API_KEY", None)
        self.td.close()

    def _run(self, served: str) -> dict:
        TA = self.TA
        resp = TA.msg([TA.text(json.dumps(TA.answer()))], "end_turn")
        resp.model = served
        client = TA.ScriptedClient([resp])
        self.agent._client_get = lambda: client
        req = {"trigger": "SETUP_CONFIRMED", "snapshot_id": "SNP-1", "setup_id": "MQS-1", "setup_state": "CONFIRMED", "question": None,
               "key": "k"}
        return asyncio.run(self.agent.run_once(req, TA.CTX))

    def _warnings(self) -> list:
        return self.db.query("SELECT message FROM app_events WHERE code='COST_PRICE_MISSING'")

    def test_unpriced_served_model_is_reported(self):
        r = self._run("claude-opus-4-8")                                          # model zapasowy spoza cennika
        self.assertEqual(r["status"], "OK")
        self.assertIsNone(r["est_cost_usd"])                                     # budżet: bez zmian (0)
        self.assertEqual(self.agent.spent_today(), 0.0)
        self.assertEqual(self.agent.status()["last_run"]["price_missing_for"], "claude-opus-4-8")
        self.assertEqual(len(self._warnings()), 1)
        self.assertIn("claude-opus-4-8", self._warnings()[0]["message"])
        self._run("claude-opus-4-8")
        self.assertEqual(len(self._warnings()), 1)                                # raz na model, bez zalewania dziennika

    def test_priced_model_not_reported(self):
        r = self._run("claude-opus-5-5")
        self.assertIsNotNone(r["est_cost_usd"])
        self.assertIsNone(self.agent.status()["last_run"]["price_missing_for"])
        self.assertEqual(self._warnings(), [])


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
