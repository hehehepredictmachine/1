"""API routes: laboratorium.

register(app, ctx): laboratorium 1.14, kontekst wskaźników IQ (PMW-UPD-02), modele / badania / próby / strefy / repaint laboratorium
    (22 routes; create_app before the split, 7ba7ab0: lines 377-607)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

import json
import os
import re as _re  # lab_study; base create_app (7ba7ab0) bound `_re` later, in the market block (import re as _re): same module
import sys

from fastapi import Body, HTTPException, Query

from ... import paths
from ...config import ALLOWED_ASSETS
from ...timeutil import TIMEFRAMES
from ..common import body_num


def register(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 377-607: 22 routes."""
    rt = ctx.rt
    _asset = ctx._asset
    _check_asset = ctx._check_asset
    _nss_job = ctx._nss_job

    @app.get("/api/v1/lab")
    def lab_state(asset: str | None = None):
        return rt.lab.public(_asset(asset))

    @app.get("/api/v1/lab/traceability")
    def lab_trace():
        from ...lab import traceability
        return {"rows": traceability.ROWS, "summary": traceability.summary()}

    @app.get("/api/v1/lab/memory")
    def lab_memory(tf: str = Query(...), t: str = Query(...)):
        from ...lab.sessions import memory_sequence
        if tf not in TIMEFRAMES:
            raise HTTPException(400, "INVALID_TIMEFRAME")
        from ...timeutil import parse_iso
        try:
            parse_iso(t)                                  # 1.46: garbage / naive time was an unhandled 500
        except (TypeError, ValueError):
            raise HTTPException(400, "INVALID_TIME: ISO-8601 z Z albo przesunięciem") from None
        by = {x: [b for b in rt.bridge.bars(x, 500, include_forming=False) if b.get("open_utc")] for x in ("M1", "M5", "M15", "M30", "H1", "H4", "D1")}
        return {"asset": rt.cfg.get().assets.active, **memory_sequence(by, tf, t)}

    @app.post("/api/v1/lab/train")
    def lab_train(body: dict = Body(default={})):
        from ...lab.protocol import default_protocol, FAMILIES, EXPERIMENTS
        a = _asset(body.get("asset"))
        if body.get("task_id") == "SCALP_SETUP_MARKET_V1":           # PMW-UPD-04 NSS: same jobs view, own child process, activate=none
            return _nss_job(["train", "--asset", a, "--activate", "none"])
        if a != rt.cfg.get().assets.active:
            raise HTTPException(409, "TRAIN_ONLY_ACTIVE_ASSET")
        sym = _check_asset(a, "TRAINING")
        if rt.bridge.state != "CONNECTED":
            raise HTTPException(409, "MT5_NOT_CONNECTED")
        fams = [f for f in (body.get("families") or FAMILIES) if f in FAMILIES]
        exps = [e for e in (body.get("experiments") if body.get("experiments") is not None else EXPERIMENTS) if e in EXPERIMENTS]
        nbars = int(min(max(body_num(body, "bars", 20000, int), 2000), 100000))
        min_events = body_num(body, "min_events", 600, int, 1, 10_000_000)
        bars = [b for b in rt.bridge.symbol_bars(sym, "M5", nbars) if b.get("closed") and b.get("open_utc")]
        prot = default_protocol(a, families=fams, experiments=exps, min_events=min_events)
        meta = rt.bridge.symbol_meta(sym) or {}
        if not meta.get("point"):
            raise HTTPException(409, "NO_SYMBOL_METADATA")       # 1.46: was trained with an assumed point 0.01 (missing data guessed)
        src = "SYNTHETIC" if (rt.demo or rt.bridge.synthetic or rt.cfg.get().synthetic_demo) else "MT5"
        return rt.lab.trainer.start(a, bars, point=float(meta["point"]), data_source=src,
                                    instrument_id=rt.assets.instrument(a)["instrument_id"], protocol=prot,
                                    artifact_family=body.get("artifact_family") if (body.get("artifact_family") in fams or body.get("artifact_family") == "ALL") else "auto")

    @app.get("/api/v1/lab/jobs")
    def lab_jobs():
        return {"jobs": rt.lab.trainer.public()}

    @app.post("/api/v1/lab/jobs/{jid}/cancel")
    def lab_cancel(jid: str):
        return rt.lab.trainer.cancel(jid)

    # ------------------------------------------------------------ PMW-UPD-02: IQ Gold Gann / IQ Star Lines / PAL02M / SAR
    @app.get("/api/v1/indicator-context")
    def indicator_context_status():
        from ...extind import features as icf
        from ...extind import trainer as ict
        inst = rt.cfg.get().assets.active
        reg_p = ict.root(inst) / "registry.json"
        reg = json.loads(reg_p.read_text(encoding="utf-8")) if reg_p.exists() else {"active": None, "runs": {}}
        runs = {k: v for k, v in sorted(reg.get("runs", {}).items())[-10:]}
        return {"instrument": inst, "sources": rt.extind.status(inst), "sar": {"profile": "MQ_SAR_WILDER_PROFILE_V1", "live_params": {"step": 0.02, "max": 0.2},
                "implementation_status": "VERIFIED_REFERENCE_TESTS", "weights_training": "NOT_APPLICABLE", "calibration": "GRID_ON_TRAIN_FOLD (indicator-context calibrate-sar)",
                "mt5_parity": "MT5_PARITY_NOT_RUN"}, "model": {"active": reg.get("active"), "runs": runs,
                "task_id": "SCALP_TP1_FIRST_WITHIN_FROZEN_POLICY_V1", "schema": icf.FEATURE_SCHEMA}}       # 1.46 arch I0163: the current schema

    @app.get("/api/v1/indicator-context/chart")
    def indicator_context_chart(tf: str = Query("M5")):
        from ...scalp.indicators import SAR_PROFILE, sar_points
        from ...timeutil import utcnow as _now
        if tf not in TIMEFRAMES:
            raise HTTPException(400, "INVALID_TIMEFRAME")        # 1.46: unknown TF was a KeyError in the bar buffer -> 500
        b = [x for x in rt.bridge.bars(tf, 600, include_forming=False) if x.get("open_utc")]
        sar = None
        if len(b) >= 2:
            pts = sar_points([x["h"] for x in b], [x["l"] for x in b], 0.02, 0.2)
            sar = {"profile": SAR_PROFILE, "params": {"step": 0.02, "max": 0.2},
                   "points": [{"t": b[i]["open_utc"], "sar": p["sar"], "trend": p["trend"], "flip": p["flip"]} for i, p in enumerate(pts) if p]}
        inst = rt.cfg.get().assets.active
        lv = []
        for a, short in (("IQ_GOLD_GANN", "IQ Gann"), ("IQ_STAR_LINES", "IQ Star")):
            snap = rt.extind.as_of(a, inst, _now())
            for x in (snap or {}).get("levels") or []:
                if x.get("kind") == "LEVEL" and x.get("price") is not None:
                    lv.append({"price": x["price"], "title": f"{short}: {x.get('role')}", "adapter": a, "snapshot_id": snap["snapshot_id"],
                               "known_at": snap["available_at"]})
        return {"tf": tf, "instrument": inst, "sar": sar, "ext_levels": lv}

    @app.get("/api/v1/indicator-context/inventory")
    def indicator_context_inventory(adapter: str = Query(...)):
        if adapter not in ("IQ_GOLD_GANN", "IQ_STAR_LINES", "PAL02M"):
            raise HTTPException(400, "UNKNOWN_ADAPTER")
        from ...extind import mapping as emp
        return {"adapter": adapter, "heartbeat": rt.extind.heartbeat.get(adapter), "mapping": emp.mapping(adapter), "manifest": emp.manifest(adapter)}

    @app.put("/api/v1/indicator-context/mapping")
    def indicator_context_mapping(body: dict):
        from ...extind import mapping as emp
        a = body.get("adapter")
        if a not in ("IQ_GOLD_GANN", "IQ_STAR_LINES"):
            raise HTTPException(400, "MAPPING_ONLY_FOR_IDENTIFIED_IQ")
        try:
            return emp.save_mapping(a, body)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    # 1.46: one heavy training process per kind - every POST started another one (4 CPU) and parallel runs raced on registry.json
    train_procs: dict = rt.api_services.train_procs                    # Etap 4 (krok A): owned by the composition root (rt.api_services)
    train_procs_lock = rt.api_services.train_procs_lock

    def _train_start(kind: str, start):
        with train_procs_lock:                                         # check + start atomically (a double click runs in 2 pool threads)
            pr = train_procs.get(kind)
            if pr is not None and pr.poll() is None:
                raise HTTPException(409, "JOB_RUNNING – jedno zadanie treningu naraz (poprzedni proces jeszcze działa)")
            train_procs[kind] = start()
            # arch146 I0100: ended by Runtime.stop() (tree without MT5)
            from ... import procs as _procs
            _procs.REGISTRY.register(f"api:{kind}", train_procs[kind], "training")
            return train_procs[kind]

    @app.post("/api/v1/indicator-context/train")
    def indicator_context_train(body: dict):
        """Separate process (never in the bot); POST returns at once, the result is in the registry/report."""
        import subprocess
        inst = body.get("asset") or rt.cfg.get().assets.active
        if inst not in ALLOWED_ASSETS:
            raise HTTPException(400, "UNKNOWN_INSTRUMENT")
        comm = body_num(body, "commission", None, float, 0, 1000)      # 1.46: 'abc' was a ValueError -> 500, NaN / negative went to the CLI
        from ...training import core as tc
        kw = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if os.name == "nt" else {"start_new_session": True}
        cmd = [sys.executable, "-m", "masterquo", "indicator-context", "train", "--asset", inst]
        if comm is not None:
            cmd += ["--commission", str(comm)]

        def start():
            with open(tc.training_dir() / "indicator_context_train.log", "a", encoding="utf-8") as log:      # the child keeps its own handle
                return subprocess.Popen(cmd, cwd=str(paths.ROOT_DIR / "backend"), stdout=log, stderr=subprocess.STDOUT, **kw)
        _train_start("indicator_context", start)
        return {"started": True, "instrument": inst}

    # 1.46: asset from the body is checked (XAUUSD / BTC) - '../..' created folders and files outside the data folder, a list was a 500
    @app.post("/api/v1/indicator-context/activate")
    def indicator_context_activate(body: dict):
        from ...extind import trainer as ict
        inst = _asset(body.get("asset") or rt.cfg.get().assets.active)
        try:
            return {"ok": True, "active": ict.activate(inst, str(body.get("run_id")), str(body.get("variant")))}
        except (ValueError, OSError, KeyError) as exc:
            return {"ok": False, "reason": str(exc)}

    @app.post("/api/v1/indicator-context/rollback")
    def indicator_context_rollback(body: dict):
        from ...extind import trainer as ict
        inst = _asset(body.get("asset") or rt.cfg.get().assets.active)
        try:
            return {"ok": True, "active": ict.rollback(inst)}
        except (ValueError, OSError) as exc:
            return {"ok": False, "reason": str(exc)}

    @app.get("/api/v1/lab/models")
    def lab_models(asset: str | None = None):
        a = _asset(asset)
        return {"asset": a, "models": rt.lab.trainer.models(a)}

    @app.get("/api/v1/lab/studies/{jid}")
    def lab_study(jid: str):
        if not _re.fullmatch(r"LJOB-[0-9TZ]+-[0-9a-f]{4}", jid):
            raise HTTPException(400, "INVALID_JOB_ID")
        f = rt.lab.trainer.root / "studies" / f"{jid}.json"
        if not f.exists():
            raise HTTPException(404, "NO_STUDY")
        return json.loads(f.read_text(encoding="utf-8"))

    @app.get("/api/v1/lab/trials")
    def lab_trials(asset: str | None = None):
        a = _asset(asset)
        return {"asset": a, "trials": rt.db.query("SELECT trial_id, created_at, horizon, model_family, protocol_id, data_hash, status, metrics, note "
                                                  "FROM lab_trials WHERE asset=? ORDER BY created_at DESC LIMIT 200", (a,)),
                "holdout_access": rt.db.query("SELECT * FROM lab_holdout_access WHERE asset=? ORDER BY at DESC LIMIT 50", (a,))}

    @app.post("/api/v1/lab/zones")
    def lab_zone_add(body: dict = Body(...)):
        a = body.get("asset") or rt.cfg.get().assets.active
        _check_asset(a, "ZONES")
        try:
            return rt.lab.zones.add_manual(a, str(body["tf"]), str(body["kind"]), float(body["top"]), float(body["bottom"]), str(body["origin_time"]))
        except (KeyError, ValueError, TypeError) as exc:                  # 1.46: TypeError (top: null) was a 500
            raise HTTPException(400, f"INVALID_ZONE: {exc}") from exc

    @app.patch("/api/v1/lab/zones/{zone_id}")
    def lab_zone_patch(zone_id: str, body: dict = Body(...)):
        # 1.46: expected_revision null / text and a non-numeric top / bottom were TypeErrors -> 500 (now 400 with the field name)
        rev = body_num(body, "expected_revision", None, int)
        if rev is None:
            raise HTTPException(400, "EXPECTED_REVISION_REQUIRED")
        top, bottom = body_num(body, "top", None, float), body_num(body, "bottom", None, float)
        try:
            return rt.lab.zones.patch(zone_id, rev, top=top, bottom=bottom, state=body.get("state"),
                                      blacklist=body.get("blacklist"), reason=str(body.get("reason") or ""))
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.delete("/api/v1/lab/zones/{zone_id}")
    def lab_zone_delete(zone_id: str, expected_revision: int):
        try:
            return rt.lab.zones.delete(zone_id, expected_revision)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/v1/lab/zones/diagnostics")
    def lab_zone_diag(asset: str | None = None):
        a = asset or rt.cfg.get().assets.active
        return rt.lab.zones.diagnostics(a)

    @app.get("/api/v1/lab/zones")
    def lab_zones(asset: str | None = None):
        a = _asset(asset)
        return {"asset": a, "zones": rt.lab.zones.list_asof(a)[-100:], "events": rt.lab.zones.events[-10:], "snapshot": rt.lab.zones.snapshot_status.get(a)}

    @app.get("/api/v1/lab/repaint")
    def lab_repaint():
        return {"report": rt.lab.repaint.report(),
                "recent": rt.db.query("SELECT asset, module, tf, bar_open, observed_at, change FROM lab_repaint ORDER BY id DESC LIMIT 50")}

    ctx._train_start = _train_start
