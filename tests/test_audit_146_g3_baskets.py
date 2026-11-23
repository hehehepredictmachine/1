"""1.46 audit (group G3_baskets) - regression tests for backend/masterquo/baskets/service.py (+ catalog docstring).

Unit level only (no HTTP server, no network): a fake Hyperliquid adapter, a fake runtime and an isolated data dir per test."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import types
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

import _env  # noqa: F401  (sys.path, MQ_BASKETS_OFFLINE)
import numpy as np

TF_S = {"M1": 60, "M3": 180, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600}


def _rt(**kw):
    return types.SimpleNamespace(**{"demo": True, "bridge": None, "db": None, "bus": None, "quant": None, "news": None, **kw})


def _walk(n: int, *, end_t: float, step: float, seed: int = 5, start: float = 2000.0) -> list[dict]:
    rng = np.random.default_rng(seed)
    c = start + np.cumsum(rng.normal(0, 1.5, n))
    out = []
    for k in range(n):
        o = c[k - 1] if k else c[0]
        out.append({"t": end_t - (n - 1 - k) * step, "o": float(o), "h": float(max(o, c[k]) + 0.5), "l": float(min(o, c[k]) - 0.5),
                    "c": float(c[k]), "tv": 1.0})
    return out


class FakeHL:
    """Public-data adapter double: catalog with core + Trade[XYZ] markets, closed candles aligned to real time."""

    errors = 0
    last_error = None

    def __init__(self):
        core = {"native_id": None, "dex": "core", "szDecimals": 3, "maxLeverage": 20, "delisted": False, "namespace": "Hyperliquid core"}
        xyz = {**core, "dex": "xyz", "namespace": "Trade[XYZ]"}
        self.cat = {"BTC": {**core, "native_id": "BTC"}, "ETH": {**core, "native_id": "ETH"}, "SOL": {**core, "native_id": "SOL"},
                    "xyz:SP500": {**xyz, "native_id": "xyz:SP500"}, "xyz:NVDA": {**xyz, "native_id": "xyz:NVDA"}}
        self.calls: list[tuple] = []

    def catalog(self):
        return self.cat

    def contexts(self):
        return {}

    def flow(self, coin):
        return {"t": time.time(), "connected": True}

    def candles(self, coin, tf, n=500):
        self.calls.append((coin, tf, n))
        sec = TF_S[tf]
        last = (time.time() // sec) * sec - sec                       # last CLOSED candle
        return [{"t": last - (n - 1 - k) * sec, "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.0, "v": 1.0, "trades": 1} for k in range(n)]


class _Svc(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.d = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def svc(self, **rt):
        from masterquo.baskets import service as BS
        return BS.BasketService(_rt(**rt), data_dir=self.d, hl=FakeHL())

    def write(self, name, obj):
        (self.d / name).write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8")


# ---------------------------------------------------------------------------------------------------------------- focus_X2#0
class TestResearchOnlyMarkets(_Svc):
    """Trade[XYZ] markets (INDICES / FOMO_STOCK_PERPS) are RESEARCH_ONLY - never scanned / ticketed by CRYPTO_FOMO_PERPS."""

    def test_update_settings_rejects_xyz_markets(self):
        s = self.svc()
        bad = ({"profiles": {"CRYPTO_FOMO_PERPS": {"instruments": ["BTC", "xyz:NVDA"]}}},
               {"profiles": {"CRYPTO_FOMO_PERPS": {"flow_instrument": "xyz:SP500"}}},
               {"profiles": {"CRYPTO_FOMO_PERPS": {"pair_map": {"SOL": "xyz:NVDA"}}}},
               {"profiles": {"CRYPTO_FOMO_PERPS": {"pair_map": {"xyz:NVDA": "SOL"}}}},
               {"profiles": {"CRYPTO_FOMO_PERPS": {"same_underlying": {"BTC": "xyz:BTC"}}}},
               {"strategies": {"CP_HEDGE_01": {"params": {"factor": "xyz:SP500"}}}},
               {"strategies": {"CP_HEDGE_05": {"params": {"pairs": {"SOL": "xyz:NVDA"}}}}})
        for patch in bad:
            with self.assertRaises(ValueError, msg=patch) as cm:
                s.update_settings(patch)
            self.assertTrue(str(cm.exception).startswith("RESEARCH_ONLY_MARKET"), cm.exception)
        self.assertFalse((self.d / "settings.json").exists())                                   # nothing stored
        st = s.update_settings({"profiles": {"CRYPTO_FOMO_PERPS": {"instruments": ["BTC", "SOL"], "pair_map": {"SOL": "ETH"}}}})
        self.assertEqual(st["profiles"]["CRYPTO_FOMO_PERPS"]["instruments"], ["BTC", "SOL"])

    def test_crypto_scan_never_runs_a_research_only_market(self):
        # settings stored by an older version (no validation then): kept in the file, excluded from the active scan
        stored = {"profiles": {"CRYPTO_FOMO_PERPS": {"instruments": ["BTC", "xyz:SP500", "xyz:NVDA"], "pair_map": {"BTC": "xyz:SP500", "SOL": "ETH"},
                                                     "same_underlying": {"BTC": "xyz:BTC"}}}}
        self.write("settings.json", stored)
        s = self.svc()
        seen = []
        s._run_ctx = lambda c, st, bars_fn, q, extra: seen.append((c.instrument, bars_fn, extra)) or {"state": "READY"}
        with mock.patch.dict(os.environ):
            os.environ.pop("MQ_BASKETS_OFFLINE", None)
            out = s._crypto(s.settings())
        self.assertEqual([x[0] for x in seen], ["BTC"])
        self.assertEqual(out["xyz:SP500"]["state"], "RESEARCH_ONLY")
        self.assertEqual(out["xyz:NVDA"]["state"], "RESEARCH_ONLY")
        self.assertFalse([k for k in s.ctx if "xyz:" in k])
        self.assertEqual(seen[0][2]["pair_map"], {"SOL": "ETH"})
        self.assertEqual(seen[0][2]["same_underlying"], {})
        self.assertEqual(json.loads((self.d / "settings.json").read_text(encoding="utf-8")), stored)   # file untouched (rollback)

    def test_hedge_leg_on_research_only_market_is_refused(self):
        from masterquo.baskets import catalog as CAT
        from masterquo.baskets import detectors as D
        from masterquo.baskets import hedge as HG
        s = self.svc()
        c = s._context("CRYPTO_FOMO_PERPS", "SOL", "HYPERLIQUID:core", "MAINNET", "PUBLIC_DATA", "PERPETUAL")
        c.feats["M15"] = D.build(_walk(300, end_t=1.7e9, step=900), 0.01)
        plan = {"plan_type": "HedgePlan", "legs": [{"instrument": "xyz:SP500", "side": "SHORT", "size": 1.0}]}
        with mock.patch.dict(HG.PLANNERS, {"crypto_beta": lambda ctx: {"state": "HEDGE_PLAN", "reason": "x", "plan": plan}}):
            s._hedge(c, CAT.BY_ID["CP_HEDGE_01"], s.settings(), {"exposure": [], "bars": {}})
        self.assertEqual(c.state["CP_HEDGE_01"]["state"], "NO_HEDGE")
        self.assertIn("RESEARCH_ONLY_MARKET", c.state["CP_HEDGE_01"]["reason"])
        with sqlite3.connect(self.d / "ledger.sqlite") as db:
            self.assertEqual(db.execute("SELECT count(*) FROM hedge_plans").fetchone()[0], 0)


# ---------------------------------------------------------------------------------------------------------------- chunk_06#2 / #3
class TestHyperliquidSeries(_Svc):
    def test_cache_does_not_truncate_a_longer_request(self):                       # chunk_06#2
        s = self.svc()
        c = s._context("CRYPTO_FOMO_PERPS", "ETH", "HYPERLIQUID:core", "MAINNET", "PUBLIC_DATA", "PERPETUAL")
        self.assertEqual(len(s._hl_bars(c, "ETH", "M5", 300)), 300)                   # auxiliary series first (as in _crypto)
        self.assertEqual(len(s._hl_bars(c, "ETH", "M5", 500)), 500)                   # own signal series: full length
        n_calls = len(s.hl.calls)
        self.assertEqual(len(s._hl_bars(c, "ETH", "M5", 300)), 300)                   # served from the cache, sliced
        self.assertEqual(len(s._hl_bars(c, "ETH", "M5", 500)), 500)
        self.assertEqual(len(s.hl.calls), n_calls)

    def test_signal_series_covers_previous_utc_day(self):                          # chunk_06#3
        self.write("settings.json", {"profiles": {"CRYPTO_FOMO_PERPS": {"instruments": ["BTC"]}}})
        s = self.svc()
        seen = []
        s._run_ctx = lambda c, st, bars_fn, q, extra: seen.append(bars_fn) or {"state": "READY"}
        with mock.patch.dict(os.environ):
            os.environ.pop("MQ_BASKETS_OFFLINE", None)
            s._crypto(s.settings())
        self.assertEqual(len(seen[0]("M5", 600)), 600)                                 # _run_ctx asks for 600 (was capped at 500)
        # why 600: CP_SMC_09 (PREV_UTC_DAY) needs the whole previous UTC day + the current day; at 22:00 UTC 500 M5 bars are not enough
        from masterquo.baskets import detectors as D
        from masterquo.baskets import rules as R
        end = datetime(2026, 11, 20, 22, 0, tzinfo=UTC).timestamp()
        with self.assertRaises(R.Unavailable):
            R.range_sweep(D.build(_walk(500, end_t=end, step=300), 0.01), 1, {"range": "PREV_UTC_DAY"}, {})
        R.range_sweep(D.build(_walk(600, end_t=end, step=300), 0.01), 1, {"range": "PREV_UTC_DAY"}, {})     # no Unavailable


# ---------------------------------------------------------------------------------------------------------------- chunk_06#4
class TestFxHedgeUnsuppliedInputs(_Svc):
    def _fx(self, s, tf, end_t):
        from masterquo.baskets import detectors as D
        c = s._context("FOREX_MT5", "XAUUSD-", "MT5", "SYNTHETIC", "1", "CFD")
        c.feats[tf] = D.build(_walk(400, end_t=end_t, step=TF_S[tf]), 0.01)
        extra = {"account": {"margin_mode": "HEDGING", "currency": "USD"}, "spec": {"XAUUSD-": {"point": 0.01, "spread_price": 0.2}},
                 "exposure": [{"leg": "PRIMARY", "symbol": "XAUUSD-", "side": "LONG", "volume": 1.0, "id": "P1"},
                              {"leg": "PRIMARY", "symbol": "EURUSD", "side": "LONG", "volume": 1.0, "id": "P2"}],
                 "fx_pairs": ["GBPUSD"], "pair_map": {"XAUUSD-": "XAGUSD"}, "symbol": "XAUUSD-", "events": None}
        return c, extra

    def test_planners_without_service_inputs_report_unsupported_input(self):
        from masterquo.baskets import catalog as CAT
        s = self.svc()
        s.update_settings({"strategies": {"FX_HEDGE_10": {"params": {"risk_limit": 0.0}}}})
        st = s.settings()
        c, extra = self._fx(s, "M15", 1.7e9)
        for sid in ("FX_HEDGE_08", "FX_HEDGE_09", "FX_HEDGE_10"):
            s._hedge(c, CAT.BY_ID[sid], st, extra)
            self.assertEqual(c.state[sid]["state"], "UNSUPPORTED_INPUT", (sid, c.state[sid]))
            self.assertIn("nie pobiera świec", c.state[sid]["reason"])
        tokyo_open = datetime(2026, 11, 20, 0, 5, tzinfo=UTC).timestamp()           # 09:05 Asia/Tokyo -> session transition
        c, extra = self._fx(s, "M5", tokyo_open)
        s._hedge(c, CAT.BY_ID["FX_HEDGE_04"], st, extra)
        self.assertEqual(c.state["FX_HEDGE_04"]["state"], "UNSUPPORTED_INPUT", c.state["FX_HEDGE_04"])
        self.assertIn("mediany spreadu", c.state["FX_HEDGE_04"]["reason"])

    def test_missing_data_that_the_service_does_supply_stays_waiting(self):
        from masterquo.baskets import catalog as CAT
        s = self.svc()
        c, extra = self._fx(s, "M15", 1.7e9)
        s._hedge(c, CAT.BY_ID["FX_HEDGE_08"], s.settings(), {**extra, "bars": {"XAUUSD-": {"M15": []}}})     # bars supplied, partner empty
        self.assertEqual(c.state["FX_HEDGE_08"]["state"], "WAITING_FOR_DATA")


# ---------------------------------------------------------------------------------------------------------------- chunk_06#10
class TestSettingsValidation(_Svc):
    BAD = ({"profiles": {"FOREX_MT5": "x"}}, {"profiles": {"FOREX_MT5": None}}, {"baskets": {"FX_SMC": 5}}, {"strategies": {"FX_SMC_01": "on"}},
           {"profiles": {"FOREX_MT5": {"enabled": "no"}}}, {"profiles": {"FOREX_MT5": {"capital": {"risk_money": "abc"}}}},
           {"profiles": {"FOREX_MT5": {"capital": {"risk_money": -5}}}}, {"profiles": {"FOREX_MT5": {"capital": 5}}},
           {"profiles": {"CRYPTO_FOMO_PERPS": {"instruments": "BTC"}}}, {"profiles": {"FOREX_MT5": {"fx_pairs": [1]}}},
           {"baskets": {"FX_SMC": {"max_pending_intents": "dużo"}}}, {"baskets": {"FX_SMC": {"cooldown_bars": -1}}},
           {"baskets": {"FX_SMC": {"max_pending_intents": 2.5}}}, {"baskets": {"FX_SMC": {"enabled": 1}}},
           {"strategies": {"FX_SMC_01": {"params": {"tp_r": "ab"}}}}, {"strategies": {"FX_SMC_01": {"params": {"tp_r": ["a", 3.0]}}}},
           {"strategies": {"FX_SMC_01": {"params": "x"}}}, {"strategies": {"FX_SMC_01": {"enabled": "yes"}}},
           {"strategies": {"FX_SMC_03": {"params": {"max_wait": "6"}}}}, {"strategies": {"FX_SMC_01": {"params": {"timeout_bars": float("nan")}}}},
           {"manual_select": {"FOREX_MT5": 5}}, {"manual_select": {"FOREX_MT5": [5]}}, {"manual_select": {"NOPE": ["FX_SMC_01"]}},
           {"active_profile": ["FOREX_MT5"]})

    def test_bad_types_are_400_and_never_stored(self):
        s = self.svc()
        s.update_settings({"strategies": {"FX_SMC_02": {"enabled": False}}})
        before = (self.d / "settings.json").read_text(encoding="utf-8")
        for patch in self.BAD:
            with self.assertRaises(ValueError, msg=patch):
                s.update_settings(patch)
        with self.assertRaises(ValueError):
            s.update_settings(["profiles"])                                              # not an object
        self.assertEqual((self.d / "settings.json").read_text(encoding="utf-8"), before)

    def test_valid_patches_still_accepted(self):
        s = self.svc()
        for patch in ({"active_profile": "CRYPTO_FOMO_PERPS"}, {"profiles": {"FOREX_MT5": {"selection": "MANUAL_SELECT"}}},
                      {"baskets": {"FX_SMC": {"enabled": False, "max_pending_intents": 2, "cooldown_bars": 0}}},
                      {"strategies": {"FX_SMC_01": {"enabled": True, "params": {"tp_r": [1.5, 2], "timeout_bars": 12}}}},
                      {"strategies": {"FX_HEDGE_09": {"params": {"partner": "EURUSD"}}}},
                      {"profiles": {"FOREX_MT5": {"capital": {"risk_money": 50}, "fx_pairs": ["EURUSD"], "pair_map": {"XAUUSD-": "XAGUSD"}}}},
                      {"profiles": {"CRYPTO_FOMO_PERPS": {"capital": {"risk_money": None}, "fees": {"taker": 0.00045, "maker": None}}}},
                      {"manual_select": {"FOREX_MT5": ["FX_SMC_01"]}}):
            s.update_settings(patch)
        st = s.settings()
        self.assertEqual(st["strategies"]["FX_SMC_01"]["params"]["tp_r"], [1.5, 2])
        self.assertEqual(st["baskets"]["FX_SMC"]["max_pending_intents"], 2)

    def test_stored_non_object_entries_do_not_break_views(self):
        self.write("settings.json", {"profiles": {"FOREX_MT5": "x", "CRYPTO_FOMO_PERPS": None}, "baskets": {"FX_SMC": 5}})
        s = self.svc()
        st = s.settings()
        self.assertIsInstance(st["profiles"]["FOREX_MT5"], dict)
        self.assertIsInstance(st["baskets"]["FX_SMC"], dict)
        s.status()
        s.basket_view()
        s.sh_candidates("XAUUSD-")


# ---------------------------------------------------------------------------------------------------------------- chunk_06#11 / focus_X2#12 / chunk_07#6
class TestDamagedFiles(_Svc):
    def test_sfb_json_not_an_object_keeps_the_service_alive(self):
        for raw in ("null", "[]", "5", '"x"', '{"mode": "OFF", "future_key": 1}', '{"mode": "TURBO"}'):
            self.write("sfb.json", raw)
            s = self.svc()                                                               # must not raise
            st = s.sfb.status()
            self.assertEqual(st["mode"], "OFF", raw)
            self.assertTrue(str(st["mode_requested"]).startswith("INVALID_CONFIG"), (raw, st["mode_requested"]))
            self.assertEqual((self.d / "sfb.json").read_text(encoding="utf-8"), raw)    # file left as it is

    def test_settings_json_not_an_object(self):
        for raw in ("[1]", "5", '"x"'):
            self.write("settings.json", raw)
            s = self.svc()
            self.assertEqual(s.settings()["active_profile"], "FOREX_MT5", raw)
            s.status()

    def _run_thread(self, cycle_s, secs):
        self.write("settings.json", {"cycle_s": cycle_s, "profiles": {"FOREX_MT5": {"enabled": False}, "CRYPTO_FOMO_PERPS": {"enabled": False}}})
        s = self.svc()
        calls = []
        s.cycle = lambda: calls.append(1) or {}
        s.start()
        try:
            time.sleep(secs)
            alive = s._thread.is_alive()
        finally:
            s.stop()
            s._thread.join(5)
        return alive, len(calls)

    def test_invalid_cycle_s_does_not_kill_the_thread(self):
        alive, n = self._run_thread("abc", 0.4)
        self.assertTrue(alive)
        self.assertEqual(n, 1)

    def test_negative_cycle_s_is_not_a_busy_loop(self):
        alive, n = self._run_thread(-3, 0.5)
        self.assertTrue(alive)
        self.assertLessEqual(n, 2)


# ---------------------------------------------------------------------------------------------------------------- chunk_06#12
class TestViewsUnderConcurrentWrites(_Svc):
    def test_status_and_basket_view_while_the_basket_thread_adds_contexts_and_states(self):
        s = self.svc()
        stop = threading.Event()

        def writer():                                   # what the basket thread does: new contexts (under the lock) + new state keys
            k = 0
            while not stop.is_set():
                k += 1
                c = s._context("FOREX_MT5" if k % 2 else "CRYPTO_FOMO_PERPS", f"I{k // 25}", "V", "E", "A", "P")
                c.state[f"S{k}"] = {"state": "NO_SETUP"}
        old = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)
        t = threading.Thread(target=writer, daemon=True)
        t.start()
        errors = []
        try:
            end = time.monotonic() + 1.5
            while time.monotonic() < end:
                try:
                    s.status()
                    s.basket_view()
                except RuntimeError as exc:
                    errors.append(str(exc))
        finally:
            stop.set()
            t.join(5)
            sys.setswitchinterval(old)
        self.assertEqual(errors[:3], [])


# ---------------------------------------------------------------------------------------------------------------- chunk_06#20 / focus_X2#19
class TestRetiredOtcFeedIsLazy(_Svc):
    def test_start_does_not_create_otc_dirs_or_load_ticks(self):
        s = self.svc()
        self.assertFalse((self.d / "otc").exists())
        s.cycle()                                                                       # offline: nothing scanned, OTC never touched
        self.assertFalse((self.d / "otc").exists())

    def test_legacy_history_reader_still_available_on_demand(self):
        (self.d / "otc").mkdir()
        (self.d / "otc" / "ticks.jsonl").write_text("[1700000000.0, 2000.5]\n", encoding="utf-8")
        s = self.svc()
        self.assertEqual(s.otc.state()["state"], "HISTORY_ONLY")
        self.assertEqual(s.otc.price_at(1700000001.0), 2000.5)


# ---------------------------------------------------------------------------------------------------------------- focus_X2#18
class TestRetiredOtcSignals(_Svc):
    def test_active_otc_signal_from_old_version_is_shown_retired_not_active(self):
        s = self.svc()
        row = {"signal_id": "EV-1|OTC_SMC_01", "event_id": "EV-1", "strategy_id": "OTC_SMC_01", "basket_id": "OTC_SMC", "profile_id": "OTC_GOLD_POCKETOPTION",
               "context_key": "OTC_GOLD_POCKETOPTION|POCKET_OPTION|LIVE|USER|FIXED_EXPIRY|GOLD_OTC", "instrument": "GOLD_OTC", "tf": "S15", "side": "CALL",
               "created_at": 1.7e9, "bar_t": 1.7e9, "status": "ACTIVE", "role": "PRIMARY", "plan": {"plan_type": "FixedExpiryPlan"}, "setup": {}, "scores": {}}
        self.assertTrue(s.ledger.add_signal(row))
        got = s.ledger.recent()[0]
        self.assertEqual(got["status"], "RETIRED")
        self.assertEqual(got["stored_status"], "ACTIVE")
        self.assertEqual(s.ledger.open_signals(), [])
        with sqlite3.connect(self.d / "ledger.sqlite") as db:                                # stored row untouched (history / rollback)
            self.assertEqual(db.execute("SELECT status FROM signals").fetchone()[0], "ACTIVE")


# ---------------------------------------------------------------------------------------------------------------- chunk_06#22
class TestTrackDataGap(_Svc):
    def _signal(self, s, c, bar_t):
        sig = {"signal_id": f"EV-{bar_t}|FX_SMC_01", "event_id": f"EV-{bar_t}", "strategy_id": "FX_SMC_01", "basket_id": "FX_SMC", "profile_id": "FOREX_MT5",
               "context_key": c.key, "instrument": c.instrument, "tf": "M5", "side": "LONG", "created_at": bar_t, "bar_t": bar_t, "status": "ACTIVE",
               "role": "PRIMARY", "plan": {"plan_type": "PositionPlan", "side": "LONG", "sl": 90.0, "targets": [{"price": 110.0}], "timeout_bars": 4},
               "setup": {}, "scores": {}}
        s.ledger.add_signal(sig)
        return sig["signal_id"]

    def _flat(self, t0, n):
        return [{"t": t0 + k * 300, "o": 100.0, "h": 100.5, "l": 99.5, "c": 100.0} for k in range(n)]

    def test_window_starting_after_the_signal_is_unknown_not_a_guess(self):
        s = self.svc()
        c = s._context("FOREX_MT5", "XAUUSD-", "MT5", "SYNTHETIC", "1", "CFD")
        t0 = 1.7e9
        gap = self._signal(s, c, t0)
        s._track(c, {"M5": self._flat(t0 + 100 * 300, 50)})                                 # bars right after the signal are missing
        row = next(r for r in s.ledger.recent() if r["signal_id"] == gap)
        self.assertEqual((row["status"], row["outcome_kind"]), ("CLOSED", "UNKNOWN"))

    def test_continuous_window_is_still_simulated(self):
        s = self.svc()
        c = s._context("FOREX_MT5", "XAUUSD-", "MT5", "SYNTHETIC", "1", "CFD")
        t0 = 1.7e9
        ok = self._signal(s, c, t0)
        s._track(c, {"M5": self._flat(t0 - 10 * 300, 30)})
        row = next(r for r in s.ledger.recent() if r["signal_id"] == ok)
        self.assertEqual((row["status"], row["outcome_kind"]), ("CLOSED", "TIMEOUT"))
        self.assertEqual(row["outcome_at"], t0 + 4 * 300)


if __name__ == "__main__":
    unittest.main()
