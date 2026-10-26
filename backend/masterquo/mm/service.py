"""Bot-side SHADOW service of the master models (PMW-MM-SERVICE-1).

Recomputes on the bot's CLOSED bars (rt.bridge, forming bar excluded) only when a new M5 bar has closed (or after 60 s): Align Mean on
every loaded TF (one shared configuration = the cross-chart view), read-only account P&L from the same bridge data the statistics page
uses, Kalman state, breakout zones + latest-direction panel, robust volatility, Multi-Indicator decision trace, SMC continuation setups
and a GP forecast (fitted transactionally on the current window; every forecast logged to the SHADOW ledger, matured from later closed
bars). Trained candidates (HDC / event engine / STE) are only listed: they are served only after a VALIDATED_SHADOW artifact exists for
the instrument (REAL data + gates). Nothing here can place, modify or close an order; execution_allowed is always False.
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
        se = SF.run(b5.slice(max(0, len(b5) - 1500), len(b5)), SF.SMCFVGConfig(tick=tick), 300, inst, "M5")
        live = [s for s in se.setups.values() if s["state"] in ("IDM_PENDING", "WAITING_FOR_VALID_RETRACEMENT")]
        out["smc_fvg"] = {"trend": se.smc.trend, "live_setups": [{k: s.get(k) for k in ("setup_id", "direction", "state", "A", "B", "idm")} for s in live[-3:]],
                          "last_events": se.events[-4:], "depth_min": SF.SMCFVGConfig().depth_min}
        out["gpr"] = self._gpr(inst, b5, quality)
        from .contracts import Envelope, ModelOutput
        from .fusion import board
        outs = []
        for src, kind, payload in (("kalman", "INDICATOR_STATE", {"direction": "BULLISH" if "BULLISH" in kc.state else "BEARISH" if "BEARISH" in kc.state else None}),
                                   ("breakout_zones", "INDICATOR_STATE", {"direction": None if be.panel()["direction"] == "NONE" else be.panel()["direction"]}),
                                   ("multi_indicator", "RULE_SIGNAL", {"direction": d.get("decision") if d.get("decision") in ("LONG", "SHORT") else None})):
            outs.append(ModelOutput(Envelope(src, inst, "M5", t_avail - 300, t_avail, quality), kind, payload).to_dict())
        g = out["gpr"]
        if g.get("status") in ("OK", "DEGRADED"):
            outs.append(ModelOutput(Envelope("gpr", inst, "M5", t_avail - 300, t_avail, quality, model_version="PMW-MM-GPR-1"), "GAUSSIAN_PREDICTIVE",
                                    {"mean_logret": g["mean_logret"], "horizon": "3 bars"}).to_dict())
        out["board"] = board(outs, inst, now=t_avail + 1)
        ptr = artifacts.read_pointer(inst)
        out["trained_models"] = {m: ("SHADOW: " + ptr["active"][m]) if m in ptr["active"] else "brak artefaktu VALIDATED_SHADOW (dane rzeczywiste + bramki)"
                                 for m in ("hdc_dir3", "event_engine_dir3", "ste_flownet_ret", "gpr_logret")}
        return out

    def _gpr(self, inst: str, b5: Bars, quality: str) -> dict:
        from . import gpr as G
        cfg = G.GPRConfig()
        c = np.asarray(b5.c, float)
        T = len(c) - 1
        m = G.GPModel(cfg)
        r = m.refit(c, T, True, f"{inst}:M5:{int(b5.t[T])}")
        if not r["ok"]:
            return {"status": r["status"], "reason": r.get("reason")}
        p = m.predict(math.log(c[T] / c[T - 1]), c[T])
        led = self._ledger(inst)
        mid = "gpr_logret:LIVE"
        if p["status"] in ("OK", "DEGRADED"):
            led.log(pred_id=f"{mid}:{inst}:M5:{int(b5.t[T])}:h{cfg.horizon}", model_id=mid, artifact_id=None, feature_schema="GPR_LAG1_LOGRET", symbol=inst,
                    timeframe="M5", source_ts=float(b5.t[T]), available_at=float(b5.t[T]) + 300, matures_at=float(b5.t[T]) + 300 * (cfg.horizon + 1),
                    horizon=f"{cfg.horizon}bars", kind="GAUSSIAN_PREDICTIVE", payload={"pred": p["mean_logret"], "sd": p["sd"], "base": c[T]},
                    quality=quality)
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
        led.mature(float(b5.t[-1]) + 300, resolve, mid)
        sc = [x["outcome"] for x in led.rows(mid, scored_only=True)]
        cal = {"n_scored": len(sc), "coverage_1sd": float(np.mean([s["in_1sd"] for s in sc])) if sc else None,
               "coverage_2sd": float(np.mean([s["in_2sd"] for s in sc])) if sc else None, "inconclusive": len(sc) < 200}
        from . import drift as D                     # AR-08: calibration drift of the live forecast vs the nominal 1-sigma coverage
        enough = len(sc) >= D.DEFAULT_POLICY["min_recent"]
        cal["drift"] = D.evaluate(feature_ref={}, feature_cur={}, ref_abs_err=None, cur_abs_err=None, ref_coverage=0.6827 if enough else None,
                                  cur_coverage=cal["coverage_1sd"] if enough else None, artifact_created_at=None)
        if not enough:
            cal["drift"]["note"] = f"za mało ocenionych prognoz ({len(sc)} < {D.DEFAULT_POLICY['min_recent']}) – dryf nieoceniany"
        return {**{k: p.get(k) for k in ("status", "mean_logret", "latent_var", "observed_var", "sd", "price", "edge_price", "z", "hp", "jitter", "flags")},
                "horizon_bars": cfg.horizon, "live_calibration": cal, "search": m.last_search and {k: m.last_search[k] for k in ("candidates", "failed", "flat_surface")},
                "note": "prognoza log-zwrotu z niepewnością; pasma to założenie gaussowskie do kalibracji, nie gwarancja"}
