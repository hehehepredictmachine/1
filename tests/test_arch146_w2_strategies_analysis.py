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
                sid, v, c, _now, old_exp = self._created(stage)
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


class TestTrackerInvalidationBeforeRevision(_TrackerCase):
    """I0752: rekord z nowym poziomem inwalidacji był zapisywany PRZED twardą kontrolą, która czytała wiersze już po aktualizacji - zamknięcie
    poza opublikowanym (starym) poziomem nie unieważniało setupu, jeśli ten sam skan przesunął poziom dalej."""

    def _setup(self):
        sid = "S01"
        bars = self.TS.scenario(sid)
        v, cands = self.t._scan(bars, sid)
        c = cands[0]
        now = self.t._now(bars)
        self.upd([c], v, now, sid)
        return sid, bars, c, now

    def _bar_closing_at(self, bars, close):
        from datetime import timedelta

        from masterquo.timeutil import parse_iso
        last = bars[-1]
        nb = self.TS.F.bars_from_closes([last["c"], close], tf_min=15, wick=0.2, start=parse_iso(last["open_utc"]))[1]
        nb["open_utc"] = last["close_confirmed_utc"]
        nb["close_confirmed_utc"] = nb["available_at"] = iso_(parse_iso(last["close_confirmed_utc"]) + timedelta(minutes=15))
        return bars + [nb]

    def test_close_beyond_the_published_level_invalidates_despite_a_moved_level(self):
        from datetime import timedelta
        sid, bars, c, now = self._setup()
        lvl = c["invalidation_level"]
        bars2 = self._bar_closing_at(bars, lvl - 0.5)                 # closed beyond the level in force
        c2 = dict(c, invalidation_level=lvl - 1.0, stop_loss=lvl - 1.0)  # the next scan moves the level below that close
        ev = self.upd([c2], self.TS.view_for(bars2), now + timedelta(minutes=20), sid)
        r = self.tr.get(c["setup_id"])
        self.assertEqual((r["status"], r["terminal_reason"]), ("INVALIDATED", f"CLOSE_BEYOND_{round(lvl, 3)}"))
        self.assertIn(("INVALIDATED", c["setup_id"]), [(k, x["setup_id"]) for k, x in ev])
        self.assertNotIn("PLAN_REVISED", [k for k, _ in ev])
        self.assertEqual(r["record"]["invalidation_level"], lvl)                  # the published plan is kept as it was

    def test_touch_rule_against_the_published_level(self):
        from datetime import timedelta

        from masterquo.strategies import adapter
        sid = "S01"
        bars = self.TS.scenario(sid)
        v, cands = self.t._scan(bars, sid)
        c = dict(cands[0], invalidation_rule="TOUCH")
        now = self.t._now(bars)
        self.upd([c], v, now, sid)
        lvl = c["invalidation_level"]
        tfs = {tf: bars for tf in ("M1", "M5", "M15", "H1")}
        v2 = adapter.build_view(symbol="XAUUSD-", bars_by_tf=tfs, bid=lvl - 0.3, ask=lvl - 0.2, point=0.01, as_of=bars[-1]["close_confirmed_utc"],
                                synthetic=True)
        self.upd([dict(c, invalidation_level=lvl - 1.0)], v2, now + timedelta(seconds=30), sid)
        r = self.tr.get(c["setup_id"])
        self.assertEqual((r["status"], r["terminal_reason"]), ("INVALIDATED", f"TOUCH_{round(lvl, 3)}"))

    def test_unchanged_level_keeps_todays_path(self):
        from datetime import timedelta
        sid, bars, c, now = self._setup()
        lvl = c["invalidation_level"]
        bars2 = self._bar_closing_at(bars, lvl + 0.5)                 # no violation: the new plan is applied as before
        c2 = dict(c, invalidation_level=lvl - 1.0, stop_loss=lvl - 1.0)
        ev = self.upd([c2], self.TS.view_for(bars2), now + timedelta(minutes=20), sid)
        self.assertNotIn("INVALIDATED", [k for k, _ in ev])
        r = self.tr.get(c["setup_id"])
        self.assertEqual((r["status"], r["record"]["invalidation_level"]), ("ACTIVE", lvl - 1.0))


class _SelectorCase(unittest.TestCase):
    def setUp(self):
        import test_strategies as TS
        self.s = TS.TestSelector("test_small_difference_never_switches")
        self.s.setUp()
        self.row, self.pick, self.sel, self.db = self.s.row, self.s.pick, self.s.sel, self.s.db

    def tearDown(self):
        self.s.tearDown()

    def log(self):
        return [(r["previous_strategy"], r["selected_strategy"], r["reason"])
                for r in self.db.query("SELECT previous_strategy, selected_strategy, reason FROM strategy_selection_log ORDER BY id")]


class TestSelectorConflictSuspendsSelection(_SelectorCase):
    """I0749: konflikt LONG/SHORT w horyzoncie zerował tylko `best`; istniejący wybór zostawał (żadna gałąź go nie zdejmowała) i bot mógł
    wykonać setup w stanie CONFLICT. Teraz wybór w horyzoncie konfliktu jest ZAWIESZANY (niewykonywalny), a po ustąpieniu konfliktu wraca
    ten sam (stan histerezy bez zmian) - wykonywalny wybór to zawsze dzisiejszy albo żaden."""

    def test_conflict_suspends_and_restores_the_same_selection(self):
        a = self.row("S01", "CONFIRMED", 60, 100, "LONG")
        self.assertEqual(self.pick([a], 0)[0], "S01")
        t0 = self.sel.selected["at"]
        s, st = self.pick([a, self.row("S07", "CONFIRMED", 62, 90, "SHORT")], 10)          # opposite setup, rank difference < margin
        self.assertIsNone(s)
        self.assertIsNone(self.sel.selected)                                               # engine: selected_row() -> None, no execution
        self.assertTrue(any(r.startswith("CONFLICT_") for r in st["reason_codes"]))
        self.assertIn("SELECTION_SUSPENDED_CONFLICT", st["reason_codes"])
        self.assertEqual((st["suspended"] or {}).get("strategy_id"), "S01")
        self.assertTrue(self.log()[-1][2].startswith("SELECTION_SUSPENDED_CONFLICT_"))
        s, st = self.pick([a], 20)                                                          # conflict gone -> the same selection is back
        self.assertEqual(s, "S01")
        self.assertEqual(self.sel.selected["at"], t0)                                       # hold time / hysteresis state unchanged
        self.assertIsNone(st["suspended"])
        self.assertEqual(self.log()[-1], (None, "S01", "CONFLICT_RESOLVED_SELECTION_RESTORED"))

    def test_conflict_in_the_horizon_of_a_held_selection_that_is_not_the_best(self):
        a = self.row("S01", "CONFIRMED", 60, 100, "LONG")
        self.assertEqual(self.pick([a], 0)[0], "S01")
        x = self.row("S03", "CONFIRMED", 66, 100, "LONG", horizon="SWING")                  # leads by < min_switch_margin, other horizon
        y = self.row("S07", "CONFIRMED", 58, 100, "SHORT")                                  # opposite, same horizon as S01, close rank
        s, st = self.pick([a, x, y], 10)
        self.assertIsNone(s)
        self.assertTrue(any(r.startswith("CONFLICT_LONG_SHORT_INTRADAY") for r in st["reason_codes"]))

    def test_suspended_selection_that_disappears_is_dropped_as_today(self):
        a = self.row("S01", "CONFIRMED", 60, 100, "LONG")
        b = self.row("S02", "CONFIRMED", 61, 100, "LONG", setup="MQA-B")
        self.assertEqual(self.pick([a], 0)[0], "S01")
        self.assertIsNone(self.pick([a, self.row("S07", "CONFIRMED", 62, 90, "SHORT")], 10)[0])
        self.assertEqual(self.pick([b], 20)[0], "S02")                                     # S01 gone -> best at once (today's rule)
        self.assertEqual(self.log()[-1][2], "PREVIOUS_SETUP_NO_LONGER_VALID")

    def test_no_conflict_no_change(self):
        rows = [self.row("S01", "EARLY", 60, 100), self.row("S07", "EARLY", 40, 90, "SHORT")]   # opposite but far below
        self.assertEqual(self.pick(rows, 0)[0], "S01")
        self.assertEqual(self.pick(rows, 10)[0], "S01")
        self.assertEqual([x[2] for x in self.log()], ["FIRST_SELECTION"])


class TestWallsStoreRestart(unittest.TestCase):
    """I0868 (łata 783a153): odcisk zawierał krotkę; po rundzie przez JSON (pierwsze freeze po restarcie) był listą -> nigdy równy -> każdy
    restart tworzył wersję N+1 z nowym snapshot_id dla tych samych danych (a S12 nową tożsamość setupu dla tego samego zdarzenia)."""

    def test_same_input_after_restart_keeps_snapshot_id(self):
        from _env import TempData
        from masterquo.analysis.walls import WallsStore
        from masterquo.db.database import Database
        td = TempData()
        try:
            db = Database()
            snap = {"status": "OK", "symbol": "XAUUSD-", "anchor_time": "2026-11-20T00:00:00Z", "source_type": "HV_PROXY", "sigma_annual": 0.18,
                    "obs_id": None, "band_sigma": 0.15, "available_at": "2026-11-20T00:05:00Z",
                    "walls": [{"k": 1.0, "side": "UPPER", "level": 2410.0}, {"k": 2.0, "side": "UPPER", "level": 2430.0},
                              {"k": 1.0, "side": "LOWER", "level": 2390.0}]}
            a = WallsStore(db).freeze(dict(snap, walls=[dict(w) for w in snap["walls"]]))
            b = WallsStore(db).freeze(dict(snap, walls=[dict(w) for w in snap["walls"]]))     # new store = application restart
            self.assertEqual((b["snapshot_id"], b["snapshot_version"]), (a["snapshot_id"], 1))
            self.assertEqual(db.one("SELECT COUNT(*) n FROM walls_snapshots")["n"], 1)
            st = WallsStore(db)
            c = st.freeze(dict(snap, sigma_annual=0.25, walls=[dict(w) for w in snap["walls"]]))   # a real change -> next version
            self.assertEqual(c["snapshot_version"], 2)
            self.assertEqual(st.freeze(dict(snap, sigma_annual=0.25, walls=[dict(w) for w in snap["walls"]]))["snapshot_id"], c["snapshot_id"])
        finally:
            td.close()


class TestS12HigherLowNotTautology(unittest.TestCase):
    """I0828: warunek 'wyższy dołek' reakcji S12 RANGE_RECLAIM (min po pierwszym minimum > minimum) był tautologią - bramka NO_REACTION prawie
    nigdy nie blokowała. Ścisła reguła działa PO arbitrze wariantów (arbiter i jego reguła konfliktu LONG/SHORT widzą te same fazy co
    dotąd - ścisła reakcja liczona wcześniej mogłaby przepuścić inny wariant albo stronę przeciwną: nowe wejście)."""

    @staticmethod
    def _m1(lows):
        from datetime import timedelta

        import test_s12_family as SF
        from masterquo.strategies.base import TFView
        bars = [{"open_utc": SF.iso(SF.T0 + timedelta(minutes=k)), "o": lo + 0.3, "h": lo + 0.6, "l": lo, "c": lo + 0.3, "tv": 100, "closed": True}
                for k, lo in enumerate(lows)]                  # doji-like bars: no candle reaction evidence
        return TFView("M1", bars)

    def test_monotonic_rise_after_the_low_is_not_a_higher_low(self):
        from masterquo.strategies.registry import STRATEGIES
        s = STRATEGIES["S12"]
        rising = self._m1([2000.0, 1999.5, 1999.0, 1998.0, 1998.2, 1998.4, 1998.6, 1998.8])    # minimum at 3, then only higher lows
        r = s._reaction(rising, 1, 7, 1997.0, [0.5] * 8)
        self.assertFalse(r["sweep"])
        self.assertFalse(r["higher_low"])
        trough = self._m1([2000.0, 1999.5, 1999.0, 1998.0, 1998.6, 1998.3, 1998.7, 1998.9])    # a local low at 5 above the episode low
        self.assertTrue(s._reaction(trough, 1, 7, 1997.0, [0.5] * 8)["higher_low"])

    def _detect_with(self, longs, shorts):
        import test_s12_family as SF
        s, p = SF.s12()
        v = SF.make_view(SF.build_reclaim(), SF.walls_snap([("LOWER", 1.0, 1998.0), ("UPPER", 1.0, 2010.0)]))
        calls = iter([(longs, {}), (shorts, {})])
        s._side = lambda view, p: next(calls)            # instance attribute: only this call of the shared singleton
        try:
            return {(d.direction, d.facts.get("variant")): d for d in s.detect(v, p)}
        finally:
            del s._side

    @staticmethod
    def _cand(variant, phase, direction="LONG", **extra):
        from masterquo.strategies.base import Draft
        d = Draft(strategy_id="S12", direction="LONG", timeframe="M1", phase=phase, structure_key=f"{variant}:k", event_key="e", anchor_time=None,
                  entry_plan=None, invalidation_level=None, expires_bars=3 if phase == "TRIGGER" else 20,
                  components={"structure": 0.8, "formation": 1.0, "trigger": 1.0 if phase == "TRIGGER" else 0.0}, facts={"variant": variant})
        return {"variant": variant, "draft": d, **extra}

    def test_strict_reaction_downgrades_the_published_draft_after_the_arbiter(self):
        out = self._detect_with([self._cand("RANGE_RECLAIM", "TRIGGER", reaction_ok=False, trigger_closed=True),
                                 self._cand("BREAKOUT_RETEST", "TRIGGER")], [])
        self.assertNotIn(("LONG", "BREAKOUT_RETEST"), out)                  # the arbiter's choice is unchanged (no other variant let through)
        d = out[("LONG", "RANGE_RECLAIM")]
        self.assertEqual(d.phase, "EARLY")
        self.assertIn("NO_REACTION", d.missing)
        self.assertEqual((d.components["trigger"], d.components["formation"], d.expires_bars), (0.0, 0.4, 3))       # TTL never longer than the draft had

    def test_the_opposite_side_stays_in_conflict(self):
        out = self._detect_with([self._cand("RANGE_RECLAIM", "EARLY", reaction_ok=False, trigger_closed=False)],
                                [self._cand("BREAKOUT_RETEST", "TRIGGER")])
        self.assertEqual({d.phase for d in out.values()}, {"WATCH"})          # the SHORT trigger is NOT released by the stricter LONG


class TestSRClusterBounded(unittest.TestCase):
    """I0757: klasteryzacja pivotów S/R była łańcuchowa (single-linkage: p - ostatni <= tol) - łańcuch równo rozłożonych pivotów sklejał się
    w strefę wielokrotnie szerszą od tolerancji. multi_tf (wykres, narzędzie agenta) używa teraz klastra ograniczonego (p - pierwszy <= tol,
    MQ-SR-1.1.0); zones_for_tf domyślnie zostaje przy regule MQ-SR-1.0.0 - z niej liczona jest mapa stref (zones/engine), a z niej cechy
    wytrenowanych modeli (ML legacy zone_*, Quant analysis:zones): stare artefakty dostają dokładnie dzisiejsze wejścia."""

    @staticmethod
    def _view():
        from datetime import UTC, datetime, timedelta

        from masterquo.strategies.base import MarketView, TFView
        t0 = datetime(2026, 10, 1, tzinfo=UTC)
        closes = []
        for cyc in range(12):                                   # zig-zag whose lows / highs rise by 0.4 per swing (< tolerance ~0.67)
            lo = 2000.0 + 0.4 * cyc
            closes += [lo + 2.5 * k for k in range(4)] + [lo + 10 - 2.5 * k for k in range(4)]
        bars, prev = [], closes[0]
        for i, c in enumerate(closes):
            bars.append({"open_utc": iso_(t0 + timedelta(hours=i)), "o": prev, "h": max(prev, c) + 0.1, "l": min(prev, c) - 0.1, "c": c, "closed": True})
            prev = c
        return MarketView(symbol="X", as_of="", tfs={"H1": TFView("H1", bars)}, bid=None, ask=None, point=0.01)

    def test_multi_tf_zones_are_not_wider_than_the_tolerance(self):
        from masterquo.analysis import levels as L
        r = L.multi_tf(self._view(), tfs=("H1",))
        h1 = r["by_tf"]["H1"]
        self.assertEqual(h1["status"], "OK")
        self.assertGreaterEqual(len(h1["zones"]), 4)
        for z in h1["zones"]:
            self.assertLessEqual(z["high"] - z["low"], h1["tolerance"] + 1e-6, z)
            self.assertEqual(z["version"], "MQ-SR-1.1.0")
        self.assertEqual(r["version"], "MQ-SR-1.1.0")

    def test_zone_map_rule_is_unchanged(self):
        from masterquo.analysis import levels as L
        v = self._view()
        r = L.zones_for_tf(v.tfs["H1"], "H1", point=0.01)                  # default = the rule of the zone map / trained zone features
        self.assertEqual({z["version"] for z in r["zones"]}, {"MQ-SR-1.0.0"})
        self.assertEqual(sorted(round(z["high"] - z["low"], 2) for z in r["zones"]), [4.0, 4.0])

    def test_cluster_rules(self):
        from masterquo.analysis import levels as L
        piv = [{"price": 100.0 + 0.8 * k} for k in range(10)]
        self.assertEqual([len(c) for c in L.cluster_pivots(piv, 1.0, "CHAIN")], [10])
        bounded = L.cluster_pivots(piv, 1.0, "BOUNDED")
        self.assertEqual(len(bounded), 5)
        self.assertTrue(all(c[-1]["price"] - c[0]["price"] <= 1.0 for c in bounded))


if __name__ == "__main__":
    unittest.main()
