"""LabService (1.14): runs the lab modules for the ACTIVE asset on closed bars, keeps per-asset state (never mixes XAUUSD and
BTC), persists snapshots / zones / forecast archive, runs model inference with telemetry and builds SHADOW scenarios.
Observational only: no reference to the execution gateway or risk engine.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from pathlib import Path

import numpy as np

from .. import paths
from ..analytics.ta import TF_SEC
from . import features as FE
from . import fourier, market, scenarios, sessions, ticks as TK
from .common import closed, iso, ts
from .edge import RepaintInspector
from .protocol import LabTrainer, load_artifact
from .zones import ZoneStore, detect as detect_zones

log = logging.getLogger("masterquo.lab")
VERSION = "MQ-LAB-SVC-1.0.0"
TFS = ("M5", "M15", "H1")
NN_FAMILIES = ("RESNET1D", "SEW_SNN")


class LabService:
    def __init__(self, cfg_store, bridge, db, bus, applog, assets=None):
        self.cfg_store, self.bridge, self.db, self.bus, self.log, self.assets = cfg_store, bridge, db, bus, applog, assets
        self.root = paths.data_dir() / "lab"
        self.trainer = LabTrainer(db, self.root)
        self.zones = ZoneStore(db, self.root / "zones")
        self.repaint = RepaintInspector(db)
        self.state: dict[str, dict] = {}
        self.seq = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_key: dict[str, str] = {}
        self._models: dict[str, tuple] = {}
        self._kin_archive: dict[str, list] = {}
        self._restored: set[str] = set()
        self.errors: list[dict] = []

    # ------------------------------------------------------------------ lifecycle
    def start(self):
        self._thread = threading.Thread(target=self._loop, name="lab", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:  # isolated: a lab failure never stops the main engine
                log.exception("lab tick failed")
                self.errors = (self.errors + [{"at": iso(time.time()), "error": f"{type(exc).__name__}: {exc}"[:300]}])[-20:]
            self._stop.wait(5.0)

    # ------------------------------------------------------------------ one cycle
    def tick(self, force: bool = False) -> dict | None:
        cfg = self.cfg_store.get()
        asset, sym = cfg.assets.active, cfg.mt5.symbol
        if self.bridge.state != "CONNECTED":
            return None
        if self.assets is not None:
            self.assets.check_symbol(sym, "LAB")
        bars = {tf: closed(self.bridge.bars(tf, 600 if tf != "M5" else 1200, include_forming=False)) for tf in (*TFS, "D1")}
        if not bars["M5"]:
            return None
        ml = self.trainer.models(asset)
        key = f"{asset}|{sym}|{bars['M5'][-1]['open_utc']}|{','.join(m['model_id'] for m in ml)}"     # new artefact -> recompute
        if not force and self._last_key.get(asset) == key:
            self._tick_quotes(asset, sym)
            return self.state.get(asset)
        if asset not in self._restored:
            self.zones.restore(asset)
            self._restored.add(asset)
        t0 = time.perf_counter()
        trace = "LTR-" + uuid.uuid4().hex[:16]
        mods: dict[str, dict] = {}
        for tf in TFS:
            b = bars[tf]
            if len(b) < 60:
                mods[tf] = {"status": "warming_up", "bars": len(b)}
                continue
            mods[tf] = {
                "regime": market.regime_map(b, tf), "vol": market.vol_regime(b), "swings": market.swing_structure(b, tf),
                "trendlines": market.trendlines(b, tf), "liquidity": market.liquidity(b, tf, bars["D1"]), "ict": market.ict_sequence(b, tf),
                "smma": market.smma_channel(b), "zscore": market.zscore(b), "psar": market.psar(b, *self._psar_params(asset)),
                "stoch_breakout": market.stoch_daily_breakout(b, tf, bars["D1"], asset), "quiet_drift": market.quiet_drift(b),
                "bars": len(b), "last_bar_open": b[-1]["open_utc"]}
        if len(bars["M5"]) >= 60:
            mods["M5"]["markov"] = market.markov(bars["M5"])
        if len(bars["M15"]) >= 20:
            mods["M15"]["sessions"] = sessions.session_boxes(bars["M15"], "M15", asset)
        # zones (persisted)
        zl = []
        for tf in ("M15", "H1"):
            if len(bars[tf]) >= 60:
                z = detect_zones(bars[tf], tf, asset)
                self.zones.save(asset, z, sym)
                zl += z
        # Fourier with point-in-time archive
        fx = {}
        for tf in ("M15", "H1"):
            c = np.array([x["c"] for x in bars[tf]])
            r = fourier.extrapolate(c, n_past=min(256, max(64, len(c) - 1)))
            if r.get("status") == "ready":
                as_of = iso(ts(bars[tf][-1]["open_utc"]) + TF_SEC[tf])
                rec = fourier.archive_record(asset, tf, as_of, bars[tf][-1]["open_utc"], r)
                self.db.execute("INSERT OR IGNORE INTO lab_forecasts(forecast_id, asset, module, tf, issued_as_of, payload) VALUES (?,?,?,?,?,?)",
                                (rec["forecast_id"], asset, "M29", tf, as_of, json.dumps(rec)))
                arch = [json.loads(x["payload"]) for x in self.db.query(
                    "SELECT payload FROM lab_forecasts WHERE asset=? AND module='M29' AND tf=? ORDER BY issued_as_of DESC LIMIT 200", (asset, tf))]
                ev = fourier.evaluate(arch, {x["open_utc"]: x["c"] for x in bars[tf]}, [x["open_utc"] for x in bars[tf]])
                fx[tf] = {"forecast": r, "forecast_id": rec["forecast_id"], "archive_evaluation": ev}
        # repaint observation of per-bar series (closed bars only)
        obs_at = iso(time.time())
        rp = []
        if mods.get("M5", {}).get("zscore", {}).get("series"):
            ser = mods["M5"]["zscore"]["series"]
            opens = [x["open_utc"] for x in bars["M5"]][-len(ser):]
            rp += self.repaint.observe(asset, "M23_zscore", "M5", dict(zip(opens, ser)), obs_at)
        if mods.get("M15", {}).get("vol", {}).get("series"):
            rp += self.repaint.observe(asset, "M11_vol", "M15", {x["t"]: x["state"] for x in mods["M15"]["vol"]["series"]}, obs_at)
        # context, model, scenarios
        q = self.bridge.quote_status()
        at = mods.get("M5", {}).get("vol", {}).get("atr")
        fresh = bool(q and q.get("age_seconds") is not None and q["age_seconds"] <= cfg.mt5.max_quote_age_seconds)
        as_of = iso(ts(bars["M5"][-1]["open_utc"]) + TF_SEC["M5"])
        ctx = {"asset": asset, "symbol": sym, "trace_id": trace, "as_of": as_of, "last_close": bars["M5"][-1]["c"],
               "last_bar_open": {tf: (bars[tf][-1]["open_utc"] if bars[tf] else None) for tf in TFS},
               "regime": mods.get("M15", {}).get("regime"), "fresh": fresh,
               "fresh_detail": f"wiek notowania {q.get('age_seconds')} s" if q else "brak notowania",
               "cost": {"spread_atr": (q["spread"] / at) if (q and at) else None}}
        model, all_models = self._infer_all(asset, bars["M5"], trace)
        scen = scenarios.build(ctx, mods, model)
        prev = {s["setup_id"]: s for s in (self.state.get(asset) or {}).get("scenarios", [])}
        for s in scen:
            p = prev.get(s["setup_id"])
            s["history"] = (p.get("history", []) if p else []) + ([] if p and p["status"] == s["status"] else [{"at": as_of, "status": s["status"]}])
        with self._lock:
            self.seq += 1
            st = {"asset": asset, "symbol": sym, "instrument": self.assets.instrument(asset) if self.assets else None, "seq": self.seq,
                  "trace_id": trace, "as_of": as_of, "computed_at": iso(time.time()), "version": VERSION,
                  "data_mode": "fixture" if (self.bridge.synthetic or cfg.synthetic_demo) else "live", "modules": mods, "fourier": fx, "zones": zl[-20:],
                  "zone_events": self.zones.events[-5:], "repaint_changes": rp[-10:], "scenarios": scen, "model": model, "models": all_models,
                  "latency_ms": round((time.perf_counter() - t0) * 1000, 1), "quote": q, "fresh": fresh}
            st["ticks"] = (self.state.get(asset) or {}).get("ticks")
            self.state[asset] = st
            self._last_key[asset] = key
        self.db.execute("INSERT OR IGNORE INTO lab_snapshots(created_at, asset, tf, as_of, trace_id, payload) VALUES (?,?,?,?,?,?)",
                        (iso(time.time()), asset, "M5", as_of, trace, json.dumps({k: st[k] for k in ("scenarios", "model", "as_of", "symbol")}, default=str)))
        self.db.execute("DELETE FROM lab_snapshots WHERE id < (SELECT IFNULL(MAX(id),0) - 3000 FROM lab_snapshots)")
        self._tick_quotes(asset, sym, force=True)
        self.bus.publish("lab", self.summary(asset))
        return st

    def _psar_params(self, asset: str) -> tuple[float, float]:
        return (0.02, 0.2) if asset == "XAUUSD" else (0.02, 0.2)      # separate per asset; equal start values, not tuned

    def _tick_quotes(self, asset: str, sym: str, force: bool = False):
        st = self.state.get(asset)
        if st is None:
            return
        last = (st.get("ticks") or {}).get("at_t", 0)
        if not force and time.time() - last < 30:
            return
        try:
            tk = self.bridge.ticks(sym, 3 * 3600)
        except Exception as exc:
            st["ticks"] = {"status": "error", "reason": f"{type(exc).__name__}: {exc}"[:200], "at_t": time.time()}
            return
        res = {"status": tk["status"], "reason": tk.get("reason"), "count": tk.get("count", 0), "source": tk.get("source"), "at_t": time.time(),
               "received_at_utc": tk.get("received_at_utc")}
        if tk["ticks"]:
            res["acd"] = TK.acd_activity(tk["ticks"], time.time())
            kin = TK.kinematics(tk["ticks"])
            res["kinematics"] = kin
            arch = self._kin_archive.setdefault(asset, [])
            if kin.get("status") == "ready":
                arch.append(kin["forecast"])
                del arch[:-500]
            res["kinematics_verification"] = TK.verify_forecasts(arch, tk["ticks"])
        st["ticks"] = res

    # ------------------------------------------------------------------ models + telemetry
    def _active_models(self, asset: str) -> list[tuple]:
        """Latest artefact of EVERY model family of this asset (all of them run; one is shown as primary)."""
        out, seen, errors = [], set(), []
        for m in self.trainer.models(asset):
            if m.get("family") in seen:
                continue
            seen.add(m.get("family"))
            path = str(self.trainer.root / "models" / asset / m["path"])
            cached = self._models.get(path)
            if cached is None:
                try:
                    fitted, man = load_artifact(Path(path), asset=asset, feature_set=FE.FEATURE_SET)
                except Exception as exc:
                    errors.append(f"{m.get('model_id')}: {exc}")
                    continue
                cached = self._models[path] = (path, fitted, man)
            out.append(cached)
        self._artifact_errors = errors
        return out

    @staticmethod
    def _primary(results: list[dict]) -> dict | None:
        """Shown on the dashboard: validated (shadow) first, then a neural network, then the newest."""
        ready = [r for r in results if r.get("status") == "ready"]
        if not ready:
            return results[0] if results else None
        for pred in (lambda r: r.get("role") in ("shadow", "active"), lambda r: r.get("family") == "SEW_SNN",
                     lambda r: r.get("family") == "RESNET1D", lambda r: True):
            hit = [r for r in ready if pred(r)]
            if hit:
                return hit[0]
        return ready[0]

    def _infer_all(self, asset: str, m5: list[dict], trace: str) -> tuple[dict, list[dict]]:
        models = self._active_models(asset)
        if not models:
            reason = f"brak wytrenowanego modelu dla {asset} (Modele i trening → uruchom badanie)"
            if getattr(self, "_artifact_errors", None):
                reason = "ARTEFAKT_ODRZUCONY: " + "; ".join(self._artifact_errors)[:300]
            m = {"status": "no_model", "reason": reason, "nn_status": "INACTIVE", "nn_reason": "sieć nieaktywna – brak artefaktu"}
            return m, []
        results = []
        for got in models:
            try:
                results.append(self._infer(asset, m5, trace, got))
            except Exception as exc:  # one model failing never stops the others
                results.append({"status": "error", "model_id": got[2].get("model_id"), "family": got[1].family, "reason": f"{type(exc).__name__}: {exc}"[:200]})
        prim = self._primary(results)
        nn_any = any(r.get("family") in NN_FAMILIES and r.get("status") == "ready" for r in results)
        if prim is not None and prim.get("family") not in NN_FAMILIES and nn_any:
            prim = {**prim, "nn_reason": "sieć działa jako dodatkowy model – wybierz ją w liście modeli"}
        return prim, results

    def _infer(self, asset: str, m5: list[dict], trace: str, got: tuple) -> dict:
        path, fitted, man = got
        tf, H = man["horizon"].split("x")
        if tf != "M5":
            return {"status": "unsupported", "reason": "model dla innego TF"}
        t0 = time.perf_counter()
        fm = FE.feature_matrix(m5, "M5")
        i = len(m5) - 1
        if fm["warmup"][i] or i < man["seq_len"]:
            return {"status": "warming_up", "model_id": man["model_id"], "nn_status": "WARMING_UP"}
        X = fm["X"][i:i + 1]
        Xs = FE.sequences(fm["X"], np.array([i]), man["seq_len"])
        regime = (X[:, FE.FEATURES.index("vol_pct")] > 0.5).astype(float)
        p = float(fitted.predict(X, Xs, regime)[0])
        lat = (time.perf_counter() - t0) * 1000
        t1 = time.perf_counter()
        arch, layers, spikes = self._architecture(fitted, X, Xs, regime)
        tel_ms = (time.perf_counter() - t1) * 1000
        as_of = iso(ts(m5[-1]["open_utc"]) + TF_SEC["M5"])
        inf_id = "INF-" + uuid.uuid4().hex[:14]
        side = (man.get("label_spec") or {}).get("side", "LONG")
        is_nn = fitted.family in NN_FAMILIES
        fq = {g: ("OK" if not np.isnan(X[0, [FE.FEATURES.index(f) for f in fs]]).any() else "NAN") for g, fs in FE.FEATURE_GROUPS.items()}
        tel = {"trace_id": trace, "inference_id": inf_id, "instrument_id": man.get("instrument_id"), "canonical_asset": asset,
               "as_of_time": as_of, "input_available_at": as_of, "model_id": man["model_id"], "model_version": man.get("model_version"),
               "model_role": man.get("role"), "architecture_id": fitted.family, "state_mode": "STATELESS_WINDOW" if fitted.family != "SEW_SNN" else
               "STATE_RESET_PER_WINDOW", "feature_groups": [{"group": g, "features": fs, "quality": fq[g]} for g, fs in FE.FEATURE_GROUPS.items()],
               "architecture": arch, "layer_summaries": layers, "spike_metrics": spikes,
               "output_schema": {"classes": ["SL_LUB_BRAK_TP", "TP_PRZED_SL"], "event": f"{side}: TP {man['label_spec']['k_tp_atr']}×ATR przed SL {man['label_spec']['k_sl_atr']}×ATR w {H} świecach M5"},
               "raw_output": [round(1 - p, 4), round(p, 4)], "calibrated_output": None,
               "calibration_note": f"brak osobnego kalibratora; ECE z walidacji = {(man.get('metrics') or {}).get('ece_mean')}",
               "latency_ms": round(lat, 2), "telemetry_overhead_ms": round(tel_ms, 2),
               "quality": "OK" if all(v == "OK" for v in fq.values()) else "DEGRADED",
               "warnings": (["MODEL_TECHNICZNY_NA_DANYCH_SYNTETYCZNYCH – nie do decyzji"] if man.get("role") == "fixture_only" else []) +
                           ([] if man.get("verdict") == "HOLDOUT_PASSED" else [f"werdykt badania: {man.get('verdict')}"]),
               "expires_at": iso(ts(as_of) + TF_SEC["M5"])}
        return {"status": "ready", "model_id": man["model_id"], "family": fitted.family, "role": man.get("role"), "horizon": man["horizon"],
                "side": side, "raw_score": round(p, 4), "probability": None, "calibration_ece": (man.get("metrics") or {}).get("ece_mean"),
                "inference_id": inf_id, "event": tel["output_schema"]["event"], "data_source": man.get("data_source"),
                "nn_status": ("ACTIVE_" + str(man.get("role")).upper()) if is_nn else "INACTIVE",
                "nn_reason": None if is_nn else f"championem jest {fitted.family} (nie sieć neuronowa) – pokazano jego rzeczywisty przepływ",
                "telemetry": tel}

    def _architecture(self, f, X, Xs, regime):
        fam = f.family
        if fam in NN_FAMILIES:
            m = f.obj
            xs = (Xs - f.prep["mu"]) / f.prep["sd"]
            if fam == "RESNET1D":
                t = m.telemetry(xs)
            else:
                t = m.telemetry(xs.transpose(0, 2, 1), regime)
            return m.describe(), t["layer_summaries"], t.get("spike_metrics")
        if fam in ("LOGREG", "LOGREG_PCA", "LOGREG_NEUTRALIZED", "LOGREG_GMM_AUG"):
            z = f.prep["sc"].transform(X)
            if "pca" in f.prep:
                z = f.prep["pca"].transform(z)
            if "neut" in f.prep:
                z = z - f.prep["neut_fac"](X) @ f.prep["neut"]
            coef = f.obj.coef_[0]
            contrib = coef * z[0]
            names = FE.FEATURES if len(coef) == len(FE.FEATURES) else [f"PC{i + 1}" for i in range(len(coef))]
            top = sorted(zip(names, contrib), key=lambda x: -abs(x[1]))[:6]
            return ([{"stage": "input", "name": "cechy FS-1.0.0"}, {"stage": "encoder", "name": "StandardScaler (fit w treningu)" + (" + PCA" if "pca" in f.prep else "")},
                     {"stage": "output", "name": "regresja logistyczna (liniowa) → sigmoida"}],
                    [{"layer": "linear", "logit": float(f.obj.decision_function(z)[0]),
                      "contributions_coef_x_value": [{"feature": n, "value": round(float(v), 4)} for n, v in top],
                      "method": "współczynnik × wartość standaryzowana (model liniowy) – nie jest to waga ważności ogólnej"}], None)
        if fam == "TREE":
            path = f.obj.decision_path(X).indices.tolist()
            return ([{"stage": "input", "name": "cechy FS-1.0.0"}, {"stage": "output", "name": f"drzewo decyzyjne (głębokość {f.obj.get_depth()})"}],
                    [{"layer": "tree", "decision_path_nodes": path, "leaf": int(f.obj.apply(X)[0])}], None)
        if fam == "MINIROCKET":
            Z = f.prep["mr"].transform(Xs)
            return ([{"stage": "input", "name": "okna sekwencji"}, {"stage": "encoder", "name": f"MiniRocket ({Z.shape[1]} cech PPV, biasy z treningu)"},
                     {"stage": "output", "name": "regresja logistyczna"}],
                    [{"layer": "minirocket", "ppv_mean": float(Z.mean()), "ppv_std": float(Z.std())}], None)
        if fam == "XGB":
            return ([{"stage": "input", "name": "cechy FS-1.0.0"}, {"stage": "output", "name": f"XGBoost ({f.cfg.get('trees')} drzew, głęb. {f.cfg.get('max_depth')})"}],
                    [{"layer": "xgb", "margin": float(f.obj.predict(X, output_margin=True)[0])}], None)
        return ([{"stage": "output", "name": fam}], [], None)

    # ------------------------------------------------------------------ public
    def summary(self, asset: str) -> dict:
        st = self.state.get(asset) or {}
        return {"asset": asset, "seq": st.get("seq"), "trace_id": st.get("trace_id"), "as_of": st.get("as_of"),
                "scenarios": len(st.get("scenarios") or []), "model_status": (st.get("model") or {}).get("status")}

    def public(self, asset: str) -> dict:
        active = self.cfg_store.get().assets.active
        st = self.state.get(asset)
        if st is None:
            return {"asset": asset, "active": active, "status": "warming_up" if asset == active else "not_active",
                    "reason": "pierwsze obliczenie po połączeniu" if asset == active else f"aktywne jest {active}; dane {asset} nie są liczone w tle"}
        out = dict(st)
        out["active"] = active
        out["is_active_asset"] = asset == active
        age = time.time() - ts(st["computed_at"])
        out["stale"] = (asset != active) or age > 180
        if out["stale"]:
            out["stale_reason"] = "inne aktywo niż aktywne" if asset != active else f"brak przeliczenia od {age:.0f} s"
            if out.get("model") and out["model"].get("telemetry"):
                out["model"] = {**out["model"], "telemetry": {**out["model"]["telemetry"], "warnings": out["model"]["telemetry"]["warnings"] + ["DANE_NIEAKTUALNE"]}}
        return out
