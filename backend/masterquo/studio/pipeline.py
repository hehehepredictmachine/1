"""Stages of ONE Studio task (PMW-STUDIO-PIPE-1): export -> validate_raw -> build_dataset -> validate_dataset -> train_or_fit ->
evaluate -> verify_loader (+ package files); transfer is a separate operation (importer.py).

Sources (chosen once per job, written into the manifest):
  BOT_CACHE   the bot is running: the bot keeps the only terminal connection; Studio materialises the needed TFs from the bot's
              candle store (read-only copy, chunked by month) - it never opens its own MT5 session next to the bot.
  MT5_DIRECT  the bot is not running: Studio's own read-only adapter (marketdata.sources.open_direct, NoOrders wrapper) exports the
              FULL available history in chunks (historical mode from 2000-01-01) under the cross-process export lock.
  OFFLINE     an existing candle store given explicitly (path).
  SYNTHETIC   FakeMT5 simulator - test packages only, always marked SYNTHETIC.
The trainer receives the exact package path (dataset_id); nothing picks a "latest" folder.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import time
from pathlib import Path

import numpy as np

from .package import ARTIFACT, DATASET, EVAL, LOADER, RAW, VAL_DS, VAL_RAW, Package, atomic_json, read_json

VERSION = "PMW-STUDIO-PIPE-1"
FULL_HISTORY_FROM = 946684800            # 2000-01-01: "all available history" - the source decides what exists
TF_ORDER = ("M1", "M3", "M5", "M15", "M30", "H1", "H4", "D1")


class Blocked(Exception):
    def __init__(self, state: str, reason: str):
        super().__init__(reason)
        self.state, self.reason = state, reason


class Ctx:
    def __init__(self, task: dict, pkg: Package, *, source: dict, profile: str = "smoke", cancel=None, pause=None, progress=None, cfg_store=None):
        self.task, self.pkg, self.source, self.profile = task, pkg, source, profile
        self.cancel = cancel or (lambda: False)
        self.pause = pause or (lambda: False)
        self.progress = progress or (lambda d: None)
        self.cfg_store = cfg_store

    def check(self):
        if self.cancel():
            raise Blocked("CANCELLED", "anulowano przez użytkownika")
        if self.pause():
            raise Blocked("PAUSED", "wstrzymano – wznowienie od ostatniego zatwierdzonego etapu / porcji")


def needed_tfs(task: dict) -> list[str]:
    out = [s["tf"] for s in task.get("sources") or [] if s["kind"] in ("BARS", "BARS_MULTI", "BARS_RUNNER_EXPORT") and s.get("tf")]
    if task["adapter"] == "TRAINHUB":
        from ..trainhub import features as F
        out = [task["base_tf"], *F.HTF_OF[task["base_tf"]]]
    return sorted(set(out), key=lambda t: TF_ORDER.index(t) if t in TF_ORDER else 99)


def raw_store(pkg: Package):
    from ..marketdata.store import Store
    return Store(pkg.dir / RAW)


# ------------------------------------------------------------------ export
def stage_export(ctx: Ctx) -> dict:
    from ..marketdata.store import Store, TF_SECONDS
    task, pkg = ctx.task, ctx.pkg
    if task["adapter"] == "RUNNER_GROUP":
        return _export_runner(ctx)
    tfs = needed_tfs(task)
    tmp = pkg.tmp("export")
    dst = Store(tmp)
    inst = task["instrument"]
    mode = ctx.source["mode"]
    cutoff = int(ctx.source.get("cutoff") or time.time())
    report = {"mode": mode, "cutoff_utc": cutoff, "timeframes": {}, "requested": "CAŁA DOSTĘPNA HISTORIA" if not ctx.source.get("start") else
              {"from": ctx.source.get("start"), "to": ctx.source.get("end")}}
    if mode in ("BOT_CACHE", "OFFLINE"):
        src = Store(Path(ctx.source["store_root"]))
        man = src.manifest(inst) or {}
        if not man:
            raise Blocked("BLOCKED_DATA", f"brak danych {inst} w magazynie źródłowym {ctx.source['store_root']} – uruchom eksport w bocie")
        for tf in tfs:
            ctx.check()
            n, t0, t1 = 0, None, None
            for key in src.parts(inst, tf):                                           # chunk = one month part
                ctx.check()
                rows = src._read_part(inst, tf, key)
                keep = [r for t, r in sorted(rows.items()) if t + TF_SECONDS[tf] <= cutoff and (not ctx.source.get("start") or t >= ctx.source["start"])]
                if keep:
                    dst.merge(inst, tf, keep)
                    n += len(keep)
                    t0 = keep[0][0] if t0 is None else t0
                    t1 = keep[-1][0]
                ctx.progress({"stage": "export", "tf": tf, "chunk": key, "rows": n})
            report["timeframes"][tf] = {"rows": n, "from": t0, "to": t1, "stop_reason": "koniec danych w magazynie źródłowym" if n else "brak danych"}
        dst.write_manifest(inst, {k: v for k, v in man.items() if k != "files"} | {"exported_by": "STUDIO", "source_mode": mode})
    elif mode in ("MT5_DIRECT", "SYNTHETIC"):
        from ..marketdata import export as EX
        from ..marketdata.sources import DirectSource, open_direct
        if mode == "SYNTHETIC":
            from ..mt5.fake import FakeMT5
            fake = FakeMT5(history_days=int(ctx.source.get("days", 30)) + 5)
            fake.initialize()
            source = DirectSource(fake, offset=fake.offset, offset_basis="SIMULATOR")
            sym = task.get("broker_symbol") or ("XAUUSD-" if inst == "XAUUSD" else "BTCUSD-")
            start = time.time() - 86400 * float(ctx.source.get("days", 30))
        else:
            source, sym = open_direct(ctx.cfg_store.get() if ctx.cfg_store else None), task.get("broker_symbol")
            start = ctx.source.get("start") or FULL_HISTORY_FROM
        if not sym:
            raise Blocked("BLOCKED_DATA", f"brak symbolu brokera dla {inst} (konfiguracja aktywów)")
        summ = EX.run(source, dst, inst, sym, timeframes=tfs, mode="historical", start=start, end=ctx.source.get("end") or cutoff,
                      progress=lambda d: ctx.progress({"stage": "export", **d}), cancel=lambda: ctx.cancel() or ctx.pause())
        for tf in tfs:
            t = dst.read(inst, tf)["time"]
            report["timeframes"][tf] = {"rows": len(t), "from": t[0] if t else None, "to": t[-1] if t else None,
                                        "stop_reason": "źródło nie zwróciło wcześniejszej historii" if t else "brak danych"}
        report["export_summary"] = summ
    else:
        raise Blocked("FAILED", f"nieznany tryb źródła {mode}")
    report["missing"] = [tf for tf, r in report["timeframes"].items() if r["rows"] == 0]
    atomic_json(tmp / "export_report.json", report)
    pkg.commit("export", tmp, {"report": report}, subdir="raw")
    if report["missing"]:
        raise Blocked("BLOCKED_DATA", f"brak danych dla TF: {', '.join(report['missing'])}")
    return report


def _export_runner(ctx: Ctx) -> dict:
    """Runner groups use the runner's own exporter (forecast/export dataset format) - into THIS package only."""
    import subprocess
    import sys
    task, pkg = ctx.task, ctx.pkg
    mode = ctx.source["mode"]
    if mode == "BOT_CACHE":
        raise Blocked("BLOCKED_DEPENDENCY", "zadania grupowe runnera eksportują przez własne połączenie MT5 – zatrzymaj bota (tryb MT5_DIRECT) "
                                            "albo użyj Centrum treningu w bocie")
    tmp = pkg.tmp("export")
    out = tmp / "runner_dataset"
    months = 1 if mode == "SYNTHETIC" else int(ctx.source.get("months") or 240)
    cmd = [sys.executable, "-m", "masterquo", "training", "export", "--instrument", task["instrument"], "--symbol",
           task.get("broker_symbol") or ("XAUUSD-" if task["instrument"] == "XAUUSD" else "BTCUSD-"), "--months", str(months), "--out", str(out),
           "--tfs", ",".join(needed_tfs(task))] + (["--synthetic"] if mode == "SYNTHETIC" else [])
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=6 * 3600,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    (pkg.dir / "logs" / "runner_export.log").write_text((p.stdout or "") + (p.stderr or ""), encoding="utf-8")
    if p.returncode != 0 or not (out / "source_metadata.json").exists():
        raise Blocked("FAILED", f"eksport runnera zakończony kodem {p.returncode}")
    rep = {"mode": mode, "format": "forecast/export (runner)", "metadata": read_json(out / "source_metadata.json", {}), "missing": []}
    atomic_json(tmp / "export_report.json", rep)
    pkg.commit("export", tmp, {"report": rep}, subdir="raw")
    return rep


# ------------------------------------------------------------------ validation
def _md(title, rep) -> str:
    lines = [f"# {title}", "", f"Status: **{rep.get('status')}**", ""]
    lines += [f"- BLOKADA: {b}" for b in rep.get("blocking") or []]
    lines += [f"- ostrzeżenie: {w}" for w in rep.get("warnings") or []]
    lines += ["", "```json", json.dumps(rep.get("checks"), ensure_ascii=False, indent=1, default=str)[:20000], "```"]
    return "\n".join(lines)


def stage_validate_raw(ctx: Ctx) -> dict:
    from ..marketdata import quality as Q
    task, pkg = ctx.task, ctx.pkg
    tmp = pkg.tmp("validate_raw")
    rep = {"checks": {}, "blocking": [], "warnings": []}
    if task["adapter"] == "RUNNER_GROUP":
        meta = read_json(pkg.dir / RAW / "runner_dataset" / "source_metadata.json", {}) or {}
        rep["checks"]["runner_metadata"] = {"instrument": meta.get("instrument"), "symbol": meta.get("symbol"), "data_kind": meta.get("data_kind")}
        if meta.get("instrument") != task["instrument"]:
            rep["blocking"].append("instrument w metadanych eksportu ≠ zadanie")
        rep["data_kind"] = meta.get("data_kind")
    else:
        st = raw_store(pkg)
        for tf in needed_tfs(task):
            cols = st.read(task["instrument"], tf)
            rep["checks"][tf] = Q.report(cols, tf)
            if not cols["time"]:
                rep["blocking"].append(f"{tf}: brak świec")
            c = np.asarray(cols["close"], dtype=float) if cols["close"] else np.zeros(0)
            if len(c) and (not np.all(np.isfinite(c)) or np.any(c <= 0)):
                rep["blocking"].append(f"{tf}: ceny nieskończone / niedodatnie")
            t = np.asarray(cols["time"])
            if len(t) > 1 and np.any(np.diff(t) <= 0):
                rep["blocking"].append(f"{tf}: czas niemonotoniczny / duplikaty")
        man = st.manifest(task["instrument"]) or {}
        rep["data_kind"] = "SYNTHETIC" if ctx.source["mode"] == "SYNTHETIC" else (man.get("data_kind") or "UNKNOWN")
    rep["status"] = "FAILED" if rep["blocking"] else "OK"
    atomic_json(tmp / "raw.json", rep)
    (tmp / "raw.md").write_text(_md("Walidacja danych źródłowych", rep), encoding="utf-8")
    pkg.commit("validate_raw", tmp, {"status": rep["status"], "data_kind": rep.get("data_kind")}, subdir="validation")
    if rep["blocking"]:
        raise Blocked("FAILED", "walidacja surowych danych: " + "; ".join(rep["blocking"][:5]))
    return rep


def data_kind(pkg: Package) -> str:
    return (read_json(pkg.dir / VAL_RAW / "raw.json", {}) or {}).get("data_kind") or "UNKNOWN"


# ------------------------------------------------------------------ dataset
def stage_build_dataset(ctx: Ctx) -> dict:
    task, pkg = ctx.task, ctx.pkg
    tmp = pkg.tmp("build_dataset")
    inst = task["instrument"]
    st = raw_store(pkg)
    info, root_files = {}, []
    if task["adapter"] == "TRAINHUB":
        from ..trainhub import dataset as DS
        from ..trainhub import features as F
        from ..trainhub import pipeline as TP
        cfg = TP.config({"models": [task["model_id"]], "base_tf": task["base_tf"], "horizon": task["horizon"], "profile": ctx.profile},
                        st.manifest(inst))
        ds, desc = TP.stage_dataset(st, inst, cfg)
        np.savez_compressed(tmp / "dataset.npz", **{k: ds[k] for k in ("t", "X", "y", "label_end", "fwd", "cost", "atr")})
        atomic_json(pkg.dir / "feature_schema.json", F.schema(cfg["base_tf"]))
        atomic_json(pkg.dir / "label_schema.json", {"task": task["task_id"], "version": DS.LABEL_VERSION, "horizon_bars": cfg["horizon"],
                                                    "k_atr": cfg["k_atr"], "classes": list(DS.CLASSES), "costs": cfg.get("cost_status"),
                                                    "maturity": "label_end = otwarcie świecy t+H; próbki bez dojrzałej etykiety są usuwane"})
        sp = DS.splits(ds, holdout_frac=float(cfg["holdout_frac"]), n_folds=int(cfg["n_folds"]), embargo_bars=int(cfg["embargo_bars"]),
                       step=F.TF_S[cfg["base_tf"]], min_samples=int(cfg["min_samples"]), min_train=int(cfg["min_train"]))
        atomic_json(pkg.dir / "splits.json", {"holdout_start_utc": sp["holdout_start"], "embargo_s": sp["embargo_s"], "dev_rows": int(len(sp["dev"])),
                                              "holdout_rows": int(len(sp["holdout"])), "folds": len(sp["folds"]),
                                              "rule": "chronologicznie; purge po czasie końca etykiety + embargo"})
        info = {"rows": int(len(ds["y"])), "features": len(ds["names"]), "class_counts": np.bincount(ds["y"], minlength=3).tolist(),
                "names": ds["names"], "cfg": {k: cfg[k] for k in ("base_tf", "horizon", "k_atr", "n_folds", "holdout_frac", "min_samples")}}
        root_files = ["feature_schema.json", "label_schema.json", "splits.json"]
    elif task["adapter"] in ("FAMILY", "DETERMINISTIC"):
        from ..modelhub.families import base as FB
        tf = task["base_tf"]
        bars = FB.bars_from_store(st, inst, tf) if tf not in ("NONE", None) else []
        (tmp / f"bars_{tf}.json").write_text(json.dumps(bars), encoding="utf-8")
        info = {"rows": len(bars), "tf": tf}
        if task["adapter"] == "DETERMINISTIC":
            import csv
            feats = deterministic_features(task, bars, st)
            with (tmp / "features.csv").open("w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(feats[0].keys()) if feats else ["t"])
                w.writeheader()
                for r in feats:
                    w.writerow(r)
            info["feature_rows"] = len(feats)
            atomic_json(pkg.dir / "feature_schema.json", {"indicator": task["model_id"], "columns": list(feats[0].keys()) if feats else [],
                                                          "causal": "każdy wiersz liczony wyłącznie z zamkniętych świec <= t"})
            atomic_json(pkg.dir / "label_schema.json", {"task": "NOT_APPLICABLE"})
        else:
            atomic_json(pkg.dir / "label_schema.json", {"task": task["task_id"], "family": task["model_id"]})
            atomic_json(pkg.dir / "feature_schema.json", {"family": task["model_id"], "schema": task["feature_schema_version"]})
        root_files = ["feature_schema.json", "label_schema.json"]
    elif task["adapter"] == "RUNNER_GROUP":
        info = {"dataset_dir": str(pkg.dir / RAW / "runner_dataset"), "note": "format runnera (forecast/export) – przekazany jawnie"}
    atomic_json(tmp / "dataset_info.json", info)
    pkg.commit("build_dataset", tmp, {"info": {k: v for k, v in info.items() if k != "names"}}, subdir="dataset", files=root_files)
    return info


def deterministic_features(task: dict, bars: list[dict], st) -> list[dict]:
    """Causal per-bar features with the bot's own indicator code."""
    out = []
    if task["model_id"] == "IND_SEMIVAR":
        lr = [0.0] + [math.log(bars[i]["c"] / bars[i - 1]["c"]) if bars[i]["t"] - bars[i - 1]["t"] <= 90 else float("nan")
                      for i in range(1, len(bars))]                         # a return across a gap is skipped (SKIP mode of PMW-IND-SEMIVAR-1)

        def share(v):
            up = sum(x * x for x in v if x > 0)
            dn = sum(x * x for x in v if x < 0)
            return (dn / (up + dn)) if up + dn > 0 else ""
        for i in range(len(bars)):
            r20 = [x for x in lr[max(0, i - 19):i + 1] if x == x]
            r60 = [x for x in lr[max(0, i - 59):i + 1] if x == x]
            out.append({"t": bars[i]["t"], "downside_share_20": share(r20) if len(r20) >= 20 else "",
                        "downside_share_60": share(r60) if len(r60) >= 60 else ""})
    elif task["model_id"] == "IND_AVWAP_SESSION":
        from ..analytics import session_engine as SE
        from ..indicators.avwap import Accumulator
        prof = "LAB_XAU_REFERENCE_V1" if task["instrument"] == "XAUUSD" else "LAB_BTC_REFERENCE_V1"
        acc, cur = None, None
        for b in bars:
            ws = [w for w in SE.windows(prof, b["t"], 1, 0) if w["start"].timestamp() <= b["t"] < w["end"].timestamp()]
            key = (ws[-1]["session"], ws[-1]["local_date"]) if ws else None
            if key != cur:
                acc, cur = (Accumulator() if key else None), key
            if acc is None:
                out.append({"t": b["t"], "session": "", "avwap": "", "sigma": ""})
                continue
            acc.add((b["h"] + b["l"] + b["c"]) / 3.0, float(b.get("tv") or 0))
            m, sd = acc.value()
            out.append({"t": b["t"], "session": key[0], "avwap": m if m is not None else "", "sigma": sd if sd is not None else ""})
    elif task["model_id"] == "IND_XAU_DXY":
        from ..indicators import dxy as DX
        from ..modelhub.families import base as FB
        dx = FB.bars_from_store(st, "DXY", "H1") if st.manifest("DXY") else []
        if not dx:
            raise Blocked("BLOCKED_DATA", "brak serii DXY H1 w paczce (skonfiguruj dxy_symbol i eksport DXY) – nie zastępuję jej")
        xb = [{"open_utc": b["t"], "c": b["c"], "closed": True, "available_at": b["t"] + 3600} for b in bars]
        db = [{"open_utc": b["t"], "c": b["c"], "closed": True, "available_at": b["t"] + 3600} for b in dx]
        for b in bars[300:]:
            r = DX.compute(xb, db, as_of=b["t"] + 3600, instrument=task["instrument"], broker_symbol=None, dxy_symbol="DXY")
            out.append({"t": b["t"], "status": r["status"], "corr_72": (r["values"] or {}).get("corr_72"), "beta_72": (r["values"] or {}).get("beta_72")})
    return out


def load_family_data(ctx: Ctx) -> dict:
    task, pkg = ctx.task, ctx.pkg
    tf = task["base_tf"]
    p = pkg.dir / DATASET / f"bars_{tf}.json"
    bars = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    data = {"instrument": task["instrument"], "point": 0.01, "data_kind": data_kind(pkg), "symbol": task.get("broker_symbol"), "bars": bars}
    if ctx.cfg_store is not None:
        fc = ctx.cfg_store.get().families
        data["pair"] = (fc.pairs or [None])[0]
        data["basket"] = fc.basket
    if task["model_id"] == "NLP_SENTIMENT":
        from ..modelhub.families.nlp import load_corpus
        data["corpus"] = load_corpus()
    if task["model_id"] == "MICROSTRUCTURE":
        from ..modelhub.families.run import books_from_archive
        data["books"] = books_from_archive(ctx.source.get("indicators_db"), task.get("broker_symbol"))
    return data


def stage_validate_dataset(ctx: Ctx) -> dict:
    task, pkg = ctx.task, ctx.pkg
    tmp = pkg.tmp("validate_dataset")
    rep = {"checks": {}, "blocking": [], "warnings": []}
    info = read_json(pkg.dir / DATASET / "dataset_info.json", {}) or {}
    if task["adapter"] == "TRAINHUB":
        z = np.load(pkg.dir / DATASET / "dataset.npz")
        X, y, lend, t = z["X"], z["y"], z["label_end"], z["t"]
        sch = read_json(pkg.dir / "feature_schema.json", {}) or {}
        cutoff = (pkg.manifest["stages"]["export"]["report"])["cutoff_utc"]
        rep["checks"] = {"rows": int(len(y)), "finite": bool(np.all(np.isfinite(X))), "class_counts": np.bincount(y, minlength=3).tolist(),
                         "feature_order_matches_schema": list(sch.get("names") or []) == list(info.get("names") or []),
                         "labels_mature_before_cutoff": bool(np.all(lend <= cutoff)), "time_monotonic": bool(np.all(np.diff(t) > 0))}
        if not rep["checks"]["finite"]:
            rep["blocking"].append("wartości nieskończone w cechach")
        if not rep["checks"]["feature_order_matches_schema"]:
            rep["blocking"].append("kolejność cech ≠ schemat modelu")
        if not rep["checks"]["labels_mature_before_cutoff"]:
            rep["blocking"].append("etykiety sięgają poza moment końcowy eksportu")
        if min(rep["checks"]["class_counts"]) == 0:
            rep["warnings"].append("brak którejś klasy – model zachowa prior tej klasy")
    elif task["adapter"] == "FAMILY":
        from ..modelhub.families import registry as famreg
        ok, why = famreg()[task["model_id"]].validate_data(load_family_data(ctx))
        rep["checks"]["family_validate_data"] = {"ok": ok, "reason": why}
        if not ok:
            rep["blocking"].append(why)
    elif task["adapter"] == "DETERMINISTIC":
        rep["checks"]["feature_rows"] = info.get("feature_rows")
        if not info.get("feature_rows"):
            rep["blocking"].append("brak wierszy cech")
    rep["data_kind"] = data_kind(pkg)
    if rep["data_kind"] == "SYNTHETIC":
        rep["warnings"].append("dane SYNTETYCZNE – paczka testowa, nie dopuszcza modelu do roli produkcyjnej")
    rep["status"] = "FAILED" if rep["blocking"] else "OK"
    atomic_json(tmp / "dataset.json", rep)
    (tmp / "dataset.md").write_text(_md("Zgodność datasetu z modelem", rep), encoding="utf-8")
    pkg.commit("validate_dataset", tmp, {"status": rep["status"]}, subdir="validation")
    if rep["blocking"]:
        raise Blocked("BLOCKED_DATA" if task["adapter"] == "FAMILY" else "FAILED", "walidacja datasetu: " + "; ".join(rep["blocking"][:5]))
    return rep


# ------------------------------------------------------------------ training
def stage_train(ctx: Ctx) -> dict:
    task, pkg = ctx.task, ctx.pkg
    tmp = pkg.tmp("train")
    cfg_out = {"dataset_id": pkg.manifest.get("dataset_id"), "package": str(pkg.final), "working_dir_during_training": str(pkg.dir),
               "profile": ctx.profile, "task_key": task["task_key"]}
    if task["adapter"] == "TRAINHUB":
        from ..trainhub import pipeline as TP
        from ..trainhub import registry as TR
        st = raw_store(pkg)
        cfg = TP.config({"models": [task["model_id"]], "base_tf": task["base_tf"], "horizon": task["horizon"], "profile": ctx.profile},
                        st.manifest(task["instrument"]))
        cfg["models"] = [task["model_id"]]
        out = TP.stage_train(st, task["instrument"], cfg, progress=lambda d: ctx.progress({"stage": "train", **d}), cancel=ctx.cancel)
        if not out["packages"]:
            raise Blocked("FAILED", "trener nie zwrócił paczki: " + json.dumps(out.get("skipped"), ensure_ascii=False))
        p = out["packages"][0]
        shutil.copytree(TR.package_dir(task["instrument"], p["model_key"], p["version"]), tmp / "trainhub" / p["model_key"] / p["version"])
        res = {"kind": "TRAINHUB", "model_key": p["model_key"], "version": p["version"], "holdout": p.get("holdout"),
               "walk_forward": p.get("walk_forward"), "trading_eval_holdout": p.get("trading_eval_holdout")}
    elif task["adapter"] == "FAMILY":
        from ..modelhub.families import base as FB
        from ..modelhub.families import run as RUN
        r = RUN.train(task["model_id"], task["instrument"], ctx.profile, {}, data=load_family_data(ctx), store=FB.Store(tmp / "families"))
        if r["state"] != "DONE":
            raise Blocked("BLOCKED_DATA" if r["state"] == "BLOCKED" else "FAILED", r.get("reason") or r["state"])
        m = read_json(Path(r["dir"]) / "manifest.json", {}) or {}
        res = {"kind": "FAMILY", "run_id": r["run_id"], "validation": (m.get("validation") or {}).get("status"), "metrics": m.get("metrics")}
    elif task["adapter"] == "RUNNER_GROUP":
        res = _train_runner(ctx)
    else:
        raise Blocked("FAILED", f"adapter {task['adapter']} nie trenuje")
    atomic_json(pkg.dir / "training_config.json", cfg_out)
    atomic_json(tmp / "train_result.json", res)
    pkg.commit("train", tmp, {"result": {k: v for k, v in res.items() if k != "metrics"}}, subdir="artifact", files=["training_config.json"])
    return res


def _train_runner(ctx: Ctx) -> dict:
    from ..training import core as RC
    from ..training import runner as RN
    task = ctx.task
    kind = task["task_id"]
    plan, tasks = RN.build_plan(instruments=[task["instrument"]], profile="quick" if ctx.profile == "smoke" else "standard",
                                symbols={task["instrument"]: task.get("broker_symbol") or "XAUUSD-"}, commissions={}, months=None,
                                synthetic=ctx.source["mode"] == "SYNTHETIC", tasks=[kind],
                                datasets={task["instrument"]: str(ctx.pkg.dir / RAW / "runner_dataset")}, origin="studio")
    plan["activate"] = False                                                   # Studio never inherits activation
    for t in tasks:
        if t["kind"] in ("activate", "bot"):
            t.update(execution="POMINIETE", detail="Studio: aktywacja i przeładowanie bota tylko jawnie w bocie")
    run = RC.Run.create(plan, tasks)
    rc = RN.execute(run)
    return {"kind": "RUNNER_GROUP", "rc": rc, "runner_run_id": run.run_id,
            "tasks": {t["id"]: {k: t.get(k) for k in ("execution", "quality", "detail")} for t in run.state["tasks"]}}


def stage_evaluate(ctx: Ctx) -> dict:
    pkg = ctx.pkg
    tmp = pkg.tmp("evaluate")
    res = read_json(pkg.dir / ARTIFACT / "train_result.json", {}) or {}
    ev = {"result": res}
    if res.get("kind") == "TRAINHUB":
        ev["decision"] = "BEATS_BASELINE_ON_HOLDOUT" if ((res.get("holdout") or {}).get("skill_vs_baseline") or 0) > 0 else "NO_EDGE_VS_BASELINE"
    elif res.get("kind") == "FAMILY":
        ev["decision"] = res.get("validation") or "UNKNOWN"
    else:
        ev["decision"] = "SEE_RUNNER_REPORT"
    ev["promotion"] = "brak automatycznej promocji – import do bota jako kandydat (SHADOW), aktywacja roli jawnie w bocie"
    atomic_json(tmp / "metrics.json", ev)
    pkg.commit("evaluate", tmp, {"decision": ev["decision"]}, subdir="evaluation")
    return ev


def stage_verify_loader(ctx: Ctx) -> dict:
    """Clean process: the BOT's loader reads the artifact and reproduces the inference sample."""
    import subprocess
    import sys
    pkg = ctx.pkg
    tmp = pkg.tmp("verify_loader")
    p = subprocess.run([sys.executable, "-m", "masterquo.studio.verify", str(pkg.dir)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=900, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    try:
        res = json.loads((p.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        res = {"ok": False, "error": (p.stderr or "")[-800:]}
    atomic_json(tmp / "loader.json", res)
    pkg.commit("verify_loader", tmp, {"ok": bool(res.get("ok"))}, subdir="evaluation")
    if not res.get("ok"):
        raise Blocked("FAILED", f"loader bota nie odtworzył próbki: {res.get('error') or res.get('reason')}")
    return res


def write_reproduce(pkg: Package, task: dict, source: dict) -> None:
    txt = (f"# Odtworzenie paczki {pkg.run_id}\n\nZadanie: `{task['task_key']}` ({task['model_id']} / {task['task_id']} / {task['instrument']} / "
           f"{task['base_tf']} / H{task.get('horizon')})\n\n1. Dane: `{RAW}/` (sumy SHA-256 w manifest.json → stages.export.files), źródło "
           f"{source['mode']}, cutoff {source.get('cutoff')}.\n2. Dataset: `{DATASET}/` zbudowany wspólnym kodem bota (trainhub / modelhub.families / "
           "indicators).\n3. Trening: `training_config.json` (dataset_id + dokładna ścieżka paczki, profil).\n"
           "4. Odczyt: `python -m masterquo.studio.verify <ta paczka>`.\n5. Import do bota: Studio → Kolejka i wyniki → „Przekaż do bota” "
           "(kandydat SHADOW, rollback importu dostępny).\n")
    (pkg.dir / "REPRODUCE.md").write_text(txt, encoding="utf-8")


STAGES = {"export": stage_export, "validate_raw": stage_validate_raw, "build_dataset": stage_build_dataset, "validate_dataset": stage_validate_dataset,
          "train": stage_train, "evaluate": stage_evaluate, "verify_loader": stage_verify_loader}
OPS = {"FULL_EXPORT": ["export"], "VALIDATE": ["export", "validate_raw"], "BUILD_DATASET": ["export", "validate_raw", "build_dataset", "validate_dataset"],
       "EXPORT_FEATURES": ["export", "validate_raw", "build_dataset", "validate_dataset"],
       "TRAIN": ["export", "validate_raw", "build_dataset", "validate_dataset", "train", "evaluate", "verify_loader"]}
OPS["FIT"] = OPS["CALIBRATE"] = OPS["FULL_PROCESS"] = OPS["TRAIN"]
STATE_OF_STAGE = {"export": "EXPORTING", "validate_raw": "VALIDATING_RAW", "build_dataset": "BUILDING_DATASET", "validate_dataset": "VALIDATING_DATASET",
                  "train": "TRAINING", "evaluate": "EVALUATING", "verify_loader": "PACKAGING"}
FINAL_OF = {"export": "EXPORTED", "validate_raw": "VALIDATED", "validate_dataset": "READY_FOR_TRAINING", "train": "TRAINED", "evaluate": "TRAINED",
            "verify_loader": "PACKAGED"}


def run_task(task: dict, pkg: Package, op: str, ctx: Ctx) -> dict:
    stages = OPS[op]
    if task["adapter"] == "RUNNER_GROUP":
        stages = [s for s in stages if s not in ("validate_dataset", "verify_loader")]
    if task["adapter"] == "DETERMINISTIC":
        stages = [s for s in stages if s not in ("train", "evaluate", "verify_loader")]
    done = []
    for s in stages:
        if pkg.stage_done(s):
            done.append(s)
            continue
        ctx.check()
        ctx.progress({"state": STATE_OF_STAGE[s], "stage": s})
        pkg.log(f"stage {s} start")
        STAGES[s](ctx)
        pkg.log(f"stage {s} committed")
        done.append(s)
    write_reproduce(pkg, task, ctx.source)
    status = "FEATURES_EXPORTED" if task["adapter"] == "DETERMINISTIC" and stages[-1] == "validate_dataset" else FINAL_OF.get(stages[-1], "DONE")
    final = pkg.finalize(status)
    return {"status": status, "stages": done, "package": str(final)}
