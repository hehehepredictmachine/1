"""Studio task registry (PMW-STUDIO-REG-1): every real model of the project expanded to CONCRETE tasks (model x task x instrument x TF x
horizon x side). One task = one export = one package. Categories: TRAINABLE, FITTABLE, CALIBRATABLE, DETERMINISTIC, PRETRAINED, SIMULATION,
EXTERNAL / NOT_IMPLEMENTED. The same list feeds the UI, the queue and MODEL_DATA_MATRIX.json - no second catalog."""
from __future__ import annotations

import hashlib
import json

from ..training import tasks as _TT

VERSION = "PMW-STUDIO-REG-1"
INSTRUMENTS = ("XAUUSD", "BTC")
ADAPTER_VERSION = {"TRAINHUB": "1", "FAMILY": "1", "RUNNER_GROUP": "1", "DETERMINISTIC": "1", "PRETRAINED": "1"}

# existing training/runner.py tasks: each is ONE model task group with its own trainer + registry; activation stays manual. arch146 I0131: from the
# one task registry (training/tasks.py) - the same keys, categories, venvs and Studio export timeframes (a field of their own there)
RUNNER_GROUPS = _TT.studio_runner_groups()
DETERMINISTIC = {
    "IND_AVWAP_SESSION": ("AVWAP od początku sesji (PMW-IND-AVWAP-1)", "M5"),
    "IND_SEMIVAR": ("Semiwariancja 20/60 M1 (PMW-IND-SEMIVAR-1)", "M1"),
    "IND_XAU_DXY": ("Relacja XAUUSD × DXY H1 (PMW-IND-DXY-1)", "H1"),
}
# 1.46: tasks that need series other than the task's own instrument (Studio does not export them - pipeline.run_task refuses them too)
NO_MULTI_SERIES = {"MULTI_SERIES": "Studio nie eksportuje serii pary / koszyka – trenuj w bocie (Centrum modeli)",
                   "IND_XAU_DXY": "Studio nie eksportuje serii DXY – wskaźnik liczy bot"}


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
            if kind == "MULTI_SERIES":
                # 1.46: Studio exports ONLY the task's own instrument - pair / basket tasks (PAIR_COINT, STATARB) were SUPPORTED with export /
                # train buttons and always failed (KeyError pair_bars / basket_bars); the task key does not depend on state / reason
                st, why = "NOT_IMPLEMENTED", NO_MULTI_SERIES["MULTI_SERIES"]
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
            # arch146 I0704: a runner task that does not apply to the instrument (sh_pack: XAUUSD only) was offered as SUPPORTED - the user
            # waited for the export (up to 240 months) and the runner then skipped it (BLOCKED_DEPENDENCY); the task key does not depend on state
            applies = _TT.applies_to(kind, inst)
            out.append(_task(model_id=f"RUNNER:{kind}", task_id=kind, instrument=inst, broker_symbol=sym.get(inst), base_tf=tfs[0], horizon=None,
                             feature_schema_version=f"runner:{kind}", label_schema_version=f"runner:{kind}", adapter="RUNNER_GROUP", category=cat,
                             name=title, trainer=f"training.runner STEPS['{kind}'] (jawny dataset, bez aktywacji)", loader="rejestr zadania (runner)",
                             env=env, sources=[{"kind": "BARS_RUNNER_EXPORT", "tf": t, "mandatory": True} for t in tfs],
                             resume={"export": "RUNNER_EXPORT", "training": "RESTART_FROM_DATASET"},
                             state="SUPPORTED" if applies else "NOT_IMPLEMENTED",
                             reason=None if applies else f"{_TT.NOT_APPLICABLE_DETAIL} {inst}: {_TT.scope_reason(kind)}",
                             transfer="MANUAL_ACTIVATION_IN_BOT", group_note="zadanie grupowe runnera – wewnątrz osobne modele i artefakty"))
        for iid, (title, tf) in DETERMINISTIC.items():
            out.append(_task(model_id=iid, task_id="FEATURE_EXPORT", instrument=inst, broker_symbol=sym.get(inst), base_tf=tf, horizon=None,
                             feature_schema_version=iid, label_schema_version="NOT_APPLICABLE", adapter="DETERMINISTIC", category="DETERMINISTIC",
                             name=title, trainer=None, loader=None, env=".venv",
                             sources=[{"kind": "BARS", "tf": tf, "mandatory": True}] + ([{"kind": "BARS_DXY", "tf": "H1", "mandatory": True}]
                                                                                       if iid == "IND_XAU_DXY" else []),
                             resume={"export": "CHUNK_CHECKPOINT", "training": "NOT_APPLICABLE"},
                             # 1.46: the DXY series is never exported into the package - IND_XAU_DXY (also offered for BTC) always ended
                             # BLOCKED_DATA after the export; not offered as SUPPORTED any more
                             state="NOT_IMPLEMENTED" if iid in NO_MULTI_SERIES else "SUPPORTED", reason=NO_MULTI_SERIES.get(iid),
                             transfer=None))
        out.append(_task(model_id="KRONOS_SMALL", task_id="CANDLE_PATH", instrument=inst, broker_symbol=sym.get(inst), base_tf="M5", horizon=None,
                         feature_schema_version="kronos-tokenizer-base", label_schema_version="NOT_APPLICABLE", adapter="PRETRAINED",
                         category="PRETRAINED", name="Kronos-small (wagi pretrained NeoQuasar, 1.42.8)", trainer=None,
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
