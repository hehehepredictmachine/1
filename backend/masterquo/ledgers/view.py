"""PMW-LEDGER-VIEW-1: a read-only, canonical view of the prediction / outcome ledgers (1.46 arch, I0028 + I0037; docs/arch146/ETAP2 §4).

Before: 15 tables in the main database (+ the legacy ML tables of BTC in its own ml.sqlite) and 3 separate files (mm predictions per
instrument, evaluation, quant rows + assessments), each with its own key, time encoding, status vocabulary and instrument id; the
same column name meant different moments (decision_time = plan time in scalp_shadow, dequeue time in nss_inferences, processing time in
ml_scalp_samples; settled_at = event time or wall clock). Nothing could read them together.
Etap 4 (ETAP2 §5 'ledgery: evaluation, quant/ledger, mm ledger, decision/ledger, scalp, ml (+ pliki)'): AUX_ADAPTERS add, read-only as
well, the decision ledger of PMW-ARC-1 (decision_records, execution_intents, risk_reservations - decision/coordinator.py, decision/ledger.py),
the holdout / trial registries (eval_ledger - ml/scalp_task.reserve_holdout, lab_holdout_access / lab_trials - lab/protocol.py) and the
file ledgers outside the databases (apollo/asge_trials.jsonl - apollo/asge.TrialLedger; holdout_access of structure_intelligence/<I> and
flow_context/<I>/registry.json; context_ind/<I>/ledger/*.jsonl - structure events). ADAPTERS keeps the 19 prediction / outcome ledgers.

This module changes NOTHING in the writers or the data:
* stores()   the registry of stores; the paths use the writers' own building blocks (paths.data_dir, the expression of
             mq_instruments.root(kind, inst) - without its mkdir -, mm/artifacts.root, evaluation/service._default_dir, quant/service.qdir)
             for every instrument of mq_instruments.profiles(); a store that does not exist is reported as missing and NOT created;
* connect_ro the only connection: sqlite URI mode=ro (like exports/sources.ReadOnlyDB) - a write raises, nothing is migrated;
* ADAPTERS   one adapter per table / file mapping a row to the canonical record below; the original row stays in `raw`;
* records()  iterate canonical records of one ledger (all instruments or one).

Canonical record (keys always present): view, ledger, store, source_table, source_key, pred_id ('<ledger>:<pk>'), link_ids (setup_id,
sample_id, forecast_id, row_id, run_id, ...), model_id, artifact, fingerprint, feature_schema, task, label_policy, instrument (canonical
id), broker_symbol, timeframe, horizon ({bars|seconds|text}), side, the times decision_ts (moment of the decision / plan), available_at,
predicted_at (written), processed_at (taken from a queue / processed), matures_at, matured_at (wall clock of the scoring), outcome_event_ts
(time of the outcome event) - each UTC epoch seconds plus <name>_iso -, data_kind REAL|SYNTHETIC|UNKNOWN, run_mode
LIVE_SHADOW|LIVE|WALK_FORWARD|REPLAY|OFFLINE_VALIDATION (RUN_MODES), prediction, outcome_status (ONE vocabulary, OUTCOME_STATUSES) next to
status_raw, outcome, metrics, raw.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

VERSION = "PMW-LEDGER-VIEW-1"
OUTCOME_STATUSES = ("PENDING", "SCORED", "NO_DATA", "OUT_OF_BUFFER", "EXCLUDED", "NOT_APPLICABLE", "INVALID")
# raw status of any writer -> canonical outcome_status (I0037); the raw value is always kept in status_raw
STATUS_MAP = {
    "PENDING": "PENDING", "PENDING_ENTRY": "PENDING", "OPEN": "PENDING",
    "SCORED": "SCORED", "SETTLED": "SCORED", "MATURED": "SCORED", "LABELED": "SCORED", "LABELLED": "SCORED",
    "WIN": "SCORED", "LOSS": "SCORED", "BREAKEVEN": "SCORED", "TIMEOUT": "SCORED",            # ai_signals: outcome classes
    "NO_DATA": "NO_DATA", "DATA_GAP": "NO_DATA", "NO_BARS": "NO_DATA", "NO_CONTINUOUS_DATA": "NO_DATA", "MISSING_DATA": "NO_DATA",
    "EXCLUDED_GAP": "NO_DATA", "UNSCORED_GAP": "NO_DATA",                                        # gap policy = status_raw
    "OUT_OF_BUFFER": "OUT_OF_BUFFER",
    "MISSED_LIMIT": "EXCLUDED", "NO_EXECUTABLE_ENTRY": "EXCLUDED", "EXPIRED": "EXCLUDED", "NO_TRADE": "EXCLUDED", "REJECTED": "EXCLUDED",
    "ERROR": "INVALID", "FAILED": "INVALID",
}
# LIVE = a record of the running bot in its execution mode (decision ledger - the mode itself is in prediction.mode);
# OFFLINE_VALIDATION = trials / holdout evaluations run offline on stored bars (no live decision)
RUN_MODES = ("LIVE_SHADOW", "LIVE", "WALK_FORWARD", "REPLAY", "OFFLINE_VALIDATION")
TIME_KEYS = ("decision_ts", "available_at", "predicted_at", "processed_at", "matures_at", "matured_at", "outcome_event_ts")
REQUIRED = ("view", "ledger", "store", "source_table", "source_key", "pred_id", "link_ids", "model_id", "artifact", "fingerprint",
            "feature_schema", "task", "label_policy", "instrument", "broker_symbol", "timeframe", "horizon", "side", *TIME_KEYS,
            *(k + "_iso" for k in TIME_KEYS), "data_kind", "run_mode", "prediction", "outcome_status", "status_raw", "outcome", "metrics", "raw")


def canonical_status(raw) -> tuple[str, str | None]:
    """(canonical outcome_status, note). An unknown raw status is INVALID with a note - never guessed into SCORED / PENDING."""
    if raw is None or raw == "":
        return "INVALID", "STATUS_MISSING"
    s = str(raw).upper()
    return (STATUS_MAP[s], None) if s in STATUS_MAP else ("INVALID", f"UNKNOWN_STATUS:{raw}")


def _t(v) -> float | None:
    """UTC epoch seconds from an epoch number or an ISO text ('Z' / offset / naive = UTC); unreadable -> None."""
    if v is None or v == "":
        return None
    if isinstance(v, int | float):
        return float(v)
    s = str(v).strip()
    try:
        return float(s)
    except ValueError:
        pass
    try:
        d = datetime.fromisoformat(s)                                       # 3.11+: a trailing Z is UTC
    except ValueError:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=UTC)).timestamp()


def _iso(t: float | None) -> str | None:
    return None if t is None else datetime.fromtimestamp(t, UTC).isoformat().replace("+00:00", "Z")


def _j(v):
    if isinstance(v, str) and v[:1] in ("{", "["):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


def _kind(data_kind=None, synthetic=None) -> str:
    if data_kind:
        s = str(data_kind).upper()
        return "SYNTHETIC" if "SYNTH" in s else ("REAL" if s in ("REAL", "REAL_USER_DATA", "LIVE") else "UNKNOWN")
    if synthetic is None or synthetic == "":
        return "UNKNOWN"
    return "SYNTHETIC" if int(synthetic) else "REAL"


# ---------------------------------------------------------------------------------------------------------------------- stores
@dataclass(frozen=True)
class Store:
    id: str                   # e.g. main, ml:BTC, mm:XAUUSD, evaluation, quant, apollo_trials, context_ind:XAUUSD
    kind: str                 # main | ml | mm | evaluation | quant | apollo_trials | structure_intelligence | flow_context | context_ind
    path: Path
    instrument: str | None    # the store's instrument when the store is per instrument
    fmt: str = "sqlite"       # sqlite | jsonl | json | jsonl_dir (a folder of .jsonl files)

    @property
    def exists(self) -> bool:
        return self.path.is_dir() if self.fmt == "jsonl_dir" else self.path.is_file()


def _inst_root(kind: str, inst: str) -> Path:
    """mq_instruments.root(kind, inst) without its mkdir (the view never creates a folder) - kept equal to it by a test."""
    import mq_instruments as mi
    return mi.data_dir() / kind if inst == mi.DEFAULT else mi.data_dir() / "instruments" / inst / kind


def instruments() -> list[str]:
    import mq_instruments as mi
    return list(mi.profiles())


def stores(insts: list[str] | None = None) -> list[Store]:
    import mq_instruments as mi

    from .. import paths
    data = paths.data_dir()
    main = data / "masterquo.sqlite"                                           # db/database.Database default
    out = [Store("main", "main", main, None)]
    for inst in insts or instruments():
        if inst != mi.DEFAULT:                                                 # ml/router.ml_store: the default instrument uses the main db
            out.append(Store(f"ml:{inst}", "ml", _inst_root("ml", inst) / "ml.sqlite", inst))
        out.append(Store(f"mm:{inst}", "mm", _inst_root("mm", inst) / "ledger.sqlite", inst))       # mm/service: artifacts.root(inst)
    out.append(Store("evaluation", "evaluation", data / "evaluation" / "ledger.sqlite", None))   # evaluation/service._default_dir()
    out.append(Store("quant", "quant", data / "quant" / "ledger.sqlite", None))                 # quant/service.qdir()
    # file ledgers (Etap 4): the writers' own paths without their mkdir (lab roots = mq_instruments.data_dir() / <area> / <inst>)
    out.append(Store("apollo_trials", "apollo_trials", data / "apollo" / "asge_trials.jsonl", None, "jsonl"))   # wf32_services TrialLedger
    for inst in insts or instruments():
        for area in ("structure_intelligence", "flow_context"):               # lab/structure_task.root, lab/flow_context/task.root
            out.append(Store(f"{area}:{inst}", area, mi.data_dir() / area / inst / "registry.json", inst, "json"))
        out.append(Store(f"context_ind:{inst}", "context_ind", mi.data_dir() / "context_ind" / inst / "ledger", inst, "jsonl_dir"))
    return out


def connect_ro(path: Path) -> sqlite3.Connection:
    """Read-only connection (URI mode=ro): a write raises sqlite3.OperationalError, a missing file raises - nothing is created."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(str(p))
    c = sqlite3.connect(f"{p.resolve().as_uri()}?mode=ro", uri=True, timeout=15, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


# ---------------------------------------------------------------------------------------------------------------------- adapters
@dataclass(frozen=True)
class Adapter:
    name: str                 # ledger name in the view
    stores: tuple[str, ...]   # store kinds holding the table
    table: str                # sqlite table, or the file / record set of a file store
    pk: tuple[str, ...]
    fn: Callable[[dict], dict]   # row -> adapter-specific fields of the canonical record
    reader: Callable[[Path], Iterator[dict]] | None = None    # file stores: rows of one file (read-only); None = sqlite table
    group: str = "prediction"    # prediction | decision | holdout | trials | events


def _ml_predictions(r):
    return {"model_id": f"ml:legacy_s01_s12/{r['model_id']}", "artifact": r["model_id"], "task": "NET_R_POSITIVE_S01_S12",
            "link_ids": {"setup_id": r["setup_id"]}, "decision_ts": r["at"], "predicted_at": r["at"],
            "prediction": {"raw_score": r["raw_score"], "p": r["calibrated_probability"], "readiness": r["readiness"], "role": r["role"],
                           "setup_version": r["setup_version"], "contract": _j(r["contract_json"])},
            "outcome_status": "NOT_APPLICABLE", "status_note": "wynik w ml_samples (link setup_id)"}


def _ml_scalp_predictions(r):
    st = str(r["status"] or "").upper()
    return {"model_id": "ml_scalp:xgb_net_r", "artifact": r["model_hash"], "fingerprint": r["snapshot_hash"], "task": "SCALP_NET_R_POSITIVE",
            "instrument": r["instrument"], "side": r["side"], "link_ids": {"sample_id": r["sample_id"]},
            "decision_ts": r["as_of"], "predicted_at": r["computed_at"],         # as_of = the plan time (I0037)
            "prediction": {"p": r["p"], "raw_margin": r["raw_margin"], "expected_net_r": r["expected_net_r"], "role": r["role"],
                           "proposed_filter": r["proposed_filter"], "expires_at": r["expires_at"], "status": r["status"], "detail": _j(r["detail"])},
            "status_raw": r["status"],
            "outcome_status": "INVALID" if st in ("ERROR", "FAILED") else "NOT_APPLICABLE",
            "status_note": None if st in ("ERROR", "FAILED") else "wynik w ml_scalp_samples (link sample_id)"}


def _forecast_shadow(r):
    st = r["outcome_status"]
    return {"model_id": "forecast:gold_candles", "artifact": r["run_id"], "task": "CANDLE_CLOSE_DIRECTION_M5", "instrument": r["instrument"],
            "timeframe": "M5", "horizon": {"seconds": (r["horizon_minutes"] or 0) * 60}, "link_ids": {"run_id": r["run_id"]},
            "decision_ts": r["feature_time_utc"], "predicted_at": r["created_at"], "matures_at": r["target_time_utc"],
            "matured_at": r["scored_at"],                                       # scored_at = wall clock of the scoring (I0037)
            "prediction": {"p_down": r["p_down"], "p_flat": r["p_flat"], "p_up": r["p_up"], "q10": r["q10"], "q50": r["q50"], "q90": r["q90"],
                           "close_now": r["close_now"], "neutral_band": r["neutral_band"], "session_check": r["session_check"],
                           "horizon_status": r["horizon_status"]},
            "status_raw": st, "outcome": {"close": r["outcome_close"], "class": r["outcome_class"]} if r["outcome_close"] is not None else None}


def _scalp_shadow(r):
    st = str(r["outcome_status"] or "").upper()
    settled = r["settled_at"]
    return {"model_id": f"scalp:profile/{r['profile_id']}", "task": "SCALP_PLAN_NET_R", "instrument": r["instrument"], "side": r["direction"],
            "link_ids": {"setup_id": r["setup_id"]}, "decision_ts": r["decision_time_utc"], "predicted_at": r["created_at"],
            # settled_at = label_end (event time) for SETTLED, the wall clock for NO_DATA / MISSED_LIMIT (I0037)
            "outcome_event_ts": settled if st == "SETTLED" else None, "matured_at": None if st in ("SETTLED", "PENDING") else settled,
            "prediction": {"status": r["status"], "reasons": _j(r["reasons"]), "plan": _j(r["plan"]), "gates": _j(r["gates"]), "hedge": _j(r["hedge"])},
            "status_raw": r["outcome_status"], "outcome": _j(r["outcome"]), "metrics": {"net_r": r["net_r"]}}


def _lab_forecasts(r):
    p = _j(r["payload"])
    return {"model_id": f"lab:{r['module']}", "instrument": r["asset"], "timeframe": r["tf"], "link_ids": {"forecast_id": r["forecast_id"]},
            "decision_ts": r["issued_as_of"], "predicted_at": r["issued_as_of"], "prediction": p,
            "outcome_status": "NOT_APPLICABLE", "status_note": "archiwum prognoz punkt-w-czasie – wynik nie jest zapisywany w tej tabeli"}


def _nss_inferences(r):
    st = r["label_status"]
    return {"model_id": "nss:tcn", "artifact": r["model_hash"], "fingerprint": r["snapshot_hash"], "task": r["task_id"], "instrument": r["instrument"],
            "side": r["side"], "link_ids": {"setup_id": r["setup_id"], "request_id": r["request_id"]},
            "decision_ts": r["signal_time"],                                    # the plan time; decision_time = dequeue (I0037)
            "processed_at": r["decision_time"], "predicted_at": r["computed_at"], "outcome_event_ts": r["label_end"],
            "matured_at": r["label_available_at"], "run_mode": "LIVE_SHADOW" if str(r["mode"] or "").upper() in ("", "SHADOW", "LIVE") else "REPLAY",
            "prediction": {"output": _j(r["output"]), "plan": _j(r["plan"]), "technical_status": r["technical_status"], "expires_at": r["expires_at"]},
            "status_raw": st, "outcome": {"event": r["label_event"]} if r["label_event"] else None, "metrics": {"net_r": r["label_net_r"]}}


def _si_forecasts(r):
    return {"model_id": f"si:{r['model_id']}", "artifact": r["model_id"], "task": r["task_id"], "instrument": r["instrument"], "timeframe": "M1",
            "horizon": {"bars": r["horizon"]}, "link_ids": {"forecast_id": r["id"], "snapshot_id": r["snapshot_id"]},
            "decision_ts": r["as_of"], "predicted_at": r["emitted_at"], "prediction": _j(r["payload"]),
            "outcome_status": "NOT_APPLICABLE", "status_note": "wynik w si_outcomes (link forecast_id)"}


def _si_outcomes(r):
    return {"model_id": "si", "link_ids": {"forecast_id": r["forecast_id"]}, "matured_at": r["matured_at"], "status_raw": r["status"],
            "outcome": {"label": r["label"], "r_h": r["r_h"], "data_revision": r["data_revision"]}, "metrics": {"r_h": r["r_h"]}}


def _quote_forecasts(r):
    return {"model_id": "quotes:MQ_NEWTONIAN_QUOTES_V2", "side": r["side"], "link_ids": {"forecast_id": r["forecast_id"]},
            "decision_ts": r["issued_at"], "predicted_at": r["issued_at"], "matures_at": r["target_at"],
            "prediction": {"context": r["context"], "scale": r["scale"], "payload": _j(r["payload"])},
            "outcome_status": "NOT_APPLICABLE", "status_note": "wynik w quote_outcomes (link forecast_id)"}


def _quote_outcomes(r):
    return {"model_id": "quotes:MQ_NEWTONIAN_QUOTES_V2", "link_ids": {"forecast_id": r["forecast_id"]}, "matured_at": r["scored_at"],
            "status_raw": r["status"], "outcome": _j(r["outcome"]), "metrics": {"error": r["error"]}}


def _bars_forecast(model_prefix: str):
    def fn(r):
        out = {"model_id": r.get("model_id") or model_prefix, "artifact": r.get("model_revision"), "fingerprint": r.get("fingerprint") or r.get("input_hash"),
               "task": "PRICE_PATH_H", "instrument": r["instrument"], "broker_symbol": r["symbol"], "timeframe": r["timeframe"],
               "horizon": {"bars": r["horizon_bars"]}, "link_ids": {"forecast_id": r["forecast_id"], "snapshot_id": r.get("snapshot_id")},
               "decision_ts": r["created_at"], "available_at": r.get("data_available_at"), "predicted_at": r["created_at"],
               "matured_at": r["settled_at"],                                   # settled_at = wall clock of the settlement (I0037)
               "data_kind": _kind(r["data_kind"]),
               "prediction": {"last_close": r["last_close"], "pred_close_h": r["pred_close_h"], "delta_price": r["delta_price"],
                              "direction": r["direction"], "neutral_band": r["neutral_band"], "path": _j(r["path_json"]),
                              "quantiles": _j(r.get("quantiles_json")), "uncertainty": _j(r.get("uncertainty_json"))},
               "status_raw": r["outcome_status"],
               "outcome": _j(r["outcome_json"]) if r["outcome_json"] else ({"actual_close_h": r["actual_close_h"]} if r["actual_close_h"] is not None else None),
               "metrics": {"abs_err_h": r["abs_err_h"], "naive_abs_err_h": r["naive_abs_err_h"], "path_mae": r["path_mae"],
                           "direction_hit": r["direction_hit"], "pinball_h": r.get("pinball_h"), "covered_80": r.get("covered_80")}}
        return out
    return fn


def _ai_signals(r):
    return {"model_id": f"agent:{r['model_id']}" if r["model_id"] else "agent", "artifact": r["prompt_version"], "broker_symbol": r["symbol"],
            "timeframe": r["timeframe"], "horizon": {"text": r["horizon"]} if r["horizon"] else None, "side": r["action"],
            "link_ids": {"setup_id": r["setup_id"], "event_id": r["event_id"], "run_id": r["run_id"]},
            "decision_ts": r["created_at"], "predicted_at": r["created_at"], "matures_at": r["valid_until"], "outcome_event_ts": r["closed_at"],
            "data_kind": _kind(None, r["synthetic"]),
            "prediction": {"entry_type": r["entry_type"], "entry_price": r["entry_price"], "stop_loss": r["stop_loss"],
                           "take_profits": _j(r["take_profits_json"]), "confidence": r["confidence"], "source": r["source"],
                           "strategy_id": r["strategy_id"], "ai_verdict": r["ai_verdict"]},
            "status_raw": r["status"], "outcome": {"exit_price": r["exit_price"], "tp_hit": r["tp_hit"], "fill_price": r["fill_price"]},
            "metrics": {"outcome_r": r["outcome_r"]}}


def _ml_samples(r):
    src = str(r["source"] or "")
    return {"model_id": "ml:legacy_s01_s12", "task": "NET_R_POSITIVE_S01_S12", "feature_schema": r["feature_schema_version"],
            "label_policy": r["label_policy_version"], "broker_symbol": r["symbol"], "timeframe": r["timeframe"], "side": r["direction"],
            "link_ids": {"sample_id": r["sample_id"], "setup_id": r["setup_id"], "event_id": r["event_id"]},
            "decision_ts": r["asof_utc"], "predicted_at": r["created_at"], "outcome_event_ts": r["label_end_utc"], "matured_at": r["label_known_utc"],
            "data_kind": _kind(None, r["synthetic"]), "run_mode": "LIVE_SHADOW" if src == "LIVE" else "REPLAY",
            "prediction": None, "status_raw": r["status"],
            "outcome": {"label": r["label"], "exit_reason": r["exit_reason"], "outcome_source": r["outcome_source"], "realized": _j(r["realized_json"])},
            "metrics": {"outcome_r": r["outcome_r"], "mfe_r": r["mfe_r"], "mae_r": r["mae_r"]}}


def _ml_scalp_samples(r):
    return {"model_id": "ml_scalp:xgb_net_r", "feature_schema": r["feature_schema"], "fingerprint": r["snapshot_hash"], "instrument": r["instrument"],
            "side": r["side"], "link_ids": {"sample_id": r["sample_id"], "setup_id": r["setup_id"], "range_id": r["range_id"]},
            "decision_ts": r["signal_time"],                                    # the plan time; decision_time = processing (I0037)
            "processed_at": r["decision_time"], "predicted_at": r["created_at"], "outcome_event_ts": r["label_end"],
            "matured_at": r["label_available_at"], "prediction": None, "status_raw": r["status"],
            "outcome": {"y": r["y"], "precision": r["precision"]}, "metrics": {"net_r": r["net_r"]}}


def _mm_predictions(r):
    out = _j(r["outcome"])
    st = (out.get("status") if isinstance(out, dict) and out.get("status") else "SCORED") if out is not None else "PENDING"
    rm = str(r["run_mode"] or "SHADOW").upper()
    return {"model_id": r["model_id"], "artifact": r["artifact_id"], "feature_schema": r["feature_schema"], "broker_symbol": r["symbol"],
            "timeframe": r["timeframe"], "horizon": {"text": r["horizon"]}, "link_ids": {},
            "decision_ts": r["source_ts"], "available_at": r["available_at"], "predicted_at": r["predicted_at"], "matures_at": r["matures_at"],
            "matured_at": r["matured_at"], "run_mode": "LIVE_SHADOW" if rm in ("SHADOW", "LIVE", "LIVE_SHADOW") else rm,
            "prediction": {"kind": r["kind"], "payload": _j(r["payload"]), "quality": r["quality"]},
            "status_raw": st, "outcome": out, "metrics": {"error": r["error"]} if r["error"] else {}}


def _quant_rows(r):
    return {"model_id": "quant:metamodel", "task": r["task_hash"], "instrument": r["instrument"], "side": r["direction"],
            "link_ids": {"row_id": r["row_id"], "event_id": r["event_id"], "snapshot_id": r["snapshot_id"]},
            "decision_ts": r["decision_ts"], "predicted_at": r["created_at"], "matures_at": r["matures_at"], "outcome_event_ts": r["resolve_ts"],
            "data_kind": _kind(r["data_kind"]),
            "prediction": {"engine": r["engine"], "strategy": r["strategy"], "spec": _j(r["spec_json"]), "generation": r["generation"]},
            "status_raw": r["status"], "outcome": _j(r["label_json"]), "metrics": {"y": r["y"], "net_r": r["net_r"]}}


def _quant_assessments(r):
    return {"model_id": "quant:metamodel", "side": r["direction"], "link_ids": {"row_id": r["row_id"]}, "decision_ts": r["created_at"],
            "predicted_at": r["created_at"], "prediction": {"mode": r["mode"], "engine": r["engine"], "strategy": r["strategy"],
                                                            "payload": _j(r["payload_json"])},
            "outcome_status": "NOT_APPLICABLE", "status_note": "wynik w quant rows (link row_id)"}


_A = [
    Adapter("ml_predictions", ("main", "ml"), "ml_predictions", ("id",), _ml_predictions),
    Adapter("ml_scalp_predictions", ("main", "ml"), "ml_scalp_predictions", ("prediction_id",), _ml_scalp_predictions),
    Adapter("forecast_shadow", ("main",), "forecast_shadow", ("id",), _forecast_shadow),
    Adapter("scalp_shadow", ("main",), "scalp_shadow", ("id",), _scalp_shadow),
    Adapter("lab_forecasts", ("main",), "lab_forecasts", ("forecast_id",), _lab_forecasts),
    Adapter("nss_inferences", ("main",), "nss_inferences", ("inference_id",), _nss_inferences),
    Adapter("si_forecasts", ("main",), "si_forecasts", ("id",), _si_forecasts),
    Adapter("si_outcomes", ("main",), "si_outcomes", ("forecast_id", "data_revision"), _si_outcomes),
    Adapter("quote_forecasts", ("main",), "quote_forecasts", ("forecast_id",), _quote_forecasts),
    Adapter("quote_outcomes", ("main",), "quote_outcomes", ("forecast_id",), _quote_outcomes),
    Adapter("kronos_forecasts", ("main",), "kronos_forecasts", ("id",), _bars_forecast("kronos:Kronos-small")),
    Adapter("tsfm_forecasts", ("main",), "tsfm_forecasts", ("id",), _bars_forecast("tsfm")),
    Adapter("ai_signals", ("main",), "ai_signals", ("signal_id",), _ai_signals),
    Adapter("ml_samples", ("main", "ml"), "ml_samples", ("sample_id",), _ml_samples),
    Adapter("ml_scalp_samples", ("main", "ml"), "ml_scalp_samples", ("sample_id",), _ml_scalp_samples),
    Adapter("mm_predictions", ("mm",), "predictions", ("pred_id",), _mm_predictions),
    Adapter("evaluation", ("evaluation",), "predictions", ("pred_id",), _mm_predictions),
    Adapter("quant_rows", ("quant",), "rows", ("row_id",), _quant_rows),
    Adapter("quant_assessments", ("quant",), "assessments", ("assessment_id",), _quant_assessments),
]
ADAPTERS: dict[str, Adapter] = {a.name: a for a in _A}
ML_STORE_TABLES = ("ml_predictions", "ml_scalp_predictions", "ml_samples", "ml_scalp_samples")   # main db for XAUUSD, ml.sqlite otherwise


# ---------------------------------------------------------------------------------------------------------------------- Etap 4: AUX
# The decision ledger (PMW-ARC-1), holdout / trial registries and file ledgers. Their own state vocabularies are mapped HERE (local
# maps, never added to STATUS_MAP - a raw value of another writer must not change its meaning); an unknown state = INVALID + note.
INTENT_STATUS = {"NEW": "PENDING", "RESERVED": "PENDING", "SENT": "PENDING", "UNKNOWN": "PENDING",
                 "FILLED": "SCORED", "PARTIAL": "SCORED", "RECONCILED_FILLED": "SCORED",
                 "REJECTED": "EXCLUDED", "BLOCKED": "EXCLUDED", "RECONCILED_NOT_FOUND": "EXCLUDED"}       # decision/ledger.IntentLedger
RESERVATION_STATUS = {"HELD": "PENDING", "UNKNOWN": "PENDING", "CONSUMED": "SCORED", "RELEASED": "EXCLUDED", "EXPIRED": "EXCLUDED"}


def _local(vocab: dict, raw) -> tuple[str, str | None]:
    s = str(raw or "").upper()
    return (vocab[s], None) if s in vocab else ("INVALID", f"UNKNOWN_STATUS:{raw}")


def _decision_records(r):
    return {"model_id": f"decision:coordinator/{r['path']}", "task": "DECISION_VERDICT", "broker_symbol": r["symbol"], "side": r["direction"],
            "link_ids": {"record_id": r["record_id"], "source_id": r["source_id"]}, "decision_ts": r["created_at"], "predicted_at": r["created_at"],
            "fingerprint": r["inputs_hash"], "run_mode": "LIVE",
            "prediction": {"path": r["path"], "mode": r["mode"], "strategy_id": r["strategy_id"], "account_key": r["account_key"],
                           "base_verdict": r["base_verdict"], "final_verdict": r["final_verdict"], "reason_codes": _j(r["reason_codes"]),
                           "models": _j(r["models_json"])},
            "status_raw": r["final_verdict"], "outcome_status": "NOT_APPLICABLE",
            "status_note": "wynik wykonania w execution_intents (link record_id)"}


def _execution_intents(r):
    st, note = _local(INTENT_STATUS, r["state"])
    return {"model_id": f"decision:intent/{r['path']}", "task": f"EXECUTION_{r['kind']}", "broker_symbol": r["symbol"], "side": r["side"],
            "link_ids": {"intent_id": r["intent_id"], "record_id": r["record_id"], "source_ref": r["source_ref"], "reservation_id": r["reservation_id"]},
            "decision_ts": r["created_at"], "predicted_at": r["created_at"], "processed_at": r["updated_at"], "run_mode": "LIVE",
            "prediction": {"path": r["path"], "mode": r["mode"], "account_key": r["account_key"], "volume": r["volume"],
                           "risk_money": r["risk_money"], "dedup_key": r["dedup_key"]},
            "status_raw": r["state"], "outcome_status": st, "status_note": note, "outcome": _j(r["outcome_json"])}


def _risk_reservations(r):
    st, note = _local(RESERVATION_STATUS, r["state"])
    return {"model_id": f"decision:risk_book/{r['path']}", "task": "RISK_RESERVATION",
            "link_ids": {"reservation_id": r["reservation_id"], "subject": r["subject"]},
            "decision_ts": r["created_ts"] if r["created_ts"] is not None else r["created_at"], "predicted_at": r["created_at"],
            "processed_at": r["updated_at"], "run_mode": "LIVE",
            "prediction": {"path": r["path"], "mode": r["mode"], "account_key": r["account_key"], "risk_money": r["risk_money"],
                           "positions": r["positions"], "reservation_key": r["reservation_key"], "note": r["note"]},
            "status_raw": r["state"], "outcome_status": st, "status_note": note}


def _eval_ledger(r):
    return {"model_id": f"holdout:{r['task_id']}", "artifact": r["artifact_hash"], "task": r["task_id"], "instrument": r["instrument"],
            "link_ids": {"id": r["id"]}, "decision_ts": r["at"], "predicted_at": r["at"], "run_mode": "OFFLINE_VALIDATION",
            "prediction": {"period_start": r["period_start"], "period_end": r["period_end"]},
            "status_raw": r["status"], "outcome_status": "NOT_APPLICABLE",
            "status_note": "rejestr użycia okresu holdout (FRESH / REUSED_PERIOD_EXPLORATORY), nie prognoza"}


def _lab_holdout_access(r):
    return {"model_id": "lab:holdout", "artifact": r["candidate_id"], "task": r["horizon"], "instrument": r["asset"],
            "link_ids": {"id": r["id"], "candidate_id": r["candidate_id"]}, "fingerprint": r["holdout_hash"], "decision_ts": r["at"],
            "predicted_at": r["at"], "run_mode": "OFFLINE_VALIDATION", "prediction": {"protocol_id": r["protocol_id"]},
            "outcome": _j(r["result"]), "outcome_status": "NOT_APPLICABLE", "status_note": "jednorazowy dostęp do holdoutu (lab/protocol)"}


def _lab_trials(r):
    m = _j(r["metrics"])
    return {"model_id": f"lab:{r['model_family']}", "artifact": r["trial_id"], "task": r["horizon"], "instrument": r["asset"],
            "link_ids": {"trial_id": r["trial_id"]}, "fingerprint": r["data_hash"], "decision_ts": r["created_at"], "predicted_at": r["created_at"],
            "run_mode": "OFFLINE_VALIDATION",
            "prediction": {"protocol_id": r["protocol_id"], "config": _j(r["config"]), "seeds": _j(r["seeds"]), "note": r["note"]},
            "status_raw": r["status"], "metrics": m if isinstance(m, dict) else {}, "outcome_status": "NOT_APPLICABLE",
            "status_note": "rejestr prób protokołu walidacji (liczba prób = poprawka na wielokrotne testy)"}


def _asge_trials(r):
    return {"model_id": "apollo:asge", "artifact": r["ir_hash"], "fingerprint": r["data_hash"], "task": "ASGE_STRATEGY_TRIAL",
            "link_ids": {"trial_id": r["trial_id"], "parent": r["parent"], "holdout_reused_from": r["holdout_reused_from"]},
            "decision_ts": r["created_at"], "predicted_at": r["created_at"], "run_mode": "OFFLINE_VALIDATION",
            "prediction": {"ir": r["ir"], "version": r["version"], "hurdle_net_r": r["hurdle_net_r"], "execution_allowed": r["execution_allowed"],
                           "reasons": r["reasons"], "integrity": r["integrity"]},
            "status_raw": r["status"], "metrics": {"dev_trades": r["dev_trades"], "dev_mean_net_r": r["dev_mean_net_r"],
                                                   "positive_folds": r["positive_folds"], "holdout_mean_net_r": r["holdout_mean_net_r"]},
            "outcome_status": "NOT_APPLICABLE", "status_note": "ledger prób generatora strategii (lineage, holdout raz na kandydata) - nie prognoza"}


def _holdout_registry(area: str):
    def fn(r):
        led = r["ledger"] if isinstance(r["ledger"], dict) else {}
        return {"model_id": f"lab:{area}", "artifact": r["model_hash"] or r["candidate_id"], "task": r["task_id"],
                "link_ids": {"candidate_id": r["candidate_id"]}, "decision_ts": r["at"], "predicted_at": r["at"], "run_mode": "OFFLINE_VALIDATION",
                "prediction": {"protocol_id": r["protocol_id"], "role": r["role"], "edge_status": r["edge_status"], "ledger": r["ledger"]},
                "status_raw": led.get("status"), "outcome": {"metrics": r["metrics"]}, "outcome_status": "NOT_APPLICABLE",
                "status_note": f"jednorazowa ocena holdout ({area}/<instrument>/registry.json holdout_access)"}
    return fn


def _context_ind_events(r):
    parts = str(r["ledger_id"] or "").split("|")                           # <inst>|<tf>|<profile_hash>|E<epoch>|<event_id>
    return {"model_id": "lab:context_ind", "task": f"STRUCTURE_EVENT_{r['kind']}", "timeframe": parts[1] if len(parts) > 1 else None,
            "fingerprint": parts[2] if len(parts) > 2 else None, "link_ids": {"event_id": r["event_id"], "event_key": r["event_key"]},
            "decision_ts": r["available_at"], "available_at": r["available_at"], "predicted_at": r["available_at"],
            "prediction": {k: v for k, v in r.items() if k not in ("_file", "_line")}, "outcome_status": "NOT_APPLICABLE",
            "status_note": "zdarzenie struktury (SMC), nie prognoza - zapis append-only lab/context_ind/service.py"}


def _read_jsonl(path: Path) -> Iterator[dict]:
    """Rows of one JSONL file (read-only); a torn / unreadable line is skipped, as apollo/asge.TrialLedger skips it."""
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                yield {**row, "_file": path.name, "_line": n}


def _read_jsonl_dir(path: Path) -> Iterator[dict]:
    for f in sorted(path.glob("*.jsonl")):
        yield from _read_jsonl(f)


def _read_holdout(path: Path) -> Iterator[dict]:
    """holdout_access of a lab registry.json ({candidate_id: result}); an unreadable registry yields nothing (never repaired here)."""
    try:
        reg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    acc = reg.get("holdout_access") if isinstance(reg, dict) else None
    for cid, v in (acc or {}).items():
        if isinstance(v, dict):
            yield {**v, "candidate_id": v.get("candidate_id") or cid}


_AUX = [
    Adapter("decision_records", ("main",), "decision_records", ("record_id",), _decision_records, group="decision"),
    Adapter("execution_intents", ("main",), "execution_intents", ("intent_id",), _execution_intents, group="decision"),
    Adapter("risk_reservations", ("main",), "risk_reservations", ("reservation_id",), _risk_reservations, group="decision"),
    Adapter("eval_ledger", ("main", "ml"), "eval_ledger", ("id",), _eval_ledger, group="holdout"),
    Adapter("lab_holdout_access", ("main",), "lab_holdout_access", ("id",), _lab_holdout_access, group="holdout"),
    Adapter("lab_trials", ("main",), "lab_trials", ("trial_id",), _lab_trials, group="trials"),
    Adapter("asge_trials", ("apollo_trials",), "asge_trials.jsonl", ("trial_id",), _asge_trials, _read_jsonl, "trials"),
    Adapter("structure_intelligence_holdout", ("structure_intelligence",), "registry.json:holdout_access", ("candidate_id",),
            _holdout_registry("structure_intelligence"), _read_holdout, "holdout"),
    Adapter("flow_context_holdout", ("flow_context",), "registry.json:holdout_access", ("candidate_id",), _holdout_registry("flow_context"),
            _read_holdout, "holdout"),
    Adapter("context_ind_events", ("context_ind",), "ledger/*.jsonl", ("ledger_id",), _context_ind_events, _read_jsonl_dir, "events"),
]
AUX_ADAPTERS: dict[str, Adapter] = {a.name: a for a in _AUX}
ALL_ADAPTERS: dict[str, Adapter] = {**ADAPTERS, **AUX_ADAPTERS}


def to_record(ad: Adapter, store: Store, row: dict) -> dict:
    """One row of `ad.table` from `store` -> the canonical record (pure function, no I/O)."""
    pk = ":".join(str(row.get(k)) for k in ad.pk)
    rec = {"view": VERSION, "ledger": ad.name, "store": store.id, "source_table": ad.table, "source_key": pk, "pred_id": f"{ad.name}:{pk}",
           "link_ids": {}, "model_id": None, "artifact": None, "fingerprint": None, "feature_schema": None, "task": None, "label_policy": None,
           "instrument": store.instrument, "broker_symbol": None, "timeframe": None, "horizon": None, "side": None,
           "data_kind": "UNKNOWN", "run_mode": "LIVE_SHADOW", "prediction": None, "outcome_status": None, "status_raw": None, "status_note": None,
           "outcome": None, "metrics": {}, "raw": dict(row)}
    rec.update(dict.fromkeys(TIME_KEYS))
    fields = ad.fn(_Row(row))
    if fields.get("instrument") is None:
        fields.pop("instrument", None)                                     # keep the store's instrument when the row has none
    rec.update(fields)
    for k in TIME_KEYS:
        rec[k] = _t(rec[k])
        rec[k + "_iso"] = _iso(rec[k])
    rec["link_ids"] = {k: v for k, v in (rec["link_ids"] or {}).items() if v not in (None, "")}
    rec["metrics"] = {k: v for k, v in (rec["metrics"] or {}).items() if v is not None}
    if rec["side"] is not None:
        rec["side"] = str(rec["side"]).upper()
    if rec["outcome_status"] is None:
        rec["outcome_status"], note = canonical_status(rec["status_raw"])
        rec["status_note"] = rec["status_note"] or note
    return rec


class _Row(dict):
    """Row access for adapters: a column missing in an OLDER schema reads as None (KeyError only for a typo in the adapter is not
    worth a crash of the whole view)."""

    def __getitem__(self, k):
        return self.get(k)


def _stores_for(ad: Adapter, insts: list[str] | None) -> list[Store]:
    import mq_instruments as mi
    out = []
    for s in stores(insts):
        if s.kind not in ad.stores:
            continue
        if s.kind == "main" and ad.table in ML_STORE_TABLES:
            if insts and mi.DEFAULT not in insts:
                continue
            s = Store("main", "main", s.path, mi.DEFAULT)                 # main db = the ML space of the default instrument only
        out.append(s)
    return out


def records(ledger: str, *, instrument: str | None = None, limit: int | None = None) -> Iterator[dict]:
    """Canonical records of one ledger, store by store (read-only). A missing store / table yields nothing (see status())."""
    ad = ALL_ADAPTERS[ledger]
    for s in _stores_for(ad, [instrument] if instrument else None):
        if not s.exists:
            continue
        if ad.reader is not None:                                           # file ledger: read-only reader, nothing is created
            for k, row in enumerate(ad.reader(s.path)):
                if limit and k >= int(limit):
                    break
                rec = to_record(ad, s, row)
                if instrument and rec["instrument"] not in (None, instrument):
                    continue
                yield rec
            continue
        con = connect_ro(s.path)
        try:
            if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (ad.table,)).fetchone():
                continue
            q = f'SELECT * FROM "{ad.table}"' + (f" LIMIT {int(limit)}" if limit else "")
            for row in con.execute(q):
                rec = to_record(ad, s, dict(row))
                if instrument and rec["instrument"] not in (None, instrument):
                    continue
                yield rec
        finally:
            con.close()


def status() -> dict:
    """Per store: path, exists; per ledger (prediction ledgers + AUX): rows by canonical outcome_status (read-only)."""
    out = {"view": VERSION, "stores": [{"id": s.id, "kind": s.kind, "path": str(s.path), "exists": s.exists, "instrument": s.instrument,
                                        "fmt": s.fmt} for s in stores()], "ledgers": {}}
    for name in ALL_ADAPTERS:
        cnt: dict[str, int] = {}
        for r in records(name):
            cnt[r["outcome_status"]] = cnt.get(r["outcome_status"], 0) + 1
        out["ledgers"][name] = cnt
    return out
