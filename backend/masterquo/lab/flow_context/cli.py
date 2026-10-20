"""python -m masterquo flow-context ... (PMW-UPD-11 FF07). Offline commands never open MT5; export runs through the live bot (one
worker). Nothing activates execution; SHADOW selection is manual; the holdout is opened once by evaluate-holdout."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

INSTR = ("XAUUSD", "BTC")


def _print(x) -> None:
    print(json.dumps(x, indent=1, ensure_ascii=False, default=str))


def _raw(asset: str, path: str | None, allow_syn: bool):
    from ...extind.cli import _latest_real
    ds = Path(path) if path else _latest_real(asset)
    if ds is None or not (ds / "source_metadata.json").exists():
        return None, "BLOCKED_NO_REAL_DATA: brak eksportu REAL_USER_DATA (00_TRENING_START.bat / export) – podaj --dataset"
    meta = json.loads((ds / "source_metadata.json").read_text(encoding="utf-8"))
    if meta.get("data_kind") != "REAL_USER_DATA" and not allow_syn:
        return None, f"BLOCKED_SYNTHETIC: {meta.get('data_kind')} – tylko z --allow-synthetic-fixture (TEST_ONLY)"
    return ds, None


def main(argv: list[str]) -> int:
    from . import heikin as HF
    from . import markov as MK
    from . import stop_distance as SD
    from . import task as FT
    ap = argparse.ArgumentParser(prog="masterquo flow-context", description="Markov 3-state / buckets, Heikin Flow, S/R channels, StopDistance")
    sub = ap.add_subparsers(dest="c", required=True)

    def common(s, latest=True, ds=True):
        s.add_argument("--asset", choices=INSTR, default="XAUUSD")
        if latest:
            s.add_argument("--latest", action="store_true")
        if ds:
            s.add_argument("--dataset")
            s.add_argument("--allow-synthetic-fixture", action="store_true")
    s = sub.add_parser("audit")
    common(s, False, False)
    s.add_argument("--symbol")
    s.add_argument("--source", choices=("bridge", "import"), default="bridge")
    s = sub.add_parser("export")
    common(s, False, False)
    s.add_argument("--symbol")
    s.add_argument("--months", type=int, default=12)
    s.add_argument("--source", choices=("bridge", "import"), default="bridge")
    s = sub.add_parser("calibrate")
    common(s)
    s.add_argument("--modules", default="heikin,sr-channels,stopdistance")
    s = sub.add_parser("train-markov")
    common(s)
    s.add_argument("--models", default=f"{MK.M3},{MK.MD}")
    s = sub.add_parser("dataset")
    common(s)
    s.add_argument("--task", default=FT.TASK)
    s = sub.add_parser("train")
    common(s)
    s.add_argument("--task", default=FT.TASK)
    s.add_argument("--families", default="LOGREG,XGB")
    s.add_argument("--profile", choices=("standard", "quick"), default="standard")
    s.add_argument("--no-ablation", action="store_true")
    s.add_argument("--out")
    s = sub.add_parser("replay")
    common(s)
    s.add_argument("--mode", choices=("shadow",), default="shadow")
    s = sub.add_parser("native-parity")
    s.add_argument("--fixtures", default=str(Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "flow_context"))
    s.add_argument("--native-status-file")
    s = sub.add_parser("benchmark")
    s.add_argument("--profile", choices=("cpu",), default="cpu")
    s = sub.add_parser("report")
    common(s)
    s.add_argument("--run")
    s = sub.add_parser("evaluate-holdout")
    common(s, False, False)
    s.add_argument("--candidate-id", required=True)
    s.add_argument("--protocol-id", required=True)
    s = sub.add_parser("select")
    common(s, False, False)
    s.add_argument("--candidate-id", required=True)
    s = sub.add_parser("rollback")
    common(s, False, False)
    s = sub.add_parser("pipeline", help="train-all: kalibracja → Markov → dataset → trening → raport (bez aktywacji)")
    common(s, False)
    s.add_argument("--profile", choices=("standard", "quick"), default="standard")
    s.add_argument("--out")
    a = ap.parse_args(argv)
    try:
        if a.c == "audit":
            from ...extind.cli import _latest_real
            ds = _latest_real(a.asset)
            reg = FT._reg(a.asset)
            _print({"instrument": a.asset, "latest_real_export": str(ds) if ds else None, "profile": FT.profile(a.asset),
                    "latest_dataset": str(FT.latest(a.asset) or "") or None, "runs": len(reg["runs"]), "shadow": reg["shadow"],
                    "blocked": None if ds else "BLOCKED_NO_REAL_DATA"})
            return 0 if ds else 2
        if a.c == "export":
            print("[INFO] Eksport historii wykonuje działający bot przez istniejący worker MT5 (00_TRENING_START.bat → Eksport). "
                  "Ta komenda nie łączy się z terminalem (bez drugiego initialize).")
            return 2
        if a.c in ("calibrate", "train-markov", "dataset", "pipeline"):
            ds, err = _raw(a.asset, a.dataset, a.allow_synthetic_fixture)
            if err:
                print("[BLAD] " + err)
                return 2
            from ...extind.trainer import _bars
            meta = json.loads((ds / "source_metadata.json").read_text(encoding="utf-8"))
            tick = float(meta["tick_size"])
            point = float((meta.get("spec") or {}).get("point") or tick)
            m1 = _bars(ds, meta.get("file_prefix") or "XAUUSD", "M1")
            dev = m1[: int(0.8 * len(m1))]                                     # calibration and Markov fits see the DEV part only
        if a.c in ("calibrate", "pipeline"):
            out = calibrate(a.asset, dev, point, tick, (getattr(a, "modules", None) or "heikin,sr-channels,stopdistance").split(","), meta)
            if a.c == "calibrate":
                _print(out)
                return 0
        if a.c in ("train-markov", "pipeline"):
            mk = train_markov(a.asset, dev, point, tick, meta)
            if a.c == "train-markov":
                _print(mk)
                return 0
        if a.c in ("dataset", "pipeline"):
            man = FT.build_dataset(a.asset, ds)
            if a.c == "dataset":
                _print(man)
                return 0
        if a.c in ("train", "pipeline"):
            from ...db.database import Database
            d = FT.latest(a.asset)
            if d is None:
                print(f"[BLAD] BLOCKED_NO_DATASET: python -m masterquo flow-context dataset --asset {a.asset} --latest")
                return 2
            fams = [f.strip() for f in getattr(a, "families", "LOGREG,XGB").split(",") if f.strip()]
            rep = FT.train(a.asset, d, fams, a.profile, db=Database(), ablation=not getattr(a, "no_ablation", False))
            if a.out:
                Path(a.out).write_text(json.dumps(rep if a.c == "train" else {"calibration": out, "markov": mk, "train": rep}, indent=1, default=str),
                                       encoding="utf-8")
            if rep.get("status") == "STALE_DATASET":
                print(f"[BLAD] STALE_DATASET: {rep['reason']} – {rep['rebuild']}")
                return 2
            _print({k: rep.get(k) for k in ("run_id", "status", "role", "evidence", "comparison", "candidates", "edge_status", "run_dir")})
            return 4 if rep["status"] == "INSUFFICIENT_EVIDENCE" else 0
        if a.c == "replay":
            reg = FT._reg(a.asset)
            s_ = reg["shadow"].get(FT.TASK)
            if not s_:
                print("[INFO] brak wybranego modelu SHADOW (select --candidate-id …) – replay nie ma czego odtwarzać")
                return 2
            meta_, m = FT.load_candidate(Path(s_["dir"]))
            data = FT.load(FT.root(a.asset) / "datasets" / meta_["dataset_id"])
            from .. import structure_task as T
            sp = T.split(data)
            tail = sp["dev"][-2000:]
            b = data["rows_idx"]
            P, Q = m.predict(data["fe"]["F"][b][tail])
            _print({"mode": "shadow", "scope": "DEV_TAIL (holdout nieotwierany)", "metrics_uncalibrated": T.metrics(P, Q, data["Y"][b][tail], data["R"][b][tail])})
            return 0
        if a.c == "native-parity":
            from . import native
            _print(native.parity(Path(a.fixtures), Path(a.native_status_file) if a.native_status_file else None))
            return 0
        if a.c == "benchmark":
            import numpy as np
            sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tests"))
            rng = np.random.default_rng(1)
            c = 2000 + np.cumsum(rng.normal(0, .4, 5000))
            bars = [{"open_utc": 1.7e9 + 60 * i, "o": c[i - 1] if i else c[0], "h": max(c[i], c[i - 1] if i else c[0]) + .1,
                     "l": min(c[i], c[i - 1] if i else c[0]) - .1, "c": c[i]} for i in range(len(c))]
            res = {}
            for name, fn in (("heikin", lambda: HF.heikin_series(bars)), ("stopdistance", lambda: SD.series(bars, None, .01)),
                             ("features_flow_context", lambda: FT.features(bars, .01, .01))):
                t0 = time.perf_counter()
                fn()
                res[name] = {"bars": len(bars), "ms_per_bar": (time.perf_counter() - t0) * 1000 / len(bars)}
            md = MK.MarkovDiff(.01).fit(bars)
            t0 = time.perf_counter()
            for _ in range(20):
                md.forecast(4, c[-1], 15)
            res["markov_diff_forecast_mc2048"] = {"ms": (time.perf_counter() - t0) * 1000 / 20}
            _print({"platform": "PYTHON_NUMPY", "results": res, "note": "pomiar tej maszyny (syntetyczne wejście do pomiaru czasu)"})
            return 0
        if a.c == "report":
            reg = FT._reg(a.asset)
            rid = a.run or (sorted(reg["runs"])[-1] if reg["runs"] else None)
            if not rid:
                print("[BLAD] brak runów")
                return 2
            rep = json.loads((Path(reg["runs"][rid]["run_dir"]) / "report.json").read_text(encoding="utf-8"))
            _print({k: rep.get(k) for k in ("run_id", "status", "role", "evidence", "comparison", "ablations", "candidates", "edge_status", "holdout_from")})
            return 0
        if a.c == "evaluate-holdout":
            from ...db.database import Database
            _print(FT.evaluate_holdout(a.asset, a.candidate_id, a.protocol_id, Database()))
            return 0
        if a.c == "select":
            _print(FT.select_shadow(a.asset, a.candidate_id))
            return 0
        if a.c == "rollback":
            _print(FT.rollback(a.asset))
            return 0
    except ValueError as exc:
        print(f"[BLAD] {exc}")
        return 2
    return 1


def calibrate(inst: str, dev: list[dict], point: float, tick: float, modules: list[str], meta: dict) -> dict:
    """Profiles chosen on the DEV part only (inner fit 60 % / score rest). Criteria are stated; nothing is called edge."""
    from . import heikin as HF
    from . import sr_channels as SR
    from . import stop_distance as SD
    from . import task as FT
    k = int(len(dev) * 0.6)
    fit, ev = dev[:k], dev[k:]
    out = {"dev_bars": len(dev), "holdout_read": False, "modules": {}}
    prof = {kk: v for kk, v in FT.profile(inst).items() if kk in ("heikin", "stopdistance", "sr")}
    if "heikin" in modules:
        trials = []
        for name, (m1, p1, m2, p2) in HF.PROFILES.items():
            rows = HF.heikin_series(ev, {"ma1": m1, "p1": p1, "ma2": m2, "p2": p2}, point)["rows"]
            flips = sum(1 for x, y in zip(rows, rows[1:]) if x["color"] != y["color"])
            lag = HF.color_lag(ev, rows)
            trials.append({"profile": name, "colour_flips_per_1000": 1000 * flips / max(1, len(rows)), "median_lag_bars": lag["median_bars"]})
        best = min((x for x in trials if x["median_lag_bars"] is not None), key=lambda x: (x["colour_flips_per_1000"] * (1 + (x["median_lag_bars"] or 0))),
                   default=None)
        if best:
            m1, p1, m2, p2 = HF.PROFILES[best["profile"]]
            prof["heikin"] = {"ma1": m1, "p1": p1, "ma2": m2, "p2": p2}
        out["modules"]["heikin"] = {"trials": trials, "chosen": best, "criterion": "zmiany koloru × (1+opóźnienie) – stabilność, nie edge"}
    if "stopdistance" in modules:
        c = SD.calibrate_factor(fit, point)
        if c.get("status") == "OK":
            chk = SD.calibrate_factor(ev, point)
            prof["stopdistance"] = dict(prof.get("stopdistance") or {}, factor=round(c["factor"], 4))
            c["dev_eval_quantile_factor"] = chk.get("factor")
        out["modules"]["stopdistance"] = c
    if "sr-channels" in modules:
        trials = []
        for depth in (5, 10, 15):
            for wp in (3.0, 5.0):
                touches = []
                for t in range(max(400, len(ev) // 2), len(ev) - 15, 60):
                    s = SR.channels_at(ev[max(0, t - 700):t + 1], min(t, 700), {"depth": depth, "width_pct": wp})
                    nn = SR.nearest(s, ev[t]["c"])
                    lv = [x for x in (nn["support"], nn["resistance"]) if x]
                    fut = ev[t + 1:t + 16]
                    touches.append(any(any(z["lo"] <= b["h"] and b["l"] <= z["hi"] for b in fut) for z in lv) if lv else False)
                trials.append({"depth": depth, "width_pct": wp, "snapshots": len(touches), "touch_next15_share": sum(touches) / max(1, len(touches))})
        out["modules"]["sr_channels"] = {"trials": trials, "chosen": prof.get("sr"), "note": "raport opisowy; domyślne 10/10, 5% zachowane (bez dopasowania pod wynik)"}
    prof.update(source="CALIBRATED_ON_DEV", created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), data_kind=meta.get("data_kind"))
    p = FT.root(inst) / "profile.json"
    if p.exists():
        (FT.root(inst) / f"profile_{int(time.time())}.json").write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    p.write_text(json.dumps(prof, indent=1), encoding="utf-8")
    out["profile"] = FT.profile(inst)
    return out


def train_markov(inst: str, dev: list[dict], point: float, tick: float, meta: dict) -> dict:
    """Fit both Markov models on the DEV fit part, evaluate prequentially on the rest of dev (state logloss/Brier, cumulative MAE)."""
    import numpy as np
    from . import markov as MK
    from . import task as FT
    k = int(len(dev) * 0.6)
    fit, ev = dev[:k], dev[k:]
    out = {"models": {}}
    m3 = MK.Markov3(point, tick).fit(fit)
    for i in range(1, len(ev)):
        m3.step(ev[max(0, i - 3):i + 1])
    sc = m3.scores
    out["models"][MK.M3] = {"fit": m3.fit_info, "dev_eval": {"n": len(sc), "logloss": float(np.mean([x["logloss"] for x in sc])) if sc else None,
                                                             "brier": float(np.mean([x["brier"] for x in sc])) if sc else None}}
    md = MK.MarkovDiff(point).fit(fit)
    errs = {h: [] for h in (1, 5, 15)}
    for i in range(1, len(ev) - 15, 5):
        r = md.step(ev[i - 1:i + 1], 15, mc=False)
        if r.get("projection"):
            for h in errs:
                errs[h].append(abs(ev[i + h]["c"] - r["projection"][str(h)]["price_mean"]))
    base = {h: [abs(ev[i + h]["c"] - ev[i]["c"]) for i in range(1, len(ev) - 15, 5)] for h in errs}
    out["models"][MK.MD] = {"fit": md.fit_info, "eligibility": md.eligibility(),
                            "dev_eval": {str(h): {"mae": float(np.mean(v)) if v else None, "mae_no_drift": float(np.mean(base[h]))} for h, v in errs.items()}}
    d = FT.root(inst) / "markov" / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    d.mkdir(parents=True)
    (d / "markov3.json").write_text(json.dumps(m3.to_dict(), default=float), encoding="utf-8")
    md.save(d / "diff")
    (FT.root(inst) / "markov" / "latest.txt").write_text(str(d), encoding="utf-8")
    out.update(dir=str(d), data_kind=meta.get("data_kind"), role="TEST_ONLY" if meta.get("data_kind") != "REAL_USER_DATA" else "RESEARCH")
    return out


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
