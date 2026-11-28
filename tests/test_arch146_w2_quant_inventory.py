"""1.46 arch, fala 2 – grupa quant_inventory: inwentarz Quant (quant/inventory.py), rejestr kanoniczny (quant/ids.py), katalog modeli,
mapa modeli i walidacja decision.required_models. Każdy test nie przechodzi na kodzie sprzed poprawki (klucze pozycji w nazwach testów).

* I0187 / I0274 / I0302 / I0313 / I0336 / I0401 / I0442 (I0645) / I0353 / I0571 / I0587 / I0600 / I0604 / I0544 / I0011: opisy, ścieżki
  artefaktów, odbiorcy i oś walidacji inwentarza zgodne z kodem (tylko metadane – decyzje bez zmian).
* I0269 / I0270: eksperymenty lab (LOGREG_PCA / _GMM_AUG / _NEUTRALIZED) mają ścieżkę na żywo (adapter lab) i należą do grupy 'lab'.
* I0378 / I0379 / I0570 / I0596 / I0598: rola CONTEXT_FEATURE tylko dla rekordów, z których quant/features.py buduje cechy (albo z
  jawnym feature_via) – rekordy STATE bez cech mają rolę CONTEXT_STATE; jednostka align_mean = 'mixed' (inwentarz = rekord).
* I0529: resolve() zna prefiks 'quant' (quant:metamodel); golden resolve() 1.46 dla wszystkich pozostałych nazw bez zmian.
* I0009: aliasy z jednego źródła (quant/ids) – stałe TH_* / SEQ_GRU_EVENT, mm_artifact_of, canonical_id w katalogu i w
  /api/v1/models/predictions (na kopii rekordu).
* I0000: decision.required_models – nowo dodane nieznane id odrzucane przy zapisie (podpowiedź tylko w komunikacie), zapisane id
  nie są zmieniane ani blokowane (ostrzeżenie w logu i w statusie koordynatora); evaluate_models bez zmian.
"""
from __future__ import annotations

import inspect
import json
import unittest
from types import SimpleNamespace
from unittest import mock

import _env
from _env import TempData

INST = "XAUUSD"

# resolve() of quant/ids on the code BEFORE this group (1.46 branch) - every name below must resolve exactly as then (only the 'quant:'
# names are new: I0529). Generated once from the base commit; grouped by the resolved id (None = unresolved).
GOLDEN_RESOLVE_1_46 = {
    None: ('', 'TH_FOO_M5_H6', 'analysis:signals', 'analytics:session_engine', 'apollo:market_trap', 'baskets:sfb', 'buzoa', 'chart_sync',
           'chronos2_M5', 'data_grabber', 'engine:volzones', 'extind:IQ_GOLD_GANN', 'extind:IQ_STAR_LINES', 'extind:PAL02M', 'extind:knowledge',
           'extind:sar_context', 'fusion_board', 'group:lab', 'head_shoulders', 'kronos_M5', 'lab', 'mathbench', 'quant_momentum',
           'quotes:MQ_NEWTONIAN_QUOTES_V2', 'renko', 'research:g7', 'research:g7_smc_radar', 'research:graph50', 'research:graph50:TP1',
           'research:sdformerflow', 'sdom', 'si_move', 'stfs', 'strategies:regime', 'th_direction', 'th_logreg', 'tsvp', 'zzz',),
    'agent:claude': ('agent', 'agent:claude',),
    'context_ind:context_move_m5': ('CONTEXT_MOVE_M5_V1', 'context_ind:context_move_m5', 'context_move',),
    'extind:indicator_context': ('extind:indicator_context', 'indicator_context',),
    'family:BREAKOUT': ('BREAKOUT', 'family:BREAKOUT',),
    'family:KALMAN_LS': ('KALMAN_LS', 'family:KALMAN_LS',),
    'family:MICROSTRUCTURE': ('MICROSTRUCTURE', 'family:MICROSTRUCTURE',),
    'family:NLP_SENTIMENT': ('NLP_SENTIMENT', 'family:NLP_SENTIMENT',),
    'family:PAIR_COINT': ('PAIR_COINT', 'family:PAIR_COINT',),
    'family:RL_PPO': ('RL_PPO', 'family:RL_PPO',),
    'family:SEQ_GRU': ('SEQ_GRU', 'family:SEQ_GRU',),
    'family:SEQ_LSTM': ('SEQ_LSTM', 'family:SEQ_LSTM',),
    'family:STATARB': ('STATARB', 'family:STATARB',),
    'family:TS_ARIMA': ('TS_ARIMA', 'family:TS_ARIMA',),
    'family:TS_SARIMAX': ('TS_SARIMAX', 'family:TS_SARIMAX',),
    'family:VOL_GARCH': ('VOL_GARCH', 'family:VOL_GARCH',),
    'flow:markov3': ('flow:markov3',),
    'flow:reaction_m1': ('flow:reaction_m1', 'flow_reaction',),
    'forecast:double_retest_v2': ('forecast:double_retest_v2',),
    'forecast:gold_candles': ('forecast:gold_candles', 'gold_candles', 'gold_candles_15m', 'gold_candles_30m', 'gold_candles_5m', 'gold_candles_99m',
                              'gold_forecast',),
    'forecast:long_horizon': ('forecast:long_horizon',),
    'kronos:Kronos-base': ('KRONOS_BASE', 'Kronos-base', 'kronos:Kronos-base',),
    'kronos:Kronos-small': ('KRONOS_SMALL', 'Kronos-small', 'kronos', 'kronos:Kronos-small',),
    'kronos:Kronos-small@M5': ('kronos:Kronos-small@M5',),
    'lab:DUMMY': ('lab:DUMMY',),
    'lab:LOGREG': ('lab:LOGREG',),
    'lab:LOGREG_GMM_AUG': ('lab:LOGREG_GMM_AUG',),
    'lab:LOGREG_NEUTRALIZED': ('lab:LOGREG_NEUTRALIZED',),
    'lab:LOGREG_PCA': ('lab:LOGREG_PCA',),
    'lab:M29_fourier': ('lab:M29_fourier',),
    'lab:M31_tick_kinematics': ('lab:M31_tick_kinematics',),
    'lab:M39_M41_edge': ('lab:M39_M41_edge',),
    'lab:M42_trade_pad': ('lab:M42_trade_pad',),
    'lab:MINIROCKET': ('lab:MINIROCKET',),
    'lab:RESNET1D': ('lab:RESNET1D',),
    'lab:RULE': ('lab:RULE',),
    'lab:SEW_SNN': ('lab:SEW_SNN',),
    'lab:TREE': ('lab:TREE',),
    'lab:XGB': ('lab:XGB',),
    'lab:models': ('lab:models',),
    'ml:association_rules': ('ml:association_rules',),
    'ml:change_point_engine': ('ml:change_point_engine',),
    'ml:decision_tree_ranker': ('ml:decision_tree_ranker',),
    'ml:legacy_s01_s12': ('legacy_ml', 'ml:legacy_s01_s12',),
    'ml:pt_directional_skill': ('ml:pt_directional_skill',),
    'ml_scalp:xgb_net_r': ('ml_scalp', 'ml_scalp:xgb_net_r',),
    'mm:align_mean': ('align_mean', 'mm:align_mean', 'mm_align_mean',),
    'mm:bat_encoder': ('mm:bat_encoder',),
    'mm:breakout_zones': ('breakout_zones', 'mm:breakout_zones', 'mm_breakout',),
    'mm:buzoa': ('mm:buzoa',),
    'mm:chart_sync': ('mm:chart_sync',),
    'mm:data_grabber': ('mm:data_grabber',),
    'mm:drift': ('mm:drift',),
    'mm:event_engine': ('mm:event_engine',),
    'mm:event_engine_dir3': ('SEQ_GRU_EVENT', 'event_engine', 'event_engine_dir3', 'family:SEQ_GRU_EVENT', 'mm:event_engine_dir3', 'mm_event_engine',),
    'mm:fusion_board': ('mm:fusion_board',),
    'mm:gpr': ('mm:gpr',),
    'mm:gpr_logret': ('gpr', 'gpr_logret', 'gpr_logret:LIVE', 'mm:gpr_logret', 'mm_gpr',),
    'mm:hdc': ('mm:hdc',),
    'mm:hdc_dir3': ('hdc', 'hdc_dir3', 'mm:hdc_dir3', 'mm_hdc',),
    'mm:head_shoulders': ('mm:head_shoulders',),
    'mm:kalman': ('mm:kalman',),
    'mm:kalman_cross': ('kalman', 'mm:kalman_cross', 'mm_kalman',),
    'mm:kalman_params': ('mm:kalman_params',),
    'mm:mathbench': ('mm:mathbench',),
    'mm:multi_indicator': ('mm:multi_indicator', 'mm_multi_indicator', 'multi_indicator',),
    'mm:quant_momentum': ('mm:quant_momentum',),
    'mm:renko': ('mm:renko',),
    'mm:robust_vol': ('mm:robust_vol',),
    'mm:sdom': ('mm:sdom',),
    'mm:smc_fvg': ('mm:smc_fvg', 'mm_smc_fvg', 'smc_fvg',),
    'mm:ste_flownet': ('mm:ste_flownet',),
    'mm:ste_flownet_ret': ('mm:ste_flownet_ret', 'mm_ste_flownet', 'ste_flownet', 'ste_flownet_ret',),
    'mm:stfs': ('mm:stfs',),
    'mm:tsvp': ('mm:tsvp',),
    'nss:tcn': ('nss', 'nss:tcn',),
    'rule:atr_vol': ('atr_vol', 'rule:atr_vol',),
    'rule:candles_patterns': ('candles_patterns', 'rule:candles_patterns',),
    'rule:data_quality': ('data_quality', 'rule:data_quality',),
    'rule:decomposition': ('decomposition', 'rule:decomposition',),
    'rule:flow_sr': ('flow_sr', 'rule:flow_sr',),
    'rule:fractal': ('fractal', 'rule:fractal',),
    'rule:liquidity': ('liquidity', 'rule:liquidity',),
    'rule:news': ('news', 'rule:news',),
    'rule:regime_v2': ('regime_v2', 'rule:regime_v2',),
    'rule:risk_engine': ('risk_engine', 'rule:risk_engine',),
    'rule:smc_pullback': ('rule:smc_pullback', 'smc_pullback',),
    'rule:structure_v2': ('rule:structure_v2', 'structure_v2',),
    'rule:vamd': ('rule:vamd', 'vamd',),
    'scalp:A_direction': ('scalp:A_direction', 'scalp_A',),
    'scalp:B_setup_quality': ('scalp:B_setup_quality', 'scalp_B',),
    'scalp:C_policy': ('scalp:C_policy',),
    'sh:tp_model': ('sh:tp_model', 'sh_tp_model',),
    'si:LOGREG': ('si:LOGREG',),
    'si:MQ_MINIROCKET_RIDGE_V2': ('si:MQ_MINIROCKET_RIDGE_V2',),
    'si:MQ_RESNEXT1D_V2': ('si:MQ_RESNEXT1D_V2',),
    'si:MQ_SEW_RESNET1D_V2': ('si:MQ_SEW_RESNET1D_V2',),
    'si:MQ_SEW_RESNEXT_EB_V1': ('si:MQ_SEW_RESNEXT_EB_V1',),
    'si:MQ_SPIKE_BRAIN_FINANCE_V1': ('si:MQ_SPIKE_BRAIN_FINANCE_V1',),
    'si:XGB': ('si:XGB',),
    'trainhub:TH_BASELINE': ('TH_BASELINE', 'TH_BASELINE_M5_H6', 'trainhub:TH_BASELINE',),
    'trainhub:TH_HGB': ('TH_HGB', 'TH_HGB_M5_H6', 'trainhub:TH_HGB',),
    'trainhub:TH_LOGREG': ('TH_LOGREG', 'TH_LOGREG_D1_H1', 'TH_LOGREG_M5_H6', 'trainhub:TH_LOGREG',),
    'trainhub:TH_RF': ('TH_RF', 'TH_RF_M5_H6', 'family:TH_RF', 'trainhub:TH_RF',),
    'trainhub:TH_SVM': ('TH_SVM', 'TH_SVM_M5_H6', 'family:TH_SVM', 'trainhub:TH_SVM',),
    'trainhub:TH_XGB': ('TH_XGB', 'TH_XGB_H1_H3', 'TH_XGB_M5_H6', 'family:TH_XGB', 'trainhub:TH_XGB',),
    'tsfm:chronos2': ('CHRONOS2', 'Chronos-2', 'chronos2', 'tsfm:chronos2',),
    'tsfm:fincast': ('FINCAST', 'FinCast', 'fincast', 'tsfm:fincast',),
    'tsfm:granite_ttm': ('GRANITE_TTM', 'Granite TTM', 'granite_ttm', 'tsfm:granite_ttm',),
    'tsfm:tirex2': ('TIREX2', 'TiRex-2', 'tirex2', 'tsfm:tirex2',),
}


def _text(e: dict) -> str:
    return " ".join(str(e.get(k) or "") for k in ("name", "not_applicable_reason", "notes"))


class _Inv(unittest.TestCase):
    """One offline inventory (no running bot) for the read-only checks."""

    @classmethod
    def setUpClass(cls):
        cls.td = TempData()
        from masterquo.quant import inventory as QI
        cls.QI = QI
        cls.inv = QI.build(None, INST)
        cls.by = {e["id"]: e for e in cls.inv["entries"]}

    @classmethod
    def tearDownClass(cls):
        cls.td.close()


# ================================================================================================ descriptions / paths / receivers
class TestInventoryDescriptions(_Inv):
    def test_I0187_indicators_description_matches_modules(self):
        e = self.by["analysis:indicators"]
        for absent in ("RSI", "MACD", "EMA", "BB"):
            self.assertNotIn(absent, e["name"])
        for present in ("AVWAP", "DXY", "OFI", "semiwariancja", "spread"):
            self.assertIn(present, e["name"])
        from masterquo.indicators import service as IS
        src = inspect.getsource(IS)
        for mod in ("avwap", "dxy", "ofi", "profile", "semivar", "spread"):
            self.assertIn(f"from . import {mod} as", src)                      # the modules the service really runs

    def test_I0274_si_rows_describe_live_shadow_forecast(self):
        si = [e for e in self.inv["entries"] if e["id"].startswith("si:")]
        self.assertGreaterEqual(len(si), 7)                                   # 5 families of si_move + si:LOGREG + si:XGB
        for e in si:
            t = _text(e)
            self.assertNotIn("na żądanie", t, e["id"])
            self.assertIn("si_forecasts", t, e["id"])
            self.assertIsNone(e["adapter"], e["id"])                           # still no Quant adapter (that would be a new feature)
        for e in si:
            if e["id"] not in ("si:LOGREG", "si:XGB"):
                self.assertTrue(any("scalp.dashboard" in r for r in e["receivers"]), e["id"])
        from masterquo.lab import si_service
        self.assertIn("self.forecast(", inspect.getsource(si_service.StructureIntelligenceService.snapshot))   # MTF snapshot (each closed M1)

    def test_I0302_flow_reaction_is_not_connected(self):
        e = self.by["flow:reaction_m1"]
        self.assertTrue(e["not_applicable_reason"].startswith("NOT_CONNECTED"), e["not_applicable_reason"])
        self.assertNotIn("liczony per wykres", e["not_applicable_reason"])
        from masterquo.lab.flow_context import service as FS
        self.assertNotIn("load_candidate", inspect.getsource(FS))             # the panel never loads the reaction model

    def test_I0313_rule_vamd_and_fractal_list_sh_receivers(self):
        for cid, key in (("rule:vamd", "vamd_m5"), ("rule:fractal", "fd_zone_m5")):
            e = self.by[cid]
            self.assertTrue(any("sh.setup" in r for r in e["receivers"]), cid)
            self.assertTrue(any("sh.tpmodel" in r for r in e["receivers"]), cid)
            self.assertIn(key, e["not_applicable_reason"])
            self.assertNotIn("bez akcesora snapshotu", e["not_applicable_reason"])
        from masterquo.sh import context as CX
        from masterquo.sh import setup as SS
        from masterquo.sh import tpmodel as TP
        for key in ("vamd_m5", "fd_zone_m5"):
            self.assertIn(f'out["{key}"]', inspect.getsource(CX._ctx_m5))
            self.assertIn(f'ctx.get("{key}")', inspect.getsource(SS))
            self.assertIn(f'ctx.get("{key}")', inspect.getsource(TP))

    def test_I0336_ml_scalp_owner_file(self):
        e = self.by["ml_scalp:xgb_net_r"]
        self.assertEqual(e["files"][0], "backend/masterquo/ml/scalp_task.py")
        self.assertIn("backend/masterquo/ml/service.py", e["files"])
        # the model map generator (tools/model_map.py -> MAPA_MODELI_I_TRENINGU.*) lists the scalp ML model with its owner
        import importlib.util
        spec = importlib.util.spec_from_file_location("model_map_qi", _env.ROOT / "tools" / "model_map.py")
        mm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mm)
        el = [x for x in mm.ELEMENTS if "scalp_task" in x["implementation"]]
        self.assertEqual([x["id"] for x in el], ["ML_SCALP_NET_R"])
        self.assertIn("SCALP-NET-FEAT-1.0.0", el[0]["features"])
        from masterquo.scalp import strategy as ST
        self.assertEqual(ST.NET_FEATURE_SCHEMA, "SCALP-NET-FEAT-1.0.0")

    def test_I0401_family_artifact_path(self):
        e = self.by["family:TS_ARIMA"]
        self.assertEqual(e["artifact"], "<data>/model_families/TS_ARIMA/<instrument>/<run_id>")
        from masterquo import paths
        from masterquo.modelhub.families import base as B
        rd = B.Store().run_dir("TS_ARIMA", INST, "R1")
        self.assertEqual(rd.relative_to(paths.data_dir()).as_posix(), "model_families/TS_ARIMA/XAUUSD/R1")

    def test_I0442_I0645_trainhub_artifact_path(self):
        from masterquo import paths
        from masterquo.trainhub import registry as TR
        th = [e for e in self.inv["entries"] if e["id"].startswith("trainhub:")]
        self.assertEqual(len(th), 6)
        for e in th:
            self.assertEqual(e["artifact"], "<data>/trainhub/models/<instrument>/<model_key>/<version>", e["id"])
        self.assertEqual(TR.package_dir(INST, "TH_RF_M5_H6", "v1").relative_to(paths.data_dir()).as_posix(), "trainhub/models/XAUUSD/TH_RF_M5_H6/v1")

    def test_I0353_hdc_unit_is_similarity_margin(self):
        from masterquo.modelhub import contract as C
        e = self.by["mm:hdc_dir3"]
        self.assertNotEqual(e["unit"], "score_0_100")
        self.assertIn(e["unit"], C.UNITS)
        self.assertIn("margines", e["notes"] or "")

    def test_I0571_I0587_no_false_accessor_claims(self):
        e = self.by["rule:smc_pullback"]
        self.assertNotIn("brak stabilnego akcesora", e["not_applicable_reason"])
        from masterquo.sh import context as CX
        src = inspect.getsource(CX._ctx_m5)
        for key in ("smc_trend_m5", "smc_high_m5", "smc_low_m5", "pb_last_high_m5", "pb_last_low_m5"):
            self.assertIn(f'out["{key}"]', src)
        self.assertIn("smc_trend_m5", e["not_applicable_reason"])
        self.assertTrue(any("sh." in r for r in e["receivers"]))
        liq = self.by["rule:liquidity"]
        self.assertNotIn("quant.snapshot", liq["not_applicable_reason"])
        from masterquo.quant import features as F
        from masterquo.quant import snapshot as QS
        for mod in (F, QS):
            self.assertNotIn("liquid", inspect.getsource(mod).lower())        # really no liquidity feature in Quant

    def test_I0544_trained_rows_require_validation(self):
        bad = [e["id"] for e in self.inv["entries"]
               if e["category"] in ("MODEL_TRAINED", "MODEL_PRETRAINED", "TRAINABLE") and e["validation"] == "NOT_APPLICABLE"]
        self.assertEqual(bad, [])
        for cid in ("sh:tp_model", "mm:event_engine_dir3", "kronos:Kronos-small", "mm:stfs"):
            self.assertEqual(self.by[cid]["validation"], "NOT_VALIDATED", cid)
        self.assertEqual(self.by["rule:vamd"]["validation"], "NOT_APPLICABLE")  # rules / measurements unchanged

    def test_I0598_market_zones_is_panel_visualisation(self):
        e = self.by["analysis:market_zones"]
        self.assertEqual(e["quant_role"], "NOT_A_VOTE")
        self.assertIsNone(e["adapter"])
        self.assertTrue(e["not_applicable_reason"])

    def test_I0600_walls_names_hv_proxy(self):
        e = self.by["analysis:walls"]
        self.assertIn("HV_PROXY", e["name"] + " " + (e["notes"] or e["not_applicable_reason"] or ""))
        self.assertNotIn("Opcje / walls / IV", e["name"])
        self.assertEqual(e["quant_role"], "GATE_EXISTING")
        self.assertTrue(any("S12" in r for r in e["receivers"]))
        from masterquo.analysis import walls as W
        r = W.choose_source(cfg=SimpleNamespace(source="AUTO", hv_window=5), symbol=INST, d1_closed=[{"c": 2000.0 + i * (-1) ** i} for i in range(30)],
                            iv_obs=None, manual=None, now=None)
        self.assertEqual(r["source_type"], "HV_PROXY")                         # AUTO without IV -> historical volatility of D1

    def test_I0604_svp_receivers(self):
        e = self.by["analysis:svp"]
        self.assertTrue(any("PMW_HG08" in r and "PMW_SC10" in r for r in e["receivers"]), e["receivers"])
        self.assertEqual(e["quant_role"], "GATE_EXISTING")
        self.assertIn("backend/masterquo/sh/pack/features.py", e["files"])
        from masterquo.sh.pack import catalog as PC
        for vid in ("PMW_HG08", "PMW_SC10"):
            self.assertEqual(PC._DEF[vid][4], "value_area_rejection")           # detector of both variants (profile = entry condition)

    def test_I0011_docstring_and_lab_placeholder_id(self):
        self.assertNotIn("(37 rows)", self.QI.__doc__)
        from masterquo.quant import adapters as QA
        ids = set(self.by)
        for st in ({}, {INST: {"models": [], "model": {"status": "no_model"}}}):
            recs = QA.lab(SimpleNamespace(lab=SimpleNamespace(state=st)), INST)
            self.assertTrue(recs)
            for r in recs:
                self.assertNotEqual(r["state"], "READY")                       # a placeholder never becomes a feature
                self.assertIn(r["canonical_id"], ids, r["canonical_id"])


# ================================================================================================ lab experiments (I0269 / I0270)
class TestLabExperiments(_Inv):
    def test_I0270_lab_group_contains_experiments(self):
        from masterquo.lab import protocol as LP
        from masterquo.lab import si_families as SF
        from masterquo.lab import structure_nets as SN
        from masterquo.quant import ids as I
        self.assertEqual(set(I.GROUPS["lab"]), {f"lab:{x}" for x in LP.FAMILIES + LP.EXPERIMENTS})
        self.assertEqual(tuple(I.GROUPS["si_move"]), tuple(f"si:{x}" for x in tuple(SN.FAMILIES) + tuple(SF.FAMILIES)))
        self.assertEqual(set(self.by["group:lab"]["variants"]), set(I.GROUPS["lab"]))

    def test_I0269_every_savable_lab_family_has_live_adapter(self):
        from masterquo.lab import protocol as LP
        for f in LP.FAMILIES + LP.EXPERIMENTS:
            if f == "DUMMY":
                continue
            e = self.by[f"lab:{f}"]
            self.assertEqual(e["adapter"], self.QI.A_EXT, f)
            self.assertNotIn("bez ścieżki na żywo", e["not_applicable_reason"] or "", f)
        for x in LP.EXPERIMENTS:
            e = self.by[f"lab:{x}"]
            self.assertEqual((e["unit"], e["task_type"], e["quant_role"], e["category"]), ("ratio", "SCORE", "BASE_FORECAST", "RESEARCH"), x)
            self.assertEqual(e["owner_infer"], "lab.service")


# ================================================================================================ roles vs features (I0378 / I0379 / I0570 / I0596)
def _mm_rt():
    v = {"status": "OK", "last_closed_m5": 1_700_000_100.0, "data_quality": "OK",
         "kalman": {"state": "BULLISH_CONFIRMED", "fast": 1.0, "slow": 0.9},
         "breakout": {"panel": {"direction": "UP"}},
         "multi_indicator": {"decision": "BUY", "status": "OK"},
         "smc_fvg": {"trend": "BULL", "live_setups": []},
         "align_mean": {"charts": [{"tf": "M5", "status": "OK", "dist_points": 10.0, "dist_pct": 0.1, "dist_atr": 0.5}]},
         "gpr": {"status": "OK", "mean_logret": 0.001, "sd": 0.002}}
    return SimpleNamespace(mm=SimpleNamespace(_cache={INST: {"value": v}}))


# one READY result that satisfies every branch of quant/features.prediction_features (the task_type decides which one is read)
ANY_RESULT = {"state": "BULLISH_CONFIRMED", "corr_72": 0.3, "resid_z_72": 0.1, "beta_72": 0.2, "status": "READY", "raw_score": 0.5,
              "UP": 0.5, "DOWN": 0.3, "FLAT": 0.2, "mean": 0.001, "sd": 0.002, "decision": "BUY", "trend": "BULL"}


class TestRolesMatchFeatures(_Inv):

    def test_I0379_I0570_I0596_context_feature_has_consumer(self):
        """Every quant.adapters.extended entry declared CONTEXT_FEATURE produces >= 1 MetaModel column from a READY record (FEAT-1 and
        FEAT-3), or names the candidate field that carries the information (feature_via)."""
        from masterquo.quant import features as F
        bad = []
        for e in self.inv["entries"]:
            if e["adapter"] != self.QI.A_EXT or e["quant_role"] != "CONTEXT_FEATURE":
                continue
            if e.get("feature_via"):
                continue
            rec = {"canonical_id": e["id"], "state": "READY", "task_type": e["task_type"] or "STATE", "unit": e["unit"], "task": "T",
                   "timeframe": "M5", "result": dict(ANY_RESULT), "eligibility": {"eligible": True}}
            for sem in (F.VERSION, F.VERSION3):
                if not F.prediction_features([rec], "LONG", semantics=sem):
                    bad.append((e["id"], sem))
        self.assertEqual(bad, [])
        for cid in ("mm:align_mean", "mm:multi_indicator", "mm:smc_fvg", "rule:structure_v2", "analysis:zones", "analysis:indicators"):
            self.assertEqual(self.by[cid]["quant_role"], "CONTEXT_STATE", cid)
        self.assertIn("CONTEXT_STATE", self.QI.ROLE_PL)
        for cid in ("rule:regime_v2", "rule:atr_vol"):
            self.assertTrue(self.by[cid].get("feature_via"), cid)

    def test_I0378_I0379_adapter_records_match_inventory(self):
        from masterquo.quant import adapters as QA
        recs = {r["canonical_id"]: r for r in QA.mm(_mm_rt(), INST)}
        self.assertEqual(recs["mm:align_mean"]["state"], "READY")
        self.assertEqual(recs["mm:align_mean"]["unit"], self.by["mm:align_mean"]["unit"])
        self.assertEqual(self.by["mm:align_mean"]["unit"], "mixed")
        for cid in ("mm:align_mean", "mm:multi_indicator", "mm:smc_fvg"):
            self.assertEqual(recs[cid]["analytic_role"], self.by[cid]["quant_role"], cid)
        for cid in ("mm:kalman_cross", "mm:breakout_zones"):                   # FILTER_STATE -> st:<cid>:aligned (a real feature)
            self.assertEqual(recs[cid]["analytic_role"], "CONTEXT_FEATURE", cid)
            self.assertEqual(self.by[cid]["quant_role"], "CONTEXT_FEATURE", cid)
        # features from these records unchanged: only the FILTER_STATE records give columns (FEAT-1 and FEAT-3)
        from masterquo.quant import features as F
        ready = [dict(r, eligibility={"eligible": True}) for r in recs.values()]
        for sem in (F.VERSION, F.VERSION3):
            cols = F.prediction_features(ready, "LONG", semantics=sem)
            self.assertEqual({k.split(":")[1] + ":" + k.split(":")[2] for k in cols if k.startswith("st:")}, {"mm:kalman_cross", "mm:breakout_zones"})
            self.assertFalse([k for k in cols if "align_mean" in k or "multi_indicator" in k or "smc_fvg" in k])


# ================================================================================================ canonical ids (I0529 / I0009)
class TestCanonicalIds(unittest.TestCase):
    def test_I0529_quant_prefix_resolves(self):
        from masterquo.quant import ids as I
        self.assertEqual(I.resolve("quant:metamodel"), "quant:metamodel")
        self.assertEqual(I.canonical({"family": "quant:metamodel"}), "quant:metamodel")
        self.assertEqual(I.resolve("quant:tabicl_v2"), "quant:tabicl_v2")

    def test_I0529_I0009_golden_resolution_unchanged(self):
        from masterquo.quant import ids as I
        diff = {n: (want, I.resolve(n)) for want, names in GOLDEN_RESOLVE_1_46.items() for n in names if I.resolve(n) != want}
        self.assertEqual(diff, {})
        for want, names in GOLDEN_RESOLVE_1_46.items():                     # canonical() of a record named by any key -> the same id
            for n in names:
                if n and want:
                    self.assertEqual(I.canonical({"model_name": n}), want, n)

    def test_I0009_alias_constants_single_source(self):
        from masterquo.quant import ids as I
        self.assertEqual(set(I.TRAINHUB_FAMILY_ALIASES), {"TH_RF", "TH_XGB", "TH_SVM"})     # pinned literally (safety condition 1)
        self.assertEqual(I.EVENT_GRU_FAMILY, "SEQ_GRU_EVENT")
        derived = {a.split(":", 1)[1] for c, al in I.ALIASES.items() if c.startswith("trainhub:") for a in al if a.startswith("family:")}
        self.assertEqual(derived, set(I.TRAINHUB_FAMILY_ALIASES))
        self.assertEqual({m: I.mm_artifact_of(m) for m in ("mm_gpr", "mm_hdc", "mm_event_engine", "mm_ste_flownet")},
                         {"mm_gpr": "gpr_logret", "mm_hdc": "hdc_dir3", "mm_event_engine": "event_engine_dir3", "mm_ste_flownet": "ste_flownet_ret"})
        self.assertIsNone(I.mm_artifact_of("lab"))
        from masterquo.modelhub.families import service as FS
        from masterquo.sh import models as SM
        from masterquo.studio import registry as SR
        for mod in (FS, SR):
            src = inspect.getsource(mod)
            self.assertNotIn('("TH_RF", "TH_XGB", "TH_SVM")', src, mod.__name__)
            self.assertNotIn('== "SEQ_GRU_EVENT"', src, mod.__name__)
        self.assertNotIn('"mm_gpr": "gpr_logret"', inspect.getsource(SM.probe))
        self.assertIn("item[\"kind\"] == \"TRAINED\"", inspect.getsource(SM.probe))   # the TRAINED condition stays (safety condition 2)

    def test_I0009_inventory_mm_rows_use_resolve(self):
        from masterquo.quant import inventory as QI
        self.assertFalse(hasattr(QI, "_MM_TO_CANON"))

    def test_I0009_catalog_rows_carry_canonical_id(self):
        td = TempData()
        try:
            from masterquo.modelhub import catalog as CT
            from masterquo.quant import inventory as QI
            cat = CT.build(None, INST)
            inv_ids = {e["id"] for e in QI.build(None, INST)["entries"]}
        finally:
            td.close()
        by = {r["id"]: r for r in cat["items"]}
        self.assertEqual(by["mm_gpr"]["canonical_id"], "mm:gpr_logret")
        self.assertEqual(by["lab"]["canonical_id"], "group:lab")
        self.assertEqual(by["kronos"]["canonical_id"], "kronos:Kronos-small")
        self.assertEqual(by["gold_forecast"]["canonical_id"], "forecast:gold_candles")
        self.assertEqual(by["th_logreg"]["canonical_id"], "trainhub:TH_LOGREG")
        self.assertEqual(by["chronos2"]["canonical_id"], "tsfm:chronos2")
        missing = {r["id"]: r.get("canonical_id") for r in cat["items"] if r.get("canonical_id") not in inv_ids}
        self.assertEqual(missing, {})                                         # one registry: every catalog row is an inventory row

    def test_I0009_predictions_api_adds_canonical_id_on_a_copy(self):
        td = TempData()
        try:
            from masterquo.api import app as A
            rt = mock.MagicMock()
            rt.license.locked = False
            cached = [{"model_name": "Kronos-small", "model_key": "kronos_M5", "state": "READY"},
                      {"model_key": "TH_XGB_M5_H6", "model_name": "TH_XGB_M5_H6", "state": "READY"},
                      {"model_name": "research:graph50:TP1", "canonical_id": "research:graph50:TP1", "family": "research:graph50"}]
            before = json.dumps(cached, sort_keys=True)
            with mock.patch("masterquo.modelhub.adapters.all_predictions", return_value=cached):
                app = A.create_app(rt, 18784)
                fn = next(r.endpoint for r in app.routes if getattr(r, "path", None) == "/api/v1/models/predictions")
                out = fn(instrument="XAUUSD")
        finally:
            td.close()
        self.assertEqual([p["canonical_id"] for p in out["items"]], ["kronos:Kronos-small", "trainhub:TH_XGB", "research:graph50:TP1"])
        self.assertEqual(json.dumps(cached, sort_keys=True), before)              # the cached records (SH / Quant / coordinator) untouched
        self.assertEqual([{k: v for k, v in p.items() if k != "canonical_id"} for p in out["items"]],
                         [{k: v for k, v in p.items() if k != "canonical_id"} for p in cached])


# ================================================================================================ decision.required_models (I0000)
class TestRequiredModelsValidation(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)

    def _store(self):
        from masterquo.config import ConfigStore
        return ConfigStore()

    def test_I0000_new_unknown_id_saved_as_before_with_warning_and_hint(self):
        """arch146 merge (safety verdict I0440): refusing the save would keep the bot entering where the saved list blocks every new
        entry today - only a warning with the hint; the list is saved exactly as before (nothing mapped automatically)."""
        cs = self._store()
        with self.assertLogs("masterquo.config", level="WARNING") as lg:
            cs.update({"decision": {"required_models": ["TH_XGB"]}, "risk": {"max_open_positions": 3}})
        msg = " ".join(lg.output)
        self.assertIn("UNKNOWN_REQUIRED_MODEL:TH_XGB", msg)
        self.assertIn("trainhub:TH_XGB", msg)                                  # hint only - never applied automatically
        self.assertEqual(cs.get().decision.required_models, ["TH_XGB"])       # saved as before (blocks every new entry, as today)
        self.assertEqual(cs.get().risk.max_open_positions, 3)
        for bad, hint in (("family:TS_ARIMA", "TS_ARIMA"), ("mm:event_engine_dir3", "SEQ_GRU_EVENT"), ("chronos2", "tsfm:chronos2"),
                          ("kronos:Kronos-small@M5", "kronos:Kronos-small"), ("TH_XGB_M5_H6", "trainhub:TH_XGB"), ("lab:models", None)):
            with self.assertLogs("masterquo.config", level="WARNING") as lg:
                cs.update({"decision": {"required_models": [bad]}})
            if hint:
                self.assertIn(hint, " ".join(lg.output))
            self.assertEqual(cs.get().decision.required_models, [bad])

    def test_I0000_valid_ids_accepted(self):
        cs = self._store()
        for ok in (["TS_ARIMA"], ["trainhub:TH_XGB"], ["SEQ_GRU_EVENT", "tsfm:chronos2", "quant:metamodel", "rule:news", "lab:LOGREG_PCA"]):
            self.assertEqual(cs.update({"decision": {"required_models": ok}}).decision.required_models, ok)

    def test_I0000_saved_unknown_id_kept_and_never_blocks_other_saves(self):
        from masterquo.config import ConfigStore
        cs = ConfigStore()
        raw = json.loads(cs.path.read_text(encoding="utf-8"))
        raw["decision"]["required_models"] = ["TH_XGB"]
        cs.path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertLogs("masterquo.config", level="WARNING") as lg:
            cs2 = ConfigStore()                                               # load: no error, nothing changed
        self.assertTrue(any("TH_XGB" in m for m in lg.output))
        self.assertEqual(cs2.get().decision.required_models, ["TH_XGB"])
        self.assertEqual(json.loads(cs2.path.read_text(encoding="utf-8"))["decision"]["required_models"], ["TH_XGB"])
        # other saves pass (risk, the whole decision section sent back unchanged, a valid id added next to the saved one)
        cs2.update({"risk": {"max_open_positions": 4}})
        cs2.update({"decision": {"required_models": ["TH_XGB"], "enabled": True}})
        self.assertEqual(cs2.update({"decision": {"required_models": ["TH_XGB", "TS_ARIMA"]}}).decision.required_models, ["TH_XGB", "TS_ARIMA"])
        with self.assertLogs("masterquo.config", level="WARNING"):
            cs2.update({"decision": {"required_models": ["TH_XGB", "TS_ARIMA", "TH_RF"]}})   # saved, warned (never refused)
        self.assertEqual(cs2.get().decision.required_models, ["TH_XGB", "TS_ARIMA", "TH_RF"])

    def test_I0000_coordinator_status_reports_unknown_and_evaluation_unchanged(self):
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        from masterquo.decision import coordinator as DC
        cs = ConfigStore()
        raw = json.loads(cs.path.read_text(encoding="utf-8"))
        raw["decision"]["required_models"] = ["TH_XGB", "TS_ARIMA"]
        cs.path.write_text(json.dumps(raw), encoding="utf-8")
        cs = ConfigStore()
        db = Database()
        self.addCleanup(lambda: getattr(db, "close", lambda: None)())
        st = DC.DecisionCoordinator(db, cs).status()
        self.assertEqual(st["required_models_unknown"], ["TH_XGB"])
        # the pure evaluation is unchanged: the unknown id still blocks (MODEL_REQUIRED_UNAVAILABLE), nothing is mapped to trainhub:TH_XGB
        rec = {"model_key": "TH_XGB_M5_H6", "state": "READY", "task_type": "CLASS_PROBABILITIES", "result": {"UP": 0.6, "DOWN": 0.2, "FLAT": 0.2},
               "data_time": 1000.0}
        _, why = DC.evaluate_models([rec], "BUY", required={"TH_XGB"}, assist_threshold=0.6, max_age_s=900, now=1010.0)
        self.assertEqual(why, ["MODEL_REQUIRED_UNAVAILABLE:TH_XGB"])
        _, why = DC.evaluate_models([rec], "BUY", required={"trainhub:TH_XGB"}, assist_threshold=0.6, max_age_s=900, now=1010.0)
        self.assertEqual(why, [])

    def test_I0000_put_config_saves_and_warns(self):
        from masterquo.api import app as A
        from masterquo.config import ConfigStore
        rt = mock.MagicMock()
        rt.license.locked = False
        rt.cfg = ConfigStore()
        app = A.create_app(rt, 18785)
        fn = next(r.endpoint for r in app.routes if getattr(r, "path", None) == "/api/v1/config" and "PUT" in (getattr(r, "methods", None) or ()))
        with self.assertLogs("masterquo.config", level="WARNING") as lg:
            fn(patch={"decision": {"required_models": ["TH_XGB"]}})
        self.assertIn("UNKNOWN_REQUIRED_MODEL:TH_XGB", " ".join(lg.output))
        self.assertEqual(rt.cfg.get().decision.required_models, ["TH_XGB"])
        fn(patch={"decision": {"required_models": ["trainhub:TH_XGB"]}})
        self.assertEqual(rt.cfg.get().decision.required_models, ["trainhub:TH_XGB"])

    def test_I0000_valid_set_covers_every_live_producer(self):
        """Safety condition 5: every producer whose record can reach the coordinator is configurable - the inventory entries with a live
        adapter map to a valid id (the string _mid / family / model_id carries)."""
        from masterquo.quant import ids as I
        from masterquo.quant import inventory as QI
        valid = set(I.required_ids())
        inv = QI.build(None, INST)
        need = set()
        for e in inv["entries"]:
            if e["adapter"] not in (QI.A_EXISTING, QI.A_FAM, QI.A_EXT) or e["code_state"] != "IMPLEMENTED":
                continue
            cid = e["id"]
            if cid.startswith("family:"):
                need.add(cid.split(":", 1)[1])
            elif cid == "mm:event_engine_dir3":
                need.add(I.EVENT_GRU_FAMILY)
            elif cid == "research:g7_smc_radar":
                need.add("research:g7")
            else:
                need.add(cid)
        self.assertEqual(sorted(need - valid), [])
        self.assertIn("quant:metamodel", valid)
        for no in ("TH_XGB", "family:TS_ARIMA", "mm:event_engine_dir3", "kronos:Kronos-base", "tsfm:fincast", "lab:models", "group:lab"):
            self.assertNotIn(no, valid)


if __name__ == "__main__":
    unittest.main()
