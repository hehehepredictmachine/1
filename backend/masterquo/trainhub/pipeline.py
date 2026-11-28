"""Pipeline stages (PMW-TH-PIPE-1): export -> validation -> features -> labels -> chronological split -> training -> evaluation ->
package -> (controlled, manual) activation. Used by the Training Center jobs (worker.py, separate process) and by the CLI.
XAUUSD and BTC are always trained and evaluated separately (one instrument per call)."""
from __future__ import annotations

import math
import time

from ..marketdata.store import Store, atomic_json, iso, read_json
from . import dataset as DS
from . import features as F
from . import learn as L
from . import registry as R

DEFAULTS = {"base_tf": "M5", "horizon": 6, "k_atr": 0.25, "holdout_frac": 0.2, "n_folds": 4, "embargo_bars": None, "min_samples": 2000,
            "min_train": 500, "seed": 7, "models": ["TH_BASELINE", "TH_LOGREG", "TH_HGB"], "start": None, "end": None}
# 1.33 training profiles: budgets, not quality promises. smoke = the process runs end to end (one grid point, 2 folds) - it says
# nothing about investment skill; research = every available tabular model with its grid; full = more folds and the whole grid.
PROFILES = {
    "smoke": {"models": ["TH_BASELINE", "TH_LOGREG", "TH_RF", "TH_SVM"], "n_folds": 2, "grid_limit": 1, "time_budget_s": 600},
    "research": {"models": ["TH_BASELINE", "TH_LOGREG", "TH_HGB", "TH_XGB", "TH_RF", "TH_SVM"], "n_folds": 4, "grid_limit": None, "time_budget_s": 3600},
    "full": {"models": ["TH_BASELINE", "TH_LOGREG", "TH_HGB", "TH_XGB", "TH_RF", "TH_SVM"], "n_folds": 6, "grid_limit": None, "time_budget_s": 6 * 3600},
}
# 1.46 (I0050): one meaning of costs.slippage_stress_points in the bot - slippage of ONE fill (risk/engine.py, evaluation/service.py
# count 2 per trade). Label costs are per round trip, so trainhub counts SLIPPAGE_FILLS fills. Labels change -> new cost policy id in
# config.json / dataset.json; packages trained before keep working (their inputs are unchanged), retraining is recommended.
SLIPPAGE_FILLS = 2
COST_POLICY = "PMW-TH-COST-2"


def _check_num(cfg: dict, k: str, lo: float, hi: float | None = None, *, integer: bool = False, none_ok: bool = False) -> None:
    """1.46: range check of one training parameter (API params / CLI) - ValueError (HTTP 400 / CLI exit 2) instead of an IndexError /
    empty grid deep inside the training job."""
    v = cfg.get(k)
    if v is None and none_ok:
        return
    try:
        f = float(v)
    except (TypeError, ValueError):
        f = math.nan
    if not math.isfinite(f) or f < lo or (hi is not None and f > hi) or (integer and f != int(f)):
        rng = f"{lo:g}..{hi:g}" if hi is not None else f">= {lo:g}"
        raise ValueError(f"parametr {k}={v!r} poza zakresem ({rng}{', liczba całkowita' if integer else ''}{', albo brak' if none_ok else ''})")
    cfg[k] = int(f) if integer else f


def config(params: dict | None, store_manifest: dict | None = None, cost_cfg=None) -> dict:
    prof = (params or {}).get("profile")
    if prof is not None and prof not in PROFILES:
        raise ValueError(f"profil {prof} – dozwolone: {', '.join(PROFILES)}")
    base = {**DEFAULTS, **(PROFILES[prof] if prof else {}), "profile": prof}
    cfg = {**base, **{k: v for k, v in (params or {}).items() if v is not None and k != "profile"}}
    if cfg["base_tf"] not in F.HTF_OF:
        raise ValueError(f"interwał bazowy {cfg['base_tf']} – dozwolone: {', '.join(F.HTF_OF)}")
    cfg["horizon"] = int(cfg["horizon"])
    if not 1 <= cfg["horizon"] <= 96:
        raise ValueError("horyzont 1..96 świec")
    if cfg["embargo_bars"] is None:
        cfg["embargo_bars"] = cfg["horizon"]
    models = cfg["models"]
    cfg["models"] = list(models) if isinstance(models, (list, tuple)) else [models]   # 1.46: one id as text / number -> list, not chars
    bad = [m for m in cfg["models"] if m not in L.MODELS]
    if bad:
        raise ValueError(f"nieznane modele: {bad}")
    # 1.46: ranges of the remaining parameters (1.45.0 checked only base_tf / horizon / models: holdout_frac=0 -> IndexError, >1 -> a
    # negative split index, grid_limit<0 -> empty grid -> min() of an empty sequence in learn.train_one)
    _check_num(cfg, "holdout_frac", 0.05, 0.5)
    _check_num(cfg, "n_folds", 2, 20, integer=True)
    _check_num(cfg, "embargo_bars", 0, 10_000, integer=True)
    _check_num(cfg, "min_samples", 1, integer=True)
    _check_num(cfg, "min_train", 1, integer=True)
    _check_num(cfg, "grid_limit", 1, integer=True, none_ok=True)
    _check_num(cfg, "time_budget_s", 0, none_ok=True)
    _check_num(cfg, "k_atr", 0, 100)
    _check_num(cfg, "seed", 0, 2 ** 32 - 1, integer=True)
    t0, t1 = DS.epoch(cfg.get("start"), "start (--from)"), DS.epoch(cfg.get("end"), "end (--to)")   # ISO kept in cfg (REPRODUCE.md)
    if t0 is not None and t1 is not None and t0 >= t1:
        raise ValueError(f"zakres dat pusty: start {cfg.get('start')} >= end {cfg.get('end')}")
    man = store_manifest or {}
    costs = man.get("costs") or {}
    spec = man.get("symbol_spec") or {}
    if (params or {}).get("point") is not None and DS.positive(params["point"]) is None:
        raise ValueError(f"point={params['point']!r} – oczekiwana liczba dodatnia")
    # 1.46: point measured (manifest) or given explicitly - never the 0.01 default (DS.build refuses an unknown point)
    point = DS.symbol_point(man, {"point": (params or {}).get("point")})
    comm = (costs.get("commission") or {}).get("commission_per_lot_side")
    comm_status = "MEASURED_FROM_DEALS"
    if comm is None:
        comm = getattr(cost_cfg, "commission_per_lot_per_side", None) if cost_cfg is not None else None
        comm_status = "USER_ASSUMPTION" if comm is not None else "UNKNOWN_ZERO_USED"
    blockers = []
    cfg["point"] = point
    if params and params.get("commission_price") is not None:
        cfg["commission_price"] = float(params.get("commission_price"))
        comm_status = "USER_GIVEN_PRICE_UNITS"
    elif comm is None or float(comm) == 0:
        cfg["commission_price"] = 0.0                                  # unknown -> 'UNKNOWN_ZERO_USED' (labelled), known zero -> 0
    else:
        # 1.46: the commission is in the ACCOUNT currency per lot and side (deal history / Settings). 1.45.0 divided it by contract_size
        # as if account currency = quote currency (PLN account: cost ~3.7x too high) and, without contract_size, used 0.0 while still
        # reporting MEASURED_FROM_DEALS / USER_ASSUMPTION. Account currency per 1.0 of price per lot = trade_tick_value / trade_tick_size.
        tsz, tvl = DS.positive(spec.get("trade_tick_size")), DS.positive(spec.get("trade_tick_value"))
        if tsz and tvl:
            cfg["commission_price"] = 2 * float(comm) / (tvl / tsz)
        else:
            cfg["commission_price"] = 0.0                              # never used: stage_dataset refuses while cost_blockers is not empty
            blockers.append(f"prowizja {comm} ({comm_status}, waluta rachunku) bez specyfikacji symbolu (trade_tick_value / trade_tick_size) – "
                            "nie da się jej przeliczyć na jednostki ceny; ponów „Eksportuj dane” przy połączonym MT5 albo podaj commission_price")
            comm_status = "CONVERSION_UNKNOWN"
    slip_pts = getattr(cost_cfg, "slippage_stress_points", None) if cost_cfg is not None else None
    if params and params.get("slippage_price") is not None:
        cfg["slippage_price"], slip_status = float(params.get("slippage_price")), "USER_GIVEN_PRICE_UNITS"
    elif slip_pts is None:
        cfg["slippage_price"], slip_status = 0.0, "UNKNOWN_ZERO_USED"   # 1.46: was reported as ASSUMPTION_STRESS
    elif point is None:
        cfg["slippage_price"], slip_status = 0.0, "POINT_UNKNOWN"       # never used: DS.build refuses an unknown point
    else:
        # 1.46 (I0050): slippage_stress_points = slippage of ONE fill (risk/engine and evaluation/service count it twice per trade);
        # the label cost is a round trip -> SLIPPAGE_FILLS fills (up to COST_POLICY ...-1 it was counted once)
        cfg["slippage_price"], slip_status = float(slip_pts) * point * SLIPPAGE_FILLS, "ASSUMPTION_STRESS"
    cfg["cost_blockers"] = blockers
    cfg["cost_policy"] = COST_POLICY                   # in config.json of every package (packages without it: policy -1, one fill)
    cfg["cost_status"] = {"spread": "MEASURED_PER_BAR" if point is not None else "POINT_UNKNOWN", "commission": comm_status, "slippage": slip_status,
                          "slippage_fills": SLIPPAGE_FILLS if slip_status == "ASSUMPTION_STRESS" else None, "policy": COST_POLICY,
                          "note": "prowizja (waluta rachunku -> cena przez trade_tick_value/trade_tick_size) i poślizg w jednostkach ceny na 1 lot "
                                  "(round-trip; poślizg z ustawień = slippage_stress_points x point na wypełnienie x 2 wypełnienia); "
                                  "'UNKNOWN_ZERO_USED' zawyża ocenę"}
    return cfg


def dataset_dir(inst: str, cfg: dict):
    return R.root() / "datasets" / inst / f"{cfg['base_tf']}_H{cfg['horizon']}"


def stage_validate(store: Store, inst: str) -> dict:
    """Data validation before features: manifest present, checksums, schema, per-TF quality status."""
    man = store.manifest(inst)
    if not man.get("files"):
        raise DS.InsufficientData(f"brak danych {inst} w magazynie – najpierw „Eksportuj dane”")
    ver = store.verify(inst)
    if not ver["ok"]:
        raise ValueError(f"dane {inst} uszkodzone lub zmienione po eksporcie: {ver}")
    q = read_json(store.inst_dir(inst) / "quality_report.json", {}) or {}
    bad = {tf: r["status"] for tf, r in (q.get("timeframes") or {}).items() if r.get("status") != "OK"}
    return {"ok": not bad, "checksums": ver, "quality_errors": bad, "data_kind": man.get("data_kind"),
            "timeframes": {tf: {k: v.get(k) for k in ("rows", "first_utc", "last_utc")} for tf, v in (man.get("timeframes") or {}).items()}}


def stage_dataset(store: Store, inst: str, cfg: dict, progress=None) -> tuple[dict, dict]:
    if progress:
        progress({"stage": "cechy i etykiety", "instrument": inst})
    if cfg.get("cost_blockers"):                       # 1.46: a known commission that cannot be converted is not replaced by 0
        raise DS.InsufficientData("koszty etykiet nieznane: " + "; ".join(cfg["cost_blockers"]))
    ds = DS.build(store, inst, cfg, cfg.get("start"), cfg.get("end"))
    d = dataset_dir(inst, cfg)
    d.mkdir(parents=True, exist_ok=True)
    desc = DS.save(ds, d)
    desc["config"] = {k: cfg[k] for k in ("base_tf", "horizon", "k_atr", "commission_price", "slippage_price", "cost_status", "start", "end")}
    atomic_json(d / "dataset.json", desc)
    return ds, desc


def stage_train(store: Store, inst: str, cfg: dict, progress=None, cancel=None, ds=None, desc=None) -> dict:
    if ds is None:
        ds, desc = stage_dataset(store, inst, cfg, progress)
    sp = DS.splits(ds, holdout_frac=float(cfg["holdout_frac"]), n_folds=int(cfg["n_folds"]), embargo_bars=int(cfg["embargo_bars"]),
                   step=F.TF_S[cfg["base_tf"]], min_samples=int(cfg["min_samples"]), min_train=int(cfg["min_train"]))
    man = store.manifest(inst)
    avail = L.available()
    out = {"instrument": inst, "dataset": desc, "split": {"dev": int(len(sp["dev"])), "holdout": int(len(sp["holdout"])), "folds": len(sp["folds"]),
                                                          "holdout_start_utc": iso(sp["holdout_start"]), "embargo_s": sp["embargo_s"]},
           "packages": [], "skipped": [], "profile": cfg.get("profile")}
    t_start = time.time()
    for mid in cfg["models"]:
        if not avail.get(mid):
            out["skipped"].append({"model": mid, "reason": "biblioteka niedostępna w tym środowisku (np. xgboost)"})
            continue
        if cancel and cancel():
            raise InterruptedError("anulowano")
        if progress:
            progress({"stage": "trening", "model": mid, "instrument": inst})
        if cfg.get("time_budget_s") and time.time() - t_start > float(cfg["time_budget_s"]):
            out["skipped"].append({"model": mid, "reason": f"budżet czasu profilu {cfg.get('profile')} wyczerpany ({cfg['time_budget_s']} s)"})
            continue
        tr = L.train_one(mid, ds, sp, seed=int(cfg["seed"]), progress=progress, cancel=cancel, grid_limit=cfg.get("grid_limit"))
        if tr["result"].get("svm_fallback"):
            # 1.46 (I0674): the final TH_SVM fit fell back to the class frequencies - a baseline under the name TH_SVM is not saved
            # (it could be activated as an SVM); the result says why
            out["skipped"].append({"model": mid, "reason": "TH_SVM: blok kalibracyjny bez ≥2 klas – model = częstości klas (baseline), "
                                                           "paczka nie zapisana", "detail": tr["result"].get("svm_fallback_reason"),
                                   "svm_fallback_folds": tr["result"].get("svm_fallback_folds"), "holdout": tr["result"]["holdout"]})
            continue
        pkg = R.save_package(inst, cfg, tr, desc, man)
        out["packages"].append({**pkg, "holdout": tr["result"]["holdout"], "walk_forward": {k: v for k, v in tr["result"]["walk_forward"].items()
                                                                                           if k != "folds"},
                                "trading_eval_holdout": tr["result"]["trading_eval_holdout"], "data_kind": man.get("data_kind")})
    out["note"] = ("Trening nie aktywuje modelu. Aktywacja wyłącznie ręcznie (test zgodności i predykcji). Trafność nie jest rentownością – "
                   "ocena handlowa uwzględnia koszty i jest raportowana osobno.")
    return out


def stage_evaluate(store: Store, inst: str, key: str, version: str) -> dict:
    """'Oceń': the package on data AFTER its training data (forward check), same features / labels / costs as at training."""
    # 1.46: model_key / version of an EVALUATE job come from free API params and become a path (joblib.load, evaluations.json write)
    if not (isinstance(key, str) and isinstance(version, str) and R.SAFE_ID.match(key) and R.SAFE_ID.match(version)):
        raise ValueError(f"nieprawidłowy identyfikator modelu / wersji: {str(key)[:80]!r} / {str(version)[:80]!r}")
    d = R.package_dir(inst, key, version)
    if not d.resolve().is_relative_to((R.root() / "models" / inst).resolve()):
        raise ValueError("ścieżka paczki poza katalogiem modeli")
    obj, conf, _ = R.load(inst, key, version)          # 1.46: config.json was read here twice (the first read skipped the compatibility check)
    dm = read_json(d / "data_manifest.json", {}) or {}
    end_utc = ((dm.get("dataset") or {}).get("range_utc") or [None, None])[1]
    from ..marketdata.export import _ts
    after = (_ts(end_utc) or 0) + F.TF_S[conf["base_tf"]] * (int(conf["horizon"]) + 1)
    cfg = {k: conf[k] for k in ("base_tf", "horizon", "k_atr", "commission_price", "slippage_price")}
    cfg["point"] = conf.get("point")                   # 1.46: the package's point when the store manifest has none (no 0.01 guess any more)
    ds = DS.build(store, inst, cfg)
    m = ds["t"] >= after
    if m.sum() < 50:
        return {"status": "NO_NEW_DATA", "reason": f"po końcu danych treningu ({end_utc}) jest {int(m.sum())} próbek z etykietą (< 50) – "
                                                   "wyeksportuj nowsze dane i oceń ponownie", "after_utc": iso(after)}
    p = R.predict_loaded(obj, ds["X"][m])
    y = ds["y"][m]
    met = L.metrics(p, y)
    base = L.Prior().fit(None, ds["y"][~m] if (~m).any() else y).predict_proba(ds["X"][m])
    met["baseline_log_loss"] = round(L.logloss(base, y), 5)
    met["skill_vs_baseline"] = round(1 - met["log_loss"] / met["baseline_log_loss"], 5)
    res = {"status": "OK", "model_key": key, "version": version, "after_utc": iso(after), "rows": int(m.sum()), "metrics": met,
           "trading_eval": L.trade_eval(p, ds["fwd"][m], ds["cost"][m], ds["atr"][m], float(conf.get("decision_threshold") or 0.2)),
           "evaluated_at": iso(time.time()), "data_kind": (store.manifest(inst) or {}).get("data_kind")}
    hist = read_json(d.parent / f"{version}.evaluations.json", []) or []
    atomic_json(d.parent / f"{version}.evaluations.json", (hist + [res])[-20:])
    return res


def export_dataset_zip(inst: str, cfg: dict, out) -> str:
    import zipfile
    from pathlib import Path
    d = dataset_dir(inst, cfg)
    if not (d / "dataset.json").exists():
        raise FileNotFoundError("dataset nie istnieje – użyj „Przygotuj dataset”")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(d.iterdir()):
            z.write(p, f"{inst}_{d.name}/{p.name}")
        man = Store().manifest_path(inst)
        if man.exists():
            z.write(man, f"{inst}_{d.name}/store_manifest.json")
    return str(out)
