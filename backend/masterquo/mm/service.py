"""Bot-side SHADOW service of the master models (PMW-MM-SERVICE-1).

Recomputes on the bot's CLOSED bars (rt.bridge, forming bar excluded) only when a new M5 bar has closed (or after 60 s): Align Mean on
every loaded TF (one shared configuration = the cross-chart view), read-only account P&L from the same bridge data the statistics page
uses, Kalman state, breakout zones + latest-direction panel, robust volatility, Multi-Indicator decision trace, SMC continuation setups
and a GP forecast (fitted transactionally on the current window; every forecast logged to the SHADOW ledger, matured from later closed
bars). 1.46 arch (I0357): next to it the procedure the gpr job validated (walk_forward: grid search every retune_every bars) runs as a
separate SHADOW track with its own ledger id; the Quant-facing forecast keeps its per-bar grid fit (MetaModel inputs unchanged).
Trained artifacts are only LISTED here (_trained_models): the event engine is inferred in SHADOW by Quant (EventGRU) once a
VALIDATED_SHADOW artifact is active; HDC / STE-FlowNet have no live inference even with a validated pointer; the live GP never loads
the gpr_logret artifact (validation reference only). Nothing here can place, modify or close an order; execution_allowed is always False.
"""
from __future__ import annotations

import json
import math
import threading
import time
from datetime import datetime, timezone

import numpy as np

from . import artifacts, inventory
from .data import TF_S, Bars

VERSION = "PMW-MM-SERVICE-1"
RECENT_SCORED = 500                     # 1.46: live calibration / drift window (newest scored forecasts; >= drift min_recent)


def _trained_models(ptr: dict) -> dict:
    """1.46: what each SHADOW pointer really serves ('SHADOW: <aid>' suggested a live forecast from the artifact for all four)."""
    act = ptr.get("active") or {}
    none = "brak artefaktu VALIDATED_SHADOW (dane rzeczywiste + bramki)"
    out = {}
    for m in ("hdc_dir3", "event_engine_dir3", "ste_flownet_ret"):
        aid = act.get(m)
        if not aid:
            out[m] = none
        elif m == "event_engine_dir3":
            out[m] = f"SHADOW: {aid} – inferencja SHADOW w Quant (EventGRU)"
        else:
            out[m] = f"zwalidowany {aid} – brak inferencji na żywo (nic nie liczy predykcji)"
    aid = act.get("gpr_logret")
    out["gpr_logret"] = ("na żywo: dopasowanie GP co świecę M5; " + (f"artefakt {aid} tylko jako referencja walidacji (nie jest wczytywany)" if aid
                                                                    else "brak artefaktu walidacji VALIDATED_SHADOW"))
    return out


def _kalman_direction(state: str | None, accepted: int | None = None) -> str | None:
    """1.46: direction of the last ACCEPTED Kalman crossover (+1 BULLISH / -1 BEARISH / 0 none). `"BULLISH" in state` also matched the
    unconfirmed BULLISH_CANDIDATE / BEARISH_CANDIDATE (a raw change AGAINST the accepted direction). Without `accepted` (results of an
    older run) only the *_CONFIRMED states give a direction."""
    if accepted is not None:
        return "BULLISH" if accepted > 0 else "BEARISH" if accepted < 0 else None
    return {"BULLISH_CONFIRMED": "BULLISH", "BEARISH_CONFIRMED": "BEARISH"}.get(str(state or ""))


def _to_bars(rows: list[dict], tf: str) -> Bars | None:
    rows = [r for r in rows if r.get("closed") and r.get("open_utc")]
    if not rows:
        return None
    t = np.array([datetime.fromisoformat(r["open_utc"].replace("Z", "+00:00")).replace(tzinfo=timezone.utc).timestamp() for r in rows])
    g = lambda k: np.array([float(r.get(k) if r.get(k) is not None else np.nan) for r in rows])  # noqa: E731
    return Bars(tf, t, g("o"), g("h"), g("l"), g("c"), g("tv"), g("spread"))


class MMService:
    def __init__(self, rt):
        self.rt = rt
        self._lock = threading.Lock()
        self._cache: dict = {}
        self._ledgers: dict = {}
        self._gpr_wf: dict = {}                 # 1.46 arch (I0357): per instrument {model, tuned_ts} of the walk-forward SHADOW track
        self._gpr_wf_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.loop = {"runs": 0, "last_bar": None, "last_error": None}
        self.loop_interval_s = 30.0

    # AR-08: inference on every new closed M5 bar, also when the panel is closed (no gaps in the SHADOW ledger). Own thread,
    # read-only; it never touches the order path.
    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="mm-shadow", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.loop_interval_s):
            try:
                rows = self.rt.bridge.bars("M5", include_forming=False)
                t = rows[-1].get("open_utc") if rows else None
                if t and t != self.loop["last_bar"]:
                    self.loop["last_bar"] = t                    # one attempt per bar, also when it fails (no retry storm)
                    self.live(self._active())
                    self.loop.update(runs=self.loop["runs"] + 1, last_error=None)
            except Exception as exc:  # noqa: BLE001 - SHADOW loop never stops the bot
                self.loop["last_error"] = f"{type(exc).__name__}: {exc}"[:200]

    def ledger(self, inst: str):
        """1.46 arch (I0089): the instrument's prediction ledger (public name of _ledger; read by GET /api/v1/mm/ledger)."""
        return self._ledger(inst)

    def _ledger(self, inst: str):
        from .ledger import Ledger
        if inst not in self._ledgers:
            self._ledgers[inst] = Ledger(artifacts.root(inst) / "ledger.sqlite")
        return self._ledgers[inst]

    def _active(self) -> str:
        try:
            return self.rt.cfg.get().assets.active
        except Exception:  # noqa: BLE001
            return "XAUUSD"

    def status(self, inst: str) -> dict:
        rep = inventory.latest_report(inst)
        return {"version": VERSION, "instrument": inst, "inventory": inventory.merge_run(rep), "latest_run": rep and {k: rep.get(k) for k in
                ("run_id", "status", "profile", "started_at", "finished_at", "snapshot", "jobs", "safety")},
                "artifacts": artifacts.list_artifacts(inst), "shadow_pointer": artifacts.read_pointer(inst), "ledger": self._ledger(inst).summary(),
                "spec_bundle": inventory.SPEC_BUNDLE, "execution_allowed": False, "shadow_loop": dict(self.loop)}

    def live(self, inst: str) -> dict:
        if inst != self._active():
            return {"status": "UNAVAILABLE", "reason": f"instrument {inst} nie jest aktywny w bocie ({self._active()})", "execution_allowed": False}
        b5 = _to_bars(self.rt.bridge.bars("M5", include_forming=False), "M5")
        if b5 is None or len(b5) < 200:
            return {"status": "DATA_MISSING", "reason": f"za mało zamkniętych świec M5 ({0 if b5 is None else len(b5)})", "execution_allowed": False}
        key = (inst, float(b5.t[-1]))
        with self._lock:
            c = self._cache.get(inst)
            if c and c["key"] == key and time.time() - c["at"] < 60:
                return c["value"]
        val = self._compute(inst, b5)
        with self._lock:
            self._cache[inst] = {"key": key, "at": time.time(), "value": val}
        return val

    # ----------------------------------------------------------------------------------------------------------------
    def _compute(self, inst: str, b5: Bars) -> dict:
        from . import align_mean as AM
        from . import breakout_zones as BZ
        from . import kalman as K
        from . import multi_indicator as MI
        from . import robust_vol as RV
        from . import smc_fvg as SF
        br = self.rt.bridge
        info = getattr(br, "symbol_info", None) or {}
        point = float(info.get("point") or 0.01)
        tick = float(info.get("trade_tick_size") or point)
        synthetic = bool(getattr(br, "synthetic", False))
        quality = "SYNTHETIC_TEST" if synthetic else "OK"
        t_avail = float(b5.t[-1]) + 300
        out: dict = {"version": VERSION, "instrument": inst, "status": "OK", "last_closed_m5": float(b5.t[-1]), "data_quality": quality,
                     "computed_at": time.time(), "execution_allowed": False}
        cfg = AM.AlignConfig()
        charts = []
        for tf in ("M1", "M5", "M15", "M30", "H1"):
            rows = br.bars(tf, include_forming=False) if tf in getattr(br, "tfs", {}) else []
            b = _to_bars(rows, tf) if rows else None
            if b is None or len(b) < 30:
                charts.append({"symbol": inst, "tf": tf, "status": "NO_DATA"})
                continue
            charts.append(AM.latest(AM.compute(b.t, b.o, b.h, b.l, b.c, TF_S[tf], cfg, point), inst, tf))
        out["align_mean"] = {"config": cfg.__dict__, "config_key": cfg.key(), "charts": charts}
        acc = br.account_status() if hasattr(br, "account_status") else None
        out["pnl"] = {"source": "MT5 account via bridge (read-only)" if acc else None, "status": "OK" if acc else "UNAVAILABLE",
                      "balance": (acc or {}).get("balance"), "equity": (acc or {}).get("equity"), "unrealized": (acc or {}).get("profit"),
                      "currency": (acc or {}).get("currency"), "note": "P&L konta to dane konta - nie wynik odległości od średniej"}
        try:
            from .. import stats
            with br._lock:
                deals = list(br.deals)
            ds = br.server_day_start_utc()
            ds_raw = ds.timestamp() + br.clock.offset if ds and br.clock.offset is not None else None
            out["pnl"]["realized_today"] = stats.account_stats(deals, self.rt.cfg.get().mt5.symbol, ds_raw) if br.account_key else None
        except Exception as exc:  # noqa: BLE001
            out["pnl"]["realized_today"] = {"status": "ERROR", "reason": type(exc).__name__}
        kc, krows = K.run(b5.t, b5.c, K.CrossConfig())
        last = krows[-1]
        out["kalman"] = {"state": kc.state, "fast": last.get("fast"), "slow": last.get("slow"), "K_fast": last.get("K_fast"), "K_slow": last.get("K_slow"),
                         "last_event": kc.events[-1] if kc.events else None, "events_in_window": len(kc.events),
                         "K_steady": {"fast": K.steady_state_gain(1.0, 0.2), "slow": K.steady_state_gain(0.005, 0.2)}}
        be = BZ.run(b5, BZ.BreakoutConfig(), point, 300)
        live_z = [z for z in be.zones if z["state"] in ("QUALIFIED_RESISTANCE", "QUALIFIED_SUPPORT")][-6:]
        out["breakout"] = {"panel": be.panel(), "zones": [{k: z[k] for k in ("zone_id", "kind", "state", "lower", "upper", "touches", "last_touch_ts")} for z in live_z],
                           "last_events": be.events[-3:], "volume_source": "TICK_VOLUME_PROXY (VWAP)"}
        rv = RV.window_stat(b5.c[-48:], RV.RobustVolConfig())
        out["robust_vol"] = rv
        ind = MI.compute(b5.o, b5.h, b5.l, b5.c, MI.MIConfig())
        d = MI.evaluate_bar(ind, len(b5.c) - 1, MI.MIConfig())
        out["multi_indicator"] = {"decision": d.get("decision"), "status": d["status"], "long_reasons": (d.get("sides") or {}).get("LONG", {}).get("reasons"),
                                  "short_reasons": (d.get("sides") or {}).get("SHORT", {}).get("reasons"),
                                  "risk": ((d.get("sides") or {}).get(d.get("decision")) or {}).get("risk") if d.get("decision") in ("LONG", "SHORT") else None}
        se = SF.run(b5.slice(max(0, len(b5) - 1500), len(b5)), SF.SMCFVGConfig(tick=tick, point=point), 300, inst, "M5")   # 1.46: buffer in points
        live = [s for s in se.setups.values() if s["state"] in ("IDM_PENDING", "WAITING_FOR_VALID_RETRACEMENT")]
        out["smc_fvg"] = {"trend": se.smc.trend, "live_setups": [{k: s.get(k) for k in ("setup_id", "direction", "state", "A", "B", "idm")} for s in live[-3:]],
                          "last_events": se.events[-4:], "depth_min": SF.SMCFVGConfig().depth_min}
        out["gpr"] = self._gpr(inst, b5, quality)
        from .contracts import Envelope, ModelOutput
        from .fusion import board
        outs = []
        for src, kind, payload in (("kalman", "INDICATOR_STATE", {"direction": _kalman_direction(kc.state, kc.accepted), "state": kc.state}),
                                   ("breakout_zones", "INDICATOR_STATE", {"direction": None if be.panel()["direction"] == "NONE" else be.panel()["direction"]}),
                                   ("multi_indicator", "RULE_SIGNAL", {"direction": d.get("decision") if d.get("decision") in ("LONG", "SHORT") else None})):
            outs.append(ModelOutput(Envelope(src, inst, "M5", t_avail - 300, t_avail, quality), kind, payload).to_dict())
        g = out["gpr"]
        if g.get("status") in ("OK", "DEGRADED"):
            outs.append(ModelOutput(Envelope("gpr", inst, "M5", t_avail - 300, t_avail, quality, model_version="PMW-MM-GPR-1"), "GAUSSIAN_PREDICTIVE",
                                    {"mean_logret": g["mean_logret"], "horizon": "3 bars"}).to_dict())
        out["board"] = board(outs, inst, now=t_avail + 1)
        out["trained_models"] = _trained_models(artifacts.read_pointer(inst))
        return out

    @staticmethod
    def _resolver(b5: Bars, c: np.ndarray):
        """Outcome of a GP ledger row from the closed bars of the current bridge window (None while bar t+h is not in it)."""
        idx = {float(t): i for i, t in enumerate(b5.t)}

        def resolve(row):
            i = idx.get(float(row["source_ts"]))
            h = int(row["horizon"].replace("bars", ""))
            if i is None or i + h >= len(c):
                return None
            pl = json.loads(row["payload"])
            real = math.log(c[i + h] / c[i])
            z = (real - pl["pred"]) / pl["sd"]
            return {"realized_logret": real, "z": z, "in_1sd": abs(z) <= 1, "in_2sd": abs(z) <= 2}
        return resolve

    def _gpr_walk_forward(self, inst: str, b5: Bars, c: np.ndarray, quality: str) -> dict:
        """1.46 arch (I0357): the procedure the gpr job validated (mm/gpr.walk_forward) as a separate SHADOW track - ONE model per instrument,
        the hyper-parameter grid search only when there is no committed fit or `retune_every` closed M5 bars have passed since the last
        successful search, otherwise a refit on the current window with the last tuned hyper-parameters. Bars are counted in the bridge
        window (a recompute of the same bar never counts; a tuned bar that left the window -> search). Logged under its own ledger id with
        feature_schema GPR_LAG1_LOGRET;retune=N so its live calibration is comparable with the job's. Never fed to Quant: the top-level
        forecast (Quant column fc:mm:gpr_logret) keeps its per-bar grid fit, so trained MetaModels get exactly the inputs they were built on."""
        from . import gpr as G
        cfg = G.GPRConfig()
        T = len(c) - 1
        ts = float(b5.t[T])
        mid = f"gpr_logret:LIVE_RETUNE{cfg.retune_every}"
        fs = f"GPR_LAG1_LOGRET;retune={cfg.retune_every}"
        with self._gpr_wf_lock:
            st = self._gpr_wf.setdefault(inst, {"model": G.GPModel(G.GPRConfig()), "tuned_ts": None})
            m = st["model"]
            since = None
            if st["tuned_ts"] is not None:
                j = int(np.searchsorted(b5.t, st["tuned_ts"]))
                if j < len(b5.t) and float(b5.t[j]) == st["tuned_ts"]:
                    since = T - j
            tune = m.fit is None or since is None or since >= cfg.retune_every
            r = m.refit(c, T, tune, f"{inst}:M5:{int(ts)}")
            if tune and r["ok"]:
                st["tuned_ts"], since = ts, 0
            p = m.predict(math.log(c[T] / c[T - 1]), c[T]) if r["ok"] else None
        out = {"procedure": f"mm/gpr.walk_forward: siatka hiperparametrów co {cfg.retune_every} świec M5, pomiędzy refit na stałych hiperparametrach",
               "retune_every": cfg.retune_every, "retuned": bool(tune and r["ok"]), "bars_since_tune": since, "ledger_model_id": mid,
               "feature_schema": fs, "used_by_quant": False}
        if p is None:
            return {**out, "status": r["status"], "reason": r.get("reason")}
        led = self._ledger(inst)
        if p["status"] in ("OK", "DEGRADED"):
            led.log(pred_id=f"{mid}:{inst}:M5:{int(ts)}:h{cfg.horizon}", model_id=mid, artifact_id=None, feature_schema=fs, symbol=inst,
                    timeframe="M5", source_ts=ts, available_at=ts + 300, matures_at=ts + 300 * (cfg.horizon + 1), horizon=f"{cfg.horizon}bars",
                    kind="GAUSSIAN_PREDICTIVE", payload={"pred": p["mean_logret"], "sd": p["sd"], "base": c[T], "hp": p["hp"], "retuned": out["retuned"]},
                    quality=quality)
        led.mature(ts + 300, self._resolver(b5, c), mid, min_source_ts=float(b5.t[0]))
        tot = led.outcome_means(mid, ("in_1sd", "in_2sd"))
        return {**out, **{k: p.get(k) for k in ("status", "mean_logret", "sd", "hp", "jitter", "flags")},
                "live_calibration": {"n_scored": tot["n"], "coverage_1sd": tot["in_1sd"] if tot["n"] else None,
                                     "coverage_2sd": tot["in_2sd"] if tot["n"] else None, "inconclusive": tot["n"] < 200}}

    def _gpr(self, inst: str, b5: Bars, quality: str) -> dict:
        from . import gpr as G
        cfg = G.GPRConfig()
        c = np.asarray(b5.c, float)
        T = len(c) - 1
        try:
            wf = self._gpr_walk_forward(inst, b5, c, quality)
        except Exception as exc:  # noqa: BLE001 - the SHADOW track never takes the Quant-facing forecast down with it
            wf = {"status": "ERROR", "reason": f"{type(exc).__name__}: {exc}"[:200], "used_by_quant": False}
        m = G.GPModel(cfg)
        r = m.refit(c, T, True, f"{inst}:M5:{int(b5.t[T])}")
        if not r["ok"]:
            return {"status": r["status"], "reason": r.get("reason"), "walk_forward": wf}
        p = m.predict(math.log(c[T] / c[T - 1]), c[T])
        led = self._ledger(inst)
        mid = "gpr_logret:LIVE"
        if p["status"] in ("OK", "DEGRADED"):
            led.log(pred_id=f"{mid}:{inst}:M5:{int(b5.t[T])}:h{cfg.horizon}", model_id=mid, artifact_id=None, feature_schema="GPR_LAG1_LOGRET", symbol=inst,
                    timeframe="M5", source_ts=float(b5.t[T]), available_at=float(b5.t[T]) + 300, matures_at=float(b5.t[T]) + 300 * (cfg.horizon + 1),
                    horizon=f"{cfg.horizon}bars", kind="GAUSSIAN_PREDICTIVE", payload={"pred": p["mean_logret"], "sd": p["sd"], "base": c[T]},
                    quality=quality)
        # 1.46 arch (I0358): rows whose base bar left the bridge window can never be resolved here - not re-scanned (kept, unscored)
        led.mature(float(b5.t[-1]) + 300, self._resolver(b5, c), mid, min_source_ts=float(b5.t[0]))
        from . import drift as D                     # AR-08: calibration drift of the live forecast vs the nominal 1-sigma coverage
        # 1.46: the drift input was the coverage of the WHOLE history (and rows() returned the OLDEST 100k): a fresh mis-calibration was
        # diluted and never alerted, and every M5 bar loaded + decoded the full ledger. Cumulative coverage = SQL aggregate (information);
        # drift = the newest RECENT_SCORED scored forecasts.
        tot = led.outcome_means(mid, ("in_1sd", "in_2sd"))
        rec = [x["outcome"] for x in led.rows(mid, scored_only=True, limit=max(RECENT_SCORED, D.DEFAULT_POLICY["min_recent"]), newest=True)]
        cal = {"n_scored": tot["n"], "coverage_1sd": tot["in_1sd"] if tot["n"] else None, "coverage_2sd": tot["in_2sd"] if tot["n"] else None,
               "inconclusive": tot["n"] < 200,
               "recent": {"n": len(rec), "window": max(RECENT_SCORED, D.DEFAULT_POLICY["min_recent"]),
                          "coverage_1sd": float(np.mean([s["in_1sd"] for s in rec])) if rec else None,
                          "coverage_2sd": float(np.mean([s["in_2sd"] for s in rec])) if rec else None}}
        enough = len(rec) >= D.DEFAULT_POLICY["min_recent"]
        cal["drift"] = D.evaluate(feature_ref={}, feature_cur={}, ref_abs_err=None, cur_abs_err=None, ref_coverage=0.6827 if enough else None,
                                  cur_coverage=cal["recent"]["coverage_1sd"] if enough else None, artifact_created_at=None)
        cal["drift"]["measured_on"] = f"ostatnie {len(rec)} ocenionych prognoz"
        if not enough:
            cal["drift"]["note"] = f"za mało ocenionych prognoz ({len(rec)} < {D.DEFAULT_POLICY['min_recent']}) – dryf nieoceniany"
        return {**{k: p.get(k) for k in ("status", "mean_logret", "latent_var", "observed_var", "sd", "price", "edge_price", "z", "hp", "jitter", "flags")},
                "horizon_bars": cfg.horizon, "live_calibration": cal, "search": m.last_search and {k: m.last_search[k] for k in ("candidates", "failed", "flat_surface")},
                "procedure": "siatka hiperparametrów na każdej świecy M5 (wartości cechy Quant bez zmian); procedura walidowana: walk_forward",
                "walk_forward": wf,
                "note": "prognoza log-zwrotu z niepewnością; pasma to założenie gaussowskie do kalibracji, nie gwarancja"}
