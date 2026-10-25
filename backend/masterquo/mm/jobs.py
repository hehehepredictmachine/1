"""Job adapters of the master-model orchestrator (PMW-MM-JOBS-1). Each job: real data of the snapshot -> the module's own lifecycle.

Deterministic modules get EVALUATION jobs (no fake fit). Trainable models: dataset -> chronological split (purge/embargo) -> fit ->
validate (selection on VALIDATION only) -> frozen candidate -> one TEST evaluation (HoldoutGuard) -> artifact (immutable) -> status.
Gates are fixed here BEFORE any run (never tuned on the test block). On SYNTHETIC_TEST data every artifact is TECHNICAL_TEST_ONLY and
`validation_passed` is False by definition (a technical run is not market validation).
"""
from __future__ import annotations

import math
import time

import numpy as np

from . import artifacts, splits

GATES = {
    "hdc": {"min_test": 300, "beat_logreg": 0.0, "beat_null_se": 2.0},
    "gpr": {"min_scored": 200, "cov1": (0.60, 0.76), "cov2": (0.90, 0.99), "mae_vs_zero_max_ratio": 1.0},
    "event_engine": {"min_test": 300, "logloss_gain_vs_prior": 0.002, "max_ece": 0.10},
    "ste_flownet": {"min_test": 300, "mae_gain_vs_zero": 0.005},
}


def _status(ctx, passed: bool) -> str:
    if ctx.synthetic:
        return "TECHNICAL_TEST_ONLY"
    return "VALIDATED_SHADOW" if passed else "VALIDATION_FAILED"


def _save(ctx, model_id: str, state: dict, manifest: dict, passed: bool) -> tuple[str, str]:
    st = _status(ctx, passed)
    aid = artifacts.save(ctx.inst, model_id, state, {**manifest, "status": st, "snapshot_id": ctx.snap.snapshot_id, "data_kind": ctx.snap.data_kind,
                                                     "seed": ctx.seed, "profile": ctx.profile})
    if st == "VALIDATED_SHADOW":
        artifacts.promote_shadow(ctx.inst, model_id, aid, "gates passed on REAL_USER_DATA (shadow observation only)")
    return aid, st


def _tf_s(tf: str) -> int:
    from .data import TF_S
    return TF_S[tf]


# ------------------------------------------------------------------------------------------------ data
def job_snapshot(ctx) -> dict:
    q = ctx.snap.quality
    need = ("M1", "M5")
    bad = {tf: q.get(tf, {}).get("status") for tf in need if q.get(tf, {}).get("status") != "OK"}
    if bad:
        return {"status": "BLOCKED_DATA_QUALITY", "reason": f"wymagane TF niepoprawne/brak: {bad}", "quality": q}
    return {"lineage": ctx.snap.lineage(), "quality": q, "note": "dane SYNTHETIC_TEST" if ctx.synthetic else "REAL_USER_DATA"}


# ------------------------------------------------------------------------------------------------ deterministic modules
def job_align_mean(ctx) -> dict:
    from . import align_mean as AM
    cfg = AM.AlignConfig()
    out = {}
    for tf in ("M1", "M5", "M15", "M30"):
        b = ctx.bars(tf)
        if b is None or len(b) < 100:
            continue
        r = AM.compute(b.t, b.o, b.h, b.l, b.c, _tf_s(tf), cfg, ctx.snap.point)
        z = r["dist_atr"][np.isfinite(r["dist_atr"])]
        out[tf] = {"latest": AM.latest(r, ctx.inst, tf), "dist_atr_p05_p50_p95": np.percentile(z, [5, 50, 95]).tolist() if len(z) else None,
                   "ready_share": float(np.isfinite(r["mean"]).mean())}
    modes = {}
    b = ctx.bars("M5")
    for mode, lb in (("ROLLING_MEAN", "BARS"), ("SESSION_MEAN", "SESSION"), ("FIXED_ANCHORED_MEAN", "SESSION")):
        modes[mode] = AM.latest(AM.compute(b.t, b.o, b.h, b.l, b.c, 300, AM.AlignConfig(mode=mode, lookback=lb), ctx.snap.point), ctx.inst, "M5")
    return {"config": cfg.__dict__, "config_key": cfg.key(), "per_tf": out, "modes_m5": modes, "training": "NOT_APPLICABLE",
            "pnl_visibility": "panel bota: konto/transakcje z mostka MT5 (tylko odczyt) - w zadaniu offline brak danych konta",
            "optimal_setting": "NOT_EVALUATED - brak kontrolowanego eksperymentu OOS; ustawienie domyślne nie jest deklarowane jako optymalne"}


def job_kalman(ctx) -> dict:
    from . import kalman as K
    checks = {}
    for name, (Q, R, ref) in {"fast": (1.0, 0.2, 0.854), "slow": (0.005, 0.2, 0.146)}.items():
        f = K.LocalLevel(Q, R, 1.0)
        f.step(100.0)
        for i in range(400):
            f.step(100.0 + math.sin(i))
        checks[name] = {"K_iterated": f.K, "K_analytic": K.steady_state_gain(Q, R), "reference": ref, "abs_diff": abs(f.K - K.steady_state_gain(Q, R))}
    out = {}
    for tf in ("M5", "M15"):
        b = ctx.bars(tf)
        if b is None:
            continue
        cfg = K.CrossConfig()
        full, rows = K.run(b.t, b.c, cfg)
        inc = K.KalmanCross(cfg)
        for k in range(len(b.t)):
            inc.update(float(b.t[k]), float(b.c[k]))
            inc.update(float(b.t[k]), float(b.c[k]))                        # repeated tick on the same bar: ignored
        parity = full.events == inc.events and abs(full.fast.x - inc.fast.x) < 1e-12
        ev = K.evaluate(b.t, b.c, cfg)
        out[tf] = {**ev, "replay_vs_incremental_identical": parity, "last_state": full.state}
    return {"steady_state": checks, "per_tf": out, "training": "NOT_APPLICABLE (filtr rekurencyjny)",
            "note": "zbieżność K potwierdza równania, nie przewagę"}


def job_kalman_calibration(ctx) -> dict:
    """Bounded BUZOA search of Kalman parameters on TRAIN, comparison on VAL, frozen best tested once on TEST; never applied."""
    from . import buzoa as BZ
    from . import kalman as K
    b = ctx.bars("M5")
    n = len(b.t)
    i1, i2 = int(n * 0.6), int(n * 0.8)
    sp = np.nanmedian(b.spread) * ctx.snap.point if np.isfinite(b.spread).any() else 0.0
    cost = float(sp / np.median(b.c)) if sp else 0.0

    def objective(seg):
        t, c = b.t[seg[0]:seg[1]], b.c[seg[0]:seg[1]]

        def f(x):
            cfg = K.CrossConfig(Q_fast=10 ** x[0], Q_slow=10 ** x[1], confirm_bars=int(round(x[2])))
            e = K.evaluate(t, c, cfg, horizon=12, cost=cost)
            if e["fwd_n"] < 30:
                return float("nan")                                       # too few events: invalid evaluation, never a best
            return e["fwd_mean_logret"]
        return f
    lb, ub = np.array([-2.0, -4.0, 1.0]), np.array([1.0, -1.0, 4.0])
    cfg = BZ.BuzoaConfig(pop=10, epochs=1000, max_evals=ctx.prof["buzoa_evals"], seed=ctx.seed % 10000, direction="max")
    res = BZ.buzoa(objective((0, i1)), lb, ub, cfg, cancel=ctx.cancel)
    rnd = BZ.random_search(objective((0, i1)), lb, ub, max_evals=ctx.prof["buzoa_evals"], seed=ctx.seed % 10000, direction="max")
    val = objective((i1 - 200, i2))
    default_x = [0.0, math.log10(0.005), 2.0]
    cand = {"buzoa": res["best_x"], "random": rnd["best_x"], "default": default_x}
    val_scores = {k: (val(np.array(x)) if x is not None else None) for k, x in cand.items()}
    pick = max((k for k in cand if val_scores[k] is not None and math.isfinite(val_scores[k])), key=lambda k: val_scores[k], default="default")
    guard = splits.HoldoutGuard(np.arange(i2, n))
    guard.open({"pick": pick, "x": cand[pick]})
    test_score = objective((i2 - 200, n))(np.array(cand[pick]))
    trial_count = res["evaluations"] + rnd["evaluations"]
    state = {"params": np.array(cand[pick], float)}
    aid, st = _save(ctx, "kalman_params", state, {"model_type": "KALMAN_PARAM_CANDIDATE", "feature_schema": "CLOSE_ONLY",
                                                  "target": "fwd 12-bar signed log return net cost", "trials": trial_count,
                                                  "metrics": {"val": val_scores, "test_once": test_score}, "gates": None}, False)
    return {"buzoa": {k: v for k, v in res.items() if k != "trials"}, "random_search": {k: v for k, v in rnd.items() if k not in ("trials",)},
            "val_scores": val_scores, "picked": pick, "picked_x": cand[pick], "test_once": test_score, "holdout": guard.record(),
            "trials_total": trial_count, "cost_log": cost, "artifact_id": aid, "artifact_status": st, "training_executed": True,
            "validation_passed": False, "applied_to_production": False,
            "note": "kandydat parametrów nie jest stosowany automatycznie; wybór na VAL, test otwarty raz"}


def job_breakout_zones(ctx) -> dict:
    from . import breakout_zones as BZN
    from . import robust_vol as RV
    out = {}
    for tf in ("M5", "M15", "M30"):
        b = ctx.bars(tf)
        if b is None or len(b) < 200:
            out[tf] = {"status": "NO_DATA"}
            continue
        out[tf] = {}
        for f in BZN.FILTERS:
            ev = BZN.evaluate(b, BZN.BreakoutConfig(confirmation=f), ctx.snap.point, _tf_s(tf))
            ev.pop("config", None)
            out[tf][f] = ev
    b = ctx.bars("M5")
    rv = RV.benchmark(b.h, b.l, b.c, RV.RobustVolConfig())
    return {"breakout": out, "robust_vol_m5": rv, "training": "NOT_APPLICABLE",
            "volume_note": "SESSION_VWAP ważony tick volume (proxy aktywności, nie wolumen transakcyjny)"}


def job_multi_indicator(ctx) -> dict:
    from . import multi_indicator as MI
    out = {}
    for tf in ("M5", "M15"):
        b = ctx.bars(tf)
        if b is None:
            continue
        j = MI.journal(b, MI.MIConfig(), ctx.inst, tf, _tf_s(tf))
        j.pop("rows")
        out[tf] = j
    abl = MI.ablations(ctx.bars("M5"), MI.MIConfig(), ctx.inst, "M5", 300)
    return {"journal": out, "ablations_m5": abl, "training": "NOT_APPLICABLE"}


def job_smc_fvg(ctx) -> dict:
    from . import smc_fvg as SF
    out = {}
    for tf in ("M5", "M15"):
        b = ctx.bars(tf)
        if b is None:
            continue
        out[tf] = {"PROSE_73": SF.evaluate(b, SF.SMCFVGConfig(tick=ctx.snap.tick_size), _tf_s(tf))}
        if tf == "M5":
            out[tf]["DIAGRAM_50_UNRESOLVED"] = SF.evaluate(b, SF.SMCFVGConfig(depth_min=0.5, profile="DIAGRAM_50_UNRESOLVED", tick=ctx.snap.tick_size), 300)
    return {"per_tf": out, "training": "NOT_APPLICABLE", "ambiguity": "50% z diagramu vs 73% z opisu - domyślnie 73%, 50% tylko jako jawny profil"}


def _ticks(ctx) -> tuple[list[dict], str]:
    try:
        from ..lab import tick_store
        tk = tick_store.load(ctx.inst)
        if tk:
            return tk, "REAL_TICK_ARCHIVE"
    except Exception:  # noqa: BLE001
        pass
    if not ctx.synthetic:
        return [], "NO_TICK_ARCHIVE"
    from datetime import datetime, timezone
    from ..mt5.fake import FakeMT5
    m = FakeMT5()
    m.initialize()
    end = float(ctx.snap.bars["M1"].t[-1])
    arr = m.copy_ticks_from(m.symbol, datetime.fromtimestamp(end - 6 * 3600, timezone.utc), 200_000, 0)
    tk = [{"time_msc": int(r["time_msc"]), "bid": float(r["bid"]), "ask": float(r["ask"]), "last": float(r["last"]), "volume": int(r["volume"]),
           "volume_real": float(r["volume_real"]), "flags": int(r["flags"])} for r in arr]
    return tk, "SYNTHETIC_FAKE_MT5_TICKS"


def job_tsvp(ctx) -> dict:
    from . import tsvp as TV
    ticks, src = _ticks(ctx)
    if not ticks:
        return {"status": "BLOCKED_DATA_QUALITY", "reason": "brak archiwum ticków (lab/tick_store) - wyeksportuj ticki z MT5 w panelu Dane", "source": src}
    ticks.sort(key=lambda x: x["time_msc"])
    s, e = ticks[0]["time_msc"], ticks[-1]["time_msc"]
    cfg = TV.TSVPConfig(tick=ctx.snap.tick_size)
    t0 = time.perf_counter()
    full = TV.rebuild(cfg, s, e, ticks)
    t_full = time.perf_counter() - t0
    inc = TV.Profile(cfg, s, e)
    t1 = time.perf_counter()
    k, step, ov = 0, max(50, len(ticks) // 40), 25                        # overlapping inclusive reads
    while k < len(ticks):
        lo = max(0, k - ov)
        inc.ingest(ticks[lo:k + step], read_until_ms=ticks[min(len(ticks) - 1, k + step)]["time_msc"])
        k += step
    t_inc = time.perf_counter() - t1
    same = full.map.items() == inc.map.items() and full.poc == inc.poc
    act = TV.Profile(TV.TSVPConfig(source="ACTUAL_TRADE_VOLUME", tick=ctx.snap.tick_size), s, e)
    act.ingest(ticks, read_until_ms=e)
    return {"source": src, "ticks": len(ticks), "proxy": full.summary(), "incremental_equals_rebuild": bool(same), "incremental_ignored": inc.ignored,
            "rebuild_s": t_full, "incremental_s": t_inc, "actual_volume_mode": act.summary()["status"], "training": "NOT_APPLICABLE",
            "render_note": "renderer MQL5 (PMW_TickSessionVP.mq5: OBJ_RECTANGLE czas/cena, OnTimer z budżetem wierszy) - niewykonany w tym środowisku (brak terminala)"}


def job_buzoa(ctx) -> dict:
    from . import buzoa as BZ
    return {"benchmark": BZ.benchmark(dims=(2, 10, 30) if ctx.profile == "standard" else (2, 10), seeds=(1, 2, 3, 4, 5) if ctx.profile == "standard" else (1, 2),
                                      budget=ctx.prof["bench_budget"]), "training": "NOT_APPLICABLE (optymalizator)"}


# ------------------------------------------------------------------------------------------------ trainable / online models
HDC_FEATURES = ["ret_1", "ret_3", "ret_12", "atr_rel_14", "body_rel", "dist_ema20_atr", "rsi_14", "tv_rel_48"]


def job_hdc(ctx) -> dict:
    from sklearn.linear_model import LogisticRegression

    from . import features as FE
    from . import hdc as H
    b = ctx.bars("M5")
    ds = FE.dataset(b, HDC_FEATURES, 300, 12)
    X, y, to, te = ds["X"], ds["y"], ds["t_obs"], ds["t_end"]
    sp = splits.chrono_split(to, te, (0.6, 0.2, 0.2), embargo_s=12 * 300)
    splits.assert_no_overlap(sp, to, te)
    tr, va, ts = sp["train"], sp["val"], sp["test"]
    if min(len(tr), len(va), len(ts)) < 100:
        return {"status": "BLOCKED_DATA_QUALITY", "reason": f"za mało próbek: {len(tr)}/{len(va)}/{len(ts)}"}
    space = H.Space(ctx.prof["hdc_D"], seed=ctx.seed % 100000)
    enc = H.Encoder(space, HDC_FEATURES, levels=16).fit(X[tr])
    V = [enc.record(x) for x in X]
    # online accumulation in chronological order with the label watermark (labels of train rows mature before the val block)
    clf = H.Classifier(space, 3)
    wm = float(te[tr].max())
    for i in tr:
        clf.update(V[i], int(y[i]), label_available_at=float(te[i]), watermark=wm)
    reb = H.Classifier(space, 3)
    for i in tr:
        reb.update(V[i], int(y[i]))
    exact = bool(np.array_equal(clf.acc, reb.acc)) and bool(np.array_equal(clf.finalize(), reb.finalize()))
    from .event_engine import metrics as cls_metrics

    def evaluate(c, idx):
        pred = np.array([c.predict(V[i])[0] for i in idx])
        oh = np.eye(3)[pred]
        return cls_metrics(np.clip(oh, 1e-6, 1), y[idx])
    base_val = evaluate(clf, va)
    cor = H.Classifier(space, 3)
    cor.acc = clf.acc.copy()
    cor.updates = clf.updates
    ncor = cor.correct([V[i] for i in tr], y[tr], passes=1)
    cor_val = evaluate(cor, va)
    pick = "corrections_1" if cor_val["balanced_accuracy"] > base_val["balanced_accuracy"] else "no_corrections"
    final = cor if pick == "corrections_1" else clf
    lr = LogisticRegression(max_iter=500).fit(X[tr], y[tr])
    guard = splits.HoldoutGuard(ts)
    guard.open({"model": "hdc", "pick": pick, "D": space.D})
    test = evaluate(final, ts)
    lr_test = cls_metrics(lr.predict_proba(X[ts]), y[ts])
    maj = int(np.bincount(y[tr]).argmax())
    maj_test = cls_metrics(np.clip(np.eye(3)[np.full(len(ts), maj)], 1e-6, 1), y[ts])
    rng = np.random.Generator(np.random.PCG64(ctx.seed))
    blk = 288
    ysh = y[tr].copy()
    starts = np.arange(0, len(ysh), blk)
    perm = rng.permutation(len(starts))
    ysh = np.concatenate([y[tr][starts[p]:starts[p] + blk] for p in perm])[: len(tr)]
    null = H.Classifier(space, 3)
    for i, yy in zip(tr, ysh):
        null.update(V[i], int(yy))
    null_test = evaluate(null, ts)
    se = math.sqrt(0.25 / len(ts))
    g = GATES["hdc"]
    gates = {"n_test>=min": len(ts) >= g["min_test"], "beats_logreg": test["balanced_accuracy"] > lr_test["balanced_accuracy"] + g["beat_logreg"],
             "beats_block_null_2se": test["balanced_accuracy"] > null_test["balanced_accuracy"] + g["beat_null_se"] * se}
    passed = all(gates.values()) and not ctx.synthetic
    lat = H.measure_update_latency(space, enc, X[tr], y[tr], 200)
    state = {"roles": enc.roles, "levels": enc.levels, "tie": space.tie, "acc": final.acc, "lo": enc.lo, "hi": enc.hi,
             "meta": np.array([space.D, space.seed, enc.L, 3])}
    aid, st = _save(ctx, "hdc_dir3", state, {"model_type": "HDC_CLASSIFIER", "feature_schema": ds["schema"], "features": HDC_FEATURES,
                                             "target": ds["target"], "intervals": sp["intervals"], "hyper": {"D": space.D, "levels": 16, "pick": pick},
                                             "metrics": {"val": cor_val if pick == "corrections_1" else base_val, "test_once": test}, "gates": gates}, passed)
    return {"n": {"train": int(len(tr)), "val": int(len(va)), "test": int(len(ts))}, "split": {k: v for k, v in sp.items() if k in ("intervals", "purged")},
            "online_equals_rebuild_bit_exact": exact, "corrections_applied": int(ncor), "picked": pick, "val": {"no_corrections": base_val, "corrections_1": cor_val},
            "test_once": test, "baselines_test": {"logreg": lr_test, "majority": maj_test, "block_shuffled_null_hdc": null_test}, "noise_model": space.null(3.0),
            "latency": lat, "gates": gates, "artifact_id": aid, "artifact_status": st, "training_executed": True, "validation_passed": passed,
            "holdout": guard.record()}


def job_gpr(ctx) -> dict:
    from . import gpr as G
    from .ledger import Ledger
    b = ctx.bars("M5")
    n = len(b.t)
    cfg = G.GPRConfig()
    i1, i2 = int(n * 0.6), int(n * 0.8)
    step = ctx.prof["gpr_step"]
    val = G.walk_forward(b.t, b.c, cfg, max(i1, cfg.window + cfg.horizon + 2), i2 - cfg.horizon, step, cancel=ctx.cancel)
    cal_val = G.calibration(val["rows"])
    guard = splits.HoldoutGuard(np.arange(i2, n))
    guard.open({"model": "gpr", "cfg": cfg.__dict__})
    led = Ledger(artifacts.root(ctx.inst) / "ledger.sqlite")
    model = val["model"]
    ledger_mid = f"gpr_logret:{ctx.snap.snapshot_id}"
    test = G.walk_forward(b.t, b.c, cfg, i2, n, step, ledger=led, symbol=ctx.inst, tf="M5", tf_s=300, model_id=ledger_mid, artifact_id=None,
                          cancel=ctx.cancel)
    c = np.asarray(b.c, float)
    tidx = {float(t): i for i, t in enumerate(b.t)}

    def resolver(row):
        i = tidx.get(float(row["source_ts"]))
        h = int(row["horizon"].replace("bars", ""))
        if i is None or i + h >= len(c):
            return None
        p = __import__("json").loads(row["payload"])
        real = math.log(c[i + h] / c[i])
        z = (real - p["pred"]) / p["sd"]
        return {"realized_logret": real, "z": z, "in_1sd": abs(z) <= 1, "in_2sd": abs(z) <= 2, "matured_bar_ts": float(b.t[i + h])}
    matured = led.mature(float(b.t[-1]) + 300, resolver, ledger_mid)
    cal_test = G.calibration(test["rows"])
    g = GATES["gpr"]
    gates = {"min_scored": cal_test.get("n_scored", 0) >= g["min_scored"],
             "cov1_band": g["cov1"][0] <= cal_test.get("coverage_1sd", -1) <= g["cov1"][1],
             "cov2_band": g["cov2"][0] <= cal_test.get("coverage_2sd", -1) <= g["cov2"][1],
             "mae_not_worse_than_zero": cal_test.get("n_scored", 0) > 0 and cal_test["mae"]["gp"] <= g["mae_vs_zero_max_ratio"] * cal_test["mae"]["zero"]}
    passed = all(gates.values()) and not ctx.synthetic
    state = model.state() if model.fit is not None else {"empty": np.zeros(1)}
    aid, st = _save(ctx, "gpr_logret", state, {"model_type": "GPR_MATERN32", "feature_schema": "GPR_LAG1_LOGRET", "config": cfg.__dict__,
                                               "target": f"ln(C[t+{cfg.horizon}]/C[t])", "ledger_model_id": ledger_mid,
                                               "metrics": {"val": cal_val, "test_once": cal_test}, "gates": gates,
                                               "state_note": "ostatnie dopasowanie z końca okna walidacji (start na żywo); GP i tak dopasowuje się co świecę"}, passed)
    return {"config": cfg.__dict__, "grid_note": G.GRID_NOTE, "val_calibration": cal_val, "test_calibration_once": cal_test, "ledger_matured": matured,
            "failures": {"val": val["failures"], "test": test["failures"]}, "last_search": test["last_search"], "gates": gates, "artifact_id": aid,
            "artifact_status": st, "ledger_model_id": ledger_mid, "training_executed": True, "validation_passed": passed, "holdout": guard.record(),
            "separate_claims": {"numerical_correctness": "testy jednostkowe (kernel, Cholesky, LML, wariancje)", "point_forecast_vs_baselines": cal_test.get("mae"),
                                "uncertainty_calibration": {k: cal_test.get(k) for k in ("coverage_1sd", "coverage_2sd")}, "trading_usefulness": "NOT_EVALUATED"}}


def _events(ctx):
    from . import data as D
    from . import events as EV
    src = None
    try:
        from ..lab import tick_store
        tk = tick_store.load(ctx.inst)
        if tk and len(tk) > 20000:
            ev = D.events_from_ticks(tk)
            src = "REAL_TICKS"
    except Exception:  # noqa: BLE001
        tk = None
    if src is None:
        ev = D.events_from_bars(ctx.bars("M1"), ctx.snap.point)
        src = "BAR_CLOSE_EVENTS"
    acc = EV.from_arrays(ev, ctx.inst, 900)
    return acc, EV.featurize(acc), src


def job_event_engine(ctx) -> dict:
    from sklearn.linear_model import LogisticRegression

    from . import event_engine as EE
    from . import events as EV
    from .stfs import STFS
    acc, fe, src = _events(ctx)
    u = EV.units(acc, fe, 16)
    tg = EV.unit_targets(u, 2)
    idx = np.where(tg["ok"])[0]
    if len(idx) < 600:
        return {"status": "BLOCKED_DATA_QUALITY", "reason": f"za mało jednostek: {len(idx)}"}
    sp = splits.chrono_split(u["t_end"][idx], tg["t_label"][idx], (0.6, 0.2, 0.2), 0.0)
    splits.assert_no_overlap(sp, u["t_end"][idx], tg["t_label"][idx])
    tr, va, ts = idx[sp["train"]], idx[sp["val"]], idx[sp["test"]]
    band = float(0.25 * np.median(np.abs(tg["r"][tr])))
    y = EV.classify(np.nan_to_num(tg["r"]), band)
    sc = EV.Scaler().fit(u["X"][tr])
    X = sc.transform(u["X"])
    seg = u["segment"]
    ep = ctx.prof["epochs"]
    variants = {}
    for name, kw in (("full", {}), ("no_stack", {"use_stack": False}), ("full_stfs", {"stfs": STFS(seed=ctx.seed % 1000)})):
        r = EE.train(X[tr], y[tr], seg[tr], X[va], y[va], seg[va], epochs=ep, seed=ctx.seed % 1000, cancel=ctx.cancel, **kw)
        pv = EE.predict(r["model"], X[va], seg[va])
        variants[name] = {"res": r, "val": EE.metrics(pv, y[va])}
    pick = min(variants, key=lambda k: variants[k]["val"]["log_loss"])
    m = variants[pick]["res"]["model"]
    guard = splits.HoldoutGuard(ts)
    guard.open({"model": "event_engine", "pick": pick})
    test = EE.metrics(EE.predict(m, X[ts], seg[ts]), y[ts])
    prior = np.bincount(y[tr], minlength=3) / len(tr)
    prior_test = EE.metrics(np.tile(prior, (len(ts), 1)), y[ts])
    last_dm = X[:, :, 1].sum(axis=1)
    pers = np.where(last_dm > 0, 2, np.where(last_dm < 0, 0, 1))
    pers_p = np.clip(np.eye(3)[pers[ts]] * 0.8 + 0.2 / 3, 1e-6, 1)
    summ = np.column_stack([u["X"][:, :, k].sum(axis=1) for k in (1, 2)] + [u["X"][:, :, k].mean(axis=1) for k in (0, 4, 6)])
    lr = LogisticRegression(max_iter=500).fit((summ[tr] - summ[tr].mean(0)) / (summ[tr].std(0) + 1e-12), y[tr])
    lr_test = EE.metrics(lr.predict_proba((summ[ts] - summ[tr].mean(0)) / (summ[tr].std(0) + 1e-12)), y[ts])
    stfs_cmp = {k: {"val_log_loss": variants[k]["val"]["log_loss"], "val_bacc": variants[k]["val"]["balanced_accuracy"], "n_params": variants[k]["res"]["n_params"],
                    "train_s": variants[k]["res"]["train_s"]} for k in ("full", "full_stfs")}
    # online runtime replay on the first test units (identical math, real streaming path) + latency + backend
    rt = EE.Runtime(m, sc, 16, ctx.inst, "candidate", 900.0)
    first = int(u["first_event"][ts[0]])
    seg_start = int(np.where(acc["segment"] == acc["segment"][first])[0][0])
    out_probs = []
    k0 = seg_start
    for k in range(k0, min(len(acc["t"]), first + 16 * 200)):
        spok = bool(np.isfinite(acc["spread"][k]))
        sp_ = acc["spread"][k] if spok else 0.0
        r = rt.push({"t": float(acc["t"][k]), "bid": float(acc["mid"][k] - sp_ / 2), "ask": float(acc["mid"][k] + sp_ / 2), "activity": float(acc["activity"][k]),
                     "spread_ok": spok})
        if r and r.get("status") == "OK":
            out_probs.append((float(r["source_ts"]), r["probs"]))
    off = EE.predict(m, X, seg)
    t_end_to_u = {float(t): i for i, t in enumerate(u["t_end"])}
    diffs = [float(np.max(np.abs(np.array(p) - off[t_end_to_u[t]]))) for t, p in out_probs if t in t_end_to_u]
    g = GATES["event_engine"]
    gates = {"n_test>=min": len(ts) >= g["min_test"], "logloss_gain_vs_prior": test["log_loss"] < prior_test["log_loss"] - g["logloss_gain_vs_prior"],
             "ece<=max": test["ece_top_label"] <= g["max_ece"]}
    passed = all(gates.values()) and not ctx.synthetic
    st = {**m.state(), "scaler_med": sc.med, "scaler_iqr": sc.iqr, "band": np.array([band])}
    aid, ast = _save(ctx, "event_engine_dir3", st, {"model_type": "EVENT_GRU_STACK", "feature_schema": "PMW-MM-EVENT-1:" + ",".join(EV.FEATURES),
                                                     "target": f"DIR3 unit k=2 band={band:.3e}", "event_source": src, "pick": pick,
                                                     "metrics": {"val": variants[pick]["val"], "test_once": test}, "gates": gates}, passed)
    return {"event_source": src, "ingest_counts": acc["counts"], "units": {"train": int(len(tr)), "val": int(len(va)), "test": int(len(ts))}, "band": band,
            "variants_val": {k: v["val"] for k, v in variants.items()}, "picked": pick, "test_once": test,
            "baselines_test": {"prior": prior_test, "persistence": EE.metrics(pers_p, y[ts]), "logreg_unit_summary": lr_test},
            "stfs": stfs_cmp, "online_offline_max_prob_diff": max(diffs) if diffs else None, "online_units_compared": len(diffs),
            "latency_us": rt.latency(), "backend_used": rt.stack.backend_used, "backend_note": rt.stack.cl_error, "gates": gates, "artifact_id": aid,
            "artifact_status": ast, "training_executed": True, "validation_passed": passed, "holdout": guard.record(),
            "gradient_semantics": "gradient tylko do bieżącego deskryptora (top); historia stosu = stała pamięć (brak BPTT między jednostkami)"}


def job_stfs(ctx) -> dict:
    ev = ctx.results.get("event_engine") or {}
    s = ev.get("stfs")
    if not s:
        return {"status": "BLOCKED_DEPENDENCY", "reason": "brak wyników event_engine"}
    better = s["full_stfs"]["val_log_loss"] < s["full"]["val_log_loss"]
    return {"comparison_val": s, "stfs_better_on_val": better, "sampling_params": 0, "param_count_equal": s["full"]["n_params"] == s["full_stfs"]["n_params"],
            "training_executed": True, "validation_passed": False, "insertion_point": "po enkoderze GRU zdarzeń (mapa cech [B,T,C]); SSAM nie istnieje",
            "note": "porównanie na tych samych splitach i ziarnie; przewaga tylko jeśli potwierdzi się poza próbą na danych rzeczywistych"}


def job_ste_flownet(ctx) -> dict:
    from . import ste_flownet as SF
    acc, fe, src = _events(ctx)
    smp = SF.build_samples(acc, fe, 8, 16, 32)
    ok = np.where(np.isfinite(smp["y"]))[0]
    if len(ok) < 600:
        return {"status": "BLOCKED_DATA_QUALITY", "reason": f"za mało próbek: {len(ok)}"}
    sp = splits.chrono_split(smp["t_obs"][ok], smp["t_label"][ok], (0.6, 0.2, 0.2), 0.0)
    splits.assert_no_overlap(sp, smp["t_obs"][ok], smp["t_label"][ok])
    tr, va, ts = ok[sp["train"]], ok[sp["val"]], ok[sp["test"]]
    smp_nw = SF.build_samples(acc, fe, 8, 16, 32, weighting=False)

    def norm(Xs):
        mu, sd = Xs[tr].reshape(-1, Xs.shape[2]).mean(0), Xs[tr].reshape(-1, Xs.shape[2]).std(0) + 1e-12
        return (Xs - mu) / sd, mu, sd
    XS, mu, sd = norm(smp["X"])
    XN, _, _ = norm(smp_nw["X"])
    y = smp["y"]
    ep = ctx.prof["epochs"]
    variants = {"full": (XS, {}), "no_temporal_weighting": (XN, {}), "no_recurrence": (XS, {"recurrence": False}),
                "no_correlation": (XS, {"correlation": False}), "no_refinement_K1": (XS, {"K": 1})}
    res = {}
    for k, (Xv, arch) in variants.items():
        r = SF.train(Xv[tr], y[tr], Xv[va], y[va], epochs=ep, seed=ctx.seed % 1000, cancel=ctx.cancel, **arch)
        res[k] = {"res": r, "val": SF.reg_metrics(r["model"].predict(Xv[va]), y[va])}
    pick = min(res, key=lambda k: res[k]["val"]["mae"])
    guard = splits.HoldoutGuard(ts)
    guard.open({"model": "ste_flownet", "pick": pick})
    Xp = variants[pick][0]
    m = res[pick]["res"]["model"]
    test = SF.reg_metrics(m.predict(Xp[ts]), y[ts])
    zero = SF.reg_metrics(np.zeros(len(ts)), y[ts])
    lag = XS[:, -1, 2] * sd[2] + mu[2]                                        # last split's weighted sum of dmid (price units)
    A_ = np.column_stack([np.ones(len(tr)), lag[tr]])
    beta = np.linalg.lstsq(A_, y[tr], rcond=None)[0]
    ols = SF.reg_metrics(beta[0] + beta[1] * lag[ts], y[ts])
    g = GATES["ste_flownet"]
    gates = {"n_test>=min": len(ts) >= g["min_test"], "mae_gain_vs_zero": test["mae"] < zero["mae"] * (1 - g["mae_gain_vs_zero"])}
    passed = all(gates.values()) and not ctx.synthetic
    st = {**m.state(), "x_mu": mu, "x_sd": sd}
    aid, ast = _save(ctx, "ste_flownet_ret", st, {"model_type": "STE_FLOWNET_FIN_ADAPT", "feature_schema": "STE-SPLITS-8x16:" + ",".join(SF.CHANNELS),
                                                   "target": "ln(mid[e+32]/mid[e])", "event_source": src, "pick": pick,
                                                   "metrics": {"val": res[pick]["val"], "test_once": test}, "gates": gates}, passed)
    return {"event_source": src, "samples": {"train": int(len(tr)), "val": int(len(va)), "test": int(len(ts))}, "ablations_val": {k: v["val"] for k, v in res.items()},
            "n_params": {k: v["res"]["n_params"] for k, v in res.items()}, "picked": pick, "test_once": test,
            "baselines_test": {"zero": zero, "ols_last_split_dmid": ols}, "gates": gates, "artifact_id": aid, "artifact_status": ast,
            "training_executed": True, "validation_passed": passed, "holdout": guard.record(), "backend_used": "CPU (numpy autodiff)",
            "loss": "Huber(final) + sum 0.5^(K-k) Huber(iter_k) + 0.3 Huber(aux level-2)"}


def job_mathbench(ctx) -> dict:
    from . import mathbench as MB
    out = ctx.out / "mathbench"
    man = MB.export(out, seed=ctx.seed)
    chk = MB.python_checks(out)
    return {"manifest": man, "python_checks": chk, "files_dir": str(out), "mql5": "NOT_EXECUTED - brak MetaEditor/terminala MT5 w tym środowisku",
            "training": "NOT_APPLICABLE (benchmark; jednorazowy trening wag referencyjnych na syntetyce)"}


def job_fusion_board(ctx) -> dict:
    from .contracts import Envelope, ModelOutput
    from .fusion import board
    b = ctx.bars("M5")
    t_last = float(b.t[-1]) + 300
    outs = []

    def add(src, kind, payload, tf="M5", ver=None, q=None):
        env = Envelope(src, ctx.inst, tf, t_last - 300, t_last, q or ("SYNTHETIC_TEST" if ctx.synthetic else "OK"), model_version=ver)
        outs.append(ModelOutput(env, kind, payload).to_dict())
    am = ((ctx.results.get("align_mean") or {}).get("per_tf") or {}).get("M5", {}).get("latest")
    if am:
        add("align_mean", "INDICATOR_STATE", {"dist_atr": am.get("dist_atr"), "mean": am.get("mean")})
    kl = ((ctx.results.get("kalman") or {}).get("per_tf") or {}).get("M5", {})
    if kl:
        d = kl.get("last_state", "")
        add("kalman", "INDICATOR_STATE", {"direction": "BULLISH" if "BULLISH" in d else "BEARISH" if "BEARISH" in d else None, "state": d})
    bz = (((ctx.results.get("breakout_zones") or {}).get("breakout") or {}).get("M5") or {}).get("SESSION_VWAP", {})
    if bz.get("panel"):
        add("breakout_zones", "INDICATOR_STATE", {"direction": bz["panel"]["direction"] if bz["panel"]["direction"] != "NONE" else None})
    g = ctx.results.get("gpr") or {}
    if g.get("artifact_id"):
        add("gpr", "GAUSSIAN_PREDICTIVE", {"horizon": "3 bars", "note": "ostatnia prognoza w ledgerze"}, ver=g["artifact_id"])
    return {"board": board(outs, ctx.inst, now=t_last), "training": "NOT_APPLICABLE"}
