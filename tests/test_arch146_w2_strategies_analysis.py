"""1.46 arch, fala 2 - grupa strategies_analysis (strategie S01-S12, selektor, tracker, analiza S/R i walls).

Każda klasa odpowiada pozycji triażu (klucz w docstringu); test nie przechodził na kodzie sprzed poprawki.
"""
from __future__ import annotations

import importlib
import unittest

import _env


class TestPackagesRegular(unittest.TestCase):
    """I0090: strategies/ i lab/ były niejawnymi pakietami przestrzeni nazw (brak __init__.py, __file__ None) - jako jedyne z podpakietów
    backend/masterquo; narzędzia wykrywania pakietów i pakowanie mogły je pomijać."""

    def test_strategies_and_lab_are_regular_packages(self):
        for name in ("masterquo.strategies", "masterquo.lab"):
            mod = importlib.import_module(name)
            self.assertIsNotNone(getattr(mod, "__file__", None), name)
            self.assertTrue(str(mod.__file__).endswith("__init__.py"), name)

    def test_every_backend_directory_with_modules_has_init(self):
        pkg = _env.ROOT / "backend" / "masterquo"
        missing = sorted(str(d.relative_to(pkg)) for d in [pkg, *[p for p in pkg.rglob("*") if p.is_dir()]]
                         if "__pycache__" not in d.parts and any(d.glob("*.py")) and not (d / "__init__.py").exists())
        self.assertEqual(missing, [])


class TestStrategyParamsIsolation(unittest.TestCase):
    """I0098: STRATEGIES to singletony współdzielone przez skan live, backfill ML i API; params_for robił płytką kopię (lista 'tfs'
    wspólna z atrybutem klasy), a describe() oddawał żywy słownik params - mutacja u konsumenta zmieniała parametry skanu live."""

    def test_describe_returns_copies(self):
        from masterquo.strategies import registry
        before = list(registry.STRATEGIES["S01"].params["tfs"])
        d = next(x for x in registry.describe() if x["strategy_id"] == "S01")
        d["params"]["tfs"].append("X")
        d["params"]["new_key"] = 1
        d["regime_fit"]["TREND_UP"] = -1.0
        self.assertEqual(registry.STRATEGIES["S01"].params["tfs"], before)
        self.assertNotIn("new_key", registry.STRATEGIES["S01"].params)
        self.assertNotEqual(registry.STRATEGIES["S01"].regime_fit.get("TREND_UP"), -1.0)

    def test_params_for_is_a_deep_copy(self):
        from masterquo.strategies import registry
        before = list(registry.STRATEGIES["S01"].params["tfs"])
        p = registry.params_for("S01", None)
        p["tfs"].append("X")
        self.assertEqual(registry.STRATEGIES["S01"].params["tfs"], before)
        override = {"tfs": ["M15"]}
        q = registry.params_for("S01", override)
        q["tfs"].append("H1")
        self.assertEqual(override["tfs"], ["M15"])                    # the user's config value is not mutated either
        self.assertEqual(registry.params_for("S01", {"tfs": ["M5"]})["tfs"], ["M5"])   # overrides still apply

    def test_strategies_keep_no_instance_state_outside_thread_local(self):
        from masterquo.strategies import registry
        for sid, s in registry.STRATEGIES.items():
            self.assertLessEqual(set(vars(s)), {"_tls"}, sid)


def iso_(dt) -> str:
    from masterquo.timeutil import iso
    return iso(dt)


class _TrackerCase(unittest.TestCase):
    """Tracker on a temporary DB with the S01-S10 synthetic scenarios of test_strategies."""

    def setUp(self):
        import test_strategies as TS
        self.TS = TS
        self.t = TS.TestTracker("test_dedupe_invalidation_expiry_restore")
        self.t.setUp()
        self.tr, self.cfg = self.t.tr, self.t.cfg

    def tearDown(self):
        self.t.tearDown()

    def upd(self, cands, view, now, sid, new_data=True):
        return self.tr.update(cands, view=view, symbol="XAUUSD-", account_key="acc", data_ok=True, new_data=new_data, now=now, cfg=self.cfg,
                              scanned={sid})


class TestTrackerEnteredNotResurrected(_TrackerCase):
    """I0751 (łata 649be2f cofnięta w 00f269b): skan (wątek silnika) zapisywał wiersze przeczytane na swoim początku; ENTERED ustawione w tym
    czasie przez wykonanie (POST /api/v1/execute, wątek API) wracało na ACTIVE - setup mógł zostać wybrany i wykonany drugi raz."""

    def test_stale_copy_cannot_overwrite_entered_or_final(self):
        sid = "S01"
        bars = self.TS.scenario(sid)
        v, cands = self.t._scan(bars, sid)
        now = self.t._now(bars)
        self.upd(cands, v, now, sid)
        row = self.tr.active("XAUUSD-", "acc")[0]                                  # the scan's copy (status ACTIVE)
        self.tr.mark_entered(row["setup_id"], "AUTO_DEMO_FILLED", "2026-11-20T10:00:00Z")   # execution thread
        row["updated_at"] = "2026-11-20T10:00:01Z"
        self.tr._save(row)                                                          # the scan finishes and writes its stale copy
        self.assertEqual(self.tr.get(row["setup_id"])["status"], "ENTERED")
        self.assertEqual(self.tr.active("XAUUSD-", "acc"), [])
        for st in ("INVALIDATED", "EXPIRED", "MISSED_ENTRY"):
            with self.subTest(final=st):
                self.tr.db.execute("UPDATE strategy_setups SET status=? WHERE setup_id=?", (st, row["setup_id"]))
                self.tr._save(dict(row, status="ACTIVE"))
                self.assertEqual(self.tr.get(row["setup_id"])["status"], st)

    def test_cancelled_soft_stop_is_still_reactivated(self):
        sid = "S01"
        bars = self.TS.scenario(sid)
        v, cands = self.t._scan(bars, sid)
        now = self.t._now(bars)
        self.upd(cands, v, now, sid)
        sids = {r["setup_id"] for r in self.tr.active("XAUUSD-", "acc")}
        self.tr.cancel_all("XAUUSD-", "acc", "RESTART_REVALIDATION", iso_(now))
        ev = self.upd(cands, v, now, sid)
        self.assertTrue(any(k.startswith("NEW_") for k, _ in ev))
        self.assertEqual({r["setup_id"] for r in self.tr.active("XAUUSD-", "acc")}, sids)


class TestTrackerReactivationTtl(_TrackerCase):
    """I0750: reaktywacja setupu CANCELLED (CONDITIONS_NO_LONGER_MET / RESTART_REVALIDATION) liczyła nowe okno z expires_bars od teraz - bez
    gałęzi CONFIRMED i bez starego expires_at: restart lub powrót warunków dawał pełny nowy TTL, także po upływie starego okna."""

    def _created(self, stage=None):
        from masterquo.timeutil import parse_iso
        sid = "S01"
        bars = self.TS.scenario(sid)
        v, cands = self.t._scan(bars, sid)
        c = dict(cands[0], stage=stage) if stage else cands[0]
        now = self.t._now(bars)
        self.upd([c], v, now, sid)
        row = self.tr.get(c["setup_id"])
        self.tr.cancel_all("XAUUSD-", "acc", "RESTART_REVALIDATION", iso_(now))
        return sid, v, c, now, parse_iso(row["expires_at"])

    def test_no_reactivation_after_the_old_window(self):
        from datetime import timedelta
        for stage, final in (("CONFIRMED", "MISSED_ENTRY"), ("EARLY", "EXPIRED")):
            with self.subTest(stage=stage):
                self.tr.db.execute("DELETE FROM strategy_setups")
                sid, v, c, now, old_exp = self._created(stage)
                ev = self.upd([c], v, old_exp + timedelta(seconds=1), sid)
                self.assertFalse([k for k, _ in ev if k.startswith("NEW_")])
                self.assertEqual(self.tr.active("XAUUSD-", "acc"), [])
                r = self.tr.get(c["setup_id"])
                self.assertEqual((r["status"], r["terminal_reason"]), (final, "TTL_ELAPSED_BEFORE_REACTIVATION"))

    def test_reactivated_window_is_never_longer(self):
        from datetime import timedelta

        from masterquo.strategies.base import TF_SECONDS
        from masterquo.timeutil import parse_iso
        for stage, again in (("CONFIRMED", "CONFIRMED"), ("EARLY", "EARLY"), ("EARLY", "CONFIRMED")):
            with self.subTest(stage=stage, again=again):
                self.tr.db.execute("DELETE FROM strategy_setups")
                sid, v, c, now, old_exp = self._created(stage)
                t2 = now + timedelta(minutes=10)
                ev = self.upd([dict(c, stage=again)], v, t2, sid)
                self.assertIn("NEW_" + again, [k for k, _ in ev])
                r = self.tr.get(c["setup_id"])
                self.assertEqual(r["status"], "ACTIVE")
                exp = parse_iso(r["expires_at"])
                self.assertLessEqual(exp, old_exp)
                if again == "CONFIRMED":
                    self.assertLessEqual(exp, t2 + timedelta(seconds=TF_SECONDS[c["timeframe"]] * self.cfg.confirmed_window_bars))


if __name__ == "__main__":
    unittest.main()
