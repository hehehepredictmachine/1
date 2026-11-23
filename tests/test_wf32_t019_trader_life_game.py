"""WF3.2 TASK 019 - TraderLifeGame backend: character / difficulty validation, separate money domains, idempotent XP / quests / gold,
server-graded academy, no-lookahead simulator, read-only MT5 view (no order path), local-only leaderboard."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import _env  # noqa: F401


class Clock:
    def __init__(self, t=1_763_700_000.0):
        self.t = t

    def __call__(self):
        return self.t


def bars(n=200, start=2000.0):
    out = []
    p = start
    for i in range(n):
        o = p
        p = p + (1.0 if (i // 10) % 2 == 0 else -0.8)
        out.append({"time": 1_700_000_000 + i * 3600, "open": o, "high": max(o, p) + 0.5, "low": min(o, p) - 0.5, "close": p})
    return out


DEALS = [
    {"ticket": 1, "order": 11, "time": 1_763_600_000, "type": 0, "entry": 0, "position_id": 100, "volume": 1.0, "price": 2000, "profit": 0,
     "commission": -3, "swap": 0, "fee": 0, "symbol": "XAUUSD"},
    {"ticket": 2, "order": 12, "time": 1_763_603_600, "type": 1, "entry": 1, "position_id": 100, "volume": 0.5, "price": 2010, "profit": 500,
     "commission": -1.5, "swap": 0, "fee": 0, "symbol": "XAUUSD"},
    {"ticket": 3, "order": 13, "time": 1_763_607_200, "type": 1, "entry": 1, "position_id": 100, "volume": 0.5, "price": 2005, "profit": 250,
     "commission": -1.5, "swap": -2, "fee": 0, "symbol": "XAUUSD"},
    {"ticket": 3, "order": 13, "time": 1_763_607_200, "type": 1, "entry": 1, "position_id": 100, "volume": 0.5, "price": 2005, "profit": 250,
     "commission": -1.5, "swap": -2, "fee": 0, "symbol": "XAUUSD"},                                  # duplicate delivery of the same deal
    {"ticket": 4, "order": 0, "time": 1_763_500_000, "type": 2, "entry": 0, "position_id": 0, "volume": 0, "price": 0, "profit": 10000,
     "commission": 0, "swap": 0, "fee": 0, "symbol": ""},                                            # balance deposit - not a trade
]


class Base(unittest.TestCase):
    def setUp(self):
        from masterquo.trader_life_game import GameService, ReadOnlyAccountView
        self.tmp = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.view = ReadOnlyAccountView(lambda: [dict(d) for d in DEALS], lambda: {"balance": 10750.0, "equity": 10760.0, "currency": "USD"},
                                        lambda s, tf, n: bars(min(n, 200)))
        self.g = GameService(Path(self.tmp.name), self.view, clock=self.clock)

    def tearDown(self):
        self.g.close()
        self.tmp.cleanup()

    def mk(self, cls="THE_ROOKIE", diff="EASY"):
        return self.g.create_profile({"username": "Kuba", "class_id": cls, "difficulty": diff, "currency": "usd", "virtual_capital": 10000})


class TestProfile(Base):
    def test_create_validate_and_single_local_profile(self):
        from masterquo.trader_life_game import GameError
        for bad in ({"username": "x", "class_id": "THE_ROOKIE", "difficulty": "EASY"}, {"username": "Kuba", "class_id": "WIZARD", "difficulty": "EASY"},
                    {"username": "Kuba", "class_id": "THE_ROOKIE", "difficulty": "GOD"},
                    {"username": "Kuba", "class_id": "THE_ROOKIE", "difficulty": "EASY", "virtual_capital": -5}):
            with self.assertRaises(GameError):
                self.g.create_profile(bad)
        st = self.mk()
        self.assertEqual((st["progress"]["level"], st["progress"]["rank"], st["profile"]["milestone"]), (1, "Beginner", 10000))
        with self.assertRaises(GameError) as cm:
            self.mk()
        self.assertEqual(cm.exception.code, "PROFILE_EXISTS")
        self.assertEqual(self.g.update_profile({"difficulty": "HARD"})["profile"]["milestone"], 100000)

    def test_money_domains_are_separate(self):
        st = self.mk()["balances"]
        self.assertEqual((st["real_balance"], st["real_source"], st["virtual_balance"], st["simulated_pnl"], st["trader_gold"], st["xp"]),
                         (10750.0, "MT5_REAL", 10000.0, 0.0, 0, 0))

    def test_level_formula_and_ranks(self):
        from masterquo.trader_life_game import service as S
        self.assertEqual(S.level_for_xp(0), 1)
        self.assertEqual(S.level_for_xp(S.xp_to_reach(11)), 11)
        self.assertEqual(S.level_for_xp(S.xp_to_reach(11) - 1), 10)
        self.assertEqual([S.rank_for(x) for x in (1, 10, 11, 55, 100)], ["Beginner", "Beginner", "Apprentice", "Senior Trader", "Trading Legend"])
        self.assertEqual(S.level_for_xp(10 ** 9), 100)


class TestJournalQuests(Base):
    def test_journal_groups_partial_exits_dedupes_and_ignores_balance(self):
        self.mk()
        j = self.g.journal()
        self.assertEqual(len(j["items"]), 1)
        p = j["items"][0]
        self.assertEqual((p["ref"], p["status"], p["side"], p["realized_pnl"], p["costs"], p["strategy_attribution"]),
                         ("MT5:100", "CLOSED", "BUY", 750.0, -8.0, "UNATTRIBUTED"))
        self.assertEqual(len(p["deals"]), 3)

    def test_annotation_rewards_are_idempotent_and_quest_claim_once(self):
        from masterquo.trader_life_game import GameError
        self.mk()
        with self.assertRaises(GameError):
            self.g.annotate("MT5:999", {"setup": "x"})                         # only existing canonical trades
        r = self.g.annotate("MT5:100", {"setup": "retest OB", "reason": "plan A", "emotion_before": "spokój", "lesson": "czekać na close",
                                        "rule_compliance": True, "review_score": 8, "mistakes": ["wejście przed zamknięciem świecy"]})
        kinds = [x for x in r["rewards"] if x["recorded"]]
        self.assertEqual(len(kinds), 4)                                           # journal + review + compliant + mistake
        r2 = self.g.annotate("MT5:100", {"lesson": "czekać na close świecy"})
        self.assertTrue(all(not x["recorded"] for x in r2["rewards"]))           # no second reward for the same trade
        xp = self.g.xp_total()
        q = {x["id"]: x for x in self.g.quests()}
        self.assertEqual(q["D_JOURNAL"]["status"], "COMPLETED")
        self.assertEqual(q["D_CHART"]["status"], "AVAILABLE")
        out = self.g.claim("D_JOURNAL")
        self.assertEqual((out["xp"], out["trader_gold"]), (30, 10))
        self.assertEqual(self.g.xp_total(), xp + 30)
        with self.assertRaises(GameError) as cm:
            self.g.claim("D_JOURNAL")
        self.assertEqual(cm.exception.code, "ALREADY_CLAIMED")
        with self.assertRaises(GameError) as cm:
            self.g.claim("D_CHART")
        self.assertEqual(cm.exception.code, "QUEST_NOT_COMPLETED")
        self.clock.t += 86400                                                     # next day: the daily quest resets, journal ref cannot farm again
        self.assertEqual({x["id"]: x for x in self.g.quests()}["D_JOURNAL"]["status"], "AVAILABLE")

    def test_notes_daily_cap_and_validation(self):
        from masterquo.trader_life_game import GameError
        self.mk()
        with self.assertRaises(GameError):
            self.g.add_note("ANALYSIS", {"text": "za krótko"})
        with self.assertRaises(GameError):
            self.g.add_note("ANALYSIS", {"text": "x" * 50})                       # no invalidation level
        xs = [self.g.add_note("ANALYSIS", {"text": "Analiza H1 XAUUSD: sweep dołka azjatyckiego i reclaim.", "invalidation": "2390"})["reward"]["xp"]
              for _ in range(7)]
        self.assertEqual(xs[:5], [20] * 5)
        self.assertEqual(xs[5:], [0, 0])                                          # DAILY_CAP stops farming
        w1 = self.g.add_note("WEEKLY", {"text": "Przegląd tygodnia: 3 transakcje, 2 zgodne z planem, jedna za wcześnie."})
        w2 = self.g.add_note("WEEKLY", {"text": "Przegląd tygodnia ponownie, ta sama treść tylko dłuższa niż czterdzieści znaków."})
        self.assertTrue(w1["reward"]["recorded"])
        self.assertFalse(w2["reward"]["recorded"])                                # one weekly review per ISO week


class TestAcademySkills(Base):
    def test_quiz_graded_on_server_requires_lessons_and_never_leaks_answers(self):
        from masterquo.trader_life_game import GameError
        from masterquo.trader_life_game import content as C
        self.mk(cls="THE_QUANT")
        ac = self.g.academy()
        self.assertNotIn(2, [len(q) for L in ac["levels"] for q in L["quiz"] if "answer" in q])
        for L in ac["levels"]:
            for q in L["quiz"]:
                self.assertEqual(set(q), {"q", "options"})
        with self.assertRaises(GameError) as cm:
            self.g.submit_quiz(1, [1, 0, 1])
        self.assertEqual(cm.exception.code, "LESSONS_NOT_COMPLETED")
        for ls in C.ACADEMY[1]["lessons"]:
            self.g.complete_lesson(ls["id"])
        bad = self.g.submit_quiz(1, [0, 1, 0])
        self.assertFalse(bad["passed"])
        good = self.g.submit_quiz(1, [1, 0, 1])
        self.assertTrue(good["passed"])
        self.assertEqual(good["rewards"][0]["xp"], 69)                           # 60 x 1.15 (THE QUANT bonus for QUIZ_PASSED)
        self.assertFalse(self.g.submit_quiz(1, [1, 0, 1])["rewards"][0]["recorded"])

    def test_risk_exercise_and_skill_tree(self):
        from masterquo.trader_life_game import GameError
        self.mk()
        ex = self.g.risk_exercise()
        want = ex["account"] * ex["risk_pct"] / 100 / ex["sl_distance"]
        self.assertFalse(self.g.submit_risk_exercise(ex["exercise_id"], want * 2)["correct"])
        self.assertTrue(self.g.submit_risk_exercise(ex["exercise_id"], want)["correct"])
        sk = self.g.skills()
        self.assertEqual(sk["level"], 2)                                          # 50 XP from the risk exercise
        self.assertEqual(sk["points_available"], 2)                               # level // 2 + 1
        self.g.unlock_skill("RISK_1")
        with self.assertRaises(GameError):
            self.g.unlock_skill("RISK_2")                                         # level 5 required
        self.g.unlock_skill("TA_1")
        with self.assertRaises(GameError):
            self.g.unlock_skill("QUANT_1")                                        # no points left


class TestSimulator(Base):
    def test_no_lookahead_virtual_ledger_and_sl_first(self):
        self.mk()
        v = self.g.sim_start("XAUUSD", "H1", 200)
        self.assertEqual(len(v["bars"]), 60)
        full = bars(200)
        self.assertEqual(v["bars"][-1]["c"], full[59]["close"])
        self.assertNotIn(full[60]["close"], [b["c"] for b in v["bars"]] if full[60]["close"] not in [x["close"] for x in full[:60]] else [])
        v = self.g.sim_open(v["id"], "BUY", 2, sl=v["bars"][-1]["c"] - 3, tp=v["bars"][-1]["c"] + 3)
        entry = v["trades"][0]["entry"]
        self.assertEqual(entry, full[59]["close"])                                # filled on the last REVEALED close
        v = self.g.sim_step(v["id"], 40)
        self.assertEqual(len(v["bars"]), 100)
        t = v["trades"][0]
        self.assertIn(t["reason"], ("SL", "TP"))
        out = self.g.sim_finish(v["id"])
        self.assertTrue(out["reward"]["recorded"])
        st = self.g.state()["balances"]
        self.assertEqual(st["simulated_pnl"], round(t["pnl"], 2))
        self.assertEqual(st["virtual_balance"], round(10000 + t["pnl"], 2))
        self.assertEqual(st["real_balance"], 10750.0)                             # real balance untouched by the simulator

    def test_sl_checked_before_tp_in_same_bar(self):
        from masterquo.trader_life_game.service import GameService
        t = {"side": "BUY", "sl": 99.0, "tp": 101.0}
        self.assertEqual(GameService._sltp(t, {"h": 102, "l": 98}), (99.0, "SL"))


class TestSafety(Base):
    def test_read_only_view_blocks_everything_else(self):
        for name in ("order_send", "positions_modify", "set_mode", "stop", "_deals"):
            if name == "_deals":
                continue
            with self.assertRaises(PermissionError):
                getattr(self.view, name)
        with self.assertRaises(PermissionError):
            self.view.order_send = lambda *a: None

    def test_service_has_no_trading_references(self):
        import ast
        import inspect
        from masterquo.trader_life_game import service as S
        src = inspect.getsource(S)
        mods = set()
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, ast.Import):
                mods |= {a.name for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                mods.add(("." * n.level) + (n.module or ""))
        self.assertEqual(mods, {"__future__", "hashlib", "json", "math", "sqlite3", "threading", "time", "datetime", "pathlib", "."})
        code = "\n".join(l for l in src.splitlines() if not l.strip().startswith(("#", '"')) and "order_send / position modify" not in l)
        for word in ("order_send(", "TRADE_ACTION", "positions_get", "set_mode(", "risk_book", "kill_switch"):
            self.assertNotIn(word, code, word)
        self.assertEqual(set(vars(self.g)) & {"bridge", "rt", "execution", "risk"}, set())

    def test_bridge_wrapper_only_reads(self):
        from masterquo.trader_life_game import ReadOnlyAccountView
        import threading

        class Bridge:
            _lock = threading.Lock()
            deals = [{"ticket": 1}]

            def account_status(self):
                return {"balance": 1}

            def symbol_bars(self, s, tf, n):
                return [{"time": 1, "open": 1, "high": 1, "low": 1, "close": 1}]

            def order_send(self, *a):
                raise AssertionError("order_send called")
        v = ReadOnlyAccountView.from_bridge(Bridge())
        self.assertEqual(v.deals(), [{"ticket": 1}])
        with self.assertRaises(PermissionError):
            v.order_send

    def test_lifestyle_gold_and_leaderboard_local_only(self):
        from masterquo.trader_life_game import GameError
        self.mk()
        life = self.g.lifestyle()
        self.assertEqual({i["id"] for i in life["items"] if i["owned"]}, {"DESK_BASIC", "OFFICE_HOME", "APT_STUDIO"})
        with self.assertRaises(GameError):
            self.g.buy("ROOM_PREMIUM")
        lb = self.g.leaderboard()
        self.assertFalse(lb["global"]["enabled"])
        self.assertEqual(len(lb["local"]), 1)
        self.assertNotIn("pnl", " ".join(lb["local"][0]))

    def test_coach_rules_only_and_memory_rejects_secrets(self):
        from masterquo.trader_life_game import GameError
        self.mk()
        c = self.g.coach()
        self.assertEqual((c["mode"], c["ai"]), ("RULES_ONLY", "AI_UNAVAILABLE"))
        self.assertTrue(any("bez wpisu" in o["text"] for o in c["observations"]))
        with self.assertRaises(GameError):
            self.g.coach_memory_add("moje hasło do MT5 to abc")
        self.g.coach_memory_add("Wolę handlować tylko sesję londyńską.")
        self.assertEqual(len(self.g.coach()["memory"]), 1)
        self.g.coach_memory_delete()
        self.assertEqual(self.g.coach()["memory"], [])

    def test_calendar_marks_trading_and_rest(self):
        self.mk()
        cal = self.g.calendar("2025-11")
        self.assertIn("BROKER_SERVER_TIME", cal["time_basis"]["real_trades"])
        trading = [d for d in cal["days"] if d["type"] == "TRADING"]
        self.assertEqual(len(trading), 1)
        self.assertEqual(trading[0]["real_net_pnl"], 742.0)


if __name__ == "__main__":
    unittest.main()
