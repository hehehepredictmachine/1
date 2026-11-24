"""1.46 arch, fala 2 – grupa families_impl. Każdy test nie przechodzi na kodzie sprzed poprawki (bazie 2dce8bf).

* I0215 (+I0218): inferencja SEQ_LSTM / SEQ_GRU / RL_PPO startowała NOWY proces .venv_deep (import torch) przy każdej świecy, synchronicznie
  w cyklu SH / koordynatora. Teraz trwały proces workera (--serve, linie JSON) z tym samym timeoutem i mapowaniem błędów; trening dalej
  w osobnych procesach.
* I0223 (+I0224) / I0471: NAME rodziny NLP_SENTIMENT obiecywał „opcjonalny lokalny transformer”, którego nikt nie woła (op nlp_predict bez
  wywołującego, nlp_transformer_path tylko przekazywany). Tylko teksty; klucz config zostaje.
* I0396: ARIMA / SARIMAX bez pola direction – w roli REQUIRED koordynator dawał PASS niezależnie od kierunku prognozy (wyłącznie zaostrzenie).
* I0400 (+I0406/I0410/I0413/I0419/I0425/I0429) / I0468: RECEIVERS deklarowały odbiorców bez czytelnika w kodzie (AGENT / RISK / STRATEGY /
  PORTFOLIO) – przeniesione do PLANNED_RECEIVERS (capabilities['planned_receivers']).
* I0409: GARCH na żywo dostaje ~760 świec zamiast okna 2000 – wynik mówi teraz, ile zwrotów użyto i jaki jest ślad startu filtra.
* I0422 (+I0427): aktywacja PAIR_COINT / STATARB nie sprawdzała próbki inferencji (brak wejść w próbce).
* I0424: uszkodzona / brakująca noga pary -> wyjątek poza try (proces bez wyniku) albo mało konkretny powód; teraz BLOCKED z nazwą nogi.
* I0446: TH_XGB deklarował puste DEPS, a wymaga xgboost.
* I0465: deep_runtime/rl.predict ustawiał core.pos bez ceny wejścia i świec w pozycji (obserwacja spoza rozkładu treningu).
* I0470: data_kind artefaktu NLP brany z manifestu ŚWIEC, nie z pochodzenia korpusu.
* I0475: trening SEQ_GRU_EVENT przez CLI / API kończył się FAILED NotImplementedError zamiast DELEGATED.
"""
from __future__ import annotations

import itertools
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from contextlib import nullcontext
from pathlib import Path
from typing import ClassVar
from unittest import mock

import numpy as np

import _env

T0 = 1_772_409_600  # 2026-03-02 00:00 UTC
BACKEND = _env.ROOT / "backend"


def _bars(n, tf_s=300, seed=3, start=2000.0, sd=1e-3):
    rng = np.random.default_rng(seed)
    c, out = start, []
    for i in range(n):
        o = c
        c = c * math.exp(rng.normal(0, sd))
        out.append({"t": T0 + i * tf_s, "o": o, "h": max(o, c) * 1.0002, "l": min(o, c) * 0.9998, "c": c, "tv": 50, "spread": 20})
    return out


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.tdata = _env.TempData()
        self.addCleanup(self.tdata.close)
        self.td = tempfile.mkdtemp(prefix="fam_w2_")
        self.addCleanup(shutil.rmtree, self.td, True)
        prev = os.environ.get("PMW_FAMILIES_DIR")
        os.environ["PMW_FAMILIES_DIR"] = self.td
        self.addCleanup(lambda: os.environ.pop("PMW_FAMILIES_DIR", None) if prev is None else os.environ.__setitem__("PMW_FAMILIES_DIR", prev))
        from masterquo.modelhub.families import base as B
        self.B = B
        self.store = B.Store(Path(self.td))

    def svc(self):
        from masterquo.config import ConfigStore
        from masterquo.modelhub.families.service import FamilyService
        return FamilyService(ConfigStore(), None, store=self.store)


# ===================================================================================================================== I0396
class TestArimaDirection(unittest.TestCase):
    """ARIMA / SARIMAX predict carries direction UP / DOWN / FLAT from the 90 % model interval of the first horizon vs 0."""

    def _art(self, const, sigma2=1e-6):
        return {"transform": "RETURNS", "order": [0, 0, 0], "trend": "c", "params": [const, sigma2], "param_names": ["intercept", "sigma2"],
                "window": 60, "scale": 1.0}

    def test_arima_direction_from_interval(self):
        from masterquo.modelhub.families import arima as A
        f, bars = A.ARIMA(), _bars(80)
        for const, want in ((0.01, "UP"), (-0.01, "DOWN"), (0.0, "FLAT"), (0.001, "FLAT")):
            r = f.predict(self._art(const), {"bars": bars})
            self.assertEqual(r["direction"], want, (const, r["lo"], r["hi"]))
            self.assertEqual(r["direction"], "UP" if r["lo"] > 0 else "DOWN" if r["hi"] < 0 else "FLAT")
            self.assertIn("90%", r["direction_rule"])
            rec = f.pred(inst="XAUUSD", symbol="XAUUSD", state="READY", result=r, run_id="R1", data_time=bars[-1]["t"])   # PMW-PRED-2 valid
            self.assertEqual(rec["result"]["direction"], want)

    def test_sarimax_direction_from_interval(self):
        from masterquo.modelhub.families import arima as A
        f = A.SARIMAX()
        nx = A.calendar_exog(np.asarray([float(T0)]), "LAB_XAU_REFERENCE_V1").shape[1]
        bars = _bars(80, tf_s=3600)
        for const, want in ((0.01, "UP"), (-0.01, "DOWN"), (0.0, "FLAT")):
            art = {"transform": "RETURNS", "order": [0, 0, 0], "trend": "c", "seasonal": [0, 0, 0, 0], "params": [const] + [0.0] * nx + [1e-6],
                   "window": 60, "profile_id": "LAB_XAU_REFERENCE_V1", "tf_s": 3600, "scale": 1.0}
            r = f.predict(art, {"bars": bars})
            self.assertEqual(r["direction"], want)

    def _rec(self, direction, *, use="SHADOW", state="READY", age=10.0, now=None):
        """The row shape the coordinator receives (family records; record_sh rows carry no data_time)."""
        res = {"mean": 0.0, "lo": -1.0, "hi": 1.0}
        if direction is not None:
            res["direction"] = direction
        return {"family": "TS_ARIMA", "model_name": "TS_ARIMA", "state": state, "use": use, "task_type": "REGRESSION", "unit": "log_return",
                "result": res if state == "READY" else None, "data_time": None if age is None else (now - age),
                "unavailable_reason": None if state == "READY" else "x"}

    def test_required_coordinator_blocks_flat_and_contrary(self):
        from masterquo.decision.coordinator import evaluate_models
        now = float(T0 + 10_000)
        kw = {"required": {"TS_ARIMA"}, "assist_threshold": 0.6, "max_age_s": 900.0, "now": now}
        from masterquo.modelhub.families import arima as A
        res = A.ARIMA().predict(self._art(0.0), {"bars": _bars(80)})                 # FLAT forecast from the real predict
        rec = A.ARIMA().pred(inst="XAUUSD", symbol="XAUUSD", state="READY", result=res, run_id="R1", data_time=now - 10)
        self.assertEqual(evaluate_models([rec], "BUY", **kw)[1], ["MODEL_REQUIRED_NOT_CONFIRMING:TS_ARIMA"])      # was [] (PASS)
        self.assertEqual(evaluate_models([self._rec("DOWN", now=now)], "BUY", **kw)[1], ["MODEL_REQUIRED_CONTRARY:TS_ARIMA"])
        self.assertEqual(evaluate_models([self._rec("UP", now=now)], "BUY", **kw)[1], [])
        r = evaluate_models([self._rec("DOWN", use="ASSIST", now=now)], "BUY", required=set(), assist_threshold=0.6, max_age_s=900.0, now=now)
        self.assertEqual(r[1], ["MODEL_ASSIST_HOLD:TS_ARIMA"])

    def test_direction_only_tightens(self):
        """For every role / state / age / side: the blocking reasons WITHOUT direction (today) are a subset of those WITH direction -
        no hold / block of today disappears, nothing new passes."""
        from masterquo.decision.coordinator import evaluate_models
        now = float(T0 + 10_000)
        for use, state, age, side, d, req in itertools.product(("SHADOW", "ASSIST"), ("READY", "BLOCKED_DATA"), (10.0, 5000.0, None, -60.0),
                                                                 ("BUY", "SELL", "NONE"), ("UP", "DOWN", "FLAT"), (True, False)):
            kw = {"required": {"TS_ARIMA"} if req else set(), "assist_threshold": 0.6, "max_age_s": 900.0, "now": now}
            before = set(evaluate_models([self._rec(None, use=use, state=state, age=age, now=now)], side, **kw)[1])
            after = set(evaluate_models([self._rec(d, use=use, state=state, age=age, now=now)], side, **kw)[1])
            self.assertTrue(before <= after, (use, state, age, side, d, req, before, after))


# ===================================================================================================================== I0409
class TestGarchBurnIn(unittest.TestCase):
    def test_bars_used_and_burn_in_reported(self):
        from masterquo.modelhub.families import garch as G
        f = G.GARCH()
        art = {"dist": "normal", "omega": 0.01, "alpha": 0.05, "beta": 0.9, "scale": "percent_internal", "window": 2000}
        bars = _bars(760)
        r = f.predict(art, {"bars": bars})
        self.assertEqual(r["bars_used"], 759)
        self.assertEqual(r["window_declared"], 2000)
        self.assertAlmostEqual(r["burn_in_residual"], 0.95 ** 759, places=15)
        fc = f._forecast(art, np.asarray([b["c"] for b in bars]))
        self.assertEqual(r["sigma"], fc["horizons"]["6"]["sigma"])                       # the forecast itself is unchanged
        long = f.predict(art, {"bars": _bars(2500)})
        self.assertEqual(long["bars_used"], 2000)                                        # the window is the maximum
        f.pred(inst="XAUUSD", symbol="XAUUSD", state="READY", result=r, run_id="R1", data_time=bars[-1]["t"])   # PMW-PRED-2 valid


# ===================================================================================================================== I0400 / I0468
CONNECTED = {"SH_CONTEXT", "DECISION", "QUANT", "PANEL", "MODELHUB", "MM_BOARD"}


class TestFamilyReceiversConnected(unittest.TestCase):
    def test_receivers_have_a_reader_planned_listed_apart(self):
        from masterquo.modelhub.families import registry
        for fid, f in registry().items():
            caps = f.capabilities()
            for r in caps["receivers"]:
                self.assertIn(r.split(":")[0], CONNECTED, (fid, r))
            self.assertIn("planned_receivers", caps, fid)
            for r in caps["planned_receivers"]:
                self.assertNotIn(r.split(":")[0], CONNECTED, (fid, r))
            rec = f.pred(inst="XAUUSD", symbol=None, state="BLOCKED_DATA", reason="x")
            self.assertEqual(rec["receivers"], caps["receivers"])                         # the record carries the connected ones only

    def test_labels_kept_as_planned(self):
        from masterquo.modelhub.families import registry
        reg = registry()
        self.assertIn("RISK:volatility_scenario", reg["VOL_GARCH"].capabilities()["planned_receivers"])
        self.assertIn("AGENT:context", reg["TS_ARIMA"].capabilities()["planned_receivers"])
        self.assertIn("SH_CONTEXT:volatility", reg["VOL_GARCH"].capabilities()["receivers"])

    def test_service_docstring_has_no_risk_view_or_agent_promise(self):
        from masterquo.modelhub.families import service as S
        doc = S.__doc__
        self.assertNotIn("adds a volatility scenario to the risk view", doc)
        self.assertNotIn("panel / agent", doc)


# ===================================================================================================================== I0223 / I0471
class TestNlpNoDeadTransformerPromise(unittest.TestCase):
    def test_name_without_transformer_while_nothing_calls_it(self):
        import re

        from masterquo.modelhub.families import registry
        call_rx = re.compile(r"""call\(\s*["']nlp_predict""")
        read_rx = re.compile(r"""(\.nlp_transformer_path|\[["']nlp_transformer_path["']\]|get\(\s*["']nlp_transformer_path)""")
        src = {p: p.read_text(encoding="utf-8") for p in (BACKEND / "masterquo").rglob("*.py")}
        callers = [p for p, s in src.items() if call_rx.search(s)]
        reads = [p for p, s in src.items() if read_rx.search(s) and p.name not in ("service.py", "cli.py")]   # those two only pass it on
        self.assertEqual((callers, reads), ([], []))                                     # the premise: no caller, no reader
        f = registry()["NLP_SENTIMENT"]
        self.assertNotIn("transformer", f.NAME.lower())
        self.assertNotIn("transformer", f.capabilities()["name"].lower())
        self.assertEqual((f.ID, f.TASK, f.TASK_TYPE), ("NLP_SENTIMENT", "TEXT_SENTIMENT_3", "NLP_SENTIMENT"))   # identity unchanged

    def test_worker_op_kept_and_marked(self):
        from deep_runtime import nlp as DN
        from deep_runtime import worker as W
        self.assertIn("nlp_predict", Path(W.__file__).read_text(encoding="utf-8"))      # the op is kept (condition 3)
        self.assertIn("NOT CONNECTED", DN.__doc__)
        self.assertEqual(DN.predict({"texts": ["x"]}), {"ok": False, "error": "CHECKPOINT_NOT_FOUND"})

    def test_config_key_kept_description_says_unused(self):
        from masterquo.config import FamiliesConfig
        fld = FamiliesConfig.model_fields["nlp_transformer_path"]
        self.assertIsNone(fld.default)
        self.assertIn("not used", fld.description)
        self.assertEqual(FamiliesConfig.model_validate({"nlp_transformer_path": "C:/ckpt"}).nlp_transformer_path, "C:/ckpt")


# ===================================================================================================================== I0470
def _corpus_rows(n=600, seed=4):
    rng = np.random.default_rng(seed)
    pos, neg, neu = ["gold rallies", "bullion surges", "strong demand lifts"], ["gold plunges", "prices slump", "sell-off deepens"], \
        ["market waits", "traders eye data", "session opens quietly"]
    rows = []
    for i in range(n):
        k = i % 3
        w = (pos, neu, neg)[k][(i // 3) % 3] + f" item {i} " + " ".join(rng.choice(["today", "again", "now", "on fed"], 2))
        rows.append({"text": w, "label": ("POSITIVE", "NEUTRAL", "NEGATIVE")[k], "first_seen_at": f"2026-01-{1 + i % 28:02d}T00:{i % 60:02d}:00Z"})
    return rows


class TestNlpDataKindFromCorpus(_Tmp):
    def _md_manifest(self, kind="REAL_USER_DATA"):
        from masterquo.marketdata.store import Store
        st = Store()
        st.inst_dir("XAUUSD").mkdir(parents=True, exist_ok=True)
        st.write_manifest("XAUUSD", {"data_kind": kind, "symbol": "XAUUSD"})

    def _file(self, rows, name="c.jsonl"):
        p = Path(self.td) / name
        p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        return p

    def test_load_data_kind_comes_from_the_corpus(self):
        from masterquo.modelhub.families import nlp as NL
        from masterquo.modelhub.families import registry
        from masterquo.modelhub.families import run as RUN
        self._md_manifest("REAL_USER_DATA")
        NL.import_file(self._file(_corpus_rows()), data_kind="SYNTHETIC_TEST")
        self.assertEqual(RUN.load_data(registry()["NLP_SENTIMENT"], "XAUUSD", {})["data_kind"], "SYNTHETIC_TEST")   # was REAL_USER_DATA

    def test_corpus_kind_rules(self):
        from masterquo.modelhub.families import nlp as NL
        from masterquo.modelhub.families import registry
        from masterquo.modelhub.families import run as RUN
        self._md_manifest("REAL_USER_DATA")
        fam = registry()["NLP_SENTIMENT"]
        rows = _corpus_rows(30)
        NL.import_file(self._file(rows[:10], "a.jsonl"))                                # undeclared -> UNKNOWN_SOURCE
        self.assertEqual(NL.load_corpus()[0]["data_kind"], "UNKNOWN_SOURCE")
        self.assertEqual(RUN.load_data(fam, "XAUUSD", {})["data_kind"], "UNKNOWN_SOURCE")
        NL.corpus_path().unlink()
        NL.import_file(self._file(rows[:10], "b.jsonl"), data_kind="REAL_USER_DATA")
        self.assertEqual(RUN.load_data(fam, "XAUUSD", {})["data_kind"], "REAL_USER_DATA")   # every row REAL
        NL.import_file(self._file(rows[10:20], "c.jsonl"), data_kind="SYNTHETIC_TEST")
        self.assertEqual(RUN.load_data(fam, "XAUUSD", {})["data_kind"], "SYNTHETIC_TEST")   # any synthetic row
        NL.corpus_path().unlink()
        with NL.corpus_path().open("w", encoding="utf-8") as fh:                         # a 1.46 corpus row (no provenance field)
            fh.write(json.dumps({"hash": "h1", "text": "gold", "label": "POSITIVE"}) + "\n")
        self.assertEqual(RUN.load_data(fam, "XAUUSD", {})["data_kind"], "UNKNOWN_SOURCE")
        with self.assertRaises(ValueError):
            NL.import_file(self._file(rows[20:], "d.jsonl"), data_kind="WHATEVER")

    def test_trained_artifact_on_synthetic_corpus_cannot_get_assist(self):
        from masterquo.modelhub.families import nlp as NL
        from masterquo.modelhub.families import run as RUN
        self._md_manifest("REAL_USER_DATA")
        NL.import_file(self._file(_corpus_rows()), data_kind="SYNTHETIC_TEST")
        r = RUN.train("NLP_SENTIMENT", "XAUUSD", "smoke", {}, store=self.store)
        self.assertEqual(r["state"], "DONE", r)
        m = self.store.runs("NLP_SENTIMENT", "XAUUSD")[-1]
        self.assertEqual(m["data_kind"], "SYNTHETIC_TEST")
        self.assertFalse(self.store.assist_ok("NLP_SENTIMENT", "XAUUSD", r["run_id"])[0])


# ===================================================================================================================== I0422 / I0427
def _pair(n=900, seed=1):
    rng = np.random.default_rng(seed)
    x = np.cumsum(rng.normal(0, 0.01, n)) + 7.0
    y = 0.5 + 0.8 * x + rng.normal(0, 0.003, n)
    A = [{"t": T0 + i * 3600, "c": float(np.exp(y[i]))} for i in range(n)]
    Bb = [{"t": T0 + i * 3600, "c": float(np.exp(x[i]))} for i in range(n)]
    return A, Bb


def _basket(n=900, seed=2):
    rng = np.random.default_rng(seed)
    f = np.cumsum(rng.normal(0, 0.01, n))
    return [[{"t": T0 + i * 3600, "c": float(np.exp(5 + k * 0.3 * f[i] + rng.normal(0, 0.002)))} for i in range(n)] for k in (1, 2, 3)]


class TestPairSampleCheck(_Tmp):
    def _train(self, fid, data):
        from masterquo.modelhub.families import run as RUN
        r = RUN.train(fid, "XAUUSD", "smoke", {}, data={"instrument": "XAUUSD", "data_kind": "REAL_USER_DATA", **data}, store=self.store)
        self.assertEqual(r["state"], "DONE", r)
        return r["run_id"]

    def _tamper(self, fid, rid, fn):
        p = self.store.run_dir(fid, "XAUUSD", rid) / "manifest.json"
        m = json.loads(p.read_text(encoding="utf-8"))
        fn(m["sample"])
        p.write_text(json.dumps(m), encoding="utf-8")                                    # the manifest is not in its own checksum list

    def test_pair_sample_checked_on_activation(self):
        A, Bb = _pair()
        rid = self._train("PAIR_COINT", {"pair": ["XAUUSD", "EURUSD"], "pair_bars": [A, Bb]})
        s = self.svc()
        a = s.activate("PAIR_COINT", "XAUUSD", rid)
        self.assertEqual(a["status"], "ACTIVE", a)
        self.assertTrue(a["sample_check"]["checked"])
        z = s.fams["PAIR_COINT"].predict(s.fams["PAIR_COINT"].load(self.store.run_dir("PAIR_COINT", "XAUUSD", rid)), {"pair_bars": [A, Bb]})["z"]
        m = json.loads((self.store.run_dir("PAIR_COINT", "XAUUSD", rid) / "manifest.json").read_text(encoding="utf-8"))
        self.assertAlmostEqual(m["sample"]["expected"]["z_last"], z, places=12)          # the sample is what predict computes
        self._tamper("PAIR_COINT", rid, lambda smp: smp["expected"].update(z_last=smp["expected"]["z_last"] + 1.0))
        self.assertEqual(s.activate("PAIR_COINT", "XAUUSD", rid)["status"], "INCOMPATIBLE")   # was ACTIVE (no check)

    def test_old_pair_artifact_without_inputs_still_activates(self):
        A, Bb = _pair()
        rid = self._train("PAIR_COINT", {"pair": ["XAUUSD", "EURUSD"], "pair_bars": [A, Bb]})
        self._tamper("PAIR_COINT", rid, lambda smp: [smp.pop(k, None) for k in ("a_last", "b_last")])
        a = self.svc().activate("PAIR_COINT", "XAUUSD", rid)
        self.assertEqual(a["status"], "ACTIVE")
        self.assertFalse(a["sample_check"]["checked"])

    def test_statarb_sample_checked_on_activation(self):
        ser = _basket()
        rid = self._train("STATARB", {"basket": ["A", "B", "C"], "basket_bars": ser})
        s = self.svc()
        a = s.activate("STATARB", "XAUUSD", rid)
        self.assertEqual(a["status"], "ACTIVE", a)
        self.assertTrue(a["sample_check"]["checked"])                                    # was checked=False (expected None)
        res = s.fams["STATARB"].predict(s.fams["STATARB"].load(self.store.run_dir("STATARB", "XAUUSD", rid)), {"basket_bars": ser})
        m = json.loads((self.store.run_dir("STATARB", "XAUUSD", rid) / "manifest.json").read_text(encoding="utf-8"))
        np.testing.assert_allclose(m["sample"]["expected"]["s_scores"], res["s_scores"], rtol=0, atol=1e-9)
        self._tamper("STATARB", rid, lambda smp: smp["expected"].update(s_scores=[x + 0.5 for x in smp["expected"]["s_scores"]]))
        self.assertEqual(s.activate("STATARB", "XAUUSD", rid)["status"], "INCOMPATIBLE")


# ===================================================================================================================== I0424
class TestPairLegData(_Tmp):
    def _xau(self, n=700):
        from masterquo.marketdata.store import Store
        rng = np.random.default_rng(7)
        c = 2000 * np.exp(np.cumsum(rng.normal(0, 1e-3, n)))
        Store().merge("XAUUSD", "H1", [(T0 + i * 3600, float(c[i]), float(c[i]) + 1, float(c[i]) - 1, float(c[i]), 10, 20, 0, T0 + i * 3600, 0)
                                       for i in range(n)])

    def test_corrupt_leg_is_blocked_with_its_name(self):
        from masterquo.marketdata.store import Store
        from masterquo.modelhub.families import run as RUN
        self._xau()
        d = Store().tf_dir("EURUSD", "H1")
        d.mkdir(parents=True, exist_ok=True)
        (d / "2026-03.csv").write_text("time_utc,time,open,high,low,close,tick_volume,spread,real_volume,server_time,dst_ambiguous\n"
                                       "x,xx,1,1,1,1,1,1,0,1,0\n", encoding="utf-8")
        sf = Path(self.td) / "job.json"
        r = RUN.train("PAIR_COINT", "XAUUSD", "smoke", {"pairs": [["XAUUSD", "EURUSD"]]}, status_file=sf, store=self.store)   # was ValueError
        self.assertEqual(r["state"], "BLOCKED", r)
        self.assertIn("EURUSD", r["reason"])
        self.assertEqual(json.loads(sf.read_text(encoding="utf-8"))["state"], "BLOCKED")

    def test_missing_leg_reason_names_the_leg(self):
        from masterquo.modelhub.families import run as RUN
        self._xau()
        r = RUN.train("PAIR_COINT", "XAUUSD", "smoke", {"pairs": [["XAUUSD", "EURUSD"]]}, store=self.store)
        self.assertEqual(r["state"], "BLOCKED")
        self.assertIn("EURUSD", r["reason"])                                             # was 'za mało wspólnych świec: 0'
        self.assertIn("marketdata", r["reason"])
        r = RUN.train("STATARB", "XAUUSD", "smoke", {"basket": ["XAUUSD", "EURUSD", "GBPUSD"]}, store=self.store)
        self.assertEqual(r["state"], "BLOCKED")
        self.assertIn("EURUSD", r["reason"])

    def test_load_data_exception_is_blocked_not_raised(self):
        from masterquo.modelhub.families import run as RUN
        sf = Path(self.td) / "job.json"
        with mock.patch.object(RUN, "load_data", side_effect=OSError("disk gone")):
            r = RUN.train("KALMAN_LS", "XAUUSD", "smoke", {}, status_file=sf, store=self.store)
        self.assertEqual(r["state"], "BLOCKED")
        self.assertIn("disk gone", r["reason"])
        self.assertEqual(json.loads(sf.read_text(encoding="utf-8"))["state"], "BLOCKED")


# ===================================================================================================================== I0446
class TestThXgbDeps(unittest.TestCase):
    def test_xgb_declares_xgboost(self):
        from masterquo.modelhub.families import registry
        f = registry()["TH_XGB"]
        self.assertEqual(f.capabilities()["deps"], ["xgboost"])
        from masterquo.trainhub import learn as L
        with mock.patch.object(L, "available", return_value={"TH_XGB": False}):
            self.assertEqual(f.implementation()[0], "MISSING_DEPENDENCY")              # availability still from trainhub
        with mock.patch.object(L, "available", return_value={"TH_XGB": True}):
            self.assertEqual(f.implementation(), ("AVAILABLE", None))


# ===================================================================================================================== I0465
def _rl_fakes(seen):
    gym = types.ModuleType("gymnasium")

    class Env:
        def __init__(self):
            pass
    gym.Env = Env
    spaces = types.ModuleType("gymnasium.spaces")
    spaces.Box = lambda *a, **k: ("Box", a, k)
    spaces.Discrete = lambda n: ("Discrete", n)
    gym.spaces = spaces
    sb3 = types.ModuleType("stable_baselines3")

    class Probs:
        def __init__(self, a):
            self.a = a

        def cpu(self):
            return self

        def numpy(self):
            return self.a

    class Policy:
        def obs_to_tensor(self, oo):
            return oo, None

        def get_distribution(self, x):
            return types.SimpleNamespace(distribution=types.SimpleNamespace(probs=Probs(np.array([[0.2, 0.5, 0.3]]))))

    class Model:
        policy = Policy()

        def predict(self, oo, deterministic=True):
            seen.append(np.array(oo))
            return np.array([1]), None
    sb3.PPO = types.SimpleNamespace(load=lambda path, device="cpu": Model())
    common = types.ModuleType("stable_baselines3.common")
    vec = types.ModuleType("stable_baselines3.common.vec_env")
    vec.DummyVecEnv = lambda fns: [f() for f in fns]

    class VN:
        training = True

        def normalize_obs(self, o):
            return o
    vec.VecNormalize = types.SimpleNamespace(load=lambda path, venv: VN())
    torch = types.ModuleType("torch")
    torch.no_grad = nullcontext
    return {"gymnasium": gym, "gymnasium.spaces": spaces, "stable_baselines3": sb3, "stable_baselines3.common": common,
            "stable_baselines3.common.vec_env": vec, "torch": torch}


class TestRlLiveObservation(unittest.TestCase):
    ENV: ClassVar[dict] = {"k": 8, "spread": 0.2, "slippage": 0.05, "commission": 0.0, "unit": 1.0, "max_units": 1, "reward_scale": 2.0, "max_steps": 50}

    def _bars(self):
        return [{k: b[k] for k in ("o", "h", "l", "c")} for b in _bars(60)]

    def test_set_live_state(self):
        from masterquo.modelhub.families.rl_core import ReplayCore
        bars = self._bars()
        core = ReplayCore(bars, **self.ENV)
        core.reset(len(bars) - 1)
        with self.assertRaises(ValueError):
            core.set_live_state(1.0, entry=None, bars_in_pos=0)                         # incomplete state
        with self.assertRaises(ValueError):
            core.set_live_state(1.0, entry=float("nan"), bars_in_pos=0)
        with self.assertRaises(ValueError):
            core.set_live_state(0.37, entry=bars[-1]["c"], bars_in_pos=0)               # not a multiple of unit
        with self.assertRaises(ValueError):
            core.set_live_state(2.0, entry=bars[-1]["c"], bars_in_pos=0)                # above max_units
        core.set_live_state(1.0, entry=bars[-1]["c"], bars_in_pos=3)
        o = core.obs()
        self.assertEqual(float(o[-2]), 0.0)
        self.assertAlmostEqual(float(o[-1]), 0.03, places=6)
        core.set_live_state(-1.0, entry=bars[-1]["c"] + 4.0, bars_in_pos=250)
        o = core.obs()
        self.assertAlmostEqual(float(o[-2]), (-1.0 * (bars[-1]["c"] - (bars[-1]["c"] + 4.0))) / 2.0, places=4)   # in reward units
        self.assertAlmostEqual(float(o[-1]), 1.0)
        core.set_live_state(0.0, entry=None, bars_in_pos=None)                           # flat: exactly the reset state
        ref = ReplayCore(bars, **self.ENV)
        ref.reset(len(bars) - 1)
        np.testing.assert_array_equal(core.obs(), ref.obs())

    def _predict(self, req):
        from deep_runtime import rl
        seen: list = []
        with tempfile.TemporaryDirectory() as d:
            Path(d, "rl_config.json").write_text(json.dumps({"env": self.ENV}), encoding="utf-8")
            with mock.patch.dict(sys.modules, _rl_fakes(seen)):
                out = rl.predict({"dir": d, "bars": self._bars(), **req})
        return out, seen

    def test_worker_refuses_incomplete_position_state(self):
        out, seen = self._predict({"position": 1.0})
        self.assertEqual(out, {"ok": False, "error": "POSITION_STATE_INCOMPLETE"})       # was a price-level unrealised P/L
        self.assertEqual(seen, [])
        bars = self._bars()
        out, seen = self._predict({"position": 1.0, "position_entry": bars[-1]["c"] - 1.0, "bars_in_position": 5})
        self.assertTrue(out["ok"])
        self.assertAlmostEqual(float(seen[0][0][-2]), 1.0 / self.ENV["reward_scale"], places=4)
        self.assertAlmostEqual(float(seen[0][0][-1]), 0.05, places=6)
        out, seen = self._predict({"position": 0.0})                                     # flat: unchanged observation
        from masterquo.modelhub.families.rl_core import ReplayCore
        ref = ReplayCore(bars, **self.ENV)
        ref.reset(len(bars) - 1)
        np.testing.assert_allclose(seen[0][0], ref.obs(), rtol=1e-6)

    def test_family_predict_blocks_incomplete_state_and_forwards_it(self):
        from masterquo.modelhub.families import base as B
        from masterquo.modelhub.families import deep as D
        from masterquo.modelhub.families import rl as RL
        f = RL.PPO()
        bars = _bars(60)
        with mock.patch.object(D, "call", return_value={"ok": True, "action": 2, "probs": [0.1, 0.2, 0.7]}) as call:
            with self.assertRaises(B.Unavailable) as cm:
                f.predict({"dir": "x"}, {"bars": bars, "position": 1.0})
            self.assertEqual(cm.exception.state, "BLOCKED_DATA")
            call.assert_not_called()
            f.predict({"dir": "x"}, {"bars": bars, "position": 1.0, "position_entry": 2001.0, "bars_in_position": 4})
            sent = call.call_args[0][1]
            self.assertEqual((sent["position"], sent["position_entry"], sent["bars_in_position"]), (1.0, 2001.0, 4))


# ===================================================================================================================== I0475
class TestDelegatedFamilies(_Tmp):
    def test_run_train_event_gru_delegated(self):
        from masterquo.modelhub.families import run as RUN
        sf = Path(self.td) / "job.json"
        r = RUN.train("SEQ_GRU_EVENT", "XAUUSD", "smoke", {}, status_file=sf, store=self.store)
        self.assertEqual(r["state"], "DELEGATED", r)                                    # was FAILED NotImplementedError
        self.assertIn("mm", r["reason"].lower())
        self.assertEqual(json.loads(sf.read_text(encoding="utf-8"))["state"], "DELEGATED")
        d = Path(self.td) / "SEQ_GRU_EVENT"
        self.assertEqual([p.name for p in d.rglob(".tmp-*")] if d.exists() else [], [])  # no unfinished run dir

    def test_submit_delegated_without_a_process(self):
        from masterquo.trainhub import learn as L
        s = self.svc()
        with mock.patch("subprocess.Popen", side_effect=AssertionError("no process for a delegated family")), \
                mock.patch.object(L, "available", return_value={"TH_XGB": True}):
            for fid in ("SEQ_GRU_EVENT", "TH_XGB"):
                r = s.submit(fid, "XAUUSD")
                self.assertEqual((r["ok"], r["status"]), (False, "DELEGATED"), (fid, r))
                self.assertTrue(r["reason"])
                self.assertEqual(s.job(fid, "XAUUSD")["state"], "DELEGATED")
        with mock.patch("subprocess.Popen", side_effect=AssertionError("no process")), mock.patch.object(L, "available", return_value={}):
            r = s.submit("TH_XGB", "XAUUSD")                                              # what run.train answers without xgboost
            self.assertEqual((r["ok"], r["status"]), (False, "BLOCKED"))


# ===================================================================================================================== I0215
class _FakeProc:
    """A stand-in for the persistent worker: answers every request line with one JSON line (same id)."""

    instances: ClassVar[list] = []

    def __init__(self, argv, *a, hang=False, **kw):
        self.argv, self.hang, self.killed = argv, hang, False
        self.pid = 4242 + len(_FakeProc.instances)
        self._q: list = []
        self._ev = threading.Event()
        self.stdin = types.SimpleNamespace(write=self._write, flush=lambda: None, close=lambda: None)
        self.stdout = types.SimpleNamespace(readline=self._readline)
        _FakeProc.instances.append(self)

    def _write(self, s):
        for line in s.splitlines():
            if line.strip():
                self._q.append(json.loads(line))
                self._ev.set()

    def _readline(self):
        if self.hang:
            self._ev.clear()
            self._ev.wait(5)                                                              # until killed
            return ""
        self._ev.wait(5)
        if self.killed or not self._q:
            return ""
        req = self._q.pop(0)
        if not self._q:
            self._ev.clear()
        if req.get("op") == "quit":
            return json.dumps({"ok": True, "id": req.get("id"), "bye": True}) + "\n"
        return json.dumps({"ok": True, "p": [[0.2, 0.3, 0.5]], "id": req.get("id"), "op": req.get("op")}) + "\n"

    def poll(self):
        return -9 if self.killed else None

    def kill(self):
        self.killed = True
        self._ev.set()

    terminate = kill

    def wait(self, timeout=None):
        self.killed = True
        return -9


class TestDeepPersistentWorker(unittest.TestCase):
    def setUp(self):
        from masterquo.modelhub.families import deep as D
        tmp = _env.TempData()                                                             # logs/deep_worker.log of the worker
        self.addCleanup(tmp.close)
        self.D = D
        _FakeProc.instances = []
        self.runs = []
        prev = os.environ.get("MQ_DEEP_PYTHON")
        os.environ["MQ_DEEP_PYTHON"] = sys.executable                                     # an existing interpreter file
        self.addCleanup(lambda: os.environ.pop("MQ_DEEP_PYTHON", None) if prev is None else os.environ.__setitem__("MQ_DEEP_PYTHON", prev))
        self.addCleanup(lambda: getattr(D, "shutdown", lambda: None)())
        getattr(D, "shutdown", lambda: None)()

    def _run(self, argv, *a, **kw):
        self.runs.append(argv)
        Path(argv[-1]).write_text(json.dumps({"ok": True, "p": [[0.2, 0.3, 0.5]]}), encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, "", "")

    def test_two_predictions_one_process(self):
        with mock.patch.object(self.D.subprocess, "run", side_effect=self._run), mock.patch.object(self.D.subprocess, "Popen", _FakeProc):
            r1 = self.D.call("predict_seq", {"dir": "d", "x_path": "x.npy"}, timeout=10)
            r2 = self.D.call("predict_seq", {"dir": "d", "x_path": "x.npy"}, timeout=10)
            r3 = self.D.call("predict_ppo", {"dir": "d", "bars": [], "position": 0.0}, timeout=10)
        self.assertTrue(r1["ok"] and r2["ok"] and r3["ok"], (r1, r2, r3))
        self.assertEqual(r1["p"], [[0.2, 0.3, 0.5]])
        self.assertNotIn("id", r1)
        self.assertEqual(len(self.runs) + len(_FakeProc.instances), 1)                  # was 3 separate worker processes
        self.assertIn("--serve", _FakeProc.instances[0].argv)

    def test_training_stays_one_shot(self):
        with mock.patch.object(self.D.subprocess, "run", side_effect=self._run), mock.patch.object(self.D.subprocess, "Popen", _FakeProc):
            self.assertTrue(self.D.call("train_seq", {"dir": "d", "arch": "GRU", "cfg": {}}, timeout=10)["ok"])
        self.assertEqual((len(self.runs), len(_FakeProc.instances)), (1, 0))

    def test_timeout_kills_and_next_call_restarts(self):
        hang = {"on": True}

        def popen(argv, *a, **kw):
            return _FakeProc(argv, hang=hang["on"])
        with mock.patch.object(self.D.subprocess, "run", side_effect=self._run), mock.patch.object(self.D.subprocess, "Popen", side_effect=popen):
            t0 = time.monotonic()
            r = self.D.call("predict_seq", {"dir": "d", "x_path": "x.npy"}, timeout=0.3)
            self.assertLess(time.monotonic() - t0, 3.0)
            self.assertEqual(r, {"ok": False, "error": "TIMEOUT 0s"})                   # the same error text as the one-shot call
            self.assertTrue(_FakeProc.instances[0].killed)
            hang["on"] = False
            r = self.D.call("predict_seq", {"dir": "d", "x_path": "x.npy"}, timeout=5)
        self.assertTrue(r["ok"], r)
        self.assertEqual(len(_FakeProc.instances), 2)

    def test_dead_worker_reported_and_restarted(self):
        with mock.patch.object(self.D.subprocess, "Popen", _FakeProc):
            self.assertTrue(self.D.call("predict_seq", {"dir": "d", "x_path": "x.npy"}, timeout=5)["ok"])
            _FakeProc.instances[0].killed = True                                         # the process died between calls
            self.assertTrue(self.D.call("predict_seq", {"dir": "d", "x_path": "x.npy"}, timeout=5)["ok"])
        self.assertEqual(len(_FakeProc.instances), 2)

    def test_not_installed_unchanged(self):
        os.environ["MQ_DEEP_PYTHON"] = str(Path(tempfile.gettempdir()) / "no_such_python_w2")
        with mock.patch.object(self.D, "python", return_value=None):
            r = self.D.call("predict_seq", {"dir": "d", "x_path": "x.npy"}, timeout=5)
        self.assertFalse(r["ok"])
        self.assertIn("DEEP_ENV_NOT_INSTALLED", r["error"])


def _deep_py() -> str | None:
    p = os.environ.get("MQ_DEEP_PYTHON")
    if not p or not Path(p).is_file():
        return None
    try:
        ok = subprocess.run([p, "-c", "import torch"], capture_output=True, timeout=120, check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        ok = False
    return p if ok else None


_DEEP = _deep_py()


@unittest.skipUnless(_DEEP, "brak interpretera .venv_deep z torch (MQ_DEEP_PYTHON) – test integracyjny pominięty")
class TestDeepPersistentWorkerReal(unittest.TestCase):
    """The real .venv_deep: the persistent worker returns exactly the one-shot result, one process for several calls."""

    def test_same_result_as_one_shot(self):
        from masterquo.modelhub.families import deep as D
        tmp = _env.TempData()
        self.addCleanup(tmp.close)
        self.addCleanup(D.shutdown)
        with tempfile.TemporaryDirectory() as d:
            mk = ("import json, sys, numpy as np, torch; sys.path.insert(0, sys.argv[2]); from deep_runtime.seq import _net; d = sys.argv[1]; "
                  "torch.manual_seed(3); net = _net('GRU', 5, 8, 1, 0.0); torch.save(net.state_dict(), d + '/model.pt'); "
                  "open(d + '/seq_config.json', 'w').write(json.dumps({'arch': 'GRU', 'n_feat': 5, 'hidden': 8, 'layers': 1, 'dropout': 0.0, "
                  "'temperature': 1.5, 'lookback': 12})); np.save(d + '/x.npy', np.random.default_rng(1).normal(size=(3, 12, 5)).astype('float32'))")
            subprocess.run([_DEEP, "-c", mk, d, str(BACKEND)], check=True, capture_output=True, timeout=300)
            rq, rs = Path(d) / "rq.json", Path(d) / "rs.json"
            rq.write_text(json.dumps({"op": "predict_seq", "dir": d, "x_path": d + "/x.npy"}), encoding="utf-8")
            subprocess.run([_DEEP, "-m", "deep_runtime.worker", str(rq), str(rs)], cwd=str(BACKEND), check=True, capture_output=True, timeout=300)
            one_shot = json.loads(rs.read_text(encoding="utf-8"))
            prev = os.environ.get("MQ_DEEP_PYTHON")
            os.environ["MQ_DEEP_PYTHON"] = _DEEP
            try:
                a = D.call("predict_seq", {"dir": d, "x_path": d + "/x.npy"}, timeout=300)
                pid = D._SRV["proc"].pid
                b = D.call("predict_seq", {"dir": d, "x_path": d + "/x.npy"}, timeout=120)
                self.assertEqual(D._SRV["proc"].pid, pid)                                # the same process
            finally:
                os.environ["MQ_DEEP_PYTHON"] = prev if prev is not None else _DEEP
        self.assertTrue(one_shot["ok"] and a["ok"] and b["ok"], (one_shot, a, b))
        self.assertEqual(a["p"], one_shot["p"])
        self.assertEqual(b["p"], one_shot["p"])


if __name__ == "__main__":
    unittest.main()
