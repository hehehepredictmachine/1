"""Full inventory of the computational components of the bot (PMW-QUANT-INV-1) -> docs/quant/INVENTORY.md / INVENTORY.json.

Sources (read from the code at generation time, nothing typed by hand twice): sh/models.REGISTRY (37 rows), modelhub/families registry
(15 + SEQ_GRU_EVENT adapter), trainhub/learn.MODELS (6), mm/inventory.MODULES (20), lab/protocol.FAMILIES + EXPERIMENTS,
lab/structure_nets.FAMILIES, lab/si_families.FAMILIES, lab/flow_context/task.FAMILIES, plus the analysis services wired in runtime.py.
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

from . import ids as I

VERSION = "PMW-QUANT-INV-1"
OPERATIONAL = ("READY", "SHADOW_ONLY", "DETERMINISTIC_OK")

# quant roles (how Quant Core uses the output)
ROLE_PL = {"GATE_EXISTING": "istniejąca bramka (bez zmian)", "CONTEXT_FEATURE": "cecha kontekstu meta-modelu (z maską braku)",
           "BASE_FORECAST": "prognoza bazowa – cecha meta-modelu pod własną nazwą", "SETUP_EVENT": "prawdopodobieństwo zdarzenia setupu (ewaluacja)",
           "TOOL": "narzędzie / proces uczenia / optymalizacja – nie głos", "NOT_A_VOTE": "opis / opinia – bez p(win)",
           "META_MODEL": "Quant MetaModel", "SIMULATION": "symulacja (MODEL_SIMULATED) – nie skalibrowane p", "NONE": "brak (nie istnieje)"}

# adapter of the live output into PMW-PRED-2 (quant/adapters.py) or the justified NOT_APPLICABLE reason
A_EXISTING = "modelhub.adapters.all_predictions"
A_FAM = "modelhub.families.service.predictions"
A_EXT = "quant.adapters.extended"
A_SETUP = "evaluation.service (prawdopodobieństwo per kandydat setupu)"

_OVR: dict[str, dict] = {
    # --- rules / measurements (SH deterministic rows) -------------------------------------------------------------
    "rule:data_quality": {"role": "GATE_EXISTING", "adapter": A_EXT, "files": ["backend/masterquo/mt5/bridge.py"], "unit": "state", "task_type": "STATE",
                          "data": "notowanie MT5, zegar, spread", "receivers": ["sh.service", "engine.decision", "quant.snapshot"]},
    "rule:risk_engine": {"role": "GATE_EXISTING", "adapter": None, "na": "bramka ryzyka liczona w ścieżce wykonania (RiskBook / risk/portfolio.py) – Quant jej nie dubluje",
                         "files": ["backend/masterquo/sh/risk.py", "backend/masterquo/risk/portfolio.py"], "unit": "state", "task_type": "STATE"},
    "rule:news": {"role": "GATE_EXISTING", "adapter": A_EXT, "files": ["backend/masterquo/news/"], "unit": "state", "task_type": "STATE",
                  "data": "kalendarz makro (czas pierwszego odbioru)"},
    "rule:regime_v2": {"role": "CONTEXT_FEATURE", "adapter": A_EXT, "unit": "state", "task_type": "STATE", "tfs": ["M5", "M15", "H1"]},
    "rule:structure_v2": {"role": "CONTEXT_FEATURE", "adapter": A_EXT, "unit": "state", "task_type": "STATE", "tfs": ["M5", "M15", "H1"]},
    "rule:smc_pullback": {"role": "CONTEXT_FEATURE", "adapter": None, "na": "stan SMC w context_ind – brak stabilnego akcesora poza panelem; cecha strukturalna z structure_v2"},
    "rule:vamd": {"role": "CONTEXT_FEATURE", "adapter": None, "na": "VAMD liczony per wykres w context_ind (panel); bez akcesora snapshotu – nie jest modelem „Quant Ultimate Momentum Pro”"},
    "rule:fractal": {"role": "CONTEXT_FEATURE", "adapter": None, "na": "Katz FD liczony per wykres w context_ind; bez akcesora snapshotu"},
    "rule:atr_vol": {"role": "CONTEXT_FEATURE", "adapter": A_EXT, "unit": "price", "task_type": "STATE", "tfs": ["M1", "M5"]},
    "rule:candles_patterns": {"role": "CONTEXT_FEATURE", "adapter": None, "na": "formacje opisowe (role świec) – kontekst panelu, bez liczbowego wyjścia"},
    "rule:liquidity": {"role": "CONTEXT_FEATURE", "adapter": None, "na": "poziomy płynności (strefy) – w mapie stref; cecha odległości dostępna przez quant.snapshot"},
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
                           "task_type": "EVENT_PROBABILITY", "files": ["backend/masterquo/scalp/service.py"]},
    "nss:tcn": {"role": "SETUP_EVENT", "adapter": None, "na": "P(TP1_FIRST/SL_FIRST/TIMEOUT) innego setupu – liczony per plan w scalp.neural", "unit": "probability",
                "task_type": "CLASS_PROBABILITIES", "files": ["backend/masterquo/lab/nss_service.py"]},
    "flow:reaction_m1": {"role": "BASE_FORECAST", "adapter": None, "na": "model reakcji M1 liczony per wykres w flow_context (panel) – bez akcesora snapshotu poza panelem",
                         "unit": "probability", "task_type": "CLASS_PROBABILITIES", "tfs": ["M1"], "files": ["backend/masterquo/lab/flow_context/"],
                         "variants": ["flow:LOGREG", "flow:XGB"]},
    "context_ind:context_move_m5": {"role": "BASE_FORECAST", "adapter": None, "na": "NOT_CONNECTED: model badawczy bez ścieżki inferencji na żywo (F-17)",
                                    "unit": "probability", "task_type": "CLASS_PROBABILITIES", "tfs": ["M5"], "files": ["backend/masterquo/lab/context_ind/"]},
    # --- MM ---------------------------------------------------------------------------------------------------------
    "mm:align_mean": {"role": "CONTEXT_FEATURE", "adapter": A_EXT, "unit": "atr", "task_type": "STATE"},
    "mm:kalman_cross": {"role": "CONTEXT_FEATURE", "adapter": A_EXT, "unit": "state", "task_type": "FILTER_STATE", "tfs": ["M5"]},
    "mm:breakout_zones": {"role": "CONTEXT_FEATURE", "adapter": A_EXT, "unit": "state", "task_type": "FILTER_STATE", "tfs": ["M5"]},
    "mm:multi_indicator": {"role": "CONTEXT_FEATURE", "adapter": A_EXT, "unit": "state", "task_type": "STATE", "tfs": ["M5"]},
    "mm:smc_fvg": {"role": "CONTEXT_FEATURE", "adapter": A_EXT, "unit": "state", "task_type": "STATE", "tfs": ["M5"]},
    "mm:gpr_logret": {"role": "BASE_FORECAST", "adapter": A_EXT, "unit": "log_return", "task_type": "REGRESSION", "task": "LOG_RETURN_H3_M5", "tfs": ["M5"],
                      "horizon": "3 świece M5"},
    "mm:hdc_dir3": {"role": "BASE_FORECAST", "adapter": None, "na": "margines HDC (nie prawdopodobieństwo); brak ścieżki na żywo bez artefaktu VALIDATED_SHADOW",
                    "unit": "score_0_100", "task_type": "SCORE", "tfs": ["M5"]},
    "mm:event_engine_dir3": {"role": "BASE_FORECAST", "adapter": A_EXT, "unit": "probability", "task_type": "CLASS_PROBABILITIES", "task": "EVENT_UNITS_DIR3",
                             "tfs": ["EVENT"], "horizon": "2 jednostki zdarzeń (16 zdarzeń/jednostka)"},
    "mm:ste_flownet_ret": {"role": "BASE_FORECAST", "adapter": None, "na": "brak ścieżki na żywo (tylko artefakt badawczy); log-zwrot h zdarzeń",
                           "unit": "log_return", "task_type": "REGRESSION", "tfs": ["EVENT"]},
    # --- other SH rows ------------------------------------------------------------------------------------------------
    "kronos:Kronos-small": {"role": "BASE_FORECAST", "adapter": A_EXISTING, "unit": "price", "task_type": "REGRESSION", "task": "KRONOS_CLOSE_PATH_H*",
                            "tfs": ["M1", "M5", "M15", "H1"], "env": ".venv_kronos", "files": ["backend/masterquo/kronos/", "backend/kronos_runtime/"],
                            "notes": "pojedyncza ścieżka nie jest prawdopodobieństwem; pretrained ≠ dostrojony do brokera"},
    "agent:claude": {"role": "NOT_A_VOTE", "adapter": None, "na": "opis / weto tekstowe agenta – bez p(win); poza meta-modelem", "unit": "state", "task_type": "STATE"},
}

_MM_TO_CANON = {"align_mean": "mm:align_mean", "hdc": "mm:hdc_dir3", "smc_fvg": "mm:smc_fvg", "event_engine": "mm:event_engine_dir3",
                "ste_flownet": "mm:ste_flownet_ret", "gpr": "mm:gpr_logret", "kalman": "mm:kalman_cross", "breakout_zones": "mm:breakout_zones",
                "multi_indicator": "mm:multi_indicator"}
_MM_TOOL = {"buzoa": "TOOL", "sdom": "TOOL", "stfs": "TOOL", "quant_momentum": "NONE", "renko": "NONE", "head_shoulders": "NONE",
            "data_grabber": "TOOL", "tsvp": "TOOL", "mathbench": "TOOL", "chart_sync": "TOOL", "fusion_board": "TOOL"}


def _e(cid: str, **kw) -> dict:
    base = {"id": cid, "aliases": I.aliases_of(cid), "name": cid, "category": "?", "files": [], "input": None, "output": None, "unit": None,
            "task_type": None, "task": None, "horizon": None, "timeframes": [], "data_required": None, "features": None, "owner_train": None,
            "owner_infer": None, "env": ".venv", "artifact": None, "dependencies": [], "code_state": "IMPLEMENTED", "runtime_state": "NOT_EVALUATED",
            "state_reason": None, "validation": "NOT_APPLICABLE", "receivers": [], "quant_role": "CONTEXT_FEATURE", "adapter": None,
            "not_applicable_reason": None, "variants": [], "source_registry": [], "notes": None}
    base.update({k: v for k, v in kw.items() if v is not None})
    o = _OVR.get(cid) or {}
    for k_src, k_dst in (("role", "quant_role"), ("adapter", "adapter"), ("na", "not_applicable_reason"), ("files", "files"), ("unit", "unit"),
                         ("task_type", "task_type"), ("task", "task"), ("tfs", "timeframes"), ("horizon", "horizon"), ("env", "env"),
                         ("train", "owner_train"), ("infer", "owner_infer"), ("data", "data_required"), ("receivers", "receivers"),
                         ("variants", "variants"), ("notes", "notes")):
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
        cat = {"DETERMINISTIC": "RULE_OR_MEASUREMENT", "TRAINED": "MODEL_TRAINED", "EXTERNAL": "AGENT"}[it["kind"]]
        if sid == "kronos":
            cat = "MODEL_PRETRAINED"
        out.append(_e(cid, name=it["name"], category=cat, output=it["output"], owner_train=it.get("train"), source_registry=["sh.models.REGISTRY"],
                      receivers=[f"SH:{it['roles']['SCALPING']}/{it['roles']['HEDGING']}"], dependencies=[f"grupa korelacji {it['group']}"],
                      _sh=it))
    return out


def _family_rows() -> list[dict]:
    from ..modelhub.families import registry
    out = []
    for fid, f in registry().items():
        cid = I.resolve(fid)
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
                      artifact=f"<data>/families/{fid}/<instrument>/runs/<run_id>",
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
                      owner_train="trainhub.jobs.TrainingCenter", owner_infer="trainhub.inference.TrainhubInference", artifact="<data>/trainhub/<instrument>/<model_key>/<version>",
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
        out.append(_e(f"lab:{f}", name=f"Lab {f}", category="MODEL_TRAINED" if f not in ("DUMMY", "RULE") else "BASELINE",
                      files=["backend/masterquo/lab/protocol.py", "backend/masterquo/lab/service.py"], unit="score_0_100", task_type="SCORE",
                      task="TRIPLE_BARRIER_1.5ATR_LONG (score nieskalibrowany)", timeframes=["M5"], owner_train="lab (training: lab)", owner_infer="lab.service",
                      artifact="<data>/lab/models/<asset>/", validation="NOT_VALIDATED", quant_role="BASE_FORECAST" if f not in ("DUMMY", "RULE") else "TOOL",
                      adapter=A_EXT, source_registry=["lab.protocol.FAMILIES"], notes="score innego zdarzenia niż TP setupu – cecha pod własną nazwą"))
    for x in getattr(P, "EXPERIMENTS", ()):
        out.append(_e(f"lab:{x}", name=f"Eksperyment lab {x}", category="RESEARCH", files=["backend/masterquo/lab/protocol.py"], quant_role="TOOL",
                      not_applicable_reason="eksperyment badawczy (PCA / GMM / neutralizacja) – wariant LOGREG, bez ścieżki na żywo",
                      source_registry=["lab.protocol.EXPERIMENTS"], validation="NOT_VALIDATED"))
    for f in tuple(SN.FAMILIES) + tuple(SF.FAMILIES):
        out.append(_e(f"si:{f}", name=f"Structure Intelligence {f}", category="MODEL_TRAINED",
                      files=["backend/masterquo/lab/structure_nets.py" if f in SN.FAMILIES else "backend/masterquo/lab/si_families.py", "backend/masterquo/lab/si_service.py"],
                      unit="probability", task_type="CLASS_PROBABILITIES", task="M1_MOVE_H3/5/15 (DOWN/FLAT/UP + kwantyle r_h/ATR)", timeframes=["M1"],
                      owner_train="training (structure_intelligence)", owner_infer="lab.si_service", artifact="<data>/structure_intelligence/<instrument>/",
                      validation="NOT_VALIDATED", quant_role="BASE_FORECAST", adapter=None,
                      not_applicable_reason="wynik liczony w raporcie SI na żądanie panelu; brak publikowanej predykcji na żywo – stan z rejestru",
                      source_registry=["lab.structure_nets.FAMILIES" if f in SN.FAMILIES else "lab.si_families.FAMILIES"]))
    return out


def _mm_rows() -> list[dict]:
    from ..mm import inventory as MI
    out = []
    for m in MI.MODULES:
        cid = _MM_TO_CANON.get(m["id"])
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
                      state_reason="NO_SPEC" if nospec else None))
    return out


def _analysis_rows() -> list[dict]:
    rows = [
        ("analysis:montecarlo", "Monte Carlo (PMW-MC-1) – symulacja ścieżek", "SIMULATION", ["backend/masterquo/montecarlo/"], "SIMULATION",
         "MODEL_SIMULATED – wynik symulacji, nie prawdopodobieństwo skalibrowane na zdarzeniach"),
        ("analysis:zones", "Mapa stref (PMW-ZONES)", "ANALYSIS", ["backend/masterquo/zones/"], "CONTEXT_FEATURE", None),
        ("analysis:market_zones", "Strefy rynkowe M1/M5/M15/M30 (1.28)", "ANALYSIS", ["backend/masterquo/zones/market_service.py"], "CONTEXT_FEATURE",
         "liczone na żądanie panelu (job) – brak cyklu niezależnego od panelu"),
        ("analysis:indicators", "Wskaźniki PMW-IND-1 (EMA/VWAP/RSI/MACD/BB, mikrostruktura, DXY)", "ANALYSIS", ["backend/masterquo/indicators/"],
         "CONTEXT_FEATURE", None),
        ("analysis:svp", "Session Volume Profile (PMW-SVP-1)", "ANALYSIS", ["backend/masterquo/svp/"], "CONTEXT_FEATURE",
         "profile użytkownika (tick volume = aktywność feedu, nie wolumen obrotu) – kontekst panelu"),
        ("analysis:dxy_correlation", "Korelacja XAUUSD–DXY (PMW-IND-1 dxy)", "ANALYSIS", ["backend/masterquo/indicators/"], "CONTEXT_FEATURE", None),
        ("analysis:walls", "Opcje / walls / IV (opcjonalne źródło)", "ANALYSIS", ["backend/masterquo/analysis/"], "CONTEXT_FEATURE",
         "wymaga importu IV (import-iv); brak źródła = stan danych, nie zero"),
        ("analysis:evaluation", "AI Setup Probability Engine (PMW-EVAL)", "ANALYSIS", ["backend/masterquo/evaluation/"], "SETUP_EVENT", None),
        ("quant:metamodel", "PMW Quant MetaModel (logistyczny + net R ridge, OOF, kalibracja)", "META_MODEL", ["backend/masterquo/quant/metamodel.py"],
         "META_MODEL", None),
    ]
    out = []
    for cid, name, cat, files, role, na in rows:
        ad = {"analysis:indicators": A_EXT, "analysis:dxy_correlation": A_EXT, "analysis:zones": A_EXT, "analysis:montecarlo": A_EXT,
              "analysis:evaluation": "evaluation.service (ledger)", "quant:metamodel": "quant.service (assessment)"}.get(cid)
        out.append(_e(cid, name=name, category=cat, files=files, quant_role=role, adapter=ad, not_applicable_reason=na if not ad else None,
                      notes=na if ad else None, source_registry=["runtime.py"], validation="NOT_VALIDATED" if cat in ("META_MODEL", "SIMULATION") else "NOT_APPLICABLE"))
    out.append(_e("ext:catboost", name="CatBoost", category="NOT_IMPLEMENTED", code_state="NOT_IMPLEMENTED", quant_role="NONE", runtime_state="UNAVAILABLE",
                  state_reason="wspomniany w dokumentacji / traceability (M06); brak implementacji i zależności w kodzie",
                  not_applicable_reason="nie istnieje w kodzie – nie dodano fikcyjnego adaptera", source_registry=["lab/traceability.py (wzmianka)"]))
    return out


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
                from ..trainhub import registry as TR
                s = TR.summary(inst)
                key = e["id"].split(":", 1)[1]
                mine = [v for v in s.get("versions") or [] if str(v.get("model_key", "")).startswith(key + "_")]
                act = {k: v for k, v in (s.get("active") or {}).items() if k.startswith(key + "_")}
                e["runtime_state"] = "SHADOW_ONLY" if act else ("CANDIDATE" if mine else "NOT_TRAINED")
                e["state_reason"] = (f"aktywne: {act}" if act else f"wersji: {len(mine)}, brak aktywnej paczki")
        except Exception as exc:  # noqa: BLE001 - a broken probe is a state, never a crash of the inventory
            e["runtime_state"], e["state_reason"] = "ERROR", f"{type(exc).__name__}: {exc}"[:160]


def build(rt=None, inst: str = "XAUUSD") -> dict:
    entries = _sh_rows() + _trainhub_rows() + _family_rows() + _lab_rows()
    merges = []
    for r in _mm_rows():
        if "_merge" in r:
            merges.append(r)
        else:
            entries.append(r)
    entries += _analysis_rows()
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
    oper = [e for e in impl if e["runtime_state"] in OPERATIONAL and e["adapter"]]
    evaluated = [e for e in impl if e["runtime_state"] != "NOT_EVALUATED"]
    anal = [e for e in impl if e["validation"] == "VALIDATED"]
    need_val = [e for e in impl if e["validation"] != "NOT_APPLICABLE"]
    return {
        "inventory": {"recognised": len(real), "classified": len(classified), "groups_expanded": len(entries) - len(real),
                      "aliases_folded": sum(len(e["aliases"]) for e in real),
                      "by_category": _count(real, "category"), "by_code_state": _count(real, "code_state")},
        "adapters": {"implemented": len(impl), "with_adapter": len(with_adapter), "not_applicable_justified": len(justified), "missing": missing},
        "operational": {"evaluated": len(evaluated), "ready_with_live_output": len(oper), "ids": [e["id"] for e in oper],
                        "by_runtime_state": _count(impl, "runtime_state"),
                        "note": "dane + wagi + poprawna inferencja; przy generowaniu offline stany usług nie są oceniane"},
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
    L = [f"# Inwentaryzacja komponentów obliczeniowych – PMW Quant Core", "",
         f"Wygenerowano: {inv['generated_at']} · instrument: {inv['instrument']} · tryb: {inv['runtime']} · generator: `python -m masterquo quant inventory` ({VERSION})", "",
         "Plik maszynowy: `docs/quant/INVENTORY.json`. Kanoniczne identyfikatory i aliasy: `backend/masterquo/quant/ids.py`.", "",
         "## Pokrycie (cztery osobne miary)", "",
         f"* **Inwentaryzacja:** rozpoznano {c['inventory']['recognised']} komponentów, sklasyfikowano {c['inventory']['classified']}; "
         f"rozwinięto {c['inventory']['groups_expanded']} wierszy grupowych; złożono {c['inventory']['aliases_folded']} aliasów.",
         f"* **Adaptery:** zaimplementowanych {c['adapters']['implemented']}; z adapterem/odbiorcą {c['adapters']['with_adapter']}; "
         f"uzasadnione NOT_APPLICABLE {c['adapters']['not_applicable_justified']}; brakujące: {', '.join(c['adapters']['missing']) or 'brak'}.",
         f"* **Gotowość operacyjna:** ocenionych {c['operational']['evaluated']}; z działającym wyjściem na żywo {c['operational']['ready_with_live_output']}. {c['operational']['note']}.",
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
