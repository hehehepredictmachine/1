"""Full inventory of the computational components of the bot (PMW-QUANT-INV-1) -> docs/quant/INVENTORY.md / INVENTORY.json.

Sources (read from the code at generation time, nothing typed by hand twice - the row counts are in the generated coverage, not here):
sh/models.REGISTRY, modelhub/families registry (with the SEQ_GRU_EVENT adapter), trainhub/learn.MODELS, mm/inventory.MODULES,
lab/protocol.FAMILIES + EXPERIMENTS, lab/structure_nets.FAMILIES, lab/si_families.FAMILIES, lab/flow_context/task.FAMILIES,
quant/ids.EXTRA_PRODUCERS, plus the analysis services wired in runtime.py.
Group rows (lab, si_move, th_direction) are expanded to their real families; aliases are folded into ONE canonical entry (quant/ids.py).

Three separate axes per entry (never merged into one "ready" flag):
* code_state     - IMPLEMENTED | NOT_IMPLEMENTED | NO_SPEC | GROUP ;
* runtime_state  - the live probe of the existing service (READY / SHADOW_ONLY / DETERMINISTIC_OK / NOT_TRAINED / NOT_CONNECTED /
                   MISSING_DEPENDENCY / UNAVAILABLE / ERROR), or NOT_EVALUATED when generated without a running bot;
* validation     - VALIDATED (artifact gate passed for its own role) | NOT_VALIDATED | NOT_APPLICABLE (rules, measurements, infra).
Coverage is reported four times: inventory, adapters, operational readiness, analytical readiness - catalog coverage is never shown as
model readiness.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..kronos.settings import TF_ALL as _KRONOS_TF
from ..tsfm.settings import TF_ALL as _TSFM_TF
from . import ids as I

VERSION = "PMW-QUANT-INV-1"
OPERATIONAL = ("READY", "SHADOW_ONLY", "DETERMINISTIC_OK")

# quant roles (how Quant Core uses the output)
ROLE_PL = {"GATE_EXISTING": "istniejąca bramka (bez zmian)", "CONTEXT_FEATURE": "cecha kontekstu meta-modelu (z maską braku)",
           # 1.46 arch (I0189): a context record no feature is built from (quant/features.py) - panel / agent / REQUIRED only
           "CONTEXT_STATE": "stan kontekstu (panel / agent) – bez cech meta-modelu",
           "BASE_FORECAST": "prognoza bazowa – cecha meta-modelu pod własną nazwą", "SETUP_EVENT": "prawdopodobieństwo zdarzenia setupu (ewaluacja)",
           "TOOL": "narzędzie / proces uczenia / optymalizacja – nie głos", "NOT_A_VOTE": "opis / opinia – bez p(win)",
           "META_MODEL": "Quant MetaModel", "SIMULATION": "symulacja (MODEL_SIMULATED) – nie skalibrowane p", "NONE": "brak (nie istnieje)"}

# adapter of the live output into PMW-PRED-2 (quant/adapters.py) or the justified NOT_APPLICABLE reason
A_EXISTING = "modelhub.adapters.all_predictions"
A_FAM = "modelhub.families.service.predictions"
A_EXT = "quant.adapters.extended"
A_SETUP = "evaluation.service (prawdopodobieństwo per kandydat setupu)"
VALIDATION_CATEGORIES = ("MODEL_TRAINED", "MODEL_PRETRAINED", "TRAINABLE")      # validation axis NOT_VALIDATED / VALIDATED, never NOT_APPLICABLE

_OVR: dict[str, dict] = {
    # --- rules / measurements (SH deterministic rows) -------------------------------------------------------------
    # 1.46 arch (I0553): the files where the data-quality checks really live (SH limits, ACTIVE session model, Quant snapshot QC)
    "rule:data_quality": {"role": "GATE_EXISTING", "adapter": A_EXT, "files": ["backend/masterquo/sh/context.py", "backend/masterquo/data/quality.py",
                                                                             "backend/masterquo/quant/snapshot.py", "backend/masterquo/mt5/bridge.py"],
                          "unit": "state", "task_type": "STATE",
                          "data": "notowanie MT5, zegar, spread", "receivers": ["sh.service", "engine.decision", "quant.snapshot"]},
    "rule:risk_engine": {"role": "GATE_EXISTING", "adapter": None, "na": "bramka ryzyka liczona w ścieżce wykonania (RiskBook / risk/portfolio.py) – Quant jej nie dubluje",
                         "files": ["backend/masterquo/sh/risk.py", "backend/masterquo/risk/portfolio.py"], "unit": "state", "task_type": "STATE"},
    "rule:news": {"role": "GATE_EXISTING", "adapter": A_EXT, "files": ["backend/masterquo/news/"], "unit": "state", "task_type": "STATE",
                  "data": "kalendarz makro (czas pierwszego odbioru)"},
    # 1.46 arch (I0570): the STATE records of regime / ATR give no column (quant/features.py) - the same information enters the MetaModel
    # through the candidate (feature_via); structure_v2 has no such path -> CONTEXT_STATE (published record, not a feature)
    "rule:regime_v2": {"role": "CONTEXT_FEATURE", "adapter": A_EXT, "unit": "state", "task_type": "STATE", "tfs": ["M5", "M15", "H1"],
                       "feature_via": "reżim kandydata (market_regime) -> ctx:regime=* (quant/features.context_features) – nie z rekordu STATE"},
    "rule:structure_v2": {"role": "CONTEXT_STATE", "adapter": A_EXT, "unit": "state", "task_type": "STATE", "tfs": ["M5", "M15", "H1"],
                          "notes": "rekord STATE w migawce Quant (panel / agent / REQUIRED); quant/features.py nie buduje z niego cech – struktura "
                                   "nie jest wejściem MetaModelu (nowa cecha = osobna decyzja z nową wersją schematu cech)"},
    # 1.46 arch (I0571 / I0313): the SH snapshot (sh/context.py, every SH cycle) carries these values - they are SH inputs, not panel-only
    "rule:smc_pullback": {"role": "CONTEXT_FEATURE", "adapter": None,
                          "na": "akcesor istnieje: migawka SH sh.snapshot['ctx'] w każdym cyklu SH (smc_trend_m5, smc_high_m5 / smc_low_m5, "
                                "pb_last_high_m5 / pb_last_low_m5, smc_trend_m1 / smc_last_m1); brak adaptera Quant – nie jest cechą MetaModelu (PMW-PRED-2)",
                          "receivers": ["sh.setup (potwierdzenie odwrócenia: CHoCH M1 smc_last_m1)",
                                        "sh.context.obstacles (aktywne poziomy SMC M5 jako przeszkody przed TP)", "context_ind (panel)"]},
    "rule:vamd": {"role": "CONTEXT_FEATURE", "adapter": None,
                  "na": "VAMD liczony na żywo w migawce SH (sh.context: ctx.vamd_m5 / ctx.vamd_m1) i per wykres w context_ind (panel); bez adaptera "
                        "Quant (PMW-PRED-2) – nie jest modelem „Quant Ultimate Momentum Pro”",
                  "notes": "dwie parametryzacje: SH = profil DEFAULT (zamrożony, sh/context.py), panel/SI = skalibrowany profil context_ind "
                           "(profile_hash w odpowiedzi; panel pokazuje obok wartości DEFAULT używane przez SH)",
                  "receivers": ["sh.setup (warunek potwierdzenia CONTINUATION: znak vamd_m5)", "sh.tpmodel (cechy vamd_m5 / vamd_m1)", "context_ind (panel)"]},
    "rule:fractal": {"role": "CONTEXT_FEATURE", "adapter": None,
                     "na": "Katz FD liczony na żywo w migawce SH (sh.context: ctx.fd_zone_m5) i per wykres w context_ind; bez adaptera Quant (PMW-PRED-2)",
                     "notes": "dwie parametryzacje: SH = profil DEFAULT (zamrożony, sh/context.py), panel/SI = skalibrowany profil context_ind "
                              "(profile_hash w odpowiedzi; panel pokazuje obok wartości DEFAULT używane przez SH)",
                     "receivers": ["sh.setup (warunek potwierdzenia CONTINUATION: fd_zone_m5 ≠ CHOP)", "sh.tpmodel (cechy fd_trend / fd_chop z fd_zone_m5)",
                                   "context_ind (panel)"]},
    "rule:atr_vol": {"role": "CONTEXT_FEATURE", "adapter": A_EXT, "unit": "price", "task_type": "STATE", "tfs": ["M1", "M5"],
                     "feature_via": "ATR kandydata (features.atr_m5) -> ctx:risk_atr, fcp:*:d_atr / band_atr (quant/features.py) – nie z rekordu STATE"},
    "rule:candles_patterns": {"role": "CONTEXT_FEATURE", "adapter": None, "na": "formacje opisowe (role świec) – kontekst panelu, bez liczbowego wyjścia"},
    # 1.46 arch (I0587): neither quant/snapshot.py nor quant/features.py computes liquidity - no distance feature exists
    "rule:liquidity": {"role": "CONTEXT_FEATURE", "adapter": None,
                       "na": "poziomy płynności (boksy sesji / sweep – analytics.session_engine, heatmapa likwidacji – analytics.liquidation) w polityce "
                             "OBSERVE analytics.liquidity_context (panel, kontekst silnika, agent); brak adaptera Quant i brak cechy MetaModelu"},
    "rule:flow_sr": {"role": "CONTEXT_FEATURE", "adapter": None, "na": "pasma S/R flow_context per wykres – bez akcesora snapshotu"},
    "rule:decomposition": {"role": "CONTEXT_FEATURE", "adapter": None, "na": "obserwacja cyklu (FFT/EMD/VMD) – brak zadania predykcyjnego"},
    # --- older services ---------------------------------------------------------------------------------------------
    "sh:tp_model": {"role": "SETUP_EVENT", "adapter": A_SETUP, "unit": "probability", "task_type": "EVENT_PROBABILITY", "task": "TP2_BEFORE_SL_H",
                    "files": ["backend/masterquo/sh/tpmodel.py"], "env": ".venv", "train": "training (sh_models)", "infer": "sh.service"},
    "scalp:A_direction": {"role": "BASE_FORECAST", "adapter": A_EXT, "unit": "probability", "task_type": "CLASS_PROBABILITIES", "task": "SCALP_DIRECTION_H1_3_5M",
                          "tfs": ["M1"], "files": ["backend/masterquo/scalp/service.py"], "env": ".venv_candles", "train": "training (scalp_A)", "infer": "forecast worker (.venv_candles)"},
    "scalp:B_setup_quality": {"role": "SETUP_EVENT", "adapter": None, "na": "P(TP1 przed SL) INNEGO setupu (Range→Sweep→Retest) – liczony tylko dla planu scalp; brak modelu z replayu na danych rzeczywistych",
                              "unit": "probability", "task_type": "EVENT_PROBABILITY", "tfs": ["M1"], "env": ".venv_candles"},
    "forecast:gold_candles": {"role": "BASE_FORECAST", "adapter": A_EXISTING, "unit": "probability", "task_type": "CLASS_PROBABILITIES", "task": "CANDLE_CLOSE_DIRECTION_H*_M5",
                              "tfs": ["M5"], "horizon": "1/3/6 świec M5 (5/15/30 min)", "files": ["backend/masterquo/forecast/"], "env": ".venv_candles"},
    "ml:legacy_s01_s12": {"role": "SETUP_EVENT", "adapter": A_SETUP, "unit": "probability", "task_type": "EVENT_PROBABILITY", "task": "NET_R_POSITIVE_S01_S12",
                          "files": ["backend/masterquo/ml/"], "env": ".venv"},
    "extind:indicator_context": {"role": "SETUP_EVENT", "adapter": None, "na": "score polityki scalp (TP1 przed SL innego planu) – liczony per plan w scalp.indicator_context",
                                 "unit": "probability", "task_type": "SCORE", "files": ["backend/masterquo/extind/"]},
    "ml_scalp:xgb_net_r": {"role": "SETUP_EVENT", "adapter": None, "na": "P(net R>0) innego cyklu scalp – liczony per plan w scalp.ml_scalp", "unit": "probability",
                           # 1.46 arch (I0336): owner = ml/scalp_task.py (dataset / training / selection / bundle), inference ml/service.py
                           "task_type": "EVENT_PROBABILITY", "files": ["backend/masterquo/ml/scalp_task.py", "backend/masterquo/ml/service.py",
                                                                       "backend/masterquo/scalp/service.py"],
                           "train": "ml/scalp_task.py (training ml_scalp)", "infer": "ml.service.MLService.on_scalp_candidate (scalp.service)"},
    "nss:tcn": {"role": "SETUP_EVENT", "adapter": None, "na": "P(TP1_FIRST/SL_FIRST/TIMEOUT) innego setupu – liczony per plan w scalp.neural", "unit": "probability",
                "task_type": "CLASS_PROBABILITIES", "files": ["backend/masterquo/lab/nss_service.py"]},
    "flow:reaction_m1": {"role": "BASE_FORECAST", "adapter": None,
                         # 1.46 arch (I0302): FlowSections (panel / SI cells) loads only markov/latest.txt; the reaction candidate is replay-only
                         "na": "NOT_CONNECTED: model reakcji FLOW_CONTEXT_MOVE_M1_V1 trenowany (LOGREG / XGB), bez ścieżki inferencji na żywo – "
                               "FlowSections liczy tylko Heikin / S-R / StopDistance i Markov3 (flow:markov3); replay tylko z CLI (F-17)",
                         "unit": "probability", "task_type": "CLASS_PROBABILITIES", "tfs": ["M1"], "files": ["backend/masterquo/lab/flow_context/"],
                         "variants": ["flow:LOGREG", "flow:XGB"]},
    "context_ind:context_move_m5": {"role": "BASE_FORECAST", "adapter": None, "na": "NOT_CONNECTED: model badawczy bez ścieżki inferencji na żywo (F-17)",
                                    "unit": "probability", "task_type": "CLASS_PROBABILITIES", "tfs": ["M5"], "files": ["backend/masterquo/lab/context_ind/"]},
    # --- MM ---------------------------------------------------------------------------------------------------------
    # 1.46 arch (I0378 / I0379): STATE records - quant/features.py builds no column from them (only FILTER_STATE / dxy STATE) -> CONTEXT_STATE;
    # align_mean carries distances in points, % and ATR per TF -> unit 'mixed' (the adapter record says the same)
    "mm:align_mean": {"role": "CONTEXT_STATE", "adapter": A_EXT, "unit": "mixed", "task_type": "STATE",
                      "notes": "odległości od średniej per TF (<TF>_dist_points / _dist_pct / _dist_atr: punkty, %, ATR) – rekord STATE bez cech MetaModelu"},
    "mm:kalman_cross": {"role": "CONTEXT_FEATURE", "adapter": A_EXT, "unit": "state", "task_type": "FILTER_STATE", "tfs": ["M5"]},
    "mm:breakout_zones": {"role": "CONTEXT_FEATURE", "adapter": A_EXT, "unit": "state", "task_type": "FILTER_STATE", "tfs": ["M5"]},
    "mm:multi_indicator": {"role": "CONTEXT_STATE", "adapter": A_EXT, "unit": "state", "task_type": "STATE", "tfs": ["M5"]},
    "mm:smc_fvg": {"role": "CONTEXT_STATE", "adapter": A_EXT, "unit": "state", "task_type": "STATE", "tfs": ["M5"]},
    "mm:gpr_logret": {"role": "BASE_FORECAST", "adapter": A_EXT, "unit": "log_return", "task_type": "REGRESSION", "task": "LOG_RETURN_H3_M5", "tfs": ["M5"],
                      "horizon": "3 świece M5"},
    "mm:hdc_dir3": {"role": "BASE_FORECAST", "adapter": None, "na": "margines HDC (nie prawdopodobieństwo); brak ścieżki na żywo bez artefaktu VALIDATED_SHADOW",
                    # 1.46 arch (I0353): HDCClassifier.predict returns s[top1] - s[top2] of the similarities 1 - 2H/D (mm/hdc.py), not 0-100
                    "unit": "ratio", "task_type": "SCORE", "tfs": ["M5"],
                    "notes": "margines podobieństwa: różnica podobieństw (1 − 2H/D) dwóch najlepszych klas, zakres 0..2 – nie skala 0–100, nie prawdopodobieństwo"},
    "mm:event_engine_dir3": {"role": "BASE_FORECAST", "adapter": A_EXT, "unit": "probability", "task_type": "CLASS_PROBABILITIES", "task": "EVENT_UNITS_DIR3",
                             "tfs": ["EVENT"], "horizon": "2 jednostki zdarzeń (16 zdarzeń/jednostka)"},
    "mm:ste_flownet_ret": {"role": "BASE_FORECAST", "adapter": None, "na": "brak ścieżki na żywo (tylko artefakt badawczy); log-zwrot h zdarzeń",
                           "unit": "log_return", "task_type": "REGRESSION", "tfs": ["EVENT"]},
    # --- other SH rows ------------------------------------------------------------------------------------------------
    "tsfm:chronos2": {"role": "BASE_FORECAST", "adapter": A_EXISTING, "unit": "price", "task_type": "REGRESSION", "task": "TSFM_CLOSE_H*",
                      "tfs": list(_TSFM_TF), "env": ".venv_chronos2", "files": ["backend/masterquo/tsfm/", "backend/tsfm_runtime/"],
                      "notes": "amazon/chronos-2 (120M); kwantyle modelu, punkt = mediana; nieskalibrowane na danych brokera; "
                               "interwały = dozwolone w ustawieniach TSFM (domyślnie włączone M5, M15)"},
    "tsfm:granite_ttm": {"role": "BASE_FORECAST", "adapter": A_EXISTING, "unit": "price", "task_type": "REGRESSION", "task": "TSFM_CLOSE_H*",
                         "tfs": list(_TSFM_TF), "env": ".venv_granite", "files": ["backend/masterquo/tsfm/", "backend/tsfm_runtime/"],
                         "notes": "ibm-granite/granite-timeseries-ttm-r2 (TTM R2 512-96, 0,8M); prognoza punktowa (bez kwantyli); nieskalibrowana; "
                                  "1.40 zamiast FinCast (FinCast: RETIRED, historia zachowana); "
                                  "interwały = dozwolone w ustawieniach TSFM (domyślnie włączone M5, M15)"},
    # 1.46 w2 (I0206): TiRex-2 is a row of sh/models.REGISTRY (was quant/ids.EXTRA_PRODUCERS) - same metadata as before
    "tsfm:tirex2": {"role": "BASE_FORECAST", "adapter": "modelhub.adapters.all_predictions", "unit": "price", "task_type": "REGRESSION", "task": "TSFM_CLOSE_H*",
                    "tfs": ["M5", "M15"], "env": ".venv_tirex2", "files": ["backend/masterquo/tsfm/", "backend/tsfm_runtime/"],
                    "notes": "rekordy z model_id tsfm:tirex2 (TsfmService, jak Chronos-2 / Granite TTM); kwantyle; nieskalibrowane na danych brokera"},
    "kronos:Kronos-small": {"role": "BASE_FORECAST", "adapter": A_EXISTING, "unit": "price", "task_type": "REGRESSION", "task": "KRONOS_CLOSE_PATH_H*",
                            "tfs": list(_KRONOS_TF), "env": ".venv_kronos", "files": ["backend/masterquo/kronos/", "backend/kronos_runtime/"],
                            "notes": "pojedyncza ścieżka nie jest prawdopodobieństwem; pretrained ≠ dostrojony do brokera; "
                                     "interwały = dozwolone w ustawieniach Kronos (domyślnie włączone M5, M15)"},
    "agent:claude": {"role": "NOT_A_VOTE", "adapter": None, "na": "opis / weto tekstowe agenta – bez p(win); poza meta-modelem", "unit": "state", "task_type": "STATE"},
}

_MM_TOOL = {"buzoa": "TOOL", "sdom": "TOOL", "stfs": "TOOL", "quant_momentum": "NONE", "renko": "NONE", "head_shoulders": "NONE",
            "data_grabber": "TOOL", "tsvp": "TOOL", "mathbench": "TOOL", "chart_sync": "TOOL", "fusion_board": "TOOL"}


def _e(cid: str, **kw) -> dict:
    base = {"id": cid, "aliases": I.aliases_of(cid), "name": cid, "category": "?", "files": [], "input": None, "output": None, "unit": None,
            "task_type": None, "task": None, "horizon": None, "timeframes": [], "data_required": None, "features": None, "owner_train": None,
            "owner_infer": None, "env": ".venv", "artifact": None, "dependencies": [], "code_state": "IMPLEMENTED", "runtime_state": "NOT_EVALUATED",
            "state_reason": None, "validation": "NOT_APPLICABLE", "receivers": [], "quant_role": "CONTEXT_FEATURE", "adapter": None,
            "not_applicable_reason": None, "variants": [], "source_registry": [], "notes": None, "feature_via": None}
    base.update({k: v for k, v in kw.items() if v is not None})
    o = _OVR.get(cid) or {}
    for k_src, k_dst in (("role", "quant_role"), ("adapter", "adapter"), ("na", "not_applicable_reason"), ("files", "files"), ("unit", "unit"),
                         ("task_type", "task_type"), ("task", "task"), ("tfs", "timeframes"), ("horizon", "horizon"), ("env", "env"),
                         ("train", "owner_train"), ("infer", "owner_infer"), ("data", "data_required"), ("receivers", "receivers"),
                         ("variants", "variants"), ("notes", "notes"), ("feature_via", "feature_via")):
        if k_src in o:
            base[k_dst] = o[k_src]
    return base


def _sh_rows() -> list[dict]:
    from ..sh import models as SM
    out = []
    for it in SM.REGISTRY:
        sid = it["id"]
        if sid in I.GROUPS:
            out.append(_e(f"group:{sid}", name=it["name"], category="GROUP", code_state="GROUP", output=it["output"], quant_role="NONE",
                          not_applicable_reason="wiersz grupowy – rozwinięty na rzeczywiste rodziny: " + ", ".join(I.GROUPS[sid]),
                          variants=list(I.GROUPS[sid]), source_registry=["sh.models.REGISTRY"], adapter=None))
            continue
        cid = I.resolve(sid) or f"sh:{sid}"
        # 1.46 w2 (I0008): one kind -> category map (PRETRAINED in sh/models), no hard-coded exception by id
        cat = {"DETERMINISTIC": "RULE_OR_MEASUREMENT", "TRAINED": "MODEL_TRAINED", "PRETRAINED": "MODEL_PRETRAINED", "EXTERNAL": "AGENT"}[it["kind"]]
        # 1.46 arch (I0544): a trained / pretrained producer needs a validation for its role (was the NOT_APPLICABLE default of _e)
        out.append(_e(cid, name=it["name"], category=cat, output=it["output"], owner_train=it.get("train"), source_registry=["sh.models.REGISTRY"],
                      validation="NOT_VALIDATED" if cat in VALIDATION_CATEGORIES else None,
                      receivers=[f"SH:{it['roles']['SCALPING']}/{it['roles']['HEDGING']}"], dependencies=[f"grupa korelacji {it['group']}"],
                      _sh=it))
    return out


def _family_rows(probe_deep: bool = True) -> list[dict]:
    from ..modelhub.families import registry
    out = []
    for fid, f in registry().items():
        cid = I.resolve(fid)
        if not probe_deep and getattr(f, "RUNTIME", None) == "DEEP":
            from ..modelhub.families import deep as DP
            ok, why = DP.available_cached(f.DEPS)             # the catalog view never starts the .venv_deep health process
            impl, why = ("AVAILABLE", None) if ok else ("MISSING_DEPENDENCY", why)
        else:
            impl, why = f.implementation()
        if cid and not cid.startswith("family:"):
            continue                                         # alias of trainhub / mm producer - folded into that entry
        role = {"RL_ACTION": "NOT_A_VOTE", "PAIR_RELATION": "CONTEXT_FEATURE", "MICROSTRUCTURE": "CONTEXT_FEATURE", "FILTER_STATE": "CONTEXT_FEATURE",
                "NLP_SENTIMENT": "CONTEXT_FEATURE"}.get(f.TASK_TYPE, "BASE_FORECAST")
        env = ".venv_deep" if fid in ("SEQ_LSTM", "SEQ_GRU", "RL_PPO") else ".venv"
        out.append(_e(cid, name=f.NAME, category="MODEL_TRAINED" if f.KIND == "TRAINED" else ("MEASUREMENT" if f.KIND == "MEASUREMENT" else "MODEL_ESTIMATED"),
                      files=[f"backend/masterquo/modelhub/families/{type(f).__module__.rsplit('.', 1)[-1]}.py"], unit=f.UNIT, task_type=f.TASK_TYPE,
                      task=f.TASK, timeframes=[f.TF] if f.TF else [], horizon=(f"{list(f.HORIZONS)} świec {f.TF}" if f.HORIZONS else "brak (pomiar stanu)"),
                      data_required=(getattr(f, "DATA", None) or {}).get("note") if isinstance(getattr(f, "DATA", None), dict) else None,
                      owner_train="modelhub.families.service (proces obok)", owner_infer="modelhub.families.service", env=env,
                      artifact=f"<data>/model_families/{fid}/<instrument>/<run_id>",            # 1.46 arch (I0401): families/base.Store.run_dir
                      code_state="IMPLEMENTED", runtime_state="MISSING_DEPENDENCY" if impl == "MISSING_DEPENDENCY" else "NOT_EVALUATED",
                      state_reason=why, validation="NOT_VALIDATED", receivers=list(getattr(f, "RECEIVERS", ()) or ()), quant_role=role,
                      adapter=A_FAM, source_registry=["modelhub.families.registry"],
                      notes="akcja RL ≠ p(win)" if fid == "RL_PPO" else ("sentyment ≠ kierunek XAUUSD bez wyuczonego związku" if fid == "NLP_SENTIMENT" else None)))
    return out


def _trainhub_rows() -> list[dict]:
    from ..trainhub import learn
    out = []
    for mid, m in learn.MODELS.items():
        cid = f"trainhub:{mid}"
        fam = [a for a in I.aliases_of(cid) if a.startswith("family:")]
        out.append(_e(cid, name=m.get("name") or mid, category="MODEL_TRAINED", files=["backend/masterquo/trainhub/learn.py", "backend/masterquo/trainhub/inference.py"],
                      unit="probability", task_type="CLASS_PROBABILITIES", task="DIRECTION_H<h>_<TF> po kosztach", timeframes=["M1", "M5", "M15", "M30"],
                      horizon="h świec (per paczka)", features="trainhub.features.FEATURE_SCHEMA (wspólna implementacja trening/inferencja)",
                      owner_train="trainhub.jobs.TrainingCenter", owner_infer="trainhub.inference.TrainhubInference",
                      artifact="<data>/trainhub/models/<instrument>/<model_key>/<version>",     # 1.46 arch (I0442): trainhub/registry.package_dir
                      validation="NOT_VALIDATED", quant_role="BASE_FORECAST" if mid != "TH_BASELINE" else "TOOL", adapter=A_EXISTING,
                      source_registry=["trainhub.learn.MODELS"] + (["modelhub.families (alias)"] if fam else []),
                      notes=("alias rodziny " + ", ".join(fam) + " – jeden artefakt, jeden trening, jeden głos") if fam else
                      ("baseline częstości klas – punkt odniesienia" if mid == "TH_BASELINE" else None)))
    return out


def _lab_rows() -> list[dict]:
    from ..lab import protocol as P
    from ..lab import si_families as SF
    from ..lab import structure_nets as SN
    out = []
    for f in P.FAMILIES:
        out.append(_e(f"lab:{f}", name=f"Lab {f}", category="MODEL_TRAINED" if f not in P.BASELINE_FAMILIES else "BASELINE",
                      # 1.46: the lab adapter publishes raw_score as unit 'ratio' (0-1, lab.service round(p, 4)), not score_0_100
                      files=["backend/masterquo/lab/protocol.py", "backend/masterquo/lab/service.py"], unit="ratio", task_type="SCORE",
                      task="TRIPLE_BARRIER_1.5ATR_LONG (score nieskalibrowany)", timeframes=["M5"], owner_train="lab (training: lab)", owner_infer="lab.service",
                      artifact="<data>/lab/models/<asset>/", validation="NOT_VALIDATED", quant_role="BASE_FORECAST" if f not in P.BASELINE_FAMILIES else "TOOL",
                      adapter=A_EXT, source_registry=["lab.protocol.FAMILIES"], notes="score innego zdarzenia niż TP setupu – cecha pod własną nazwą"))
    for x in getattr(P, "EXPERIMENTS", ()):
        # 1.46 arch (I0269): an experiment is saved like a family (artifact_family ALL of `training lab-offline`, or when it wins the
        # selection), runs in LabService and is published by quant.adapters.lab as lab:<X> READY - it was declared "bez ścieżki na żywo"
        out.append(_e(f"lab:{x}", name=f"Eksperyment lab {x}", category="RESEARCH",
                      files=["backend/masterquo/lab/protocol.py", "backend/masterquo/lab/service.py"], unit="ratio", task_type="SCORE",
                      task="TRIPLE_BARRIER_1.5ATR_LONG (score nieskalibrowany)", timeframes=["M5"], owner_train="lab (training: lab)",
                      owner_infer="lab.service", artifact="<data>/lab/models/<asset>/", quant_role="BASE_FORECAST", adapter=A_EXT,
                      source_registry=["lab.protocol.EXPERIMENTS"], validation="NOT_VALIDATED",
                      notes="eksperyment badawczy (PCA / GMM / neutralizacja) – wariant LOGREG, score innego zdarzenia niż TP setupu; artefakt w trybie "
                            "ALL (training lab-offline, profil PEŁNY TRENING) albo gdy wygra selekcję; t_activate przypina rolę research -> rekord lab:<X> w Quant"))
    for f in tuple(SN.FAMILIES) + tuple(SF.FAMILIES):
        out.append(_e(f"si:{f}", name=f"Structure Intelligence {f}", category="MODEL_TRAINED",
                      files=["backend/masterquo/lab/structure_nets.py" if f in SN.FAMILIES else "backend/masterquo/lab/si_families.py", "backend/masterquo/lab/si_service.py"],
                      unit="probability", task_type="CLASS_PROBABILITIES", task="M1_MOVE_H3/5/15 (DOWN/FLAT/UP + kwantyle r_h/ATR)", timeframes=["M1"],
                      owner_train="training (structure_intelligence)", owner_infer="lab.si_service", artifact="<data>/structure_intelligence/<instrument>/",
                      validation="NOT_VALIDATED", quant_role="BASE_FORECAST", adapter=None,
                      not_applicable_reason=I.SI_LIVE,                 # 1.46 arch (I0274): live SHADOW forecast, not a report on request
                      receivers=["scalp.dashboard (migawka MTF, prognoza SHADOW)", "agent.tools get_structure_intelligence",
                                 "archiwum si_forecasts / si_outcomes"],
                      source_registry=["lab.structure_nets.FAMILIES" if f in SN.FAMILIES else "lab.si_families.FAMILIES"]))
    return out


def _mm_rows() -> list[dict]:
    from ..mm import inventory as MI
    out = []
    for m in MI.MODULES:
        cid = I.resolve(m["id"])                             # 1.46 arch (I0009): the alias table of quant/ids, not a copy of it
        if cid:
            out.append({"_merge": cid, "files": list(m.get("files") or []), "input": m.get("inputs"), "output_mm": m.get("outputs"),
                        "train": m.get("training"), "receivers": list(m.get("callers") or [])})
            continue
        nospec = not m.get("spec")
        role = _MM_TOOL.get(m["id"], "TOOL")
        out.append(_e(f"mm:{m['id']}", name=m["name"], category="NO_SPEC" if nospec else m["category"], files=list(m.get("files") or []),
                      input=m.get("inputs"), output=m.get("outputs"), code_state="NO_SPEC" if nospec else "IMPLEMENTED", quant_role=role,
                      owner_train=m.get("training"), receivers=list(m.get("callers") or []), source_registry=["mm.inventory.MODULES"],
                      not_applicable_reason=("brak specyfikacji w paczce – algorytm nie jest odtwarzany z nazwy" if nospec else
                                             "narzędzie / infrastruktura / proces uczenia – nie osobny głos modelu"),
                      runtime_state="UNAVAILABLE" if nospec else "NOT_EVALUATED",
                      state_reason="NO_SPEC" if nospec else None,
                      validation="NOT_VALIDATED" if m["category"] in VALIDATION_CATEGORIES and not nospec else None))
    return out


def _analysis_rows() -> list[dict]:
    rows = [
        ("analysis:montecarlo", "Monte Carlo (PMW-MC-1) – symulacja ścieżek", "SIMULATION", ["backend/masterquo/montecarlo/"], "SIMULATION",
         "MODEL_SIMULATED – wynik symulacji, nie prawdopodobieństwo skalibrowane na zdarzeniach"),
        # 1.46 arch (I0596): the zone record is a STATE summary quant/features.py does not map - the zone_* features reach the candidate
        # and the evaluation ledger (evaluation.zone_context), not the MetaModel
        ("analysis:zones", "Mapa stref (PMW-ZONES)", "ANALYSIS", ["backend/masterquo/zones/"], "CONTEXT_STATE",
         ("rekord STATE (ZONE_MAP_SUMMARY) w migawce Quant bez cech MetaModelu – quant/features.py nie mapuje stref; cechy zone_* trafiają do "
          "kandydata i ledgera oceny (evaluation.zone_context)")),
        # 1.46 arch (I0598): panel visualisation (job on request), no adapter and no feature consumer
        ("analysis:market_zones", "Strefy rynkowe M1/M5/M15/M30 (1.28)", "ANALYSIS", ["backend/masterquo/zones/market_service.py"], "NOT_A_VOTE",
         "wizualizacja panelu Strefy rynkowe – liczone na żądanie (job) / w panelu, brak cyklu niezależnego od panelu; bez adaptera Quant i konsumenta cech"),
        # 1.46 arch (I0187): the modules indicators/ really computes (no EMA / RSI / MACD / BB there); I0189: no feature -> CONTEXT_STATE
        ("analysis:indicators", ("Wskaźniki PMW-IND-1 (AVWAP sesja/zdarzenie/manualny, semiwariancja, percentyl spreadu, cechy profilu sesji, "
                                 "mikrostruktura arkusza/OFI, relacja DXY)"), "ANALYSIS", ["backend/masterquo/indicators/"], "CONTEXT_STATE", None),
        # 1.46 arch (I0604): the previous-session profile is an entry condition of the SH pack variants PMW_HG08 / PMW_SC10
        ("analysis:svp", "Session Volume Profile (PMW-SVP-1)", "ANALYSIS", ["backend/masterquo/svp/", "backend/masterquo/sh/pack/features.py"],
         "GATE_EXISTING",
         ("profil poprzedniej sesji (svp.engine.compute na zamkniętych M5, tick volume = aktywność feedu, nie wolumen obrotu) jest warunkiem wejścia "
          "wariantów pakietu SH PMW_HG08 / PMW_SC10 (value_area_rejection: brak profilu = NO_DATA, bez setupu); profile użytkownika – panel; "
          "Quant nie dubluje bramki")),
        ("analysis:dxy_correlation", "Korelacja XAUUSD–DXY (PMW-IND-1 dxy)", "ANALYSIS", ["backend/masterquo/indicators/"], "CONTEXT_FEATURE", None),
        # 1.46 arch (I0600): AUTO without an IV import computes the walls from the historical volatility of D1 (analysis/walls.choose_source)
        ("analysis:walls", "Walls D1 (σ: import IV → IV ręczna → HV_PROXY domyślnie)", "ANALYSIS",
         ["backend/masterquo/analysis/walls.py", "backend/masterquo/analysis/iv_import.py"], "GATE_EXISTING",
         ("bez importu IV źródłem σ jest zmienność historyczna D1 (HV_PROXY, close-to-close), nie rynek opcji; IV_SOURCED niezaimplementowane "
          "(NOT_CONFIGURED); brak źródła = UNAVAILABLE, nie zero; poziomy ścian są wejściem strategii S12 (ścieżka A) – Quant ich nie dubluje")),
        ("analysis:evaluation", "AI Setup Probability Engine (PMW-EVAL)", "ANALYSIS", ["backend/masterquo/evaluation/"], "SETUP_EVENT", None),
        ("quant:metamodel", "PMW Quant MetaModel (logistyczny + net R ridge, OOF, kalibracja)", "META_MODEL", ["backend/masterquo/quant/metamodel.py"],
         "META_MODEL", None),
    ]
    recv = {"analysis:svp": ["SH pack PMW_HG08 / PMW_SC10 (sh/pack/detectors.value_area_rejection – profil poprzedniej sesji)",
                             "panel SVP (profile użytkownika)"],
            "analysis:walls": ["strategies.s12_walls_range (ścieżka A, S12)", "panel / API ścian zmienności"],
            "analysis:zones": ["evaluation.service (zone_context kandydata)", "migawka Quant (rekord STATE)"]}
    out = []
    for cid, name, cat, files, role, na in rows:
        ad = {"analysis:indicators": A_EXT, "analysis:dxy_correlation": A_EXT, "analysis:zones": A_EXT, "analysis:montecarlo": A_EXT,
              "analysis:evaluation": "evaluation.service (ledger)", "quant:metamodel": "quant.service (assessment)"}.get(cid)
        out.append(_e(cid, name=name, category=cat, files=files, quant_role=role, adapter=ad, not_applicable_reason=na if not ad else None,
                      notes=na if ad else None, source_registry=["runtime.py"], receivers=recv.get(cid),
                      validation="NOT_VALIDATED" if cat in ("META_MODEL", "SIMULATION") else "NOT_APPLICABLE"))
    out.append(_e("ext:catboost", name="CatBoost", category="NOT_IMPLEMENTED", code_state="NOT_IMPLEMENTED", quant_role="NONE", runtime_state="UNAVAILABLE",
                  state_reason="wspomniany w dokumentacji / traceability (M06); brak implementacji i zależności w kodzie",
                  not_applicable_reason="nie istnieje w kodzie – nie dodano fikcyjnego adaptera", source_registry=["lab/traceability.py (wzmianka)"]))
    return out


def _extra_rows() -> list[dict]:
    """1.46 arch: producers that were in the code but in no registry (quant/ids.EXTRA_PRODUCERS) - one row each, same three axes."""
    out = []
    for cid, (name, cat, env, files, role, adapter, why) in I.EXTRA_PRODUCERS.items():
        nospec = cat == "NO_SPEC"
        out.append(_e(cid, name=name, category=cat, env=env, files=list(files), quant_role=role, adapter=adapter,
                      not_applicable_reason=None if adapter else why, notes=why if adapter else None,
                      code_state="NO_SPEC" if nospec else "IMPLEMENTED", runtime_state="UNAVAILABLE" if nospec else "NOT_EVALUATED",
                      state_reason="NO_SPEC" if nospec else None, source_registry=["quant.ids.EXTRA_PRODUCERS (1.46)"],
                      validation="NOT_VALIDATED" if cat in VALIDATION_CATEGORIES else "NOT_APPLICABLE"))
    return out


def _th_runtime_state(st: dict) -> str:
    """trainhub registry.status_of (catalog vocabulary) -> runtime_state of this inventory. Without a live view (no running bot) an active
    package stays SHADOW_ONLY as in 1.46; while the bot runs an active package without a prediction is DATA_MISSING (was SHADOW_ONLY)."""
    s, cause, act, vers = st["state"], st.get("cause"), st.get("active"), st.get("versions")
    if s == "READY" or (cause == "NO_LIVE_VIEW" and act):
        return "SHADOW_ONLY"
    if s == "TRAINING":
        return "SHADOW_ONLY" if act else ("CANDIDATE" if vers else "NOT_TRAINED")
    if s == "DISABLED":
        return {"NO_ACTIVE": "CANDIDATE", "NO_LIBRARY": "MISSING_DEPENDENCY"}.get(cause, "UNAVAILABLE")
    return {"BLOCKED_DATA": "DATA_MISSING", "NOT_TRAINED": "NOT_TRAINED", "INCOMPATIBLE": "INCOMPATIBLE"}.get(s, "ERROR")


def _probe(entries: list[dict], rt, inst: str) -> None:
    """Live / on-disk state through the EXISTING probes (sh.models.probe, families status, trainhub registry). Never raises."""
    from ..sh import models as SM
    fam_svc = getattr(rt, "families", None) if rt is not None else None
    for e in entries:
        it = e.pop("_sh", None)
        try:
            if it is not None:
                st = SM.probe(it, rt, inst)
                e["runtime_state"], e["state_reason"] = st["status"], st.get("reason")
                if rt is None and (it["kind"] == "DETERMINISTIC" or it["id"] == "mm_gpr"):
                    e["runtime_state"], e["state_reason"] = "NOT_EVALUATED", "liczone z bieżących świec – stan tylko przy działającym bocie"
            elif e["id"].startswith("family:"):
                fid = e["id"].split(":", 1)[1]
                if fam_svc is not None:
                    st = fam_svc.status(fid, inst)
                    e["runtime_state"] = ("MISSING_DEPENDENCY" if st["implementation"] == "MISSING_DEPENDENCY" else
                                          "SHADOW_ONLY" if st.get("use") in ("SHADOW", "ASSIST") else ("NOT_TRAINED" if st["artifact"] == "NOT_TRAINED" else "CANDIDATE"))
                    e["state_reason"] = st.get("implementation_reason") or f"artefakt {st['artifact']}, użycie {st.get('use')}"
                    e["validation"] = "VALIDATED" if st["artifact"] == "APPROVED" else "NOT_VALIDATED"
            elif e["id"].startswith("trainhub:"):
                # arch146 I0010: the one trainhub state (registry.status_of, the same as the catalog / SH probe) in the probe vocabulary
                from ..trainhub import registry as TR
                st = TR.status_of(inst, e["id"].split(":", 1)[1], rt)
                e["runtime_state"], e["state_reason"] = _th_runtime_state(st), st["reason"]
        except Exception as exc:  # noqa: BLE001 - a broken probe is a state, never a crash of the inventory
            e["runtime_state"], e["state_reason"] = "ERROR", f"{type(exc).__name__}: {exc}"[:160]


def _live_outputs(entries: list[dict], rt) -> None:
    """Operational readiness from what Quant Core actually PUBLISHED (eligible = valid, fresh, READY), not from the probes."""
    pub = getattr(getattr(rt, "quant", None), "pub", None) if rt is not None else None
    cur = pub.current() if pub is not None else None
    for e in entries:
        e["live_output"] = "NOT_EVALUATED" if cur is None else None
    if cur is None:
        return
    ready = {p.get("canonical_id") for p in cur.get("eligible") or []}
    why = {}
    for p in cur.get("excluded") or []:
        why.setdefault(p.get("canonical_id"), (p.get("eligibility") or {}).get("reason"))
    for e in entries:
        if e["adapter"] in (A_EXISTING, A_FAM, A_EXT):
            e["live_output"] = "READY" if e["id"] in ready else (why.get(e["id"]) or "BRAK_REKORDU_W_GENERACJI")
        else:
            e["live_output"] = "NOT_APPLICABLE"


def build(rt=None, inst: str = "XAUUSD", *, probe_deep: bool = True) -> dict:
    """probe_deep=False (panel catalog): deep families use the cached .venv_deep health only - no health process is started."""
    entries = _sh_rows() + _trainhub_rows() + _family_rows(probe_deep) + _lab_rows()
    merges = []
    for r in _mm_rows():
        if "_merge" in r:
            merges.append(r)
        else:
            entries.append(r)
    entries += _analysis_rows()
    entries += _extra_rows()
    by_id = {e["id"]: e for e in entries}
    for m in merges:                                         # MM module metadata folded into the SH row of the same producer
        e = by_id.get(m["_merge"])
        if e is None:
            continue
        e["files"] = sorted(set(e["files"]) | set(m["files"]))
        e["input"] = e["input"] or m["input"]
        e["owner_train"] = e["owner_train"] or m["train"]
        e["receivers"] = sorted(set(e["receivers"]) | set(m["receivers"]))
        e["source_registry"] = sorted(set(e["source_registry"]) | {"mm.inventory.MODULES"})
    for g in [e for e in entries if e["category"] == "GROUP"]:
        for v in g["variants"]:
            if v in by_id:
                by_id[v]["source_registry"] = sorted(set(by_id[v]["source_registry"]) | {f"sh.models.REGISTRY ({g['id'].split(':', 1)[1]})"})
    if by_id.get("flow:reaction_m1"):
        by_id["flow:reaction_m1"]["variants"] = ["flow:LOGREG", "flow:XGB"]
    _probe(entries, rt, inst)
    _live_outputs(entries, rt)
    for e in entries:
        if e["category"] == "?":
            e["category"] = "UNCLASSIFIED"
    return {"version": VERSION, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "instrument": inst,
            "runtime": "LIVE" if rt is not None else "OFFLINE (bez działającego bota – stany reguł i usług NOT_EVALUATED)",
            "entries": entries, "coverage": coverage(entries)}


def coverage(entries: list[dict]) -> dict:
    real = [e for e in entries if e["code_state"] != "GROUP"]
    impl = [e for e in real if e["code_state"] == "IMPLEMENTED"]
    classified = [e for e in real if e["category"] not in ("UNCLASSIFIED", "?")]
    with_adapter = [e for e in impl if e["adapter"]]
    justified = [e for e in impl if not e["adapter"] and e["not_applicable_reason"]]
    missing = [e["id"] for e in impl if not e["adapter"] and not e["not_applicable_reason"]]
    live = any(e.get("live_output") not in (None, "NOT_EVALUATED") for e in impl)
    oper = [e for e in impl if e.get("live_output") == "READY"] if live else []
    evaluated = [e for e in impl if e.get("live_output") not in (None, "NOT_EVALUATED")] if live else []
    anal = [e for e in impl if e["validation"] == "VALIDATED"]
    need_val = [e for e in impl if e["validation"] != "NOT_APPLICABLE"]
    return {
        "inventory": {"recognised": len(real), "classified": len(classified), "groups_expanded": len(entries) - len(real),
                      "aliases_folded": sum(len(e["aliases"]) for e in real),
                      "by_category": _count(real, "category"), "by_code_state": _count(real, "code_state")},
        "adapters": {"implemented": len(impl), "with_adapter": len(with_adapter), "not_applicable_justified": len(justified), "missing": missing},
        "operational": {"evaluated": len(evaluated), "ready_with_live_output": len(oper), "ids": [e["id"] for e in oper],
                        "by_runtime_state": _count(impl, "runtime_state"),
                        "probe_ok_with_adapter": len([e for e in impl if e["runtime_state"] in OPERATIONAL and e["adapter"]]),
                        "note": "liczone z opublikowanej generacji Quant Core (ważny, świeży wynik READY); offline – nieoceniane"},
        "analytical": {"requiring_validation": len(need_val), "validated_for_role": len(anal), "ids": [e["id"] for e in anal],
                       "note": "pełne pokrycie katalogu nie oznacza gotowości modeli"},
    }


def _count(es, k) -> dict:
    out: dict = {}
    for e in es:
        out[e[k]] = out.get(e[k], 0) + 1
    return dict(sorted(out.items()))


def to_markdown(inv: dict) -> str:
    c = inv["coverage"]
    L = ["# Inwentaryzacja komponentów obliczeniowych – Apollo23 Quant Core", "",      # 1.46: display name (identifiers unchanged)
         f"Wygenerowano: {inv['generated_at']} · instrument: {inv['instrument']} · tryb: {inv['runtime']} · generator: `python -m masterquo quant inventory` ({VERSION})", "",
         "Plik maszynowy: `docs/quant/INVENTORY.json`. Kanoniczne identyfikatory i aliasy: `backend/masterquo/quant/ids.py`.", "",
         "## Pokrycie (cztery osobne miary)", "",
         f"* **Inwentaryzacja:** rozpoznano {c['inventory']['recognised']} komponentów, sklasyfikowano {c['inventory']['classified']}; "
         f"rozwinięto {c['inventory']['groups_expanded']} wierszy grupowych; złożono {c['inventory']['aliases_folded']} aliasów.",
         f"* **Adaptery:** zaimplementowanych {c['adapters']['implemented']}; z adapterem/odbiorcą {c['adapters']['with_adapter']}; "
         f"uzasadnione NOT_APPLICABLE {c['adapters']['not_applicable_justified']}; brakujące: {', '.join(c['adapters']['missing']) or 'brak'}.",
         f"* **Gotowość operacyjna:** ocenionych {c['operational']['evaluated']}; z działającym wyjściem na żywo {c['operational']['ready_with_live_output']} "
         f"({', '.join(c['operational']['ids']) or 'brak'}); sondy OK z adapterem: {c['operational']['probe_ok_with_adapter']}. {c['operational']['note']}.",
         f"* **Gotowość analityczna:** wymagających walidacji {c['analytical']['requiring_validation']}; zwalidowanych dla roli {c['analytical']['validated_for_role']}. "
         f"{c['analytical']['note']}.", "",
         "Kategorie: " + ", ".join(f"{k}={v}" for k, v in c["inventory"]["by_category"].items()), "",
         "## Komponenty", "",
         "| Kanoniczny id | Aliasy | Kategoria | Zadanie / jednostka | TF / horyzont | Stan kodu | Stan działania | Walidacja | Rola w Quant Core | Adapter / uzasadnienie |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for e in inv["entries"]:
        ad = e["adapter"] or ("NOT_APPLICABLE: " + (e["not_applicable_reason"] or "?"))
        task = " / ".join(x for x in (e["task_type"], e["task"], e["unit"]) if x) or "–"
        tf = ", ".join(e["timeframes"]) or "–"
        if e["horizon"]:
            tf += f"; {e['horizon']}"
        st = e["runtime_state"] + (f" ({e['state_reason']})" if e["state_reason"] else "")
        if e.get("live_output") not in (None, "NOT_EVALUATED", "NOT_APPLICABLE"):
            st += f"; wynik na żywo: {e['live_output']}"
        L.append("| " + " | ".join(str(x).replace("|", "/").replace("\n", " ") for x in (
            f"`{e['id']}`", ", ".join(e["aliases"]) or "–", e["category"], task, tf, e["code_state"], st[:220], e["validation"],
            ROLE_PL.get(e["quant_role"], e["quant_role"]), ad[:240])) + " |")
    L += ["", "## Szczegóły (pliki, właściciele, środowiska, odbiorcy)", ""]
    for e in inv["entries"]:
        L.append(f"### `{e['id']}` – {e['name']}")
        for k, lab in (("files", "Pliki"), ("input", "Wejście"), ("output", "Wyjście"), ("data_required", "Wymagane dane"), ("features", "Cechy"),
                       ("owner_train", "Właściciel treningu"), ("owner_infer", "Właściciel inferencji"), ("env", "Środowisko"), ("artifact", "Artefakt"),
                       ("dependencies", "Zależności"), ("receivers", "Odbiorcy"), ("variants", "Warianty / członkowie"), ("source_registry", "Rejestry źródłowe"),
                       ("notes", "Uwagi")):
            v = e.get(k)
            if v:
                L.append(f"* {lab}: " + (", ".join(f"`{x}`" if k == "files" else str(x) for x in v) if isinstance(v, list) else str(v)))
        L.append("")
    return "\n".join(L) + "\n"


def write(out_dir: Path, rt=None, inst: str = "XAUUSD") -> dict:
    inv = build(rt, inst)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "INVENTORY.json").write_text(json.dumps(inv, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    (out_dir / "INVENTORY.md").write_text(to_markdown(inv), encoding="utf-8")
    return inv
