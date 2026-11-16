"""Inventory of the REAL strategies and models of this installation (1.41 update, PRESERVE_AND_EXTEND).

Nothing here is written from memory: every entry is read from the code registries and the effective configuration of the
data folder (config.json, data/sh/config_override.json, data/sh/pack_override.json, ...). The same functions produce the
"before" report (first start of 1.41, before any migration step) and the "after" report; preservation.py compares them.

Strategy sources (all trade/scan XAUUSD - the broker symbol is the configured one, e.g. "XAUUSD-", never normalised):
  ACTIVE   S01-S12             strategies/registry.py + config.active.strategies / params
  SH       LEGACY_SCALPING/HEDGING  config/sh_strategies_v1.json + data/sh/config_override.json
  SH_PACK  PMW_SC01-10, PMW_HG01-10  sh/pack/catalog.py + config/sh_strategy_pack_v2.json + override
  SCALP    Range -> Sweep -> Retest profile + its variants  config/scalp_profile_v1.json, scalp_variants_v1.json
  SIGNALS  Double Retest v2 (research machine)  forecast service - a signal source, listed with its switch
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .. import paths

SCHEMA = "PMW-INVENTORY-1"


def _h(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _cfg_raw(cfg_store=None) -> dict:
    if cfg_store is not None:
        try:
            return cfg_store.get().model_dump(mode="json")
        except Exception:  # noqa: BLE001
            pass
    from ..config import AppConfig
    raw = _read(paths.data_dir() / "config.json", None)
    try:
        return AppConfig.model_validate(raw or {}).model_dump(mode="json")
    except Exception:  # noqa: BLE001 - a config that does not validate is reported as such, defaults are not invented over it
        return raw or {}


def strategies(cfg_store=None) -> list[dict]:
    """Every strategy entry with identity, parameters (+hash), enabled/use state, symbol mapping, history keys."""
    cfg = _cfg_raw(cfg_store)
    out: list[dict] = []
    sym = ((cfg.get("mt5") or {}).get("symbol")) or "XAUUSD"
    # --- ACTIVE S01-S12
    from ..strategies import registry as R
    act = cfg.get("active") or {}
    toggles = act.get("strategies") or {}
    over = act.get("params") or {}
    for sid, s in R.STRATEGIES.items():
        p = R.params_for(sid, over.get(sid))
        tg = toggles.get(sid) or {}
        out.append({"strategy_id": sid, "source": "ACTIVE", "name": s.name, "family": s.family, "version": s.version,
                    "implementation": f"strategies/{type(s).__module__.rsplit('.', 1)[-1]}.py:{type(s).__name__}",
                    "aliases": [], "symbols": [sym], "venue": "MT5", "timeframes": list(s.setup_tfs), "context_tf": s.context_tf,
                    "enabled": {"scan": bool(tg.get("scan", True)), "trade": bool(tg.get("trade", sid not in R.DEFAULT_NO_TRADE))},
                    "parameters": p, "parameters_hash": _h(p), "user_overrides": over.get(sid) or {},
                    "entry_invalidation": "kod strategii (detect/Draft) – reguły w implementacji", "exit_policy": "plan ACTIVE (engine) – TP R-targets/SL strategii",
                    "required_models": [], "history_keys": [f"setup_id:MQA-*|strategy={sid}", f"decision.strategy_id={sid}"],
                    "execution_route": "engine.active -> decision.coordinator", "validation_status": s.validation_status})
    # --- SH legacy SCALPING / HEDGING
    try:
        from ..sh import config as SHC
        shc = SHC.load()
        for strat in ("SCALPING", "HEDGING"):
            for inst, ic in (shc.get("instruments") or {}).items():
                p = ic.get(strat) or {}
                out.append({"strategy_id": f"LEGACY_{strat}", "source": "SH", "name": f"{strat} (SH 1.x)", "family": strat, "version": shc.get("schema"),
                            "implementation": "sh/setup.py + sh/lifecycle.py", "aliases": [strat], "symbols": [sym if inst == "XAUUSD" else inst],
                            "instrument": inst, "venue": "MT5", "timeframes": None, "enabled": {"status": ic.get("status")},
                            "parameters": p, "parameters_hash": _h(p), "config_hash": shc.get("_hash"),
                            "override_version": shc.get("_override_version"), "required_models": [],
                            "history_keys": [f"sh/store family={strat} instrument={inst}"], "execution_route": "sh.service -> sh.coordinator -> decision.coordinator"})
    except Exception as exc:  # noqa: BLE001
        out.append({"strategy_id": "LEGACY_SCALPING/HEDGING", "source": "SH", "error": f"{type(exc).__name__}: {exc}"[:200]})
    # --- SH pack v2 (20)
    try:
        from ..sh.pack import catalog as PC
        pk = PC.load()
        for vid in PC.IDS:
            v = PC.variant(pk, vid)
            out.append({"strategy_id": vid, "source": "SH_PACK", "name": PC._DEF[vid][0], "family": PC._DEF[vid][1], "version": pk.get("version") or pk.get("schema"),
                        "implementation": f"sh/pack/detectors.py:{PC._DEF[vid][4]}", "aliases": [], "symbols": [sym], "venue": "MT5",
                        "timeframes": list(PC._DEF[vid][5]), "context_tfs": list(PC._DEF[vid][6]), "management_policy": PC._DEF[vid][7],
                        "enabled": {"enabled": v.get("enabled"), "use": v.get("use") or v.get("mode")}, "parameters": v, "parameters_hash": _h(v),
                        "required_models": [], "history_keys": [f"sh/store variant={vid}"], "execution_route": "sh.pack.engine -> sh.coordinator"})
    except Exception as exc:  # noqa: BLE001
        out.append({"strategy_id": "PMW_SC/HG", "source": "SH_PACK", "error": f"{type(exc).__name__}: {exc}"[:200]})
    # --- scalp profile Range -> Sweep -> Retest + variants
    prof = _read(paths.ROOT_DIR / "config" / "scalp_profile_v1.json", {}) or {}
    var = _read(paths.ROOT_DIR / "config" / "scalp_variants_v1.json", {}) or {}
    src = (cfg.get("bot_signals") or {}).get("strategy_sources") or {}
    out.append({"strategy_id": prof.get("profile_id", "SCALP_RANGE_SWEEP_RETEST"), "source": "SCALP_PROFILE", "name": "Range → Sweep → Retest",
                "family": "SCALPING", "version": prof.get("status"), "implementation": "scalp profile (config/scalp_profile_v1.json)",
                "aliases": ["range_sweep_retest"], "symbols": [prof.get("symbol") or sym], "venue": "MT5", "timeframes": prof.get("timeframes"),
                "enabled": {"signal_source": bool(src.get("range_sweep_retest", True))}, "parameters": {k: prof.get(k) for k in ("range", "zone", "trigger", "exits", "risk", "hedge")},
                "parameters_hash": _h(prof), "variants": [v.get("id") for v in (var.get("variants") or [])], "variants_hash": _h(var),
                "required_models": [], "history_keys": ["scalp research ledger"], "execution_route": "signals only (SHADOW profile)"})
    out.append({"strategy_id": "DOUBLE_RETEST_V2", "source": "SIGNALS", "name": "Double Retest v2", "family": "RESEARCH", "version": "v2",
                "implementation": "forecast/ (research state machine)", "aliases": ["double_retest"], "symbols": [sym], "venue": "MT5",
                "enabled": {"signal_source": bool(src.get("double_retest", True))}, "parameters": {}, "parameters_hash": _h({}),
                "required_models": ["gold_candles (forecast)"], "history_keys": ["forecast research ledger"], "execution_route": "signals only"})
    return out


def models(cfg_store=None) -> list[dict]:
    """Every model of the installation with its install / artifact / use state (read, never assumed)."""
    out: list[dict] = []
    # foundation models (TSFM)
    try:
        from ..tsfm import settings as TS
        st = TS.SettingsStore().get().model_dump(mode="json")
        for mid in TS.MODEL_IDS:
            c = (st.get("models") or {}).get(mid) or {}
            py = TS.find_python(mid, TS.SettingsStore().get().models[mid]) if hasattr(TS, "find_python") else None
            out.append({"model_id": f"tsfm:{mid}", "kind": "PRETRAINED_FORECASTER", "settings": c, "python": py, "installed_env": bool(py),
                        "retired": False})
        for mid, r in (st.get("retired") or {}).items():
            out.append({"model_id": f"tsfm:{mid}", "kind": "RETIRED", "retired": True, "detail": r})
    except Exception as exc:  # noqa: BLE001
        out.append({"model_id": "tsfm", "error": f"{type(exc).__name__}: {exc}"[:200]})
    # Kronos
    try:
        from ..kronos import settings as KS
        ks = KS.SettingsStore().get().model_dump(mode="json") if hasattr(KS, "SettingsStore") else {}
        out.append({"model_id": "kronos", "kind": "PRETRAINED_FORECASTER", "settings": ks})
    except Exception as exc:  # noqa: BLE001
        out.append({"model_id": "kronos", "error": f"{type(exc).__name__}: {exc}"[:200]})
    # model families
    try:
        from ..modelhub.families import registry as FR
        for fid in FR():
            out.append({"model_id": f"family:{fid}", "kind": "MODEL_FAMILY"})
    except Exception as exc:  # noqa: BLE001
        out.append({"model_id": "families", "error": f"{type(exc).__name__}: {exc}"[:200]})
    # TrainHub models + registry
    try:
        from ..trainhub import learn as TL
        from ..trainhub import registry as TR
        for mid in TL.MODELS:
            out.append({"model_id": f"trainhub:{mid}", "kind": "TABULAR_TRAINABLE"})
        for inst in ("XAUUSD", "BTC"):
            try:
                out.append({"model_id": f"trainhub_registry:{inst}", "kind": "REGISTRY", "registry": TR.registry(inst)})
            except Exception:  # noqa: BLE001
                pass
    except Exception as exc:  # noqa: BLE001
        out.append({"model_id": "trainhub", "error": f"{type(exc).__name__}: {exc}"[:200]})
    # Quant metamodel artifacts
    qd = paths.data_dir() / "quant"
    arts = sorted(str(p.relative_to(qd)) for p in qd.glob("**/*.json") if "meta" in p.name.lower()) if qd.exists() else []
    out.append({"model_id": "quant:metamodel", "kind": "LOGISTIC_METAMODEL", "artifacts": arts})
    # gold_candles forecast models
    out.append({"model_id": "gold_candles", "kind": "FORECAST_SHADOW", "detail": "forecast/ (SHADOW, no order permission)"})
    return out


def write_reports(kind: str, cfg_store=None, out_dir: Path | None = None) -> dict:
    """kind = 'before' | 'after'. Reports go to <data>/reports (the 'before' report is written once and never overwritten)."""
    d = out_dir or (paths.data_dir() / "reports")
    d.mkdir(parents=True, exist_ok=True)
    res = {}
    for name, fn in (("strategy_inventory", strategies), ("model_inventory", models)):
        p = d / f"{name}_{kind}.json"
        if kind == "before" and p.exists():
            res[name] = str(p)
            continue
        items = fn(cfg_store)
        p.write_text(json.dumps({"schema": SCHEMA, "kind": kind, "generated_at": _now(), "count": len(items), "items": items},
                                indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        res[name] = str(p)
    return res
