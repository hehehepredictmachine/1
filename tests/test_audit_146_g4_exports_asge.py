"""1.46 audit regressions - group G4 (exports / ASGE):
* TraderLifeGame backup imported into a game that already has its own data (id collisions must not drop rows of the backup and simulator trades
  must stay attached to their own session);
* ASGE Trial Ledger: execution_allowed is a constant False also for rows read from the file and in the export;
* ASGE backtest: an open gapping through the SL is a loss of the gap, not -1R;
* ASGE multiple-testing hurdle counts every distinct trial on the same data (not only the current call) and the frozen holdout is not re-used;
* ASGE data_hash covers the whole bar (o / h / l / c and time), not only the close."""
from __future__ import annotations

import itertools
import json
import math
import random
import sqlite3
import types
import unittest
from pathlib import Path
from unittest import mock

import _env  # noqa: F401
from _env import TempData


def _mt5_bars(n=200, start=2000.0, seed=1):
    rnd = random.Random(seed)
    p, out = start, []
    for i in range(n):
        o = p
        p = p * (1 + rnd.gauss(0, 0.002))
        out.append({"time": 1_780_000_000 + 3600 * i, "o": o, "h": max(o, p) + 0.5, "l": min(o, p) - 0.5, "c": p})
    return out


class _Clock:
    def __init__(self, t0: float):
        self.t = t0

    def __call__(self) -> float:
        self.t += 1.25
        return self.t


# ---------------------------------------------------------------------------------------------------- focus_X2#1
class TestTlgImportIntoExistingGame(unittest.TestCase):
    NOTE = "Plan sesji nr {}: czekam na sweep dołka azjatyckiego i reclaim powyżej poziomu."

    def setUp(self):
        self.src_td = TempData()
        self.src = Path(self.src_td.dir)
        self.dst_td = TempData()
        self.dst = Path(self.dst_td.dir)

    def tearDown(self):
        self.dst_td.close()
        self.src_td.close()

    @staticmethod
    def game(d: Path, t0: float, seed: int):
        from masterquo.trader_life_game import GameService
        from masterquo.trader_life_game.service import ReadOnlyAccountView
        view = ReadOnlyAccountView(bars=lambda s, tf, count: _mt5_bars(200, seed=seed))
        return GameService(d / "trader_life_game", account=view, clock=_Clock(t0))

    @staticmethod
    def export(d: Path) -> Path:
        from masterquo.exports import registry as R
        from masterquo.exports.sources import SourceContext
        return Path(R.run("trader-life-game", SourceContext(d))["path"])

    @staticmethod
    def q(d: Path, sql: str) -> list[tuple]:
        c = sqlite3.connect(str(d / "trader_life_game" / "game.sqlite"))
        try:
            return c.execute(sql).fetchall()
        finally:
            c.close()

    def make_backup(self) -> Path:
        """Game A: simulator session 1 (XAUUSD H1) with one trade, three PLAN notes, two coach memories."""
        a = self.game(self.src, 1_790_000_000.0, seed=1)
        a.create_profile({"username": "Kopia", "class_id": "THE_ANALYST", "difficulty": "MEDIUM"})
        sid = a.sim_start("XAUUSD", "H1")["id"]
        a.sim_step(sid, 3)
        a.sim_open(sid, "BUY", 0.5)
        for k in range(3):
            a.add_note("PLAN", {"text": self.NOTE.format(f"A{k}"), "max_risk": "0.5%"})
        a.coach_memory_add("A: pamiętaj o dzienniku")
        a.coach_memory_add("A: nie handluj po newsach")
        a.close()
        return self.export(self.src)

    def make_target(self):
        """Game B (already in use): its own session 1 (EURUSD M5) without trades, one ANALYSIS note, one coach memory."""
        b = self.game(self.dst, 1_791_000_000.0, seed=2)
        b.create_profile({"username": "Inny", "class_id": "THE_ROOKIE", "difficulty": "EASY"})
        b.sim_start("EURUSD", "M5")
        b.add_note("ANALYSIS", {"text": self.NOTE.format("B0"), "invalidation": "1.0500"})
        b.coach_memory_add("B: tylko sesja londyńska")
        b.close()

    def test_import_into_non_empty_game_keeps_every_backup_row_and_session_links(self):
        from masterquo.exports.tlg_import import import_backup
        folder = self.make_backup()
        src_notes = set(self.q(self.src, "SELECT kind, ts, data FROM notes"))
        src_memory = set(self.q(self.src, "SELECT ts, text FROM coach_memory"))
        src_trade = self.q(self.src, "SELECT side, size, entry, opened_idx FROM sim_trades")
        src_keys = {t: {r[0] for r in self.q(self.src, f"SELECT key FROM {t}")} for t in ("events", "xp_ledger", "gold_ledger")}
        self.make_target()
        own_notes = set(self.q(self.dst, "SELECT kind, ts, data FROM notes"))

        rep = import_backup(folder, self.dst)

        notes = set(self.q(self.dst, "SELECT kind, ts, data FROM notes"))
        self.assertEqual(notes, src_notes | own_notes)                           # 3 notes of the backup + 1 own (HEAD: only the own one + 2)
        self.assertEqual(len(notes), 4)
        self.assertEqual(set(self.q(self.dst, "SELECT ts, text FROM coach_memory")) >= src_memory, True)
        sessions = {r[1]: r[0] for r in self.q(self.dst, "SELECT id, symbol FROM sim_sessions")}
        self.assertEqual(set(sessions), {"XAUUSD", "EURUSD"})                     # the backup session is not dropped
        trades = self.q(self.dst, "SELECT session_id, side, size, entry, opened_idx FROM sim_trades")
        self.assertEqual(trades, [(sessions["XAUUSD"], *src_trade[0])])          # the trade belongs to ITS session, never to the local session 1
        self.assertEqual(self.q(self.dst, f"SELECT COUNT(*) FROM sim_trades WHERE session_id = {sessions['EURUSD']}"), [(0,)])
        for t, keys in src_keys.items():                                          # every ledger row of the backup is there (by idempotency key)
            have = {r[0] for r in self.q(self.dst, f"SELECT key FROM {t}")}
            self.assertTrue(keys <= have, (t, keys - have))
        self.assertEqual(rep["rejected"].get("sim_trades"), 0)

        # idempotent: the same backup again changes nothing
        before = {t: self.q(self.dst, f"SELECT COUNT(*) FROM {t}")[0][0] for t in ("notes", "coach_memory", "sim_sessions", "sim_trades", "events",
                                                                                     "xp_ledger")}
        rep2 = import_backup(folder, self.dst)
        self.assertEqual(rep2["total_inserted"], 0, rep2["inserted"])
        after = {t: self.q(self.dst, f"SELECT COUNT(*) FROM {t}")[0][0] for t in before}
        self.assertEqual(after, before)

    def test_reimport_after_playing_on_and_exact_restore_into_empty_game(self):
        from masterquo.exports.tlg_import import import_backup
        folder = self.make_backup()
        rep = import_backup(folder, self.dst)                                     # fresh installation: ids are kept (exact restore)
        self.assertEqual(self.q(self.dst, "SELECT id, symbol FROM sim_sessions"), self.q(self.src, "SELECT id, symbol FROM sim_sessions"))
        self.assertEqual(self.q(self.dst, "SELECT id, session_id FROM sim_trades"), self.q(self.src, "SELECT id, session_id FROM sim_trades"))
        self.assertEqual(self.q(self.dst, "SELECT id, kind, ts FROM notes"), self.q(self.src, "SELECT id, kind, ts FROM notes"))
        self.assertGreater(rep["total_inserted"], 0)
        # the user plays on in the restored game (session moves, the trade is closed), then imports the same backup again
        g = self.game(self.dst, 1_792_000_000.0, seed=1)
        sid = self.q(self.dst, "SELECT id FROM sim_sessions")[0][0]
        tid = self.q(self.dst, "SELECT id FROM sim_trades")[0][0]
        g.sim_step(sid, 2)
        g.sim_close(sid, tid)
        g.close()
        rep2 = import_backup(folder, self.dst)
        self.assertEqual(rep2["total_inserted"], 0, rep2["inserted"])             # an older snapshot of the same rows is not a new row
        self.assertEqual(self.q(self.dst, "SELECT COUNT(*) FROM sim_sessions"), [(1,)])
        self.assertEqual(self.q(self.dst, "SELECT COUNT(*) FROM sim_trades"), [(1,)])


# ---------------------------------------------------------------------------------------------------- focus_X2#5
class TestAsgeExecutionAllowedConstant(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.data = Path(self.td.dir)

    def tearDown(self):
        self.td.close()

    def test_rows_from_file_and_add_never_carry_true(self):
        from masterquo.apollo import asge as A
        p = self.data / "apollo" / "asge_trials.jsonl"
        p.parent.mkdir(parents=True)
        lines = [{"trial_id": "T00001", "status": "SHADOW_CHALLENGER", "execution_allowed": True},      # tampered / foreign file
                 {"trial_id": "T00002", "status": "REJECTED", "execution_allowed": False},
                 {"trial_id": "T00003", "status": "REJECTED"}]
        raw = "".join(json.dumps(x) + "\n" for x in lines)
        p.write_text(raw, encoding="utf-8")
        led = A.TrialLedger(p)
        self.assertEqual([r["execution_allowed"] for r in led.rows], [False, False, False])
        self.assertEqual(led.rows[0].get("integrity"), A.TAMPERED_FLAG)            # visible, not silently "repaired"
        self.assertIsNone(led.rows[1].get("integrity"))
        self.assertEqual(p.read_text(encoding="utf-8"), raw)                       # append-only file is never rewritten
        row = led.add({"status": "REJECTED", "execution_allowed": True})
        self.assertIs(row["execution_allowed"], False)
        self.assertIs(A.TrialLedger(p).rows[-1]["execution_allowed"], False)

    def test_export_publishes_the_constant(self):
        from masterquo.exports import sources as S
        fake = types.SimpleNamespace(rows=[{"trial_id": "T00001", "created_at": 1_790_000_000.0, "execution_allowed": True}], path=None)
        col = S.asge_trials(S.SourceContext(self.data, wf32={"trials": fake}))
        rows = col.datasets[0].rows
        self.assertIs(rows[0]["execution_allowed"], False)
        p = self.data / "apollo" / "asge_trials.jsonl"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({"trial_id": "T00001", "created_at": 1_790_000_000.0, "execution_allowed": True}) + "\n", encoding="utf-8")
        col = S.asge_trials(S.SourceContext(self.data))                         # CLI path: the durable file
        self.assertIs(col.datasets[0].rows[0]["execution_allowed"], False)


# ---------------------------------------------------------------------------------------------------- chunk_05#5
GAP_IR = {"side": "LONG", "conditions": [{"type": "close_above_sma", "n": 5}], "exit": {"tp_r": 2.0, "sl_atr": 1.0, "max_bars": 10}}


class TestAsgeGapThroughStop(unittest.TestCase):
    @staticmethod
    def bars(gap_open: float) -> list[dict]:
        out = [{"o": 100.0, "h": 100.5, "l": 99.5, "c": 100.0} for _ in range(15)]
        out.append({"o": 100.0, "h": 101.5, "l": 100.0, "c": 101.0})                # bar 15: close above SMA5 -> signal
        out.append({"o": 101.0, "h": 101.2, "l": 100.8, "c": 101.0})                # bar 16: entry at the open, inside SL / TP
        out.append({"o": gap_open, "h": gap_open + 0.5, "l": gap_open - 0.5, "c": gap_open})     # bar 17 opens beyond the SL
        out += [{"o": gap_open, "h": gap_open + 0.5, "l": gap_open - 0.5, "c": gap_open} for _ in range(3)]
        return out

    def test_gap_loss_is_the_gap_not_one_r(self):
        from masterquo.apollo import asge as A
        bars = self.bars(80.0)
        atr = sum(max(b["h"] - b["l"], abs(b["h"] - p["c"]), abs(b["l"] - p["c"])) for p, b in itertools.pairwise(bars[1:16])) / 14
        risk = 1.0 * atr
        r = A.backtest(GAP_IR, bars, cost_r=0.0)
        self.assertEqual(len(r), 1)
        self.assertAlmostEqual(r[0], (80.0 - 101.0) / risk, places=9)            # HEAD: -1.0
        self.assertLess(r[0], -10)

    def test_stop_touched_without_gap_stays_minus_one_r(self):
        from masterquo.apollo import asge as A
        bars = self.bars(100.4)                                                    # opens above the SL, the low trades through it
        bars[17] = {"o": 100.4, "h": 100.6, "l": 99.0, "c": 99.2}
        bars[18:] = [{"o": 98.0, "h": 98.2, "l": 97.8, "c": 98.0} for _ in bars[18:]]     # below the SMA: no second signal
        self.assertEqual(A.backtest(GAP_IR, bars, cost_r=0.0), [-1.0])


# ---------------------------------------------------------------------------------------------------- chunk_05#6
def _walk(n=1200, seed=4, drift=0.0004, vol=0.01, start=100.0):
    rnd = random.Random(seed)
    p, out = start, []
    for i in range(n):
        o = p
        p *= math.exp(rnd.gauss(drift, vol))
        out.append({"t": i * 3600, "o": o, "h": max(o, p) * (1 + abs(rnd.gauss(0, vol / 3))), "l": min(o, p) * (1 - abs(rnd.gauss(0, vol / 3))), "c": p})
    return out


SEED = {"side": "LONG", "family": "TREND", "conditions": [{"type": "close_above_sma", "n": 50}, {"type": "breakout_high", "n": 20}],
        "exit": {"tp_r": 2.0, "sl_atr": 1.5, "max_bars": 30}}
SEED2 = {"side": "SHORT", "conditions": [{"type": "rsi_above", "n": 14, "level": 70}], "exit": {"tp_r": 1.5, "sl_atr": 2.0, "max_bars": 20}}


class TestAsgeCumulativeTrials(unittest.TestCase):
    def test_hurdle_counts_earlier_trials_on_the_same_data(self):
        from masterquo.apollo import asge as A
        bars = _walk()
        led = A.TrialLedger()
        r1 = A.run(bars, [SEED], n_children=6, ledger=led)
        self.assertAlmostEqual(r1["hurdle_net_r"], 0.05 * math.log(7))        # first call: never looser than the per-call count
        r2 = A.run(bars, [SEED2], n_children=0, seed=11, ledger=led)       # another call, other seed, the same data / holdout
        self.assertEqual(r2["trials"], 1)                                          # this call
        distinct = len({r["ir_hash"] for r in led.rows})
        self.assertEqual(r2["trials_cumulative"], distinct)
        self.assertAlmostEqual(r2["hurdle_net_r"], 0.05 * math.log(distinct))    # HEAD: 0.05 * log(2) - the hurdle started from scratch
        self.assertGreater(distinct, 2)
        self.assertGreater(r2["hurdle_net_r"], 0.05 * math.log(2))             # the second call does not start from the lowest hurdle
        r3 = A.run(bars, [SEED], n_children=6, ledger=led)                  # the identical request is not a new hypothesis
        self.assertEqual(r3["trials_cumulative"], distinct)
        other = A.run(_walk(seed=5), [SEED2], n_children=0, ledger=led)     # other data: its own count
        self.assertEqual(other["trials_cumulative"], 1)

    def test_holdout_evaluated_once_per_candidate_and_data(self):
        from masterquo.apollo import asge as A
        bars = _walk()
        cut = int(len(bars) * 0.75)
        calls = []

        def fake_backtest(ir, part, cost_r=0.05):                                  # every candidate passes dev and holdout
            calls.append(part[0] is bars[cut])
            return [0.5] * 30

        led = A.TrialLedger()
        with mock.patch.object(A, "backtest", fake_backtest):
            r1 = A.run(bars, [SEED], n_children=0, ledger=led)
            n_hold = sum(calls)
            r2 = A.run(bars, [SEED], n_children=0, ledger=led)
        self.assertEqual(n_hold, 1)
        self.assertEqual(sum(calls), 1)                                            # HEAD: 2 - the holdout was consulted again
        self.assertEqual(len(r1["challengers"]), 1)
        self.assertEqual(len(r2["challengers"]), 1)                                # the recorded result is returned
        self.assertEqual(r2["challengers"][0]["holdout_reused_from"], r1["challengers"][0]["trial_id"])
        self.assertEqual(r2["holdout_evaluations"], 1)
        self.assertEqual(len(led.rows), 2)                                         # still every call is recorded (append-only)


# ---------------------------------------------------------------------------------------------------- chunk_05#9
class TestAsgeDataHash(unittest.TestCase):
    def test_hash_covers_high_low_open_and_time(self):
        from masterquo.apollo import asge as A
        seed = {"side": "LONG", "conditions": [{"type": "close_above_sma", "n": 20}], "exit": {"tp_r": 2.0, "sl_atr": 1.5, "max_bars": 20}}
        bars = _walk(800)
        hashes = set()
        for variant in (bars, [{**b, "h": b["h"] * 1.01} for b in bars], [{**b, "l": b["l"] * 0.99} for b in bars],
                        [{**b, "o": b["c"]} for b in bars], [{**b, "t": b["t"] + 60} for b in bars]):
            led = A.TrialLedger()
            A.run(variant, [seed], n_children=0, ledger=led)
            hashes.add(led.rows[0]["data_hash"])
        self.assertEqual(len(hashes), 5)                                           # HEAD: 1 (closes only)
        led1, led2 = A.TrialLedger(), A.TrialLedger()
        A.run(bars, [seed], n_children=0, ledger=led1)
        A.run([dict(b) for b in bars], [seed], n_children=0, ledger=led2)
        self.assertEqual(led1.rows[0]["data_hash"], led2.rows[0]["data_hash"])     # deterministic


if __name__ == "__main__":
    unittest.main()
