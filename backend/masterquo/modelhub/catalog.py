"""Model registry of the whole bot (PMW-CATALOG-1): every model / analytical module that REALLY exists in the code, with its location,
purpose, required data, input / output, instruments, training method, category and a LIVE state in the unified states.

Sources (not re-declared here): sh/models.REGISTRY (role per strategy + live probes), mm/inventory.MODULES (PMW-MM modules, spec /
blocked status), trainhub registry (Training Center packages) + the modules added in 1.28 (market zones). A documented model without
code appears only from those sources with its blocker - nothing is reported as implemented or trained without evidence.
Categories: TRAINABLE (artifact from training), ONLINE (estimated / filtered online), INDICATOR (deterministic calculation), RULE
(rule / state machine / strategy), SIMULATION (Monte Carlo), EXTERNAL (Claude agent), INFRA (optimiser, benchmark, data).
"""
from __future__ import annotations

from . import contract as C

STATE_FROM_PROBE = {"READY": "READY", "SHADOW_ONLY": "READY", "DETERMINISTIC_OK": "READY", "NOT_TRAINED": "NOT_TRAINED", "NOT_CONNECTED": "DISABLED",
                    "INCOMPATIBLE": "INCOMPATIBLE", "ERROR": "ERROR", "DATA_MISSING": "ERROR", "UNAVAILABLE": "DISABLED"}
CAT_FROM_KIND = {"DETERMINISTIC": "INDICATOR", "TRAINED": "TRAINABLE", "EXTERNAL": "EXTERNAL"}
CAT_FROM_MM = {"TRAINABLE": "TRAINABLE", "ONLINE_LEARNER": "ONLINE", "RECURSIVE_FILTER": "ONLINE", "DETERMINISTIC_INDICATOR": "INDICATOR",
               "RULE_STRATEGY": "RULE", "OPTIMIZER": "INFRA", "DATA_INFRA": "INFRA", "VISUALIZATION": "INDICATOR", "BENCHMARK": "INFRA"}
# where the code lives + what it needs (sh/models.REGISTRY ids)
LOCATION = {
    "data_quality": ("mt5/bridge.py, engine (M01)", "notowania + świece z MT5"), "risk_engine": ("sh/risk.py", "rachunek, pozycje, specyfikacja symbolu"),
    "news": ("news/", "kalendarz makro"), "regime_v2": ("lab/market_v2.py", "świece M1–H1"), "structure_v2": ("lab/structure_v2.py", "świece M5/M15/H1"),
    "smc_pullback": ("lab/context_ind/smc.py", "świece M5"), "vamd": ("extind/vamd.py", "świece M1/M5"), "fractal": ("extind/fractal.py", "świece M1/M5"),
    "atr_vol": ("strategies/indicators.py", "świece M1/M5"), "candles_patterns": ("analysis/candles.py, analysis/chart_patterns.py", "świece"),
    "liquidity": ("analytics/liquidity_context.py, analytics/session_engine.py", "świece M5, sesje"),
    "flow_sr": ("lab/flow_context/", "świece M1/M5"), "decomposition": ("analytics/ (FFT/EMD/VMD)", "świece"),
    "sh_tp_model": ("sh/tpmodel.py", "historia klienta (cykle SH) + świece"), "scalp_A": ("scalp/ (runner scalp)", "eksport M1–H1"),
    "scalp_B": ("scalp/", "eksport M1–H1 + cykle R→S→R"), "gold_forecast": ("forecast/ (gold_candles)", "eksport M5/M30"),
    "legacy_ml": ("ml/ (DT + XGBoost)", "historia setupów S01–S12"), "lab": ("lab/models (LOGREG/TREE/MiniRocket/XGB/ResNet1D/SEW-SNN)", "eksport + etykiety triple-barrier"),
    "indicator_context": ("extind/ (SAR+IQ)", "eksport M1/M5"), "ml_scalp": ("ml/scalp_task.py", "eksport M1–M15"), "nss": ("scalp/nss (TCN)", "eksport M1"),
    "si_move": ("lab/structure_intelligence/", "ticki/świece M1"), "flow_reaction": ("lab/flow_context/markov.py", "świece M1"),
    "context_move": ("lab/context_ind/", "świece M5"), "mm_align_mean": ("mm/align_mean.py", "świece"), "mm_kalman": ("mm/kalman.py", "świece M5"),
    "mm_breakout": ("mm/breakout_zones.py, mm/robust_vol.py", "świece M5"), "mm_multi_indicator": ("mm/multi_indicator.py", "świece M5"),
    "mm_smc_fvg": ("mm/smc_fvg.py", "świece M5"), "mm_gpr": ("mm/gpr.py", "świece M5"), "mm_hdc": ("mm/hdc.py", "cechy M5"),
    "mm_event_engine": ("mm/event_engine.py", "ticki / zdarzenia"), "mm_ste_flownet": ("mm/ste_flownet.py", "zdarzenia"), "agent": ("agent/", "kontekst + klucz API"),
    "th_direction": ("trainhub/inference.py (aktywne paczki)", "świece M1–M30 przez bridge"),
    "kronos": ("kronos/ (serwis) + backend/kronos_runtime (proces .venv_kronos, kod Kronos MIT; 1.37: Kronos-base)", "zamknięte świece M1–H1 z MT5 przez bridge"),
    "chronos2": ("tsfm/ (serwis) + backend/tsfm_runtime (proces .venv_chronos2, chronos-forecasting 2.3.2, Apache-2.0)", "zamknięte świece M5/M15 z MT5 przez bridge"),
    "fincast": ("tsfm/ (serwis) + backend/tsfm_runtime (proces .venv_fincast, kod FinCast Apache-2.0)", "zamknięte świece M5/M15 z MT5 przez bridge"),
}


def _th_entries(inst: str, rt) -> list[dict]:
    from ..trainhub import learn as L
    from ..trainhub import registry as R
    reg = R.registry(inst)
    running = set()
    try:
        tc = getattr(rt, "trainhub", None) if rt else None
        if tc is not None:
            for j in tc.list(20):
                if j["status"] in ("RUNNING", "QUEUED") and j["instrument"] == inst and j["kind"] in ("TRAIN", "FULL"):
                    running.update((j.get("params") or {}).get("models") or ["TH_BASELINE", "TH_LOGREG", "TH_HGB"])
    except Exception:  # noqa: BLE001
        pass
    preds = {}
    try:
        inf = getattr(rt, "trainhub_inference", None) if rt else None
        if inf is not None:
            preds = {p["model_key"]: p for p in inf.predictions(inst)}
    except Exception:  # noqa: BLE001
        preds = {}
    avail = L.available()
    out = []
    for mid, spec in L.MODELS.items():
        keys = [k for k in (reg.get("versions") or {}) if k.startswith(mid + "_")]
        act = {k: v for k, v in (reg.get("active") or {}).items() if k.startswith(mid + "_")}
        if mid in running:
            state, reason = "TRAINING", "zadanie treningu w Centrum treningu"
        elif not avail.get(mid):
            state, reason = "DISABLED", "biblioteka modelu niedostępna w tym środowisku"
        elif act:
            ps = [preds.get(k) for k in act]
            bad = [p for p in ps if p and p["state"] != "READY"]
            if bad:
                state, reason = bad[0]["state"], bad[0]["unavailable_reason"]
            elif all(ps):
                state, reason = "READY", "aktywna wersja: " + ", ".join(f"{k}={v}" for k, v in act.items())
            else:
                state, reason = "READY", "aktywna wersja (czeka na pierwszą zamkniętą świecę): " + ", ".join(f"{k}={v}" for k, v in act.items())
        elif keys:
            state, reason = "DISABLED", f"{sum(len(reg['versions'][k]) for k in keys)} wersji, żadna nieaktywna – aktywacja ręczna w Centrum treningu"
        else:
            state, reason = "NOT_TRAINED", "brak paczki – trening w Centrum treningu"
        out.append({"id": mid.lower(), "name": spec["name"] + " – kierunek po kosztach (Centrum treningu)", "category": "TRAINABLE",
                    "location": "trainhub/learn.py, trainhub/features.py", "purpose": "P(DOWN/FLAT/UP) ruchu po kosztach w horyzoncie H świec",
                    "required_data": "magazyn świec data/marketdata (M1/M5/M15/M30, eksport z MT5)", "input": "cechy PMW-TH-FEAT-1 (wspólne trening/inferencja)",
                    "output": "rozkład 3 klas, kalibracja temperaturą (dev)", "instruments": ["XAUUSD", "BTC"], "training": "Centrum treningu / trainhub",
                    "state": state, "state_pl": C.STATES[state], "reason": reason, "versions": keys, "active": act, "source": "trainhub"})
    return out


def build(rt, inst: str) -> dict:
    from ..sh import models as SM
    rows = []
    for it in SM.REGISTRY:
        try:
            pr = SM.probe(it, rt, inst)
        except Exception as exc:  # noqa: BLE001
            pr = {"status": "ERROR", "reason": f"{type(exc).__name__}: {exc}"[:160]}
        state = STATE_FROM_PROBE.get(pr["status"], "ERROR")
        loc, data = LOCATION.get(it["id"], ("?", "?"))
        cat = CAT_FROM_KIND.get(it["kind"], "INDICATOR")
        if it["id"] in ("data_quality", "risk_engine", "news"):
            cat = "RULE"
        rows.append({"id": it["id"], "name": it["name"], "category": cat, "location": loc, "purpose": it["output"], "required_data": data,
                     "input": data, "output": it["output"], "instruments": ["XAUUSD", "BTC"], "training": it.get("train") or "nie dotyczy",
                     "state": state, "state_pl": C.STATES[state], "reason": pr.get("reason"), "probe_status": pr["status"], "group": it["group"],
                     "roles": it["roles"], "source": "sh/models.REGISTRY"})
    seen = {r["id"] for r in rows}
    try:
        from ..mm import inventory as MI
        for m in MI.MODULES:
            rid = "mm_" + m["id"]
            if rid in seen or m["id"] in ("fusion_board",):
                continue
            blocked = m.get("blocked")
            rows.append({"id": rid, "name": m["name"], "category": CAT_FROM_MM.get(m.get("category"), "INFRA"), "location": ", ".join(m.get("files") or []) or "—",
                         "purpose": m.get("outputs") or "—", "required_data": m.get("inputs") or "—", "input": m.get("inputs") or "—", "output": m.get("outputs") or "—",
                         "instruments": ["XAUUSD", "BTC"], "training": m.get("training") or "—",
                         "state": "DISABLED", "state_pl": C.STATES["DISABLED"],
                         "reason": ("BLOKADA: " + blocked) if blocked else "moduł PMW-MM bez ścieżki w strategiach (obserwacja / badania – panel 12 Master Models)",
                         "source": "mm/inventory.MODULES"})
    except Exception:  # noqa: BLE001
        pass
    rows.append({"id": "market_zones", "name": "Strefy rynkowe M1/M5/M15/M30 (PMW-MZ-1)", "category": "INDICATOR", "location": "zones/market.py, zones/market_service.py",
                 "purpose": "strefy S/R, popyt/podaż, FVG, order blocks, EQH/EQL + konfluencja", "required_data": "zamknięte świece M1–M30 z MT5",
                 "input": "świece", "output": "lista stref (jakość 0–100 – nie prawdopodobieństwo)", "instruments": ["XAUUSD", "BTC"], "training": "nie dotyczy",
                 "state": "READY", "state_pl": C.STATES["READY"], "reason": "liczone na żądanie / na żywo w panelu Strefy rynkowe", "source": "1.28"})
    zst = "READY" if rt is None or getattr(rt, "zones", None) is not None else "DISABLED"
    rows.append({"id": "zone_map", "name": "Mapa stref HLZE+DSVIE+UZICE (M5/M15)", "category": "INDICATOR", "location": "zones/engine.py, zones/service.py",
                 "purpose": "strefy + profile sesji dla strategii", "required_data": "świece M5/M15/H1/D1", "input": "świece", "output": "mapa stref",
                 "instruments": ["XAUUSD", "BTC"], "training": "nie dotyczy", "state": zst, "state_pl": C.STATES[zst],
                 "reason": "co zamkniętą świecę M5 (aktywny instrument)", "source": "zones"})
    rows.append({"id": "monte_carlo", "name": "Monte Carlo ścieżek cen (PMW-MC-1)", "category": "SIMULATION", "location": "montecarlo/",
                 "purpose": "P(TP przed SL w horyzoncie) – symulacja, nie model uczony", "required_data": "świece M1", "input": "świece M1",
                 "output": "prawdopodobieństwo w modelu (kalibracja osobno)", "instruments": ["XAUUSD", "BTC"], "training": "kalibracja: montecarlo validate",
                 "state": "READY", "state_pl": C.STATES["READY"], "reason": "symulacja na żądanie", "source": "montecarlo"})
    rows += _th_entries(inst, rt)
    counts = {}
    for r in rows:
        counts.setdefault(r["category"], 0)
        counts[r["category"]] += 1
    return {"instrument": inst, "items": rows, "counts_by_category": counts,
            "counts_by_state": {s: sum(1 for r in rows if r["state"] == s) for s in C.STATES}, "states": C.STATES,
            "note": "stan = sonda na żywo; 'gotowy' dla modelu SHADOW oznacza gotowy do obserwacji, nie dopuszczony do głosu w strategii"}
