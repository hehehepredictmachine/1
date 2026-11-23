"""1.46 data exporters: every exporter writes CSV + JSONL + manifest.json; row counts equal the source, hashes verify, an empty source gives
a valid empty export, no secret ever reaches a file, real and virtual data stay in separate files, the TraderLifeGame backup imports
additively / idempotently with a pre-import copy, and the API writes only into <data>/exports."""
from __future__ import annotations

import collections
import json
import math
import os
import random
import sqlite3
import time
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path

import _env  # noqa: F401
from _env import TempData

TOKEN = "123456789:AAFakeTelegramTokenForTests_abcdefghijklmn"      # token-shaped, never a real one


class FakeHL:
    """Hyperliquid public API double: deterministic metadata, candles, trades and book (no network)."""

    def __init__(self, n_trades=40):
        self.errors, self.last_error = 0, None
        self.n_trades = n_trades
        self.calls = []

    def post(self, body):
        self.calls.append(body)
        t = body.get("type")
        if t == "perpDexs":
            return [None, {"name": "xyz"}]
        if t == "meta" and body.get("dex") == "xyz":
            return {"universe": [{"name": "xyz:NVDA", "szDecimals": 3, "maxLeverage": 10}, {"name": "xyz:TSLA", "szDecimals": 3, "maxLeverage": 10},
                                 {"name": "xyz:SP500", "szDecimals": 2, "maxLeverage": 20}, {"name": "xyz:GOLD", "szDecimals": 2, "maxLeverage": 20}]}
        if t == "meta":
            return {"universe": [{"name": "BTC", "szDecimals": 5, "maxLeverage": 40}, {"name": "ETH", "szDecimals": 4, "maxLeverage": 25}]}
        if t == "candleSnapshot":
            iv = body["req"]["interval"]
            step = {"1d": 86400, "8h": 28800, "4h": 14400, "1h": 3600, "30m": 1800, "15m": 900, "5m": 300, "3m": 180, "1m": 60}[iv]
            end = body["req"]["endTime"] // 1000 // step * step
            out = []
            for k in range(60, 0, -1):
                t0 = end - k * step
                px = 100 + math.sin(t0 / 5000.0)
                out.append({"t": t0 * 1000, "T": (t0 + step) * 1000 - 1, "o": str(px), "h": str(px + 1), "l": str(px - 1), "c": str(px + 0.5),
                            "v": "3.5", "n": 7})
            out.append({"t": end * 1000, "T": (end + step) * 1000 - 1, "o": "1", "h": "1", "l": "1", "c": "1", "v": "1", "n": 1})   # forming
            return out
        if t == "recentTrades":
            base = 1_795_000_000_000
            return [{"tid": 1000 + i, "time": base + i * 1500, "px": str(100 + (i % 5) * 0.1), "sz": str(0.5 + i % 3), "side": "B" if i % 2 else "A"}
                    for i in range(self.n_trades)]
        if t == "l2Book":
            return {"time": 1_795_000_100_000, "levels": [[{"px": str(100 - i * 0.1), "sz": str(1 + i)} for i in range(5)],
                                                          [{"px": str(100.1 + i * 0.1), "sz": str(2 + i)} for i in range(5)]]}
        if t == "metaAndAssetCtxs":
            return [{"universe": []}, []]
        return None


def all_text(folder: Path) -> str:
    return "".join(p.read_text(encoding="utf-8") for p in sorted(folder.iterdir()) if p.is_file())


class Base(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.data = Path(self.td.dir)

    def tearDown(self):
        self.td.close()

    def ctx(self, **kw):
        from masterquo.exports.sources import SourceContext
        return SourceContext(self.data, **kw)

    def run_export(self, name, ctx=None, params=None, formats=("csv", "jsonl")):
        from masterquo.exports import registry as R
        return R.run(name, ctx or self.ctx(), params or {}, formats=formats)

    def check(self, man, expected_rows: dict | None = None):
        """manifest + hashes verify; CSV and JSONL carry the same rows; optional exact row counts per dataset."""
        from masterquo.exports.core import SCHEMA_VERSION, read_rows, verify_export
        folder = Path(man["path"])
        v = verify_export(folder)
        self.assertTrue(v["ok"], v["problems"])
        m = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(m["schema_version"], SCHEMA_VERSION)
        for k in ("export_id", "provenance", "date_range", "row_counts", "total_rows", "files", "created_at_utc"):
            self.assertIn(k, m)
        self.assertTrue(m["created_at_utc"].endswith("Z"))
        self.assertEqual(m["total_rows"], sum(m["row_counts"].values()))
        for f in m["files"]:
            self.assertEqual(len(read_rows(folder / f["path"])), m["row_counts"][f["dataset"]])
        if expected_rows is not None:
            for ds, n in expected_rows.items():
                self.assertEqual(m["row_counts"][ds], n, ds)
        self.assertNotIn(TOKEN, all_text(folder))
        kinds = {}
        for f in m["files"]:
            kinds.setdefault(f["dataset"], set()).add(f["data_kind"])
        self.assertTrue(all(len(k) == 1 for k in kinds.values()), kinds)         # one data kind per file / dataset
        return m, folder


# ---------------------------------------------------------------------------------------------------- core writer
class TestCore(Base):
    def test_csv_jsonl_manifest_nulls_and_atomic_folder(self):
        from masterquo.exports.core import Collected, Dataset, read_rows, write_export
        rows = [{"t_utc": "2026-11-20T10:00:00Z", "x": 1.5, "missing": None, "nan": float("nan"), "nested": {"a": [1, 2]}, "flag": True},
                {"t_utc": "2026-11-21T10:00:00Z", "x": 2, "missing": None, "nan": float("inf"), "nested": None, "flag": False}]
        man = write_export("unit-test", Collected([Dataset("t", rows, "DERIVED", time_columns={"t_utc": "UTC"})], {"source": "test"}),
                           data_dir=self.data, secret_values=[])
        m, folder = self.check(man, {"t": 2})
        j = read_rows(folder / "t.jsonl")
        self.assertIsNone(j[0]["missing"])
        self.assertIsNone(j[0]["nan"])                       # NaN / Inf -> null, never 0
        self.assertIsNone(j[1]["nan"])
        c = read_rows(folder / "t.csv")
        self.assertEqual(c[0]["missing"], "")
        self.assertEqual(c[0]["flag"], "true")
        self.assertEqual(m["date_range"]["from_utc"], "2026-11-20T10:00:00Z")
        self.assertEqual(m["date_range"]["to_utc"], "2026-11-21T10:00:00Z")
        self.assertEqual([p.name for p in folder.parent.iterdir() if p.name.startswith(".")], [])    # no partial folder left
        self.assertEqual(folder.parent, self.data / "exports")

    def test_secret_values_and_patterns_are_redacted(self):
        from masterquo.exports.core import Collected, Dataset, write_export
        from masterquo.secrets_store import SecretStore
        SecretStore(self.data).set("ANTHROPIC_API_KEY", "custom-secret-value-123456")
        rows = [{"text": f"token {TOKEN} key custom-secret-value-123456 and sk-ant-api03-abcdefghijklmnopqrstuvwxyz"}]
        man = write_export("unit-test", Collected([Dataset("t", rows, "STATE")], {"source": "test", "leak": TOKEN}), data_dir=self.data)
        m, folder = self.check(man, {"t": 1})
        txt = all_text(folder)
        self.assertNotIn("custom-secret-value-123456", txt)
        self.assertNotIn("sk-ant-api03", txt)
        self.assertNotIn(TOKEN, txt)
        self.assertGreaterEqual(m["redactions"], 4)

    def test_tampered_file_fails_verification(self):
        from masterquo.exports.core import Collected, Dataset, verify_export, write_export
        man = write_export("unit-test", Collected([Dataset("t", [{"a": 1}], "STATE")], {}), data_dir=self.data, secret_values=[])
        p = Path(man["path"]) / "t.csv"
        p.write_text("a\n2\n", encoding="utf-8")
        v = verify_export(Path(man["path"]))
        self.assertFalse(v["ok"])
        self.assertTrue(any("SHA256_MISMATCH" in x for x in v["problems"]))

    def test_bad_names_formats_and_ids_rejected(self):
        from masterquo.exports.core import Collected, Dataset, ExportError, export_dir, write_export
        with self.assertRaises(ExportError):
            Dataset("../x", [], "STATE")
        with self.assertRaises(ExportError):
            Dataset("x", [], "MONEY")
        with self.assertRaises(ExportError):
            write_export("../evil", Collected([], {}), data_dir=self.data, secret_values=[])
        with self.assertRaises(ExportError):
            write_export("ok", Collected([], {}), data_dir=self.data, formats=("xlsx",), secret_values=[])
        for bad in ("../../etc", "bootstrap-20261123T000000Z-zzzzzz", "", None, "a/b"):
            with self.assertRaises(ExportError):
                export_dir(bad, self.data)

    def test_registry_params_bounded(self):
        from masterquo.exports import registry as R
        from masterquo.exports.core import ExportError
        with self.assertRaises(ExportError):
            R.run("nope", self.ctx())
        with self.assertRaises(ExportError):
            R.run("change-points", self.ctx(), {"lookback": "abc"})
        with self.assertRaises(ExportError):
            R.run("change-points", self.ctx(), {"lookback": "999999"})
        with self.assertRaises(ExportError):
            R.run("market-candles", self.ctx(hl=FakeHL()), {"instruments": "BTC", "timeframes": "2h"})
        with self.assertRaises(ExportError):
            R.run("bootstrap", self.ctx(), {"path": "/etc"})                  # no path parameter exists


# ---------------------------------------------------------------------------------------------------- sources
class TestTraderLifeGame(Base):
    def make_game(self, d: Path):
        from masterquo.trader_life_game import GameService
        g = GameService(d / "trader_life_game")
        g.create_profile({"username": "Kopia", "class_id": "THE_ANALYST", "difficulty": "MEDIUM", "virtual_capital": 20000})
        g.add_note("ANALYSIS", {"text": "Analiza H1: sweep dołka azjatyckiego i reclaim powyżej poziomu.", "invalidation": "2390"})
        g.coach_memory_add("Pamiętaj o dzienniku")
        return g

    def counts(self, dbp: Path) -> dict:
        c = sqlite3.connect(str(dbp))
        try:
            return {t: c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in
                    ("profile", "events", "xp_ledger", "gold_ledger", "notes", "inventory", "coach_memory", "quest_claims")}
        finally:
            c.close()

    def test_export_matches_db_and_import_is_additive_idempotent_reversible(self):
        g = self.make_game(self.data)
        src_counts = self.counts(self.data / "trader_life_game" / "game.sqlite")
        g.close()
        self.assertGreater(src_counts["xp_ledger"], 0)
        man = self.run_export("trader-life-game")
        m, folder = self.check(man, {k: v for k, v in src_counts.items()})
        self.assertEqual(m["provenance"]["game_schema_version"], "1")
        kinds = {f["dataset"]: f["data_kind"] for f in m["files"]}
        self.assertEqual((kinds["sim_trades"], kinds["notes"], kinds["xp_ledger"]), ("SIMULATED", "USER_NOTE", "GAME"))
        rows = json.loads((folder / "xp_ledger.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self.assertTrue(rows["ts_utc"].endswith("Z"))
        # import into a fresh installation
        from masterquo.exports.tlg_import import import_backup
        other = TempData()
        try:
            od = Path(other.dir)
            rep = import_backup(folder, od)
            self.assertEqual(rep["profile"], "IMPORTED")
            self.assertIsNone(rep["pre_import_copy"])                       # nothing existed before
            self.assertEqual(self.counts(od / "trader_life_game" / "game.sqlite"), src_counts)
            rep2 = import_backup(folder, od)                                  # idempotent
            self.assertEqual(rep2["total_inserted"], 0)
            self.assertTrue(Path(rep2["pre_import_copy"]).is_file())        # reversible: copy made before writing
            self.assertEqual(self.counts(od / "trader_life_game" / "game.sqlite"), src_counts)
            # the restored game works (XP totals equal)
            from masterquo.trader_life_game import GameService
            g2 = GameService(od / "trader_life_game")
            g1 = GameService(self.data / "trader_life_game")
            self.assertEqual((g2.xp_total(), g2.gold_total()), (g1.xp_total(), g1.gold_total()))
            g1.close()
            g2.close()
        finally:
            other.close()

    def test_import_keeps_existing_profile_and_dry_run_writes_nothing(self):
        self.make_game(self.data).close()
        man = self.run_export("trader-life-game")
        from masterquo.exports.tlg_import import import_backup
        from masterquo.trader_life_game import GameService
        other = TempData()
        try:
            od = Path(other.dir)
            g = GameService(od / "trader_life_game")
            g.create_profile({"username": "Inny", "class_id": "THE_ROOKIE", "difficulty": "EASY"})
            g.close()
            before = self.counts(od / "trader_life_game" / "game.sqlite")
            dry = import_backup(Path(man["path"]), od, dry_run=True)
            self.assertTrue(dry["dry_run"])
            self.assertEqual(self.counts(od / "trader_life_game" / "game.sqlite"), before)
            rep = import_backup(Path(man["path"]), od)
            self.assertTrue(rep["profile"].startswith("KEPT_EXISTING"))
            g = GameService(od / "trader_life_game")
            self.assertEqual(g._profile()["username"], "Inny")
            g.close()
        finally:
            other.close()

    def test_import_rejects_tampered_or_foreign_backup(self):
        from masterquo.exports.core import ExportError
        from masterquo.exports.tlg_import import import_backup
        self.make_game(self.data).close()
        man = self.run_export("trader-life-game")
        p = Path(man["path"]) / "profile.jsonl"
        p.write_text(p.read_text(encoding="utf-8").replace("Kopia", "Hakr!"), encoding="utf-8")
        with self.assertRaises(ExportError):
            import_backup(Path(man["path"]), self.data)
        boot = self.run_export("bootstrap")
        with self.assertRaises(ExportError):
            import_backup(Path(boot["path"]), self.data)

    def test_empty_source_valid_empty_export(self):
        man = self.run_export("trader-life-game")
        m, _ = self.check(man)
        self.assertEqual((m["status"], m["total_rows"]), ("EMPTY", 0))


class TestTelegramCenter(Base):
    def test_events_outbox_no_token_and_masked_account(self):
        from masterquo.notify.account_center import AccountCenter
        from masterquo.secrets_store import SecretStore
        SecretStore(self.data).set("TELEGRAM_BOT_TOKEN", TOKEN)
        deals = [{"ticket": 11, "position_id": 11, "type": 0, "entry": 0, "symbol": "XAUUSD", "volume": 0.1, "price": 2400.0, "time": 1_795_000_000,
                  "magic": 0, "profit": 0, "commission": 0, "swap": 0}]
        acct = {"server": "Broker-Live", "login": 987654321}
        c = AccountCenter(self.data / "telegram_account", deals_fn=lambda: list(deals), account_fn=lambda: acct, clock=lambda: 1_795_000_000.0)
        c.bind("Broker-Live:987654321")
        c.update({"account_event_enabled": True, "notify_position_open": True, "notify_position_close": True})
        deals.append({"ticket": 12, "position_id": 12, "type": 1, "entry": 0, "symbol": "XAUUSD", "volume": 0.2, "price": 2401.0, "time": 1_795_000_100,
                      "magic": 0, "profit": 0, "commission": 0, "swap": 0})
        evs = c.poll()
        self.assertEqual(len(evs), 1)
        c.state["outbox"].append({"key": "leak-test", "text": f"debug {TOKEN}"})       # even a leaked token never leaves in an export
        c._save()
        st = json.loads((self.data / "telegram_account" / "telegram_account_state.json").read_text(encoding="utf-8"))
        man = self.run_export("telegram-center")
        m, folder = self.check(man, {"outbox_pending": len(st["outbox"]), "seen_deals": len(st["cursor"]), "sent_events": len(st["sent_keys"])})
        txt = all_text(folder)
        self.assertNotIn(TOKEN, txt)
        self.assertNotIn("987654321", txt)
        self.assertIn("Broker-Live:***321", txt)
        self.assertGreaterEqual(m["redactions"], 1)

    def test_empty(self):
        m, _ = self.check(self.run_export("telegram-center"))
        self.assertEqual((m["status"], m["total_rows"]), ("EMPTY", 0))


class TestStrategyRoi(Base):
    def test_environments_in_separate_files_and_counts(self):
        from masterquo.db.database import Database
        from masterquo.evaluation import strategy_roi as SR
        db = Database(self.data / "masterquo.sqlite")
        cols = [r["name"] for r in db.query("PRAGMA table_info(trades)")]
        k = 0
        for mode, n in (("PAPER", 5), ("AUTO_LIVE", 3)):
            for i in range(n):
                k += 1
                row = {c: None for c in cols}
                row.update({"mode": mode, "source": "BOT", "strategy_id": "S01", "symbol": "XAUUSD-", "account_key": "Srv:12345678",
                            "closed_at": f"2026-11-{10 + i:02d}T10:00:00Z", "net_pnl": 10.0 if i % 2 else -5.0, "status": "CLOSED"})
                for c in cols:
                    if row[c] is None and c in ("id",):
                        row.pop(c)
                req = [r for r in db.query("PRAGMA table_info(trades)") if r["notnull"] and r["dflt_value"] is None and r["name"] != "id"]
                for r in req:
                    if row.get(r["name"]) is None:
                        row[r["name"]] = f"x{k}" if r["type"].upper() == "TEXT" else 0
                keys = [c for c in row if row[c] is not None]
                with db.tx() as cx:
                    cx.execute(f"INSERT INTO trades({','.join(keys)}) VALUES({','.join('?' * len(keys))})", [row[c] for c in keys])
        exp = {name: len(SR.report(SR.outcomes_from_db(db, mode, None))["items"]) + len(SR.report(SR.outcomes_from_db(db, mode, None))["retired_scope"])
               for mode, name, _ in (("PAPER", "roi_paper", 0), ("AUTO_DEMO", "roi_auto_demo", 0), ("AUTO_LIVE", "roi_auto_live", 0))}
        man = self.run_export("strategy-roi")
        m, folder = self.check(man, exp)
        kinds = {f["dataset"]: f["data_kind"] for f in m["files"]}
        self.assertEqual((kinds["roi_paper"], kinds["roi_auto_demo"], kinds["roi_auto_live"]), ("VIRTUAL", "DEMO", "REAL"))
        txt = all_text(folder)
        self.assertNotIn("12345678", txt)
        live = json.loads((folder / "roi_auto_live.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(live["trades"], 3)
        self.assertEqual(live["scope_environment"], "AUTO_LIVE")

    def test_no_database_gives_empty_export_without_creating_it(self):
        m, _ = self.check(self.run_export("strategy-roi"))
        self.assertEqual(m["status"], "EMPTY")
        self.assertFalse((self.data / "masterquo.sqlite").exists())


class TestBootstrap(Base):
    def test_state_rows(self):
        from masterquo.bootstrap import COMPONENTS, Bootstrap
        b = Bootstrap(state_file=self.data / "bootstrap_state.json", probes={c[0]: (lambda: (True, "ok")) for c in COMPONENTS})
        b.verify_all()
        m, folder = self.check(self.run_export("bootstrap"), {"components": len(COMPONENTS)})
        r = json.loads((folder / "components.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(r["state"], "VERIFIED")
        self.assertTrue(r["at_utc"].endswith("Z"))

    def test_empty(self):
        m, _ = self.check(self.run_export("bootstrap"))
        self.assertEqual((m["status"], m["total_rows"]), ("EMPTY", 0))


class TestMarkets(Base):
    def test_candles_all_ten_timeframes(self):
        from masterquo.markets.universe import TIMEFRAMES
        hl = FakeHL()
        man = self.run_export("market-candles", self.ctx(hl=hl), {"market": "CRYPTO", "instruments": "BTC", "n": "40"})
        m, folder = self.check(man)
        self.assertEqual(len([f for f in m["files"] if f["format"] == "csv"]), len(TIMEFRAMES))
        self.assertEqual(m["row_counts"]["candles_btc_1h"], 40)
        self.assertGreater(m["row_counts"]["candles_btc_10m"], 0)            # 10m = deterministic resample of 5m
        r = json.loads((folder / "candles_btc_10m.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(r["resampled_from"], "300s")
        self.assertTrue(r["open_utc"].endswith("Z"))
        self.assertEqual(m["provenance"]["execution"], "MANUAL_ONLY")

    def test_research_only_markets_and_fomo_resolution(self):
        hl = FakeHL()
        m, _ = self.check(self.run_export("market-candles", self.ctx(hl=hl), {"market": "FOMO_STOCK_PERPS", "instruments": "NVDA", "timeframes": "1h,10m"}))
        self.assertEqual((m["provenance"]["status"], m["provenance"]["execution"]), ("RESEARCH_ONLY", "DISABLED"))
        m, folder = self.check(self.run_export("fomo-universe", self.ctx(hl=hl)), {"fomo_101_resolution": 101})
        rows = [json.loads(x) for x in (folder / "fomo_101_resolution.jsonl").read_text(encoding="utf-8").splitlines()]
        st = {r["symbol"]: r["status"] for r in rows}
        self.assertEqual(st["NVDA"], "ACTIVE")
        self.assertEqual(sum(1 for v in st.values() if v == "NOT_FOUND"), 100 - (1 if "TSLA" in st else 0))
        self.assertTrue(all(r["metadata_version"] for r in rows if r["status"] == "ACTIVE"))
        self.assertTrue(m["provenance"]["metadata_versions"]["xyz"])

    def test_unknown_instrument_is_reported_not_filled(self):
        m, _ = self.check(self.run_export("market-candles", self.ctx(hl=FakeHL()), {"instruments": "NOPE", "timeframes": "1h"}))
        self.assertEqual((m["status"], m["total_rows"]), ("UNAVAILABLE", 0))
        self.assertTrue(any("UNKNOWN_INSTRUMENT" in n for n in m["notes"]))


class TestOrderflow(Base):
    def test_ledger_footprint_vp_dom_heatmap(self):
        from masterquo.orderflow.trades import TradeLedger
        hl = FakeHL(n_trades=40)
        led = TradeLedger()
        ctx = self.ctx(hl=hl, wf32={"ledger": led})
        man = self.run_export("orderflow", ctx, {"market": "CRYPTO", "instrument": "BTC"})
        m, folder = self.check(man, {"trades": 40, "dom_snapshot": 10})
        self.assertEqual(m["row_counts"]["trades"], len(led.events("HYPERLIQUID|core|BTC|0")))
        fp = sum(r["V"] for r in (json.loads(x) for x in (folder / "footprint.jsonl").read_text(encoding="utf-8").splitlines()))
        self.assertAlmostEqual(fp, led.total_volume("HYPERLIQUID|core|BTC|0"), places=9)      # footprint V sums to the ledger volume
        t = json.loads((folder / "trades.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(t["aggressor"], "UNKNOWN")                                          # Hyperliquid side not verified
        self.assertIsNone(json.loads((folder / "footprint.jsonl").read_text(encoding="utf-8").splitlines()[0])["delta"])
        man2 = self.run_export("orderflow", ctx, {"market": "CRYPTO", "instrument": "BTC"})   # same trades again: one ledger, no duplicates
        self.assertEqual(man2["row_counts"]["trades"], 40)

    def test_without_running_app_unavailable(self):
        m, _ = self.check(self.run_export("orderflow", self.ctx(hl=FakeHL()), {"instrument": "BTC"}))
        self.assertEqual((m["status"], m["total_rows"]), ("UNAVAILABLE", 0))


class FakeBridge:
    def __init__(self, n=1200, step=3600, with_utc=True):
        rnd = random.Random(3)
        px, self.rows = 2000.0, []
        t0 = 1_790_000_000
        for i in range(n):
            px *= math.exp(rnd.gauss(0, 0.002 if i < n // 2 else 0.006))
            self.rows.append({"t_raw": t0 + i * step + 7200, "open_utc": (datetime.fromtimestamp(t0 + i * step, timezone.utc).isoformat()
                              .replace("+00:00", "Z") if with_utc else None), "o": px, "h": px * 1.001, "l": px * 0.999, "c": px, "tv": 100, "closed": True})
        self.tfs = {"H1": None, "M5": None}

    def bars(self, tf, count, include_forming=True):
        return [dict(b) for b in self.rows[-count:]]


class TestShadowModels(Base):
    def rt(self, **kw):
        return types.SimpleNamespace(bridge=FakeBridge(**kw))

    def test_change_points_long_horizon_association(self):
        ctx = self.ctx(rt=self.rt())
        m, folder = self.check(self.run_export("change-points", ctx, {"timeframe": "H1", "lookback": "1000"}))
        self.assertEqual(m["provenance"]["status"], "OK")
        self.assertGreaterEqual(m["row_counts"]["change_points"], 1)
        self.assertEqual(m["row_counts"]["segments"], m["row_counts"]["change_points"] + 1)
        cp = json.loads((folder / "change_points.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self.assertTrue(cp["bar_open_utc"].endswith("Z"))
        self.assertEqual(m["files"][0]["time_columns"]["start_bar_open_server"], "BROKER_SERVER_TIME")
        m, folder = self.check(self.run_export("long-horizon", ctx, {"timeframe": "H1"}), {"forecasts": 4})
        f = [json.loads(x) for x in (folder / "forecasts.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([x["horizon"] for x in f], ["24h", "36h", "48h", "72h"])
        self.assertTrue(all(x["as_of_utc"] == "2026-09-12T19:00:00Z" or x["as_of_utc"].endswith("Z") for x in f))
        m, folder = self.check(self.run_export("association-rules", ctx, {"timeframe": "H1", "horizon": "12"}))
        self.assertEqual(m["row_counts"]["assessment"], 2)

    def test_unverified_server_offset_is_not_guessed(self):
        m, _ = self.check(self.run_export("long-horizon", self.ctx(rt=self.rt(with_utc=False)), {"timeframe": "H1"}))
        self.assertEqual((m["status"], m["total_rows"]), ("UNAVAILABLE", 0))
        self.assertTrue(any("TIME_OFFSET_UNVERIFIED" in n for n in m["notes"]))

    def test_without_app_unavailable(self):
        for name in ("change-points", "long-horizon", "association-rules", "pt-skill", "dt-ranker", "asge-trials", "sfb-snapshots"):
            m, _ = self.check(self.run_export(name))
            self.assertEqual((m["status"], m["total_rows"]), ("UNAVAILABLE", 0), name)

    def test_pt_and_dt_journal_rows(self):
        from masterquo.evaluation import pt_skill as PT
        from masterquo.ml import dt_ranker as DT
        j = collections.deque(maxlen=500)
        f = [1 if i % 3 else -1 for i in range(60)]
        y = [1 if i % 4 else -1 for i in range(60)]
        for _ in range(3):
            j.append({"kind": "pt", "at": time.time(), "n": 60, "inputs_sha256": "x", "profile": "ARTICLE_25105_V1", "result": PT.evaluate(f, y)})
        j.append({"kind": "dt", "at": time.time(), "n": 0, "inputs_sha256": "y", "result": DT.rank(None, [])})
        ctx = self.ctx(wf32={"shadow_journal": j})
        self.check(self.run_export("pt-skill", ctx), {"pt_results": 3})
        m, folder = self.check(self.run_export("dt-ranker", ctx), {"dt_rankings": 1})
        r = json.loads((folder / "dt_rankings.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(r["decision"], "NO_TRADE")

    def test_asge_trials_and_sfb_snapshots(self):
        from masterquo.apollo import asge as ASG
        from masterquo.baskets import catalog as CAT
        from masterquo.baskets.sfb import StrategyFilterBucket
        bars = [{"o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"]} for b in FakeBridge(n=900).rows]
        led = ASG.TrialLedger()
        ASG.run(bars, [{"side": "LONG", "conditions": [{"type": "close_above_sma", "n": 20}], "exit": {"tp_r": 2.0, "sl_atr": 1.5, "max_bars": 20}}],
                3, ledger=led)
        m, folder = self.check(self.run_export("asge-trials", self.ctx(wf32={"trials": led})), {"asge_trials": len(led.rows)})
        r = json.loads((folder / "asge_trials.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self.assertIs(r["execution_allowed"], False)
        self.assertTrue(r["created_at_utc"].endswith("Z"))
        sfb = StrategyFilterBucket({"mode": "SHADOW"})
        strats = [s for s in CAT.strategies() if s["profile_id"] == "FOREX_MT5"][:5]
        self.assertEqual(len(strats), 5)
        sfb.filter(strats, {"profile": "FOREX_MT5", "venue": "MT5", "environment": "PAPER", "product": None, "instrument": "XAUUSD"})
        sfb.filter(strats, {"profile": "FOREX_MT5", "venue": "MT5", "environment": "AUTO_DEMO", "product": None, "instrument": "XAUUSD"})
        rt = types.SimpleNamespace(baskets=types.SimpleNamespace(sfb=sfb))
        m, _ = self.check(self.run_export("sfb-snapshots", self.ctx(rt=rt)), {"sfb_snapshots": len(sfb.snapshots),
                                                                              "sfb_items": sum(len(s["items"]) for s in sfb.snapshots)})
        self.assertFalse(m["provenance"]["apply_to_execution"])


class TestStoreTables(Base):
    def test_rows_equal_source_modes_split_accounts_masked_excluded_tables(self):
        from masterquo.db.database import Database
        db = Database(self.data / "masterquo.sqlite")
        with db.tx() as c:
            for i, mode in enumerate(["PAPER", "PAPER", "AUTO_LIVE", "AUTO_DEMO", "SIGNALS"]):
                c.execute("INSERT INTO equity_snapshots(ts, mode, account_key, balance, equity, margin, free_margin, currency) VALUES(?,?,?,?,?,?,?,?)",
                          (f"2026-11-2{i}T10:00:00Z", mode, "Broker-Live:55554444", 1000.0 + i, 1000.0, 0.0, 1000.0, "USD"))
            c.execute("INSERT INTO accounts_seen(account_key, login, server, company, currency, trade_mode, margin_mode, first_seen, last_seen) "
                      "VALUES('Broker-Live:55554444', 55554444, 'Broker-Live', 'X', 'USD', 'REAL', 'HEDGING', '2026-11-01T00:00:00Z', '2026-11-02T00:00:00Z')")
            for i in range(2500):
                c.execute("INSERT INTO app_events(ts, level, category, code, message, data_json) VALUES(?,?,?,?,?,?)",
                          (f"2026-11-20T10:{i % 60:02d}:00Z", "INFO", "TEST", "T", f"m{i}", None))
        man = self.run_export("store-tables", params={"store": "main", "tables": "equity_snapshots,app_events"})
        m, folder = self.check(man, {"equity_snapshots__paper": 2, "equity_snapshots__auto_live": 1, "equity_snapshots__auto_demo": 1,
                                     "equity_snapshots__signals": 1, "app_events": 2500})
        kinds = {f["dataset"]: f["data_kind"] for f in m["files"]}
        self.assertEqual((kinds["equity_snapshots__paper"], kinds["equity_snapshots__auto_live"], kinds["equity_snapshots__auto_demo"]),
                         ("VIRTUAL", "REAL", "DEMO"))
        txt = all_text(folder)
        self.assertNotIn("55554444", txt)
        self.assertIn("Broker-Live:***444", txt)
        self.assertEqual(m["files"][0]["time_columns"].get("ts"), "UTC")
        self.assertEqual(m["date_range"]["from_utc"], "2026-11-20T10:00:00Z")
        from masterquo.exports.core import ExportError
        with self.assertRaises(ExportError):
            self.run_export("store-tables", params={"store": "main", "tables": "accounts_seen"})        # personal data never exported
        with self.assertRaises(ExportError):
            self.run_export("store-tables", params={"store": "main", "tables": "trades;DROP TABLE trades"})
        with self.assertRaises(ExportError):
            self.run_export("store-tables", params={"store": "../secrets"})
        full = self.run_export("store-tables", params={"store": "main"})
        self.assertNotIn("accounts_seen", full["row_counts"])
        self.assertEqual(full["row_counts"]["app_events"], 2500)

    def test_missing_store_is_empty_and_not_created(self):
        m, _ = self.check(self.run_export("store-tables", params={"store": "svp"}))
        self.assertEqual((m["status"], m["total_rows"]), ("EMPTY", 0))
        self.assertFalse((self.data / "svp" / "svp.sqlite").exists())


# ---------------------------------------------------------------------------------------------------- CLI + API
class TestCli(Base):
    def test_cli_out_folder_and_unavailable_exit_code(self):
        import subprocess
        import sys
        env = dict(os.environ, MASTERQUO_DATA_DIR=str(self.data), PYTHONPATH=str(_env.ROOT / "backend"), PMW_BOOTSTRAP="0")
        cfg = self.data / "config.json"
        cfg.write_text(json.dumps({"server": {"port": 8799}}), encoding="utf-8")      # nothing listens there -> "app not running"
        out = self.data / "out_cli"
        p = subprocess.run([sys.executable, "-m", "masterquo", "export-bootstrap", "--out", str(out), "--format", "jsonl"], env=env,
                           cwd=str(_env.ROOT / "backend"), capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr)
        made = [d for d in out.iterdir() if d.is_dir()]
        self.assertEqual(len(made), 1)
        man = json.loads((made[0] / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(man["formats"], ["jsonl"])
        p = subprocess.run([sys.executable, "-m", "masterquo", "export-asge-trials", "--out", str(out)], env=env, cwd=str(_env.ROOT / "backend"),
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 3, p.stdout + p.stderr)
        p = subprocess.run([sys.executable, "-m", "masterquo", "export-change-points", "--lookback", "abc"], env=env, cwd=str(_env.ROOT / "backend"),
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 2)


class TestExportApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PMW_BOOTSTRAP"] = "0"
        from _demo_server import Server
        cls.S = Server
        Server.start_server()

    @classmethod
    def tearDownClass(cls):
        cls.S.stop_server()

    def test_api_exports_write_only_into_data_folder(self):
        c = self.S.call
        code, idx = c("/api/v1/exports")
        self.assertEqual(code, 200)
        names = {e["name"] for e in idx["exporters"]}
        self.assertTrue({"orderflow", "market-candles", "fomo-universe", "strategy-roi", "sfb-snapshots", "asge-trials", "change-points", "long-horizon",
                         "association-rules", "pt-skill", "dt-ranker", "telegram-center", "trader-life-game", "bootstrap", "store-tables"} <= names)
        code, st = c("/api/v1/exports/store-tables?store=main&tables=app_events")
        self.assertEqual(code, 200, st)
        self.assertGreater(st["row_counts"]["app_events"], 0)
        self.assertEqual(c("/api/v1/exports/nope")[0], 404)
        self.assertEqual(c("/api/v1/exports/bootstrap?out=/tmp/x")[0], 400)          # no path parameter
        self.assertEqual(c("/api/v1/exports/change-points?lookback=-5")[0], 400)
        code, st = c("/api/v1/tlg/profile", {"username": "Eksport", "class_id": "THE_ROOKIE", "difficulty": "EASY"})
        self.assertIn(code, (200, 409))
        code, man = c("/api/v1/exports/trader-life-game")
        self.assertEqual(code, 200, man)
        self.assertEqual(Path(man["path"]).parent, Path(self.S.td.dir).resolve() / "exports")
        self.assertGreaterEqual(man["row_counts"]["profile"], 1)
        code, mm = c(f"/api/v1/exports/trader-life-game/{man['export_id']}/manifest")
        self.assertEqual((code, mm["verification"]["ok"]), (200, True))
        self.assertEqual(c("/api/v1/exports/trader-life-game/..%2F..%2Fetc/manifest")[0], 404)
        # PT / DT journal through the real routes
        f = [1 if i % 3 else -1 for i in range(40)]
        self.assertEqual(c("/api/v1/models/pt/evaluate", {"forecasts": f, "outcomes": f[::-1]})[0], 200)
        code, pt = c("/api/v1/exports/pt-skill")
        self.assertEqual((code, pt["row_counts"]["pt_results"]), (200, 1))
        code, ch = c("/api/v1/exports/change-points?timeframe=H1")
        self.assertEqual(code, 200, ch)
        # import: POST needs CSRF; id validated; profile kept (additive)
        self.assertEqual(c("/api/v1/exports/trader-life-game/import", {"export_id": man["export_id"]}, csrf=False)[0], 403)
        self.assertEqual(c("/api/v1/exports/trader-life-game/import", {"export_id": "../../x"})[0], 404)
        code, rep = c("/api/v1/exports/trader-life-game/import", {"export_id": man["export_id"]})
        self.assertEqual(code, 200, rep)
        self.assertEqual(rep["total_inserted"], 0)
        self.assertTrue(rep["profile"].startswith("KEPT_EXISTING"))


if __name__ == "__main__":
    unittest.main()
