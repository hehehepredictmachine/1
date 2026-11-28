"""Fala 2 (grupa sh_service): SCALPING / HEDGING service, its model matrix and the shared registries. Each test fails on the code before
the fix and documents one item; tests of the decision path also prove that no block / WAIT of today disappears.

I0004 the cycle's model rows come from a cached LIVE matrix (provider) or are NOT_EVALUATED - never false DATA_MISSING / UNAVAILABLE;
      decisions identical with and without the provider.
I0551 data_quality in su['models'] is read from the cycle's own snapshot (GATE when the snapshot is OK).
I0359 mm_* rows report the MM loop state (UNAVAILABLE / ERROR / DATA_MISSING) instead of a declared SHADOW_ONLY / DETERMINISTIC_OK.
I0006 th_direction row: correlation groups per TF from modelhub.aggregate.ROUTES (additive field).
I0008 pretrained producers have kind PRETRAINED (catalog / inventory / training panel / Studio categories).
I0206 TiRex-2 is a row of the SH matrix and of the model catalog (one inventory row).
I0312 SH computes VAMD / FD with the frozen DEFAULT profile - documented (two parametrisations).
I0315 (safe variant) the context panel shows the DEFAULT values SH really uses; SH computation unchanged.
I0408 VOL_GARCH for HG09 only from an artifact with use != OFF that passes the ASSIST gate (REAL + APPROVED) - fail-closed.
I0557 SH new entries blocked inside a high-impact macro window (same rule as the ACTIVE path); hedges / exits not affected.
I0095 optional dependencies of the services have class-level defaults (None).
I0111 SH actions in UNKNOWN are visible (status + log), read only.
I0745 an ENTRY_UNKNOWN plan is adopted from the terminal without waiting for a reconnect (no hedge leg for an adopted basket).
I0746 SH daily loss: min(today's measure, broker-day measure of this mode / account) - never later than today.
I0747 no position data from MT5 = WAIT (one owner unverifiable), never 'no foreign positions'.
I0748 (safe variant) open SH plans of another symbol are reported (asset switch, SH status) - management unchanged.
I0817 a pack validation report counts only for the configuration it was made for (config_hash).
I0818 pack override validated before it is saved (types, ranges).
I0824 a broken SH event model never aborts the cycle; the bar stays without entries (as today), the cycle completes.
I0825 the duplicate window counts signals with a plan in any status (EXPIRED after TTL too).
I0826 the legacy hedge step opens no new hedge leg under STOP / entry block (exits unchanged).
I0862 basket net_rr is the net RR (costs, both targets); the coordinator order is unchanged (rank_rr = the former value).
"""
import json
import random
import time
import types
import unittest
from datetime import UTC, datetime, timedelta
from unittest import mock

import _env  # noqa: F401
import test_sh_service as TS
from _env import TempData

NOW = TS.NOW


def _bars(n=520, tf_s=300, seed=7, start=1_759_000_000):
    rnd = random.Random(seed)
    px, out = 2000.0, []
    for i in range(n):
        o = px
        c = o + rnd.gauss(0, 1.2)
        h, lo = max(o, c) + abs(rnd.gauss(0, 0.6)), min(o, c) - abs(rnd.gauss(0, 0.6))
        out.append({"open_utc": start + tf_s * i, "o": round(o, 2), "h": round(h, 2), "l": round(lo, 2), "c": round(c, 2)})
        px = c
    return out


class _Data(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)


# ====================================================================================================================== cycle helper
class _Cycle(unittest.TestCase):
    mode = "SIGNALS"

    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        from masterquo.sh import config as C
        from masterquo.sh.service import SHService
        self.bridge = TS.Bridge(None, "HEDGING")
        self.svc = SHService(ConfigStore(), self.bridge, Database(), None, TS.Log(), TS.Modes(self.mode), clock=lambda: NOW)
        self.shc = C.load()
        self.spec = self.svc.spec(self.svc.account())
        self.ex = self.svc.executor(self.spec)
        self.opened = []

    def setups(self, side_s="BUY", st_s="READY", st_h="NO_TRADE"):
        s = TS.mk_setup(self.spec, "SCALPING", side_s, ref=2000.2, now=NOW)
        h = TS.mk_setup(self.spec, "HEDGING", "BUY", ref=2000.0, now=NOW)
        s["status"], h["status"] = st_s, st_h
        return {"SCALPING": s, "HEDGING": h}

    def cycle(self, setups, snap=None, risk="PASS", entry_block=None, mode=None):
        from masterquo.sh import service as S
        q = {"bid": 2000.0, "ask": 2000.2, "spread": 0.2, "age_s": 0.3, "time": NOW}
        bars = {tf: [] for tf in ("M1", "M5", "M15", "H1")}
        rk = {"status": risk, "checks": [], "warnings": [], "reasons": [], "volume": 0.1, "legs": [0.05, 0.03, 0.02]} if risk else None
        snap = snap or {"vol": {"atr_m5": 1.5}, "data": {"status": "OK", "issues": []}}

        def op(*a, **k):
            self.opened.append(a[1]["signal_id"])
            return {"status": "OPEN"}

        def ev(strat, *a, **k):                                                # as sh/setup.finish: the rows are copied, never read
            return dict(setups[strat], models=[{x: r.get(x) for x in ("id", "status", "group")} |
                                               {"use": (r.get(strat) or {}).get("use"), "role": (r.get(strat) or {}).get("role")}
                                               for r in (k.get("models") or [])])
        with mock.patch.object(S.CX, "snapshot", return_value=snap), \
             mock.patch.object(S.SU, "evaluate", side_effect=ev), \
             mock.patch.object(S.RK, "evaluate", side_effect=lambda **k: dict(rk) if rk else None), \
             mock.patch.object(self.svc, "open_plan", side_effect=op):
            return self.svc.cycle("XAUUSD", bars, q, self.spec, self.svc.account(), mode or self.mode, NOW, self.shc, self.ex,
                                  entry_block=entry_block)


def _decisive(evals):
    return {k: (v.get("status"), v.get("side"), (v.get("risk") or {}).get("status"), (v.get("coordination") or {}).get("decision"),
                v.get("entry_ref"), v.get("sl")) for k, v in evals.items()}


# ====================================================================================================================== I0004 / I0551
class TestCycleModelRows(_Cycle):
    def test_without_provider_rows_are_not_evaluated_not_false_states(self):
        evals = self.cycle(self.setups())
        rows = {r["id"]: r for r in evals["SCALPING"]["models"]}
        self.assertEqual(rows["legacy_ml"]["status"], "NOT_EVALUATED")         # before: UNAVAILABLE ('instrument inny niż aktywny')
        self.assertEqual(rows["agent"]["status"], "NOT_EVALUATED")             # before: SHADOW_ONLY 'agent: ?'
        self.assertEqual(rows["legacy_ml"]["use"], "NONE")
        self.assertTrue(all(r["use"] not in ("GATE", "EVIDENCE", "PROBABILITY") for r in rows.values() if r["status"] == "NOT_EVALUATED"))

    def test_data_quality_from_the_cycle_snapshot(self):
        evals = self.cycle(self.setups())
        dq = next(r for r in evals["SCALPING"]["models"] if r["id"] == "data_quality")
        self.assertEqual((dq["status"], dq["use"]), ("DETERMINISTIC_OK", "GATE"))   # before: DATA_MISSING / GATE_UNAVAILABLE
        bad = {"vol": {"atr_m5": 1.5}, "data": {"status": "BLOCK", "issues": ["M1: dane nieaktualne"]}}
        evals = self.cycle(self.setups(), snap=bad)
        dq = next(r for r in evals["SCALPING"]["models"] if r["id"] == "data_quality")
        self.assertEqual((dq["status"], dq["use"]), ("DATA_MISSING", "GATE_UNAVAILABLE"))

    def test_provider_rows_used_and_decisions_identical(self):
        from masterquo.sh import models as MR
        base = self.cycle(self.setups())
        rows = MR.matrix(None, "XAUUSD")["rows"]
        for r in rows:
            if r["id"] == "legacy_ml":
                r["status"] = "SHADOW_ONLY"
        self.svc.models_provider = lambda inst: rows
        self.svc.last_saved.clear()
        withp = self.cycle(self.setups())
        lm = next(r for r in withp["SCALPING"]["models"] if r["id"] == "legacy_ml")
        self.assertEqual(lm["status"], "SHADOW_ONLY")
        self.assertEqual(_decisive(base), _decisive(withp))

        def boom(inst):
            raise RuntimeError("probe hang")
        self.svc.models_provider = boom
        self.svc.last_saved.clear()
        err = self.cycle(self.setups())                                         # a failing provider never stops the cycle
        self.assertEqual(next(r for r in err["SCALPING"]["models"] if r["id"] == "legacy_ml")["status"], "NOT_EVALUATED")
        self.assertEqual(_decisive(base), _decisive(err))

    def test_payload_of_the_saved_signal_carries_the_rows(self):
        self.cycle(self.setups())
        row = self.svc.store.db.one("SELECT payload FROM sh_signals WHERE strategy='SCALPING'")
        st = {m["id"]: m["status"] for m in json.loads(row["payload"])["models"]}
        self.assertEqual(st["kronos"], "NOT_EVALUATED")                         # before: UNAVAILABLE in the signal history


class TestMatrixCache(unittest.TestCase):
    def test_cache_ttl_errors_and_first_call(self):
        from masterquo.sh import models as MR
        calls = []
        t = [100.0]

        def fake_matrix(rt, inst, **kw):
            calls.append(inst)
            return {"rows": [{"id": "x", "status": "READY", "n": len(calls)}]}
        c = MR.MatrixCache(object(), ttl=30.0, background=False, clock=lambda: t[0])
        with mock.patch.object(MR, "matrix", side_effect=fake_matrix):
            self.assertEqual(c("XAUUSD")[0]["n"], 1)
            t[0] += 10
            self.assertEqual(c("XAUUSD")[0]["n"], 1)                            # cached
            t[0] += 25
            self.assertEqual(c("XAUUSD")[0]["n"], 2)                            # refreshed after the TTL
        with mock.patch.object(MR, "matrix", side_effect=RuntimeError("x")):
            t[0] += 40
            rows = c("XAUUSD")
        self.assertTrue(all(r["status"] == "NOT_EVALUATED" for r in rows))     # error -> NOT_EVALUATED, never an exception

    def test_background_refresh_never_blocks_the_caller(self):
        import threading

        from masterquo.sh import models as MR
        gate = threading.Event()

        def slow(rt, inst, **kw):
            gate.wait(5)
            return {"rows": [{"id": "x", "status": "READY"}]}
        c = MR.MatrixCache(object(), ttl=30.0)
        with mock.patch.object(MR, "matrix", side_effect=slow):
            t0 = time.time()
            rows = c("XAUUSD")
            self.assertLess(time.time() - t0, 1.0)
            self.assertTrue(all(r["status"] == "NOT_EVALUATED" for r in rows))
            gate.set()
            for _ in range(50):
                if c("XAUUSD")[0].get("id") == "x":
                    break
                time.sleep(0.02)
            self.assertEqual(c("XAUUSD"), [{"id": "x", "status": "READY"}])

    def test_runtime_wires_the_provider(self):
        import inspect

        from masterquo import runtime
        src = inspect.getsource(runtime.Runtime.__init__)
        self.assertIn("models_provider", src)
        self.assertIn("news=self.news", src)


# ====================================================================================================================== I0359
class TestMMProbeChecksLoop(_Data):
    @staticmethod
    def _it(mid):
        from masterquo.sh import models as MR
        return next(i for i in MR.REGISTRY if i["id"] == mid)

    def test_without_mm_service_rows_are_not_ready(self):
        from masterquo.sh import models as MR
        self.assertNotEqual(MR.probe(self._it("mm_gpr"), None, "XAUUSD")["status"], "SHADOW_ONLY")        # before: SHADOW_ONLY
        self.assertNotEqual(MR.probe(self._it("mm_kalman"), None, "XAUUSD")["status"], "DETERMINISTIC_OK")  # before: DETERMINISTIC_OK

    def test_loop_state_drives_the_status(self):
        from masterquo.sh import models as MR
        ok = types.SimpleNamespace(mm=types.SimpleNamespace(loop={"runs": 1, "last_error": None},
                                                            _cache={"XAUUSD": {"value": {"status": "OK", "gpr": {"status": "OK"}}}}))
        self.assertEqual(MR.probe(self._it("mm_gpr"), ok, "XAUUSD")["status"], "SHADOW_ONLY")
        self.assertEqual(MR.probe(self._it("mm_kalman"), ok, "XAUUSD")["status"], "DETERMINISTIC_OK")
        err = types.SimpleNamespace(mm=types.SimpleNamespace(loop={"runs": 3, "last_error": "ValueError: x"}, _cache={}))
        self.assertEqual(MR.probe(self._it("mm_kalman"), err, "XAUUSD")["status"], "ERROR")
        empty = types.SimpleNamespace(mm=types.SimpleNamespace(loop={"runs": 0, "last_error": None}, _cache={}))
        self.assertEqual(MR.probe(self._it("mm_align_mean"), empty, "XAUUSD")["status"], "DATA_MISSING")
        g_bad = types.SimpleNamespace(mm=types.SimpleNamespace(loop={"runs": 1, "last_error": None},
                                                               _cache={"XAUUSD": {"value": {"status": "OK", "gpr": {"status": "NOT_CONVERGED"}}}}))
        self.assertEqual(MR.probe(self._it("mm_gpr"), g_bad, "XAUUSD")["status"], "DATA_MISSING")
        for st_rt in (None, ok, err, empty):                                    # OBSERVATION never becomes a gate / evidence
            for mid in ("mm_gpr", "mm_kalman", "mm_smc_fvg"):
                it = self._it(mid)
                p = MR.participation(it, MR.probe(it, st_rt, "XAUUSD"), "SCALPING")
                self.assertIn(p["use"], ("INFO", "NONE"))


# ====================================================================================================================== I0006
class TestTHGroupConsistency(_Data):
    def test_group_by_tf_from_routes(self):
        from masterquo.modelhub import aggregate as AG
        from masterquo.sh import models as MR
        mx = MR.matrix(None, "XAUUSD")
        th = next(r for r in mx["rows"] if r["id"] == "th_direction")
        self.assertEqual(th["group"], "TH_DIRECTION")                           # unchanged
        self.assertEqual(th.get("group_by_tf"), {"M1": "M1_DIRECTION", "M5": "M5_DIRECTION", "M15": "HTF_DIRECTION", "M30": "HTF_DIRECTION"})
        groups = {v["group"] for (task, _tf), v in AG.ROUTES.items() if task == "DIRECTION_H"}
        self.assertTrue(groups <= set(mx["correlation_groups"]))


# ====================================================================================================================== I0008
class TestPretrainedKind(_Data):
    def test_kind_and_categories(self):
        from masterquo.modelhub import catalog as CA
        from masterquo.quant import inventory as QI
        from masterquo.sh import models as MR
        from masterquo.training import panel as TP
        kinds = {i["id"]: i["kind"] for i in MR.REGISTRY}
        for mid in ("kronos", "chronos2", "granite_ttm", "tirex2"):
            self.assertEqual(kinds.get(mid), "PRETRAINED", mid)                # before: TRAINED
        rows = {r["id"]: r for r in TP.models(None, "XAUUSD")["models"]}
        self.assertFalse(rows["kronos"]["requires_training"])                  # before: True (panel Trening: 'wymaga treningu')
        self.assertFalse(rows["chronos2"]["requires_training"])
        self.assertTrue(rows["sh_tp_model"]["requires_training"])
        cat = {r["id"]: r for r in CA.build(None, "XAUUSD")["items"]}
        self.assertEqual(cat["kronos"]["category"], "PRETRAINED")              # before: TRAINABLE
        inv = {e["id"]: e for e in QI._sh_rows()}
        self.assertEqual(inv["kronos:Kronos-small"]["category"], "MODEL_PRETRAINED")
        self.assertEqual(inv["tsfm:chronos2"]["category"], "MODEL_PRETRAINED")
        self.assertEqual(inv["sh:tp_model"]["category"], "MODEL_TRAINED")

    def test_studio_measurement_family(self):
        from masterquo.studio import registry as SR
        t = next(x for x in SR.tasks() if x["model_id"] == "MICROSTRUCTURE")
        self.assertEqual(t["category"], "MEASUREMENT")                         # before: TRAINABLE
        self.assertEqual(SR.operations(t)[:3], ["FULL_EXPORT", "VALIDATE", "BUILD_DATASET"])   # operations unchanged


# ====================================================================================================================== I0206
class TestTirexInRegistries(_Data):
    def test_sh_matrix_catalog_and_inventory(self):
        from masterquo.modelhub import catalog as CA
        from masterquo.quant import inventory as QI
        from masterquo.sh import models as MR
        it = next((i for i in MR.REGISTRY if i["id"] == "tirex2"), None)
        self.assertIsNotNone(it)                                                # before: missing from the SH matrix
        self.assertEqual(it["group"], "TSFM_PRICE")
        self.assertEqual(it["roles"], {"SCALPING": "OBSERVATION", "HEDGING": "OBSERVATION"})
        cat = {r["id"]: r for r in CA.build(None, "XAUUSD")["items"]}
        self.assertIn(".venv_tirex2", cat["tirex2"]["location"])
        inv = QI.build(None, "XAUUSD")["entries"]
        self.assertEqual(sum(1 for e in inv if e["id"] == "tsfm:tirex2"), 1)    # one row per producer
        ts = types.SimpleNamespace(workers={"tirex2": types.SimpleNamespace(state={"status": "READY"})},
                                   settings=types.SimpleNamespace(get=lambda: types.SimpleNamespace(
                                       models={"tirex2": types.SimpleNamespace(use={"SCALPING": types.SimpleNamespace(use="ASSIST"),
                                                                                    "HEDGING": types.SimpleNamespace(use="OBSERVE")})})))
        st = MR.probe(it, types.SimpleNamespace(tsfm=ts), "XAUUSD")
        self.assertEqual(st["status"], "SHADOW_ONLY")
        self.assertEqual(MR.participation(it, st, "SCALPING")["use"], "HOLD_ONLY")


# ====================================================================================================================== I0312 / I0315
class TestShContextProfile(_Data):
    def _profile(self):
        from masterquo.lab.context_ind import task as CT
        (CT.root("XAUUSD") / "profile.json").write_text(json.dumps({"vamd": {"P": 20}, "fd": {"N": 40}, "source": "CALIBRATED_ON_DEV",
                                                                     "data_kind": "REAL"}), encoding="utf-8")

    def test_sh_values_stay_default_with_a_calibrated_profile(self):
        from masterquo.lab.context_ind import fractal as FD
        from masterquo.lab.context_ind import vamd as VM
        from masterquo.sh import context as CX
        self._profile()
        m5 = _bars()
        c = CX._ctx_m5(m5, 0.01)
        v = [x for x in VM.series(m5[-300:], VM.DEFAULT) if x.get("status") == "READY"]
        f = [x for x in FD.series(m5[-200:], FD.DEFAULT) if x.get("zone")]
        self.assertEqual(c["vamd_m5"], v[-1]["y"])
        self.assertEqual(c["fd_zone_m5"], f[-1]["zone"])

    def test_two_parametrisations_documented(self):
        from masterquo.quant import inventory as QI
        from masterquo.sh import models as MR
        for cid in ("rule:vamd", "rule:fractal"):
            notes = QI._OVR[cid].get("notes") or ""
            self.assertIn("DEFAULT", notes, cid)                               # before: no note
            self.assertIn("skalibrowany", notes, cid)
        names = {i["id"]: i["name"] for i in MR.REGISTRY}
        self.assertIn("DEFAULT", names["vamd"])
        self.assertIn("DEFAULT", names["fractal"])

    def test_panel_shows_the_values_sh_uses(self):
        from masterquo.lab.context_ind.service import ContextSections
        from masterquo.sh import context as CX
        self._profile()
        m5 = _bars()
        cs = ContextSections()
        s = cs.summary(cs.update("XAUUSD", "M5", m5, 0.01, ledger=False), tf="M5")
        sh = s.get("sh")
        self.assertIsNotNone(sh)                                                # before: the panel had only the calibrated profile
        self.assertEqual(sh["profile"], "DEFAULT")
        self.assertIn("SH używa profilu DEFAULT", sh["label"])
        self.assertTrue(sh["differs"])
        ref = CX._ctx_m5(m5, 0.01)
        for k in ("vamd_m5", "fd_zone_m5", "smc_trend_m5", "pb_last_low_m5", "pb_last_high_m5"):
            self.assertEqual(sh["values"][k], ref[k], k)
        m1 = _bars(400, 60, seed=3)
        s1 = cs.summary(cs.update("XAUUSD", "M1", m1, 0.01, ledger=False), tf="M1")
        ref1 = CX._ctx_m1(m1, 0.01)
        self.assertEqual(s1["sh"]["values"]["vamd_m1"], ref1["vamd_m1"])
        self.assertEqual(s1["sh"]["values"]["smc_trend_m1"], ref1["smc_trend_m1"])


# ====================================================================================================================== I0408
class _Fam:
    def __init__(self, st, ok=(True, None), store=True):
        self.st = st
        if store:
            self.store = types.SimpleNamespace(assist_ok=(ok if callable(ok) else (lambda f, i, r: ok)))

    def status(self, fid, inst):
        return dict(self.st)

    def _artifact(self, fid, inst, rid):
        return {"omega": 0.01, "alpha": 0.05, "beta": 0.9, "dist": "t"}


class TestGarchArtifactGate(unittest.TestCase):
    def svc(self, fam):
        from masterquo.sh.service import SHService
        s = SHService.__new__(SHService)
        s.families = fam
        return s

    def test_only_real_approved_and_not_off(self):
        ap = {"artifact": "APPROVED", "active_run": "R1", "use": "SHADOW"}
        self.assertEqual(self.svc(_Fam(ap)).garch_artifact("XAUUSD")["status"], "READY")
        syn = self.svc(_Fam(ap, ok=(False, "artefakt na danych SYNTHETIC_TEST (nie REAL)")))
        self.assertNotEqual(syn.garch_artifact("XAUUSD")["status"], "READY")    # before: READY
        off = self.svc(_Fam(dict(ap, use="OFF")))
        self.assertEqual(off.garch_artifact("XAUUSD")["status"], "OFF")         # before: READY
        self.assertNotEqual(self.svc(_Fam(ap, store=False)).garch_artifact("XAUUSD")["status"], "READY")   # fail-closed

        def boom(f, i, r):
            raise OSError("manifest")
        self.assertNotEqual(self.svc(_Fam(ap, ok=boom)).garch_artifact("XAUUSD")["status"], "READY")
        self.assertEqual(self.svc(_Fam(dict(ap, artifact="CANDIDATE"))).garch_artifact("XAUUSD")["status"], "CANDIDATE")


# ====================================================================================================================== I0557
class _Risk:
    def __init__(self, block=True, required=False):
        self.macro_block_high_impact, self.macro_calendar_required = block, required


class TestMacroCodes(unittest.TestCase):
    @staticmethod
    def _ref(macro, risk_cfg):                                                  # engine/decision.py MARKET node before the change
        unmet, codes = [], []
        if risk_cfg.macro_block_high_impact:
            if macro.get("status") not in ("OK", "PARTIAL"):
                if risk_cfg.macro_calendar_required:
                    unmet.append("MACRO_CALENDAR_AVAILABLE")
                codes.append("MACRO_CALENDAR_" + str(macro.get("status")))
            elif macro.get("risk_level") == "HIGH":
                unmet.append("NO_HIGH_IMPACT_EVENT_WINDOW")
                codes.append("MACRO_EVENT_WINDOW")
        return unmet, codes

    def test_grid_parity_and_blocking_codes(self):
        from masterquo.engine import decision as D
        for st in ("OK", "PARTIAL", "DISABLED", "NOT_LOADED", "UNAVAILABLE", "STALE", None):
            for lvl in ("HIGH", "LOW", "UNKNOWN"):
                for b in (True, False):
                    for req in (True, False):
                        m, rc = {"status": st, "risk_level": lvl}, _Risk(b, req)
                        self.assertEqual(D.macro_market(m, rc), self._ref(m, rc))
                        codes = D.macro_block_codes(m, rc)
                        exp = []
                        if b and st in ("OK", "PARTIAL") and lvl == "HIGH":
                            exp = ["MACRO_EVENT_WINDOW"]
                        elif b and req and st not in ("OK", "PARTIAL"):
                            exp = [f"MACRO_CALENDAR_{st}"]
                        self.assertEqual(codes, exp, (st, lvl, b, req))


class _News:
    def __init__(self, level="HIGH", status="PARTIAL", exc=None):
        self.level, self.status, self.exc = level, status, exc

    def macro(self):
        if self.exc:
            raise self.exc
        return {"status": self.status, "risk_level": self.level, "events": []}


class TestShNewsGate(TS.Base):
    def bars_one(self):
        b = [{"open_utc": NOW - 120, "o": 2000.0, "h": 2000.5, "l": 1999.5, "c": 2000.1}]
        self.bridge.bars = lambda tf, n, include_forming=False: b if tf == "M1" else []

    def run_tick(self, news):
        self.svc.news = news
        self.bars_one()
        seen = []
        with mock.patch.object(self.svc, "cycle", side_effect=lambda *a, **k: seen.append(list(k.get("entry_block") or []))):
            self.svc._tick()
        return seen[0]

    def test_high_impact_window_blocks_new_entries(self):
        self.assertEqual(self.run_tick(None), [])                               # no news service (tests, replay) -> as today
        self.svc.last_bar_key = None
        self.assertEqual(self.run_tick(_News("LOW")), [])
        self.svc.last_bar_key = None
        self.assertEqual(self.run_tick(_News("HIGH")), ["MACRO_EVENT_WINDOW"])  # before: [] (SH never read the calendar)
        self.svc.last_bar_key = None
        self.assertEqual(self.run_tick(_News(exc=RuntimeError("x"))), ["MACRO_GATE_ERROR:RuntimeError"])   # fail-closed
        self.assertEqual(self.svc.gate()["entry_block"], [])                    # the gate of hedges / exits is unchanged

    def test_existing_blocks_are_kept(self):
        self.svc.modes = types.SimpleNamespace(gate=lambda key, **kw: {"mode": "PAPER", "reason_codes": ["STOP_ACTIVE"]})
        self.assertEqual(self.run_tick(_News("HIGH")), ["STOP_ACTIVE", "MACRO_EVENT_WINDOW"])


class TestShNewsGateCycle(_Cycle):
    mode = "PAPER"

    def test_block_means_no_plan(self):
        evals = self.cycle(self.setups(), entry_block=["MACRO_EVENT_WINDOW"])
        self.assertEqual(self.opened, [])
        self.assertIn("MACRO_EVENT_WINDOW", evals["SCALPING"]["entry_block"])
        self.cycle(self.setups(side_s="SELL"))
        self.assertEqual(len(self.opened), 1)                                   # without the block: as today

    def test_news_probe_shows_the_risk_level(self):
        from masterquo.sh import models as MR
        it = next(i for i in MR.REGISTRY if i["id"] == "news")
        st = MR.probe(it, None, "XAUUSD", news=_News("HIGH"))
        self.assertEqual(st["status"], "DETERMINISTIC_OK")
        self.assertIn("HIGH", st["reason"])                                    # before: 'kalendarz ?' (no risk level)
        self.svc.news = _News("HIGH")
        evals = self.cycle(self.setups(), entry_block=["MACRO_EVENT_WINDOW"])
        nw = next(r for r in evals["SCALPING"]["models"] if r["id"] == "news")
        self.assertEqual((nw["status"], nw["use"]), ("DETERMINISTIC_OK", "GATE"))


# ====================================================================================================================== I0095
class TestOptionalDepsHaveDefaults(unittest.TestCase):
    def test_class_defaults(self):
        from masterquo.engine.service import EngineService
        from masterquo.execution.manager import PositionManager
        from masterquo.kronos.service import KronosService
        from masterquo.modelhub.families.service import FamilyService
        from masterquo.sh.service import SHService
        from masterquo.tsfm.service import TsfmService
        need = {SHService: ("arc", "baskets", "tsfm", "families", "kronos", "indicators", "predictions_provider", "pack", "news",
                            "models_provider"),
                EngineService: ("si", "liquidity", "indicators_provider", "svp_provider", "extind", "mm_provider"),
                PositionManager: ("arc",), KronosService: ("governor",), TsfmService: ("governor",), FamilyService: ("event_gru_provider",)}
        for cls, attrs in need.items():
            for a in attrs:
                self.assertTrue(hasattr(cls, a), f"{cls.__name__}.{a}")
                self.assertIsNone(getattr(cls, a), f"{cls.__name__}.{a}")


# ====================================================================================================================== I0111
class TestUnknownActionsVisible(TS.Base):
    mode = "AUTO_DEMO"

    def test_unknown_close_is_reported(self):
        self.open(volume=0.3)
        row = self.row()
        aid = f"{row['plan_id']}:CLOSE_RUNNER:MANUAL"
        self.svc.store.claim_action({"action_id": aid, "plan_id": row["plan_id"], "kind": "CLOSE_RUNNER", "volume": 0.3}, NOW)
        self.svc.store.finish_action(aid, "UNKNOWN", {"status": "UNKNOWN", "reason": "timeout"}, NOW)
        self.svc._tick()
        ua = self.svc.public().get("unknown_actions")
        self.assertIsNotNone(ua)                                                # before: no key (nothing reads unknown_actions())
        self.assertIn(aid, [a["action_id"] for a in ua])
        a = next(x for x in ua if x["action_id"] == aid)
        self.assertEqual((a["kind"], a["status"], a["plan_id"]), ("CLOSE_RUNNER", "UNKNOWN", row["plan_id"]))
        st = self.svc.store.db.one("SELECT status FROM sh_actions WHERE action_id=?", (aid,))["status"]
        self.assertEqual(st, "UNKNOWN")                                         # read only: never resolved / resent


# ====================================================================================================================== I0745
class TestUnknownEntryAdoptedWithoutReconnect(TS.Base):
    mode = "AUTO_DEMO"

    def _unknown(self, strategy="SCALPING", volume=0.1, with_position=True, account=None):
        self.fake.hang_order_send = True
        self.open(strategy, volume=volume)
        self.fake.hang_order_send = False
        row = self.row()
        self.assertEqual(row["state"], "ENTRY_UNKNOWN")
        if account:
            self.svc.store.db.execute("UPDATE sh_plans SET account_key=? WHERE plan_id=?", (account, row["plan_id"]))
        if with_position:
            ex = self.ex

            def go(m):
                t = m.symbol_info_tick(self.spec.symbol)
                return m.order_send({"action": m.TRADE_ACTION_DEAL, "symbol": self.spec.symbol, "volume": volume, "type": m.ORDER_TYPE_BUY,
                                     "price": t.ask, "sl": float(row["plan"]["setup"]["sl"]), "tp": 0.0, "deviation": 10,
                                     "magic": self.shc["magic_number"], "comment": ex.comment(row["plan_id"], "P"), "type_time": m.ORDER_TIME_GTC,
                                     "type_filling": 1})
            self.svc.terminal()(go)
        self.svc.recovered_epoch = self.bridge.session_epoch                   # no reconnect
        return row

    def test_adopted_on_tick_without_epoch_change(self):
        row = self._unknown()
        self.t += 20
        self.svc._tick()
        r = self.row()
        self.assertEqual(r["state"], "OPEN")                                    # before: ENTRY_UNKNOWN until a reconnect
        self.assertTrue(r["primary_ticket"])
        self.assertIn("ADOPTED", [e["kind"] for e in self.svc.store.events(row["plan_id"])])

    def test_without_position_stays_unknown(self):
        self._unknown(with_position=False)
        for _ in range(3):
            self.t += 20
            self.svc._tick()
        self.assertEqual(self.row()["state"], "ENTRY_UNKNOWN")                 # never REJECTED outside a reconnect (symbol stays blocked)

    def test_other_account_not_adopted(self):
        self._unknown(account="Other:1")
        self.t += 20
        self.svc._tick()
        self.assertEqual(self.row()["state"], "ENTRY_UNKNOWN")

    def test_owned_by_another_plan_not_adopted(self):
        row = self._unknown()
        tk = self.svc.executor(self.spec).terminal_positions(self.spec.symbol)[-1]["ticket"]
        self.svc.store.own(self.bridge.account_key, tk, "PL-OTHER", "OPEN_P", NOW)
        self.t += 20
        self.svc._tick()
        self.assertEqual(self.row()["state"], "ENTRY_UNKNOWN")
        self.assertIn("ADOPT_REFUSED", [e["kind"] for e in self.svc.store.events(row["plan_id"])])

    def test_adopted_basket_opens_no_hedge_leg(self):
        row = self._unknown("HEDGING", volume=0.4)
        self.t += 20
        self.svc._tick()
        r = self.row()
        b = r["fsm_obj"]
        self.assertEqual(b.activations, b.cfg.max_activations)
        self.assertIn("HEDGE_DISABLED_ADOPTED", [e["kind"] for e in self.svc.store.events(row["plan_id"])])
        self.step(b.primary.entry - 1.8, dt=5)                                  # beyond the hedge trigger
        self.assertFalse(any(a["kind"] == "OPEN_H" for a in self.svc.store.actions(row["plan_id"])))

    def test_bind_error_keeps_plan_unknown(self):
        with mock.patch.object(self.svc, "bind_fill", side_effect=RuntimeError("bind")):
            r, _su = self.open(volume=0.1)
        self.assertEqual(r["status"], "UNKNOWN")
        row = self.row()
        self.assertEqual(row["state"], "ENTRY_UNKNOWN")                         # before: the exception left PENDING_ENTRY and broke the cycle
        self.assertIn("BIND_ERROR", [e["kind"] for e in self.svc.store.events(row["plan_id"])])


# ====================================================================================================================== I0746
class TestDailyLossBrokerDay(_Cycle):
    mode = "AUTO_DEMO"

    def _closed(self, closed_at, net, mode="AUTO_DEMO", account=None):
        pid = f"PL-{closed_at}-{mode}"
        self.svc.store.db.execute(
            "INSERT INTO sh_plans(plan_id, signal_id, strategy, instrument, symbol, side, exec_mode, account_key, state, config_hash, plan, created_at, "
            "updated_at, closed_at, result) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, "SG" + pid, "SCALPING", "XAUUSD", self.spec.symbol, "BUY", mode, account or self.bridge.account_key, "CLOSED", "h", "{}",
             closed_at - 60, closed_at, closed_at, json.dumps({"net_money": net})))

    def test_broker_day_loss_counts(self):
        now = datetime(2026, 11, 24, 0, 30, tzinfo=UTC).timestamp()
        self._closed(now - 90 * 60, -500.0)                                     # 23:00 UTC yesterday = 01:00 of the broker day (+2 h)
        self.bridge.server_day_start_utc = lambda: datetime(2026, 11, 23, 22, 0, tzinfo=UTC)
        st = self.svc.risk_state(self.spec.symbol, "SCALPING", now, 0, mode="AUTO_DEMO")
        self.assertEqual(st["daily_realized_money"], -500.0)                    # before: 0.0 (day from UTC midnight)
        from masterquo.sh import risk as RK
        su = TS.mk_setup(self.spec, now=now)
        prof = __import__("masterquo.sh.config", fromlist=["C"]).profile(self.shc, "XAUUSD", "SCALPING")
        r = RK.evaluate(setup=su, spec=self.spec, prof=prof, cfg=self.shc, inst="XAUUSD", account=self.svc.account(), state=st,
                        exec_mode="AUTO_DEMO", now=now, quote={"spread": 0.2, "age_s": 0.3})
        self.assertFalse(next(c for c in r["checks"] if c["id"] == "daily_loss")["ok"])

    def test_never_milder_than_today(self):
        now = datetime(2026, 11, 24, 3, 0, tzinfo=UTC).timestamp()
        self._closed(now - 2 * 3600, -500.0, mode="PAPER")                     # 01:00 UTC, another mode
        self._closed(now - 2.5 * 3600, -300.0)                                  # 00:30 UTC, this mode
        self.bridge.server_day_start_utc = lambda: datetime(2026, 11, 24, 5, 0, tzinfo=UTC) - timedelta(days=1)   # offset -5 h
        st = self.svc.risk_state(self.spec.symbol, "SCALPING", now, 0, mode="AUTO_DEMO")
        self.assertLessEqual(st["daily_realized_money"], -800.0)                # m1 (all modes since UTC midnight) is kept
        self.bridge.server_day_start_utc = lambda: None                         # offset unknown -> as today
        st = self.svc.risk_state(self.spec.symbol, "SCALPING", now, 0, mode="AUTO_DEMO")
        self.assertEqual(st["daily_realized_money"], -800.0)

        def boom():
            raise RuntimeError("clock")
        self.bridge.server_day_start_utc = boom
        self.assertEqual(self.svc.risk_state(self.spec.symbol, "SCALPING", now, 0, mode="AUTO_DEMO")["daily_realized_money"], -800.0)


# ====================================================================================================================== I0747
class TestForeignPositionsUnavailable(_Cycle):
    mode = "AUTO_DEMO"

    def test_none_and_error_are_unavailable(self):
        self.svc._terminal = lambda fn: fn(types.SimpleNamespace(positions_get=lambda symbol: None))
        self.assertIsNone(self.svc.foreign_positions("XAUUSD-", 1))             # before: 0
        self.svc._terminal = lambda fn: (_ for _ in ()).throw(RuntimeError("busy"))
        self.assertIsNone(self.svc.foreign_positions("XAUUSD-", 1))

    def test_cycle_waits_without_position_data(self):
        self.svc._terminal = lambda fn: fn(types.SimpleNamespace(positions_get=lambda symbol: None))
        evals = self.cycle(self.setups())
        cd = evals["SCALPING"]["coordination"]
        self.assertEqual(cd["decision"], "WAIT")                                # before: PROCEED (treated as 0 foreign positions)
        self.assertIn("brak danych o pozycjach", cd["reason"])
        self.assertEqual(self.opened, [])

    def test_risk_check_fails_on_marker(self):
        from masterquo.sh import config as C
        from masterquo.sh import risk as RK
        su = TS.mk_setup(self.spec, now=NOW)
        st = {"open_plans": [], "daily_realized_money": 0.0, "last_close_at": {}, "recent_signals": [], "foreign_positions": "UNAVAILABLE"}
        r = RK.evaluate(setup=su, spec=self.spec, prof=C.profile(self.shc, "XAUUSD", "SCALPING"), cfg=self.shc, inst="XAUUSD",
                        account=self.svc.account(), state=st, exec_mode="AUTO_DEMO", now=NOW, quote={"spread": 0.2, "age_s": 0.3})
        c = next(x for x in r["checks"] if x["id"] == "foreign_owner")
        self.assertFalse(c["ok"])
        self.assertIn("brak danych o pozycjach", c["detail"])

    def test_paper_unchanged(self):
        self.svc._terminal = lambda fn: fn(types.SimpleNamespace(positions_get=lambda symbol: None))
        evals = self.cycle(self.setups(), mode="PAPER")
        self.assertEqual(evals["SCALPING"]["coordination"]["decision"], "PROCEED")


# ====================================================================================================================== I0748
class TestOtherSymbolPlansReported(TS.Base):
    def test_status_lists_plans_of_another_symbol(self):
        self.open(volume=0.3)
        self.svc.store.db.execute("UPDATE sh_plans SET symbol='BTCUSD-'")
        self.svc._tick()
        un = self.svc.public().get("unmanaged_plans")
        self.assertTrue(un)                                                     # before: invisible (manage covers only the active symbol)
        self.assertEqual(un[0]["symbol"], "BTCUSD-")
        self.assertEqual(self.row()["state"], "OPEN")                           # management unchanged (no action on another symbol)

    def test_open_plans_warning_helper(self):
        from masterquo.sh.service import SHService
        self.open(volume=0.3)
        w = SHService.open_plans_warning(self.svc.store, "BTCUSD-")
        self.assertTrue(w and w["plans"][0]["symbol"] == "XAUUSD-")
        self.assertIsNone(SHService.open_plans_warning(self.svc.store, "XAUUSD-"))


# ====================================================================================================================== I0817
class TestValidationBoundToConfigHash(_Data):
    def test_hash_mismatch_is_not_validated(self):
        from masterquo import paths
        from masterquo.sh.pack import catalog as CAT
        d = paths.data_dir() / "sh" / "pack_validation"
        d.mkdir(parents=True, exist_ok=True)
        (d / "PMW_SC01.json").write_text(json.dumps({"verdict": "VALIDATED", "data_kind": "REAL_USER_DATA", "config_hash": "aaa",
                                                     "report_id": "PKR-1"}), encoding="utf-8")
        self.assertEqual(CAT.validation_status("PMW_SC01")["status"], "VALIDATED")                   # without a hash: as today
        self.assertEqual(CAT.validation_status("PMW_SC01", config_hash="aaa")["status"], "VALIDATED")
        v = CAT.validation_status("PMW_SC01", config_hash="bbb")
        self.assertEqual(v["status"], "NOT_VALIDATED")                                                # before: VALIDATED
        (d / "PMW_SC02.json").write_text(json.dumps({"verdict": "VALIDATED", "data_kind": "REAL_USER_DATA"}), encoding="utf-8")
        self.assertEqual(CAT.validation_status("PMW_SC02", config_hash="bbb")["status"], "NOT_VALIDATED")
        cfg = CAT.load()
        pub = {i["strategy_id"]: i for i in CAT.public(cfg)["items"]}
        self.assertEqual(pub["PMW_SC01"]["validation"]["status"], "NOT_VALIDATED")                  # catalog compares the current hash
        from masterquo.sh.service import SHService
        su = {"strategy_id": "PMW_SC01", "pack": {"config_hash": "bbb"}}
        self.assertFalse(SHService.pack_live_validation(su)["ok"])
        su = {"strategy_id": "PMW_SC01", "pack": {"config_hash": "aaa"}}
        self.assertTrue(SHService.pack_live_validation(su)["ok"])


# ====================================================================================================================== I0818
class TestPackOverrideValidation(_Data):
    def test_invalid_values_rejected_before_save(self):
        from masterquo.sh.pack import catalog as CAT
        p = CAT._override_path()
        for bad in ({"variants": {"PMW_SC01": {"position_max_minutes": -5}}},
                    {"families": {"SCALPING": {"rr_min": "x"}}},
                    {"variants": {"PMW_SC01": {"signal_tfs": "M5"}}},
                    {"variants": {"PMW_SC01": {"params": [1]}}},
                    {"variants": {"PMW_SC01": {"enabled": "tak"}}},
                    {"common": {"b_tick_mult": float("nan")}}):
            with self.assertRaises(ValueError, msg=str(bad)):                   # before: saved, or TypeError (500)
                CAT.save_override(bad)
            self.assertFalse(p.exists(), bad)
        CAT.save_override({"variants": {"PMW_SC01": {"position_max_minutes": 45}}})                 # a valid change still saves
        self.assertEqual(CAT.load()["variants"]["PMW_SC01"]["position_max_minutes"], 45.0)

    def test_api_maps_type_errors_to_400(self):
        import inspect

        # Etap 4 krok B: the SH route block moved from api/app.py to api/routes/sh.py
        from masterquo.api.routes import sh as A
        src = inspect.getsource(A)
        i = src.index("def sh_strategies_config")
        self.assertIn("TypeError", src[i:i + 700])


# ====================================================================================================================== I0824
class TestTpModelErrorDoesNotAbortCycle(_Cycle):
    mode = "PAPER"

    def test_error_bar_without_entries_cycle_completes(self):
        from masterquo.sh import service as S
        heard = []
        self.svc.listeners.append(lambda evals, **k: heard.append({k2: v["status"] for k2, v in evals.items()}))
        with mock.patch.object(S.TM, "status", side_effect=ValueError("registry.json uszkodzony")):
            evals = self.cycle(self.setups())                                   # before: ValueError out of cycle (bar lost)
        self.assertEqual(evals["SCALPING"]["status"], "WAIT")
        self.assertIn("model zdarzenia SH", evals["SCALPING"]["status_reason"])
        self.assertEqual(evals["SCALPING"]["probability"]["status"], "ERROR")
        self.assertFalse(any(v["status"] == "READY" for v in evals.values()))  # no READY anywhere in the error bar (as today: no entry)
        self.assertEqual(self.opened, [])
        self.assertEqual(len(heard), 1)
        self.svc.last_saved.clear()
        with mock.patch.object(S.TM, "status", return_value={"status": "NOT_TRAINED"}):
            self.cycle(self.setups(side_s="SELL"))
        self.assertEqual(len(self.opened), 1)                                   # a working model: unchanged

    def test_other_ready_candidates_held_in_the_error_bar(self):
        from masterquo.sh import service as S
        su = self.setups(st_h="READY")
        su["HEDGING"]["side"] = "BUY"
        with mock.patch.object(S.TM, "status", side_effect=lambda inst, strat: (_ for _ in ()).throw(ValueError("x")) if strat == "SCALPING"
                               else {"status": "NOT_TRAINED"}):
            evals = self.cycle(su)
        self.assertNotEqual(evals["HEDGING"]["status"], "READY")
        self.assertEqual(self.opened, [])


# ====================================================================================================================== I0825
class TestDuplicateWindowAfterExpire(_Cycle):
    def test_expired_signal_with_plan_still_counts(self):
        su = TS.mk_setup(self.spec, now=NOW - 15 * 60)
        su["valid_until"] = NOW - 5 * 60
        self.svc.store.save_signal(su, now=NOW - 15 * 60)
        self.svc.store.db.execute("INSERT INTO sh_plans(plan_id, signal_id, strategy, instrument, symbol, side, exec_mode, state, config_hash, plan, "
                                  "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                                  ("PL-1", su["signal_id"], "SCALPING", "XAUUSD", self.spec.symbol, "BUY", "PAPER", "CLOSED", "h", "{}",
                                   NOW - 15 * 60, NOW - 15 * 60))
        self.svc.store.expire_signals(NOW)
        st = self.svc.risk_state(self.spec.symbol, "SCALPING", NOW, 0)
        self.assertIn(su["signal_id"], [s["signal_id"] for s in st["recent_signals"]])                # before: [] (READY filter)
        from masterquo.sh import config as C
        from masterquo.sh import risk as RK
        new = TS.mk_setup(self.spec, ref=2001.0, now=NOW)
        r = RK.evaluate(setup=new, spec=self.spec, prof=C.profile(self.shc, "XAUUSD", "SCALPING"), cfg=self.shc, inst="XAUUSD",
                        account=self.svc.account(), state=st, exec_mode="PAPER", now=NOW, quote={"spread": 0.2, "age_s": 0.3})
        self.assertFalse(next(c for c in r["checks"] if c["id"] == "duplicate")["ok"])

    def test_signal_without_plan_does_not_count(self):
        su = TS.mk_setup(self.spec, now=NOW - 15 * 60)
        self.svc.store.save_signal(su, now=NOW - 15 * 60)
        self.assertEqual(self.svc.risk_state(self.spec.symbol, "SCALPING", NOW, 0)["recent_signals"], [])


# ====================================================================================================================== I0826
class TestLegacyHedgeRespectsStop(TS.Base):
    def test_stop_blocks_new_leg_not_exits(self):
        self.open("HEDGING", volume=0.4)
        row = self.row()
        b = row["fsm_obj"]
        self.svc.modes = types.SimpleNamespace(gate=lambda key, **kw: {"mode": "PAPER", "reason_codes": ["STOP_ACTIVE"]})
        q = self.q(b.primary.entry - 1.8)
        acts = self.svc.hedge_step(row, b, self.spec, q, self.t, True)
        self.assertFalse(any(a["kind"] == "OPEN_HEDGE" for a in acts))          # before: OPEN_HEDGE despite STOP
        self.assertEqual(b.activations, 0)                                      # no activation used up, no REDUCE
        self.assertFalse(any(a["kind"] == "CLOSE_PRIMARY_PART" for a in acts))
        self.svc.modes = TS.Modes("PAPER")
        acts = self.svc.hedge_step(row, b, self.spec, q, self.t, True)
        self.assertTrue(any(a["kind"] == "OPEN_HEDGE" for a in acts))           # without STOP: as today

    def test_exit_still_allowed_under_stop(self):
        self.open("HEDGING", volume=0.4)
        row = self.row()
        b = row["fsm_obj"]
        self.svc.modes = types.SimpleNamespace(gate=lambda key, **kw: {"mode": "PAPER", "reason_codes": ["STOP_ACTIVE"]})
        acts = self.svc.hedge_step(row, b, self.spec, self.q(b.primary.entry - 1.8), self.t, False)    # structure invalid -> EXIT
        self.assertTrue(any(a["kind"] in ("CLOSE_PRIMARY", "CLOSE_RUNNER") for a in acts))


# ====================================================================================================================== I0862
class TestBasketNetRR(unittest.TestCase):
    def test_net_rr_and_unchanged_order(self):
        from masterquo.sh.coordinator import arbitrate
        from masterquo.sh.pack import solver as SV
        from masterquo.sh.service import SHService
        spec = types.SimpleNamespace(symbol="EURUSD")
        sg = {"signal_id": "B1", "basket_id": "FX_SMC", "strategy_id": "FX_SMC_01", "tf": "M5", "created_at": NOW, "valid_until": NOW + 600,
              "plan": {"side": "LONG", "entry_ref": 100.0, "sl": 99.0, "targets": [{"price": 101.0}, {"price": 102.0}], "timeout_bars": 8}}
        su = SHService.basket_su(sg, "EURUSD", spec, {"bid": 99.95, "ask": 100.0, "spread": 0.3}, NOW)
        self.assertEqual(su["net_rr"], round(SV.rr_plan_net(1.0, 2.0, 1.0, 0.3, 0.3, 0.5, 0.5), 3))   # before: 1.0 (gross TP1)
        self.assertLess(su["net_rr"], 1.0)
        self.assertEqual(su["gross_rr_tp1"], 1.0)
        self.assertEqual(su["rank_rr"], 1.0)
        # order of two basket candidates: by the former value (rank_rr) - the coordinator picks the same plan as before
        a = dict(su, signal_id="A", strategy_id="X1", net_rr=0.2, rank_rr=2.0, pack={"cluster": "FX_SMC"})
        b = dict(su, signal_id="B", strategy_id="X0", net_rr=0.9, rank_rr=1.0, pack={"cluster": "FX_SMC"})
        out = arbitrate([b, a], open_plans=[], foreign_positions=0, cfg={}, symbol="EURUSD")
        self.assertEqual(next(o for o in out if o["decision"] == "PROCEED")["signal_id"], "A")
        c = dict(b, signal_id="C")
        c.pop("rank_rr")
        out = arbitrate([c, dict(a, signal_id="D", rank_rr=None, net_rr=0.2)], open_plans=[], foreign_positions=0, cfg={}, symbol="EURUSD")
        self.assertEqual(next(o for o in out if o["decision"] == "PROCEED")["signal_id"], "C")         # without rank_rr: net_rr as today


if __name__ == "__main__":
    unittest.main()
