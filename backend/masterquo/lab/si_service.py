"""Structure Intelligence runtime (PMW-UPD-07 R01, R04, R13) - extends the EXISTING MTF dashboard snapshot (no second app).

cells(): for every TF of the dashboard (the SAME closed bar set, cutoff = as_of of the parent MTF snapshot): last closed bar, structure
(STRUCTURE_CAUSAL_V2 internal/major trend, last HH/HL/LH/LL, last BOS/STRUCTURE_CHANGE/SWEEP), active chart pattern with the v2
automaton state, SCI2 candle role of the last closed bar, MITP held state vs current votes, nearest zone of the zone store and its
distance, ATR. MTF divergences are listed as explicit facts (never a majority colour); MITP / candles of one evidence group are not
summed as independent votes. Forecast (STRUCTURE_MOVE_M1_V1) only from a manually selected SHADOW artefact; it is archived BEFORE its
outcome is known (UNIQUE context/task/model/as_of/horizon) and matured later from closed M1 bars. Nothing here trains or sends orders.
Jobs (dataset / calibrate / train) run in a background thread with progress / cancel; GET never trains.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import threading
import time
import uuid
from datetime import datetime, timezone

from ..analysis import chart_patterns as CP, mitp, sci2, structure_v2 as S
from ..timeutil import iso, utcnow

TFS = ("H1", "M30", "M15", "M5", "M1")
TF_S = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600}
WINDOW = 300


def _ts(s: str) -> float:
    return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()


class _View:
    """Minimal TFView-compatible view of CLOSED bars for chart_patterns.scan."""

    def __init__(self, tf, bars):
        from ..strategies.base import TFView
        self.v = TFView(tf, [dict(b, closed=True) for b in bars])


class StructureIntelligenceService:
    def __init__(self, cfg, bridge, db, bus, log, lab=None):
        self.cfg, self.bridge, self.db, self.bus, self.log, self.lab = cfg, bridge, db, bus, log, lab
        self.seq = 0
        self.last: dict | None = None
        self.jobs: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._fc = None
        self._fc_key = None
        self.timings: list[float] = []
        self.neutral: dict = {}
        self.neutral_last: dict = {}
        self.quote_engine = None
        self.quote_key = None
        self.quote_last: dict | None = None
        self.quote_status = {"status": "NOT_STARTED"}
        self._qstop = threading.Event()
        self._qthread = None
        from .market_service import MarketSections
        self.market = MarketSections()                          # PMW-UPD-09 R22-R25 sections (incremental, checkpointed)
        self.native_importer = None

    # ------------------------------------------------------------ per-TF cell
    def cell(self, tf: str, bars: list[dict], tick: float, zones: list[dict], instrument: str | None = None) -> dict:
        b = bars[-WINDOW:]
        if len(b) < 30:
            return {"tf": tf, "status": "WARMING_UP", "bars": len(b)}
        try:
            market = self.market.summary(self.market.update(instrument or "XAUUSD", tf, bars, tick))
        except Exception as exc:                                # noqa: BLE001 - one section must not hide the rest
            market = {"status": "ERROR", "error": type(exc).__name__}
        t, o, h, lo, c = [x["open_utc"] for x in b], [x["o"] for x in b], [x["h"] for x in b], [x["l"] for x in b], [x["c"] for x in b]
        st = S.analyse(t, h, lo, c, tick=tick)
        a = S._atr(h, lo, c, len(c) - 1)
        try:
            scan = CP.scan(_View(tf, b).v, tf)
            pats = S.upgrade_patterns(scan, t, o, h, lo, c, a)
        except Exception as exc:                                # noqa: BLE001 - a broken detector must not hide the rest
            pats, scan = [], {"error": type(exc).__name__}
        active = [p for p in pats if p.get("v2_state") in ("FORMING", "CONFIRMED", "RETEST_PENDING")]
        tfz = [z for z in zones if z.get("tf") in (tf, None) and z.get("active", True)] or zones
        rd = sci2.read(t, o, h, lo, c, tf, tick=tick, patterns=pats, structure=st, zones=tfz,
                       available_at=iso(datetime.fromtimestamp(_ts(t[-1]) + TF_S[tf], timezone.utc)))
        mt = mitp.run(h, lo, c, profile="GROUP_BALANCED")
        lay = st["layers"]["internal"]
        sw = lay["swings"]
        last_ev = [e for e in st["events"] if e["layer"] == "internal"][-1:] or [None]
        return {"tf": tf, "status": "OK", "last_closed_open": t[-1], "bars": len(b), "atr14": a,
                "structure": {"trend_internal": lay["trend"], "trend_major": st["layers"]["major"]["trend"],
                              "last_high": next((x for x in reversed(sw) if x["kind"] == "H"), None),
                              "last_low": next((x for x in reversed(sw) if x["kind"] == "L"), None), "last_event": last_ev[0], "profile": S.PROFILE},
                "pattern": ({"pattern_id": active[-1]["pattern_id"], "type": active[-1]["type"], "state": active[-1]["v2_state"],
                             "geometry_quality": active[-1].get("geometry_quality"), "invalidation": active[-1].get("invalidation")} if active else None),
                "patterns_seen": len(pats), "candle_role": {k: rd.get(k) for k in ("reading_id", "role", "role_direction", "reason_codes", "evidence", "invalidation")},
                "mitp": {"status": mt["status"], "held_state": (mt.get("general") or {}).get("held_state"), "current_vote": (mt.get("general") or {}).get("current_vote"),
                         "votes": mt.get("votes"), "note": "utrzymany stan ≠ aktualna jednomyślność"},
                "zone": rd.get("zone"), "market": market}

    def divergences(self, cells: dict) -> list[str]:
        facts = []
        tr = {tf: (c.get("structure") or {}).get("trend_internal") for tf, c in cells.items() if c.get("status") == "OK"}
        ups = [tf for tf, v in tr.items() if v == "UP"]
        dns = [tf for tf, v in tr.items() if v == "DOWN"]
        if ups and dns:
            facts.append(f"konflikt struktury: UP na {', '.join(ups)}; DOWN na {', '.join(dns)}")
        for tf, c in cells.items():
            r = (c.get("candle_role") or {}).get("role")
            if r == "BREAKOUT_FAILURE":
                facts.append(f"{tf}: nieudane wybicie (BREAKOUT_FAILURE)")
            if r == "MID_RANGE":
                facts.append(f"{tf}: środek zakresu – ograniczona wartość kierunkowa")
        return facts

    # ------------------------------------------------------------ snapshot (attached to the MTF parent snapshot)
    def snapshot(self, bars: dict, instrument: str, tick: float, as_of: str | None) -> dict:
        t0 = time.perf_counter()
        zones = []
        try:
            if self.lab is not None:
                zones = self.lab.zones.list_asof(instrument)
        except Exception:                                       # noqa: BLE001
            zones = []
        cells = {}
        for tf in TFS:
            try:
                cells[tf] = self.cell(tf, bars.get(tf) or [], tick, zones, instrument)
            except Exception as exc:                            # noqa: BLE001
                cells[tf] = {"tf": tf, "status": "ERROR", "error": type(exc).__name__}
        fc = self.forecast(bars, instrument, tick, as_of)
        try:
            neu = self.neutralize(instrument, bars.get("M1") or [])
        except Exception as exc:                                # noqa: BLE001
            neu = {"status": "ERROR", "error": type(exc).__name__}
        with self._lock:
            self.seq += 1
            seq = self.seq
        sid = "SIS-" + hashlib.sha256(json.dumps({"i": instrument, "a": as_of, "c": {k: v.get("last_closed_open") for k, v in cells.items()}},
                                                 sort_keys=True).encode()).hexdigest()[:16]
        snap = {"snapshot_id": sid, "seq": seq, "instrument": instrument, "as_of": as_of, "computed_at": iso(utcnow()), "cells": cells,
                "divergences": self.divergences(cells), "forecast": fc, "neutralization": neu,
                "quotes": self.quotes_public(compact=True), "native": self.native_status(instrument, poll=False),
                "profiles": {"structure": S.PROFILE, "mitp": mitp.VERSION, "sci": sci2.VERSION, "regime": "MQ_REGIME_MULTI_V2",
                             "behavior": "MARKET_BEHAVIOR_V1", "smma": "MQ_SMMA_HL3_V2", "zscore": "MQ_ZSCORE_V2"},
                "note": "kontekst analityczny; kierunek nie jest zleceniem"}
        ms = (time.perf_counter() - t0) * 1000
        self.timings = (self.timings + [ms])[-200:]
        snap["build_ms"] = round(ms, 1)
        self.last = snap
        try:
            self.db.execute("INSERT OR IGNORE INTO si_snapshots(snapshot_id, instrument, as_of, seq, created_at, payload) VALUES (?,?,?,?,?,?)",
                            (sid, instrument, as_of or "", seq, snap["computed_at"], json.dumps(snap, default=str)))
        except Exception:                                       # noqa: BLE001
            snap["warning"] = "ARCHIVE_WRITE_FAILED"
        self.bus.publish("structure_intelligence", {k: snap[k] for k in ("snapshot_id", "seq", "instrument", "as_of", "computed_at")})
        return snap

    # ------------------------------------------------------------ PMW-UPD-08 R17 live neutralization (ROC20, persistent state)
    def neutralize(self, instrument: str, m1: list[dict]) -> dict:
        from ..analysis import neutralization as NZ
        key = f"{instrument}|ROC20|DETERMINISTIC"
        nz = self.neutral.get(key)
        if nz is None:
            r = self.db.one("SELECT state FROM neutralizer_state WHERE state_key=?", (key,))
            nz = NZ.RollingNeutralizer.load(json.loads(r["state"]), "ROC20", "DETERMINISTIC", instrument) if r else NZ.RollingNeutralizer("ROC20", "DETERMINISTIC", instrument)
            self.neutral[key] = nz
        b = m1[-400:]
        if len(b) < 60:
            return {"status": "WARMUP", "bars": len(b)}
        h, lo, c = [x["h"] for x in b], [x["l"] for x in b], [x["c"] for x in b]
        raw, fac = NZ.roc20(c), NZ.factors(h, lo, c)
        last = None
        for i, x in enumerate(b):
            t = _ts(x["open_utc"]) + 60
            if nz.last_t is not None and t <= nz.last_t:
                continue
            last = nz.step(t, raw[i], {k: v[i] for k, v in fac.items()}, available_at=iso(datetime.fromtimestamp(t, timezone.utc)))
            if last.get("status") != "DUPLICATE_OR_OLD":
                self.db.execute("INSERT OR IGNORE INTO neutralization_events(event_key, state_key, t, created_at, payload) VALUES (?,?,?,?,?)",
                                (f"{key}|{t}", key, t, iso(utcnow()), json.dumps(last, default=str)))
        if last is not None:
            self.db.execute("INSERT INTO neutralizer_state(state_key, updated_at, seq, state) VALUES (?,?,?,?) ON CONFLICT(state_key) DO UPDATE SET "
                            "updated_at=excluded.updated_at, seq=excluded.seq, state=excluded.state", (key, iso(utcnow()), nz.seq, json.dumps(nz.state())))
            self.neutral_last[instrument] = last
        return self.neutral_last.get(instrument) or {"status": "WARMUP"}

    def neutralization(self, instrument: str, limit: int = 120) -> dict:
        from ..analysis import neutralization as NZ
        key = f"{instrument}|ROC20|DETERMINISTIC"
        rows = [json.loads(r["payload"]) for r in self.db.query("SELECT payload FROM neutralization_events WHERE state_key=? ORDER BY t DESC LIMIT ?",
                                                                (key, limit))][::-1]
        return {"profile": NZ.PROFILE, "legacy_profile": NZ.LEGACY, "signal_id": "ROC20", "factors": NZ.DEFAULT["factors"], "last": self.neutral_last.get(instrument),
                "history": rows, "diagnostics": NZ.diagnostics(rows, NZ.DEFAULT["factors"]),
                "note": "reszta = część nieopisana wybranymi czynnikami liniowymi; nie jest automatycznie alpha"}

    # ------------------------------------------------------------ PMW-UPD-08 R19 live quote kinematics (same bridge, own thread)
    # ------------------------------------------------------------ PMW-UPD-09 R21 native MiniRocket status (read-only SHADOW audit)
    def native_status(self, instrument: str, poll: bool = True) -> dict:
        import os
        from . import minirocket_v2 as MR
        files = os.environ.get("MQ_MT5_FILES_DIR")
        exp = Path(os.environ.get("MQ_MINIROCKET_EXPORT_DIR") or (Path(__file__).resolve().parents[3] / "exports" / "minirocket"))
        man = None
        try:
            man = json.loads((exp / "manifest.json").read_text(encoding="utf-8")) if (exp / "manifest.json").exists() else None
        except (OSError, ValueError):
            man = None
        sym = None
        try:
            sym = self.cfg.get().assets.symbols.get(instrument) if hasattr(self.cfg.get().assets, "symbols") else None
        except Exception:                                       # noqa: BLE001
            sym = None
        if self.native_importer is None or self.native_importer.dir != (Path(files) if files else None):
            self.native_importer = MR.NativeResultImporter(files, (man or {}).get("model_bin_sha256"), sym or "XAUUSD-", "M1")
        res = self.native_importer.poll() if poll else (self.native_importer.last or {"status": "NOT_POLLED"})
        st = MR.native_status(Path(files) / "PMW" / "native_status.json" if files else None)
        return {"export": {"status": "EXPORTED" if man else "NOT_EXPORTED", "model_bin_sha256": (man or {}).get("model_bin_sha256"),
                           "role": (man or {}).get("role"), "layout_F": ((man or {}).get("layout") or {}).get("F")},
                "compile": st, "feed": {k: v for k, v in res.items() if k != "scores"} if isinstance(res, dict) else res,
                "scores": (res or {}).get("scores") if isinstance(res, dict) else None,
                "parity_scope": "sktime 1.2.0 frozen-state fixture (tests/fixtures/minirocket); native NOT_EXECUTED bez terminala",
                "role": "SHADOW_AUDIT – nie nadpisuje głównej prognozy ani Execution Lock"}

    def start(self) -> None:
        if self._qthread is None:
            self._qstop.clear()
            self._qthread = threading.Thread(target=self._quote_loop, name="si-quotes", daemon=True)
            self._qthread.start()

    def stop(self) -> None:
        self._qstop.set()
        if self._qthread is not None:
            self._qthread.join(timeout=3)
            self._qthread = None

    def _quote_loop(self) -> None:
        last_snap = 0.0
        while not self._qstop.wait(0.5):                         # ingestion <= 2 Hz; model snapshot <= 1 Hz
            try:
                self.quote_tick(force_snapshot=time.time() - last_snap >= 1.0)
                if time.time() - last_snap >= 1.0:
                    last_snap = time.time()
            except Exception as exc:                            # noqa: BLE001 - a failing collector never stops the bot
                self.quote_status = {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"[:200]}

    def quote_tick(self, force_snapshot: bool = True) -> dict | None:
        from . import quotes as Q
        b = self.bridge
        if getattr(b, "state", None) != "CONNECTED":
            self.quote_status = {"status": "DISCONNECTED"}
            return None
        sym = self.cfg.get().mt5.symbol
        inst = self.cfg.get().assets.active
        info = getattr(b, "symbol_info", None) or {}
        tick, point = float(info.get("trade_tick_size") or 0), float(info.get("point") or 0)
        key = (inst, sym, getattr(b, "session_epoch", None))
        if self.quote_key != key or self.quote_engine is None:
            self.quote_engine, self.quote_key = Q.QuoteEngine(f"{inst}|{sym}", tick, point), key     # reset on asset / session change
            self._q_since = None
        eng = self.quote_engine
        secs = 600 if eng.last_tick_ms is None else max(5, min(600, int(time.time() - eng.last_tick_ms / 1000.0) + 5))
        r = b.ticks(sym, secs)
        if r.get("status") not in ("ok", "missing_data"):
            self.quote_status = {"status": "MISSING_TICKS", "reason": r.get("reason") or r.get("status")}
            return None
        eng.ingest(r.get("ticks") or [])
        if eng.last_tick_ms is None:
            self.quote_status = {"status": "MISSING_TICKS", "reason": r.get("reason") or "NO_TICKS"}
            return None
        if not force_snapshot:
            return None
        now_ms = int(time.time() * 1000)
        snap = eng.snapshot(now_ms)
        org = eng.origin_ms / 1000.0
        for fc in eng.emit(snap, now_ms):
            self.db.execute("INSERT OR IGNORE INTO quote_forecasts(forecast_id, context, side, scale, issued_at, target_at, payload) VALUES (?,?,?,?,?,?,?)",
                            (fc["forecast_id"], fc["context"], fc["side"], fc["scale"], iso(datetime.fromtimestamp(org + fc["issued_s"], timezone.utc)),
                             iso(datetime.fromtimestamp(org + fc["target_s"], timezone.utc)), json.dumps(fc, default=str)))
        for m in eng.score(now_ms):
            self.db.execute("INSERT OR IGNORE INTO quote_outcomes(forecast_id, status, scored_at, outcome, error, payload) VALUES (?,?,?,?,?,?)",
                            (m["forecast_id"], m["status"], iso(utcnow()), m.get("outcome"), m.get("error"), json.dumps(m, default=str)))
        pub = {k: v for k, v in snap.items() if k != "_fits"}
        pub.update(instrument=inst, symbol=sym, source=r.get("source"), clock_transform=r.get("clock_transform"),
                   last_tick_at=iso(datetime.fromtimestamp(eng.last_tick_ms / 1000.0, timezone.utc)), computed_at=iso(utcnow()))
        self.quote_last = pub
        self.quote_status = {"status": "OK", "seq": snap["seq"]}
        self.bus.publish("structure_quotes", {"seq": snap["seq"], "instrument": inst, "phase": snap["phase"]})
        return pub

    def quotes_public(self, compact: bool = False) -> dict:
        q = self.quote_last
        if not q:
            return dict(self.quote_status)
        if not compact:
            return dict(q, collector=self.quote_status)
        sides = {nm: {str(N): {k: f.get(k) for k in ("status", "velocity_points_s", "acceleration_points_s2", "z_v", "z_a", "n_eff", "span_s", "turning_status")}
                      for N, f in fs.items()} for nm, fs in q["sides"].items()}
        return {"phase": q["phase"], "seq": q["seq"], "computed_at": q["computed_at"], "clock": q["clock"]["mode"], "spread": q["spread"].get("level"), "sides": sides}

    def quote_forecasts(self, limit: int = 100) -> list[dict]:
        rows = self.db.query("SELECT f.forecast_id, f.side, f.scale, f.issued_at, f.target_at, f.payload, o.status, o.outcome, o.error FROM quote_forecasts f "
                             "LEFT JOIN quote_outcomes o ON o.forecast_id=f.forecast_id ORDER BY f.issued_at DESC LIMIT ?", (limit,))
        for r in rows:
            p = json.loads(r.pop("payload"))
            r.update(price=p["price"], se_model=p["se_model"], h_s=p["h_s"], band=p["band"])
        return rows

    def quote_quality(self) -> dict:
        eng = self.quote_engine
        return {"scoreboard": eng.scoreboard() if eng else {}, "clock": eng.clock if eng else None, "flags": sorted(eng.flags) if eng else [],
                "collector": self.quote_status, "note": "estymacja SE ≠ trafność prognozy; R² względem persistence, null przy stałym celu"}

    # ------------------------------------------------------------ forecast (SHADOW artefact only) + archive + maturation
    def forecast(self, bars: dict, instrument: str, tick: float, as_of: str | None) -> dict:
        from . import structure_task as T
        try:
            reg = T._reg(instrument)
        except Exception:                                       # noqa: BLE001
            return {"forecast_status": "ABSTAIN", "reason": "REGISTRY_UNAVAILABLE"}
        key = json.dumps(reg.get("shadow", {}).get(T.TASK_MOVE), sort_keys=True)
        if self._fc is None or self._fc_key != (instrument, key):
            self._fc, self._fc_key = T.Forecaster(instrument), (instrument, key)
        if self._fc.model is None:
            return {"forecast_status": "ABSTAIN", "reason": self._fc.reason}
        m1 = bars.get("M1") or []
        out = self._fc.forecast(m1[-1500:], {tf: bars.get(tf) or [] for tf in ("M5", "M15", "H1")}, tick)
        if out.get("forecast_status") == "OK":
            for hd in out["heads"]:
                try:
                    self.db.execute("INSERT OR IGNORE INTO si_forecasts(instrument, task_id, model_id, as_of, horizon, snapshot_id, emitted_at, payload) "
                                    "VALUES (?,?,?,?,?,?,?,?)", (instrument, T.TASK_MOVE, out["artifact_id"], out["as_of"], hd["h_bars"], None, iso(utcnow()),
                                                                 json.dumps(dict(hd, anchor_close=out["anchor_close"], anchor_atr=out["anchor_atr"]))))
                except Exception:                               # noqa: BLE001
                    pass
            self.mature(instrument, m1)
        return out

    def mature(self, instrument: str, m1: list[dict]) -> int:
        """Outcome of archived forecasts once the end bar is CLOSED (separate table, data revision = bar open+close)."""
        idx = {b["open_utc"]: k for k, b in enumerate(m1)}
        rows = self.db.query("SELECT f.id, f.as_of, f.horizon, f.payload FROM si_forecasts f LEFT JOIN si_outcomes o ON o.forecast_id=f.id "
                             "WHERE f.instrument=? AND o.forecast_id IS NULL ORDER BY f.id DESC LIMIT 500", (instrument,))
        n = 0
        for r in rows:
            p = json.loads(r["payload"])
            start = iso(datetime.fromtimestamp(_ts(r["as_of"]) - 60, timezone.utc))
            k = idx.get(start)
            if k is None or k + r["horizon"] >= len(m1):
                continue
            end = m1[k + r["horizon"]]
            ok = all(_ts(m1[j + 1]["open_utc"]) - _ts(m1[j]["open_utc"]) == 60 for j in range(k, k + r["horizon"]))
            rr = (end["c"] - p["anchor_close"]) / p["anchor_atr"] if ok else None
            b = 0.15 * r["horizon"] ** 0.5
            lab = None if rr is None else "DOWN" if rr < -b else "UP" if rr > b else "FLAT"
            self.db.execute("INSERT OR IGNORE INTO si_outcomes(forecast_id, data_revision, matured_at, r_h, label, status) VALUES (?,?,?,?,?,?)",
                            (r["id"], f"{end['open_utc']}|{end['c']}", iso(utcnow()), rr, lab, "MATURED" if ok else "EXCLUDED_GAP"))
            n += 1
        return n

    def forecasts(self, instrument: str, limit: int = 50) -> list[dict]:
        rows = self.db.query("SELECT f.id, f.task_id, f.model_id, f.as_of, f.horizon, f.emitted_at, f.payload, o.r_h, o.label, o.status AS outcome "
                             "FROM si_forecasts f LEFT JOIN si_outcomes o ON o.forecast_id=f.id WHERE f.instrument=? ORDER BY f.id DESC LIMIT ?", (instrument, limit))
        for r in rows:
            r["payload"] = json.loads(r["payload"])
        return rows

    def quality(self, instrument: str) -> dict:
        rows = self.db.query("SELECT f.horizon, f.payload, o.label, o.r_h FROM si_forecasts f JOIN si_outcomes o ON o.forecast_id=f.id "
                             "WHERE f.instrument=? AND o.status='MATURED'", (instrument,))
        by = {}
        for r in rows:
            p = json.loads(r["payload"])
            d = by.setdefault(r["horizon"], {"n": 0, "ll": 0.0, "cover": 0})
            pk = {"DOWN": p["p_down"], "FLAT": p["p_flat"], "UP": p["p_up"]}[r["label"]]
            import math
            d["n"] += 1
            d["ll"] += -math.log(max(1e-12, pk))
            d["cover"] += int(p["q10"] <= r["r_h"] <= p["q90"])
        t = sorted(self.timings)
        return {"matured": {h: {"n": d["n"], "log_loss": d["ll"] / d["n"], "coverage_10_90": d["cover"] / d["n"]} for h, d in by.items()},
                "latency_ms": {"p50": t[len(t) // 2] if t else None, "p95": t[int(0.95 * (len(t) - 1))] if t else None, "budget_p95": 2000},
                "note": "ocena tylko dojrzałych etykiet; brak dojrzałych = brak oceny"}

    # ------------------------------------------------------------ background jobs (progress / cancel; GET never trains)
    def start_job(self, kind: str, params: dict) -> dict:
        if kind not in ("dataset", "train", "calibrate", "calibrate_market", "tick_export", "tick_replay", "experiment"):
            raise ValueError("JOB_KIND_INVALID")
        jid = "SIJ-" + uuid.uuid4().hex[:10]
        ev = threading.Event()
        job = {"job_id": jid, "kind": kind, "params": params, "status": "RUNNING", "log": [], "started_at": iso(utcnow()), "cancel": ev}
        with self._lock:
            if any(j["status"] == "RUNNING" for j in self.jobs.values()):
                raise ValueError("JOB_ALREADY_RUNNING (jeden trial równolegle)")
            self.jobs[jid] = job
        threading.Thread(target=self._run_job, args=(job,), name=f"si-job-{jid}", daemon=True).start()
        return self.job(jid)

    def _run_job(self, job: dict) -> None:
        from . import structure_task as T
        from ..extind.cli import _latest_real
        p = job["params"]
        inst = p.get("asset") or self.cfg.get().assets.active
        log = lambda *a: job["log"].append(" ".join(str(x) for x in a)[:300])  # noqa: E731
        try:
            if job["kind"] == "dataset":
                ds = _latest_real(inst)
                if ds is None:
                    raise ValueError("BLOCKED_NO_HISTORY: brak eksportu REAL_USER_DATA")
                d = T.build_setup_dataset(inst, ds, log=log) if p.get("task") == T.TASK_SETUP else T.build_move_dataset(inst, ds, log)
                job["result"] = T.save_dataset(inst, d)
            elif job["kind"] == "calibrate":
                job["result"] = T.calibrate_indicators(inst, log=log)
            elif job["kind"] == "calibrate_market":
                from . import market_v2 as MV
                from ..extind.trainer import _bars
                ds = _latest_real(inst)
                if ds is None:
                    raise ValueError("BLOCKED_NO_HISTORY: brak eksportu REAL_USER_DATA")
                meta = json.loads((ds / "source_metadata.json").read_text(encoding="utf-8"))
                rep = MV.calibrate_profiles(_bars(ds, meta.get("file_prefix") or "XAUUSD", "M1"), float(meta["tick_size"]),
                                            [MV.REGIME_PROFILE, MV.SMMA_PROFILE, MV.Z_PROFILE, "STRUCTURE_CAUSAL_V2"])
                (T.root(inst) / "market_profiles.json").write_text(json.dumps(rep, indent=1, default=float), encoding="utf-8")
                job["result"] = {"status": rep["status"], "profiles": list(rep.get("profiles", {}))}
            elif job["kind"] == "tick_export":
                from . import tick_store as TS
                job["result"] = TS.export_via_bridge(self.bridge, self.cfg.get().mt5.symbol, inst, float(p.get("days") or 7),
                                                     progress=lambda f: job.update(progress=round(f, 3)), cancel=job["cancel"].is_set)
            elif job["kind"] == "tick_replay":
                from . import tick_store as TS
                info = getattr(self.bridge, "symbol_info", None) or {}
                job["result"] = {k: v for k, v in TS.replay(inst, float(info.get("trade_tick_size") or 0.01), float(info.get("point") or 0.01)).items()}
            elif job["kind"] == "experiment":
                d = T.latest_dataset(inst, T.TASK_MOVE)
                if d is None:
                    raise ValueError("BLOCKED_NO_DATASET: najpierw dataset")
                r = T.train_experiment(inst, d, p.get("experiment") or "MQ_NEUTRAL_REACTION_V1", p.get("families") or ["LOGREG", "XGB"], p.get("profile") or "quick",
                                       db=self.db, log=log)
                job["result"] = {k: r.get(k) for k in ("run_id", "status", "experiment_id", "rows", "rows_rejected_warmup_or_failure", "reason")}
            else:
                task = p.get("task") or T.TASK_MOVE
                d = T.latest_dataset(inst, task)
                if d is None:
                    raise ValueError("BLOCKED_NO_DATASET: najpierw dataset")
                job["result"] = {k: v for k, v in T.train(inst, d, task, p.get("families") or ["LOGREG"], p.get("profile") or "quick", db=self.db, log=log,
                                                         cancel=job["cancel"].is_set, sew_operators=p.get("sew_operators"),
                                                         spike_cfg={k: p[k] for k in ("encoder", "attention") if p.get(k)},
                                                         transform=p.get("transform")).items()
                                 if k in ("run_id", "status", "evidence", "candidates", "comparison")}
            job["status"] = "CANCELLED" if job["cancel"].is_set() else "COMPLETED"
        except Exception as exc:                                # noqa: BLE001
            job["status"], job["error"] = "FAILED", f"{type(exc).__name__}: {exc}"[:400]
        job["finished_at"] = iso(utcnow())

    def job(self, jid: str) -> dict | None:
        j = self.jobs.get(jid)
        return None if j is None else {k: v for k, v in j.items() if k != "cancel"}

    def cancel(self, jid: str) -> bool:
        j = self.jobs.get(jid)
        if j and j["status"] == "RUNNING":
            j["cancel"].set()
            return True
        return False
