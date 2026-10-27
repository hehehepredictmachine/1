"""SCALPING scenario of a 2.5-10 USD price move (prompt MC §3/§7): levels TP1-TP3 as partial orders and 7.5 / 10 as scenarios, leg
volumes on the broker grid, account result from the terminal tick value with spread / commission / slippage shown separately (unknown
commission = no net number, never 0), Monte Carlo bounds per level, models each with their own event and no combined probability,
reason for no order. All market data here is SYNTHETIC."""
from __future__ import annotations

import unittest

import _env
from _env import TempData
from test_montecarlo import bars, _Bridge

XAU_INFO = {"name": "XAUUSD-", "trade_tick_size": 0.01, "point": 0.01, "trade_tick_value": 1.0, "trade_contract_size": 100.0, "volume_min": 0.01,
            "volume_step": 0.01, "volume_max": 50.0, "digits": 2, "currency_profit": "USD", "currency_base": "XAU"}


class _SH:
    def __init__(self, bridge, last_eval=None, mode="SIGNALS"):
        self.bridge, self.last_eval, self.mode = bridge, last_eval or {}, mode

    def instrument(self):
        return "XAUUSD"

    def spec(self, acc):
        from masterquo.sh.units import SymbolSpec
        return SymbolSpec.from_mt5(self.bridge.symbol_info, {"margin_mode": "HEDGING"})

    def quote(self, now):
        q = self.bridge.quote_status()
        return {"bid": q["bid"], "ask": q["ask"], "spread": q["ask"] - q["bid"], "age_s": 0.5}

    def public(self):
        return {"mode": self.mode}


class _ScBridge(_Bridge):
    def __init__(self, b, info=None):
        super().__init__(b)
        self.symbol_info = dict(info or XAU_INFO)

    def account_status(self):
        return {"currency": "USD", "margin_mode": "HEDGING", "trade_mode": "DEMO"}


class _RT:
    def __init__(self, sh, bridge, mc):
        self.sh, self.bridge, self.montecarlo = sh, bridge, mc


def ready_setup(entry, side="BUY", sl_dist=3.0):
    sg = 1 if side == "BUY" else -1
    return {"strategy": "SCALPING", "status": "READY", "status_reason": None, "side": side, "entry_ref": entry, "sl": round(entry - sg * sl_dist, 2),
            "invalidation": round(entry - sg * (sl_dist - 0.2), 2),
            "score": {"value": 71.4, "definition": "heurystyka 0–100 z checklisty – NIE jest prawdopodobieństwem"},
            "checklist": [{"id": "trigger", "label": "Trigger M1", "status": "PASS", "detail": "zamknięcie"}],
            "be": {"after": "TP2", "rule": "ENTRY_PLUS_COSTS", "offset_price": 0.22},
            "probability": {"value": None, "event": "TP2 przed SL w 30 min", "status": "BRAK_MODELU_ZDARZENIA"},
            "coordination": {"decision": "PROCEED"}, "risk": {"status": "PASS", "volume": 0.04, "legs": [0.02, 0.01, 0.01]}}


class TestScenario(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.config import ConfigStore
        from masterquo.montecarlo.service import MonteCarloService
        self.b = bars()
        self.bridge = _ScBridge(self.b)
        self.mc = MonteCarloService(ConfigStore(), self.bridge, synthetic=True, n_paths=600)
        self.entry = round(self.b[-1]["c"] + 0.12, 2)

    def tearDown(self):
        self.mc.stop()
        self.td.close()

    def build(self, last_eval=None, mode="SIGNALS", volume=None, bridge=None):
        from masterquo.sh import scenario as S
        br = bridge or self.bridge
        return S.build(_RT(_SH(br, last_eval, mode), br, self.mc), "SCALPING", volume)

    def test_levels_legs_money_and_costs_separately(self):
        r = self.build({"SCALPING": ready_setup(self.entry)})
        self.assertEqual(r["status"], "PLAN")
        self.assertEqual(r["levels_usd"], [2.5, 3.0, 5.0, 7.5, 10.0])
        rows = {x["level_usd"]: x for x in r["levels"]}
        self.assertTrue(rows[2.5]["role"].startswith("TP1") and rows[3.0]["role"].startswith("TP2") and rows[5.0]["role"].startswith("TP3"))
        self.assertIn("bez zlecenia", rows[7.5]["role"])
        self.assertIn("bez zlecenia", rows[10.0]["role"])
        # smallest volume that gives every leg the broker minimum: 0.04 -> 0.02 / 0.01 / 0.01
        self.assertEqual(r["volume"]["total"], 0.04)
        self.assertEqual([rows[d]["leg_volume"] for d in (2.5, 3.0, 5.0)], [0.02, 0.01, 0.01])
        self.assertIsNone(rows[7.5]["leg_volume"])
        # 1 lot of 100 oz: tick 0.01 = 1 USD -> 100 USD per 1.00 price move; TP1 leg 0.02 lot x 2.50 = 5.00 USD
        self.assertAlmostEqual(rows[2.5]["gross_account"], 5.0)
        self.assertAlmostEqual(rows[2.5]["price"], round(self.entry + 2.5, 2))
        self.assertAlmostEqual(rows[2.5]["slippage_cost"], round(2 * 0.05 * 100 * 0.02, 2))
        self.assertIsNotNone(rows[2.5]["spread_value"])
        self.assertAlmostEqual(rows[2.5]["move_needed_from_quote"], 2.5 + r["costs"]["spread_price"], places=6)
        # commission of the default profile is unknown: shown as unknown, the net result is NOT computed with 0
        self.assertFalse(r["costs"]["commission_known"])
        self.assertIsNone(rows[2.5]["commission_cost"])
        self.assertIsNone(rows[2.5]["net_account"])
        self.assertIn("nie zakładam 0", rows[2.5]["net_note"])
        self.assertIn("nie zysk rachunku", r["unit"])
        self.assertEqual(r["score"], 71.4)                           # number for the panel, never the raw dict

    def test_known_commission_gives_net_result(self):
        from masterquo.sh import config as C
        C.save_override({"instruments": {"XAUUSD": {"commission_per_lot_side": 3.5}}})
        r = self.build({"SCALPING": ready_setup(self.entry)})
        row = r["levels"][0]
        self.assertAlmostEqual(row["commission_cost"], 2 * 3.5 * 0.02)
        self.assertAlmostEqual(row["net_account"], round(row["gross_account"] - row["slippage_cost"] - row["commission_cost"], 2))

    def test_monte_carlo_bounds_never_combined(self):
        r = self.build({"SCALPING": ready_setup(self.entry)})
        self.assertEqual(r["montecarlo"]["status"], "OK")
        self.assertEqual(r["montecarlo"]["probability_kind"], "MODEL_SIMULATED")
        reach = []
        for x in r["levels"]:
            self.assertLessEqual(x["p_tp_before_sl_conservative"], x["p_tp_before_sl_optimistic"] + 1e-12)
            self.assertGreaterEqual(x["mc_error_95"], 0)
            self.assertIsNone(x["p_calibrated"])                    # no validation on the user's data -> no calibrated number
            reach.append(x["p_reach_within_h"])
        self.assertEqual(reach, sorted(reach, reverse=True))        # farther level -> never more likely
        self.assertEqual(r["combined_probability"]["status"], "N/A")
        self.assertIsNone(r["combined_probability"]["value"])
        ids = [m["model"] for m in r["models"]]
        self.assertEqual(ids[:2], ["sh_tp_model", "montecarlo"])
        self.assertEqual(r["models"][0]["status"], "NOT_TRAINED")
        self.assertIn("W_MODELU", r["models"][1]["kind"])

    def test_break_even_after_confirmed_tp2_with_costs(self):
        r = self.build({"SCALPING": ready_setup(self.entry)})
        be = r["break_even"]
        self.assertEqual(be["after"], "TP2")
        self.assertEqual(be["rule"], "ENTRY_PLUS_COSTS")
        self.assertAlmostEqual(be["price"], round(self.entry + 0.22, 5))
        s = ready_setup(round(self.b[-1]["c"], 2), side="SELL")
        r = self.build({"SCALPING": s})
        self.assertAlmostEqual(r["break_even"]["price"], round(s["entry_ref"] - 0.22, 5))
        self.assertLess(r["levels"][0]["price"], s["entry_ref"])  # SELL targets below the entry

    def test_no_setup_shows_both_directions_and_the_reason(self):
        r = self.build({"SCALPING": {"status": "WAIT", "status_reason": "czekam na trigger", "checklist": []}})
        self.assertEqual(r["status"], "NO_SETUP")
        self.assertEqual(r["no_plan_reason"], "czekam na trigger")
        self.assertEqual(r["order"]["why_no_order"], "czekam na trigger")
        x = r["levels"][0]
        self.assertIsNone(x["price"])
        self.assertIn("p_up_reach", x)
        self.assertIn("p_down_reach", x)
        self.assertNotIn("p_tp_before_sl_conservative", x)
        r = self.build({})                                           # engine has not evaluated a closed M1 bar yet
        self.assertEqual(r["status"], "NO_SETUP")
        self.assertIn("nie ocenił", r["order"]["why_no_order"])

    def test_signals_mode_is_the_reason_for_no_order(self):
        r = self.build({"SCALPING": ready_setup(self.entry)}, mode="SIGNALS")
        self.assertIn("SIGNALS", r["order"]["why_no_order"])
        r = self.build({"SCALPING": ready_setup(self.entry)}, mode="PAPER")
        self.assertIsNone(r["order"]["why_no_order"])
        s = ready_setup(self.entry)
        s["risk"] = {"status": "BLOCK", "reasons": ["margin: za mało wolnego depozytu"]}
        r = self.build({"SCALPING": s}, mode="PAPER")
        self.assertIn("margin", r["order"]["why_no_order"])

    def test_volume_from_panel_off_grid_and_infeasible_split(self):
        r = self.build({"SCALPING": ready_setup(self.entry)}, volume=0.015)
        self.assertFalse(r["volume"]["on_broker_grid"])
        r = self.build({"SCALPING": ready_setup(self.entry)}, volume=0.02)
        self.assertEqual(r["volume"]["split"]["status"], "INFEASIBLE")
        self.assertIsNone(r["levels"][0]["leg_volume"])            # no leg volume invented when the split is impossible

    def test_unknown_tick_value_and_foreign_quote_currency(self):
        r = self.build({"SCALPING": ready_setup(self.entry)}, bridge=_ScBridge(self.b, dict(XAU_INFO, trade_tick_value=0)))
        self.assertIsNone(r["levels"][0]["gross_account"])
        self.assertIn("wartości ticka", r["levels"][0]["net_note"])
        r = self.build({"SCALPING": ready_setup(self.entry)}, bridge=_ScBridge(self.b, dict(XAU_INFO, currency_profit="EUR")))
        self.assertEqual(r["status"], "UNIT_ERROR")

    def test_config_tp3_choices_and_levels_validated(self):
        from masterquo.sh import config as C
        cfg = C.load()
        sc = cfg["instruments"]["XAUUSD"]["SCALPING"]
        self.assertEqual(sc["tp_usd"], [2.5, 3.0, 5.0])
        self.assertEqual(sc["tp3_choices"], [5.0, 7.5, 10.0])
        self.assertNotIn("scenario_levels_usd", cfg["instruments"]["BTC"]["SCALPING"])   # XAUUSD levels are not copied to BTC
        bad = {"instruments": {"XAUUSD": {"SCALPING": dict(sc, tp_usd=[2.5, 3.0, 8.0])}}}
        self.assertTrue(any("TP3" in e for e in C.validate(bad)))
        bad = {"instruments": {"XAUUSD": {"SCALPING": dict(sc, scenario_levels_usd=[2.5, 10.0, 5.0])}}}
        self.assertTrue(any("scenariusza" in e for e in C.validate(bad)))
        self.assertEqual(C.validate(cfg), [])
        with self.assertRaises(ValueError):                         # negative commission refused
            C.save_override({"instruments": {"XAUUSD": {"commission_per_lot_side": -1}}})
        C.save_override({"instruments": {"XAUUSD": {"commission_per_lot_side": 3.5}}})
        C.save_override({"instruments": {"XAUUSD": {"commission_per_lot_side": None}}})   # back to unknown (panel: empty field)
        self.assertIsNone(C.load()["instruments"]["XAUUSD"]["commission_per_lot_side"])


class TestScenarioApi(unittest.TestCase):
    """Demo server (simulator): the endpoint answers for both strategies and refuses unknown names."""

    @classmethod
    def setUpClass(cls):
        from test_ui_export import Server
        cls.S = type("S", (Server,), {})
        cls.S.start_server()

    @classmethod
    def tearDownClass(cls):
        cls.S.stop_server()

    def test_endpoint(self):
        from _env import wait_for
        self.assertTrue(wait_for(lambda: self.S.call("/api/v1/sh/scenario")[1].get("montecarlo", {}).get("status") == "OK", 120, 1))
        st, r = self.S.call("/api/v1/sh/scenario?strategy=SCALPING")
        self.assertEqual(st, 200, r)
        self.assertIn(r["status"], ("PLAN", "NO_SETUP"))
        self.assertEqual(r["levels_usd"], [2.5, 3.0, 5.0, 7.5, 10.0])
        self.assertEqual(len(r["levels"]), 5)
        self.assertEqual(r["montecarlo"]["data"]["kind"], "SYNTHETIC_TEST")
        self.assertEqual(r["combined_probability"]["status"], "N/A")
        self.assertGreater(len(r["models"]), 5)
        st, r = self.S.call("/api/v1/sh/scenario?strategy=SCALPING&volume=0.1")
        self.assertEqual(st, 200, r)
        self.assertEqual(r["volume"]["total"], 0.1)
        self.assertEqual(self.S.call("/api/v1/sh/scenario?strategy=FOO")[0], 400)
        self.assertEqual(self.S.call("/api/v1/sh/scenario?volume=-1")[0], 422)


if __name__ == "__main__":
    unittest.main()
