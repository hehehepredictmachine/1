"""1.46 architecture fixes, group "forecast" (gold_candles forecast and scalp registries, gold_candles adapter in the prediction contract).

D20  Activation by hand (registry_cli / scalp_registry activate) and rollback accepted a run whose VALIDATION verdict was REJECTED -
     only the data kind, horizons, checksum and contract were checked. New gate admissible(): a REJECTED run (or one without a verdict)
     is refused on activate and skipped on rollback. It is NOT part of activatable(): the worker calls activatable() on every forecast,
     so an already active run is never switched off silently (registry_cli list warns; its rejected horizons are not READY - D21).
     SYNTHETIC_TEST under the test override keeps testing the code path (a random-walk verdict has no market meaning).
D21  modelhub.adapters.forecast_predictions published READY for every horizon of a SHADOW forecast: also for horizons REJECTED in
     validation and for horizons over the weekly market break (worker session_check BLOCKED_SESSION_BREAK); READY horizons were labelled
     UNCALIBRATED although gold_candles always applies its multinomial calibrator fitted on the calibration period.
     (The scalp A record in quant/adapters.py belongs to another group.)
All entries here are hand-built registry rows in an isolated data dir; nothing is trained and nothing is a forecast."""
from __future__ import annotations

import contextlib
import io
import json
import os
import unittest

import _env


class _EnvGuard:
    """Restores os.environ keys the runtime sets (use_instrument writes MQ_INSTRUMENT) and the registered broker symbols."""
    KEYS = ("MQ_INSTRUMENT", "MQ_FORECAST_TEST_ALLOW_SYNTHETIC", "MASTERQUO_DATA_DIR")

    def __enter__(self):
        from gold_candles import data as gd
        self.prev = {k: os.environ.get(k) for k in self.KEYS}
        self.syms = set(gd.REGISTERED_SYMBOLS)
        return self

    def __exit__(self, *exc):
        from gold_candles import data as gd
        for k, v in self.prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        gd.REGISTERED_SYMBOLS.clear()
        gd.REGISTERED_SYMBOLS.update(self.syms)


class _Case(unittest.TestCase):
    def setUp(self):
        self.guard = _EnvGuard().__enter__()
        self.td = _env.TempData()
        os.environ.pop("MQ_FORECAST_TEST_ALLOW_SYNTHETIC", None)
        os.environ.pop("MQ_INSTRUMENT", None)

    def tearDown(self):
        self.td.close()
        self.guard.__exit__(None, None, None)


# ===================================================================================================== D20 gold forecast registry
def _gold_entry(rid: str, overall: str | None, *, data_kind: str = "REAL_USER_DATA") -> dict:
    """Registry row of a forecast run with a real artifact file (checksum) and the CURRENT contract - activatable() passes."""
    from gold_candles.model import SCHEMA
    from gold_candles_runtime.common import current_contract, forecast_dir, sha256_file
    d = forecast_dir() / "runs" / rid
    d.mkdir(parents=True, exist_ok=True)
    mp = d / "forecast_model.json"
    mp.write_text(json.dumps({"schema": SCHEMA, "run_id": rid}), encoding="utf-8")
    e = {"run_id": rid, "model_path": str(mp), "artifact_sha256": sha256_file(mp), "data_kind": data_kind, "symbol": "XAUUSD-",
         "tick_size": 0.01, "horizons_trained": ["1", "3", "6"], "horizon_status": {"1": "REJECTED", "3": "REJECTED", "6": "REJECTED"}}
    if overall is not None:
        e["overall_status"] = overall
    e["contract_hash"] = current_contract(e)
    return e


class TestGoldActivationRefusesRejected(_Case):
    def write(self, active, history, runs):
        from gold_candles_runtime.common import write_registry
        write_registry({"schema": "masterquo-forecast-registry-1", "active": active, "history": list(history), "runs": runs})

    def test_activate_refuses_rejected_and_missing_verdict(self):
        from gold_candles_runtime import common
        self.write("RUN_OK", [], {"RUN_OK": _gold_entry("RUN_OK", "PARTIAL_VALIDATION"), "RUN_REJ": _gold_entry("RUN_REJ", "REJECTED"),
                                  "RUN_NONE": _gold_entry("RUN_NONE", None)})
        for rid, why in (("RUN_REJ", "REJECTED"), ("RUN_NONE", "VALIDATION_MISSING")):
            with self.assertRaises(SystemExit) as cm:
                common.activate(rid, reason="test")
            self.assertIn(why, str(cm.exception), rid)
            reg = common.read_registry()
            self.assertEqual((reg["active"], reg["history"]), ("RUN_OK", []), rid)            # registry untouched

    def test_activate_keeps_non_rejected_runs(self):
        from gold_candles_runtime import common
        self.write(None, [], {f"RUN_{s}": _gold_entry(f"RUN_{s}", s) for s in ("TRAINED_SHADOW", "PARTIAL_VALIDATION", "SHADOW_UNVALIDATED")})
        for s in ("TRAINED_SHADOW", "PARTIAL_VALIDATION", "SHADOW_UNVALIDATED"):
            self.assertEqual(common.activate(f"RUN_{s}", reason="test")["active"], f"RUN_{s}")

    def test_admissible_is_not_part_of_activatable(self):
        # the worker calls activatable() on every forecast - an already active REJECTED run must not vanish without a trace
        from gold_candles_runtime import common
        e = _gold_entry("RUN_REJ", "REJECTED")
        self.assertEqual(common.activatable(e, common.current_contract(e)), (True, None))
        self.assertEqual(common.admissible(e), (False, "VALIDATION_REJECTED"))

    def test_rollback_skips_a_rejected_run(self):
        from gold_candles_runtime import registry_cli
        from gold_candles_runtime.common import read_registry
        self.write("RUN_C", ["RUN_GOOD", "RUN_REJ"], {"RUN_GOOD": _gold_entry("RUN_GOOD", "TRAINED_SHADOW"),
                                                       "RUN_REJ": _gold_entry("RUN_REJ", "REJECTED"), "RUN_C": _gold_entry("RUN_C", "TRAINED_SHADOW")})
        with contextlib.redirect_stdout(io.StringIO()):
            rc = registry_cli.main(["rollback"])
        self.assertEqual(rc, 0)
        self.assertEqual(read_registry()["active"], "RUN_GOOD")                                # was RUN_REJ

    def test_list_shows_the_verdict_and_warns_about_an_active_rejected_run(self):
        from gold_candles_runtime import registry_cli
        self.write("RUN_REJ", [], {"RUN_REJ": _gold_entry("RUN_REJ", "REJECTED"), "RUN_OK": _gold_entry("RUN_OK", "TRAINED_SHADOW")})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(registry_cli.main(["list"]), 0)
        lines = out.getvalue().splitlines()
        self.assertIn("NIE: VALIDATION_REJECTED", next(x for x in lines if "RUN_REJ" in x and "REAL_USER_DATA" in x))
        self.assertIn("może być aktywny", next(x for x in lines if "RUN_OK" in x))
        self.assertTrue(any(x.startswith("[UWAGA]") and "RUN_REJ" in x for x in lines), lines)

    def test_synthetic_code_path_test_still_activates(self):
        # SYNTHETIC_TEST with the test override (tests/gold_candles, models check --smoke): random-walk data are REJECTED by construction
        from gold_candles_runtime import common
        os.environ["MQ_FORECAST_TEST_ALLOW_SYNTHETIC"] = "1"
        self.write(None, [], {"RUN_SYN": _gold_entry("RUN_SYN", "REJECTED", data_kind="SYNTHETIC_TEST")})
        self.assertEqual(common.activate("RUN_SYN", reason="test")["active"], "RUN_SYN")
        os.environ.pop("MQ_FORECAST_TEST_ALLOW_SYNTHETIC")
        self.assertEqual(common.admissible(_gold_entry("RUN_SYN2", "REJECTED", data_kind="SYNTHETIC_TEST")), (False, "VALIDATION_REJECTED"))


# ===================================================================================================== D20 scalp registry
def _scalp_entry(rid: str, task_a: str | None, *, data_kind: str = "REAL_USER_DATA") -> dict:
    from gold_candles_runtime import scalp_features as SF
    from gold_candles_runtime.scalp_infer import scalp_dir
    d = scalp_dir() / "runs" / rid
    d.mkdir(parents=True, exist_ok=True)
    return {"run_id": rid, "run_dir": str(d), "data_kind": data_kind, "symbol": "XAUUSD-", "tick_size": 0.01, "task_a_status": task_a,
            "horizon_status": {"1": task_a, "3": task_a, "5": task_a}, "artifacts": {}, "models": {},
            "contract_hash": SF.contract_hash("XAUUSD-", 0.01)}


class TestScalpActivationRefusesRejected(_Case):
    def write(self, active, history, runs):
        from gold_candles_runtime.common import write_json_atomic
        from gold_candles_runtime.scalp_infer import registry_path
        write_json_atomic(registry_path(), {"schema": "masterquo-scalp-registry-1", "active": active, "history": list(history), "runs": runs})

    def run_cli(self, *args):
        from gold_candles_runtime import scalp_registry
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = scalp_registry.main(list(args))
        return rc, out.getvalue()

    def test_activate_refuses_rejected(self):
        from gold_candles_runtime.scalp_infer import read_registry
        self.write("S_OK", [], {"S_OK": _scalp_entry("S_OK", "PARTIAL_VALIDATION"), "S_REJ": _scalp_entry("S_REJ", "REJECTED")})
        rc, out = self.run_cli("activate", "S_REJ")
        self.assertEqual(rc, 2, out)
        self.assertIn("VALIDATION_REJECTED", out)
        self.assertEqual(read_registry()["active"], "S_OK")

    def test_activate_keeps_unvalidated_and_validated(self):
        from gold_candles_runtime.scalp_infer import read_registry
        self.write(None, [], {"S_U": _scalp_entry("S_U", "SHADOW_UNVALIDATED"), "S_V": _scalp_entry("S_V", "TRAINED_SHADOW")})
        for rid in ("S_U", "S_V"):
            rc, out = self.run_cli("activate", rid)
            self.assertEqual(rc, 0, out)
            self.assertEqual(read_registry()["active"], rid)

    def test_rollback_skips_rejected_and_worker_gate_unchanged(self):
        from gold_candles_runtime import scalp_features as SF
        from gold_candles_runtime.scalp_infer import (
            activatable,
            admissible,
            read_registry,
        )
        self.write("S_C", ["S_GOOD", "S_REJ"], {"S_GOOD": _scalp_entry("S_GOOD", "TRAINED_SHADOW"), "S_REJ": _scalp_entry("S_REJ", "REJECTED"),
                                                "S_C": _scalp_entry("S_C", "TRAINED_SHADOW")})
        rc, out = self.run_cli("rollback")
        self.assertEqual(rc, 0, out)
        self.assertEqual(read_registry()["active"], "S_GOOD")                                  # was S_REJ
        e = _scalp_entry("S_X", "REJECTED")
        self.assertEqual(activatable(e, SF.contract_hash("XAUUSD-", 0.01)), (True, None))      # worker path (scalp_forecast) unchanged
        self.assertEqual(admissible(e), (False, "VALIDATION_REJECTED"))

    def test_list_shows_the_verdict(self):
        self.write("S_REJ", [], {"S_REJ": _scalp_entry("S_REJ", "REJECTED")})
        rc, out = self.run_cli("list")
        self.assertEqual(rc, 0)
        self.assertIn("NIE: VALIDATION_REJECTED", next(x for x in out.splitlines() if "S_REJ" in x and "REAL_USER_DATA" in x))
        self.assertTrue(any(x.startswith("[UWAGA]") and "S_REJ" in x for x in out.splitlines()), out)

    def test_synthetic_code_path_test_still_activates(self):
        # tests/gold_candles/test_scalp_train.py::test_worker_path_and_checksum and models check --smoke scalp_gold activate a synthetic
        # (REJECTED by construction) run under the test override; without the override it stays refused (NOT_REAL_USER_DATA first)
        from gold_candles_runtime.scalp_infer import read_registry
        self.write(None, [], {"S_SYN": _scalp_entry("S_SYN", "REJECTED", data_kind="SYNTHETIC_TEST")})
        rc, out = self.run_cli("activate", "S_SYN")
        self.assertEqual(rc, 2)
        self.assertIn("NOT_REAL_USER_DATA", out)
        os.environ["MQ_FORECAST_TEST_ALLOW_SYNTHETIC"] = "1"
        rc, out = self.run_cli("activate", "S_SYN")
        self.assertEqual(rc, 0, out)
        self.assertEqual(read_registry()["active"], "S_SYN")


# ===================================================================================================== D21 gold_candles adapter
def _rt(state: dict):
    fs = type("FS", (), {"public": lambda self_: state})()
    return type("RT", (), {"forecast": fs, "trainhub_inference": None})()


def _probs(mins: int, session: str = "NOT_VERIFIED_BROKER_SESSIONS", **kw) -> dict:
    return {"horizon_minutes": mins, "probabilities": {"DOWN": 0.2, "FLAT": 0.3, "UP": 0.5}, "session_check": session, **kw}


class TestGoldForecastAdapterStates(unittest.TestCase):
    def state(self, model: dict) -> dict:
        rep = {"symbol": "XAUUSD-", "forecast": {"feature_time_utc": "2026-11-20T20:45:00Z", "probabilities": {
            "5": _probs(5), "15": _probs(15),
            "30": _probs(30, "BLOCKED_SESSION_BREAK", blocked_reason="horyzont obejmuje przerwę rynku – prognoza niedopuszczalna")}}}
        return {"status": "SHADOW", "instrument": "XAUUSD", "report": rep, "model": model}

    def test_rejected_and_session_break_horizons_are_not_ready(self):
        from masterquo.modelhub import adapters as AD
        from masterquo.modelhub import contract as C
        ps = AD.forecast_predictions(_rt(self.state({"run_id": "R1", "horizon_status": {"1": "SHADOW_VALIDATED", "3": "REJECTED",
                                                                                         "6": "SHADOW_UNVALIDATED"}})), "XAUUSD")
        self.assertEqual([(p["horizon"]["bars"], p["state"]) for p in ps], [(1, "READY"), (3, "DISABLED"), (6, "BLOCKED_DATA")])   # was 3x READY
        self.assertEqual(ps[0]["result"], {"DOWN": 0.2, "FLAT": 0.3, "UP": 0.5})
        for p in ps[1:]:
            self.assertIsNone(p["result"])                                                    # a refused horizon never carries a value
            self.assertTrue(p["unavailable_reason"])
            self.assertEqual(p["model_key"], f"gold_candles_{p['horizon']['bars'] * 5}m")
        self.assertIn("REJECTED", ps[1]["unavailable_reason"])
        self.assertIn("przerwę rynku", ps[2]["unavailable_reason"])
        for p in ps:
            C.validate(p)

    def test_ready_horizons_are_calibrated_on_the_calibration_period(self):
        from masterquo.modelhub import adapters as AD
        ps = AD.forecast_predictions(_rt(self.state({"run_id": "R1", "horizon_status": {"1": "SHADOW_UNVALIDATED", "3": "SHADOW_VALIDATED",
                                                                                         "6": "SHADOW_VALIDATED"}})), "XAUUSD")
        ready = [p for p in ps if p["state"] == "READY"]
        self.assertEqual(len(ready), 2)
        for p in ready:
            self.assertEqual(p["calibration"]["status"], "CALIBRATED_DEV")                   # was UNCALIBRATED
            self.assertTrue(p["calibration"]["method"])

    def test_quant_features_only_from_admitted_horizons(self):
        # impact on Quant: fc:gold_candles:* features exist only for READY horizons (vectorise() masks the others)
        from masterquo.modelhub import adapters as AD
        from masterquo.quant import features as F
        ps = AD.forecast_predictions(_rt(self.state({"run_id": "R1", "horizon_status": {"1": "SHADOW_VALIDATED", "3": "REJECTED",
                                                                                         "6": "SHADOW_VALIDATED"}})), "XAUUSD")
        keys = sorted(F.prediction_features(ps, "LONG"))
        self.assertEqual(keys, ["fc:gold_candles_5m:CANDLE_CLOSE_DIRECTION_H1_M5:M5:edge"])

    def test_without_registry_verdict_the_horizon_stays_ready(self):
        from masterquo.modelhub import adapters as AD
        st = self.state({"run_id": "R0"})
        st["report"]["forecast"]["probabilities"].pop("30")
        ps = AD.forecast_predictions(_rt(st), "XAUUSD")
        self.assertEqual([p["state"] for p in ps], ["READY", "READY"])


# ===================================================================================================== review of D20 / D21 (round 2)
class TestScalpGoldSmokeExpectsPerHorizonStates(unittest.TestCase):
    """models check --smoke --area scalp_gold, step predict of forecast:gold_candles: the synthetic run is REJECTED by construction, so
    after D21 the adapter publishes its rejected horizons as DISABLED (and a horizon over the market break as BLOCKED_DATA). The smoke
    required 3x READY - a false FAIL of the whole area - and it would not notice the adapter going back to READY for a REJECTED horizon."""

    def setUp(self):
        self.td = _env.TempData()

    def tearDown(self):
        self.td.close()

    def run_gold(self, horizon_status: dict, sessions=("NOT_VERIFIED_BROKER_SESSIONS",) * 3, adapter=None) -> dict:
        from pathlib import Path
        from types import SimpleNamespace
        from unittest import mock

        from masterquo.modelhub.smoke import ok as smoke_ok
        from masterquo.modelhub.smoke import scalp_gold as SG
        mp = Path(self.td.dir) / "forecast_model.json"
        mp.write_text("{}", encoding="utf-8")
        import hashlib
        gold = {"run_id": "R_SYN", "horizons_trained": ["1", "3", "6"], "overall_status": "REJECTED", "horizon_status": horizon_status,
                "training_seconds": 1.0, "model_path": str(mp), "artifact_sha256": hashlib.sha256(mp.read_bytes()).hexdigest(),
                "runtime_check": {"status": "OK", "checked": 5, "parity": {"max_abs_prob_diff": 0.0}}}
        tr = {"py": "/x/python", "gold": gold, "gold_gate": (1, "[BLAD] ... NOT_REAL_USER_DATA"), "gold_activate": (0, "Aktywny model: R_SYN")}
        probs = {str(m): _probs(m, s, **({"blocked_reason": "horyzont obejmuje przerwę rynku – prognoza niedopuszczalna"}
                                          if s == "BLOCKED_SESSION_BREAK" else {})) for m, s in zip((5, 15, 30), sessions)}
        state = {"status": "SHADOW", "execution_permission": False, "instrument": "XAUUSD",
                 "report": {"symbol": "XAUUSD-", "forecast": {"feature_time_utc": "2026-11-20T20:45:00Z", "probabilities": probs}},
                 "model": {"run_id": "R_SYN", "horizon_status": horizon_status}}
        lv = {"state": state, "rt": _rt(state), "shadow_rows": [{"outcome_status": "PENDING"}] * 3}
        ctx = SimpleNamespace(step="import", contract_step=lambda recs: smoke_ok(f"{len(recs)} rekordy"))
        with mock.patch.object(SG, "_common", return_value=(None, tr)), mock.patch.object(SG, "_live", return_value=lv):
            if adapter is None:
                return SG._gold(ctx)
            with mock.patch("masterquo.modelhub.adapters.forecast_predictions", adapter):
                return SG._gold(ctx)

    def test_rejected_synthetic_run_is_not_a_false_fail(self):
        out = self.run_gold({"1": "REJECTED", "3": "REJECTED", "6": "SHADOW_UNVALIDATED"})
        self.assertEqual(out["predict"]["status"], "OK", out["predict"])                  # was FAIL: [DISABLED, DISABLED, READY] != 3x READY
        self.assertNotIn("ZNANY PROBLEM", out["predict"]["detail"])
        self.assertIn("DISABLED", out["predict"]["detail"])
        self.assertEqual(out["artifact"]["status"], "OK", out["artifact"])
        self.assertNotIn("nie sprawdza jakości", out["artifact"]["detail"])                # stale since D20 (activate checks the verdict)

    def test_session_break_horizon_is_expected_blocked_data(self):
        out = self.run_gold({"1": "SHADOW_UNVALIDATED", "3": "SHADOW_UNVALIDATED", "6": "SHADOW_UNVALIDATED"},
                            sessions=("NOT_VERIFIED_BROKER_SESSIONS", "NOT_VERIFIED_BROKER_SESSIONS", "BLOCKED_SESSION_BREAK"))
        self.assertEqual(out["predict"]["status"], "OK", out["predict"])

    def test_adapter_back_to_ready_for_a_rejected_horizon_is_a_fail(self):
        from masterquo.modelhub import adapters as AD
        real = AD.forecast_predictions

        def all_ready(rt, inst):                                                          # the pre-D21 behaviour of the adapter
            from masterquo.modelhub import contract as C
            out = []
            for p in real(rt, inst):
                if p["state"] != "READY":
                    p = C.make(instrument=inst, symbol=p.get("symbol"), timeframe="M5", model_name="gold_candles", model_version=p.get("model_version"),
                               task_type="CLASS_PROBABILITIES", task=p["task"], horizon_bars=p["horizon"]["bars"], unit="probability", state="READY",
                               result={"DOWN": 0.2, "FLAT": 0.3, "UP": 0.5}, data_time=p.get("data_time"),
                               calibration=p.get("calibration"), extra={"model_key": p.get("model_key")})
                out.append(p)
            return out
        out = self.run_gold({"1": "REJECTED", "3": "REJECTED", "6": "SHADOW_UNVALIDATED"}, adapter=all_ready)
        self.assertEqual(out["predict"]["status"], "FAIL", out["predict"])               # the old 3x READY check passed it


# ----------------------------------------------------------------------------------------------- D21 -> MetaModel Quant (retraining)
GOLD_FEAT = "fc:forecast:gold_candles:CANDLE_CLOSE_DIRECTION_H3_M5:M5:edge"


def _meta(inst: str, names: list[str], *, pre_d21: bool) -> tuple[str, str]:
    """A VALIDATED_SHADOW MetaModel artifact made active; pre_d21 = manifest written before D21 (no inputs revision)."""
    from masterquo.quant import features as F
    from masterquo.quant import metamodel as M
    model = {"version": M.VERSION, "feature_names": names, "feature_schema": F.schema(names)}
    import hashlib
    th = "task" + ("a" if pre_d21 else "b") + hashlib.sha256("|".join(names).encode()).hexdigest()[:8]
    ver = M.save(inst, {"model": model, "status": "VALIDATED_SHADOW", "report": {}}, spec={"task_hash": th})
    if pre_d21:
        mp = M.root(inst) / th / ver / "manifest.json"
        man = json.loads(mp.read_text(encoding="utf-8"))
        man.pop("inputs_rev", None)
        mp.write_text(json.dumps(man), encoding="utf-8")
    M.activate(inst, th, ver)
    return th, ver


class TestMetaModelRetrainNoticeAfterD21(unittest.TestCase):
    """D21 masks fc:forecast:gold_candles:* for horizons REJECTED in validation / over the market break, while the ledger rows an existing
    MetaModel was trained on carry values there. Not INCOMPATIBLE (validated_active() would drop it, ASSIST would stop and every Quant
    HOLD would vanish - a looser entry gate, S0 b): the model stays active and status / CLI say it needs retraining / revalidation."""

    def setUp(self):
        self.td = _env.TempData()

    def tearDown(self):
        self.td.close()

    def test_active_pre_d21_model_with_gold_features_is_flagged_but_stays_active(self):
        from masterquo.quant import features as F
        from masterquo.quant import metamodel as M
        th, ver = _meta("XAUUSD", ["plan:gain_r", GOLD_FEAT], pre_d21=True)
        _meta("XAUUSD", ["plan:gain_r", "ctx:spread_r"], pre_d21=True)                       # no gold_candles feature: nothing to say
        n = M.retrain_notices("XAUUSD")
        self.assertEqual([(x["task_hash"], x["version"]) for x in n], [(th, ver)])
        self.assertIn("D21", n[0]["message"])
        self.assertIn("retreningu", n[0]["message"])
        self.assertEqual(n[0]["features"], [GOLD_FEAT])
        self.assertEqual(F.VERSION, "PMW-QUANT-FEAT-1")                                     # schema NOT bumped on purpose
        M.load("XAUUSD", th, ver)                                                            # still loads (not INCOMPATIBLE)

    def test_model_trained_after_d21_is_not_flagged(self):
        from masterquo.quant import metamodel as M
        th, ver = _meta("XAUUSD", ["plan:gain_r", GOLD_FEAT], pre_d21=False)
        man = json.loads((M.root("XAUUSD") / th / ver / "manifest.json").read_text(encoding="utf-8"))
        self.assertIn("D21", man["inputs_rev"])
        self.assertEqual(M.retrain_notices("XAUUSD"), [])

    def test_status_and_cli_show_the_notice(self):
        from types import SimpleNamespace

        from masterquo.quant import cli
        from masterquo.quant.service import QuantService
        th, ver = _meta("XAUUSD", ["plan:gain_r", GOLD_FEAT], pre_d21=True)
        q = QuantService(SimpleNamespace(sh=SimpleNamespace(instrument=lambda: "XAUUSD"), bridge=None))
        st = q.status()["metamodel"]
        self.assertEqual(st["validated_active"], {th: ver})                                  # unchanged: ASSIST keeps its model
        self.assertEqual([x["version"] for x in st["retrain_required"]], [ver])
        for argv in (["status", "--instrument", "XAUUSD"], ["list", "--instrument", "XAUUSD"]):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(cli.main(argv), 0)
            got = json.loads(out.getvalue())
            rr = got["retrain_required"]
            rr = rr.get("XAUUSD", rr) if isinstance(rr, dict) else rr
            self.assertEqual([x["version"] for x in rr], [ver], argv)


if __name__ == "__main__":
    unittest.main()
