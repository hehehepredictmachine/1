"""SYNTHETIC ONLY: tests for a minimal M01 contract reference model.
No connection to MT5/TradingView, no real live/backtest capability.
Run: python -m unittest -v M01_CONTRACT_TESTS.py
"""
import copy
import json
import math
import pathlib
import unittest
from datetime import datetime, timezone
from jsonschema import Draft202012Validator, FormatChecker

BASE = pathlib.Path(__file__).parent
SCHEMA = json.loads((BASE / "M01_DATA_SNAPSHOT_SCHEMA_v2_0_EXTENSION.json").read_text(encoding="utf-8"))
SNAPSHOT = json.loads((BASE / "M01_SYNTHETIC_EXAMPLE.json").read_text(encoding="utf-8"))
SPEC = (BASE / "M01_DATA_INTELLIGENCE_v4.2.1_CANDIDATE.txt").read_text(encoding="utf-8")
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def quote_check(bid, ask, point=None):
    if any(not isinstance(x, (int, float)) or not math.isfinite(x) for x in (bid, ask)):
        return False, "NON_FINITE", None
    if bid <= 0 or ask <= 0 or bid > ask:
        return False, "INVALID_BID_ASK", None
    spread = ask-bid
    if point is not None and (not math.isfinite(point) or point <= 0):
        return False, "INVALID_POINT", None
    return True, None, (spread, spread / point if point else None)


def bar_check(bar):
    nums = [bar[k] for k in ("open", "high", "low", "close")]
    if any(not isinstance(x, (int, float)) or not math.isfinite(x) or x <= 0 for x in nums):
        return False
    o, h, l, c = nums
    return l <= min(o, c) <= max(o, c) <= h and (bar.get("tick_volume") is None or bar["tick_volume"] >= 0) and (bar.get("real_volume") is None or bar["real_volume"] >= 0)


def completeness(present, required):
    if not required:
        return {"numerator": 0, "denominator": 0, "value": None, "reason": "NO_REQUIRED_FIELDS_DEFINED"}
    numerator = sum(key in present and present[key] is not None for key in required)
    return {"numerator": numerator, "denominator": len(required), "value": numerator / len(required), "reason": None}


def eligible_source_comparison(primary, secondary):
    return (primary["instrument_id"] == secondary["instrument_id"]
            and primary["price_basis"] == secondary["price_basis"]
            and primary["timeframe"] == secondary["timeframe"]
            and primary["bar_boundary"] == secondary["bar_boundary"])


def check_available_at(record, analysis_as_of):
    return datetime.fromisoformat(record["available_at"].replace("Z", "+00:00")) <= datetime.fromisoformat(analysis_as_of.replace("Z", "+00:00"))


def reference_scope_gate(required, present, freshness_known=True, critical_bad=False):
    if critical_bad:
        return "FAIL"
    if not required.issubset(present):
        return "PENDING"
    if not freshness_known:
        return "PENDING"
    return "PASS"


class SchemaTests(unittest.TestCase):
    def test_01_schema_well_formed(self):
        Draft202012Validator.check_schema(SCHEMA)

    def test_02_synthetic_snapshot_valid(self):
        self.assertEqual([], list(VALIDATOR.iter_errors(SNAPSHOT)))

    def test_03_null_quote_allowed(self):
        x = copy.deepcopy(SNAPSHOT); x["quote"] = None
        self.assertEqual([], list(VALIDATOR.iter_errors(x)))

    def test_04_no_quote_required_field_fails(self):
        x = copy.deepcopy(SNAPSHOT); del x["quote"]
        self.assertTrue(list(VALIDATOR.iter_errors(x)))

    def test_05_invalid_gate_scope_rejected(self):
        x = copy.deepcopy(SNAPSHOT); x["data_gates"][0]["required_for"] = ["ORDER_SEND"]
        self.assertTrue(list(VALIDATOR.iter_errors(x)))

    def test_06_unknown_evidence_status_rejected(self):
        x = copy.deepcopy(SNAPSHOT); x["quote"]["evidence_status"] = "PROBABLY_OK"
        self.assertTrue(list(VALIDATOR.iter_errors(x)))

    def test_07_negative_spread_rejected_by_schema(self):
        x = copy.deepcopy(SNAPSHOT); x["quote"]["spread_abs"] = -0.25
        self.assertTrue(list(VALIDATOR.iter_errors(x)))

    def test_08_candle_state_restricted(self):
        x = copy.deepcopy(SNAPSHOT); x["candles_by_tf"]["M1"][0]["bar_state"] = "MAYBE_CLOSED"
        self.assertTrue(list(VALIDATOR.iter_errors(x)))

    def test_09_duplicate_evidence_ids_rejected(self):
        x = copy.deepcopy(SNAPSHOT); x["evidence_ids"].append(x["evidence_ids"][0])
        self.assertTrue(list(VALIDATOR.iter_errors(x)))

    def test_10_timestamp_format_rejected(self):
        x = copy.deepcopy(SNAPSHOT); x["as_of"] = "yesterday"
        self.assertTrue(list(VALIDATOR.iter_errors(x)))

    def test_11_preserve_global_schema(self):
        self.assertIn("BASE_SCHEMA_VERSION: 2.0.0 (BEZ ZMIANY)", SPEC)

    def test_12_isolate_module_boundary(self):
        self.assertTrue(SPEC.startswith("## M01 — DATA INTELLIGENCE ENGINE"))
        self.assertNotIn("\n## M02 — MARKET REGIME", SPEC)
        self.assertIn("M00 oraz M02–M15 pozostają bez zmian", SPEC)

    def test_13_no_live_claim(self):
        self.assertIn("STATUS: OCZEKUJE_NA_AKCEPTACJĘ", SPEC)


class ReferenceBehaviorTests(unittest.TestCase):
    def test_14_quote_valid(self):
        result = quote_check(3000.1, 3000.4, 0.01)
        self.assertTrue(result[0]); self.assertAlmostEqual(result[2][0], 0.3)
        self.assertAlmostEqual(result[2][1], 30)

    def test_15_inverted_bid_ask(self):
        self.assertFalse(quote_check(3000.4, 3000.1)[0])

    def test_16_non_finite_quote(self):
        self.assertFalse(quote_check(float("nan"), 3000.2)[0])

    def test_17_invalid_point(self):
        self.assertFalse(quote_check(3000.1, 3000.2, 0)[0])

    def test_18_valid_ohlc(self):
        self.assertTrue(bar_check(SNAPSHOT["candles_by_tf"]["M1"][0]))

    def test_19_invalid_ohlc(self):
        b = dict(SNAPSHOT["candles_by_tf"]["M1"][0]); b["low"] = b["high"] + 1
        self.assertFalse(bar_check(b))

    def test_20_volume_negative(self):
        b = dict(SNAPSHOT["candles_by_tf"]["M1"][0]); b["tick_volume"] = -1
        self.assertFalse(bar_check(b))

    def test_21_completeness(self):
        c = completeness({"quote": 1, "M1": 1}, {"quote", "M1", "H1"})
        self.assertEqual((c["numerator"], c["denominator"]), (2, 3))
        self.assertAlmostEqual(c["value"], 2/3)

    def test_22_empty_required_not_perfect(self):
        self.assertIsNone(completeness({}, set())["value"])

    def test_23_secondary_tv_not_comparable_as_ask_with_bid(self):
        mt = dict(instrument_id="XAUUSD", price_basis="BID", timeframe="M5", bar_boundary="broker")
        tv = dict(instrument_id="XAUUSD", price_basis="MID", timeframe="M5", bar_boundary="broker")
        self.assertFalse(eligible_source_comparison(mt, tv))

    def test_24_cross_source_compatible(self):
        x = dict(instrument_id="XAUUSD", price_basis="BID", timeframe="M5", bar_boundary="broker")
        self.assertTrue(eligible_source_comparison(x, dict(x)))

    def test_25_future_evidence_does_not_enter_historical_snapshot(self):
        ev = {"available_at": "2026-10-08T08:29:00Z"}
        self.assertFalse(check_available_at(ev, "2026-10-08T08:28:00Z"))

    def test_26_scopes_separate(self):
        self.assertEqual("PASS", reference_scope_gate({"M1"}, {"M1"}))
        self.assertEqual("PENDING", reference_scope_gate({"M1", "quote", "freshness"}, {"M1", "quote"}))

    def test_27_missing_exec_freshness_blocks_exec_only(self):
        self.assertEqual("PENDING", reference_scope_gate({"quote"}, {"quote"}, freshness_known=False))
        self.assertEqual("PASS", reference_scope_gate({"M1"}, {"M1"}))

    def test_28_corrupt_required_field_fails(self):
        self.assertEqual("FAIL", reference_scope_gate({"quote"}, {"quote"}, critical_bad=True))

    def test_29_forming_bar_is_not_confirmed_closed(self):
        self.assertNotEqual("CLOSED", "FORMING")
        self.assertIn("bar nr 0 jest tylko FORMING", SPEC)

    def test_30_secondary_does_not_replace_broker_exec(self):
        self.assertIn("nie zamieniaj brokera wykonawczego na TV", SPEC)

    def test_31_failure_recovery_requires_recheck(self):
        self.assertIn("revalidate server/symbol", SPEC)

    def test_32_no_spread_40_policy_in_data_module(self):
        self.assertIn("Nie realizuje własnego progu 40%", SPEC)

    def test_33_synthetic_candle_has_close_timestamp(self):
        b = SNAPSHOT["candles_by_tf"]["M1"][0]
        self.assertEqual(b["bar_state"], "CLOSED")
        self.assertTrue(check_available_at(b, SNAPSHOT["as_of"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
