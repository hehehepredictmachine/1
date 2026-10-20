"""The shared training pipeline: plan -> per instrument (XAUUSD first, then BTC): export -> quality -> gold_candles forecasts ->
scalp A/B/C -> legacy ML DT/XGB -> lab families -> activation (atomic, only admitted models) -> bot reload -> report.

Every model-producing task runs in its own process (thread limits, lower priority, timeout, cancel) and reads the EXPLICIT
dataset directory of this run (never "the latest export"). Nothing here sends, modifies or closes orders; the export uses its
own MT5 connection wrapped so that order functions raise.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .. import paths
from . import core
from .core import Run, now

TASKS = (("export", "Eksport historii z MT5"), ("quality", "Kontrola jakości danych"), ("forecast", "Prognozy świec gold_candles 5/15/30 min"),
         ("scalp_A", "Scalp A: kierunek 1/3/5 min (LR/HGB/MLP)"), ("scalp_B", "Scalp B: jakość setupu P(TP1 przed SL)"),
         ("scalp_C", "Scalp C: ocena polityki hedge vs REDUCE w replayu (to nie jest sieć)"), ("ml", "Legacy ML: Decision Tree + XGBoost (setupy S01–S12)"),
         ("lab", "Lab: LOGREG/TREE/MiniRocket/XGB/ResNet1D/SEW-SNN (+eksperymenty), strona LONG"),
         ("indicator_context", "Kontekst wskaźników (SAR + IQ/PAL): kalibracja SAR i model reakcji P(TP1 przed SL)"),
         ("ml_scalp", "Scalp ML: XGBoost P(dodatni wynik netto cyklu) + net_R, osobno LONG/SHORT"),
         ("neural_scalp", "Neural Scalp System: TCN M1/M5 + kontekst – P(TP1/SL/TIMEOUT) i net_R kandydata scalp"),
         ("structure_intelligence", "Structure Intelligence: ruch M1 h=3/5/15 (LOGREG/XGB/ResNeXt/SEW/SEW-EB/SpikingBrain/MiniRocket V2) + kontekst setupu"),
         ("activate", "Aktywacja w rejestrach + zgodność loaderów"),
         ("bot", "Przekazanie do działającego bota (przeładowanie)"))


def build_plan(*, instruments: list[str], profile: str, symbols: dict, commissions: dict, months: int | None, synthetic: bool,
               tasks: list[str] | None = None, include_approx: bool = True, lab_bars: int | None = None, threads: int | None = None,
               ml_days: int | None = None, min_events: int | None = None, origin: str = "menu") -> tuple[dict, list[dict]]:
    prof = dict(core.profiles()[profile])
    plan = {"run_id": core.new_run_id(), "profile": profile, "profile_params": prof, "instruments": instruments, "symbols": symbols,
            "commissions": commissions, "months": int(months or prof["months"]), "synthetic": synthetic, "include_approx": include_approx,
            "lab_bars": int(lab_bars or prof["lab_bars"]), "threads": int(threads or prof["threads"]), "ml_days": int(ml_days or prof["ml_days"]),
            "lab_min_events": int(min_events or prof["lab_min_events"]), "activate": bool(prof["activate"]) and not synthetic,
            "requested_tasks": tasks or [k for k, _ in TASKS], "origin": origin, "frozen_at": now(),
            "rules": {"split": "chronologiczny: rozwój → kalibracja → holdout (holdout zarezerwowany przed wyborem modelu)",
                      "walk_forward": "foldy chronologiczne z purge/embargo (każdy trener)", "refit": "brak refitu dziedziczącego status – zapisywany jest oceniany model",
                      "approx": "próbki APPROX tylko w tym zadaniu ML (config bota bez zmian); model APPROX nie zostaje championem",
                      "activation": "tylko modele dopuszczone (walidacja SHADOW) + zgodność loadera; odrzucone = do badań, nie zastępują aktywnego"}}
    tasks_out = []
    for inst in instruments:
        for kind, title in TASKS:
            t = core.task(f"{inst}:{kind}", inst, kind, title)
            if kind not in plan["requested_tasks"] and kind not in ("export", "quality", "activate", "bot"):
                t.update(execution="POMINIETE", detail="nie wybrano w planie")
            tasks_out.append(t)
    return plan, tasks_out


# ------------------------------------------------------------------ helpers
def _json(p: Path) -> dict | None:
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _dataset(run: Run, inst: str) -> Path:
    return paths.data_dir() / "training" / "datasets" / inst / run.run_id


def _skip(run: Run, tid: str, why: str, quality: str = "NIE_DOTYCZY") -> None:
    run.set(tid, execution="POMINIETE", quality=quality, detail=why, reasons=[why])
    run.event(f"{tid}: pominięte – {why}")


def _fail(run: Run, tid: str, why: str) -> None:
    run.set(tid, execution="BLAD_TECHNICZNY", detail=why[-600:])
    run.event(f"{tid}: BŁĄD – {why[-200:]}")


# ------------------------------------------------------------------ tasks
def t_export(run: Run, inst: str) -> None:
    tid, plan = f"{inst}:export", run.state["plan"]
    sym = plan["symbols"].get(inst)
    if not sym:
        return _skip(run, tid, f"brak wybranego symbolu brokera dla {inst} – wybierz go w kreatorze (Diagnostyka pokaże kandydatów)")
    out = _dataset(run, inst)
    cmd = [core.bot_python(), "-m", "masterquo", "training", "export", "--instrument", inst, "--symbol", sym, "--months", str(plan["months"]),
           "--out", str(out), "--tfs", ",".join(plan["profile_params"]["timeframes"])] + (["--synthetic"] if plan["synthetic"] else [])
    rc, tail = core.run_child(run, tid, cmd, core.child_env(plan, inst), 6 * 3600, f"{inst}_export")
    if rc is None:
        return run.set(tid, execution="ANULOWANE")
    meta = _json(out / "source_metadata.json")
    if rc != 0 or not meta:
        return _fail(run, tid, f"eksport zakończony kodem {rc}: {tail}")
    if meta.get("instrument") != inst or meta.get("symbol") != sym:
        return _fail(run, tid, f"metadane eksportu {meta.get('instrument')}/{meta.get('symbol')} ≠ {inst}/{sym}")
    run.set(tid, execution="UKONCZONE", quality="TEST_TECHNICZNY" if meta["data_kind"] != "REAL_USER_DATA" else "NIE_DOTYCZY",
            integration="ZAPISANY_DO_BADAN", detail=f"{meta['symbol']} {meta['range_utc'][0]} – {meta['range_utc'][1]}, prowizja "
            f"{(meta.get('costs') or {}).get('commission_per_lot_side', 'nieznana')} ({(meta.get('costs') or {}).get('source')})",
            dataset_dir=str(out), dataset_id=meta.get("dataset_id"), data_kind=meta["data_kind"],
            received_range_utc=meta["range_utc"], requested_months=plan["months"], quote_currency=meta.get("quote_currency"),
            files_sha256=meta.get("files_sha256"), artifacts=[str(out / "source_metadata.json")])


def t_quality(run: Run, inst: str) -> None:
    tid = f"{inst}:quality"
    ex = run.task(f"{inst}:export")
    if ex["execution"] != "UKONCZONE":
        return _skip(run, tid, "brak danych (eksport nie ukończony)")
    dq = _json(Path(ex["dataset_dir"]) / "DATA_QUALITY_REPORT.json") or {}
    problems, warn = [], []
    for tf, v in (dq.get("timeframes") or {}).items():
        if not v.get("rows"):
            problems.append(f"{tf}: brak świec")
        if v.get("conflicting_revisions_count"):
            warn.append(f"{tf}: {v['conflicting_revisions_count']} rewizji OHLC usuniętych")
        if v.get("invalid_geometry_count"):
            warn.append(f"{tf}: {v['invalid_geometry_count']} świec z błędną geometrią usuniętych")
        if (v.get("gaps") or {}).get("other"):
            warn.append(f"{tf}: {v['gaps']['other']} nietypowych luk")
        if v.get("dst_ambiguous_rows"):
            warn.append(f"{tf}: {v['dst_ambiguous_rows']} świec w niejednoznacznej godzinie DST")
    suff = (dq.get("sufficiency") or {}).get("status")
    if suff and suff != "OK":
        warn.append(f"krótka historia: {suff}")
    q = "ODRZUCONY" if problems else ("TEST_TECHNICZNY" if ex.get("data_kind") != "REAL_USER_DATA" else "NIE_DOTYCZY")
    run.set(tid, execution="UKONCZONE", quality=q, detail="; ".join(problems + warn) or "bez uwag (duplikaty/geometria/luki/DST sprawdzone)",
            reasons=problems + warn, artifacts=[str(Path(ex["dataset_dir"]) / "DATA_QUALITY_REPORT.json")])


def _ready(run: Run, inst: str, tid: str, need_candles: bool = False) -> Path | None:
    ex, qa = run.task(f"{inst}:export"), run.task(f"{inst}:quality")
    if ex["execution"] != "UKONCZONE":
        _skip(run, tid, "brak danych (eksport nie ukończony)")
        return None
    if qa["quality"] == "ODRZUCONY":
        _skip(run, tid, "dane odrzucone przez kontrolę jakości: " + (qa.get("detail") or ""))
        return None
    if need_candles and not core.candles_python():
        _skip(run, tid, "brak środowiska .venv_candles – uruchom INSTALUJ_TRENING.bat")
        return None
    return Path(ex["dataset_dir"])


def _kind(run: Run) -> str:
    return "SYNTHETIC_TEST" if run.state["plan"]["synthetic"] else "REAL_USER_DATA"


def t_forecast(run: Run, inst: str) -> None:
    tid, plan = f"{inst}:forecast", run.state["plan"]
    ds = _ready(run, inst, tid, True)
    if ds is None:
        return
    import mq_instruments
    out = mq_instruments.root("forecast", inst) / "runs" / f"{run.run_id}"
    cmd = [core.candles_python(), "-m", "gold_candles_runtime.plan_train", "--instrument", inst, "--data-dir", str(ds), "--out", str(out),
           "--trees", str(plan["profile_params"]["forecast_trees"]), "--data-kind", _kind(run), "--no-activate"]
    rc, tail = core.run_child(run, tid, cmd, core.child_env(plan, inst), plan["profile_params"]["task_timeout_minutes"] * 60, f"{inst}_forecast")
    if rc is None:
        return run.set(tid, execution="ANULOWANE")
    val = _json(out / "forecast_validation.json")
    if rc == 4 and val:
        return run.set(tid, execution="UKONCZONE", quality="BRAK_PRZESLANEK", detail="; ".join(val.get("reasons") or []), run_dir=str(out))
    if rc != 0 or not val:
        return _fail(run, tid, f"plan_train kod {rc}: {tail}")
    st = val["overall_status"]
    q = {"TRAINED_SHADOW": "ZWALIDOWANY_SHADOW", "PARTIAL_VALIDATION": "CZESCIOWO_ZWALIDOWANY", "REJECTED": "ODRZUCONY",
         "INSUFFICIENT_DATA": "BRAK_PRZESLANEK"}.get(st, "NIEZWALIDOWANY")
    if plan["synthetic"]:
        q = "TEST_TECHNICZNY"
    rt = val.get("runtime_check") or {}
    run.set(tid, execution="UKONCZONE", quality=q, integration="ZAPISANY_DO_BADAN", model_id=val["run_id"], run_dir=str(out),
            detail=f"{st}; horyzonty {json.dumps({k: v['status'] for k, v in val['horizon_status'].items()})}; loader {rt.get('status')} "
                   f"max|Δp| {(rt.get('parity') or {}).get('max_abs_prob_diff')}",
            parity=rt, artifacts=[str(out / "forecast_model.json"), str(out / "forecast_validation.json")],
            unit={"task": "rozkład kierunku zamknięcia (DOWN/FLAT/UP) + kwantyle", "tf": "M5 (+kontekst M30)", "horizons": "5/15/30 min", "side": "nie dotyczy"})


def t_scalp(run: Run, inst: str) -> None:
    plan = run.state["plan"]
    ids = [f"{inst}:scalp_{x}" for x in "ABC"]
    if all(run.task(i)["execution"] == "POMINIETE" and run.task(i).get("detail") == "nie wybrano w planie" for i in ids):
        return
    ds = _ready(run, inst, ids[0], True)
    if ds is None:
        for i in ids[1:]:
            _skip(run, i, run.task(ids[0])["detail"])
        return
    meta = _json(ds / "source_metadata.json") or {}
    com = plan["commissions"].get(inst)
    if com is None and (meta.get("costs") or {}).get("commission_per_lot_side") is None and inst != "XAUUSD":
        for i in ids:
            _skip(run, i, f"nieznana prowizja {inst} (brak transakcji w historii) – podaj ją w kreatorze; bez niej etykiety po kosztach byłyby fikcją")
        return
    cmd = [core.candles_python(), "-m", "gold_candles_runtime.scalp_train", "--instrument", inst, "--history", str(ds), "--data-kind", _kind(run),
           "--no-activate"] + (["--commission-per-lot-side", str(com)] if com is not None else []) + (["--small-test"] if plan["synthetic"] else [])
    rc, tail = core.run_child(run, ids[0], cmd, core.child_env(plan, inst), plan["profile_params"]["task_timeout_minutes"] * 60, f"{inst}_scalp")
    if rc is None:
        for i in ids:
            run.set(i, execution="ANULOWANE")
        return
    import mq_instruments
    reg = _json(mq_instruments.root("scalp", inst) / "registry.json") or {}
    entry = max((e for e in (reg.get("runs") or {}).values() if e.get("dataset_id") == meta.get("dataset_id")),
                key=lambda e: e.get("created_at_utc") or "", default=None)
    if rc != 0 or not entry:
        for i in ids:
            _fail(run, i, f"scalp_train kod {rc}: {tail}")
        return
    rep = _json(Path(entry["run_dir"]) / "report.json") or {}
    qa = {"TRAINED_SHADOW": "ZWALIDOWANY_SHADOW", "PARTIAL_VALIDATION": "CZESCIOWO_ZWALIDOWANY", "REJECTED": "ODRZUCONY",
          "INSUFFICIENT_DATA": "BRAK_PRZESLANEK", "SHADOW_UNVALIDATED": "NIEZWALIDOWANY"}
    tb, tc = entry.get("task_b_status"), entry.get("task_c_status")
    common = {"model_id": entry["run_id"], "run_dir": entry["run_dir"], "integration": "ZAPISANY_DO_BADAN"}
    syn = plan["synthetic"]
    run.set(ids[0], execution="UKONCZONE", quality="TEST_TECHNICZNY" if syn else qa.get(entry["task_a_status"], "NIEZWALIDOWANY"),
            detail=f"{entry['task_a_status']} {json.dumps(entry.get('horizon_status'))}; koszty {entry['costs']['commission_per_lot_side']} "
                   f"({entry['costs']['commission_source']}); loader {json.dumps((rep.get('runtime_check') or {}).get('horizons'))}",
            parity=rep.get("runtime_check"), artifacts=[str(Path(entry["run_dir"]) / "report.json")], **common,
            unit={"task": "kierunek M1 po kosztach", "tf": "M1", "horizons": "1/3/5 min", "side": "oba (klasy DOWN/FLAT/UP)"})
    run.set(ids[1], execution="UKONCZONE", quality="TEST_TECHNICZNY" if syn else ("BRAK_PRZESLANEK" if tb == "INSUFFICIENT_DATA" else
                                                                                 "ZWALIDOWANY_SHADOW" if tb and "VALID" in tb and "UN" not in tb else
                                                                                 "ODRZUCONY" if tb and "REJECT" in tb else "NIEZWALIDOWANY"),
            detail=f"{tb}: {(rep.get('task_B') or {}).get('reason') or ''}", **common,
            unit={"task": "P(TP1 przed SL) setupu Range→Sweep→Retest", "tf": "M1/M5", "horizons": "do 30 min", "side": "BUY i SELL w jednym modelu (cecha kierunku)"})
    run.set(ids[2], execution="UKONCZONE", quality="TEST_TECHNICZNY" if syn else ("BRAK_PRZESLANEK" if tc == "INSUFFICIENT_DATA" else
                                                                                 "NIEZWALIDOWANY"),
            detail=f"{tc}: ocena polityki w replayu OHLC (bez ticków), nie sieć neuronowa. {(rep.get('task_C') or {}).get('reason') or ''}",
            model_id=entry["run_id"], integration="NIEZAPISANY", unit={"task": "porównanie polityk HEDGE_PARTIAL vs REDUCE", "tf": "M1", "side": "oba"})


def t_ml(run: Run, inst: str) -> None:
    tid, plan = f"{inst}:ml", run.state["plan"]
    ds = _ready(run, inst, tid)
    if ds is None:
        return
    ram = core.free_ram_mb()
    if ram is not None and ram < plan["profile_params"]["min_free_ram_mb"]:
        return _skip(run, tid, f"za mało wolnej pamięci RAM ({ram} MB < {plan['profile_params']['min_free_ram_mb']} MB)")
    out = run.dir / f"{inst}_ml_result.json"
    com = plan["commissions"].get(inst)
    cmd = [core.bot_python(), "-m", "masterquo", "training", "ml-offline", "--instrument", inst, "--dataset", str(ds), "--days", str(plan["ml_days"]),
           "--threads", str(plan["threads"]), "--out", str(out)] + (["--include-approx"] if plan["include_approx"] else []) + \
        (["--commission", str(com)] if com is not None else [])
    rc, tail = core.run_child(run, tid, cmd, core.child_env(plan, inst), plan["profile_params"]["task_timeout_minutes"] * 60, f"{inst}_ml")
    if rc is None:
        return run.set(tid, execution="ANULOWANE")
    res = _json(out)
    if not res:
        return _fail(run, tid, f"ml-offline kod {rc}: {tail}")
    st = res.get("status")
    if st == "INSUFFICIENT_DATA":
        return run.set(tid, execution="UKONCZONE", quality="BRAK_PRZESLANEK", detail=res.get("reason"), result=res)
    if st != "DONE":
        return _fail(run, tid, f"{st}: {res.get('reason')}")
    passed = [m for m, d in res["models"].items() if d["passed_rules"]]
    q = "TEST_TECHNICZNY" if plan["synthetic"] else ("NIEZWALIDOWANY" if res["role"] == "RESEARCH_APPROX" and passed else
                                                   "ZWALIDOWANY_SHADOW" if passed else "ODRZUCONY")
    integ = "AKTYWNY_W_REJESTRZE" if res.get("champion") in passed and res["role"] == "ELIGIBLE_FOR_CHAMPION" else "ZAPISANY_DO_BADAN"
    run.set(tid, execution="UKONCZONE", quality=q, integration=integ, model_id=",".join(res["models"]), result={k: res[k] for k in ("counts", "role", "champion", "models", "costs")},
            detail=f"{res['role']}: " + ", ".join(f"{d['family']} {'spełnia reguły' if d['passed_rules'] else 'odrzucony'}" for d in res["models"].values())
                   + f"; etykiet {res['counts']['labeled']}",
            unit={"task": "P(setup S01–S12 osiąga cel netto przed SL)", "tf": "TF setupu (M5–H1)", "side": "oba (cecha kierunku setupu)"})


def t_lab(run: Run, inst: str) -> None:
    tid, plan = f"{inst}:lab", run.state["plan"]
    ds = _ready(run, inst, tid)
    if ds is None:
        return
    ram = core.free_ram_mb()
    if ram is not None and ram < plan["profile_params"]["min_free_ram_mb"]:
        return _skip(run, tid, f"za mało wolnej pamięci RAM ({ram} MB)")
    out = run.dir / f"{inst}_lab_result.json"
    pp = plan["profile_params"]
    cmd = [core.bot_python(), "-m", "masterquo", "training", "lab-offline", "--instrument", inst, "--dataset", str(ds), "--bars", str(plan["lab_bars"]),
           "--families", ",".join(pp["lab_families"]), "--experiments", ",".join(pp["lab_experiments"]), "--min-events", str(plan["lab_min_events"]),
           "--out", str(out)]
    rc, tail = core.run_child(run, tid, cmd, core.child_env(plan, inst), pp["task_timeout_minutes"] * 60, f"{inst}_lab")
    if rc is None:
        return run.set(tid, execution="ANULOWANE")
    res = _json(out)
    if not res:
        return _fail(run, tid, f"lab-offline kod {rc}: {tail}")
    job = res["job"]
    if job.get("status") == "FAILED":
        return _fail(run, tid, job.get("error") or "lab FAILED")
    req = job.get("requested_families") or []
    saved = res.get("models") or []
    verdict = job.get("verdict")
    q = ("TEST_TECHNICZNY" if plan["synthetic"] else "BRAK_PRZESLANEK" if verdict == "INSUFFICIENT_EVIDENCE" else
         "ZWALIDOWANY_SHADOW" if verdict == "HOLDOUT_PASSED" else "ODRZUCONY" if verdict == "NO_VALIDATED_EDGE" else "NIEZWALIDOWANY")
    run.set(tid, execution="UKONCZONE", quality=q, integration="ZAPISANY_DO_BADAN" if saved else "NIEZAPISANY",
            model_id=",".join(m["model_id"] for m in saved), lab_models=saved, missing=job.get("missing"),
            detail=f"werdykt {verdict}; zapisano {len(saved)}/{len(req)} rodzin" + (f"; brak: {json.dumps(job.get('missing'), ensure_ascii=False)}" if job.get("missing") else ""),
            artifacts=[job.get("result_file")],
            unit={"task": "potrójna bariera TP 1.5×ATR / SL 1.0×ATR", "tf": "M5", "horizons": "12 świec (60 min)", "side": "LONG (tylko długie)"})


def t_indicator_context(run: Run, inst: str) -> None:
    """PMW-UPD-02: SAR calibration + reaction models (BASE / +SAR / +IQ / PAL blocked) on the same scalp replay cycles."""
    tid, plan = f"{inst}:indicator_context", run.state["plan"]
    ds = _ready(run, inst, tid)
    if ds is None:
        return
    out = run.dir / f"{inst}_indicator_context.json"
    com = plan["commissions"].get(inst)
    cmd = [core.bot_python(), "-m", "masterquo", "indicator-context", "train", "--asset", inst, "--dataset", str(ds), "--out", str(out)] + \
        (["--allow-synthetic-fixture"] if plan["synthetic"] else []) + (["--commission", str(com)] if com is not None else [])
    rc, tail = core.run_child(run, tid, cmd, core.child_env(plan, inst), plan["profile_params"]["task_timeout_minutes"] * 60, f"{inst}_indicator_context")
    if rc is None:
        return run.set(tid, execution="ANULOWANE")
    rep = _json(out)
    if rc == 2 and "COMMISSION_UNKNOWN" in tail:
        return _skip(run, tid, f"nieznana prowizja {inst} – podaj ją w kreatorze")
    if not rep:
        return _fail(run, tid, f"indicator-context kod {rc}: {tail}")
    vs = {k: v.get("status") for k, v in (rep.get("variants") or {}).items()}
    q = ("TEST_TECHNICZNY" if plan["synthetic"] else "BRAK_PRZESLANEK" if rep["status"] != "EVALUATED" else
         "NIEZWALIDOWANY")                                   # one holdout: edge stays NO_VALIDATED_EDGE until an independent evaluation
    run.set(tid, execution="UKONCZONE", quality=q, integration="ZAPISANY_DO_BADAN" if rep["status"] == "EVALUATED" else "NIEZAPISANY",
            model_id=rep.get("run_id"), detail=f"{rep['status']}; cykli {rep.get('cycles')}; warianty {json.dumps(vs, ensure_ascii=False)}; "
            f"SAR wybrany na TUNE {((rep.get('sar_calibration') or {}).get('selected'))}; edge {rep.get('edge_status')}",
            unit={"task": "P(TP1 przed SL) w zamrożonej polityce scalp", "tf": "M1 (+SAR M5/M15)", "horizons": "do wyjścia cyklu", "side": "BUY+SELL"})


def t_ml_scalp(run: Run, inst: str) -> None:
    """PMW-UPD-03 SCALP_NET_PROFIT_MARKET_V1: walk-forward + frozen bundle + one holdout evaluation; never selected automatically."""
    tid, plan = f"{inst}:ml_scalp", run.state["plan"]
    ds = _ready(run, inst, tid)
    if ds is None:
        return
    out = run.dir / f"{inst}_ml_scalp.json"
    com = plan["commissions"].get(inst)
    cmd = [core.bot_python(), "-m", "masterquo", "ml-scalp", "train", "--asset", inst, "--dataset", str(ds), "--out", str(out), "--activate", "none"] + \
        (["--allow-synthetic-fixture"] if plan["synthetic"] else []) + (["--commission", str(com)] if com is not None else [])
    rc, tail = core.run_child(run, tid, cmd, core.child_env(plan, inst), plan["profile_params"]["task_timeout_minutes"] * 60, f"{inst}_ml_scalp")
    if rc is None:
        return run.set(tid, execution="ANULOWANE")
    rep = _json(out)
    if rc == 2 and "COSTS_UNKNOWN" in tail:
        return _skip(run, tid, f"nieznana prowizja {inst} – podaj ją w kreatorze")
    if not rep:
        return _fail(run, tid, f"ml-scalp kod {rc}: {tail}")
    sides = {k: v.get("status") for k, v in rep["sides"].items()}
    q = ("TEST_TECHNICZNY" if plan["synthetic"] else "ZWALIDOWANY_SHADOW" if "HOLDOUT_PASSED" in sides.values() else
         "BRAK_PRZESLANEK" if all(v in (None, "INSUFFICIENT_EVIDENCE") for v in sides.values()) else "ODRZUCONY")
    run.set(tid, execution="UKONCZONE", quality=q, integration="ZAPISANY_DO_BADAN" if rep["status"] == "EVALUATED" else "NIEZAPISANY",
            model_id=rep["run_id"], detail=f"{rep['status']}; kandydatów {rep['candidates']}; strony {json.dumps(sides)}; wybór roli ręcznie (OBSERVE/SHADOW_GATE)",
            unit={"task": "P(net_R cyklu > 0) + E[net_R]", "tf": "M1/M5 (+M15/M30/H1)", "horizons": "pełny cykl (max hold profilu)", "side": "LONG i SHORT osobno"})


def t_neural_scalp(run: Run, inst: str) -> None:
    """PMW-UPD-04 CAUSAL_MTF_TCN_V1 / SCALP_SETUP_MARKET_V1: walk-forward, frozen ensemble, one holdout evaluation; never selected."""
    tid, plan = f"{inst}:neural_scalp", run.state["plan"]
    ds = _ready(run, inst, tid)
    if ds is None:
        return
    out = run.dir / f"{inst}_neural_scalp.json"
    com = plan["commissions"].get(inst)
    cmd = [core.bot_python(), "-m", "masterquo", "neural-scalp", "train", "--asset", inst, "--dataset", str(ds), "--out", str(out), "--activate", "none"] + \
        (["--allow-synthetic-fixture"] if plan["synthetic"] else []) + (["--commission", str(com)] if com is not None else [])
    rc, tail = core.run_child(run, tid, cmd, core.child_env(plan, inst), plan["profile_params"]["task_timeout_minutes"] * 60, f"{inst}_neural_scalp")
    if rc is None:
        return run.set(tid, execution="ANULOWANE")
    rep = _json(out)
    if rc == 2 and "COSTS_UNKNOWN" in tail:
        return _skip(run, tid, f"nieznana prowizja {inst} – podaj ją w kreatorze")
    if not rep:
        return _fail(run, tid, f"neural-scalp kod {rc}: {tail}")
    sides = {k: v.get("status") for k, v in rep.get("sides", {}).items()}
    q = ("TEST_TECHNICZNY" if plan["synthetic"] else "ZWALIDOWANY_SHADOW" if "HOLDOUT_PASSED" in sides.values() else
         "BRAK_PRZESLANEK" if rep["status"] in ("INSUFFICIENT_EVIDENCE", "BUDGET_EXCEEDED") else "ODRZUCONY")
    run.set(tid, execution="UKONCZONE", quality=q, integration="ZAPISANY_DO_BADAN" if rep.get("model_hash") else "NIEZAPISANY",
            model_id=rep["run_id"], detail=f"{rep['status']}; próbek {rep['candidates']}; strony {json.dumps(sides)}; wybór OBSERVE/SHADOW_GATE ręcznie",
            unit={"task": "P(TP1_FIRST/SL_FIRST/TIMEOUT) + E[net_R]", "tf": "M1 128 + M5 32 (+M15/H1)", "horizons": "max hold profilu", "side": "głowice LONG/SHORT"})


def t_structure_intelligence(run: Run, inst: str) -> None:
    """PMW-UPD-07 STRUCTURE_MOVE_M1_V1 + SCALP_STRUCTURE_CONTEXT_V1: dataset + frozen protocol; holdout not opened; never selected."""
    tid, plan = f"{inst}:structure_intelligence", run.state["plan"]
    ds = _ready(run, inst, tid)
    if ds is None:
        return
    out = run.dir / f"{inst}_structure_intelligence.json"
    com = plan["commissions"].get(inst)
    prof = "quick" if plan["profile"] == "TEST_INSTALACJI" or plan["synthetic"] else "standard"
    cmd = [core.bot_python(), "-m", "masterquo", "structure-intelligence", "pipeline", "--asset", inst, "--dataset", str(ds), "--out", str(out),
           "--profile", prof] + (["--allow-synthetic-fixture"] if plan["synthetic"] else []) + (["--commission", str(com)] if com is not None else [])
    rc, tail = core.run_child(run, tid, cmd, core.child_env(plan, inst), plan["profile_params"]["task_timeout_minutes"] * 60, f"{inst}_structure_intelligence")
    if rc is None:
        return run.set(tid, execution="ANULOWANE")
    rep = _json(out)
    if not rep:
        return _fail(run, tid, f"structure-intelligence kod {rc}: {tail}")
    st = {k: v.get("status") for k, v in rep["tasks"].items()}
    q = ("TEST_TECHNICZNY" if plan["synthetic"] else "BRAK_PRZESLANEK" if all(v in ("INSUFFICIENT_EVIDENCE", "NO_SETUP", "BLOCKED_COSTS", "BLOCKED_NO_TICK_HISTORY")
                                                                              for v in st.values())
         else "DO_OCENY_NA_DEV")
    run.set(tid, execution="UKONCZONE", quality=q, integration="ZAPISANY_DO_BADAN",
            model_id=(rep["tasks"].get("STRUCTURE_MOVE_M1_V1") or {}).get("run_id"),
            detail=f"zadania {json.dumps(st)}; profil {prof}{' (niepełny smoke)' if prof == 'quick' else ''}; holdout tylko przez evaluate-holdout; SHADOW ręcznie",
            unit={"task": "P(DOWN/FLAT/UP) + q10/q50/q90 r_h/ATR; setup TP1/SL/TIMEOUT", "tf": "M1 128 + M5/M15/H1 point-in-time", "horizons": "3/5/15 świec M1",
                  "side": "kierunek ruchu (nie zlecenie)"})


def t_activate(run: Run, inst: str) -> None:
    """Atomic activation of ADMITTED models only; rejected / unvalidated ones stay for inspection and never replace the active one."""
    tid, plan = f"{inst}:activate", run.state["plan"]
    run.set(tid, execution="W_TOKU", started_at=now())
    done, kept = [], []
    if not plan["activate"]:
        reason = "dane syntetyczne – modele techniczne" if plan["synthetic"] else f"profil {plan['profile']} nie aktywuje modeli"
        return run.set(tid, execution="UKONCZONE", detail=f"bez aktywacji: {reason}", quality="NIE_DOTYCZY")
    import subprocess
    env = core.child_env(plan, inst)
    fc = run.task(f"{inst}:forecast")
    if fc.get("model_id") and fc["quality"] in ("ZWALIDOWANY_SHADOW", "CZESCIOWO_ZWALIDOWANY") and (fc.get("parity") or {}).get("status") == "OK":
        r = subprocess.run([core.candles_python(), "-m", "gold_candles_runtime.registry_cli", "--instrument", inst, "activate", fc["model_id"]],
                           cwd=str(paths.ROOT_DIR / "backend"), env=env, capture_output=True, text=True, timeout=300)
        (done if r.returncode == 0 else kept).append(f"prognozy {fc['model_id']}" + ("" if r.returncode == 0 else f": {r.stdout[-200:]}{r.stderr[-200:]}"))
        if r.returncode == 0:
            run.set(f"{inst}:forecast", integration="AKTYWNY_W_REJESTRZE")
    elif fc.get("model_id"):
        kept.append(f"prognozy {fc['model_id']} ({fc['quality']}) – poprzedni aktywny bez zmian")
    sa = run.task(f"{inst}:scalp_A")
    if sa.get("model_id") and sa["quality"] in ("ZWALIDOWANY_SHADOW", "CZESCIOWO_ZWALIDOWANY"):
        r = subprocess.run([core.candles_python(), "-m", "gold_candles_runtime.scalp_registry", "--instrument", inst, "activate", sa["model_id"]],
                           cwd=str(paths.ROOT_DIR / "backend"), env=env, capture_output=True, text=True, timeout=300)
        (done if r.returncode == 0 else kept).append(f"scalp {sa['model_id']}" + ("" if r.returncode == 0 else f": {r.stdout[-200:]}"))
        if r.returncode == 0:
            for x in "AB":
                run.set(f"{inst}:scalp_{x}", integration="AKTYWNY_W_REJESTRZE")
    elif sa.get("model_id"):
        kept.append(f"scalp {sa['model_id']} ({sa['quality']}) – poprzedni aktywny bez zmian")
    ml = run.task(f"{inst}:ml")
    if ml.get("integration") == "AKTYWNY_W_REJESTRZE":
        done.append(f"ML champion {(ml.get('result') or {}).get('champion')} (reguły promocji rejestru ML)")
    lab = run.task(f"{inst}:lab")
    from ..lab.protocol import read_pointer, set_active
    root = paths.data_dir() / "lab"
    for m in lab.get("lab_models") or []:
        cur = read_pointer(root, inst)["active"].get(m["family"])
        cur_role = (_json(root / "models" / inst / cur / "manifest.json") or {}).get("role") if cur else None
        if m["role"] == "shadow" or (cur_role != "shadow" and m["role"] == "research"):
            set_active(root, inst, m["family"], m["model_id"], f"run {run.run_id} ({m['role']})")
            done.append(f"lab {m['family']} {m['model_id']} ({'SHADOW zwalidowany' if m['role'] == 'shadow' else 'obserwacja badawcza – niezwalidowany'})")
        else:
            kept.append(f"lab {m['family']}: zostaje zwalidowany {cur}")
    if lab.get("lab_models"):
        run.set(f"{inst}:lab", integration="AKTYWNY_W_REJESTRZE")
    run.set(tid, execution="UKONCZONE", detail=("aktywowano: " + "; ".join(done) if done else "nic nie aktywowano") +
            (" | bez zmian: " + "; ".join(kept) if kept else ""), activated=done, kept=kept)


def t_bot(run: Run, inst: str) -> None:
    """Reload in a running bot (identity checked via /api/v1/health, session + CSRF). Never starts a second bot."""
    tid = f"{inst}:bot"
    from ..train_all import Bot, _health
    from ..version import APP_NAME
    from ..__main__ import _port
    port = _port()
    h = _health(port)
    if not h:
        return run.set(tid, execution="POMINIETE", detail="bot nie działa – modele z rejestru załadują się przy starcie (03_START_MASTERQUO.bat)")
    if h.get("app") != APP_NAME:
        return run.set(tid, execution="POMINIETE", detail=f"na porcie {port} działa inny serwer ({h.get('app')}) – nic nie wysłano")
    try:
        bot = Bot(port)
        bot.login()
        active = bot.get("/api/v1/assets")[1].get("active")
        bot.post("/api/v1/forecast/reload")
        bot.post("/api/v1/ml/reload")
        confirmed = []
        if active == inst:
            fc = run.task(f"{inst}:forecast")
            if fc.get("integration") == "AKTYWNY_W_REJESTRZE":
                ok = _wait(lambda: ((bot.get("/api/v1/forecast")[1].get("model") or {}).get("run_id") == fc["model_id"]), 90)
                confirmed.append(f"prognozy {fc['model_id']}: {'potwierdzony w bocie' if ok else 'brak potwierdzenia (czeka na zamkniętą świecę M5)'}")
                if ok:
                    run.set(f"{inst}:forecast", integration="ZALADOWANY_DO_SHADOW")
            lab = run.task(f"{inst}:lab")
            want = {m["model_id"] for m in lab.get("lab_models") or []}
            if want:
                ok = _wait(lambda: want & {m.get("model_id") for m in bot.get(f"/api/v1/lab?asset={inst}")[1].get("models") or []}, 120)
                confirmed.append(f"lab: {'modele widoczne w bocie' if ok else 'brak potwierdzenia'}")
                if ok:
                    run.set(f"{inst}:lab", integration="ZALADOWANY_DO_SHADOW")
            run.set(tid, execution="UKONCZONE", detail="przeładowano; " + ("; ".join(confirmed) or "brak nowych aktywnych modeli"))
        else:
            run.set(tid, execution="UKONCZONE", detail=f"przeładowano rejestry; aktywne aktywo bota to {active} – modele {inst} załadują się po przełączeniu")
    except Exception as exc:  # noqa: BLE001 - the bot keeps its previous models
        run.set(tid, execution="BLAD_TECHNICZNY", detail=f"{type(exc).__name__}: {exc}"[:300])


def _wait(pred, timeout: float, step: float = 3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            if pred():
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(step)
    return False


STEPS = {"export": t_export, "quality": t_quality, "forecast": t_forecast, "scalp_A": t_scalp, "ml": t_ml, "lab": t_lab,
         "indicator_context": t_indicator_context, "ml_scalp": t_ml_scalp, "neural_scalp": t_neural_scalp,
         "structure_intelligence": t_structure_intelligence,
         "activate": t_activate, "bot": t_bot}


def execute(run: Run) -> int:
    holder = core.acquire_lock(run.run_id)
    if holder:
        print(f"[BLAD] Trwa inny trening ({holder}). Poczekaj albo anuluj go w menu.")
        return 2
    try:
        (run.dir / "CANCEL").unlink(missing_ok=True)
        run.state["status"] = "RUNNING"
        run.event(f"start run {run.run_id}: {', '.join(run.state['plan']['instruments'])}, profil {run.state['plan']['profile']}")
        for inst in run.state["plan"]["instruments"]:                  # XAUUSD first, then BTC (plan order)
            for kind, _ in TASKS:
                if kind in ("scalp_B", "scalp_C"):
                    continue                                         # produced together with scalp_A
                t = run.task(f"{inst}:{kind}")
                if t["execution"] in ("UKONCZONE", "POMINIETE") and kind != "bot":
                    continue                                         # resume: finished tasks are not repeated
                if run.cancel_requested():
                    raise KeyboardInterrupt
                run.event(f"{inst}: {t['title']}…")
                try:
                    STEPS[kind](run, inst)
                except KeyboardInterrupt:
                    raise
                except Exception as exc:  # noqa: BLE001 - one task never stops the next one
                    import traceback
                    _fail(run, t["id"], f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-1200:]}")
                if run.task(t["id"])["execution"] == "ANULOWANE":
                    raise KeyboardInterrupt
        run.state["status"] = "FINISHED"
    except KeyboardInterrupt:
        run.state["status"] = "CANCELLED"
        for t in run.state["tasks"]:
            if t["execution"] == "W_TOKU":
                t["execution"] = "ANULOWANE"
        run.event("anulowano – wznowienie: menu → Wznów ostatni trening")
    finally:
        run.state["finished_at"] = now()
        run.save()
        core.release_lock(run.run_id)
    from . import report
    report.write(run)
    tasks = run.state["tasks"]
    if run.state["status"] == "CANCELLED":
        return 3
    if any(t["execution"] == "BLAD_TECHNICZNY" for t in tasks):
        return 1
    if any(t["execution"] == "POMINIETE" and t.get("detail") != "nie wybrano w planie" for t in tasks if t["kind"] != "bot"):
        return 4
    return 0
