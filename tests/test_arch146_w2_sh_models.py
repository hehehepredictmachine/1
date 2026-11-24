"""1.46 arch, fala 2 – grupa sh_models: rejestr modeli SH (sh/models.py), katalog, sondy MM, panel treningu, pakiet SH (engine / policies),
kontekst i replay SH. Każdy test nie przechodzi na kodzie sprzed poprawki (klucze pozycji w nazwach klas).

* I0271 / I0303 / I0624 / I0352 / I0356: sonda nie raportuje SHADOW_ONLY, gdy nic nie jest w obserwacji ani nie liczy predykcji.
* I0318 / I0569 / I0586 / I0591 / I0593: udział w macierzy SH odpowiada temu, co sh/setup.py naprawdę czyta (bramka / wejście / informacja).
* I0005: oś use (OBSERVE / ASSIST / REQUIRED, ml.mode) jest widoczna w macierzy i katalogu – tylko prezentacja.
* I0014: pole runner_step to klucz training.runner.STEPS albo None (właściciel treningu poza runnerem).
* I0563 / I0660: opisy rejestru zgodne z kodem.
* I0055: legacy replay SH dostaje progi wieku danych z konfiguracji SH (jak live).
* I0861: notowanie bez znacznika czasu = BLOCK (nie świeże).
* I0743 / I0819 / I0820 / I0821 / I0822: pakiet SH – wyłącznie zaostrzenia (mniej wejść / aktywacji hedge niż dziś).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _env  # noqa: F401
from _env import TempData

INST = "XAUUSD"


def _item(mid: str) -> dict:
    from masterquo.sh import models as SM
    return next(i for i in SM.REGISTRY if i["id"] == mid)


def _write(p: Path, obj: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


class _Data(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)
        self.base = Path(self.td.dir)


# ================================================================================================ sondy SH (sh/models.probe)
class TestI0271ProbeNoSelection(_Data):
    """Rejestr ma runy, ale wskaźnik wyboru jest pusty -> nic nie jest w obserwacji: NOT_CONNECTED, udział NONE (było SHADOW_ONLY / INFO)."""

    def test_runs_without_selection_is_not_shadow_only(self):
        import mq_instruments as mi
        from masterquo.sh import models as SM
        _write(self.base / "nss" / INST / "registry.json", {"runs": {"R1": {}}, "selected": None})
        _write(self.base / "ml_scalp" / INST / "registry.json", {"runs": {"R1": {}}, "selected": {}})
        _write(self.base / "structure_intelligence" / INST / "registry.json", {"runs": {"R1": {}}, "shadow": {}})
        _write(self.base / "indicator_context" / INST / "registry.json", {"runs": {"R1": {}}, "active": None})
        _write(mi.root("forecast", INST) / "registry.json", {"runs": {"R1": {}}, "active": None})
        for mid in ("nss", "ml_scalp", "si_move", "indicator_context", "gold_forecast"):
            st = SM.probe(_item(mid), None, INST)
            self.assertEqual(st["status"], "NOT_CONNECTED", (mid, st))
            self.assertIn("żaden nie wybrany", st["reason"])
            for strat in ("SCALPING", "HEDGING"):
                self.assertEqual(SM.participation(_item(mid), st, strat)["use"], "NONE", mid)

    def test_no_runs_is_not_trained(self):
        from masterquo.sh import models as SM
        _write(self.base / "nss" / INST / "registry.json", {"runs": {}, "selected": None})
        self.assertEqual(SM.probe(_item("nss"), None, INST)["status"], "NOT_TRAINED")

    def test_si_setup_shadow_only_is_not_live(self):
        from masterquo.sh import models as SM
        p = self.base / "structure_intelligence" / INST / "registry.json"
        _write(p, {"runs": {"R1": {}}, "shadow": {"SCALP_STRUCTURE_CONTEXT_V1": {"candidate_id": "C1", "dir": "x"}}})
        st = SM.probe(_item("si_move"), None, INST)
        self.assertEqual(st["status"], "NOT_CONNECTED", st)                  # Forecaster reads only shadow[STRUCTURE_MOVE_M1_V1]
        self.assertIn("SCALP_STRUCTURE_CONTEXT_V1", st["reason"])
        _write(p, {"runs": {"R1": {}}, "shadow": {"STRUCTURE_MOVE_M1_V1": {"candidate_id": "C2", "dir": "y"}}})
        self.assertEqual(SM.probe(_item("si_move"), None, INST)["status"], "SHADOW_ONLY")


class TestI0303ProbeFlowReaction(_Data):
    def test_selected_shadow_without_live_path_is_not_connected(self):
        from masterquo.sh import models as SM
        _write(self.base / "flow_context" / INST / "registry.json",
               {"runs": {"R1": {}}, "shadow": {"FLOW_CONTEXT_MOVE_M1_V1": {"candidate_id": "C1", "dir": "x", "model_hash": "h"}}})
        st = SM.probe(_item("flow_reaction"), None, INST)
        self.assertEqual(st["status"], "NOT_CONNECTED", st)                  # nothing loads the reaction model live (Markov3 only)
        self.assertIn("C1", st["reason"])
        self.assertIn("bez ścieżki inferencji na żywo", st["reason"])
        self.assertEqual(SM.participation(_item("flow_reaction"), st, "SCALPING")["use"], "NONE")


class TestI0624ProbeScalpB(_Data):
    def test_active_run_without_setup_model_is_not_trained(self):
        import mq_instruments as mi
        from masterquo.sh import models as SM
        p = mi.root("scalp", INST) / "registry.json"
        _write(p, {"runs": {"R1": {"task_b_status": "INSUFFICIENT"}}, "active": "R1"})
        st = SM.probe(_item("scalp_B"), None, INST)
        self.assertEqual(st["status"], "NOT_TRAINED", st)                   # worker answers NO_SETUP_MODEL for this run
        self.assertIn("INSUFFICIENT", st["reason"])
        self.assertEqual(SM.probe(_item("scalp_A"), None, INST)["status"], "SHADOW_ONLY")
        _write(p, {"runs": {"R1": {"task_b_status": "OK", "setup_model": {"file": "setup_model_LR.json", "threshold": 0.6}}}, "active": "R1"})
        st = SM.probe(_item("scalp_B"), None, INST)
        self.assertEqual(st["status"], "SHADOW_ONLY")
        self.assertEqual(st["detail"]["task_b_status"], "OK")


class TestI0352I0356MMShadowStatusHonest(_Data):
    def _promote(self, mid: str) -> str:
        from masterquo.mm import artifacts as MA
        aid = MA.save(INST, mid, {"w": [1.0, 2.0]}, {"status": "VALIDATED_SHADOW"})
        MA.promote_shadow(INST, mid, aid, "test")
        return aid

    def test_validated_pointer_without_live_inference_is_not_connected(self):
        from masterquo.sh import models as SM
        for mid, sid in (("hdc_dir3", "mm_hdc"), ("ste_flownet_ret", "mm_ste_flownet")):
            aid = self._promote(mid)
            st = SM.probe(_item(sid), None, INST)
            self.assertEqual(st["status"], "NOT_CONNECTED", (sid, st))
            self.assertIn(aid, st["reason"])
            self.assertNotIn("obserwacja", st["reason"])
            self.assertEqual(SM.participation(_item(sid), st, "SCALPING")["use"], "NONE")

    def test_event_engine_follows_the_quant_live_path(self):
        from masterquo.sh import models as SM
        self._promote("event_engine_dir3")
        self.assertEqual(SM.probe(_item("mm_event_engine"), None, INST)["status"], "SHADOW_ONLY")   # Quant EventGRU serves it
        gru = SimpleNamespace(latest={INST: {"state": "BLOCKED_DATA", "unavailable_reason": "za mało zamkniętych świec M1"}})
        rt = SimpleNamespace(quant=SimpleNamespace(event_gru=gru))
        st = SM.probe(_item("mm_event_engine"), rt, INST)
        self.assertEqual(st["status"], "DATA_MISSING", st)
        self.assertIn("za mało", st["reason"])
        gru.latest[INST] = {"state": "READY"}
        self.assertEqual(SM.probe(_item("mm_event_engine"), rt, INST)["status"], "SHADOW_ONLY")

    def test_gpr_pointer_not_claimed_as_live_source(self):
        from masterquo.mm import artifacts as MA
        from masterquo.mm import service as MS
        from masterquo.sh import models as SM
        aid = self._promote("gpr_logret")
        st = SM.probe(_item("mm_gpr"), None, INST)
        self.assertIn("nie jest wczytywany", st["reason"])
        self.assertIn(aid, st["reason"])
        self.assertNotIn("zwalidowany na danych rzeczywistych", st["reason"])
        self._promote("hdc_dir3")
        tm = MS._trained_models(MA.read_pointer(INST))
        self.assertFalse(tm["gpr_logret"].startswith("SHADOW:"), tm)
        self.assertIn("dopasowanie", tm["gpr_logret"])
        self.assertIn("brak inferencji na żywo", tm["hdc_dir3"])
        self.assertTrue(tm["ste_flownet_ret"].startswith("brak artefaktu"))

    def test_inventory_callers_match_the_code(self):
        from masterquo.mm import inventory as MI
        mods = {m["id"]: m for m in MI.MODULES}
        self.assertNotIn("mm.service", mods["hdc"]["callers"])                 # the service only lists the pointer
        self.assertTrue(any("EventGRU" in c for c in mods["event_engine"]["callers"]))


# ================================================================================================ udział w macierzy SH
class TestI0569I0586I0591I0593I0318ParticipationMatchesSetup(unittest.TestCase):
    def test_participation_matches_setup_consumers(self):
        td = TempData()
        self.addCleanup(td.close)
        from masterquo.sh import models as SM
        rows = {r["id"]: r for r in SM.matrix(None, INST)["rows"]}
        for strat in ("SCALPING", "HEDGING"):
            self.assertEqual(rows["structure_v2"][strat]["use"], "GATE")          # HTF conflict -> WAIT, obstacle -> NO_TRADE
            self.assertEqual(rows["vamd"][strat]["use"], "GATE")                  # CONTINUATION confirmation
            self.assertEqual(rows["candles_patterns"][strat]["use"], "GATE")      # REVERSAL confirmation
            self.assertEqual(rows["atr_vol"][strat]["use"], "GATE")               # ATR warm-up -> WAIT, reach -> NO_TRADE
            self.assertEqual(rows["smc_pullback"][strat]["use"], "EVIDENCE")      # zone / levels of the setup
            for mid in ("liquidity", "flow_sr", "decomposition"):                 # nothing in sh/setup.py reads them
                self.assertEqual(rows[mid][strat]["use"], "INFO", (mid, strat))

    def test_supervision_is_never_evidence(self):
        from masterquo.sh import models as SM
        for mid in ("decomposition", "scalp_B", "legacy_ml", "agent"):
            for s in ("READY", "DETERMINISTIC_OK", "SHADOW_ONLY"):
                self.assertEqual(SM.participation(_item(mid), {"status": s}, "SCALPING")["use"], "INFO", (mid, s))
            self.assertEqual(SM.participation(_item(mid), {"status": "NOT_TRAINED"}, "SCALPING")["use"], "NONE")

    def test_every_sh_use_is_known(self):
        from masterquo.sh import models as SM
        for it in SM.REGISTRY:
            self.assertIn(it.get("sh_use"), (None, "GATE", "INPUT"), it["id"])


# ================================================================================================ oś use (I0005)
def _kronos_rt(use_s: str, status: str = "READY"):
    st = SimpleNamespace(strategy_use={"SCALPING": SimpleNamespace(use=use_s), "HEDGING": SimpleNamespace(use="OBSERVE")})
    return SimpleNamespace(kronos=SimpleNamespace(state={"status": status, "reason": status}, settings=SimpleNamespace(get=lambda: st)))


class TestI0005SHMatrixUse(_Data):
    def test_required_or_assist_is_shown_as_hold_only(self):
        from masterquo.sh import models as SM
        it = _item("kronos")
        st = SM.probe(it, _kronos_rt("REQUIRED"), INST)
        p = SM.participation(it, st, "SCALPING")
        self.assertEqual((p["use"], p.get("use_configured")), ("HOLD_ONLY", "REQUIRED"))
        self.assertEqual(SM.participation(it, st, "HEDGING")["use"], "INFO")
        st = SM.probe(it, _kronos_rt("REQUIRED", "NO_WEIGHTS"), INST)          # REQUIRED holds READY -> WAIT also when unavailable
        self.assertEqual(SM.participation(it, st, "SCALPING")["use"], "HOLD_ONLY")
        st = SM.probe(it, _kronos_rt("ASSIST", "NO_WEIGHTS"), INST)            # ASSIST without a forecast changes nothing
        self.assertEqual(SM.participation(it, st, "SCALPING")["use"], "NONE")
        st = SM.probe(it, _kronos_rt("ASSIST"), INST)
        self.assertEqual(SM.participation(it, st, "SCALPING")["use"], "HOLD_ONLY")

    def test_tsfm_use_is_read(self):
        from masterquo.sh import models as SM
        uses = {"ACTIVE": SimpleNamespace(use="OBSERVE"), "SCALPING": SimpleNamespace(use="ASSIST"), "HEDGING": SimpleNamespace(use="OBSERVE")}
        ts = SimpleNamespace(workers={"chronos2": SimpleNamespace(state={"status": "READY"})},
                             settings=SimpleNamespace(get=lambda: SimpleNamespace(models={"chronos2": SimpleNamespace(use=uses)})))
        it = _item("chronos2")
        st = SM.probe(it, SimpleNamespace(tsfm=ts), INST)
        self.assertEqual(SM.participation(it, st, "SCALPING")["use"], "HOLD_ONLY")
        self.assertEqual(SM.participation(it, st, "HEDGING")["use"], "INFO")

    def test_legacy_ml_mode_is_shown(self):
        from masterquo.modelhub import catalog as CATL
        from masterquo.sh import models as SM
        rt = SimpleNamespace(ml=SimpleNamespace(inst=INST, registry=SimpleNamespace(champion_id="C1")),
                             cfg=SimpleNamespace(get=lambda: SimpleNamespace(ml=SimpleNamespace(mode="ASSIST"))))
        st = SM.probe(_item("legacy_ml"), rt, INST)
        self.assertEqual(st["detail"]["ml_mode"], "ASSIST")
        self.assertIn("bramka ścieżki ACTIVE", st["reason"])
        row = next(r for r in CATL.build(rt, INST)["items"] if r["id"] == "legacy_ml")
        self.assertIn("ASSIST", row.get("use_note") or "")
        self.assertNotIn("nie dopuszczony do głosu", row.get("use_note") or "")


# ================================================================================================ runner_step (I0014)
class TestI0014TrainOwner(_Data):
    def test_runner_step_is_a_runner_step_or_none(self):
        from masterquo.sh import models as SM
        from masterquo.training import runner as R
        for it in SM.REGISTRY:
            step = SM.runner_step(it)
            self.assertTrue(step is None or step in R.STEPS, (it["id"], step))
        for mid in ("th_direction", "granite_ttm"):
            self.assertIsNone(SM.runner_step(_item(mid)))
            self.assertTrue(_item(mid).get("owner_train"))

    def test_panel_names_the_owner_instead_of_a_missing_task(self):
        from masterquo.training import panel as TP
        rows = {r["id"]: r for r in TP.models(None, INST)["models"]}
        th = rows["th_direction"]
        self.assertNotIn("uruchom zadanie trainhub", " ".join(th["blockers"]))
        self.assertTrue(any("Centrum treningu" in b for b in th["blockers"]), th["blockers"])
        self.assertIsNone(th["runner_step"])


# ================================================================================================ opisy rejestru
class TestI0563RegimeText(unittest.TestCase):
    def test_regime_outputs_match_machine(self):
        from masterquo.modelhub import catalog as CATL
        out = _item("regime_v2")["output"]
        self.assertNotIn("HIGH_VOL", out)
        for s in ("TREND_UP", "TREND_DOWN", "RANGE", "TRANSITION"):
            self.assertIn(s, out)
        self.assertEqual(CATL.LOCATION["regime_v2"][1], "świece M5")         # sh/context._regime(m5) – M5 only


class TestI0660ThDirectionName(unittest.TestCase):
    def test_name_lists_every_trainhub_model(self):
        from masterquo.trainhub import learn as L
        name = _item("th_direction")["name"]
        for mid in L.MODELS:
            if mid != "TH_BASELINE":
                self.assertIn(mid.removeprefix("TH_"), name, mid)
        self.assertIn("bazowy", name)


# ================================================================================================ legacy replay SH (I0055) / kontekst (I0861)
class TestI0055ReplaySnapshotCfg(unittest.TestCase):
    def test_replay_uses_the_configured_age_limits(self):
        from masterquo.sh import config as C
        from masterquo.sh import replay as RP
        from test_sh_pack import all_tfs, series
        td = TempData()
        self.addCleanup(td.close)
        bars = all_tfs(series(n=1300))
        seen = []

        def fake_snapshot(w, q, **kw):
            seen.append(kw.get("cfg"))
            return {"data": {"status": "OK"}}
        market = RP.Market({k: bars[k] for k in ("M1", "M5", "M15", "H1")}, spread_fallback=0.2)
        prof = {"SCALPING": {"_instrument": {"max_spread_usd": 0.5}}}
        with mock.patch.object(RP.CX, "snapshot", fake_snapshot), mock.patch.object(RP.SU, "evaluate", lambda *a, **k: {"status": "WAIT"}):
            next(RP.scan(market, _spec(), prof))
        risk = C.load()["risk"]
        self.assertEqual(seen[0]["max_bar_age_s"], risk["max_bar_age_s"])
        self.assertEqual(seen[0]["max_quote_age_s"], risk["max_quote_age_s"])
        self.assertEqual(seen[0]["max_spread_usd"], 0.5)


class TestI0861QuoteWithoutTime(unittest.TestCase):
    def test_quote_without_time_is_blocked(self):
        from masterquo.sh import context as CX
        cfg = {"max_bar_age_s": {}, "max_quote_age_s": 5.0}
        for q in ({"bid": 1.0, "ask": 1.1}, {"bid": 1.0, "ask": 1.1, "time": 0}, {"bid": 1.0, "ask": 1.1, "time": "x"}):
            r = CX.data_quality({}, q, 1_760_000_000.0, cfg)
            self.assertEqual(r["status"], "BLOCK", q)
            self.assertIsNone(r["quote_age_s"])
            self.assertIn("brak znacznika czasu notowania", r["issues"])
        r = CX.data_quality({}, {"bid": 1.0, "ask": 1.1, "time": 1_760_000_000.0 - 1.0}, 1_760_000_000.0, cfg)
        self.assertEqual((r["status"], r["quote_age_s"]), ("OK", 1.0))


# ================================================================================================ pakiet SH (engine / policies)
def _spec():
    from masterquo.sh.units import SymbolSpec
    return SymbolSpec("XAUUSD-", 0.01, 1.0, 100, 0.01, 0.01, 50, 2, "USD", point=0.01)


def _plan_found(vid: str, cfg: dict | None = None):
    """(engine, candidate, X, v, tf, quote, t, cfg2, det) for the first BUY setup of `vid` on the deterministic series of test_sh_pack."""
    from masterquo.sh.pack.engine import PackEngine
    from test_sh_pack import _Found, ctx
    bars, found, cfg0 = _Found.get()
    cfg = cfg or cfg0
    t, tf, d = found[vid]
    X = ctx(bars, t)
    v = cfg["variants"][vid]
    last = X.tf(tf, False)
    c = last.c[last.n - 1]
    q = {"bid": c, "ask": c + 0.2, "spread": 0.2, "age_s": 0.3}
    cfg2 = dict(cfg, common=dict(cfg["common"], warmup={"ema_mult": 1}))
    e = PackEngine()
    su = e._plan(X, v, tf, "BUY", d, INST, _spec(), {"slippage_usd": 0.05}, q, t, cfg["instruments"][INST], cfg2, 100.0, "USD")
    return e, su, X, v, tf, q, t, cfg2, d


def _m5(closes, t0, base=3000.0):
    from test_sh_pack import m5bars
    return m5bars(closes, t0, base)


class TestI0743LiveHedgeParamsFromConfig(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)

    def _cfg(self, adverse: float):
        from masterquo.sh.pack import catalog as CAT
        return CAT.load({"variants": {"PMW_HG01": {"hedge": {"adverse_min_r": adverse, "confirm_closes": 3}}}})

    def test_plan_freezes_the_variant_activation_params_tightening_only(self):
        _e, su, *_ = _plan_found("PMW_HG01", self._cfg(1.0))
        h = su["pack"]["hedge"]
        self.assertEqual(h["adverse_min_r"], 1.0)                              # stricter than the built-in 0.5 -> the configured value
        self.assertEqual(h["confirm_closes"], 3)
        _e, su, *_ = _plan_found("PMW_HG01", self._cfg(0.3))
        self.assertEqual(su["pack"]["hedge"]["adverse_min_r"], 0.5)            # looser -> never an earlier hedge than 1.46 live (S0)

    def test_live_policy_reads_the_frozen_threshold(self):
        from masterquo.sh.pack import catalog as CAT
        from masterquo.sh.pack import policies as POL
        from test_sh_pack import T0
        _e, su, *_ = _plan_found("PMW_HG01", self._cfg(1.0))
        plan = {"pack": {"hedge": su["pack"]["hedge"], "params": su["pack"].get("params"), "economics": {"c_round_trip": 0.2}}}
        bars = _m5([3000.0] * 30 + [2996.0, 2995.5, 2995.0], T0)
        prim = {"side": "BUY", "entry": 3000.0, "sl": 2990.0, "remaining": 1.0, "volume": 1.0, "opened_at": T0 + 300 * 30}
        dec = POL.decision("PMW_HG01", plan=plan, st={}, pstate={}, m5_bars=bars, h1_bars=[], quote={"bid": 2993.0, "ask": 2993.2},
                           now=T0 + 300 * 33, primary=prim, hedged=False, hedge_opened_at=None, activations=0, tick=0.01, common=CAT.load()["common"])
        self.assertEqual(dec["decision"], "HOLD")                              # MAE 0.7r < frozen 1.0r (1.46 live: HEDGE at 0.5r)
        plan["pack"]["hedge"] = {k: v for k, v in plan["pack"]["hedge"].items() if k not in ("adverse_min_r", "confirm_closes")}
        dec = POL.decision("PMW_HG01", plan=plan, st={}, pstate={}, m5_bars=bars, h1_bars=[], quote={"bid": 2993.0, "ask": 2993.2},
                           now=T0 + 300 * 33, primary=prim, hedged=False, hedge_opened_at=None, activations=0, tick=0.01, common=CAT.load()["common"])
        self.assertEqual(dec["decision"], "HEDGE")                             # plans frozen before the fix keep the 1.46 behaviour

    def test_strict_values(self):
        from masterquo.sh.pack import policies as POL
        f = POL.frozen_activation({"adverse_min_r": 0.2, "confirm_closes": 1, "body_atr": 1.2, "sigma_ratio_on": 2.0, "move_atr": 0.1,
                                   "ratio_min": 0.4, "ratio_max": 0.3, "mfe_min_r": 2.0, "giveback_r": 0.25, "sigma_ratio_off": 1.0, "off_bars": 9})
        self.assertEqual(f, {"adverse_min_r": 0.5, "confirm_closes": 2, "body_atr": 1.2, "sigma_ratio_on": 2.0, "move_atr": 0.5,
                             "ratio_min": 0.25, "ratio_max": 0.3, "mfe_min_r": 2.0, "giveback_r": 0.5})   # unwind params are not frozen
        self.assertEqual(POL.frozen_activation({}), {})


class TestI0819PackLastCleared(unittest.TestCase):
    def test_removed_tf_and_disabled_variant_are_dropped(self):
        from masterquo.sh.pack import catalog as CAT
        from masterquo.sh.pack.engine import PackEngine
        td = TempData()
        self.addCleanup(td.close)
        now = 1_762_200_000.0
        e = PackEngine()
        e.last[("PMW_HG01", "M15")] = {"status": "READY", "pack": {}}
        e.last[("PMW_SC02", "M1")] = {"status": "READY", "pack": {}}
        e.active[("PMW_HG01", "M15", "BUY")] = {"status": "READY", "valid_until": now + 600, "pack": {"signal_tf": "M15"}}
        e.active[("PMW_SC02", "M1", "BUY")] = {"status": "READY", "valid_until": now + 600, "pack": {"signal_tf": "M1"}}
        cfg = CAT.load({"variants": {"PMW_HG01": {"signal_tfs": ["M5"]}, "PMW_SC02": {"enabled": False}}})
        e.evaluate(bars={}, quote=None, spec=_spec(), inst=INST, ic={}, now=now, cfg=cfg)
        self.assertNotIn(("PMW_HG01", "M15"), e.last)                          # TF removed from the configuration
        self.assertIn(("PMW_HG01", "M5"), e.last)
        self.assertNotIn(("PMW_HG01", "M15", "BUY"), e.active)
        self.assertNotIn(("PMW_SC02", "M1", "BUY"), e.active)                  # disabled: its READY never comes back after re-enabling
        self.assertEqual(e.last[("PMW_SC02", "M1")]["pack"]["reason_code"], "DISABLED")
        self.assertNotIn(("PMW_HG01", "M15"), {(x["strategy_id"], x["signal_tf"]) for x in e.public()["items"]})


class TestI0820HedgeBufferUnavailable(unittest.TestCase):
    def test_hg_without_m5_buffer_is_no_trade(self):
        from masterquo.sh.pack import features as F
        td = TempData()
        self.addCleanup(td.close)
        with mock.patch.object(F.TF, "b", lambda self, i, tick, cm: None):
            _e, su, *_ = _plan_found("PMW_HG01")
        self.assertEqual(su["status"], "NO_TRADE", su.get("status_reason"))
        self.assertEqual(su["pack"]["reason_code"], "HEDGE_BUFFER_UNAVAILABLE")


class TestI0821ReadyInvalidatedOnConfigChange(unittest.TestCase):
    def test_ready_of_an_older_config_is_invalidated(self):
        from masterquo.sh.pack import catalog as CAT
        from test_sh_pack import _Found
        td = TempData()
        self.addCleanup(td.close)
        _bars, found, _cfg = _Found.get()
        for vid in sorted(found):
            e, su, X, v, tf, q, t, cfg2, _d = _plan_found(vid)
            if su["status"] != "READY":
                continue
            ready = dict(su, config_hash="OLD", pack=dict(su["pack"], config_hash="OLD"))
            e.active[(vid, tf, "BUY")] = ready
            cfg = CAT.load()
            out = e._one(X, v, tf, INST, _spec(), {"slippage_usd": 0.05}, q, t, cfg["instruments"][INST], cfg2, 100.0, "USD")
            self.assertEqual(out["status"], "INVALIDATED", (vid, out.get("status_reason")))
            self.assertEqual(out["pack"]["reason_code"], "CONFIG_CHANGED")
            self.assertNotIn((vid, tf, "BUY"), e.active)
            e.active[(vid, tf, "BUY")] = su                                        # same config: the frozen READY is kept (unchanged)
            out = e._one(X, v, tf, INST, _spec(), {"slippage_usd": 0.05}, q, t, cfg["instruments"][INST], cfg2, 100.0, "USD")
            self.assertEqual(out["status"], "READY")
            return
        self.fail("brak kandydata READY w danych testowych")


class TestI0822HG01EmaWarmup(unittest.TestCase):
    def test_sell_base_without_ema20_never_activates(self):
        from masterquo.sh.pack import catalog as CAT
        from masterquo.sh.pack import policies as POL
        from test_sh_pack import T0
        cfg = CAT.load()
        v = cfg["variants"]["PMW_HG01"]
        plan = {"pack": {"hedge": v["hedge"], "params": v["params"], "economics": {"c_round_trip": 0.2}}}
        bars = _m5([3000.0] * 19, T0)                                           # < 20 closed M5: EMA20 is None everywhere
        prim = {"side": "SELL", "entry": 3000.0, "sl": 3010.0, "remaining": 1.0, "volume": 1.0, "opened_at": T0 + 300 * 15}
        dec = POL.decision("PMW_HG01", plan=plan, st={}, pstate={}, m5_bars=bars, h1_bars=[], quote={"bid": 3005.8, "ask": 3006.0},
                           now=T0 + 300 * 19, primary=prim, hedged=False, hedge_opened_at=None, activations=0, tick=0.01, common=cfg["common"])
        self.assertEqual(dec["decision"], "HOLD", dec)                         # 1.46: HEDGE (None -> 0, mirrored closes always 'below')


if __name__ == "__main__":
    unittest.main()
