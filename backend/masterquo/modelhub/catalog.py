"""Model registry of the whole bot (PMW-CATALOG-1): every model / analytical module that REALLY exists in the code, with its location,
purpose, required data, input / output, instruments, training method, category and a LIVE state in the unified states.

Sources (not re-declared here): sh/models.REGISTRY (role per strategy + live probes), mm/inventory.MODULES (PMW-MM modules, spec /
blocked status), trainhub registry (Training Center packages) + the modules added in 1.28 (market zones). A documented model without
code appears only from those sources with its blocker - nothing is reported as implemented or trained without evidence.
Categories: TRAINABLE (artifact from training), PRETRAINED (pretrained weights, no training in the bot - 1.46 w2), ONLINE (estimated /
filtered online), INDICATOR (deterministic calculation), RULE (rule / state machine / strategy), SIMULATION (Monte Carlo), EXTERNAL
(Claude agent), INFRA (optimiser, benchmark, data).
1.46 arch (I0003), state axes per row: `state` (unified catalog state - kept for compatibility; for SH rows a LOSSY mapping of the probe,
e.g. SHADOW_ONLY -> READY), `runtime_state` (the raw probe status of an SH row; the state itself for rows without a probe) and, for SH rows,
`use` (participation per strategy from sh/models.participation - the SH matrix). Rows naming a GROUP of producers (quant/ids.GROUPS:
th_direction, lab, si_move) carry is_group / members and are left out of counts_by_category / counts_by_state (counts_group_rows).
"""
from __future__ import annotations

from . import contract as C

STATE_FROM_PROBE = {"READY": "READY", "SHADOW_ONLY": "READY", "DETERMINISTIC_OK": "READY", "NOT_TRAINED": "NOT_TRAINED", "NOT_CONNECTED": "DISABLED",
                    "INCOMPATIBLE": "INCOMPATIBLE", "ERROR": "ERROR", "DATA_MISSING": "ERROR", "UNAVAILABLE": "DISABLED"}
CAT_FROM_KIND = {"DETERMINISTIC": "INDICATOR", "TRAINED": "TRAINABLE", "PRETRAINED": "PRETRAINED", "EXTERNAL": "EXTERNAL"}
CAT_FROM_MM = {"TRAINABLE": "TRAINABLE", "ONLINE_LEARNER": "ONLINE", "RECURSIVE_FILTER": "ONLINE", "DETERMINISTIC_INDICATOR": "INDICATOR",
               "RULE_STRATEGY": "RULE", "OPTIMIZER": "INFRA", "DATA_INFRA": "INFRA", "VISUALIZATION": "INDICATOR", "BENCHMARK": "INFRA"}
# 1.46 arch (I0384): the 1.41 panel "12 Master Models" is not in the current frontend - the API stays (public contract)
MM_NO_PATH = "moduł PMW-MM bez ścieżki w strategiach (obserwacja / badania – API /api/v1/mm/*; brak panelu w bieżącym interfejsie)"
STRATEGIES = ("SCALPING", "HEDGING")
# where the code lives + what it needs (sh/models.REGISTRY ids)
LOCATION = {
    # 1.46 arch (I0553): the three data-quality checks that really run (SH limits, ACTIVE session model, Quant snapshot QC) - it named
    # 'mt5/bridge.py, engine (M01)', where none of them lives
    "data_quality": ("sh/context.py (SH), data/quality.py (ACTIVE), quant/snapshot.py (QC migawki Quant)", "notowania + świece z MT5"),
    "risk_engine": ("sh/risk.py", "rachunek, pozycje, specyfikacja symbolu"),
    "news": ("news/", "kalendarz makro"), "regime_v2": ("lab/market_v2.py", "świece M5"),
    # 1.46 arch (I0276 / I0314 / I0316 / I0568 / I0573 / I0576 / I0579): every path below exists (tests/test_arch146_w2_catalog.py)
    "structure_v2": ("analysis/structure_v2.py (SH: sh/context._structure)", "świece M5/M15/H1"),
    "smc_pullback": ("lab/context_ind/smc.py", "świece M5"), "vamd": ("lab/context_ind/vamd.py (SH: sh/context._ctx_m5/_ctx_m1)", "świece M1/M5"),
    "fractal": ("lab/context_ind/fractal.py (SH: sh/context._ctx_m5)", "świece M5"),
    "atr_vol": ("sh/context.py (_atr, Wilder 14)", "świece M1/M5"), "candles_patterns": ("analysis/candles.py, analysis/chart_patterns.py", "świece"),
    "liquidity": ("analytics/liquidity_context.py, analytics/session_engine.py", "świece M5, sesje"),
    "flow_sr": ("lab/flow_context/", "świece M1/M5"), "decomposition": ("analytics/ (FFT/EMD/VMD)", "świece"),
    "sh_tp_model": ("sh/tpmodel.py", "historia klienta (cykle SH) + świece"), "scalp_A": ("scalp/ (runner scalp)", "eksport M1–H1"),
    "scalp_B": ("scalp/", "eksport M1–H1 + cykle R→S→R"), "gold_forecast": ("forecast/ (gold_candles)", "eksport M5/M30"),
    "legacy_ml": ("ml/ (DT + XGBoost)", "historia setupów S01–S12"),
    "lab": ("lab/protocol.py, lab/nets.py, lab/minirocket.py, lab/service.py (LOGREG/TREE/MiniRocket/XGB/ResNet1D/SEW-SNN)", "eksport + etykiety triple-barrier"),
    "indicator_context": ("extind/ (SAR+IQ)", "eksport M1/M5"), "ml_scalp": ("ml/scalp_task.py", "eksport M1–M15"),
    "nss": ("lab/nss.py, lab/scalp_net.py (TCN), lab/nss_service.py", "eksport M1"),
    "si_move": ("lab/structure_task.py, lab/structure_nets.py, lab/si_families.py, lab/si_service.py", "ticki/świece M1"),
    # I0304: the reaction model only - Markov3 (lab/flow_context/markov.py) is its own producer flow:markov3 (quant/ids.EXTRA_PRODUCERS)
    "flow_reaction": ("lab/flow_context/task.py (model reakcji CLASS_FREQ/LOGREG/XGB; bez inferencji na żywo)", "świece M1"),
    "context_move": ("lab/context_ind/", "świece M5"), "mm_align_mean": ("mm/align_mean.py", "świece"), "mm_kalman": ("mm/kalman.py", "świece M5"),
    "mm_breakout": ("mm/breakout_zones.py, mm/robust_vol.py", "świece M5"), "mm_multi_indicator": ("mm/multi_indicator.py", "świece M5"),
    "mm_smc_fvg": ("mm/smc_fvg.py", "świece M5"), "mm_gpr": ("mm/gpr.py", "świece M5"), "mm_hdc": ("mm/hdc.py", "cechy M5"),
    "mm_event_engine": ("mm/event_engine.py", "ticki / zdarzenia"), "mm_ste_flownet": ("mm/ste_flownet.py", "zdarzenia"), "agent": ("agent/", "kontekst + klucz API"),
    "th_direction": ("trainhub/inference.py (aktywne paczki)", "świece M1–M30 przez bridge"),
    "kronos": ("kronos/ (serwis) + backend/kronos_runtime (proces .venv_kronos, kod Kronos MIT; 1.42.8: Kronos-small)", "zamknięte świece M1–H1 z MT5 przez bridge"),
    "chronos2": ("tsfm/ (serwis) + backend/tsfm_runtime (proces .venv_chronos2, chronos-forecasting 2.3.2, Apache-2.0)", "zamknięte świece M5/M15 z MT5 przez bridge"),
    "granite_ttm": ("tsfm/ (serwis) + backend/tsfm_runtime (proces .venv_granite, granite-tsfm 0.3.11, Apache-2.0; 1.40 zamiast FinCast)",
                    "zamknięte świece M5/M15 z MT5 przez bridge (wspólny snapshot z Chronos-2)"),
    "tirex2": ("tsfm/ (serwis) + backend/tsfm_runtime (proces .venv_tirex2, TiRex-2 NX-AI; 1.41)",
               "zamknięte świece M5/M15 z MT5 przez bridge (wspólny snapshot z Chronos-2)"),
}


def _th_entries(inst: str, rt) -> list[dict]:
    from ..trainhub import learn as L
    from ..trainhub import registry as R
    out = []
    for mid, spec in L.MODELS.items():
        # arch146 I0010: one state computation for every view of the trainhub models (registry.status_of) - unchanged here
        st = R.status_of(inst, mid, rt)
        state, reason, keys, act = st["state"], st["reason"], st["versions"], st["active"]
        out.append({"id": mid.lower(), "name": spec["name"] + " – kierunek po kosztach (Centrum treningu)", "category": "TRAINABLE",
                    "location": "trainhub/learn.py, trainhub/features.py", "purpose": "P(DOWN/FLAT/UP) ruchu po kosztach w horyzoncie H świec",
                    "required_data": "magazyn świec data/marketdata (M1/M5/M15/M30, eksport z MT5)", "input": "cechy PMW-TH-FEAT-1 (wspólne trening/inferencja)",
                    "output": "rozkład 3 klas, kalibracja temperaturą (dev)", "instruments": ["XAUUSD", "BTC"], "training": "Centrum treningu / trainhub",
                    "state": state, "state_pl": C.STATES[state], "reason": reason, "versions": keys, "active": act, "source": "trainhub"})
    return out


# 1.46 arch (I0002): the catalog is the only model list the panel reads - it now covers the canonical registry (quant/inventory, quant/ids)
CAT_FROM_INV = {"MODEL_TRAINED": "TRAINABLE", "MODEL_PRETRAINED": "TRAINABLE", "TRAINABLE": "TRAINABLE", "BASELINE": "TRAINABLE",
                "META_MODEL": "TRAINABLE", "MODEL_ESTIMATED": "ONLINE", "MEASUREMENT": "INDICATOR", "RULE_OR_MEASUREMENT": "RULE",
                "ANALYSIS": "INDICATOR", "NATIVE_MQL5": "INDICATOR", "VISUALIZATION": "INDICATOR", "SIMULATION": "SIMULATION", "AGENT": "EXTERNAL",
                "RESEARCH": "INFRA", "TOOL": "INFRA", "OPTIMIZER": "INFRA", "BENCHMARK": "INFRA", "DATA_INFRA": "INFRA"}
_FIXED_CANON = {"market_zones": "analysis:market_zones", "zone_map": "analysis:zones", "monte_carlo": "analysis:montecarlo"}


def _canonical_of(r: dict) -> str:
    """Canonical id (quant/ids) of an existing catalog row - the same id the inventory gives its producer. One source: canonical_row_id
    (I0009); the rules below only name rows it leaves without an id (e.g. TH_BASELINE, plain SH rows)."""
    from ..quant import ids as I
    cid = canonical_row_id(r)
    if cid:
        return cid
    rid, src = r["id"], r.get("source")
    if src == "trainhub":
        return "trainhub:" + rid.upper()
    if src == "mm/inventory.MODULES":
        mid = rid.removeprefix("mm_")
        return I.resolve(mid) or I.resolve("mm:" + mid) or "mm:" + mid
    if rid in _FIXED_CANON:
        return _FIXED_CANON[rid]
    if rid in I.GROUPS:
        return "group:" + rid
    return I.resolve(rid) or "sh:" + rid


def _family_state(fid: str, rt, inst: str) -> tuple[str, str]:
    """State of a family row from FamilyService: its stored state, its training job and the last cached record - no computation and no
    dependency probe (the .venv_deep health process is never started by the catalog); never READY without a record."""
    from .families.service import NO_LIVE_PATH
    fam = getattr(rt, "families", None) if rt is not None else None
    if fam is None:
        return "DISABLED", "serwis rodzin modeli nie działa w tym procesie – stan na żywo nieznany"
    st = fam.store.state(fid, inst)
    if ((fam.job(fid, inst) or {}).get("state")) == "RUNNING":
        return "TRAINING", "trening rodziny w toku"
    use = st.get("use", "OFF")
    if fid != "MICROSTRUCTURE":                          # MICROSTRUCTURE measures without an artifact
        if not st.get("active"):
            return "NOT_TRAINED", "brak aktywnego artefaktu – trening / aktywacja w Centrum treningu (rodziny modeli)"
        if use == "OFF":
            return "DISABLED", "rola OFF – rodzina nie jest liczona"
        if fid in NO_LIVE_PATH:
            return "DISABLED", NO_LIVE_PATH[fid]
    last = fam.last_prediction(fid, inst)
    if not last:
        return "BLOCKED_DATA", f"brak prognozy w tym cyklu (rola {use}) – liczona przy odczycie prognoz rodzin"
    state = last.get("state") if last.get("state") in C.STATES else "ERROR"
    return state, last.get("unavailable_reason") or f"ostatnia prognoza: {C.STATES[state]} (rola {last.get('use') or use})"


def _canonical_rows(rt, inst: str, rows: list[dict]) -> list[dict]:
    """canonical_id / aliases on every row + one row per canonical producer the catalog did not list yet (families, TiRex-2, TabICL,
    research modules, lab / SI members, ...). Existing ids and fields stay as they were (contract); NO_SPEC / NOT_IMPLEMENTED entries
    are not added. State of an added row: families from FamilyService; otherwise READY only when its record is eligible in the current
    Quant snapshot, else the inventory probe - an unprobed producer is never shown as READY."""
    from ..quant import ids as I
    from ..quant import inventory as QI
    for r in rows:
        r["canonical_id"] = _canonical_of(r)
        r["aliases"] = I.aliases_of(r["canonical_id"])
    have = {r["canonical_id"] for r in rows}
    pub = getattr(getattr(rt, "quant", None), "pub", None) if rt is not None else None
    cur = (pub.current() if pub is not None else None) or {}
    ready = {p.get("canonical_id") for p in cur.get("eligible") or []}
    excluded = {p.get("canonical_id"): (p.get("eligibility") or {}).get("reason") for p in cur.get("excluded") or []}
    out = []
    for e in QI.build(None, inst)["entries"]:
        cid = e["id"]
        if cid in have or e.get("code_state") in ("NO_SPEC", "NOT_IMPLEMENTED", "GROUP"):
            continue
        have.add(cid)
        rs = e.get("runtime_state") or "NOT_EVALUATED"
        if cid.startswith("family:"):
            try:
                state, reason = _family_state(cid.split(":", 1)[1], rt, inst)
            except Exception as exc:  # noqa: BLE001
                state, reason = "ERROR", f"{type(exc).__name__}: {exc}"[:160]
        elif cid in ready:
            state, reason = "READY", "rekord dopuszczony w bieżącej migawce Quant"
        elif cid in excluded:
            state, reason = "BLOCKED_DATA", f"poza migawką Quant: {excluded[cid]}"
        elif rs in ("MISSING_DEPENDENCY", "UNAVAILABLE", "NOT_CONNECTED"):
            state, reason = "DISABLED", str(e.get("state_reason") or rs)
        elif rs in ("NOT_TRAINED", "ERROR"):
            state, reason = rs, str(e.get("state_reason") or rs)
        else:
            state, reason = "DISABLED", ("stan na żywo nie jest sondowany w katalogu – "
                                         + str(e.get("not_applicable_reason") or e.get("notes") or "producent z rejestru kanonicznego"))[:300]
        files = [str(f).replace("backend/masterquo/", "") for f in e.get("files") or []]
        out.append({"id": cid, "name": e.get("name") or cid, "category": CAT_FROM_INV.get(e.get("category"), "INFRA"),
                    "location": ", ".join(files) or "—", "purpose": e.get("output") or e.get("task") or "—",
                    "required_data": e.get("data_required") or "—", "input": e.get("input") or "—", "output": e.get("output") or e.get("task") or "—",
                    "instruments": ["XAUUSD", "BTC"], "training": e.get("owner_train") or "nie dotyczy", "state": state, "state_pl": C.STATES[state],
                    "reason": reason, "probe_status": rs, "source": "quant/inventory (rejestr kanoniczny)", "canonical_id": cid,
                    "aliases": list(e.get("aliases") or [])})
    return out


def _use_note(pr: dict) -> str | None:
    """1.46: the configured use of a model that can act outside OBSERVE (the catalog note 'not admitted to vote' is not true for them)."""
    d = pr.get("detail") or {}
    if d.get("ml_mode") == "ASSIST":
        return "ml.mode ASSIST: bramka ścieżki ACTIVE (S01–S12) – może zablokować decyzję ścieżki ACTIVE; w SH tylko nadzór"
    use = d.get("use") if isinstance(d.get("use"), dict) else {}
    act = {k: v for k, v in use.items() if v in ("ASSIST", "REQUIRED")}
    if act:
        return "użycie " + ", ".join(f"{k}={v}" for k, v in sorted(act.items())) + " – może tylko wstrzymać READY -> WAIT (nigdy nie dopuszcza wejścia)"
    return None


_FIXED_CANON = {"market_zones": "analysis:market_zones", "zone_map": "analysis:zones", "monte_carlo": "analysis:montecarlo"}


def canonical_row_id(r: dict) -> str | None:
    """1.46 arch (I0009): canonical id of a catalog row in the canonical registry (quant/ids + quant/inventory): SH rows as the inventory
    folds them (group:<id> for a group row, aliases resolved, else sh:<id>), MM modules mm:<module>, Training Center packages trainhub:<MODEL>.
    Additive field - the row 'id' stays as it was (the panel matches predictions by canonical_id first)."""
    from ..quant import ids as I
    rid, src = str(r.get("id") or ""), r.get("source")
    if src == "sh/models.REGISTRY":
        return f"group:{rid}" if rid in I.GROUPS else (I.resolve(rid) or f"sh:{rid}")
    if src == "mm/inventory.MODULES":
        m = rid.removeprefix("mm_")
        return I.resolve(m) or f"mm:{m}"
    if src == "trainhub":
        return I.resolve(rid.upper())
    return _FIXED_CANON.get(rid)


def build(rt, inst: str) -> dict:
    from ..quant import ids as I
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
                     "roles": it["roles"], "source": "sh/models.REGISTRY", "use_note": _use_note(pr),
                     # 1.46 arch (I0003): the raw probe (state above is the lossy compatibility mapping) and what the bot really does
                     # with the component per strategy (sh/models.participation - the SH matrix; presentation only)
                     "runtime_state": pr["status"], "use": {s: SM.participation(it, pr, s)["use"] for s in STRATEGIES}})
        if it["id"] in I.GROUPS:                                         # a GROUP of producers (th_direction / lab / si_move), never one
            rows[-1].update(is_group=True, members=list(I.GROUPS[it["id"]]))
    seen = {r["id"] for r in rows}
    seen_canon = {I.resolve(r["id"]) for r in rows} - {None}          # 1.46 arch: join MM modules to SH rows by canonical id, not by 'mm_'
    try:
        from ..mm import inventory as MI
        for m in MI.MODULES:
            rid = "mm_" + m["id"]
            if rid in seen or m["id"] in ("fusion_board",) or (I.resolve(m["id"]) or I.resolve("mm:" + m["id"])) in seen_canon:
                continue
            blocked = m.get("blocked")
            rows.append({"id": rid, "name": m["name"], "category": CAT_FROM_MM.get(m.get("category"), "INFRA"), "location": ", ".join(m.get("files") or []) or "—",
                         "purpose": m.get("outputs") or "—", "required_data": m.get("inputs") or "—", "input": m.get("inputs") or "—", "output": m.get("outputs") or "—",
                         "instruments": ["XAUUSD", "BTC"], "training": m.get("training") or "—",
                         "state": "DISABLED", "state_pl": C.STATES["DISABLED"],
                         "reason": ("BLOKADA: " + blocked) if blocked else MM_NO_PATH,
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
    try:
        rows += _canonical_rows(rt, inst, rows)
    except Exception as exc:  # noqa: BLE001 - the canonical view never breaks the catalog the panel already shows
        import logging
        logging.getLogger(__name__).warning("catalog: canonical registry rows unavailable: %s: %s", type(exc).__name__, exc)
        for r in rows:
            r.setdefault("canonical_id", canonical_row_id(r))
    for r in rows:
        r.setdefault("runtime_state", r["state"])                       # rows without a probe: the state itself (no mapping happened)
    # 1.46 arch (I0003): group rows are not producers - counting them doubled th_direction next to th_* (TRAINABLE)
    real = [r for r in rows if not r.get("is_group")]
    counts = {}
    for r in real:
        counts.setdefault(r["category"], 0)
        counts[r["category"]] += 1
    return {"instrument": inst, "items": rows, "counts_by_category": counts,
            "counts_by_state": {s: sum(1 for r in real if r["state"] == s) for s in C.STATES}, "states": C.STATES,
            "counts_group_rows": len(rows) - len(real),
            "note": "stan = sonda na żywo; 'gotowy' dla modelu SHADOW oznacza gotowy do obserwacji, nie dopuszczony do głosu w strategii "
                    "(wyjątki – ASSIST / REQUIRED – opisuje pole use_note wiersza); runtime_state = surowa sonda, use = udział per strategia "
                    "(macierz SH); wiersze grupowe (is_group: th_direction, lab, si_move) nie są liczone w counts_by_*"}
