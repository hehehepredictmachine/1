"""1.46 arch, fala 2 - grupa families_core (rodziny modeli: serwis, CLI, katalog, kontrakt). Każdy test nie przechodzi na kodzie
sprzed poprawki (wynik przed/po w opisie commitu).

* I0216 (+I0219, I0221): integralność artefaktu (sha256 z manifestu) była sprawdzana tylko przy aktywacji - po restarcie pickle / joblib
  wczytywano bez kontroli, a worker .venv_deep czytał pliki przy każdym wywołaniu. Teraz przy każdym liczeniu (z pamięcią po stat plików).
  Rola ASSIST: rekord liczony jak w 1.45 (wstrzymania nie znikają - S0 fail-open), tylko z polem integrity_violation.
* I0395 (+duplikaty) / I0472: ASSIST przyjmowany dla typów wyniku bez odbiorcy - odmowa ASSIST_NO_RECEIVER, pole assist_effect.
* I0417 / I0856: jawne OFF dla MICROSTRUCTURE ignorowane.
* I0450: brak single-flight - dwa wątki liczyły tę samą świecę dwa razy.
* I0452: brak zależności -> DISABLED zamiast BLOCKED_DATA.
* I0464: RL_PPO bez źródła pozycji na żywo -> DISABLED (NO_LIVE_PATH) zamiast wiecznego BLOCKED_DATA.
* I0469: polecenie `families import-corpus` z prawdziwym data_kind korpusu (run.load_data nie dziedziczy rodzaju danych świec).
* I0477: SEQ_GRU_EVENT 'AVAILABLE' bez działającego Quant.
* I0790: inferencja deep liczona w tle po zamknięciu świecy, ścieżka SH czyta wynik z pamięci.
* I0553 / I0002: katalog - lokalizacja kontroli jakości danych, pokrycie rejestru kanonicznego.
* I0052: słownik data_quality (PMW-PRED-2 normalizacja bez odrzucania; kandydat SH bez statusu setupu w data_quality).
* I0642: TH_BASELINE poza migawką Quant (REFERENCE_BASELINE).
"""
from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _env

INST = "XAUUSD"
T0 = 1_760_000_100.0                                                            # bar open on the M5 grid


def _bars(n=80, last_open=T0):
    return [{"t": last_open - 300 * i, "o": 2000.0, "h": 2001.0, "l": 1999.0, "c": 2000.0 + 0.1 * i, "tv": 10, "spread": 20}
            for i in range(n)][::-1]


class _Case(unittest.TestCase):
    def setUp(self):
        from masterquo.modelhub.families import base as B
        tmp = _env.TempData()
        self.addCleanup(tmp.close)
        self.td = tempfile.mkdtemp(prefix="fam_core_")
        self.addCleanup(shutil.rmtree, self.td, True)
        self.B, self.store = B, B.Store(Path(self.td))

    def svc(self):
        from masterquo.config import ConfigStore
        from masterquo.modelhub.families.service import FamilyService
        return FamilyService(ConfigStore(), None, store=self.store)

    def committed_run(self, fid, *, status="APPROVED", kind="REAL_USER_DATA", payload=b'{"w": [1, 2, 3]}', name="payload.json"):
        rid, tmp = self.store.new_run(fid, INST)
        (tmp / name).write_bytes(payload)
        self.store.commit(fid, INST, rid, tmp, {"validation": {"status": status}, "data_kind": kind})
        return rid

    def manifest_run(self, fid, rid, status="APPROVED", kind="REAL_USER_DATA"):
        d = self.store.run_dir(fid, INST, rid)
        d.mkdir(parents=True)
        self.B._atomic_json(d / "manifest.json", {"run_id": rid, "validation": {"status": status}, "data_kind": kind, "created_at": 1})
        return d


def _seq_patches(s, fid="SEQ_LSTM", probs=None, bars=None, load=None, predict=None):
    f = s.fams[fid]
    return (mock.patch.object(f, "implementation", return_value=("AVAILABLE", None)),
            mock.patch.object(f, "load", side_effect=load or (lambda d: {"dir": str(d)})),
            mock.patch.object(f, "predict", side_effect=predict or (lambda art, live: dict(probs or {"DOWN": 0.7, "FLAT": 0.2, "UP": 0.1}))),
            mock.patch.object(s, "_live", side_effect=lambda f_, inst: {"bars": list(bars() if callable(bars) else (bars or _bars()))}))


class _Patched:
    def __init__(self, *ps):
        self.ps = ps

    def __enter__(self):
        return [p.__enter__() for p in self.ps]

    def __exit__(self, *exc):
        for p in reversed(self.ps):
            p.__exit__(*exc)
        return False


# ---------------------------------------------------------------------------------------------------------------- I0216
class TestFamilyIntegrityOnLoad(_Case):
    """I0216 (+I0219, I0221): the artifact checksum is verified on every computation (cached by the files' stat), not only at activation."""

    FID = "SEQ_LSTM"

    def tamper(self, rid, name="payload.json"):
        p = self.store.run_dir(self.FID, INST, rid) / name
        b = bytearray(p.read_bytes())
        b[2] ^= 0x01
        p.write_bytes(bytes(b))

    def test_restart_after_tamper_is_incompatible_without_loading(self):
        rid = self.committed_run(self.FID)
        self.store.set_active(self.FID, INST, rid, "t")                          # use SHADOW
        s = self.svc()
        with _Patched(*_seq_patches(s)):
            self.assertEqual(s.predict(self.FID, INST)["state"], "READY")        # untouched files -> READY as before
        self.tamper(rid)
        s2 = self.svc()                                                           # restart: nothing loaded yet
        load = mock.Mock(side_effect=lambda d: {"dir": str(d)})
        with _Patched(*_seq_patches(s2, load=load)):
            p = s2.predict(self.FID, INST)
        self.assertEqual(p["state"], "INCOMPATIBLE", p)
        self.assertIn("suma kontrolna", p["unavailable_reason"])
        load.assert_not_called()                                                  # the changed pickle / weights are never read

    def test_change_after_load_seen_on_next_bar(self):
        """SEQ / RL workers read the weights on every call - a file changed after the in-process load is caught on the next bar."""
        rid = self.committed_run(self.FID)
        self.store.set_active(self.FID, INST, rid, "t")
        s = self.svc()
        cur = {"t": T0}
        with _Patched(*_seq_patches(s, bars=lambda: _bars(last_open=cur["t"]))):
            self.assertEqual(s.predict(self.FID, INST)["state"], "READY")
            self.tamper(rid)
            cur["t"] = T0 + 300
            p = s.predict(self.FID, INST)
        self.assertEqual(p["state"], "INCOMPATIBLE", p)

    def test_verification_is_cached_by_stat(self):
        rid = self.committed_run(self.FID)
        self.store.set_active(self.FID, INST, rid, "t")
        s = self.svc()
        cur = {"t": T0}
        with _Patched(*_seq_patches(s, bars=lambda: _bars(last_open=cur["t"]))), \
                mock.patch.object(s.store, "verify", wraps=s.store.verify) as ver:
            for i in range(3):
                cur["t"] = T0 + 300 * i
                self.assertEqual(s.predict(self.FID, INST)["state"], "READY")
        self.assertEqual(ver.call_count, 1)                                       # hashed once, then the stat signature

    def test_assist_role_keeps_1_45_record_with_violation_field(self):
        """S0 (fail-open): an ASSIST family computed from a changed file keeps the record (and so its holds) exactly as in 1.45; the
        violation is only reported."""
        rid = self.committed_run(self.FID)
        self.store.set_active(self.FID, INST, rid, "t")
        self.store.set_use(self.FID, INST, "ASSIST")
        self.tamper(rid)
        s = self.svc()
        with _Patched(*_seq_patches(s)):
            p = s.predict(self.FID, INST)
            ctx = s.setup_context({"side": "BUY", "status": "READY"}, INST)
        self.assertEqual((p["state"], p["use"]), ("READY", "ASSIST"), p)
        self.assertIn("suma kontrolna", p["integrity_violation"])
        self.assertIsNotNone(ctx["hold"])                                         # P(DOWN)=0.7 >= 0.6: the hold of 1.45 stays


# ---------------------------------------------------------------------------------------------------------------- I0450
class TestFamilyPredictSingleFlight(_Case):
    def test_two_threads_one_computation(self):
        rid = self.committed_run("SEQ_LSTM")
        self.store.set_active("SEQ_LSTM", INST, rid, "t")
        s = self.svc()
        calls = []

        def slow(art, live):
            calls.append(threading.current_thread().name)
            time.sleep(0.3)
            return {"DOWN": 0.2, "FLAT": 0.6, "UP": 0.2}
        out = []
        with _Patched(*_seq_patches(s, predict=slow)):
            ts = [threading.Thread(target=lambda: out.append(s.predict("SEQ_LSTM", INST))) for _ in range(2)]
            for t in ts:
                t.start()
            for t in ts:
                t.join(10)
        self.assertEqual(len(calls), 1, calls)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["state"], "READY")
        self.assertEqual(out[0]["result"], out[1]["result"])


# ---------------------------------------------------------------------------------------------------------------- I0452 / I0464
class TestFamilyUnavailableStates(_Case):
    def test_missing_dependency_is_disabled(self):
        rid = self.committed_run("SEQ_LSTM")
        self.store.set_active("SEQ_LSTM", INST, rid, "t")
        s = self.svc()
        f = s.fams["SEQ_LSTM"]
        with mock.patch.object(f, "implementation", return_value=("MISSING_DEPENDENCY", "brak .venv_deep")), \
                mock.patch.object(s, "_live", return_value={"bars": _bars()}):
            p = s.predict("SEQ_LSTM", INST)
        self.assertEqual(p["state"], "DISABLED", p)
        self.assertIn(".venv_deep", p["unavailable_reason"])

    def test_implementation_error_is_error(self):
        rid = self.committed_run("SEQ_LSTM")
        self.store.set_active("SEQ_LSTM", INST, rid, "t")
        s = self.svc()
        with mock.patch.object(s.fams["SEQ_LSTM"], "implementation", return_value=("ERROR", "worker padł")), \
                mock.patch.object(s, "_live", return_value={"bars": _bars()}):
            self.assertEqual(s.predict("SEQ_LSTM", INST)["state"], "ERROR")

    def test_rl_ppo_has_no_live_path(self):
        rid = self.committed_run("RL_PPO", payload=json.dumps({"env": {"unit": 1.0, "max_units": 1}}).encode(), name="rl_config.json")
        self.store.set_active("RL_PPO", INST, rid, "t")
        s = self.svc()
        with mock.patch.object(s.fams["RL_PPO"], "implementation", return_value=("AVAILABLE", None)), \
                mock.patch.object(s, "_live", return_value={"bars": _bars(200)}):
            p = s.predict("RL_PPO", INST)
        self.assertEqual(p["state"], "DISABLED", p)
        self.assertIn("pozycji", p["unavailable_reason"])


# ---------------------------------------------------------------------------------------------------------------- I0417 / I0856
class TestMicrostructureExplicitOff(_Case):
    def micro(self, s):
        return mock.patch.object(s, "_live", return_value={"micro_snapshot": {"status": "BLOCKED", "reason": "brak arkusza"}})

    def test_default_without_state_is_shadow_measurement(self):
        s = self.svc()
        with self.micro(s):
            p = s.predict("MICROSTRUCTURE", INST)
        self.assertIsNotNone(p)
        self.assertEqual(p["use"], "SHADOW")

    def test_explicit_off_without_artifact_is_honoured(self):
        s = self.svc()
        s.set_use("MICROSTRUCTURE", INST, "OFF")
        with self.micro(s):
            self.assertIsNone(s.predict("MICROSTRUCTURE", INST))
            self.assertEqual([p for p in s.predictions(INST) if p.get("family") == "MICROSTRUCTURE"], [])
        s.set_use("MICROSTRUCTURE", INST, "SHADOW")                              # back on
        with self.micro(s):
            self.assertEqual(s.predict("MICROSTRUCTURE", INST)["use"], "SHADOW")

    def test_explicit_off_with_artifact_is_honoured(self):
        rid = self.committed_run("MICROSTRUCTURE")
        self.store.set_active("MICROSTRUCTURE", INST, rid, "t")
        s = self.svc()
        s.set_use("MICROSTRUCTURE", INST, "OFF")
        with self.micro(s):
            self.assertIsNone(s.predict("MICROSTRUCTURE", INST))


# ---------------------------------------------------------------------------------------------------------------- I0395 / I0472
class TestFamiliesAssistReceiver(_Case):
    def test_assist_refused_without_receiver_state_untouched(self):
        s = self.svc()
        for fid in ("KALMAN_LS", "MICROSTRUCTURE", "NLP_SENTIMENT", "TS_ARIMA", "TS_SARIMAX", "BREAKOUT", "RL_PPO", "PAIR_COINT"):
            self.manifest_run(fid, "R1")
            self.store.set_active(fid, INST, "R1", "t")
            before = self.store._state_path(fid, INST).read_bytes()
            with self.assertRaises(ValueError, msg=fid) as cm:
                s.set_use(fid, INST, "ASSIST")
            self.assertIn("ASSIST_NO_RECEIVER", str(cm.exception), fid)
            self.assertEqual(self.store._state_path(fid, INST).read_bytes(), before, fid)
            self.assertEqual(s.status(fid, INST)["assist_effect"], "NONE", fid)

    def test_assist_allowed_for_direction_and_volatility(self):
        s = self.svc()
        for fid, eff in (("SEQ_LSTM", "HOLD_DIRECTION"), ("SEQ_GRU", "HOLD_DIRECTION"), ("VOL_GARCH", "CONTEXT_VOL")):
            self.manifest_run(fid, "R1")
            self.store.set_active(fid, INST, "R1", "t")
            self.assertEqual(s.set_use(fid, INST, "ASSIST")["state"]["use"], "ASSIST", fid)
            self.assertEqual(s.status(fid, INST)["assist_effect"], eff)
        cat = {c["id"]: c for c in s.catalog(INST)}
        self.assertEqual(cat["SEQ_LSTM"]["assist_effect"], "HOLD_DIRECTION")
        self.assertEqual(cat["NLP_SENTIMENT"]["assist_effect"], "NONE")
        self.assertEqual(cat["TH_RF"]["status"]["assist_effect"], "NONE")

    def test_gate_answer_first_for_not_approved(self):
        """An artifact that would not pass the ASSIST gate keeps the gate's answer (as before)."""
        s = self.svc()
        self.manifest_run("KALMAN_LS", "R1", kind="SYNTHETIC_TEST")
        self.store.set_active("KALMAN_LS", INST, "R1", "t")
        with self.assertRaises(ValueError) as cm:
            s.set_use("KALMAN_LS", INST, "ASSIST")
        self.assertIn("SYNTHETIC_TEST", str(cm.exception))

    def test_saved_assist_is_not_lowered(self):
        self.manifest_run("NLP_SENTIMENT", "R1")
        self.store._save_state("NLP_SENTIMENT", INST, {"active": "R1", "use": "ASSIST", "history": []})
        s = self.svc()
        self.assertEqual(s.status("NLP_SENTIMENT", INST)["use"], "ASSIST")
        self.assertEqual(self.store.state("NLP_SENTIMENT", INST)["use"], "ASSIST")

    def test_model_docs_role_text_depends_on_result_type(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("model_docs_t", str(_env.ROOT / "tools" / "model_docs.py"))
        md = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(md)
        nlp = md.role_rules({"id": "NLP_SENTIMENT", "task_type": "NLP_SENTIMENT", "assist_effect": "NONE"})
        seq = md.role_rules({"id": "SEQ_LSTM", "task_type": "CLASS_PROBABILITIES", "assist_effect": "HOLD_DIRECTION"})
        self.assertIn("ASSIST_NO_RECEIVER", nlp)
        self.assertNotIn("może wyłącznie wstrzymać wejście", nlp)
        self.assertIn("wstrzymać", seq)


# ---------------------------------------------------------------------------------------------------------------- I0477
class TestEventGruStatusWithoutQuant(_Case):
    def test_no_provider_or_quant_off_is_no_source(self):
        s = self.svc()
        self.assertEqual(s.status("SEQ_GRU_EVENT", INST)["implementation"], "NO_SOURCE")          # CLI: no runtime / no Quant
        s.event_gru_provider = lambda inst: None
        s.event_gru_live = lambda: False
        st = s.status("SEQ_GRU_EVENT", INST)
        self.assertEqual(st["implementation"], "NO_SOURCE")
        self.assertIn("Quant", st["implementation_reason"])
        s.event_gru_live = lambda: True
        self.assertEqual(s.status("SEQ_GRU_EVENT", INST)["implementation"], "AVAILABLE")

    def test_probe_failure_is_no_source_not_exception(self):
        s = self.svc()
        s.event_gru_provider = lambda inst: None

        def boom():
            raise ValueError("settings.json nieczytelny")
        s.event_gru_live = boom
        st = s.status("SEQ_GRU_EVENT", INST)
        self.assertEqual(st["implementation"], "NO_SOURCE")
        self.assertIn("settings.json", st["implementation_reason"])

    def test_predict_unchanged_reads_provider(self):
        s = self.svc()
        s.event_gru_provider = lambda inst: {"state": "READY", "family": "SEQ_GRU_EVENT"}
        s.event_gru_live = lambda: False                                          # status only - predict reads the provider as before
        self.assertEqual(s.predict("SEQ_GRU_EVENT", INST)["state"], "READY")

    def test_runtime_wires_quant_mode_probe(self):
        src = (_env.ROOT / "backend" / "masterquo" / "runtime.py").read_text(encoding="utf-8")
        self.assertIn("self.families.event_gru_live = ", src)


# ---------------------------------------------------------------------------------------------------------------- I0790
class TestFamiliesDeepPrecompute(_Case):
    def setUp(self):
        super().setUp()
        rid = self.committed_run("SEQ_LSTM")
        self.store.set_active("SEQ_LSTM", INST, rid, "t")
        self.store.set_use("SEQ_LSTM", INST, "ASSIST")
        self.s = self.svc()
        self.calls = []

    def fake(self, art, live):
        self.calls.append(threading.current_thread().name)
        return {"DOWN": 0.7, "FLAT": 0.2, "UP": 0.1}

    def test_background_result_used_by_sh(self):
        s = self.s
        with _Patched(*_seq_patches(s, predict=self.fake)):
            t = threading.Thread(target=s.precompute_once, args=(INST,), name="families-precompute")
            t.start()
            t.join(10)
            self.assertEqual(self.calls, ["families-precompute"])
            ctx = s.setup_context({"side": "BUY", "status": "READY"}, INST)
        self.assertEqual(self.calls, ["families-precompute"])                     # the SH thread computed nothing
        self.assertIsNotNone(ctx["hold"])

    def test_without_background_result_sh_computes_as_before(self):
        s = self.s
        with _Patched(*_seq_patches(s, predict=self.fake)):
            ctx = s.setup_context({"side": "BUY", "status": "READY"}, INST)
        self.assertEqual(len(self.calls), 1)
        self.assertIsNotNone(ctx["hold"])

    def test_background_error_is_not_the_bar_result(self):
        s = self.s
        state = {"fail": True}

        def flaky(art, live):
            self.calls.append(threading.current_thread().name)
            if state["fail"]:
                raise self.B.Unavailable("ERROR", "TIMEOUT 120s")
            return {"DOWN": 0.7, "FLAT": 0.2, "UP": 0.1}
        with _Patched(*_seq_patches(s, predict=flaky)):
            self.assertEqual(s.precompute_once(INST), 1)
            self.assertEqual(s.precompute_once(INST), 0)                          # one background attempt per bar - no retry loop
            state["fail"] = False
            p = s.predict("SEQ_LSTM", INST)
        self.assertEqual(p["state"], "READY")
        self.assertEqual(len(self.calls), 2)

    def test_background_not_ready_is_not_stored(self):
        s = self.s
        with _Patched(*_seq_patches(s, predict=self.fake)), \
                mock.patch.object(s.fams["SEQ_LSTM"], "implementation", return_value=("MISSING_DEPENDENCY", "health: TIMEOUT")):
            self.assertEqual(s.precompute_once(INST), 1)
        self.assertIsNone(s.last_prediction("SEQ_LSTM", INST))                     # the SH path computes it itself, as before

    def test_health_refreshed_in_background_before_expiry(self):
        from masterquo.modelhub.families import deep as D
        s = self.s
        with _Patched(*_seq_patches(s, predict=self.fake)), mock.patch.object(D, "python", return_value="py"), \
                mock.patch.object(D, "health", return_value={"ok": True}) as h:
            with mock.patch.object(D, "health_age", return_value=100.0):
                s.precompute_once(INST)
            h.assert_not_called()
            with mock.patch.object(D, "health_age", return_value=560.0):
                s.precompute_once(INST)                                           # same bar: no new inference, the health still refreshed
        h.assert_called_once_with(force=True)
        self.assertEqual(len(self.calls), 1)

    def test_only_deep_families_with_active_artifact(self):
        s = self.s
        with _Patched(*_seq_patches(s, predict=self.fake)), mock.patch.object(s, "predict", wraps=s.predict) as pr:
            s.precompute_once(INST)
        self.assertEqual(sorted({c.args[0] for c in pr.call_args_list}), ["SEQ_LSTM"])


# ---------------------------------------------------------------------------------------------------------------- I0469
class TestFamiliesCliImportCorpus(unittest.TestCase):
    def setUp(self):
        tmp = _env.TempData()
        self.addCleanup(tmp.close)
        self.fd = tempfile.mkdtemp(prefix="fam_corpus_")
        self.addCleanup(shutil.rmtree, self.fd, True)
        p = mock.patch.dict(os.environ, {"PMW_FAMILIES_DIR": self.fd})
        p.start()
        self.addCleanup(p.stop)

    def cli(self, *argv):
        from masterquo.modelhub.families import cli
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                rc = cli.main(list(argv))
            except SystemExit as exc:
                rc = exc.code
        return rc, out.getvalue(), err.getvalue()

    def corpus(self, name="c.jsonl", n=6):
        p = Path(self.fd) / name
        lab = ("NEGATIVE", "NEUTRAL", "POSITIVE")
        p.write_text("\n".join(json.dumps({"text": f"gold headline {i}", "label": lab[i % 3], "published_at": f"2026-01-0{1 + i % 9}T10:00:00Z"})
                               for i in range(n)) + "\n", encoding="utf-8")
        return p

    def load_kind(self):
        from masterquo.modelhub.families import base as B
        from masterquo.modelhub.families import registry
        from masterquo.modelhub.families import run as RUN
        d = RUN.load_data(registry()["NLP_SENTIMENT"], INST, {})
        return d["data_kind"], B.kind_class(d["data_kind"]), len(d["corpus"])

    def test_import_synthetic_corpus_is_not_real(self):
        rc, out, err = self.cli("import-corpus", "--file", str(self.corpus()), "--data-kind", "SYNTHETIC_TEST")
        self.assertEqual(rc, 0, err)
        self.assertEqual(json.loads(out)["added"], 6)
        from masterquo.modelhub.families import nlp
        self.assertTrue(all(r.get("data_kind") == "SYNTHETIC_TEST" for r in nlp.load_corpus()))
        kind, cls, n = self.load_kind()
        self.assertEqual((kind, n), ("SYNTHETIC_TEST", 6))
        self.assertNotEqual(cls, "REAL")

    def test_real_only_corpus_is_real_mixed_or_unmarked_is_not(self):
        self.assertEqual(self.cli("import-corpus", "--file", str(self.corpus()), "--data-kind", "REAL_USER_DATA")[0], 0)
        self.assertEqual(self.load_kind()[:2], ("REAL_USER_DATA", "REAL"))
        self.assertEqual(self.cli("import-corpus", "--file", str(self.corpus("d.jsonl", 9)))[0], 0)   # default: unknown source
        self.assertIsNone(self.load_kind()[1])
        from masterquo.modelhub.families import nlp
        cp = nlp.corpus_path()
        with cp.open("a", encoding="utf-8") as f:                                  # a 1.45 record without a marker
            f.write(json.dumps({"hash": "x1", "text": "old", "label": "NEUTRAL"}) + "\n")
        self.assertIsNone(self.load_kind()[1])

    def test_validation_and_cli_contract(self):
        self.assertEqual(self.cli("import-corpus", "--file", str(Path(self.fd) / "missing.jsonl"))[0], 2)
        bad = Path(self.fd) / "c.txt"
        bad.write_text("x", encoding="utf-8")
        self.assertEqual(self.cli("import-corpus", "--file", str(bad))[0], 2)
        self.assertEqual(self.cli("import-corpus")[0], 2)                         # --file required for this command
        self.assertEqual(self.cli("import-corpus", "--file", str(self.corpus()), "--data-kind", "REAL")[0], 2)
        self.assertEqual(self.cli("list")[0], 2)                                   # existing commands still need --instrument
        self.assertEqual(self.cli("rollback", "--family", "TS_ARIMA")[0], 2)
        from masterquo.modelhub.families import nlp
        big = Path(self.fd) / "big.jsonl"
        big.write_text("x", encoding="utf-8")
        with mock.patch.object(nlp, "MAX_IMPORT_BYTES", 0):
            self.assertEqual(self.cli("import-corpus", "--file", str(big))[0], 2)
        self.assertEqual(nlp.load_corpus(), [])
        self.assertFalse(any(Path(self.fd).glob("*/*/state.json")))               # import never touches a family state

    def test_import_appends_only(self):
        self.cli("import-corpus", "--file", str(self.corpus()), "--data-kind", "REAL_USER_DATA")
        self.cli("import-corpus", "--file", str(self.corpus("e.jsonl", 9)), "--data-kind", "REAL_USER_DATA")
        from masterquo.modelhub.families import nlp
        self.assertEqual(len(nlp.load_corpus()), 9)                               # dedup by text, nothing removed


# ---------------------------------------------------------------------------------------------------------------- I0553 / I0002
class TestCatalogLocationsAndCoverage(unittest.TestCase):
    def setUp(self):
        tmp = _env.TempData()
        self.addCleanup(tmp.close)

    def test_data_quality_location_names_live_code(self):
        from masterquo.modelhub import catalog as C
        from masterquo.quant import inventory as QI
        loc = C.LOCATION["data_quality"][0]
        self.assertIn("sh/context.py", loc)
        self.assertIn("quant/snapshot.py", loc)
        for part in loc.split(","):
            path = part.strip().split(" ")[0]
            self.assertTrue((_env.ROOT / "backend" / "masterquo" / path).exists(), path)
        files = QI._OVR["rule:data_quality"]["files"]
        self.assertIn("backend/masterquo/sh/context.py", files)
        for f in files:
            self.assertTrue((_env.ROOT / f).exists(), f)

    def test_catalog_covers_canonical_registry(self):
        from masterquo.modelhub import catalog as C
        from masterquo.quant import inventory as QI
        cat = C.build(None, INST)
        inv = QI.build(None, INST)
        by = {}
        for r in cat["items"]:
            by.setdefault(r.get("canonical_id"), []).append(r["id"])
        for e in inv["entries"]:
            if e["code_state"] in ("NO_SPEC", "NOT_IMPLEMENTED"):
                continue
            self.assertEqual(len(by.get(e["id"]) or []), 1, (e["id"], by.get(e["id"])))
        for r in cat["items"]:
            self.assertIn(r["state"], C.C.STATES, r["id"])
        old = {r["id"]: r for r in cat["items"]}
        self.assertEqual(old["kronos"]["source"], "sh/models.REGISTRY")             # existing rows / ids unchanged
        self.assertEqual(old["th_baseline"]["canonical_id"], "trainhub:TH_BASELINE")
        fam = old.get("family:TS_ARIMA")
        self.assertIsNotNone(fam)
        self.assertNotEqual(fam["state"], "READY")                                 # no family service here - never READY without evidence

    def test_family_rows_take_state_from_family_service(self):
        from masterquo.modelhub import catalog as C
        from masterquo.modelhub.families import deep as D
        st = {"active": "R1", "use": "SHADOW", "history": []}
        last = {"SEQ_LSTM": {"state": "READY", "use": "SHADOW"}}
        fam = SimpleNamespace(store=SimpleNamespace(state=lambda fid, inst: dict(st)), job=lambda fid, inst: None,
                              last_prediction=lambda fid, inst: last.get(fid))
        rt = SimpleNamespace(families=fam)
        with mock.patch.object(D, "health", side_effect=AssertionError("the catalog never starts the .venv_deep health process")):
            rows = {r["id"]: r for r in C.build(rt, INST)["items"]}
            self.assertEqual(rows["family:SEQ_LSTM"]["state"], "READY")
            self.assertEqual(rows["family:SEQ_GRU"]["state"], "BLOCKED_DATA")             # active, no record yet - never READY
            self.assertEqual(rows["family:RL_PPO"]["state"], "DISABLED")                  # NO_LIVE_PATH
            last["SEQ_LSTM"] = {"state": "DISABLED", "unavailable_reason": "brak .venv_deep"}
            st.update(use="OFF")
            rows = {r["id"]: r for r in C.build(rt, INST)["items"]}
            self.assertEqual(rows["family:SEQ_LSTM"]["state"], "DISABLED")
            st.update(active=None)
            rows = {r["id"]: r for r in C.build(rt, INST)["items"]}
            self.assertEqual(rows["family:TS_ARIMA"]["state"], "NOT_TRAINED")


# ---------------------------------------------------------------------------------------------------------------- I0052
class TestDataQualityVocabulary(unittest.TestCase):
    def test_pred2_normalises_without_refusing(self):
        from masterquo.modelhub import contract as C
        kw = {"instrument": INST, "symbol": None, "timeframe": "M5", "model_name": "m", "model_version": None, "task_type": "STATE", "task": "T",
              "horizon_bars": None, "unit": "state", "state": "READY", "result": "OK", "data_time": "2026-01-01T00:00:00Z"}
        p = C.make(data_quality="GOOD", **kw)
        self.assertEqual((p["data_quality"], p["data_quality_raw"]), ("OK", "GOOD"))
        self.assertEqual(C.make(data_quality="SYNTHETIC_TEST", **kw)["data_quality"], "SYNTHETIC")
        self.assertEqual(C.make(data_quality="BLOCK", **kw)["data_quality"], "INVALID")
        q = C.make(**kw)
        self.assertEqual(q["data_quality"], "OK")
        self.assertNotIn("data_quality_raw", q)                                    # a value from the vocabulary is not touched
        r = C.make(data_quality="COKOLWIEK", **kw)                                 # unknown: kept, warned, never refused
        self.assertEqual(r["data_quality"], "COKOLWIEK")
        self.assertIn("DATA_QUALITY_UNKNOWN", r["data_quality_warning"])
        self.assertEqual(C.normalize_dq("DEGRADED"), "DEGRADED")

    def test_sh_candidate_data_quality_is_not_the_setup_status(self):
        from masterquo.evaluation import contract as K
        from masterquo.evaluation import engine as E
        su = {"strategy": "SCALPING", "side": "BUY", "status": "WAIT", "signal_id": "S1", "symbol": "XAUUSD", "instrument": INST,
              "created_at": T0, "entry_ref": 2000.0, "sl": 1998.0, "tps": [{"price": 2003.0, "share": 1.0, "name": "TP1"}],
              "costs": {"spread": 0.2, "round_trip_price": 0.2, "commission_known": True}}
        c = K.from_sh_setup(su)
        self.assertEqual(c.data_quality["status"], "OK")
        self.assertEqual(c.stage, "WAIT")                                          # the setup status stays in stage
        a = E.assess(c, prob=None, extra_cost=0.0)
        self.assertFalse(any(r.startswith("DATA_") for r in a.rejection_reasons), a.rejection_reasons)
        rd = K.from_sh_setup(dict(su, status="READY"))
        self.assertEqual(rd.data_quality["status"], "OK")                          # READY exactly as before
        bad = K.from_sh_setup(dict(su, status="NO_TRADE", checklist=[{"id": "data", "status": "FAIL", "detail": "M1: brak świec"}]))
        self.assertEqual(bad.data_quality["status"], "INVALID")                    # a real data problem keeps a data reason
        self.assertIn("DATA_INVALID", E.assess(bad, prob=None, extra_cost=0.0).rejection_reasons)


# ---------------------------------------------------------------------------------------------------------------- I0642
class TestQuantScreenExcludesBaseline(unittest.TestCase):
    def rec(self, model_key, cid):
        from datetime import UTC, datetime

        from masterquo.modelhub import contract as C
        p = C.make(instrument=INST, symbol="XAUUSD", timeframe="M5", model_name=model_key, model_version="v1", task_type="CLASS_PROBABILITIES",
                   task="DIRECTION_H6_M5", horizon_bars=6, unit="probability", state="READY", result={"DOWN": 0.3, "FLAT": 0.4, "UP": 0.3},
                   data_time=datetime.fromtimestamp(T0, UTC).isoformat(), source="trainhub", extra={"model_key": model_key})
        p["canonical_id"] = cid
        return p

    def test_baseline_excluded_others_eligible(self):
        from masterquo.quant import checks as CK
        scr = CK.screen([self.rec("TH_BASELINE_M5_H6", "trainhub:TH_BASELINE"), self.rec("TH_LOGREG_M5_H6", "trainhub:TH_LOGREG")],
                        now=T0 + 60, snapshot_kind="REAL")
        self.assertEqual([p["canonical_id"] for p in scr["eligible"]], ["trainhub:TH_LOGREG"])
        ex = [p for p in scr["excluded"] if p["canonical_id"] == "trainhub:TH_BASELINE"]
        self.assertEqual(len(ex), 1)
        self.assertEqual(ex[0]["eligibility"]["reason"], "REFERENCE_BASELINE")


if __name__ == "__main__":
    unittest.main()
