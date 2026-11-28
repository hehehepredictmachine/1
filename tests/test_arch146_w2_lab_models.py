"""Fala 2 / grupa lab_models (Apollo23 1.46): metadane i statusy modeli lab / SI / flow / ctx / MR2, filtry instrumentu ledgerów,
identyfikator Kronos w koordynatorze, kontrakt workera scalp, rozjazd trening/serwowanie extind (schemat V2), model fixture_only na
danych REAL, pasmo neutralne TSFM (wyłącznie zaostrzenie REQUIRED), etykiety scalp przy nieznanej prowizji, odcisk SETUP_FEATURES.
Każdy test nie przechodzi na kodzie sprzed poprawki. Dane SYNTETYCZNE - sprawdzają reguły, nie wartość predykcyjną."""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _env  # noqa: F401
from _env import TempData

ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------------------------------------------------------------ I0225
class TestLabBaselineRole(unittest.TestCase):
    """I0225: adapter Quant publikował DUMMY/RULE jako analytic_role BASE_FORECAST, inwentarz nadaje im rolę TOOL."""

    def test_baseline_role_matches_inventory(self):
        from masterquo.quant import adapters as A
        from masterquo.quant import inventory as INV
        st = {"as_of": "2026-11-24T10:00:00Z", "data_mode": "live",
              "models": [{"family": f, "status": "ready", "raw_score": 0.4, "model_id": f"m-{f}", "horizon": "M5x12"}
                         for f in ("DUMMY", "RULE", "LOGREG")]}
        rt = SimpleNamespace(lab=SimpleNamespace(state={"XAUUSD": st}, assets=None))
        roles = {r["id"]: r["quant_role"] for r in INV._lab_rows()}
        recs = A.lab(rt, "XAUUSD")
        self.assertEqual(len(recs), 3)
        for r in recs:
            self.assertEqual(r["analytic_role"], roles[r["canonical_id"]], r["canonical_id"])
        self.assertEqual({r["canonical_id"]: r["analytic_role"] for r in recs},
                         {"lab:DUMMY": "TOOL", "lab:RULE": "TOOL", "lab:LOGREG": "BASE_FORECAST"})


# ------------------------------------------------------------------------------------------------------------------------ I0212
class TestTabiclInstallFacade(unittest.TestCase):
    """I0212: API wołało prywatne TsfmService._run_job_proc do instalacji TabICL."""

    def test_api_does_not_call_private_tsfm_methods(self):
        src = (ROOT / "backend" / "masterquo" / "api" / "app.py").read_text(encoding="utf-8")
        import re
        self.assertEqual(re.findall(r"rt\.tsfm\._\w+", src), [])

    def test_public_method_delegates_unchanged(self):
        # merge with the target (I0089): one public facade - TsfmService.start_job_process("install_tabicl", argv) replaced
        # start_tabicl_install; the same delegation (job name, argv, env=None, on_done=None) is asserted
        from masterquo.tsfm.service import TsfmService
        calls = []
        stub = SimpleNamespace(_run_job_proc=lambda name, argv, env=None, on_done=None: calls.append((name, argv, env, on_done)) or {"ok": True})
        argv = ["py", "tools/tsfm_setup.py", "--model", "tabicl"]
        self.assertEqual(TsfmService.start_job_process(stub, "install_tabicl", argv), {"ok": True})
        self.assertEqual(calls, [("install_tabicl", argv, None, None)])
        src = (ROOT / "backend" / "masterquo" / "api" / "app.py").read_text(encoding="utf-8")
        self.assertIn('rt.tsfm.start_job_process("install_tabicl", argv)', src)


# ------------------------------------------------------------------------------------------------------------------------ I0329
class TestLegacyMLVersionsInDocs(unittest.TestCase):
    """I0329: kontrakt predykcji ML podawał MQ-LABEL-1.0.0 (kod: labels.LABEL_POLICY_VERSION), mapa modeli starą wersję cech."""

    def test_target_definition_uses_current_label_version(self):
        from masterquo.ml import labels as LB
        from masterquo.ml.service import MLService
        r = MLService.predict(SimpleNamespace(cfg=SimpleNamespace(mode="SHADOW")), None, None)
        self.assertEqual(r["uncertainty_reason"], "NO_SETUP")
        self.assertIn(LB.LABEL_POLICY_VERSION, r["target_definition"])

    def test_model_map_generator_uses_current_feature_schema(self):
        import importlib.util

        from masterquo.ml import features as FE
        spec = importlib.util.spec_from_file_location("model_map_t", ROOT / "tools" / "model_map.py")
        mm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mm)
        for e in mm.ELEMENTS:
            if e["id"].startswith("LEGACY_ML_"):
                self.assertTrue(e["features"].startswith(FE.FEATURE_SCHEMA_VERSION), e["id"])


# ------------------------------------------------------------------------------------------------------------ I0040 / I0030
class TestLedgerListingsPerInstrument(unittest.TestCase):
    """I0040: listy ledgerów (forecast/scalp SHADOW, notowania SI, oceny Quant) mieszały instrumenty; I0030: czytnik quote_forecasts
    bez filtra kontekstu. Wołający wewnętrzni (instrument=None) dostają dzisiejsze zachowanie."""

    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)
        from masterquo.db.database import Database
        self.db = Database(Path(self.td.dir) / "t.sqlite")

    def test_forecast_and_scalp_recent_filter(self):
        from masterquo.forecast.service import ForecastService
        from masterquo.scalp.service import ScalpService
        for inst in ("XAUUSD", "BTC"):
            self.db.execute("INSERT INTO forecast_shadow(created_at, run_id, feature_time_utc, horizon_minutes, target_time_utc, close_now, "
                            "neutral_band, p_down, p_flat, p_up, outcome_status, instrument) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                            ("2026-11-24T10:00:00Z", "r", f"2026-11-24T10:00:00Z-{inst}", 5, "2026-11-24T10:05:00Z", 1.0, 0.1, .3, .4, .3,
                             "PENDING", inst))
            self.db.execute("INSERT INTO scalp_shadow(created_at, setup_id, profile_id, direction, decision_time_utc, status, reasons, plan, gates, "
                            "hedge, outcome_status, instrument) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                            ("2026-11-24T10:00:00Z", f"S-{inst}", "p", "BUY", "2026-11-24T10:00:00Z", "BLOCKED", "[]", "{}", "[]", "{}",
                             "NOT_APPLICABLE", inst))
        fs = SimpleNamespace(db=self.db)
        sc = SimpleNamespace(db=self.db)
        self.assertEqual({r["instrument"] for r in ForecastService.recent(fs, 10, instrument="BTC")}, {"BTC"})
        self.assertEqual({r["instrument"] for r in ScalpService.recent(sc, 10, instrument="BTC")}, {"BTC"})
        self.assertEqual({r["instrument"] for r in ForecastService.recent(fs, 10)}, {"XAUUSD", "BTC"})     # internal callers unchanged
        self.assertEqual({r["instrument"] for r in ScalpService.recent(sc, 10)}, {"XAUUSD", "BTC"})

    def test_quote_forecasts_context_filter(self):
        from masterquo.lab.si_service import StructureIntelligenceService
        for ctx in ("XAUUSD|XAUUSD-", "BTC|BTCUSD"):
            p = {"price": 1.0, "se_model": 0.1, "h_s": 5, "band": [0.9, 1.1]}
            self.db.execute("INSERT INTO quote_forecasts(forecast_id, context, side, scale, issued_at, target_at, payload) VALUES (?,?,?,?,?,?,?)",
                            (f"F-{ctx}", ctx, "BID", 5, "2026-11-24T10:00:00Z", "2026-11-24T10:00:05Z", json.dumps(p)))
        si = SimpleNamespace(db=self.db)
        q = StructureIntelligenceService.quote_forecasts
        self.assertEqual([r["forecast_id"] for r in q(si, 10, context="BTC|BTCUSD")], ["F-BTC|BTCUSD"])
        self.assertEqual([r["forecast_id"] for r in q(si, 10, instrument="XAUUSD")], ["F-XAUUSD|XAUUSD-"])
        self.assertEqual(len(q(si, 10)), 2)                                                             # internal callers unchanged

    def test_quant_assessments_instrument_filter(self):
        from masterquo.quant.ledger import QuantLedger
        led = QuantLedger(Path(self.td.dir) / "quant" / "ledger.sqlite")
        for i, inst in enumerate(("XAUUSD", "BTC")):
            led.add_row({"row_id": f"R{i}", "instrument": inst, "engine": "SH", "strategy": "s", "direction": "BUY", "decision_ts": 1.0 + i,
                         "task_hash": "t", "event_id": "e", "spec": {}, "features": {}, "matures_at": 10.0})
            led.add_assessment({"assessment_id": f"A{i}", "row_id": f"R{i}", "created_at": time.time() + i, "mode": "SHADOW", "engine": "SH"})
        self.assertEqual([a["assessment_id"] for a in led.assessments(10, instrument="BTC")], ["A1"])
        self.assertEqual([a["assessment_id"] for a in led.assessments(10)], ["A1", "A0"])

    def test_api_routes_take_optional_asset(self):
        src = (ROOT / "backend" / "masterquo" / "api" / "app.py").read_text(encoding="utf-8")
        for fn in ("def scalp_shadow(", "def forecast_shadow(", "def si_quote_fc(", "def quant_assessments("):
            line = next(x for x in src.splitlines() if fn in x)
            self.assertIn("asset: str | None = None", line, fn)


# ------------------------------------------------------------------------------------------------------- I0479 / I0519 / I0522
class TestNativeStatusReadsLiveSelftest(unittest.TestCase):
    """I0479 (MR2) / I0519 (flow): plik statusu powstaje zaraz po kompilacji, a self-test uruchamia się w terminalu później -
    native_status nie czytał ponownie pliku self-testu (NATIVE_EXECUTED nigdy PASS). Ctx czytał plik bez sprawdzenia świeżości."""

    def _case(self, status_name, selftest_name, text, delta_s):
        d = Path(tempfile.mkdtemp(prefix="mq_native_"))
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        sf = d / status_name
        sf.write_text(json.dumps({"compile_errors": 0, "ex5_sha256": "ab" * 32, "source_sha256": "cd" * 32,
                                  "selftest_result": "NATIVE_NOT_EXECUTED"}), encoding="utf-8")
        st = d / selftest_name
        st.write_text(text, encoding="utf-8")
        t = sf.stat().st_mtime
        os.utime(st, (t + delta_s, t + delta_s))
        return sf

    def test_mr2_selftest_after_status_is_read(self):
        from masterquo.lab import minirocket_v2 as MR
        sf = self._case("native_status.json", "mr2_selftest.txt", "PMW_MR2_SELFTEST RESULT=PASS failures=0 build=4620\n", 10)
        r = MR.native_status(sf)
        self.assertEqual(r["NATIVE_EXECUTED"], "PASS")
        self.assertEqual(r["build"], 4620)
        sf = self._case("native_status.json", "mr2_selftest.txt", "PMW_MR2_SELFTEST RESULT=PASS failures=0 build=4620\n", -10)
        self.assertEqual(MR.native_status(sf)["NATIVE_EXECUTED"], "NATIVE_NOT_EXECUTED")        # older = previous build, not evidence

    def test_flow_selftest_after_status_is_read(self):
        from masterquo.lab.flow_context import native as FN
        sf = self._case("flow_native_status.json", "flow_selftest.txt", "PMW_FLOW_SELFTEST RESULT=FAIL\r\n", 10)
        self.assertEqual(FN.native_status(sf)["NATIVE_EXECUTED"], "FAIL")
        sf = self._case("flow_native_status.json", "flow_selftest.txt", "PMW_FLOW_SELFTEST RESULT=PASS\r\n", -10)
        self.assertEqual(FN.native_status(sf)["NATIVE_EXECUTED"], "NATIVE_NOT_EXECUTED")

    def test_ctx_ignores_selftest_older_than_status(self):
        from masterquo.lab.context_ind import native as CN
        sf = self._case("ctx_native_status.json", "ctx_selftest.txt", "PMW_CTX_SELFTEST RESULT=PASS\r\n", -10)
        self.assertEqual(CN.native_status(sf)["NATIVE_EXECUTED"], "NATIVE_NOT_EXECUTED")
        sf = self._case("ctx_native_status.json", "ctx_selftest.txt", "PMW_CTX_SELFTEST RESULT=PASS\r\n", 10)
        self.assertEqual(CN.native_status(sf)["NATIVE_EXECUTED"], "PASS")


class TestNativeStatusNamesUnified(unittest.TestCase):
    """I0522: ten sam stan (brak MetaEditora / pliku statusu) miał dwie nazwy (flow/MR2 vs ctx)."""

    def test_same_name_for_missing_status(self):
        from masterquo.lab import minirocket_v2 as MR
        from masterquo.lab.context_ind import native as CN
        from masterquo.lab.flow_context import native as FN
        names = {CN.native_status(None)["NATIVE_COMPILED"], FN.native_status(None)["NATIVE_COMPILED"], MR.native_status(None)["NATIVE_COMPILED"]}
        self.assertEqual(names, {"NOT_COMPILED_NO_METAEDITOR"})


# ------------------------------------------------------------------------------------------------------------------------ I0486
class TestMiniRocketExportDir(unittest.TestCase):
    """I0486: CLI eksportował do ./exports/minirocket względem cwd (backend/), a si_service czytał <repo>/exports/minirocket - status
    NOT_EXPORTED, oczekiwany sha None i importer pomijał kontrolę MODEL_MISMATCH."""

    def _cli_output_default(self, cwd):
        import argparse

        from masterquo.lab import structure_cli as SC
        got, orig = [], argparse.ArgumentParser.parse_args

        class _Stop(Exception):
            pass

        def cap(self, args=None, namespace=None):
            got.append(orig(self, args, namespace))
            raise _Stop
        old = os.getcwd()
        os.chdir(cwd)
        try:
            with mock.patch.object(argparse.ArgumentParser, "parse_args", cap), self.assertRaises(_Stop):
                SC.main(["minirocket", "native-status"])
        finally:
            os.chdir(old)
        return Path(got[0].output).resolve()

    def test_cli_default_equals_service_dir_regardless_of_cwd(self):
        from masterquo.lab import minirocket_v2 as MR
        with mock.patch.dict(os.environ, {"MQ_MINIROCKET_EXPORT_DIR": ""}):
            want = (ROOT / "exports" / "minirocket").resolve()
            self.assertEqual(MR.default_export_dir().resolve(), want)
            self.assertEqual(self._cli_output_default(ROOT / "backend"), want)
            self.assertEqual(self._cli_output_default(tempfile.gettempdir()), want)
        with mock.patch.dict(os.environ, {"MQ_MINIROCKET_EXPORT_DIR": str(Path(tempfile.gettempdir()) / "mr_exp")}):
            self.assertEqual(self._cli_output_default(ROOT / "backend"), (Path(tempfile.gettempdir()) / "mr_exp").resolve())

    def test_importer_without_expected_model_rejects(self):
        import numpy as np
        from masterquo.lab import minirocket_v2 as MR
        with tempfile.TemporaryDirectory() as d:
            now = int(time.time())
            MR.write_result(Path(d) / MR.NativeResultImporter.NAME, 3, "ab" * 32, "XAUUSD-", "M1", now - 60, now, "UTC", np.zeros(3))
            r = MR.NativeResultImporter(d, None, "XAUUSD-", "M1").poll()
            self.assertEqual(r["status"], "REJECTED")
            self.assertIn("EXPECTED_MODEL_UNKNOWN", r["reason"])
            self.assertEqual(MR.NativeResultImporter(d, "ab" * 32, "XAUUSD-", "M1").poll()["status"], "IMPORTED")


# ------------------------------------------------------------------------------------------------------------ I0517 / I0518
SR_HDR = {"depth": 10, "retention": 290, "loopback": 300, "width_pct": 5.0, "max_selected": 10, "source": "WICK"}


def _flow_export(path, bars, sr=True, shift_sup_lo=False):
    from masterquo.lab.flow_context import heikin as HF
    from masterquo.lab.flow_context import native as NV
    from masterquo.lab.flow_context import sr_channels as SR
    from masterquo.lab.flow_context import stop_distance as SD
    hf = HF.heikin_series(bars, {"ma1": "EMA", "p1": 10, "ma2": "EMA", "p2": 5}, 0.01)["rows"]
    sd = SD.series(bars, {"period": 20, "method": "SMA", "factor": 1.5}, 0.01, 0.01)
    piv = SR.pivots(bars, 10, "WICK")
    rows, shifted = [], False
    for i, (b, r, s) in enumerate(zip(bars, hf, sd)):
        nr = SR.nearest(SR.channels_at(bars, i, SR_HDR, piv=piv), b["c"])
        row = {"bar_time": b["open_utc"], "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "ha_o": r["o"], "ha_h": r["h"], "ha_l": r["l"],
               "ha_c": r["c"], "sd_range": s["range_points"], "sd_avg": s["average_points"], "sd_sugg": s["suggested_points"]}
        for kind, pre in (("support", "sup"), ("resistance", "res"), ("inside", "in")):
            band = nr[kind]
            row[f"{pre}_lo"], row[f"{pre}_hi"] = (band["lo"], band["hi"]) if band else (None, None)
        if shift_sup_lo and not shifted and i > 150 and row["sup_lo"] is not None:
            row["sup_lo"] += 1.0
            shifted = True
        rows.append(row)
    hdr = {"seq": 3, "symbol": "XAUUSD-", "tf": "M15", "point": 0.01, "tick": 0.01, "written_at_utc": time.time(), "seed_origin": bars[0]["open_utc"],
           "heikin": {"ma1": "EMA", "p1": 10, "ma2": "EMA", "p2": 5}, "stopdistance": {"period": 20, "method": "SMA", "factor": 1.5}}
    if sr:
        hdr["sr"] = SR_HDR
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    NV.write_export(Path(path), hdr, rows)
    return shifted


class TestFlowSRParity(unittest.TestCase):
    """I0517: compare() porównywał tylko Heikin i StopDistance - kolumny S/R (MQ_SRChannels) eksportowane, nigdy porównywane."""

    def test_sr_columns_are_compared(self):
        from masterquo.lab.flow_context import native as NV
        bars = NV.frozen_inputs(300)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "ok.txt"
            _flow_export(p, bars)
            r = NV.compare(NV.parse_export(p.read_bytes()))
            self.assertEqual(r["status"], "OWN_IMPLEMENTATIONS_MATCH", r)
            self.assertEqual(r["sr_status"], "MATCH")
            p2 = Path(d) / "bad.txt"
            self.assertTrue(_flow_export(p2, bars, shift_sup_lo=True))
            r = NV.compare(NV.parse_export(p2.read_bytes()))
            self.assertEqual(r["status"], "MISMATCH")
            self.assertIn("sup_lo", {x["field"] for x in r["first"]})
            p3 = Path(d) / "nosr.txt"
            _flow_export(p3, bars, sr=False, shift_sup_lo=True)
            r = NV.compare(NV.parse_export(p3.read_bytes()))
            self.assertEqual(r["status"], "OWN_IMPLEMENTATIONS_MATCH")              # no configuration -> S/R not guessed
            self.assertTrue(r["sr_status"].startswith("NOT_COMPARED"))

    def test_collector_header_declares_sr_config(self):
        src = (ROOT / "mql5" / "FlowContext" / "Scripts" / "MQ_FlowCollector.mq5").read_text(encoding="utf-8")
        self.assertIn('\\"sr\\":{', src)
        self.assertIn('iCustom(_Symbol, _Period, "PMW\\\\MQ_SRChannels", SR_DEPTH, SR_RETENTION, SR_LOOPBACK, SR_WIDTH_PCT, SR_MAX_SELECTED)', src)


class TestFlowNativeParityExport(unittest.TestCase):
    """I0518: native-parity czytało wyłącznie <fixtures>/native_export.txt (kolektor pisze PMW_FLOW_EXPORT.txt)."""

    def test_parity_uses_given_export(self):
        from masterquo.lab.flow_context import native as NV
        with tempfile.TemporaryDirectory() as d:
            exp = Path(d) / "files" / "PMW" / "PMW_FLOW_EXPORT.txt"
            _flow_export(exp, NV.frozen_inputs(120))
            fx = Path(d) / "fixtures"
            fx.mkdir()
            r = NV.parity(fx, None, export=exp)
            self.assertEqual(r["OWN_IMPLEMENTATIONS"]["status"], "OWN_IMPLEMENTATIONS_MATCH")
            self.assertEqual(NV.parity(fx, None)["OWN_IMPLEMENTATIONS"]["status"], "NOT_RUN")

    def test_cli_defaults_from_mt5_files_dir(self):
        from masterquo.lab.flow_context import cli as FC
        from masterquo.lab.flow_context import native as NV
        with tempfile.TemporaryDirectory() as d:
            files = Path(d) / "Files"
            _flow_export(files / "PMW" / "PMW_FLOW_EXPORT.txt", NV.frozen_inputs(120))
            fx = Path(d) / "fixtures"
            fx.mkdir()
            out = []
            with mock.patch.dict(os.environ, {"MQ_MT5_FILES_DIR": str(files)}), mock.patch.object(FC, "_print", out.append):
                self.assertEqual(FC.main(["native-parity", "--fixtures", str(fx)]), 0)
            self.assertEqual(out[0]["OWN_IMPLEMENTATIONS"]["status"], "OWN_IMPLEMENTATIONS_MATCH")


# ------------------------------------------------------------------------------------------------------------------------ I0195
class TestKronosOneProducerInCoordinator(unittest.TestCase):
    """I0195: kronos_rows nadawał family 'kronos:Kronos-small@M5' (resolve() zwraca bez zmian) - z Quant ASSIST rekord Kronos z migawki
    Quant nie był odfiltrowany (dwa rekordy jednego producenta; z required 'kronos:Kronos-small' rekord Quant dawał PASS)."""

    NOW = 1_800_000_000.0

    def _rec(self, direction="UP"):
        from masterquo.modelhub import contract as C
        from masterquo.timeutil import from_epoch, iso
        return C.make(instrument="XAUUSD", symbol="XAUUSD-", timeframe="M5", model_name="Kronos-small", model_version="r1", task_type="REGRESSION",
                      task="KRONOS_CLOSE_PATH_H12_M5", horizon_bars=12, unit="price", state="READY", data_time=iso(from_epoch(self.NOW - 30)),
                      result={"last_close": 100.0, "pred_close": 101.0, "delta_price": 1.0, "delta_pct": 1.0, "direction": direction,
                              "neutral_band": 0.1, "forecast_id": "f1"})

    def _coord(self, quant_rows):
        from masterquo.decision.coordinator import DecisionCoordinator
        from masterquo.tsfm import predictions as TP
        co = DecisionCoordinator.__new__(DecisionCoordinator)                          # _preds() needs only these attributes
        co.instrument_fn, co.families = (lambda: "XAUUSD"), None
        co.quant = SimpleNamespace(assist_active=lambda: True, coordinator_predictions=lambda inst: quant_rows)
        kr = SimpleNamespace(settings=SimpleNamespace(get=lambda: SimpleNamespace(strategy_use={})))
        co.extra_providers = [lambda inst: TP.kronos_rows(kr, inst)]
        return co

    def test_kronos_rows_carry_canonical_id(self):
        from masterquo.quant import ids as I
        from masterquo.tsfm import predictions as TP
        kr = SimpleNamespace(settings=SimpleNamespace(get=lambda: SimpleNamespace(strategy_use={})))
        with mock.patch("masterquo.kronos.predictions.contract_predictions", return_value=[self._rec()]), \
                mock.patch("masterquo.kronos.predictions.model_name", return_value="Kronos-small"):
            rows = TP.kronos_rows(kr, "XAUUSD")
        self.assertEqual(rows[0]["family"], "kronos:Kronos-small@M5")                 # identifier at the coordinator boundary unchanged
        self.assertEqual(I.canonical(rows[0]), "kronos:Kronos-small")
        self.assertTrue(rows[0]["no_required"])

    def test_quant_duplicate_dropped_and_required_blocks(self):
        from masterquo.decision.coordinator import _mid, evaluate_models
        from masterquo.quant import ids as I
        q = dict(self._rec(), canonical_id="kronos:Kronos-small", model_id="kronos:Kronos-small")
        other = dict(self._rec(), canonical_id="tsfm:chronos2", model_id="tsfm:chronos2", model_name="Chronos-2")
        co = self._coord([q, other])
        with mock.patch("masterquo.kronos.predictions.contract_predictions", return_value=[self._rec()]), \
                mock.patch("masterquo.kronos.predictions.model_name", return_value="Kronos-small"):
            preds = co._preds()
        kron = [p for p in preds if I.canonical(p) == "kronos:Kronos-small"]
        self.assertEqual(len(kron), 1)                                                    # one record per producer (was 2)
        self.assertTrue(kron[0]["no_required"])
        self.assertIn("tsfm:chronos2", {_mid(p) for p in preds})                          # other Quant records untouched
        ev = lambda req: evaluate_models(preds, "BUY", required=set(req), assist_threshold=0.6, max_age_s=900, now=self.NOW)
        _, reasons = ev({"kronos:Kronos-small"})
        self.assertIn("MODEL_REQUIRED_UNAVAILABLE:kronos:Kronos-small", reasons)          # was PASS through the Quant record
        self.assertEqual(ev(())[1], [])

    def test_assist_or_hold_records_are_never_dropped(self):
        from masterquo.quant import ids as I
        q = dict(self._rec(), canonical_id="kronos:Kronos-small", model_id="kronos:Kronos-small", use="ASSIST")
        h = dict(self._rec(), canonical_id="kronos:Kronos-small", model_id="kronos:Kronos-small", quant_hold="x")
        co = self._coord([q, h])
        with mock.patch("masterquo.kronos.predictions.contract_predictions", return_value=[self._rec()]), \
                mock.patch("masterquo.kronos.predictions.model_name", return_value="Kronos-small"):
            preds = co._preds()
        self.assertEqual(len([p for p in preds if I.canonical(p) == "kronos:Kronos-small"]), 3)


# ------------------------------------------------------------------------------------------------------------ I0616 / I0626
class TestScalpWorkerContract(unittest.TestCase):
    """I0616 (zadanie A) / I0626 (zadanie B): worker liczył kontrakt z symbolu/ticka zapisanych we wpisie rejestru, żądanie bota ich nie
    zawierało - zmiana symbolu brokera / tick size nigdy nie dawała CONTRACT_MISMATCH (jak dla prognoz świec)."""

    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)
        p = mock.patch.dict(os.environ, {"MQ_INSTRUMENT": "XAUUSD"})
        p.start()
        self.addCleanup(p.stop)
        from gold_candles_runtime import scalp_features as SF
        from gold_candles_runtime import worker as W
        from gold_candles_runtime.scalp_infer import registry_path, scalp_dir
        self.W = W
        W._scalp_cache.clear()
        W._scalp_cache.update(run_id=None, model=None)
        rd = scalp_dir() / "runs" / "R1"
        rd.mkdir(parents=True)
        entry = {"run_id": "R1", "run_dir": str(rd), "data_kind": "REAL_USER_DATA", "task_a_status": "ACCEPTED", "artifacts": {},
                 "symbol": "XAUUSD-", "tick_size": 0.01, "contract_hash": SF.contract_hash("XAUUSD-", 0.01),
                 "setup_model": {"features": ["x"], "threshold": 0.5, "selected": "LR"}}
        registry_path().write_text(json.dumps({"schema": "masterquo-scalp-registry-1", "active": "R1", "history": [], "runs": {"R1": entry}}),
                                   encoding="utf-8")

    def test_forecast_contract_mismatch(self):
        ans = self.W.scalp_forecast({"m1": [], "symbol": "GOLD.pro", "tick_size": 0.01})
        self.assertEqual(ans["status"], "UNAVAILABLE")
        self.assertTrue(ans["reason"].startswith("CONTRACT_MISMATCH"), ans)
        ans = self.W.scalp_forecast({"m1": [], "symbol": "XAUUSD-", "tick_size": 0.001})
        self.assertTrue(ans["reason"].startswith("CONTRACT_MISMATCH"), ans)
        self.assertEqual(self.W.scalp_forecast({"m1": []})["reason"], "REQUEST_WITHOUT_CONTRACT")
        self.assertFalse(ans["execution_permission"])

    def test_setup_quality_contract_mismatch(self):
        ans = self.W.setup_quality({"features": {"x": 1.0}, "symbol": "GOLD.pro", "tick_size": 0.01})
        self.assertEqual(ans["status"], "UNAVAILABLE")
        self.assertTrue(ans["reason"].startswith("CONTRACT_MISMATCH"), ans)
        self.assertFalse(ans["pass"])
        self.assertEqual(self.W.setup_quality({"features": {"x": 1.0}})["reason"], "REQUEST_WITHOUT_CONTRACT")

    def test_bot_requests_carry_symbol_and_tick(self):
        from masterquo.scalp.service import ScalpService
        sent = []
        sc = ScalpService.__new__(ScalpService)
        sc.inst = "XAUUSD"
        sc.registry = lambda: {"active": "R1", "runs": {"R1": {"setup_model": {"features": []}}}}
        sc.forecast = SimpleNamespace(proc=object(), _ask=lambda req, t: sent.append(req) or {"status": "SHADOW"})
        sc.bridge = SimpleNamespace(symbol_info={"point": 0.01, "trade_tick_size": 0.01},
                                    bars=lambda tf, n, include_forming=False: [{"open_utc": "2026-11-24T10:00:00Z", "o": 1, "h": 1, "l": 1, "c": 1, "tv": 1}])
        sc.cfg_store = SimpleNamespace(get=lambda: SimpleNamespace(mt5=SimpleNamespace(symbol="XAUUSD-")))
        sc.forecasts()
        sc.setup_quality({"features": {}})
        self.assertEqual([(r["cmd"], r.get("symbol"), r.get("tick_size")) for r in sent],
                         [("scalp_forecast", "XAUUSD-", 0.01), ("setup_quality", "XAUUSD-", 0.01)])


# ------------------------------------------------------------------------------------------------------------------------ I0621
class TestScalpForecastCache(unittest.TestCase):
    """I0621: dwa identyczne zapytania scalp_forecast na każde M1 (ScalpService.tick i Quant scalp_a), każde liczyło sha256 artefaktów."""

    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)

    def _svc(self, bars):
        from masterquo.scalp.service import ScalpService
        calls = []
        sc = ScalpService.__new__(ScalpService)
        sc.inst = "XAUUSD"
        sc.registry = lambda: {"active": "R1", "runs": {}}
        sc.forecast = SimpleNamespace(proc=object(), _ask=lambda req, t: calls.append(req) or {"status": "SHADOW", "n": len(calls)})
        sc.bridge = SimpleNamespace(symbol_info={"point": 0.01, "trade_tick_size": 0.01}, bars=lambda tf, n, include_forming=False: list(bars))
        sc.cfg_store = SimpleNamespace(get=lambda: SimpleNamespace(mt5=SimpleNamespace(symbol="XAUUSD-")))
        return sc, calls

    @staticmethod
    def _now(text):
        from datetime import datetime
        return mock.patch("masterquo.scalp.service.utcnow", return_value=datetime.fromisoformat(text))

    def test_one_worker_request_per_closed_m1(self):
        # merge with I0754 (as_of): the newest M1 closed 30 s ago (within FORECAST_CACHE_FRESH_S) - the cache stays valid for its request
        bars = [{"open_utc": "2026-11-24T10:00:00Z", "o": 1.0, "h": 1.0, "l": 1.0, "c": 1.0, "tv": 1}]
        sc, calls = self._svc(bars)
        with self._now("2026-11-24T10:01:30+00:00"):
            a, b = sc.forecasts(), sc.forecasts()
        self.assertEqual(len(calls), 1)
        self.assertEqual(a, b)
        self.assertEqual(calls[0]["as_of"], "2026-11-24T10:01:30Z")     # I0754: the worker judges feed freshness
        bars.append({"open_utc": "2026-11-24T10:01:00Z", "o": 1.0, "h": 1.1, "l": 1.0, "c": 1.1, "tv": 1})
        with self._now("2026-11-24T10:02:10+00:00"):
            sc.forecasts()
        self.assertEqual(len(calls), 2)

    def test_frozen_feed_is_asked_again(self):
        # merge I0621 + I0754: same bars, but the newest M1 closed minutes ago - never a cached answer, the worker gets the current
        # as_of each time (and answers STALE_DATA in the real worker)
        bars = [{"open_utc": "2026-11-24T10:00:00Z", "o": 1.0, "h": 1.0, "l": 1.0, "c": 1.0, "tv": 1}]
        sc, calls = self._svc(bars)
        with self._now("2026-11-24T10:01:30+00:00"):
            sc.forecasts()
        with self._now("2026-11-24T10:05:00+00:00"):
            sc.forecasts()
        self.assertEqual([r["as_of"] for r in calls], ["2026-11-24T10:01:30Z", "2026-11-24T10:05:00Z"])

    def test_worker_reuses_checksum_until_file_changes(self):
        from gold_candles_runtime import scalp_infer as SI
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "a.bin"
            f.write_bytes(b"abc")
            cache = {}
            with mock.patch.object(SI, "sha256_file", wraps=SI.sha256_file) as sh:
                h1 = SI.cached_sha256(f, cache)
                h2 = SI.cached_sha256(f, cache)
                self.assertEqual(h1, h2)
                self.assertEqual(sh.call_count, 1)
                f.write_bytes(b"abcd")
                self.assertNotEqual(SI.cached_sha256(f, cache), h1)
                self.assertEqual(sh.call_count, 2)


# ------------------------------------------------------------------------------------------------------------------------ I0072
class TestLabSkipsFixtureOnRealData(unittest.TestCase):
    """I0072: _active_models brał najnowszy model rodziny bez filtra roli - model fixture_only (trening na danych syntetycznych) działał
    na danych REAL bota i trafiał do Quant jako rekord REAL."""

    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)

    def _svc(self, models, synthetic=False, pinned=None):
        from masterquo.lab import protocol as P
        from masterquo.lab.service import LabService
        root = Path(self.td.dir) / "lab"
        (root / "models" / "XAUUSD").mkdir(parents=True)
        if pinned:
            P.pointer_path(root, "XAUUSD").write_text(json.dumps({"active": pinned, "history": []}), encoding="utf-8")
        svc = LabService.__new__(LabService)
        svc.trainer = SimpleNamespace(root=root, models=lambda asset: list(models))
        svc._models = {}
        svc.bridge = SimpleNamespace(synthetic=synthetic)
        svc.cfg_store = SimpleNamespace(get=lambda: SimpleNamespace(synthetic_demo=False))
        return svc

    def _ids(self, svc):
        with mock.patch("masterquo.lab.service.load_artifact", side_effect=lambda p, **kw: (SimpleNamespace(family="LOGREG"), {"model_id": Path(p).name})):
            return [got[2]["model_id"] for got in svc._active_models("XAUUSD")]

    MODELS = ({"model_id": "fx", "family": "LOGREG", "role": "fixture_only", "path": "fx", "trained_at": "2026-11-24"},
              {"model_id": "re", "family": "LOGREG", "role": "research", "path": "re", "trained_at": "2026-11-20"})

    def test_fixture_model_skipped_on_real_data(self):
        svc = self._svc(self.MODELS)
        self.assertEqual(self._ids(svc), ["re"])                       # newest NON-fixture model of the family (was fx)
        self.assertTrue(any("fixture_only" in e for e in svc._artifact_errors))

    def test_pinned_fixture_model_not_replaced(self):
        svc = self._svc(self.MODELS, pinned={"LOGREG": "fx"})
        self.assertEqual(self._ids(svc), [])                           # explicit pin: skipped, no silent switch to another artefact

    def test_fixture_mode_unchanged(self):
        self.assertEqual(self._ids(self._svc(self.MODELS, synthetic=True)), ["fx"])


# ------------------------------------------------------------------------------------------------------------ I0163 / I0180
def _csv(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("time_open_utc,open,high,low,close,tick_volume,spread_points\n")
        fh.writelines(f"{r['open_utc']},{r['o']},{r['h']},{r['l']},{r['c']},10,20\n" for r in rows)


class TestIndicatorContextTrainServeParity(unittest.TestCase):
    """I0163: trening liczył ATR14 z 40 zamkniętych M5 w chwili decyzji, na żywo podawany jest ATR zakresu zamrożony przy RANGE_ARMED
    (plan['range']['atr_m5']) - mianownik cech SAR / IQ. Schemat SCALP_INDICATOR_CONTEXT_V2; artefakty V1 abstynują."""

    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)

    def test_replay_cycles_carry_decision_inputs(self):
        import sys
        sys.path.insert(0, str(ROOT / "tests" / "scalp"))
        import scenario as S
        from masterquo.scalp import replay
        from masterquo.scalp import strategy as st
        p = st.load_profile()
        p["context_filter"]["enabled"]["value"] = False
        bars, _ = S.build(p)
        res = replay.run(bars, p, 0.01, {"commission_price_side": 0.035, "slippage_price": 0.02})
        self.assertTrue(res["cycles"])
        for c in res["cycles"]:
            self.assertGreater(c["range_atr_m5"], 0)
            self.assertIsNotNone(c["ref_close_bid"])

    def test_dataset_uses_decision_inputs(self):
        from datetime import UTC, datetime, timedelta

        from masterquo.extind import trainer as T
        ds = Path(self.td.dir) / "ds"
        ds.mkdir()
        t0 = datetime(2026, 10, 19, 8, 0, tzinfo=UTC)
        m5 = [{"open_utc": (t0 + timedelta(minutes=5 * k)).isoformat().replace("+00:00", "Z"), "o": 100 + k * .01, "h": 100.3 + k * .01,
               "l": 99.7 + k * .01, "c": 100 + k * .01} for k in range(60)]
        _csv(ds / "XAUUSD_M1.csv", m5[:5])
        _csv(ds / "XAUUSD_M5.csv", m5)
        _csv(ds / "XAUUSD_M15.csv", m5[::3])
        (ds / "source_metadata.json").write_text(json.dumps({"instrument": "XAUUSD", "file_prefix": "XAUUSD", "symbol": "XAUUSD-", "tick_size": 0.01,
                                                             "spec": {"point": 0.01, "trade_contract_size": 100}, "data_kind": "SYNTHETIC_TEST"}),
                                                 encoding="utf-8")
        dec = (t0 + timedelta(minutes=5 * 50)).isoformat().replace("+00:00", "Z")
        cyc = {"setup_id": "S1", "range_id": "R1", "direction": "BUY", "decision_time": dec, "fill_time": dec, "exits": [{"time": dec}],
               "fill": 100.9, "features": {}, "tp1_before_sl": True, "net_r": 1.0, "ambiguous": False, "ref_close_bid": 100.5, "range_atr_m5": 2.0}
        old = {k: v for k, v in cyc.items() if k not in ("ref_close_bid", "range_atr_m5")}
        with mock.patch("masterquo.scalp.replay.run", return_value={"cycles": [cyc, dict(old, setup_id="S2")]}):
            data = T.build_dataset("XAUUSD", ds, commission=0.5, log=lambda m: None)
        r1, r2 = data["rows"]
        self.assertEqual(r1["atr_m5"], 2.0)                                       # the frozen range ATR the live model gets (was ATR14 of 40 M5)
        self.assertNotEqual(r2["atr_m5"], 2.0)                                    # cycle without the field: legacy ATR, counted
        self.assertEqual(data["legacy_atr_rows"], 1)

    def _man(self, schema):
        from masterquo.extind import features as F
        spec = F.default_spec(("BASE",))
        return {"instrument": "XAUUSD", "feature_schema": schema, "spec": spec, "feature_order": F.feature_names(spec), "platt": [1.0, 0.0],
                "task_id": F.TASK_ID, "threshold": 0.5, "groups": ["BASE"], "role": "shadow_candidate", "parity": {"status": "OK"}}

    def test_old_schema_abstains(self):
        from datetime import UTC, datetime

        import numpy as np
        from masterquo.extind import features as F
        from masterquo.extind import trainer as T
        obj = {"prep": SimpleNamespace(transform=lambda X: X), "model": SimpleNamespace(predict_proba=lambda Z: np.tile([0.4, 0.6], (len(Z), 1)))}
        snap = {"decision_time": datetime(2026, 10, 19, 12, tzinfo=UTC), "side": "BUY", "price": 100.0, "atr_m5": 1.0, "base": {"er10": 0.3}, "bars": {}, "ext": {}}
        old = T.ContextModel(self._man("SCALP_INDICATOR_CONTEXT_V1"), obj).predict(snap, "XAUUSD")
        self.assertEqual(old["status"], "ABSTAIN")
        # after the merge with scalp_extind (I0164/I0784, the same V2 bump): the reason also names the expected schema
        self.assertEqual(old["reason"], "FEATURE_SCHEMA_MISMATCH:SCALP_INDICATOR_CONTEXT_V1!=SCALP_INDICATOR_CONTEXT_V2")
        self.assertEqual(T.ContextModel(self._man(F.FEATURE_SCHEMA), obj).predict(snap, "XAUUSD")["status"], "READY_INFERENCE")
        self.assertEqual(F.FEATURE_SCHEMA, "SCALP_INDICATOR_CONTEXT_V2")

    def test_activate_refuses_old_schema_without_writing(self):
        from masterquo.extind import trainer as T
        rd = Path(self.td.dir) / "run1"
        rd.mkdir()
        (rd / "model_BASE.json").write_text(json.dumps(self._man("SCALP_INDICATOR_CONTEXT_V1")), encoding="utf-8")
        reg_p = T.root("XAUUSD") / "registry.json"
        reg = {"schema": "pmw-indicator-context-registry-1", "active": None, "runs": {"R1": {"run_dir": str(rd), "artifacts": ["model_BASE.json"]}}}
        reg_p.write_text(json.dumps(reg), encoding="utf-8")
        before = reg_p.read_bytes()
        with self.assertRaises(ValueError) as cm:
            T.activate("XAUUSD", "R1", "BASE")
        self.assertIn("NOT_ACTIVATABLE_SCHEMA", str(cm.exception))
        self.assertEqual(reg_p.read_bytes(), before)

    def test_api_reports_current_schema(self):
        src = (ROOT / "backend" / "masterquo" / "api" / "app.py").read_text(encoding="utf-8")
        self.assertFalse('"schema": "SCALP_INDICATOR_CONTEXT_V1"' in src)


class TestIQLevelsWithoutVerifiedOffset(unittest.TestCase):
    """I0180: bez zweryfikowanego offsetu serwera cały odczyt dostawał TIME_BASIS_UNVERIFIED i as_of go wykluczał - także czyste poziomy
    cenowe (od offsetu niezależne). Okna Star bez czasu mają być NaN (nieznane), nigdy 0."""

    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        from masterquo.extind import mapping, service
        self.m = mapping
        self.db = Database()
        self.svc = service.ExtIndService(ConfigStore(), self.db)                 # no bridge -> no verified server offset

    def test_levels_usable_without_verified_offset(self):
        from datetime import UTC, datetime, timedelta

        from masterquo.extind import contract as C
        from test_ind_context import _env_body
        t0 = datetime(2026, 10, 19, 10, 0, tzinfo=UTC)
        self.m.save_mapping("IQ_GOLD_GANN", {"product_version": "1.0", "approved": True, "verified_examples": [{"name": "IQG_major_1", "chart": 2650.0}],
                                             "rules": [{"prefix": "IQG_major", "type": "HLINE", "kind": "LEVEL", "role": "MAJOR"}]})
        self.svc.ingest_bytes(C.wrap(_env_body(basis="BROKER_SERVER")), now=t0)
        s = self.svc.as_of("IQ_GOLD_GANN", "XAUUSD", t0 + timedelta(minutes=1))
        self.assertIsNotNone(s)                                                   # was None (whole read excluded)
        self.assertEqual(s["time_status"], "TIME_BASIS_UNVERIFIED")
        self.assertEqual([x["price"] for x in s["levels"]], [2650.0])
        self.db.execute("UPDATE extind_snapshots SET time_status='NOT_DECODED'")
        self.assertIsNone(self.svc.as_of("IQ_GOLD_GANN", "XAUUSD", t0 + timedelta(minutes=1)))   # only OK / TIME_BASIS_UNVERIFIED

    def test_star_windows_unknown_without_verified_time(self):
        import math
        from datetime import UTC, datetime

        from masterquo.extind import features as F
        t = datetime(2026, 10, 19, 12, tzinfo=UTC)
        star = {"levels": [{"kind": "LEVEL", "price": 101.0}, {"kind": "LEVEL", "price": 99.0}],
                "windows": [{"scheduled_start_utc": None, "scheduled_end_utc": None, "source_time_raw": [1, 2]}],
                "available_at": "2026-10-19T11:59:00Z", "time_status": "TIME_BASIS_UNVERIFIED"}
        snap = {"decision_time": t, "side": "BUY", "price": 100.0, "atr_m5": 1.0, "base": {}, "bars": {}, "ext": {"IQ_STAR_LINES": star}}
        f = F.build_indicator_context_features(snap, F.default_spec(("IQ_STAR_LINES",)))["features"]
        self.assertTrue(math.isnan(f["star_in_window"]))                          # was 0.0 (a non-schedule looked like 'outside every window')
        self.assertTrue(math.isnan(f["star_min_to_start"]) and math.isnan(f["star_min_to_end"]))
        self.assertAlmostEqual(f["star_up_dist_atr"], 1.0)
        ok = dict(star, time_status="OK", windows=[{"scheduled_start_utc": t.timestamp() - 60, "scheduled_end_utc": t.timestamp() + 600}])
        g = F.build_indicator_context_features(dict(snap, ext={"IQ_STAR_LINES": ok}), F.default_spec(("IQ_STAR_LINES",)))["features"]
        self.assertEqual(g["star_in_window"], 1.0)

    def test_agent_context_drops_windows_without_time(self):
        from masterquo.engine.service import EngineService
        star = {"snapshot_id": "s1", "available_at": "2026-10-19T11:59:00Z", "time_status": "TIME_BASIS_UNVERIFIED",
                "levels": [{"kind": "LEVEL", "price": 101.0}], "windows": [{"scheduled_start_utc": None, "scheduled_end_utc": None}]}
        st = {a: {"identity_status": "IDENTIFIED", "source_status": "RECEIVING", "mapping_status": "MAPPING_APPROVED", "runtime_status": "READY_RUNTIME"}
              for a in ("IQ_GOLD_GANN", "IQ_STAR_LINES", "PAL02M")}
        ext = SimpleNamespace(status=lambda inst: {"adapters": st}, as_of=lambda a, inst, t: star if a == "IQ_STAR_LINES" else None)
        eng = EngineService.__new__(EngineService)
        eng.extind = ext
        eng.bridge = SimpleNamespace(bars=lambda tf, n, include_forming=False: [])
        eng.cfg_store = SimpleNamespace(get=lambda: SimpleNamespace(assets=SimpleNamespace(active="XAUUSD")))
        ctx = eng._indicator_context({"as_of": "2026-10-19T12:00:00Z"})
        src = ctx["sources"]["IQ_STAR_LINES"]
        self.assertEqual(src["windows"], [])
        self.assertEqual(src["time_status"], "TIME_BASIS_UNVERIFIED")
        self.assertNotIn("IND-K04", ctx["applied_rules"])
        self.assertIn("IND-K02", ctx["applied_rules"])


# ------------------------------------------------------------------------------------------------------------------------ I0864
class TestTsfmBandIncomplete(unittest.TestCase):
    """I0864 (wariant bezpieczny wg sceptyka): brak point / ATR liczony jako 0 w paśmie neutralnym. Pasmo, kierunek, księga i settle bez
    zmian; niepełne pasmo oznaczone polem tekstowym band_incomplete_reason poza `result`; tylko rola REQUIRED wstrzymuje wejście."""

    def setUp(self):
        import test_tsfm_bot as TB
        self.TB = TB.TestService("test_coordinator_rows_active_role")
        self.TB.setUp()
        self.addCleanup(self.TB.tearDown)
        self.svc = svc = self.TB.make()
        svc.settings.update({"direction_band_min_points": 5.0})
        p = mock.patch.object(svc, "_point", return_value=(None, None))           # symbol_meta read failed (cached None for an hour)
        p.start()
        self.addCleanup(p.stop)
        svc.tick()
        self.TB.run_queue()

    def test_forecast_marked_band_and_ledger_unchanged(self):
        fc = self.svc.latest[("chronos2", "XAUUSD", "M5")]
        self.assertEqual(fc["band_incomplete_reason"], "POINT_MISSING")
        self.assertIsInstance(fc["neutral_band"], float)                          # the rule itself is unchanged (missing point = 0)
        row = self.svc.db.one("SELECT neutral_band, direction FROM tsfm_forecasts WHERE forecast_id=?", (fc["id"],))
        self.assertEqual((row["neutral_band"], row["direction"]), (fc["neutral_band"], fc["direction"]))

    def test_contract_rows_validate(self):
        from masterquo.modelhub import contract as C
        from masterquo.tsfm import predictions as TP
        rows = TP.contract_predictions(self.svc, "XAUUSD")                       # must not raise (None / bool in result would)
        ready = [r for r in rows if r["state"] == "READY"]
        self.assertTrue(ready)
        for r in rows:
            C.validate(r)
        for r in ready:
            self.assertEqual(r["band_incomplete_reason"], "POINT_MISSING")
            self.assertNotIn("band_incomplete_reason", r["result"])
            self.assertIsInstance(r["result"]["neutral_band"], float)

    def _rows(self):
        from masterquo.tsfm import predictions as TP
        self.svc.settings.update({"models": {"chronos2": {"use": {"ACTIVE": {"use": "REQUIRED", "timeframe": "M5"}}},
                                             "granite_ttm": {"use": {"ACTIVE": {"use": "ASSIST", "timeframe": "M5"}}}}})
        with mock.patch.object(TP, "approval_ok", return_value=(True, None)):
            return TP.coordinator_rows(self.svc, "XAUUSD")

    def _ev(self, rows, side, required=()):
        from masterquo.decision.coordinator import evaluate_models
        return evaluate_models(rows, side, required=set(required), assist_threshold=0.6, max_age_s=900, now=self.TB.now[0])[1]

    def test_required_blocks_assist_unchanged(self):
        rows = self._rows()
        by = {r["family"]: r for r in rows}
        self.assertTrue({"tsfm:chronos2", "tsfm:granite_ttm"} <= set(by))       # every TSFM row stays in the coordinator input
        self.assertEqual(by["tsfm:chronos2"]["state"], "STALE")                  # REQUIRED with an incomplete band -> unavailable
        self.assertEqual(by["tsfm:granite_ttm"]["state"], "READY")               # ASSIST row kept as it is
        up = by["tsfm:granite_ttm"]["result"]["direction"]
        self.assertEqual(up, "UP")
        self.assertIn("MODEL_REQUIRED_UNAVAILABLE:tsfm:chronos2", self._ev(rows, "BUY"))      # was PASS (UP confirms BUY)
        self.assertIn("MODEL_ASSIST_HOLD:tsfm:granite_ttm", self._ev(rows, "SELL"))          # the other model's hold is still there

    def test_required_by_decision_config_blocks(self):
        rows = [dict(r, use="SHADOW") for r in self._rows() if r["family"] == "tsfm:granite_ttm"]
        self.assertIn("MODEL_REQUIRED_NOT_CONFIRMING:tsfm:granite_ttm", self._ev(rows, "BUY", required={"tsfm:granite_ttm"}))
        legacy = [{k: v for k, v in r.items() if k != "band_incomplete_reason"} for r in rows]           # stored inputs without the field
        self.assertEqual(self._ev(legacy, "BUY", required={"tsfm:granite_ttm"}), [])

    def test_sh_required_waits_assist_unchanged(self):
        from masterquo.tsfm import predictions as TP
        self.svc.settings.update({"models": {"chronos2": {"use": {"SCALPING": {"use": "REQUIRED", "timeframe": "M5"}}}}})
        with mock.patch.object(TP, "approval_ok", return_value=(True, None)):
            ctx = TP.context(self.svc, "chronos2", "XAUUSD", "SCALPING", side="BUY")
        self.assertEqual(ctx["relation"], "ZGODNY")                              # relation / direction unchanged
        su = TP.apply_to_setup({"status": "READY", "side": "BUY"}, ctx)
        self.assertEqual(su["status"], "WAIT")
        a = dict(ctx, use="ASSIST")
        self.assertEqual(TP.apply_to_setup({"status": "READY", "side": "BUY"}, a)["status"], "READY")


# ------------------------------------------------------------------------------------------------------------------------ I0045
class TestScalpLabelsUnknownCommission(unittest.TestCase):
    """I0045: bramka scalp przy nieznanej prowizji blokuje, ale etykiety SHADOW / ML scalp / NSS liczono z prowizją 0 i zapisywano jako
    zwykłe LABELED (trening na wyniku 'netto' bez prowizji)."""

    T = 1_800_000_000.0

    def _svc(self, commission):
        from masterquo.scalp import strategy as st
        from masterquo.scalp.service import ScalpService
        sc = ScalpService.__new__(ScalpService)
        sc.prof = st.load_profile()
        sc.cfg_store = SimpleNamespace(get=lambda: SimpleNamespace(scalp=SimpleNamespace(commission_per_lot_side=commission, slippage_ticks=2.0)))
        sc.bridge = SimpleNamespace(symbol_info={"trade_contract_size": 100.0, "trade_tick_size": 0.01})
        return sc

    def _settle(self, commission):
        plan = {"decision_ts": self.T, "direction": "BUY", "sl": 99.0, "tp1": 101.0, "tp2": 102.0, "fill_shadow": 100.0,
                "economics": {"risk_per_unit": 1.0}, "sizing": {}}
        P = SimpleNamespace(index={self.T: 0}, t=[self.T, self.T + 60])
        with mock.patch("masterquo.scalp.replay.walk", return_value={"exits": [(1.0, 101.0, self.T + 60, "TP1")], "ambiguous": False}), \
                mock.patch("masterquo.scalp.replay.pnl", return_value=0.9):
            return self._svc(commission)._outcome(P, plan)

    def test_outcome_marks_unknown_commission(self):
        stt, out = self._settle(None)
        self.assertEqual(stt, "SETTLED")
        self.assertEqual(out["cost_status"], "COMMISSION_UNKNOWN")
        stt, out = self._settle(3.5)
        self.assertNotIn("cost_status", out)

    def test_ml_and_nss_labels_cost_unknown(self):
        from masterquo.lab.nss_service import NeuralScalpService
        from masterquo.ml.service import MLService
        calls = []
        db = SimpleNamespace(execute=lambda sql, args=(): calls.append((sql, args)))
        _, out = self._settle(None)
        MLService.scalp_label(SimpleNamespace(db=db), "S1", "SETTLED", out)
        NeuralScalpService.label(SimpleNamespace(db=db), "N1", "SETTLED", out)
        self.assertNotIn("LABELED", calls[0][0])
        self.assertIn("COST_UNKNOWN", calls[0][0] + str(calls[0][1]))
        self.assertNotIn("'LABELED'", calls[1][0])
        self.assertIn("COST_UNKNOWN", calls[1][0] + str(calls[1][1]))
        calls.clear()
        _, out = self._settle(3.5)
        MLService.scalp_label(SimpleNamespace(db=db), "S1", "SETTLED", out)
        self.assertIn("status='LABELED'", calls[0][0])                             # known commission: labelled as before


# ------------------------------------------------------------------------------------------------------------------------ I0020
class TestSetupFeaturesFingerprint(unittest.TestCase):
    """I0020: SETUP_FEATURES (model B, extind BASE, NSS, NET) nie miał własnego id ani odcisku; aktywowalność modelu B sprawdzała tylko
    kontrakt zadania A. Brak pola w artefakcie = zgodny wstecz (legacy); inna wartość = SETUP_FEATURES_MISMATCH."""

    def test_fingerprint_identity(self):
        from masterquo.scalp import strategy as st
        fp = st.setup_features_fingerprint()
        self.assertEqual(st.SETUP_FEATURES_ID, "SCALP-SETUP-FEAT-1.0.0")
        self.assertEqual(st.setup_features_tag(), {"setup_features_id": st.SETUP_FEATURES_ID, "setup_features_fp": fp})
        with mock.patch.object(st, "SETUP_FEATURES", st.SETUP_FEATURES[:-1]):
            self.assertNotEqual(st.setup_features_fingerprint(), fp)
        self.assertIsNone(st.setup_features_check({}))                              # legacy artefact
        self.assertIsNone(st.setup_features_check(st.setup_features_tag()))
        self.assertTrue(st.setup_features_check({"setup_features_fp": "x"}).startswith("SETUP_FEATURES_MISMATCH"))

    def test_model_b_worker_refuses_other_fingerprint(self):
        td = TempData()
        self.addCleanup(td.close)
        with mock.patch.dict(os.environ, {"MQ_INSTRUMENT": "XAUUSD"}):
            from gold_candles_runtime import scalp_features as SF
            from gold_candles_runtime import worker as W
            from gold_candles_runtime.scalp_infer import registry_path, scalp_dir
            rd = scalp_dir() / "runs" / "R1"
            rd.mkdir(parents=True)
            entry = {"run_id": "R1", "run_dir": str(rd), "data_kind": "REAL_USER_DATA", "task_a_status": "ACCEPTED", "artifacts": {},
                     "symbol": "XAUUSD-", "tick_size": 0.01, "contract_hash": SF.contract_hash("XAUUSD-", 0.01),
                     "setup_model": {"features": ["x"], "threshold": 0.5, "selected": "LR", "setup_features_fp": "x"}}
            registry_path().write_text(json.dumps({"active": "R1", "history": [], "runs": {"R1": entry}}), encoding="utf-8")
            ans = W.setup_quality({"features": {"x": 1.0}, "symbol": "XAUUSD-", "tick_size": 0.01})
        self.assertEqual(ans["status"], "UNAVAILABLE")
        self.assertTrue(ans["reason"].startswith("SETUP_FEATURES_MISMATCH"), ans)
        self.assertFalse(ans["pass"])

    def test_extind_model_abstains_on_other_fingerprint(self):
        from datetime import UTC, datetime

        import numpy as np
        from masterquo.extind import features as F
        from masterquo.extind import trainer as T
        spec = F.default_spec(("BASE",))
        man = {"instrument": "XAUUSD", "feature_schema": F.FEATURE_SCHEMA, "spec": spec, "feature_order": F.feature_names(spec), "platt": [1.0, 0.0],
               "task_id": F.TASK_ID, "threshold": 0.5, "groups": ["BASE"], "role": "shadow_candidate", "setup_features_fp": "x"}
        obj = {"prep": SimpleNamespace(transform=lambda X: X), "model": SimpleNamespace(predict_proba=lambda Z: np.tile([0.4, 0.6], (len(Z), 1)))}
        snap = {"decision_time": datetime(2026, 10, 19, 12, tzinfo=UTC), "side": "BUY", "price": 100.0, "atr_m5": 1.0, "base": {"er10": 0.3}, "bars": {}, "ext": {}}
        r = T.ContextModel(man, obj).predict(snap, "XAUUSD")
        self.assertEqual(r["status"], "ABSTAIN")
        self.assertTrue(r["reason"].startswith("SETUP_FEATURES_MISMATCH"))
        legacy = {k: v for k, v in man.items() if k != "setup_features_fp"}
        self.assertEqual(T.ContextModel(legacy, obj).predict(snap, "XAUUSD")["status"], "READY_INFERENCE")

    def test_nss_and_net_bundles_refuse_other_fingerprint(self):
        from masterquo.lab import nss
        from masterquo.ml import scalp_task as stk
        sn = nss.sn
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "manifest.json").write_text(json.dumps({"architecture_id": sn.ARCH_ID, "task_id": nss.TASK_ID, "files_sha256": {},
                                                               "setup_features_fp": "x"}), encoding="utf-8")
            with self.assertRaises(ValueError) as cm:
                nss.NSSBundle(Path(d))
            self.assertIn("SETUP_FEATURES_MISMATCH", str(cm.exception))
            with self.assertRaises(ValueError) as cm:
                stk.ScalpBundle(Path(d))
            self.assertIn("SETUP_FEATURES_MISMATCH", str(cm.exception))

    def test_writers_record_the_fingerprint(self):
        for rel in ("backend/gold_candles_runtime/scalp_train.py", "backend/masterquo/extind/trainer.py", "backend/masterquo/lab/nss.py",
                    "backend/masterquo/ml/scalp_task.py"):
            self.assertIn("setup_features_tag()", (ROOT / rel).read_text(encoding="utf-8"), rel)


# ------------------------------------------------------------------------------------------------------------------------ I0085
def _full_import_graph() -> dict[str, set[str]]:
    """Import graph of backend/masterquo INCLUDING imports inside functions (the architecture test sees module level only)."""
    import ast
    pkg_root = ROOT / "backend"
    mods = {}
    for p in (pkg_root / "masterquo").rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        parts = list(p.relative_to(pkg_root).with_suffix("").parts)
        mods[".".join(parts[:-1] if parts[-1] == "__init__" else parts)] = p
    g = {m: set() for m in mods}
    for m, p in mods.items():
        pkg = m if p.name == "__init__.py" else m.rsplit(".", 1)[0]
        for st in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(st, ast.Import):
                names = [a.name for a in st.names]
            elif isinstance(st, ast.ImportFrom):
                base = pkg.split(".")
                if st.level:
                    base = base[:len(base) - (st.level - 1)] if st.level > 1 else base
                    mod = ".".join(base + ([st.module] if st.module else []))
                else:
                    mod = st.module or ""
                names = [f"{mod}.{a.name}" if f"{mod}.{a.name}" in mods else mod for a in st.names]
            else:
                continue
            g[m].update(n for n in names if n in mods and n != m)
    return g


def _reaches(g: dict[str, set[str]], a: str, b: str) -> bool:
    seen, todo = {a}, [a]
    while todo:
        for w in g[todo.pop()]:
            if w == b:
                return True
            if w not in seen:
                seen.add(w)
                todo.append(w)
    return False


class TestNoLazyImportCycles(unittest.TestCase):
    """I0085: cykle importów ukryte w importach wewnątrz funkcji (test architektury widzi tylko poziom modułu): structure_task<->si_families,
    tsfm validation<->service, montecarlo validate<->engine, research components<->service, forecast.export<->training.requirements."""

    PAIRS = (("masterquo.lab.structure_task", "masterquo.lab.si_families"), ("masterquo.tsfm.validation", "masterquo.tsfm.service"),
             ("masterquo.montecarlo.validate", "masterquo.montecarlo.engine"), ("masterquo.research.components", "masterquo.research.service"),
             ("masterquo.forecast.export", "masterquo.training.requirements"))

    def test_pairs_not_in_one_cycle(self):
        g = _full_import_graph()
        cyc = [(a, b) for a, b in self.PAIRS if _reaches(g, a, b) and _reaches(g, b, a)]
        self.assertEqual(cyc, [])

    def test_old_names_still_importable(self):
        from masterquo.forecast import dataset_state as DS
        from masterquo.forecast import export as EX
        from masterquo.lab import structure_tab, structure_task
        from masterquo.montecarlo import calibration, validate
        from masterquo.research import atomic_io
        from masterquo.research import service as RS
        from masterquo.tsfm import core
        from masterquo.tsfm import service as TS
        self.assertIs(structure_task.TAB, structure_tab.TAB)
        self.assertIs(TS.neutral_band, core.neutral_band)
        self.assertIs(TS.predict_request, core.predict_request)
        self.assertIs(validate.apply_calibrator, calibration.apply_calibrator)
        self.assertIs(RS._atomic, atomic_io._atomic)
        self.assertIs(EX.dataset_state, DS.dataset_state)
        self.assertIs(EX.read_status, DS.read_status)
        self.assertEqual((EX.META_FILE, EX.STATUS_FILE), ("source_metadata.json", "EXPORT_STATUS.json"))


# ------------------------------------------------------------------------------------------------------------------------ I0036
def _old_settle(r, closes, first_open, last_open, quantiles):
    """Reference: the per-row body of Kronos.settle / TSFM.settle before 1.46 arch I0036 (copied verbatim)."""
    path = json.loads(r["path_json"])
    if path[-1]["t_utc"] > last_open:
        return None
    if r["last_bar_open_utc"] < first_open:
        return "OUT_OF_BUFFER", {}
    act = [closes.get(x["t_utc"]) for x in path]
    if act[-1] is None:
        return "NO_DATA", {"missing_steps": sum(1 for a in act if a is None)}
    band = r["neutral_band"] or 0.0
    d = act[-1] - r["last_close"]
    dir_act = "UP" if d > band else "DOWN" if d < -band else "FLAT"
    errs = [abs(x["c"] - a) for x, a in zip(path, act) if a is not None]
    if not quantiles:
        return "SETTLED", {"actual_close_h": act[-1], "abs_err_h": abs(r["pred_close_h"] - act[-1]), "naive_abs_err_h": abs(r["last_close"] - act[-1]),
                           "path_mae": sum(errs) / len(errs), "steps_with_data": len(errs), "direction_actual": dir_act,
                           "direction_hit": None if (r["direction"] == "FLAT" or dir_act == "FLAT") else int(r["direction"] == dir_act)}
    qj = json.loads(r["quantiles_json"] or "null") or {}
    qh = (qj.get("path") or [{}])[-1]
    pin = None
    if qh:
        y = act[-1]
        pin = sum(max(float(lv) * (y - v), (float(lv) - 1) * (y - v)) for lv, v in ((k[1:], v) for k, v in qh.items())) / len(qh)
    cov = None
    if "q0.1" in qh and "q0.9" in qh:
        cov = int(qh["q0.1"] <= act[-1] <= qh["q0.9"])
    return "SETTLED", {"actual_close_h": act[-1], "abs_err_h": abs(r["pred_close_h"] - act[-1]), "naive_abs_err_h": abs(r["last_close"] - act[-1]),
                       "path_mae": sum(errs) / len(errs), "steps_with_data": len(errs), "direction_actual": dir_act, "pinball_h": pin,
                       "covered_80": cov, "direction_hit": None if (r["direction"] == "FLAT" or dir_act == "FLAT") else int(r["direction"] == dir_act)}


class TestSettleHelperParity(unittest.TestCase):
    """I0036: Kronos.settle i TSFM.settle były kopiami algorytmu 'prognoza vs zamknięcie' - wspólna funkcja daje bajt w bajt te same
    outcome_json (kolejność kluczy, pinball / pokrycie tylko dla TSFM)."""

    def _rows(self, n=400, seed=5):
        import random
        rnd = random.Random(seed)
        ts = [f"2026-11-24T{h:02d}:{m:02d}:00Z" for h in range(10, 14) for m in range(0, 60, 5)]
        closes = {t: 100 + rnd.uniform(-2, 2) for t in ts if rnd.random() > 0.1}
        rows = []
        for _ in range(n):
            k = rnd.randrange(0, len(ts) - 3)
            hz = rnd.randint(1, 3)
            path = [{"t_utc": ts[min(len(ts) - 1, k + j + 1)], "c": 100 + rnd.uniform(-2, 2)} for j in range(hz)]
            q = {"path": [{"q0.1": 99.0, "q0.5": 100.0, "q0.9": 101.0}]} if rnd.random() > 0.3 else None
            rows.append({"path_json": json.dumps(path), "last_bar_open_utc": ts[k], "neutral_band": rnd.choice([None, 0.0, 0.3]),
                         "last_close": 100 + rnd.uniform(-1, 1), "pred_close_h": 100 + rnd.uniform(-2, 2), "direction": rnd.choice(["UP", "DOWN", "FLAT"]),
                         "quantiles_json": json.dumps(q) if q else None})
        return rows, closes, ts[3], ts[-4]

    def test_byte_identical_outcomes(self):
        from masterquo.ledgers.settle import settle_close_path
        rows, closes, first_open, last_open = self._rows()
        seen = set()
        for r in rows:
            for q in (False, True):
                old, new = _old_settle(r, closes, first_open, last_open, q), settle_close_path(r, closes, first_open, last_open, quantiles=q)
                self.assertEqual(json.dumps(old), json.dumps(new))
                seen.add(old[0] if old else None)
        self.assertEqual(seen, {None, "OUT_OF_BUFFER", "NO_DATA", "SETTLED"})

    def test_services_use_the_helper(self):
        for rel in ("backend/masterquo/kronos/service.py", "backend/masterquo/tsfm/service.py"):
            self.assertIn("settle_close_path(", (ROOT / rel).read_text(encoding="utf-8"), rel)


class TestGprResolverShared(unittest.TestCase):
    """I0036 (b): resolver GPR był skopiowany w mm/service.py i mm/jobs.py."""

    def test_one_resolver_same_values(self):
        import math

        from masterquo.mm import gpr as G
        c = [100.0, 100.5, 101.0, 100.2, 99.8, 100.9]
        t = [1000.0 + 300 * i for i in range(len(c))]
        tidx = {float(x): i for i, x in enumerate(t)}
        row = {"source_ts": 1300.0, "horizon": "3bars", "payload": json.dumps({"pred": 0.001, "sd": 0.004})}
        real = math.log(c[4] / c[1])
        z = (real - 0.001) / 0.004
        self.assertEqual(G.logret_resolver(c, tidx)(row), {"realized_logret": real, "z": z, "in_1sd": abs(z) <= 1, "in_2sd": abs(z) <= 2})
        self.assertEqual(G.logret_resolver(c, tidx, t)(row)["matured_bar_ts"], t[4])
        self.assertIsNone(G.logret_resolver(c, tidx)(dict(row, source_ts=2500.0)))
        for rel in ("backend/masterquo/mm/service.py", "backend/masterquo/mm/jobs.py"):
            self.assertIn("logret_resolver(", (ROOT / rel).read_text(encoding="utf-8"), rel)


class TestSIMatureOutOfBuffer(unittest.TestCase):
    """I0036 (c): SI mature() pomijał wiersz, którego świeca startowa wypadła z bufora M1 - wisiał bez wyniku na zawsze."""

    def test_forecast_older_than_buffer_gets_status(self):
        td = TempData()
        self.addCleanup(td.close)
        from masterquo.db.database import Database
        from masterquo.lab.si_service import StructureIntelligenceService
        db = Database(Path(td.dir) / "t.sqlite")
        payload = json.dumps({"anchor_close": 100.0, "anchor_atr": 1.0})
        for i, as_of in enumerate(("2026-11-24T09:00:00Z", "2026-11-24T10:01:00Z")):
            db.execute("INSERT INTO si_forecasts(instrument, task_id, model_id, as_of, horizon, snapshot_id, emitted_at, payload) VALUES (?,?,?,?,?,?,?,?)",
                       ("XAUUSD", "T", "M", as_of, 3, None, as_of, payload))
        m1 = [{"open_utc": f"2026-11-24T10:{k:02d}:00Z", "c": 100.0 + k} for k in range(10)]
        svc = SimpleNamespace(db=db)
        n = StructureIntelligenceService.mature(svc, "XAUUSD", m1)
        rows = {r["as_of"]: r["status"] for r in db.query("SELECT f.as_of, o.status FROM si_forecasts f JOIN si_outcomes o ON o.forecast_id=f.id")}
        self.assertEqual(rows, {"2026-11-24T09:00:00Z": "OUT_OF_BUFFER", "2026-11-24T10:01:00Z": "MATURED"})
        self.assertEqual(n, 2)


if __name__ == "__main__":
    unittest.main()
