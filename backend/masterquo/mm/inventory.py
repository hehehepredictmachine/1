"""Verified module inventory of the master prompt (PMW-MM-INVENTORY-1).

Static facts (files, category, contracts, spec file) are declared here; dynamic facts (training executed, validation, shadow) come from
the latest orchestrator run (`merge_run`). A status is never stronger than its evidence: no spec -> BLOCKED_SPEC_MISSING (the module is
not reconstructed from its name); native MQL5 code is IMPLEMENTED until it is compiled and executed in a real MT5 terminal, and the
native status names its scope (`native_scope`: what of the module is ported, what stays Python-only). UNIT_TESTED needs a declared unit
test class (UNIT_TESTS).
"""
from __future__ import annotations

import json
from pathlib import Path

VERSION = "PMW-MM-INVENTORY-1"
SPEC_BUNDLE = "XXX.rar (10 plików .md) + PEPEMARKETWIZARD_MASTER_MODEL_AUDIT_INTEGRATION_TRAINING_PROMPT.md"

M = "backend/masterquo/mm/"
Q = "mql5/MasterModels/"

MODULES: list[dict] = [
    {"n": 1, "id": "align_mean", "name": "Align Mean & Cross-Chart Visibility", "version": "PMW-MM-ALIGNMEAN-1", "category": "DETERMINISTIC_INDICATOR",
     "spec": "PEPEMARKETWIZARD_AlignMean_HDC_SMC_Claude_Code_Prompt.md (Module A)", "files": [M + "align_mean.py", Q + "Indicators/PMW_AlignMean.mq5"],
     "entry": "align_mean.compute / latest; API /api/v1/mm/live (align_mean)", "inputs": "closed OHLC (any TF)", "outputs": "mean, dist points/%/ATR (INDICATOR_STATE)",
     "training": "NOT_APPLICABLE", "callers": ["mm.service (panel)", "mm.orchestrator:align_mean"], "execution_risk": "none (read-only)",
     "native_scope": "MQL5 PMW_AlignMean.mq5 (wskaźnik; bez fixture parytetu natywnego)"},
    {"n": 2, "id": "hdc", "name": "HDC (binary hypervectors, online accumulators)", "version": "PMW-MM-HDC-1", "category": "ONLINE_LEARNER",
     "spec": "PEPEMARKETWIZARD_AlignMean_HDC_SMC_Claude_Code_Prompt.md (Module B)", "files": [M + "hdc.py", "mql5/MasterModels/Include/PMW/PMW_HDC.mqh"],
     "entry": "hdc.Space/Encoder/Classifier; orchestrator:hdc", "inputs": "feature registry FS (M5)", "outputs": "class + margin + noise-floor (HDC_SIMILARITY)",
     "training": "APPLICABLE (integer accumulators)", "callers": ["mm.orchestrator:hdc", "mm.service (tylko wskaźnik artefaktu, bez inferencji)"],
     "execution_risk": "none",
     "native_scope": "PRIMITIVES_ONLY (PMW_HDC.mqh: bind/bundle/permute/hamming + akumulatory klas CPmwHDCAcc, parytet w PMW_MM_SelfTest; "
                     "bez enkodera cech i codebooków - brak inferencji natywnej)"},
    {"n": 3, "id": "smc_fvg", "name": "SMC BoS / CHOCH / IDM / FVG continuation", "version": "PMW-MM-SMCFVG-1", "category": "RULE_STRATEGY",
     "spec": "PEPEMARKETWIZARD_AlignMean_HDC_SMC_Claude_Code_Prompt.md (Module C)", "files": [M + "smc_fvg.py", "backend/masterquo/lab/context_ind/smc.py (reused)"],
     "entry": "smc_fvg.ContinuationEngine", "inputs": "closed OHLC", "outputs": "setup events entry/SL/2R (STRUCTURE_EVENT, execution_allowed=false)",
     "training": "NOT_APPLICABLE", "callers": ["mm.orchestrator:smc_fvg", "mm.service"], "execution_risk": "none (no order path imported)"},
    {"n": 4, "id": "buzoa", "name": "BUZOA Optimization Engine", "version": "PMW-MM-BUZOA-1", "category": "OPTIMIZER",
     "spec": "PEPEMARKETWIZARD_BUZOA_Event_Driven_Engine_Claude_Code_Prompt.md (Model A)", "files": [M + "buzoa.py"],
     "entry": "buzoa.buzoa / benchmark; orchestrator:buzoa_bench, kalman_calibration", "inputs": "objective adapter (train/val only)",
     "outputs": "OPTIMIZER_RESULT", "training": "NOT_APPLICABLE (optimiser)", "callers": ["mm.orchestrator"], "execution_risk": "none (never writes production config)"},
    {"n": 5, "id": "sdom", "name": "SDOm Optimization Engine", "version": None, "category": "OPTIMIZER", "spec": None, "files": [],
     "entry": None, "training": "NOT_APPLICABLE", "blocked": "SPEC_FILE_NOT_PROVIDED - nie rekonstruuję algorytmu z nazwy (brak w XXX.rar)"},
    {"n": 6, "id": "event_engine", "name": "Event-Driven Market Intelligence Engine (+ state stack, stack correlation)", "version": "PMW-MM-EVENTENGINE-1",
     "category": "TRAINABLE", "spec": "PEPEMARKETWIZARD_BUZOA_Event_Driven_Engine_Claude_Code_Prompt.md (Model B)",
     "files": [M + "events.py", M + "event_engine.py", M + "kernels/state_stack.cl", Q + "Include/PMW/PMW_StateStack.mqh"],
     "entry": "event_engine.train / Runtime", "inputs": "REAL_TICKS (tick archive) or BAR_CLOSE_EVENTS adapter", "outputs": "CLASS_PROBABILITIES (temperature-scaled)",
     "training": "APPLICABLE", "callers": ["mm.orchestrator:event_engine", "quant.adapters.EventGRU (inferencja SHADOW aktywnego artefaktu)"],
     "execution_risk": "none",
     "native_scope": "HEADER_ONLY (PMW_StateStack.mqh: stos stanów OpenCL/CPU, parytet w PMW_MM_SelfTest; brak natywnego GRU i inferencji)"},
    {"n": 7, "id": "ste_flownet", "name": "STE-FlowNet financial adaptation", "version": "PMW-MM-STEFLOW-1", "category": "TRAINABLE",
     "spec": "PEPEMARKETWIZARD_STE_FlowNet_Financial_Event_Engine_Claude_Code_Prompt.md", "files": [M + "ste_flownet.py"],
     "entry": "ste_flownet.train", "inputs": "event splits (Gaussian temporal weighting)", "outputs": "RETURN_PREDICTION (h-event mid log return)",
     "training": "APPLICABLE", "callers": ["mm.orchestrator:ste_flownet"], "execution_risk": "none"},
    {"n": 8, "id": "stfs", "name": "S3CE-Net / STFS (training-time sampling)", "version": "PMW-MM-STFS-1", "category": "TRAINABLE",
     "spec": "PEPEMARKETWIZARD_S3CE_NET_STFS_Implementation_Prompt.md", "files": [M + "stfs.py"], "entry": "stfs.STFS inside event_engine.train",
     "inputs": "event-encoder feature map [B,T,C]", "outputs": "training views + losses (no inference output)", "training": "APPLICABLE (as a training strategy)",
     "callers": ["mm.event_engine.train"], "execution_risk": "none",
     "note": "SSAM / spiking backbone of S3CE-Net nie istnieje w repo i nie ma specyfikacji - STFS wpięty za istniejącym enkoderem zdarzeń"},
    {"n": 9, "id": "quant_momentum", "name": "Quant Ultimate Momentum Pro / Quant 2nd Model / Momentum AI Fusion", "version": None, "category": "TRAINABLE",
     "spec": None, "files": [], "training": "UNKNOWN", "blocked": "SPEC_FILE_NOT_PROVIDED (brak w XXX.rar); istniejące VAMD momentum (lab/context_ind/vamd.py) to inny moduł"},
    {"n": 10, "id": "gpr", "name": "Native Gaussian Process Regression (XAUUSD)", "version": "PMW-MM-GPR-1", "category": "TRAINABLE",
     "spec": "PEPEMARKETWIZARD_Native_GPR_XAUUSD_Claude_Code_Prompt.md", "files": [M + "gpr.py", Q + "Include/PMW/PMW_GPR.mqh", Q + "Indicators/PMW_GPR_Forecast.mq5",
     Q + "Experts/PMW_GPR_ShadowEA.mq5"], "entry": "gpr.GPModel / walk_forward / calibration", "inputs": "lag-1 log return",
     "outputs": "GAUSSIAN_PREDICTIVE (latent + observed variance)", "training": "APPLICABLE (fit + LML grid)", "callers": ["mm.orchestrator:gpr", "mm.service"],
     "execution_risk": "none",
     "native_scope": "MQL5 PMW_GPR.mqh + wskaźnik + EA SHADOW (parytet: stałe hiperparametry i siatka LML w PMW_MM_SelfTest)"},
    {"n": 11, "id": "kalman", "name": "Kalman Filter Crossover", "version": "PMW-MM-KALMAN-1", "category": "RECURSIVE_FILTER",
     "spec": "PEPEMARKETWIZARD_Kalman_Filter_Crossover_MQL5_Claude_Code_Prompt.md", "files": [M + "kalman.py", Q + "Include/PMW/PMW_Kalman.mqh",
     Q + "Indicators/PMW_KalmanCross.mq5", Q + "Experts/PMW_KalmanShadowEA.mq5"], "entry": "kalman.KalmanCross", "inputs": "closed close",
     "outputs": "INDICATOR_STATE + crossover events", "training": "NOT_APPLICABLE (state estimation; Q/R calibration = separate BUZOA job)",
     "callers": ["mm.orchestrator:kalman", "mm.service"], "execution_risk": "none (EA has no order calls)",
     "native_scope": "MQL5 PMW_Kalman.mqh + wskaźnik + EA SHADOW (parytet w PMW_MM_SelfTest)"},
    {"n": 12, "id": "renko", "name": "Renko Regression Forecasting", "version": None, "category": "TRAINABLE", "spec": None, "files": [],
     "training": "UNKNOWN", "blocked": "SPEC_FILE_NOT_PROVIDED (brak w XXX.rar)"},
    {"n": 13, "id": "head_shoulders", "name": "Head & Shoulders Structure Detector", "version": None, "category": "DETERMINISTIC_INDICATOR", "spec": None,
     "files": ["backend/masterquo/analysis/chart_patterns.py (istniejący detektor formacji, w tym H&S)"], "training": "NOT_APPLICABLE",
     "blocked": "SPEC_FILE_NOT_PROVIDED - nowa wersja z regułami ATR/neckline nie powstała; istniejący detektor bez zmian"},
    {"n": 14, "id": "data_grabber", "name": "Multi-TF Data Grabber Lite", "version": None, "category": "DATA_INFRA", "spec": None,
     "files": ["backend/masterquo/forecast/export.py (istniejący eksport historii zamkniętych świec + metadane + sha256)"], "training": "NOT_APPLICABLE",
     "blocked": "SPEC_FILE_NOT_PROVIDED - rolę pełni istniejący eksport `training export` (snapshoty mm.data)"},
    {"n": 15, "id": "breakout_zones", "name": "Confirmed Swing Breakout Zones + Robust Volatility", "version": "PMW-MM-BREAKOUT-1 / PMW-MM-ROBUSTVOL-1",
     "category": "DETERMINISTIC_INDICATOR", "spec": "PEPEMARKETWIZARD_Breakout_Zones_Robust_Volatility_Claude_Code_Prompt.md",
     "files": [M + "breakout_zones.py", M + "robust_vol.py", Q + "Include/PMW/PMW_BreakoutCore.mqh", Q + "Indicators/PMW_BreakoutZones.mq5"], "entry": "breakout_zones.Engine; robust_vol.series",
     "inputs": "closed OHLC + tick volume (VWAP proxy)", "outputs": "zones, breakout events, latest-direction panel; dispersion stats",
     "training": "NOT_APPLICABLE", "callers": ["mm.orchestrator:breakout", "mm.service"], "execution_risk": "none",
     "native_scope": {"breakout_zones": "MQL5 PMW_BreakoutCore.mqh + wskaźnik (parytet 4 trybów potwierdzenia w PMW_MM_SelfTest)",
                      "robust_vol": "PYTHON_ONLY"}},
    {"n": 16, "id": "tsvp", "name": "Tick Session Volume Profile", "version": "PMW-MM-TSVP-1", "category": "VISUALIZATION",
     "spec": "PEPEMARKETWIZARD_Tick_Session_Volume_Profile_Claude_Code_Prompt.md", "files": [M + "tsvp.py", Q + "Include/PMW/PMW_TSVPCore.mqh", Q + "Indicators/PMW_TickSessionVP.mq5"],
     "entry": "tsvp.Profile", "inputs": "MT5 ticks (proxy or actual trade volume)", "outputs": "buckets, POC, render state", "training": "NOT_APPLICABLE",
     "callers": ["mm.orchestrator:tsvp"], "execution_risk": "none",
     "native_scope": "MQL5 PMW_TSVPCore.mqh + wskaźnik (parytet rdzenia w PMW_MM_SelfTest; odczyt CopyTicksRange niesprawdzony)"},
    {"n": 17, "id": "multi_indicator", "name": "Multi-Indicator Strategy Pro", "version": "PMW-MM-MULTIIND-1", "category": "RULE_STRATEGY",
     "spec": "PEPEMARKETWIZARD_Multi_Indicator_Strategy_Pro_Implementation_Prompt.md", "files": [M + "multi_indicator.py"],
     "entry": "multi_indicator.evaluate_bar / journal / ablations", "inputs": "closed OHLC (reuses scalp SAR + Wilder RSI)", "outputs": "RULE_SIGNAL with decision trace",
     "training": "NOT_APPLICABLE", "callers": ["mm.orchestrator:multi_indicator", "mm.service"], "execution_risk": "none"},
    {"n": 18, "id": "mathbench", "name": "Math Engine Fidelity Benchmark", "version": "PMW-MM-MATHBENCH-1", "category": "BENCHMARK",
     "spec": "PEPEMARKETWIZARD_Math_Fidelity_Benchmark_Claude_Code_Prompt (1).md", "files": [M + "mathbench.py", "mql5/MathFidelity/train_export_model.py", "mql5/MathFidelity/Experts/MathFidelityBenchmark_EA.mq5", "mql5/MathFidelity/Indicators/FidelityMonitor.mq5", "mql5/MathFidelity/Scripts/MathFidelity_SelfTest.mq5"],
     "entry": "mathbench.export / python_checks; MQL5 MathFidelityBenchmark_EA", "outputs": "BENCHMARK_RESULT", "training": "NOT_APPLICABLE",
     "callers": ["mm.orchestrator:mathbench"], "execution_risk": "none (no trading code)",
     "native_scope": "MQL5 MathFidelity (osobny benchmark: EA + wskaźnik + self-test)"},
    {"n": 19, "id": "chart_sync", "name": "MT5 Multi-Timeframe Chart Synchronization", "version": None, "category": "VISUALIZATION", "spec": None,
     "files": ["frontend (istniejąca opcjonalna synchronizacja wykresów w panelu, J1)"], "training": "NOT_APPLICABLE",
     "blocked": "SPEC_FILE_NOT_PROVIDED - brak natywnej synchronizacji MT5; panel bota ma własną synchronizację czasu wykresów"},
    {"n": 20, "id": "fusion_board", "name": "Evidence board (cross-model integration layer, discovered need)", "version": "PMW-MM-FUSION-1",
     "category": "DATA_INFRA", "spec": "master prompt §8.2", "files": [M + "fusion.py"], "entry": "fusion.board", "training": "NOT_APPLICABLE",
     "callers": ["mm.service", "API /api/v1/mm/live (board)"], "execution_risk": "none (no vote, no score merge)"},
]


_T = "tests/test_mm_core.py::"
# 1.46 arch (I0355): UNIT_TESTED only for a module with a declared unit test class (tests/test_arch146_w2_mm.py checks that every class
# exists in its file). The suite result itself is not read at runtime - the status says "has unit tests in the suite", nothing stronger.
UNIT_TESTS: dict[str, tuple[str, ...]] = {
    "align_mean": (_T + "TestAlignMean",), "hdc": (_T + "TestHDC",), "smc_fvg": (_T + "TestSMC",), "buzoa": (_T + "TestBUZOA",),
    "event_engine": (_T + "TestEventsSTFS",), "ste_flownet": (_T + "TestEventsSTFS",), "stfs": (_T + "TestEventsSTFS",), "gpr": (_T + "TestGPR",),
    "kalman": (_T + "TestKalman",), "breakout_zones": (_T + "TestBreakoutAndVol",), "tsvp": (_T + "TestTSVP",),
    "multi_indicator": (_T + "TestMultiIndicator",), "mathbench": (_T + "TestMathBench",),
    "fusion_board": ("tests/test_audit_146_b_mm_1.py::TestKalmanDirectionOnBoard",),
}
NATIVE_NOTE = "MQL5 nieskompilowany: brak MetaEditor/terminala w tym środowisku"


def by_id() -> dict:
    return {m["id"]: m for m in MODULES}


def _native(m: dict) -> str | None:
    """1.46 arch (I0499/I0505/I0508): native status from the module's declared scope - one MQL5 file used to mark the whole module
    IMPLEMENTED (robust_vol has no port, HDC is primitives only, the state stack header had no program including it)."""
    if not any(f.startswith("mql5/") for f in m.get("files", [])):
        return None
    sc = m.get("native_scope")
    if not sc:
        return f"NATIVE_SCOPE_UNDECLARED ({NATIVE_NOTE})"
    text = "; ".join(f"{k}: {v}" for k, v in sc.items()) if isinstance(sc, dict) else str(sc)
    return f"{text} – IMPLEMENTED ({NATIVE_NOTE})"


def merge_run(run_report: dict | None) -> list[dict]:
    """Inventory rows with evidence-based statuses from the latest orchestrator report."""
    jobs = (run_report or {}).get("jobs") or {}
    out = []
    for m in MODULES:
        row = dict(m)
        if m.get("blocked"):
            row["status"] = "BLOCKED"
            out.append(row)
            continue
        j = jobs.get(m["id"]) or {}
        tests = UNIT_TESTS.get(m["id"])
        st = ["IMPLEMENTED"] + (["UNIT_TESTED"] if tests else [])
        row["unit_tests"] = tests
        if j.get("status") == "SUCCEEDED":
            st.append("INTEGRATION_TESTED")
            if j.get("training_executed"):
                st.append("TRAINING_EXECUTED")
            if j.get("validation_passed"):
                st.append("VALIDATION_PASSED")
        row["status_chain"] = st
        row["status"] = st[-1]
        row["last_job"] = {k: j.get(k) for k in ("status", "reason", "data_kind", "training_executed", "validation_passed", "artifact_id", "gates")} if j else None
        row["native"] = _native(m)
        out.append(row)
    return out


def latest_report(inst: str) -> dict | None:
    from . import artifacts
    p = artifacts.root(inst) / "LATEST_RUN.json"
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
