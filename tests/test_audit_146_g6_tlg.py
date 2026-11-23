"""1.46 audit, group G6 (TraderLifeGame service): missing MT5 deal history shown as "MT5_REAL, 0 trades", the forming bar leaking into
the simulator, MAIN quests counting quizzes of the wrong levels and the simulator drawdown computed in opening (not closing) order.

TraderLifeGame stays EXECUTION_ISOLATED: every test talks to the service through ReadOnlyAccountView only (fake bridges expose read
functions; no order path exists). All market data / deals here are SYNTHETIC."""
from __future__ import annotations

import tempfile
import threading
import unittest
from datetime import UTC, datetime
from pathlib import Path

import _env  # noqa: F401
from masterquo.trader_life_game import GameError, GameService, ReadOnlyAccountView
from masterquo.trader_life_game import content as C

T0 = 1_763_700_000.0          # 2025-11-21 UTC
DEALS = [
    {"ticket": 1, "order": 11, "time": 1_763_600_000, "type": 0, "entry": 0, "position_id": 100, "volume": 1.0, "price": 2000, "profit": 0,
     "commission": -3, "swap": 0, "fee": 0, "symbol": "XAUUSD"},
    {"ticket": 2, "order": 12, "time": 1_763_603_600, "type": 1, "entry": 1, "position_id": 100, "volume": 1.0, "price": 2010, "profit": 1000,
     "commission": -3, "swap": 0, "fee": 0, "symbol": "XAUUSD"},
]


def fixture_bars(n=200, start=2000.0):
    out, p = [], start
    for i in range(n):
        o = p
        p = p + (1.0 if (i // 10) % 2 == 0 else -0.8)
        out.append({"time": 1_700_000_000 + i * 3600, "open": o, "high": max(o, p) + 0.5, "low": min(o, p) - 0.5, "close": p})
    return out


def bridge_bars(n=100, forming_close=1.05):
    """MarketBridge.symbol_bars format: o/h/l/c + 'closed'; the newest bar is still forming (closed=False), no 'forming' key."""
    out = []
    for i in range(n):
        c = 1.0 + (i % 7) * 0.001
        out.append({"open_utc": None, "t_raw": 1_700_000_000 + i * 3600, "o": c, "h": c + 0.002, "l": c - 0.002, "c": c, "tv": 1, "rv": 0,
                    "spread": 1, "closed": True})
    out[-1].update({"c": forming_close, "h": forming_close + 0.001, "closed": False})
    return out


class FakeBridge:
    """Only the read attributes ReadOnlyAccountView.from_bridge uses; deals_loaded_at mirrors MarketBridge (None until _poll_deals)."""

    def __init__(self, deals=None, loaded_at=None, bars=None):
        self._lock = threading.Lock()
        self.deals = list(deals or [])
        self.deals_loaded_at = loaded_at
        self._bars = bars

    def account_status(self):
        return {"balance": 1000.0, "equity": 1000.0, "currency": "USD"}

    def symbol_bars(self, symbol, tf, count):
        return [dict(b) for b in (self._bars or [])][-count:]

    def order_send(self, *a):          # pragma: no cover - must never be reachable
        raise AssertionError("order_send called")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.services = []

    def tearDown(self):
        for g in self.services:
            g.close()
        self.tmp.cleanup()

    def game(self, view=None, diff="EASY", sub="g"):
        g = GameService(Path(self.tmp.name) / sub, view, clock=lambda: T0)
        self.services.append(g)
        g.create_profile({"username": "Kuba", "class_id": "THE_ROOKIE", "difficulty": diff, "currency": "usd", "virtual_capital": 10000})
        return g


class DealsNotLoadedAreUnavailable(Base):
    """focus_X2#4 / chunk_35#35: bridge.deals == [] until the first successful history read (deals_loaded_at None), and without a
    bridge the view returned [] - journal() declared that 'MT5_REAL' with 0 trades (calendar REST days, coach silent, annotate 404)."""

    def test_history_not_loaded_is_unavailable_not_zero_trades(self):
        br = FakeBridge(deals=[], loaded_at=None)
        view = ReadOnlyAccountView.from_bridge(br)
        self.assertIsNone(view.deals())
        g = self.game(view)
        jr = g.journal()
        self.assertEqual(jr["source"], "UNAVAILABLE")
        self.assertIsNone(jr["items"])
        g.complete_lesson("L1_MARKET")                                        # a LEARNING day
        g._ledger("xp_ledger", "test:xp-only", 5, "TEST")                     # a day with no game activity, trades unknown
        cal = g.calendar("2025-11")
        self.assertEqual(cal["real_source"], "UNAVAILABLE")
        self.assertTrue(cal["days"])
        for d in cal["days"]:
            self.assertIsNone(d["real_trades"])
            self.assertIsNone(d["real_net_pnl"])
            self.assertNotEqual(d["type"], "REST")                            # REST = "no trades" - not known here
        with self.assertRaises(GameError) as cm:
            g.annotate("MT5:100", {"setup": "x"})
        self.assertEqual((cm.exception.code, cm.exception.status), ("DEALS_UNAVAILABLE", 409))
        coach = g.coach()
        self.assertTrue(any("UNAVAILABLE" in o["text"] for o in coach["observations"]))
        # history read later (the same bridge object) -> real data, annotate works
        br.deals, br.deals_loaded_at = [dict(d) for d in DEALS], datetime.now(UTC)
        jr = g.journal()
        self.assertEqual((jr["source"], len(jr["items"])), ("MT5_REAL", 1))
        self.assertEqual(g.annotate("MT5:100", {"setup": "breakout"})["ref"], "MT5:100")
        trading = [d for d in g.calendar("2025-11")["days"] if d["type"] == "TRADING"]
        self.assertEqual((len(trading), trading[0]["real_trades"]), (1, 1))

    def test_no_bridge_is_unavailable(self):
        self.assertIsNone(ReadOnlyAccountView.from_bridge(None).deals())
        self.assertIsNone(ReadOnlyAccountView().deals())
        g = self.game(None)
        self.assertEqual((g.journal()["source"], g.journal()["items"]), ("UNAVAILABLE", None))

    def test_loaded_empty_history_is_a_real_zero(self):
        g = self.game(ReadOnlyAccountView.from_bridge(FakeBridge(deals=[], loaded_at=datetime.now(UTC))))
        self.assertEqual((g.journal()["source"], g.journal()["items"]), ("MT5_REAL", []))
        with self.assertRaises(GameError) as cm:
            g.annotate("MT5:100", {"setup": "x"})
        self.assertEqual((cm.exception.code, cm.exception.status), ("UNKNOWN_TRADE_REF", 404))


class SimulatorDropsFormingBar(Base):
    """focus_X2#9 / chunk_35#32: sim_start filtered on a 'forming' key the bridge never sets (it marks the newest bar closed=False),
    so the still-forming bar (close = live price) was revealed as the last 'closed' bar."""

    def test_forming_bar_from_the_bridge_never_enters_the_session(self):
        g = self.game(ReadOnlyAccountView.from_bridge(FakeBridge(loaded_at=None, bars=bridge_bars(100, forming_close=1.05))))
        v = g.sim_start("EURUSD", "H1", 100)
        v = g.sim_step(v["id"], 50)
        self.assertEqual(len(v["bars"]), 99)
        self.assertNotIn(1.05, [b["c"] for b in v["bars"]])
        out = g.sim_finish(v["id"])
        self.assertEqual(out["provenance"]["bars"], 99)

    def test_bars_without_closed_flag_are_kept(self):
        g = self.game(ReadOnlyAccountView(None, None, lambda s, tf, n: fixture_bars(min(n, 200))))
        v = g.sim_start("XAUUSD", "H1", 200)
        self.assertEqual(g.sim_step(v["id"], 50)["cursor"], 110)
        self.assertEqual(g.sim_view(v["id"])["provenance"]["bars"], 200)


class MainQuestsCountTheirOwnLevels(Base):
    """chunk_35#33: M_EASY (levels 1-2), M_MEDIUM (levels 1-3) counted ANY passed quiz - passing levels 3 and 4 completed M_EASY."""

    def _pass(self, g, level):
        for ls in C.ACADEMY[level]["lessons"]:
            g.complete_lesson(ls["id"])
        self.assertTrue(g.submit_quiz(level, [ok for _, _, ok in C.ACADEMY[level]["quiz"]])["passed"])

    def test_main_quests_require_the_named_levels(self):
        g = self.game(None, diff="HARD")
        self._pass(g, 3)
        self._pass(g, 4)
        q = {x["id"]: x for x in g.quests()}
        self.assertEqual((q["M_EASY"]["progress"], q["M_EASY"]["status"]), (0, "AVAILABLE"))
        self.assertEqual(q["M_MEDIUM"]["progress"], 1)
        self.assertEqual(q["M_HARD"]["progress"], 2)
        with self.assertRaises(GameError):
            g.claim("M_EASY")
        self._pass(g, 1)
        self._pass(g, 2)
        q = {x["id"]: x for x in g.quests()}
        self.assertEqual([q[k]["status"] for k in ("M_EASY", "M_MEDIUM", "M_HARD")], ["COMPLETED"] * 3)
        self.assertEqual(q["M_HARD"]["progress"], 4)


class SimAnalyticsInClosingOrder(Base):
    """chunk_35#34: the equity curve / max drawdown was accumulated in insertion (= opening) order, not in the order PnL was realised."""

    def test_drawdown_follows_closed_idx(self):
        g = self.game(ReadOnlyAccountView(None, None, lambda s, tf, n: fixture_bars(min(n, 200))))
        sid = g.sim_start("XAUUSD", "H1", 200)["id"]
        for pnl, closed_idx in ((100.0, 70), (-50.0, 65), (-60.0, 75)):     # opened in this order, closed 2nd, 1st, 3rd
            g.db.execute("INSERT INTO sim_trades(session_id, side, size, entry, sl, tp, opened_idx, closed_idx, exit, pnl, reason) "
                         "VALUES(?, 'BUY', 1, 2000, NULL, NULL, 60, ?, 2000, ?, 'MANUAL')", (sid, closed_idx, pnl))
        an = g.sim_finish(sid)["analytics"]
        # realised: -50 (dd 50) -> +100 (eq 50, peak 50) -> -60 (eq -10, dd 60); opening order would give 110
        self.assertEqual(an["max_drawdown"], 60.0)
        self.assertEqual(an["net"], -10.0)


if __name__ == "__main__":
    unittest.main()


class SpecialPsychoQuestDescription(unittest.TestCase):
    """chunk_35#33 (description part): S_PSYCHO counts all 8 level-2 lessons (skills + psychology), its text said 'psychology lessons'."""

    def test_description_matches_the_counted_lessons(self):
        from masterquo.trader_life_game import content as C
        q = next(q for q in C.QUESTS if q[0] == "S_PSYCHO")
        self.assertEqual(q[5], 8)
        self.assertIn("poziomu 2", q[3])
        self.assertIn("umiejętności", q[3])


class SharedConnectionIsSerialized(unittest.TestCase):
    """focus_X3#3: one SQLite connection shared by the API threads; reads ran without the lock -> InterfaceError / missing profile rows when
    the panel loads /tlg/state, /tlg/quests and /tlg/skills at the same time."""

    def test_parallel_panel_reads_are_complete(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        g = GameService(Path(tmp.name), ReadOnlyAccountView(deals=lambda: []))
        self.addCleanup(g.close)
        g.create_profile({"username": "Kuba", "class_id": "THE_ROOKIE", "difficulty": "EASY", "currency": "usd", "virtual_capital": 10000})
        errors, missing = [], []

        def worker():
            for _ in range(150):
                try:
                    if g._profile(required=False) is None:
                        missing.append(1)
                    g.quests()
                    g.skills()
                except Exception as exc:  # noqa: BLE001 - collected and asserted below
                    errors.append(f"{type(exc).__name__}: {exc}")
        ts = [threading.Thread(target=worker) for _ in range(6)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(120)
        self.assertEqual(errors[:3], [])
        self.assertEqual(missing, [])
