"""Smoke checks of the lab area (`models check --smoke --area lab`): lab M5 triple-barrier families and experiments, Structure Intelligence
move families, Neural Scalp System (TCN), flow context (Markov3 / reaction model), context indicators model, QuoteEngine and the lab tools
(M29 Fourier, M31 tick kinematics, M39-M41 edge tools, M42 trade pad).

Training is grouped and cached on the Ctx of the area process (27 producers must fit in the area time budget):
* ONE synthetic training export - the `training export --synthetic` path (FakeMT5 installed as the MetaTrader5 module ->
  forecast.export.export_candles, data_kind SYNTHETIC_TEST) - feeds every dataset builder;
* ONE lab study for all lab families + experiments (LabTrainer._run, as `training lab-offline`, artifact_family ALL) plus a DUMMY-only study
  (artifact_family DUMMY: the ALL mode never saves the baseline by design);
* ONE Structure Intelligence run for all SI families (structure_task.train with a temporary in-memory smoke profile);
* ONE MarketBridge on a FakeMT5 terminal (the composition of the demo bot) for the live paths: LabService.tick -> quant.adapters.lab,
  StructureIntelligenceService (forecast, quote collector, M1 cell with the flow sections), NeuralScalpService.
Honesty gates (TEST_ONLY / FIXTURE_ONLY artefacts never selected for SHADOW / OBSERVE; a TEST_ONLY Markov fit not loaded into the SI cell,
decision D23 (b) - its live path is exercised with the test opt-in PMW_FLOW_ALLOW_TEST_MODEL=1 set in this area process only) are correct
behaviour and reported as such; a producer without a live path is shown in `predict` exactly in the state the bot's own code returns.
"""
from __future__ import annotations

from datetime import UTC

from . import check, fail

INST = "XAUUSD"
LAB_FAMILIES = ("DUMMY", "RULE", "LOGREG", "TREE", "MINIROCKET", "XGB", "RESNET1D", "SEW_SNN")
LAB_EXPERIMENTS = ("LOGREG_PCA", "LOGREG_GMM_AUG", "LOGREG_NEUTRALIZED")
SI_FAMILIES = ("MQ_RESNEXT1D_V2", "MQ_SEW_RESNET1D_V2", "MQ_SEW_RESNEXT_EB_V1", "MQ_MINIROCKET_RIDGE_V2", "MQ_SPIKE_BRAIN_FINANCE_V1", "LOGREG", "XGB")
EXPORT_DAYS = 3
SI_PROFILE = "models_check_smoke"
NSS_CFG = {"m1_len": 20, "m5_len": 8, "m1_dil": [1, 2], "m5_dil": [1], "width": 8}
NSS_TRAIN = {"members": [17], "epochs": 2, "patience": 1}


# ---------------------------------------------------------------------------------------------------------------- shared helpers
def _quiet(*_a, **_k) -> None:
    return None


def _loc(exc: BaseException) -> str:
    """file:line of the deepest bot frame of an exception ('' when it was raised by the smoke itself)."""
    import traceback
    bot = [f for f in traceback.extract_tb(exc.__traceback__)
           if "masterquo/" in f.filename.replace("\\", "/") and "/modelhub/smoke/" not in f.filename.replace("\\", "/")]
    if not bot:
        return ""
    fn = bot[-1].filename.replace("\\", "/")
    return f"{fn[fn.find('masterquo/'):]}:{bot[-1].lineno}"


def _shared(ctx, key: str, build):
    """One build per area process; a failed build is reported by every producer that needs it (never re-run, never hidden)."""
    cache = ctx.__dict__.setdefault("_lab_smoke", {})
    if key not in cache:
        try:
            cache[key] = (True, build(ctx))
        except Exception as exc:
            where = _loc(exc)
            cache[key] = (False, f"{type(exc).__name__}: {exc}{' @ ' + where if where else ''}"[:300])
            raise
    good, val = cache[key]
    if not good:
        raise RuntimeError(f"wspólny etap '{key}' nie powiódł się: {val}")
    return val


def _partial(fn):
    """Run a smoke that fills `out` step by step; an exception becomes a FAIL of the step being executed (with the bot file:line) while
    the steps already checked are kept (the area runner would replace the whole result with the failing step)."""
    def run(ctx) -> dict:
        out: dict = {}
        try:
            fn(ctx, out)
        except Exception as exc:  # noqa: BLE001 - a crash is a FAIL of ctx.step, never hidden
            where = _loc(exc)
            out[ctx.step] = fail(f"{type(exc).__name__}: {exc}{' @ ' + where if where else ''}")
        return out
    run.__name__ = getattr(fn, "__name__", "smoke")
    return run


def _finite(*xs) -> bool:
    import math
    return all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in xs)


def _dist_ok(p) -> bool:
    vals = list(p.values()) if isinstance(p, dict) else list(p)
    return bool(vals) and _finite(*vals) and all(0.0 <= v <= 1.0 for v in vals) and abs(sum(vals) - 1.0) < 1e-6


def _db(ctx):
    def build(_ctx):
        from ...db.database import Database
        db = Database()
        db.migrate()
        return db
    return _shared(ctx, "db", build)


def _export(ctx) -> dict:
    """`python -m masterquo training export --synthetic` in-process (training/cli.py cmd_export): FakeMT5 as MetaTrader5 -> export_candles."""
    import contextlib
    import io
    import json
    import os
    import sys
    from datetime import datetime, timedelta
    os.environ.setdefault("MQ_FAKE_MARKET_ALWAYS_OPEN", "1")
    from ...forecast.export import export_candles
    from ...mt5.fake import BTCUSDT_SYN, SYN_MARKETS, FakeMT5
    out = ctx.data_dir / "smoke_lab" / "export_synthetic"
    end = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    prev = sys.modules.get("MetaTrader5")
    sys.modules["MetaTrader5"] = FakeMT5(markets=dict(SYN_MARKETS, **BTCUSDT_SYN))
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = export_candles(1, str(out), "AUTO", ("M1", "M5", "M15", "H1"), "training", INST, None,
                                date_from=(end - timedelta(days=EXPORT_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ"), date_to=end.strftime("%Y-%m-%dT%H:%M:%SZ"))
    finally:
        if prev is None:
            sys.modules.pop("MetaTrader5", None)
        else:
            sys.modules["MetaTrader5"] = prev
    if rc != 0 or not (out / "source_metadata.json").exists():
        raise RuntimeError(f"eksport syntetyczny: kod {rc}: {buf.getvalue()[-250:]}")
    meta = json.loads((out / "source_metadata.json").read_text(encoding="utf-8"))
    if meta.get("data_kind") != "SYNTHETIC_TEST":
        raise RuntimeError(f"eksport z FakeMT5 oznaczony {meta.get('data_kind')} zamiast SYNTHETIC_TEST")
    from ...extind.trainer import _bars
    prefix = meta.get("file_prefix") or INST
    n = {tf: len(_bars(out, prefix, tf)) for tf in ("M1", "M5", "M15", "H1")}
    tick = float(meta["tick_size"])
    return {"dir": out, "meta": meta, "prefix": prefix, "tick": tick, "point": float((meta.get("spec") or {}).get("point") or tick), "n": n}


def _live(ctx):
    """MarketBridge on a FakeMT5 terminal (tests/_env core + AssetRegistry = the demo composition of the bot), started once."""
    import os
    import time
    from types import SimpleNamespace
    os.environ.setdefault("MQ_FAKE_MARKET_ALWAYS_OPEN", "1")
    from ...assets.registry import AssetRegistry
    from ...config import ConfigStore
    from ...events import AppLog, EventBus
    from ...mt5.bridge import MarketBridge
    from ...mt5.fake import FakeMT5
    from ...mt5.worker import MT5Worker
    cfg = ConfigStore()
    db = _db(ctx)
    bus = EventBus()
    log = AppLog(db, bus)
    fake = FakeMT5()
    worker = MT5Worker(lambda: fake)
    worker.start()
    bridge = MarketBridge(cfg, worker, db, bus, log)
    reg = AssetRegistry(cfg, bridge, log)
    bridge.assets = reg
    bridge.start()
    end = time.monotonic() + 60
    while time.monotonic() < end and not (bridge.state == "CONNECTED" and bridge.clock.verified and bridge.bars("M5", 5, include_forming=False)):
        time.sleep(0.05)
    if bridge.state != "CONNECTED":
        bridge.stop()
        worker.stop()
        raise RuntimeError(f"MarketBridge na FakeMT5 nie połączył się w 60 s (stan {bridge.state}: {bridge.state_reason})")
    sym = cfg.get().mt5.symbol
    info = bridge.symbol_info or {}

    def bars(tf: str, n: int = 1500) -> list[dict]:
        return [b for b in bridge.bars(tf, n, include_forming=False) if b.get("open_utc")]

    def stop() -> None:
        bridge.stop()
        worker.stop()
    return SimpleNamespace(cfg=cfg, db=db, bus=bus, log=log, bridge=bridge, reg=reg, worker=worker, sym=sym, bars=bars, stop=stop,
                           tick=float(info.get("trade_tick_size") or 0.01), point=float(info.get("point") or 0.01))


def _teardown(ctx) -> list[str]:
    """Stop the bridge / NSS worker threads (daemon threads - only to free the CPU). Errors are returned, never raised."""
    cache = ctx.__dict__.get("_lab_smoke") or {}
    errs = []
    for key in ("nss_service", "live"):
        good, val = cache.pop(key, (False, None))
        if good and val is not None:
            try:
                val.stop()
            except Exception as exc:  # noqa: BLE001 - teardown never changes a result
                errs.append(f"{key}: {type(exc).__name__}: {exc}")
    return errs


# ---------------------------------------------------------------------------------------------------------------- lab families
def _lab_train(ctx) -> dict:
    """LabTrainer._run exactly as `training lab-offline` (training/cli.py cmd_lab_offline) - smoke protocol: 2 folds, tuning budget 1."""
    import json
    from pathlib import Path

    from ... import paths
    from ...lab.protocol import EXPERIMENTS, FAMILIES, LabTrainer, default_protocol
    from ...training.cli import load_m5
    exp = _shared(ctx, "export", _export)
    bars, meta = load_m5(exp["dir"], 100000)
    tr = LabTrainer(_db(ctx), paths.data_dir() / "lab")
    iid = f"{INST}:{meta.get('account_server')}:{meta['symbol']}"

    def run(families, experiments, artifact_family: str) -> tuple[dict, dict]:
        prot = default_protocol(INST, families=families, experiments=experiments, min_events=300, folds=2, budget=1)
        job = {"job_id": f"LJOB-SMOKE-{artifact_family}", "asset": INST, "status": "RUNNING", "progress": 0, "total": 0, "stage": "start", "logs": [],
               "started_at": "", "protocol_id": prot["protocol_id"], "data_source": "SYNTHETIC", "cancel": False}
        tr._run(job, bars, exp["point"], "SYNTHETIC", iid, prot, artifact_family)
        if job["status"] != "COMPLETED":
            raise RuntimeError(f"LabTrainer._run({artifact_family}): {job['status']} {job.get('error') or ''}")
        return job, json.loads(Path(job["result_file"]).read_text(encoding="utf-8"))
    job, res = run(FAMILIES, EXPERIMENTS, "ALL")
    job_d, res_d = run(("DUMMY",), (), "DUMMY")
    models = {}
    for m in tr.models(INST):                       # newest first: one artefact per family
        if m.get("family") not in models:
            p = tr.root / "models" / INST / m["path"]
            models[m["family"]] = {"path": p, "model_id": m["model_id"], "manifest": json.loads((p / "manifest.json").read_text(encoding="utf-8"))}
    return {"job": job, "res": res, "job_dummy": job_d, "res_dummy": res_d, "models": models, "bars": len(bars)}


def _lab_tick(ctx) -> dict:
    """LabService.tick(force=True) on the bridge (the lab loop body) -> quant.adapters.lab (PMW-PRED-2 records read by Quant Core)."""
    from types import SimpleNamespace

    from ...lab.service import LabService
    from ...quant import adapters as QA
    _shared(ctx, "lab_train", _lab_train)
    lv = _shared(ctx, "live", _live)
    svc = LabService(lv.cfg, lv.bridge, lv.db, lv.bus, lv.log, lv.reg)
    st = svc.tick(force=True)
    if not st:
        raise RuntimeError("LabService.tick zwrócił None (bridge nie CONNECTED albo brak zamkniętych M5)")
    return {"svc": svc, "state": st, "recs": QA.lab(SimpleNamespace(lab=svc), INST), "bus": lv.bus.activity().get("lab", {})}


def _lab_family(fam: str):
    def smoke(ctx, out: dict) -> dict:
        import math

        from ...lab import features as FE
        from ...lab.protocol import load_artifact
        from ...quant import ids as I
        ctx.step = "train"
        tr = _shared(ctx, "lab_train", _lab_train)
        res = tr["res_dummy"] if fam == "DUMMY" else tr["res"]
        fr = (res.get("families") or {}).get(fam) or {}
        lls = [f.get("log_loss") for f in fr.get("folds") or []]
        out["train"] = check(fr.get("status") == "COMPLETED" and bool(lls) and _finite(*lls),
                             f"LabTrainer._run (jak training lab-offline; protokół smoke folds=2, budżet 1): {fam} COMPLETED, {len(lls)} foldy walk-forward, "
                             f"log_loss śr. {(sum(lls) / len(lls)) if lls else float('nan'):.3f}; {res.get('samples')} zdarzeń z {tr['bars']} świec M5 "
                             f"SYNTHETIC_TEST; werdykt badania {res.get('verdict')}",
                             f"badanie lab: rodzina {fam} status {fr.get('status')} {fr.get('note') or ''} (lab/protocol.py Study.run)")
        ctx.step = "artifact"
        m = tr["models"].get(fam)
        job = tr["job_dummy"] if fam == "DUMMY" else tr["job"]
        if m is None:
            out["artifact"] = fail(f"brak artefaktu {fam} po LabTrainer._run: missing={job.get('missing')} (lab/protocol.py:600-658)")
        else:
            man = m["manifest"]
            lp = man.get("loader_parity") or {}
            fitted, man2 = load_artifact(m["path"], asset=INST, feature_set=FE.FEATURE_SET)       # sha256 + schema checked by the bot's loader
            out["artifact"] = check(lp.get("status") == "OK" and lp.get("foreign_asset") == "REJECTED" and man.get("role") == "fixture_only"
                                    and fitted.family == fam and man2.get("sha256") == man.get("sha256"),
                                    f"save_artifact → load_artifact: loader_parity trenera max|Δp|={lp.get('max_abs_diff')} na {lp.get('rows')} wierszach, "
                                    f"obce aktywo odrzucone, sha256 zgodne; rola fixture_only (bramka danych syntetycznych)"
                                    + ("; DUMMY zapisany przez artifact_family=DUMMY (tryb ALL pomija bazę z założenia)" if fam == "DUMMY" else ""),
                                    f"artefakt {m['model_id']}: loader_parity {lp}, rola {man.get('role')}, rodzina {fitted.family}")
        ctx.step = "predict"
        tk = _shared(ctx, "lab_tick", _lab_tick)
        r = next((x for x in tk["state"].get("models") or [] if x.get("family") == fam), None) or {}
        warn = (r.get("telemetry") or {}).get("warnings") or []
        p = r.get("raw_score")
        note = (" UWAGA: quant/inventory.py:206 deklaruje 'bez ścieżki na żywo', a LabService ładuje każdą rodzinę (lab/service.py:196-217) "
                "i quant.adapters.lab publikuje rekord READY") if fam in LAB_EXPERIMENTS else ""
        out["predict"] = check(r.get("status") == "ready" and _finite(p) and 0.0 <= p <= 1.0 and r.get("model_id") == (m or {}).get("model_id")
                               and any("SYNTETYCZNYCH" in w for w in warn),
                               f"LabService.tick (MarketBridge/FakeMT5): {fam} ready, raw_score={p} (score, nie p(win)), {r.get('model_id')}, "
                               f"rola {r.get('role')} + ostrzeżenie MODEL_TECHNICZNY_NA_DANYCH_SYNTETYCZNYCH.{note}",
                               f"LabService.tick: wynik {fam} = {({k: r.get(k) for k in ('status', 'reason', 'model_id', 'raw_score')})}, ostrzeżenia {warn}")
        ctx.step = "contract"
        recs = [x for x in tk["recs"] if I.canonical(x) == f"lab:{fam}"]
        c = ctx.contract_step(recs)
        if c["status"] == "OK":
            x = recs[0]
            v = (x.get("result") or {}).get("raw_score")
            c = check(x.get("state") == "READY" and _finite(v) and math.isclose(v, float(p if p is not None else -1)) and x.get("data_kind") == "SYNTHETIC"
                      and x.get("unit") == "ratio",
                      f"quant.adapters.lab → PMW-PRED-2: {len(recs)} rekord READY, task {x.get('task')}, unit ratio, raw_score={v} = LabService, "
                      f"data_kind SYNTHETIC",
                      f"rekord quant.adapters.lab: stan {x.get('state')}, wynik {x.get('result')}, data_kind {x.get('data_kind')} (quant/adapters.py:358-394)")
        out["contract"] = c
        return out
    return smoke


# ---------------------------------------------------------------------------------------------------------------- lab tools
def _m29_fourier(ctx, out: dict) -> dict:
    import json

    import numpy as np

    from ...lab import fourier
    ctx.step = "predict"
    tk = _shared(ctx, "lab_tick", _lab_tick)
    fx = tk["state"].get("fourier") or {}
    db = _db(ctx)
    rows = {r["tf"]: r for r in db.query("SELECT tf, forecast_id, payload FROM lab_forecasts WHERE asset=? AND module='M29'", (INST,))}
    ready = {tf: v for tf, v in fx.items() if (v.get("forecast") or {}).get("status") == "ready"}
    c = 2000 + np.sin(np.arange(300) / 7) + np.arange(300) * 0.01
    direct = fourier.extrapolate(c)
    out["predict"] = check(bool(ready) and direct.get("status") == "ready" and all(_finite(*v["forecast"]["path"]) for v in ready.values()),
                           f"LabService.tick: prognoza M29 ready dla {sorted(ready)} (ścieżka {len(next(iter(ready.values()))['forecast']['path'])} świec, "
                           f"harmoniczne {[len(v['forecast']['harmonics']) for v in ready.values()]}); fourier.extrapolate(sinus) ready"
                           if ready else "brak", f"M29 w stanie lab: {({k: (v.get('forecast') or {}).get('status') for k, v in fx.items()})}, "
                           f"bezpośrednio {direct.get('status')}")
    ctx.step = "artifact"
    diffs = []
    for tf, v in ready.items():
        row = rows.get(tf)
        if row is None:
            diffs.append(f"{tf}: brak wiersza lab_forecasts")
            continue
        pl = json.loads(row["payload"])
        d = max(abs(a - b) for a, b in zip(pl["path"], v["forecast"]["path"]))
        if row["forecast_id"] != v["forecast_id"] or d > 1e-12:
            diffs.append(f"{tf}: id {row['forecast_id']}≠{v['forecast_id']} albo |Δ|={d}")
    out["artifact"] = check(bool(ready) and not diffs,
                            f"archiwum lab_forecasts (point-in-time) odczytane = prognoza stanu lab dla {sorted(ready)}, |Δścieżki|=0",
                            "; ".join(diffs) or "brak prognoz do archiwum")
    ctx.step = "contract"
    ev = [v.get("archive_evaluation") or {} for v in ready.values()]
    keys_ok = all({"status", "path", "harmonics", "params"} <= set(v["forecast"]) for v in ready.values())
    out["contract"] = check(keys_ok and all("evaluated_points" in e for e in ev),
                            f"słownik M29: status/path/harmonics/params + ocena archiwum (evaluated_points {[e.get('evaluated_points') for e in ev]})",
                            f"klucze M29 niekompletne: {[sorted(v['forecast']) for v in ready.values()]}, ocena {ev}")
    return out


def _m31_kinematics(ctx, out: dict) -> dict:
    import numpy as np

    from ...lab import ticks as TK
    ctx.step = "predict"
    tk = _shared(ctx, "lab_tick", _lab_tick)
    st = tk["state"].get("ticks") or {}
    kin = st.get("kinematics") or {}
    rng = np.random.default_rng(5)
    t0, mid, ticks = 1_790_000_000.0, 2400.0, []
    for i in range(600):                                    # dense quote stream (~2 quotes / s), Bid/Ask as the bridge returns them
        mid += rng.normal(0, 0.02)
        ticks.append({"t": t0 + 0.5 * i + rng.uniform(0, 0.1), "bid": round(mid - 0.06, 2), "ask": round(mid + 0.06, 2)})
    arch = []
    for k in range(200, 560, 40):
        r = TK.kinematics(ticks[:k])
        if r.get("status") == "ready":
            arch.append(r["forecast"])
    ver = TK.verify_forecasts(arch, ticks)
    live_ok = st.get("status") in ("ok", "missing_data") and kin.get("status") in ("ready", "missing_data")
    kin_txt = (f"ready (v={kin.get('velocity_per_s'):.4g}/s, n={kin.get('n')})" if kin.get("status") == "ready" and _finite(kin.get("velocity_per_s"))
               else f"{kin.get('status')} {kin.get('reason') or ''} (stan zwrócony przez kod – FakeMT5 ≈1 notowanie/6 s)")
    out["predict"] = check(live_ok and len(arch) >= 5 and ver.get("verified", 0) >= 5,
                           f"LabService._tick_quotes (MarketBridge.ticks FakeMT5): status {st.get('status')}, {st.get('count')} ticków, kinematyka {kin_txt}; "
                           f"TK.kinematics na gęstych tickach: {len(arch)} prognoz ready, verify_forecasts zweryfikowało {ver.get('verified')}",
                           f"ticki w stanie lab {({k: st.get(k) for k in ('status', 'reason', 'count')})}, kinematyka {kin.get('status')}, "
                           f"gęste: {len(arch)} ready, weryfikacja {ver}")
    ctx.step = "contract"
    last = TK.kinematics(ticks)
    out["contract"] = check(last.get("status") == "ready" and _finite(last["velocity_per_s"], last["acceleration_per_s2"], last["forecast"]["mid"])
                            and (last["velocity_se"] is None or _finite(last["velocity_se"])) and _finite(ver.get("mae")),
                            f"słownik M31: velocity/acceleration skończone, SE skończone lub None (bez NaN w JSON), MAE weryfikacji {ver.get('mae'):.4f}"
                            if _finite(ver.get("mae")) else "brak", f"słownik kinematyki {last}, weryfikacja {ver}")
    return out


def _m39_m41_edge(ctx, out: dict) -> dict:
    from ...lab.edge import block_bootstrap_mean, edge_drift
    ctx.step = "predict"
    tk = _shared(ctx, "lab_tick", _lab_tick)
    svc = tk["svc"]
    rep = svc.repaint.report()
    key = next(iter(svc.repaint.mem), None)
    changes = []
    if key is not None:                                     # the same closed bar evaluated again with another value -> CHANGED logged
        series = dict(svc.repaint.mem[key])
        bar = next(iter(series))
        series[bar] = {"smoke_changed": str(series[bar])}
        changes = svc.repaint.observe(key[0], key[1], key[2], series, "2026-01-01T00:00:00Z")
    n_db = (_db(ctx).one("SELECT COUNT(*) AS n FROM lab_repaint") or {}).get("n", 0)
    boot = block_bootstrap_mean([0.1] * 30 + [-0.05] * 30)
    drift = edge_drift([0.05] * 10 + [-0.4] * 30, baseline_mean=0.05)
    out["predict"] = check(bool(rep) and [c["change"] for c in changes] == ["CHANGED"] and n_db >= 1 and boot.get("status") == "ready"
                           and drift.get("state") in ("WARNING", "DEGRADED"),
                           f"M39 RepaintInspector w LabService.tick: {len(rep)} serii obserwowanych, ponowna ocena serii ze zmienioną zamkniętą świecą → "
                           f"{[c['change'] for c in changes]} zapisane w lab_repaint ({n_db}); M41 block_bootstrap_mean: {boot.get('verdict')} "
                           f"CI95 {[round(x, 4) for x in boot.get('ci95') or []]}; M40 edge_drift: {drift.get('state')} "
                           f"(edge_drift nie ma wywołania w kodzie bota – tylko lab/traceability.py)",
                           f"M39 raport {rep}, zmiany {changes}, wiersze {n_db}; M41 {boot}; M40 {drift}")
    ctx.step = "contract"
    out["contract"] = check(_finite(boot.get("mean"), *(boot.get("ci95") or [None])) and boot["ci95"][0] <= boot["mean"] <= boot["ci95"][1]
                            and _finite(drift.get("cusum")),
                            f"M41: mean {boot.get('mean'):.4f} w CI95, M40: cusum {drift.get('cusum')} skończony" if _finite(boot.get("mean")) else "brak",
                            f"M41 {boot}, M40 {drift}")
    return out


def _m42_trade_pad(ctx, out: dict) -> dict:
    from ...lab.edge import trade_pad_plan
    ctx.step = "predict"
    lv = _shared(ctx, "live", _live)
    meta = lv.bridge.symbol_meta(lv.sym) or {}
    meta = {**meta, **{k: (lv.bridge.symbol_info or {}).get(k) for k in ("volume_min", "volume_step")}}      # as api/app.py lab_tradepad
    q = lv.bridge.quote_status() or {}
    acct = (lv.bridge.account_status() or {}).get("currency")
    comm = lv.cfg.get().scalp.commission_per_lot_side
    e = float(q.get("ask") or 2400.0)
    plan = trade_pad_plan(side="BUY", entry=e, sl=e - 5.0, tp=e + 10.0, lots=0.1, meta=meta, quote=q or None,
                          commission_per_lot_side=float(comm or 0), account_currency=acct)
    try:
        trade_pad_plan(side="BUY", entry=e, sl=e + 5.0, tp=e + 10.0, lots=0.1, meta=meta, quote=None, commission_per_lot_side=0.0)
        refused = "NIE"
    except ValueError as exc:
        refused = str(exc)
    out["predict"] = check(plan.get("mode") == "SIMULATION_ONLY" and plan.get("rr") == 2.0 and refused == "SL_TP_WRONG_SIDE",
                           f"trade_pad_plan z metadanymi MarketBridge (jak /api/v1/lab/tradepad): BUY 0.1 lota, RR {plan.get('rr')}, P/L przy TP "
                           f"{plan.get('pnl_at_tp')} {plan.get('pnl_currency') or ''} ({plan.get('currency_status')}), prowizja z konfiguracji {comm}; "
                           f"SL po złej stronie odrzucony ({refused})",
                           f"trade pad: {plan}, odrzucenie złego SL: {refused}")
    ctx.step = "contract"
    need = ("mode", "execution", "rr", "pnl_at_tp", "pnl_at_sl", "commission_round_turn", "gross_at_tp_profit_ccy", "contract_size", "lot_valid")
    miss = [k for k in need if k not in plan]
    nums = [plan[k] for k in ("rr", "gross_at_tp_profit_ccy", "gross_at_sl_profit_ccy", "contract_size")]
    out["contract"] = check(not miss and _finite(*nums) and plan["execution"] == "VIA_MANUAL_PAD" and plan["lot_valid"] is True,
                            "słownik M42: komplet kluczy, liczby skończone, wykonanie tylko przez Manual Pad, lot poprawny",
                            f"brak kluczy {miss} albo wartości {nums} / execution {plan.get('execution')}")
    return out


def _si_service(ctx):
    from ...lab.si_service import StructureIntelligenceService
    lv = _shared(ctx, "live", _live)
    return StructureIntelligenceService(lv.cfg, lv.bridge, lv.db, lv.bus, lv.log)


def _quotes(ctx, out: dict) -> dict:
    import numpy as np

    from ...lab import quotes as Q
    ctx.step = "predict"
    si = _shared(ctx, "si_service", _si_service)
    pub = si.quote_tick(force_snapshot=True)                 # the si-quotes collector body (MarketBridge.ticks on FakeMT5)
    rng = np.random.default_rng(1)
    p, t0, tt, ticks = 2000.0, 1_700_000_000_000, 0, []
    for _ in range(3000):                                    # dense synthetic Bid/Ask stream: the forecast / score path needs > 8 quotes per scale
        tt += int(rng.integers(50, 400))
        p += rng.normal(0, 0.02)
        ticks.append({"t_ms": t0 + tt, "bid": round(p, 2), "ask": round(p + 0.12, 2)})
    eng = Q.QuoteEngine(f"{INST}|smoke", 0.01, 0.01)
    eng.ingest(ticks[:2000])
    now = ticks[1999]["t_ms"]
    snap = eng.snapshot(now)
    fc = eng.emit(snap, now)
    eng.ingest(ticks[2000:])
    sc = eng.score(t0 + tt)
    scored = [m for m in sc if m["status"] == "SCORED"]
    bid = {n: f.get("status") for n, f in ((pub or {}).get("sides") or {}).get("BID", {}).items()}
    out["predict"] = check(pub is not None and si.quote_status.get("status") == "OK" and len(fc) > 0 and len(scored) > 0,
                           f"StructureIntelligenceService.quote_tick (MarketBridge/FakeMT5): faza {pub.get('phase') if pub else None}, "
                           f"seq {pub.get('seq') if pub else None}, BID {bid}; "
                           f"QuoteEngine na gęstych tickach: {len(fc)} prognoz, {len(scored)}/{len(sc)} ocenionych SCORED, faza {snap['phase']}",
                           f"quote_tick → {si.quote_status}, gęste: prognozy {len(fc)}, ocenione {[m['status'] for m in sc][:5]}")
    ctx.step = "contract"
    bad = [f["forecast_id"] for f in fc if not (_finite(f["price"], f["se_model"], f["h_s"]) and f["se_model"] >= 0 and f["h_s"] > 0)]
    rows = si.quote_forecasts(50)
    out["contract"] = check(not bad and {"phase", "seq", "sides", "spread", "clock"} <= set(snap) and all(_finite(m["error"]) for m in scored),
                            f"słownik QuoteEngine: phase/seq/sides/spread/clock; prognozy z price/se_model/h_s skończonymi; błędy ocen skończone; "
                            f"quote_forecasts w bazie bota: {len(rows)} wierszy (FakeMT5)",
                            f"prognozy z wartościami nieskończonymi {bad[:3]} albo klucze migawki {sorted(snap)}")
    return out


# ---------------------------------------------------------------------------------------------------------------- Structure Intelligence
def _si_train(ctx) -> dict:
    from ...lab import structure_task as T
    exp = _shared(ctx, "export", _export)
    T.save_dataset(INST, T.build_move_dataset(INST, exp["dir"], log=_quiet))
    dsdir = T.latest_dataset(INST, T.TASK_MOVE)
    # temporary in-memory smoke profile (the 'quick' profile takes ~60 s for 7 families here); removed right after the run
    T.PROFILES[SI_PROFILE] = dict(T.PROFILES["quick"], epochs=1, max_fit_rows=200, mr_requested=168, mr_max_fit_rows=150, spike_max_fit_rows=24,
                                  batch=12, max_eval_rows=40, seeds=[11], net_cfg={"widths": [4, 8], "blocks_per_stage": 1, "cardinality": 2})
    try:
        rep = T.train(INST, dsdir, T.TASK_MOVE, list(SI_FAMILIES), SI_PROFILE, db=_db(ctx), log=_quiet,
                      spike_cfg={"encoder": "BAR_EVENT_V1", "attention": "HYBRID"})
    finally:
        T.PROFILES.pop(SI_PROFILE, None)
    return {"rep": rep, "dsdir": dsdir, "data": T.load_dataset(dsdir, T.TASK_MOVE), "m1": exp["n"]["M1"]}


def _si_live(ctx) -> dict:
    """What the bot does with the run: SHADOW selection (refused for TEST_ONLY), the SI snapshot forecast, the SH probe."""
    from ...lab import structure_task as T
    from ...sh import models as SM
    tr = _shared(ctx, "si_train", _si_train)
    lv = _shared(ctx, "live", _live)
    si = _shared(ctx, "si_service", _si_service)
    refusals = {}
    for fam, c in tr["rep"]["candidates"].items():
        if "candidate_id" in c:
            try:
                T.select_shadow(INST, c["candidate_id"])
                refusals[fam] = "PRZYJĘTY"
            except ValueError as exc:
                refusals[fam] = str(exc).split(":")[0]
    bars = {tf: lv.bars(tf) for tf in ("M1", "M5", "M15", "H1")}
    svc = si.forecast(bars, INST, lv.tick, None)             # the call of StructureIntelligenceService.snapshot (MTF dashboard)
    item = next(i for i in SM.REGISTRY if i["id"] == "si_move")
    probe = SM.probe(item, None, INST)
    return {"refusals": refusals, "bars": bars, "service": svc, "probe": probe}


def _si_family(fam: str):
    def smoke(ctx, out: dict) -> dict:
        from pathlib import Path

        import numpy as np

        from ...lab import structure_task as T
        from ...ml import scalp_task as stk
        ctx.step = "train"
        tr = _shared(ctx, "si_train", _si_train)
        rep = tr["rep"]
        c = rep["candidates"].get(fam) or {}
        fold = next((f for f in reversed(rep.get("folds") or []) if f.get("status") == "OK"), {})
        fst = [x.get("status") for x in (fold.get("families") or {}).get(fam) or []]
        bad = (None, "NAN_LOSS", "CANCELLED", "FAILED", "NOT_AVAILABLE", "BUDGET_EXCEEDED")
        out["train"] = check("candidate_id" in c and c.get("status") not in bad and bool(fst) and not any(x in bad for x in fst)
                             and rep.get("role") == "TEST_ONLY",
                             f"structure_task.train (jeden przebieg 7 rodzin, profil smoke w pamięci: 1 epoka, ≤200 wierszy FIT, 1 fold; eksport "
                             f"SYNTHETIC_TEST M1={tr['m1']}): fold {fst}, "
                             f"kandydat {c.get('status')}, status runu {rep.get('status')} (dane smoke), rola TEST_ONLY",
                             f"brak kandydata {fam}: {c} (run {rep.get('status')}, fold {fst})")
        ctx.step = "artifact"
        d = Path(rep["run_dir"]) / "models" / fam
        meta, model = T.load_candidate(d)                 # model hash of every file checked by the bot's loader
        data = tr["data"]
        sp = T.split(data)
        fb = stk.inner_blocks(sp["dev"], sp["rows"], sp["embargo_s"])
        _, Y, _ = T._task_arrays(data, T.TASK_MOVE)
        cal = fb["CALIBRATION"]
        P, _ = T._predict(model, fam, data, T.TASK_MOVE, cal)
        temps = [T._temperature(P[:, j], Y[cal, j]) for j in range(Y.shape[1])]
        dT = max(abs(a["T"] - b["T"]) for a, b in zip(temps, meta["calibration"]))
        out["artifact"] = check(meta["model_hash"] == c.get("model_hash") and dT == 0.0 and bool(np.isfinite(P).all()),
                                f"save_candidate → load_candidate (hash plików OK): temperatury kalibracji przeliczone z modelu po odczycie "
                                f"na bloku CALIBRATION ({len(cal)} wierszy) = zapisane, max|ΔT|={dT}; P skończone",
                                f"po odczycie: hash {meta['model_hash'][:12]} vs {str(c.get('model_hash'))[:12]}, max|ΔT|={dT}, T={[t['T'] for t in temps]} vs "
                                f"{[t['T'] for t in meta['calibration']]}")
        ctx.step = "predict"
        lv_si = _shared(ctx, "si_live", _si_live)
        ref = lv_si["refusals"].get(fam)
        svc = lv_si["service"]
        fc = T.Forecaster(INST)
        fc.meta, fc.model = T.load_candidate(d, {"task_id": T.TASK_MOVE, "feature_schema": T.FEATURE_SCHEMA, "instrument": INST,
                                                 "indicator_profile_hash": T.indicator_profile(INST)["hash"]})
        why = fc._live_incompatible(d)
        bars = lv_si["bars"]
        lv = _shared(ctx, "live", _live)
        res = fc.forecast(bars["M1"][-1500:], {tf: bars[tf] for tf in ("M5", "M15", "H1")}, lv.tick, point=lv.point) if why is None else {}
        pr = lv_si["probe"]
        out["predict"] = check(ref == "TEST_ONLY_ARTIFACT" and svc.get("forecast_status") == "ABSTAIN" and res.get("forecast_status") == "OK",
                               f"select_shadow odmówił ({ref}) – odmowa zgodnie z bramką; StructureIntelligenceService.forecast (jak migawka SI): "
                               f"{svc.get('forecast_status')} {svc.get('reason')}; sonda SH si_move: {pr.get('status')} ({pr.get('reason')}); "
                               f"brak adaptera Quant. Forecaster.forecast na kandydacie (load_candidate z warunkami Forecastera, bez wskaźnika SHADOW): OK, h3 "
                               f"p={[round(res['heads'][0][k], 3) for k in ('p_down', 'p_flat', 'p_up')] if res.get('heads') else None}",
                               f"bramka {ref}, serwis {svc}, Forecaster {res.get('forecast_status')} {res.get('reason') or why}")
        ctx.step = "contract"
        heads = res.get("heads") or []
        okh = [h for h in heads if _dist_ok([h["p_down"], h["p_flat"], h["p_up"]]) and _finite(h["q10"], h["q50"], h["q90"])
               and h["q10"] <= h["q50"] <= h["q90"]]
        out["contract"] = check(len(heads) == 3 and len(okh) == 3 and [h["h_bars"] for h in heads] == list(T.HORIZONS) and res.get("role") == "SHADOW",
                                f"słownik prognozy SI (bez rekordu PMW-PRED-2 – brak adaptera Quant): głowy h={[h['h_bars'] for h in heads]}, rozkład "
                                f"DOWN/FLAT/UP suma 1, q10≤q50≤q90, rola SHADOW",
                                f"prognoza SI: głowy {heads}, poprawne {len(okh)}")
        return out
    return smoke


# ---------------------------------------------------------------------------------------------------------------- NSS
def _nss_train(ctx) -> dict:
    """The CLI path first (`neural-scalp train` = nss.train on the export). The scalp replay finds no cycle on the synthetic export, so the
    network itself is trained by nss.run_protocol on a generated table whose INPUTS come from nss.snapshot (the bot's one feature function)
    on the export bars; the labels are a synthetic first-touch TP1 / SL / TIME of +-1 ATR (no strategy setup exists in these data)."""
    import hashlib
    from datetime import datetime

    import numpy as np

    from ...extind.trainer import _bars
    from ...lab import nss
    from ...scalp import strategy as stg
    exp = _shared(ctx, "export", _export)
    db = _db(ctx)
    cli = nss.train(INST, exp["dir"], db=db, train_cfg=NSS_TRAIN, log=_quiet)
    point = exp["point"]
    bars = {tf: [dict(b, spread_price=(b["spread"] * point if b["spread"] is not None else None)) for b in _bars(exp["dir"], exp["prefix"], tf)]
            for tf in ("M1", "M5", "M15", "H1")}
    idx = nss.index_bars(bars)
    prof = stg.load_profile(instrument=INST)
    hold = int((prof.get("exits") or {}).get("max_hold_minutes", {}).get("value") or 30)
    feats = {k: 0.1 for k in stg.SETUP_FEATURES}
    m1 = bars["M1"]
    ts = [nss._ts(b["open_utc"]) for b in m1]
    rows, M1, M5, C, skipped = [], [], [], [], {}

    def iso(t: float) -> str:
        return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    for i in range(0, len(m1) - hold - 1, 10):
        T = ts[i] + 60                                      # decision at the close of bar i
        s = nss.snapshot(idx, T, feats, NSS_CFG)
        if s["status"] != "OK":
            k = s["status"].split(":")[0]
            skipped[k] = skipped.get(k, 0) + 1
            continue
        side = "BUY" if len(rows) % 2 == 0 else "SELL"
        sg = 1 if side == "BUY" else -1
        entry, atr = m1[i]["c"], nss._atr(m1[max(0, i - 13):i + 1])
        ev, end, amb = 2, i + hold, False
        for j in range(i + 1, i + hold + 1):
            up, dn = m1[j]["h"] >= entry + atr, m1[j]["l"] <= entry - atr
            tp, sl = (up, dn) if sg > 0 else (dn, up)
            if tp or sl:
                ev, end, amb = (1 if sl else 0), j, bool(tp and sl)
                break
        r = 1.0 if ev == 0 else -1.0 if ev == 1 else sg * (m1[end]["c"] - entry) / atr
        rows.append({"setup_id": f"SMK{i}", "range_id": f"R{i // 30}", "side": side, "signal_time": iso(T), "label_end": iso(ts[end] + 60), "net_r": r,
                     "net_price": r * atr, "spread": m1[i]["spread_price"], "risk": atr, "ambiguous": amb, "event": ev})
        M1.append(s["m1"])
        M5.append(s["m5"])
        C.append(s["ctx"])
    arr = {"m1": np.array(M1, float), "m5": np.array(M5, float), "ctx": np.array(C, float), "side": np.array([0 if r["side"] == "BUY" else 1 for r in rows]),
           "y": np.array([r["event"] for r in rows], int), "r": np.array([r["net_r"] for r in rows], float)}
    meta = exp["meta"]
    data = {"instrument": INST, "symbol": meta["symbol"], "dataset_id": meta.get("dataset_id"), "data_kind": meta["data_kind"],
            "content_hash": hashlib.sha256(b"".join(np.ascontiguousarray(arr[k]).tobytes() for k in arr)).hexdigest()[:16],
            "profile_id": prof["profile_id"], "profile_hash": stg.profile_hash(prof), "costs": {"commission_per_lot_side": None, "commission_source": "SMOKE"},
            "availability_basis": "HISTORICAL_CLOSE_ASSUMPTION",
            "population": "punkty decyzyjne co 10 min (smoke; replay scalp na eksporcie syntetycznym: 0 cykli)",
            "skipped": skipped, "cfg": dict(NSS_CFG), "tick": exp["tick"], "rows": rows, "arr": arr, "prof": prof}
    rep = nss.run_protocol(INST, data, db=db, train_cfg=NSS_TRAIN, log=_quiet)
    return {"cli": cli, "rep": rep, "rows": len(rows), "skipped": skipped, "profile_hash": data["profile_hash"], "feats": feats}


def _nss_service(ctx):
    from ...lab.nss_service import NeuralScalpService
    lv = _shared(ctx, "live", _live)
    s = NeuralScalpService(lv.db, lv.bus, lv.log, instrument=INST)
    s.start()
    return s


def _nss(ctx, out: dict) -> dict:
    import time
    from datetime import datetime

    from ...lab import nss
    ctx.step = "train"
    tr = _shared(ctx, "nss_train", _nss_train)
    rep, cli = tr["rep"], tr["cli"]
    out["train"] = check(rep.get("status") == "EVALUATED" and rep.get("role") == "FIXTURE_ONLY" and bool(rep.get("model_hash")),
                         f"`neural-scalp train` (nss.train) na eksporcie syntetycznym: {cli.get('status')} ({cli.get('reason')}) – replay scalp bez cykli; "
                         f"nss.run_protocol na tabeli {tr['rows']} punktów z nss.snapshot (etykiety syntetyczne ±1 ATR): {rep.get('status')}, "
                         f"rola FIXTURE_ONLY, foldy {[f.get('status') for f in rep.get('folds') or []]}, "
                         f"strony {({k: v.get('status') for k, v in (rep.get('sides') or {}).items()})}",
                         f"run_protocol: {rep.get('status')} {rep.get('reason') or ''} (tabela {tr['rows']}, pominięte {tr['skipped']})")
    ctx.step = "artifact"
    bdir = nss.root(INST) / "fixture_runs" / rep["run_id"] / "bundle"
    b = nss.load_bundle(bdir)                            # files sha256 + schema checked by the bot's loader
    tf = (rep.get("final") or {}).get("temperatures") or {}
    dT = max((abs(float(tf[s]["T"]) - float(b.ens.temps[s]["T"])) for s in tf if "T" in tf[s]), default=None)
    out["artifact"] = check(b.man["model_hash"] == rep["model_hash"] and dT is not None and dT == 0.0 and b.man["role"] == "FIXTURE_ONLY",
                            f"save_bundle → load_bundle (sha256 plików OK): model_hash zgodny, temperatury finalnego ensemble po odczycie = raport "
                            f"(max|ΔT|={dT}), {len(b.ens.members)} członek, cfg m1_len={b.cfg.get('m1_len')}",
                            f"bundle: hash {b.man['model_hash'][:12]} vs {str(rep.get('model_hash'))[:12]}, ΔT={dT}, rola {b.man['role']}")
    ctx.step = "predict"
    try:
        nss.select(INST, rep["run_id"], "OBSERVE")
        gate = "PRZYJĘTY"
    except ValueError as exc:
        gate = str(exc)
    lv = _shared(ctx, "live", _live)
    svc = _shared(ctx, "nss_service", _nss_service)
    bars = {tf_: lv.bars(tf_) for tf_ in ("M1", "M5", "M15", "H1")}
    T = nss._ts(bars["M1"][-1]["open_utc"]) + 60
    plan = {"setup_id": "SMOKE-NSS-1", "range_id": "R-SMOKE", "direction": "BUY", "decision_ts": T,
            "decision_time": datetime.fromtimestamp(T, UTC).isoformat(), "sl": 1.0, "tp1": 2.0, "tp2": 3.0, "entry_mode": "MARKET",
            "features": tr["feats"]}
    q = svc.submit(plan, bars, instrument=INST, profile_hash=tr["profile_hash"], epoch=1, point=lv.point)
    end = time.monotonic() + 15
    while time.monotonic() < end and (svc.last is None or svc.last.get("request_id") != q["request_id"]):
        time.sleep(0.05)
    rec = svc.last or {}
    n_db = (lv.db.one("SELECT COUNT(*) AS n FROM nss_inferences WHERE request_id=?", (q["request_id"],)) or {}).get("n", 0)
    tail = svc._with_spread(svc._tail(bars), lv.point)
    snap = nss.snapshot(nss.index_bars(tail), T, tr["feats"], b.cfg)
    pr = b.predict(snap, instrument=INST, profile_hash=tr["profile_hash"], side="BUY")
    co = pr.get("candidate_output") or {}
    out["predict"] = check(gate == "FIXTURE_ONLY_NOT_SELECTABLE" and rec.get("technical_status") == "NO_MODEL" and rec.get("archived") is True and n_db == 1
                           and lv.bus.activity().get("lab_neural", {}).get("count", 0) >= 1 and pr.get("technical_status") == "READY_INFERENCE",
                           f"nss.select odmówił ({gate}) – odmowa zgodnie z bramką; NeuralScalpService.submit → worker: {rec.get('technical_status')} "
                           f"(rekord w nss_inferences, zdarzenie lab_neural); bundle.predict na nss.snapshot z MarketBridge: READY_INFERENCE, "
                           f"P(TP1/SL/TIMEOUT) surowe {[round(x, 3) for x in co.get('raw_probabilities') or []]}, net_R {co.get('expected_net_R')}",
                           f"bramka {gate}; serwis {rec.get('technical_status')} archiwum {rec.get('archived')} wiersze {n_db}; "
                           f"bundle {pr.get('technical_status')} {pr.get('reason') or ''}")
    ctx.step = "contract"
    raw, calp = co.get("raw_probabilities") or [], co.get("calibrated_probabilities")
    out["contract"] = check(co.get("class_order") is not None and len(co["class_order"]) == 3 and _dist_ok(raw) and (calp is None or _dist_ok(calp))
                            and _finite(co.get("expected_net_R")) and rec.get("candidate_output") is None and bool(rec.get("inputs")),
                            f"słownik NSS (setup-scoped – brak samodzielnego rekordu PMW-PRED-2): klasy {co.get('class_order')}, P surowe i "
                            f"{'kalibrowane' if calp else 'kalibracja ' + str(co.get('calibration_status'))} sumują się do 1, net_R skończone; "
                            f"rekord serwisu bez modelu nie ma wyniku (NO_MODEL), ma wejścia {[i['quality'] for i in rec.get('inputs') or []]}",
                            f"wyjście NSS {co}, rekord serwisu {({k: rec.get(k) for k in ('technical_status', 'candidate_output', 'reasons')})}")
    return out


# ---------------------------------------------------------------------------------------------------------------- flow context
def _flow_train(ctx) -> dict:
    import contextlib
    import io
    import json

    from ...lab.flow_context import cli as FC
    from ...lab.flow_context import task as FT
    exp = _shared(ctx, "export", _export)
    ds = str(exp["dir"])
    with contextlib.redirect_stdout(io.StringIO()) as blocked:
        rc_blocked = FC.main(["train-markov", "--asset", INST, "--dataset", ds])           # without the flag synthetic data are refused
    with contextlib.redirect_stdout(io.StringIO()) as mk_out:
        rc_mk = FC.main(["train-markov", "--asset", INST, "--dataset", ds, "--allow-synthetic-fixture"])
    with contextlib.redirect_stdout(io.StringIO()):
        rc_ds = FC.main(["dataset", "--asset", INST, "--dataset", ds, "--allow-synthetic-fixture"])
    if rc_mk != 0 or rc_ds != 0:
        raise RuntimeError(f"flow-context train-markov kod {rc_mk}, dataset kod {rc_ds}")
    try:
        mk = json.loads(mk_out.getvalue())
    except ValueError:
        mk = {}
    rep = FT.train(INST, FT.latest(INST), ["LOGREG", "XGB"], "quick", db=_db(ctx), log=_quiet, ablation=False)
    return {"rc_blocked": rc_blocked, "blocked": blocked.getvalue().strip()[:160], "markov": mk, "rep": rep}


def _flow_cell(ctx) -> dict:
    """M1 cell of the SI snapshot (StructureIntelligenceService.cell -> FlowSections.update/summary) on the bridge bars.

    The smoke Markov fit is TEST_ONLY (synthetic export). Decision D23 (b): the bot does not load it into the SI cell - checked first on a
    separate FlowSections without the test opt-in (MODEL_TEST_ONLY_NOT_LOADED expected); the SI service cell is then built with
    PMW_FLOW_ALLOW_TEST_MODEL=1 so the live path of a loaded model is exercised. The variable is set only around that call (a flow key reads
    it once, when it is created) in this area process, which runs on a temporary MASTERQUO_DATA_DIR."""
    import os

    from ...lab.flow_context import service as FS
    lv = _shared(ctx, "live", _live)
    si = _shared(ctx, "si_service", _si_service)
    _shared(ctx, "flow_train", _flow_train)
    m1 = lv.bars("M1")
    prev = os.environ.pop(FS.ALLOW_TEST_MODEL_ENV, None)
    try:
        fs = FS.FlowSections()                                  # without the opt-in: the bot's own D23 gate
        gated = fs.summary(fs.update(INST, "M1", m1, lv.point, lv.tick))
        os.environ[FS.ALLOW_TEST_MODEL_ENV] = "1"
        cell = si.cell("M1", m1, lv.tick, [], INST)
    finally:
        if prev is None:
            os.environ.pop(FS.ALLOW_TEST_MODEL_ENV, None)
        else:
            os.environ[FS.ALLOW_TEST_MODEL_ENV] = prev
    return {"cell": cell, "flow": cell.get("flow") or {}, "gated": gated}


def _flow_markov3(ctx, out: dict) -> dict:
    import json
    from pathlib import Path

    from ...lab.flow_context import markov as MK
    from ...lab.flow_context import task as FT
    ctx.step = "train"
    tr = _shared(ctx, "flow_train", _flow_train)
    mk = tr["markov"]
    m3 = (mk.get("models") or {}).get(MK.M3) or {}
    out["train"] = check(tr["rc_blocked"] == 2 and "BLOCKED_SYNTHETIC" in tr["blocked"] and mk.get("role") == "TEST_ONLY" and bool(m3.get("fit")),
                         f"flow-context train-markov: bez --allow-synthetic-fixture odmowa (kod 2, BLOCKED_SYNTHETIC) – zgodnie z bramką; z flagą: Markov3 "
                         f"tau={m3['fit'].get('tau_points'):.2f} pkt na {m3['fit'].get('train_bars')} świecach M1 DEV, ocena prekwencyjna n="
                         f"{(m3.get('dev_eval') or {}).get('n')}, rola TEST_ONLY" if m3.get("fit") else "brak",
                         f"train-markov: odmowa {tr['rc_blocked']} '{tr['blocked']}', wynik {({k: mk.get(k) for k in ('role', 'dir')})}")
    ctx.step = "artifact"
    # the fit just trained (train-markov "dir"); a TEST_ONLY fit does not replace a RESEARCH model in latest.txt (D23)
    d = Path(mk.get("dir") or (FT.root(INST) / "markov" / "latest.txt").read_text(encoding="utf-8").strip())
    raw = json.loads((d / "markov3.json").read_text(encoding="utf-8"))
    back = json.loads(json.dumps(MK.Markov3.from_dict(raw).to_dict(), default=float))
    diff = [k for k in raw if raw[k] != back.get(k)]
    md = MK.MarkovDiff.load(d / "diff")                      # emissions sha256 + transition rows checked by the loader
    out["artifact"] = check(not diff and md.bins.get("K_effective", 0) >= 2,
                            f"markov3.json → Markov3.from_dict → to_dict: parametry identyczne (tau, ring {len(raw.get('ring') or [])} przejść); "
                            f"MarkovDiff.load (sha256 emisji) K_eff={md.bins.get('K_effective')}",
                            f"różne pola po odczycie {diff}, K_eff {md.bins.get('K_effective')}")
    ctx.step = "predict"
    fc = _shared(ctx, "flow_cell", _flow_cell)
    fl = fc["flow"]
    g3 = (fc["gated"] or {}).get("markov3") or {}
    m3o = fl.get("markov3") or {}
    nxt = m3o.get("next") or {}
    out["predict"] = check(g3.get("status") == "MODEL_TEST_ONLY_NOT_LOADED" and "next" not in g3
                           and fl.get("status") == "OK" and m3o.get("state") in ("DOWN", "FLAT", "UP") and _dist_ok(nxt),
                           f"bramka D23: bez PMW_FLOW_ALLOW_TEST_MODEL komórka M1 nie wczytuje modelu TEST_ONLY ({g3.get('status')}, dane "
                           f"{g3.get('data_kind')}) – zgodnie z bramką; z PMW_FLOW_ALLOW_TEST_MODEL=1 (tylko proces obszaru na folderze tymczasowym) "
                           f"StructureIntelligenceService.cell('M1') → FlowSections (MarketBridge/FakeMT5): Markov3 stan {m3o.get('state')}, następny "
                           f"{({k: round(v, 3) for k, v in nxt.items()})}, wiadra {sorted((fl.get('buckets') or {}).keys())}",
                           f"bramka D23 bez zmiennej: {g3}; komórka M1 flow z PMW_FLOW_ALLOW_TEST_MODEL=1: {fl.get('status')} markov3 {m3o}")
    ctx.step = "contract"
    marker = m3o.get("model_role") == "TEST_ONLY" and m3o.get("data_kind") == "SYNTHETIC_TEST"
    gate_keys = {"status", "model_role", "data_kind", "reason"} <= set(g3)
    out["contract"] = check(_dist_ok(nxt) and marker and gate_keys,
                            f"słownik markov3 z oznaczeniem pochodzenia (model_role {m3o.get('model_role')}, data_kind {m3o.get('data_kind')}), rozkład next "
                            "suma 1; decyzja D23 (b): model TEST_ONLY nie trafia do komórki SI (MODEL_TEST_ONLY_NOT_LOADED z model_role, data_kind, "
                            "reason), wczytywany tylko ze zmienną testów PMW_FLOW_ALLOW_TEST_MODEL=1",
                            f"markov3 bez oznaczenia TEST_ONLY/SYNTHETIC_TEST ({m3o.get('model_role')}/{m3o.get('data_kind')}), stan bramki bez pól "
                            f"model_role/data_kind/reason ({sorted(g3)}) albo rozkład next {'poprawny' if _dist_ok(nxt) else 'NIEPOPRAWNY'}")
    return out


def _flow_reaction(ctx, out: dict) -> dict:
    from pathlib import Path

    import numpy as np

    from ...extind.trainer import _bars
    from ...lab import structure_task as T
    from ...lab.flow_context import task as FT
    from ...ml import scalp_task as stk
    from ...sh import models as SM
    ctx.step = "train"
    tr = _shared(ctx, "flow_train", _flow_train)
    rep = tr["rep"]
    cands = rep.get("candidates") or {}
    fold = next((f for f in reversed(rep.get("folds") or []) if f.get("status") == "OK"), {})
    out["train"] = check(all((cands.get(f) or {}).get("status") == "TRAINED" for f in ("LOGREG", "XGB")) and rep.get("role") == "TEST_ONLY",
                         f"flow-context dataset (--allow-synthetic-fixture) + task.train (profil quick, bez ablacji): kandydaci "
                         f"{({k: v.get('status') for k, v in cands.items()})}, fold {sorted((fold.get('families') or {}).keys())}, status {rep.get('status')}, "
                         f"rola TEST_ONLY", f"flow train: {rep.get('status')} kandydaci {cands}")
    ctx.step = "artifact"
    data = FT.load(FT.latest(INST))
    sp = T.split(data)
    fb = stk.inner_blocks(sp["dev"], sp["rows"], sp["embargo_s"])
    b = data["rows_idx"]
    X, Y = data["fe"]["F"][b], data["Y"][b].astype(np.int64)
    cal = fb["CALIBRATION"]
    dts, loaded = {}, {}
    for fam in ("LOGREG", "XGB"):
        meta, m = FT.load_candidate(Path(rep["run_dir"]) / "models" / fam)
        P, _ = m.predict(X[cal])
        temps = [T._temperature(P[:, j], Y[cal, j]) for j in range(Y.shape[1])]
        dts[fam] = max(abs(a["T"] - c["T"]) for a, c in zip(temps, meta["calibration"]))
        loaded[fam] = (meta, m)
    out["artifact"] = check(all(v == 0.0 for v in dts.values()),
                            f"save_candidate → load_candidate (sha256 tabular.npz): temperatury przeliczone po odczycie na bloku CALIBRATION "
                            f"({len(cal)}) = zapisane, max|ΔT| {dts}", f"po odczycie ΔT {dts}")
    ctx.step = "predict"
    exp = _shared(ctx, "export", _export)
    fl = _shared(ctx, "flow_cell", _flow_cell)["flow"]
    try:
        FT.select_shadow(INST, cands["LOGREG"]["candidate_id"])
        gate = "PRZYJĘTY"
    except ValueError as exc:
        gate = str(exc)
    probe = SM.probe(next(i for i in SM.REGISTRY if i["id"] == "flow_reaction"), None, INST)
    m1 = _bars(exp["dir"], exp["prefix"], "M1")[-1500:]
    fe = FT.features(m1, exp["point"], exp["tick"], FT.profile(INST))
    preds = {fam: m.predict(fe["F"][-1:]) for fam, (_, m) in loaded.items()}
    reaction_live = [k for k in fl if "reaction" in k.lower() or k in ("LOGREG", "XGB", "probabilities")]
    out["predict"] = check(gate == "TEST_ONLY_ARTIFACT" and not reaction_live and all(_dist_ok(P[0, 0]) for P, _ in preds.values()),
                           f"brak ścieżki na żywo: komórka SI M1 (FlowSections) nie liczy modelu reakcji (klucze {','.join(sorted(fl))}); "
                           f"select_shadow: {gate} – odmowa zgodnie z bramką; sonda SH flow_reaction: {probe.get('status')} ({probe.get('reason')}); "
                           f"po odczycie na FT.features h3 P(D/F/U) {({f: [round(float(x), 3) for x in P[0, 0]] for f, (P, _) in preds.items()})}",
                           f"bramka {gate}, klucze flow {sorted(fl.keys())}, P {({f: P[0, 0].tolist() for f, (P, _) in preds.items()})}")
    ctx.step = "contract"
    okq = all(bool(np.all(np.diff(Q[0], axis=-1) >= 0)) and bool(np.isfinite(Q).all()) for _, Q in preds.values())
    out["contract"] = check(all(P.shape[1:] == (len(T.HORIZONS), 3) and all(_dist_ok(P[0, j]) for j in range(P.shape[1])) for P, _ in preds.values()) and okq,
                            f"słownik reakcji (bez rekordu PMW-PRED-2 – brak konsumenta): {len(T.HORIZONS)} głowy × DOWN/FLAT/UP suma 1, kwantyle q10≤q50≤q90",
                            f"kształty {[P.shape for P, _ in preds.values()]}, kwantyle uporządkowane {okq}")
    return out


# ---------------------------------------------------------------------------------------------------------------- context indicators
def _context_move(ctx, out: dict) -> dict:
    from pathlib import Path

    import numpy as np

    from ...extind.trainer import _bars
    from ...lab import structure_task as T
    from ...lab.context_ind import task as CT
    from ...ml import scalp_task as stk
    from ...sh import models as SM
    try:
        ctx.step = "train"
        exp = _shared(ctx, "export", _export)
        man = CT.build_dataset(INST, exp["dir"], log=_quiet)
        rep = CT.train(INST, CT.latest(INST), families=("LOGREG", "XGB"), profile_name="quick", db=_db(ctx), log=_quiet)
        fold = next((f for f in reversed(rep.get("folds") or []) if f.get("status") == "OK"), {})
        c = (rep.get("candidates") or {}).get("LOGREG") or {}
        out["train"] = check("candidate_id" in c and rep.get("role") == "TEST_ONLY" and bool(fold),
                             f"context_ind build_dataset ({man['rows']} wierszy M5) + task.train (profil quick): {rep.get('status')}, fold "
                             f"{({k: v.get('status') for k, v in (fold.get('families') or {}).items()})}, kandydat LOGREG (XGB tylko w foldach – z założenia "
                             f"context_ind/task.py:293), rola TEST_ONLY", f"context train: {rep.get('status')} kandydaci {rep.get('candidates')}")
        ctx.step = "artifact"
        meta, m = CT.load_candidate(Path(rep["run_dir"]) / "models" / "LOGREG")
        data = CT._load(CT.latest(INST))
        sp = T.split(data)
        fb = stk.inner_blocks(sp["dev"], sp["rows"], sp["embargo_s"])
        b = data["rows_idx"]
        X, Y, R = data["fe"]["F"][b], data["Y"][b].astype(np.int64), data["R"][b].astype(np.float64)
        ref = T.Tabular("LOGREG", len(CT.HORIZONS)).fit(X, Y, R, fb["FIT"], fb["TUNE"])     # the trainer's (deterministic) fit on the same blocks
        P1, _ = m.predict(X[-200:])
        P2, _ = ref.predict(X[-200:])
        d = float(np.max(np.abs(P1 - P2)))
        out["artifact"] = check(d < 1e-12 and meta.get("role") == "TEST_ONLY",
                                f"tabular.npz → load_candidate (sha256 + lista cech): P po odczycie vs ten sam deterministyczny fit trenera "
                                f"na blokach FIT/TUNE, max|ΔP|={d:.1e} na 200 wierszach", f"po odczycie max|ΔP|={d}, rola {meta.get('role')}")
        ctx.step = "predict"
        probe = SM.probe(next(i for i in SM.REGISTRY if i["id"] == "context_move"), None, INST)
        m5 = _bars(exp["dir"], exp["prefix"], "M5")[-600:]
        fe = CT.features(m5, exp["tick"], CT.profile(INST))
        P, Q = m.predict(fe["F"][-1:])
        out["predict"] = check(probe.get("status") == "NOT_CONNECTED" and all(_dist_ok(P[0, j]) for j in range(P.shape[1])),
                               f"stan zwrócony przez kod: sonda SH context_move {probe.get('status')} ({probe.get('reason')}) – "
                               f"brak ścieżki inferencji na żywo; kandydat po odczycie na CT.features (ostatnia M5 eksportu): h3 P(DOWN/FLAT/UP) "
                               f"{[round(float(x), 3) for x in P[0, 0]]}",
                               f"sonda {probe}, P {P[0].tolist()}")
        ctx.step = "contract"
        okq = bool(np.all(np.diff(Q[0], axis=-1) >= 0)) and bool(np.isfinite(Q).all())
        out["contract"] = check(P.shape[1:] == (len(CT.HORIZONS), 3) and okq,
                                f"słownik CONTEXT_MOVE_M5_V1 (bez rekordu PMW-PRED-2): głowy h={list(CT.HORIZONS)} M5 × DOWN/FLAT/UP suma 1, q10≤q50≤q90",
                                f"kształt {P.shape}, kwantyle uporządkowane {okq}")
    finally:
        _teardown(ctx)                                      # last producer of the area: stop the bridge / NSS worker threads
    return out


SMOKES = {
    **{f"lab:{f}": _partial(_lab_family(f)) for f in LAB_FAMILIES + LAB_EXPERIMENTS},
    "lab:M29_fourier": _partial(_m29_fourier),
    "lab:M31_tick_kinematics": _partial(_m31_kinematics),
    "lab:M39_M41_edge": _partial(_m39_m41_edge),
    "lab:M42_trade_pad": _partial(_m42_trade_pad),
    "quotes:MQ_NEWTONIAN_QUOTES_V2": _partial(_quotes),
    **{f"si:{f}": _partial(_si_family(f)) for f in SI_FAMILIES},
    "nss:tcn": _partial(_nss),
    "flow:markov3": _partial(_flow_markov3),
    "flow:reaction_m1": _partial(_flow_reaction),
    "context_ind:context_move_m5": _partial(_context_move),
}
