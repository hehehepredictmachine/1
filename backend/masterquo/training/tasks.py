"""One registry of the training tasks of `masterquo training run` (arch146 I0131).

Until 1.46 the same task ids were written out by hand in six places (runner.TASKS + STEPS, pepe_center.PIPELINE, studio RUNNER_GROUPS,
requirements.REQUIREMENTS, the train-all list and the API check that uses runner.TASKS) and had already drifted apart (Studio timeframes,
the train-all list, the CLI accepted any name). Everything below is DATA only - this module imports nothing of the bot (no runtime, no MT5)
and has no side effects; the step functions stay in training/runner.py (runner.STEPS) and are checked against this table by the tests.

Per task (the ORDER of SPECS is the order of execution of the runner: 'activate' second to last, 'bot' last):
  id, title           - runner.TASKS (id, title) exactly as before;
  center              - (name, group) of Centrum Treningowe Pepe (pepe_center.PIPELINE) or None;
  studio              - (category, title, venv, base timeframe) of the Studio runner group (studio/registry.RUNNER_GROUPS) or None; the
                        base timeframe is part of the Studio task_key (unchanged since 1.46.0). 1.46 (I0130 / I0622): the Studio export
                        timeframes are derived (studio_export_tfs): the base timeframe first, then what the trainer reads (the task's
                        `requirements`, required + optional) - the hand lists missed required timeframes (ml, indicator_context, ...);
  requirements        - readiness of one export (training/requirements.REQUIREMENTS) under `requirements_key` ('scalp' for the A/B/C unit,
                        the key the readiness report has always shown); the ROW ORDER of that report is REQUIREMENTS_ORDER (1.46.0);
  train_all           - the skip flag of `masterquo train-all` (skip_candles / skip_ml / skip_lab) or None = never part of train-all
                        (sh_models, sh_pack, monte_carlo, master_models write live gates / pointers - never in train-all);
  instruments         - instruments the task applies to (None = every instrument); outside them the task is NOT APPLICABLE, not skipped.
"""
from __future__ import annotations

NOT_APPLICABLE_DETAIL = "nie dotyczy instrumentu"
ALWAYS = ("export", "quality", "activate", "bot")          # run for every instrument whatever the selection (never "nie wybrano w planie")
NONE_TASK = "none"                                          # `--tasks none` (train-all with every model skipped): no model task at all

SPECS: tuple[dict, ...] = (
    {"id": "export", "title": "Eksport historii z MT5"},
    {"id": "quality", "title": "Kontrola jakości danych"},
    {"id": "forecast", "title": "Prognozy świec gold_candles 5/15/30 min",
     "center": ("Prognozy świec 5/15/30 min", "Prognozy i kierunek"),
     "studio": ("TRAINABLE", "gold_candles 5/15/30 min (kierunek świecy)", ".venv_candles", "M5"),
     "requirements": {"title": "Prognozy świec gold_candles 5/15/30 min", "required": ("M5", "M30"), "optional": (),
                      "reader": "gold_candles_runtime/plan_train.py (<prefix>_M5.csv, <prefix>_M30.csv)", "recommended_rows": 20000},
     "train_all": "skip_candles"},
    {"id": "scalp_A", "title": "Scalp A: kierunek 1/3/5 min (LR/HGB/MLP)",
     "center": ("Scalp A – kierunek 1/3/5 min", "Scalp"),
     # 1.46 (I0622): scalp_A runs in .venv_candles like forecast (runner t_scalp / t_forecast: core.candles_python())
     "studio": ("TRAINABLE", "Scalp A/B: kierunek 1/3/5 min + P(TP1 przed SL); C = ocena polityki w replayu", ".venv_candles", "M1"),
     "requirements_key": "scalp",
     "requirements": {"title": "Scalp A/B/C (kierunek, P(TP1 przed SL), polityka hedge/REDUCE)", "required": ("M1",), "optional": (),
                      "reader": "gold_candles_runtime/scalp_train.py (<prefix>_M1.csv)", "recommended_rows": 60000},
     "train_all": "skip_candles"},
    {"id": "scalp_B", "title": "Scalp B: jakość setupu P(TP1 przed SL)",
     "center": ("Scalp B – jakość setupu", "Scalp")},
    {"id": "scalp_C", "title": "Scalp C: ocena polityki hedge vs REDUCE w replayu (to nie jest sieć)",
     "center": ("Scalp C – polityka hedge", "Scalp")},
    {"id": "ml", "title": "Legacy ML: Decision Tree + XGBoost (setupy S01–S12)",
     "center": ("Legacy ML – setupy S01–S12", "Strategie"),
     "studio": ("TRAINABLE", "Legacy ML: Decision Tree + XGBoost na historii setupów S01–S12", ".venv", "M5"),
     "requirements": {"title": "Legacy ML: Decision Tree + XGBoost (setupy S01–S12)", "required": ("M1", "M5", "M15", "H1", "H4", "D1"),
                      "optional": (), "reader": "masterquo/ml/offline.py load_dataset (NEED)", "recommended_rows": 60000},
     "train_all": "skip_ml"},
    {"id": "lab", "title": "Lab: LOGREG/TREE/MiniRocket/XGB/ResNet1D/SEW-SNN (+eksperymenty), strona LONG",
     "center": ("Lab – LOGREG / TREE / XGB / ResNet / SNN", "Laboratorium"),
     "studio": ("TRAINABLE", "Lab: LOGREG/TREE/MiniRocket/XGB/ResNet1D/SEW-SNN (strona LONG)", ".venv", "M1"),
     "requirements": {"title": "Lab: LOGREG/TREE/MiniRocket/XGB/ResNet1D/SEW-SNN", "required": ("M5",), "optional": (),
                      "reader": "masterquo/training/cli.py load_m5", "recommended_rows": 20000},
     "train_all": "skip_lab"},
    {"id": "indicator_context", "title": "Kontekst wskaźników (SAR + IQ/PAL): kalibracja SAR i model reakcji P(TP1 przed SL)",
     "center": ("Kontekst wskaźników SAR / IQ / PAL", "Kontekst rynku"),
     "studio": ("CALIBRATABLE", "SAR + IQ/PAL: kalibracja SAR i model reakcji P(TP1 przed SL)", ".venv", "M1"),
     "requirements": {"title": "Kontekst wskaźników SAR + IQ/PAL", "required": ("M1", "M5", "M15"), "optional": (),
                      "reader": "masterquo/extind/trainer.py", "recommended_rows": 60000},
     "train_all": "skip_candles"},
    {"id": "ml_scalp", "title": "Scalp ML: XGBoost P(dodatni wynik netto cyklu) + net_R, osobno LONG/SHORT",
     "center": ("Scalp ML – XGBoost wynik netto", "Scalp"),
     "studio": ("TRAINABLE", "Scalp ML: XGBoost P(wynik netto > 0) + net_R, osobno LONG/SHORT", ".venv", "M1"),
     "requirements": {"title": "Scalp ML: XGBoost netto cyklu", "required": ("M1",), "optional": (),
                      "reader": "masterquo/ml/scalp_task.py (_bars M1)", "recommended_rows": 60000},
     "train_all": "skip_ml"},
    {"id": "neural_scalp", "title": "Neural Scalp System: TCN M1/M5 + kontekst – P(TP1/SL/TIMEOUT) i net_R kandydata scalp",
     "center": ("Neural Scalp – sieć TCN", "Scalp"),
     "studio": ("TRAINABLE", "Neural Scalp System: TCN M1/M5 – P(TP1/SL/TIMEOUT), net_R", ".venv", "M1"),
     "requirements": {"title": "Neural Scalp System TCN", "required": ("M1", "M5", "M15", "H1"), "optional": (),
                      "reader": "masterquo/lab/nss.py", "recommended_rows": 60000},
     "train_all": "skip_lab"},
    {"id": "structure_intelligence",
     "title": "Structure Intelligence: ruch M1 h=3/5/15 (LOGREG/XGB/ResNeXt/SEW/SEW-EB/SpikingBrain/MiniRocket V2) + kontekst setupu",
     "center": ("Structure Intelligence – ruch M1", "Laboratorium"),
     "studio": ("TRAINABLE", "Structure Intelligence: ruch M1 h=3/5/15", ".venv", "M1"),
     "requirements": {"title": "Structure Intelligence (ruch M1 h=3/5/15)", "required": ("M1", "M5", "M15", "H1"), "optional": (),
                      "reader": "masterquo/lab/structure_task.py", "recommended_rows": 60000},
     "train_all": "skip_lab"},
    {"id": "flow_context", "title": "Flow context: kalibracja Heikin/S-R/StopDistance, Markov3 + koszyki, model reakcji FLOW_CONTEXT_MOVE_M1_V1",
     "center": ("Flow context – reakcja M1", "Kontekst rynku"),
     "studio": ("CALIBRATABLE", "Flow context: kalibracja + model reakcji FLOW_CONTEXT_MOVE_M1_V1", ".venv", "M1"),
     "requirements": {"title": "Flow context: Markov3 + koszyki + model reakcji", "required": ("M1",), "optional": (),
                      "reader": "masterquo/lab/flow_context/task.py (_bars M1)", "recommended_rows": 60000},
     "train_all": "skip_lab"},
    {"id": "context_indicators", "title": "Kontekst VAMD / FD / Pullback+SMC: kalibracja dev (<=24 konfiguracje), model CONTEXT_MOVE_M5_V1 + ablacje",
     "center": ("Kontekst VAMD / FD / SMC", "Kontekst rynku"),
     "studio": ("CALIBRATABLE", "VAMD / FD / Pullback+SMC: kalibracja + CONTEXT_MOVE_M5_V1", ".venv", "M5"),
     "requirements": {"title": "Kontekst VAMD / FD / Pullback+SMC", "required": ("M5",), "optional": (),
                      "reader": "masterquo/lab/context_ind/task.py (_bars M5)", "recommended_rows": 20000},
     "train_all": "skip_lab"},
    {"id": "sh_models", "title": "SCALPING/HEDGING: replay strategii + model zdarzenia P(TP2 przed SL) + raport walidacji",
     "center": ("SCALPING / HEDGING – model zdarzenia", "Strategie"),
     "studio": ("TRAINABLE", "SCALPING/HEDGING: model zdarzenia P(TP2 przed SL) + replay", ".venv", "M1"),
     "requirements": {"title": "SCALPING/HEDGING: replay + P(TP2 przed SL) + walidacja", "required": ("M1",), "optional": ("M5", "M15", "H1"),
                      "ticks": "opcjonalne – rozstrzygają kolejność TP/SL w jednej świecy",
                      "reader": "masterquo/sh/replay.py load_dataset (M5/M15/H1 składane z M1, gdy brak)", "recommended_rows": 60000}},
    {"id": "sh_pack", "title": "Pakiet 20 strategii SC/HG: replay walk-forward (te same detektory, solver i polityki hedge) + werdykt per wariant",
     "center": ("Pakiet 20 strategii SC / HG", "Strategie"),
     "studio": ("SIMULATION", "Pakiet 20 strategii SC/HG: replay walk-forward i werdykt per wariant (bez treningu parametrów)", ".venv",
                "M1"),
     "requirements": {"title": "Pakiet 20 strategii SC/HG: replay walk-forward", "required": ("M1",), "optional": ("M3", "M5", "M15", "H1"),
                      "ticks": "opcjonalne – bez ticków kolejność TP/SL w jednej świecy = STOP_FIRST", "reader": "masterquo/sh/pack/replay.py load",
                      "recommended_rows": 120000},
     # arch146 I0073 / I0704: the pack is defined for XAUUSD only (pip definition PMW_XAU_PRICE_0_10_V1) - BTC is not applicable
     "instruments": ("XAUUSD",), "scope_reason": "pakiet 20 strategii jest zdefiniowany dla XAUUSD (definicja pipsa PMW_XAU_PRICE_0_10_V1)"},
    {"id": "monte_carlo", "title": "Monte Carlo ścieżek: walidacja wariantów IID/BLOCK/REGIME, P(TP przed SL) i kalibracja poza próbą",
     "center": ("Monte Carlo ścieżek", "Strategie"),
     "studio": ("SIMULATION", "Monte Carlo ścieżek: walidacja wariantów IID/BLOCK/REGIME", ".venv", "M1"),
     "requirements": {"title": "Monte Carlo ścieżek (walidacja P(TP przed SL))", "required": ("M1",), "optional": ("M5", "M15"),
                      "ticks": "opcjonalne – kolejność TP/SL w jednej świecy", "reader": "masterquo/montecarlo/validate.py",
                      "recommended_rows": 40000}},
    {"id": "master_models", "title": "Master models (XXX.rar): HDC/GPR/event engine+STFS/STE-FlowNet + ewaluacja Kalman/Breakout/SMC/Multi-Indicator/TSVP/BUZOA",
     "center": ("Master models – HDC / GPR / STE", "Laboratorium"),
     "studio": ("TRAINABLE", "Master models: HDC/GPR/event engine/STE-FlowNet + ewaluacja deterministycznych", ".venv", "M5"),
     "requirements": {"title": "Master models (HDC/GPR/event engine/STE-FlowNet + ewaluacje)", "required": ("M1", "M5"), "optional": ("M15", "M30"),
                      "reader": "masterquo/mm/data.py open_snapshot (M1,M5,M15,M30)", "recommended_rows": 60000}},
    {"id": "activate", "title": "Aktywacja w rejestrach + zgodność loaderów"},
    {"id": "bot", "title": "Przekazanie do działającego bota (przeładowanie)"},
)
BY_ID = {s["id"]: s for s in SPECS}


def runner_tasks() -> tuple[tuple[str, str], ...]:
    """runner.TASKS: (id, title) in the order of execution."""
    return tuple((s["id"], s["title"]) for s in SPECS)


def center_pipeline() -> tuple[tuple[str, str, str], ...]:
    """pepe_center.PIPELINE: (id, name, group) of every model task of the main training."""
    return tuple((s["id"], *s["center"]) for s in SPECS if s.get("center"))


def studio_export_tfs(task_id: str) -> list[str]:
    """1.46 (I0130 / I0622): the Studio export timeframes of a runner group = its base timeframe (first - part of task_key, so existing
    Studio tasks and packages keep their keys) + what its trainer reads (`requirements`, required + optional - taken from the trainers'
    code) instead of a hand list (ml / indicator_context / neural_scalp / structure_intelligence / master_models got an export without
    required timeframes, scalp_A two it never reads)."""
    s = BY_ID[task_id]
    rq = s.get("requirements") or {}
    out = [s["studio"][3]]
    for tf in (*rq.get("required", ()), *rq.get("optional", ())):
        if tf not in out:
            out.append(tf)
    return out


def studio_runner_groups() -> dict[str, tuple]:
    """studio/registry.RUNNER_GROUPS: id -> (category, title, venv, Studio export timeframes - studio_export_tfs, base timeframe first)."""
    return {s["id"]: (s["studio"][0], s["studio"][1], s["studio"][2], studio_export_tfs(s["id"])) for s in SPECS if s.get("studio")}


# Row order of the readiness report (check_dataset: /api/v1 data readiness, export report) exactly as in 1.46.0 - it differs from the runner
# order (master_models before monte_carlo). Only the ORDER lives here; a readiness key missing from this tuple is appended in runner order.
REQUIREMENTS_ORDER: tuple[str, ...] = ("forecast", "scalp", "ml", "lab", "indicator_context", "ml_scalp", "neural_scalp", "structure_intelligence",
                                       "flow_context", "context_indicators", "sh_models", "sh_pack", "master_models", "monte_carlo")


def requirements() -> dict[str, dict]:
    """training/requirements.REQUIREMENTS: readiness key ('scalp' for the A/B/C unit) -> required / optional data of one export, in the row
    order of the readiness report (REQUIREMENTS_ORDER, as in 1.46.0)."""
    rq = {s.get("requirements_key", s["id"]): dict(s["requirements"]) for s in SPECS if s.get("requirements")}
    rank = {k: i for i, k in enumerate(REQUIREMENTS_ORDER)}
    return dict(sorted(rq.items(), key=lambda kv: rank.get(kv[0], len(rank))))     # stable: unknown keys keep the runner order at the end


def requirements_kind(task_id: str) -> str | None:
    """Readiness key of a task id (alias on input only: scalp_A / scalp_B / scalp_C -> 'scalp'); the reports keep the readiness key."""
    if task_id in ("scalp_B", "scalp_C"):
        task_id = "scalp_A"
    s = BY_ID.get(task_id)
    return s.get("requirements_key", task_id) if s and s.get("requirements") else None


def train_all_tasks(skip: dict | None = None) -> list[str]:
    """Tasks of `masterquo train-all` in runner order; `skip` maps skip_candles / skip_ml / skip_lab -> bool."""
    skip = skip or {}
    return [s["id"] for s in SPECS if s.get("train_all") and not skip.get(s["train_all"])]


def applies_to(task_id: str, inst: str) -> bool:
    s = BY_ID.get(task_id) or {}
    return s.get("instruments") is None or inst in s["instruments"]


def scope_reason(task_id: str) -> str | None:
    """Why the task does not apply to some instruments (None = applies to every instrument)."""
    return (BY_ID.get(task_id) or {}).get("scope_reason")


def not_applicable_detail(task_id: str) -> str:
    why = scope_reason(task_id)
    return f"{NOT_APPLICABLE_DETAIL}: {why}" if why else NOT_APPLICABLE_DETAIL


def validate(names) -> list[str]:
    """Task names given to `training run --tasks` / build_plan. Unknown names raise ValueError('BAD_TASKS: ...') - a typo used to run an
    export + bot reload without any training. 'none' (train-all with every model skipped) means: no model task; export, quality, activation
    and bot reload still run as before."""
    names = [str(n).strip() for n in names if str(n).strip()]
    bad = [n for n in names if n != NONE_TASK and n not in BY_ID]
    if bad:
        raise ValueError(f"BAD_TASKS: nieznane zadania {', '.join(bad)} – dozwolone: {', '.join(BY_ID)} (albo '{NONE_TASK}')")
    return [n for n in names if n != NONE_TASK]
