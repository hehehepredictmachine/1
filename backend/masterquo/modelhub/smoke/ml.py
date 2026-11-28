"""Smoke checks of the ML area (`models check --smoke --area ml`): SH event model, legacy Decision Tree + XGBoost, Scalp ML, Claude agent
(request shape only, no API call) and the WF3.2 model layers (decision-tree ranker, association rules, PT test, PELT, long horizon).

Every function goes through the bot's own code on SYNTHETIC_TEST data: the training export of the synthetic terminal (the same
`training export --synthetic` path: FakeMT5 as MetaTrader5), the trainers and registries (sh train_cli / tpmodel, the ml trainer
subprocess started by MLService, scalp_task), the services the bot calls (MLService.gate / on_scalp_candidate, tpmodel.predict) and the
real FastAPI route functions of api/wf32_routes.register (collected by a stand-in app, no HTTP server). Technical checks only.
"""
from __future__ import annotations

import math
import time
from datetime import UTC

from . import check, fail, unverified

INST = "XAUUSD"
_CACHE: dict = {}


# ---------------------------------------------------------------------------------------------------------------- shared helpers
def _quiet(fn, *a, **k):
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


def _dataset(ctx):
    """Synthetic training export (1 month M1..H1) written by forecast.export.export_candles with FakeMT5 as the MetaTrader5 module -
    exactly what `python -m masterquo training export --synthetic` does (training/cli.py cmd_export). One export per area process."""
    d = ctx.data_dir / "smoke_ml_export"
    if (d / "source_metadata.json").exists():
        return d
    import sys

    from ...mt5.fake import FakeMT5
    prev = sys.modules.get("MetaTrader5")
    sys.modules["MetaTrader5"] = FakeMT5()
    try:
        from ...forecast.export import export_candles
        rc = _quiet(export_candles, 1, str(d), "AUTO", ("M1", "M5", "M15", "M30", "H1"), "training", INST, "XAUUSD-")
    finally:
        if prev is None:
            sys.modules.pop("MetaTrader5", None)
        else:
            sys.modules["MetaTrader5"] = prev
    if rc != 0 or not (d / "source_metadata.json").exists():
        raise RuntimeError(f"eksport syntetyczny zakończony kodem {rc}")
    return d


class _MLBridge:
    """Bridge surface MLService reads (synthetic flag selects the SYNTHETIC sample world - never mixed with real samples)."""
    synthetic = True
    account_key = "SYN:1"

    def __init__(self):
        self.symbol_info = {"point": 0.01, "trade_contract_size": 100.0, "spread": 12}

    class clock:
        offset = 0

    def account_status(self):
        return {"server": "Synthetic", "login": 1, "trade_mode": "DEMO"}

    def quote_status(self):
        return {"bid": 2000.0, "ask": 2000.1, "spread": 0.1, "age_seconds": 1.0}

    def bars(self, tf, include_forming=True):
        return []


def _wf32(ctx) -> dict:
    """Route functions of api/wf32_routes.register (the app the bot serves) collected by a stand-in app; bridge = closed FakeMT5 bars."""
    if "wf32" in _CACHE:
        return _CACHE["wf32"]
    import threading
    from types import SimpleNamespace

    from ...api import wf32_routes
    series = {tf: ctx.bars(tf, n) for tf, n in (("H1", 2000), ("M15", 1500))}

    class Bridge:
        def bars(self, tf, count=None, include_forming=False):
            rows = series.get(tf) or []
            return list(rows[-count:] if count else rows)

    class App:
        def __init__(self):
            self.routes = {}

        def __getattr__(self, method):
            def deco(path, *a, **k):
                def wrap(fn):
                    self.routes[(method, path)] = fn
                    return fn
                return wrap
            return deco

    app = App()
    rt = SimpleNamespace(bridge=Bridge(), db=None, _acct_thread=True, _stop=threading.Event())
    wf32_routes.register(app, rt)
    _CACHE["wf32"] = {"routes": app.routes, "n_h1": len(series["H1"])}
    return _CACHE["wf32"]


def _route(ctx, method: str, path: str, *a, **k):
    return _wf32(ctx)["routes"][(method, path)](*a, **k)


# ---------------------------------------------------------------------------------------------------------------- sh:tp_model
def _tp_samples(n: int, seed: int = 11) -> list[dict]:
    import numpy as np

    from ...sh import tpmodel as TM
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, len(TM.FEATURES)))
    y = (rng.random(n) < 1.0 / (1.0 + np.exp(-(1.5 * X[:, 0] - 1.0 * X[:, 3])))).astype(int)
    t0 = time.time() - 86400.0 * 60
    return [{"t": t0 + 600.0 * i, "x": X[i].tolist(), "y": int(y[i])} for i in range(n)]


def _tp_model(ctx) -> dict:
    """sh train_cli (replay of the synthetic export -> tpmodel.train, no promotion, no live write) + tpmodel.train on synthetic samples
    (promotion refused for test data) -> technical activation -> npz roundtrip -> tpmodel.predict (sh/service.py:229-230)."""
    import json

    from ... import paths
    from ...evaluation.service import EvaluationService
    from ...sh import tpmodel as TM
    from ...sh import train_cli as TC
    ctx.step = "train"
    ds = _dataset(ctx)
    out = ctx.data_dir / "smoke_sh_train" / "sh_models.json"
    t0 = time.monotonic()
    refused = None
    try:
        TC.train(ds, INST, out, last_m1=600, strategies=("SCALPING",), log=lambda m: None, live_write=False)
    except ValueError as exc:
        refused = str(exc)
    r = TC.train(ds, INST, out, allow_synthetic=True, last_m1=1500, strategies=("SCALPING",), min_n=200, log=lambda m: None, live_write=False)
    sc = r["strategies"].get("SCALPING") or {}
    mdl = sc.get("model") or {}
    live_file = paths.data_dir() / "sh" / "validation" / f"{INST}_SCALPING.json"
    cli_ok = (r.get("status") == "DONE" and r.get("data_kind") == "SYNTHETIC_TEST" and not mdl.get("promoted") and not live_file.exists()
              and (refused or "").startswith("SYNTHETIC_DATA_REQUIRES"))
    if not cli_ok:
        return {"train": fail(f"sh train_cli: status {r.get('status')}, data_kind {r.get('data_kind')}, model {mdl}, plik walidacji na żywo "
                              f"{live_file.exists()}, odmowa bez --allow-synthetic: {refused}")}
    samples = _tp_samples(800)
    rec = TM.train(INST, "SCALPING", samples, embargo_s=1800.0, min_n=200, log=lambda m: None, allow_promotion=False,
                   provenance={"data_kind": "SYNTHETIC_TEST", "dataset_id": "SMOKE"})
    gate = None
    try:
        TM.promote(INST, "SCALPING", rec["run_id"])
    except ValueError as exc:
        gate = str(exc)
    st0, pr0 = TM.status(INST, "SCALPING")["status"], TM.predict(INST, "SCALPING", samples[0]["x"])["status"]
    # technical activation (temporary folder only): tpmodel.train with allow_promotion=True - the flag the caller owns (train_cli passes
    # `real and live_write`); provenance stays SYNTHETIC_TEST
    rec2 = TM.train(INST, "SCALPING", samples, embargo_s=1800.0, min_n=200, log=lambda m: None, allow_promotion=True,
                    provenance={"data_kind": "SYNTHETIC_TEST", "dataset_id": "SMOKE", "note": "aktywacja techniczna smoke"})
    dt = time.monotonic() - t0
    good = (rec["verdict"] == "HOLDOUT_PASSED" and not rec["promoted"] and gate == "DANE_TESTOWE_BEZ_PROMOCJI" and st0 == "SHADOW_ONLY"
            and pr0 == "NOT_TRAINED" and rec2["promoted"])
    steps = {"train": check(good, f"train_cli (replay 1500 M1 eksportu SYNTHETIC_TEST): {r['status']}, SCALPING {sc.get('setups_ready')} setupów -> "
                                  f"{mdl.get('verdict')}, bez promocji i bez data/sh/validation; bez --allow-synthetic: odmowa; tpmodel.train 800 próbek: "
                                  f"{rec['verdict']}, promote -> {gate} (bramka), status {st0}, predict {pr0}; "
                                  f"aktywacja techniczna -> {rec2['run_id']}; {dt:.1f} s",
                            f"tpmodel: {rec.get('verdict')} promoted={rec.get('promoted')}, promote {gate}, status {st0}, predict {pr0}, "
                            f"techniczny promoted={rec2.get('promoted')}")}
    if steps["train"]["status"] != "OK":
        return steps
    ctx.step = "artifact"
    rid = rec2["run_id"]
    reg = json.loads((TM.root(INST, "SCALPING") / "registry.json").read_text(encoding="utf-8"))
    run = next(x for x in reg["runs"] if x["run_id"] == rid)
    import hashlib
    sha_ok = hashlib.sha256((TM.root(INST, "SCALPING") / f"{rid}.npz").read_bytes()).hexdigest() == run.get("sha256")
    hold = samples[int(0.8 * len(samples)):]
    ps = [TM.predict(INST, "SCALPING", s["x"])["p"] for s in hold]
    brier = sum((p - s["y"]) ** 2 for p, s in zip(ps, hold)) / len(hold)
    diff = abs(brier - rec2["holdout"]["brier"])
    steps["artifact"] = check(sha_ok and reg.get("active") == rid and diff < 1e-9 and len(hold) == rec2["split"]["holdout"],
                              f"{rid}.npz (sha256 zgodny z rejestrem, aktywny) -> odczyt przez tpmodel.predict odtwarza Brier holdoutu "
                              f"{brier:.6f} (różnica {diff:.1e}, n={len(hold)})",
                              f"sha256 {sha_ok}, aktywny {reg.get('active')}, Brier {brier} vs {rec2['holdout']['brier']}, n {len(hold)}/{rec2['split']}")
    ctx.step = "predict"
    f = ctx.fake()
    last = ctx.bars("M1", 2)[-1]
    ref = round(float(last["c"]), 2)
    su = {"side": "BUY", "entry_ref": ref, "sl": ref - 2.0, "tps": [{"distance_actual": 1.0}, {"distance_actual": 2.0}], "created_at": float(last["t"]) + 60,
          "mode": "CONTINUATION", "net_rr": 1.2, "args_against": [], "status": "READY"}
    snap = {"vol": {"atr_m1": 0.8, "atr_m5": 2.0}, "ctx": {"vamd_m5": 0.3, "vamd_m1": 0.1, "fd_zone_m5": "TREND"}, "structure_H1": {"major": "UP"},
            "data": {"spread": 0.2}, "regime": {"state": "TREND_UP"}}
    x = TM.features(su, snap)
    pr = TM.predict(INST, "SCALPING", x) if su["status"] == "READY" and TM.status(INST, "SCALPING").get("status") == "READY" else {}
    p = pr.get("p")
    steps["predict"] = check(pr.get("status") == "READY" and isinstance(p, float) and 0.0 <= p <= 1.0 and pr.get("version") == rid,
                             f"jak sh/service.py:229-230: status READY -> tpmodel.predict(features(setup, snapshot)) = {pr.get('status')} p={p} "
                             f"(model {pr.get('version')}; setup na cenie FakeMT5 {f.symbol} {ref})",
                             f"predict: {pr}")
    ctx.step = "contract"
    ncal = EvaluationService._sh_n_cal(INST, "SCALPING")                      # the evaluation ledger reads the calibration size
    errs = []
    if len(x) != len(TM.FEATURES) or not all(math.isfinite(v) for v in x):
        errs.append(f"wektor cech {len(x)} != {len(TM.FEATURES)} lub nieskończony")
    if set(pr) != {"status", "p", "version"}:
        errs.append(f"klucze wyniku {sorted(pr)}")
    if ncal != rec2["split"]["cal"]:
        errs.append(f"EvaluationService._sh_n_cal {ncal} != split cal {rec2['split']['cal']}")
    steps["contract"] = check(not errs, f"{TM.VERSION}: {len(x)} cech {TM.FEATURES[0]}…{TM.FEATURES[-1]}, wynik {{status, p, version}}, "
                                        f"n_calibration dla ledgera ewaluacji = {ncal}", "; ".join(errs))
    return steps


# ---------------------------------------------------------------------------------------------------------------- ml:legacy_s01_s12
def _ml_rows(n: int, seed: int = 1) -> list[dict]:
    """Labelled S01-S12 samples (feature schema of ml/features.py) with a real noisy dependence on two features; time ordered."""
    import json
    import random
    from datetime import datetime, timedelta

    from ...ml import features as fe
    rng = random.Random(seed)
    t = datetime(2026, 3, 2, 8, 0, tzinfo=UTC)

    def iso(d):
        return d.isoformat().replace("+00:00", "Z")
    rows = []
    for i in range(n):
        t += timedelta(minutes=rng.choice((15, 30, 45)))
        f = {k: None for k in fe.FEATURE_NAMES}
        a, b = rng.gauss(0, 1), rng.gauss(0, 1)
        f.update({"M15_rsi": 50 + 10 * a, "M5_er20": 0.5 + 0.2 * b, "M15_atr_pct": abs(rng.gauss(0.2, 0.05)), "hour_sin": math.sin(t.hour / 24 * 2 * math.pi),
                  "M5_ret3": rng.gauss(0, 1) if rng.random() > 0.1 else None, "strategy_id": rng.choice(["S01", "S03", "S08"]),
                  "direction": rng.choice(["LONG", "SHORT"]), "timeframe": "M15", "regime": rng.choice(["TREND_UP", "RANGE"]), "family": "TREND"})
        y = int(rng.random() < 1 / (1 + math.exp(-(1.2 * a - 0.8 * b))))
        rows.append({"sample_id": f"SM{i}:1", "setup_id": f"SM{i}", "group_id": f"SM{i}", "event_id": f"E{i // 2}", "strategy_id": f["strategy_id"],
                     "direction": f["direction"], "asof_utc": iso(t), "label_end_utc": iso(t + timedelta(minutes=rng.choice((20, 60, 180)))),
                     "label_known_utc": iso(t + timedelta(minutes=200)), "features_json": json.dumps(fe.to_json_safe(f)), "label": y,
                     "outcome_r": (1.2 if y else -1.0) + rng.gauss(0, 0.1), "feature_schema_version": fe.FEATURE_SCHEMA_VERSION})
    return rows


def _legacy(ctx) -> dict:
    """MLService.start_training (labelled synthetic samples -> immutable snapshot -> `python -m masterquo.ml.trainer` subprocess) ->
    _poll_job -> Registry.register (champion) -> fresh MLService (champion loaded from disk) -> predict / gate / rank_adjust."""
    import json

    from ...config import ConfigStore
    from ...db.database import Database
    from ...events import AppLog, EventBus
    from ...ml.service import PRED_CONTRACT, MLService
    ctx.step = "train"
    cfg = ConfigStore()
    cfg.update({"ml": {"dt_tuning_budget": 8, "xgb_tuning_budget": 3, "xgb_max_trees": 150, "xgb_threads": 1,
                       "promotion": {"min_test_samples": 100, "min_test_per_class": 20}}})
    db = Database(ctx.data_dir / "smoke_ml_legacy.sqlite")
    bus = EventBus()
    log = AppLog(db, bus)
    root = ctx.data_dir / "smoke_ml_legacy"
    ml = MLService(cfg, db, _MLBridge(), bus, log, root=root)
    rows = _ml_rows(1000)
    now = "2026-11-01T00:00:00Z"
    for r in rows:
        db.execute("""INSERT INTO ml_samples(sample_id, setup_id, setup_version, group_id, event_id, symbol, feed_id, strategy_id, strategy_version, direction,
                      timeframe, asof_utc, feature_schema_version, features_json, entry_json, cost_model_version, label_policy_version, source, quality,
                      status, label, outcome_r, label_end_utc, label_known_utc, synthetic, created_at, updated_at)
                      VALUES (?,?,1,?,?,'XAUUSD-','SYN',?,'1',?,'M15',?,?,?,'{}','c','l','SMOKE','HIGH','LABELED',?,?,?,?,1,?,?)""",
                   (r["sample_id"], r["setup_id"], r["group_id"], r["event_id"], r["strategy_id"], r["direction"], r["asof_utc"], r["feature_schema_version"],
                    r["features_json"], r["label"], r["outcome_r"], r["label_end_utc"], r["label_known_utc"], now, now))
    t0 = time.monotonic()
    st = ml.start_training("SMOKE", force=True)
    if not st.get("started"):
        return {"train": fail(f"MLService.start_training: {st}")}
    while ml._job is not None and time.monotonic() - t0 < 150:
        ml._poll_job()
        time.sleep(0.3)
    if ml._job is not None:                                                     # never leave a trainer process behind the area worker
        ml.stop()
    job = db.one("SELECT status, detail_json FROM ml_jobs WHERE job_id=?", (st["job_id"],)) or {}
    det = json.loads(job.get("detail_json") or "{}")
    dec = det.get("decisions") or {}
    dt = time.monotonic() - t0
    cands = ", ".join(str(d.get("family")) + ":" + ("OK" if d.get("passed") else "ODRZUCONY") for d in dec.values())
    # 1.46 D6: the bot's job applies the one promotion policy (training/promotion.py) - synthetic samples never make a champion. The
    # remaining steps need a loaded champion: the best passing candidate is promoted explicitly in this temporary smoke database only.
    pol = det.get("promotion_policy") or {}
    gate_ok = ml.registry.champion_id is None and pol.get("role") == "FIXTURE_ONLY"
    passing = sorted(((m, d) for m, d in dec.items() if d.get("passed")), key=lambda x: x[1].get("family") != "XGBOOST")
    if job.get("status") == "DONE" and gate_ok and passing:
        ml.registry.promote(passing[0][0], "SMOKE_TECHNICAL_PROMOTION (dane syntetyczne, tymczasowa baza smoke)")
    champ = ml.registry.champion_id
    steps = {"train": check(job.get("status") == "DONE" and gate_ok and champ is not None and len(dec) == 2,
                            f"podproces masterquo.ml.trainer na snapshocie {st['snapshot_id']} ({st['rows']} próbek SYNTHETIC, HIGH): DONE w {dt:.1f} s; "
                            f"kandydaci {cands}; polityka promocji {pol.get('role')} – bez championa z danych syntetycznych (D6); "
                            f"champion techniczny {champ} ustawiony jawnie przez Registry.promote w tymczasowej bazie",
                            f"job {job.get('status')} {str(det)[:200]}, polityka {pol.get('role')}, champion {champ}")}
    if steps["train"]["status"] != "OK":
        return steps
    ctx.step = "artifact"
    f = json.loads(rows[0]["features_json"])
    f.update(M15_rsi=80.0)
    db.execute("""INSERT INTO ml_samples(sample_id, setup_id, setup_version, group_id, symbol, feed_id, strategy_id, strategy_version, direction, timeframe,
                  asof_utc, feature_schema_version, features_json, entry_json, cost_model_version, label_policy_version, source, quality, status, synthetic,
                  created_at, updated_at) VALUES ('SMK-G:1','SMK-G',1,'SMK-G','XAUUSD-','SYN','S01','1','LONG','M15',?,?,?,'{}','c','l','SMOKE','HIGH',
                  'PENDING',1,?,?)""", (now, rows[0]["feature_schema_version"], json.dumps(f), now, now))
    row = {"setup_id": "SMK-G", "version": 1, "record": {}}
    p1 = ml.predict(row, None)
    ml2 = MLService(cfg, db, _MLBridge(), bus, log, root=root)                 # registry reloads the champion bundle (integrity.json) from disk
    p2 = ml2.predict(row, None)
    d_raw = abs((p1.get("raw_score") or 0) - (p2.get("raw_score") or 1e9))
    d_p = abs((p1.get("calibrated_probability") or 0) - (p2.get("calibrated_probability") or 1e9))
    path = (db.one("SELECT path FROM ml_models WHERE model_id=?", (champ,)) or {}).get("path")
    steps["artifact"] = check(ml2.registry.champion_id == champ and d_raw < 1e-9 and d_p < 1e-9,
                              f"champion {champ} ({ml.registry.champion.family}) zapisany w {str(path)[-40:]} i wczytany przez nowy MLService: "
                              f"raw {p1.get('raw_score')} / p {p1.get('calibrated_probability')} identyczne (różnica {max(d_raw, d_p):.1e})",
                              f"po odczycie champion {ml2.registry.champion_id} vs {champ}, raw {p1.get('raw_score')} vs {p2.get('raw_score')}, "
                              f"p {p1.get('calibrated_probability')} vs {p2.get('calibrated_probability')}")
    ctx.step = "predict"
    out = {}
    try:
        for mode in ("SHADOW", "ASSIST"):                                       # ML component mode of the temporary config only
            cfg.update({"ml": {"mode": mode}})
            g = ml.gate(row, None)
            out[mode] = (g["status"], g["codes"][:2], ml.rank_adjust(row, None))
    finally:
        cfg.update({"ml": {"mode": "SHADOW"}})
    pred = p1
    thr = pred.get("threshold") or 0.5
    exp_assist = "PASS" if (pred.get("calibrated_probability") or 0) >= thr else "FAIL"
    steps["predict"] = check(pred.get("readiness") == "READY" and out["SHADOW"][0] == "PASS" and out["ASSIST"][0] == exp_assist and out["SHADOW"][2] == 0.0,
                             f"MLService.predict READY p={pred.get('calibrated_probability')} (próg {thr}); gate SHADOW {out['SHADOW'][0]} "
                             f"{out['SHADOW'][1]}, ASSIST {out['ASSIST'][0]} {out['ASSIST'][1]}; rank_adjust SHADOW 0, ASSIST {out['ASSIST'][2]:+.2f}",
                             f"predict {pred.get('readiness')} {pred.get('uncertainty_reason')}, gate {out}, oczekiwany ASSIST {exp_assist}")
    ctx.step = "contract"
    keys = ("setup_id", "model_id", "model_version", "feature_schema_version", "asof_utc", "raw_score", "calibrated_probability", "calibration_status",
            "target_definition", "readiness", "uncertainty_reason", "data_quality", "explanation_ref")
    miss = [k for k in keys if k not in pred]
    cp = pred.get("calibrated_probability")
    saved = db.one("SELECT model_id, role FROM ml_predictions WHERE setup_id='SMK-G' AND role='CHAMPION'") or {}
    errs = []
    if miss or pred.get("contract") != PRED_CONTRACT:
        errs.append(f"brak pól {miss} / kontrakt {pred.get('contract')}")
    if not (isinstance(cp, float) and 0.0 <= cp <= 1.0) or pred.get("model_id") != champ:
        errs.append(f"p={cp}, model {pred.get('model_id')}")
    if saved.get("model_id") != champ:
        errs.append(f"wiersz ml_predictions {saved}")
    nm = MLService(ConfigStore(), Database(ctx.data_dir / "smoke_ml_empty.sqlite"), _MLBridge(), bus, log, root=ctx.data_dir / "smoke_ml_empty")
    p0 = nm.predict(row, None)
    if (p0.get("readiness"), p0.get("calibrated_probability")) != ("NOT_READY", None):
        errs.append(f"bez modelu: {p0.get('readiness')} p={p0.get('calibrated_probability')} (oczekiwane NOT_READY, None – nigdy fałszywe 50 %)")
    steps["contract"] = check(not errs, f"{PRED_CONTRACT}: komplet pól, p∈[0,1], model = champion, zapis ml_predictions; bez modelu NOT_READY/None",
                              "; ".join(errs))
    return steps


# ---------------------------------------------------------------------------------------------------------------- ml_scalp:xgb_net_r
def _scalp_rows(n: int, seed: int = 3) -> list[dict]:
    from datetime import datetime, timedelta

    import numpy as np

    from ...scalp.strategy import NET_FEATURES
    rng = np.random.default_rng(seed)
    t0 = datetime(2026, 1, 5, tzinfo=UTC)
    out = []
    for k in range(n):
        t = t0 + timedelta(minutes=90 * k)
        x = {f: float(rng.normal()) for f in NET_FEATURES}
        if k % 7 == 0:
            x[NET_FEATURES[3]] = float("nan")
        y = int(rng.random() < 1 / (1 + math.exp(-1.2 * x[NET_FEATURES[0]])))
        nr = (1.0 if y else -1.0) * float(rng.uniform(0.3, 1.5))
        out.append({"setup_id": f"S{k}", "range_id": f"R{k // 2}", "side": "BUY", "signal_time": t.isoformat(), "fill_time": t.isoformat(),
                    "label_end": (t + timedelta(minutes=30)).isoformat(), "x": x, "net_r": nr, "y": y, "spread": 0.1, "risk": 1.0, "net_price": nr,
                    "ambiguous": False})
    return out


def _scalp(ctx) -> dict:
    """scalp_task.train on the synthetic export (FIXTURE_ONLY) + fit_pair -> save_bundle -> load roundtrip -> registry (fixture refused,
    technical OBSERVE selection) -> MLService.on_scalp_candidate -> ml_scalp_predictions."""
    import json

    import numpy as np

    from ...config import ConfigStore
    from ...db.database import Database
    from ...events import EventBus
    from ...ml import scalp_task as stk
    from ...ml.service import MLService
    ctx.step = "train"
    t0 = time.monotonic()
    db = Database(ctx.data_dir / "smoke_ml_scalp.sqlite")
    rep0 = stk.train(INST, _dataset(ctx), commission=0.5, db=db, log=lambda m: None)
    reg0 = json.loads((stk.root(INST) / "registry.json").read_text(encoding="utf-8"))
    rows = _scalp_rows(600)
    X, y, r = stk.matrix(rows), np.array([x["y"] for x in rows]), np.array([x["net_r"] for x in rows])
    fp = stk.fit_pair(X, y, r, stk.inner_blocks(np.arange(len(rows)), rows, 1800.0))
    dt = time.monotonic() - t0
    good = rep0.get("role") == "FIXTURE_ONLY" and reg0.get("selected") == {} and fp.get("clf") is not None and fp.get("reg") is not None
    steps = {"train": check(good, f"scalp_task.train na eksporcie SYNTHETIC_TEST: {rep0.get('status')} / {rep0.get('role')} (nie do wyboru); fit_pair "
                                  f"(XGB klasyfikator + regresor, siatka {len(stk.CONFIGS)} konfiguracji) na 600 syntetycznych cyklach: cfg {fp.get('cfg')}, "
                                  f"polityka {fp.get('policy')}, kalibracja {(fp.get('calibrator') or {}).get('status')}; {dt:.1f} s",
                            f"train {rep0.get('status')}/{rep0.get('role')}, selected {reg0.get('selected')}, fit_pair {sorted(fp)}")}
    if steps["train"]["status"] != "OK":
        return steps
    ctx.step = "artifact"
    base = {"instrument": INST, "symbol": "XAUUSD-", "profile_id": "smoke", "profile_hash": "SMOKE-PROFILE", "costs": {}, "dataset_id": "SMOKE",
            "data_kind": "SYNTHETIC_TEST"}
    fx = stk.root(INST) / "fixture_runs" / "SMOKE-FX"
    mh_fx = stk.save_bundle(fx / "bundle_BUY", fp, dict(base, role="FIXTURE_ONLY"), "BUY", {})
    stk._register(INST, "SMOKE-FX", fx, {"status": "EVALUATED", "role": "FIXTURE_ONLY", "sides": {"BUY": {"status": "FIXTURE_ONLY", "model_hash": mh_fx}}})
    gate = None
    try:
        stk.select(INST, "SMOKE-FX", "BUY", "OBSERVE")
    except ValueError as exc:
        gate = str(exc)
    b = stk.load_bundle(fx / "bundle_BUY")                                   # file hashes verified on load
    mem = {"p": stk._cal(fp["clf"].predict(X, output_margin=True), fp["calibrator"]), "ev": fp["reg"].predict(X)}
    disk = b.predict_matrix(X)
    diff = max(float(np.max(np.abs(mem["p"] - disk["p"]))), float(np.max(np.abs(mem["ev"] - disk["ev"]))))
    steps["artifact"] = check(gate == "FIXTURE_ONLY_NOT_SELECTABLE" and diff < 1e-6 and b.man["model_hash"] == mh_fx,
                              f"bundle_BUY (classifier.ubj, regressor.ubj, preprocessor/calibrator/policy.json, manifest sha256) -> load_bundle: "
                              f"p i E[net R] na {len(X)} wierszach identyczne (max różnica {diff:.1e}); wybór runu FIXTURE_ONLY odrzucony ({gate})",
                              f"wybór fixture: {gate}, różnica {diff}, hash {b.man['model_hash']} vs {mh_fx}")
    ctx.step = "predict"
    # technical OBSERVE selection (temporary folder): a run that is not FIXTURE_ONLY - the manifest keeps data_kind SYNTHETIC_TEST
    rd = stk.root(INST) / "runs" / "SMOKE-TECH"
    mh = stk.save_bundle(rd / "bundle_BUY", fp, dict(base, role="RESEARCH"), "BUY", {})
    stk._register(INST, "SMOKE-TECH", rd, {"status": "EVALUATED", "role": "RESEARCH", "sides": {"BUY": {"status": "NO_VALIDATED_EDGE", "model_hash": mh}}})
    stk.select(INST, "SMOKE-TECH", "BUY", "OBSERVE")
    ml = MLService(ConfigStore(), db, None, EventBus(), None, root=ctx.data_dir / "smoke_ml_scalp")
    last = ctx.bars("M1", 2)[-1]
    ref = round(float(last["c"]), 2)
    plan = {"setup_id": "SMK-SC-1", "direction": "BUY", "decision_ts": float(last["t"]) + 60, "decision_time": last["open_utc"], "sl": ref - 1.0,
            "tp1": ref + 1.0, "tp2": ref + 2.0, "entry_mode": "MARKET", "net_features": rows[1]["x"]}
    o = ml.on_scalp_candidate(plan, instrument=INST, profile_hash="SMOKE-PROFILE", session_epoch=1, costs={}, entry_mode="MARKET")
    mis = ml.on_scalp_candidate(dict(plan, setup_id="SMK-SC-2"), instrument=INST, profile_hash="OTHER", session_epoch=1, costs={}, entry_mode="MARKET")
    saved = db.query("SELECT status, role, model_hash FROM ml_scalp_predictions ORDER BY computed_at")
    p, ev = o.get("calibrated_probability"), o.get("expected_net_r")
    steps["predict"] = check(o.get("status") == "READY_INFERENCE" and o.get("model_hash") == mh and mis.get("status") == "ABSTAIN" and len(saved) == 2,
                             f"MLService.on_scalp_candidate (plan na cenie FakeMT5 {ref}): {o.get('status')} p={p} E[net R]={ev} "
                             f"(kalibracja {o.get('calibration_status')}, filtr {o.get('proposed_filter')}, rola {o.get('role')}, {o.get('latency_ms')} ms); "
                             f"inny profil -> {mis.get('status')} ({mis.get('reason')}); wiersze ml_scalp_predictions: {len(saved)}",
                             f"on_scalp_candidate {o.get('status')} {o.get('reason')}, hash {o.get('model_hash')} vs {mh}, inny profil {mis}, wiersze {saved}")
    ctx.step = "contract"
    errs = []
    if p is not None and not 0.0 <= p <= 1.0:
        errs.append(f"p poza [0,1]: {p}")
    if p is None and o.get("calibration_status") == "FITTED_ON_CALIBRATION":
        errs.append("brak p mimo kalibracji")
    if not (isinstance(ev, float) and math.isfinite(ev)):
        errs.append(f"E[net R] {ev}")
    for k in ("task_id", "model_hash", "raw_margin", "calibration_status", "policy", "proposed_filter", "role", "meaning", "prediction_id", "expires_at"):
        if k not in o:
            errs.append(f"brak pola {k}")
    if o.get("role") != "OBSERVE":
        errs.append(f"rola {o.get('role')} (oczekiwana OBSERVE z rejestru)")
    steps["contract"] = check(not errs, f"{stk.TASK_ID}: status/p/E[net R]/polityka/rola/wygaśnięcie {o.get('expires_at')}, znaczenie: "
                                        f"'{(o.get('meaning') or '')[:50]}…'", "; ".join(errs))
    return steps


# ---------------------------------------------------------------------------------------------------------------- agent:claude
class _NoKey:
    def get(self, name):
        return None

    def source(self, name):
        return "MISSING"

    def mask(self, name):
        return None


class _Recorder:
    """Stand-in AsyncAnthropic client: records the keyword arguments of messages.create / beta.messages.create (no network)."""

    def __init__(self, fail_fallback_once: bool = False):
        from types import SimpleNamespace
        self.calls: list = []
        self._fail = fail_fallback_once
        self.messages = SimpleNamespace(create=self._plain)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._beta))

    async def _plain(self, **kw):
        self.calls.append(("messages", kw))
        return {"stub": True}

    async def _beta(self, **kw):
        self.calls.append(("beta", kw))
        if self._fail:
            self._fail = False
            import anthropic
            import httpx2
            resp = httpx2.Response(400, request=httpx2.Request("POST", "https://api.invalid/v1/messages"))
            raise anthropic.BadRequestError("fallbacks: not available for this organization", response=resp, body=None)
        return {"stub": True}


def _agent(ctx) -> dict:
    """ClaudeAgent without an API key: status, then _create on a recording client - request shape per model from the price list against the
    installed anthropic SDK signature (output_config effort + json_schema, cache_control, server-side fallback beta). No API call."""
    import asyncio
    import inspect

    import anthropic
    from anthropic.resources.beta.messages import AsyncMessages as BetaMessages
    from anthropic.resources.messages import AsyncMessages

    from ...agent import service as AS
    from ...agent.schema import OUTPUT_SCHEMA
    from ...agent.tools import TOOL_DEFS
    from ...config import ConfigStore
    from ...db.database import Database
    from ...events import AppLog, EventBus
    ctx.step = "contract"
    db = Database(ctx.data_dir / "smoke_agent.sqlite")
    bus = EventBus()
    ag = AS.ClaudeAgent(ConfigStore(), _NoKey(), db, bus, AppLog(db, bus), lambda sid: None)
    st = ag.status()
    system, pver = AS.load_prompt()
    msgs = [{"role": "user", "content": "smoke: kształt żądania"}]
    sig_plain = set(inspect.signature(AsyncMessages.create).parameters)
    sig_beta = set(inspect.signature(BetaMessages.create).parameters)
    errs, seen = [], []
    for model in sorted(ag.cfg.price_per_mtok):
        rec = _Recorder()
        asyncio.run(ag._create(rec, model, system, msgs, True))
        kind, kw = rec.calls[-1]
        oc = kw.get("output_config") or {}
        want_beta = model in AS.FALLBACK_MODELS and ag.cfg.use_refusal_fallback
        unknown = sorted(set(kw) - (sig_beta if kind == "beta" else sig_plain))
        if unknown:
            errs.append(f"{model}: parametry spoza SDK {anthropic.__version__}: {unknown}")
        if (kind == "beta") != want_beta or (want_beta and (kw.get("betas") != [AS.FALLBACK_BETA] or kw.get("fallbacks") != "default")):
            errs.append(f"{model}: ścieżka {kind}, betas {kw.get('betas')}, fallbacks {kw.get('fallbacks')}")
        if oc.get("effort") != ag.cfg.effort or (oc.get("format") or {}).get("type") != "json_schema" or oc["format"].get("schema") is not OUTPUT_SCHEMA:
            errs.append(f"{model}: output_config {sorted(oc)} effort {oc.get('effort')}")
        if (kw.get("cache_control") != {"type": "ephemeral"} or kw.get("tools") is not TOOL_DEFS or kw.get("max_tokens") != ag.cfg.max_tokens
                or kw.get("model") != model):
            errs.append(f"{model}: cache_control/tools/max_tokens/model")
        seen.append((model.replace("claude-", ""), kind))
    # a server-side fallback rejected by the API -> disabled for the session and the same request repeated without it
    fb = sorted(AS.FALLBACK_MODELS & set(ag.cfg.price_per_mtok))
    if fb:
        rec = _Recorder(fail_fallback_once=True)
        asyncio.run(ag._create(rec, fb[0], system, msgs, True))
        if [k for k, _ in rec.calls] != ["beta", "messages"] or not ag.disable_fallback or "fallbacks" in rec.calls[-1][1]:
            errs.append(f"odrzucony fallback: wywołania {[k for k, _ in rec.calls]}, disable_fallback {ag.disable_fallback}")
    if st.get("state") != "AI_UNAVAILABLE_NO_KEY" or ag._client_get() is not None:
        errs.append(f"bez klucza: stan {st.get('state')}")
    fb_txt, plain_txt = ", ".join(m for m, k in seen if k == "beta"), ", ".join(m for m, k in seen if k != "beta")
    steps = {"contract": check(not errs, f"bez klucza: {st.get('state')}; _create dla {len(seen)} modeli z cennika (fallback beta: {fb_txt}; "
                                         f"zwykłe: {plain_txt}): parametry "
                                         f"zgodne z anthropic {anthropic.__version__}, output_config effort '{ag.cfg.effort}' + json_schema, cache_control, "
                                         f"fallback {AS.FALLBACK_BETA} 'default'; odrzucony fallback -> ponowienie bez niego; prompt {pver[:22]}…",
                                 "; ".join(errs))}
    steps["predict"] = unverified("brak klucza Anthropic – wywołanie API niesprawdzone")
    return steps


# ---------------------------------------------------------------------------------------------------------------- WF3.2 model layers
def _dt_sets(n_events: int = 600, seed: int = 5) -> list[dict]:
    import random

    from ...ml.dt_ranker import Candidate, net_r_label
    rnd = random.Random(seed)
    out = []
    t0 = 1_790_000_000.0                                    # fixed epoch: the ranker features include the time of day (repeatable smoke)
    for e in range(n_events):
        ts = t0 + e * 3600
        for k in range(3):
            rr = rnd.choice([1.0, 2.0, 3.0])
            spread = rnd.choice([0.05, 0.6])
            c = Candidate(f"c{e}-{k}", f"S{k}", "BASKET", "FOREX", INST, "M15", "LONG", ts, ts, f"g{e}", 100.0, 99.0, 100.0 + rr,
                          setup_score=rnd.random(), spread=spread, commission_R=0.02, atr=2.0)
            win = rnd.random() < (0.55 if (rr == 3.0 and spread < 0.1) else 0.25)
            lab = net_r_label(c, c.target if win else c.stop)
            out.append({"candidate": c, "net_R": lab["net_R"], "decision_ts": ts, "label_end_ts": ts + 1800, "event_group_id": f"g{e}"})
    return out


def _dt_ranker(ctx) -> dict:
    """dt_ranker.train / RankerBundle.predict / rank on synthetic candidate sets; the app route /api/v1/models/dt-ranker/* (never trained
    in the app -> FALLBACK_BASELINE). The bundle has no save/load in the code, so there is no artifact step."""
    from ...ml import dt_ranker as DT
    ctx.step = "train"
    sets = _dt_sets()
    res = DT.train(sets, {"min_leaf_events": 20, "calib_min": 10_000})
    ev = (res.get("evaluation") or {}).get("DT_RANKER") or {}
    steps = {"train": check(res.get("status") == "READY" and res.get("bundle") is not None,
                            f"dt_ranker.train na {len(sets)} syntetycznych kandydatach (600 grup zdarzeń): READY, "
                            f"split {res.get('manifest', {}).get('split')}, "
                            f"ccp_alpha {res.get('manifest', {}).get('ccp_alpha')}; test: net R/akcję {ev.get('mean_net_R_per_action')}; brak zapisu "
                            "artefaktu w kodzie (RankerBundle bez save/load, ml/dt_ranker.py:158)",
                            f"train: {res.get('status')} {res.get('reason')}")}
    if steps["train"]["status"] != "OK":
        return steps
    ctx.step = "predict"
    last = ctx.bars("M15", 2)[-1]
    px = round(float(last["c"]), 2)
    ts = float(last["t"]) + 900
    cands = [DT.Candidate(f"smk-{k}", f"S{k}", "BASKET", "FOREX", INST, "M15", "LONG", ts, ts, "g-smk", px, px - 1.0, px + rr, setup_score=0.5,
                          spread=sp, commission_R=0.02, atr=2.0) for k, (rr, sp) in enumerate(((3.0, 0.05), (1.0, 0.6), (2.0, 0.05)))]
    rk = DT.rank(res["bundle"], cands, {"min_leaf_events": 20})
    api_st = _route(ctx, "get", "/api/v1/models/dt-ranker/status")
    api = _route(ctx, "post", "/api/v1/models/dt-ranker/rank", body={"candidates": [DT.to_dict(c) for c in cands]})
    good = rk.get("decision") in ("SELECT", "ABSTAIN", "NO_TRADE") and api.get("decision") == "FALLBACK_BASELINE" and api_st["ready"] is False
    steps["predict"] = check(good,
                             f"rank (bundle z treningu, 3 kandydatów na cenie FakeMT5 {px}): {rk.get('decision')} {rk.get('selected_candidate_id')}; "
                             f"trasa aplikacji /dt-ranker/rank: {api.get('decision')} {api.get('reason_codes')} (ready={api_st['ready']} – model nigdy "
                             "nie trenowany w aplikacji, stan zgodny z kodem)",
                             f"rank {rk.get('decision')} {rk.get('reason_codes')}, API {api.get('decision')}, status {api_st}")
    ctx.step = "contract"
    pr = res["bundle"].predict(cands[0])
    errs = []
    if rk.get("schema") != DT.SCHEMA or rk.get("mode") != "SHADOW" or rk.get("apply_to_selection") is not False:
        errs.append(f"schema/mode {rk.get('schema')} {rk.get('mode')} {rk.get('apply_to_selection')}")
    for k in ("expected_net_R", "p_positive_net_R", "probability_status", "leaf_id", "leaf_support_events", "uncertainty_R", "conservative_net_R"):
        if k not in pr:
            errs.append(f"brak {k}")
    if pr.get("p_positive_net_R") is not None or pr.get("probability_status") != "UNCALIBRATED":
        errs.append(f"bez kalibracji (calib_min) p={pr.get('p_positive_net_R')} {pr.get('probability_status')}")
    if not math.isfinite(pr.get("expected_net_R", float("nan"))):
        errs.append("expected_net_R nieskończone")
    steps["contract"] = check(not errs, f"{DT.SCHEMA}: tryb SHADOW (apply_to_selection False), predict: E[net R]={pr['expected_net_R']:.3f}, liść "
                                        f"{pr['leaf_id']} ({pr['leaf_support_events']} zdarzeń), p UNCALIBRATED (calib_min) – bez wymyślonego p",
                              "; ".join(errs))
    return steps


def _association(ctx) -> dict:
    """Route /api/v1/models/association/snapshot: event bits -> rule counting -> assess on FakeMT5 H1 bars (counted on request, no model)."""
    from ...ml import association_rules as AR
    ctx.step = "predict"
    r = _route(ctx, "get", "/api/v1/models/association/snapshot", timeframe="H1", horizon=24)
    al, sh = r.get("assess_long") or {}, r.get("assess_short") or {}
    steps = {"predict": check(r.get("status") == "READY" and isinstance(r.get("rules"), int),
                              f"trasa /association/snapshot ({_wf32(ctx)['n_h1']} świec H1 FakeMT5): {r.get('status')}, {r.get('n_labeled')} etykiet, "
                              f"{r.get('rules')} reguł (zwalidowanych na holdoucie: {r.get('validated_rules')}), LONG {al.get('action')} "
                              f"({al.get('reason')}), SHORT {sh.get('action')} ({sh.get('reason')})",
                              f"snapshot: {str(r)[:300]}")}
    ctx.step = "contract"
    errs = []
    if r.get("mode") != "OBSERVE" or r.get("schema") != AR.SCHEMA or r.get("validation") != AR.VALIDATION:
        errs.append(f"mode/schema/walidacja {r.get('mode')} {r.get('schema')} {r.get('validation')}")
    if not isinstance(r.get("current_mask"), int) or not all(e in AR.CATALOG for e in r.get("current_events") or []):
        errs.append(f"maska {r.get('current_mask')} / zdarzenia {r.get('current_events')}")
    for a in (al, sh):
        if "action" not in a or "reason" not in a:
            errs.append(f"assess bez action/reason: {sorted(a)}")
    steps["contract"] = check(not errs, f"{AR.SCHEMA}: tryb OBSERVE, maska {r.get('current_mask')} -> {r.get('current_events')}, assess LONG/SHORT z "
                                        f"action/reason, {AR.VALIDATION} (SUPPORTED tylko z reguł zwalidowanych; wynik nie trafia do decyzji)",
                              "; ".join(errs))
    return steps


def _pt(ctx) -> dict:
    """Route /api/v1/models/pt/evaluate: Pesaran-Timmermann on the sign of the previous FakeMT5 H1 return vs the next one (a measurement)."""
    from fastapi import HTTPException

    from ...evaluation import pt_skill as PT
    ctx.step = "predict"
    c = [float(b["c"]) for b in ctx.bars("H1", 600)]
    ret = [c[i] - c[i - 1] for i in range(1, len(c))]
    f = [1 if x > 0 else -1 for x in ret[:-1]]
    y = [1 if x > 0 else -1 for x in ret[1:]]
    r = _route(ctx, "post", "/api/v1/models/pt/evaluate", body={"forecasts": f, "outcomes": y})
    steps = {"predict": check(r.get("status") in ("OK", "DEGENERATE", "INSUFFICIENT_DATA") and r.get("n") == len(f),
                              f"trasa /pt/evaluate (n={r.get('n')}, znak poprzedniego zwrotu H1 FakeMT5): {r.get('status')}, PT={r.get('pt')}, "
                              f"p_right={r.get('p_right')}, p_two={r.get('p_two')}",
                              f"PT: {str(r)[:300]}")}
    ctx.step = "contract"
    errs = []
    pr = r.get("p_right")
    if pr is not None and not 0.0 <= pr <= 1.0:
        errs.append(f"p_right {pr}")
    for bad in ({"forecasts": [1, -1], "outcomes": [1]}, {"forecasts": [1, "x"], "outcomes": [1, -1]}, {"forecasts": [1], "outcomes": [1], "profile": "?"}):
        try:
            _route(ctx, "post", "/api/v1/models/pt/evaluate", body=bad)
            errs.append(f"brak odmowy dla {bad}")
        except HTTPException as exc:
            if exc.status_code != 400:
                errs.append(f"kod {exc.status_code} dla {bad}")
    known = PT.evaluate([1, -1] * 50, [1, -1] * 45 + [-1, 1] * 5)
    if not (known.get("status") == "OK" and known.get("pt", 0) > 2):
        errs.append(f"przypadek znany (90 % trafień): {known.get('status')} PT={known.get('pt')}")
    steps["contract"] = check(not errs, f"p_right∈[0,1], błędne dane -> HTTP 400 (3 przypadki), przypadek znany 90 % trafień: PT={known.get('pt'):.2f}",
                              "; ".join(errs))
    return steps


def _pelt(ctx) -> dict:
    """Route /api/v1/change-points: PELT segmentation of FakeMT5 H1 closes (closed bars only) + a planted volatility change."""
    import random

    from ...lab.change_points import pelt
    ctx.step = "predict"
    r = _route(ctx, "get", "/api/v1/change-points", timeframe="H1", lookback=500, min_segment=10)
    segs = r.get("segments") or []
    steps = {"predict": check(r.get("status") == "OK" and isinstance(r.get("change_points"), list) and bool(segs),
                              f"trasa /change-points (H1 FakeMT5, lookback 500): {r.get('status')}, punkty {r.get('change_points')[:6]}, segmentów "
                              f"{len(segs)}, pruning {r.get('pruning_used')}",
                              f"PELT: {str(r)[:300]}")}
    ctx.step = "contract"
    errs = []
    if any(s["start"] > s["end"] for s in segs) or (segs and (segs[0].get("start_utc") is None or segs[-1].get("end_utc") is None)):
        errs.append(f"segmenty / czasy UTC: {segs[:2]}")
    rng = random.Random(1)
    c = [2000.0]
    for i in range(1000):
        c.append(c[-1] * math.exp(rng.gauss(0, 0.002 if i < 500 else 0.006)))
    d = pelt.detect(c, 1000, 10)
    if d.get("status") != "OK" or not any(400 <= cp <= 600 for cp in d.get("change_points") or []):
        errs.append(f"wszczepiona zmiana zmienności (indeks 500) niewykryta: {d.get('change_points')}")
    steps["contract"] = check(not errs, f"segmenty uporządkowane z czasami UTC, 'closed bars only'; wszczepiona zmiana zmienności w 500/1000 -> "
                                        f"{d.get('change_points')}", "; ".join(errs))
    return steps


def _long_horizon(ctx) -> dict:
    """Route /api/v1/forecast/long-horizon: empirical direct-return quantiles 24 h on FakeMT5 H1 bars (UTC from the bridge)."""
    from ...forecast import long_horizon as LH
    ctx.step = "predict"
    r = _route(ctx, "get", "/api/v1/forecast/long-horizon", horizon="24h", timeframe="H1")
    q = r.get("log_return_quantiles") or {}
    steps = {"predict": check(r.get("status") in ("OK", "LOW_SAMPLE", "STALE") and bool(q),
                              f"trasa /forecast/long-horizon 24h (H1 FakeMT5): {r.get('status')}, {r.get('calibration')}, próbki {r.get('samples')} "
                              f"(efektywne {r.get('samples_effective')}), p_up={r.get('p_up')}, q50={q.get('q50')}",
                              f"LH: {str(r)[:300]}")}
    ctx.step = "contract"
    errs = []
    ks = sorted(q, key=lambda k: float(k[1:]))
    vals = [q[k] for k in ks]
    if vals != sorted(vals) or not all(math.isfinite(v) for v in vals):
        errs.append(f"kwantyle niemonotoniczne: {q}")
    pu = r.get("p_up")
    if pu is None or not 0.0 <= pu <= 1.0:
        errs.append(f"p_up {pu}")
    try:
        _route(ctx, "get", "/api/v1/forecast/long-horizon", horizon="5h", timeframe="H1")
        errs.append("nieznany horyzont przyjęty")
    except Exception as exc:  # noqa: BLE001 - fastapi HTTPException expected
        if getattr(exc, "status_code", None) != 400:
            errs.append(f"nieznany horyzont: {type(exc).__name__}")
    steps["contract"] = check(not errs, f"kwantyle {', '.join(ks)} monotoniczne, p_up∈[0,1], horyzonty {list(LH.HORIZONS_S)}, nieznany -> 400",
                              "; ".join(errs))
    return steps


SMOKES = {"sh:tp_model": _tp_model, "ml:legacy_s01_s12": _legacy, "ml_scalp:xgb_net_r": _scalp, "agent:claude": _agent,
          "ml:decision_tree_ranker": _dt_ranker, "ml:association_rules": _association, "ml:pt_directional_skill": _pt,
          "ml:change_point_engine": _pelt, "forecast:long_horizon": _long_horizon}
