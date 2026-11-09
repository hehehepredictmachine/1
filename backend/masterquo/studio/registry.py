"""Studio task registry (PMW-STUDIO-REG-1): every real model of the project expanded to CONCRETE tasks (model x task x instrument x TF x
horizon x side). One task = one export = one package. Categories: TRAINABLE, FITTABLE, CALIBRATABLE, DETERMINISTIC, PRETRAINED, SIMULATION,
EXTERNAL / NOT_IMPLEMENTED. The same list feeds the UI, the queue and MODEL_DATA_MATRIX.json - no second catalog."""
from __future__ import annotations

import hashlib
import json

VERSION = "PMW-STUDIO-REG-1"
INSTRUMENTS = ("XAUUSD", "BTC")
ADAPTER_VERSION = {"TRAINHUB": "1", "FAMILY": "1", "RUNNER_GROUP": "1", "DETERMINISTIC": "1", "PRETRAINED": "1"}

RUNNER_GROUPS = {   # existing training/runner.py tasks: each is ONE model task group with its own trainer + registry; activation stays manual
    "forecast": ("TRAINABLE", "gold_candles 5/15/30 min (kierunek świecy)", ".venv_candles", ["M5", "M30"]),
    "scalp_A": ("TRAINABLE", "Scalp A/B: kierunek 1/3/5 min + P(TP1 przed SL); C = ocena polityki w replayu", ".venv", ["M1", "M15", "H1"]),
    "ml": ("TRAINABLE", "Legacy ML: Decision Tree + XGBoost na historii setupów S01–S12", ".venv", ["M5", "M15", "H1"]),
    "lab": ("TRAINABLE", "Lab: LOGREG/TREE/MiniRocket/XGB/ResNet1D/SEW-SNN (strona LONG)", ".venv", ["M1", "M5"]),
    "indicator_context": ("CALIBRATABLE", "SAR + IQ/PAL: kalibracja SAR i model reakcji P(TP1 przed SL)", ".venv", ["M1", "M5"]),
    "ml_scalp": ("TRAINABLE", "Scalp ML: XGBoost P(wynik netto > 0) + net_R, osobno LONG/SHORT", ".venv", ["M1", "M5"]),
    "neural_scalp": ("TRAINABLE", "Neural Scalp System: TCN M1/M5 – P(TP1/SL/TIMEOUT), net_R", ".venv", ["M1", "M5"]),
    "structure_intelligence": ("TRAINABLE", "Structure Intelligence: ruch M1 h=3/5/15", ".venv", ["M1", "M5", "M15"]),
    "flow_context": ("CALIBRATABLE", "Flow context: kalibracja + model reakcji FLOW_CONTEXT_MOVE_M1_V1", ".venv", ["M1", "M5"]),
    "context_indicators": ("CALIBRATABLE", "VAMD / FD / Pullback+SMC: kalibracja + CONTEXT_MOVE_M5_V1", ".venv", ["M5"]),
    "sh_models": ("TRAINABLE", "SCALPING/HEDGING: model zdarzenia P(TP2 przed SL) + replay", ".venv", ["M1", "M5", "M15", "H1"]),
    "monte_carlo": ("SIMULATION", "Monte Carlo ścieżek: walidacja wariantów IID/BLOCK/REGIME", ".venv", ["M1", "M5"]),
    "master_models": ("TRAINABLE", "Master models: HDC/GPR/event engine/STE-FlowNet + ewaluacja deterministycznych", ".venv", ["M5"]),
}
DETERMINISTIC = {
    "IND_AVWAP_SESSION": ("AVWAP od początku sesji (PMW-IND-AVWAP-1)", "M5"),
    "IND_SEMIVAR": ("Semiwariancja 20/60 M1 (PMW-IND-SEMIVAR-1)", "M1"),
    "IND_XAU_DXY": ("Relacja XAUUSD × DXY H1 (PMW-IND-DXY-1)", "H1"),
}


def _key(d: dict) -> str:
    return hashlib.sha256(json.dumps({k: d.get(k) for k in ("model_id", "task_id", "instrument", "base_tf", "horizon", "side",
                                                             "feature_schema_version", "label_schema_version", "adapter", "adapter_version",
                                                             "config_hash")}, sort_keys=True).encode()).hexdigest()[:16]


def _task(**kw) -> dict:
    kw.setdefault("side", None)
    kw.setdefault("config_hash", hashlib.sha256(json.dumps(kw.get("config") or {}, sort_keys=True).encode()).hexdigest()[:12])
    kw["adapter_version"] = ADAPTER_VERSION[kw["adapter"]]
    kw["task_key"] = f"{kw['model_id']}:{kw['instrument']}:{kw['base_tf']}:H{kw.get('horizon')}:{_key(kw)}"
    return kw


def tasks(cfg_store=None) -> list[dict]:
    from ..trainhub import dataset as TD
    from ..trainhub import features as TF
    from ..trainhub import learn as TL
    from ..trainhub import pipeline as TP
    sym = {}
    if cfg_store is not None:
        try:
            m = cfg_store.get().assets.mappings
            sym = {k: v.broker_symbol for k, v in m.items()}
        except Exception:  # noqa: BLE001
            sym = {}
    out = []
    avail = TL.available()
    for inst in INSTRUMENTS:
        for mid, spec in TL.MODELS.items():
            out.append(_task(model_id=mid, task_id="DIRECTION_H_AFTER_COST", instrument=inst, broker_symbol=sym.get(inst), base_tf=TP.DEFAULTS["base_tf"],
                             horizon=TP.DEFAULTS["horizon"], feature_schema_version=TF.FEATURE_SCHEMA, label_schema_version=TD.LABEL_VERSION,
                             adapter="TRAINHUB", category="TRAINABLE", name=spec["name"], trainer="trainhub.pipeline.stage_train",
                             loader="trainhub.registry.load + prediction_test", env=".venv",
                             sources=[{"kind": "BARS", "tf": tf, "mandatory": True} for tf in ("M1", "M5", "M15", "M30")],
                             resume={"export": "CHUNK_CHECKPOINT", "training": "RESTART_FROM_DATASET"},
                             state="SUPPORTED" if avail.get(mid) else "BLOCKED_DEPENDENCY",
                             reason=None if avail.get(mid) else "biblioteka niedostępna", transfer="TRAINHUB_REGISTRY", config={"models": [mid]}))
        from ..modelhub.families import registry as famreg
        for fid, f in famreg().items():
            if fid in ("TH_RF", "TH_XGB", "TH_SVM"):
                continue                                                        # trained through the TRAINHUB tasks above
            kind = f.DATA.get("kind")
            cat = {"TRAINED": "TRAINABLE", "ESTIMATED": "FITTABLE", "VALIDATED_RULES": "CALIBRATABLE", "MEASUREMENT": "TRAINABLE",
                   "PRETRAINED_ADAPTER": "EXTERNAL"}[f.KIND]
            impl, why = f.implementation()
            st = "SUPPORTED" if impl == "AVAILABLE" else "BLOCKED_DEPENDENCY"
            if fid == "SEQ_GRU_EVENT":
                st, why = "EXTERNAL", "trening w Centrum MM (mm/event_engine) – Studio pokazuje stan, nie trenuje drugi raz"
            src = {"BARS": [{"kind": "BARS", "tf": f.DATA.get("tf") or f.TF, "mandatory": True}],
                   "MULTI_SERIES": [{"kind": "BARS_MULTI", "tf": f.TF, "mandatory": True, "config": f.DATA.get("config")}],
                   "L2_BOOK": [{"kind": "BOOK_SNAPSHOTS", "mandatory": True, "note": "archiwum arkusza bota (book_snapshots)"}],
                   "TEXT": [{"kind": "TEXT_CORPUS", "mandatory": True, "note": "import JSONL/CSV"}],
                   "EVENTS": [{"kind": "EVENTS", "mandatory": True}]}.get(kind, [])
            out.append(_task(model_id=fid, task_id=f.TASK, instrument=inst, broker_symbol=sym.get(inst), base_tf=f.TF or "NONE",
                             horizon=(f.HORIZONS[0] if f.HORIZONS else None), feature_schema_version=f.DATA.get("schema") or f"{fid}-1",
                             label_schema_version=f.TASK, adapter="FAMILY", category=cat, name=f.NAME, trainer="modelhub.families.run.train",
                             loader="FamilyService.activate (próbka inferencji)", env=".venv_deep" if f.RUNTIME == "DEEP" else ".venv",
                             sources=src, resume={"export": "CHUNK_CHECKPOINT", "training": "RESTART_FROM_DATASET"}, state=st, reason=why,
                             transfer="FAMILY_STORE", fit_label=f.FIT_LABEL))
        for kind, (cat, title, env, tfs) in RUNNER_GROUPS.items():
            out.append(_task(model_id=f"RUNNER:{kind}", task_id=kind, instrument=inst, broker_symbol=sym.get(inst), base_tf=tfs[0], horizon=None,
                             feature_schema_version=f"runner:{kind}", label_schema_version=f"runner:{kind}", adapter="RUNNER_GROUP", category=cat,
                             name=title, trainer=f"training.runner STEPS['{kind}'] (jawny dataset, bez aktywacji)", loader="rejestr zadania (runner)",
                             env=env, sources=[{"kind": "BARS_RUNNER_EXPORT", "tf": t, "mandatory": True} for t in tfs],
                             resume={"export": "RUNNER_EXPORT", "training": "RESTART_FROM_DATASET"}, state="SUPPORTED", reason=None,
                             transfer="MANUAL_ACTIVATION_IN_BOT", group_note="zadanie grupowe runnera – wewnątrz osobne modele i artefakty"))
        for iid, (title, tf) in DETERMINISTIC.items():
            out.append(_task(model_id=iid, task_id="FEATURE_EXPORT", instrument=inst, broker_symbol=sym.get(inst), base_tf=tf, horizon=None,
                             feature_schema_version=iid, label_schema_version="NOT_APPLICABLE", adapter="DETERMINISTIC", category="DETERMINISTIC",
                             name=title, trainer=None, loader=None, env=".venv",
                             sources=[{"kind": "BARS", "tf": tf, "mandatory": True}] + ([{"kind": "BARS_DXY", "tf": "H1", "mandatory": True}]
                                                                                       if iid == "IND_XAU_DXY" else []),
                             resume={"export": "CHUNK_CHECKPOINT", "training": "NOT_APPLICABLE"}, state="SUPPORTED", reason=None, transfer=None))
        out.append(_task(model_id="KRONOS_BASE", task_id="CANDLE_PATH", instrument=inst, broker_symbol=sym.get(inst), base_tf="M5", horizon=None,
                         feature_schema_version="kronos-tokenizer-base", label_schema_version="NOT_APPLICABLE", adapter="PRETRAINED",
                         category="PRETRAINED", name="Kronos-base (wagi pretrained NeoQuasar, 1.37)", trainer=None,
                         loader="kronos_runtime (.venv_kronos)", env=".venv_kronos", sources=[{"kind": "BARS", "tf": "M5", "mandatory": True}],
                         resume={}, state="EXTERNAL", reason="ewaluacja i instalacja w panelu Kronos bota; fine-tuning nie jest obsługiwany przez projekt",
                         transfer=None))
    return out


def operations(t: dict) -> list[str]:
    c = t["category"]
    if t["state"] in ("EXTERNAL", "NOT_IMPLEMENTED"):
        return []
    if c == "DETERMINISTIC":
        return ["FULL_EXPORT", "VALIDATE", "EXPORT_FEATURES"]
    base = ["FULL_EXPORT", "VALIDATE", "BUILD_DATASET"]
    verb = {"TRAINABLE": "TRAIN", "FITTABLE": "FIT", "CALIBRATABLE": "CALIBRATE", "SIMULATION": "CALIBRATE"}.get(c, "TRAIN")
    return base + [verb, "FULL_PROCESS"] + (["TRANSFER"] if t.get("transfer") in ("TRAINHUB_REGISTRY", "FAMILY_STORE") else [])


def by_key(cfg_store=None) -> dict:
    return {t["task_key"]: t for t in tasks(cfg_store)}


def matrix(cfg_store=None) -> dict:
    rows = []
    for t in tasks(cfg_store):
        rows.append({k: t.get(k) for k in ("task_key", "model_id", "task_id", "instrument", "broker_symbol", "base_tf", "horizon", "side", "category",
                                           "adapter", "sources", "feature_schema_version", "label_schema_version", "trainer", "loader", "env",
                                           "resume", "state", "reason", "transfer")} | {"operations": operations(t)})
    return {"version": VERSION, "rows": rows, "count": len(rows),
            "note": "jeden wiersz = jedno zadanie = jeden eksport = jedna paczka; grupy runnera to istniejące zadania z własnymi rejestrami"}
