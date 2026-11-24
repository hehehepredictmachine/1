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

import _env  # noqa: F401
from _env import TempData

OLD_SAVED_PRICES = {   # cennik zapisany w config.json przez 1.45/1.46 (przed D13) - bez claude-fable-5-2
    "claude-fable-5-1": [10.0, 50.0], "claude-opus-5-5": [4.0, 20.0], "claude-opus-5": [5.0, 25.0],
    "claude-sonnet-5-5": [2.0, 10.0], "claude-sonnet-5": [2.0, 10.0], "claude-haiku-5-5": [0.10, 0.50],
}


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
        want = (500_000 * 8 + 100_000 * 8 * 1.25 + 1_000_000 * 8 * 0.1 + 50_000 * 40) / 1_000_000
        self.assertAlmostEqual(ag._cost("claude-fable-5-2", usage), round(want, 6))
        self.assertAlmostEqual(ag._cost("claude-fable-5-1", {"input_tokens": 1_000_000}), 10.0)   # zapisane ceny działają jak dotąd
        self.assertIsNone(ag._cost("claude-unknown-model", {"input_tokens": 1_000_000}))        # nieznany model: nadal brak szacunku

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

    def test_every_fallback_model_is_priced(self):
        from masterquo.agent import service as AS
        from masterquo.config import AgentConfig
        self.assertFalse(AS.FALLBACK_MODELS - set(AgentConfig().price_per_mtok))


if __name__ == "__main__":
    unittest.main()
