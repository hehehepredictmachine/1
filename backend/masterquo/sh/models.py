"""Model registry for SCALPING / HEDGING: every model / analytics module of the bot with its ROLE per strategy, the event it
predicts, its correlation group and a LIVE status probe (never a declared status).

Participation rules (docs/strategie_sh/03_MODELE_I_ROLE.md):
* GATE roles (data quality, risk / anomaly, regime) are deterministic and must pass, otherwise WAIT / NO_TRADE.
* EVIDENCE roles count toward the setup only when the component is READY (trained, selected, compatible, with a live inference
  path AND validated on holdout for its own event). Otherwise it is shown as INFO with the concrete reason - never a vote.
* One correlation group = one piece of evidence: e.g. four models that all predict the M1 move direction are summarised once
  (agreement inside the group is not independent confirmation).
* TARGET_PROB: only a model trained on EXACTLY the strategy's event ("TP2 before SL within H minutes" for this TP grid) may
  supply a probability. Models of other events (TP1 of the range-sweep setup, 1.5 ATR triple barrier, net-R > 0) are scores.
"""
from __future__ import annotations

import json
from pathlib import Path

ROLES = ("DATA_QUALITY", "RISK_ANOMALY", "REGIME", "DIRECTION_STRUCTURE", "VOLATILITY", "TIMING", "PATTERN", "LIQUIDITY",
         "TARGET_PROB", "SUPERVISION")
STATUS = ("READY", "SHADOW_ONLY", "NOT_TRAINED", "NOT_CONNECTED", "INCOMPATIBLE", "ERROR", "DETERMINISTIC_OK", "DATA_MISSING", "UNAVAILABLE")

# id, name, kind, event/output, correlation group, roles {SCALPING, HEDGING}, training task (runner) or None
REGISTRY: list[dict] = [
    # --- deterministic (no training) -----------------------------------------------------------------------------------
    {"id": "data_quality", "name": "Jakość i świeżość danych (bridge, zegar, spread)", "kind": "DETERMINISTIC", "output": "OK/BLOCK + wiek danych",
     "group": "DATA", "roles": {"SCALPING": "DATA_QUALITY", "HEDGING": "DATA_QUALITY"}, "train": None},
    {"id": "risk_engine", "name": "Wspólny silnik ryzyka SH (limity, margin, spread, ekspozycja)", "kind": "DETERMINISTIC", "output": "PASS/BLOCK + powody",
     "group": "RISK", "roles": {"SCALPING": "RISK_ANOMALY", "HEDGING": "RISK_ANOMALY"}, "train": None},
    {"id": "news", "name": "Kalendarz makro (blokada wysokiego wpływu)", "kind": "DETERMINISTIC", "output": "blackout tak/nie",
     "group": "RISK", "roles": {"SCALPING": "RISK_ANOMALY", "HEDGING": "RISK_ANOMALY"}, "train": None},
    {"id": "regime_v2", "name": "Reżim rynku MQ_REGIME_MULTI_V2 (market_v2)", "kind": "DETERMINISTIC", "output": "TREND/RANGE/TRANSITION/HIGH_VOL",
     "group": "REGIME", "roles": {"SCALPING": "REGIME", "HEDGING": "REGIME"}, "train": None},
    {"id": "structure_v2", "name": "Struktura rynku structure_v2 (M5/M15/H1, BOS/CHoCH)", "kind": "DETERMINISTIC", "output": "trend per TF",
     "group": "STRUCTURE", "roles": {"SCALPING": "DIRECTION_STRUCTURE", "HEDGING": "DIRECTION_STRUCTURE"}, "train": None},
    {"id": "smc_pullback", "name": "Pullback + SMC (BoS/CHoCH/IDM) – context_ind", "kind": "DETERMINISTIC", "output": "trend SMC, aktywne poziomy",
     "group": "STRUCTURE", "roles": {"SCALPING": "DIRECTION_STRUCTURE", "HEDGING": "DIRECTION_STRUCTURE"}, "train": None},
    {"id": "vamd", "name": "VAMD momentum", "kind": "DETERMINISTIC", "output": "y (znak = momentum)", "group": "MOMENTUM",
     "roles": {"SCALPING": "TIMING", "HEDGING": "TIMING"}, "train": None},
    {"id": "fractal", "name": "Bounded Katz FD (trend/chop bez kierunku)", "kind": "DETERMINISTIC", "output": "TREND/NEUTRAL/CHOP", "group": "REGIME",
     "roles": {"SCALPING": "REGIME", "HEDGING": "REGIME"}, "train": None},
    {"id": "atr_vol", "name": "Zmienność ATR(14) M1/M5 + StopDistance", "kind": "DETERMINISTIC", "output": "ATR w USD", "group": "VOLATILITY",
     "roles": {"SCALPING": "VOLATILITY", "HEDGING": "VOLATILITY"}, "train": None},
    {"id": "candles_patterns", "name": "Świece i formacje (candles, chart_patterns, sci2)", "kind": "DETERMINISTIC", "output": "rola świecy / formacja",
     "group": "PATTERN", "roles": {"SCALPING": "PATTERN", "HEDGING": "PATTERN"}, "train": None},
    {"id": "liquidity", "name": "Płynność: sesje (sweep boxes) + heatmapa likwidacji", "kind": "DETERMINISTIC", "output": "poziomy płynności",
     "group": "LIQUIDITY", "roles": {"SCALPING": "LIQUIDITY", "HEDGING": "LIQUIDITY"}, "train": None},
    {"id": "flow_sr", "name": "Heikin Flow + kanały S/R (flow_context)", "kind": "DETERMINISTIC", "output": "kolor HA, pasma S/R", "group": "STRUCTURE",
     "roles": {"SCALPING": "DIRECTION_STRUCTURE", "HEDGING": "LIQUIDITY"}, "train": None},
    {"id": "decomposition", "name": "Dekompozycja sygnału FFT/EMD/VMD (analytics)", "kind": "DETERMINISTIC", "output": "cykl dominujący (obserwacja)",
     "group": "CYCLE", "roles": {"SCALPING": "SUPERVISION", "HEDGING": "SUPERVISION"}, "train": None},
    # --- trained models -------------------------------------------------------------------------------------------------
    {"id": "sh_tp_model", "name": "SH: P(TP2 przed SL w horyzoncie) – model zdarzenia strategii", "kind": "TRAINED",
     "output": "skalibrowane P dokładnie zdarzenia strategii", "group": "TP_EVENT_SH", "roles": {"SCALPING": "TARGET_PROB", "HEDGING": "TARGET_PROB"},
     "train": "sh_models"},
    {"id": "scalp_A", "name": "Scalp A – kierunek 1/3/5 min (LR/HGB/MLP)", "kind": "TRAINED", "output": "P(DOWN/FLAT/UP) po kosztach", "group": "M1_DIRECTION",
     "roles": {"SCALPING": "DIRECTION_STRUCTURE", "HEDGING": "TIMING"}, "train": "scalp_A"},
    {"id": "scalp_B", "name": "Scalp B – jakość setupu Range→Sweep→Retest", "kind": "TRAINED", "output": "P(TP1 przed SL) INNEGO setupu (score)",
     "group": "TP_OTHER_EVENT", "roles": {"SCALPING": "SUPERVISION", "HEDGING": "SUPERVISION"}, "train": "scalp_A"},
    {"id": "gold_forecast", "name": "gold_candles – prognoza świec 5/15/30 min", "kind": "TRAINED", "output": "P(DOWN/FLAT/UP) zamknięcia",
     "group": "M5_DIRECTION", "roles": {"SCALPING": "TIMING", "HEDGING": "DIRECTION_STRUCTURE"}, "train": "forecast"},
    {"id": "legacy_ml", "name": "Legacy ML Decision Tree + XGBoost (setupy S01–S12)", "kind": "TRAINED", "output": "P(net R > 0) setupu S01–S12",
     "group": "TP_OTHER_EVENT", "roles": {"SCALPING": "SUPERVISION", "HEDGING": "SUPERVISION"}, "train": "ml"},
    {"id": "lab", "name": "Lab: LOGREG/TREE/MiniRocket/XGB/ResNet1D/SEW-SNN", "kind": "TRAINED", "output": "score triple-barrier LONG (nieskalibrowany)",
     "group": "TP_OTHER_EVENT", "roles": {"SCALPING": "SUPERVISION", "HEDGING": "SUPERVISION"}, "train": "lab"},
    {"id": "indicator_context", "name": "Kontekst wskaźników SAR + IQ (reakcja)", "kind": "TRAINED", "output": "P(TP1 przed SL) polityki scalp (score)",
     "group": "TP_OTHER_EVENT", "roles": {"SCALPING": "SUPERVISION", "HEDGING": "SUPERVISION"}, "train": "indicator_context"},
    {"id": "ml_scalp", "name": "Scalp ML XGBoost (net R cyklu)", "kind": "TRAINED", "output": "P(net_R > 0), E[net_R] innego cyklu", "group": "TP_OTHER_EVENT",
     "roles": {"SCALPING": "SUPERVISION", "HEDGING": "SUPERVISION"}, "train": "ml_scalp"},
    {"id": "nss", "name": "Neural Scalp System (TCN)", "kind": "TRAINED", "output": "P(TP1_FIRST/SL_FIRST/TIMEOUT) innego setupu", "group": "TP_OTHER_EVENT",
     "roles": {"SCALPING": "SUPERVISION", "HEDGING": "SUPERVISION"}, "train": "neural_scalp"},
    {"id": "si_move", "name": "Structure Intelligence – ruch M1 h=3/5/15 (ResNeXt/SEW/SpikingBrain/MiniRocket v2…)", "kind": "TRAINED",
     "output": "P(DOWN/FLAT/UP) + kwantyle r_h/ATR", "group": "M1_DIRECTION", "roles": {"SCALPING": "DIRECTION_STRUCTURE", "HEDGING": "TIMING"},
     "train": "structure_intelligence"},
    {"id": "flow_reaction", "name": "Flow context – model reakcji M1 + Markov3", "kind": "TRAINED", "output": "P(DOWN/FLAT/UP) M1; stany Markowa",
     "group": "M1_DIRECTION", "roles": {"SCALPING": "TIMING", "HEDGING": "TIMING"}, "train": "flow_context"},
    {"id": "context_move", "name": "Context indicators – CONTEXT_MOVE_M5_V1", "kind": "TRAINED", "output": "P(DOWN/FLAT/UP) M5", "group": "M5_DIRECTION",
     "roles": {"SCALPING": "TIMING", "HEDGING": "DIRECTION_STRUCTURE"}, "train": "context_indicators"},
    {"id": "agent", "name": "Agent Claude (weto, opis)", "kind": "EXTERNAL", "output": "BUY/SELL/WAIT/NO_TRADE bez prawdopodobieństwa",
     "group": "AGENT", "roles": {"SCALPING": "SUPERVISION", "HEDGING": "SUPERVISION"}, "train": None},
]


def _json(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _probe_registry_file(path: Path, key: str) -> tuple[str, str, dict]:
    reg = _json(path)
    if reg is None:
        return "NOT_TRAINED", f"brak rejestru {path.name} (zadanie treningu nie zostało uruchomione na danych)", {}
    sel = reg.get(key)
    if not sel:
        return "NOT_TRAINED" if not reg.get("runs") else "SHADOW_ONLY", f"brak wybranego modelu ({key} puste)", {"runs": len(reg.get("runs") or {})}
    return "SHADOW_ONLY", "wybrany do obserwacji SHADOW – brak walidacji holdout dla zdarzenia strategii SH", {"selected": sel}


def probe(item: dict, rt, inst: str) -> dict:
    """Live status of one component. Never raises: a broken probe is reported as ERROR with the exception type."""
    import mq_instruments as mi
    from .. import paths
    mid = item["id"]
    try:
        if item["kind"] == "DETERMINISTIC":
            if mid == "data_quality":
                q = rt.bridge.quote_status() if rt else None
                return {"status": "DETERMINISTIC_OK" if q else "DATA_MISSING", "reason": "notowanie dostępne" if q else "brak notowania z MT5"}
            if mid == "news":
                return {"status": "DETERMINISTIC_OK", "reason": "kalendarz " + str(((rt.news.summary() if rt else {}) or {}).get("status", "?"))}
            return {"status": "DETERMINISTIC_OK", "reason": "nie wymaga treningu; liczony z bieżących świec"}
        if mid == "agent":
            st = getattr(rt.agent, "state", "?") if rt else "?"
            return {"status": "SHADOW_ONLY" if st not in ("DISABLED", "NO_KEY") else "UNAVAILABLE", "reason": f"agent: {st}; weto/opis, nie głos"}
        if mid == "sh_tp_model":
            from . import tpmodel
            st = tpmodel.status(inst)
            return {"status": st["status"], "reason": st["reason"], "detail": st}
        if mid == "gold_forecast":
            return dict(zip(("status", "reason", "detail"), _probe_registry_file(mi.root("forecast", inst) / "registry.json", "active")))
        if mid in ("scalp_A", "scalp_B"):
            return dict(zip(("status", "reason", "detail"), _probe_registry_file(mi.root("scalp", inst) / "registry.json", "active")))
        if mid == "legacy_ml":
            if rt and getattr(rt.ml, "inst", None) == inst:
                cid = rt.ml.registry.champion_id
                return {"status": "SHADOW_ONLY" if cid else "NOT_TRAINED", "reason": f"champion {cid}; zdarzenie S01–S12, nie TP SH" if cid else "brak championa"}
            return {"status": "UNAVAILABLE", "reason": "instrument inny niż aktywny w bocie"}
        if mid == "lab":
            ptr = _json(paths.data_dir() / "lab" / "models" / inst / "ACTIVE.json") or {}
            act = {k: v for k, v in (ptr.get("active") or ptr).items() if v} if isinstance(ptr, dict) else {}
            return {"status": "SHADOW_ONLY" if act else "NOT_TRAINED", "reason": "aktywne rodziny: " + (", ".join(act) if act else "brak") +
                    " – score nieskalibrowany, zdarzenie 1.5 ATR LONG"}
        base = paths.data_dir()
        files = {"indicator_context": (base / "indicator_context" / inst / "registry.json", "active"),
                 "ml_scalp": (base / "ml_scalp" / inst / "registry.json", "selected"),
                 "nss": (base / "nss" / inst / "registry.json", "selected"),
                 "si_move": (base / "structure_intelligence" / inst / "registry.json", "shadow"),
                 "flow_reaction": (base / "flow_context" / inst / "registry.json", "shadow")}
        if mid in files:
            return dict(zip(("status", "reason", "detail"), _probe_registry_file(*files[mid])))
        if mid == "context_move":
            runs = list((base / "context_ind" / inst / "runs").glob("*/report.json"))
            return {"status": "NOT_CONNECTED", "reason": f"{len(runs)} runów; model bez ścieżki inferencji na żywo (F-17) – tylko badania"}
        return {"status": "UNAVAILABLE", "reason": "brak sondy"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "ERROR", "reason": f"{type(exc).__name__}: {exc}"[:200]}


def participation(item: dict, st: dict, strategy: str) -> dict:
    """How this component takes part in `strategy` right now."""
    role = item["roles"].get(strategy)
    s = st["status"]
    if role in ("DATA_QUALITY", "RISK_ANOMALY", "REGIME"):
        use = "GATE" if s == "DETERMINISTIC_OK" else "GATE_UNAVAILABLE"
    elif role == "TARGET_PROB":
        use = "PROBABILITY" if s == "READY" else "NONE"
    elif s in ("READY", "DETERMINISTIC_OK"):
        use = "EVIDENCE"
    elif s == "SHADOW_ONLY":
        use = "INFO"
    else:
        use = "NONE"
    return {"role": role, "use": use}


def matrix(rt, inst: str) -> dict:
    rows = []
    for it in REGISTRY:
        st = probe(it, rt, inst)
        rows.append({**{k: it[k] for k in ("id", "name", "kind", "output", "group", "train")}, "instrument": inst, "status": st["status"],
                     "reason": st["reason"], "detail": st.get("detail"),
                     "SCALPING": participation(it, st, "SCALPING"), "HEDGING": participation(it, st, "HEDGING")})
    tp = next(r for r in rows if r["id"] == "sh_tp_model")
    return {"instrument": inst, "rows": rows,
            "mode": "PEŁNA" if tp["status"] == "READY" else "OGRANICZONA",
            "mode_note": None if tp["status"] == "READY" else
            ("TRYB OGRANICZONY (zdefiniowany): brak skalibrowanego modelu zdarzenia strategii – setup ma tylko score, "
             "sygnały wyłącznie SIGNALS/PAPER; AUTO zablokowane do czasu treningu i walidacji sh_tp_model"),
            "correlation_groups": sorted({r["group"] for r in rows})}
